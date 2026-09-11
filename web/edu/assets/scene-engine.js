/**
 * SceneEngine — движок «сцен машины времени» главы 2 (SPEC_edu_level2_central_banks.md §4).
 * Три режима поверх Lightweight Charts, на реальных данных из web/data/edu_scenes/*.json:
 *
 *   EVENT  — решение до раскрытия: график обрывается перед маркером, пользователь выбирает
 *            ответ, затем график достраивается и показывается, что случилось на самом деле.
 *   REPLAY — марафон по чек-пойнтам (например, 12 заседаний FOMC): «Дальше →» пошагово
 *            достраивает график до каждой следующей даты и показывает решение.
 *   STORY  — скроллителлинг: N аннотаций вдоль оси времени, «Дальше →» шагает по ним,
 *            подсвечивая на графике момент, к которому относится текст.
 *   MULTI  — N синхронных мини-графиков (глава 3, cold open): все данные уже показаны
 *            целиком (не прогрессивный реплей), пользователь тапает по графикам, отвечая
 *            на вопрос, затем жмёт «Проверить» и видит, какие тапы были верными.
 *
 * Использование: SceneEngine.mount(containerEl, {mode, data, symbol, copy, lang})
 * data — уже загруженный JSON одного из файлов web/data/edu_scenes/ch2_*.json.
 * Не требует React — используется и в vanilla-превью, и (через ref-callback) в живой JSX главе.
 */
