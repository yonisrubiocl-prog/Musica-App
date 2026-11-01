// Prueba "Buscar en internet" en un Chromium de verdad: la lista sale tal cual la da YouTube Music, con lo guardado marcado
// "Guardada" (no escondido), y tocar una guardada suena la copia del servidor sin bajar nada.
// Uso: tools/probar-web.sh prueba-internet.js
const { chromium } = require('playwright');
const fs = require('fs');
const [,, html, token] = process.argv;
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({viewport: {width: 1600, height: 900}})).newPage();
  const errs = [], streams = [];
  page.on('pageerror', e => errs.push(e.message));
  page.on('request', r => { if (r.url().includes('/stream/')) streams.push(r.url().split('?')[0].split('/').pop()); });
  await page.route('**/web/', r => r.fulfill({contentType: 'text/html', body: fs.readFileSync(html, 'utf8')}));
  await page.goto('http://127.0.0.1:8090/');
  await page.evaluate(t => localStorage.setItem('musica_sesion', t), token);
  await page.goto('http://127.0.0.1:8090/web/');
  await page.waitForTimeout(1500);
  await page.evaluate(() => { const b = document.querySelector('[data-tab="buscar"], [data-go="buscar"]'); if (b) b.click(); });
  await page.waitForTimeout(300);
  const box = page.locator('input[type="search"], .search input').first();
  await box.fill('Clint Eastwood Gorillaz'); await box.press('Enter');
  await page.locator('button.yt').click();
  await page.locator('#net .row').first().waitFor();
  const filas = await page.locator('#net .row').evaluateAll(rs => rs.map(r => ({t: r.querySelector('.t').textContent, a: r.querySelector('.a').textContent})));
  filas.slice(0, 20).forEach((f, i) => console.log(String(i + 1).padStart(2), f.a.slice(0, 44).padEnd(44), '|', f.t.slice(0, 44)));
  console.log('la canción guardada sale 1.ª y marcada:', /^Guardada/.test(filas[0].a) ? 'SÍ' : 'NO');
  await page.locator('#net .row .hit').first().click();
  await page.waitForTimeout(1200);
  const cur = await page.evaluate(() => ({id: cur && cur.id, where: cur && cur.where}));
  console.log('al tocarla suena:', cur, '· stream:', streams[0], '· errores JS:', errs.length ? errs : 'ninguno');
  await browser.close();
})();
