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
// La llave de la TV: la manda el celular o la web al conectar (canal propio de Cast). Solo vale para mirar y escuchar
// (el servidor no deja cambiar nada con ella) y no se guarda: al cerrar la pantalla se pierde.
const CANAL = 'urn:x-cast:com.yoneapolis.musica';
let llave = null;

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
const idDe = media => { try { return new URL(media.contentUrl || media.contentId, location.href).pathname.split('/')[2]; } catch (e) { return null; } };
const imagenDe = media => media?.metadata?.images?.[0]?.url || '';
// Avisos: en la consola (chrome://inspect desde el PC) y en el registro de la API (POST /tv/registro, con la firma de
// la canción que suena: sin ella el servidor no los acepta). Para depurar la TV sin tenerla delante.
const pendientes = [];
const log = (...a) => {
  const txt = a.map(x => typeof x === 'string' ? x : JSON.stringify(x)).join(' ');
  console.log('[tv]', txt); pendientes.push(txt); if (pendientes.length > 200) pendientes.shift();
};
function mandaAvisos(yaMismo) {   // yaMismo: al cerrarse la página (keepalive: sale aunque se cierre)
  if (!pendientes.length || (!actual?.t && !llave)) return;
  // con la firma de la canción que suena o, si aún no suena nada, con la llave (antes sin canción no salía nada)
  const conFirma = !!actual?.t, body = JSON.stringify({...(conFirma ? {id: actual.id, t: actual.t} : {}), lineas: pendientes.splice(0, 30)});
  fetch('/tv/registro', {method: 'POST', keepalive: !!yaMismo, body,
    headers: {'Content-Type': 'application/json', ...(conFirma ? {} : {Authorization: 'Bearer ' + llave})}}).catch(() => {});
}
setInterval(mandaAvisos, 3000);
addEventListener('pagehide', () => { log('la página se cierra'); mandaAvisos(true); despedida(); });
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
function pinta(media, proximas = []) {
  if (!limpia(media)) return;
  const m = media.metadata || {}, u = new URL(media.contentUrl || media.contentId, location.href);
  const id = u.pathname.split('/')[2], t = u.searchParams.get('t') || '';
  if (!ID.test(id)) return;
  document.body.classList.add('con-cancion');
  if (!actual || actual.id !== id || actual.t !== t) {   // (la misma con firma nueva: venía del espejo, sin Canvas ni letra)
    const img = imagenDe(media);
    actual = {id, t, titulo: m.title || '', artista: m.artist || m.albumArtist || '', album: m.albumName || '', dur: media.duration || 0};
    $('titulo').textContent = actual.titulo; $('artista').textContent = actual.artista; $('album').textContent = actual.album;
    for (const el of [$('tapa'), $('tapaFondo'), $('tapaMini')]) if (img) el.src = img; else el.removeAttribute('src');
    $('fondo').style.backgroundImage = img ? `url("${img.replace(/["\\]/g, '')}")` : 'none';
    $('media').classList.remove('con-canvas'); video()?.remove();
    $('letra').textContent = ''; lineas = []; lineaAhora = -2;
    if (!soloAudio) { canvas(actual); letra(actual); }
    marcaSonando();
  }
  pintaCola(proximas.filter(p => limpia(p.media)));
}
// "A continuación": las próximas (hasta 6) en una fila; con OK sobre una, salta a esa. Solo se repinta si cambia
// (Cast avisa de su estado a menudo y repintar quitaría el elegido).
let colaFirma = '';
function pintaCola(proximas) {
  const lista = proximas.slice(0, 4), firma = lista.map(p => p.media.contentUrl || p.media.contentId).join('|');
  if (firma === colaFirma) return; colaFirma = firma;
  $('cola').hidden = !lista.length;
  const enfocada = document.activeElement?.closest?.('#colaFila');
  $('colaFila').innerHTML = lista.map(p => { const m = p.media.metadata || {}, img = imagenDe(p.media);
    return `<button class="mini f" data-salto="${p.salto}">${img ? `<img src="${esc(img)}" alt="">` : '<span class="ph">♪</span>'}
      <b>${esc(m.title || '')}</b><small>${esc(m.artist || '')}</small><span class="tx"><b>${esc(m.title || '')}</b><small>${esc(m.artist || '')}</small></span></button>`; }).join('')
    + `<button class="mini f todo" data-todo="1"><span class="ph">☰</span><b>Lista completa</b><small>Toda la cola</small><span class="tx"><b>Lista completa</b><small>Toda la cola</small></span></button>`;
  if (enfocada) enfoca($('colaFila').querySelector('.f') || document.querySelector('#controles .grande'));
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
  // la anterior (gris), la que suena (grande) y la siguiente (gris), como en la pestaña Ahora de la web
  for (const [l, c] of [[lineas[i - 1], 'antes'], [lineas[i], 'ahora'], [lineas[i + 1], 'luego']]) if (l) { const p = document.createElement('p'); p.className = c; p.textContent = l.txt; $('letra').append(p); }
}

// ---------- el control remoto: las flechas van al elemento más cercano en esa dirección, OK lo pulsa ----------
// Todo lo que se puede elegir lleva la clase "f" (pestañas, botones, tarjetas, canciones, teclas). Las teclas
// multimedia del mando (⏯, ⏭, ⏮, ⏩, ⏪) valen siempre. En captura y sin dejar que siga: el reproductor de Cast usaba
// ← → para adelantar/atrasar por su cuenta.
let acciones = {};   // las pone Cast (en la demo no hacen nada)
let tocado = Date.now();   // última tecla (para cerrar solo tras un rato sin usarla ni sonar nada)
// solo lo de la pantalla que se ve: las pestañas y, o los botones de "Ahora", o el menú abierto
const visibles = () => [...document.querySelectorAll(eleccionAbierta() ? '#eleccion .f' : vista === 'ahora' ? '#pestanas .f, #controles .f, #colaFila .f' : '#pestanas .f, #menu .f, #panelIr')]
  .filter(el => el.offsetParent !== null && !el.closest('[hidden]'));
function vecino(dir) {
  const todos = visibles(), cur = todos.includes(document.activeElement) ? document.activeElement : null;
  if (!cur) return todos[0];
  const a = cur.getBoundingClientRect(), ax = a.left + a.width / 2, ay = a.top + a.height / 2;
  let mejor = null, md = Infinity;
  for (const el of todos) {
    if (el === cur) continue;
    const r = el.getBoundingClientRect(), dx = r.left + r.width / 2 - ax, dy = r.top + r.height / 2 - ay;
    const h = dir === 'izq' || dir === 'der';
    if (!(dir === 'izq' ? dx < -4 : dir === 'der' ? dx > 4 : dir === 'arr' ? dy < -4 : dy > 4)) continue;
    // gana lo que está a la misma altura (de lado) o en la misma columna (arriba/abajo), como en las apps de TV
    const solapa = h ? r.top < a.bottom && r.bottom > a.top : r.left < a.right && r.right > a.left;
    const d = (h ? Math.abs(dx) : Math.abs(dy)) + (solapa ? 0 : 2000 + 2.5 * (h ? Math.abs(dy) : Math.abs(dx)));
    if (d < md) { md = d; mejor = el; }
  }
  return mejor;
}
function enfoca(el) {
  if (!el) return;
  el.focus({preventScroll: true});
  el.scrollIntoView({block: 'nearest', inline: 'nearest', behavior: 'smooth'});
}
// La interfaz de serie de Cast (en la Chromecast con Google TV: al pausar, título, barra blanca e iconos en
// cuadraditos encima de todo, y se queda el control). La mete Cast DENTRO de esta página (por eso sus iconos salen en
// cuadraditos: la CSP no deja cargar su fuente y la página seguía recibiendo las teclas), así que se puede esconder:
// lo que aparezca en el documento y no sea nuestro, fuera de la vista (y al registro, para saber qué es).
const PROPIOS = new Set(['audio', 'fondo', 'pestanas', 'menu', 'ahora', 'aviso', 'espera', 'canvas', 'eleccion']);
const NO_VISUAL = new Set(['SCRIPT', 'STYLE', 'LINK', 'META', 'HEAD', 'BODY', 'TITLE', 'TEMPLATE']);
function escondeIntrusos() {
  for (const el of [...document.documentElement.children, ...document.body.children]) {
    if (NO_VISUAL.has(el.tagName) || PROPIOS.has(el.id) || el.dataset.escondido) continue;
    el.dataset.escondido = '1'; el.style.setProperty('display', 'none', 'important');
    log('escondo lo que puso Cast:', `<${el.tagName.toLowerCase()}${el.id ? ' id=' + el.id : ''}${el.className && typeof el.className === 'string' ? ' class=' + el.className : ''}>`);
  }
}
new MutationObserver(escondeIntrusos).observe(document.documentElement, {childList: true, subtree: false});
new MutationObserver(escondeIntrusos).observe(document.body, {childList: true});
escondeIntrusos();
// Si algo de fuera (la interfaz de Cast) se queda el control un rato, al volver se elige otra vez lo de antes
let ultimoFoco = null;
addEventListener('focusin', e => { if (e.target?.classList?.contains('f')) ultimoFoco = e.target;
  document.body.classList.toggle('panel-elegido', e.target?.id === 'panelIr'); });
