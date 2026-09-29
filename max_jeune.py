"""
===============================================================================
 MAX JEUNE - Interface Tkinter (V2)
===============================================================================

Interface graphique seule : toute la logique de recherche est dans
max_jeune_engine.py (à garder dans le même dossier).

Lancement :   python max_jeune.py
Tests moteur : python -m pytest tests

Onglets :
    - Résultats : résultats groupés (MAX direct / montée en cours / 2 segments),
      tri par clic sur les colonnes.
    - Balayage : même recherche sur N jours (30 par défaut), lancée à la
      demande ; double-clic sur un jour pour afficher son détail.
"""

from __future__ import annotations

import calendar as _cal
import csv
import queue
import re
import threading
import time
import urllib.error
from datetime import date, datetime
from typing import Callable, Dict, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import max_jeune_engine as E
from max_jeune_engine import _parse_hhmm, normalize


# =============================================================================
# 1. STYLE
# =============================================================================

COLORS = {
    "bg": "#F4F6FA",
    "card": "#FFFFFF",
    "primary": "#1F4E8C",
    "primary_active": "#173B6B",
    "text": "#1E2430",
    "muted": "#6B7385",
    "A": "#E8F5EC",      # vert pâle : MAX direct
    "B": "#E8F0FB",      # bleu pâle : montée en cours
    "C": "#FFF4E5",      # orange pâle : 2 segments
    "D": "#F3ECFA",      # violet pâle : MAX + TER
    "group": "#DDE3EE",
    "zero": "#9AA1AE",
}


def apply_style(root: tk.Tk) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    base = ("Segoe UI", 10) if root.tk.call("tk", "windowingsystem") == "win32" else ("Helvetica", 11)
    root.option_add("*Font", base)
    root.configure(bg=COLORS["bg"])
    style.configure(".", background=COLORS["bg"], foreground=COLORS["text"], font=base)
    style.configure("Card.TFrame", background=COLORS["card"])
    style.configure("Card.TLabel", background=COLORS["card"])
    style.configure("Card.TCheckbutton", background=COLORS["card"])
    style.configure("Muted.TLabel", background=COLORS["card"], foreground=COLORS["muted"])
    style.configure("Header.TFrame", background=COLORS["primary"])
    style.configure("Header.TLabel", background=COLORS["primary"], foreground="white",
                    font=(base[0], base[1] + 7, "bold"))
    style.configure("SubHeader.TLabel", background=COLORS["primary"], foreground="#C9D6EA")
    style.configure("Accent.TButton", background=COLORS["primary"], foreground="white",
                    font=(base[0], base[1], "bold"), padding=(16, 6), borderwidth=0)
    style.map("Accent.TButton", background=[("active", COLORS["primary_active"])])
    style.configure("TButton", padding=(10, 5))
    style.configure("Treeview", rowheight=26, background=COLORS["card"],
                    fieldbackground=COLORS["card"])
    style.configure("Treeview.Heading", font=(base[0], base[1], "bold"),
                    background=COLORS["group"], relief="flat")
    style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", padding=(14, 6))
    style.configure("Status.TLabel", background=COLORS["group"], foreground=COLORS["text"],
                    padding=(10, 4))


# =============================================================================
# 2. FENÊTRE PRINCIPALE
# =============================================================================

RESULT_COLS = ("trajet", "depart", "arrivee", "duree", "train", "od", "commentaire")
RESULT_HEADERS = {
    "trajet": "Trajet proposé", "depart": "Départ", "arrivee": "Arrivée",
    "duree": "Durée", "train": "TRAIN_NO", "od": "OD MAX officiel",
    "commentaire": "Commentaire",
}
SHORT_LABELS = {"A": "   direct", "B": "   montée en cours", "C": "   2 segments",
                "D": "   MAX + TER"}
RESULT_WIDTHS = {"trajet": 360, "depart": 70, "arrivee": 90, "duree": 65,
                 "train": 95, "od": 340, "commentaire": 560}


def _train_key(s: str):
    return tuple(int(x) for x in re.findall(r"\d+", s)) or (0,)


SORT_KEYS: Dict[str, Callable[[E.SearchResult], object]] = {
    "trajet": lambda r: r.itineraire,
    "depart": lambda r: r.dt_dep,
    "arrivee": lambda r: r.dt_arr,
    "duree": lambda r: r.minutes,
    "train": lambda r: _train_key(r.train_no),
    "od": lambda r: r.od_max,
    "commentaire": lambda r: r.commentaire,
}

SCAN_COLS = ("jour", "direct", "montee", "deux", "ter", "total", "premier", "dernier", "rapide")
SCAN_HEADERS = {"jour": "Jour", "direct": "Directs", "montee": "Montée en cours",
                "deux": "2 segments", "ter": "MAX + TER", "total": "Total", "premier": "1er départ",
                "dernier": "Dernier départ", "rapide": "Plus rapide"}


