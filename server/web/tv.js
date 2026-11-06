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
function pinta(media, proximas = []) {
  if (!limpia(media)) return;
  const m = media.metadata || {}, u = new URL(media.contentUrl || media.contentId, location.href);
  const id = u.pathname.split('/')[2], t = u.searchParams.get('t') || '';
  if (!ID.test(id)) return;
  document.body.classList.add('con-cancion');
  if (!actual || actual.id !== id) {
    const img = imagenDe(media);
    actual = {id, t, titulo: m.title || '', artista: m.artist || m.albumArtist || '', album: m.albumName || '', dur: media.duration || 0};
    $('titulo').textContent = actual.titulo; $('artista').textContent = actual.artista; $('album').textContent = actual.album;
    for (const el of [$('tapa'), $('tapaFondo')]) if (img) el.src = img; else el.removeAttribute('src');
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
  const lista = proximas.slice(0, 6), firma = lista.map(p => p.media.contentUrl || p.media.contentId).join('|');
  if (firma === colaFirma) return; colaFirma = firma;
  $('cola').hidden = !lista.length;
  const enfocada = document.activeElement?.closest?.('#colaFila');
  $('colaFila').innerHTML = lista.map(p => { const m = p.media.metadata || {}, img = imagenDe(p.media);
    return `<button class="mini f" data-salto="${p.salto}">${img ? `<img src="${esc(img)}" alt="">` : '<span class="ph">♪</span>'}
      <b>${esc(m.title || '')}</b><small>${esc(m.artist || '')}</small></button>`; }).join('');
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
  for (const l of [lineas[i], lineas[i + 1]]) if (l) { const p = document.createElement('p'); p.textContent = l.txt; $('letra').append(p); }
}

// ---------- el control remoto: las flechas van al elemento más cercano en esa dirección, OK lo pulsa ----------
// Todo lo que se puede elegir lleva la clase "f" (pestañas, botones, tarjetas, canciones, teclas). Las teclas
// multimedia del mando (⏯, ⏭, ⏮, ⏩, ⏪) valen siempre. En captura y sin dejar que siga: el reproductor de Cast usaba
// ← → para adelantar/atrasar por su cuenta.
let acciones = {};   // las pone Cast (en la demo no hacen nada)
let tocado = Date.now();   // última tecla (para cerrar solo tras un rato sin usarla ni sonar nada)
// solo lo de la pantalla que se ve: las pestañas y, o los botones de "Ahora", o el menú abierto
const visibles = () => [...document.querySelectorAll(vista === 'ahora' ? '#pestanas .f, #controles .f, #colaFila .f' : '#pestanas .f, #menu .f, #panelIr')]
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
function pulsa(a) { const f = acciones[a]; const hecho = f ? f() : ''; log('botón:', a, hecho || '(sin Cast)'); if (hecho) avisa(hecho); }
document.getElementById('controles').addEventListener('click', e => { const b = e.target.closest('button'); if (b) pulsa(b.dataset.a); });
document.getElementById('panelIr').addEventListener('click', () => { pila = []; irA('ahora'); });
document.getElementById('colaFila').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  const hecho = acciones.saltaA ? acciones.saltaA(+b.dataset.salto) : ''; log('a continuación: salto', b.dataset.salto); if (hecho) avisa(hecho);
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
  log('tecla:', k || '?', c);
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
  if (v === 'ahora') return enfoca(document.querySelector('#controles .grande'));
  $('menu').innerHTML = '<div class="scroll"><p class="vacio">Cargando…</p></div>';
  (render || VISTAS[v])().then(h => { $('menu').innerHTML = `<div class="scroll">${h}</div>`; enfoca(visibles().find(el => el.closest('#menu'))); })
    .catch(e => { $('menu').innerHTML = `<div class="scroll"><p class="vacio">No pude cargarlo (${esc(e.message)})</p></div>`; log('menú:', e.message); });
}
function abre(render, base) { pila.push({base: base || (vista === 'detalle' ? pila[pila.length - 1]?.base : vista), render}); irA('detalle', render); }
function volver() { pila.pop(); const p = pila[pila.length - 1]; p ? irA('detalle', p.render) : irA(VISTA_BASE); }
let VISTA_BASE = 'inicio';
document.getElementById('pestanas').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { pila = []; VISTA_BASE = b.dataset.vista; irA(b.dataset.vista); } });
const tarjetas = (lista, k) => lista.map((s, i) => `<button class="tarjeta f" data-l="${k}" data-i="${i}">${imgOk(s.thumb) ? `<img src="${imgOk(s.thumb)}" alt="">` : '<span class="ph">♪</span>'}
  <b>${esc(s.title)}</b><small>${esc(s.artist || '')}</small></button>`).join('');
