'use strict';

// Loaded only for /?login-debug=1 (or /profile?login-debug=1). It records the
// focus, viewport and dialog events that make an on-screen keyboard disappear,
// so a phone screenshot shows the real cause instead of another guess.
(() => {
  const lines = [];
  const box = document.createElement('pre');
  box.setAttribute('aria-live', 'polite');
  box.style.cssText = 'position:fixed;z-index:2147483647;left:8px;right:8px;bottom:8px;max-height:42vh;overflow:auto;margin:0;padding:10px 12px;border-radius:10px;background:rgb(0 0 0 / 88%);color:#7dff9b;font:11px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;pointer-events:none;user-select:none';
  const name = element => element ? (element.name || element.id || element.tagName.toLowerCase()) : '-';
  const viewport = () => `win ${innerWidth}x${innerHeight} vv ${Math.round(visualViewport?.width || 0)}x${Math.round(visualViewport?.height || 0)}@${Math.round(visualViewport?.offsetTop || 0)} dlg ${[...document.querySelectorAll('dialog')].filter(d => d.open).map(d => d.id || d.tagName).join(',') || '-'} active ${name(document.activeElement)}`;
  function log(message) {
    lines.push(`${new Date().toISOString().slice(11, 23)} ${message} | ${viewport()}`);
    box.textContent = lines.slice(-60).join('\n');
  }
  document.body.append(box);
  for (const type of ['focusin', 'focusout']) document.addEventListener(type, event => log(`${type} ${name(event.target)} -> ${name(event.relatedTarget)}`), true);
  document.addEventListener('blur', event => log(`blur ${name(event.target)}`), true);
  document.addEventListener('visibilitychange', () => log(`visibility ${document.visibilityState}`));
  document.addEventListener('close', event => log(`close event ${name(event.target)}`), true);
  for (const type of ['resize', 'orientationchange']) window.addEventListener(type, () => log(type));
  if (window.visualViewport) {
    for (const type of ['resize', 'scroll']) visualViewport.addEventListener(type, () => log(`visualViewport.${type}`), { passive: true });
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
  log('login debug ready');
})();
