// SPDX-License-Identifier: Apache-2.0
// Tiny i18n runtime (zh / en, no libraries). The server inlines window.UIC_DICT ({zh:{key:text},en:{...}}, from assets/i18n.json)
// and window.UIC_LANG (the language stored for this runtime directory: 'zh' | 'en' | null = follow the browser).
// Markup: a data-i18n attribute holds the key for the element text; data-i18n-<attr> does the same for an attribute (title, aria-label, ...). tr(key, {name: value}) fills {name}.
(function () {
  'use strict';
  const dict = window.UIC_DICT || {};
  const stored = window.UIC_LANG === 'zh' || window.UIC_LANG === 'en' ? window.UIC_LANG : null;
  const browser = ((navigator.languages && navigator.languages[0]) || navigator.language || '').toLowerCase();
  const lang = stored || (browser.indexOf('zh') === 0 ? 'zh' : 'en');
  function tr(key, params) {
    let text = dict[lang] && dict[lang][key];
    if (text == null) text = dict.en && dict.en[key];
    if (text == null) text = key;
    return params ? text.replace(/\{(\w+)\}/g, (m, name) => (name in params ? params[name] : m)) : text;
  }
  tr.lang = lang;
  tr.stored = stored;
  tr.apply = function (root) {
    root = root || document;
    root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = tr(el.getAttribute('data-i18n')); });
    root.querySelectorAll('*').forEach(el => {
      for (const attr of Array.from(el.attributes)) {
        if (attr.name.indexOf('data-i18n-') === 0) el.setAttribute(attr.name.slice('data-i18n-'.length), tr(attr.value));
      }
    });
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  };
  // Every request tells the server which language this page shows, so API errors match the page.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    init = Object.assign({}, init);
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.charAt(0) === '/' || url.indexOf(location.origin) === 0) {
      const headers = new Headers(init.headers || (typeof input !== 'string' && input.headers) || {});
      headers.set('X-UIC-Lang', lang);
      init.headers = headers;
    }
    return nativeFetch(input, init);
  };
  // Another tab (the list page) may change the language: reload when this tab regains focus, unless the user is mid-edit.
  async function recheck() {
    if (document.hidden) return;
    try {
      const res = await nativeFetch('/api/lang', { cache: 'no-store' });
      if (!res.ok) return;
      const now = await res.json();
      if (now.lang !== stored) {
        if (document.querySelector('dialog[open]') || (document.activeElement && /^(TEXTAREA|INPUT)$/.test(document.activeElement.tagName))) return;
        location.reload();
      }
    } catch (e) { /* offline: keep the current language */ }
  }
  document.addEventListener('visibilitychange', recheck);
  window.addEventListener('focus', recheck);
  document.addEventListener('DOMContentLoaded', () => tr.apply(document));
  window.tr = tr;
})();