class MaxJeuneApp(tk.Tk):

    def __init__(self) -> None:
        super().__init__()
        self.title("MAX Jeune — Moteur de recherche")
        self.geometry("1360x820")
        self.minsize(1000, 600)
        apply_style(self)

        self.ds: Optional[E.Dataset] = None
        self.net: Optional[E.TerNetwork] = None
        self.net_error: str = ""
        self.known: set = set()
        self.patterns: Dict = {}
        self.patterns_error: str = ""
        self.last_results: List[E.SearchResult] = []
        self._row_results: Dict[str, E.SearchResult] = {}
        self._sort_state: Dict[str, bool] = {}
        self._scan_dates: Dict[str, str] = {}
        self._busy = False
        self._queue: "queue.Queue[Callable[[], None]]" = queue.Queue()

        self._build_ui()
        self.after(50, self._poll_queue)
        self.after(100, self._start)

    # ------------------------------------------------------------ threading --
    def _ui(self, fn: Callable[[], None]) -> None:
        """Exécute fn dans le thread Tk (appelable depuis un thread worker)."""
        self._queue.put(fn)

    def _poll_queue(self) -> None:
        try:
            while True:
                self._queue.get_nowait()()
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    def _run_bg(self, work: Callable[[], object], done: Callable[[object], None],
                label: str) -> None:
        if self._busy:
            return
        self._busy = True
        self.status.set(label)
        self.config(cursor="watch")

        def worker():
            try:
                res = work()
                err = None
            except Exception as e:  # noqa: BLE001
                res, err = None, e

            def finish():
                self._busy = False
                self.config(cursor="")
                if err is not None:
                    messagebox.showerror("Erreur", str(err))
                    self.status.set("Erreur : " + str(err)[:120])
                else:
                    done(res)
            self._ui(finish)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------- UI --
    def _build_ui(self) -> None:
        # En-tête
        header = ttk.Frame(self, style="Header.TFrame", padding=(18, 12))
        header.pack(fill="x")
        ttk.Label(header, text="MAX Jeune", style="Header.TLabel").pack(side="left")
        self.header_info = tk.StringVar(value="Chargement des données…")
        ttk.Label(header, textvariable=self.header_info, style="SubHeader.TLabel").pack(
            side="right")

        # Carte de recherche
        card = ttk.Frame(self, style="Card.TFrame", padding=(18, 14))
        card.pack(fill="x", padx=14, pady=(14, 8))

        ttk.Label(card, text="Départ", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.entry_dep = AutocompleteEntry(card, width=30)
        self.entry_dep.grid(row=1, column=0, sticky="we", padx=(0, 6))
        ttk.Button(card, text="⇄", width=3, command=self._swap).grid(row=1, column=1)
        ttk.Label(card, text="Arrivée", style="Card.TLabel").grid(row=0, column=2, sticky="w",
                                                                   padx=(6, 0))
        self.entry_arr = AutocompleteEntry(card, width=30)
        self.entry_arr.grid(row=1, column=2, sticky="we", padx=(6, 18))

        ttk.Label(card, text="Date", style="Card.TLabel").grid(row=0, column=3, sticky="w")
        self.entry_date = DatePicker(card, style="Card.TFrame")
        self.entry_date.grid(row=1, column=3, sticky="w", padx=(0, 18))

        ttk.Label(card, text="Partir après", style="Card.TLabel").grid(row=0, column=4, sticky="w")
        self.entry_hmin = TimePicker(card, initial="00:00", style="Card.TFrame")
        self.entry_hmin.grid(row=1, column=4, sticky="w", padx=(0, 18))

        self.var_amax = tk.BooleanVar(value=False)
        ttk.Checkbutton(card, text="Arriver avant", variable=self.var_amax,
                        style="Card.TCheckbutton").grid(row=0, column=5, sticky="w")
        self.entry_amax = TimePicker(card, initial="23:59", style="Card.TFrame")
        self.entry_amax.grid(row=1, column=5, sticky="w", padx=(0, 18))

        card.columnconfigure(6, weight=1)

        opts = ttk.Frame(card, style="Card.TFrame")
        opts.grid(row=2, column=0, columnspan=6, sticky="w", pady=(12, 0))
        ttk.Button(card, text="Rechercher", style="Accent.TButton",
                   command=self._do_search).grid(row=2, column=5, columnspan=2, sticky="e",
                                                 pady=(12, 0))
        self.var_extended = tk.BooleanVar(value=False)
        self.var_boarding = tk.BooleanVar(value=True)
        self.var_two_seg = tk.BooleanVar(value=True)
        self.var_ter = tk.BooleanVar(value=True)
        self.var_force_ter = tk.BooleanVar(value=False)
        for text, var in [
            ("Hubs étendus", self.var_extended),
            ("Montée / descente en cours", self.var_boarding),
            ("2 segments MAX", self.var_two_seg),
            ("MAX + TER (si pas de 100 % MAX)", self.var_ter),
            ("Toujours MAX + TER", self.var_force_ter),
        ]:
            ttk.Checkbutton(opts, text=text, variable=var,
                            style="Card.TCheckbutton").pack(side="left", padx=(0, 18))
        self.entry_dep.bind("<Return>", lambda e: self._do_search(), add="+")
        self.entry_arr.bind("<Return>", lambda e: self._do_search(), add="+")

        # Barre d'outils secondaire
        tools = ttk.Frame(self, padding=(14, 0))
        tools.pack(fill="x")
        for text, cmd in [("Exporter CSV", self._export_csv), ("Diagnostic", self._diagnostic),
                          ("Recharger données", self._reload_data)]:
            ttk.Button(tools, text=text, command=cmd).pack(side="right", padx=(6, 0))

        # Onglets
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=14, pady=8)
        self.tab_results = ttk.Frame(self.nb)
        self.tab_scan = ttk.Frame(self.nb)
        self.nb.add(self.tab_results, text="Résultats")
        self.nb.add(self.tab_scan, text="Balayage multi-jours")
        self._build_results_tab()
        self._build_scan_tab()

        self.status = tk.StringVar(value="Démarrage…")
        ttk.Label(self, textvariable=self.status, style="Status.TLabel", anchor="w").pack(
            fill="x", side="bottom")

    def _build_results_tab(self) -> None:
        frame = self.tab_results
        self.tree = ttk.Treeview(frame, columns=RESULT_COLS, show="tree headings")
        self.tree.heading("#0", text="Type")
        self.tree.column("#0", width=235, stretch=False)
        for c in RESULT_COLS:
            self.tree.heading(c, text=RESULT_HEADERS[c], command=lambda c=c: self._sort_by(c))
            self.tree.column(c, width=RESULT_WIDTHS[c], anchor="w",
                             stretch=(c == "commentaire"))
        for g in (E.GROUP_A, E.GROUP_B, E.GROUP_C, E.GROUP_D):
            self.tree.tag_configure(g, background=COLORS[g])
        self.tree.tag_configure("group", background=COLORS["group"],
                                font=("TkDefaultFont", 10, "bold"))
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self._show_detail)

    def _build_scan_tab(self) -> None:
        frame = self.tab_scan
        bar = ttk.Frame(frame, padding=(0, 8))
        bar.grid(row=0, column=0, columnspan=2, sticky="we")
        ttk.Label(bar, text="Même recherche (gares, horaires, options) sur").pack(side="left")
        self.var_days = tk.StringVar(value=str(E.SCAN_DEFAULT_DAYS))
        ttk.Spinbox(bar, from_=1, to=60, width=4, textvariable=self.var_days).pack(
            side="left", padx=6)
        ttk.Label(bar, text="jours à partir de la date choisie.").pack(side="left")
        ttk.Button(bar, text="Lancer le balayage", style="Accent.TButton",
                   command=self._do_scan).pack(side="left", padx=14)
        ttk.Label(bar, text="Double-clic sur un jour = détail dans l'onglet Résultats",
                  foreground=COLORS["muted"]).pack(side="right")

        self.scan_tree = ttk.Treeview(frame, columns=SCAN_COLS, show="headings")
        for c in SCAN_COLS:
            self.scan_tree.heading(c, text=SCAN_HEADERS[c])
            self.scan_tree.column(c, width=150 if c == "jour" else 110,
                                  anchor="w" if c == "jour" else "center")
        self.scan_tree.tag_configure("zero", foreground=COLORS["zero"])
        self.scan_tree.tag_configure("some", background=COLORS["A"])
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.scan_tree.yview)
        self.scan_tree.configure(yscrollcommand=vsb.set)
        self.scan_tree.grid(row=1, column=0, sticky="nsew")
        vsb.grid(row=1, column=1, sticky="ns")
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        self.scan_tree.bind("<Double-1>", self._scan_open_day)

    # --------------------------------------------------------------- Données --
    def _start(self) -> None:
        try:
            self.patterns = E.load_patterns_from_excel(E.AXES_XLSX_PATH)
        except Exception as e:  # noqa: BLE001 — l'Excel ne sert qu'à la future Partie D
            self.patterns_error = str(e)
        if E.TGVMAX_CACHE_PATH.exists():
            self._load_cache()
        else:
            self._reload_data()

    def _load_all(self):
        """Worker : CSV TGVMax puis GTFS (facultatif : sans lui, pas de Partie D)."""
        ds = E.load_dataset()
        net, err = None, ""
        try:
            self._ui(lambda: self.status.set("Lecture des horaires TER (GTFS)…"))
            net = E.load_ter_network(max_stations=ds.stations)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        return ds, net, err

    def _load_cache(self) -> None:
        self._run_bg(self._load_all, self._on_loaded, "Lecture du cache TGVMax…")

    def _on_loaded(self, loaded) -> None:
        ds, self.net, self.net_error = loaded
        self.ds = ds
        self.known = set(ds.stations) | (self.net.stations if self.net else set())
        items = E.build_autocomplete_entries(self.known)
        self.entry_dep.set_completion_list(items)
        self.entry_arr.set_completion_list(items)
        dates = ds.dates
        age = (time.time() - E.TGVMAX_CACHE_PATH.stat().st_mtime) / 3600
        span = f"du {E.day_label(dates[0])} au {E.day_label(dates[-1])}" if dates else "vide"
        age_txt = f"{age:.0f} h" if age < 48 else f"{age / 24:.0f} jours"
        self.header_info.set(f"{len(ds.tickets):,} billets MAX OUI · {span} · "
                             f"mis à jour il y a {age_txt}".replace(",", " "))
        msg = (f"Données prêtes : {ds.n_rows:_} lignes, {len(ds.runs):_} circulations "
               f"reconstituées.").replace("_", " ")
        if self.net:
            msg += f" Horaires TER : version {self.net.feed_version}."
        else:
            msg += " Horaires TER indisponibles (Partie D désactivée) : " + self.net_error
        if age > E.CACHE_MAX_AGE_HOURS:
            msg += "  Cache ancien : pense à « Recharger données »."
        self.status.set(msg)
        if dates and self.entry_date.get() < dates[0]:
            self.entry_date.set(dates[0])

    def _reload_data(self) -> None:
        def work():
            E.download_tgvmax(E.TGVMAX_CACHE_PATH, progress_cb=lambda n: self._ui(
                lambda: self.status.set(f"Téléchargement TGVMax… {n / 1e6:.1f} Mo")))
            E.download_gtfs(E.GTFS_PATH, progress_cb=lambda n: self._ui(
                lambda: self.status.set(f"Téléchargement horaires TER… {n / 1e6:.1f} Mo")))
            return self._load_all()
        self._run_bg(work, self._on_loaded, "Téléchargement du CSV TGVMax…")

    # ------------------------------------------------------------- Recherche --
    def _swap(self) -> None:
        a, b = self.entry_dep.get(), self.entry_arr.get()
        self.entry_dep.delete(0, "end")
        self.entry_dep.insert(0, b)
        self.entry_arr.delete(0, "end")
        self.entry_arr.insert(0, a)

    def _build_query(self) -> Optional[tuple]:
        if self.ds is None:
            messagebox.showwarning("Données", "Les données ne sont pas encore chargées.")
            return None
        date_str = self.entry_date.get()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Date invalide", "Format attendu : AAAA-MM-JJ.")
            return None
        for picker in (self.entry_hmin, self.entry_amax):
            try:
                _parse_hhmm(picker.get())
            except ValueError:
                messagebox.showerror("Heure invalide", "Format attendu : HH:MM.")
                return None
        ext = self.var_extended.get()
        dep = E.resolve_location(self.entry_dep.get(), self.known, ext)
        arr = E.resolve_location(self.entry_arr.get(), self.known, ext)
        if not dep or not arr:
            messagebox.showerror("Gare inconnue",
                                 f"{'Départ' if not dep else 'Arrivée'} non reconnu(e).")
            return None
        q = E.Query(date_str, dep.candidates, arr.candidates,
                    heure_min=self.entry_hmin.get(),
                    arrivee_max=self.entry_amax.get() if self.var_amax.get() else None,
                    allow_boarding=self.var_boarding.get(),
                    allow_two_segments=self.var_two_seg.get(),
                    allow_ter=self.var_ter.get(),
                    force_ter=self.var_force_ter.get())
        return q, dep.display, arr.display

    def _do_search(self) -> None:
        built = self._build_query()
        if not built:
            return
        q, dep_d, arr_d = built
        out = E.run_search(self.ds, q, self.net)
        self.last_results = out.all
        self._display(out)
        self.nb.select(self.tab_results)
        self.status.set(
            f"{dep_d} → {arr_d}, {E.day_label(q.date_str)} : {len(out.direct)} direct(s), "
            f"{len(out.boarding)} montée(s) en cours, {len(out.two_segments)} solution(s) "
            f"2 segments, {len(out.max_ter)} MAX + TER.")

    def _display(self, out: E.SearchOutcome) -> None:
        self.tree.delete(*self.tree.get_children())
        self._row_results.clear()
        for group, results in ((E.GROUP_A, out.direct), (E.GROUP_B, out.boarding),
                               (E.GROUP_C, out.two_segments), (E.GROUP_D, out.max_ter)):
            if group == E.GROUP_D and not out.max_ter:
                continue
            label = f"{E.GROUP_LABELS[group]}  ({len(results)})"
            parent = self.tree.insert("", "end", text=label, open=True, tags=("group",))
            for r in results:
                iid = self.tree.insert(parent, "end", text=SHORT_LABELS[group], tags=(group,), values=(
                    r.itineraire, r.depart, r.arrivee, r.duree, r.train_no, r.od_max,
                    r.commentaire))
                self._row_results[iid] = r
        if not out.all:
            self.tree.insert("", "end", text="Aucun résultat",
                             values=("Essaie une autre date, l'onglet Balayage, ou les hubs étendus.",))

    def _sort_by(self, col: str) -> None:
        asc = self._sort_state.get(col, True)
        key = SORT_KEYS[col]
        for parent in self.tree.get_children(""):
            kids = [k for k in self.tree.get_children(parent) if k in self._row_results]
            kids.sort(key=lambda k: key(self._row_results[k]), reverse=not asc)
            for i, k in enumerate(kids):
                self.tree.move(k, parent, i)
        for c in RESULT_COLS:
            arrow = (" ▲" if asc else " ▼") if c == col else ""
            self.tree.heading(c, text=RESULT_HEADERS[c] + arrow)
        self._sort_state[col] = not asc

    def _show_detail(self, _event) -> None:
        sel = self.tree.selection()
        r = self._row_results.get(sel[0]) if sel else None
        if r:
            messagebox.showinfo(r.type, f"{r.itineraire}\n{E.day_label(r.date_str)} · "
                                f"{r.depart} → {r.arrivee} ({r.duree})\nTrain {r.train_no}\n"
                                f"Billet(s) : {r.od_max}\n\n{r.commentaire}")

    # -------------------------------------------------------------- Balayage --
    def _do_scan(self) -> None:
        built = self._build_query()
        if not built:
            return
        q, dep_d, arr_d = built
        try:
            n = max(1, min(60, int(self.var_days.get())))
        except ValueError:
            n = E.SCAN_DEFAULT_DAYS

        def work():
            return E.scan_days(self.ds, q, n, progress_cb=lambda i, t: self._ui(
                lambda: self.status.set(f"Balayage… {i}/{t} jours")), net=self.net)

        def done(days: List[E.DaySummary]):
            self.scan_tree.delete(*self.scan_tree.get_children())
            self._scan_dates.clear()
            for d in days:
                iid = self.scan_tree.insert("", "end", tags=("zero" if d.total == 0 else "some",),
                                            values=(E.day_label(d.date_str), d.n_direct,
                                                    d.n_boarding, d.n_two, d.n_ter, d.total,
                                                    d.first_dep, d.last_dep, d.fastest))
                self._scan_dates[iid] = d.date_str
            ok = sum(1 for d in days if d.total)
            self.status.set(f"Balayage {dep_d} → {arr_d} : {ok} jour(s) sur {len(days)} "
                            f"avec au moins une solution.")

        self.nb.select(self.tab_scan)
        self._run_bg(work, done, "Balayage en cours…")

    def _scan_open_day(self, _event) -> None:
        sel = self.scan_tree.selection()
        if sel and sel[0] in self._scan_dates:
            self.entry_date.set(self._scan_dates[sel[0]])
            self._do_search()

    # ---------------------------------------------------- Diagnostic / Export --
    def _diagnostic(self) -> None:
        ds = self.ds
        m = [f"Cache : {E.TGVMAX_CACHE_PATH}  (existe : {E.TGVMAX_CACHE_PATH.exists()})"]
        if E.TGVMAX_CACHE_PATH.exists():
            m.append(f"  âge : {(time.time() - E.TGVMAX_CACHE_PATH.stat().st_mtime) / 3600:.1f} h")
        if ds:
            m += [f"  lignes lues : {ds.n_rows}   dont OUI : {len(ds.tickets)}",
                  f"  circulations reconstituées (date, train) : {len(ds.runs)}",
                  f"  gares distinctes : {len(ds.stations)}",
                  f"  dates : {ds.dates[0] if ds.dates else '-'} → {ds.dates[-1] if ds.dates else '-'}",
                  "", "Colonnes détectées :"]
            m += [f"  {k:8s} -> {v}" for k, v in ds.debug.get("columns", {}).items()]
            suspects = sorted(s for s in ds.stations if "INTRAMUROS" in s)
            m += ["", "Libellés 'intramuros' non résolus (code IATA à ajouter) : "
                  + (", ".join(suspects) if suspects else "aucun")]
            m += ["", "Couverture des hubs (billets OUI au départ ou à l'arrivée) :"]
            cnt: Dict[str, int] = {}
            for t in ds.tickets:
                cnt[t.origine] = cnt.get(t.origine, 0) + 1
                cnt[t.destination] = cnt.get(t.destination, 0) + 1
            for hub, lst in E.HUBS.items():
                m.append(f"  [{hub}]")
                m += [f"    {s:32s} {cnt.get(s, 0)}" for s in lst]
        if self.net:
            m += ["", f"Horaires TER (GTFS) : {E.GTFS_PATH.name}, version {self.net.feed_version}",
                  f"  trajets TER/Intercités : {len(self.net.trips)}   gares : {len(self.net.stations)}"]
            if ds:
                missing = sorted(ds.stations - self.net.stations)
                m.append(f"  gares MAX absentes du réseau TER ({len(missing)}) : " + ", ".join(missing))
        else:
            m += ["", f"Horaires TER (GTFS) indisponibles : {self.net_error}"]
        m += ["", f"Axes Excel (plus utilisés par le moteur) : {len(self.patterns)} couples OD"
              + (f" — non chargés : {self.patterns_error}" if self.patterns_error else "")]
        top = tk.Toplevel(self)
        top.title("Diagnostic")
        txt = tk.Text(top, width=100, height=36, font=("Courier", 10))
        txt.insert("1.0", "\n".join(m))
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)

    def _export_csv(self) -> None:
        if not self.last_results:
            messagebox.showinfo("Export", "Aucun résultat à exporter.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile="max_jeune_resultats.csv")
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Type", "Trajet", "Date", "Depart", "Arrivee", "Duree", "Train_no",
                        "OD_MAX_officiel", "Commentaire"])
            for r in self.last_results:
                w.writerow([r.type, r.itineraire, r.date_str, r.depart, r.arrivee, r.duree,
                            r.train_no, r.od_max, r.commentaire])
        messagebox.showinfo("Export", f"Résultats exportés :\n{path}")


