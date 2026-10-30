# Recomendaciones: plan de diseño

> **Estado:** plan, sin hacer (30-10-2026). Junta la propuesta de Claude y las correcciones de GPT. Este documento
> se reescribe según se construya: cada fase hecha pasa a describir cómo funciona de verdad.
> Lo que no sea de recomendaciones va en el `README.md`.

## 1. Objetivo y principios

Que la app y la web propongan música que apetezca escuchar: **Radio** (sigue sola desde una canción o un artista)
y **Para ti** primero; después mixes y descubrir cosas nuevas. Para unas 7–15 personas.

1. **Todo el cerebro en el servidor.** Las apps (Android y web) solo dibujan lo que manda el servidor y le cuentan
   lo que hace el usuario. Se mejora sin publicar app nueva; la web y el móvil ven lo mismo. Discord, fuera.
2. **Primero lo que ya está guardado:** gratis, al instante, sin YouTube. YouTube solo para descubrir (lo último).
3. **Cada uno aprende de lo suyo.** Usar lo de los demás es opcional y está apagado por defecto (con 7 personas,
   incluso lo agregado puede delatar gustos de alguien).
4. **Se puede apagar y quitar** sin romper nada (sección 11).
5. **Empezar pequeño:** Radio y Para ti deciden si se siente inteligente o aleatorio; el resto viene después.

## 2. Señales (qué aprende)

Solo la **app** sabe si una canción se escuchó entera o se quitó (el servidor solo ve cuándo empieza a sonar), así
que la app manda **eventos** (sección 9). Pesos iniciales, para ajustar con datos (constantes en el código):

| Señal | Peso | Notas |
|---|---|---|
| ♡ favorita | +4 | ya existe (`/favorites`) |
| Añadir a una playlist | +3 | ya existe (`/playlists`) |
| Repetirla por voluntad (otro día, o volver a ponerla) | +2 | del historial |
| Escuchar más del 80 % | +1 | evento `entera` |
| **"No me gusta / no recomendar"** (botón) | −5 | la señal más clara; se respeta siempre |
| Saltarla antes del 15 % **en algo recomendado** (radio, mix, Para ti) | −1 | solo baja "recomendármela ahora" |
| Saltarla antes del 15 % en algo que puso uno mismo | −0,3 | casi nada: a veces solo apetece otra |
| Saltarla 3 veces en días distintos | −2 | aquí sí: "no me gusta" |
| Quitar el ♡ | −1 | |

**No cuentan** como salto: errores de reproducción, cambio de dispositivo, cortes (llamadas, sin red) ni
reproducciones de menos de 5 s seguidas de otra igual (doble toque). La app marca la causa del corte.

Dos efectos distintos de un salto, por separado:
- **"No me la recomiendes ahora"**: rápido y temporal (unos días).
- **"No me gusta"**: lento, solo con saltos repetidos o el botón.

## 3. Perfil doble de cada usuario

Con las señales, por persona y por **artista** y **género** (y época):

| Perfil | Pierde la mitad de su fuerza en | Para qué |
|---|---|---|
| **Histórico** | ~6 meses | lo que le gusta desde siempre (no desaparece por un mes escuchando otra cosa) |
| **Reciente** | ~10 días | la obsesión del momento |

Al recomendar se mezclan (p. ej. 60 % histórico, 40 % reciente; ajustable).

## 4. Una canción = todas sus versiones

Un mismo tema puede estar como pista del disco, videoclip, "letra", directo o remasterizado. Para recomendar se
agrupan en **una canción** con clave `artista normalizado + título limpio` (sin "(Official Video)", "(Letra)",
"[4K]", "ft. …", "Remastered…"). Directo, acústico y remix se marcan aparte: **no** cuentan como la misma versión
de estudio. Al proponer una canción se pone **la mejor versión guardada** (la pista del disco si está, si no la más
puesta). Nunca dos versiones de lo mismo en la misma lista. (La precarga ya hace algo parecido para no bajar
duplicados.)

## 5. Mapa de parecidos (qué se parece a qué)

Se calcula **cada noche** (05:00 de Chile) y se guarda: para cada canción, sus ~50 más parecidas. No se compara
todo con todo: solo con **candidatas** (mismo artista, mismo género, canciones que suenan juntas). Mezcla:

