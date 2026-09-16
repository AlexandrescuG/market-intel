/* SBF Academy — виджеты для edu-глав. Vanilla JS, без React. */
(function(G){
'use strict';

/* i18n: window.sbfI18n не кэшируется — проверяем заново при каждом вызове,
   т.к. эти виджеты монтируются в разное время относительно defer-скриптов. */
function t(key, fallback) {
  var i = window.sbfI18n;
  return i ? i.t(key, fallback) : (fallback || key);
}
function _locale() {
  return (window.sbfI18n && window.sbfI18n.lang === 'ro') ? 'ro-RO' : 'ru-RU';
}

/* Цвета в raw hex (CSS vars не работают в SVG-атрибутах).
   16.09.2026: затемнены до порога AA — тем же цветом рисуется и линия,
   и подпись к ней, см. разбор в edu/assets/grafik-engine.js. */
var C={
  up:'#287A62',down:'#BC4643',gold:'#866A19',
  surf:'#FCFAF5',border:'#E7DFCF',ink:'#2B2B33',muted:'#716A5A'
};

/* ── Seeded RNG ────────────────────────────────────────────────────────────── */
function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;var t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}

/* ── Price builders ────────────────────────────────────────────────────────── */
function walk(n,start,drift,vol,r){var px=start,cs=[];for(var i=0;i<n;i++){px+=drift+(r()*2-1)*vol;cs.push(px);}return cs;}
function toCandles(closes,vol,r,startOpen){var cs=[],prev=startOpen!=null?startOpen:closes[0];for(var i=0;i<closes.length;i++){var o=prev,c=closes[i],hi=Math.max(o,c)+Math.abs(r()*vol*0.9),lo=Math.min(o,c)-Math.abs(r()*vol*0.9);cs.push({o:o,h:hi,l:lo,c:c});prev=c;}return cs;}
function noisyPath(piv,perSeg,vol,r){var cs=[];for(var s=0;s<piv.length-1;s++){var a=piv[s],b=piv[s+1];for(var k=0;k<perSeg;k++){var t=k/perSeg;cs.push(a+(b-a)*t+(r()*2-1)*vol);}}cs.push(piv[piv.length-1]);return cs;}

/* ── Candle patterns ───────────────────────────────────────────────────────── */
var PAT={
  bullEngulf: function(p,u){return[{o:p,c:p-0.8*u,h:p+0.25*u,l:p-1.0*u},{o:p-1.2*u,c:p+0.7*u,h:p+0.9*u,l:p-1.35*u}];},
  bearEngulf: function(p,u){return[{o:p,c:p+0.8*u,h:p+1.0*u,l:p-0.25*u},{o:p+1.2*u,c:p-0.7*u,h:p+1.35*u,l:p-0.9*u}];},
  hammer:     function(p,u){return[{o:p,c:p+0.35*u,h:p+0.55*u,l:p-1.9*u}];},
  doji:       function(p,u){return[{o:p,c:p+0.05*u,h:p+1.0*u,l:p-1.0*u}];},
  morningStar:function(p,u){return[{o:p,c:p-2.0*u,h:p+0.2*u,l:p-2.2*u},{o:p-2.45*u,c:p-2.2*u,h:p-2.0*u,l:p-2.6*u},{o:p-2.2*u,c:p-0.4*u,h:p-0.2*u,l:p-2.35*u}];},
  eveningStar:function(p,u){return[{o:p,c:p+2.0*u,h:p+2.2*u,l:p-0.2*u},{o:p+2.45*u,c:p+2.2*u,h:p+2.6*u,l:p+2.0*u},{o:p+2.2*u,c:p+0.4*u,h:p+2.35*u,l:p+0.2*u}];},
  harami:     function(p,u){return[{o:p,c:p-2.0*u,h:p+0.2*u,l:p-2.2*u},{o:p-1.5*u,c:p-0.8*u,h:p-0.6*u,l:p-1.65*u}];}
};

function buildReversal(dir,patFn,seed){
  var r=mulberry32(seed),vol=0.62,u=1.3;
  var ctx=walk(13,dir==='bull'?62:46,dir==='bull'?-0.55:0.55,vol,r);
  var p0=ctx[ctx.length-1],pat=patFn(p0,u);pat[0].o=p0;
  var fol=walk(5,pat[pat.length-1].c,dir==='bull'?0.6:-0.6,vol,r);
  var cCtx=toCandles(ctx,vol,r),cFol=toCandles(fol,vol,r,pat[pat.length-1].c);
  return{candles:cCtx.concat(pat,cFol),zone:[cCtx.length,cCtx.length+pat.length-1],trend:dir==='bull'?t('eduindex.widgets.trend_down','тренд ↓'):t('eduindex.widgets.trend_up','тренд ↑')};
}
function buildChart(piv,perSeg,seed,annos){var r=mulberry32(seed),vol=0.7;return{candles:toCandles(noisyPath(piv,perSeg,vol,r),vol,r),annos:annos||[]};}

function buildSVG(candles,annos,opts){
  opts=opts||{};var W=opts.w||300,H=opts.h||172,px=16,pt=20,pb=14;
  var lo=Infinity,hi=-Infinity,i;
  for(i=0;i<candles.length;i++){lo=Math.min(lo,candles[i].l);hi=Math.max(hi,candles[i].h);}
  (annos||[]).forEach(function(a){if(a.y!=null){lo=Math.min(lo,a.y);hi=Math.max(hi,a.y);}if(a.from){lo=Math.min(lo,a.from.y,a.to.y);hi=Math.max(hi,a.from.y,a.to.y);}});
  var sp=(hi-lo)*0.08||1;lo-=sp;hi+=sp;
  var n=candles.length,pw=W-px*2,ph=H-pt-pb;
  var X=function(idx){return px+(n<=1?pw/2:(idx/(n-1))*pw);};
  var Y=function(v){return pt+(hi-v)/(hi-lo)*ph;};
  var cw=Math.max(2.5,Math.min((pw/n)*0.62,9));
  var s='<svg viewBox="0 0 '+W+' '+H+'" xmlns="http://www.w3.org/2000/svg"><rect width="'+W+'" height="'+H+'" rx="8" fill="'+C.surf+'" stroke="'+C.border+'"/>';
  if(opts.zone){var x0=X(opts.zone[0])-cw/2-3,x1=X(opts.zone[1])+cw/2+3;
    s+='<rect x="'+x0.toFixed(1)+'" y="'+(pt-4)+'" width="'+(x1-x0).toFixed(1)+'" height="'+(ph+8)+'" fill="'+C.gold+'" opacity="0.10" rx="3"/>'
     +'<line x1="'+x0.toFixed(1)+'" y1="'+(pt-4)+'" x2="'+x0.toFixed(1)+'" y2="'+(pt+ph+4).toFixed(1)+'" stroke="'+C.gold+'" stroke-width="1" stroke-dasharray="3 3" opacity="0.5"/>'
     +'<line x1="'+x1.toFixed(1)+'" y1="'+(pt-4)+'" x2="'+x1.toFixed(1)+'" y2="'+(pt+ph+4).toFixed(1)+'" stroke="'+C.gold+'" stroke-width="1" stroke-dasharray="3 3" opacity="0.5"/>';}
  (annos||[]).forEach(function(a){
    if(a.type==='hline'){var yy=Y(a.y).toFixed(1);s+='<line x1="'+px+'" y1="'+yy+'" x2="'+(W-px)+'" y2="'+yy+'" stroke="'+C.gold+'" stroke-width="1.2" stroke-dasharray="4 3" opacity="0.7"/>';if(a.label)s+='<text x="'+(px+2)+'" y="'+(Y(a.y)-3).toFixed(1)+'" font-family="Montserrat,sans-serif" font-size="11" font-weight="700" fill="'+C.gold+'">'+a.label+'</text>';}
    if(a.type==='line'){s+='<line x1="'+X(a.from.i).toFixed(1)+'" y1="'+Y(a.from.y).toFixed(1)+'" x2="'+X(a.to.i).toFixed(1)+'" y2="'+Y(a.to.y).toFixed(1)+'" stroke="'+C.gold+'" stroke-width="1.2" stroke-dasharray="4 3" opacity="0.7"/>';}
  });
  if(opts.trend){s+='<text x="'+px+'" y="13" font-family="Montserrat,sans-serif" font-size="9.5" font-weight="600" fill="'+C.muted+'">'+opts.trend+'</text>';}
  for(i=0;i<candles.length;i++){var ca=candles[i],xx=X(i),bull=ca.c>=ca.o,col=bull?C.up:C.down;
    s+='<line x1="'+xx.toFixed(1)+'" y1="'+Y(ca.h).toFixed(1)+'" x2="'+xx.toFixed(1)+'" y2="'+Y(ca.l).toFixed(1)+'" stroke="'+col+'" stroke-width="1.1"/>';
    var yo=Y(ca.o),yc=Y(ca.c),top=Math.min(yo,yc),bh=Math.abs(yc-yo);if(bh<1.6)bh=1.6;
    s+='<rect x="'+(xx-cw/2).toFixed(1)+'" y="'+top.toFixed(1)+'" width="'+cw.toFixed(1)+'" height="'+bh.toFixed(1)+'" rx="0.8" fill="'+col+'"/>';}
  return s+'</svg>';
}

var candleDefs=[
  ['bullEngulf','bull',t('eduindex.widgets.candle.bullEngulf.name','Бычье поглощение'),t('eduindex.widgets.candle.bullEngulf.desc','Бычья свеча полностью охватывает предыдущую медвежью — после снижения.'),7],
  ['bearEngulf','bear',t('eduindex.widgets.candle.bearEngulf.name','Медвежье поглощение'),t('eduindex.widgets.candle.bearEngulf.desc','Медвежья свеча полностью охватывает предыдущую бычью — после роста.'),13],
  ['hammer','bull',t('eduindex.widgets.candle.hammer.name','Молот (Hammer)'),t('eduindex.widgets.candle.hammer.desc','Малое тело и длинная нижняя тень после снижения.'),21],
  ['doji','bull',t('eduindex.widgets.candle.doji.name','Доджи'),t('eduindex.widgets.candle.doji.desc','Открытие и закрытие почти совпадают — нерешительность рынка.'),4],
  ['morningStar','bull',t('eduindex.widgets.candle.morningStar.name','Утренняя звезда'),t('eduindex.widgets.candle.morningStar.desc','Большая медвежья → маленькая звезда → большая бычья. Разворот вверх.'),31],
  ['eveningStar','bear',t('eduindex.widgets.candle.eveningStar.name','Вечерняя звезда'),t('eduindex.widgets.candle.eveningStar.desc','Большая бычья → маленькая звезда → большая медвежья. Разворот вниз.'),5],
  ['harami','bull',t('eduindex.widgets.candle.harami.name','Харами (Harami)'),t('eduindex.widgets.candle.harami.desc','Малая свеча внутри тела предыдущей большой — затухание импульса.'),9]
];
var chartDefs=[
  [t('eduindex.widgets.chart.triangleAsc.name','Восходящий треугольник'),t('eduindex.widgets.chart.triangleAsc.desc','Горизонтальное сопротивление, восходящая поддержка.'),[50,61,54,61,57,61,59,61.5,64],3,55,[{type:'hline',y:61,label:t('eduindex.widgets.lbl_resistance','сопр.')},{type:'line',from:{i:0,y:50},to:{i:18,y:59}}],'triangleAsc'],
  [t('eduindex.widgets.chart.triangleDesc.name','Нисходящий треугольник'),t('eduindex.widgets.chart.triangleDesc.desc','Горизонтальная поддержка, нисходящее сопротивление.'),[60,50,57,50,54,50,52,50,47],3,12,[{type:'hline',y:50,label:t('eduindex.widgets.lbl_support','подд.')},{type:'line',from:{i:0,y:60},to:{i:18,y:52}}],'triangleDesc'],
  [t('eduindex.widgets.chart.pennant.name','Вымпел'),t('eduindex.widgets.chart.pennant.desc','Импульс (флагшток), затем сжатие в сходящемся треугольнике.'),[48,50,52,63,60,62,60.5,61.5,65],3,3,[{type:'line',from:{i:9,y:63},to:{i:24,y:61.7}},{type:'line',from:{i:11,y:59.6},to:{i:24,y:61.1}}],'pennant'],
  [t('eduindex.widgets.chart.hns.name','Голова и плечи'),t('eduindex.widgets.chart.hns.desc','Три пика, средний выше — разворот тренда.'),[48,57,51,63,51,57,49],3,8,[{type:'hline',y:51,label:t('eduindex.widgets.lbl_neckline','линия шеи')}],'hns'],
  [t('eduindex.widgets.chart.doubleTop.name','Двойная вершина'),t('eduindex.widgets.chart.doubleTop.desc','Два пика на одном уровне — фигура «M».'),[48,60,53,59.5,49],4,21,[{type:'hline',y:53,label:t('eduindex.widgets.lbl_neckline','линия шеи')}],'doubleTop'],
  [t('eduindex.widgets.chart.doubleBottom.name','Двойное дно'),t('eduindex.widgets.chart.doubleBottom.desc','Два минимума на одном уровне — фигура «W».'),[60,50,57,50,62],4,2,[{type:'hline',y:57,label:t('eduindex.widgets.lbl_neckline','линия шеи')}],'doubleBottom'],
  [t('eduindex.widgets.chart.wedge.name','Клин (Wedge)'),t('eduindex.widgets.chart.wedge.desc','Сходящиеся наклонные линии — ослабление тренда.'),[50,55,52.5,57,54.5,58.5,56.5,59,54],3,14,[{type:'line',from:{i:3,y:55},to:{i:21,y:59}},{type:'line',from:{i:0,y:50},to:{i:18,y:56.5}}],'wedge'],
  [t('eduindex.widgets.chart.flag.name','Флаг'),t('eduindex.widgets.chart.flag.desc','Импульс, затем наклонный канал против движения.'),[48,50,62,60,61,59.5,60.5,58.5,64],3,6,[{type:'line',from:{i:6,y:62},to:{i:21,y:59}},{type:'line',from:{i:8,y:59.5},to:{i:21,y:57}}],'flag']
];

/* ── Pattern gallery ─────────────────────────────────────────────────────────
   🔴 ДВЕ ПРАВКИ ЧЕСТНОСТИ. Первая: галерея была единственным из
   инжектируемых блоков БЕЗ метки «СХЕМА · ИЛЛЮСТРАЦИЯ» — пятнадцать форм
   рисуются генератором со случайным зерном, а заголовок «Паттерны рынка»
   ничем не отличал их от наблюдений.

   Вторая, и она важнее. По шести из этих паттернов у нас есть настоящие
   измерения: pattern_stats_job считает их еженедельно по 80+ инструментам,
   суммарно 117 тысяч наблюдений на эти шесть. И измерения говорят ровно
   то, ради чего написана глава: доля случаев, когда цена через пять баров
   пошла в обещанную сторону, лежит между 0.481 и 0.518. Монетка.
   Показывать красивую форму и молчать о том, что мы её уже проверили, —
   значит оставлять читателя при впечатлении, которое сами же опровергли. */
var GALLERY_STATS = null;     // наши измерения по паттерну
var GALLERY_EXAMPLES = null;  // настоящие вхождения в истории

function _грузи(путь, дальше){
  try {
    var q = new XMLHttpRequest();
    q.open('GET', путь, true);
    q.onload = function(){
      if (q.status !== 200) { дальше(null); return; }
      try { дальше(JSON.parse(q.responseText)); } catch (e) { дальше(null); }
    };
    q.onerror = function(){ дальше(null); };
    q.send();
  } catch (e) { дальше(null); }
}

/* Оба файла приходят асинхронно, а карточки уже нарисованы схемами.
   Поэтому после каждой загрузки карточки переcобираются заново — так они
   не зависят от того, какой ответ пришёл первым. */
function обновитьКарточки(){
  document.querySelectorAll('[data-sbf-pat]').forEach(function(узел){
    var ключ = узел.getAttribute('data-sbf-pat');
    if (!ключ) return;
    var пример = GALLERY_EXAMPLES && GALLERY_EXAMPLES['примеры'] && GALLERY_EXAMPLES['примеры'][ключ];
    var было = узел.querySelector('.sbf-pat-stat');
    if (было) было.remove();
    var подпись = узел.querySelector('.sbf-pat-real');
    if (подпись) подпись.remove();
    if (пример){
      var svg = узел.querySelector('svg');
      if (svg) svg.outerHTML = реальныйГрафик(пример);
      var метка = узел.querySelector('.sbf-pat-tag');
      if (метка) метка.remove();   // это уже не схема
      узел.setAttribute('data-sbf-real', '1');
      узел.insertAdjacentHTML('beforeend', подписьПримера(пример));
    }
    узел.insertAdjacentHTML('beforeend', статистикаПаттерна(ключ));
  });
}

function реальныйГрафик(пример){
  var i = пример['индекс_паттерна'];
  return buildSVG(пример['бары'], [], {zone:[i, i]});
}

function подписьПримера(пример){
  var д = new Date(пример['ts'] * 1000);
  var дата = ('0'+д.getUTCDate()).slice(-2)+'.'+('0'+(д.getUTCMonth()+1)).slice(-2)+'.'+д.getUTCFullYear();
  var итог = пример['итог_процентов'];
  var знак = итог >= 0 ? '+' : '';
  // Цвет по тому, оправдался ли паттерн, а не по знаку движения: у
  // медвежьего паттерна рост — это промах, и он обязан читаться как промах.
  var напр = пример['направление'];
  var верно = напр === 'bullish' ? итог > 0 : напр === 'bearish' ? итог < 0 : null;
  var цвет = верно === null ? 'sbf-pat-neutral' : (верно ? 'sbf-pat-hit' : 'sbf-pat-miss');
  return '<div class="sbf-pat-real">' + пример['имя'] + ' · ' + пример['tf'] + ' · ' + дата +
    '<span class="' + цвет + '"> → через ' + (пример['бары'].length - 1 - i_пример(пример)) +
    ' баров ' + знак + итог + '%</span></div>';
}

function i_пример(пример){ return пример['индекс_паттерна']; }

function статистикаПаттерна(ключ){
  if (!GALLERY_STATS || !GALLERY_STATS['паттерны']) return '';
  var з = GALLERY_STATS['паттерны'][ключ];
  if (!з) return '';
  var доля = Math.round(з['доля_5'] * 1000) / 10;
  var набл = з['наблюдений'].toLocaleString('ru-RU');
  return '<div class="sbf-pat-stat">' +
         t('eduindex.widgets.pat_stat_prefix', 'наша проверка:') + ' ' +
         доля.toFixed(1) + '% · ' + набл + ' ' +
         t('eduindex.widgets.pat_stat_obs', 'наблюдений') + '</div>';
}

_грузи('/data/edu_capsules/pattern_gallery_stats.json', function(j){
  GALLERY_STATS = j; обновитьКарточки();
});
_грузи('/data/edu_capsules/pattern_examples.json', function(j){
  GALLERY_EXAMPLES = j; обновитьКарточки();
});

function mountPatternGallery(el, opts) {
  var filter=(opts&&opts.filter)||'all';
  var html='';
  if(filter==='all'||filter==='candle') html+='<div class="sbf-sect-label">'+t('eduindex.widgets.section_candle','Свечные паттерны')+' <span class="sbf-sect-n">7</span></div><div class="sbf-card-grid" id="sbfw-cg"></div>';
  if(filter==='all'||filter==='chart')  html+='<div class="sbf-sect-label">'+t('eduindex.widgets.section_chart','Графические паттерны')+' <span class="sbf-sect-n">8</span></div><div class="sbf-card-grid" id="sbfw-hg"></div>';
  el.innerHTML='<div class="sbf-widget">'+
    '<div class="sbf-widget-head">'+t('eduindex.widgets.gallery_head','Паттерны рынка')+'</div>'+html+'</div>';
  function card(name,desc,svg,ключ){
    // Пока не пришёл файл с примерами, честно считаем карточку схемой:
    // она ею и является. Метку снимет обновитьКарточки(), когда окажется,
    // что под этот паттерн есть настоящее вхождение.
    return'<div class="sbf-pat-card" data-sbf-pat="'+(ключ||'')+'">'+
      '<div class="sbf-pat-tag">'+t('eduindex.widgets.pat_tag_schema','схема')+'</div>'+
      svg+'<div class="sbf-pat-name">'+name+'</div><div class="sbf-pat-desc">'+desc+'</div>'+
      статистикаПаттерна(ключ)+'</div>';}
  var cg=el.querySelector('#sbfw-cg');
  if(cg) candleDefs.forEach(function(p){var d=buildReversal(p[1],PAT[p[0]],p[4]);cg.innerHTML+=card(p[2],p[3],buildSVG(d.candles,[],{zone:d.zone,trend:d.trend}),p[0]);});
  var hg=el.querySelector('#sbfw-hg');
  if(hg) chartDefs.forEach(function(p){var d=buildChart(p[2],p[3],p[4],p[5]);hg.innerHTML+=card(p[0],p[1],buildSVG(d.candles,p[5],{}),p[6]);});
  var виджет=el.querySelector('.sbf-widget');
  if(виджет) виджет.insertAdjacentHTML('beforeend',
    '<div class="sbf-pat-foot">'+t('eduindex.widgets.pat_foot',
     'Каждый пример — одно настоящее вхождение из тысяч, выбранное как типичное по размаху, '+
     'а не как удачное: что случилось после, не отбиралось. Один случай ничего не доказывает — '+
     'смотри строку «наша проверка»: там доля по всем вхождениям сразу.')+'</div>');
}

/* ── Risk calculator ───────────────────────────────────────────────────────── */
function mountRiskCalc(el) {
  el.innerHTML=
    '<div class="sbf-widget">'+
    '<div class="sbf-widget-head">'+t('eduindex.widgets.risk.head','Риск-калькулятор')+'</div>'+
    '<div class="sbf-calc-grid">'+
    /* Panel 1 */
    '<div class="sbf-panel">'+
      '<div class="sbf-panel-title">'+t('eduindex.widgets.risk.panel1_title','Позиция и риск')+'</div>'+
      '<div class="sbf-panel-sub">'+t('eduindex.widgets.risk.panel1_sub','Размер сделки от принятого риска')+'</div>'+
      '<div class="sbf-field"><label for="sbfw-cap">'+t('eduindex.widgets.risk.label_capital','Капитал ($)')+'</label><input id="sbfw-cap" type="number" value="10000" step="100"></div>'+
      '<div class="sbf-field"><label for="sbfw-rsk">'+t('eduindex.widgets.risk.label_risk_pct','Риск на сделку (%)')+'</label><input id="sbfw-rsk" type="number" value="1" step="0.1"></div>'+
      '<div class="sbf-row2">'+
        '<div class="sbf-field"><label for="sbfw-entry">'+t('eduindex.widgets.risk.label_entry','Вход')+'</label><input id="sbfw-entry" type="number" value="100" step="0.01"></div>'+
        '<div class="sbf-field"><label for="sbfw-stop">'+t('eduindex.widgets.risk.label_stop','Стоп-лосс')+'</label><input id="sbfw-stop" type="number" value="96" step="0.01"></div>'+
      '</div>'+
      '<div class="sbf-field"><label for="sbfw-target">'+t('eduindex.widgets.risk.label_target','Тейк-профит')+'</label><input id="sbfw-target" type="number" value="112" step="0.01"></div>'+
      '<div class="sbf-out" id="sbfw-posOut"></div>'+
    '</div>'+
    /* Panel 2 */
    '<div class="sbf-panel">'+
      '<div class="sbf-panel-title">'+t('eduindex.widgets.risk.panel2_title','Ожидание системы')+'</div>'+
      '<div class="sbf-panel-sub">'+t('eduindex.widgets.risk.panel2_sub','Средний результат на сделку, в R')+'</div>'+
      '<div class="sbf-field"><label for="sbfw-wr">'+t('eduindex.widgets.risk.label_winrate','Винрейт (%)')+'</label><input id="sbfw-wr" type="number" value="45" step="1"></div>'+
      '<div class="sbf-row2">'+
        '<div class="sbf-field"><label for="sbfw-aw">'+t('eduindex.widgets.risk.label_avg_win','Сред. выигрыш (R)')+'</label><input id="sbfw-aw" type="number" value="2" step="0.1"></div>'+
        '<div class="sbf-field"><label for="sbfw-al">'+t('eduindex.widgets.risk.label_avg_loss','Сред. проигрыш (R)')+'</label><input id="sbfw-al" type="number" value="1" step="0.1"></div>'+
      '</div>'+
      '<div class="sbf-out" id="sbfw-expOut"></div>'+
      '<div class="sbf-verdict" id="sbfw-verdict"></div>'+
    '</div>'+
    /* Panel 3 */
    '<div class="sbf-panel">'+
      '<div class="sbf-panel-title">'+t('eduindex.widgets.risk.panel3_title','Просадка')+'</div>'+
      '<div class="sbf-panel-sub">'+t('eduindex.widgets.risk.panel3_sub','Снижение капитала и возврат')+'</div>'+
      '<div class="sbf-seg">'+
        '<button id="sbfw-ddA" class="sbf-seg-btn active" type="button">'+t('eduindex.widgets.risk.seg_current','Текущая')+'</button>'+
        '<button id="sbfw-ddB" class="sbf-seg-btn" type="button">'+t('eduindex.widgets.risk.seg_streak','Серия убытков')+'</button>'+
      '</div>'+
      '<div id="sbfw-panA"><div class="sbf-row2">'+
        '<div class="sbf-field"><label for="sbfw-peak">'+t('eduindex.widgets.risk.label_peak','Пик капитала')+'</label><input id="sbfw-peak" type="number" value="12000" step="100"></div>'+
        '<div class="sbf-field"><label for="sbfw-cur">'+t('eduindex.widgets.risk.label_current','Текущий')+'</label><input id="sbfw-cur" type="number" value="9600" step="100"></div>'+
      '</div></div>'+
      '<div id="sbfw-panB" style="display:none"><div class="sbf-row2">'+
        '<div class="sbf-field"><label for="sbfw-ddR">'+t('eduindex.widgets.risk.label_risk_per_trade','Риск/сделку (%)')+'</label><input id="sbfw-ddR" type="number" value="2" step="0.1"></div>'+
        '<div class="sbf-field"><label for="sbfw-ddN">'+t('eduindex.widgets.risk.label_losses_streak','Убытков подряд')+'</label><input id="sbfw-ddN" type="number" value="8" step="1"></div>'+
      '</div></div>'+
      '<div class="sbf-out" id="sbfw-ddOut"></div>'+
    '</div>'+
    '</div></div>';

  var $=function(id){return el.querySelector('#'+id);};
  function money(x){return(x<0?'-$':'$')+Math.abs(x).toLocaleString(_locale(),{maximumFractionDigits:2});}
  function num(x,d){return Number(x).toLocaleString(_locale(),{maximumFractionDigits:d==null?2:d});}
  function row(k,v,cls){return'<div class="sbf-o-row"><span class="sbf-o-k">'+k+'</span><span class="sbf-o-v '+(cls||'')+'">'+v+'</span></div>';}

  function calcPos(){
    var cap=+$('sbfw-cap').value,rsk=+$('sbfw-rsk').value,
        entry=+$('sbfw-entry').value,stop=+$('sbfw-stop').value,target=+$('sbfw-target').value;
    var rAmt=cap*rsk/100,perU=Math.abs(entry-stop),size=perU>0?rAmt/perU:0;
    var h=row(t('eduindex.widgets.risk.row_risk_amount','Риск на сделку'),money(rAmt),'gold')+row(t('eduindex.widgets.risk.row_position_size','Размер позиции'),num(size,2)+' '+t('eduindex.widgets.risk.unit','ед.'))+row(t('eduindex.widgets.risk.row_position_cost','Стоимость позиции'),money(size*entry));
    if(target&&perU>0){var rr=Math.abs(target-entry)/perU,profit=size*Math.abs(target-entry);
      h+=row(t('eduindex.widgets.risk.row_r_multiple','R-мультипликатор'),'1 : '+num(rr,2),rr>=1?'pos':'neg')+row(t('eduindex.widgets.risk.row_potential_profit','Потенц. прибыль'),money(profit),'pos');}
    $('sbfw-posOut').innerHTML=h;
  }
  function calcExp(){
    var wr=+$('sbfw-wr').value/100,aw=+$('sbfw-aw').value,al=+$('sbfw-al').value,e=wr*aw-(1-wr)*al;
    $('sbfw-expOut').innerHTML=row(t('eduindex.widgets.risk.row_expectancy','Ожидание'),num(e,2)+' '+t('eduindex.widgets.risk.per_trade_suffix','R / сделку'),e>0?'pos':'neg')+row(t('eduindex.widgets.risk.row_per_100','На 100 сделок'),num(e*100,1)+' R',e>0?'pos':'neg');
    var v=$('sbfw-verdict');
    if(e>0){v.style.color='var(--up)';v.textContent=t('eduindex.widgets.risk.verdict_positive','Положительное ожидание: система в плюсе на дистанции при дисциплине.');}
    else if(e===0){v.style.color='var(--muted)';v.textContent=t('eduindex.widgets.risk.verdict_zero','Нулевое ожидание: система в ноль до издержек.');}
    else{v.style.color='var(--down)';v.textContent=t('eduindex.widgets.risk.verdict_negative','Отрицательное ожидание: на дистанции теряет. Пересмотри R или винрейт.');}
  }
  var ddMode='A';
  function calcDD(){
    if(ddMode==='A'){var peak=+$('sbfw-peak').value,cur=+$('sbfw-cur').value,dd=peak>0?(peak-cur)/peak*100:0,rec=cur>0?(peak/cur-1)*100:0;
      $('sbfw-ddOut').innerHTML=row(t('eduindex.widgets.risk.row_dd_from_peak','Просадка от пика'),num(dd,1)+'%',dd>0?'neg':'')+row(t('eduindex.widgets.risk.row_recovery_needed','Нужно для возврата'),'+'+num(rec,1)+'%','gold');}
    else{var r=+$('sbfw-ddR').value/100,n=+$('sbfw-ddN').value,rem=Math.pow(1-r,n),ddp=(1-rem)*100,rec2=rem>0?(1/rem-1)*100:0;
      $('sbfw-ddOut').innerHTML=row(t('eduindex.widgets.risk.row_capital_left','Осталось капитала'),num(rem*100,1)+'%','neg')+row(t('eduindex.widgets.risk.row_dd_size','Размер просадки'),num(ddp,1)+'%','neg')+row(t('eduindex.widgets.risk.row_recovery_needed','Нужно для возврата'),'+'+num(rec2,1)+'%','gold');}
  }
  $('sbfw-ddA').onclick=function(){ddMode='A';this.classList.add('active');$('sbfw-ddB').classList.remove('active');$('sbfw-panA').style.display='';$('sbfw-panB').style.display='none';calcDD();};
  $('sbfw-ddB').onclick=function(){ddMode='B';this.classList.add('active');$('sbfw-ddA').classList.remove('active');$('sbfw-panB').style.display='';$('sbfw-panA').style.display='none';calcDD();};
  ['cap','rsk','entry','stop','target'].forEach(function(id){$('sbfw-'+id).addEventListener('input',calcPos);});
  ['wr','aw','al'].forEach(function(id){$('sbfw-'+id).addEventListener('input',calcExp);});
  ['peak','cur','ddR','ddN'].forEach(function(id){$('sbfw-'+id).addEventListener('input',calcDD);});
  calcPos(); calcExp(); calcDD();
}

/* ── Mount system ──────────────────────────────────────────────────────────── */
function mountWidget(el, type, opts) {
  el.style.margin='40px 0';
  if(type==='pattern-gallery') mountPatternGallery(el,opts);
  else if(type==='risk-calc')  mountRiskCalc(el);
  else if(type==='session-clock'){
    // Готового виджета сессий здесь нет (таблица сессий уже есть и работает
    // в главе 5 — SBFSessionTable), а анонсировать "появится в следующем
    // обновлении" запрещено правилом §3.3: неготовое не анонсируем. Не рендерим
    // ничего, а не обещание.
    el.style.display='none';
  }
}

function autoMount(){
  document.querySelectorAll('[data-sbf-widget]').forEach(function(el){
    mountWidget(el, el.dataset.sbfWidget, {filter:el.dataset.filter});
  });
}

if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',autoMount);}
else{autoMount();}

G.SBFWidgets={mount:mountWidget,autoMount:autoMount};
})(window);
