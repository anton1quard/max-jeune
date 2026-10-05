"""
Décide s'il faut republier le site.

Compare l'empreinte des données fraîchement préparées avec celle du site en
ligne. Écrit « deploy=true » ou « deploy=false » (format GitHub Actions).
  - modification du code (push) ou option « forcer » : on publie toujours ;
  - sinon (cron-job.org, secours programmé, bouton Run workflow) : on ne
    publie que si les données SNCF ont changé. Ainsi l'heure affichée sur le
    site (« Places MAX mises à jour le… ») correspond à la dernière vraie
    mise à jour des données.

Usage : python pipeline/check_changed.py <meta.json local> <URL du meta.json en ligne>
"""
import json
import os
import sys
import urllib.request


def main() -> None:
    local_path, online_url = sys.argv[1], sys.argv[2]
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    local = json.load(open(local_path, encoding="utf-8"))
    try:
        with urllib.request.urlopen(online_url, timeout=30) as r:
            online = json.load(r)
    except Exception as e:  # site pas encore publié, réseau…
        online = {}
        print(f"Site en ligne illisible ({e}) : on publie.", file=sys.stderr)
    same = bool(online) and online.get("content_hash") == local["content_hash"]
    force = os.environ.get("FORCE", "").lower() == "true"
    deploy = event == "push" or force or not same
    print(f"Événement={event or '?'} ; forcer={force} ; données identiques au site en ligne={same} ; publication={deploy}",
          file=sys.stderr)
    print(f"deploy={'true' if deploy else 'false'}")


if __name__ == "__main__":
    main()
