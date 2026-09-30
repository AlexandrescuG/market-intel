/* sbf-attrib.js — источник перехода, 27.08.2026.

   ЗАЧЕМ. До этого файла метки кампаний не доезжали до регистрации ни при
   каких условиях: `_handle_register_via_survey` (serve.py) принимал почту,
   пароль, имя, согласия и ответы опроса — полей под источник там не было
   вовсе. То есть человек приходил по ссылке вида
   ?utm_source=facebook&utm_campaign=kw-acces-ro, регистрировался, и сказать,
   из какого ролика он пришёл, было невозможно.

   ПОЧЕМУ СЕССИЯ, А НЕ URL В МОМЕНТ ОТПРАВКИ. Метки стоят на ссылке, по
   которой человек ВОШЁЛ на сайт, а регистрируется он двумя-тремя страницами
   позже — с /brokers или с пейволла главы 6. К моменту отправки формы в
   адресной строке их уже нет. Поэтому ловим на первом же заходе и держим в
   sessionStorage до конца визита.

   ПЕРВОЕ КАСАНИЕ ПОБЕЖДАЕТ. Если метки уже сохранены, повторный заход с
   другими не перезаписывает их: иначе переход внутри сайта по ссылке с
   меткой (например из брифинга) затирал бы настоящий источник. */
(function (w) {
  'use strict';

  var KEY = 'sbf_attrib';
  var FIELDS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'];

  function read() {
    try {
      var raw = w.sessionStorage.getItem(KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  function capture() {
    if (read()) return;                       // первое касание уже записано
    var out = {};
    try {
      var q = new URLSearchParams(w.location.search);
      FIELDS.forEach(function (f) {
        var v = q.get(f);
        if (v) out[f] = String(v).slice(0, 120);
      });
    } catch (e) { /* старый браузер без URLSearchParams — пропускаем */ }

    // Реферер полезен, даже когда меток нет: показывает, что человек пришёл
    // не напрямую. Свои же страницы не считаем источником.
    try {
      if (w.document.referrer && w.document.referrer.indexOf(w.location.host) === -1) {
        out.referrer = w.document.referrer.slice(0, 200);
      }
    } catch (e) { /* пусто */ }

    // Landing запоминаем всегда: даже без меток видно, на какую страницу
    // человек приземлился — это уже отвечает на «с какого ролика».
    out.landing = (w.location.pathname || '/').slice(0, 120);

    var hasSource = FIELDS.some(function (f) { return out[f]; }) || out.referrer;
    if (!hasSource) return;                   // прямой заход — не засоряем хранилище

    try { w.sessionStorage.setItem(KEY, JSON.stringify(out)); } catch (e) { /* приватный режим */ }
  }

  capture();

  w.sbfAttrib = {
    /* Объект для отправки на сервер. Пустой объект, если источника нет —
       вызывающему не нужно проверять на null. */
    get: function () { return read() || {}; }
  };
})(window);
