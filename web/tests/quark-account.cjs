// Synthetic browser test: no real website, credentials or Quark requests.
const { chromium } = require('playwright');
const { readFile, mkdir } = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.CHROME_CHANNEL || 'chrome'});
  try {
    for (const width of [390, 1280]) {
      const context = await browser.newContext({viewport: {width, height: 1000}});
      const page = await context.newPage();
      const errors = [], submissions = [];
      page.on('pageerror', error => errors.push(error.message));
      let bound = false;
      await page.route('http://profile.test/**', async route => {
        const request = route.request(), url = new URL(request.url());
        if (url.pathname === '/api/session') return route.fulfill({json: {
          id: '1', username: 'alice', csrf: 'synthetic-csrf', preferences: {},
          quota: {remaining: 5, daily_limit: 5, used: 0}, mcp_url: 'http://profile.test/mcp'}});
        if (url.pathname === '/api/history') return route.fulfill({json: {items: []}});
        if (url.pathname === '/api/mcp-token') return route.fulfill({json: {active: false, token: null}});
        if (url.pathname === '/api/quark-account/reveal') {
          await new Promise(resolve => setTimeout(resolve, 100));
          return route.fulfill({json: {cookie: 'session=synthetic-test-only'}});
        }
        if (url.pathname === '/api/quark-account') {
          if (request.method() === 'POST') {
            assert.equal(request.headers()['x-csrf-token'], 'synthetic-csrf');
            submissions.push(request.postDataJSON()); bound = true;
          }
          if (request.method() === 'DELETE') bound = false;
          return route.fulfill({json: {bound}});
        }
        if (url.pathname.startsWith('/api/')) return route.fulfill({json: {}});
        const file = url.pathname === '/profile' ? 'index.html' : url.pathname.replace('/assets/', '');
        return route.fulfill({body: await readFile(path.join(__dirname, '../static', file)),
          contentType: file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'});
      });
      await page.goto('http://profile.test/profile?tab=security');
      await page.waitForFunction(() => document.getElementById('quark-status').textContent === '未绑定');
      assert.equal(await page.locator('#quark-cookie').getAttribute('placeholder'), '请输入 Cookie');
      assert.equal(await page.locator('#toggle-quark-cookie').isDisabled(), true);
      assert.equal(await page.locator('#copy-quark-cookie').isDisabled(), true);
      await page.locator('#quark-cookie').fill('session=synthetic-test-only');
      // The saved Cookie is never echoed; refreshing the status must not wipe
      // what the user has already typed.
      await page.evaluate(() => loadQuarkAccount());
      assert.equal(await page.locator('#quark-cookie').inputValue(), 'session=synthetic-test-only');
      await page.locator('#quark-form [type=submit]').click();
      await page.waitForFunction(() => document.getElementById('quark-status').textContent === '已绑定');
      // Like the MCP Token row, the Cookie stays in its field after saving.
      assert.equal(await page.locator('#quark-cookie').inputValue(), 'session=synthetic-test-only');
      assert.equal(await page.locator('#quark-cookie').getAttribute('type'), 'password');
      assert.equal(await page.locator('#quark-cookie').getAttribute('type'), 'password');
      assert.equal(await page.locator('#toggle-quark-cookie').isDisabled(), false);
      assert.equal(await page.locator('#copy-quark-cookie').isDisabled(), false);
      await page.locator('#toggle-quark-cookie').click();
      assert.equal(await page.locator('#quark-cookie').getAttribute('type'), 'text');
      assert.equal(await page.locator('#toggle-quark-cookie').textContent(), '隐藏');
      await page.locator('#toggle-quark-cookie').click();
      assert.equal(await page.locator('#quark-cookie').getAttribute('type'), 'password');
      assert.equal(await page.locator('#toggle-quark-cookie').textContent(), '显示');
      assert.deepEqual(submissions, [{cookie: 'session=synthetic-test-only'}]);
      // After reloading a saved binding, Show still retrieves this user's Cookie.
      await page.reload();
      await page.waitForFunction(() => document.getElementById('quark-status').textContent === '已绑定');
      await page.waitForFunction(() => document.getElementById('quark-cookie').value === 'session=synthetic-test-only');
      assert.equal(await page.locator('#quark-cookie').getAttribute('type'), 'password');
      assert.equal(await page.locator('#toggle-quark-cookie').isDisabled(), false);
      await page.locator('#toggle-quark-cookie').click();
      await page.waitForFunction(() => document.getElementById('quark-cookie').type === 'text');
      assert.equal(await page.locator('#quark-cookie').inputValue(), 'session=synthetic-test-only');
      await page.locator('#toggle-quark-cookie').click();
      assert.equal(await page.locator('#quark-cookie').getAttribute('type'), 'password');
      for(const id of ['mcp-token','quark-cookie']){
        await page.locator('#'+id).focus();
        const style=await page.locator('#'+id).evaluate(e=>({border:getComputedStyle(e).borderWidth,shadow:getComputedStyle(e).boxShadow,background:getComputedStyle(e).backgroundColor}));
        assert.equal(style.border,'0px');assert.equal(style.shadow,'none');assert.equal(style.background,'rgba(0, 0, 0, 0)');
      }
      // A newer status load must release the obsolete reveal's pending state.
      await page.evaluate(async () => {
        document.getElementById('quark-cookie').value='';
        const older=readQuarkCookie();
        await loadQuarkAccount();
        await older;
      });
      assert.equal(await page.locator('#quark-cookie').inputValue(), 'session=synthetic-test-only');
      assert.equal(await page.locator('#toggle-quark-cookie').isDisabled(), false);
      // Changing browser-session identity clears the previous owner's credentials.
      await page.evaluate(() => {state.csrf='different-session';state.user={...state.user,id:'2',username:'bob'};identity();});
      assert.equal(await page.locator('#quark-cookie').inputValue(), '');
      assert.equal(await page.locator('#toggle-quark-cookie').isDisabled(), true);
      await page.evaluate(async () => {state.csrf='synthetic-csrf';state.user={...state.user,id:'1',username:'alice'};identity();await loadQuarkAccount();});

      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.locator('.mcp-token-field #toggle-mcp-token').count(), 1);
      assert.equal(await page.locator('.mcp-token-field #copy-mcp-token').count(), 1);
      assert.equal(await page.locator('#quark-form .mcp-token-field #toggle-quark-cookie').count(), 1);
      assert.equal(await page.locator('#quark-form .mcp-token-field #copy-quark-cookie').count(), 1);
      assert.equal(await page.locator('.copy-field #copy-mcp').count(), 1);
      const alignment = await page.evaluate(() => {
        const field = document.querySelector('.mcp-token-field').getBoundingClientRect();
        const action = document.getElementById('revoke-mcp-token').getBoundingClientRect();
        return Math.abs(field.right - action.right);
      });
      assert.ok(alignment < 2, `Token actions align right: ${alignment}`);
      const quarkAlignment = await page.evaluate(() => {
        const field = document.querySelector('#quark-form .mcp-token-field').getBoundingClientRect();
        const action = document.getElementById('quark-unbind').getBoundingClientRect();
        return Math.abs(field.right - action.right);
      });
      assert.ok(quarkAlignment < 2, `Quark actions align right: ${quarkAlignment}`);

      await mkdir(path.join(__dirname, '../../.cache/quark-ui'), {recursive: true});
      await page.screenshot({path: path.join(__dirname, `../../.cache/quark-ui/profile-${width}.png`), fullPage: true});
      await page.locator('#quark-unbind').click();
      await page.waitForFunction(() => document.getElementById('quark-status').textContent === '未绑定');
      assert.equal(await page.locator('#quark-unbind').isDisabled(), true);
      assert.equal(await page.locator('#quark-cookie').inputValue(), '');
      assert.equal(await page.locator('#quark-cookie').getAttribute('placeholder'), '请输入 Cookie');
      assert.equal(await page.locator('#quark-cookie').getAttribute('type'), 'password');
      assert.equal(await page.locator('#toggle-quark-cookie').isDisabled(), true);
      assert.equal(await page.locator('#copy-quark-cookie').isDisabled(), true);
      assert.deepEqual(errors, []);
      await context.close();
      console.log(`Quark profile ${width}px: passed`);
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
