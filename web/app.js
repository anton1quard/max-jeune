// MAX Jeune — interface web (mobile d'abord). La logique de recherche est dans engine.js.
import {
  Engine, MaxDay, TerDay, runSearch, completeWithTer, allResults, daySummary, dayLabel, normalize,
} from "./engine.js";

const BUILD = "__BUILD__";          // remplacé au déploiement (identifiant du commit)
const DATA = "./data/";
const $ = (id) => document.getElementById(id);

const state = {
  meta: null, E: null, entries: [],
  maxDays: new Map(), terDays: new Map(),
  last: null, filter: "all", sort: "dep", busy: false,
};

// ---------------------------------------------------------------------------
// Affichage des noms de gares : "MARNE LA VALLEE CHESSY" -> "Marne La Vallee Chessy"
// ---------------------------------------------------------------------------
const KEEP_UPPER = new Set(["MAX", "TER", "TGV", "CDG", "SNCF", "HBF", "ET", "OUI", "II", "IC"]);
const prettyWord = (w) => (KEEP_UPPER.has(w) ? w : w.charAt(0) + w.slice(1).toLowerCase());
export function pretty(s) {
  return s.replace(/[A-Z][A-Z0-9'\-]*/g, (w) => w.split("-").map(prettyWord).join("-"));
}
/** Dans un texte libre, ne réécrit que les suites de mots en capitales (noms de gares). */
const prettyText = (s) => s.replace(/\b[A-Z][A-Z0-9'\-]+(?: [A-Z0-9][A-Z0-9'\-]*)*\b/g, (m) => pretty(m));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------------------------------------------------------------------------
// Chargement des données (le service worker gère le cache hors ligne)
// ---------------------------------------------------------------------------
async function getJSON(path) {
  const r = await fetch(DATA + path);
  if (!r.ok) throw new Error(`${path} : HTTP ${r.status}`);
  return r.json();
}
async function maxDay(date) {
  if (!state.maxDays.has(date)) state.maxDays.set(date, new MaxDay(await getJSON(`max/${date}.json`)));
  return state.maxDays.get(date);
}
async function terDay(date) {
  if (!state.terDays.has(date)) {
    state.terDays.set(date, new TerDay(await getJSON(`ter/${date}.json`), state.meta.config.TER_SEARCH_WINDOW_MIN));
  }
  return state.terDays.get(date);
}

// ---------------------------------------------------------------------------
// Préférences (mémorisées sur l'appareil)
// ---------------------------------------------------------------------------
const PREF_KEY = "maxjeune.prefs.v1";
const OPTS = { ext: "opt-ext", boarding: "opt-boarding", two: "opt-two", ter: "opt-ter", forceTer: "opt-force-ter" };
function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREF_KEY)) || {}; } catch { return {}; }
}
function savePrefs() {
  const p = { dep: $("dep").value, arr: $("arr").value, hmin: $("hmin").value, amaxOn: $("amax-on").checked,
    amax: $("amax").value, sort: state.sort };
  for (const [k, id] of Object.entries(OPTS)) p[k] = $(id).checked;
  try { localStorage.setItem(PREF_KEY, JSON.stringify(p)); } catch { /* stockage indisponible */ }
}

