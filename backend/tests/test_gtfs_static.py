"""Test del parsing GTFS statico e della mappa linea → route_id."""

from __future__ import annotations

from app.gtfs_static import GtfsStatic, _mode_for_route_type


def test_route_short_name_maps_to_multiple_route_ids(gtfs: GtfsStatic):
    # La linea 10 ha due varianti di percorso (R10A, R10B).
    assert sorted(gtfs.route_ids_for_line("10")) == ["R10A", "R10B"]
    assert gtfs.route_ids_for_line("55") == ["R55"]
    assert gtfs.route_ids_for_line("999") == []


def test_short_name_lookups(gtfs: GtfsStatic):
    assert gtfs.short_name_for_route_id("R10A") == "10"
    assert gtfs.short_name_for_trip("T3") == "55"
    assert gtfs.short_name_for_route_id(None) is None


def test_headsign_for_trip(gtfs: GtfsStatic):
    assert gtfs.headsign_for_trip("T1") == "Corso Settembrini"
    assert gtfs.headsign_for_trip("ignoto") is None


def test_lines_listing_sorted_numerically(gtfs: GtfsStatic):
    lines = gtfs.lines()
    names = [line.line for line in lines]
    assert names == ["10", "55"]
    ten = next(line for line in lines if line.line == "10")
    assert ten.description  # long_name presente
    assert sorted(ten.route_ids) == ["R10A", "R10B"]


def test_search_stops_by_name_and_code(gtfs: GtfsStatic):
    by_name = gtfs.search_stops("massari")
    assert len(by_name) == 1 and by_name[0].stop_id == "350"
    assert by_name[0].lat == 45.07

    by_code = gtfs.search_stops("0351")
    assert by_code[0].stop_id == "351"

    assert gtfs.search_stops("") == []
    assert gtfs.search_stops("zzz") == []


def test_search_stops_limit(gtfs: GtfsStatic):
    # Tutte e tre le fermate contengono lettere comuni? usiamo limit.
    res = gtfs.search_stops("a", limit=1)
    assert len(res) == 1


def test_mode_for_route_type_basic_and_extended():
    assert _mode_for_route_type("0") == "tram"
    assert _mode_for_route_type("1") == "metro"
    assert _mode_for_route_type("3") == "bus"
    assert _mode_for_route_type("7") == "funicular"
    # Extended (HVT): classificato per centinaia.
    assert _mode_for_route_type("900") == "tram"
    assert _mode_for_route_type("401") == "metro"
    # Sconosciuto / vuoto → bus difensivo.
    assert _mode_for_route_type("") == "bus"
    assert _mode_for_route_type(None) == "bus"
    assert _mode_for_route_type("xyz") == "bus"


def test_mode_lookups_and_lines_expose_mode():
    gtfs = GtfsStatic(
        routes={
            "R3": {"route_id": "R3", "route_short_name": "3", "route_type": "0"},
            "R55": {"route_id": "R55", "route_short_name": "55", "route_type": "3"},
        },
        short_name_to_route_ids={"3": ["R3"], "55": ["R55"]},
    )
    assert gtfs.mode_for_route_id("R3") == "tram"
    assert gtfs.mode_for_line("3") == "tram"
    assert gtfs.mode_for_line("55") == "bus"
    assert gtfs.mode_for_line("999") == "bus"  # linea ignota
    modes = {line.line: line.mode for line in gtfs.lines()}
    assert modes == {"3": "tram", "55": "bus"}


