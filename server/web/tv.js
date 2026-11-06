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
// Avisos: en la consola (chrome://inspect desde el PC) y en el registro de la API (POST /tv/registro, con la firma de
// la canción que suena: sin ella el servidor no los acepta). Para depurar la TV sin tenerla delante.
const pendientes = [];
const log = (...a) => {
  const txt = a.map(x => typeof x === 'string' ? x : JSON.stringify(x)).join(' ');
  console.log('[tv]', txt); pendientes.push(txt); if (pendientes.length > 200) pendientes.shift();
};
setInterval(() => {
  if (!pendientes.length || !actual?.t) return;
  fetch('/tv/registro', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: actual.id, t: actual.t, lineas: pendientes.splice(0, 30)})}).catch(() => {});
}, 3000);
addEventListener('error', e => log('error JS:', e.message, `${e.filename}:${e.lineno}`));
addEventListener('unhandledrejection', e => log('promesa rechazada:', String(e.reason)));
// El vídeo del Canvas se crea aquí, cuando hace falta (no en el HTML): así Cast nunca lo toma por el reproductor
const video = () => document.getElementById('canvas');
function videoNuevo() {
  video()?.remove();
  const v = document.createElement('video');
  v.id = 'canvas'; v.muted = true; v.loop = true; v.playsInline = true; v.preload = 'auto';
  v.disableRemotePlayback = true; v.setAttribute('disableremoteplayback', '');
  $('media').append(v);
  return v;
}

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
    $('media').classList.remove('con-canvas'); video()?.remove();
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
    const v = videoNuevo();
    v.oncanplay = () => { if (actual === c) { $('media').classList.add('con-canvas'); if (!leer().pausa) v.play().catch(() => {}); } };
    v.src = `/canvas/${c.id}${q}`;
    log('canvas de', c.id);
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

// ---------- botones (control remoto): ← → eligen, OK pulsa; las teclas multimedia también valen ----------
let acciones = {};   // las pone Cast (en la demo no hacen nada)
const botones = () => [...document.querySelectorAll('#controles button')];
let foco = 2;   // ⏯
function enfoca(i) {
  const b = botones(); foco = Math.max(0, Math.min(b.length - 1, i));
  b.forEach((x, k) => x.classList.toggle('foco', k === foco)); b[foco].focus({preventScroll: true});
}
function pulsa(a) { const f = acciones[a]; const hecho = f ? f() : ''; log('botón:', a, hecho || '(sin Cast)'); if (hecho) avisa(hecho); }
document.getElementById('controles').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { enfoca(botones().indexOf(b)); pulsa(b.dataset.a); } });
addEventListener('keydown', e => {
  const k = e.key, c = e.keyCode;
  const tecla = k === 'MediaPlayPause' || c === 179 ? 'playpausa' : k === 'MediaPlay' || c === 126 ? 'play' : k === 'MediaPause' || c === 127 ? 'pausa'
    : k === 'MediaTrackNext' || c === 176 ? 'siguiente' : k === 'MediaTrackPrevious' || c === 177 ? 'anterior'
    : k === 'MediaFastForward' || c === 228 ? 'mas10' : k === 'MediaRewind' || c === 227 ? 'menos10' : '';
  if (tecla) { e.preventDefault(); return pulsa(tecla); }
  if (k === 'ArrowLeft' || c === 37) { e.preventDefault(); enfoca(foco - 1); }
  else if (k === 'ArrowRight' || c === 39) { e.preventDefault(); enfoca(foco + 1); }
  else if (k === 'Enter' || k === 'Select' || k === 'Accept' || c === 13 || c === 23 || c === 66 || k === ' ') { e.preventDefault(); pulsa(botones()[foco].dataset.a); }
  else if (k === 'ArrowUp' || c === 38) { e.preventDefault(); pulsa('playpausa'); }   // por si el OK no llega a la página
  else log('tecla:', k || '?', c);
});
const ICO_PLAY = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
const ICO_PAUSA = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>';
let iconoPausa = true;
function pintaPlay(pausa) {
  if (iconoPausa === !pausa) return; iconoPausa = !pausa;
  $('bPlay').innerHTML = pausa ? ICO_PLAY : ICO_PAUSA; $('bPlay').setAttribute('aria-label', pausa ? 'Seguir' : 'Pausa');
}

// Aviso grande un momento al pulsar (⏸, ▶, +10 s, ⏭…)
let avisoT = null;
function avisa(txt) {
  const a = $('aviso'); a.textContent = txt; a.classList.add('on');
  clearTimeout(avisoT); avisoT = setTimeout(() => a.classList.remove('on'), 1100);
}