| Fuente | Peso inicial | Comentario |
|---|---|---|
| "Qué suena después" en el historial **propio** | alto | lo más fiable para la radio |
| Mismo artista | medio | buena pista (no tenemos datos del sonido), pero algunos cambian de estilo |
| Mismo género + época parecida (±5 años) | medio | |
| Mismo álbum | bajo | sirve para encontrar candidatas, no para ordenar |
| Lo de **todos** ("qué suena después", "a quien le gusta A le gusta B") | medio | **solo si el usuario lo activa** |
| Relacionados de YouTube Music | — | solo para Descubre (fase 6) |

## 6. Secciones

| Sección | Fase | Cómo se arma |
|---|---|---|
| **Radio de…** (canción o artista) | 1 | desde la semilla: "qué suena después" + parecidas, sin repetir; infinita (pide más al acabar) |
| **Para ti** | 1 | canciones guardadas **no escuchadas** de sus artistas/géneros + parecidas a sus favoritas |
| **Vuelve a escuchar** | 1 | las que ponía mucho hace 1–3 meses y ya no (barata: sale del historial) |
| **Tus mixes** (hasta 3, por sus géneros principales) | 4 | 25 canciones; se renuevan cada noche |
| **Porque escuchaste X** | 4 | parecidas a una canción que le gustó hace poco |
| **Descubre** | 6 | música nueva de YouTube Music parecida a lo suyo; se baja de noche y sale cuando ya está guardada |

**Reglas para todas:**
- Variedad: como mucho 2 del mismo artista cada 10 canciones; géneros mezclados.
- Nada de lo escuchado en las últimas 24 h (salvo "Vuelve a escuchar"); nada marcado "no me gusta".
- **Descubrimiento ajustable** (fase 4): el usuario elige cuánto conocido y cuánto nuevo (p. ej. 75/25 por
  defecto). Hasta entonces, fijo: ~85 % conocido, ~15 % sorpresa.
- Usuario nuevo: lo más escuchado en el servidor + elegir 3 artistas o géneros; en 5–10 canciones ya se adapta.

## 7. "¿Qué te parecieron las recomendaciones?" (opinión del usuario)

Además de lo que se deduce de saltos y favoritas, la app **pregunta de vez en cuando** y deja opinar cuando uno
quiera. Es la señal más directa de si el algoritmo acierta, y cada respuesta **cambia algo concreto** solo para
esa persona.

**Cuándo pregunta** (sin ser pesada):
- Tras una radio o un mix de **10 canciones o más**, al pararla o al acabar.
- Como mucho **una vez por semana** por persona y nunca dos veces seguidas en el mismo tipo (radio, Para ti, mix).
- Siempre se puede cerrar sin contestar ("Ahora no" no cuenta como opinión).
- Y en cualquier momento desde el menú de Radio, Para ti o un mix: **"Opinar sobre estas recomendaciones"**.

**Cómo pregunta:** una tarjeta pequeña, sin salir de la música: **"¿Qué te parecieron?"** con 👍 / 👎 y, si toca
👎 (o quiere afinar), varias opciones marcables y un texto libre opcional:

| Opción | Qué cambia para esa persona |
|---|---|
| 👍 **Me gustaron** | nada; confirma que va bien (y cuenta en las medidas) |
| **Muy repetitivas** (los mismos artistas o canciones) | más variedad: como mucho 1 del mismo artista cada 10, no repetir lo recomendado en 7 días en vez de 1, algo más de descubrimiento |
| **No me gustaron las canciones** | menos sorpresa y más de su gusto de siempre (perfil histórico); lo de todos pesa menos |
| **Ya las conozco todas, quiero cosas nuevas** | más descubrimiento (sube el % nuevo) y más peso a artistas que apenas ha escuchado |
| **Muy raras / nada que ver conmigo** | menos descubrimiento; solo artistas y géneros que ya escucha |
| **Mezcla géneros que no pegan** | la radio se queda más cerca del género de la canción de partida |
| **Quiero más de lo que escucho últimamente** | más peso al perfil reciente |
| **Salen canciones repetidas o versiones raras** (directos, letra, otra versión) | aviso para revisar la agrupación de versiones (sección 4); prefiere la versión de estudio |
| ✍️ **Otra cosa** (texto) | se guarda para leerlo a mano; no cambia nada solo |