const recuperaFoco = () => { if (document.activeElement && document.activeElement !== document.body) return;
  const vis = visibles(); enfoca(vis.includes(ultimoFoco) ? ultimoFoco : vis[0]); };
addEventListener('focus', () => { log('la página recupera el control'); setTimeout(recuperaFoco, 50); });
addEventListener('blur', () => log('la página pierde el control (otra cosa en pantalla)'));
setInterval(recuperaFoco, 1000);
function pulsa(a) { const f = acciones[a]; const hecho = espejo ? mandoEspejo(a) : f ? f() : ''; log('botón:', a, hecho || '(sin Cast)'); if (hecho) avisa(hecho); recuenta(); }
// Tras play/pausa o un salto, contarlo ya (y otra vez al rato): si el aviso de Cast no llega, el mando (la web o el
// celular) seguía creyendo que sonaba y su play mandaba "pausar" a una TV ya en pausa (le pasó a Juancho, 06-11-2026)
const recuenta = () => { setTimeout(() => cxCuenta(), 400); setTimeout(() => cxCuenta(), 2000); };
document.getElementById('controles').addEventListener('click', e => { const b = e.target.closest('button'); if (b) pulsa(b.dataset.a); });
document.getElementById('panelIr').addEventListener('click', () => { pila = []; irA('ahora'); });
document.getElementById('colaFila').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.todo) return abre(colaCompleta, 'ahora');
  const hecho = espejo ? mandoEspejo('saltaA', +b.dataset.salto) : acciones.saltaA ? acciones.saltaA(+b.dataset.salto) : ''; log('a continuación: salto', b.dataset.salto); if (hecho) avisa(hecho);
});
const DIR = {37: 'izq', 39: 'der', 38: 'arr', 40: 'aba', ArrowLeft: 'izq', ArrowRight: 'der', ArrowUp: 'arr', ArrowDown: 'aba'};
addEventListener('keydown', e => {
  const k = e.key, c = e.keyCode;
  e.stopImmediatePropagation(); tocado = Date.now();
  const tecla = k === 'MediaPlayPause' || c === 179 ? 'playpausa' : k === 'MediaPlay' || c === 126 ? 'play' : k === 'MediaPause' || c === 127 ? 'pausa'
    : k === 'MediaTrackNext' || c === 176 ? 'siguiente' : k === 'MediaTrackPrevious' || c === 177 ? 'anterior'
    : k === 'MediaFastForward' || c === 228 ? 'mas10' : k === 'MediaRewind' || c === 227 ? 'menos10' : '';
  if (tecla) { e.preventDefault(); return pulsa(tecla); }
  const dir = DIR[k] || DIR[c];
  if (dir) { e.preventDefault(); return enfoca(vecino(dir)); }
  if (k === 'Enter' || k === 'Select' || k === 'Accept' || c === 13 || c === 23 || c === 66 || k === ' ') {
    e.preventDefault();
    const el = visibles().includes(document.activeElement) ? document.activeElement : null;
    return el ? el.click() : enfoca(visibles()[0]);
  }
  // Atrás: dentro de los menús vuelve (como en Spotify); en Ahora no hace nada (salir cerraba la pantalla y desde la
  // TV no se puede volver a abrir). Si el sistema se la queda antes que la página, cierra igual: ver el registro.
  if (['GoBack', 'BrowserBack', 'Backspace', 'Escape', 'Back'].includes(k) || [4, 8, 27, 166, 461, 10009].includes(c)) {
    e.preventDefault(); log('atrás:', k, c);
    if (eleccionAbierta()) return cierraEleccion();
    if (vista === 'detalle') return volver();
    if (vista !== 'ahora') { pila = []; return irA('ahora'); }
    return avisa('Para salir: ⏻ Salir, arriba');
  }
  log('tecla:', k || '?', c); mandaAvisos(true);
}, true);
for (const ev of ['keyup', 'keypress']) addEventListener(ev, e => {   // lo mismo al soltar (por si Cast la escucha ahí)
  if ([37, 38, 39, 40, 13, 23, 66].includes(e.keyCode) || /^(Arrow|Enter|Select|Accept)/.test(e.key)) { e.stopImmediatePropagation(); e.preventDefault(); }
}, true);

// ---------- menús (con la llave: Inicio, Biblioteca, Buscar, playlists, artistas, álbumes) ----------
const esc = t => String(t ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const imgOk = u => u && imagenOk(u) ? esc(u) : '';
async function api(ruta, op = {}) {
  if (!llave) throw new Error('sin llave');
  const r = await fetch(ruta, {...op, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + llave}});
  if (!r.ok) throw new Error(ruta + ': ' + r.status);
  return r.json();
}
let vista = 'ahora', pila = [], listas = {}, nl = 0;   // listas: las canciones de cada fila o lista que se pinta
const guarda = canciones => { const k = 'l' + (++nl); listas[k] = canciones; return k; };
function irA(v, render) {
  vista = v;
  document.querySelectorAll('#pestanas button').forEach(b => b.classList.toggle('on', b.dataset.vista === v || (v === 'detalle' && b.dataset.vista === pila[0]?.base)));
  document.body.classList.toggle('con-menu', v !== 'ahora');
  $('menu').hidden = v === 'ahora';
  if (v === 'ahora') { const e = $('ahora'); e.classList.remove('entra'); void e.offsetWidth; e.classList.add('entra');
    return enfoca(document.querySelector('#controles .grande')); }
  $('menu').innerHTML = '<div class="scroll"><p class="vacio">Cargando…</p></div>';
  (render || VISTAS[v])().then(h => { $('menu').innerHTML = `<div class="scroll">${h}</div>`;
    enfoca($('menu').querySelector('[data-foco]') || visibles().find(el => el.closest('#menu'))); })
    .catch(e => { $('menu').innerHTML = `<div class="scroll"><p class="vacio">No pude cargarlo (${esc(e.message)})</p></div>`; log('menú:', e.message); });
}
function abre(render, base) { pila.push({base: base || (vista === 'detalle' ? pila[pila.length - 1]?.base : vista), render}); irA('detalle', render); }
function volver() { const q = pila.pop(), p = pila[pila.length - 1]; p ? irA('detalle', p.render) : irA(q?.base === 'ahora' ? 'ahora' : VISTA_BASE); }
let VISTA_BASE = 'inicio';
document.getElementById('pestanas').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.salir !== undefined) return salir(b);
  pila = []; VISTA_BASE = b.dataset.vista; irA(b.dataset.vista); });