// Cada medio segundo: barra, tiempos, pausa (y el Canvas con ella) y la letra
setInterval(() => {
  if (!actual || soloAudio) return;
  const {t, d, pausa} = leer(), total = d || actual.dur;
  $('progreso').style.width = total ? Math.min(100, 100 * t / total) + '%' : 0;
  $('actual').textContent = dur(t); $('total').textContent = dur(total);
  document.body.classList.toggle('sonando', !pausa); document.body.classList.toggle('en-pausa', pausa); pintaPlay(pausa);
  const v = video(); if (v) { if (pausa && !v.paused) v.pause(); else if (!pausa && v.paused) v.play().catch(() => {}); }
  if (lineas.length) pintaLetra(t);
}, 500);

// ---------- Cast (CAF): suena en el <audio> de la página ----------
const demo = new URLSearchParams(location.search).has('demo');
if (window.cast && cast.framework && !demo) {
  const ctx = cast.framework.CastReceiverContext.getInstance(), pm = ctx.getPlayerManager();
  const E = cast.framework.events.EventType, M = cast.framework.messages;
  const audio = $('audio');
  pm.setMediaElement(audio);
  audio.addEventListener('error', () => log('error del <audio>:', audio.error?.code, audio.error?.message || ''));
  audio.addEventListener('durationchange', () => log('el <audio> dura', Math.round(audio.duration), 's'));
  audio.addEventListener('ended', () => log('el <audio> terminó en el', Math.round(audio.currentTime), 's'));
  setInterval(() => { if (actual) { const r = leer(); log('estado:', Math.round(r.t), '/', Math.round(r.d), r.pausa ? 'pausa' : 'sonando', '· audio', audio.paused ? 'parado' : 'suena', Math.round(audio.currentTime)); } }, 30000);
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
  pm.addEventListener(E.PLAYER_LOAD_COMPLETE, () => {
    log('cargada:', pm.getMediaInformation()?.metadata?.title, '· duración según Cast', pm.getDurationSec(),
        '· el <audio> tiene', audio.currentSrc ? 'el /stream' : 'NADA', '· vídeos en la página', document.querySelectorAll('video').length);
    ahora();
  });
  pm.addEventListener(E.ERROR, e => log('error de Cast:', e.detailedErrorCode, e.error));
  pm.addEventListener(E.MEDIA_STATUS, ahora);
  pm.addEventListener([E.PAUSE, E.PLAYING], () => {
    const v = video(); if (v) (pm.getPlayerState() === M.PlayerState.PLAYING ? v.play().catch(() => {}) : v.pause());
  });
  pm.addEventListener(E.MEDIA_FINISHED, () => { if (!siguiente()) { actual = null; document.body.classList.remove('con-cancion'); } });
  ctx.addEventListener(cast.framework.system.EventType.READY, () => {
    pm.setMediaElement(audio);   // otra vez, por si acaso: el reproductor es el <audio>
    const caps = ctx.getDeviceCapabilities();
    soloAudio = !!caps && caps[cast.framework.system.DeviceCapabilities.DISPLAY_SUPPORTED] === false;   // parlante
    document.body.classList.toggle('solo-audio', soloAudio);
    log('lista · pantalla:', !soloAudio);
  });
  // ---- botones en pantalla (y las teclas multimedia del mando): Cast avisa del cambio a la app o la web
  const salta = paso => {
    try { const r = new M.QueueUpdateRequestData(); r.jump = paso; pm.sendLocalMediaRequest(r); }
    catch (e) { log('no pude saltar de canción:', String(e)); }
  };
  const suena = () => pm.getPlayerState() === M.PlayerState.PLAYING;
  acciones = {
    playpausa: () => { const s = suena(); s ? pm.pause() : pm.play(); return s ? '⏸' : '▶'; },
    play: () => { pm.play(); return '▶'; },
    pausa: () => { pm.pause(); return '⏸'; },
    mas10: () => { pm.seek((pm.getCurrentTimeSec() || 0) + 10); return '+10 s'; },
    menos10: () => { pm.seek(Math.max(0, (pm.getCurrentTimeSec() || 0) - 10)); return '−10 s'; },
    siguiente: () => { salta(1); return '⏭'; },
    anterior: () => {
      const i = (() => { try { return pm.getQueueManager().getCurrentItemIndex(); } catch (e) { return 0; } })();
      if ((pm.getCurrentTimeSec() || 0) > 3 || !i) pm.seek(0); else salta(-1);
      return '⏮';
    },
  };
  const op = new cast.framework.CastReceiverOptions();
  op.maxInactivity = 3600;   // que no se corte la conexión con la app en las pausas largas
  ctx.start(op);
  enfoca(foco);
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
  enfoca(foco);
}