// ---------------------------------------------------------------------------
// Autocomplétion
// ---------------------------------------------------------------------------
function setupAutocomplete(input, list) {
  let items = [], active = -1;
  const close = () => { list.hidden = true; active = -1; };
  const choose = (i) => { input.value = items[i].label; close(); input.dispatchEvent(new Event("change")); };
  const render = () => {
    list.innerHTML = items.map((it, i) => `<li role="option" data-i="${i}" aria-selected="${i === active}">`
      + `<span>${esc(it.hub ? it.label : pretty(it.label))}</span>`
      + (it.hub ? `<span class="tag">${it.ext ? "Hub étendu" : "Hub"}</span>` : "") + "</li>").join("");
    list.hidden = items.length === 0;
  };
  input.addEventListener("input", () => {
    const n = normalize(input.value);
    if (!n) { items = []; return close(); }
    const starts = [], contains = [];
    for (const e of state.entries) {
      if (e.norm.startsWith(n)) starts.push(e);
      else if (e.norm.includes(n)) contains.push(e);
    }
    const byHub = (a, b) => (b.hub - a.hub) || (a.norm.length - b.norm.length);
    items = [...starts.sort(byHub), ...contains.sort(byHub)].slice(0, 8);
    active = -1;
    render();
  });
  input.addEventListener("keydown", (ev) => {
    if (list.hidden) return;
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      active = (active + (ev.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
      render();
    } else if (ev.key === "Enter" && items.length) {
      ev.preventDefault();
      choose(active >= 0 ? active : 0);
    } else if (ev.key === "Escape") close();
  });
  list.addEventListener("pointerdown", (ev) => {
    const li = ev.target.closest("li");
    if (li) { ev.preventDefault(); choose(Number(li.dataset.i)); }
  });
  input.addEventListener("blur", () => setTimeout(close, 150));
}

// ---------------------------------------------------------------------------
// Recherche
// ---------------------------------------------------------------------------
function buildQuery(dateOverride) {
  const E = state.E;
  const ext = $("opt-ext").checked;
  const dep = E.resolveLocation($("dep").value, ext);
  const arr = E.resolveLocation($("arr").value, ext);
  if (!dep) throw new Error($("dep").value.trim() ? "Gare de départ inconnue." : "Indiquez une gare de départ.");
  if (!arr) throw new Error($("arr").value.trim() ? "Gare d'arrivée inconnue." : "Indiquez une gare d'arrivée.");
  const date = dateOverride || $("date").value;
  if (!state.meta.dates.includes(date)) {
    throw new Error(`Pas de données MAX pour cette date (disponibles du ${dayLabel(state.meta.dates[0])} `
      + `au ${dayLabel(state.meta.dates.at(-1))}).`);
  }
  return {
    q: { date, depCands: dep.candidates, arrCands: arr.candidates, heureMin: $("hmin").value || "00:00",
      arriveeMax: $("amax-on").checked ? $("amax").value : null,
      allowBoarding: $("opt-boarding").checked, allowTwoSegments: $("opt-two").checked,
      allowTer: $("opt-ter").checked, forceTer: $("opt-force-ter").checked },
    depLabel: dep.display, arrLabel: arr.display,
  };
}

async function search(date) {
  const { q, depLabel, arrLabel } = buildQuery(date);
  const day = await maxDay(q.date);
  const out = runSearch(state.E, day, q);
  if (out.needsTer) {
    try { completeWithTer(state.E, day, await terDay(q.date), q, out); } catch (e) { out.terError = e.message; }
  }
  return { out, q, depLabel, arrLabel };
}

const closeSuggest = () => { $("dep-suggest").hidden = true; $("arr-suggest").hidden = true; };

async function doSearch() {
  closeSuggest();
  if (state.busy || !state.E) return;
  showTab("results");
  let res;
  try {
    state.busy = true;
    $("go").disabled = true;
    $("results").innerHTML = '<div class="spinner" aria-label="Recherche…"></div>';
    res = await search();
  } catch (e) {
    $("results").innerHTML = `<div class="empty"><p class="big">Oups</p><p>${esc(e.message)}</p></div>`;
    $("summary").hidden = $("toolbar").hidden = true;
    return;
  } finally {
    state.busy = false;
    $("go").disabled = false;
  }
  state.last = res;
  state.filter = "all";
  savePrefs();
  history.replaceState(null, "", "#" + new URLSearchParams({ dep: $("dep").value, arr: $("arr").value,
    date: res.q.date, h: $("hmin").value }).toString());
  renderResults();
  $("view-results").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------------------
// Rendu des résultats
// ---------------------------------------------------------------------------
const GROUPS = [
  ["A", "Direct", "MAX direct"],
  ["B", "Montée en cours", "Montée / descente en cours"],
  ["C", "2 segments", "2 segments MAX"],
  ["D", "MAX + TER", "MAX + TER"],
];

function card(r) {
  const [main, via] = r.itineraire.split(" (via ");
  const arr = r.arrivee.replace(" (+1j)", "<small>+1j</small>");
  const trains = r.trainNo.includes("+") ? `Trains ${r.trainNo.replace(/\+/g, " + ")}` : `Train ${r.trainNo}`;
  const tickets = r.odMax.split(" | ");
  const ticketLbl = r.group === "D" ? "Billet MAX à réserver · TER en plus"
    : tickets.length > 1 ? "2 billets MAX à réserver" : "Billet MAX à réserver";
  return `<article class="card g-${r.group}">
    <div class="times"><span class="t">${esc(r.depart)}</span><span class="rail"></span>
      <span class="t">${arr}</span><span class="dur">${r.duree}</span></div>
    <div class="route">${esc(pretty(main))}${via ? ` <span class="via">via ${esc(pretty(via.replace(/\)$/, "")))}</span>` : ""}</div>
    <div class="meta"><span class="badge">${esc(r.type)}</span><span>${esc(trains)}</span></div>
    ${r.group === "A" ? "" : `<div class="ticket"><span class="k">${ticketLbl}</span>${tickets.map((t) => `<b>${esc(pretty(t))}</b>`).join("<br>")}</div>`}
    <details><summary>Détails</summary><p>${esc(prettyText(r.commentaire))}</p></details>
  </article>`;
}

function renderResults() {
  const { out, q, depLabel, arrLabel } = state.last;
  const byGroup = { A: out.direct, B: out.boarding, C: out.twoSegments, D: out.maxTer };
  const all = allResults(out);
  const sortKey = { dep: (r) => [r.dep, r.arr], arr: (r) => [r.arr, r.dep], dur: (r) => [r.minutes, r.dep] }[state.sort];
  const sorted = (lst) => [...lst].sort((a, b) => {
    const ka = sortKey(a), kb = sortKey(b);
    return ka[0] - kb[0] || ka[1] - kb[1];
  });

  $("summary").hidden = false;
  $("summary").innerHTML = `<b>${esc(pretty(depLabel))} → ${esc(pretty(arrLabel))}</b> · ${dayLabel(q.date)}`
    + ` · ${all.length} solution${all.length > 1 ? "s" : ""}`;

  if (!all.length) {
    $("toolbar").hidden = true;
    const ter = out.terError ? `<p>Horaires TER indisponibles : ${esc(out.terError)}</p>` : "";
    $("results").innerHTML = `<div class="empty"><p class="big">Aucune solution ce jour-là</p>
      <p>Essayez une autre date (onglet <b>Calendrier 30 jours</b>), un horaire plus tôt, ou les hubs étendus.</p>${ter}</div>`;
    return;
  }
  $("toolbar").hidden = false;
  $("sort").value = state.sort;
  const chips = [["all", "Tous", all.length], ...GROUPS.filter(([g]) => byGroup[g].length).map(([g, s]) => [g, s, byGroup[g].length])];
  $("chips").innerHTML = chips.map(([k, lbl, n]) =>
    `<button type="button" class="chip" data-f="${k}" aria-pressed="${state.filter === k}">${lbl}<span class="n">${n}</span></button>`).join("");

  let html = "";
  if (state.filter === "all") {
    for (const [g, , title] of GROUPS) {
      if (!byGroup[g].length) continue;
      html += `<h2 class="group-title g-${g}">${title} · ${byGroup[g].length}</h2>` + sorted(byGroup[g]).map(card).join("");
    }
  } else {
    html = sorted(byGroup[state.filter]).map(card).join("");
  }
  $("results").innerHTML = html;
}

// ---------------------------------------------------------------------------
// Calendrier (balayage multi-jours)
// ---------------------------------------------------------------------------
async function doScan() {
  if (state.busy) return;
  let base;
  try { base = buildQuery(); } catch (e) { toast(e.message); return; }
  const start = Date.parse(base.q.date);
  const days = state.meta.dates.filter((d) => {
    const diff = (Date.parse(d) - start) / 86400000;
    return diff >= 0 && diff < state.meta.config.SCAN_DEFAULT_DAYS;
  });
  state.busy = true;
  $("scan-go").disabled = true;
  const bar = $("scan-progress");
  bar.hidden = false;
  const rows = [];
  try {
    for (let i = 0; i < days.length; i++) {
      const res = await search(days[i]);
      rows.push(daySummary(days[i], res.out));
      bar.firstElementChild.style.width = `${Math.round(((i + 1) / days.length) * 100)}%`;
    }
  } catch (e) {
    toast(e.message);
  } finally {
    state.busy = false;
    $("scan-go").disabled = false;
    setTimeout(() => { bar.hidden = true; bar.firstElementChild.style.width = "0"; }, 400);
  }
  const maxTot = Math.max(1, ...rows.map((r) => r.total));
  $("scan-list").innerHTML = rows.map((r) => {
    const seg = (n, g) => (n ? `<i style="width:${(n / maxTot) * 100}%;background:var(--${g})"></i>` : "");
    const deps = r.firstDep === r.lastDep ? `départ ${r.firstDep}` : `départs de ${r.firstDep} à ${r.lastDep}`;
    const info = r.total ? `${deps} · plus rapide ${r.fastest}` : "aucune solution";
    const [wd, dm] = dayLabel(r.date).split(" ");
    return `<button type="button" class="day${r.total ? "" : " zero"}" data-date="${r.date}">
      <span class="d">${dm}<small>${wd}</small></span>
      <span><span class="bars">${seg(r.nDirect, "A")}${seg(r.nBoarding, "B")}${seg(r.nTwo, "C")}${seg(r.nTer, "D")}</span>
        <span class="info">${info}</span></span>
      <span class="tot">${r.total}</span></button>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// Divers : onglets, signalement, notifications, service worker
// ---------------------------------------------------------------------------
function showTab(name) {
  closeSuggest();
  const res = name === "results";
  $("tab-results").setAttribute("aria-selected", res);
  $("tab-scan").setAttribute("aria-selected", !res);
  $("view-results").hidden = !res;
  $("view-scan").hidden = res;
}

let toastTimer;
function toast(msg, action) {
  const t = $("toast");
  t.innerHTML = `<span>${esc(msg)}</span>` + (action ? `<button type="button">${esc(action.label)}</button>` : "");
  if (action) t.querySelector("button").onclick = action.run;
  t.hidden = false;
  clearTimeout(toastTimer);
  if (!action) toastTimer = setTimeout(() => { t.hidden = true; }, 4000);
}

function report() {
  const m = state.meta;
  const lines = [
    "**Ce qui ne va pas :**", "", "", "**Ce que j'attendais :**", "", "", "---",
    `Recherche : ${location.href}`,
    state.last ? `Résumé : ${state.last.depLabel} → ${state.last.arrLabel}, ${state.last.q.date}, `
      + `${allResults(state.last.out).length} résultat(s)` : "Aucune recherche lancée",
    `Données : ${m ? m.generated_at : "?"} · GTFS ${m ? m.gtfs_version : "?"} · version ${BUILD}`,
    `Appareil : ${navigator.userAgent}`,
  ];
  const body = lines.join("\n");
  const title = state.last ? `Problème : ${state.last.depLabel} → ${state.last.arrLabel} (${state.last.q.date})` : "Problème";
  if (location.hostname.endsWith(".github.io")) {
    const owner = location.hostname.split(".")[0];
    const repo = location.pathname.split("/").filter(Boolean)[0] || `${owner}.github.io`;
    window.open(`https://github.com/${owner}/${repo}/issues/new?${new URLSearchParams({ title, body })}`, "_blank", "noopener");
  } else if (navigator.clipboard) {
    navigator.clipboard.writeText(`${title}\n\n${body}`).then(() => toast("Détails copiés : collez-les dans votre message."));
  }
}

function registerSW() {
  if (!("serviceWorker" in navigator) || location.protocol === "file:") return;
  navigator.serviceWorker.register("sw.js").then((reg) => {
    const ask = (w) => toast("Nouvelle version disponible", { label: "Mettre à jour", run: () => w.postMessage("skipWaiting") });
    if (reg.waiting && navigator.serviceWorker.controller) ask(reg.waiting);
    reg.addEventListener("updatefound", () => {
      const w = reg.installing;
      w.addEventListener("statechange", () => {
        if (w.state === "installed" && navigator.serviceWorker.controller) ask(w);
      });
    });
  }).catch(() => { /* pas de mode hors ligne, sans gravité */ });
  let reloaded = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!reloaded) { reloaded = true; location.reload(); }
  });
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// Démarrage
// ---------------------------------------------------------------------------
async function init() {
  registerSW();
  $("version").textContent = `Version ${BUILD}`;
  const prefs = loadPrefs();
  for (const [k, id] of Object.entries(OPTS)) if (k in prefs) $(id).checked = prefs[k];
  if (prefs.dep) $("dep").value = prefs.dep;
  if (prefs.arr) $("arr").value = prefs.arr;
  if (prefs.hmin) $("hmin").value = prefs.hmin;
  if (prefs.amax) $("amax").value = prefs.amax;
  $("amax-on").checked = !!prefs.amaxOn;
  $("amax").disabled = !$("amax-on").checked;
  if (prefs.sort) state.sort = prefs.sort;

  setupAutocomplete($("dep"), $("dep-suggest"));
  setupAutocomplete($("arr"), $("arr-suggest"));
  $("search").addEventListener("submit", (ev) => { ev.preventDefault(); doSearch(); });
  $("swap").addEventListener("click", () => { [$("dep").value, $("arr").value] = [$("arr").value, $("dep").value]; });
  $("amax-on").addEventListener("change", () => { $("amax").disabled = !$("amax-on").checked; });
  $("tab-results").addEventListener("click", () => showTab("results"));
  $("tab-scan").addEventListener("click", () => showTab("scan"));
  $("scan-go").addEventListener("click", doScan);
  $("scan-list").addEventListener("click", (ev) => {
    const b = ev.target.closest(".day");
    if (b) { $("date").value = b.dataset.date; doSearch(); }
  });
  $("chips").addEventListener("click", (ev) => {
    const c = ev.target.closest(".chip");
    if (c) { state.filter = c.dataset.f; renderResults(); }
  });
  $("sort").addEventListener("change", () => { state.sort = $("sort").value; savePrefs(); renderResults(); });
  $("report").addEventListener("click", report);

  try {
    state.meta = await getJSON("meta.json");
  } catch (e) {
    $("freshness").textContent = "Données indisponibles (hors ligne ?)";
    $("results").innerHTML = `<div class="empty"><p class="big">Impossible de charger les données</p><p>${esc(e.message)}</p></div>`;
    return;
  }
  const m = state.meta;
  state.E = new Engine(m);
  state.entries = state.E.autocompleteEntries().map((label) => ({
    label, norm: normalize(label), hub: label.endsWith("(HUB)") || label.endsWith("(HUB ETENDU)"),
    ext: label.endsWith("(HUB ETENDU)"),
  }));
  const gen = new Date(m.generated_at);
  $("freshness").textContent = `Places MAX mises à jour le ${gen.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })}`
    + ` à ${gen.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}`;
  // La SNCF publie vers 6 h 30 : après 8 h, des données de la veille sont en retard.
  const parisDay = (d) => d.toLocaleDateString("sv-SE", { timeZone: "Europe/Paris" });
  const parisHour = Number(new Date().toLocaleString("en-GB", { timeZone: "Europe/Paris", hour: "2-digit", hour12: false }));
  if (parisDay(gen) < parisDay(new Date()) && parisHour >= 8) {
    $("freshness").textContent += " · ⚠ pas encore les places du jour";
  }
  const dateInput = $("date");
  dateInput.min = m.dates[0];
  dateInput.max = m.dates.at(-1);
  const today = todayISO();
  dateInput.value = m.dates.includes(today) ? today : m.dates.find((d) => d >= today) || m.dates[0];

  // Recherche partagée par lien (#dep=…&arr=…&date=…)
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.get("dep") && h.get("arr")) {
    $("dep").value = h.get("dep");
    $("arr").value = h.get("arr");
    if (h.get("date") && m.dates.includes(h.get("date"))) dateInput.value = h.get("date");
    if (h.get("h")) $("hmin").value = h.get("h");
    doSearch();
  }
}

init();
