# App Android ↔ servidor y web: lista para igualar

> Lo que la app Android tiene que usar del servidor y cómo debe comportarse para ser igual que la web
> (`server/web/web.html`, la referencia). Al día el 03-11-2026 (rutas y campos comprobados contra la API ese día). Cuando la app tenga algo, se borra su línea. Fuera
> quedan cosas solo de PC (tarjetas laterales, tres columnas, volumen). Detalle de cada ruta en el `README.md`; plan
> de recomendaciones en `docs/recomendaciones.md`. Todo con la sesión como `Bearer`.

## A. Rutas del servidor

1. **Buscar** — `GET /search?q=…&yt=0|1&offset=&limit=`. `where`: `guardada` o `youtube`. **`total`** = cuántas
   guardadas hay en total ("rawayana" → 78): úsalo en "Ver todas (N)" y pide más con `limit=200` o por páginas. Con
   `yt=1` (solo en la primera página) trae **`internet`: la lista de internet entera** (hasta 20): la que hay que
   enseñar, en ese orden: es **tal cual lo que da YouTube Music**, sin añadir, quitar ni reordenar. Lo que ya está guardado **sale en ella** con `where: guardada` (marcarlo "Guardada"; suena la
   del servidor). `results` sigue trayendo detrás solo las de `youtube`, para versiones viejas. Lo guardado
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
   **Importar playlist**: usar `GET /import/youtube?url=…` en vez de llamar a YouTube desde el móvil: devuelve
   `{name, songs, total, truncated}` con cada canción ya marcada `guardada`/`youtube` (también la búsqueda por
   artista + título en lo guardado) y el Mix ya limpio; errores 400/404 con el texto para enseñar en `detail`. El
   resumen y el guardado (`POST` + `PUT /playlists` con fichas completas) siguen igual.
8. **Historial** — `GET /history?limit=50` (lo apunta el servidor solo con cada `/stream`).
   **Audio:** pedir `/stream/<id>` con la sesión en la cabecera `Authorization: Bearer …` (just_audio admite
   `headers`); `?token=` en la dirección ya no vale (quitado el 03-11-2026). Si el reproductor no deja
   poner cabeceras: `POST /stream/<id>/enlace` → `{url}` (vale 6 h, solo esa canción; pedir uno por canción).
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
10. **Actualizaciones** — `GET /app/version` y `POST /app/enlace` (aviso de versión nueva). Los dos traen `sha256`
    (huella del APK, en minúsculas): comprobarla con lo bajado **antes de instalar**; si no coincide, borrarlo y
    decir "La descarga llegó mal, vuelve a intentarlo". Si falta el campo (servidor viejo), instalar como siempre.
    Un **429** en cualquier ruta = demasiadas sesiones falsas desde esa IP: enseñar el mensaje (`detail`), no
    volver al login.
11. **Sesiones** — máximo **3 dispositivos** por cuenta (administradores sin límite). Ante un **401**: volver al login
    con "Se inició sesión en otro dispositivo", sin quedarse callada.

12. **Pestaña DC** — `POST /discord/inicio`, `DELETE /discord`, `GET /dc/estado?desde=`, `POST /dc/pedir`,
    `/dc/saltar`, `/dc/anterior`, `/dc/pausa`, `/dc/quitar`, `/dc/mover`. `/me` trae `discord` (`{name, photo}` o `null`). Detalle en el
    README, "Pestaña DC". Esta pestaña **no tiene referencia en la web**: su comportamiento está en la sección B.
