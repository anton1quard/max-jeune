# Contexte pour Claude — projet MAX Jeune

Moteur de recherche de trajets MAX Jeune (billets SNCF à 0 €), à partir des
données ouvertes SNCF. L'utilisateur communique en français : répondre en
français, de façon concise. Il n'est pas développeur : expliquer simplement
les manipulations (GitHub Desktop, onglet Actions…).

Site en ligne : https://anton1quard.github.io/max-jeune/ (GitHub Pages,
dépôt public anton1quard/max-jeune). Détails d'usage : voir README.md.

## Architecture

- `max_jeune_engine.py` — moteur de référence (Python, bibliothèque standard).
- `web/engine.js` — portage JavaScript fidèle du moteur, utilisé par le site.
- `max_jeune.py` — appli de bureau Tkinter (tests sur PC).
- `pipeline/build_data.py` — CSV TGVMax + GTFS SNCF → JSON par jour
  (`meta.json`, `max/AAAA-MM-JJ.json`, `ter/AAAA-MM-JJ.json`) ;
  `pipeline/check_changed.py` — ne republier que si les données ont changé ;
  `pipeline/preview.py` — aperçu local.
- `web/` — PWA mobile (index.html, app.js, style.css, sw.js, manifest, icônes).
- `tests/test_engine.py` — tests Python (pytest, CSV + GTFS synthétiques).
- `web/tests/` — test de fidélité : `make_golden.py` (Python) produit ~700
  recherches de référence sur les données réelles, `golden.test.mjs` vérifie
  que le moteur JS donne exactement les mêmes résultats.
- `.github/workflows/deploy.yml` — vérification horaire (cron "7 3-21 * * *"),
  tests, test de fidélité, publication Pages si les données ont changé.

## Fonctionnalités du moteur (spécification validée avec l'utilisateur)

- A. MAX direct : billet OUI dont l'OD officielle correspond au trajet.
- B. Montée / descente en cours : billet OUI plus long sur le même train.
  Les arrêts et horaires réels sont reconstitués depuis TOUTES les lignes du
  CSV (OUI + NON) ; garde-fou « trains qui se séparent » par atteignabilité
  dans le graphe des lignes du train. Pas de patterns manuels (l'Excel des
  axes n'est plus utilisé). Masqué seulement si un billet direct existe pour
  la même paire de gares sur le même train.
- C. 2 segments MAX : marges 0–60 min même train, ≥ 10 min même gare,
  ≥ 60 min changement de gare dans un hub (Paris, Lyon) ; plafond 4 h de
  correspondance, 10 h au total ; filtre de dominance (on écarte une solution
  si une autre part au moins aussi tard et arrive au moins aussi tôt).
- D. MAX + TER (GTFS SNCF : TER, car TER, tram-train, Intercités), dans les
  deux sens (MAX puis TER, TER puis MAX), un seul TER direct ; seulement si
  aucune solution 100 % MAX, sauf option « toujours ». Pas de MAX + TER si le
  MAX arrive déjà dans la ville/hub visé.
- Hubs : PARIS (10 gares), LYON (3), LYON ETENDU (15), MARSEILLE
  (St Charles), MARSEILLE ETENDU (+ Aix TGV). L'option « hubs étendus »
  s'applique au départ ET à l'arrivée (demande de l'utilisateur).
- Balayage multi-jours (30 jours) : onglet séparé, lancé à la demande.
- Mode aller-retour : volontairement NON implémenté (choix de l'utilisateur).

## Règles de travail (importantes)

1. Toute modification du moteur se fait dans les DEUX moteurs
   (`max_jeune_engine.py` puis `web/engine.js`), puis :
   `python -m pytest tests` et
   `python pipeline/build_data.py --out _site/data` +
   `python web/tests/make_golden.py --out /tmp/golden.json` +
   `node web/tests/golden.test.mjs _site/data /tmp/golden.json`.
   L'ordre des résultats doit rester déterministe (tris avec départage explicite).
2. Ne jamais faire de commit ni de push : l'utilisateur les fait lui-même
   dans GitHub Desktop (Commit → Push origin).
3. Commandes git en lecture seule uniquement, avec `GIT_OPTIONAL_LOCKS=0`
   (un `git status` ordinaire a déjà laissé un `.git/index.lock` bloquant).
4. Ne jamais versionner les données (`*.csv`, `*.zip`, `*.xlsx` sont dans
   `.gitignore`). `tgvmax_cache.csv` et `Export_OpenData_SNCF_GTFS_NewTripId.zip`
   sont présents localement pour les tests.
5. Toute évolution du site : bumper rien à la main, `__BUILD__` est remplacé
   par le SHA du commit au déploiement (déclenche « Nouvelle version » sur
   l'iPhone).

## Pistes ouvertes / idées non faites

- Hubs supplémentaires (Montpellier, Bordeaux, Lille…) si besoin.
- MAX + TER avec changement TER-TER (actuellement un seul TER direct).
- Si GitHub continue de sauter des lancements programmés : déclencheur
  externe (ex. cron-job.org appelant l'API workflow_dispatch avec un jeton).
- GitHub suspend les tâches programmées après 60 jours sans commit.
