/**
 * edu-live.js — мини-виджет живых данных терминала для глав.
 * Инжектируется serve.py; ищет data-edu-live="TICKER" атрибуты.
 * Отображает текущую цену + RSI из /data/ohlc_*_D1.json + /data/quotes.json
 */
(function () {
  'use strict';

  // i18n: window.sbfI18n не кэшируется — проверяем заново при каждом вызове.
  function t(key, fallback) {
    const i = window.sbfI18n;
    return i ? i.t(key, fallback) : (fallback || key);
  }
  function _locale() {
    return (window.sbfI18n && window.sbfI18n.lang === 'ro') ? 'ro-RO' : 'ru-RU';
  }

  const RSI_MAP = {
    '^GSPC': 'ohlc_SPX_D1.json',
    '^NDX': 'ohlc_NASDAQ_D1.json',
    '^VIX':  null,
    'GC=F':  'ohlc_GOLD_D1.json',
    'EURUSD=X': 'ohlc_EURUSD_D1.json',
    'GBPUSD=X': 'ohlc_GBPUSD_D1.json',
    'BTC-USD':  'ohlc_BTC_D1.json',
    'CL=F':     'ohlc_WTI_D1.json',
  };

  const RSI_LABEL = {
    '^GSPC': 'S&P 500', '^NDX': 'Nasdaq 100', '^VIX': 'VIX',
    'GC=F': t('eduindex.live.ticker_gold', 'Золото'), 'EURUSD=X': 'EUR/USD', 'GBPUSD=X': 'GBP/USD',
    'BTC-USD': 'Bitcoin', 'CL=F': t('eduindex.live.ticker_wti', 'Нефть WTI'),
  };

  function rsiZone(v) {
    if (v >= 70) return { label: t('eduindex.live.rsi_overbought', 'перекупленность'), color: '#C0392B' };
    if (v <= 30) return { label: t('eduindex.live.rsi_oversold', 'перепроданность'), color: '#2C784E' };
    return { label: t('eduindex.live.rsi_neutral', 'нейтральная зона'), color: '#716A5A' };
  }

  function createWidget(ticker) {
    const el = document.createElement('div');
    el.style.cssText = [
      'display:inline-flex', 'align-items:center', 'gap:10px',
      'background:rgba(201,162,39,.06)', 'border:1px solid #E7DFCF',
      'border-radius:8px', 'padding:8px 14px', 'margin:12px 0',
      'font-family:"JetBrains Mono",monospace', 'font-size:12px', 'color:#2B2B33',
      'flex-wrap:wrap',
    ].join(';');
    el.innerHTML = '<span style="color:var(--gold-text,#866A19);font-weight:700">⬤ LIVE</span><span style="color:#716A5A">' + t('eduindex.live.loading', 'загрузка…') + '</span>';

    const ohlcFile = RSI_MAP[ticker];
    const label    = RSI_LABEL[ticker] || ticker;

    Promise.all([
      fetch('/data/quotes.json').then(r => r.json()).catch(() => null),
      ohlcFile ? fetch('/data/' + ohlcFile).then(r => r.json()).catch(() => null) : Promise.resolve(null),
    ]).then(([quotes, ohlcData]) => {
      const q = quotes && quotes.quotes && quotes.quotes[ticker];
      const price    = q ? q.price : null;
      const changePct = q ? q.change_pct : null;
      const rsiVal   = ohlcData ? ohlcData.rsi : null;

      let html = '<span style="color:var(--gold-text,#866A19);font-size:9px;letter-spacing:1px">⬤ LIVE</span>';
      html += '<span style="font-weight:700;color:#2B2B33">' + label + '</span>';

      if (price != null) {
        const chg  = changePct != null ? changePct : 0;
        const sign = chg > 0 ? '+' : '';
        const cCol = chg > 0 ? '#2C784E' : chg < 0 ? '#C0392B' : '#716A5A';
        html += '<span>' + price.toLocaleString(_locale(), {maximumFractionDigits: 4}) + '</span>';
        html += '<span style="color:' + cCol + '">' + sign + chg.toFixed(2) + '%</span>';
      }

      if (rsiVal != null) {
        const zone = rsiZone(rsiVal);
        html += '<span style="color:#716A5A">│</span>';
        html += '<span>RSI(14): <b style="color:' + zone.color + '">' + rsiVal.toFixed(1) + '</b></span>';
        html += '<span style="color:' + zone.color + ';font-size:10px">' + zone.label + '</span>';
      }

      el.innerHTML = html;
    }).catch(() => {
      el.innerHTML = '<span style="color:#716A5A;font-size:11px">⬤ ' + t('eduindex.live.data_unavailable', 'данные недоступны') + '</span>';
    });

    return el;
  }

  function init() {
    document.querySelectorAll('[data-edu-live]').forEach(target => {
      const ticker = target.getAttribute('data-edu-live');
      if (!ticker) return;
      const widget = createWidget(ticker);
      target.parentNode.insertBefore(widget, target);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