const artistas = lista => lista.map(a => `<button class="tarjeta redonda f" data-artista="${esc(a.name)}">${imgOk(a.thumb) ? `<img src="${imgOk(a.thumb)}" alt="">` : '<span class="ph">👤</span>'}
  <b>${esc(a.name)}</b><small>${a.songs || ''} canciones</small></button>`).join('');
const filas = (lista, k) => lista.map((s, i) => `<button class="cancion f${s.id === actual?.id ? ' sonando' : ''}" data-l="${k}" data-i="${i}" data-id="${esc(s.id)}"><span class="n">${s.id === actual?.id ? '▶' : i + 1}</span>${imgOk(s.thumb) ? `<img src="${imgOk(s.thumb)}" alt="">` : '<img alt="">'}
  <div><b>${esc(s.title)}</b><small>${esc([s.artist, s.album].filter(Boolean).join(' · '))}</small></div><span>${s.duration ? dur(s.duration) : ''}</span></button>`).join('');
const volverBtn = () => '<div class="acciones" style="margin-top:0"><button class="pill f" data-accion="volver">← Volver</button></div>';
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
  if (d.tecla) return escribe(d.tecla);
  if (d.artista) return abre(artista(d.artista));
  if (d.album) return abre(async () => { const a = await api(`/album?artist=${encodeURIComponent(d.de)}&name=${encodeURIComponent(d.album)}`);
    return lista(a.name, `${a.artist}${a.year ? ' · ' + a.year : ''}`, a.thumb || a.songs[0]?.thumb, a.songs)(); });
  if (d.pl) { const p = plsCache[+d.pl]; return abre(lista(p.name, `Playlist · ${p.songs.length} canciones`, p.songs.find(s => s.thumb)?.thumb, p.songs)); }
  if (d.favs) return abre(async () => { const f = await api('/favorites'); return lista('Me gusta', `${f.songs.length} canciones`, f.songs[0]?.thumb, f.songs)(); });
  if (d.l) return tocar(listas[d.l] || [], +(d.i || 0), !!d.mezcla);
});
// Cerrar sola tras 30 min sin sonar nada ni tocar el control (Cast ya no la cierra a los 5 min: ver disableIdleTimeout)
setInterval(() => { if (leer().pausa && Date.now() - tocado > 30 * 60 * 1000) { log('30 min sin usar: cierro'); try { cast.framework.CastReceiverContext.getInstance().stop(); } catch (e) {} } }, 60000);
let tocar = async () => {};   // la pone Cast: poner una lista en la TV, que suena sola
let cxCuenta = async () => {}, cxHaz = () => {};   // también (ver abajo, "varios dispositivos")
const cx = {disp: (() => { try { let d = localStorage.getItem('dispositivo'); if (!d) localStorage.setItem('dispositivo', d = 'tv' + Math.random().toString(36).slice(2, 12)); return d; }
                           catch (e) { return 'tv' + Math.random().toString(36).slice(2, 12); } })(),
            propia: false, cola: [], colaContada: false, orden: 0, ultima: 0};
