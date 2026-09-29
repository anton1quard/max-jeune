/*
 * MAX Jeune — moteur de recherche (version JavaScript du site web)
 *
 * Portage fidèle de max_jeune_engine.py : mêmes règles, même ordre des
 * résultats, mêmes textes. Toute évolution se fait d'abord en Python, puis
 * ici ; les tests "golden" (web/tests) vérifient que les deux moteurs
 * donnent exactement les mêmes résultats sur les données réelles du jour.
 *
 * Les heures sont des minutes depuis minuit du jour recherché (un trajet
 * qui passe minuit dépasse 1440).
 *
 * Fonctionne dans le navigateur et sous Node (module ES, sans dépendance).
 */

// ---------------------------------------------------------------------------
// Utilitaires
// ---------------------------------------------------------------------------

const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

/** Compare deux tuples (tableaux) élément par élément, comme Python. */
export function cmpTuple(a, b) {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    const c = cmp(a[i], b[i]);
    if (c) return c;
  }
  return a.length - b.length;
}

const sortBy = (arr, keyFn) => {
  const keyed = arr.map((v, i) => [keyFn(v), i, v]);
  keyed.sort((x, y) => cmpTuple(x[0], y[0]) || x[1] - y[1]);
  return keyed.map((x) => x[2]);
};

export function hhmm(min) {
  const m = ((min % 1440) + 1440) % 1440;
  return String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");
}

const cap = (s) => s.slice(0, 1).toUpperCase() + s.slice(1);

export function normalize(text) {
  if (text === null || text === undefined) return "";
  let t = String(text).normalize("NFKD").replace(/\p{M}/gu, "").toUpperCase();
  t = t.replace(/[^A-Z0-9\-\s]/g, " ");
  return t.replace(/\s+/g, " ").trim();
}

