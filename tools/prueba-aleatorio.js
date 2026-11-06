// Prueba el botón 🔀 Aleatorio de Me gusta y de una playlist en un Chromium de verdad: tiene que encender el
// aleatorio y poner la lista entera mezclada (sin repetir ni perder ninguna); ▶ Reproducir sigue empezando por la 1.ª.
// Uso: tools/probar-web.sh prueba-aleatorio.js
const { chromium } = require('playwright');
const fs = require('fs');
const [,, html, token] = process.argv;
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({viewport: {width: 1600, height: 900}})).newPage();
  const errs = [];
  page.on('pageerror', e => errs.push(e.message));
  await page.route('**/web/', r => r.fulfill({contentType: 'text/html', body: fs.readFileSync(html, 'utf8')}));
  await page.goto('http://127.0.0.1:8090/');
  await page.evaluate(t => { localStorage.setItem('musica_sesion', t); localStorage.removeItem('aleatorio'); }, token);
  // Me gusta y una playlist de mentira con canciones reales de la biblioteca (no se escribe nada en el servidor)
  const songs = (await (await page.request.get('http://127.0.0.1:8090/library?sort=nombre&limit=8', {headers: {Authorization: 'Bearer ' + token}})).json()).songs;
  await page.route(/\/favorites$/, r => r.request().method() === 'GET' ? r.fulfill({json: {songs}}) : r.fulfill({json: {}}));
  await page.route(/\/playlists$/, r => r.fulfill({json: {playlists: [{id: 'prueba', name: 'Prueba', songs: songs.slice(0, 6)}]}}));
  await page.goto('http://127.0.0.1:8090/web/');
  await page.waitForTimeout(1500);
  const cola = () => page.evaluate(() => ({ids: queue.map(s => s.id), shuffleOn, lista: (lists.view || lists.lib).songs.map(s => s.id)}));
  const ver = (nombre, q) => {
    const igual = q.ids.length === q.lista.length && new Set(q.ids).size === q.ids.length && q.ids.every(i => q.lista.includes(i));
    console.log(`${nombre}: aleatorio ${q.shuffleOn ? 'encendido' : 'APAGADO'} · ${q.ids.length} en cola, ${igual ? 'todas y sin repetir' : 'MAL'} · ${q.ids.join(',') === q.lista.join(',') ? 'MISMO ORDEN (mal)' : 'mezclada'}`);
  };
  console.log('favs/playlists:', await page.evaluate(async () => { await loadFavs(); await loadPls(); return [favs.size, pls.length]; }));
  await page.evaluate(() => { libTab = 'favoritas'; go('biblioteca'); });
  await page.waitForTimeout(1200);
  console.log('Me gusta tiene botones:', await page.locator('#lib [data-playall]').count(), await page.locator('#lib [data-shuffleall]').count());
  await page.locator('#lib [data-shuffleall]').click(); await page.waitForTimeout(400);
  ver('Me gusta 🔀', await cola());
  await page.evaluate(() => { shuffleOn = false; });
  await page.locator('#lib [data-playall]').click(); await page.waitForTimeout(400);
  let q = await cola(); console.log('Me gusta ▶ sin aleatorio, mismo orden:', q.ids.join(',') === q.lista.join(',') ? 'sí' : 'NO');
  const pl = await page.evaluate(async () => { await loadPls(); const p = pls.find(x => x.songs.length > 2); if (p) showPlaylist(p); return p && p.name; });
  if (pl) {
    await page.waitForTimeout(800);
    await page.locator('.hero [data-shuffleall]').click(); await page.waitForTimeout(400);
    ver(`Playlist «${pl}» 🔀`, await cola());
  } else console.log('sin playlists de más de 2 canciones para probar');
  await page.screenshot({path: '/out/aleatorio.png'});
  await page.evaluate(() => { libTab = 'favoritas'; go('biblioteca'); }); await page.waitForTimeout(800); await page.screenshot({path: '/out/aleatorio-megusta.png'});
  console.log('errores JS:', errs.length ? errs : 'ninguno');
  await browser.close();
})();