# =============================================================================
# 3. WIDGETS (calendrier, heure, autocomplete)
# =============================================================================

# --- Sélecteur de date (calendrier natif, sans dépendance) -------------------
class DatePicker(ttk.Frame):
    """Champ date YYYY-MM-DD + bouton ouvrant un calendrier popup."""

    def __init__(self, master, initial: Optional[str] = None, **kw):
        super().__init__(master, **kw)
        self.var = tk.StringVar(value=initial or datetime.now().strftime("%Y-%m-%d"))
        self.entry = ttk.Entry(self, textvariable=self.var, width=13)
        self.entry.pack(side="left")
        ttk.Button(self, text="▾", width=2, command=self._open_calendar).pack(side="left", padx=(2, 0))

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value)

    def _open_calendar(self) -> None:
        try:
            current = datetime.strptime(self.var.get().strip(), "%Y-%m-%d").date()
        except ValueError:
            current = date.today()
        CalendarPopup(self, current, on_pick=lambda d: self.var.set(d.strftime("%Y-%m-%d")))


class CalendarPopup(tk.Toplevel):
    """Petit calendrier mensuel, navigation par mois/année."""

    def __init__(self, master, initial: date, on_pick) -> None:
        super().__init__(master)
        self.title("Sélectionner une date")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.on_pick = on_pick
        self.cursor_date = initial.replace(day=1)
        self.selected = initial

        # Header : navigation mois/année
        header = ttk.Frame(self, padding=5)
        header.pack(fill="x")
        ttk.Button(header, text="«", width=3, command=self._prev_year).pack(side="left")
        ttk.Button(header, text="‹", width=3, command=self._prev_month).pack(side="left")
        self.lbl = ttk.Label(header, text="", font=("TkDefaultFont", 10, "bold"), width=18, anchor="center")
        self.lbl.pack(side="left", expand=True)
        ttk.Button(header, text="›", width=3, command=self._next_month).pack(side="right")
        ttk.Button(header, text="»", width=3, command=self._next_year).pack(side="right")

        # Grille des jours
        self.grid_frame = ttk.Frame(self, padding=5)
        self.grid_frame.pack()

        # Footer : aujourd'hui
        footer = ttk.Frame(self, padding=5)
        footer.pack(fill="x")
        ttk.Button(footer, text="Aujourd'hui", command=self._pick_today).pack(side="left")
        ttk.Button(footer, text="Annuler", command=self.destroy).pack(side="right")

        self._render()

        # Centrage approx sur le parent
        self.update_idletasks()
        x = master.winfo_rootx() + 10
        y = master.winfo_rooty() + 30
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def _render(self) -> None:
        for w in self.grid_frame.winfo_children():
            w.destroy()
        months_fr = ["janvier", "février", "mars", "avril", "mai", "juin",
                     "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        self.lbl.config(text=f"{months_fr[self.cursor_date.month - 1]} {self.cursor_date.year}")
        days = ["Lu", "Ma", "Me", "Je", "Ve", "Sa", "Di"]
        for i, d in enumerate(days):
            ttk.Label(self.grid_frame, text=d, width=4, anchor="center",
                      foreground="#666").grid(row=0, column=i, padx=1, pady=1)
        cal = _cal.Calendar(firstweekday=0)
        for week_idx, week in enumerate(
            cal.monthdatescalendar(self.cursor_date.year, self.cursor_date.month), start=1
        ):
            for col, d in enumerate(week):
                if d.month != self.cursor_date.month:
                    ttk.Label(self.grid_frame, text=str(d.day), width=4, anchor="center",
                              foreground="#bbb").grid(row=week_idx, column=col, padx=1, pady=1)
                else:
                    btn = ttk.Button(self.grid_frame, text=str(d.day), width=4,
                                     command=lambda x=d: self._pick(x))
                    btn.grid(row=week_idx, column=col, padx=1, pady=1)

    def _pick(self, d: date) -> None:
        self.on_pick(d)
        self.destroy()

    def _pick_today(self) -> None:
        self._pick(date.today())

    def _prev_month(self) -> None:
        m, y = self.cursor_date.month - 1, self.cursor_date.year
        if m == 0:
            m, y = 12, y - 1
        self.cursor_date = self.cursor_date.replace(year=y, month=m, day=1)
        self._render()

    def _next_month(self) -> None:
        m, y = self.cursor_date.month + 1, self.cursor_date.year
        if m == 13:
            m, y = 1, y + 1
        self.cursor_date = self.cursor_date.replace(year=y, month=m, day=1)
        self._render()

    def _prev_year(self) -> None:
        self.cursor_date = self.cursor_date.replace(year=self.cursor_date.year - 1, day=1)
        self._render()

    def _next_year(self) -> None:
        self.cursor_date = self.cursor_date.replace(year=self.cursor_date.year + 1, day=1)
        self._render()


# --- Sélecteur d'heure (popup natif) -----------------------------------------
class TimePicker(ttk.Frame):
    """Champ heure HH:MM + bouton ouvrant un popup heure/minute."""

    def __init__(self, master, initial: str = "00:00", **kw):
        super().__init__(master, **kw)
        self.var = tk.StringVar(value=initial)
        self.entry = ttk.Entry(self, textvariable=self.var, width=8)
        self.entry.pack(side="left")
        ttk.Button(self, text="▾", width=2, command=self._open).pack(side="left", padx=(2, 0))

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value)

    def _open(self) -> None:
        try:
            hh, mm = _parse_hhmm(self.var.get())
        except ValueError:
            hh, mm = 0, 0
        TimePickerPopup(self, hh, mm, on_pick=self._on_pick)

    def _on_pick(self, hh: int, mm: int) -> None:
        self.var.set(f"{hh:02d}:{mm:02d}")


