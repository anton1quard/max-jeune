"""
Aperçu local du site, avec les fichiers de données déjà présents dans le
dossier (tgvmax_cache.csv et le zip GTFS). Rien n'est publié.

    python pipeline/preview.py            puis ouvrir http://localhost:8000

Astuce : pour tester sur ton iPhone, connecte-le au même Wi-Fi et ouvre
http://<adresse IP de ton PC>:8000 (le mode hors ligne ne marchera pas en
http, seulement une fois publié en https).
"""
import functools
import http.server
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "_site"
PORT = 8000


def main() -> None:
    subprocess.run([sys.executable, str(ROOT / "pipeline" / "build_data.py"), "--out", str(SITE / "data")],
                   check=True)
    for name in ["index.html", "style.css", "app.js", "engine.js", "sw.js", "manifest.webmanifest"]:
        shutil.copy2(ROOT / "web" / name, SITE / name)
    shutil.copytree(ROOT / "web" / "icons", SITE / "icons", dirs_exist_ok=True)
    for name in ["app.js", "sw.js"]:
        p = SITE / name
        p.write_text(p.read_text(encoding="utf-8").replace("__BUILD__", "local"), encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    print(f"Aperçu : http://localhost:{PORT}   (Ctrl+C pour arrêter)")
    http.server.ThreadingHTTPServer(("", PORT), handler).serve_forever()


if __name__ == "__main__":
    main()
