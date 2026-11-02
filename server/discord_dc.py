"""Pestaña DC de la app: "Entrar con Discord" y el paso de peticiones al bot.

El login solo sirve para saber el id de Discord de cada cuenta (permiso `identify`). La cola no se guarda aquí: vive
en el bot, que tiene un servidor interno en la red de Docker. Ver README.md, "Pestaña DC".
"""
import os
import secrets
import threading
import time
import urllib.parse

import httpx

CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
REDIRECT = os.environ.get("DISCORD_REDIRECT", "")
BOT_KEY = os.environ.get("BOT_API_KEY", "")
BOT_URL = "http://musicbot:8100"
DISCORD_API = "https://discord.com/api/v10"
STATE_TTL = 10 * 60                     # cuánto sirve un enlace de "Entrar con Discord"
BOT_WAIT = 15                           # órdenes normales
BOT_WAIT_LONG = 90                      # pedir: puede tocar buscar la canción (el bot le pregunta a /interno/resolve)
BOT_WAIT_STATE = 35                     # /estado: el bot espera hasta 25 s un cambio

states = {}                             # state -> (sub, hasta cuándo): de un solo uso, ligado a la cuenta que lo pidió
states_lock = threading.Lock()


def configured():
    return bool(CLIENT_ID and CLIENT_SECRET and REDIRECT)


def login_url(sub):
    state = secrets.token_urlsafe(24)
    now = time.time()
    with states_lock:
        for k in [k for k, (_, until) in states.items() if until < now]:
            del states[k]
        states[state] = (sub, now + STATE_TTL)
    return "https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(
        {"client_id": CLIENT_ID, "response_type": "code", "scope": "identify", "redirect_uri": REDIRECT,
         "state": state, "prompt": "none"})


def take_state(state):
    """La cuenta que pidió este enlace, si sigue valiendo. Se gasta al usarlo."""
    with states_lock:
        sub, until = states.pop(state, (None, 0))
    return sub if until >= time.time() else None


async def identify(code):
    """Canjea el código de Discord -> {id, name, photo}. Lanza httpx.HTTPError si Discord no lo acepta."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{DISCORD_API}/oauth2/token", auth=(CLIENT_ID, CLIENT_SECRET),
                         data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT})
        r.raise_for_status()
        r = await c.get(f"{DISCORD_API}/users/@me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
        r.raise_for_status()
    me = r.json()
    photo = f"https://cdn.discordapp.com/avatars/{me['id']}/{me['avatar']}.png" if me.get("avatar") else ""
    return {"id": me["id"], "name": me.get("global_name") or me["username"], "photo": photo}


async def to_bot(method, path, params=None, body=None, wait=BOT_WAIT):
    """Pregunta al bot -> (estado HTTP, JSON). (503, ...) si no contesta."""
    try:
        async with httpx.AsyncClient(timeout=wait) as c:
            r = await c.request(method, BOT_URL + path, params=params, json=body,
                                headers={"Authorization": f"Bearer {BOT_KEY}"})
        return r.status_code, r.json()
    except (httpx.HTTPError, ValueError):
        return 503, {"error": "El bot no contesta."}
