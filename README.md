# MAX Jeune — moteur de recherche

Trouve des trajets MAX Jeune (0 €) à partir des données ouvertes SNCF :

- **MAX direct** ;
- **montée / descente en cours** (billet plus long sur le même train) ;
- **2 segments MAX** (deux billets avec correspondance) ;
- **MAX + TER** (quand il n'existe aucune solution 100 % MAX).

Deux interfaces partagent la même logique :

- **Site web / app iPhone** (`web/`) : publié gratuitement sur GitHub Pages, installable sur l'écran d'accueil ;
- **Appli de bureau** (`max_jeune.py`, Tkinter) : utile pour tester sur PC.

## Contenu du dossier

| Élément | Rôle |
|---|---|
| `max_jeune_engine.py` | Moteur de référence (Python) |
| `max_jeune.py` | Appli de bureau |
| `tests/` | Tests du moteur Python |
| `pipeline/build_data.py` | Prépare les données du site (1 fichier par jour) |
| `pipeline/preview.py` | Aperçu du site sur ton PC |
| `web/` | Le site : `engine.js` (moteur JS), `app.js` (interface), `style.css`, service worker, icônes |
| `web/tests/` | Test de fidélité : le moteur JS doit donner exactement les mêmes résultats que le moteur Python |
| `.github/workflows/deploy.yml` | Mise à jour automatique des données et publication |

Les gros fichiers (`*.csv`, `*.zip`, `*.xlsx`) ne sont **jamais** envoyés sur GitHub (voir `.gitignore`) : le serveur les télécharge lui-même.

---

## Mettre le site en ligne (une seule fois, ~15 min)

### 1. Créer un compte GitHub

Sur <https://github.com/signup>, c'est gratuit. Ton nom d'utilisateur apparaîtra dans l'adresse du site :
`https://<nom>.github.io/max-jeune/`.

### 2. Installer GitHub Desktop

Télécharge-le sur <https://desktop.github.com>, puis connecte-toi avec ton compte.

### 3. Publier le dossier

1. Dans GitHub Desktop, choisis **File → Add local repository…**, puis sélectionne ce dossier `Train`.
2. Il propose « create a repository » : accepte.
   - Nom : `max-jeune`.
   - Laisse le reste par défaut.
3. Vérifie la liste des fichiers : aucun `.csv` ni `.zip` ne doit y figurer.
4. En bas à gauche, écris « Première version », puis clique **Commit to main**.
5. Clique **Publish repository**.
   - **Décoche « Keep this code private »** : GitHub Pages est gratuit pour les dépôts publics.
   - Le code et les données SNCF sont publics de toute façon. Aucune donnée personnelle n'est dans le dépôt.

### 4. Activer GitHub Pages

1. Sur github.com, ouvre ton dépôt `max-jeune`.
2. Va dans **Settings → Pages**.
3. Dans **Source**, choisis **GitHub Actions**.

### 5. Lancer la première publication

1. Onglet **Actions**, puis **Mise à jour et déploiement**.
2. Clique **Run workflow**.
3. Compte environ 3 à 5 minutes. Quand la pastille est verte, le site est en ligne.

### 6. Installer l'app sur l'iPhone

1. Ouvre `https://<nom>.github.io/max-jeune/` dans **Safari**.
2. Touche **Partager**, puis **Sur l'écran d'accueil**.

L'icône s'ouvre en plein écran comme une app. Elle fonctionne aussi hors ligne, avec les dernières données consultées.

---

## Fonctionnement au quotidien

- **Données** : elles sont mises à jour automatiquement 3 fois par jour (≈ 6 h 15, 12 h 15 et 18 h 15, heure de Paris en été). Rien à faire. La date de mise à jour s'affiche en haut du site.
- **Si quelque chose casse** (par exemple la SNCF change son fichier) :
  - la publication est annulée et le site reste sur la dernière version valide ;
  - GitHub t'envoie un email.
- **Corriger un bug** :
  1. Modifie le code.
  2. Dans GitHub Desktop, fais **Commit**, puis **Push origin**.
  3. Le site est à jour en quelques minutes.
  4. Sur l'iPhone, un bandeau « Nouvelle version disponible » propose la mise à jour.
- **Remontées de bugs** : le bouton **Signaler un problème** en bas du site ouvre un ticket GitHub pré-rempli (recherche faite, date des données, version). C'est pratique pour reproduire le cas.

### Règle d'or pour modifier le moteur

Le moteur existe en deux versions :

- `max_jeune_engine.py` (référence) ;
- `web/engine.js` (site).

Toute modification se fait **dans les deux**. Le test de fidélité (`web/tests/`) tourne à chaque publication : si les deux moteurs ne donnent plus exactement les mêmes résultats, la publication est bloquée.

## Tester sur ton PC

```bash
python -m pytest tests                 # tests du moteur Python (pip install pytest)
python pipeline/preview.py             # aperçu du site sur http://localhost:8000
python max_jeune.py                    # appli de bureau
```

`preview.py` et l'appli de bureau utilisent `tgvmax_cache.csv` et `Export_OpenData_SNCF_GTFS_NewTripId.zip` présents dans le dossier. Pour les rafraîchir, clique « Recharger données » dans l'appli de bureau.

## Sources et licence des données

- Disponibilités MAX : jeu de données **TGVMax**, SNCF Voyageurs (<https://ressources.data.sncf.com>).
- Horaires TER / Intercités : **GTFS SNCF** (<https://transport.data.gouv.fr/datasets/horaires-sncf>), licence ODbL.
  - Les fichiers dérivés publiés par le site sont eux aussi sous ODbL.