async function cxBucle() {
  let desde = 0;
  while (llave) {
    try {
      const r = await api(`/conectar?disp=${cx.disp}&nombre=TV&desde=${desde}`);
      desde = r.v;
      if (r.activo === cx.disp) {
        const nuevas = (r.ordenes || []).filter(o => o.n > cx.orden);
        for (const o of nuevas) { cx.orden = o.n; log('orden de otro dispositivo:', o.tipo); cxHaz(o); }
        if (nuevas.length) cxCuenta();
      } else if (cx.propia && r.activo && r.activo_vivo) {   // otro se quedó la música
        cx.propia = false; log('ahora suena en', r.dispositivos?.find(d => d.id === r.activo)?.nombre || r.activo);
        if (!leer().pausa) acciones.pausa?.();
      }
    } catch (e) { await new Promise(ok => setTimeout(ok, 5000)); }
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
  let cargandoPropia = false;
  pm.setMessageInterceptor(M.MessageType.LOAD, req => {
    if (!cargandoPropia) cx.propia = false;   // la cargó el celular o la web: esa cola es suya
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
  const ahora = () => { const m = pm.getMediaInformation(); if (m) pinta(m, proximas()); };
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
    saltaA: n => { salta(n); return '⏭'; },
    anterior: () => {
      const i = (() => { try { return pm.getQueueManager().getCurrentItemIndex(); } catch (e) { return 0; } })();
      if ((pm.getCurrentTimeSec() || 0) > 3 || !i) pm.seek(0); else salta(-1);
      return '⏮';
    },
  };
  ctx.addCustomMessageListener(CANAL, e => {
    const d = e.data || {};
    if (d.tipo === 'llave' && typeof d.llave === 'string' && /^tv\.[\w-]{20,80}$/.test(d.llave)) {
      const primera = !llave;
      llave = d.llave; log('llave recibida, caduca', new Date((d.caduca || 0) * 1000).toISOString().slice(0, 16));
      $('pestanas').hidden = false; document.body.classList.add('con-pestanas');
      if (primera && !actual) irA('inicio');
      if (primera) cxBucle();
    }
  });
  // ---- la TV pone su propia cola (elegida en sus menús) y suena sola, sin depender del celular ----
  tocar = async (canciones, i = 0, mezclar = false) => {
    let l = canciones.filter(s => s && ID.test(s.id)).slice(0, 300);
    if (!l.length) return;
    if (mezclar) { for (let k = l.length - 1; k > 0; k--) { const j = Math.floor(Math.random() * (k + 1)); [l[k], l[j]] = [l[j], l[k]]; } i = 0; }
    try {
      const {enlaces} = await api('/stream/enlaces', {method: 'POST', body: JSON.stringify({ids: l.map(s => s.id)})});
      l = l.filter(s => enlaces[s.id]);
      const items = l.map(s => {
        const mi = new M.MediaInformation();
        mi.contentId = mi.contentUrl = location.origin + enlaces[s.id]; mi.contentType = 'audio/webm'; mi.streamType = M.StreamType.BUFFERED;
        const md = new M.MusicTrackMediaMetadata(); md.title = s.title || ''; md.artist = s.artist || ''; md.albumName = s.album || '';
        md.images = imagenOk(s.thumb) ? [new cast.framework.messages.Image(s.thumb)] : [];
        mi.metadata = md; mi.customData = {id: s.id}; if (s.duration) mi.duration = s.duration;
        const it = new M.QueueItem(); it.media = mi; return it;
      });
      const req = new M.LoadRequestData();
      req.queueData = new M.QueueData(); req.queueData.items = items; req.queueData.startIndex = Math.min(i, items.length - 1);
      req.media = items[req.queueData.startIndex].media; req.autoplay = true;
      cx.propia = true; cx.cola = l; cx.colaContada = false;
      cargandoPropia = true;
      try { await pm.load(req); } finally { cargandoPropia = false; }
      log('la TV pone', l.length, 'canciones desde la', req.queueData.startIndex + 1);
      marcaSonando();
      cxCuenta(true);
    } catch (e) { log('no pude poner la lista:', String(e?.message || e)); avisa('No pude ponerla'); }
  };
  // ---- "varios dispositivos": la TV es uno más ("TV"). Cuando suena lo que eligió ella, lo cuenta y hace las órdenes
  // de los otros (pausa, siguiente, poner otra cola…); si otro dispositivo se queda la música, la TV se pausa.
  cxCuenta = async (tomar = false) => {
    if (!cx.propia || !llave) return;
    const m = pm.getMediaInformation(), id = m ? new URL(m.contentUrl || m.contentId, location.href).pathname.split('/')[2] : null;
    const s = cx.cola.find(x => x.id === id); if (!s) return;
    const datos = {cancion: s, pos: Math.round((pm.getCurrentTimeSec() || 0) * 10) / 10, pausa: pm.getPlayerState() !== M.PlayerState.PLAYING,
                   qi: cx.cola.indexOf(s), duracion: pm.getDurationSec() || s.duration || 0, radio: false, repetir: 'off'};
    if (!cx.colaContada) datos.cola = cx.cola;
    try {
      await api('/conectar/estado', {method: 'POST', body: JSON.stringify({disp: cx.disp, nombre: 'TV', datos, tomar, hecho: cx.orden})});
      cx.colaContada = true; cx.ultima = Date.now();
    } catch (e) {}
  };
  cxHaz = o => {
    const d = o.datos || {};
    if (o.tipo === 'pausa') d.pausar ? pm.pause() : pm.play();
    else if (o.tipo === 'siguiente') acciones.siguiente();
    else if (o.tipo === 'anterior') acciones.anterior();
    else if (o.tipo === 'ir') pm.seek(d.pos || 0);
    else if (o.tipo === 'cola' && d.cola?.length) tocar(d.cola, d.qi || 0);
  };
  pm.addEventListener([E.PAUSE, E.PLAYING, E.PLAYER_LOAD_COMPLETE, E.SEEKED].filter(Boolean), () => cxCuenta());
  setInterval(() => { if (cx.propia && Date.now() - cx.ultima > 15000) cxCuenta(); }, 5000);
  const op = new cast.framework.CastReceiverOptions();
  op.customNamespaces = {[CANAL]: cast.framework.system.MessageType.JSON};
  op.maxInactivity = 3600;   // que no se corte la conexión con la app en las pausas largas
  op.disableIdleTimeout = true;   // con menús no debe cerrarse a los 5 min sin sonar: se cierra sola a los 30 (arriba)
  ctx.start(op);
  enfoca(document.querySelector('#controles .grande'));
} else if (demo) {
  // Para verla en un navegador: /tv/?demo&id=<id>&t=<firma>&titulo=…&artista=…&album=…&img=…&sig=…&sigA=…&sigImg=…
  const p = new URLSearchParams(location.search), t0 = Date.now();
  if (p.get('id')) {
    leer = () => ({t: (Date.now() - t0) / 1000 + 42, d: 215, pausa: p.has('pausa')});
    const ficha = (titulo, artista, img, album) => ({metadata: {title: titulo || '', artist: artista || '', albumName: album || '', images: img ? [{url: img}] : []}});
    pinta({contentUrl: `${location.origin}/stream/${p.get('id')}?t=${encodeURIComponent(p.get('t') || '')}`, duration: 215,
           ...ficha(p.get('titulo'), p.get('artista'), p.get('img'), p.get('album'))},
          p.getAll('sig').map((t, k) => ({salto: k + 1, media: {contentUrl: `${location.origin}/stream/${p.get('id')}?k=${k}`, ...ficha(t, p.getAll('sigA')[k], p.getAll('sigImg')[k])}})));
  }
  enfoca(document.querySelector('#controles .grande'));
  if (p.get('llave')) { llave = p.get('llave'); $('pestanas').hidden = false; document.body.classList.add('con-pestanas'); irA(p.get('vista') || 'inicio'); }
}
