"""
Tests du moteur MAX Jeune (max_jeune_engine) sur un petit CSV synthétique.
Lancer depuis le dossier du projet :   python -m pytest tests
"""
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import max_jeune_engine as E  # noqa: E402

D = "2026-10-01"
D2 = "2026-10-02"
HEADER = ("DATE;TRAIN_NO;ENTITY;Axe;Origine IATA;Destination IATA;Origine;Destination;"
          "Heure_depart;Heure_arrivee;Disponibilité de places MAX JEUNE et MAX SENIOR")

# (iata, libellé CSV) des gares utilisées
PGL = ("FRPLY", "PARIS (intramuros)")
PMO = ("FRPMO", "PARIS (intramuros)")
PNO = ("FRPNO", "PARIS (intramuros)")
LPD = ("FRLPD", "LYON (intramuros)")
LILLE_EUR = ("FRLLE", "LILLE (intramuros)")
MRS = ("FRMSC", "MARSEILLE ST CHARLES")
AIX = ("FRAIE", "AIX EN PROVENCE TGV")
TLN = ("FRTLN", "TOULON")
GRE = ("FRGNB", "GRENOBLE")
CHY = ("FRCMF", "CHAMBERY CHALLES LES EAUX")
BDX = ("FRBOJ", "BORDEAUX ST JEAN")
TLS = ("FRTLS", "TOULOUSE MATABIAU")
CAU = ("FRFTA", "CAUSSADE(TARN ET GARONNE)")


def row(day, train, o, d, hd, ha, oui):
    return ";".join([day, train, "X", "AXE", o[0], d[0], o[1], d[1], hd, ha,
                     "OUI" if oui else "NON"])


ROWS = [
    # Train 100 Paris -> Lyon -> Marseille -> Toulon : seul Paris->Toulon est OUI
    row(D, "100", PGL, TLN, "07:00", "11:40", True),
    row(D, "100", PGL, LPD, "07:00", "09:00", False),
    row(D, "100", LPD, MRS, "09:05", "10:40", False),
    row(D, "100", MRS, TLN, "10:45", "11:40", False),
    row(D, "100", PGL, MRS, "07:00", "10:40", False),
    # Train 101 sens retour Toulon -> Marseille -> Lyon -> Paris : Toulon->Paris OUI
    row(D, "101", TLN, PGL, "15:00", "19:40", True),
    row(D, "101", TLN, MRS, "15:00", "15:55", False),
    row(D, "101", MRS, LPD, "16:00", "17:35", False),
    row(D, "101", LPD, PGL, "17:40", "19:40", False),
    # Train 200 qui se sépare à Lyon : branche Grenoble (OUI) / branche Chambéry
    row(D, "200", PGL, GRE, "08:00", "11:00", True),
    row(D, "200", PGL, CHY, "08:00", "10:50", False),
    row(D, "200", LPD, GRE, "10:00", "11:00", False),
    row(D, "200", LPD, CHY, "10:05", "10:50", False),
    # Train 300 Paris -> Marseille direct OUI
    row(D, "300", PGL, MRS, "08:00", "11:20", True),
    # Train 350 : direct OUI Lyon->Marseille ET billet plus long sur le même train
    row(D, "350", PGL, MRS, "12:00", "15:20", True),
    row(D, "350", LPD, MRS, "14:00", "15:20", True),
    row(D, "350", PGL, LPD, "12:00", "13:55", False),
    # Partie C, même gare : Paris Montparnasse -> Bordeaux, puis Bordeaux -> Toulouse
    row(D, "400", PMO, BDX, "07:00", "09:10", True),
    row(D, "500", BDX, TLS, "09:30", "11:30", True),   # marge 20 min : OK
    row(D, "501", BDX, TLS, "09:15", "11:05", True),   # marge 5 min : refusé
    # Partie C, hub : Lille -> Paris Nord, puis Paris GdL -> Marseille
    row(D, "600", LILLE_EUR, PNO, "07:00", "08:00", True),
    row(D, "602", PGL, MRS, "09:10", "12:30", True),   # marge 70 min : OK
    row(D, "603", PGL, MRS, "09:20", "13:10", True),   # dominé par 602
    # Passage de minuit
    row(D, "700", AIX, MRS, "23:50", "00:20", True),
    # Libellé avec parenthèses
    row(D, "800", CAU, TLS, "10:00", "10:50", True),
    # Pour la Partie D
    row(D, "900", MRS, PGL, "07:40", "11:00", True),
    row(D, "950", PGL, LPD, "06:00", "08:00", True),
    # Jour suivant pour le balayage
    row(D2, "300", PGL, MRS, "08:00", "11:20", True),
    row(D2, "301", PGL, MRS, "18:00", "21:20", True),
]


