// La pantalla de la TV (receptor de Google Cast, web/tv.html). La app manda la cola por Cast (la canción que suena y
// las 2 siguientes: contentUrl = enlace firmado de /stream/<id>/enlace, metadata de música, customData.id) y maneja
// pausa, siguiente, etc.; aquí solo suena y se enseña. Ver README.md, "Pantalla de la TV".
// Seguridad: cualquiera con el App ID podría lanzar este receptor y mandarle cosas, así que solo se acepta audio de
// /stream/… de este mismo dominio e imágenes de aquí, de YouTube (i.ytimg.com) o de YouTube Music
// (*.googleusercontent.com); lo demás se ignora. Nunca hay sesión: el ?t= del enlace vale solo para esa canción y esa
// cuenta (audio, su Canvas y su letra).
const $ = id => document.getElementById(id);
const dur = s => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
let soloAudio = false, actual = null, cvTimer = null, lineas = [], lineaAhora = -2;
let leer = () => ({t: 0, d: 0, pausa: true});   // lo pone el reproductor de Cast (o la demo)

const ID = /^[\w-]{11}$/;
function deAqui(u) {   // audio: solo /stream/<id> de este dominio
  try { const x = new URL(u, location.href); return x.origin === location.origin && /^\/stream\/[\w-]{11}$/.test(x.pathname); }
  catch (e) { return false; }
}
function imagenOk(u) {
  try { const x = new URL(u); return x.protocol === 'https:' && (x.origin === location.origin || x.hostname === 'i.ytimg.com' || /\.googleusercontent\.com$/.test(x.hostname)); }
  catch (e) { return false; }
}
// Deja la ficha solo con lo permitido; null si el audio no es nuestro
function limpia(media) {
  if (!media || !deAqui(media.contentUrl || media.contentId)) return null;
  const m = media.metadata;
  if (m) m.images = (m.images || []).filter(i => i && imagenOk(i.url));
  return media;
}
const imagenDe = media => media?.metadata?.images?.[0]?.url || '';

// La canción que suena
function pinta(media, siguiente) {
  if (!limpia(media)) return;
  const m = media.metadata || {}, u = new URL(media.contentUrl || media.contentId, location.href);
  const id = u.pathname.split('/')[2], t = u.searchParams.get('t') || '';
  if (!ID.test(id)) return;
  document.body.classList.add('con-cancion');
  if (!actual || actual.id !== id) {
    const img = imagenDe(media);
    actual = {id, t, titulo: m.title || '', artista: m.artist || m.albumArtist || '', album: m.albumName || '', dur: media.duration || 0};
    $('titulo').textContent = actual.titulo; $('artista').textContent = actual.artista; $('album').textContent = actual.album;
    if (img) $('tapa').src = img; else $('tapa').removeAttribute('src');
    $('fondo').style.backgroundImage = img ? `url("${img.replace(/["\\]/g, '')}")` : 'none';
    $('media').classList.remove('con-canvas'); $('canvas').removeAttribute('src');
    $('letra').textContent = ''; lineas = []; lineaAhora = -2;
    if (!soloAudio) { canvas(actual); letra(actual); }
  }
  pintaSiguiente(limpia(siguiente));
}
function pintaSiguiente(n) {
  $('sigue').hidden = !n;
  if (!n) return;
  const m = n.metadata || {}, img = imagenDe(n);
  $('sigueT').textContent = m.title || ''; $('sigueA').textContent = m.artist || '';
  if (img) $('sigueImg').src = img; else $('sigueImg').removeAttribute('src');
}

// Canvas, con el ?t= de esa canción. Si se está haciendo (~1 min), se vuelve a preguntar.
async function canvas(c, intento = 0) {
  clearTimeout(cvTimer);
  if (!c.t) return;
  const q = '?t=' + encodeURIComponent(c.t);
  let e = {};
  try { e = await (await fetch(`/canvas/${c.id}/estado${q}`)).json(); } catch (err) { return; }
  if (actual !== c) return;
  if (e.estado === 'listo') {
    const v = $('canvas');
    v.oncanplay = () => { if (actual === c) { $('media').classList.add('con-canvas'); if (!leer().pausa) v.play().catch(() => {}); } };
    v.src = `/canvas/${c.id}${q}`;
  } else if (e.estado === 'haciendo' && intento < 8) cvTimer = setTimeout(() => actual === c && canvas(c, intento + 1), 20000);
}

// Letra con tiempos (la API la saca de lrclib.net): la línea que suena y la siguiente
async function letra(c) {
  if (!c.t) return;
  try {
    const j = await (await fetch(`/lyrics/${c.id}?t=${encodeURIComponent(c.t)}`)).json();
    if (actual !== c || !j.synced) return;
    lineas = j.synced.split('\n').map(l => { const m = l.match(/^\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$/); return m && {at: +m[1] * 60 + +m[2], txt: m[3]}; })
      .filter(x => x && x.txt);
  } catch (e) {}
}
function pintaLetra(t) {
  let i = -1; for (let k = 0; k < lineas.length && lineas[k].at <= t + .3; k++) i = k;
  if (i === lineaAhora) return; lineaAhora = i;
  $('letra').textContent = '';
  for (const l of [lineas[i], lineas[i + 1]]) if (l) { const p = document.createElement('p'); p.textContent = l.txt; $('letra').append(p); }
}

