'use strict';

// Apply the last selected appearance before CSS paints the page. Store no account data.
(() => {
  const key = 'resource-hub-theme';
  const valid = value => ['light', 'dark', 'system'].includes(value);
  let preference = 'light';
  try {
    const saved = localStorage.getItem(key);
    if (valid(saved)) preference = saved;
  } catch { /* Private browsing can make storage unavailable. */ }

  function apply(value) {
    const next = valid(value) ? value : 'light';
    const changed = preference !== next;
    preference = next;
    const resolved = preference === 'system'
      ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : preference;
    if (document.documentElement.dataset.theme !== resolved) {
      document.documentElement.dataset.theme = resolved;
    }
    if (changed) {
      try { localStorage.setItem(key, preference); } catch {}
    }
  }

  apply(preference);
  window.ResourceTheme = { apply, get preference() { return preference; } };
  const params = new URLSearchParams(location.search);
  document.documentElement.dataset.initialView = location.pathname === '/profile'
    ? 'profile' : params.get('q') ? 'results' : 'home';
})();