@pytest.fixture(scope="module")
def ds(tmp_path_factory):
    p = tmp_path_factory.mktemp("data") / "tgvmax.csv"
    p.write_text("﻿" + HEADER + "\n" + "\n".join(ROWS) + "\n", encoding="utf-8")
    return E.load_dataset(p)


# --- GTFS synthétique (Partie D) ---------------------------------------------
GTFS_STOPS = {  # UIC -> nom GTFS
    "87751008": "Marseille Saint-Charles", "87751750": "Cassis", "87755009": "Toulon",
    "87723197": "Lyon Part Dieu", "87722025": "Lyon Perrache",
}
# (trip, mode, n° train, [(uic, heure)])
GTFS_TRIPS = [
    ("t1", "Train TER", "881001", [("87751008", "11:25:00"), ("87751750", "11:48:00")]),  # marge 5 min : trop court
    ("t2", "Train TER", "881003", [("87751008", "11:40:00"), ("87751750", "12:03:00")]),
    ("t3", "Train TER", "881005", [("87751008", "12:50:00"), ("87751750", "13:13:00")]),
    ("t4", "TGV INOUI", "6199", [("87751008", "11:30:00"), ("87751750", "11:45:00")]),  # mode exclu
    ("t5", "Train TER", "881100", [("87751750", "07:00:00"), ("87751008", "07:25:00")]),
    ("t6", "Train TER", "881200", [("87755009", "12:00:00"), ("87751008", "12:50:00")]),
    ("t7", "Train TER", "17000", [("87723197", "08:20:00"), ("87722025", "08:30:00")]),
]


def write_gtfs(path):
    stops = ["stop_id,stop_name,stop_desc,stop_lat,stop_lon,zone_id,stop_url,location_type,parent_station"]
    modes = {m for _, m, _, _ in GTFS_TRIPS}
    for uic, name in GTFS_STOPS.items():
        stops.append(f"StopArea:OCE{uic},{name},,0,0,,,1,")
        for m in modes:
            stops.append(f"StopPoint:OCE{m}-{uic},{name},,0,0,,,0,StopArea:OCE{uic}")
    trips = ["route_id,service_id,trip_id,trip_headsign,direction_id,block_id,shape_id"]
    st = ["trip_id,arrival_time,departure_time,stop_id,stop_sequence,stop_headsign,pickup_type,"
          "drop_off_type,shape_dist_traveled"]
    for tid, mode, num, seq in GTFS_TRIPS:
        trips.append(f"R1,S1,{tid},{num},0,,")
        for i, (uic, h) in enumerate(seq):
            st.append(f"{tid},{h},{h},StopPoint:OCE{mode}-{uic},{i},,0,0,")
    files = {
        "feed_info.txt": "feed_id,feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,"
                         "feed_end_date,feed_version\n0,SNCF,x,fr,20261001,20261031,test",
        "stops.txt": "\n".join(stops), "trips.txt": "\n".join(trips),
        "stop_times.txt": "\n".join(st),
        "calendar_dates.txt": "service_id,date,exception_type\nS1,20261001,1",
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content + "\n")