// ⏻ Salir: cierra la pantalla de la TV (la web o el celular ven que se desconectó y se quedan con la música en pausa).
// El primer OK pregunta y solo el segundo, en 4 s, cierra: así no se sale sin querer.
let salirT = 0;
function salir(b) {
  if (Date.now() - salirT > 4000) { salirT = Date.now(); b.textContent = '¿Salir? Pulsa OK otra vez';
    setTimeout(() => { if (Date.now() - salirT >= 4000) b.textContent = '⏻ Salir'; }, 4100); return; }
  log('salir con el botón'); mandaAvisos(true); despedida();
  try { cast.framework.CastReceiverContext.getInstance().stop(); } catch (e) { avisa('No pude cerrarla'); }
}
const tarjetas = (lista, k) => lista.map((s, i) => `<button class="tarjeta f" data-l="${k}" data-i="${i}">${imgOk(s.thumb) ? `<img src="${imgOk(s.thumb)}" alt="">` : '<span class="ph">♪</span>'}
  <b>${esc(s.title)}</b><small>${esc(s.artist || '')}</small></button>`).join('');
const artistas = lista => lista.map(a => `<button class="tarjeta redonda f" data-artista="${esc(a.name)}">${imgOk(a.thumb) ? `<img src="${imgOk(a.thumb)}" alt="">` : '<span class="ph">👤</span>'}
  <b>${esc(a.name)}</b><small>${a.songs || ''} canciones</small></button>`).join('');
const filas = (lista, k) => lista.map((s, i) => `<button class="cancion f${s.id === actual?.id ? ' sonando' : ''}" data-l="${k}" data-i="${i}" data-id="${esc(s.id)}"><span class="n">${s.id === actual?.id ? '▶' : i + 1}</span>${imgOk(s.thumb) ? `<img src="${imgOk(s.thumb)}" alt="">` : '<img alt="">'}
  <div><b>${esc(s.title)}</b><small>${esc([s.artist, s.album].filter(Boolean).join(' · '))}</small></div><span>${s.duration ? dur(s.duration) : ''}</span></button>`).join('');
