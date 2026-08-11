/* ============================================================================
   SBF ГРАФИК — движок (vanilla, без зависимостей)
   Один data-driven рендерер: свечи + слои (линии/зоны/заливки/сабплоты/уровни).
   Библиотека: свечные(7) + графические(8) + структура рынка(5) + индикаторы(9).
   Live-утилиты: loadBars, detectCandles, detectSMC, calcRSI14, calcBias,
                  calcPivots, nearestPivot, pivotLayers.
   Экспорт: window.SBFGrafik = { ITEMS, CATS, PALETTE, ... }.
   ВАЖНО: на странице с SVG-рендером нужны CSS-классы (.cn/.ln/.zn + @keyframes).
   ========================================================================== */
(function (root) {
  var P = {
    up:'#2E8B6F', down:'#C0504D', gold:'#C9A227', blue:'#3B6EA5',
    violet:'#B07CC6', teal:'#1D9E75', muted:'#7C7563'
  };

  // ── RO/EN/RU язык — тот же детект, что в i18n.js / sbf-glossary.js (без
  // зависимости от порядка загрузки других скриптов) ────────────────────────
  var _langM = location.pathname.match(/^\/(ro|en)(\/|$)/);
  var LANG = _langM ? _langM[1] : 'ru';

  // Небольшой словарь для коротких надписей на самих SVG-диаграммах (линии
  // сопротивления/поддержки/шеи, TP/SL-строки и т.п.) — переводится по ТЕКСТУ
  // ярлыка, не по позиции в массиве, поэтому безопасен для фрагильных
  // ITEMS.candle/ITEMS.chart и не требует правки самих массивов/build().
  var RO_LABELS = {
    'сопротивление':  'rezistență',
    'поддержка':      'suport',
    'линия шеи':      'Linia gâtului',
    'ликвидность':    'lichiditate',
    'последний HL':   'ultimul HL',
    'ордер-блок':     'Order Block',
    'снятие':         'sweep',
    'BOS вниз':       'BOS jos'
  };
  var EN_LABELS = {
    'сопротивление':  'resistance',
    'поддержка':      'support',
    'линия шеи':      'Neckline',
    'ликвидность':    'liquidity',
    'последний HL':   'last HL',
    'ордер-блок':     'Order Block',
    'снятие':         'sweep',
    'BOS вниз':       'BOS down'
  };
  function trLbl(s) {
    if (LANG === 'ro' && RO_LABELS.hasOwnProperty(s)) return RO_LABELS[s];
    if (LANG === 'en' && EN_LABELS.hasOwnProperty(s)) return EN_LABELS[s];
    return s;
  }

  // ---- ГПСЧ и генераторы цены ----
  function mul(a){return function(){a|=0;a=a+0x6D2B79F5|0;var t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
  function walk(n,s,d,v,r){var c=[],p=s;for(var i=0;i<n;i++){p+=d+(r()*2-1)*v;c.push(p);}return c;}
  function toC(cl,v,r,so){var cs=[],pr=so!=null?so:cl[0];for(var i=0;i<cl.length;i++){var o=pr,c=cl[i];cs.push({o:o,c:c,h:Math.max(o,c)+Math.abs(r()*v*0.85),l:Math.min(o,c)-Math.abs(r()*v*0.85)});pr=c;}return cs;}
  function pivPath(piv,per,v,r){var c=[];for(var s=0;s<piv.length-1;s++){var a=piv[s],b=piv[s+1];for(var k=0;k<per;k++)c.push(a+(b-a)*(k/per)+(r()*2-1)*v);}c.push(piv[piv.length-1]);return c;}

  // ---- индикаторы (ядро) ----
  function ema(a,p){var k=2/(p+1),o=[],pr;for(var i=0;i<a.length;i++){pr=i===0?a[0]:a[i]*k+pr*(1-k);o.push(pr);}return o;}
  function sma(a,p){return a.map(function(_,i){return i<p-1?null:a.slice(i-p+1,i+1).reduce(function(x,y){return x+y;},0)/p;});}
  function stdF(a,p){return a.map(function(_,i){if(i<p-1)return null;var s=a.slice(i-p+1,i+1),mu=s.reduce(function(x,y){return x+y;},0)/p;return Math.sqrt(s.reduce(function(x,y){return x+(y-mu)*(y-mu);},0)/p);});}
  function rsiF(a,p){var o=Array(a.length).fill(null),g=0,l=0;for(var i=1;i<a.length;i++){var d=a[i]-a[i-1],u=Math.max(d,0),dn=Math.max(-d,0);if(i<=p){g+=u;l+=dn;if(i===p){g/=p;l/=p;o[i]=100-100/(1+(l===0?100:g/l));}}else{g=(g*(p-1)+u)/p;l=(l*(p-1)+dn)/p;o[i]=100-100/(1+(l===0?100:g/l));}}return o;}
  function macdF(a){var e12=ema(a,12),e26=ema(a,26),m=a.map(function(_,i){return e12[i]-e26[i];}),sig=ema(m,9);return{m:m,sig:sig,hist:m.map(function(v,i){return v-sig[i];})};}
  function stochF(c,p){var k=c.map(function(_,i){if(i<p-1)return null;var s=c.slice(i-p+1,i+1),hh=Math.max.apply(null,s.map(function(x){return x.h;})),ll=Math.min.apply(null,s.map(function(x){return x.l;}));return hh===ll?50:(c[i].c-ll)/(hh-ll)*100;});var d=k.map(function(_,i){if(i<2||k[i]==null||k[i-1]==null||k[i-2]==null)return null;return (k[i]+k[i-1]+k[i-2])/3;});return{k:k,d:d};}
  function atrF(c,p){var tr=c.map(function(x,i){if(i===0)return x.h-x.l;return Math.max(x.h-x.l,Math.abs(x.h-c[i-1].c),Math.abs(x.l-c[i-1].c));});var o=[],pr;for(var i=0;i<tr.length;i++){pr=i===0?tr[0]:(pr*(p-1)+tr[i])/p;o.push(i<p-1?null:pr);}return o;}
  function donch(c,p,i){var s=c.slice(Math.max(0,i-p+1),i+1);return (Math.max.apply(null,s.map(function(x){return x.h;}))+Math.min.apply(null,s.map(function(x){return x.l;})))/2;}

  // ---- TP/SL ----
  var TPMODE = 'measured';
  function plevels(candles,dir,zone){
    var pc=zone?candles.slice(zone[0],zone[1]+1):candles.slice(-6);
    var lo=Math.min.apply(null,pc.map(function(c){return c.l;})),hi=Math.max.apply(null,pc.map(function(c){return c.h;}));
    var ht=hi-lo, last=candles[zone?zone[1]:candles.length-1].c;
    // стоп — за крайней точкой паттерна без большого буфера
    var sl = dir==='bull' ? lo-ht*0.05 : hi+ht*0.05;
    var tp;
    // 1R: консервативная цель (60% хода), Измеренное: высота паттерна, 2R: амбициозная (180%)
    if(TPMODE==='r2')       tp = dir==='bull' ? last+ht*1.8 : last-ht*1.8;
    else if(TPMODE==='r1')  tp = dir==='bull' ? last+ht*0.6 : last-ht*0.6;
    else                    tp = dir==='bull' ? last+ht     : last-ht;
    return {entry:last, sl:sl, tp:tp};
  }

  // ---- паттерны (учебные) ----
  function reversal(dir,fn,seed){var r=mul(seed),v=0.62,u=1.3;var ctx=walk(13,dir==='bull'?62:46,dir==='bull'?-0.55:0.55,v,r);var p0=ctx[ctx.length-1];var pat=fn(p0,u);pat[0].o=p0;var fol=walk(5,pat[pat.length-1].c,dir==='bull'?0.6:-0.6,v,r);return{candles:toC(ctx,v,r).concat(pat,toC(fol,v,r,pat[pat.length-1].c)),zone:[13,13+pat.length-1]};}
  var PAT={
    bullEngulf:function(p,u){return[{o:p,c:p-0.8*u,h:p+0.25*u,l:p-1.0*u},{o:p-1.2*u,c:p+0.7*u,h:p+0.9*u,l:p-1.35*u}];},
    bearEngulf:function(p,u){return[{o:p,c:p+0.8*u,h:p+1.0*u,l:p-0.25*u},{o:p+1.2*u,c:p-0.7*u,h:p+1.35*u,l:p-0.9*u}];},
    hammer:function(p,u){return[{o:p,c:p+0.35*u,h:p+0.55*u,l:p-1.9*u}];},
    doji:function(p,u){return[{o:p,c:p+0.05*u,h:p+1.0*u,l:p-1.0*u}];},
    morningStar:function(p,u){return[{o:p,c:p-2.0*u,h:p+0.2*u,l:p-2.2*u},{o:p-2.45*u,c:p-2.2*u,h:p-2.0*u,l:p-2.6*u},{o:p-2.2*u,c:p-0.4*u,h:p-0.2*u,l:p-2.35*u}];},
    eveningStar:function(p,u){return[{o:p,c:p+2.0*u,h:p+2.2*u,l:p-0.2*u},{o:p+2.45*u,c:p+2.2*u,h:p+2.6*u,l:p+2.0*u},{o:p+2.2*u,c:p+0.4*u,h:p+2.35*u,l:p+0.2*u}];},
    harami:function(p,u){return[{o:p,c:p-2.0*u,h:p+0.2*u,l:p-2.2*u},{o:p-1.5*u,c:p-0.8*u,h:p-0.6*u,l:p-1.65*u}];}
  };
  function chartP(piv,per,seed,v){var r=mul(seed);return toC(pivPath(piv,per,v==null?0.42:v,r),v==null?0.42:v,r);}
  function indSeries(seed,phases){var r=mul(seed||91),px=100,cl=[];(phases||[[14,0.5,0.9],[12,0,0.7],[16,-0.6,1.0],[10,0.15,0.8],[12,0.5,0.9]]).forEach(function(ph){for(var i=0;i<ph[0];i++){px+=ph[1]+(r()*2-1)*ph[2];cl.push(px);}});return{closes:cl,candles:toC(cl,0.85,r)};}

  // ---- РЕНДЕРЕР ----
  function Lh(x1,y1,x2,y2){return Math.hypot(x2-x1,y2-y1);}
  function renderItem(it){
    var W=640,subH=it.sub?112:0,Hp=it.sub?248:300,padX=16,padR=(it.levels?80:16),padT=18,padB=14,plotH=Hp-padT-padB,n=it.candles.length;
    var lo=Infinity,hi=-Infinity;it.candles.forEach(function(c){lo=Math.min(lo,c.l);hi=Math.max(hi,c.h);});
    (it.layers||[]).forEach(function(L2){
      if(L2.t==='hline'){hi=Math.max(hi,L2.y);lo=Math.min(lo,L2.y);}
      if(L2.t==='line'){hi=Math.max(hi,L2.from.y,L2.to.y);lo=Math.min(lo,L2.from.y,L2.to.y);}
      if(L2.t==='poly')L2.data.forEach(function(v){if(v!=null){hi=Math.max(hi,v);lo=Math.min(lo,v);}});
      if(L2.t==='fill'){L2.up.concat(L2.dn).forEach(function(v){if(v!=null){hi=Math.max(hi,v);lo=Math.min(lo,v);}});}
      if(L2.t==='rect'){hi=Math.max(hi,L2.yTop);lo=Math.min(lo,L2.yBot);}
      if(L2.t==='label'){hi=Math.max(hi,L2.y);lo=Math.min(lo,L2.y);}
    });
    if(it.levels){[it.levels.entry,it.levels.sl,it.levels.tp].forEach(function(v){hi=Math.max(hi,v);lo=Math.min(lo,v);});}
    var sp=(hi-lo)*0.07||1;lo-=sp;hi+=sp;
    var X=function(i){return padX+i/(n-1)*(W-padX-padR);},Y=function(v){return padT+(hi-v)/(hi-lo)*plotH;},cw=Math.max(2.2,Math.min((W-padX-padR)/n*0.6,9));
    var aft=n*45+120,s='<svg viewBox="0 0 '+W+' '+(Hp+subH)+'" style="display:block;width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">';
    (it.layers||[]).forEach(function(L2){
      if(L2.t==='fill'){var top=[],bot=[];for(var i=0;i<n;i++){if(L2.up[i]==null||L2.dn[i]==null)continue;top.push([X(i),Y(Math.max(L2.up[i],L2.dn[i]))]);bot.push([X(i),Y(Math.min(L2.up[i],L2.dn[i]))]);}var pts=top.concat(bot.reverse()).map(function(p){return p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' ');s+='<polygon class="zn" style="--zop:'+(L2.op||0.1)+';animation-delay:'+aft+'ms" points="'+pts+'" fill="'+L2.color+'"/>';}
      if(L2.t==='rect'){var x0=X(L2.i0),x1=L2.i1==null?(W-padR):X(L2.i1);s+='<rect class="zn" style="--zop:'+(L2.op||0.13)+';animation-delay:'+aft+'ms" x="'+x0.toFixed(1)+'" y="'+Y(L2.yTop).toFixed(1)+'" width="'+(x1-x0).toFixed(1)+'" height="'+(Y(L2.yBot)-Y(L2.yTop)).toFixed(1)+'" fill="'+L2.color+'" rx="2"/>'+(L2.label?'<text x="'+(x0+4).toFixed(1)+'" y="'+((Y(L2.yTop)+Y(L2.yBot))/2+3).toFixed(1)+'" font-family="JetBrains Mono,monospace" font-size="11" fill="'+L2.color+'">'+trLbl(L2.label)+'</text>':'');}
    });
    for(var i=0;i<n;i++){var c=it.candles[i],xx=X(i),bull=c.c>=c.o,col=bull?P.up:P.down;var nh=Math.abs(Y(c.c)-Y(c.o));var bh=Math.max(nh,Math.min(cw*0.4,4));var by=Math.min(Y(c.o),Y(c.c))-(bh-nh)/2;s+='<g class="cn" style="animation-delay:'+(i*45)+'ms"><line x1="'+xx.toFixed(1)+'" y1="'+Y(c.h).toFixed(1)+'" x2="'+xx.toFixed(1)+'" y2="'+Y(c.l).toFixed(1)+'" stroke="'+col+'" stroke-width="1.1"/><rect x="'+(xx-cw/2).toFixed(1)+'" y="'+by.toFixed(1)+'" width="'+cw.toFixed(1)+'" height="'+bh.toFixed(1)+'" rx="0.7" fill="'+col+'"/></g>';}
    (it.layers||[]).forEach(function(L2,li){
      var dl=aft+li*90;
      if(L2.t==='poly'){var d=L2.data.map(function(v,i){return v==null?null:X(i).toFixed(1)+','+Y(v).toFixed(1);}).filter(Boolean).join(' ');s+='<polyline class="ln" style="stroke-dasharray:5000;stroke-dashoffset:5000;animation-delay:'+dl+'ms" points="'+d+'" fill="none" stroke="'+L2.color+'" stroke-width="'+(L2.w||1.5)+'" opacity="'+(L2.op==null?0.95:L2.op)+'"'+(L2.dash?' stroke-dasharray="'+L2.dash+'"':'')+'/>';}
      if(L2.t==='hline'){var yy=Y(L2.y),ln=W-padX-padR-padX;s+='<line class="ln" style="stroke-dasharray:'+ln+';stroke-dashoffset:'+ln+';animation-delay:'+dl+'ms" x1="'+padX+'" y1="'+yy.toFixed(1)+'" x2="'+(W-padR)+'" y2="'+yy.toFixed(1)+'" stroke="'+(L2.color||P.gold)+'" stroke-width="1.2"/>'+(L2.label?'<text x="'+(padX+3)+'" y="'+(yy-3).toFixed(1)+'" font-family="JetBrains Mono,monospace" font-size="11" fill="'+(L2.color||P.gold)+'">'+trLbl(L2.label)+'</text>':'');}
      if(L2.t==='line'){var x1=X(L2.from.i),y1=Y(L2.from.y),x2=X(L2.to.i),y2=Y(L2.to.y),ll=Lh(x1,y1,x2,y2);s+='<line class="ln" style="stroke-dasharray:'+ll.toFixed(0)+';stroke-dashoffset:'+ll.toFixed(0)+';animation-delay:'+dl+'ms" x1="'+x1.toFixed(1)+'" y1="'+y1.toFixed(1)+'" x2="'+x2.toFixed(1)+'" y2="'+y2.toFixed(1)+'" stroke="'+(L2.color||P.gold)+'" stroke-width="1.3"/>';}
      if(L2.t==='label')s+='<text x="'+X(L2.i).toFixed(1)+'" y="'+Y(L2.y).toFixed(1)+'" font-family="JetBrains Mono,monospace" font-size="11" fill="'+(L2.color||P.muted)+'" text-anchor="'+(L2.anchor||'middle')+'">'+trLbl(L2.text)+'</text>';
      if(L2.t==='marker'){var mx=X(L2.i),my=Y(L2.y),ms=L2.size||7;var mc=L2.dir==='up'?P.up:L2.dir==='down'?P.down:P.gold;s+='<polygon class="cn" style="animation-delay:'+dl+'ms" points="'+mx.toFixed(1)+','+(my-ms).toFixed(1)+' '+(mx+ms).toFixed(1)+','+my.toFixed(1)+' '+mx.toFixed(1)+','+(my+ms).toFixed(1)+' '+(mx-ms).toFixed(1)+','+my.toFixed(1)+'" fill="'+mc+'" opacity="0.9"/>'+(L2.label?'<text x="'+mx.toFixed(1)+'" y="'+(my-ms-4).toFixed(1)+'" font-family="JetBrains Mono,monospace" font-size="11" fill="'+mc+'" text-anchor="middle">'+trLbl(L2.label)+'</text>':'');}
    });
    if(it.levels){
      var lvE=it.levels.entry,lvS=it.levels.sl,lvT=it.levels.tp;
      var yE=Y(lvE),yS=Y(lvS),yT=Y(lvT);
      var zW=W-padX-padR;
      // зоны риска (красная) и прибыли (зелёная)
      s+='<rect x="'+padX+'" y="'+Math.min(yE,yS).toFixed(1)+'" width="'+zW.toFixed(1)+'" height="'+Math.abs(yE-yS).toFixed(1)+'" fill="'+P.down+'" opacity="0.09" rx="1"/>';
      s+='<rect x="'+padX+'" y="'+Math.min(yE,yT).toFixed(1)+'" width="'+zW.toFixed(1)+'" height="'+Math.abs(yE-yT).toFixed(1)+'" fill="'+P.up+'" opacity="0.09" rx="1"/>';
      var tpLabel = LANG==='ro'
        ? (TPMODE==='r2'?'Țintă 2R':TPMODE==='r1'?'Țintă 1R':'Țintă')
        : LANG==='en'
        ? (TPMODE==='r2'?'Target 2R':TPMODE==='r1'?'Target 1R':'Target')
        : (TPMODE==='r2'?'Цель 2R':TPMODE==='r1'?'Цель 1R':'Цель');
      var entryLabel = LANG==='ro'?'Intrare':LANG==='en'?'Entry':'Вход', slLabel = LANG==='ro'?'Stop':LANG==='en'?'Stop':'Стоп';
      var rows=[[entryLabel,lvE,P.gold],[slLabel,lvS,P.down],[tpLabel,lvT,P.up]];
      rows.forEach(function(rw,ri){var yy=Y(rw[1]),ln=W-padX-padR-padX;s+='<line class="ln" style="stroke-dasharray:'+ln+';stroke-dashoffset:'+ln+';animation-delay:'+(aft+260+ri*150)+'ms" x1="'+padX+'" y1="'+yy.toFixed(1)+'" x2="'+(W-padR)+'" y2="'+yy.toFixed(1)+'" stroke="'+rw[2]+'" stroke-width="1.2"/><text x="'+(W-padR+4)+'" y="'+(yy+3.5).toFixed(1)+'" font-family="JetBrains Mono,monospace" font-size="11" fill="'+rw[2]+'">'+rw[0]+'</text>';});
    }
    s+='</svg>';
    if(it.sub)s+=renderSub(it.sub,n,aft);
    return s;
  }
  function renderSub(sp,n,delay){var W=640,H=112,padX=16,padR=56,padT=10,padB=10,plotH=H-padT-padB;var vals=[];sp.series.forEach(function(se){se.data.forEach(function(v){if(v!=null)vals.push(v);});});var lo=sp.lo!=null?sp.lo:Math.min.apply(null,vals),hi=sp.hi!=null?sp.hi:Math.max.apply(null,vals);var pad=(hi-lo)*0.12;lo-=pad;hi+=pad;var X=function(i){return padX+i/(n-1)*(W-padX-padR);},Y=function(v){return padT+(hi-v)/(hi-lo)*plotH;};var s='<svg viewBox="0 0 '+W+' '+H+'" style="display:block;width:100%;height:auto;margin-top:6px" xmlns="http://www.w3.org/2000/svg">';
    (sp.zones||[]).forEach(function(z){s+='<rect x="'+padX+'" y="'+Y(z.to).toFixed(1)+'" width="'+(W-padX-padR)+'" height="'+(Y(z.from)-Y(z.to)).toFixed(1)+'" fill="'+z.color+'" opacity="0.08"/>';});
    (sp.guides||[]).forEach(function(g){s+='<line x1="'+padX+'" y1="'+Y(g).toFixed(1)+'" x2="'+(W-padR)+'" y2="'+Y(g).toFixed(1)+'" stroke="'+P.muted+'" stroke-width="0.7" stroke-dasharray="3 3" opacity="0.5"/><text x="'+(W-padR+3)+'" y="'+(Y(g)+3).toFixed(1)+'" font-family="JetBrains Mono,monospace" font-size="11" fill="'+P.muted+'">'+g+'</text>';});
    sp.series.forEach(function(se,si){if(se.hist){se.data.forEach(function(v,i){if(v==null)return;var y0=Y(0),y1=Y(v);s+='<rect class="cn" style="animation-delay:'+(i*34)+'ms" x="'+(X(i)-2.2).toFixed(1)+'" y="'+Math.min(y0,y1).toFixed(1)+'" width="4.4" height="'+Math.abs(y1-y0).toFixed(1)+'" fill="'+(v>=0?P.up:P.down)+'" opacity="0.55"/>';});}else if(se.bars){se.data.forEach(function(v,i){if(v==null)return;s+='<rect class="cn" style="animation-delay:'+(i*34)+'ms" x="'+(X(i)-2.2).toFixed(1)+'" y="'+Y(v).toFixed(1)+'" width="4.4" height="'+(Y(0)-Y(v)).toFixed(1)+'" fill="'+se.color+'" opacity="0.5"/>';});}else{var d=se.data.map(function(v,i){return v==null?null:X(i).toFixed(1)+','+Y(v).toFixed(1);}).filter(Boolean).join(' ');s+='<polyline class="ln" style="stroke-dasharray:5000;stroke-dashoffset:5000;animation-delay:'+(delay+si*110)+'ms" points="'+d+'" fill="none" stroke="'+se.color+'" stroke-width="1.6"/>';}});
    return s+'</svg>';}

  // ---- предрасчёт учебных серий (50-bar warm-up — все индикаторы стартуют с бара 0) ----
  var _IS0=indSeries(91,[[50,0.3,0.6],[14,0.5,0.9],[12,0,0.7],[16,-0.6,1.0],[10,0.15,0.8],[12,0.5,0.9]]),_W=50;
  var IS={closes:_IS0.closes.slice(_W),candles:_IS0.candles.slice(_W)},CL=IS.closes,CN=IS.candles;
  var ma20=sma(_IS0.closes,20).slice(_W),ma50=sma(_IS0.closes,50).slice(_W),sdv=stdF(_IS0.closes,20).slice(_W),bbU=ma20.map(function(v,i){return v==null||sdv[i]==null?null:v+2*sdv[i];}),bbD=ma20.map(function(v,i){return v==null||sdv[i]==null?null:v-2*sdv[i];});
  var RS=rsiF(_IS0.closes,14).slice(_W),_MC=macdF(_IS0.closes),MC={m:_MC.m.slice(_W),sig:_MC.sig.slice(_W),hist:_MC.hist.slice(_W)},_ST=stochF(_IS0.candles,14),ST={k:_ST.k.slice(_W),d:_ST.d.slice(_W)},AT=atrF(_IS0.candles,14).slice(_W);
  function ichi(){var c=indSeries(33,[[16,0.4,0.7],[14,-0.5,0.8],[18,0.5,0.7]]).candles;var tk=c.map(function(_,i){return donch(c,9,i);}),kj=c.map(function(_,i){return donch(c,26,i);}),sa=c.map(function(_,i){return (tk[i]+kj[i])/2;}),sb=c.map(function(_,i){return donch(c,52,i);});return{candles:c,layers:[{t:'fill',up:sa,dn:sb,color:P.teal,op:0.12},{t:'poly',data:sa,color:P.teal,w:1},{t:'poly',data:sb,color:P.down,w:1},{t:'poly',data:tk,color:P.blue,w:1.3},{t:'poly',data:kj,color:P.gold,w:1.3}]};}
  function fibItem(){var r=mul(7),c=[],p=48;for(var i=0;i<11;i++){var o=p,cc=p+0.95+(r()*2-1)*0.4;c.push({o:o,c:cc,h:Math.max(o,cc)+0.3,l:Math.min(o,cc)-0.3});p=cc;}var hi=p;for(var i=0;i<10;i++){var o=p,cc=p-0.55+(r()*2-1)*0.4;c.push({o:o,c:cc,h:Math.max(o,cc)+0.3,l:Math.min(o,cc)-0.3});p=cc;}var lo=48;var lays=[[0,'0'],[0.236,'.236'],[0.382,'.382'],[0.5,'.5'],[0.618,'.618'],[0.786,'.786'],[1,'1.0']].map(function(f){return {t:'hline',y:hi-(hi-lo)*f[0],color:P.gold,label:f[1],dash:'3 3'};});return{candles:c,layers:lays};}
  function fvgItem(){var r=mul(12),c=[],p=50;for(var i=0;i<6;i++){var o=p,cc=p+(r()*2-1)*0.4;c.push({o:o,c:cc,h:Math.max(o,cc)+0.35,l:Math.min(o,cc)-0.35});p=cc;}var a={o:p,c:p+2.2,h:p+2.4,l:p-0.15};var b={o:a.c,c:a.c+2.6,h:a.c+2.8,l:a.c-0.05};var d={o:b.c,c:b.c+2.0,h:b.c+2.2,l:b.c+0.1};c.push(a,b,d);p=d.c;for(var i=0;i<7;i++){var o=p,cc=p+(r()*2-1)*0.5-0.1;c.push({o:o,c:cc,h:Math.max(o,cc)+0.35,l:Math.min(o,cc)-0.35});p=cc;}return{candles:c,layers:[{t:'rect',i0:6,i1:null,yTop:d.l,yBot:a.h,color:P.violet,op:0.15,label:'FVG'}]};}
  function obItem(){var r=mul(15),c=[],p=58;for(var i=0;i<6;i++){var o=p,cc=p-Math.abs((r()*2-1)*0.5)-0.15;c.push({o:o,c:cc,h:Math.max(o,cc)+0.3,l:Math.min(o,cc)-0.3});p=cc;}var ob={o:p,c:p-0.8,h:p+0.2,l:p-1.0};c.push(ob);p=ob.c;for(var i=0;i<3;i++){var o=p,cc=p+2.0;c.push({o:o,c:cc,h:cc+0.2,l:o-0.15});p=cc;}for(var i=0;i<6;i++){var o=p,cc=p+(r()*2-1)*0.5+0.1;c.push({o:o,c:cc,h:Math.max(o,cc)+0.3,l:Math.min(o,cc)-0.3});p=cc;}return{candles:c,layers:[{t:'rect',i0:6,i1:null,yTop:ob.h,yBot:ob.l,color:P.gold,op:0.16,label:'ордер-блок'}]};}
  function sweepItem(){var r=mul(20),c=[],p=50;for(var i=0;i<5;i++){var o=p,cc=p+(r()*2-1)*0.5;c.push({o:o,c:cc,h:Math.max(o,cc)+0.35,l:Math.min(o,cc)-0.35});p=cc;}c.push({o:p,c:53.6,h:54.0,l:p-0.3});c.push({o:53.6,c:52.8,h:54.0,l:52.6});c.push({o:52.8,c:53.4,h:53.9,l:52.6});c.push({o:53.4,c:52.7,h:55.0,l:52.6});p=52.7;for(var i=0;i<7;i++){var o=p,cc=p-Math.abs((r()*2-1)*0.6)-0.25;c.push({o:o,c:cc,h:Math.max(o,cc)+0.3,l:Math.min(o,cc)-0.4});p=cc;}return{candles:c,layers:[{t:'hline',y:54,color:P.gold,label:'ликвидность',dash:'4 3'},{t:'label',i:8,y:55.6,text:'снятие',color:P.down}]};}
  function structItem(){var c=chartP([46,52,49,57,53,62,58,55],3,5,0.35);var labs=[];[[1,'HH'],[3,'HH'],[5,'HH']].forEach(function(L2){labs.push({t:'label',i:L2[0]*3,y:c[L2[0]*3].h+1.4,text:L2[1],color:P.up});});labs.push({t:'label',i:18,y:c[18].h+1.4,text:'LH',color:P.down});[[2,'HL'],[4,'HL']].forEach(function(L2){labs.push({t:'label',i:L2[0]*3,y:c[L2[0]*3].l-1.4,text:L2[1],color:P.down});});return{candles:c,layers:labs};}
  function bosItem(){var c=chartP([46,52,49,57,54,60,55,50,47],3,9,0.35);return{candles:c,layers:[{t:'hline',y:54,color:P.gold,label:'последний HL',dash:'4 3'},{t:'label',i:21,y:52.5,text:'BOS вниз',color:P.down}]};}

  // ---- БИБЛИОТЕКА ----
  var ITEMS={
    candle:[
      ['bullEngulf','Бычье поглощение','bull',PAT.bullEngulf,7,'После снижения малая медвежья, затем большая бычья перекрывает её тело.','Покупатели перехватили инициативу — часто разворот вверх.'],
      ['bearEngulf','Медвежье поглощение','bear',PAT.bearEngulf,13,'После роста малая бычья, затем большая медвежья перекрывает её тело.','Продавцы перехватили инициативу — часто разворот вниз.'],
      ['hammer','Молот','bull',PAT.hammer,21,'Малое тело вверху и длинная нижняя тень после снижения.','Цену продавили и выкупили — давление продавцов выдыхается.'],
      ['doji','Доджи','bull',PAT.doji,4,'Открытие и закрытие почти совпадают — тело крошечное.','Равновесие сил, нерешительность — часто пауза перед движением.'],
      ['morningStar','Утренняя звезда','bull',PAT.morningStar,31,'Большая медвежья → малая звезда с разрывом → большая бычья.','Снижение выдохлось, инициатива у покупателей.'],
      ['eveningStar','Вечерняя звезда','bear',PAT.eveningStar,5,'Большая бычья → малая звезда с разрывом → большая медвежья.','Рост выдохся, инициатива у продавцов.'],
      ['harami','Харами','bull',PAT.harami,9,'Большая свеча, затем малая внутри её тела.','Импульс резко сжался — возможна пауза или разворот.']
    ].map(function(a){return {key:a[0],n:a[1],f:a[5],w:a[6],note:'Стоп — за фигурой, цель — измеренное движение (высота фигуры).',build:function(){var d=reversal(a[2],a[3],a[4]);return renderItem({candles:d.candles,layers:[{t:'rect',i0:d.zone[0],i1:d.zone[1],yTop:Math.max.apply(null,d.candles.slice(d.zone[0],d.zone[1]+1).map(function(c){return c.h;})),yBot:Math.min.apply(null,d.candles.slice(d.zone[0],d.zone[1]+1).map(function(c){return c.l;})),color:P.gold,op:0.10}],levels:plevels(d.candles,a[2],d.zone)});}};}),
    chart:[
      ['ascTri','Восходящий треугольник','bull',[50,61,54,61,57,61,59,61.5,64],3,[{t:'hline',y:61,label:'сопротивление'},{t:'line',from:{i:0,y:50},to:{i:18,y:59}}],'Горизонтальное сопротивление, минимумы растут.','Покупатели поджимают — прорыв чаще вверх.'],
      ['descTri','Нисходящий треугольник','bear',[60,50,57,50,54,50,52,50,47],3,[{t:'hline',y:50,label:'поддержка'},{t:'line',from:{i:0,y:60},to:{i:18,y:52}}],'Горизонтальная поддержка, максимумы снижаются.','Продавцы поджимают — прорыв чаще вниз.'],
      ['pennant','Вымпел','bull',[48,50,52,63,60,62,60.5,61.5,65],3,[{t:'line',from:{i:9,y:63},to:{i:24,y:61.7}},{t:'line',from:{i:11,y:59.6},to:{i:24,y:61.1}}],'Резкий флагшток, затем сжатие в сходящемся треугольнике.','Пауза внутри сильного движения — часто продолжение.'],
      ['hns','Голова и плечи','bear',[48,57,51,63,51,57,46],4,[{t:'hline',y:51,label:'линия шеи'}],'Три пика: голова выше плеч, общая линия шеи.','Структура роста сломана — цель: высота головы от шеи.'],
      ['dtop','Двойная вершина','bear',[48,60,53,59.5,47],4,[{t:'hline',y:53,label:'линия шеи'}],'Два пика на одном уровне, между ними откат.','Сопротивление дважды устояло — разворот вниз.'],
      ['dbot','Двойное дно','bull',[60,50,57,50,63],4,[{t:'hline',y:57,label:'линия шеи'}],'Два минимума на одном уровне, между ними отскок.','Поддержка дважды устояла — разворот вверх.'],
      ['wedge','Клин','bear',[50,55,52.5,57,54.5,58.5,56.5,59,54],3,[{t:'line',from:{i:3,y:55},to:{i:21,y:59}},{t:'line',from:{i:0,y:50},to:{i:18,y:56.5}}],'Две сходящиеся наклонные линии в одну сторону.','Импульс затухает — разворот против наклона.'],
      ['flag','Флаг','bull',[48,50,62,60,61,59.5,60.5,58.5,64],3,[{t:'line',from:{i:6,y:62},to:{i:21,y:59}},{t:'line',from:{i:8,y:59.5},to:{i:21,y:57}}],'Резкий импульс, затем наклонный канал против него.','Передышка в тренде — часто продолжение.']
    ].map(function(a){return {key:a[0],n:a[1],f:a[6],w:a[7],note:'Стоп — за структурой, цель — измеренное движение фигуры.',build:function(){var c=chartP(a[3],a[4],a[1].length,0.42);return renderItem({candles:c,layers:a[5],levels:plevels(c,a[2])});}};}),
    smc:[
      {key:'structure',n:'Структура рынка (HH/HL)',f:'Последовательность всё более высоких максимумов (HH) и минимумов (HL).',w:'Пока есть HH/HL — тренд вверх; появление LH/LL — сигнал слома.',note:'Базовая разметка тренда. Контекст, не точка входа.',build:function(){return renderItem(structItem());}},
      {key:'bos',n:'Слом структуры (BOS)',f:'Цена пробивает последний значимый минимум восходящей структуры.',w:'Break of Structure — первое подтверждение возможной смены тренда.',note:'Сигнал смены контекста, а не готовая сделка.',build:function(){return renderItem(bosItem());}},
      {key:'sweep',n:'Снятие ликвидности',f:'Цена прокалывает уровень равных хаёв (где стоят стопы) и разворачивается.',w:'Ликвидность собрана — часто резкий разворот после снятия.',note:'Манипуляция перед движением. Контекст направления.',build:function(){return renderItem(sweepItem());}},
      {key:'fvg',n:'FVG / имбаланс',f:'Три свечи сильного импульса оставляют незаполненный разрыв.',w:'Цену часто тянет назад «закрыть» имбаланс перед продолжением.',note:'Зона интереса, куда может вернуться цена.',build:function(){return renderItem(fvgItem());}},
      {key:'ob',n:'Ордер-блок',f:'Последняя противоположная свеча перед сильным импульсом.',w:'Зона, откуда заходил крупный объём — часто реакция при возврате.',note:'Зона интереса, не самостоятельный сигнал.',build:function(){return renderItem(obItem());}}
    ],
    ind:[
      {key:'ma',n:'Скользящие средние',f:'Среднее цены за N баров; линия скользит по каждому бару.',w:'Сглаживает шум; пересечение быстрой и медленной MA — смена тренда.',note:'Контекст направления, не точка входа.',build:function(){return renderItem({candles:CN,layers:[{t:'poly',data:ma20,color:P.blue},{t:'poly',data:ma50,color:P.violet}]});}},
      {key:'bb',n:'Bollinger Bands',f:'Средняя (SMA20) и полосы ±2 стандартных отклонения.',w:'Ширина полос = волатильность; сжатие предшествует движению.',note:'Волатильность, а не сигнал на вход.',build:function(){return renderItem({candles:CN,layers:[{t:'fill',up:bbU,dn:bbD,color:P.blue,op:0.08},{t:'poly',data:bbU,color:P.blue,w:1,op:0.6},{t:'poly',data:bbD,color:P.blue,w:1,op:0.6},{t:'poly',data:ma20,color:P.blue,w:1.3,op:0.5,dash:'3 2'}]});}},
      {key:'rsi',n:'RSI',f:'Отношение средних роста/падения за 14 баров, шкала 0–100.',w:'>70 перекупленность, <30 перепроданность; дивергенция — ослабление.',note:'Контекст силы движения.',build:function(){return renderItem({candles:CN,sub:{series:[{data:RS,color:P.violet}],lo:0,hi:100,guides:[30,50,70],zones:[{from:70,to:100,color:P.down},{from:0,to:30,color:P.up}]}});}},
      {key:'stoch',n:'Stochastic',f:'%K — где закрытие внутри диапазона за N баров; %D — сглаживание.',w:'Зоны >80/<20 и пересечения %K и %D — контекст импульса.',note:'Осциллятор импульса, контекст.',build:function(){return renderItem({candles:CN,sub:{series:[{data:ST.k,color:P.blue},{data:ST.d,color:P.down}],lo:0,hi:100,guides:[20,80],zones:[{from:80,to:100,color:P.down},{from:0,to:20,color:P.up}]}});}},
      {key:'macd',n:'MACD',f:'EMA12−EMA26 + сигнальная EMA9 + гистограмма их разницы.',w:'Пересечения и переход гистограммы через ноль — смена импульса.',note:'Импульс, а не уровень входа.',build:function(){return renderItem({candles:CN,sub:{series:[{data:MC.hist,hist:true},{data:MC.m,color:P.blue},{data:MC.sig,color:P.down}],guides:[0]}});}},
      {key:'atr',n:'ATR',f:'Средний истинный диапазон за 14 баров — размер свечей.',w:'Мера волатильности; часто используется для ширины стопа.',note:'Помогает задать дистанцию стопа.',build:function(){return renderItem({candles:CN,sub:{series:[{data:AT,color:P.gold}]}});}},
      {key:'ichimoku',n:'Ишимоку',f:'Tenkan, Kijun и облако (Senkou A/B) — система целиком.',w:'Цена над облаком — тренд вверх; облако — динамическая поддержка/сопротивление.',note:'Комплексный контекст тренда.',build:function(){return renderItem(ichi());}},
      {key:'fib',n:'Уровни Фибоначчи',f:'Горизонтальные уровни 0–100% на импульсном движении.',w:'Зоны 0.382–0.618 — частые области отката перед продолжением.',note:'Зоны возможного отката, контекст.',build:function(){return renderItem(fibItem());}},
      {key:'volume',n:'Объём',f:'Сколько единиц сменило владельца за бар.',w:'Рост объёма подтверждает движение; слабый объём — сомнение.',note:'Подтверждение силы движения.',build:function(){var vol=CN.map(function(c,i){return Math.abs(c.c-c.o)*3+0.4+(i%5===0?2:0);});return renderItem({candles:CN,sub:{series:[{data:vol,bars:true,color:P.blue}],lo:0}});}}
    ]
  };
  var CATS=[['candle','Свечные паттерны'],['chart','Графические паттерны'],['smc','Структура рынка'],['ind','Индикаторы']];

  // ── RO overlay — переводит ТОЛЬКО отображаемый текст готовых объектов
  // ITEMS[cat][i] (n/f/w/note), построенных выше из .map()/литералов. Ключи —
  // item.key (не позиция в массиве), поэтому позиционные массивы ITEMS.candle/
  // ITEMS.chart и их geometry/build() совершенно не затрагиваются: build()
  // замыкает оригинальные a[...] из RU-массива (в т.ч. a[1].length как seed
  // генератора формы), которые здесь не трогаем и не читаем. ─────────────────
  var RO_PATTERNS = {
    // -- свечные (candle) --
    bullEngulf:  {n:'Bullish Engulfing (înghițire)', f:'După o scădere apare o lumânare bearish mică, apoi una bullish mare îi acoperă complet corpul.', w:'Cumpărătorii au preluat inițiativa — adesea urmează o răsturnare în sus.', note:'Stop dincolo de figură, țintă — mișcarea măsurată (înălțimea figurii).'},
    bearEngulf:  {n:'Bearish Engulfing (înghițire)', f:'După o creștere apare o lumânare bullish mică, apoi una bearish mare îi acoperă complet corpul.', w:'Vânzătorii au preluat inițiativa — adesea urmează o răsturnare în jos.', note:'Stop dincolo de figură, țintă — mișcarea măsurată (înălțimea figurii).'},
    hammer:      {n:'Hammer (ciocan)', f:'Corp mic în partea de sus și o umbră inferioară lungă, apărută după o scădere.', w:'Prețul a fost împins jos și răscumpărat — presiunea vânzătorilor se stinge.', note:'Stop dincolo de figură, țintă — mișcarea măsurată (înălțimea figurii).'},
    doji:        {n:'Doji (cruce)', f:'Deschiderea și închiderea aproape coincid — corpul este minuscul.', w:'Echilibru de forțe, indecizie — adesea o pauză înaintea unei mișcări.', note:'Stop dincolo de figură, țintă — mișcarea măsurată (înălțimea figurii).'},
    morningStar: {n:'Morning Star (steaua dimineții)', f:'Lumânare bearish mare → stea mică cu gol → lumânare bullish mare.', w:'Scăderea s-a epuizat, inițiativa trece la cumpărători.', note:'Stop dincolo de figură, țintă — mișcarea măsurată (înălțimea figurii).'},
    eveningStar: {n:'Evening Star (steaua serii)', f:'Lumânare bullish mare → stea mică cu gol → lumânare bearish mare.', w:'Creșterea s-a epuizat, inițiativa trece la vânzători.', note:'Stop dincolo de figură, țintă — mișcarea măsurată (înălțimea figurii).'},
    harami:      {n:'Harami (interior)', f:'O lumânare mare, apoi una mică în interiorul corpului ei.', w:'Impulsul s-a comprimat brusc — posibilă pauză sau răsturnare.', note:'Stop dincolo de figură, țintă — mișcarea măsurată (înălțimea figurii).'},
    // -- графические (chart) --
    ascTri:  {n:'Triunghi ascendent', f:'Rezistență orizontală, minimele cresc treptat.', w:'Cumpărătorii strâng prețul — spargerea are loc mai des în sus.', note:'Stop dincolo de structură, țintă — mișcarea măsurată a figurii.'},
    descTri: {n:'Triunghi descendent', f:'Suport orizontal, maximele scad treptat.', w:'Vânzătorii strâng prețul — spargerea are loc mai des în jos.', note:'Stop dincolo de structură, țintă — mișcarea măsurată a figurii.'},
    pennant: {n:'Fanion', f:'Catarg abrupt, apoi comprimare într-un triunghi convergent.', w:'Pauză în interiorul unei mișcări puternice — adesea continuare.', note:'Stop dincolo de structură, țintă — mișcarea măsurată a figurii.'},
    hns:     {n:'Cap și Umeri', f:'Trei vârfuri: capul mai sus decât umerii, cu o linie a gâtului comună.', w:'Structura de creștere e ruptă — ținta: înălțimea capului față de linia gâtului.', note:'Stop dincolo de structură, țintă — mișcarea măsurată a figurii.'},
    dtop:    {n:'Vârf dublu', f:'Două vârfuri la același nivel, cu o revenire între ele.', w:'Rezistența a rezistat de două ori — răsturnare în jos.', note:'Stop dincolo de structură, țintă — mișcarea măsurată a figurii.'},
    dbot:    {n:'Fund dublu', f:'Două minime la același nivel, cu un recul între ele.', w:'Suportul a rezistat de două ori — răsturnare în sus.', note:'Stop dincolo de structură, țintă — mișcarea măsurată a figurii.'},
    wedge:   {n:'Pană', f:'Două linii înclinate convergente, orientate în aceeași direcție.', w:'Impulsul se stinge — răsturnare împotriva înclinării.', note:'Stop dincolo de structură, țintă — mișcarea măsurată a figurii.'},
    flag:    {n:'Steag', f:'Impuls abrupt, apoi un canal înclinat împotriva lui.', w:'Respiro în cadrul tendinței — adesea continuare.', note:'Stop dincolo de structură, țintă — mișcarea măsurată a figurii.'},
    // -- структура рынка (smc) --
    structure: {n:'Structura pieței (HH/HL)', f:'O succesiune de maxime tot mai mari (HH) și minime tot mai mari (HL).', w:'Cât timp există HH/HL — trendul e ascendent; apariția LH/LL — semnal de ruptură.', note:'Marcaj de bază al trendului. Context, nu punct de intrare.'},
    bos:       {n:'Ruperea structurii (BOS)', f:'Prețul sparge ultimul minim semnificativ al structurii ascendente.', w:'Break of Structure — prima confirmare a unei posibile schimbări de trend.', note:'Semnal de schimbare a contextului, nu o tranzacție gata făcută.'},
    sweep:     {n:'Sweep de lichiditate', f:'Prețul străpunge nivelul unor maxime egale (unde stau stopurile) și se răstoarnă.', w:'Lichiditatea a fost colectată — adesea urmează o răsturnare bruscă după sweep.', note:'Manipulare înaintea mișcării. Context de direcție.'},
    fvg:       {n:'FVG / dezechilibru', f:'Trei lumânări de impuls puternic lasă un gol neacoperit.', w:'Prețul este adesea atras înapoi să „închidă” dezechilibrul înainte de continuare.', note:'Zonă de interes, unde prețul se poate întoarce.'},
    ob:        {n:'Order Block', f:'Ultima lumânare opusă înainte de un impuls puternic.', w:'Zona de unde a intrat un volum mare — reacție frecventă la revenire.', note:'Zonă de interes, nu un semnal de sine stătător.'},
    // -- индикаторы (ind) --
    ma:       {n:'Medii mobile', f:'Media prețului pe N bare; linia alunecă odată cu fiecare bară.', w:'Netezește zgomotul; intersecția MA rapide și lente — schimbare de trend.', note:'Context de direcție, nu punct de intrare.'},
    bb:       {n:'Bollinger Bands', f:'Medie (SMA20) și benzi la ±2 deviații standard.', w:'Lățimea benzilor = volatilitate; comprimarea precede mișcarea.', note:'Volatilitate, nu semnal de intrare.'},
    rsi:      {n:'RSI', f:'Raportul dintre creșterile și scăderile medii pe 14 bare, scală 0–100.', w:'>70 supracumpărare, <30 supravânzare; divergența — semnal de slăbire.', note:'Context al forței mișcării.'},
    stoch:    {n:'Stochastic', f:'%K — poziția închiderii în intervalul din ultimele N bare; %D — netezirea lui %K.', w:'Zonele >80/<20 și intersecțiile %K cu %D — context de impuls.', note:'Oscilator de impuls, context.'},
    macd:     {n:'MACD', f:'EMA12−EMA26 + linia de semnal EMA9 + histograma diferenței lor.', w:'Intersecțiile și trecerea histogramei prin zero — schimbare de impuls.', note:'Impuls, nu nivel de intrare.'},
    atr:      {n:'ATR', f:'Intervalul real mediu pe 14 bare — dimensiunea lumânărilor.', w:'Măsură a volatilității; folosit adesea pentru a stabili distanța stopului.', note:'Ajută la stabilirea distanței stopului.'},
    ichimoku: {n:'Ichimoku', f:'Tenkan, Kijun și norul (Senkou A/B) — sistemul în ansamblu.', w:'Prețul deasupra norului — trend ascendent; norul acționează ca suport/rezistență dinamică.', note:'Context complex al trendului.'},
    fib:      {n:'Niveluri Fibonacci', f:'Niveluri orizontale 0–100% aplicate pe o mișcare impulsivă.', w:'Zonele 0,382–0,618 sunt zone frecvente de recul înainte de continuare.', note:'Zone de recul posibil, context.'},
    volume:   {n:'Volum', f:'Câte unități și-au schimbat proprietarul într-o bară.', w:'Creșterea volumului confirmă mișcarea; volumul slab — semn de îndoială.', note:'Confirmare a forței mișcării.'}
  };
  var RO_CATS = {candle:'Modele de lumânări', chart:'Modele grafice', smc:'Structura pieței', ind:'Indicatori'};

  // ── EN overlay — mirrors the RO overlay above exactly (same shape, same
  // keys, same n/f/w/note fields, same application mechanism by item.key).
  // See the RO overlay comment above for why this is safe against the
  // fragile positional ITEMS.candle/ITEMS.chart arrays. ─────────────────────
  var EN_PATTERNS = {
    // -- candlestick (candle) --
    bullEngulf:  {n:'Bullish Engulfing', f:'After a decline, a small bearish candle is followed by a larger bullish candle that fully engulfs its body.', w:'Buyers have seized the initiative — often a bullish reversal.', note:'Stop beyond the pattern; target is the measured move (pattern height).'},
    bearEngulf:  {n:'Bearish Engulfing', f:'After a rally, a small bullish candle is followed by a larger bearish candle that fully engulfs its body.', w:'Sellers have seized the initiative — often a bearish reversal.', note:'Stop beyond the pattern; target is the measured move (pattern height).'},
    hammer:      {n:'Hammer', f:'A small body near the top with a long lower wick, forming after a decline.', w:'Price was pushed down and then bought back up — selling pressure is fading.', note:'Stop beyond the pattern; target is the measured move (pattern height).'},
    doji:        {n:'Doji', f:'Open and close are nearly equal — the body is tiny.', w:'A balance of forces, indecision — often a pause before the next move.', note:'Stop beyond the pattern; target is the measured move (pattern height).'},
    morningStar: {n:'Morning Star', f:'Large bearish candle → small gapped star → large bullish candle.', w:'The decline has run out of steam — buyers take the initiative.', note:'Stop beyond the pattern; target is the measured move (pattern height).'},
    eveningStar: {n:'Evening Star', f:'Large bullish candle → small gapped star → large bearish candle.', w:'The rally has run out of steam — sellers take the initiative.', note:'Stop beyond the pattern; target is the measured move (pattern height).'},
    harami:      {n:'Harami', f:'A large candle followed by a small one contained within its body.', w:'Momentum has sharply contracted — a pause or reversal is possible.', note:'Stop beyond the pattern; target is the measured move (pattern height).'},
    // -- chart patterns (chart) --
    ascTri:  {n:'Ascending Triangle', f:'Horizontal resistance with rising higher lows.', w:'Buyers are compressing price — the breakout is more often to the upside.', note:'Stop beyond the structure; target is the pattern\'s measured move.'},
    descTri: {n:'Descending Triangle', f:'Horizontal support with falling lower highs.', w:'Sellers are compressing price — the breakout is more often to the downside.', note:'Stop beyond the structure; target is the pattern\'s measured move.'},
    pennant: {n:'Pennant', f:'A sharp flagpole move, followed by a contraction into a converging triangle.', w:'A pause within a strong move — often a continuation.', note:'Stop beyond the structure; target is the pattern\'s measured move.'},
    hns:     {n:'Head & Shoulders', f:'Three peaks: the head higher than the two shoulders, sharing a common neckline.', w:'The uptrend structure is broken — target: the head\'s height measured from the neckline.', note:'Stop beyond the structure; target is the pattern\'s measured move.'},
    dtop:    {n:'Double Top', f:'Two peaks at the same level, with a pullback between them.', w:'Resistance held twice — a bearish reversal.', note:'Stop beyond the structure; target is the pattern\'s measured move.'},
    dbot:    {n:'Double Bottom', f:'Two lows at the same level, with a bounce between them.', w:'Support held twice — a bullish reversal.', note:'Stop beyond the structure; target is the pattern\'s measured move.'},
    wedge:   {n:'Wedge', f:'Two converging trendlines sloping in the same direction.', w:'Momentum is fading — a reversal against the slope.', note:'Stop beyond the structure; target is the pattern\'s measured move.'},
    flag:    {n:'Flag', f:'A sharp impulse move, followed by a sloping channel against it.', w:'A breather within the trend — often a continuation.', note:'Stop beyond the structure; target is the pattern\'s measured move.'},
    // -- market structure (smc) --
    structure: {n:'Market Structure (HH/HL)', f:'A sequence of progressively higher highs (HH) and higher lows (HL).', w:'As long as HH/HL continue, the trend is up; the appearance of LH/LL signals a break.', note:'Basic trend mapping. Context, not an entry point.'},
    bos:       {n:'Break of Structure (BOS)', f:'Price breaks the last significant low of an uptrend structure.', w:'Break of Structure — the first confirmation of a possible trend change.', note:'A signal of a context change, not a ready-made trade.'},
    sweep:     {n:'Liquidity Sweep', f:'Price pokes through a level of equal highs (where stops rest) and reverses.', w:'Liquidity has been collected — often a sharp reversal follows the sweep.', note:'Manipulation ahead of a move. Directional context.'},
    fvg:       {n:'FVG / Imbalance', f:'Three candles of a strong impulse leave an unfilled gap.', w:'Price is often pulled back to “fill” the imbalance before continuing.', note:'A zone of interest that price may return to.'},
    ob:        {n:'Order Block', f:'The last opposite-direction candle before a strong impulse move.', w:'A zone where large volume entered — often a reaction on return.', note:'A zone of interest, not a standalone signal.'},
    // -- indicators (ind) --
    ma:       {n:'Moving Averages', f:'The average price over N bars; the line slides forward with each new bar.', w:'Smooths out noise; a crossover of the fast and slow MA signals a trend change.', note:'Directional context, not an entry point.'},
    bb:       {n:'Bollinger Bands', f:'A middle line (SMA20) with bands at ±2 standard deviations.', w:'Band width reflects volatility; a squeeze often precedes a move.', note:'Volatility, not an entry signal.'},
    rsi:      {n:'RSI', f:'The ratio of average gains to losses over 14 bars, on a 0–100 scale.', w:'>70 overbought, <30 oversold; divergence signals weakening momentum.', note:'Context on the strength of the move.'},
    stoch:    {n:'Stochastic', f:'%K shows where the close sits within the N-bar range; %D is its smoothed average.', w:'The >80/<20 zones and %K/%D crossovers give momentum context.', note:'A momentum oscillator, context only.'},
    macd:     {n:'MACD', f:'EMA12−EMA26, plus a signal EMA9, plus a histogram of their difference.', w:'Crossovers and the histogram crossing zero signal a momentum shift.', note:'Momentum, not an entry level.'},
    atr:      {n:'ATR', f:'The average true range over 14 bars — the typical candle size.', w:'A volatility measure; often used to size stop distance.', note:'Helps set the stop distance.'},
    ichimoku: {n:'Ichimoku', f:'Tenkan, Kijun, and the cloud (Senkou A/B) — the system as a whole.', w:'Price above the cloud signals an uptrend; the cloud acts as dynamic support/resistance.', note:'Comprehensive trend context.'},
    fib:      {n:'Fibonacci Levels', f:'Horizontal levels from 0–100% drawn over an impulse move.', w:'The 0.382–0.618 zone is a common pullback area before continuation.', note:'Zones of possible pullback, context.'},
    volume:   {n:'Volume', f:'How many units changed hands during a bar.', w:'Rising volume confirms the move; weak volume raises doubt.', note:'Confirmation of the strength of a move.'}
  };
  var EN_CATS = {candle:'Candlestick Patterns', chart:'Chart Patterns', smc:'Market Structure', ind:'Indicators'};

  if (LANG === 'ro') {
    ['candle','chart','smc','ind'].forEach(function(cat){
      (ITEMS[cat]||[]).forEach(function(item){
        var tr = RO_PATTERNS[item.key];
        if (tr) { item.n = tr.n; item.f = tr.f; item.w = tr.w; item.note = tr.note; }
      });
    });
    CATS.forEach(function(c){ if (RO_CATS[c[0]]) c[1] = RO_CATS[c[0]]; });
  } else if (LANG === 'en') {
    ['candle','chart','smc','ind'].forEach(function(cat){
      (ITEMS[cat]||[]).forEach(function(item){
        var tr = EN_PATTERNS[item.key];
        if (tr) { item.n = tr.n; item.f = tr.f; item.w = tr.w; item.note = tr.note; }
      });
    });
    CATS.forEach(function(c){ if (EN_CATS[c[0]]) c[1] = EN_CATS[c[0]]; });
  }

  function findItem(cat,key){var arr=ITEMS[cat]||[];for(var i=0;i<arr.length;i++)if(arr[i].key===key)return arr[i];return null;}
  function setTpMode(m){TPMODE=m;}

  // ── Публичные рендереры для Календаря ─────────────────────────────────────
  var MONTHS_RU=['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек'];

  function renderEventHistory(data){
    if(!data||!data.length)return'<div style="padding:30px;text-align:center;color:'+P.muted+';font-family:JetBrains Mono,monospace;font-size:12px">История нарастает по мере выхода релизов</div>';
    var W=600,H=170,pL=38,pR=12,pT=14,pB=22,plotW=W-pL-pR,plotH=H-pT-pB,n=data.length;
    var vals=[];data.forEach(function(d){if(d.actual!=null)vals.push(+d.actual);if(d.forecast!=null)vals.push(+d.forecast);});
    if(!vals.length)return'<div style="padding:30px;text-align:center;color:'+P.muted+';font-family:JetBrains Mono,monospace;font-size:12px">Нет данных</div>';
    var lo=Math.min.apply(null,vals),hi=Math.max.apply(null,vals),pad=(hi-lo)*0.18||0.4;lo-=pad;hi+=pad;
    var BW=Math.max(5,Math.min(plotW/n*0.5,22));
    var X=function(i){return pL+(i+0.5)*(plotW/n);},Y=function(v){return pT+(hi-v)/(hi-lo)*plotH;},Y0=Math.max(pT,Math.min(pT+plotH,Y(0)));
    var hasForecast=data.some(function(d){return d.forecast!=null;});
    // Без прогноза сравнивать факт не с чем -- раньше цвет столбика (рост/спад)
    // в этом случае брался просто по знаку самого факта, а у большинства
    // индикаторов (индексы, счётчики занятости и т.п.) факт почти всегда
    // положителен -- все столбики красились в один и тот же зелёный,
    // независимо от того, вышла цифра сильной или слабой. Фолбэк на
    // "предыдущее" (оно почти всегда есть, в отличие от прогноза) даёт
    // содержательный цвет вместо декоративного.
    function surpriseOf(d){
      if(d.actual==null)return null;
      if(d.forecast!=null)return(+d.actual)-(+d.forecast);
      if(d.previous!=null)return(+d.actual)-(+d.previous);
      return+d.actual;
    }
    var gid='eh'+Math.random().toString(36).slice(2,8);
    var s='<svg viewBox="0 0 '+W+' '+H+'" style="display:block;width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">';
    s+='<defs><linearGradient id="'+gid+'-up" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+P.up+'" stop-opacity="0.95"/><stop offset="1" stop-color="'+P.up+'" stop-opacity="0.62"/></linearGradient>'
      +'<linearGradient id="'+gid+'-down" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+P.down+'" stop-opacity="0.95"/><stop offset="1" stop-color="'+P.down+'" stop-opacity="0.62"/></linearGradient></defs>';
    var unit=data[data.length-1].unit||'';
    [[lo+pad,''],[(lo+hi)/2,''],[hi-pad,'']].forEach(function(g){var yy=Y(g[0]);s+='<line x1="'+pL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-pR)+'" y2="'+yy.toFixed(1)+'" stroke="'+P.muted+'" stroke-width="0.5" opacity="0.22"/><text x="'+(pL-3).toFixed(1)+'" y="'+(yy+3.5).toFixed(1)+'" font-family="JetBrains Mono,monospace" font-size="11" fill="'+P.muted+'" text-anchor="end">'+g[0].toFixed(1)+'</text>';});
    if(lo<0&&hi>0)s+='<line x1="'+pL+'" y1="'+Y0.toFixed(1)+'" x2="'+(W-pR)+'" y2="'+Y0.toFixed(1)+'" stroke="'+P.muted+'" stroke-width="0.8" opacity="0.5"/>';
    data.forEach(function(d,i){
      var xx=X(i),surp=surpriseOf(d);
      if(d.actual!=null){
        var fill='url(#'+gid+(surp>=0?'-up':'-down')+')';
        var ay0=Math.min(Y(+d.actual),Y0),ay1=Math.max(Y(+d.actual),Y0)+1;
        s+='<rect class="cn" style="animation-delay:'+(i*35)+'ms" x="'+(xx-BW/2).toFixed(1)+'" y="'+ay0.toFixed(1)+'" width="'+BW.toFixed(1)+'" height="'+(ay1-ay0).toFixed(1)+'" fill="'+fill+'" rx="2"/>';
      }
      // Прогноз -- тонкая золотая насечка-ориентир поверх столбика (как PP/
      // fib-уровни на ценовом графике: тот же P.gold = "заданная точка
      // отсчёта"), а не отдельный конкурирующий прямоугольник-призрак.
      if(d.forecast!=null){
        var fy=Y(+d.forecast);
        s+='<line x1="'+(xx-BW/2-3).toFixed(1)+'" y1="'+fy.toFixed(1)+'" x2="'+(xx+BW/2+3).toFixed(1)+'" y2="'+fy.toFixed(1)+'" stroke="'+P.gold+'" stroke-width="1.6" stroke-linecap="round" opacity="0.9"/>';
      }
      if(i===n-1&&d.actual!=null){var col2=surp>=0?P.up:P.down;s+='<text x="'+(xx+BW/2+4).toFixed(1)+'" y="'+(Math.min(Y(+d.actual),Y0)-3).toFixed(1)+'" font-family="JetBrains Mono,monospace" font-size="11" fill="'+col2+'">'+((+d.actual).toFixed(2))+unit+'</text>';}
      var dt=new Date(d.ts*1000);s+='<text x="'+xx.toFixed(1)+'" y="'+(H-5)+'" font-family="JetBrains Mono,monospace" font-size="11" fill="'+P.muted+'" text-anchor="middle">'+MONTHS_RU[dt.getUTCMonth()]+' \''+String(dt.getUTCFullYear()).slice(2)+'</text>';
    });
    s+='<rect x="'+(W-pR-52)+'" y="'+pT+'" width="8" height="8" fill="url(#'+gid+'-up)" rx="2"/><text x="'+(W-pR-41)+'" y="'+(pT+7)+'" font-family="JetBrains Mono,monospace" font-size="11" fill="'+P.muted+'">Факт</text>';
    // Легенда прогноза -- только если хоть у одной точки он реально есть
    // (иначе показываем ключ, который ни разу не используется — выглядит
    // как неиспользуемый плейсхолдер).
    if(hasForecast)s+='<line x1="'+(W-pR-52)+'" y1="'+(pT+15)+'" x2="'+(W-pR-44)+'" y2="'+(pT+15)+'" stroke="'+P.gold+'" stroke-width="1.6" stroke-linecap="round"/><text x="'+(W-pR-41)+'" y="'+(pT+18)+'" font-family="JetBrains Mono,monospace" font-size="11" fill="'+P.muted+'">Прогноз</text>';
    return s+'</svg>';
  }

  function renderPriceChart(bars, markers){
    if(!bars||!bars.length)return'<div style="padding:30px;text-align:center;color:'+P.muted+';font-family:JetBrains Mono,monospace;font-size:12px">Нет ценовых данных. Запустите twelvedata_pull.py для загрузки.</div>';
    var tsIdx={};bars.forEach(function(b,i){tsIdx[b.ts]=i;});
    var layers=[];
    (markers||[]).forEach(function(m){
      var idx=tsIdx[m.ts];
      if(idx==null)return;
      var bar=bars[idx];
      var surp=m.forecast!=null?(+m.actual)-(+m.forecast):+m.actual;
      layers.push({t:'marker',i:idx,y:bar.h,dir:surp>=0?'up':'down',label:m.actual!=null?((+m.actual).toFixed(2)):'',size:6});
    });
    var candles=bars.map(function(b){return{o:+b.o,h:+b.h,l:+b.l,c:+b.c};});
    var start=Math.max(0,candles.length-90);
    var sliceC=candles.slice(start),sliceL=layers.map(function(L2){return Object.assign({},L2,{i:L2.i-start});}).filter(function(L2){return L2.i>=0;});
    return renderItem({candles:sliceC,layers:sliceL});
  }

  // ── Live-data utilities ────────────────────────────────────────────────────

  // WP1.2 SPEC_alpha_engine_implementation.md: до миграции ohlc_*.json на
  // price_bars ТФ-файл существовал для КАЖДОГО символа (публиковался из
  // Yahoo). Теперь M15/H1/H4 у части символов честно не пишутся (price_bars
  // не имеет этой гранулярности у брокера) -- 404 на статике. Раньше сюда
  // такой ответ не приходил вообще, поэтому r.json() на HTML-странице 404
  // ронял всю функцию необработанным исключением (пойман кликом по вкладке
  // в Playwright, не curl'ом -- см. Core-лог). "Нет данных" -- валидный,
  // не аварийный исход.
  function _emptyBars() {
    return { meta: { ticker: null, label: null, last: null, interval: null,
                      bias: null, rsi: null, nearest: null, patterns: [] },
             levels: [], bars: [], lw: [], volume: [] };
  }

  async function loadBars(symbol, tf) {
    // M5 — SPEC_chart_fixes_and_staged_signup.md §3: не статический файл
    // (не весь охват на диске, дорого), а короткое окно по API-запросу.
    var url = tf === 'M5'
      ? './api/chart/ohlc-m5?symbol=' + symbol + '&t=' + Date.now()
      : './data/ohlc_' + symbol + '_' + tf + '.json?t=' + Date.now();
    var r = await fetch(url);
    if (!r.ok) return _emptyBars();
    var d = await r.json();
    var bars = (d.candles || []).map(function(c) {
      return {
        ts:  c.time,
        o:   c.open  != null ? +c.open  : +c.o,
        h:   c.high  != null ? +c.high  : +c.h,
        l:   c.low   != null ? +c.low   : +c.l,
        c:   c.close != null ? +c.close : +c.c
      };
    });
    return {
      meta: {
        ticker: d.ticker, label: d.label, last: d.last,
        interval: d.interval, bias: d.bias, rsi: d.rsi,
        nearest: d.nearest, patterns: d.patterns || []
      },
      levels: d.levels || [],
      bars:   bars,
      lw:     d.candles || [],
      volume: d.volume  || []
    };
  }

  function calcRSI14(bars) {
    var closes = bars.map(function(b) { return b.c; });
    var rs = rsiF(closes, 14);
    var v = rs[rs.length - 1];
    return v != null ? +v.toFixed(1) : null;
  }

  function calcBias(bars) {
    var closes = bars.map(function(b) { return b.c; });
    var fast = ema(closes, 9), slow = ema(closes, 21);
    var i = closes.length - 1;
    if (!fast[i] || !slow[i]) return 'нейтр';
    var diff = (fast[i] - slow[i]) / slow[i] * 100;
    return diff > 0.3 ? 'бычья' : diff < -0.3 ? 'медвежья' : 'нейтр';
  }

  function calcPivots(bars) {
    if (bars.length < 2) return null;
    var p = bars[bars.length - 2];
    var PP = (p.h + p.l + p.c) / 3;
    return { PP: PP, R1: 2*PP - p.l, R2: PP + (p.h - p.l), S1: 2*PP - p.h, S2: PP - (p.h - p.l) };
  }

  function nearestPivot(price, pivots) {
    if (!pivots) return null;
    var pts = [{n:'R2',v:pivots.R2},{n:'R1',v:pivots.R1},{n:'PP',v:pivots.PP},{n:'S1',v:pivots.S1},{n:'S2',v:pivots.S2}];
    var best = pts[0], bd = Math.abs(price - pts[0].v);
    pts.forEach(function(p) { var d = Math.abs(price - p.v); if (d < bd) { bd = d; best = p; } });
    return { name: best.n, price: best.v, dist_pct: +((price - best.v) / best.v * 100).toFixed(2) };
  }

  function pivotLayers(pivots) {
    if (!pivots) return [];
    return [
      {t:'hline', y:pivots.R2, color:P.down,  label:'R2', dash:'3 3'},
      {t:'hline', y:pivots.R1, color:P.down,  label:'R1', dash:'4 3'},
      {t:'hline', y:pivots.PP, color:P.gold,  label:'PP'},
      {t:'hline', y:pivots.S1, color:P.up,    label:'S1', dash:'4 3'},
      {t:'hline', y:pivots.S2, color:P.up,    label:'S2', dash:'3 3'}
    ];
  }

  // ── detectCandles — детерминированный детект свечных паттернов ─────────────
  // Возвращает [{type, i, dir, label, yTop?, yBot?, y?}, ...]
  function detectCandles(bars) {
    var events = [];
    var n = bars.length;
    function bd(c) { return Math.abs(c.c - c.o); }
    function rng(c) { return c.h - c.l; }
    function bull(c) { return c.c >= c.o; }

    for (var i = 2; i < n; i++) {
      var c = bars[i], p = bars[i-1], pp = bars[i-2];

      // Бычье поглощение
      if (!bull(p) && bull(c) && bd(p) > 0 && c.o <= p.c && c.c >= p.o && bd(c) > bd(p) * 1.02) {
        events.push({type:'bullEngulf', i:i, dir:'bull', label:'бычье погл',
          yTop: Math.max(p.h, c.h), yBot: Math.min(p.l, c.l)});
      }
      // Медвежье поглощение
      if (bull(p) && !bull(c) && bd(p) > 0 && c.o >= p.c && c.c <= p.o && bd(c) > bd(p) * 1.02) {
        events.push({type:'bearEngulf', i:i, dir:'bear', label:'медвеж погл',
          yTop: Math.max(p.h, c.h), yBot: Math.min(p.l, c.l)});
      }
      // Молот (нижняя тень ≥ 2× тела, верхняя ≤ 0.5× тела)
      var lsh = Math.min(c.o, c.c) - c.l, ush = c.h - Math.max(c.o, c.c);
      if (bd(c) > 0 && lsh >= bd(c) * 2 && ush <= bd(c) * 0.5) {
        events.push({type:'hammer', i:i, dir:'bull', label:'молот', y: c.l});
      }
      // Доджи (тело < 10% диапазона)
      if (rng(c) > 0 && bd(c) / rng(c) < 0.1) {
        events.push({type:'doji', i:i, dir:'neutral', label:'доджи', y: c.h});
      }
      // Утренняя звезда
      if (!bull(pp) && rng(p) < rng(pp) * 0.5 && bull(c) && c.c > (pp.o + pp.c) / 2) {
        events.push({type:'morningStar', i:i, dir:'bull', label:'утр звезда',
          yTop: Math.max(pp.h, c.h), yBot: Math.min(pp.l, c.l)});
      }
      // Вечерняя звезда
      if (bull(pp) && rng(p) < rng(pp) * 0.5 && !bull(c) && c.c < (pp.o + pp.c) / 2) {
        events.push({type:'eveningStar', i:i, dir:'bear', label:'веч звезда',
          yTop: Math.max(pp.h, c.h), yBot: Math.min(pp.l, c.l)});
      }
      // Харами
      if (bd(p) > 0 && bd(p) > bd(c) * 2 &&
          Math.min(c.o,c.c) > Math.min(p.o,p.c) && Math.max(c.o,c.c) < Math.max(p.o,p.c)) {
        events.push({type:'harami', i:i, dir:'neutral', label:'харами', y: c.h});
      }
    }
    return events;
  }

  // ── detectSMC — детерминированный детект структуры рынка ──────────────────
  // Возвращает [{type:'hh'|'lh'|'hl'|'ll'|'bos'|'fvg'|'ob', ...}, ...]
  function detectSMC(bars, lookback) {
    var lb = lookback || 5;
    var events = [];
    var n = bars.length;

    // Свинговые точки (фракталы)
    var swH = [], swL = [];
    for (var i = lb; i < n - lb; i++) {
      var isH = true, isL = true;
      for (var j = i - lb; j <= i + lb; j++) {
        if (j === i) continue;
        if (bars[j].h >= bars[i].h) isH = false;
        if (bars[j].l <= bars[i].l) isL = false;
      }
      if (isH) swH.push({i:i, y:bars[i].h});
      if (isL) swL.push({i:i, y:bars[i].l});
    }

    // Метки HH/LH (на хаях свингов)
    for (var k = 1; k < swH.length; k++) {
      var lbl = swH[k].y > swH[k-1].y ? 'HH' : 'LH';
      events.push({type: lbl.toLowerCase(), i: swH[k].i, y: swH[k].y,
        dir: lbl === 'HH' ? 'bull' : 'bear', label: lbl});
    }
    // Метки HL/LL (на лоях свингов)
    for (var k = 1; k < swL.length; k++) {
      var lbl2 = swL[k].y > swL[k-1].y ? 'HL' : 'LL';
      events.push({type: lbl2.toLowerCase(), i: swL[k].i, y: swL[k].y,
        dir: lbl2 === 'HL' ? 'bull' : 'bear', label: lbl2});
    }

    // BOS: закрытие за последним значимым свингом
    if (swL.length >= 2) {
      var lastL = swL[swL.length - 1];
      for (var i = lastL.i + 1; i < n; i++) {
        if (bars[i].c < lastL.y) {
          events.push({type:'bos', y: lastL.y, dir:'bear', label:'BOS ↓'});
          break;
        }
      }
    }
    if (swH.length >= 2) {
      var lastH = swH[swH.length - 1];
      for (var i = lastH.i + 1; i < n; i++) {
        if (bars[i].c > lastH.y) {
          events.push({type:'bos', y: lastH.y, dir:'bull', label:'BOS ↑'});
          break;
        }
      }
    }

    // FVG: 3-свечной разрыв (показываем только последние 5 для читаемости)
    var fvgCount = 0;
    for (var i = n - 1; i >= 2 && fvgCount < 5; i--) {
      var a = bars[i-2], ci = bars[i];
      if (ci.l > a.h) {
        events.push({type:'fvg', i0:i-2, yTop:ci.l, yBot:a.h, dir:'bull', label:'FVG'});
        fvgCount++;
      } else if (ci.h < a.l) {
        events.push({type:'fvg', i0:i-2, yTop:a.l, yBot:ci.h, dir:'bear', label:'FVG'});
        fvgCount++;
      }
    }

    // OB: последняя противоположная свеча перед импульсом (последние 3)
    var obCount = 0;
    for (var i = n - 1; i >= 2 && obCount < 3; i--) {
      var ci2 = bars[i], pi = bars[i-1];
      if (pi.h === pi.l) continue;
      var imp = Math.abs(ci2.c - ci2.o);
      var prng = pi.h - pi.l;
      if (ci2.c > ci2.o && imp > prng * 1.5 && pi.c < pi.o) {
        events.push({type:'ob', i0:i-1, yTop:pi.h, yBot:pi.l, dir:'bull', label:'OB'});
        obCount++;
      } else if (ci2.c < ci2.o && imp > prng * 1.5 && pi.c > pi.o) {
        events.push({type:'ob', i0:i-1, yTop:pi.h, yBot:pi.l, dir:'bear', label:'OB'});
        obCount++;
      }
    }

    return events;
  }

  // ── chartFullscreenButton — единый FS-компонент (мобайл-оверлей + iOS-поворот) ──
  function chartFullscreenButton(container) {
    if (!document.getElementById('_sbffs')) {
      var s = document.createElement('style'); s.id = '_sbffs';
      s.textContent =
        '.sbf-fs-btn{position:absolute;top:7px;right:7px;z-index:22;width:26px;height:26px;' +
        'border:1px solid rgba(231,223,207,.85);border-radius:5px;' +
        'background:rgba(251,246,239,.9);backdrop-filter:blur(3px);cursor:pointer;' +
        'display:none;align-items:center;justify-content:center;padding:0;' +
        '-webkit-tap-highlight-color:transparent;color:#2B2B33}' +
        '@media(max-width:760px){.sbf-fs-btn{display:flex}}' +
        '.sbf-fs{position:fixed!important;inset:0!important;z-index:1000!important;' +
        'background:var(--bg,#FBF6EF)!important;overflow:hidden!important;border-radius:0!important;' +
        'padding:0!important;display:flex!important;flex-direction:column!important}' +
        '.sbf-fs>*:not(.sbf-fs-btn){flex:1 1 auto!important;min-height:0!important;height:100%!important;width:100%!important}' +
        '@media(max-width:760px) and (orientation:portrait){' +
        '.sbf-fs.sbf-fs-p{transform:rotate(90deg);transform-origin:center center;' +
        'width:100vh!important;height:100vw!important;' +
        'top:calc(50vh - 50vw)!important;left:calc(50vw - 50vh)!important}}';
      document.head.appendChild(s);
    }
    container.style.position = 'relative';
    var btn = document.createElement('button');
    btn.className = 'sbf-fs-btn';
    btn.title = 'На весь экран';
    var ICO_IN  = '<svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M1 4.5V1h3.5M8.5 1H12v3.5M12 8.5V12H8.5M4.5 12H1V8.5"/></svg>';
    var ICO_OUT = '<svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M4.5 1v3.5H1M12 4.5H8.5V1M8.5 12V8.5H12M1 8.5h3.5V12"/></svg>';
    btn.innerHTML = ICO_IN;
    container.appendChild(btn);
    var isFS = false;
    function inPortrait() { return window.innerHeight > window.innerWidth; }
    function enter() {
      isFS = true;
      container.classList.add('sbf-fs');
      if (inPortrait()) container.classList.add('sbf-fs-p');
      btn.innerHTML = ICO_OUT;
      try { container.requestFullscreen && container.requestFullscreen(); } catch(e) {}
      try { screen.orientation && screen.orientation.lock && screen.orientation.lock('landscape').catch(function(){}); } catch(e) {}
      requestAnimationFrame(function(){ window.dispatchEvent(new Event('resize')); });
    }
    function exit() {
      isFS = false;
      container.classList.remove('sbf-fs', 'sbf-fs-p');
      btn.innerHTML = ICO_IN;
      try { document.fullscreenElement && document.exitFullscreen(); } catch(e) {}
      window.dispatchEvent(new Event('resize'));
    }
    btn.addEventListener('click', function() { isFS ? exit() : enter(); });
    document.addEventListener('fullscreenchange', function() { if (!document.fullscreenElement && isFS) exit(); });
    window.addEventListener('orientationchange', function() {
      if (isFS) { inPortrait() ? container.classList.add('sbf-fs-p') : container.classList.remove('sbf-fs-p'); }
    });
    return { enter: enter, exit: exit };
  }

  // ── Экспорт ────────────────────────────────────────────────────────────────
  root.SBFGrafik = {
    ITEMS: ITEMS, CATS: CATS, PALETTE: P,
    renderItem: renderItem, renderEventHistory: renderEventHistory,
    renderPriceChart: renderPriceChart, findItem: findItem,
    setTpMode: setTpMode, get tpMode() { return TPMODE; },
    // live-data
    loadBars: loadBars, calcRSI14: calcRSI14, calcBias: calcBias,
    calcPivots: calcPivots, nearestPivot: nearestPivot, pivotLayers: pivotLayers,
    detectCandles: detectCandles, detectSMC: detectSMC,
    // UI-компоненты
    chartFullscreenButton: chartFullscreenButton
  };
})(typeof window !== 'undefined' ? window : this);
