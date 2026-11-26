"""FastAPI app read-only (Milestone 0): linee, fermate, arrivi, mezzi, avvisi.

Il polling dei feed lo fa SOLO il backend (cache condivisa nel provider): il
client parla esclusivamente con questa API.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager, suppress

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from . import realtime, scioperi
from .cache import RedisCache
from .config import get_settings
from .db import db_healthcheck
from .me import router as me_router
from .models import (
    AlertsResponse,
    ArrivalsResponse,
    Health,
    Line,
    LineShape,
    ShapePath,
    Stop,
    VehiclesResponse,
)
from .provider import DataProvider, LiveProvider
from .worker import configure_logging, create_scheduler
from .ws import ConnectionManager

ATTRIBUTION = "Dati: Città di Torino / GTT (CC BY 4.0); scioperi MIT; mappa © OpenStreetMap"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    provider = LiveProvider()
    app.state.provider = provider
    app.state.scheduler = None
    app.state.ws_manager = ConnectionManager(settings.ws_max_connections)
    app.state.ws_interval_s = settings.ws_interval_s
    # Pre-carica il GTFS statico (tollerante a rete assente).
    with suppress(Exception):
        await run_in_threadpool(provider.gtfs)
    # Scheduler nel processo API: solo per sviluppo (in produzione: app.worker).
    if settings.scheduler_enabled:
        scheduler = create_scheduler(provider, settings)
        scheduler.start()
        app.state.scheduler = scheduler
    try:
        yield
    finally:
        if app.state.scheduler is not None:
            with suppress(Exception):
                app.state.scheduler.shutdown(wait=False)
        with suppress(Exception):
            provider.close()


app = FastAPI(
    title="Transito Torino — backend",
    version="0.0.1",
    summary="Arrivi, mezzi live e avvisi del trasporto pubblico GTT di Torino.",
    description=ATTRIBUTION,
    lifespan=lifespan,
)

# CORS solo per le origini configurate (es. la web app su GitHub Pages).
if get_settings().cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# API versionata (SPEC §4); /health resta fuori per il monitoraggio.
api = APIRouter(prefix="/v1")


def get_provider() -> DataProvider:
    """Dependency: provider dati. Sovrascritta nei test con un fake da fixture."""
    return app.state.provider


@app.get("/health", response_model=Health)
def health(provider: DataProvider = Depends(get_provider)) -> Health:
    gtfs = provider.gtfs()
    cache_backend = "memory"
    cache = getattr(provider, "cache", None)
    if isinstance(cache, RedisCache):
        cache_backend = "redis" if cache.ping() else "redis-down"
    loaded_at = getattr(provider, "gtfs_loaded_at", None)
    db_ok = db_healthcheck()
    gtfs_ok = bool(gtfs.routes)
    return Health(
        status="ok" if db_ok and gtfs_ok else "degraded",
        gtfs_loaded=gtfs_ok,
        gtfs_age_s=int(time.time() - loaded_at) if loaded_at is not None else None,
        routes=len(gtfs.routes),
        stops=len(gtfs.stops),
        db=db_ok,
        cache=cache_backend,
    )


@api.get("/lines", response_model=list[Line])
def lines(provider: DataProvider = Depends(get_provider)) -> list[Line]:
    return provider.gtfs().lines()


@api.get("/stops/search", response_model=list[Stop])
def stops_search(
    q: str = Query(..., min_length=1, description="Nome fermata o codice palina"),
    limit: int = Query(20, ge=1, le=100),
    provider: DataProvider = Depends(get_provider),
) -> list[Stop]:
    return provider.gtfs().search_stops(q, limit=limit)


@api.get("/stops/{stop_id}/arrivals", response_model=ArrivalsResponse)
def stop_arrivals(
    stop_id: str,
    line: str | None = Query(None, description="Filtra per linea, es. '10'"),
    provider: DataProvider = Depends(get_provider),
) -> ArrivalsResponse:
    gtfs = provider.gtfs()
    stop = gtfs.stop(stop_id)
    if stop is None and gtfs.stops:
        raise HTTPException(status_code=404, detail="Fermata non trovata")
    feed = realtime.parse_feed(provider.trip_updates_bytes())
    arrivals = realtime.arrivals_for_stop(feed, gtfs, stop_id, line=line)
    return ArrivalsResponse(
        stop_id=stop_id,
        name=stop.name if stop else None,
        arrivals=arrivals,
    )


def _vehicles_response(provider: DataProvider, line: str) -> VehiclesResponse:
    """Posizioni dei mezzi di una linea dalla cache RT condivisa (REST e WS)."""
    gtfs = provider.gtfs()
    feed = realtime.parse_feed(provider.vehicle_positions_bytes())
    vehicles = realtime.vehicles_for_line(feed, gtfs, line)
    return VehiclesResponse(line=line, count=len(vehicles), vehicles=vehicles)


@api.get("/lines/{line}/shape", response_model=LineShape)
def line_shape(
    line: str,
    provider: DataProvider = Depends(get_provider),
) -> LineShape:
    """Tracciato (percorso) e fermate di una linea, per la mappa."""
    gtfs = provider.gtfs()
    return LineShape(
        line=line,
        polylines=[ShapePath(direction=d, points=pts) for d, pts in gtfs.shape_for_line(line)],
        stops=gtfs.stops_for_line(line),
    )


@api.get("/lines/{line}/vehicles", response_model=VehiclesResponse)
def line_vehicles(
    line: str,
    provider: DataProvider = Depends(get_provider),
) -> VehiclesResponse:
    return _vehicles_response(provider, line)


@api.websocket("/ws/lines/{line}")
async def ws_line_vehicles(
    websocket: WebSocket,
    line: str,
    provider: DataProvider = Depends(get_provider),
) -> None:
    """Spinge le posizioni della linea ogni ~3–5 s dalla cache RT condivisa.

    Fallback se il WS non è disponibile: polling REST di
    ``GET /v1/lines/{line}/vehicles`` (stesso schema del messaggio).
    """
    await websocket.accept()
    manager: ConnectionManager = websocket.app.state.ws_manager
    if not manager.register(websocket):
        # Tetto connessioni raggiunto: chiudi invitando a riprovare.
        await websocket.close(code=1013)  # Try Again Later
        return
    interval = getattr(websocket.app.state, "ws_interval_s", 4.0)
    try:
        while True:
            # Letture potenzialmente bloccanti (cache/parse) fuori dall'event loop.
            try:
                resp = await run_in_threadpool(_vehicles_response, provider, line)
            except HTTPException:
                pass  # feed momentaneamente giù: salta il giro, la connessione resta
            else:
                await websocket.send_json(resp.model_dump())
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass
    finally:
        manager.unregister(websocket)


@api.get("/alerts", response_model=AlertsResponse)
def alerts(
    line: str | None = Query(None, description="Filtra avvisi per linea"),
    provider: DataProvider = Depends(get_provider),
) -> AlertsResponse:
    gtfs = provider.gtfs()
    strikes = scioperi.filter_upcoming(
        scioperi.filter_for_torino(scioperi.parse_strikes_rss(provider.strikes_feed()))
    )
    try:
        feed = realtime.parse_feed(provider.alerts_bytes())
    except HTTPException:
        return AlertsResponse(service_alerts_available=False, strikes=strikes)
    service = realtime.service_alerts(feed, gtfs, line=line)
    return AlertsResponse(service_alerts=service, strikes=strikes)


api.include_router(me_router)
app.include_router(api)