13. **Escuchar en varios dispositivos** — `GET /conectar?disp=&nombre=&desde=` (espera larga), `POST /conectar/estado`,
    `POST /conectar/orden`. Detalle en el README, "Escuchar en varios dispositivos"; comportamiento en B.12.

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
   - **Canvas (como Spotify):** al empezar cada canción, `GET /canvas/{id}/estado` → `listo | haciendo | no`. Con
     `haciendo` (el servidor lo está haciendo, ~1 min) volver a preguntar cada 20 s unas 8 veces mientras siga esa
     canción. Con `listo`, y solo con el reproductor grande abierto, bajar `GET /canvas/{id}` (mp4 H.264 vertical
     540×960, 7 s, sin sonido, ~300–600 KB) y ponerlo **de fondo, en bucle y mudo**, con la portada oculta y un
     degradado oscuro arriba y abajo para que se lean título y controles; se para cuando se pausa la música. Guardar
     en memoria los últimos ~12. Sin Canvas (o con "reducir animaciones" del sistema): la portada viva.
     **Cómo queda la pantalla (como en Spotify):** el vídeo, el título y los controles ocupan **la pantalla entera**
     (la portada, invisible, crece para llenar el alto), con las pestañas Siguiente / Letra justo en el borde de abajo;
     la cola y la letra van debajo, al bajar, sobre el fondo normal (el vídeo no sigue detrás de ellas). Sin degradado
     oscuro: solo una capa negra muy leve (~30 % arriba, ~8 % en medio, ~30 % abajo) y el texto en blanco con sombra
     suave (también con el tema claro). Las pestañas, en una **cajita flotante de cristal** con esquinas de 18 px, como
     la barra de Inicio / Buscar / Biblioteca (fondo de la barra al 70 % + desenfoque, borde fino, sombra).
     **Iconito de estado** (30 px, redondo, negro al 40 % con desenfoque, abajo a la derecha de la portada, solo cuando
     no se ve el Canvas): película tachada = `no` (al tocarlo, aviso con el `motivo` que manda el servidor); película
     latiendo = `haciendo`; reloj = `haciendo` con `espera` (aviso con la `espera`); triángulo = error al preguntar.
     `GET /canvas/{id}/estado` trae ahora `motivo` (con `no`) y `espera` (con `haciendo`, si no se puede hacer ya).
     **No bajar la pantalla sola** hasta la
     canción que suena en la cola mientras se mira la portada/el vídeo; **tocar una pestaña sí baja** hasta ella.
   - **Títulos limpios y portadas:** la API ya manda el `title` sin "(Official Video)", "// Letra" ni el artista
     delante ("Rompe La Cintura", no "Alexis y Fido - Rompe La Cintura // Letra"); la app no tiene que hacer nada,
     solo no volver a "limpiarlo" ella (y para buscar letras puede usarlo tal cual). `GET /album` trae ahora
     `thumb` (la portada del álbum): usarla en la cabecera en vez de la de la primera canción. En las tarjetas
     (artistas, álbumes, playlists) el nombre va en **hasta 2 líneas**, no en una cortada.
   - **"🔀 Aleatorio"** al lado de "▶ Reproducir" (arriba de Me gusta, y en playlists, álbumes y géneros; solo si
     hay 2 o más): enciende el aleatorio general (se queda encendido) y empieza de cero con una cualquiera de la
     lista y el resto mezclado. En la página de un artista no hace falta (tiene su propio aleatorio).
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
11. **Pestaña DC**, junto a Inicio, Buscar y Biblioteca. Una pantalla por cada `estado` de `/dc/estado`:
    - `sin_vincular`: botón "Entrar con Discord". Abre la `url` de `/discord/inicio` en el navegador externo; al volver a
      la app se consulta el estado (no hace falta enlace profundo). Aquí no hay bucle: la respuesta llega al momento.
    - `fuera_de_voz`: "Entra a un canal de voz".
    - `sin_bot`: el buscador; pedir la primera canción trae al bot.
    - `ocupado`: los dos bots están en otros canales.
    - `con_bot`: canción actual, cola completa, `acciones` y buscador.
    - **Bucle:** `GET /dc/estado?desde=<última version>` seguido, solo con la pestaña visible; se corta al salir o en
      segundo plano. Si falla, esperar unos segundos. `posicion` la avanza la app localmente salvo con `pausada`.
    - **Buscador:** `/search` igual que en Buscar, con lo de internet; cada resultado va a `/dc/pedir`.
    - **Saltar, anterior y pausa:** mandan el `qid` que se ve y el `pausar` deseado (nunca alternar a ciegas).
      `/dc/anterior` lleva `qid: null` si no suena nada, y se activa solo si `anteriores` no está vacío.
    - **`anteriores`:** las 2 últimas que sonaron, en gris sobre la actual, con la más reciente abajo. No se quitan, pero
      se pueden arrastrar a la cola con `/dc/mover`: salen de `anteriores` y quedan en la cola con el mismo `qid`.
    - **Reordenar:** arrastre con asa ≡ como la cola normal, con `/dc/mover` **solo al soltar**. Las respuestas del
      bucle que lleguen mientras se arrastra se aplazan hasta soltar, y después manda lo del servidor. Ante 404 o 409,
      enseñar `detail` y recargar.
    - Las canciones con `id: null` se ven y se mueven, pero no se abren.
    - El reproductor de la app no se toca: la pestaña controla el bot y nada más.
    - "Desvincular Discord" con `DELETE /discord`. Un 503 es "el bot no contesta".

