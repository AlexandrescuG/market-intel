/* Реестр понятий SBF Academy. Ключи cheatsheet совпадают с seed БД. */
/* i18n: window.sbfI18n не кэшируется, проверяем заново при каждом вызове. */
function t(key, fallback) {
  var i = window.sbfI18n;
  return i ? i.t(key, fallback) : (fallback || key);
}

var CONCEPT_MAP = [
  {id:"risk_rr",    label:"Risk/Reward",                                                  chapter:3,  cheatsheet:"risk_rr",            widget:"risk-calc"},
  {id:"position",   label:t('eduindex.concept.position.label','Размер позиции'),          chapter:3,  cheatsheet:"risk_position_size", widget:"risk-calc"},
  {id:"drawdown",   label:t('eduindex.concept.drawdown.label','Просадка'),                chapter:3,  cheatsheet:"risk_drawdown",      widget:"risk-calc"},
  {id:"sessions",   label:t('eduindex.concept.sessions.label','Сессии рынка'),            chapter:5,  cheatsheet:null,                 widget:"session-clock"},
  {id:"cpi",        label:"CPI",                                                           chapter:6,  cheatsheet:"event_cpi"},
  {id:"nfp",        label:"NFP",                                                           chapter:6,  cheatsheet:"event_nfp"},
  {id:"fomc",       label:"FOMC",                                                          chapter:6,  cheatsheet:"event_fomc"},
  {id:"pce",        label:"PCE",                                                           chapter:6,  cheatsheet:"event_pce"},
  {id:"rsi",        label:"RSI",                                                           chapter:9,  cheatsheet:"ind_rsi",          grafik:{cat:"ind",   key:"rsi"}},
  {id:"macd",       label:"MACD",                                                          chapter:9,  cheatsheet:"ind_macd",         grafik:{cat:"ind",   key:"macd"}},
  {id:"divergence", label:t('eduindex.concept.divergence.label','Дивергенция'),            chapter:9,  cheatsheet:"ind_macd",         grafik:{cat:"ind",   key:"macd"}},
  {id:"patterns",   label:t('eduindex.concept.patterns.label','Графические паттерны'),     chapter:10, cheatsheet:null,               grafik:{cat:"chart", key:"ascTri"}, widget:"pattern-gallery"},
  {id:"double_top", label:t('eduindex.concept.double_top.label','Двойная вершина'),        chapter:10, cheatsheet:"chart_double_top", grafik:{cat:"chart", key:"dtop"}},
  {id:"wedge",      label:t('eduindex.concept.wedge.label','Клин'),                        chapter:10, cheatsheet:"chart_wedge",      grafik:{cat:"chart", key:"wedge"}},
  {id:"flag",       label:t('eduindex.concept.flag.label','Флаг'),                         chapter:10, cheatsheet:"chart_flag",       grafik:{cat:"chart", key:"flag"}}
];

/* Быстрый поиск: concept_id → запись */
var CM_BY_ID = {};
CONCEPT_MAP.forEach(function(c){ CM_BY_ID[c.id] = c; });

/* Быстрый поиск: cheatsheet_id → chapter */
var CM_BY_CHEAT = {};
CONCEPT_MAP.forEach(function(c){ if(c.cheatsheet) CM_BY_CHEAT[c.cheatsheet] = c; });

/* Ключевые слова → concept_id (для автотеггера в брифинге) */
var CM_KEYWORDS = {
  "PCE":"pce","CPI":"cpi","NFP":"nfp","FOMC":"fomc","ФРС":"fomc",
  "RSI":"rsi","MACD":"macd","дивергенция":"divergence","Дивергенция":"divergence",
  "двойная вершина":"double_top","Двойная вершина":"double_top",
  "клин":"wedge","Клин":"wedge","флаг":"flag","Флаг":"flag"
};