const volverBtn = () => '<div class="acciones volver"><button class="pill f" data-accion="volver">← Volver</button></div>';
function cabecera(img, titulo, sub, k, redonda) {
  return `${volverBtn()}<div class="cabecera${redonda ? ' redonda' : ''}">${imgOk(img) ? `<img src="${imgOk(img)}" alt="">` : ''}<div><h1>${esc(titulo)}</h1><p>${esc(sub)}</p>
    <div class="acciones"><button class="pill main f" data-l="${k}" data-i="0">▶ Reproducir</button><button class="pill f" data-l="${k}" data-mezcla="1">🔀 Aleatorio</button></div></div></div>`;
}
const VISTAS = {
  async inicio() {
    const [home, favs, pls, me] = await Promise.all([api('/home').catch(() => ({secciones: []})), api('/favorites').catch(() => ({songs: []})),
                                                     api('/playlists').catch(() => ({playlists: []})), api('/me').catch(() => ({}))]);
    const hora = new Date().getHours(), nombre = (me.name || me.user?.name || '').split(' ')[0];
    let h = `<div class="saludo">${hora < 12 ? 'Buenos días' : hora < 20 ? 'Buenas tardes' : 'Buenas noches'}${nombre ? ', ' + esc(nombre) : ''}</div>`;
    plsCache = pls.playlists;
    const accesos = [`<button class="acceso f" data-favs="1"><span class="ph">♥</span><span>Me gusta</span></button>`,
      ...pls.playlists.slice(0, 5).map((p, i) => { const img = p.songs.find(x => imgOk(x.thumb))?.thumb;
        return `<button class="acceso f" data-pl="${i}">${img ? `<img src="${imgOk(img)}" alt="">` : '<span class="ph">🎵</span>'}<span>${esc(p.name)}</span></button>`; })];
    h += `<div class="accesos">${accesos.join('')}</div>`;
    for (const s of home.secciones) {
      if (s.tipo === 'canciones') h += `<h2>${esc(s.titulo)}</h2><div class="fila">${tarjetas(s.items.slice(0, 20), guarda(s.items))}</div>`;
      else if (s.tipo === 'artistas') h += `<h2>${esc(s.titulo)}</h2><div class="fila">${artistas(s.items.slice(0, 20))}</div>`;
    }
    if (favs.songs.length) h += `<h2>Tus Me gusta</h2><div class="fila">${tarjetas(favs.songs.slice(0, 20), guarda(favs.songs))}</div>`;
    if (pls.playlists.length) h += `<h2>Tus playlists</h2><div class="fila">${playlists(pls.playlists)}</div>`;
    return h || '<p class="vacio">Todavía no hay nada tuyo: pon música desde la app o la web.</p>';
  },
  async biblioteca() {
    const [favs, pls, arts] = await Promise.all([api('/favorites'), api('/playlists'), api('/artists?orden=tuyos')]);
    const mios = arts.artists.filter(a => a.tuyo).slice(0, 30);
    return `<h2>Playlists</h2><div class="rejilla"><button class="tarjeta f" data-favs="1"><span class="ph">♥</span><b>Me gusta</b><small>${favs.songs.length} canciones</small></button>
      ${playlists(pls.playlists)}</div><h2>Tus artistas</h2><div class="rejilla">${artistas(mios.length ? mios : arts.artists.slice(0, 30))}</div>`;
  },
  async buscar() { return buscador(); },
};
let plsCache = [];
function playlists(pls) {
  plsCache = pls;
  return pls.map((p, i) => { const img = p.songs.find(s => imgOk(s.thumb))?.thumb;
    return `<button class="tarjeta f" data-pl="${i}">${img ? `<img src="${imgOk(img)}" alt="">` : '<span class="ph">🎵</span>'}<b>${esc(p.name)}</b><small>${p.songs.length} canciones</small></button>`; }).join('');
}
const lista = (titulo, sub, img, canciones, redonda) => async () => {
  const k = guarda(canciones);
  return cabecera(img, titulo, sub, k, redonda) + (canciones.length ? filas(canciones.slice(0, 300), k) : '<p class="vacio">No hay canciones.</p>');
};
const artista = nombre => async () => {
  const a = await api('/artist?name=' + encodeURIComponent(nombre));
  const todas = a.todas || a.loose || [], k = guarda(todas);
  const img = a.albums.find(x => x.thumb)?.thumb || todas.find(x => x.thumb)?.thumb;
  let h = cabecera(img, a.name, `${a.songs} canciones · ${a.albums.length} álbumes`, k, true);
  h += `<h2>Populares</h2>${filas(todas.slice(0, 20), k)}`;
  if (a.albums.length) h += `<h2>Álbumes</h2><div class="fila">${a.albums.map(al => `<button class="tarjeta f" data-album="${esc(al.name)}" data-de="${esc(a.name)}">
    ${imgOk(al.thumb) ? `<img src="${imgOk(al.thumb)}" alt="">` : '<span class="ph">💿</span>'}<b>${esc(al.name)}</b><small>${esc(al.year || '')}</small></button>`).join('')}</div>`;
  return h;
};
// ---------- elegir qué hacer con una canción si ya suena algo: ⏭ Que suene después · ➕ Al final · ▶ Ponerla ya ----------
// (en la TV no hay ⋮ ni pulsación larga cómoda: un OK más y lo normal, "después", ya viene elegido; Atrás la cierra)
const hayLista = () => !!((cx.propia && actual) || espejo);
const eleccionAbierta = () => !!document.getElementById('eleccion');
let eleccionDe = null;   // {lista, i, volverA: el elemento elegido antes}
// enLista: la canción es de una playlist, álbum o artista abiertos: además, "reproducir esta lista desde aquí"
function abreEleccion(lista, i, desde, enLista) {
  const s = lista[i]; if (!s) return;
  eleccionDe = {lista, i, volverA: desde};
  const el = document.createElement('div'); el.id = 'eleccion';
  el.innerHTML = `<div class="caja"><b>${esc(s.title || '')}</b><small>${esc(s.artist || '')}</small>
    <button class="f" data-e="ya">▶ Ponerla ya <small>tu lista sigue después</small></button>
    <button class="f" data-e="despues">⏭ Que suene después</button><button class="f" data-e="final">➕ Al final de la cola</button>
    ${enLista ? '<button class="f" data-e="lista">🔁 Reproducir esta lista desde aquí <small>cambia tu lista</small></button>' : ''}</div>`;
  el.addEventListener('click', e => { const x = e.target.closest('[data-e]'); if (x) elige(x.dataset.e); });
  document.body.append(el);
  enfoca(el.querySelector('.f'));
}
function cierraEleccion() { document.getElementById('eleccion')?.remove(); const v = eleccionDe?.volverA; eleccionDe = null; if (v && document.contains(v)) enfoca(v); }
async function elige(que) {
  const {lista, i} = eleccionDe || {}; cierraEleccion();
  const s = lista?.[i]; if (!s) return;
  if (que === 'lista') return tocar(lista, i);
  const hecho = await meteEnCola(s, que !== 'final', que === 'ya');
  avisa(hecho ? {ya: '▶', despues: 'Sonará después', final: 'Al final de la cola'}[que] : 'No pude añadirla', 1600);
}
// Meter una canción en lo que suena (después de la actual o al final; ya: después y saltar a ella, la lista sigue
// detrás), suene aquí o en otro dispositivo (espejo)
async function meteEnCola(s, despues, ya = false) {
  try {
    if (espejo) {   // suena en otro: su cola con la canción metida, como orden (sin "nueva": no corta allí)
      const c = (espejo.s.cola?.length ? espejo.s.cola : [espejo.s.cancion]).filter(x => x.id !== s.id || x.id === espejo.s.cancion.id);
      const qi = Math.max(0, c.findIndex(x => x.id === espejo.s.cancion.id));
      const cola = [...c]; cola.splice(despues ? qi + 1 : cola.length, 0, s);
      await api('/conectar/orden', {method: 'POST', body: JSON.stringify({disp: cx.disp, tipo: 'cola',
        datos: ya ? {cola, qi: qi + 1, nueva: true, radio: !!espejo.s.radio} : {cola, qi, radio: !!espejo.s.radio}})});
      log('meto', s.title, despues ? 'después' : 'al final', 'en lo que suena en', espejo.nombre);
      return true;
    }
    const ok = await acciones.mete?.(s, despues);
    if (ok && ya) acciones.siguiente();
    return ok;
  } catch (e) { log('no pude meterla en la cola:', e.message); return false; }
}
// La lista completa: toda la cola de la TV (la de Cast), la que suena marcada y elegida; OK salta a esa
async function colaCompleta() {
  const {items, i} = acciones.cola ? acciones.cola() : {items: [], i: 0};
  const filas = items.map((it, k) => { const m = it.media?.metadata || {}, img = imagenDe(it.media), ya = k === i;
    return `<button class="cancion f${ya ? ' sonando' : ''}" data-salto="${k - i}"${ya ? ' data-foco="1"' : ''}><span class="n">${ya ? '▶' : k + 1}</span>${img ? `<img src="${esc(img)}" alt="">` : '<img alt="">'}
      <div><b>${esc(m.title || '')}</b><small>${esc([m.artist, m.albumName].filter(Boolean).join(' · '))}</small></div><span>${it.media?.duration ? dur(it.media.duration) : ''}</span></button>`; });
  return `${volverBtn()}<div class="cabecera"><div><h1>Lista completa</h1><p>${items.length} canciones · va en la ${i + 1}</p></div></div>`
    + (filas.length ? filas.join('') : '<p class="vacio">No hay nada en la cola.</p>');
}
// Buscar: teclado en pantalla; los resultados salen debajo al escribir (de lo guardado, sin YouTube)
let consulta = '', buscaT = null;
const TECLAS = 'abcdefghijklmnñopqrstuvwxyz0123456789'.split('');
function buscador() {
  return `<div class="consulta" id="consulta">${esc(consulta)}</div><div class="teclado">${TECLAS.map(t => `<button class="f" data-tecla="${t}">${t}</button>`).join('')}
    <button class="f ancha" data-tecla=" ">espacio</button><button class="f ancha" data-tecla="⌫">⌫ borrar</button></div><div id="resultados"></div>`;
}
function escribe(t) {
  consulta = t === '⌫' ? consulta.slice(0, -1) : (consulta + t).slice(0, 60);
  $('consulta').textContent = consulta;
  clearTimeout(buscaT); buscaT = setTimeout(busca, 450);
}
async function busca() {
  const q = consulta.trim();
  if (!q) { $('resultados').innerHTML = ''; return; }
  try {
    const r = await api(`/search?q=${encodeURIComponent(q)}&yt=0&limit=20`);
    if (q !== consulta.trim()) return;
    const k = guarda(r.results.filter(s => s.where === 'guardada'));
    $('resultados').innerHTML = (r.artists.length ? `<h2>Artistas</h2><div class="fila">${artistas(r.artists)}</div>` : '')
      + (listas[k].length ? `<h2>Canciones</h2>${filas(listas[k], k)}` : '<p class="vacio">Nada guardado con eso.</p>');
  } catch (e) { log('buscar:', e.message); }
}
// La canción que suena, marcada en las listas que se ven (al cambiar de canción)
function marcaSonando() {
  document.querySelectorAll('#menu .cancion').forEach(b => { const on = b.dataset.id === actual?.id;
    b.classList.toggle('sonando', on); const n = b.querySelector('.n'); if (n) n.textContent = on ? '▶' : +b.dataset.i + 1; });
}
// Qué hace cada cosa al pulsarla con OK
document.getElementById('menu').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  const d = b.dataset;
  if (d.accion === 'volver') return volver();
  if (d.salto !== undefined) { const n = +d.salto; if (n && acciones.saltaA) avisa(acciones.saltaA(n)); pila = []; return irA('ahora'); }
  if (d.tecla) return escribe(d.tecla);
  if (d.artista) return abre(artista(d.artista));
  if (d.album) return abre(async () => { const a = await api(`/album?artist=${encodeURIComponent(d.de)}&name=${encodeURIComponent(d.album)}`);
    return lista(a.name, `${a.artist}${a.year ? ' · ' + a.year : ''}`, a.thumb || a.songs[0]?.thumb, a.songs)(); });
  if (d.pl) { const p = plsCache[+d.pl]; return abre(lista(p.name, `Playlist · ${p.songs.length} canciones`, p.songs.find(s => s.thumb)?.thumb, p.songs)); }
  if (d.favs) return abre(async () => { const f = await api('/favorites'); return lista('Me gusta', `${f.songs.length} canciones`, f.songs[0]?.thumb, f.songs)(); });
  // una canción suelta (tarjeta o fila) con algo ya sonando: elegir qué hacer, sin romper la lista que suena.
  // ▶ Reproducir / 🔀 Aleatorio de una lista (pill) la cambian directamente
  if (d.l && !b.classList.contains('pill') && hayLista()) return abreEleccion(listas[d.l] || [], +(d.i || 0), b, vista === 'detalle');
  if (d.l) return tocar(listas[d.l] || [], +(d.i || 0), !!d.mezcla);
});
// Cerrar sola tras 30 min sin sonar nada ni tocar el control (Cast ya no la cierra a los 5 min: ver disableIdleTimeout)
setInterval(() => { if (leer().pausa && Date.now() - tocado > 30 * 60 * 1000) { log('30 min sin usar: cierro'); try { cast.framework.CastReceiverContext.getInstance().stop(); } catch (e) {} } }, 60000);
let tocar = async () => {};   // la pone Cast: poner una lista en la TV, que suena sola
let cambiaAlrededor = async () => false;   // también: cambiar la cola sin cortar la que suena
let cxCuenta = async () => {}, cxHaz = () => {};   // también (ver abajo, "varios dispositivos")
const cx = {disp: (() => { try { let d = localStorage.getItem('dispositivo'); if (!d) localStorage.setItem('dispositivo', d = 'tv' + Math.random().toString(36).slice(2, 12)); return d; }
                           catch (e) { return 'tv' + Math.random().toString(36).slice(2, 12); } })(),
            nombre: 'TV', propia: false, cola: [], radio: false, colaV: 0, colaContadaV: -1, orden: 0, ultima: 0, tomada: 0};