window.SceneEngine = (function () {
  "use strict";

  var LWC_CDN = "https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js";
  var _lwcReady = typeof LightweightCharts !== "undefined" ? Promise.resolve() : null;
  function ensureLWC() {
    if (_lwcReady) return _lwcReady;
    _lwcReady = new Promise(function (res, rej) {
      var s = document.createElement("script");
      s.src = LWC_CDN; s.onload = res; s.onerror = rej;
      document.head.appendChild(s);
    });
    return _lwcReady;
  }

  function toUnixTime(t) {
    // 'YYYY-MM-DD' -> LWC business-day string (fine as-is);
    // ISO with time ('YYYY-MM-DDTHH:MM:SSZ') -> Unix seconds (LWC needs UTCTimestamp for intraday).
    if (typeof t === "string" && t.indexOf("T") >= 0) {
      return Math.floor(new Date(t).getTime() / 1000);
    }
    return t;
  }

  function baseChartOpts(h) {
    return {
      width: 0, height: h,
      layout: { background: { color: "transparent" }, textColor: "#55524B" },
      grid: { vertLines: { color: "#E7DFCF" }, horzLines: { color: "#E7DFCF" } },
      rightPriceScale: { borderColor: "#E7DFCF" },
      timeScale: { borderColor: "#E7DFCF", timeVisible: true, secondsVisible: false }
    };
  }

  function makeChart(el, h) {
    var chart = LightweightCharts.createChart(el, baseChartOpts(h));
    return chart;
  }

  function fmtLine(color) {
    return { color: color, lineWidth: 2, lastValueVisible: true, priceLineVisible: false };
  }

  /* ---------------------------------------------------------------- shell (chrome shared by all 3 modes) */
  function shell(container, copy) {
    container.innerHTML =
      '<div class="scn-wrap">' +
        '<div class="scn-chart" style="height:240px"></div>' +
        '<div class="scn-panel"></div>' +
      '</div>';
    return {
      chartEl: container.querySelector(".scn-chart"),
      panelEl: container.querySelector(".scn-panel")
    };
  }

  function btn(label, kind) {
    var b = document.createElement("button");
    b.className = "h-btn" + (kind === "ghost" ? " ghost" : "");
    b.textContent = label;
    return b;
  }

  // Кнопка-выбор в сетке решения (EVENT/MULTI): полноразмерная, рамка, текст
  // по левому краю -- не пилюля навигации (SPEC_ch2_debug_and_chart_engine.md §1.5).
  function choiceBtn(label, onClick) {
    var b = document.createElement("button");
    b.className = "scn-choice";
    b.textContent = label;
    b.onclick = onClick;
    return b;
  }

  /* ---------------------------------------------------------------- EVENT mode */
  function mountEvent(container, opts) {
    ensureLWC().then(function () {
      var refs = shell(container, opts.copy);
      var series = opts.data.series ? opts.data.series[opts.symbol] : null;
      var candles = opts.data.candles || null;
      var isOHLC = !!candles;
      var points = isOHLC ? candles : series;
      var markers = opts.data.meta.markers || (opts.data.meta.marker_time ? [{ date: opts.data.meta.marker_time, label: opts.data.meta.marker_label }] : []);
      if (!markers.length) return;

      var chart = makeChart(refs.chartEl, 240);
      var priceSeries = isOHLC
        ? chart.addCandlestickSeries({ upColor: "#2E7D5B", downColor: "#B14848", borderVisible: false, wickUpColor: "#2E7D5B", wickDownColor: "#B14848" })
        : chart.addLineSeries(fmtLine("#3a3630"));

      function cutIdx(markerDate) {
        var mt = toUnixTime(markerDate);
        for (var i = 0; i < points.length; i++) {
          var pt = toUnixTime(points[i].time);
          if (pt >= mt) return i;
        }
        return points.length - 1;
      }

      var stepIdx = 0; // which marker we're deciding on
      var revealed = false;

      function toBar(p) {
        return isOHLC ? { time: toUnixTime(p.time), open: p.open, high: p.high, low: p.low, close: p.close }
                       : { time: toUnixTime(p.time), value: p.close };
      }

      function render() {
        var cut = cutIdx(markers[stepIdx].date || markers[stepIdx].time);
        var visible = points.slice(0, revealed ? Math.min(points.length, cut + Math.max(6, Math.round((points.length - cut) * 0.35))) : cut + 1);
        if (revealed && stepIdx === markers.length - 1) visible = points; // last step: reveal everything
        priceSeries.setData(visible.map(toBar));
        chart.timeScale().fitContent();

        refs.panelEl.innerHTML = "";
        var label = document.createElement("div");
        label.className = "scn-marker-label";
        label.textContent = markers[stepIdx].label;
        refs.panelEl.appendChild(label);

        if (!revealed) {
          var q = document.createElement("p");
          q.className = "scn-question";
          q.textContent = opts.copy.question || "Твоё решение?";
          refs.panelEl.appendChild(q);
          var row = document.createElement("div");
          row.className = "scn-choicegrid";
          (opts.copy.options || ["Покупаю", "Продаю", "Жду"]).forEach(function (label) {
            row.appendChild(choiceBtn(label, function () {
              revealed = true;
              render();
            }));
          });
          refs.panelEl.appendChild(row);
        } else {
          var rev = document.createElement("p");
          rev.className = "scn-reveal";
          rev.textContent = opts.copy.revealText || "";
          refs.panelEl.appendChild(rev);
          if (stepIdx < markers.length - 1) {
            var nb = btn(opts.copy.nextMarker || "Следующее решение →");
            nb.onclick = function () { stepIdx++; revealed = false; render(); };
            refs.panelEl.appendChild(nb);
          } else if (opts.copy.onDone) {
            opts.copy.onDone(refs.panelEl);
          }
        }
      }
      render();

      new ResizeObserver(function () {
        var w = refs.chartEl.clientWidth;
        if (w > 0) chart.resize(w, 240);
      }).observe(refs.chartEl);
    });
  }

  /* ---------------------------------------------------------------- STORY mode */
  function mountStory(container, opts) {
    ensureLWC().then(function () {
      var refs = shell(container, opts.copy);
      var candles = opts.data.candles;
      var chart = makeChart(refs.chartEl, 240);
      var series = chart.addCandlestickSeries({ upColor: "#2E7D5B", downColor: "#B14848", borderVisible: false, wickUpColor: "#2E7D5B", wickDownColor: "#B14848" });
      series.setData(candles.map(function (c) { return { time: toUnixTime(c.time), open: c.open, high: c.high, low: c.low, close: c.close }; }));
      chart.timeScale().fitContent();

      var steps = opts.copy.steps || [];
      var stepIdx = 0;

      function render() {
        var s = steps[stepIdx];
        if (s && s.markerTime) {
          series.setMarkers([{ time: toUnixTime(s.markerTime), position: "aboveBar", color: "#C9A227", shape: "arrowDown", text: "◆" }]);
        } else {
          series.setMarkers([]);
        }
        refs.panelEl.innerHTML = "";
        var dots = document.createElement("div");
        dots.className = "scn-dots";
        steps.forEach(function (_, i) {
          var d = document.createElement("span");
          d.className = "scn-dot" + (i === stepIdx ? " active" : i < stepIdx ? " done" : "");
          dots.appendChild(d);
        });
        refs.panelEl.appendChild(dots);
        var p = document.createElement("p");
        p.className = "scn-story-text";
        p.textContent = s ? s.text : "";
        refs.panelEl.appendChild(p);
        var row = document.createElement("div");
        row.className = "scn-btnrow";
        if (stepIdx > 0) {
          var pb = btn(opts.copy.prev || "← Назад", "ghost");
          pb.onclick = function () { stepIdx--; render(); };
          row.appendChild(pb);
        }
        if (stepIdx < steps.length - 1) {
          var nb = btn(opts.copy.next || "Дальше →");
          nb.onclick = function () { stepIdx++; render(); };
          row.appendChild(nb);
        }
        refs.panelEl.appendChild(row);
      }
      render();

      new ResizeObserver(function () {
        var w = refs.chartEl.clientWidth;
        if (w > 0) chart.resize(w, 240);
      }).observe(refs.chartEl);
    });
  }

  /* ---------------------------------------------------------------- REPLAY mode */
  // SPEC_ch2_debug_and_chart_engine.md §4: свечи там, где есть OHLC (§4.4/4.9),
  // зум/пан с ограничением по данным, двунаправленная навигация кнопками +
  // клавиатурой + таймлайн-скраббером (§4.3), смена инструмента с сохранением
  // видимого диапазона (§4.5), режим сравнения до 3 инструментов с нормировкой
  // к 100% на баре события (§4.6), маркер + вертикальная подсветка + кнопка
  // "к событию" (§4.7). Заголовок и весь UI-текст -- из opts.copy, идентификатор
  // сцены (ch2_cycle_2022 и т.п.) сюда не попадает нигде (§4.2).
  function mountReplay(container, opts) {
    ensureLWC().then(function () {
      var refs = shell(container, opts.copy);
      refs.chartEl.classList.add("scn-chart-wrap");
      var copy = opts.copy || {};
      var checkpoints = opts.data.fomc_meetings || [];
      var symbols = (opts.data.meta && opts.data.meta.symbols) || Object.keys(opts.data.candles || opts.data.series || {});
      var COLORS = ["#3a3630", "#c9973a", "#2563eb"];

      function dataFor(sym) {
        if (opts.data.candles && opts.data.candles[sym]) return { ohlc: true, points: opts.data.candles[sym] };
        if (opts.data.series && opts.data.series[sym]) return { ohlc: false, points: opts.data.series[sym] };
        return { ohlc: false, points: [] };
      }

      var activeSymbol = symbols.indexOf(opts.symbol) >= 0 ? opts.symbol : symbols[0];
      var compareMode = false;   // включается отдельной кнопкой -- не выводится из кликов по пилюлям
      var compareSymbols = [];   // валиден, только когда compareMode===true; >=2 -- реально показывается сравнение
      var stepIdx = 0;
      var maxRevealed = 0; // "furthest visited" -- шаг назад не прячет уже открытое

      var chart = makeChart(refs.chartEl, 240);
      chart.applyOptions({ handleScroll: true, handleScale: true, timeScale: { fixLeftEdge: true, fixRightEdge: true } });

      // Все серии создаются РОВНО ОДИН раз при монтировании и никогда не
      // удаляются -- single/compare и смена инструмента переключаются через
      // setData()+visible, а не addSeries()/removeSeries() на каждый клик.
      // Живой Playwright-прогон поймал "Value is null"/"Assertion failed:
      // Series not found" при динамическом add/remove series на каждое
      // взаимодействие -- пересоздание серий на лету хрупко относительно
      // внутреннего состояния LWC v4, статичные слоты этого не имеют.
      var candleSeries = chart.addCandlestickSeries({ upColor: "#2E7D5B", downColor: "#B14848", borderVisible: false, wickUpColor: "#2E7D5B", wickDownColor: "#B14848", visible: false });
      var lineSeriesMain = chart.addLineSeries(Object.assign({}, fmtLine(COLORS[0]), { visible: false }));
      var compareSlots = [0, 1, 2].map(function (i) {
        return chart.addLineSeries({
          color: COLORS[i % COLORS.length], lineWidth: 2, lastValueVisible: true, priceLineVisible: false, visible: false,
          priceFormat: { type: "custom", minMove: 0.01, formatter: function (v) { return (v >= 0 ? "+" : "") + v.toFixed(1) + "%"; } },
        });
      });
      // Вертикальная подсветка события -- нет готового примитива в LWC v4,
      // рабочий приём: гистограмма с одним столбцом на своей отдельной,
      // невидимой шкале без полей -- столбец растягивается на всю высоту (§4.7.2).
      var hlSeries = chart.addHistogramSeries({ priceScaleId: "scn-hl", priceLineVisible: false, lastValueVisible: false, color: "rgba(201,162,39,.16)" });
      chart.priceScale("scn-hl").applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });

      function visiblePoints(points) {
        var revealTo = Math.max(stepIdx, maxRevealed);
        var cutTime = toUnixTime(checkpoints[revealTo].date);
        var end = points.length;
        for (var i = 0; i < points.length; i++) { if (toUnixTime(points[i].time) > cutTime) { end = i; break; } }
        return points.slice(0, Math.max(Math.min(points.length, end + 3), 2));
      }

      function applyMarkers(series) {
        var revealTo = Math.max(stepIdx, maxRevealed);
        var markers = [];
        for (var i = 0; i <= revealTo; i++) {
          var cp = checkpoints[i], isCurrent = i === stepIdx;
          var sign = cp.decision_bp > 0 ? "+" + cp.decision_bp : (copy.noChange || "0");
          markers.push({
            time: toUnixTime(cp.date), position: "aboveBar",
            color: isCurrent ? "#C9A227" : "rgba(58,54,48,.35)", shape: "arrowDown",
            text: isCurrent ? sign + " " + (copy.bpUnit || "bp") : sign,
          });
        }
        series.setMarkers(markers);
        hlSeries.setData([{ time: toUnixTime(checkpoints[stepIdx].date), value: 1 }]);
      }

      // ТОЛЬКО visible:false, БЕЗ setData([]) -- три живых Playwright-прогона
      // подряд поймали "Value is null" изнутри LWC именно на setData([]) для
      // серии, которая в этот момент активна/видима и держит fixLeftEdge/
      // fixRightEdge якорь диапазона (timeScale в mountReplay их включает).
      // Пустые данные на currently-anchoring серии ломают её внутренний
      // пересчёт getVisibleRange на следующем кадре. Раз серия скрыта --
      // устаревшие данные в ней не видны и не мешают: очищать нечего,
      // следующий показ этого слота всё равно перезапишет их свежими через
      // setData() ДО возврата visible:true (см. renderCompare/renderSingle).
      function hideSeries(series) {
        series.setMarkers([]);
        series.applyOptions({ visible: false });
      }

      function renderSingle() {
        compareSlots.forEach(hideSeries);
        var d = dataFor(activeSymbol);
        var active = d.ohlc ? candleSeries : lineSeriesMain;
        var inactive = d.ohlc ? lineSeriesMain : candleSeries;
        hideSeries(inactive);
        var visible = visiblePoints(d.points);
        active.setData(visible.map(function (p) {
          return d.ohlc ? { time: toUnixTime(p.time), open: p.open, high: p.high, low: p.low, close: p.close }
                         : { time: toUnixTime(p.time), value: p.close };
        }));
        active.applyOptions({ visible: true });
        applyMarkers(active);
      }

      function renderCompare() {
        hideSeries(candleSeries);
        hideSeries(lineSeriesMain);
        var syms = compareSymbols.slice(0, 3), cpTime = toUnixTime(checkpoints[stepIdx].date);
        compareSlots.forEach(function (slot, i) {
          var sym = syms[i];
          if (!sym) { hideSeries(slot); return; }
          slot.setMarkers([]); // маркеры с прошлого рендера этого слота (другой инструмент) -- снять раньше setData
          var d = dataFor(sym);
          var visible = visiblePoints(d.points);
          var baseIdx = 0;
          for (var k = 0; k < visible.length; k++) { if (toUnixTime(visible[k].time) <= cpTime) baseIdx = k; }
          var base = visible[baseIdx] ? visible[baseIdx].close : (visible[0] && visible[0].close);
          slot.setData(base ? visible.map(function (p) { return { time: toUnixTime(p.time), value: ((p.close / base) - 1) * 100 }; }) : []);
          slot.applyOptions({ visible: true, title: sym });
          if (i === 0) applyMarkers(slot);
        });
      }

      function renderChartOnly() { if (compareMode && compareSymbols.length >= 2) renderCompare(); else renderSingle(); }

      // Индекс бара в points, а не арифметика над самим временем: сцена
      // использует "YYYY-MM-DD" (business-day), а getVisibleRange()/toUnixTime()
      // для такого формата не отдают число -- prevRange.to-prevRange.from даёт
      // NaN (живой баг, пойман Playwright-верификацией). Используем ЛОГИЧЕСКИЙ
      // диапазон (getVisibleLogicalRange/setVisibleLogicalRange) -- он всегда
      // просто индексы баров, не зависит от формата времени вообще.
      function displayPoints() {
        var sym = (compareMode && compareSymbols.length) ? compareSymbols[0] : activeSymbol;
        return dataFor(sym).points;
      }
      function findIdx(points, dateStr) {
        var mt = toUnixTime(dateStr);
        for (var i = 0; i < points.length; i++) { if (toUnixTime(points[i].time) >= mt) return i; }
        return points.length - 1;
      }

      function centerOnStep(prevLogicalRange) {
        var points = displayPoints();
        var cpIdx = findIdx(points, checkpoints[stepIdx].date);
        var halfSpan = prevLogicalRange ? Math.max(3, Math.round((prevLogicalRange.to - prevLogicalRange.from) / 2)) : 35;
        chart.timeScale().setVisibleLogicalRange({ from: cpIdx - halfSpan, to: cpIdx + halfSpan });
      }

      function currentTimeInRange() {
        var vr = chart.timeScale().getVisibleLogicalRange();
        if (!vr) return true;
        var cpIdx = findIdx(displayPoints(), checkpoints[stepIdx].date);
        return cpIdx >= vr.from && cpIdx <= vr.to;
      }

      var backBtnEl = null;
      function updateBackToEventBtn() {
        if (backBtnEl) { backBtnEl.remove(); backBtnEl = null; }
        if (currentTimeInRange()) return;
        backBtnEl = document.createElement("button");
        backBtnEl.className = "scn-back-to-event";
        backBtnEl.textContent = copy.backToEvent || "↩ К событию";
        backBtnEl.onclick = function () { centerOnStep(chart.timeScale().getVisibleLogicalRange()); };
        refs.chartEl.appendChild(backBtnEl);
      }

      function goToStep(newIdx) {
        var preserved = chart.timeScale().getVisibleLogicalRange();
        stepIdx = newIdx;
        maxRevealed = Math.max(maxRevealed, stepIdx);
        renderChartOnly();
        centerOnStep(preserved);
        renderChrome();
      }

      function switchInstrument(mutate) {
        var preserved = chart.timeScale().getVisibleLogicalRange();
        mutate();
        renderChartOnly();
        if (preserved) chart.timeScale().setVisibleLogicalRange(preserved);
        renderChrome();
      }

      function renderChrome() {
        refs.panelEl.innerHTML = "";

        var head = document.createElement("div");
        head.className = "scn-replay-head";
        var title = document.createElement("div");
        title.className = "scn-replay-title";
        title.textContent = copy.title || "";
        head.appendChild(title);
        if (copy.periodLabel) {
          var period = document.createElement("div");
          period.className = "scn-replay-period";
          period.textContent = copy.periodLabel;
          head.appendChild(period);
        }
        refs.panelEl.appendChild(head);

        var symRow = document.createElement("div");
        symRow.className = "scn-symbol-row";
        symbols.forEach(function (sym) {
          var pill = document.createElement("button");
          var cmpIdx = compareSymbols.indexOf(sym);
          var inCompare = compareMode && cmpIdx >= 0;
          pill.className = "scn-symbol-pill" +
            (!compareMode && sym === activeSymbol ? " active" : "") +
            (inCompare ? " compare-on" : "");
          if (inCompare) { pill.style.borderLeftWidth = "3px"; pill.style.borderLeftColor = COLORS[cmpIdx % COLORS.length]; }
          pill.textContent = sym;
          pill.onclick = function () {
            switchInstrument(function () {
              if (compareMode) {
                var i = compareSymbols.indexOf(sym);
                if (i >= 0 && compareSymbols.length > 1) compareSymbols.splice(i, 1); // не даём остаться с 0 инструментов
                else if (i < 0 && compareSymbols.length < 3) compareSymbols.push(sym);
              } else {
                activeSymbol = sym;
              }
            });
          };
          symRow.appendChild(pill);
        });
        var cmpBtn = document.createElement("button");
        cmpBtn.className = "scn-tool-btn" + (compareMode ? " active" : "");
        cmpBtn.textContent = compareMode ? (copy.compareToggleOff || "✕ Сравнение") : (copy.compareToggle || "⇄ Сравнить");
        cmpBtn.onclick = function () {
          switchInstrument(function () {
            compareMode = !compareMode;
            compareSymbols = compareMode ? [activeSymbol] : [];
          });
        };
        symRow.appendChild(cmpBtn);
        refs.panelEl.appendChild(symRow);

        if (compareMode && compareSymbols.length >= 2) {
          var note = document.createElement("div");
          note.className = "scn-compare-note";
          note.textContent = copy.compareNote || "";
          refs.panelEl.appendChild(note);
        } else if (compareMode) {
          var hint = document.createElement("div");
          hint.className = "scn-compare-note";
          hint.textContent = copy.comparePickHint || "";
          refs.panelEl.appendChild(hint);
        }

        var meetingMeta = document.createElement("div");
        meetingMeta.className = "scn-marker-label";
        var cp = checkpoints[stepIdx];
        meetingMeta.textContent = (copy.meetingLabel || "Заседание") + " " + (stepIdx + 1) + " " + (copy.ofLabel || "из") + " " + checkpoints.length +
          " · " + cp.date + " · " + (cp.decision_bp > 0 ? "+" + cp.decision_bp + " " + (copy.bpUnit || "bp") : (copy.noChangeFull || copy.noChange || "без изменений")) + " → " + cp.rate_after;
        refs.panelEl.appendChild(meetingMeta);

        var timeline = document.createElement("div");
        timeline.className = "scn-timeline";
        checkpoints.forEach(function (_, i) {
          var d = document.createElement("button");
          d.className = "scn-timeline-dot" + (i === stepIdx ? " active" : i <= maxRevealed ? " done" : "");
          d.setAttribute("aria-label", (copy.meetingLabel || "Заседание") + " " + (i + 1));
          d.onclick = function () { goToStep(i); };
          timeline.appendChild(d);
        });
        refs.panelEl.appendChild(timeline);

        var toolRow = document.createElement("div");
        toolRow.className = "scn-toolrow";
        var navRow = document.createElement("div");
        navRow.className = "scn-btnrow";
        var pb = btn(copy.prev || "← Предыдущее заседание", "ghost");
        if (stepIdx === 0) { pb.disabled = true; pb.style.opacity = 0.35; }
        pb.onclick = function () { if (stepIdx > 0) goToStep(stepIdx - 1); };
        navRow.appendChild(pb);
        if (stepIdx < checkpoints.length - 1) {
          var nb = btn(copy.next || "Следующее заседание →");
          nb.onclick = function () { goToStep(stepIdx + 1); };
          navRow.appendChild(nb);
        } else {
          var doneEl = document.createElement("span");
          doneEl.className = "scn-story-text";
          doneEl.textContent = copy.doneText || "";
          navRow.appendChild(doneEl);
        }
        toolRow.appendChild(navRow);

        var resetBtn = document.createElement("button");
        resetBtn.className = "scn-tool-btn";
        resetBtn.textContent = copy.resetView || "⤢ Весь период";
        resetBtn.onclick = function () { chart.timeScale().fitContent(); };
        toolRow.appendChild(resetBtn);
        refs.panelEl.appendChild(toolRow);

        updateBackToEventBtn();
      }

      renderChartOnly();
      chart.timeScale().fitContent();
      renderChrome();
      chart.timeScale().subscribeVisibleTimeRangeChange(function () { updateBackToEventBtn(); });

      // Клавиатура -- только пока сцена реально во вьюпорте, чтобы не
      // перехватывать стрелки во время обычного скролла длинной страницы,
      // и не когда фокус в текстовом поле.
      function inViewport() {
        var r = container.getBoundingClientRect();
        return r.top < window.innerHeight && r.bottom > 0;
      }
      document.addEventListener("keydown", function (e) {
        if (!inViewport()) return;
        var tag = (document.activeElement && document.activeElement.tagName) || "";
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        if (e.key === "ArrowRight" && stepIdx < checkpoints.length - 1) goToStep(stepIdx + 1);
        else if (e.key === "ArrowLeft" && stepIdx > 0) goToStep(stepIdx - 1);
      });

      new ResizeObserver(function () {
        var w = refs.chartEl.clientWidth;
        if (w > 0) chart.resize(w, 240);
      }).observe(refs.chartEl);
    });
  }

  /* ---------------------------------------------------------------- MULTI mode */
  function mountMulti(container, opts) {
    ensureLWC().then(function () {
      var keys = opts.data.meta.symbols || Object.keys(opts.data.series);
      container.innerHTML =
        '<div class="scn-wrap">' +
          '<div class="scn-multi-grid"></div>' +
          '<div class="scn-panel"></div>' +
        '</div>';
      var grid = container.querySelector(".scn-multi-grid");
      var panelEl = container.querySelector(".scn-panel");
      var selected = {};
      var answered = false;
      var charts = [];

      keys.forEach(function (key) {
        var pane = document.createElement("div");
        pane.className = "scn-multi-pane";
        pane.innerHTML = '<div class="scn-multi-label">' + key + '</div><div class="scn-multi-chart"></div>';
        grid.appendChild(pane);
        var chartEl = pane.querySelector(".scn-multi-chart");
        var chart = makeChart(chartEl, 120);
        var lineSeries = chart.addLineSeries(fmtLine("#3a3630"));
        lineSeries.setData(opts.data.series[key].map(function (p) {
          return { time: toUnixTime(p.time), value: p.close };
        }));
        chart.timeScale().fitContent();
        charts.push({ chart: chart, el: chartEl });

        // 🔴 Панель графика — это вариант ответа: её выбирают и потом
        // проверяют. Была обычным <div> с курсором-пальцем: мышью
        // работает, с клавиатуры нет, диктор не назовёт ни роли, ни того,
        // выбран ли актив. Внутри панели живёт canvas-график, поэтому
        // менять тег на <button> рискованно — ставим роль, фокус и
        // обработку Enter/Space, а aria-pressed сообщает выбор.
        pane.setAttribute("role", "button");
        pane.setAttribute("tabindex", "0");
        pane.setAttribute("aria-pressed", "false");
        pane.setAttribute("aria-label", key);
        function переключить() {
          if (answered) return;
          selected[key] = !selected[key];
          pane.classList.toggle("picked", !!selected[key]);
          pane.setAttribute("aria-pressed", selected[key] ? "true" : "false");
        }
        pane.onclick = переключить;
        pane.onkeydown = function (ev) {
          if (ev.key === "Enter" || ev.key === " " || ev.key === "Spacebar") {
            ev.preventDefault();
            переключить();
          }
        };
      });

      function renderPanel() {
        panelEl.innerHTML = "";
        if (!answered) {
          var q = document.createElement("p");
          q.className = "scn-question";
          q.textContent = opts.copy.question || "";
          panelEl.appendChild(q);
          var row = document.createElement("div");
          row.className = "scn-btnrow";
          var checkBtn = btn(opts.copy.checkBtn || "Проверить");
          checkBtn.onclick = function () { answered = true; render(); };
          row.appendChild(checkBtn);
          panelEl.appendChild(row);
        } else {
          var correct = opts.copy.correctKeys || [];
          Array.prototype.forEach.call(grid.children, function (pane, i) {
            var key = keys[i];
            pane.classList.remove("picked");
            pane.classList.add(correct.indexOf(key) >= 0 ? "correct" : (selected[key] ? "wrong" : "neutral"));
          });
          var rev = document.createElement("p");
          rev.className = "scn-reveal";
          rev.textContent = opts.copy.revealNote || "";
          panelEl.appendChild(rev);
          if (opts.copy.conclusion) {
            var conc = document.createElement("div");
            conc.className = "h-note";
            conc.textContent = opts.copy.conclusion;
            panelEl.appendChild(conc);
          }
        }
      }
      function render() { renderPanel(); }
      render();

      new ResizeObserver(function () {
        charts.forEach(function (c) {
          var w = c.el.clientWidth;
          if (w > 0) c.chart.resize(w, 120);
        });
      }).observe(grid);
    });
  }

  function mount(container, opts) {
    if (opts.mode === "event") return mountEvent(container, opts);
    if (opts.mode === "story") return mountStory(container, opts);
    if (opts.mode === "replay") return mountReplay(container, opts);
    if (opts.mode === "multi") return mountMulti(container, opts);
    container.innerHTML = "<p>Unknown scene mode: " + opts.mode + "</p>";
  }

  return { mount: mount };
})();