def test_stop_name_cleaned_desc_and_lines():
    gtfs = GtfsStatic(
        routes={"R10": {"route_id": "R10", "route_short_name": "10"}},
        short_name_to_route_ids={"10": ["R10"]},
        trips={"T1": {"trip_id": "T1", "route_id": "R10"}},
        stops={
            "350": {
                "stop_code": "350",
                "stop_name": "Fermata 350 - MASSARI",
                "stop_desc": "V. GIUSTI N.6 NICHELINO",
                "stop_lat": "45.0",
                "stop_lon": "7.0",
            }
        },
        schedule={"T1": {1: ("350", 100)}},
    )
    gtfs._build_stop_lines()
    s = gtfs.stop("350")
    assert s.name == "MASSARI"  # prefisso "Fermata 350 -" rimosso
    assert s.desc == "Via Giusti N.6 Nichelino"  # abbreviazioni espanse, Title Case
    assert s.lines == ["10"]  # linea servita dalla palina
    # La ricerca trova ancora per numero/nome originale.
    assert gtfs.search_stops("massari")[0].stop_id == "350"
    assert gtfs.search_stops("350")[0].stop_id == "350"


def test_shape_and_stops_for_line():
    gtfs = GtfsStatic(
        short_name_to_route_ids={"10": ["R10"]},
        trips={
            "T1": {"trip_id": "T1", "route_id": "R10", "shape_id": "S1", "direction_id": "0"},
            "T2": {"trip_id": "T2", "route_id": "R10", "shape_id": "S1"},  # stesso shape
            "T3": {"trip_id": "T3", "route_id": "R10", "shape_id": "S2", "direction_id": "1"},
            "TX": {"trip_id": "TX", "route_id": "R99", "shape_id": "S9"},  # altra linea
        },
        shapes={
            "S1": [(45.0, 7.0), (45.1, 7.1), (45.2, 7.2)],  # più lungo
            "S2": [(45.0, 7.0), (45.05, 7.05)],
            "S9": [(40.0, 8.0)],
        },
        stops={
            "350": {"stop_name": "A", "stop_lat": "45.0", "stop_lon": "7.0"},
            "351": {"stop_name": "B", "stop_lat": "45.1", "stop_lon": "7.1"},
        },
        schedule={"T1": {1: ("350", 100), 2: ("351", 200)}},
    )
    shapes = gtfs.shape_for_line("10")
    assert len(shapes) == 2  # S1 e S2 (non S9 di un'altra linea)
    assert shapes[0] == (0, [(45.0, 7.0), (45.1, 7.1), (45.2, 7.2)])  # più lungo, direzione 0
    assert shapes[1][0] == 1  # S2 è direzione 1
    stops = gtfs.stops_for_line("10")
    assert [s.stop_id for s in stops] == ["350", "351"]  # in ordine di sequenza
    assert gtfs.shape_for_line("999") == [] and gtfs.stops_for_line("999") == []


def test_empty_gtfs_is_safe():
    empty = GtfsStatic()
    assert empty.lines() == []
    assert empty.search_stops("x") == []
    assert empty.stop("350") is None


def test_schedule_indexes_yesterday_and_today():
    """L'indice orari include le corse di ieri (notturne oltre mezzanotte) e di oggi."""
    import datetime as dt
    import io
    import zipfile

    files = {
        "routes.txt": "route_id,route_short_name\nR1,1\n",
        "stops.txt": "stop_id,stop_name\nS,Stop\n",
        "trips.txt": "route_id,service_id,trip_id\nR1,MON,TMON\nR1,TUE,TTUE\nR1,WED,TWED\n",
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
            "start_date,end_date\n"
            "MON,1,0,0,0,0,0,0,20300101,20301231\n"
            "TUE,0,1,0,0,0,0,0,20300101,20301231\n"
            "WED,0,0,1,0,0,0,0,20300101,20301231\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "TMON,24:30:00,24:30:00,S,1\nTTUE,08:00:00,08:00:00,S,1\nTWED,08:00:00,08:00:00,S,1\n"
        ),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    tuesday = dt.date(2030, 1, 8)
    gtfs = GtfsStatic.from_zip_bytes(buf.getvalue(), schedule_for_date=tuesday)
    assert set(gtfs.schedule) == {"TMON", "TTUE"}
    assert gtfs.trip_dates == {"TMON": (dt.date(2030, 1, 7),), "TTUE": (tuesday,)}
