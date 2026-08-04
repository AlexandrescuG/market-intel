/*
 * simple-lang.js — глобальный переключатель «Просто / Как есть»
 * (SPEC_ch2_debug_and_chart_engine.md §3). Состояние в localStorage,
 * действует на все главы курса (не только там, где уже есть переключатель
 * в шапке): если пользователь один раз выбрал "Просто" на главе 2, глава 5
 * позже унаследует тот же выбор, как только в ней появятся _simple-блоки.
 *
 * Профиль авторизованного пользователя НЕ подключён в этом проходе (§3.2
 * просит "хранится в профиле... и в localStorage") — у текущей auth-схемы
 * (sbf-auth.js/bot.db) нет таблицы generic-preferences, заводить отдельный
 * backend-эндпоинт и колонку ради одного read-переключателя избыточно
 * относительно ценности; localStorage покрывает основной сценарий (выбор
 * живёт на устройстве). Кросс-девайс синк — кандидат на будущее, когда/если
 * появится настоящая таблица пользовательских настроек.
 *
 * pick(strings, key) -- общее правило спеки "блоки без _simple-версии не
 * меняются": работает с ЛЮБЫМ объектом, где рядом с strings[key] может
 * существовать strings[key+"_simple"] -- одинаково подходит и для STRINGS
 * (edu_book_N.html), и для station-объектов хроники (chrono.js/chrono2.js).
 */
(function () {
  var KEY = "sbf_simple_lang";
  var mode = (function () {
    try { return localStorage.getItem(KEY) === "simple" ? "simple" : "pro"; } catch (e) { return "pro"; }
  })();
  var subs = [];

  function get() { return mode; }

  function set(next) {
    if (next !== "simple" && next !== "pro") return;
    mode = next;
    try { localStorage.setItem(KEY, mode); } catch (e) {}
    subs.forEach(function (cb) { try { cb(mode); } catch (e) {} });
  }

  function subscribe(cb) {
    subs.push(cb);
    return function () { subs = subs.filter(function (c) { return c !== cb; }); };
  }

  function pick(strings, key) {
    if (mode === "simple" && strings[key + "_simple"] != null) return strings[key + "_simple"];
    return strings[key];
  }

  window.SbfSimpleLang = { get: get, set: set, subscribe: subscribe, pick: pick };
})();
