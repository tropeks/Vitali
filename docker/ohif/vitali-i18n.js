/** Keep Vitali Imagem on the same locale layer as the host Vitali UI. */
(function bootstrapVitaliViewerLocale() {
  'use strict';

  var DEFAULT_LOCALE = 'pt-BR';
  var PREFERENCE_ENDPOINT = '/api/v1/users/me/language/';
  var VIEWER_BUNDLE = '/visualizador/app.bundle.2774acf90dddad2fa3f0.js';
  var ohifLocales = {
    'pt-BR': 'pt-BR',
    // OHIF 3.12.8 has no pt-PT catalog. Preserve the user's Vitali locale in
    // the document while deliberately using the closest Portuguese catalog.
    'pt-PT': 'pt-BR',
    es: 'es',
    en: 'en-US',
  };

  function readCookie(name) {
    var prefix = name + '=';
    var parts = document.cookie ? document.cookie.split(';') : [];
    for (var index = 0; index < parts.length; index += 1) {
      var value = parts[index].trim();
      if (value.indexOf(prefix) === 0) {
        try {
          return decodeURIComponent(value.slice(prefix.length));
        } catch (_error) {
          return '';
        }
      }
    }
    return '';
  }

  function normalize(value) {
    if (!value) return '';
    var lower = String(value).trim().replace(/_/g, '-').toLowerCase();
    if (lower === 'pt-pt' || lower.indexOf('pt-pt-') === 0) return 'pt-PT';
    if (lower === 'pt' || lower === 'pt-br' || lower.indexOf('pt-br-') === 0) return 'pt-BR';
    if (lower === 'es' || lower.indexOf('es-') === 0) return 'es';
    if (lower === 'en' || lower.indexOf('en-') === 0) return 'en';
    return '';
  }

  function readStoredLocale() {
    try {
      return normalize(window.localStorage.getItem('vitaliViewerLocale'));
    } catch (_error) {
      return '';
    }
  }

  function fetchPreferredLocale() {
    if (typeof window.fetch !== 'function') return Promise.resolve('');

    // Vitali mirrors the short-lived access token into this JS-readable cookie
    // specifically for same-origin API clients (see frontend/lib/auth.ts).
    var accessToken = readCookie('access_token_js');
    var headers = { Accept: 'application/json' };
    if (accessToken) headers.Authorization = 'Bearer ' + accessToken;

    var controller = typeof window.AbortController === 'function'
      ? new window.AbortController()
      : null;
    var timeout = window.setTimeout(function abortPreferenceRequest() {
      if (controller) controller.abort();
    }, 1500);

    return window.fetch(PREFERENCE_ENDPOINT, {
      credentials: 'same-origin',
      headers: headers,
      signal: controller ? controller.signal : undefined,
    }).then(function parsePreference(response) {
      if (!response.ok) return '';
      return response.json().then(function normalizePreference(payload) {
        return normalize(payload && payload.preferred_language);
      });
    }).catch(function ignoreUnavailablePreference() {
      return '';
    }).then(function clearPreferenceTimeout(locale) {
      window.clearTimeout(timeout);
      return locale;
    });
  }

  function persistLocale(vitaliLocale, source) {
    var viewerLocale = ohifLocales[vitaliLocale];
    document.documentElement.lang = vitaliLocale;

    // A path-scoped cookie avoids leaking OHIF's internal key to the Vitali UI.
    document.cookie = 'i18next=' + encodeURIComponent(viewerLocale)
      + '; path=/visualizador; max-age=31536000; samesite=lax';
    try {
      window.localStorage.setItem('i18nextLng', viewerLocale);
      window.localStorage.setItem('vitaliViewerLocale', vitaliLocale);
    } catch (_error) {
      // The path-scoped cookie still works when storage is disabled.
    }

    // OHIF gives its `lng` query parameter precedence over cookies and local
    // storage. Set it before loading the bundle so stale browser state cannot
    // override the canonical Vitali preference.
    try {
      var url = new URL(window.location.href);
      if (url.searchParams.get('lng') !== viewerLocale) {
        url.searchParams.set('lng', viewerLocale);
        window.history.replaceState(window.history.state, '', url.toString());
      }
    } catch (_error) {
      // Cookie/localStorage detection remains available in older browsers.
    }

    window.VITALI_VIEWER_LOCALE = vitaliLocale;
    window.VITALI_VIEWER_OHIF_LOCALE = viewerLocale;
    window.VITALI_VIEWER_LOCALE_SOURCE = source;
  }

  function loadViewerBundle() {
    if (document.querySelector('script[data-vitali-viewer-bundle]')) return;
    var script = document.createElement('script');
    script.defer = true;
    script.src = VIEWER_BUNDLE;
    script.setAttribute('data-vitali-viewer-bundle', 'true');
    document.head.appendChild(script);
  }

  var cookieLocale = normalize(readCookie('NEXT_LOCALE'));
  var storedLocale = readStoredLocale();

  window.VITALI_VIEWER_LOCALE_READY = (cookieLocale
    ? Promise.resolve({ locale: cookieLocale, source: 'NEXT_LOCALE' })
    : fetchPreferredLocale().then(function selectLocale(preferredLocale) {
      if (preferredLocale) return { locale: preferredLocale, source: 'preferred_language' };
      if (storedLocale) return { locale: storedLocale, source: 'persisted' };
      return { locale: DEFAULT_LOCALE, source: 'default' };
    })
  ).then(function initializeViewer(selection) {
    persistLocale(selection.locale, selection.source);
    loadViewerBundle();
    return selection.locale;
  });
})();
