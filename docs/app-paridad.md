# App Android ↔ servidor y web: lista para igualar

> Lo que la app Android tiene que usar del servidor y cómo debe comportarse para ser igual que la web
> (`server/web/web.html`, la referencia). Al día el 30-10-2026. Cuando la app tenga algo, se borra su línea. Fuera
> quedan cosas solo de PC (tarjetas laterales, tres columnas, volumen). Detalle de cada ruta en el `README.md`; plan
> de recomendaciones en `docs/recomendaciones.md`. Todo con la sesión como `Bearer`.

## A. Rutas del servidor

1. **Buscar** — `GET /search?q=…&yt=0|1&offset=&limit=`. `where`: `guardada` o `youtube`. **`total`** = cuántas
   guardadas hay en total ("rawayana" → 78): úsalo en "Ver todas (N)" y pide más con `limit=200` o por páginas. Con
   `yt=1` (solo en la primera página) añade **20 de internet que no estén guardadas**, de YouTube Music. Lo guardado
   tolera faltas y palabras a medio escribir. **`artists`** = los artistas que encajan, también con faltas
   ("cancerbero" → Canserbero): úsalos para la fila de artistas en vez de filtrarlos en la app.
2. **Sugerencias mientras se escribe** — `GET /suggest?q=…` (~45 ms, sin YouTube) → `{sugerencias: [{tipo:
   artista|album|cancion, texto, artista, id, canciones, thumb}]}`. Pedirlo con ~120 ms de pausa tras cada tecla.
3. **Álbumes de internet** — `GET /search/albums?q=…` (solo al abrir esa pestaña: 1 petición a YouTube) y
   `GET /search/album/<id>` (canciones en orden, `track`, y `where` para marcar las guardadas).
4. **Biblioteca** — `GET /library?sort=recientes|populares|nombre|artista&offset=&limit=&genre=` (scroll infinito),
   `GET /genres`, `GET /album?artist=&name=`. Las canciones traen `genre`.
5. **Artistas** — **no agrupar artistas en la app**: usar lo que dice el servidor tal cual (cuenta colaboraciones
   "Apache, Canserbero", "feat." del título y canciones sin artista con el nombre en el título).
   - `GET /artists?orden=tuyos` → todos, primero los que más escucha esa cuenta, que traen **`tuyo: true`**.
   - `GET /artist?name=` → `{name, songs, albums, loose}` (las colaboraciones vienen en `loose` aunque tengan
     álbum) y, con sesión, **`tuyas`** (las suyas en favoritas o playlists) y **`todas`** (la cola del artista: las
     tuyas y luego las demás, de más a menos puestas).
6. **Favoritas** — `GET /favorites`, `PUT /favorites/<id>` (si no está guardada, en el cuerpo `{title, artist, album,
   duration, thumb}`), `DELETE /favorites/<id>`.
7. **Playlists** — `GET /playlists`, `POST /playlists {name}` → `{id}`, `PUT /playlists/<id> {name, songs}` (entera;
   `songs` = ids o fichas `{id, title, …}`; si falta alguna ficha: 400 `{detail: {error, ids}}`), `DELETE /playlists/<id>`.
8. **Historial** — `GET /history?limit=50` (lo apunta el servidor solo con cada `/stream`).
9. **Recomendaciones (fase 1)**
   - `POST /eventos {eventos: [{tipo: entera|salto|no_me_gusta|ya_no_me_gusta, id, segundo, duracion, contexto,
     causa, cuando}]}` en lote; sin conexión, guardarlos y mandarlos después. **No mandar `inicio`**: lo apunta `/stream`.
   - `GET /home` → secciones `{id, titulo, tipo, items}`: `recientes`, `para_ti`, `vuelve` (`tipo: canciones`) y
     **`artistas`** ("Tus artistas", `tipo: artistas`, items como `/artists`). Las vacías no vienen; si da 404, el
     Inicio de siempre.
   - `GET /radio?desde=cancion:<id>|artista:<nombre>&ya=<ids>&n=20`; volver a pedir cuando queden 2–3. Si falla
     (500, sin red), seguir con la cola que hay y reintentar más tarde, sin cortar la música.
   - `GET /recomendaciones/preguntar?contexto=` y `POST /recomendaciones/opinion {contexto, semilla, gusto: si|no,
     opciones, texto, canciones}`.
10. **Actualizaciones** — `GET /app/version` y `POST /app/enlace` (aviso de versión nueva).
11. **Sesiones** — máximo **3 dispositivos** por cuenta (administradores sin límite). Ante un **401**: volver al login
    con "Se inició sesión en otro dispositivo", sin quedarse callada.

## B. Comportamientos a igualar