**Reglas de los ajustes:**
- Cada respuesta mueve el ajuste **un paso**, con tope (no puede llegar a "0 % de descubrimiento" por una sola
  respuesta), y **vuelve poco a poco** a lo normal en ~1 mes si no se repite. Así una mala tarde no deja el
  recomendador estropeado para siempre.
- Se guarda **con lo que se recomendó** en ese momento (qué sección, desde qué canción y qué canciones salieron),
  para poder ver después qué falló.
- Es de cada uno: no cambia las recomendaciones de los demás.

**Para el dueño:** el panel (`panel.py`) enseña un resumen: 👍 frente a 👎 de la última semana y qué opciones se
marcan más ("muy repetitivas" ×4…), y los textos libres. Es la forma más rápida de saber qué ajustar. También van
en las medidas de la sección 12.

## 8. Cómo lo usan las apps (Android y web)

El servidor manda **qué secciones hay y qué llevan** (`/home`); las apps las dibujan como carrusel o lista, sin
lógica propia. Si una ruta no existe (404) o falla, la app enseña lo de siempre (biblioteca, recientes): así se
puede apagar el recomendador sin romper las apps.

- **Inicio:** las secciones de `/home`.
- **"Iniciar radio"** en el reproductor y en el menú de cada canción y artista.
- **Al acabarse la cola, sigue sola** con la radio de la última canción (se puede apagar en ajustes).
- **"No me gusta"** en el menú de cada canción y en el reproductor.
- **La tarjeta "¿Qué te parecieron?"** (sección 7) y **"Opinar sobre estas recomendaciones"** en el menú de cada
  sección recomendada.
- **Eventos** (sección 9): al empezar, al terminar entera y al cambiar antes de tiempo. Sin conexión se guardan y
  se mandan después (como ya hace la app con favoritas y playlists).
- Web: lo mismo; los eventos salen del reproductor del navegador (`ended`, cambio antes de tiempo).

## 9. Rutas (contrato con las apps)

Todas piden la sesión como siempre.

| Ruta | Qué hace | Fase |
|---|---|---|
| `POST /eventos` | `{eventos: [{tipo, id, segundo, duracion, contexto, causa, cuando}]}` en lote. `tipo`: `inicio`, `entera`, `salto`, `no_me_gusta`, `ya_no_me_gusta`. `contexto`: `radio`, `para_ti`, `mix`, `busqueda`, `biblioteca`, `playlist`, `favoritas`. `causa` (si se cortó): `usuario`, `error`, `dispositivo`, `interrupcion`. `cuando`: hora real (para lo mandado sin conexión) | 1 |
| `GET /home` | `{secciones: [{id, titulo, tipo: canciones\|artistas\|mixes, items}]}` en el orden a enseñar | 1 |
| `GET /radio?desde=cancion:<id>` o `artista:<nombre>` `&ya=<ids puestos>&n=20` | las siguientes `n`; volver a pedir al acercarse al final | 1 |
| `POST /recomendaciones/opinion` | `{contexto: radio\|para_ti\|mix, semilla, gusto: si\|no, opciones: [repetitivas, no_me_gustaron, quiero_nuevas, muy_raras, generos_no_pegan, mas_reciente, versiones_raras], texto, canciones: [ids que se mostraron], cuando}` (sección 7) | 1 (guardar) y 3 (aplicar) |
| `GET /recomendaciones/preguntar?contexto=…` | `{preguntar: bool}`: si toca enseñar la tarjeta ahora (lleva la cuenta de "una vez por semana") | 1 |
| `GET /mixes`, `GET /mix/<id>` | los mixes del usuario | 4 |
| `PUT /ajustes/recomendaciones` | `{descubrir: 0–100, usar_lo_de_todos: bool, radio_al_acabar: bool}` | 4–5 |

## 10. Cuánto cuesta en rendimiento

Con lo de hoy (~2.200 canciones, 7 usuarios) y pensando en ~10.000 canciones y ~20 usuarios. El servidor tiene 4
núcleos y 15 GB de RAM y ahora mismo está casi parado.

