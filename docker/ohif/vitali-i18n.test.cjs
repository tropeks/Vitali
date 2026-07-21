const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(require.resolve('./vitali-i18n.js'), 'utf8');

async function run({ cookie = '', stored = {}, preferred = '', fetchOk = true } = {}) {
  const storage = new Map(Object.entries(stored));
  const scripts = [];
  let currentUrl = 'https://vitali-demo.qtec.me/visualizador/viewer?StudyInstanceUIDs=1.2.3';
  const document = {
    cookie,
    documentElement: { lang: 'pt-BR' },
    head: { appendChild: element => scripts.push(element) },
    createElement: () => ({ setAttribute(name, value) { this[name] = value; } }),
    querySelector: () => null,
  };
  const window = {
    document,
    location: { get href() { return currentUrl; } },
    history: {
      state: null,
      replaceState(_state, _unused, url) { currentUrl = url; },
    },
    localStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
    },
    fetch: async () => ({
      ok: fetchOk,
      json: async () => ({ preferred_language: preferred }),
    }),
    AbortController,
    setTimeout,
    clearTimeout,
  };
  const context = vm.createContext({ window, document, URL, Promise, encodeURIComponent, AbortController });
  vm.runInContext(source, context);
  await window.VITALI_VIEWER_LOCALE_READY;
  return { window, document, storage, scripts, url: currentUrl };
}

test('NEXT_LOCALE wins and maps English to the OHIF catalog', async () => {
  const result = await run({ cookie: 'session=x; NEXT_LOCALE=en', preferred: 'es' });
  assert.equal(result.window.VITALI_VIEWER_LOCALE, 'en');
  assert.equal(result.window.VITALI_VIEWER_OHIF_LOCALE, 'en-US');
  assert.equal(result.window.VITALI_VIEWER_LOCALE_SOURCE, 'NEXT_LOCALE');
  assert.equal(result.document.documentElement.lang, 'en');
  assert.equal(new URL(result.url).searchParams.get('lng'), 'en-US');
});

test('uses authenticated preferred_language when NEXT_LOCALE is absent', async () => {
  const result = await run({ preferred: 'es' });
  assert.equal(result.window.VITALI_VIEWER_LOCALE, 'es');
  assert.equal(result.window.VITALI_VIEWER_LOCALE_SOURCE, 'preferred_language');
  assert.equal(result.storage.get('i18nextLng'), 'es');
});

test('pt-PT is honestly preserved while using the available pt-BR catalog', async () => {
  const result = await run({ cookie: 'NEXT_LOCALE=pt-PT' });
  assert.equal(result.document.documentElement.lang, 'pt-PT');
  assert.equal(result.window.VITALI_VIEWER_OHIF_LOCALE, 'pt-BR');
  assert.equal(new URL(result.url).searchParams.get('lng'), 'pt-BR');
});

test('falls back through persisted preference to Brazilian Portuguese', async () => {
  const persisted = await run({ fetchOk: false, stored: { vitaliViewerLocale: 'pt-PT' } });
  assert.equal(persisted.window.VITALI_VIEWER_LOCALE, 'pt-PT');
  assert.equal(persisted.window.VITALI_VIEWER_LOCALE_SOURCE, 'persisted');

  const fallback = await run({ fetchOk: false });
  assert.equal(fallback.window.VITALI_VIEWER_LOCALE, 'pt-BR');
  assert.equal(fallback.window.VITALI_VIEWER_LOCALE_SOURCE, 'default');
});

test('loads exactly one viewer bundle after locale resolution', async () => {
  const result = await run({ cookie: 'NEXT_LOCALE=es' });
  assert.equal(result.scripts.length, 1);
  assert.equal(result.scripts[0].src, '/visualizador/app.bundle.2774acf90dddad2fa3f0.js');
  assert.equal(result.scripts[0]['data-vitali-viewer-bundle'], 'true');
});
