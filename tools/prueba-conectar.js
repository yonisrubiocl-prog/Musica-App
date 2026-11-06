// Dos dispositivos (PC y celular) de la misma cuenta contra /conectar de mentira (tools/conectar-falso.py, con la
// lógica real de server/conectar.py) y el audio de mentira: sin cuentas de prueba en el servidor. Uso: tools/probar-conectar.sh
const { chromium } = require('playwright');
const fs = require('fs');
const [,, html, token] = process.argv;
const AUDIO_FALSO = () => {   // audio de mentira: play/pausa/segundo sin sonar (la prueba mira estados, no sonido)
  const P = HTMLMediaElement.prototype, st = new WeakMap();
  const g = el => { if (!st.has(el)) st.set(el, {paused: true, t: 0, t0: 0, src: ''}); return st.get(el); };
  Object.defineProperty(P, 'paused', {get() { return g(this).paused; }});
  Object.defineProperty(P, 'src', {get() { return g(this).src; }, set(v) { const s = g(this); s.src = v; s.t = 0; s.paused = true;
    setTimeout(() => this.dispatchEvent(new Event('loadedmetadata')), 30); }});
  Object.defineProperty(P, 'currentTime', {get() { const s = g(this); return s.paused ? s.t : s.t + (performance.now() - s.t0) / 1000; },
    set(v) { const s = g(this); s.t = v; s.t0 = performance.now(); this.dispatchEvent(new Event('seeked')); }});
  Object.defineProperty(P, 'duration', {get() { return 200; }});
  P.play = function () { const s = g(this); if (s.paused) { s.t0 = performance.now(); s.paused = false; this.dispatchEvent(new Event('play')); } return Promise.resolve(); };
  P.pause = function () { const s = g(this); if (!s.paused) { s.t = this.currentTime; s.paused = true; this.dispatchEvent(new Event('pause')); } };
  P.load = function () {};
};
(async () => {
  const browser = await chromium.launch();
  const abre = async (tag, opts) => {
    const ctx = await browser.newContext(opts); await ctx.addInitScript(AUDIO_FALSO);
    const page = await ctx.newPage(); const errs = []; page.on('pageerror', e => errs.push(e.message));
    await page.route('**/web/', r => r.fulfill({contentType: 'text/html', body: fs.readFileSync(html, 'utf8')}));
    await page.route(/\/stream\/[^/]+\/enlace$/, r => r.fulfill({json: {url: '/audio-falso.webm'}}));
    await page.route(/\/conectar/, async r => { const u = new URL(r.request().url());
      const resp = await r.fetch({url: 'http://127.0.0.1:8777' + u.pathname + u.search}); r.fulfill({response: resp}); });
    await page.goto('http://127.0.0.1:8090/'); await page.evaluate(t => localStorage.setItem('musica_sesion', t), token);
    await page.goto('http://127.0.0.1:8090/web/'); await page.waitForTimeout(1200); page.errs = errs; page.tag = tag; return page;
  };
  const ok = (c, m) => console.log((c ? 'OK  ' : 'MAL ') + m);
  const st = p => p.evaluate(() => ({remoto, activo: cx?.activo, yo: DISP, cur: cur?.id, qi, cola: queue.map(s => s.id), paused: audio.paused,
    t: Math.round(audio.currentTime), en: $('pEn').hidden ? '' : $('pEn').textContent, disp: $('npDispT').textContent}));
  const pc = await abre('pc', {viewport: {width: 1600, height: 900}});
  const songs = await pc.evaluate(async () => (await api('/library?sort=nombre&limit=8')).songs);
  await pc.evaluate(s => playList(s.slice(0, 6), 0, false, true), songs);
  await pc.waitForTimeout(2500);
  const cel = await abre('cel', {viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36'});
  await cel.waitForTimeout(2000);
  let a = await st(pc), b = await st(cel);
  ok(!a.remoto && !a.paused && a.cur === songs[0].id, `el PC suena (${a.cur})`);
  ok(b.remoto && b.cur === a.cur && b.en.includes('PC'), `el celular ve lo del PC: «${b.en}» · ${b.disp}`);
  ok(b.paused, 'y en el celular no suena nada');
  await cel.locator('#next').click(); await pc.waitForTimeout(2000);
  a = await st(pc); b = await st(cel);
  ok(a.qi === 1 && a.cur === songs[1].id && b.cur === a.cur, `«siguiente» desde el celular: el PC pasa a la 2.ª y el celular lo ve (${b.cur})`);
  await cel.evaluate(s => playNext(s), songs[7]); await pc.waitForTimeout(2500);
  a = await st(pc); b = await st(cel);
  ok(a.cola[a.qi + 1] === songs[7].id && b.cola[b.qi + 1] === songs[7].id, '«a continuación» desde el celular: entra en la cola del PC detrás de la que suena');
  await cel.locator('#play').click(); await pc.waitForTimeout(1500);
  a = await st(pc); ok(a.paused, 'pausa desde el celular: el PC se pausa');
  await cel.locator('#play').click(); await pc.waitForTimeout(1500);
  a = await st(pc); ok(!a.paused, 'play desde el celular: el PC sigue');
  await cel.evaluate(() => irA(100)); await pc.waitForTimeout(1500);
  a = await st(pc); ok(Math.abs(a.t - 100) <= 2, `ir al segundo 100 desde el celular: el PC va por el ${a.t}`);
  await cel.evaluate(() => openNp()); await cel.waitForTimeout(600);
  await cel.locator('#npDisp').click(); await cel.waitForTimeout(400);
  console.log('     lista:', (await cel.locator('#sheet .opt').allTextContents()).map(x => x.replace(/\s+/g, ' ').trim()).join(' | '));
  await cel.locator('#sheet .opt', {hasText: 'Este dispositivo'}).click(); await cel.waitForTimeout(2500);
  a = await st(pc); b = await st(cel);
  ok(!b.remoto && b.activo === b.yo && !b.paused && b.cur === a.cur, `«escuchar aquí»: ahora suena en el celular (${b.cur}, segundo ${b.t})`);
  ok(Math.abs(b.t - a.t) <= 3 && b.t >= 100, 'en el mismo segundo');
  ok(a.remoto && a.paused && a.en.includes('Celular'), `y el PC se pausa y pasa a ser mando: «${a.en}»`);
  await pc.evaluate(s => playList(s.slice(2, 5), 0, false, true), songs); await pc.waitForTimeout(2500);
  b = await st(cel); ok(b.cur === songs[2].id && b.cola.length === 3 && !b.paused, 'el PC pone otra lista: suena en el celular');
  await pc.evaluate(() => playPausa()); await cel.waitForTimeout(1500);
  b = await st(cel); ok(b.paused, 'pausa desde el PC: el celular se pausa');
  console.log('errores JS:', pc.errs.length || cel.errs.length ? [...pc.errs, ...cel.errs] : 'ninguno');
  await browser.close();
})();