let eraActiva = false;   // en la última respuesta, la que sonaba era la TV
let cxCorta = null;   // para cortar la espera larga de /conectar (al cambiar de cuenta)
// Otra persona conecta la TV con SU cuenta (otra llave): gana la última (como en Spotify), pero limpio. La TV se
// despide de la cuenta de antes (POST /conectar/salir con la llave vieja: sus dispositivos lo ven ya, no a los 45 s),
// deja lo de esa cuenta (espejo, órdenes, "suena aquí"), recarga los menús con lo de la nueva y avisa quién la usa.
const quien = k => fetch('/me', {headers: {Authorization: 'Bearer ' + k}}).then(r => r.ok ? r.json() : null).catch(() => null)
  .then(j => j && {id: j.email || j.user?.email || j.sub || j.user?.sub || '', nombre: (j.name || j.user?.name || 'otra persona').split(' ')[0]});
async function cambioDeCuenta(vieja, nueva, t0) {
  const [antes, ahora] = await Promise.all([quien(vieja), quien(nueva)]);
  if (!ahora || (antes && antes.id === ahora.id)) return;   // la misma persona que vuelve a conectar: nada
  log('otra cuenta conecta la TV:', ahora.nombre);
  fetch('/conectar/salir', {method: 'POST', keepalive: true, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + vieja},
                            body: JSON.stringify({disp: cx.disp})}).catch(() => {});
  quitaEspejo(); eraActiva = false; cx.orden = 0;
  if (cx.tomada < t0) cx.propia = false;   // (si ya puso la cola de la nueva, esa sí es suya)
  cxCorta?.abort();
  avisa('Ahora la usa ' + ahora.nombre, 4000);
  if (vista !== 'ahora') { pila = []; irA(VISTA_BASE); }
}
// Espejo: si la música suena en otro dispositivo (la pasaron al PC o al celular), la TV enseña eso (portada, título,
// barra, "Sonando en PC · Chrome") en vez de quedarse en su última canción, y sus botones lo manejan a distancia
// (órdenes de /conectar). Al devolverle la música, ya tiene la canción a la vista.
let espejo = null;   // {s: lo que suena allí, nombre, recibido}
const leerEspejo = () => { const s = espejo.s;
  return {t: Math.min((s.pos || 0) + (s.pausa ? 0 : (Date.now() - espejo.recibido) / 1000), s.duracion || 1e9), d: s.duracion || s.cancion?.duration || 0, pausa: !!s.pausa}; };
