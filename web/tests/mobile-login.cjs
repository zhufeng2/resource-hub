// Run with Node.js and Playwright; BROWSER=webkit selects WebKit.
// Set CHROME_CHANNEL=chrome to use an installed Chrome instead of bundled Chromium.
// Viewport resizing checks layout/focus; a real phone is still needed to check its OS keyboard.
const { chromium, webkit } = require('playwright');
const { readFile } = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  for (const engine of [process.env.BROWSER === 'webkit' ? webkit : chromium]) {
    const browser = await engine.launch({ headless: true,
      ...(engine === chromium && process.env.CHROME_CHANNEL ? { channel: process.env.CHROME_CHANNEL } : {}) });
    try {
      for (const width of [320, 390, 768]) {
        const context = await browser.newContext({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true });
        const page = await context.newPage();
        await page.route('http://login.test/**', async route => {
          const url = new URL(route.request().url());
          if (url.pathname.startsWith('/api/')) {
            return route.fulfill({ json: { csrf: 'test-csrf', preferences: {} } });
          }
          const file = url.pathname === '/' ? 'index.html' : url.pathname.replace('/assets/', '');
          const contentType = file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html';
          await route.fulfill({ body: await readFile(path.join(__dirname, '../static', file)), contentType });
        });
        await page.goto('http://login.test/');
        await page.locator('#login-trigger').click();
        const username = page.locator('#login-form [name=username]');
        const password = page.locator('#login-form [name=password]');
        await username.tap();
        await username.pressSequentially('keyboard-test');
        const top = await username.evaluate(el => el.getBoundingClientRect().top);
        for (const height of [520, 380, 844]) {
          await page.setViewportSize({ width, height });
          assert.equal(await username.evaluate(el => el === document.activeElement), true);
          assert.ok(Math.abs(await username.evaluate(el => el.getBoundingClientRect().top) - top) < 1,
            `${engine.name()} ${width}: input moved as keyboard viewport changed`);
          assert.equal(await username.inputValue(), 'keyboard-test');
        }
        await password.tap();
        await password.pressSequentially('test-password');
        await page.setViewportSize({ width, height: 380 });
        assert.equal(await password.evaluate(el => el === document.activeElement), true);
        assert.equal(await password.inputValue(), 'test-password');
        assert.equal(await page.locator('#login-dialog').evaluate(el => el.open), true);
        await page.locator('#login-form button[type=submit]').scrollIntoViewIfNeeded();
        await page.setViewportSize({ width, height: 844 });
        await page.locator('#close-login').click();
        await page.locator('#login-trigger').click();
        assert.equal(await password.inputValue(), '');
        await username.tap();
        assert.equal(await username.evaluate(el => el === document.activeElement), true);
        await context.close();
        console.log(`${engine.name()} ${width}px: passed`);
      }
    } finally { await browser.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