@pytest.fixture(scope="module")
def net(ds, tmp_path_factory):
    p = tmp_path_factory.mktemp("gtfs") / "gtfs.zip"
    write_gtfs(p)
    return E.load_ter_network(p, max_stations=ds.stations)


def search(ds, dep, arr, date=D, net=None, **kw):
    ext = kw.pop("extended", False)
    known = ds.stations | (net.stations if net else set())
    dl = E.resolve_location(dep, known, ext)
    al = E.resolve_location(arr, known, ext)
    return E.run_search(ds, E.Query(date, dl.candidates, al.candidates, **kw), net)


# --- Chargement / normalisation ----------------------------------------------

def test_load_counts(ds):
    assert ds.n_rows == len(ROWS)
    assert len(ds.tickets) == sum(r.endswith("OUI") for r in ROWS)


def test_iata_disambiguation(ds):
    assert {"PARIS GARE DE LYON", "PARIS MONTPARNASSE", "PARIS NORD",
            "LYON PART DIEU", "LILLE EUROPE"} <= ds.stations
    assert not any("INTRAMUROS" in s for s in ds.stations)


def test_parentheses_removed(ds):
    assert "CAUSSADE" in ds.stations


def test_marseille_hub():
    assert E.resolve_location("MARSEILLE", set()).candidates == {"MARSEILLE ST CHARLES"}
    ext = E.resolve_location("MARSEILLE", set(), include_extended=True)
    assert ext.candidates == {"MARSEILLE ST CHARLES", "AIX EN PROVENCE TGV"}


def test_hubs_work_in_both_directions(ds):
    # Hub étendu Marseille (inclut Aix TGV) utilisable au départ comme à l'arrivée
    aller = search(ds, "AIX EN PROVENCE TGV", "MARSEILLE", extended=True)
    retour = search(ds, "MARSEILLE", "MARSEILLE ST CHARLES", extended=True)
    assert [x.train_no for x in aller.direct] == ["700"]
    assert [x.train_no for x in retour.direct] == ["700"]
    # Hub Paris au départ et à l'arrivée
    assert search(ds, "PARIS", "MARSEILLE").direct
    assert search(ds, "TOULON", "PARIS").direct


# --- Partie A -----------------------------------------------------------------

def test_direct(ds):
    r = search(ds, "PARIS", "MARSEILLE")
    assert [x.train_no for x in r.direct] == ["300", "602", "603", "350"]


def test_heure_min_and_arrivee_max(ds):
    assert [x.train_no for x in search(ds, "PARIS", "MARSEILLE", heure_min="09:00").direct] \
        == ["602", "603", "350"]
    assert [x.train_no for x in search(ds, "PARIS", "MARSEILLE", arrivee_max="12:30").direct] \
        == ["300", "602"]


def test_midnight(ds):
    r = search(ds, "AIX EN PROVENCE TGV", "MARSEILLE ST CHARLES")
    assert r.direct[0].arrivee == "00:20 (+1j)"


# --- Partie B -----------------------------------------------------------------

def test_boarding_real_times(ds):
    r = search(ds, "LYON", "MARSEILLE")
    b = [x for x in r.boarding if x.train_no == "100"]
    assert len(b) == 1
    assert b[0].depart == "09:05" and b[0].arrivee == "10:40"
    assert b[0].od_max == "PARIS GARE DE LYON → TOULON"


def test_boarding_return_direction(ds):
    r = search(ds, "MARSEILLE", "LYON")
    assert [(x.train_no, x.depart, x.arrivee) for x in r.boarding] == [("101", "16:00", "17:35")]


def test_boarding_hidden_when_train_has_direct(ds):
    r = search(ds, "LYON", "MARSEILLE")
    assert "350" in [x.train_no for x in r.direct]
    assert "350" not in [x.train_no for x in r.boarding]


