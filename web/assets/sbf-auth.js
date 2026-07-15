/* ============================================================================
   SBF AUTH — общий клиент сессии для lp.sbfconsult.com (2026-07-14).

   С моста аккаунтов на SBFAcademy_bot (см. core/journal_auth.py) токен
   'sbf_token' — это настоящий SBFAcademy JWT с TTL 60 минут, а не прежняя
   локальная opaque-сессия на 30 дней. Без обновления по refresh_token это
   означает разлогин каждый час вместо раза в месяц — реальная просадка UX.

   sbfAuth.fetch(url, opts) — обёрнутый fetch: подставляет и X-Auth-Token,
   и Authorization: Bearer (сервер читает оба, см. serve.py:_auth_token),
   и на 401 сам обновляет токен через SBFAcademy's /api/auth/refresh,
   повторяя запрос один раз.
   ========================================================================= */
(function () {
  'use strict';

  var SBF_API      = 'https://web.sbfconsult.com';
  var TOKEN_KEY     = 'sbf_token';
  var REFRESH_KEY   = 'sbf_refresh';

  function token() { return localStorage.getItem(TOKEN_KEY) || ''; }
  function refreshToken() { return localStorage.getItem(REFRESH_KEY) || ''; }

  function setTokens(access, refresh) {
    if (access) localStorage.setItem(TOKEN_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  }

  function clear() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  }

  function isLoggedIn() { return !!token(); }

  // Не запускаем обновление параллельно несколько раз, если сразу несколько
  // запросов словили 401 одновременно — все ждут ОДИН и тот же результат.
  var _refreshing = null;
  function doRefresh() {
    if (_refreshing) return _refreshing;
    var rt = refreshToken();
    if (!rt) return Promise.resolve(false);
    _refreshing = fetch(SBF_API + '/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.access_token) { clear(); return false; }
        setTokens(d.access_token, d.refresh_token || rt);
        return true;
      })
      .catch(function () { return false; })
      .then(function (result) { _refreshing = null; return result; });
    return _refreshing;
  }

  function authHeaders(extra) {
    var h = Object.assign({}, extra || {});
    var tok = token();
    if (tok) {
      h['X-Auth-Token'] = tok;
      h['Authorization'] = 'Bearer ' + tok;
    }
    return h;
  }

  function authFetch(url, opts) {
    opts = opts || {};
    var doFetch = function () {
      return fetch(url, Object.assign({}, opts, { headers: authHeaders(opts.headers) }));
    };
    return doFetch().then(function (r) {
      if (r.status !== 401 || !refreshToken()) return r;
      return doRefresh().then(function (ok) { return ok ? doFetch() : r; });
    });
  }

  window.sbfAuth = {
    token: token,
    refreshToken: refreshToken,
    setTokens: setTokens,
    clear: clear,
    isLoggedIn: isLoggedIn,
    authHeaders: authHeaders,
    fetch: authFetch,
  };
})();
