/*!
 * SBF SessionTable — таблица-мастер торгового дня (глава 5 «Глобальные Часы», §3.2)
 * ---------------------------------------------------------------------------
 * Рендерится ИЗ ДАННЫХ: web/data/edu_stats/market_hours.json.
 * В HTML не остаётся ни одного захардкоженного времени и ни одного data-utc —
 * это прямое требование приёмки главы (§8) и заодно чинит три бага текущей
 * страницы: протёкшую в текст разметку <span class='local-time'>, разъезд
 * «12:00Z подписано как 15:30 МСК» и якорь на 9 марта 2026 (дату ВНУТРИ недели
 * рассинхрона переводов часов — худший возможный якорь для главы про часы).
 *
 * Как считается время. Событие хранится в ЛОКАЛЬНОМ времени своего владельца
 * (NFP — 08:30 America/New_York, аукцион LBMA — 10:30 Europe/London, токийский
 * фикс — 09:55 Asia/Tokyo). UTC выводится через Intl на конкретную дату-якорь.
 * Поэтому режим «неделя рассинхрона» не нужно прописывать руками: он получается
 * сам, потому что 15 марта 2026 США уже на летнем времени, а Европа ещё нет.
 *
 * Переиспользуется в главе 6, в календаре и в терминале — поэтому компонент
 * вынесен из главы в общий ассет и не зависит от React.
 *
 * Использование:
 *   SBFSessionTable.mount(el, { lang: 'ru', zone: 'chisinau', mode: 'summer' })
 *   SBFSessionTable.load().then(cfg => ...)          // сырой конфиг
 *   SBFSessionTable.utcOf(event, '2026-07-15')       // Date события
 */
