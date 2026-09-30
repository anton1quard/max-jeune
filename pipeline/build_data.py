"""
Pipeline de données du site web MAX Jeune.

Transforme le CSV TGVMax et le GTFS SNCF en petits fichiers JSON lus par le
site (un fichier par jour), en réutilisant le moteur Python (même lecture,
mêmes noms de gares) : le site et l'appli de bureau voient donc exactement
les mêmes données.

Sortie (dossier --out) :
    meta.json          dates disponibles, gares, configuration du moteur
    max/AAAA-MM-JJ.json   lignes du CSV TGVMax de ce jour (OUI et NON)
    ter/AAAA-MM-JJ.json   trajets TER / Intercités circulant ce jour

Usage :
    python pipeline/build_data.py --out _site/data             (fichiers locaux)
    python pipeline/build_data.py --out _site/data --download  (télécharge d'abord)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import max_jeune_engine as E  # noqa: E402

MIN_ROWS = 10_000          # garde-fou : en dessous, le CSV est jugé cassé
FORMAT_VERSION = 1


def _minutes(dt: datetime, day: datetime) -> int:
    return int((dt - day).total_seconds() // 60)


_CONTENT_HASH = hashlib.sha256()


def _dump(path: Path, obj, hashed: bool = True) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    path.write_text(data, encoding="utf-8")
    if hashed:
        _CONTENT_HASH.update(path.name.encode() + data.encode("utf-8"))
    return len(data)


def engine_config() -> dict:
    """Constantes du moteur, exportées pour que le moteur JS utilise les mêmes."""
    return {
        "HUBS": E.HUBS,
        "HUB_EXTENDED_MAP": E.HUB_EXTENDED_MAP,
        "CONNECTION_HUBS": E.CONNECTION_HUBS,
        "MANUAL_ALIASES": E.MANUAL_ALIASES,
        "MARGIN_SAME_TRAIN_MAX": E.MARGIN_SAME_TRAIN_MAX,
        "MARGIN_SAME_STATION_MIN": E.MARGIN_SAME_STATION_MIN,
        "MARGIN_HUB_MIN": E.MARGIN_HUB_MIN,
        "MARGIN_CONNECTION_MAX": E.MARGIN_CONNECTION_MAX,
        "TWO_SEG_TOTAL_DURATION_MAX_MIN": E.TWO_SEG_TOTAL_DURATION_MAX_MIN,
        "TER_SEARCH_WINDOW_MIN": E.TER_SEARCH_WINDOW_MIN,
        "SCAN_DEFAULT_DAYS": E.SCAN_DEFAULT_DAYS,
    }


def build(out: Path, csv_path: Path, gtfs_path: Path) -> dict:
    # --- CSV TGVMax, regroupé par jour (ordre du fichier conservé) ----------
    per_day: "OrderedDict[str, dict]" = OrderedDict()
    n_rows = n_oui = 0
    all_stations = set()
    for r in E.iter_csv_rows(csv_path):
        n_rows += 1
        n_oui += r.oui
        day = per_day.get(r.date_str)
        if day is None:
            day = per_day[r.date_str] = {"idx": {}, "stations": [], "rows": [],
                                         "base": datetime.strptime(r.date_str, "%Y-%m-%d")}
        for s in (r.o, r.d):
            if s not in day["idx"]:
                day["idx"][s] = len(day["stations"])
                day["stations"].append(s)
            all_stations.add(s)
        day["rows"].append([r.train, day["idx"][r.o], day["idx"][r.d],
                            _minutes(r.dt_d, day["base"]), _minutes(r.dt_a, day["base"]),
                            1 if r.oui else 0])
    if n_rows < MIN_ROWS:
        raise SystemExit(f"CSV TGVMax suspect : seulement {n_rows} lignes lues.")

    # --- GTFS ----------------------------------------------------------------
    net = E.load_ter_network(gtfs_path, max_stations=all_stations)
    if len(net.trips) < 1000:
        raise SystemExit(f"GTFS suspect : seulement {len(net.trips)} trajets TER.")

    dates = sorted(per_day)
    sizes = {"max": 0, "ter": 0}
    for d in dates:
        day = per_day[d]
        sizes["max"] += _dump(out / "max" / f"{d}.json",
                              {"date": d, "stations": day["stations"], "rows": day["rows"]})
        # Format compact : trip = [mode, n° train, s0, a0, attente0, f0, s1, a1, ...]
        # (gare = index local, a = arrivée en minutes, attente = départ - arrivée,
        #  f = 1 montée autorisée | 2 descente autorisée)
        idx, stations, trips, modes = {}, [], [], []
        for mode, train, service, stops in net.trips:
            if d not in net.service_dates.get(service, ()):
                continue
            if mode not in modes:
                modes.append(mode)
            enc = [modes.index(mode), train]
            for st, a, dep, can_board, can_alight in stops:
                if st not in idx:
                    idx[st] = len(stations)
                    stations.append(st)
                enc += [idx[st], a, dep - a, (1 if can_board else 0) | (2 if can_alight else 0)]
            trips.append(enc)
        sizes["ter"] += _dump(out / "ter" / f"{d}.json",
                              {"date": d, "modes": modes, "stations": stations, "trips": trips})

    meta = {
        "format": FORMAT_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tgvmax_rows": n_rows,
        "tgvmax_oui": n_oui,
        "gtfs_version": net.feed_version,
        # Empreinte des fichiers de données : sert à ne republier le site que
        # si les données SNCF ont réellement changé (voir check_changed.py).
        "content_hash": _CONTENT_HASH.hexdigest(),
        "dates": dates,
        "stations": sorted(all_stations | net.stations),
        "config": engine_config(),
    }
    sizes["meta"] = _dump(out / "meta.json", meta, hashed=False)
    return {"dates": len(dates), "rows": n_rows, "oui": n_oui, "ter_trips": len(net.trips),
            "sizes_mb": {k: round(v / 1e6, 2) for k, v in sizes.items()}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--csv", type=Path, default=E.TGVMAX_CACHE_PATH)
    ap.add_argument("--gtfs", type=Path, default=E.GTFS_PATH)
    ap.add_argument("--download", action="store_true", help="télécharge CSV et GTFS avant")
    args = ap.parse_args()
    if args.download:
        print("Téléchargement TGVMax…", flush=True)
        E.download_tgvmax(args.csv)
        print("Téléchargement GTFS…", flush=True)
        E.download_gtfs(args.gtfs)
    print(json.dumps(build(args.out, args.csv, args.gtfs), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
