"""
Génère les résultats de référence ("golden") avec le moteur Python, sur les
mêmes fichiers source que ceux utilisés pour construire les données du site.
Le test JavaScript (golden.test.mjs) rejoue les mêmes recherches et doit
obtenir exactement les mêmes résultats.

Usage : python web/tests/make_golden.py --out golden.json [--csv ...] [--gtfs ...]
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import max_jeune_engine as E  # noqa: E402

CORE = ["PARIS", "LYON", "MARSEILLE", "LILLE", "NANTES", "BORDEAUX", "MONTPELLIER",
        "NICE VILLE", "STRASBOURG", "CASSIS", "GAP", "AVIGNON"]
EXTRA_PAIRS = [
    ("LYON (HUB ETENDU)", "MARSEILLE"), ("MARSEILLE", "LYON"), ("PARIS GARE DE LYON", "TOULON"),
    ("MASSY TGV", "LYON"), ("RENNES", "MARSEILLE"), ("PERPIGNAN", "PARIS"), ("ANNECY", "PARIS"),
    ("AIX EN PROVENCE", "LYON"), ("GRENOBLE", "PARIS"), ("LE MANS", "LYON"), ("DIJON VILLE", "MARSEILLE"),
    ("VALENCE TGV", "PARIS"), ("PARIS", "LYON PERRACHE"), ("TOULON", "LYON"), ("PARIS", "BREST"),
    ("PARIS", "LYON (HUB ETENDU)"), ("LYON (HUB ETENDU)", "PARIS"), ("MARSEILLE", "PARIS"),
]
VARIANTS = [
    {},
    {"extended": True},
    {"heure_min": "17:00"},
    {"arrivee_max": "12:00"},
    {"force_ter": True},
    {"allow_boarding": False, "allow_two_segments": False},
]
RESOLVE_INPUTS = ["paris", "Lyon (hub)", "LYON (HUB ETENDU)", "marseille", "Aix", "aix tgv",
                  "st etienne", "Saint-Étienne Châteaucreux", "nimes", "lille", "xyzzy", "  ",
                  "LYON ETENDU", "MARSEILLE (HUB)", "valence", "cdg 2 tgv", "Paris Gare de Lyon"]


def res_to_dict(r: E.SearchResult) -> dict:
    return {"group": r.group, "itineraire": r.itineraire, "depart": r.depart, "arrivee": r.arrivee,
            "duree": r.duree, "train_no": r.train_no, "od_max": r.od_max,
            "commentaire": r.commentaire}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--csv", type=Path, default=E.TGVMAX_CACHE_PATH)
    ap.add_argument("--gtfs", type=Path, default=E.GTFS_PATH)
    ap.add_argument("--quick", action="store_true", help="moins de requêtes (CI rapide)")
    args = ap.parse_args()

    t0 = time.time()
    ds = E.load_dataset(args.csv)
    net = E.load_ter_network(args.gtfs, max_stations=ds.stations)
    known = ds.stations | net.stations
    dates = ds.dates
    sample_dates = sorted({dates[0], dates[len(dates) // 3], dates[2 * len(dates) // 3], dates[-1]})
    if args.quick:
        sample_dates = sample_dates[:2]

    cases = []

    def run(dep, arr, date, **opts):
        ext = opts.pop("extended", False)
        dl, al = E.resolve_location(dep, known, ext), E.resolve_location(arr, known, ext)
        if not dl or not al:
            return
        q = E.Query(date, dl.candidates, al.candidates, **opts)
        out = E.run_search(ds, q, net)
        cases.append({"dep": dep, "arr": arr, "date": date, "extended": ext, "opts": opts,
                      "results": [res_to_dict(r) for r in out.all]})

    for date in sample_dates[:2]:
        for dep, arr in itertools.permutations(CORE, 2):
            run(dep, arr, date)
    for date in sample_dates:
        for dep, arr in EXTRA_PAIRS:
            for v in VARIANTS:
                run(dep, arr, date, **dict(v))

    scans = []
    for dep, arr in [("PARIS", "MARSEILLE"), ("MARSEILLE", "LYON"), ("PARIS", "CASSIS")]:
        dl, al = E.resolve_location(dep, known), E.resolve_location(arr, known)
        days = E.scan_days(ds, E.Query(dates[0], dl.candidates, al.candidates), 30, net=net)
        scans.append({"dep": dep, "arr": arr, "start": dates[0], "n_days": 30,
                      "days": [{"date": d.date_str, "n_direct": d.n_direct, "n_boarding": d.n_boarding,
                                "n_two": d.n_two, "n_ter": d.n_ter, "first_dep": d.first_dep,
                                "last_dep": d.last_dep, "fastest": d.fastest} for d in days]})

    resolves = []
    for text in RESOLVE_INPUTS:
        for ext in (False, True):
            loc = E.resolve_location(text, known, ext)
            resolves.append({"text": text, "extended": ext,
                             "result": None if loc is None else
                             {"display": loc.display, "candidates": sorted(loc.candidates)}})

    golden = {"cases": cases, "scans": scans, "resolves": resolves,
              "labels": {d: E.day_label(d) for d in dates},
              "autocomplete_count": len(E.build_autocomplete_entries(known))}
    args.out.write_text(json.dumps(golden, ensure_ascii=False), encoding="utf-8")
    n_res = sum(len(c["results"]) for c in cases)
    print(f"{len(cases)} recherches, {n_res} résultats, {len(scans)} balayages "
          f"en {time.time() - t0:.0f}s -> {args.out}")


if __name__ == "__main__":
    main()
