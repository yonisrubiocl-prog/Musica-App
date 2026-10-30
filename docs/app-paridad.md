# App Android ↔ servidor y web: lista para igualar

> Lista de lo que la app Android tiene que usar del servidor y de cómo debe comportarse para ser igual que la web
> (`server/web/web.html`, que sirve de referencia). Hecha el 30-10-2026. Se tacha (o se borra la línea) cuando la
> app lo tenga. Fuera quedan cosas solo de PC (panel lateral, tres columnas, volumen). Detalle de cada ruta en el
> `README.md`; plan de recomendaciones en `docs/recomendaciones.md`. Todo con la sesión como `Bearer`.

## A. Rutas del servidor

1. **Buscar** — `GET /search?q=…&yt=0|1&offset=&limit=`. `where`: `guardada` o `youtube`. **`total`** = cuántas
   guardadas hay en total ("rawayana" → 78): úsalo en "Ver todas (N)" y pide más con `limit=200` o por páginas. Con
   `yt=1` (solo en la primera página) añade **20 de internet que no estén guardadas**, de YouTube Music. Lo guardado
   tolera faltas y palabras a medio escribir.
2. **Sugerencias mientras se escribe** — `GET /suggest?q=…` (~45 ms, sin YouTube) → `{sugerencias: [{tipo:
   artista|album|cancion, texto, artista, id, canciones, thumb}]}`. **En un desplegable bajo el campo, sin cambiar la
   lista de abajo**; primera fila "🔎 Buscar «texto»"; tocar: artista → su página, álbum → el álbum, canción → que
   suene; los resultados completos, al pulsar buscar. Pedirlo con ~120 ms de pausa tras cada tecla.
3. **Álbumes de internet** — `GET /search/albums?q=…` (solo al abrir esa pestaña: 1 petición a YouTube) y
   `GET /search/album/<id>` (canciones en orden, `track`, y `where` para marcar las guardadas).
4. **Biblioteca** — `GET /library?sort=recientes|populares|nombre|artista&offset=&limit=&genre=` (scroll infinito),
   `GET /genres`, `GET /artists`, `GET /artist?name=`, `GET /album?artist=&name=`. Las canciones traen `genre`.
5. **Favoritas** — `GET /favorites`, `PUT /favorites/<id>` (si no está guardada, en el cuerpo `{title, artist, album,
   duration, thumb}`), `DELETE /favorites/<id>`.
6. **Playlists** — `GET /playlists`, `POST /playlists {name}` → `{id}`, `PUT /playlists/<id> {name, songs}` (entera;
   `songs` = ids o fichas `{id, title, …}`; si falta alguna ficha: 400 `{detail: {error, ids}}`), `DELETE /playlists/<id>`.
7. **Historial** — `GET /history?limit=50` (lo apunta el servidor solo con cada `/stream`).
8. **Recomendaciones (fase 1)**
   - `POST /eventos {eventos: [{tipo: entera|salto|no_me_gusta|ya_no_me_gusta, id, segundo, duracion, contexto,
     causa, cuando}]}` en lote; sin conexión, guardarlos y mandarlos después. **No mandar `inicio`**: lo apunta `/stream`.
   - `GET /home` → secciones `recientes`, `para_ti`, `vuelve` (las vacías no vienen; si da 404, el Inicio de siempre).
   - `GET /radio?desde=cancion:<id>|artista:<nombre>&ya=<ids>&n=20`; volver a pedir cuando queden 2–3.
   - `GET /recomendaciones/preguntar?contexto=` y `POST /recomendaciones/opinion {contexto, semilla, gusto: si|no,
     opciones, texto, canciones}`.
9. **Actualizaciones** — `GET /app/version` y `POST /app/enlace` (aviso de versión nueva).
10. **Sesiones** — máximo **3 dispositivos** por cuenta (administradores sin límite). Ante un **401**: volver al login
    con "Se inició sesión en otro dispositivo", sin quedarse callada.

## B. Comportamientos a igualar

1. **Cómo se arma la cola al tocar una canción**
   - **Suelta** (búsqueda, biblioteca entera, un género, "Lo más puesto") → **modo radio**: esa y detrás
     recomendadas de `/radio`, que se van añadiendo solas.
   - **Filas del Inicio** (Escuchado recientemente, Tus favoritas, Para ti, Vuelve a escuchar) → **la lista entera**
     aunque la fila enseñe 20: **la elegida y luego la lista en su orden normal desde el principio** (10 canciones,
     tocando la 7.ª: 7, 1, 2, 3, 4, 5, 6, 8, 9, 10).
   - **Biblioteca** (Me gusta, una playlist, un álbum) → **desde la elegida hacia abajo** (7, 8, 9, 10).
   - **Con aleatorio**, siempre: la elegida primero y el resto mezclado.
   - Al acabarse una lista: interruptor **"Seguir con canciones parecidas"** (radio de la última).
2. **Menú de cada canción**: "📻 Iniciar radio", "👎 No me gusta" (evento `no_me_gusta`; si es la que suena, pasar a
   la siguiente) y, si suena una radio, "💬 Opinar sobre estas recomendaciones".
3. **"¿Qué te parecieron?"**: tras 10 recomendadas seguidas, si `/recomendaciones/preguntar` dice que sí: 👍/👎,
   opciones `repetitivas`, `no_me_gustaron`, `quiero_nuevas`, `muy_raras`, `generos_no_pegan`, `mas_reciente`,
   `versiones_raras`, texto libre y "Ahora no".
4. **Inicio**: las secciones de `/home` (Para ti, Vuelve a escuchar) junto a las de siempre.
5. **Portada viva** en el reproductor grande: la portada se acerca y se mueve muy despacio (24 s, ida y vuelta) y el
   fondo desenfocado "respira" (9 s). Solo mientras suena; sin animación si el sistema pide reducir movimiento.
   (En Flutter: `ClipRRect` + `Transform` con un `AnimationController` de 24 s `repeat(reverse: true)`; fondo con
   `ImageFilter.blur` ~80 y opacidad 0,4–0,65.)
6. **Letra**: si se puede ocultar, que se recuerde; y que la barra de pestañas (Siguiente/Letra) **se quede pegada
   arriba** al bajar por la letra.
7. **Eventos para las recomendaciones**: al cambiar antes del 80 %, `salto` con el segundo; al pasar del 80 %,
   `entera`; si falló la reproducción, `salto` con `causa: "error"`. `contexto` según de dónde vino (`radio`,
   `para_ti`, `vuelve`, `busqueda`, `biblioteca`, `playlist`, `favoritas`).
