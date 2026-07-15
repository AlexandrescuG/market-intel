/**
 * EduChart — учебный движок графиков на Lightweight Charts 4.x
 * Использование:
 *   EduChart.create(element, {fixture, panes, overlays, annotations, interactive})
 *
 * fixture  — имя файла без .json (из /data/edu/)
 * panes    — ['price','rsi','macd']
 * overlays — ['ichimoku']
 * interactive — bool (zoom/pan; default true)
 * height   — высота ценовой панели в px (default 220)
 */
window.EduChart = (function () {
  'use strict';

  // i18n: window.sbfI18n не кэшируется — проверяем заново при каждом вызове.
  function t(key, fallback) {
    const i = window.sbfI18n;
    return i ? i.t(key, fallback) : (fallback || key);
  }

  const PALETTE = {
    bg:     '#FFFFFF',
    grid:   'rgba(43,43,51,0.05)',
    border: '#E7DFCF',
    text:   '#8A8275',
    up:     '#1e8e5a',
    down:   '#c0392b',
    gold:   '#C9A227',
    blue:   '#3b82f6',
    purple: '#8b5cf6',
    cloud_bull: 'rgba(30,142,90,0.12)',
    cloud_bear: 'rgba(192,57,43,0.12)',
  };

  const LWC_CDN = 'https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js';

  let _lwcReady = typeof LightweightCharts !== 'undefined'
    ? Promise.resolve() : null;

  function ensureLWC() {
    if (_lwcReady) return _lwcReady;
    _lwcReady = new Promise((res, rej) => {
      const s = document.createElement('script');
      s.src = LWC_CDN;
      s.onload = res; s.onerror = rej;
      document.head.appendChild(s);
    });
    return _lwcReady;
  }

  function baseChartOpts(h, interactive) {
    return {
      width: 0, height: h,
      layout: { background: { color: PALETTE.bg }, textColor: PALETTE.text },
      grid: {
        vertLines: { color: PALETTE.grid },
        horzLines: { color: PALETTE.grid },
      },
      rightPriceScale: { borderColor: PALETTE.border },
      timeScale: {
        borderColor: PALETTE.border, timeVisible: true, secondsVisible: false,
      },
      crosshair: {
        mode: interactive ? LightweightCharts.CrosshairMode.Normal
                          : LightweightCharts.CrosshairMode.Normal,
      },
      handleScroll: interactive,
      handleScale:  interactive,
    };
  }

  function findByTime(arr, time) {
    if (!arr) return null;
    return arr.find(a => a.time === time);
  }

  async function create(container, opts = {}) {
    opts = Object.assign({ panes: ['price'], overlays: [], interactive: true, height: 220 }, opts);

    await ensureLWC();

    // Fetch fixture
    const res = await fetch(`/data/edu/${opts.fixture}.json`);
    if (!res.ok) { container.innerHTML = `<p style="color:red">Fixture not found: ${opts.fixture}</p>`; return; }
    const fx = await res.json();

    container.innerHTML = '';
    container.style.fontFamily = "'JetBrains Mono',monospace";

    const panes = opts.panes.filter(p => {
      if (p === 'rsi'  && !fx.rsi)   return false;
      if (p === 'macd' && !fx.macd)  return false;
      return true;
    });

    // ── Highlight band helper ──────────────────────────────────────────────
    const highlights = fx.highlights || [];

    // ── PRICE PANE ─────────────────────────────────────────────────────────
    const wrapPrice = document.createElement('div');
    wrapPrice.style.cssText = 'position:relative;margin-bottom:2px';
    container.appendChild(wrapPrice);

    const priceLabel = document.createElement('div');
    priceLabel.style.cssText = 'font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:#8A8275;margin-bottom:4px';
    priceLabel.textContent = (fx.symbol || 'PRICE') + (panes.includes('rsi') ? '' : '  ·  D1');
    container.insertBefore(priceLabel, wrapPrice);

    const priceEl = document.createElement('div');
    priceEl.style.height = opts.height + 'px';
    wrapPrice.appendChild(priceEl);

    const priceChart = LightweightCharts.createChart(priceEl, baseChartOpts(opts.height, opts.interactive));
    priceChart.priceScale('right').applyOptions({ scaleMargins: { top: 0.08, bottom: 0.08 } });

    const candleSeries = priceChart.addCandlestickSeries({
      upColor: PALETTE.up, downColor: PALETTE.down,
      borderUpColor: PALETTE.up, borderDownColor: PALETTE.down,
      wickUpColor: PALETTE.up, wickDownColor: PALETTE.down,
    });
    candleSeries.setData(fx.ohlc.map(b => ({
      time: b.time, open: b.open, high: b.high, low: b.low, close: b.close
    })));

    // Ichimoku overlays
    if (opts.overlays.includes('ichimoku') && fx.ichimoku) {
      const ichi = fx.ichimoku;
      const tenkan = priceChart.addLineSeries({ color: '#e67e22', lineWidth: 1, title: 'Tenkan' });
      const kijun  = priceChart.addLineSeries({ color: '#3b82f6', lineWidth: 1, title: 'Kijun' });
      const sa     = priceChart.addLineSeries({ color: 'transparent', lineWidth: 0, priceLineVisible: false });
      const sb     = priceChart.addLineSeries({ color: 'transparent', lineWidth: 0, priceLineVisible: false });

      const toSeries = (arr, times) => arr
        .map((v, i) => v != null ? { time: times[i], value: v } : null)
        .filter(Boolean);

      const times = fx.ohlc.map(b => b.time);
      tenkan.setData(toSeries(ichi.tenkan, times));
      kijun.setData(toSeries(ichi.kijun,   times));
      sa.setData(toSeries(ichi.senkou_a,   times));
      sb.setData(toSeries(ichi.senkou_b,   times));

      // Cloud fill via area series (senkou A and B)
      const cloudA = priceChart.addAreaSeries({
        topColor: PALETTE.cloud_bull, bottomColor: PALETTE.cloud_bull,
        lineColor: '#1e8e5a', lineWidth: 1, title: 'Senkou A', lastValueVisible: false,
      });
      const cloudB = priceChart.addAreaSeries({
        topColor: PALETTE.cloud_bear, bottomColor: PALETTE.cloud_bear,
        lineColor: '#c0392b', lineWidth: 1, title: 'Senkou B', lastValueVisible: false,
      });
      cloudA.setData(toSeries(ichi.senkou_a, times));
      cloudB.setData(toSeries(ichi.senkou_b, times));
    }

    // Annotations on price pane
    const priceAnnotations = (fx.annotations || []).filter(a => a.pane === 'price');
    priceAnnotations.forEach(ann => {
      const line = priceChart.addLineSeries({
        color: ann.color || PALETTE.gold, lineWidth: 1,
        lineStyle: 2, // dashed
        lastValueVisible: false, priceLineVisible: false,
        title: ann.label || '',
      });
      const bar = fx.ohlc.find(b => b.time === ann.time);
      if (bar) {
        line.setData([{ time: ann.time, value: ann.price || bar.high }]);
      }
    });

    // Highlight vertical bands
    highlights.forEach(h => {
      if (!h.from || !h.to) return;
      // Use a no-data line series trick or just overlay a div
      const band = document.createElement('div');
      band.style.cssText = 'position:absolute;top:0;bottom:0;background:rgba(201,162,39,.08);pointer-events:none;';
      wrapPrice.style.position = 'relative';
      wrapPrice.appendChild(band);
      // Position by time — update on first render
      priceChart.timeScale().subscribeVisibleTimeRangeChange(() => {
        const from = priceChart.timeScale().timeToCoordinate(h.from);
        const to   = priceChart.timeScale().timeToCoordinate(h.to);
        if (from != null && to != null) {
          band.style.left  = Math.min(from, to) + 'px';
          band.style.width = Math.abs(to - from) + 'px';
        }
      });
    });

    // Fit content
    priceChart.timeScale().fitContent();

    // ── RSI PANE ───────────────────────────────────────────────────────────
    if (panes.includes('rsi') && fx.rsi) {
      const rsiLabel = document.createElement('div');
      rsiLabel.style.cssText = 'font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:#8A8275;margin:6px 0 4px';
      rsiLabel.textContent = 'RSI(14)';
      container.appendChild(rsiLabel);

      const rsiEl = document.createElement('div');
      rsiEl.style.height = '100px';
      container.appendChild(rsiEl);

      const rsiChart = LightweightCharts.createChart(rsiEl, Object.assign(
        baseChartOpts(100, opts.interactive),
        { rightPriceScale: { minimum: 0, maximum: 100 } }
      ));
      rsiChart.timeScale().applyOptions({ visible: false });
      rsiChart.priceScale('right').applyOptions({ scaleMargins: { top: 0.05, bottom: 0.05 } });

      // OB/OS bands
      const ob = rsiChart.addLineSeries({ color: 'rgba(192,57,43,.35)', lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false });
      const os = rsiChart.addLineSeries({ color: 'rgba(30,142,90,.35)',  lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false });
      const times = fx.ohlc.map(b => b.time);
      ob.setData(times.map(t => ({ time: t, value: 70 })));
      os.setData(times.map(t => ({ time: t, value: 30 })));

      const rsiSeries = rsiChart.addLineSeries({ color: PALETTE.blue, lineWidth: 2, lastValueVisible: true });
      rsiSeries.setData(
        fx.rsi.map((v, i) => v != null ? { time: fx.ohlc[i].time, value: v } : null).filter(Boolean)
      );

      // RSI annotations (circles via markers)
      const rsiAnnotations = (fx.annotations || []).filter(a => a.pane === 'rsi');
      if (rsiAnnotations.length) {
        rsiSeries.setMarkers(rsiAnnotations.map(a => ({
          time: a.time, position: 'aboveBar', color: a.color || '#c0392b',
          shape: 'circle', text: a.label || '',
        })));
      }

      rsiChart.timeScale().fitContent();

      // Sync timescales
      priceChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (range) rsiChart.timeScale().setVisibleLogicalRange(range);
      });
      rsiChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (range) priceChart.timeScale().setVisibleLogicalRange(range);
      });
    }

    // ── MACD PANE ──────────────────────────────────────────────────────────
    if (panes.includes('macd') && fx.macd) {
      const macdLabel = document.createElement('div');
      macdLabel.style.cssText = 'font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:#8A8275;margin:6px 0 4px';
      macdLabel.textContent = 'MACD(12,26,9)';
      container.appendChild(macdLabel);

      const macdEl = document.createElement('div');
      macdEl.style.height = '100px';
      container.appendChild(macdEl);

      const macdChart = LightweightCharts.createChart(macdEl, baseChartOpts(100, opts.interactive));
      macdChart.timeScale().applyOptions({ visible: true });

      const times = fx.ohlc.map(b => b.time);

      // Histogram
      const histSeries = macdChart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
      histSeries.setData(
        (fx.macd.hist || []).map((v, i) => v != null ? {
          time: times[i], value: v,
          color: v >= 0 ? PALETTE.up : PALETTE.down,
        } : null).filter(Boolean)
      );

      // MACD line
      const macdLine = macdChart.addLineSeries({ color: PALETTE.blue, lineWidth: 1.5, lastValueVisible: true, title: 'MACD' });
      macdLine.setData(
        (fx.macd.line || []).map((v, i) => v != null ? { time: times[i], value: v } : null).filter(Boolean)
      );

      // Signal line
      const sigLine = macdChart.addLineSeries({ color: '#e67e22', lineWidth: 1, lineStyle: 0, lastValueVisible: true, title: 'Signal' });
      sigLine.setData(
        (fx.macd.signal || []).map((v, i) => v != null ? { time: times[i], value: v } : null).filter(Boolean)
      );

      macdChart.timeScale().fitContent();

      // Sync
      priceChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (range) macdChart.timeScale().setVisibleLogicalRange(range);
      });
      macdChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (range) priceChart.timeScale().setVisibleLogicalRange(range);
      });
    }

    // ── Legend ─────────────────────────────────────────────────────────────
    const leg = document.createElement('div');
    leg.style.cssText = 'display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;font-size:10px;color:#8A8275;font-family:"JetBrains Mono",monospace';
    const legendItems = [
      { color: PALETTE.up,   label: t('eduindex.chart.legend_bull_candle', 'Бычья свеча') },
      { color: PALETTE.down, label: t('eduindex.chart.legend_bear_candle', 'Медвежья свеча') },
    ];
    if (panes.includes('rsi'))  legendItems.push({ color: PALETTE.blue,  label: 'RSI(14)' });
    if (panes.includes('macd')) legendItems.push({ color: PALETTE.blue,  label: 'MACD' }, { color: '#e67e22', label: 'Signal' });
    if (opts.overlays.includes('ichimoku')) {
      legendItems.push(
        { color: '#e67e22', label: 'Tenkan-sen' },
        { color: PALETTE.blue,  label: 'Kijun-sen' },
        { color: PALETTE.up,    label: t('eduindex.chart.legend_cloud_bull', 'Облако (бычье)') },
        { color: PALETTE.down,  label: t('eduindex.chart.legend_cloud_bear', 'Облако (медвежье)') }
      );
    }
    legendItems.forEach(item => {
      const el = document.createElement('div');
      el.style.cssText = 'display:flex;align-items:center;gap:5px';
      el.innerHTML = `<span style="display:inline-block;width:14px;height:3px;background:${item.color};border-radius:2px"></span>${item.label}`;
      leg.appendChild(el);
    });
    container.appendChild(leg);

    // Resize observer
    const ro = new ResizeObserver(() => {
      const w = container.clientWidth;
      if (w > 0) {
        priceChart.resize(w, opts.height);
      }
    });
    ro.observe(container);

    return { priceChart };
  }

  return { create };
})();
