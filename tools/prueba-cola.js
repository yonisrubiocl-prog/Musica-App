// Prueba de la cola de la web en un Chromium de verdad (PC 1600 px y móvil con dedo): arrastrar la 6.ª antes de la 3.ª.
// Uso: tools/probar-web.sh   (imagen oficial de Playwright en Docker; sirve el web.html del disco, sin reiniciar la API)
const { chromium } = require('playwright');
const fs = require('fs');
const [,, html, token] = process.argv;
(async () => {
  const browser = await chromium.launch();
  for (const modo of ['pc', 'movil']) {
    const ctx = await browser.newContext(modo === 'pc' ? {viewport: {width: 1600, height: 900}}
      : {viewport: {width: 400, height: 800}, hasTouch: true, isMobile: true});
    const page = await ctx.newPage();
    const errs = []; page.on('pageerror', e => errs.push(e.message));
    await page.route('**/web/', r => r.fulfill({contentType: 'text/html', body: fs.readFileSync(html, 'utf8')}));
    await page.goto('http://127.0.0.1:8090/');
    await page.evaluate(t => localStorage.setItem('musica_sesion', t), token);
    await page.goto('http://127.0.0.1:8090/web/');
    await page.waitForTimeout(1500);
    await page.evaluate(async () => { const j = await api('/library?sort=nombre&limit=8'); playList(j.songs, 0); });
    await page.waitForTimeout(500);
    if (modo === 'movil') {   // abrir el reproductor grande y la pestaña de la cola
      await page.evaluate(() => { openNp ? openNp() : null; });
      await page.waitForTimeout(400);
      await page.evaluate(() => { const b = document.querySelector('#npTabs [data-np="cola"]'); b && b.click(); });
      await page.waitForTimeout(400);
    }
    const order = () => page.evaluate(() => queue.map(s => s.title.slice(0, 14)));
    const before = await order();
    const box = sel => page.locator(sel).first().boundingBox();
    const dest = modo === 'pc' ? '#qList' : '#npPanel';
    const grip = await box(`${dest} [data-qrow="5"] .grip`), row2 = await box(`${dest} [data-qrow="2"]`);
    if (!grip || !row2) { console.log(modo, 'NO ENCUENTRO el asa o la fila', !!grip, !!row2, errs); continue; }
    const x = grip.x + grip.width / 2, y = grip.y + grip.height / 2, y2 = row2.y + 4;
    if (modo === 'pc') {
      await page.mouse.move(x, y); await page.mouse.down();
      for (let k = 1; k <= 10; k++) await page.mouse.move(x, y + (y2 - y) * k / 10);
      await page.mouse.up();
    } else {   // dedo de verdad (CDP)
      const cdp = await ctx.newCDPSession(page);
      const t = (type, yy) => cdp.send('Input.dispatchTouchEvent', {type, touchPoints: type === 'touchEnd' ? [] : [{x, y: yy}]});
      await t('touchStart', y);
      for (let k = 1; k <= 10; k++) { await t('touchMove', y + (y2 - y) * k / 10); await page.waitForTimeout(16); }
      await t('touchEnd', y2);
    }
    await page.waitForTimeout(300);
    const after = await order();
    console.log(`== ${modo} (asa de la 6.ª -> antes de la 3.ª)`); console.log(' antes  ', before.join(' | ')); console.log(' después', after.join(' | '));
    console.log(' ¿movida?', before[5] === after[2] ? 'SÍ' : 'NO', '· duplicadas:', after.length - new Set(after).size, '· errores JS:', errs.length ? errs : 'ninguno');
    if (modo === 'movil') {   // pulsación larga en la fila (sin asa): la 6.ª (ahora 7.ª) a antes de la 3.ª
      const r = await box(`${dest} [data-qrow="6"] .meta`), r2 = await box(`${dest} [data-qrow="2"]`);
      const cdp = await ctx.newCDPSession(page);
      const t = (type, yy) => cdp.send('Input.dispatchTouchEvent', {type, touchPoints: type === 'touchEnd' ? [] : [{x: r.x + 20, y: yy}]});
      const b2 = await order(); const yy = r.y + r.height / 2;
      await t('touchStart', yy); await page.waitForTimeout(500);
      for (let k = 1; k <= 10; k++) { await t('touchMove', yy + (r2.y + 4 - yy) * k / 10); await page.waitForTimeout(16); }
      await t('touchEnd', r2.y + 4); await page.waitForTimeout(300);
      const a2 = await order();
      console.log(' pulsación larga en la fila: ¿movida?', b2[6] === a2[2] ? 'SÍ' : 'NO', '·', a2.join(' | '));
    }
    await ctx.close();
  }
  await browser.close();
})();