function ponEspejo(s, nombre) {
  const antes = espejo?.s?.cancion?.id;
  espejo = {s, nombre, recibido: Date.now()};
  $('dondeSuena').textContent = 'Sonando en ' + nombre;
  if (antes === s.cancion.id && actual?.id === s.cancion.id) return;
  const media = c => ({contentUrl: `${location.origin}/stream/${c.id}?t=`, duration: c.duration || 0,
    metadata: {title: c.title || '', artist: c.artist || '', albumName: c.album || '', images: c.thumb ? [{url: c.thumb}] : []}});
  const cola = s.cola || [], qi = Math.max(0, cola.findIndex(x => x.id === s.cancion.id));
  pinta(media(s.cancion), cola.slice(qi + 1, qi + 7).map((c, k) => ({media: media(c), salto: k + 1})));
}
function quitaEspejo() { if (!espejo) return; espejo = null; $('dondeSuena').textContent = 'Sonando en la TV'; }
// los botones de la TV con espejo: órdenes para el dispositivo donde suena
function mandoEspejo(a, n) {
  const s = espejo.s, t = leerEspejo().t, o = (tipo, datos = {}) => api('/conectar/orden', {method: 'POST', body: JSON.stringify({disp: cx.disp, tipo, datos})}).catch(e => log('orden:', e.message));
  if (a === 'playpausa' || a === 'play' || a === 'pausa') { const pausar = a === 'pausa' || (a === 'playpausa' && !s.pausa); o('pausa', {pausar}); s.pausa = pausar; s.pos = t; espejo.recibido = Date.now(); return pausar ? '⏸' : '▶'; }
  if (a === 'siguiente') { o('siguiente'); return '⏭'; }
  if (a === 'anterior') { o('anterior'); return '⏮'; }
  if (a === 'mas10' || a === 'menos10') { const pos = Math.max(0, t + (a === 'mas10' ? 10 : -10)); o('ir', {pos}); s.pos = pos; espejo.recibido = Date.now(); return a === 'mas10' ? '+10 s' : '−10 s'; }
  if (a === 'saltaA' && s.cola?.length) { const qi = Math.max(0, s.cola.findIndex(x => x.id === s.cancion.id)) + n;
    o('cola', {cola: s.cola, qi, nueva: true, radio: !!s.radio}); return '⏭'; }
  return '';
}
// Al devolverle la música: si la TV ya tiene cargada esa misma canción y la misma cola (lo normal al ir y volver),
// solo va al segundo y suena, sin volver a pedir los enlaces ni cargarlo todo (tardaba unos segundos y la página y el
// celular se veían "pegados" mientras). Si no, false y se pone la cola entera (tocar).
function sigoAqui(s, cola) {
  const items = acciones.cola ? acciones.cola().items : [], ahora = items[acciones.cola().i];
  if (!ahora || idDe(ahora.media) !== s.cancion.id || items.length !== cola.length) return false;
  if (!items.every((it, k) => idDe(it.media) === cola[k].id)) return false;
  quitaEspejo();
  cx.propia = true; cx.cola = cola; cx.radio = !!s.radio; cx.colaV++; cx.tomada = Date.now();
  acciones.ir?.(s.pos || 0); acciones.play?.();
  log('sigo con lo que ya tenía, en el', Math.round(s.pos || 0));
  recuenta(); cxCuenta(true);
  return true;
}
// Si a los 5 s de tener la llave nadie le ha pasado una cola (el mensaje de la web o la app se perdió o tardó: la
// pantalla puede tardar ~20 s en cargar), la TV pregunta a la API qué suena en la cuenta y lo pone ella.
// (con espejo, "actual" es lo de otro dispositivo, no algo puesto aquí: antes eso lo cortaba)
async function siNadaSuena() { if ((actual && !espejo) || cx.propia || cx.ido) return; return tomaDeLaCuenta('nadie me pasó la cola'); }
// "Coge lo que suena en la cuenta": lo pide la web al conectar (mensaje {tipo:"toma"}) en vez de mandar la cola por
// Cast (un mensaje de Cast tiene tope de tamaño: con 300 canciones a veces no llegaba y la TV no sonaba)
async function tomaDeLaCuenta(por) {
  try {
    const r = await api(`/conectar?disp=${cx.disp}&nombre=${encodeURIComponent(cx.nombre)}&desde=-1`), s = r.sonando;
    if (!s?.cancion) { if (vista === 'ahora' && !actual) irA('inicio'); return log(por + ': en la cuenta no suena nada'); }
    log(por + ': pongo lo que suena en la cuenta,', s.cancion.title || s.cancion.id);
    const todas = s.cola?.length ? s.cola : [s.cancion], j = Math.max(0, todas.findIndex(x => x.id === s.cancion.id));
    const desde = Math.max(0, j - 20);   // la TV pone 300 como mucho: alrededor de la que suena
    tocar(todas.slice(desde, desde + 300), j - desde, false, s.pos || 0, !!s.radio);
  } catch (e) { log('no pude preguntar qué suena:', e.message); }
}
// Al cerrarse, la TV se despide (POST /conectar/salir): si no, los demás la veían "sonando" hasta 45 s más (VIVO del
// servidor) aunque ya no estuviera. keepalive: sale aunque la página se esté cerrando. Después ya no pregunta más.
function despedida() {
  if (!llave || cx.ido) return; cx.ido = true;
  try { fetch('/conectar/salir', {method: 'POST', keepalive: true, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + llave},
                                  body: JSON.stringify({disp: cx.disp})}).catch(() => {}); } catch (e) {}
}
async function cxBucle() {
  let desde = 0;
  while (llave && !cx.ido) {
    try {
      cxCorta = new AbortController();
      const r = await api(`/conectar?disp=${cx.disp}&nombre=${encodeURIComponent(cx.nombre)}&desde=${desde}`, {signal: cxCorta.signal});
      desde = r.v;
      if (r.desconectar) {   // la web o la app (cualquiera, no solo la que la conectó) pidió cerrar la pantalla
        log('me piden cerrar desde otro dispositivo'); mandaAvisos(true); despedida();
        try { cast.framework.CastReceiverContext.getInstance().stop(); } catch (e) {}
        return;
      }
      if (r.activo === cx.disp) quitaEspejo();
      else if (r.activo && r.activo_vivo && r.sonando?.cancion && Date.now() - cx.tomada > 5000)
        ponEspejo(r.sonando, r.dispositivos?.find(d => d.id === r.activo)?.nombre || 'otro dispositivo');
      else quitaEspejo();
      if (r.activo === cx.disp) {
        // me pasaron la música ("Dónde suena" → TV) sin ser mía: la retomo desde lo que tiene el servidor (cola y segundo)
        const s = r.sonando;
        if (!cx.propia && !eraActiva && s?.cancion && Date.now() - cx.tomada > 5000) {
          log('me pasan la música:', s.cancion.title || s.cancion.id);
          const todas = s.cola?.length ? s.cola : [s.cancion], j = Math.max(0, todas.findIndex(x => x.id === s.cancion.id));
          const desde = Math.max(0, j - 20), cola = todas.slice(desde, desde + 300);
          if (!sigoAqui(s, cola)) tocar(cola, j - desde, false, s.pos || 0, !!s.radio);
        }
        eraActiva = true;
        const nuevas = (r.ordenes || []).filter(o => o.n > cx.orden);
        for (const o of nuevas) { cx.orden = o.n; log('orden de otro dispositivo:', o.tipo, o.tipo === 'pausa' ? (o.datos?.pausar ? 'pausar' : 'seguir') : ''); cxHaz(o); }
        // recontar enseguida solo tras pausar o mover la barra: tras siguiente/anterior/otra cola, la TV aún tiene la
        // de antes cargando y la contaría (los mandos volvían atrás); al cargar la nueva ya la cuenta sola
        if (nuevas.some(o => o.tipo === 'pausa' || o.tipo === 'ir')) recuenta();
        if (nuevas.length) cxCuenta();
      } else if (r.activo && r.activo_vivo && Date.now() - cx.tomada > 5000) {   // otro se quedó la música: la TV se pausa
        // (no justo después de poner una cola: la respuesta que llega aún puede ser de antes de quedársela la TV). Sea
        // la cola de quien sea: antes solo si era propia, y al pasarla al celular seguía sonando también aquí
        if (cx.propia || eraActiva) {
          cx.propia = false; log('ahora suena en', r.dispositivos?.find(d => d.id === r.activo)?.nombre || r.activo);
          if (!leer().pausa) acciones.pausa?.();
        }
        eraActiva = false;
      }
    } catch (e) { if (e.name === 'AbortError') { desde = -1; continue; } await new Promise(ok => setTimeout(ok, 5000)); }
  }
}
const ICO_PLAY = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
const ICO_PAUSA = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>';
let iconoPausa = true;
function pintaPlay(pausa) {
  if (iconoPausa === !pausa) return; iconoPausa = !pausa;
  $('bPlay').innerHTML = pausa ? ICO_PLAY : ICO_PAUSA; $('bPlay').setAttribute('aria-label', pausa ? 'Seguir' : 'Pausa');
}

// Aviso grande un momento al pulsar (⏸, ▶, +10 s, ⏭…)
let avisoT = null;
function avisa(txt, ms = 1100) {
  const a = $('aviso'); a.textContent = txt; a.classList.add('on');
  clearTimeout(avisoT); avisoT = setTimeout(() => a.classList.remove('on'), ms);
}