def test_split_train_guard(ds):
    # Le billet Paris -> Grenoble ne dessert pas Chambéry (autre branche)
    r = search(ds, "LYON", "CHAMBERY CHALLES LES EAUX")
    assert r.boarding == [] and r.direct == []
    r = search(ds, "LYON", "GRENOBLE")
    assert [(x.train_no, x.depart) for x in r.boarding] == [("200", "10:00")]


def test_boarding_can_be_disabled(ds):
    assert search(ds, "LYON", "MARSEILLE", allow_boarding=False).boarding == []


# --- Partie C -----------------------------------------------------------------

def test_two_segments_same_station_margin(ds):
    r = search(ds, "PARIS", "TOULOUSE MATABIAU")
    assert [x.train_no for x in r.two_segments] == ["400+500"]


def test_two_segments_hub_and_dominance(ds):
    r = search(ds, "LILLE EUROPE", "MARSEILLE")
    assert [x.train_no for x in r.two_segments] == ["600+602"]
    assert "PARIS NORD → PARIS GARE DE LYON" in r.two_segments[0].itineraire


def test_two_segments_not_when_dominated_by_direct(ds):
    # Paris -> Marseille : il existe des directs, aucune combinaison ne les bat
    assert search(ds, "PARIS", "MARSEILLE").two_segments == []


# --- Balayage -------------------------------------------------------------------

def test_scan(ds):
    dl = E.resolve_location("PARIS", ds.stations).candidates
    al = E.resolve_location("MARSEILLE", ds.stations).candidates
    days = E.scan_days(ds, E.Query(D, dl, al), n_days=30)
    assert [(d.date_str, d.n_direct) for d in days] == [(D, 4), (D2, 2)]
    assert days[1].last_dep == "18:00"


# --- Partie D : MAX + TER ------------------------------------------------------

def test_gtfs_station_names_match_csv(net):
    assert {"MARSEILLE ST CHARLES", "CASSIS", "TOULON", "LYON PART DIEU"} <= net.stations


def test_max_then_ter(ds, net):
    r = search(ds, "PARIS", "CASSIS", net=net)
    assert r.all_max == []
    got = [(x.train_no, x.depart, x.arrivee) for x in r.max_ter]
    # Train 100 (descente en cours à Marseille 10:40) -> TER 11:25 : OK.
    # Train 300 (arrivée 11:20) -> TER 11:25 refusé (marge 5 min) -> TER 11:40.
    # Le TGV 6199 présent dans le GTFS est ignoré (mode exclu).
    assert got == [("100+TER 881001", "07:00", "11:48"), ("300+TER 881003", "08:00", "12:03"),
                   ("602+TER 881005", "09:10", "13:13")]
    assert "descente en cours" in r.max_ter[0].commentaire


def test_ter_then_max(ds, net):
    r = search(ds, "CASSIS", "PARIS", net=net)
    assert [(x.train_no, x.depart, x.arrivee) for x in r.max_ter] == [("TER 881100+900", "07:00", "11:00")]


def test_ter_only_when_no_full_max(ds, net):
    # Paris -> Marseille : il existe du 100 % MAX, donc pas de Partie D ...
    assert search(ds, "PARIS", "MARSEILLE", net=net).max_ter == []
    # ... et même forcée, MAX Toulon + TER retour est dominé par les directs
    assert search(ds, "PARIS", "MARSEILLE", net=net, force_ter=True).max_ter == []


def test_no_max_ter_when_max_already_reaches_city(ds, net):
    # MAX Paris -> Lyon Part-Dieu puis TER -> Perrache : déjà dans la ville
    assert search(ds, "PARIS", "LYON PERRACHE", net=net).max_ter == []


def test_ter_can_be_disabled(ds, net):
    assert search(ds, "PARIS", "CASSIS", net=net, allow_ter=False).max_ter == []