| Qué | Coste | Efecto |
|---|---|---|
| Guardar eventos | ~300–1.000 eventos al día, ~100 bytes cada uno: ~0,1 MB/día; se guardan 6 meses (~20 MB) | ninguno |
| Cálculo nocturno (mapa de parecidos, perfiles, mixes) | segundos a ~1 min de CPU una vez por noche, en un **proceso aparte** (para no frenar la API: Python no reparte bien un cálculo largo entre peticiones) | ninguno de día |
| Mapa guardado | ~50 parecidas × 10.000 canciones: ~20–40 MB en disco (en `/var`, no en `/home`, que va justo) y en memoria | poco (de 15 GB) |
| `/home` | precalculado de noche + un retoque con lo reciente: pocos ms | ninguno |
| `/radio` | puntuar ~200 candidatas de la lista ya calculada: <10–20 ms | ninguno |
| Red / internet de casa | nada nuevo: se recomienda lo que ya está guardado | ninguno |
| YouTube (fases 1–5) | **cero** | ninguno |
| YouTube (fase 6, Descubre) | ~30 consultas por noche + descargas a ritmo de persona, dentro del mismo límite que la precarga (300/h) | pequeño; es la parte frágil (no oficial) |

**Resumen: efecto pequeño.** Lo único que hay que hacer bien es que el cálculo nocturno vaya en un proceso
aparte (si no, durante ese minuto la API podría ir a tirones). Los riesgos reales no son de rendimiento sino de
calidad (que recomiende mal) y, en la fase 6, de YouTube.

## 11. Cómo ajustarlo, apagarlo o quitarlo

- **Todo en un módulo aparte** (`server/recomendar.py`) y sus datos en archivos propios (`eventos`, `perfiles`,
  `parecidos` en `/var/lib/musicapp/recomendar/`). No toca la biblioteca ni las favoritas.
- **Ajustar:** los pesos de la sección 2, las vidas medias de la sección 3, las mezclas de la 5, las reglas de la
  6 y lo que mueve cada opinión (sección 7) son constantes con nombre al principio del módulo.
- **Las opiniones** se guardan aparte (`opiniones` en la misma carpeta): se pueden borrar sin tocar lo demás.
- **Apagar:** `RECOMENDAR: "0"` en `docker-compose.yml`: las rutas responden 404 y las apps enseñan lo de siempre.
  Los eventos se pueden seguir guardando o no.
- **Quitar:** borrar el módulo, sus rutas en `app.py`, la línea de compose y la carpeta de datos. Nada más depende
  de él.

## 12. Fases y cómo saber si funciona

| Fase | Qué | Hecha cuando… |
|---|---|---|
| 1 | Eventos (app y web) + botón "No me gusta" + `/radio` y `/home` (Para ti, Vuelve a escuchar) por parecido y "qué suena después" propio + **la tarjeta de opinión** (se guarda y se ve en el panel) | la radio no repite, no pone duplicados y sigue sola al acabar la cola |
| 2 | Perfil doble (histórico + reciente) y versiones agrupadas | lo reciente se nota en días; lo de siempre no desaparece |
| 3 | Afinar con datos + **las opiniones ya cambian el recomendador de cada uno** (sección 7) | ver la tabla de abajo |
| 4 | Mixes diarios + regulador de descubrimiento | |
| 5 | Lo de todos, **opcional** (apagado por defecto) | |
| 6 | Descubre con YouTube Music, bajando de noche | |

**Medidas** (el servidor las saca de los eventos; se miran tras unas semanas):
- % de canciones recomendadas escuchadas enteras frente a las puestas a mano (meta: parecido o mejor).
- % de saltos en la radio (meta: bajar con el tiempo).
- Cuántas recomendaciones acaban en ♡ o en una playlist.
- 👍 frente a 👎 en la tarjeta de opinión, y qué opciones se repiten más (sección 7).

## 13. Riesgos

- **Que recomiende mal al principio:** pocos datos. Por eso empieza con lo seguro (parecido y lo propio) y se
  ajusta con las medidas.
- **YouTube Music no es oficial** (`ytmusicapi`): puede cambiar o fallar. Solo afecta a Descubre (fase 6), que
  puede fallar sin romper lo demás.
- **Privacidad entre amigos:** lo de todos solo si cada uno lo activa; nunca "fulano escuchó…".
- **Eventos sin la app:** sin los eventos de la app no hay saltos ni "entera"; la fase 1 depende de que la app los
  mande.