class TimePickerPopup(tk.Toplevel):
    """Popup simple : spinbox heure + spinbox minutes + presets."""

    def __init__(self, master, hh: int, mm: int, on_pick) -> None:
        super().__init__(master)
        self.title("Sélectionner une heure")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.on_pick = on_pick

        frm = ttk.Frame(self, padding=10)
        frm.pack()
        ttk.Label(frm, text="Heure :").grid(row=0, column=0, padx=5, sticky="e")
        self.h_var = tk.StringVar(value=f"{hh:02d}")
        ttk.Spinbox(frm, from_=0, to=23, textvariable=self.h_var, width=5,
                    format="%02.0f", wrap=True).grid(row=0, column=1, padx=5)
        ttk.Label(frm, text="Minutes :").grid(row=1, column=0, padx=5, sticky="e")
        self.m_var = tk.StringVar(value=f"{mm:02d}")
        ttk.Spinbox(frm, from_=0, to=55, textvariable=self.m_var, width=5,
                    format="%02.0f", increment=5, wrap=True).grid(row=1, column=1, padx=5)

        presets = ttk.Frame(self, padding=(10, 0))
        presets.pack()
        for lbl, h, m in [("00:00", 0, 0), ("06:00", 6, 0), ("09:00", 9, 0),
                          ("12:00", 12, 0), ("17:00", 17, 0), ("20:00", 20, 0)]:
            ttk.Button(presets, text=lbl, width=6,
                       command=lambda h=h, m=m: self._pick(h, m)).pack(side="left", padx=2, pady=5)

        btns = ttk.Frame(self, padding=5)
        btns.pack()
        ttk.Button(btns, text="OK", command=self._ok).pack(side="left", padx=5)
        ttk.Button(btns, text="Annuler", command=self.destroy).pack(side="left", padx=5)

        self.update_idletasks()
        x = master.winfo_rootx() + 10
        y = master.winfo_rooty() + 30
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def _ok(self) -> None:
        try:
            hh = max(0, min(23, int(self.h_var.get())))
            mm = max(0, min(59, int(self.m_var.get())))
        except ValueError:
            hh, mm = 0, 0
        self._pick(hh, mm)

    def _pick(self, hh: int, mm: int) -> None:
        self.on_pick(hh, mm)
        self.destroy()


