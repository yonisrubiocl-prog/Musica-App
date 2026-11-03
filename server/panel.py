#!/usr/bin/env python3
"""Panel de la música en la terminal: ~/MusicApp/server/panel.py

Lo de dentro está en panelmusica/ (Textual). Este archivo solo lo arranca con su entorno (.venv-panel, fuera de git);
la primera vez lo crea e instala Textual. ':' abre los comandos (:1 aprueba al 1, :H ayuda, :Q sale).
"""
import os
import shlex
import subprocess
import sys

D = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(D, ".venv-panel")
PY = os.path.join(VENV, "bin", "python")
REQ = os.path.join(D, "panelmusica", "requisitos.txt")

USERS = os.path.join(D, "data", "users.json")
if not os.access(USERS, os.R_OK) and not os.environ.get("PANEL_SG"):
    # Los datos son del grupo musicapp (la API corre como el usuario 10001). Una sesión SSH abierta antes de entrar
    # en el grupo no lo tiene todavía: se vuelve a lanzar con él (sg), sin tener que salir y entrar.
    os.environ["PANEL_SG"] = "1"
    os.execvp("sg", ["sg", "musicapp", "-c", " ".join(shlex.quote(x) for x in [sys.executable, *sys.argv])])
if not os.access(USERS, os.R_OK):
    sys.exit("No puedo leer los datos de la API (data/users.json). ¿Está tu usuario en el grupo musicapp? "
             "Mira: id -nG")

if os.path.realpath(sys.prefix) != os.path.realpath(VENV):
    if not os.path.exists(PY):
        print("Preparando el panel (solo la primera vez)…")
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)
        subprocess.run([PY, "-m", "pip", "install", "-q", "-r", REQ], check=True)
    os.execv(PY, [PY, os.path.abspath(__file__), *sys.argv[1:]])

# Color real (24 bits): por SSH casi nunca llega COLORTERM y Textual aproximaría a 256 colores (más chillones).
# Si alguna terminal vieja se ve rara: COLORTERM=256 ./panel.py
os.environ.setdefault("COLORTERM", "truecolor")
sys.path.insert(0, D)
from panelmusica.app import main  # noqa: E402

main()