(function (global) {
  "use strict";

  var CONFIG_URL = "/data/edu_stats/market_hours.json";
  var _cache = null;

  var C = {
    gold: "#c9973a", goldPale: "#f7f0e3", black: "#18181a", inkMid: "#555555",
    inkSoft: "rgba(24,24,26,0.58)", inkFaint: "rgba(24,24,26,0.28)",
    border: "rgba(24,24,26,0.1)", surface: "#faf8f5",
    red: "#f23645", redPale: "#fdecea", green: "#089981", greenPale: "#eaf5ee",
    violet: "#8b5cf6"
  };

  var T = {
    ru: {
      zone: "Показать в", mode: "Режим", summer: "Лето", winter: "Зима", desync: "Неделя рассинхрона",
      colTime: "Время", colEvent: "Событие", colWeight: "Значимость",
      utc: "UTC", checked: "Часы проверены по первоисточникам на",
      desyncNote: "Три недели в году США и Европа переводят часы не одновременно — в эти дни расписание едет. Подсвечены строки, которые в этом режиме отличаются от летних.",
      loading: "Загружаю расписание…",
      error: "Не удалось загрузить market_hours.json — таблица не отрисована. Это блокирующая ошибка сборки, а не предупреждение.",
      sunday: "вс", conditional: "в свои дни", risk: "зона повышенного риска",
      showAll: "Показать все {n} событий", showLess: "Свернуть до главных",
      tapHint: "Тап — источник и описание"
    },
    ro: {
      zone: "Afișează în", mode: "Regim", summer: "Vară", winter: "Iarnă", desync: "Săptămâna de decalaj",
      colTime: "Ora", colEvent: "Eveniment", colWeight: "Importanță",
      utc: "UTC", checked: "Orele verificate la sursele primare la",
      desyncNote: "Trei săptămâni pe an SUA și Europa nu schimbă ora simultan — atunci programul se mută. Sunt evidențiate rândurile care diferă de regimul de vară.",
      loading: "Se încarcă programul…",
      error: "Nu s-a putut încărca market_hours.json — tabelul nu a fost randat. Aceasta e o eroare blocantă de build.",
      sunday: "dum", conditional: "în zilele sale", risk: "zonă de risc ridicat",
      showAll: "Arată toate cele {n} evenimente", showLess: "Restrânge la principalele",
      tapHint: "Atinge — sursă și descriere"
    },
    en: {
      zone: "Show in", mode: "Mode", summer: "Summer", winter: "Winter", desync: "Desync week",
      colTime: "Time", colEvent: "Event", colWeight: "Weight",
      utc: "UTC", checked: "Hours verified against primary sources on",
      desyncNote: "Three weeks a year the US and Europe switch clocks on different dates — the schedule shifts. Rows that differ from the summer regime are highlighted.",
      loading: "Loading the schedule…",
      error: "Could not load market_hours.json — the table was not rendered. This is a blocking build error, not a warning.",
      sunday: "Sun", conditional: "on its days", risk: "elevated risk window",
      showAll: "Show all {n} events", showLess: "Collapse to the main ones",
      tapHint: "Tap for source and description"
    }
  };

  // ─────────────────────────────────────────────────── время без библиотек

  function tzOffsetMs(date, tz) {
    var dtf = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hour12: false,
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit"
    });
    var p = {};
    dtf.formatToParts(date).forEach(function (x) { p[x.type] = x.value; });
    var asUTC = Date.UTC(+p.year, +p.month - 1, +p.day,
      p.hour === "24" ? 0 : +p.hour, +p.minute, +p.second);
    return asUTC - date.getTime();
  }

  /** Локальное время в зоне владельца → абсолютный момент (Date). */
  function zonedToUtc(dateStr, timeStr, tz) {
    var t = timeStr.length === 5 ? timeStr + ":00" : timeStr;
    var naive = Date.parse(dateStr + "T" + t + "Z");
    var ts = naive - tzOffsetMs(new Date(naive), tz);
    ts = naive - tzOffsetMs(new Date(ts), tz);   // второй проход — для границ перехода
    return new Date(ts);
  }

  function fmt(date, tz, lang, withSeconds) {
    var o = { timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false };
    if (withSeconds) o.second = "2-digit";
    var loc = lang === "ro" ? "ro-RO" : lang === "en" ? "en-GB" : "ru-RU";
    return new Intl.DateTimeFormat(loc, o).format(date);
  }

  function utcOf(ev, dateStr) {
    return zonedToUtc(dateStr, ev.local_time, ev.tz);
  }

  function utcEndOf(ev, dateStr) {
    return ev.local_time_end ? zonedToUtc(dateStr, ev.local_time_end, ev.tz) : null;
  }

  /** Строка времени события в выбранной зоне: «12:30» или «13:30–16:00». */
  function timeString(ev, dateStr, tz, lang) {
    var sec = ev.local_time.length > 5;
    var s = fmt(utcOf(ev, dateStr), tz, lang, sec);
    var e = utcEndOf(ev, dateStr);
    return e ? s + "–" + fmt(e, tz, lang, sec) : s;
  }

  // ─────────────────────────────────────────────────────────────── загрузка

  function load() {
    if (_cache) return Promise.resolve(_cache);
    return fetch(CONFIG_URL, { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("market_hours.json: HTTP " + r.status);
        return r.json();
      })
      .then(function (cfg) { _cache = cfg; return cfg; });
  }

  // ─────────────────────────────────────────────────────────────── отрисовка

  function weightDots(w) {
    var n = Math.max(0, Math.min(5, w | 0));
    return "●".repeat(n) + "○".repeat(5 - n);
  }

  function kindColor(ev) {
    if (ev.kind === "fix") return C.gold;
    if (ev.kind === "release") return C.red;
    if (ev.kind === "overlap") return C.green;
    if (ev.kind === "broker") return C.violet;
    return C.inkSoft;
  }

  function render(el, cfg, state) {
    var lang = state.lang, t = T[lang] || T.ru;
    var zone = (cfg.zones.filter(function (z) { return z.id === state.zone; })[0]) || cfg.zones[0];
    var anchor = cfg.anchors[state.mode] || cfg.anchors.summer;
    var summerAnchor = cfg.anchors.summer;

    var rows = cfg.events.map(function (ev) {
      var now = timeString(ev, anchor, zone.tz, lang);
      var ref = timeString(ev, summerAnchor, zone.tz, lang);
      var utcNow = timeString(ev, anchor, "UTC", lang);
      return { ev: ev, time: now, utc: utcNow, moved: state.mode !== "summer" && now !== ref };
    });

    // порядок — по времени суток в UTC
    rows.sort(function (a, b) { return a.utc.localeCompare(b.utc); });

    var h = [];
    h.push('<div style="display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-bottom:18px">');
    h.push('<div><span style="font-family:monospace;font-size:11px;letter-spacing:2px;color:' + C.inkSoft + ';margin-right:8px">' + t.zone.toUpperCase() + '</span>');
    cfg.zones.forEach(function (z) {
      var on = z.id === state.zone;
      h.push('<button data-zone="' + z.id + '" style="font-family:monospace;font-size:11px;letter-spacing:1px;padding:4px 10px;margin:2px;cursor:pointer;border:1px solid ' +
        (on ? C.gold : C.border) + ';background:' + (on ? C.goldPale : "#fff") + ';color:' + (on ? C.gold : C.inkMid) + '">' +
        (z["label_" + lang] || z.label_en) + '</button>');
    });
    h.push('</div>');
    h.push('<div><span style="font-family:monospace;font-size:11px;letter-spacing:2px;color:' + C.inkSoft + ';margin-right:8px">' + t.mode.toUpperCase() + '</span>');
    ["summer", "winter", "desync"].forEach(function (m) {
      var on = m === state.mode;
      h.push('<button data-mode="' + m + '" style="font-family:monospace;font-size:11px;letter-spacing:1px;padding:4px 10px;margin:2px;cursor:pointer;border:1px solid ' +
        (on ? C.gold : C.border) + ';background:' + (on ? C.goldPale : "#fff") + ';color:' + (on ? C.gold : C.inkMid) + '">' + t[m] + '</button>');
    });
    h.push('</div></div>');

    if (state.mode === "desync") {
      var w = cfg.desync_windows_2026[0];
      h.push('<div style="background:' + C.redPale + ';border:1px solid rgba(242,54,69,.25);border-radius:4px;padding:12px 16px;margin-bottom:16px;font-size:13px;line-height:1.6;color:#c0392b">' +
        t.desyncNote + ' <strong>' + w.from + ' → ' + w.to + '</strong> · ' + (w["note_" + lang] || w.note_en) + '</div>');
    }

    // SPEC_ch5_debug.md §3: шестнадцать строк в пять колонок не помещались по
    // ширине ни при какой локали, колонка «Что это» обрезалась. Теперь по
    // умолчанию видны только вес 4-5 (7-8 строк) -- переключатель разворачивает
    // все 16; колонки описания больше нет вообще -- строка кликабельна, текст
    // и источник разворачиваются под ней во всю ширину.
    var visibleRows = state.showAll ? rows : rows.filter(function (r) { return r.ev.weight >= 4; });

    h.push('<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:13px" data-session-table="' + (state.id || "") + '">');
    h.push('<thead><tr>' +
      ['colTime', 'colEvent', 'colWeight'].map(function (k, i) {
        return '<th style="text-align:left;padding:10px 14px;font-size:11px;color:' + C.inkSoft +
          ';letter-spacing:1px;border-bottom:2px solid ' + C.border + ';text-transform:uppercase;white-space:nowrap">' + t[k] + '</th>';
      }).join("") + '</tr></thead><tbody>');

    visibleRows.forEach(function (r) {
      var ev = r.ev, col = kindColor(ev);
      var open = !!state.expanded[ev.id];
      var badges = "";
      if (ev.risk) badges += '<span style="font-size:10px;font-family:monospace;color:#c0392b;background:' + C.redPale + ';padding:2px 6px;border-radius:2px;margin-left:6px">⚠ ' + t.risk + '</span>';
      if (ev.conditional) badges += '<span style="font-size:10px;font-family:monospace;color:' + C.inkSoft + ';background:' + C.surface + ';padding:2px 6px;border-radius:2px;margin-left:6px">' + t.conditional + '</span>';
      h.push('<tr data-ev-row="' + ev.id + '" style="cursor:pointer;border-bottom:1px solid ' + C.border + (r.moved ? ';background:' + C.goldPale : "") + (open ? ';background:' + C.surface : "") + '">' +
        '<td style="padding:13px 14px;font-family:monospace;white-space:nowrap;font-weight:' + (ev.highlight ? 700 : 400) + '">' +
          (ev.weekday === "sun" ? '<span style="color:' + C.inkFaint + '">' + t.sunday + ' </span>' : "") + r.time +
          '<div style="font-size:10px;color:' + C.inkFaint + '">' + r.utc + ' ' + t.utc + '</div></td>' +
        '<td style="padding:13px 14px;font-weight:600;color:' + col + '">' +
          '<span style="display:inline-block;width:12px;color:' + C.inkFaint + ';font-family:monospace">' + (open ? "▾" : "▸") + '</span> ' +
          (ev["label_" + lang] || ev.label_en) + badges + '</td>' +
        '<td style="padding:13px 14px;font-family:monospace;color:' + col + ';white-space:nowrap">' + weightDots(ev.weight) + '</td>' +
      '</tr>');
      if (open) {
        h.push('<tr data-ev-detail="' + ev.id + '" style="border-bottom:1px solid ' + C.border + ';background:' + C.surface + '">' +
          '<td colspan="3" style="padding:4px 14px 16px 40px;color:' + C.inkMid + ';line-height:1.6;font-size:12.5px">' +
            (ev["what_" + lang] || ev.what_en) +
            '<div style="font-size:10px;color:' + C.inkFaint + ';font-family:monospace;margin-top:6px">' + (ev.source || "") + '</div></td>' +
        '</tr>');
      }
    });
    h.push('</tbody></table></div>');
    h.push('<div style="font-size:11px;color:' + C.inkFaint + ';margin:10px 0 4px">' + t.tapHint + '</div>');
    h.push('<button data-toggle-all style="font-family:monospace;font-size:11.5px;letter-spacing:0.5px;padding:7px 14px;cursor:pointer;border:1px solid ' + C.border + ';background:#fff;color:' + C.inkMid + '">' +
      (state.showAll ? t.showLess : t.showAll.replace("{n}", cfg.events.length)) + '</button>');
    h.push('<div style="font-size:11px;color:' + C.inkFaint + ';margin-top:12px;line-height:1.6">' +
      t.checked + ' ' + cfg._meta.checked + ' · ' + (cfg._meta.principle || "") + '</div>');

    el.innerHTML = h.join("");

    el.querySelectorAll("button[data-zone]").forEach(function (b) {
      b.onclick = function () {
        state.zone = b.getAttribute("data-zone");
        render(el, cfg, state);
        emit(el, "zone", state.zone);
      };
    });
    el.querySelectorAll("button[data-mode]").forEach(function (b) {
      b.onclick = function () {
        state.mode = b.getAttribute("data-mode");
        render(el, cfg, state);
        emit(el, "dst", state.mode);
      };
    });
    var toggleAllBtn = el.querySelector("button[data-toggle-all]");
    if (toggleAllBtn) {
      toggleAllBtn.onclick = function () {
        state.showAll = !state.showAll;
        render(el, cfg, state);
      };
    }
    el.querySelectorAll("tr[data-ev-row]").forEach(function (tr) {
      tr.onclick = function () {
        var id = tr.getAttribute("data-ev-row");
        state.expanded[id] = !state.expanded[id];
        render(el, cfg, state);
      };
    });
  }

  function emit(el, kind, value) {
    try {
      el.dispatchEvent(new CustomEvent("sbf:sessiontable", { bubbles: true, detail: { kind: kind, value: value } }));
    } catch (e) { /* no-op */ }
  }

  /** Автоопределение зоны пользователя из браузера, с фолбэком на UTC. */
  function guessZone(cfg) {
    try {
      var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      var hit = cfg.zones.filter(function (z) { return z.tz === tz; })[0];
      return hit ? hit.id : "UTC";
    } catch (e) { return "UTC"; }
  }

  /** Летний сейчас режим или зимний — по фактической дате, а не по табличке. */
  function currentMode(cfg, date) {
    var d = date || new Date();
    var usDst = tzOffsetMs(d, "America/New_York") !== tzOffsetMs(new Date(Date.UTC(d.getUTCFullYear(), 0, 15)), "America/New_York");
    var euDst = tzOffsetMs(d, "Europe/London") !== tzOffsetMs(new Date(Date.UTC(d.getUTCFullYear(), 0, 15)), "Europe/London");
    if (usDst !== euDst) return "desync";
    return usDst ? "summer" : "winter";
  }

  function mount(el, opts) {
    opts = opts || {};
    var lang = opts.lang || "ru";
    el.innerHTML = '<div style="padding:20px;color:' + C.inkSoft + ';font-size:13px">' + (T[lang] || T.ru).loading + '</div>';
    return load().then(function (cfg) {
      var state = {
        lang: lang,
        zone: opts.zone || guessZone(cfg),
        mode: opts.mode || currentMode(cfg),
        showAll: !!opts.showAll,
        expanded: {},
        id: opts.id || ""
      };
      el._sbfState = state;
      el._sbfCfg = cfg;
      render(el, cfg, state);
      return state;
    }).catch(function (err) {
      el.innerHTML = '<div style="padding:20px;background:' + C.redPale + ';border:1px solid rgba(242,54,69,.3);border-radius:4px;color:#c0392b;font-size:13px">' +
        (T[lang] || T.ru).error + '<div style="font-family:monospace;font-size:11px;margin-top:6px">' + err.message + '</div></div>';
      throw err;
    });
  }

  // SPEC_ch5_debug.md §5: блок DST раньше монтировал ВТОРУЮ полную таблицу
  // в режиме "неделя рассинхрона" вместо переключения первой. setMode меняет
  // режим уже смонтированной таблицы извне (состояние живёт на el, см.
  // el._sbfState в mount()) и на секунду подсвечивает её рамку -- тот же
  // способ дать понять "смотри сюда", что и подсветка карты в §7, но без
  // кросс-страничного SbfAnchorReturn: источник и цель на одной странице,
  // обычный "#id"-переход не создаёт новую загрузку, на которой мог бы
  // сработать его DOMContentLoaded-триггер.
  function setMode(el, mode) {
    if (!el || !el._sbfState || !el._sbfCfg) return;
    el._sbfState.mode = mode;
    render(el, el._sbfCfg, el._sbfState);
    var prevTransition = el.style.transition, prevBoxShadow = el.style.boxShadow;
    el.style.transition = "box-shadow .25s ease";
    el.style.boxShadow = "0 0 0 3px " + C.gold;
    setTimeout(function () {
      el.style.boxShadow = prevBoxShadow || "";
      setTimeout(function () { el.style.transition = prevTransition || ""; }, 300);
    }, 1400);
  }

  global.SBFSessionTable = {
    mount: mount, load: load, utcOf: utcOf, utcEndOf: utcEndOf,
    timeString: timeString, zonedToUtc: zonedToUtc, tzOffsetMs: tzOffsetMs,
    guessZone: guessZone, currentMode: currentMode, setMode: setMode
  };
})(window);
