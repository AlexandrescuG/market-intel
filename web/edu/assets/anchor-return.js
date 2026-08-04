/*
 * anchor-return.js — «Якоря с возвратом» (SPEC_ch2_debug_and_chart_engine.md
 * §5). Курс постоянно ссылается сам на себя («см. главу 4», «глава 3
 * объясняла») и на конкретные станции хроники (напр. станция 11, франк
 * 2015) — сейчас любая такая ссылка билет в один конец. Механика:
 *
 * 1. Ссылка с data-anchor-return-title="…" при клике пишет в sessionStorage
 *    {url, title, ts} с адресом СТРАНИЦЫ-ИСТОЧНИКА (не куда ведёт ссылка).
 * 2. Целевая страница при загрузке читает запись; если она свежая
 *    (<30 минут), показывает плашку «← Назад: …», ЛЮБОЙ дальнейший переход
 *    (клик по плашке, по другой ссылке, кнопка "назад" браузера) не оставит
 *    эту запись для следующей страницы — она read-once, стирается сразу
 *    после чтения, вне зависимости от того, что пользователь сделает потом.
 *    Ровно это и даёт свойство "ушёл сам -- плашка больше не появится"
 *    (§5.2), без слежки за кликами/history после рендера.
 * 3. window.SbfAnchorReturn.setStationAnchor(slug) — станции хроники
 *    (chrono.js/chrono2.js) вызывают это при выборе станции, чтобы адрес
 *    обновился через history.replaceState (не засоряя историю браузера) и
 *    ссылку на конкретную станцию можно было скопировать из адресной строки.
 *
 * Подключается глобально во все edu-страницы (_build_edu_page() в serve.py,
 * тот же принцип, что academy-shared.js/sbf-header.js) -- обе главы-источник
 * и глава-цель могут быть любыми, retrofit конкретных "см. главу N" ссылок
 * во все 15 глав prose — отдельная, более объёмная задача не входит в эту
 * спеку (сделан только сам механизм + одна реальная ссылка станции 2015 SNB
 * в главе 2 как пруф-оф-концепт, см. STATION_LINK_KEY использование).
 */
(function () {
  var KEY = "sbf_anchor_return";
  var TTL_MS = 30 * 60 * 1000;
  var MOBILE_BREAKPOINT = 760;
  var BACK_LABEL = { ru: "Назад", ro: "Înapoi", en: "Back" };

  function detectLang() {
    // Тот же regex, что i18n.js::detectLang() -- продублирован, а не вызван
    // напрямую: window.sbfI18n.t() резолвится асинхронно (словарь качается
    // по сети), а плашка рендерится на DOMContentLoaded, до того как DICT
    // гарантированно наполнен -- гонка дала бы русский текст на /en//ro
    // страницах. Тот же приём уже применён в calendar-terms.js/chrono2.js.
    var m = location.pathname.match(/^\/(ro|en)(\/|$)/) || location.pathname.match(/^\/edu\/(ro|en)\/b\//);
    return m ? m[1] : "ru";
  }

  function readEntry() {
    try {
      var raw = sessionStorage.getItem(KEY);
      if (!raw) return null;
      var e = JSON.parse(raw);
      if (!e || !e.url || !e.title || !e.ts) return null;
      if (Date.now() - e.ts > TTL_MS) return null;
      return e;
    } catch (err) {
      return null;
    }
  }

  function clearEntry() {
    try { sessionStorage.removeItem(KEY); } catch (err) {}
  }

  function writeEntry(title) {
    try {
      sessionStorage.setItem(KEY, JSON.stringify({
        url: location.pathname + location.search + location.hash,
        title: title,
        ts: Date.now(),
      }));
    } catch (err) {}
  }

  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest("a[data-anchor-return-title]");
    if (!a) return;
    writeEntry(a.getAttribute("data-anchor-return-title"));
  }, true);

  function injectStyle() {
    if (document.getElementById("sbf-anchor-return-style")) return;
    var s = document.createElement("style");
    s.id = "sbf-anchor-return-style";
    // bottom:66px -- КАЖДАЯ страница главы курса рендерит .edu-nav (нижний
    // нав "Далее/Назад/Содержание", инжектируется сервером в _edu_inject(),
    // fixed/bottom:0/height:48px/z-index:999, edu.css) -- это выше и ближе
    // к плашке, чем мобильный .g-bottom-nav (58px), и присутствует ВСЕГДА,
    // не только на мобильном. Живой Playwright-прогон поймал: плашка на
    // bottom:20px пряталась под .edu-nav целиком, клик не проходил (её
    // элемент в этой точке экрана перекрыт баром с z-index:999 > 190).
    s.textContent =
      ".sbf-anchor-return{position:fixed;left:50%;bottom:66px;transform:translateX(-50%);" +
      "z-index:190;background:#141416;color:#F3E8C8;font-family:'Courier New',monospace;" +
      "font-size:12.5px;letter-spacing:.02em;padding:11px 20px;border-radius:24px;cursor:pointer;" +
      "box-shadow:0 8px 24px rgba(0,0,0,.28);max-width:min(92vw,480px);white-space:nowrap;" +
      "overflow:hidden;text-overflow:ellipsis;transition:opacity .15s}" +
      ".sbf-anchor-return:hover{opacity:.9}" +
      "@media(max-width:" + MOBILE_BREAKPOINT + "px){.sbf-anchor-return{bottom:calc(var(--g-bn-h,58px) + 14px)}}";
    document.head.appendChild(s);
  }

  function renderPill(entry) {
    injectStyle();
    var label = BACK_LABEL[detectLang()] || BACK_LABEL.ru;
    var wrap = document.createElement("div");
    wrap.className = "sbf-anchor-return";
    wrap.textContent = "← " + label + ": " + entry.title;
    wrap.addEventListener("click", function () {
      location.href = entry.url;
    });
    document.body.appendChild(wrap);
  }

  function init() {
    var entry = readEntry();
    clearEntry(); // read-once: следующая страница эту запись уже не увидит
    if (entry) renderPill(entry);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.SbfAnchorReturn = {
    setStationAnchor: function (slug) {
      if (!slug) return;
      var hash = "#" + slug;
      if (location.hash !== hash) {
        history.replaceState(null, "", location.pathname + location.search + hash);
      }
    },
  };
})();
