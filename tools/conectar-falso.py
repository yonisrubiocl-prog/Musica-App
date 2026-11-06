# Servidor de mentira para tools/prueba-conectar.js: /conectar con la lógica real de server/conectar.py, una sola cuenta.
import asyncio, json, sys
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, "/cx")
import conectar as C
C.FILE = "/tmp/conectar-prueba.json"
X = C.Conectar(); SUB = "prueba"
async def atiende(r, w):
    try:
        linea = (await r.readline()).decode(); met, ruta, _ = linea.split(" ", 2)
        h = {}
        while (l := (await r.readline()).decode().strip()):
            k, v = l.split(":", 1); h[k.lower()] = v.strip()
        body = json.loads(await r.readexactly(int(h.get("content-length", 0))) or b"{}") if met == "POST" else {}
        u = urlparse(ruta); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        code, out = 200, {"ok": True}
        if u.path == "/conectar":
            out = await X.esperar(SUB, q["disp"], q.get("nombre", ""), int(q.get("desde", 0)))
        elif u.path == "/conectar/estado":
            if not X.estado(SUB, body["disp"], body.get("nombre", ""), body["datos"], body.get("tomar", False), body.get("hecho")):
                code, out = 409, {"detail": "está sonando en otro dispositivo"}
        elif u.path == "/conectar/orden":
            err = X.orden(SUB, body["disp"], body["tipo"], body.get("datos") or {})
            if err: code, out = 409, {"detail": err}
        data = json.dumps(out).encode()
        w.write(f"HTTP/1.1 {code} X\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode() + data)
        await w.drain()
    except Exception as e:
        print("error", e, flush=True)
    w.close()
async def main():
    srv = await asyncio.start_server(atiende, "127.0.0.1", 8777)
    async with srv: await srv.serve_forever()
asyncio.run(main())