// Cada medio segundo: barra, tiempos, pausa (y el Canvas con ella) y la letra
setInterval(() => {
  if (!actual || soloAudio) return;
  const {t, d, pausa} = leer(), total = d || actual.dur;
  $('progreso').style.width = total ? Math.min(100, 100 * t / total) + '%' : 0;
  $('actual').textContent = dur(t); $('total').textContent = dur(total);
  document.body.classList.toggle('sonando', !pausa); document.body.classList.toggle('en-pausa', pausa);
  const v = $('canvas'); if (v.getAttribute('src')) { if (pausa && !v.paused) v.pause(); else if (!pausa && v.paused) v.play().catch(() => {}); }
  if (lineas.length) pintaLetra(t);
}, 500);

// ---------- Cast (CAF): suena en el <audio> de la página ----------
const demo = new URLSearchParams(location.search).has('demo');
if (window.cast && cast.framework && !demo) {
  const ctx = cast.framework.CastReceiverContext.getInstance(), pm = ctx.getPlayerManager();
  const E = cast.framework.events.EventType, M = cast.framework.messages;
  pm.setMediaElement($('audio'));
  // Lo que no sea nuestro no entra: ni al cargar la cola ni al añadirle canciones
  const rechazo = () => new M.ErrorData(M.ErrorType.LOAD_FAILED);
  pm.setMessageInterceptor(M.MessageType.LOAD, req => {
    if (req.queueData && req.queueData.items) req.queueData.items = req.queueData.items.filter(it => limpia(it.media));
    if (req.media && !limpia(req.media)) return rechazo();
    if (req.queueData && req.queueData.items && !req.queueData.items.length) return rechazo();
    return req;
  });
  pm.setMessageInterceptor(M.MessageType.QUEUE_INSERT, req => {
    req.items = (req.items || []).filter(it => limpia(it.media));
    return req.items.length ? req : new M.ErrorData(M.ErrorType.INVALID_REQUEST);
  });
  const siguiente = () => {
    try { const q = pm.getQueueManager(), items = q.getItems() || [], i = q.getCurrentItemIndex(); return items[i + 1]?.media || null; }
    catch (e) { return null; }
  };
  leer = () => ({t: pm.getCurrentTimeSec() || 0, d: pm.getDurationSec() || 0, pausa: pm.getPlayerState() !== M.PlayerState.PLAYING});
  const ahora = () => { const m = pm.getMediaInformation(); if (m) pinta(m, siguiente()); };
  pm.addEventListener(E.PLAYER_LOAD_COMPLETE, ahora);
  pm.addEventListener(E.MEDIA_STATUS, ahora);
  pm.addEventListener([E.PAUSE, E.PLAYING], () => {
    const v = $('canvas'); if (v.getAttribute('src')) (pm.getPlayerState() === M.PlayerState.PLAYING ? v.play().catch(() => {}) : v.pause());
  });
  pm.addEventListener(E.MEDIA_FINISHED, () => { if (!siguiente()) { actual = null; document.body.classList.remove('con-cancion'); } });
  ctx.addEventListener(cast.framework.system.EventType.READY, () => {
    const caps = ctx.getDeviceCapabilities();
    soloAudio = !!caps && caps[cast.framework.system.DeviceCapabilities.DISPLAY_SUPPORTED] === false;   // parlante
    document.body.classList.toggle('solo-audio', soloAudio);
  });
  const op = new cast.framework.CastReceiverOptions();
  op.maxInactivity = 3600;   // que no se corte la conexión con la app en las pausas largas
  ctx.start(op);
} else if (demo) {
  // Para verla en un navegador: /tv/?demo&id=<id>&t=<firma>&titulo=…&artista=…&album=…&img=…&sig=…&sigA=…&sigImg=…
  const p = new URLSearchParams(location.search), t0 = Date.now();
  if (p.get('id')) {
    leer = () => ({t: (Date.now() - t0) / 1000 + 42, d: 215, pausa: p.has('pausa')});
    const ficha = (titulo, artista, img, album) => ({metadata: {title: titulo || '', artist: artista || '', albumName: album || '', images: img ? [{url: img}] : []}});
    pinta({contentUrl: `${location.origin}/stream/${p.get('id')}?t=${encodeURIComponent(p.get('t') || '')}`, duration: 215,
           ...ficha(p.get('titulo'), p.get('artista'), p.get('img'), p.get('album'))},
          p.get('sig') ? {contentUrl: `${location.origin}/stream/${p.get('id')}`, ...ficha(p.get('sig'), p.get('sigA'), p.get('sigImg'))} : null);
  }
}