1. **Cómo se arma la cola al tocar una canción**
   - **Suelta** (búsqueda, biblioteca entera, un género, "Lo más puesto") → **modo radio**: esa y detrás
     recomendadas de `/radio`, que se van añadiendo solas **al final**.
   - **De una lista** (filas del Inicio, Me gusta, una playlist, un álbum, la página de un artista) → **la elegida
     pasa al primer puesto y detrás la lista entera en su orden desde el principio, sin repetirla**, aunque la fila
     enseñe solo 20 (10 canciones, tocando la 7.ª: 7, 1, 2, 3, 4, 5, 6, 8, 9, 10). Nada de "desde la elegida hacia
     abajo". **Con aleatorio:** la elegida primero y el resto mezclado.
   - **Si ya suena esa misma lista** (compara los ids de la lista con los de la que armó la cola), no rehacer la
     cola: la tocada se saca de donde esté y suena ya, y lo que venía detrás sigue igual (no vuelven las que ya
     sonaron; si toca la que suena, nada). "▶ Reproducir" o una canción de otra lista sí empiezan de cero.
     Ejemplo, cola A, B, Religión, Cucú, Bendita, Pop1: toca Religión → Religión, A, B, Cucú, Bendita, Pop1; pasa a
     A; toca Bendita → Bendita, B, Cucú, Pop1.
   - **"⏭ Reproducir a continuación"** en el menú de cada canción (si suena algo y no es esa): la mete justo detrás
     de la que suena **solo en la cola de ahora**, sin tocar la playlist, Me gusta ni la lista de origen. Varias
     seguidas suenan en el orden en que se añadieron (cada una detrás de las otras añadidas); si ya estaba más
     adelante en la cola, se mueve (nunca dos veces). En la cola, marcada "Añadida". Sin nada sonando, suena ya.
   - Al acabarse una lista: interruptor **"Seguir con canciones parecidas"** (radio de la última). Sin él, la cola
     termina.
   - **Ninguna canción puede estar dos veces** en la cola (lo que añade la radio tampoco repite ids).
2. **La cola en pantalla es una lista fija**
   - Mostrar como máximo **las 2 últimas reproducidas en gris**, la actual y todas las siguientes. Las más
     antiguas se ocultan sin quitarlas de la cola interna: Anterior permite volver a ellas. Tocar una visible la vuelve a poner.
   - Al pasar de canción **no se reconstruye ni salta**: solo cambia cuál está resaltada (si queda fuera de la vista,
     bajar lo justo). Solo se repinta si la cola cambia (lista nueva, canción adelantada, aleatorio, radio añadida).
   - **Reordenar arrastrando:** asa **≡** a la derecha de cada canción que falta por sonar (en Flutter,
     `ReorderableListView` + `ReorderableDragStartListener` en el asa) y también pulsación larga en la fila. Solo
     las que faltan, a cualquier sitio después de la que suena; al soltar, la lista no salta de scroll.
3. **Artistas como en Spotify**
   - **Inicio:** la sección `artistas` de `/home` ("Tus artistas") en vez de la fila de todos los artistas.
   - **Biblioteca → Artistas:** `/artists?orden=tuyos` enseñando **solo los que traen `tuyo: true`** (ya vienen
     ordenados) y al final "Ver todos los artistas (N)"; si ninguno es `tuyo`, todos.
   - **Página de un artista**, en este orden: **"Tus canciones"** (`tuyas`, si hay), **"Populares"** (`todas` sin
     las de `tuyas`; 10 y "Ver todas (N)"; si no hay `tuyas`, se llama "Canciones") y **al final los álbumes**.
     Botón "▶ Reproducir" arriba. "▶ Reproducir" y tocar cualquiera de sus canciones usan **`todas`** con la regla
     del punto 1.
   - **Aleatorio del artista, independiente del general:** dos interruptores guardados aparte. El general vale para
     Inicio, Biblioteca, playlists, álbumes y canciones sueltas; el del artista, solo para lo que suena desde la
     página de un artista, y **empieza apagado**. El botón 🔀 cambia el de lo que está sonando.
4. **Inicio**: las secciones de `/home` (Para ti, Vuelve a escuchar, Tus artistas) junto a las de siempre.
5. **Menú de cada canción**: "📻 Iniciar radio", "👎 No me gusta" (evento `no_me_gusta`; si es la que suena, pasar a
   la siguiente) y, si suena una radio, "💬 Opinar sobre estas recomendaciones".
6. **"¿Qué te parecieron?"**: tras 10 recomendadas seguidas, si `/recomendaciones/preguntar` dice que sí: 👍/👎,
   opciones `repetitivas`, `no_me_gustaron`, `quiero_nuevas`, `muy_raras`, `generos_no_pegan`, `mas_reciente`,
   `versiones_raras`, texto libre y "Ahora no".
7. **Buscar**: las sugerencias de `/suggest` **en un desplegable bajo el campo, sin cambiar la lista de abajo**;
   primera fila "🔎 Buscar «texto»"; tocar: artista → su página, álbum → el álbum, canción → que suene; los
   resultados completos, al pulsar buscar.
8. **Portada viva** en el reproductor grande: la portada se acerca y se mueve muy despacio (24 s, ida y vuelta) y el
   fondo desenfocado "respira" (9 s). Solo mientras suena; sin animación si el sistema pide reducir movimiento.
   (En Flutter: `ClipRRect` + `Transform` con un `AnimationController` de 24 s `repeat(reverse: true)`; fondo con
   `ImageFilter.blur` ~80 y opacidad 0,4–0,65.)
9. **Letra**: si se puede ocultar, que se recuerde; y que la barra de pestañas (Siguiente/Letra) **se quede pegada
   arriba** al bajar por la letra.
10. **Eventos para las recomendaciones**: al cambiar antes del 80 %, `salto` con el segundo; al pasar del 80 %,
    `entera`; si falló la reproducción, `salto` con `causa: "error"`. `contexto` según de dónde vino (`radio`,
    `para_ti`, `vuelve`, `busqueda`, `biblioteca`, `playlist`, `favoritas`).