// Cada medio segundo: barra, tiempos, pausa (y el Canvas con ella) y la letra
setInterval(() => {
  if (!actual || soloAudio) return;
  const {t, d, pausa} = espejo ? leerEspejo() : leer(), total = d || actual.dur;
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
  let cargandoPropia = 0;   // cuántas cargas propias van (pueden solaparse: la web manda 1 canción y al rato 11)
  // Todo como vídeo (ver el <video id="audio"> de tv.html): también lo que mande la app o la web por Cast
  const comoVideo = m => { if (m && /^audio\//.test(m.contentType || '')) m.contentType = 'video/webm'; };
  pm.setMessageInterceptor(M.MessageType.LOAD, req => {
    comoVideo(req.media); (req.queueData?.items || []).forEach(it => comoVideo(it.media));
    // Una cola nueva de un celular o una web por Cast: esa cola es suya y la TV deja de contar. Cast hace pasar por aquí
    // también los saltos dentro de la cola de la TV ("A continuación", siguiente): esos no (son canciones de su cola).
    if (!cargandoPropia && cx.propia) {
      const ids = (req.queueData?.items || [req.media]).map(it => { const m = it?.media || it; return m?.customData?.id || idDe(m); });
      if (!ids.every(id => id && cx.cola.some(s => s.id === id))) { cx.propia = false; log('la cola la puso el celular o la web (Cast)', req.senderId || ''); }
    }
    if (req.queueData && req.queueData.items) req.queueData.items = req.queueData.items.filter(it => limpia(it.media));
    if (req.media && !limpia(req.media)) return rechazo();
    if (req.queueData && req.queueData.items && !req.queueData.items.length) return rechazo();
    return req;
  });
  pm.setMessageInterceptor(M.MessageType.QUEUE_INSERT, req => {
    req.items = (req.items || []).filter(it => limpia(it.media));
    return req.items.length ? req : new M.ErrorData(M.ErrorType.INVALID_REQUEST);
  });
  const proximas = () => {   // las que vienen detrás en la cola de Cast, con cuántas hay que saltar para llegar
    try { const q = pm.getQueueManager(), items = q.getItems() || [], i = q.getCurrentItemIndex();
          return items.slice(i + 1, i + 7).map((it, k) => ({media: it.media, salto: k + 1})); }
    catch (e) { return []; }
  };
  const siguiente = () => proximas()[0]?.media || null;
  leer = () => ({t: pm.getCurrentTimeSec() || 0, d: pm.getDurationSec() || 0, pausa: pm.getPlayerState() !== M.PlayerState.PLAYING});
  const ahora = () => { const m = pm.getMediaInformation(); if (m && !espejo) pinta(m, proximas()); };
  pm.addEventListener(E.PLAYER_LOAD_COMPLETE, () => {
    log('cargada:', pm.getMediaInformation()?.metadata?.title, '· duración según Cast', pm.getDurationSec(),
        '· el <audio> tiene', audio.currentSrc ? 'el /stream' : 'NADA', '· vídeos en la página', document.querySelectorAll('video').length,
        '· cola de Cast:', (() => { try { const q = pm.getQueueManager(); return `${(q.getItems() || []).length} (va en la ${q.getCurrentItemIndex() + 1})`; } catch (e) { return '?'; } })());
    ahora();
  });
  pm.addEventListener(E.ERROR, e => log('error de Cast:', e.detailedErrorCode, e.error));
  pm.addEventListener(E.MEDIA_STATUS, ahora);
  pm.addEventListener(E.PAUSE, () => setTimeout(() => {
    const ae = document.activeElement;
    log('en pausa · foco en', ae ? `<${ae.tagName.toLowerCase()}${ae.id ? ' id=' + ae.id : ''}>` : 'nada', '· elementos en <body>:',
        [...document.body.children].map(el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')).join(' '));
  }, 1500));
  pm.addEventListener([E.PAUSE, E.PLAYING], () => {
    const v = video(); if (v) (pm.getPlayerState() === M.PlayerState.PLAYING ? v.play().catch(() => {}) : v.pause());
  });
  pm.addEventListener(E.MEDIA_FINISHED, () => { if (!siguiente()) { actual = null; document.body.classList.remove('con-cancion'); } });
  ctx.addEventListener(cast.framework.system.EventType.SHUTDOWN, () => { log('Cast cierra la pantalla'); mandaAvisos(true); despedida(); });
  ctx.addEventListener(cast.framework.system.EventType.READY, () => {
    pm.setMediaElement(audio);   // otra vez, por si acaso: el reproductor es el <audio>
    const caps = ctx.getDeviceCapabilities();
    soloAudio = !!caps && caps[cast.framework.system.DeviceCapabilities.DISPLAY_SUPPORTED] === false;   // parlante
    document.body.classList.toggle('solo-audio', soloAudio);
    log('lista · pantalla:', !soloAudio, '·', navigator.userAgent, '·', innerWidth + 'x' + innerHeight, '· dpr', devicePixelRatio);
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
    saltaA: n => { salta(n); return n < 0 ? '⏮' : '⏭'; },
    ir: t => pm.seek(t),
    cola: () => { try { const q = pm.getQueueManager(); return {items: q.getItems() || [], i: q.getCurrentItemIndex()}; } catch (e) { return {items: [], i: 0}; } },
    anterior: () => {
      const i = (() => { try { return pm.getQueueManager().getCurrentItemIndex(); } catch (e) { return 0; } })();
      if ((pm.getCurrentTimeSec() || 0) > 3 || !i) pm.seek(0); else salta(-1);
      return '⏮';
    },
  };
  ctx.addCustomMessageListener(CANAL, e => {
    const d = e.data || {};
    if (d.tipo === 'llave' && typeof d.llave === 'string' && /^tv\.[\w-]{20,80}$/.test(d.llave)) {
      const primera = !llave, vieja = llave;
      if (typeof d.nombre === 'string' && d.nombre.trim()) cx.nombre = d.nombre.trim().slice(0, 40);
      llave = d.llave; log('llave recibida, caduca', new Date((d.caduca || 0) * 1000).toISOString().slice(0, 16));
      if (vieja && vieja !== llave) cambioDeCuenta(vieja, llave, Date.now());
      $('pestanas').hidden = false; document.body.classList.add('con-pestanas');
      if (primera) irA('ahora');   // abre en Ahora (con lo que suena); a Inicio solo si en la cuenta no suena nada
      if (primera) { cxBucle(); setTimeout(siNadaSuena, 5000); }
    } else if (d.tipo === 'toma' && llave) {   // la web al conectar: que suene aquí lo que suena en la cuenta
      tomaDeLaCuenta('la web me pide que lo ponga');
    } else if (d.tipo === 'cola' && llave && Array.isArray(d.cola)) {   // la web le pasa su cola al conectar: suena aquí
      log('la web me pasa', d.cola.length, 'canciones desde la', (d.qi || 0) + 1);
      tocar(d.cola, d.qi || 0, false, +d.pos || 0, !!d.radio);
    }
  });
  // ---- la TV pone su propia cola (elegida en sus menús) y suena sola, sin depender del celular ----
  const itemDe = (s, url) => {   // una canción como elemento de la cola de Cast
    const mi = new M.MediaInformation();
    mi.contentId = mi.contentUrl = location.origin + url; mi.contentType = 'video/webm'; mi.streamType = M.StreamType.BUFFERED;
    const md = new M.MusicTrackMediaMetadata(); md.title = s.title || ''; md.artist = s.artist || ''; md.albumName = s.album || '';
    md.images = imagenOk(s.thumb) ? [new cast.framework.messages.Image(s.thumb)] : [];
    mi.metadata = md; mi.customData = {id: s.id}; if (s.duration) mi.duration = s.duration;
    const it = new M.QueueItem(); it.media = mi; return it;
  };
  // Cambió la cola pero sigue la misma canción (alguien añadió, quitó o movió canciones desde el celular o la web):
  // se cambia lo de alrededor sin tocar la que suena. Antes se volvía a cargar todo y se cortaba unos segundos.
  cambiaAlrededor = async (canciones, i, radio = false) => {
    const q = pm.getQueueManager(), ya = q.getCurrentItem();
    let l = canciones.filter(s => s && ID.test(s.id));
    if (!ya || idDe(ya.media) !== l[i]?.id) return false;
    const desde = Math.max(0, i - 20); l = l.slice(desde, desde + 300); i -= desde;
    const {enlaces} = await api('/stream/enlaces', {method: 'POST', body: JSON.stringify({ids: l.filter((_, k) => k !== i).map(s => s.id)})});
    const antes = l.slice(0, i).filter(s => enlaces[s.id]), despues = l.slice(i + 1).filter(s => enlaces[s.id]);
    const otros = (q.getItems() || []).filter(it => it.itemId !== ya.itemId).map(it => it.itemId);
    if (otros.length) q.removeItems(otros);
    if (despues.length) q.insertItems(despues.map(s => itemDe(s, enlaces[s.id])));
    if (antes.length) q.insertItems(antes.map(s => itemDe(s, enlaces[s.id])), ya.itemId);
    quitaEspejo();
    cx.propia = true; cx.cola = [...antes, l[i], ...despues]; cx.radio = radio; cx.colaV++; cx.tomada = Date.now();
    log('cambio la cola sin cortar:', cx.cola.length, 'canciones, va en la', antes.length + 1);
    colaFirma = ''; ahora(); marcaSonando(); cxCuenta(true);
    return true;
  };
  acciones.mete = async (s, despues) => {
    const q = pm.getQueueManager(), ya = q.getCurrentItem(); if (!ya) return false;
    const {enlaces} = await api('/stream/enlaces', {method: 'POST', body: JSON.stringify({ids: [s.id]})});
    if (!enlaces[s.id]) return false;
    const items = q.getItems() || [], k = items.findIndex(it => it.itemId === ya.itemId), sig = despues ? items[k + 1] : null;
    q.insertItems([itemDe(s, enlaces[s.id])], sig ? sig.itemId : undefined);
    const j = Math.max(0, cx.cola.findIndex(x => x.id === idDe(ya.media)));
    cx.cola = [...cx.cola]; cx.cola.splice(despues ? j + 1 : cx.cola.length, 0, s); cx.colaV++;
    log('meto', s.title, despues ? 'después' : 'al final', '(sin cortar)');
    colaFirma = ''; ahora(); cxCuenta();
    return true;
  };
  tocar = async (canciones, i = 0, mezclar = false, desde = 0, radio = false) => {
    let l = canciones.filter(s => s && ID.test(s.id)).slice(0, 300);
    if (!l.length) return;
    if (mezclar) { for (let k = l.length - 1; k > 0; k--) { const j = Math.floor(Math.random() * (k + 1)); [l[k], l[j]] = [l[j], l[k]]; } i = 0; }
    try {
      const {enlaces} = await api('/stream/enlaces', {method: 'POST', body: JSON.stringify({ids: l.map(s => s.id)})});
      l = l.filter(s => enlaces[s.id]);
      const items = l.map(s => itemDe(s, enlaces[s.id]));
      const req = new M.LoadRequestData();
      req.queueData = new M.QueueData(); req.queueData.items = items; req.queueData.startIndex = Math.min(i, items.length - 1);
      req.media = items[req.queueData.startIndex].media; req.autoplay = true; if (desde) req.currentTime = desde;
      quitaEspejo();
      cx.propia = true; cx.cola = l; cx.radio = radio; cx.colaV++; cx.tomada = Date.now();
      cargandoPropia++;
      try { await pm.load(req); } finally { cargandoPropia--; }
      log('la TV pone', l.length, 'canciones desde la', req.queueData.startIndex + 1);
      marcaSonando();
      cxCuenta(true);
    } catch (e) { log('no pude poner la lista:', String(e?.message || e)); avisa('No pude ponerla'); }
  };
  // ---- "varios dispositivos": la TV es uno más ("TV"). Cuando suena lo que eligió ella, lo cuenta y hace las órdenes
  // de los otros (pausa, siguiente, poner otra cola…); si otro dispositivo se queda la música, la TV se pausa.
  cxCuenta = async (tomar = false) => {
    if (!cx.propia || !llave || cx.ido) return;
    const m = pm.getMediaInformation(), id = m ? new URL(m.contentUrl || m.contentId, location.href).pathname.split('/')[2] : null;
    const s = cx.cola.find(x => x.id === id); if (!s) return;
    const datos = {cancion: s, pos: Math.round((pm.getCurrentTimeSec() || 0) * 10) / 10, pausa: pm.getPlayerState() !== M.PlayerState.PLAYING,
                   qi: cx.cola.indexOf(s), duracion: pm.getDurationSec() || s.duration || 0, radio: cx.radio, repetir: 'off'};
    const v = cx.colaV; if (cx.colaContadaV !== v) datos.cola = cx.cola;   // la cola, si no se contó ESTA (no otra de antes)
    try {
      await api('/conectar/estado', {method: 'POST', body: JSON.stringify({disp: cx.disp, nombre: cx.nombre, datos, tomar, hecho: cx.orden})});
      if (datos.cola) cx.colaContadaV = v; cx.ultima = Date.now();
    } catch (e) { log('no pude contar lo que suena:', e.message); }
  };
  cxHaz = o => {
    const d = o.datos || {};
    if (o.tipo === 'pausa') d.pausar ? pm.pause() : pm.play();
    else if (o.tipo === 'siguiente') acciones.siguiente();
    else if (o.tipo === 'anterior') acciones.anterior();
    else if (o.tipo === 'ir') pm.seek(d.pos || 0);
    else if (o.tipo === 'cola' && d.cola?.length) {   // si sigue la misma canción (solo cambió lo que viene), en el mismo segundo
      const m = pm.getMediaInformation(), id = m ? new URL(m.contentUrl || m.contentId, location.href).pathname.split('/')[2] : null;
      const misma = !d.nueva && id && d.cola[d.qi || 0]?.id === id;
      (misma ? cambiaAlrededor(d.cola, d.qi || 0, !!d.radio).catch(e => { log('no pude cambiar la cola sin cortar:', String(e?.message || e)); return false; })
             : Promise.resolve(false))
        .then(hecho => hecho || tocar(d.cola, d.qi || 0, false, misma ? pm.getCurrentTimeSec() || 0 : 0, !!d.radio));
    }
  };
  pm.addEventListener([E.PAUSE, E.PLAYING, E.PLAYER_LOAD_COMPLETE, E.SEEKED].filter(Boolean), () => cxCuenta());
  setInterval(() => { if (cx.propia && Date.now() - cx.ultima > 15000) cxCuenta(); }, 5000);
  const op = new cast.framework.CastReceiverOptions();
  op.customNamespaces = {[CANAL]: cast.framework.system.MessageType.JSON};
  op.maxInactivity = 3600;   // que no se corte la conexión con la app en las pausas largas
  op.disableIdleTimeout = true;   // con menús no debe cerrarse a los 5 min sin sonar: se cierra sola a los 30 (arriba)
  // En algunas Google TV (la de Juancho, 06-11-2026), al pausar Cast ponía SU interfaz encima (título, barra blanca,
  // iconos en cuadraditos) y se quedaba con el control hasta dar play desde fuera. Esto le dice a Cast que la página
  // tiene su propia interfaz manejable; no hay opción documentada para quitarla del todo.
  try { const ui = new cast.framework.ui.UiConfig(); ui.touchScreenOptimizedApp = true; op.uiConfig = ui; } catch (e) { log('sin UiConfig:', String(e)); }
  ctx.start(op);
  try { cast.framework.ui.Controls.getInstance().hasMediaControlsOverlay().then(v => log('Cast pone su interfaz encima:', v)).catch(() => {}); } catch (e) {}
  enfoca(document.querySelector('#controles .grande'));
} else if (demo) {
  // Para verla en un navegador: /tv/?demo&id=<id>&t=<firma>&titulo=…&artista=…&album=…&img=…&sig=…&sigA=…&sigImg=…
  const p = new URLSearchParams(location.search), t0 = Date.now();
  if (p.get('id')) {
    leer = () => ({t: (Date.now() - t0) / 1000 + 42, d: 215, pausa: p.has('pausa')});
    const ficha = (titulo, artista, img, album) => ({metadata: {title: titulo || '', artist: artista || '', albumName: album || '', images: img ? [{url: img}] : []}});
    const yo = {contentUrl: `${location.origin}/stream/${p.get('id')}?t=${encodeURIComponent(p.get('t') || '')}`, duration: 215,
                ...ficha(p.get('titulo'), p.get('artista'), p.get('img'), p.get('album'))};
    const sig = p.getAll('sig').map((t, k) => ({salto: k + 1, media: {contentUrl: `${location.origin}/stream/${p.get('id')}?k=${k}`, ...ficha(t, p.getAll('sigA')[k], p.getAll('sigImg')[k])}}));
    acciones.cola = () => ({items: [{media: yo}, ...sig], i: 0});
    pinta(yo, sig);
  }
  enfoca(document.querySelector('#controles .grande'));
  if (p.get('llave')) { llave = p.get('llave'); $('pestanas').hidden = false; document.body.classList.add('con-pestanas'); irA(p.get('vista') || 'inicio'); }
}
