'use strict';

// Guard the OAuth form against a double click/Enter. A second POST would find
// the ticket already consumed and show the misleading "expired" error.
document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('form[action="/oauth/authorize"]');
  if (!form) return;
  form.addEventListener('submit', (event) => {
    if (form.dataset.submitting === '1') {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = '1';
  });
});

if (new URLSearchParams(location.search).has('login-debug')) import('/assets/login-debug.js').catch(() => {});
