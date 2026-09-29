// Test de fidélité : le moteur JS doit reproduire exactement le moteur Python.
// Usage : node web/tests/golden.test.mjs <dossier data> <golden.json>
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  Engine, MaxDay, TerDay, runSearch, completeWithTer, allResults, daySummary, dayLabel,
} from "../engine.js";

const [dataDir, goldenPath] = process.argv.slice(2);
if (!dataDir || !goldenPath) {
  console.error("Usage : node golden.test.mjs <dossier data> <golden.json>");
  process.exit(2);
}
const load = (p) => JSON.parse(readFileSync(p, "utf-8"));
const meta = load(join(dataDir, "meta.json"));
const golden = load(goldenPath);
const E = new Engine(meta);

const maxCache = new Map(), terCache = new Map();
const maxDay = (d) => maxCache.get(d) ?? maxCache.set(d, new MaxDay(load(join(dataDir, "max", `${d}.json`)))).get(d);
const terDay = (d) => terCache.get(d)
  ?? terCache.set(d, new TerDay(load(join(dataDir, "ter", `${d}.json`)), meta.config.TER_SEARCH_WINDOW_MIN)).get(d);

function search(dep, arr, date, extended, opts) {
  const dl = E.resolveLocation(dep, extended), al = E.resolveLocation(arr, extended);
  const q = {
    date, depCands: dl.candidates, arrCands: al.candidates,
    heureMin: opts.heure_min ?? "00:00", arriveeMax: opts.arrivee_max ?? null,
    allowBoarding: opts.allow_boarding ?? true, allowTwoSegments: opts.allow_two_segments ?? true,
    allowTer: opts.allow_ter ?? true, forceTer: opts.force_ter ?? false,
  };
  const day = maxDay(date);
  const out = runSearch(E, day, q);
  if (out.needsTer) completeWithTer(E, day, terDay(date), q, out);
  return out;
}

let failures = 0;
const fail = (msg) => { failures++; if (failures <= 15) console.error("✗ " + msg); };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// 1. Résolution des saisies
for (const r of golden.resolves) {
  const loc = E.resolveLocation(r.text, r.extended);
  const got = loc === null ? null : { display: loc.display, candidates: [...loc.candidates].sort() };
  if (!same(got, r.result)) fail(`resolve(${JSON.stringify(r.text)}, ext=${r.extended}) : ${JSON.stringify(got)} ≠ ${JSON.stringify(r.result)}`);
}
if (E.autocompleteEntries().length !== golden.autocomplete_count) fail("nombre d'entrées d'autocomplétion");
for (const [d, lbl] of Object.entries(golden.labels)) if (dayLabel(d) !== lbl) fail(`dayLabel(${d})`);

// 2. Recherches
let nRes = 0;
for (const c of golden.cases) {
  const out = search(c.dep, c.arr, c.date, c.extended, c.opts);
  const got = allResults(out).map((r) => ({ group: r.group, itineraire: r.itineraire, depart: r.depart,
    arrivee: r.arrivee, duree: r.duree, train_no: r.trainNo, od_max: r.odMax, commentaire: r.commentaire }));
  nRes += c.results.length;
  if (!same(got, c.results)) {
    const i = got.findIndex((g, k) => !same(g, c.results[k]));
    fail(`${c.dep} → ${c.arr} ${c.date} ${JSON.stringify(c.opts)} ext=${c.extended} : `
      + `${got.length} vs ${c.results.length} résultats ; 1re différence #${i}\n    JS : ${JSON.stringify(got[i])}\n    PY : ${JSON.stringify(c.results[i])}`);
  }
}

// 3. Balayages
for (const s of golden.scans) {
  const start = s.start;
  const days = meta.dates.filter((d) => {
    const diff = (Date.parse(d) - Date.parse(start)) / 86400000;
    return diff >= 0 && diff < s.n_days;
  });
  const got = days.map((d) => {
    const x = daySummary(d, search(s.dep, s.arr, d, false, {}));
    return { date: x.date, n_direct: x.nDirect, n_boarding: x.nBoarding, n_two: x.nTwo, n_ter: x.nTer,
      first_dep: x.firstDep, last_dep: x.lastDep, fastest: x.fastest };
  });
  if (!same(got, s.days)) fail(`balayage ${s.dep} → ${s.arr}`);
}

const total = golden.cases.length + golden.scans.length + golden.resolves.length;
if (failures) {
  console.error(`\n${failures} écart(s) sur ${total} vérifications.`);
  process.exit(1);
}
console.log(`OK : ${golden.cases.length} recherches (${nRes} résultats), ${golden.scans.length} balayages, `
  + `${golden.resolves.length} résolutions — moteur JS identique au moteur Python.`);
