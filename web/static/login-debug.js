'use strict';

// Loaded only for ?login-debug=1. Shows the newest focus/window/keyboard events
// (resize noise is collapsed into one "keyboard" line) so a single phone
// screenshot identifies what actually dismisses the soft keyboard.
(() => {
  const lines = [];
  const panel = document.createElement('div');
  panel.style.cssText = 'position:fixed;z-index:2147483647;left:8px;right:8px;bottom:8px;max-height:48vh;display:flex;flex-direction:column;overflow:hidden;border-radius:10px;background:rgb(0 0 0 / 90%);color:#7dff9b;font:11px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;pointer-events:none;user-select:none';
  const head = document.createElement('div');
  head.style.cssText = 'flex:none;padding:8px 12px;border-bottom:1px solid rgb(255 255 255 / 20%);color:#fff;white-space:pre-wrap';
  const body = document.createElement('pre');
  body.style.cssText = 'flex:1;min-height:0;margin:0;padding:8px 12px;overflow:auto;white-space:pre-wrap';
  panel.append(head, body);
  document.body.append(panel);

  const name = element => element ? (element.name || element.id || element.tagName.toLowerCase()) : '-';
  const dialogs = () => [...document.querySelectorAll('dialog')].filter(dialog => dialog.open).map(dialog => dialog.id || dialog.tagName).join(',') || '-';
  const state = () => `win ${innerWidth}x${innerHeight} · vv ${Math.round(visualViewport?.width || 0)}x${Math.round(visualViewport?.height || 0)} · active ${name(document.activeElement)} · focus ${document.hasFocus()} · dlg ${dialogs()} · scroll ${Math.round(scrollY)}`;
  function paint() {
    head.textContent = state();
    body.textContent = lines.slice(-40).join('\n');
    body.scrollTop = body.scrollHeight;
  }
  function log(message) {
    lines.push(`${new Date().toISOString().slice(11, 23)} ${message}`);
    if (lines.length > 100) lines.splice(0, lines.length - 100);
    paint();
  }

  for (const type of ['focusin', 'focusout']) document.addEventListener(type, event => log(`${type} ${name(event.target)} -> ${name(event.relatedTarget)}`), true);
  document.addEventListener('blur', event => log(`blur ${name(event.target)}`), true);
  document.addEventListener('visibilitychange', () => log(`visibility ${document.visibilityState}`));
  document.addEventListener('close', event => log(`close ${name(event.target)}`), true);
  window.addEventListener('focus', () => log('window.focus'));
  window.addEventListener('blur', () => log('window.blur'));
  window.addEventListener('pagehide', () => log('pagehide'));
  window.addEventListener('pageshow', () => log('pageshow'));
  for (const type of ['input', 'compositionstart', 'compositionend']) {
    document.addEventListener(type, event => { if (event.target?.name) log(`${type} ${name(event.target)} len=${String(event.target.value).length}`); }, true);
  }
  let lastScroll = Math.round(scrollY);
  window.addEventListener('scroll', () => {
    const top = Math.round(scrollY);
    if (Math.abs(top - lastScroll) > 8) { lastScroll = top; log(`scroll ${top}`); }
  }, { passive: true });
  let lastHeight = Math.round(visualViewport?.height || innerHeight), lastPan = Math.round(visualViewport?.offsetTop || 0);
  window.addEventListener('resize', () => {
    const height = Math.round(visualViewport?.height || innerHeight);
    if (Math.abs(height - lastHeight) > 40) { lastHeight = height; log(`keyboard ${height}px`); }
    paint();
  });
  if (window.visualViewport) {
    visualViewport.addEventListener('resize', () => {
      const height = Math.round(visualViewport.height);
      if (Math.abs(height - lastHeight) > 40) { lastHeight = height; log(`keyboard ${height}px`); }
      const pan = Math.round(visualViewport.offsetTop);
      if (Math.abs(pan - lastPan) > 8) { lastPan = pan; log(`pan ${pan}px`); }
      paint();
    }, { passive: true });
  }
  for (const method of ['show', 'showModal', 'close']) {
    const native = HTMLDialogElement.prototype[method];
    HTMLDialogElement.prototype[method] = function (...args) {
      log(`dialog.${method}(${args.join(',')}) ${this.id || this.tagName}`);
      return native.apply(this, args);
    };
  }
  const nativeFocus = HTMLElement.prototype.focus;
  HTMLElement.prototype.focus = function (...args) {
    const caller = (new Error().stack || '').split('\n')[2]?.trim() || '';
    log(`focus() ${name(this)} ${caller}`);
    return nativeFocus.apply(this, args);
  };
  setInterval(paint, 700);
  log('debug ready');
})();
