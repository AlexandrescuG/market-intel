/* ============================================================================
   SBF INTELLIGENCE — анонимная личность читателя курса.
   SPEC_chart_fixes_and_staged_signup.md §5, Этап 0: до регистрации у
   анонимного визитёра нет user_id -- все анонимные посетители сайта делят
   один общий "default" (serve.py::_current_user_id). Прогресс по главам
   (какие прочитаны) поэтому раньше никогда не мог сохраняться персонально
   ДО регистрации. Этот токен -- личный, только для прогресса по курсу
   (НЕ полноценная identity, не подменяет sbfAuth) -- переносится на
   настоящего пользователя один раз, при регистрации (см. register.html,
   serve.py::_handle_auth_register → journal_gamification.migrate_anon_progress).

   Подключать БЕЗ defer, как sbf-symbols.js -- главы книги дергают
   markChapterRead() из синхронного инлайн-скрипта сразу при монтировании.
   ========================================================================= */
(function () {
  'use strict';

  var KEY = 'sbf_anon_id';

  function _genId() {
    if (window.crypto && window.crypto.randomUUID) {
      return 'anon_' + window.crypto.randomUUID().replace(/-/g, '');
    }
    return 'anon_' + Date.now().toString(36) + Math.random().toString(36).slice(2);
  }

  function getAnonId() {
    var id = null;
    try {
      id = localStorage.getItem(KEY);
      if (!id) {
        id = _genId();
        localStorage.setItem(KEY, id);
      }
      // Кука — best-effort резерв (не основной источник): localStorage
      // хватает для fetch-запросов этой же вкладки/браузера, кука не нужна
      // для чтения сервером здесь (в отличие от sbf_session в sbf-auth.js,
      // которому кука нужна для обычной навигации страницы).
      document.cookie = KEY + '=' + id + '; path=/; max-age=' + (365 * 86400) + '; SameSite=Lax';
    } catch (e) {}
    return id;
  }

  function clearAnonId() {
    try {
      localStorage.removeItem(KEY);
      document.cookie = KEY + '=; path=/; max-age=0; SameSite=Lax';
    } catch (e) {}
  }

  function markChapterRead(chapterNumber) {
    var anonId = getAnonId();
    var headers = { 'Content-Type': 'application/json' };
    if (anonId) headers['X-Anon-Id'] = anonId;
    var doFetch = (window.sbfAuth && window.sbfAuth.fetch) || fetch;
    return doFetch('/api/journal/course/complete', {
      method: 'POST', headers: headers,
      body: JSON.stringify({ chapter_number: chapterNumber }),
    }).catch(function () {});
  }

  window.SBFAnon = { getAnonId: getAnonId, clearAnonId: clearAnonId, markChapterRead: markChapterRead };
})();