# --- Autocomplete widget ------------------------------------------------------
class AutocompleteEntry(ttk.Entry):
    """Entry avec Listbox déroulante (préfixe puis contient)."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self._items: List[str] = []
        self._listbox: Optional[tk.Listbox] = None
        # Délai avant masquage sur perte de focus, suffisant pour qu'un clic
        # sur la listbox soit traité avant la disparition.
        self._hide_after_id = None
        self.bind("<KeyRelease>", self._on_keyrelease)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Return>", self._on_return)
        self.bind("<Down>", self._on_down)
        self.bind("<Escape>", lambda e: self._hide_listbox())

    def set_completion_list(self, items: List[str]) -> None:
        self._items = sorted(set(items))

    # --- événements ------------------------------------------------
    def _on_keyrelease(self, event):
        if event.keysym in ("Up", "Down", "Return", "Tab", "Escape"):
            return
        text = self.get().strip()
        if not text:
            self._hide_listbox()
            return
        norm_text = normalize(text)
        starts = [i for i in self._items if normalize(i).startswith(norm_text)]
        contains = [i for i in self._items if norm_text in normalize(i) and i not in starts]
        matches = (starts + contains)[:30]
        if matches:
            self._show_listbox(matches)
        else:
            self._hide_listbox()

    def _on_focus_out(self, event):
        # On reporte la fermeture pour laisser le clic sur la listbox aboutir.
        if self._hide_after_id:
            self.after_cancel(self._hide_after_id)
        self._hide_after_id = self.after(250, self._hide_listbox)

    def _on_return(self, event):
        # Liste ouverte : Entrée valide la 1re suggestion (sans lancer la
        # recherche). Liste fermée : on laisse passer (Entrée = Rechercher).
        if self._listbox is not None and self._listbox.winfo_ismapped() and self._listbox.size():
            self._select_index(0)
            return "break"
        return None

    def _on_down(self, event):
        if self._listbox is not None and self._listbox.winfo_ismapped() and self._listbox.size():
            self._listbox.focus_set()
            self._listbox.selection_clear(0, "end")
            self._listbox.selection_set(0)
            self._listbox.activate(0)
        return "break"

    # --- listbox ---------------------------------------------------
    def _show_listbox(self, matches: List[str]) -> None:
        if self._listbox is None:
            self._listbox = tk.Listbox(
                self.winfo_toplevel(),
                height=min(len(matches), 8),
                exportselection=False,
                activestyle="dotbox",
            )
            # ButtonRelease : la sélection est garantie d'être à jour à ce moment.
            self._listbox.bind("<ButtonRelease-1>", self._on_listbox_click)
            self._listbox.bind("<Return>", self._on_listbox_return)
        self._listbox.configure(height=min(len(matches), 8))
        self._listbox.delete(0, "end")
        for m in matches:
            self._listbox.insert("end", m)
        # Positionne la listbox sous l'Entry, au niveau du toplevel.
        top = self.winfo_toplevel()
        x = self.winfo_rootx() - top.winfo_rootx()
        y = self.winfo_rooty() - top.winfo_rooty() + self.winfo_height()
        self._listbox.place(x=x, y=y, width=max(self.winfo_width(), 280))
        self._listbox.lift()

    def _hide_listbox(self) -> None:
        if self._listbox is not None:
            self._listbox.place_forget()

    def _select_index(self, idx: int) -> None:
        if self._listbox is None:
            return
        try:
            value = self._listbox.get(idx)
        except tk.TclError:
            return
        if not value:
            return
        self.delete(0, "end")
        self.insert(0, value)
        self._hide_listbox()
        self.icursor("end")
        self.focus_set()

    def _on_listbox_click(self, event):
        if self._listbox is None:
            return
        idx = self._listbox.nearest(event.y)
        if idx < 0:
            return
        self._select_index(idx)

    def _on_listbox_return(self, event):
        if self._listbox is None:
            return
        cur = self._listbox.curselection()
        idx = cur[0] if cur else 0
        self._select_index(idx)


# =============================================================================
# 4. POINT D'ENTRÉE
# =============================================================================

def main() -> None:
    MaxJeuneApp().mainloop()


if __name__ == "__main__":
    main()