export function minutesOf(s) {
  if (!s) return null;
  const m = /^\s*(\d{1,2}):(\d{2})/.exec(s);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

// ---------------------------------------------------------------------------
// Configuration (exportée par le pipeline depuis le moteur Python)
// ---------------------------------------------------------------------------

export const HUB_SUFFIX = " (HUB)";
export const HUB_EXT_SUFFIX = " (HUB ETENDU)";

export class Engine {
  constructor(meta) {
    this.meta = meta;
    const c = meta.config;
    this.c = c;
    this.hubs = c.HUBS;
    this.known = new Set(meta.stations);
    this.hubSiblings = new Map();
    this.stationToHub = new Map();
    for (const h of c.CONNECTION_HUBS) {
      for (const s of c.HUBS[h]) {
        this.hubSiblings.set(s, new Set(c.HUBS[h]));
        this.stationToHub.set(s, h);
      }
    }
  }

  // --- saisie utilisateur ---------------------------------------------------
  autocompleteEntries() {
    const items = new Set(this.known);
    for (const name of Object.keys(this.hubs)) {
      if (name.endsWith(" ETENDU")) items.add(name.slice(0, -" ETENDU".length) + HUB_EXT_SUFFIX);
      else items.add(name + HUB_SUFFIX);
    }
    return [...items].sort(cmp);
  }

  _hubLocation(base, extended) {
    const ext = this.c.HUB_EXTENDED_MAP;
    if (extended && base in ext)
      return { display: base + HUB_EXT_SUFFIX, candidates: new Set(this.hubs[ext[base]]), isHub: true };
    return { display: base + HUB_SUFFIX, candidates: new Set(this.hubs[base]), isHub: true };
  }

  resolveLocation(userText, includeExtended = false) {
    if (!userText || !userText.trim()) return null;
    const raw = userText.trim();
    const up = raw.toUpperCase();
    if (up.endsWith(HUB_EXT_SUFFIX)) {
      const base = normalize(raw.slice(0, -HUB_EXT_SUFFIX.length));
      if (base in this.c.HUB_EXTENDED_MAP) return this._hubLocation(base, true);
    }
    if (up.endsWith(HUB_SUFFIX)) {
      const base = normalize(raw.slice(0, -HUB_SUFFIX.length));
      if (base in this.hubs) return this._hubLocation(base, includeExtended);
    }
    let n = normalize(raw);
    if (n in this.hubs) return this._hubLocation(n, includeExtended);
    n = this.c.MANUAL_ALIASES[n] ?? n;
    if (this.known.has(n)) return { display: n, candidates: new Set([n]), isHub: false };
    let cands = [...this.known].filter((s) => s.startsWith(n));
    if (!cands.length) cands = [...this.known].filter((s) => s.includes(n));
    if (cands.length === 1) return { display: cands[0], candidates: new Set(cands), isHub: false };
    if (cands.length) return { display: `${n} (plusieurs gares)`, candidates: new Set(cands), isHub: false };
    return null;
  }

  _cityZone(cands) {
    const zone = new Set(cands);
    for (const [name, lst] of Object.entries(this.hubs)) {
      if (!name.endsWith(" ETENDU") && lst.some((s) => zone.has(s))) lst.forEach((s) => zone.add(s));
    }
    return zone;
  }

  _pivots(station) {
    const s = new Set(this.hubSiblings.get(station) ?? []);
    s.add(station);
    return [...s].sort(cmp);
  }
}

// ---------------------------------------------------------------------------
// Données d'une journée : billets MAX + circulations reconstituées
// ---------------------------------------------------------------------------

class TrainRun {
  constructor(train) {
    this.train = train;
    this.dep = new Map();
    this.arr = new Map();
    this.edges = new Map();
    this._reach = new Map();
  }
  addRow(o, d, tO, tD) {
    if (!this.edges.has(o)) this.edges.set(o, new Set());
    this.edges.get(o).add(d);
    if (!this.dep.has(o)) this.dep.set(o, tO);
    if (!this.arr.has(d)) this.arr.set(d, tD);
  }
  get stations() {
    return new Set([...this.dep.keys(), ...this.arr.keys()]);
  }
  reachable(s) {
    let r = this._reach.get(s);
    if (!r) {
      r = new Set();
      const stack = [...(this.edges.get(s) ?? [])];
      while (stack.length) {
        const n = stack.pop();
        if (!r.has(n)) {
          r.add(n);
          stack.push(...(this.edges.get(n) ?? []));
        }
      }
      this._reach.set(s, r);
    }
    return r;
  }
  timeKey(s) {
    return this.dep.has(s) ? this.dep.get(s) : this.arr.get(s);
  }
  stopsBetween(o, d) {
    const rO = this.reachable(o);
    const tO = this.timeKey(o), tD = this.timeKey(d);
    let mids = [...this.stations].filter((s) => s !== d && s !== o && this.reachable(s).has(d)
      && (rO.has(s) || (tO < this.timeKey(s) && this.timeKey(s) < tD)));
    mids = sortBy(mids, (s) => [this.timeKey(s), s]);
    return [o, ...mids, d];
  }
  boardingTime(s) {
    return this.dep.has(s) ? [this.dep.get(s), true] : [this.arr.get(s), false];
  }
  alightingTime(s) {
    return this.arr.has(s) ? [this.arr.get(s), true] : [this.dep.get(s), false];
  }
}

export class MaxDay {
  /** json = { date, stations: [...], rows: [[train, o, d, depMin, arrMin, oui], ...] } */
  constructor(json) {
    this.date = json.date;
    this.tickets = [];
    this.runs = new Map();
    const S = json.stations;
    for (const [train, oi, di, tD, tA, oui] of json.rows) {
      const o = S[oi], d = S[di];
      let run = this.runs.get(train);
      if (!run) this.runs.set(train, (run = new TrainRun(train)));
      run.addRow(o, d, tD, tA);
      if (oui) {
        this.tickets.push({ train, origine: o, destination: d, dep: tD, arr: tA,
          heureDepart: hhmm(tD), heureArrivee: hhmm(tA) });
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Réseau TER d'une journée (GTFS)
// ---------------------------------------------------------------------------

export class TerDay {
  /** json = { date, modes, stations, trips: [[mode, train, s, a, attente, f, ...], ...] } */
  constructor(json, windowMin) {
    this.window = windowMin;
    this.trips = json.trips.map((t) => {
      const stops = [];
      for (let i = 2; i < t.length; i += 4) {
        const a = t[i + 1];
        stops.push({ st: json.stations[t[i]], a, d: a + t[i + 2], board: !!(t[i + 3] & 1), alight: !!(t[i + 3] & 2) });
      }
      return { mode: json.modes[t[0]], train: t[1], stops };
    });
    this.depIdx = new Map();
    this.arrIdx = new Map();
    const push = (m, k, v) => { if (!m.has(k)) m.set(k, []); m.get(k).push(v); };
    this.trips.forEach((trip, ti) => {
      const n = trip.stops.length;
      trip.stops.forEach((s, pos) => {
        if (s.board && pos < n - 1) push(this.depIdx, s.st, [s.d, ti, pos]);
        if (s.alight && pos > 0) push(this.arrIdx, s.st, [s.a, ti, pos]);
      });
    });
    for (const m of [this.depIdx, this.arrIdx]) for (const l of m.values()) l.sort(cmpTuple);
    this.stations = new Set(json.stations);
  }

  _ride(ti, i, j) {
    const t = this.trips[ti];
    return { mode: t.mode, train: t.train, board: t.stops[i].st, alight: t.stops[j].st,
      dep: t.stops[i].d, arr: t.stops[j].a };
  }

  earliestArrival(from, toSet, notBefore) {
    const lst = this.depIdx.get(from) ?? [];
    const limit = notBefore + this.window;
    let best = null;
    let k = 0;
    while (k < lst.length && lst[k][0] < notBefore) k++;
    for (; k < lst.length; k++) {
      const [dt, ti, pos] = lst[k];
      if (dt > limit || (best && dt >= best.arr)) break;
      const stops = this.trips[ti].stops;
      for (let j = pos + 1; j < stops.length; j++) {
        if (toSet.has(stops[j].st) && stops[j].alight) {
          const ride = this._ride(ti, pos, j);
          if (!best || ride.arr < best.arr) best = ride;
          break;
        }
      }
    }
    return best;
  }

  latestDeparture(fromSet, to, notAfter) {
    const lst = this.arrIdx.get(to) ?? [];
    const limit = notAfter - this.window;
    let best = null;
    let k = lst.length;
    while (k > 0 && lst[k - 1][0] > notAfter) k--;
    for (let x = k - 1; x >= 0; x--) {
      const [dt, ti, pos] = lst[x];
      if (dt < limit || (best && dt <= best.dep)) break;
      const stops = this.trips[ti].stops;
      for (let i = pos - 1; i >= 0; i--) {
        if (fromSet.has(stops[i].st) && stops[i].board) {
          const ride = this._ride(ti, i, pos);
          if (!best || ride.dep > best.dep) best = ride;
          break;
        }
      }
    }
    return best;
  }
}

const terLabel = (r) => `${r.mode} ${r.train} ${r.board} ${hhmm(r.dep)} → ${r.alight} ${hhmm(r.arr)}`;

// ---------------------------------------------------------------------------
// Tronçons réservables
// ---------------------------------------------------------------------------

const od = (t) => `${t.origine} → ${t.destination}`;

function makeLeg(t, run, b, a) {
  let tb, eb, ta, ea;
  if (b === t.origine || !run) [tb, eb] = [t.dep, true];
  else [tb, eb] = run.boardingTime(b);
  if (a === t.destination || !run) [ta, ea] = [t.arr, true];
  else [ta, ea] = run.alightingTime(a);
  return { ticket: t, board: b, alight: a, tb, ta, eb, ea,
    isDirect: b === t.origine && a === t.destination, ticketMinutes: t.arr - t.dep };
}

export function findLegs(day, depCands, arrCands) {
  const legs = [];
  for (const t of day.tickets) {
    if (depCands && arrCands && depCands.has(t.origine) && arrCands.has(t.destination)) {
      legs.push(makeLeg(t, null, t.origine, t.destination));
      continue;
    }
    const run = day.runs.get(t.train);
    const stops = run ? run.stopsBetween(t.origine, t.destination) : [t.origine, t.destination];
    for (let i = 0; i < stops.length - 1; i++) {
      const b = stops[i];
      if (depCands && !depCands.has(b)) continue;
      for (let j = i + 1; j < stops.length; j++) {
        const a = stops[j];
        if (arrCands && !arrCands.has(a)) continue;
        legs.push(makeLeg(t, run, b, a));
        if (arrCands) break;
      }
    }
  }
  return legs;
}

function bestPerRide(legs) {
  const groups = new Map();
  for (const l of legs) {
    const k = `${l.ticket.train}\u0000${l.board}\u0000${l.alight}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(l);
  }
  const out = [];
  for (const ls of groups.values()) {
    const s = sortBy(ls, (l) => [l.isDirect ? 0 : 1, l.ticketMinutes, l.ticket.origine, l.ticket.destination]);
    out.push({ leg: s[0], others: s.slice(1) });
  }
  return out;
}

// ---------------------------------------------------------------------------
// Résultats
// ---------------------------------------------------------------------------

export const GROUP_LABELS = { A: "MAX DIRECT", B: "MONTÉE / DESCENTE EN COURS", C: "2 SEGMENTS MAX", D: "MAX + TER" };

function result(group, itineraire, dep, arr, trainNo, odMax, commentaire, date, exactDep = true, exactArr = true) {
  const minutes = arr - dep;
  let arrivee = hhmm(arr);
  if (Math.floor(arr / 1440) > Math.floor(dep / 1440)) arrivee += " (+1j)";
  return {
    group, type: GROUP_LABELS[group], itineraire, dep, arr, trainNo, odMax, commentaire, date,
    exactDep, exactArr, minutes,
    depart: (exactDep ? "" : "~") + hhmm(dep),
    arrivee: (exactArr ? "" : "~") + arrivee,
    duree: `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}`,
  };
}

const resultKey = (r) => [r.dep, r.arr, r.trainNo, r.itineraire];

function timeOk(tb, ta, q) {
  if (tb < (minutesOf(q.heureMin) ?? 0)) return false;
  const amax = minutesOf(q.arriveeMax);
  return !(amax !== null && ta > amax);
}

// ---------------------------------------------------------------------------
// Parties A et B
// ---------------------------------------------------------------------------

export function searchDirectAndBoarding(E, day, q) {
  const legs = findLegs(day, q.depCands, q.arrCands).filter((l) => timeOk(l.tb, l.ta, q));
  const rides = bestPerRide(legs);
  const direct = [];
  const byTrainB = new Map();
  for (const { leg, others } of rides) {
    if (leg.isDirect) {
      let comment = "Billet MAX direct.";
      if (others.length) comment += " Aussi couvert par les billets MAX : " + others.map((o) => od(o.ticket)).join(", ") + ".";
      direct.push(result("A", `${leg.board} → ${leg.alight}`, leg.tb, leg.ta, leg.ticket.train,
        od(leg.ticket), comment, q.date));
    } else {
      if (!byTrainB.has(leg.ticket.train)) byTrainB.set(leg.ticket.train, []);
      byTrainB.get(leg.ticket.train).push({ leg, others });
    }
  }
  const boarding = [];
  if (q.allowBoarding) {
    for (const opts of byTrainB.values()) {
      const options = sortBy(opts, (o) => [o.leg.ta, -o.leg.tb, o.leg.board, o.leg.alight]);
      const { leg, others } = options[0];
      const t = leg.ticket;
      const up = leg.board !== t.origine, down = leg.alight !== t.destination;
      const kase = up && down ? "monter ET descendre en cours de route"
        : up ? "monter en cours de route" : "descendre avant le terminus";
      const parts = [`${cap(kase)} : réserver le billet MAX ${od(t)} (${t.heureDepart}→${t.heureArrivee}).`];
      if (!(leg.eb && leg.ea)) parts.push("Heure ~ : heure d'arrivée en gare (arrêt de quelques minutes).");
      if (others.length) parts.push("Autres billets valables : " + others.map((o) => od(o.ticket)).join(", ") + ".");
      const alt = options.slice(1).map((o) => o.leg);
      if (alt.length) parts.push("Autre(s) montée(s) possible(s) : " + alt.map((a) => `${a.board} ${hhmm(a.tb)}`).join(", ") + ".");
      boarding.push(result("B", `${leg.board} → ${leg.alight}`, leg.tb, leg.ta, t.train, od(t),
        parts.join(" "), q.date, leg.eb, leg.ea));
    }
  }
  return [sortBy(direct, resultKey), sortBy(boarding, resultKey)];
}

// ---------------------------------------------------------------------------
// Partie C
// ---------------------------------------------------------------------------

function connectionKind(E, l1, l2, margin) {
  const c = E.c;
  if (margin < 0 || margin > c.MARGIN_CONNECTION_MAX) return null;
  const sameStation = l1.alight === l2.board;
  if (sameStation && l1.ticket.train === l2.ticket.train)
    return margin <= c.MARGIN_SAME_TRAIN_MAX ? "même train (2 billets)" : null;
  if (sameStation) return margin >= c.MARGIN_SAME_STATION_MIN ? "correspondance même gare" : null;
  if (margin >= c.MARGIN_HUB_MIN) return `changement de gare (hub ${E.stationToHub.get(l1.alight) ?? "?"})`;
  return null;
}

function dominanceFilter(items, depOf, arrOf, better) {
  const kept = [];
  let bestArr = null;
  for (const it of items) {
    if (bestArr !== null && arrOf(it) >= bestArr) continue;
    if (better.some((r) => r.dep >= depOf(it) && r.arr <= arrOf(it))) continue;
    kept.push(it);
    bestArr = arrOf(it);
  }
  return kept;
}

export function searchTwoSegments(E, day, q, better = []) {
  const hmin = minutesOf(q.heureMin) ?? 0;
  const first = findLegs(day, q.depCands, null).filter((l) => l.tb >= hmin && !q.arrCands.has(l.alight));
  const second = findLegs(day, null, q.arrCands).filter((l) => !q.depCands.has(l.board));
  const firstRides = bestPerRide(first).map((x) => x.leg);
  const byBoard = new Map();
  for (const { leg } of bestPerRide(second)) {
    if (!byBoard.has(leg.board)) byBoard.set(leg.board, []);
    byBoard.get(leg.board).push(leg);
  }
  let raw = [];
  for (const l1 of firstRides) {
    for (const pivot of E._pivots(l1.alight)) {
      for (const l2 of byBoard.get(pivot) ?? []) {
        if (l2.ticket === l1.ticket || l2.alight === l1.board) continue;
        const margin = l2.tb - l1.ta;
        const kind = connectionKind(E, l1, l2, margin);
        if (kind === null) continue;
        if (l2.ta - l1.tb > E.c.TWO_SEG_TOTAL_DURATION_MAX_MIN) continue;
        if (!timeOk(l1.tb, l2.ta, q)) continue;
        raw.push({ l1, l2, kind, margin });
      }
    }
  }
  raw = sortBy(raw, (x) => [-x.l1.tb, x.l2.ta, x.kind.includes("hub") ? 1 : 0, -x.margin,
    x.l1.alight, x.l2.board, x.l1.ticket.train, x.l2.ticket.train, x.l1.board, x.l2.alight]);
  const kept = dominanceFilter(raw, (x) => x.l1.tb, (x) => x.l2.ta, better);
  const seg = (l) => `${l.board} ${hhmm(l.tb)} → ${l.alight} ${hhmm(l.ta)} (train ${l.ticket.train}`
    + (l.isDirect ? "" : `, billet ${od(l.ticket)}`) + ")";
  const res = kept.map(({ l1, l2, kind, margin }) => {
    const via = l1.alight === l2.board ? l1.alight : `${l1.alight} → ${l2.board}`;
    return result("C", `${l1.board} → ${l2.alight} (via ${via})`, l1.tb, l2.ta,
      `${l1.ticket.train}+${l2.ticket.train}`, `${od(l1.ticket)} | ${od(l2.ticket)}`,
      `${cap(kind)}, ${Math.round(margin)} min. Seg1 : ${seg(l1)}. Seg2 : ${seg(l2)}.`,
      q.date, l1.eb, l2.ea);
  });
  return sortBy(res, resultKey);
}

// ---------------------------------------------------------------------------
// Partie D
// ---------------------------------------------------------------------------

export function searchMaxTer(E, day, ter, q, better = []) {
  const hmin = minutesOf(q.heureMin) ?? 0;
  const depZone = E._cityZone(q.depCands), arrZone = E._cityZone(q.arrCands);
  const margin = (a, b) => (a === b ? E.c.MARGIN_SAME_STATION_MIN : E.c.MARGIN_HUB_MIN);
  const maxTxt = (l) => {
    let s = `MAX ${l.ticket.train} ${l.board} ${hhmm(l.tb)} → ${l.alight} ${hhmm(l.ta)}`;
    if (!l.isDirect) s += ` (billet ${od(l.ticket)}, ${l.board !== l.ticket.origine ? "montée" : "descente"} en cours)`;
    return s;
  };
  let combos = [];
  const first = findLegs(day, q.depCands, null).filter((l) => l.tb >= hmin && !arrZone.has(l.alight));
  for (const { leg: l1 } of bestPerRide(first)) {
    for (const pivot of E._pivots(l1.alight)) {
      const r = ter.earliestArrival(pivot, q.arrCands, l1.ta + margin(l1.alight, pivot));
      if (!r) continue;
      combos.push({ dep: l1.tb, arr: r.arr, it: `${l1.board} → ${r.alight} (via ${pivot})`,
        tr: `${l1.ticket.train}+${r.mode} ${r.train}`, od: od(l1.ticket),
        com: `MAX puis TER : ${maxTxt(l1)}, puis ${terLabel(r)} (correspondance ${r.dep - l1.ta} min).`,
        ed: l1.eb, ea: true });
    }
  }
  const second = findLegs(day, null, q.arrCands).filter((l) => !depZone.has(l.board));
  for (const { leg: l2 } of bestPerRide(second)) {
    for (const pivot of E._pivots(l2.board)) {
      const r = ter.latestDeparture(q.depCands, pivot, l2.tb - margin(pivot, l2.board));
      if (!r || r.dep < hmin) continue;
      combos.push({ dep: r.dep, arr: l2.ta, it: `${r.board} → ${l2.alight} (via ${pivot})`,
        tr: `${r.mode} ${r.train}+${l2.ticket.train}`, od: od(l2.ticket),
        com: `TER puis MAX : ${terLabel(r)}, puis ${maxTxt(l2)} (correspondance ${l2.tb - r.arr} min).`,
        ed: true, ea: l2.ea });
    }
  }
  combos = combos.filter((c) => c.arr - c.dep <= E.c.TWO_SEG_TOTAL_DURATION_MAX_MIN && timeOk(c.dep, c.arr, q));
  combos = sortBy(combos, (c) => [-c.dep, c.arr, c.it, c.tr]);
  const kept = dominanceFilter(combos, (c) => c.dep, (c) => c.arr, better);
  const res = kept.map((c) => result("D", c.it, c.dep, c.arr, c.tr, c.od,
    c.com + " Horaire TER théorique (GTFS SNCF), billet TER payant à acheter à part.", q.date, c.ed, c.ea));
  return sortBy(res, resultKey);
}

// ---------------------------------------------------------------------------
// Point d'entrée
// ---------------------------------------------------------------------------

/**
 * q = { date, depCands:Set, arrCands:Set, heureMin, arriveeMax|null,
 *       allowBoarding, allowTwoSegments, allowTer, forceTer }
 * Renvoie { direct, boarding, twoSegments, maxTer, needsTer }.
 * Si needsTer est vrai, charger le TerDay puis appeler completeWithTer().
 */
export function runSearch(E, day, q) {
  const [direct, boarding] = searchDirectAndBoarding(E, day, q);
  const twoSegments = q.allowTwoSegments ? searchTwoSegments(E, day, q, [...direct, ...boarding]) : [];
  const out = { direct, boarding, twoSegments, maxTer: [] };
  const allMax = [...direct, ...boarding, ...twoSegments];
  out.needsTer = !!q.allowTer && (!!q.forceTer || allMax.length === 0);
  return out;
}

export function completeWithTer(E, day, ter, q, out) {
  if (out.needsTer && ter) {
    out.maxTer = searchMaxTer(E, day, ter, q, [...out.direct, ...out.boarding, ...out.twoSegments]);
  }
  return out;
}

export const allResults = (out) => [...out.direct, ...out.boarding, ...out.twoSegments, ...out.maxTer];

/** Résumé d'une journée pour le balayage (identique à DaySummary Python). */
export function daySummary(date, out) {
  const all = allResults(out);
  const key = (s) => s.replace(/^~+/, "");
  let first = "—", last = "—", fastest = "—";
  if (all.length) {
    first = all[0].depart; last = all[0].depart;
    let f = all[0];
    for (const r of all) {
      if (key(r.depart) < key(first)) first = r.depart;
      if (key(r.depart) > key(last)) last = r.depart;
      if (r.minutes < f.minutes) f = r;
    }
    fastest = f.duree;
  }
  return { date, nDirect: out.direct.length, nBoarding: out.boarding.length,
    nTwo: out.twoSegments.length, nTer: out.maxTer.length, firstDep: first, lastDep: last, fastest,
    total: all.length };
}

const JOURS = ["dim", "lun", "mar", "mer", "jeu", "ven", "sam"];
export function dayLabel(date) {
  const [y, m, d] = date.split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${JOURS[wd]} ${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}`;
}
