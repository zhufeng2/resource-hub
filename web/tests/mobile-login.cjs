// Run with Node.js and Playwright; BROWSER=webkit selects WebKit.
// Set CHROME_CHANNEL=chrome to use an installed Chrome instead of bundled Chromium.
// Viewport resizing checks layout/focus; a real phone is still needed to check its OS keyboard.
const { chromium, webkit } = require('playwright');
const { readFile } = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

async function serve(page) {
  await page.route('http://login.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/api/')) {
      return route.fulfill({ json: { csrf: 'test-csrf', preferences: {} } });
    }
    const file = url.pathname === '/' ? 'index.html' : url.pathname.replace('/assets/', '');
    const contentType = file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html';
    await route.fulfill({ body: await readFile(path.join(__dirname, '../static', file)), contentType });
  });
}

(async () => {
  for (const engine of [process.env.BROWSER === 'webkit' ? webkit : chromium]) {
    const browser = await engine.launch({ headless: true,
      ...(engine === chromium && process.env.CHROME_CHANNEL ? { channel: process.env.CHROME_CHANNEL } : {}) });
    try {
      for (const width of [320, 390, 768]) {
        const context = await browser.newContext({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true });
        const page = await context.newPage();
        await serve(page);
        await page.goto('http://login.test/');
        await page.locator('#login-trigger').click();
        // Phones use an in-flow page section, not a top-layer fixed dialog.
        assert.equal(await page.locator('#login-panel').isVisible(), true, `${engine.name()} ${width}: panel visible`);
        assert.equal(await page.locator('#login-dialog').evaluate(el => el.open), false,
          `${engine.name()} ${width}: dialog stays closed`);
        assert.equal(await page.locator('#login-panel').evaluate(el => getComputedStyle(el).position), 'static',
          `${engine.name()} ${width}: panel is in normal flow`);
        assert.equal(await page.locator('#login-panel').evaluate(el => {
          for (let node = el; node; node = node.parentElement) if (getComputedStyle(node).position === 'fixed') return true;
          return false;
        }), false, `${engine.name()} ${width}: panel must not sit in a fixed layer`);
        const username = page.locator('#login-panel [name=username]');
        const password = page.locator('#login-panel [name=password]');
        assert.equal(await username.evaluate(el => !!el.closest('label')), false,
          `${engine.name()} ${width}: login input must not be wrapped in a label`);
        assert.equal(await username.evaluate(el => el.labels?.[0]?.textContent), '账号');
        await username.tap();
        await username.pressSequentially('keyboard-test');
        for (const height of [520, 380, 844]) {
          await page.setViewportSize({ width, height });
          assert.equal(await username.evaluate(el => el === document.activeElement), true,
            `${engine.name()} ${width}: focus stays in the username field`);
          assert.equal(await username.inputValue(), 'keyboard-test');
        }
        await password.tap();
        await password.pressSequentially('test-password');
        await page.setViewportSize({ width, height: 380 });
        assert.equal(await password.evaluate(el => el === document.activeElement), true,
          `${engine.name()} ${width}: focus stays in the password field`);
        assert.equal(await password.inputValue(), 'test-password');
        await page.setViewportSize({ width, height: 844 });
        await page.locator('#close-login-panel').click();
        assert.equal(await page.locator('#login-panel').isVisible(), false);
        assert.equal(await page.locator('#home-view').isVisible(), true);
        assert.equal(await page.locator('#login-trigger').isVisible(), true);
        await page.locator('#login-trigger').click();
        assert.equal(await password.inputValue(), '');
        await username.tap();
        assert.equal(await username.evaluate(el => el === document.activeElement), true,
          `${engine.name()} ${width}: reopened panel focuses normally`);
        await context.close();
        console.log(`${engine.name()} ${width}px: passed`);
      }
      {
        // Wide screens keep the native dialog.
        const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
        const page = await context.newPage();
        await serve(page);
        await page.goto('http://login.test/');
        await page.locator('#login-trigger').click();
        assert.equal(await page.locator('#login-dialog').evaluate(el => el.open), true, 'desktop: dialog opens');
        assert.equal(await page.locator('#login-dialog [name=username]').evaluate(el => !!el.closest('label')), false,
          'desktop: login input must not be wrapped in a label');
        assert.equal(await page.locator('#login-panel').isVisible(), false, 'desktop: panel stays hidden');
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#login-dialog').evaluate(el => el.open), false, 'desktop: Escape closes');
        await context.close();
        console.log(`${engine.name()} desktop: passed`);
      }
    } finally { await browser.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
