// Prueba "Reproducir a continuación" en un Chromium de verdad: suena una lista, se añaden dos canciones de fuera
// desde el menú ⋮ y deben ir justo detrás de la actual, en ese orden, sin duplicar y sin tocar la lista ni Me gusta.
// Uso: tools/probar-web.sh prueba-siguiente.js
const { chromium } = require('playwright');
const fs = require('fs');
const [,, html, token] = process.argv;
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({viewport: {width: 1600, height: 900}})).newPage();
  const errs = [], writes = [];
  page.on('pageerror', e => errs.push(e.message));
  page.on('request', r => { if (['PUT', 'POST', 'DELETE'].includes(r.method()) && !r.url().includes('/eventos')) writes.push(r.method() + ' ' + new URL(r.url()).pathname); });
  await page.route('**/web/', r => r.fulfill({contentType: 'text/html', body: fs.readFileSync(html, 'utf8')}));
  await page.goto('http://127.0.0.1:8090/');
  await page.evaluate(t => localStorage.setItem('musica_sesion', t), token);
  await page.goto('http://127.0.0.1:8090/web/');
  await page.waitForTimeout(1500);
  const res = await page.evaluate(async () => {
    const lista = (await api('/library?sort=nombre&limit=6')).songs, otras = (await api('/library?sort=populares&limit=40')).songs;
    const fuera = otras.filter(s => !lista.some(x => x.id === s.id)).slice(0, 2);
    window._lista = lista.map(s => s.id).join(',');
    playList(lista, 0); qi = 1; start();   // suena la 2.ª de la lista
    return {lista, fuera};
  });
  for (const s of res.fuera) {   // como el usuario: menú ⋮ → "Reproducir a continuación"
    await page.evaluate(s => songMenu(s), s);
    await page.getByText('Reproducir a continuación').click();
    await page.waitForTimeout(300);
  }
  // otra vez la primera: no se duplica, se mueve detrás de las añadidas
  await page.evaluate(s => songMenu(s), res.fuera[0]); await page.getByText('Reproducir a continuación').click(); await page.waitForTimeout(300);
  const q = await page.evaluate(() => ({ids: queue.map(s => s.id), titles: queue.map(s => s.title.slice(0, 16) + (s._cola ? '*' : '')), qi, lista: window._lista}));
  console.log('cola:', q.titles.map((x, i) => i === q.qi ? `[${x}]` : x).join(' | '));
  const after = q.ids.slice(q.qi + 1, q.qi + 3);
  console.log('detrás de la actual:', after.length === 2 && after.includes(res.fuera[0].id) && after.includes(res.fuera[1].id) ? 'SÍ, las dos añadidas' : 'NO');
  console.log('duplicadas:', q.ids.length - new Set(q.ids).size, '· resto de la lista sigue:', q.ids.filter(i => q.lista.split(',').includes(i)).length === 6 ? 'sí' : 'NO');
  console.log('se marcan "Añadida" en la cola:', await page.locator('#qList .tag').count());
  console.log('escrituras en el servidor (playlist/Me gusta):', writes.length ? writes : 'ninguna', '· errores JS:', errs.length ? errs : 'ninguno');
  await browser.close();
})();