12. **Escuchar en varios dispositivos (como Spotify Connect)** — la web es la referencia (`server/web/web.html`,
    "escuchar en varios dispositivos").
    - **Id del dispositivo**: uno al azar la primera vez, guardado (6–40 caracteres `[A-Za-z0-9_-]`); **nombre**:
      "Celular · App" (o el modelo, p. ej. "Pixel 7 · App"). La web se llama "PC · Chrome", "Celular · Chrome"…
    - **Bucle**: mientras la app esté abierta o sonando, `GET /conectar?disp=&nombre=&desde=<v>` sin parar (espera
      larga de 25 s; tras un error, esperar 5 s). Con la respuesta:
      - `activo == mi id`: soy el que suena. Hacer las `ordenes` con `n` mayor que la última hecha (`pausa {pausar}`,
        `siguiente`, `anterior`, `ir {pos}`, `cola {cola, qi, nueva, radio, repetir}`: cambiar la cola; si `nueva` o
        cambió la canción de `qi`, empezar esa) y luego contar el estado con `hecho`. Si antes era mando: **me la
        pasaron** → poner `sonando.cola` en `sonando.qi` desde `sonando.pos` y que suene.
      - otro `activo` con `activo_vivo`: **modo mando**. No suena nada aquí (pausar si sonaba); el mini reproductor y
        el grande enseñan `sonando` (canción, cola, segundo = `pos` + lo que pasó desde que llegó, si no está en
        pausa), con "🔊 En <nombre>" en el mini y "Sonando en <nombre>" (color de acento) en el botón 🔊. Botones →
        `POST /conectar/orden`: play/pausa `pausa {pausar}`, ⏭ `siguiente`, ⏮ `anterior`, barra `ir {pos}`; tocar una
        canción, poner una lista, "a continuación", mover o quitar de la cola, aleatorio o repetir → hacerlo en la
        copia de la cola y mandar `cola {cola, qi, radio, repetir, aleatorio, nueva: true si empieza otra}`. Sin volumen.
      - nadie vivo sonando y `sonando` con canción: dejarla cargada aquí **en pausa en su segundo** (al dar play
        sigue aquí).
    - **El que suena cuenta** (`POST /conectar/estado {disp, nombre, datos, tomar, hecho}`) al empezar canción, al
      pausar/seguir, al mover el segundo, al cambiar la cola (entonces con `cola`) y cada 15 s mientras suena. `datos`:
      `cancion` (ficha con `id, title, artist, album, duration, thumb, where`), `pos`, `pausa`, `qi`, `radio`,
      `repetir` (`off|all|one`), `aleatorio`, `duracion`, `cola` (fichas). `tomar: true` si suena aquí y el servidor
      cree que suena en otro (dar play aquí se queda la música; el otro se pausa solo).
    - **Botón 🔊 "Dónde suena"** en el reproductor grande, debajo de los controles: hoja con los dispositivos vivos
      ("Este dispositivo" primero; el que suena en color de acento, "Suena aquí"); tocar otro → `orden transferir {a}`
      (si suena aquí, contar el estado justo antes para que siga en el mismo segundo). Con uno solo: "Abre la web o
      la app en otro dispositivo con tu cuenta y saldrá aquí".
