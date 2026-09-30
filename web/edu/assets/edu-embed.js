/* ============================================================================
   SBF EDU EMBED — мост между уроками (/edu/b/{n}) и движком Графика.
   Добавь в <head> каждого урока ПОСЛЕ grafik-engine.js:
     <script src="/edu/assets/grafik-engine.js"></script>
     <script src="/edu/assets/edu-embed.js"></script>
   Затем в тексте урока:
     • фигура:        <div class="sbf-fig" data-cat="chart" data-key="hns"></div>
     • тех-карточка:  sbfTechCard({...}) → вставить HTML, или <div class="sbf-tcard" data-…>
     • ссылка в Граф"  onclick="sbfOpenGrafik('ind','rsi')"
   Сам инжектит нужный CSS (стиль «Технических карточек» с lp + анимация движка).
   ========================================================================== */
(function () {
  // i18n: window.sbfI18n не кэшируется — проверяем заново при каждом вызове.
  function t(key, fallback) {
    var i = window.sbfI18n;
    return i ? i.t(key, fallback) : (fallback || key);
  }

  // ---- 1. инжект CSS (tcard с lp + анимация движка + обёртка фигуры) ----
  var CSS = `
  :root{--sbf-up:#2C784E;--sbf-down:#C0392B;--sbf-gold:#C9A227;--sbf-gold-text:#866A19;--sbf-line:#E7DFCF;--sbf-ink:#2B2B33;--sbf-muted:#716A5A;--sbf-paper:#FFFFFF;--sbf-cream:#FBF6EF;}
  .sbf-fig{background:var(--sbf-paper);border:1px solid var(--sbf-line);border-radius:12px;padding:10px;margin:20px 0;cursor:pointer}
  .sbf-fig .sbf-fig-schema-tag{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--sbf-gold-text);border:1px solid var(--sbf-gold);border-radius:3px;display:inline-block;padding:2px 6px;margin:2px 4px 8px}
  .sbf-fig .sbf-cap{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--sbf-muted);margin:8px 4px 2px}
  .sbf-fig svg{display:block;width:100%;height:auto}
  .sbf-figlink{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--sbf-gold-text);cursor:pointer;display:inline-block;margin-top:6px}
  /* «Технические карточки» — стиль с lp.sbfconsult.com */
  .sbf-tcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;margin:20px 0}
  .sbf-tcard{background:var(--sbf-cream);border:1px solid var(--sbf-line);border-radius:10px;padding:14px 16px}
  .sbf-tcard .hd{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}
  .sbf-tcard .sym{font-family:'JetBrains Mono',monospace;font-weight:700;font-size:13px;color:var(--sbf-ink)}
  .sbf-tcard .bias{font-size:10px;padding:2px 8px;border-radius:5px;font-family:'JetBrains Mono',monospace;font-weight:700}
  .sbf-tcard .bias.bull{color:var(--sbf-up);border:1px solid var(--sbf-up);background:rgba(46,139,111,.08)}
  .sbf-tcard .bias.bear{color:var(--sbf-down);border:1px solid var(--sbf-down);background:rgba(192,80,77,.08)}
  .sbf-tcard .bias.flat{color:var(--sbf-muted);border:1px solid var(--sbf-line)}
  .sbf-tcard .lv{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--sbf-muted);display:flex;justify-content:space-between;padding:2px 0}
  .sbf-tcard .lv b{color:var(--sbf-ink);font-weight:600}
  .sbf-tcard .note{font-size:12px;color:var(--sbf-muted);margin-top:8px;line-height:1.5}
  /* анимация движка (без неё свечи/линии не проявятся) */
  @keyframes sbfcn{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
  .cn{opacity:0;animation:sbfcn .26s ease forwards}
  @keyframes sbfdr{to{stroke-dashoffset:0}}
  .ln{animation:sbfdr .55s ease forwards}
  @keyframes sbfzf{to{opacity:var(--zop,0.12)}}
  .zn{opacity:0;animation:sbfzf .4s ease forwards}`;
  var st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);

  // ---- 2. монтирование фигур из движка ----
  // SPEC_charts_and_interactivity_standard.md §2.1 (29.07 re-audit): these
  // figures are seeded, deterministic, illustrative shapes -- "what a hammer
  // looks like", not a real historical event -- and were never labeled as
  // such, so a reader has no way to tell them apart from a real chart. Per
  // §2.1 a diagram used to explain mechanics (not show data) is legitimate,
  // but must say so explicitly. Scoped to THIS file deliberately: it's the
  // only thing that mounts .sbf-fig blocks (course chapters + calendar.html);
  // grafik-engine.js's own render core is untouched here, since chart.html
  // and index.html's own "Технический" pattern-school section calls the
  // exact same ITEMS/renderItem/build() directly for a separate, real
  // feature that would need its own dedicated verification pass.
  function mountFigures(root) {
    (root || document).querySelectorAll('.sbf-fig[data-cat][data-key]').forEach(function (el) {
      if (el._sbf) return;
      var G = window.SBFGrafik;
      var it = G && G.findItem(el.dataset.cat, el.dataset.key);
      if (!it) { el.innerHTML = '<div style="font:12px monospace;color:#a99">' + t('eduindex.embed.figure_not_found', 'фигура не найдена: ') + el.dataset.cat + '/' + el.dataset.key + '</div>'; return; }
      var cap = el.dataset.caption || (it.n + ' · ' + t('eduindex.embed.how_it_forms', 'как формируется'));
      // Prefer the server-rendered label (data-schema-label, set by serve.py
      // for course chapters) over the client-side t() fallback -- the
      // client i18n dict loads async and is typically still empty at this
      // point (see comment above), so on pages without the server attribute
      // (e.g. calendar.html, which mounts .sbf-fig without serve.py's
      // _FIG_MAP wiring) this will render in Russian until sbfI18n.ready
      // resolves and the figure is re-mounted.
      var schemaLabel = el.dataset.schemaLabel || t('eduindex.embed.schema_label', 'СХЕМА · ИЛЛЮСТРАЦИЯ, НЕ РЕАЛЬНЫЕ ДАННЫЕ');
      el.innerHTML = '<div class="sbf-fig-schema-tag">' + schemaLabel + '</div><div class="sbf-fig-chart"></div><div class="sbf-cap">' + cap + '</div>';
      function render() { el.querySelector('.sbf-fig-chart').innerHTML = it.build(); метка(); }
      /* 🔴 Метка обязана следовать за тем, что показано. Индикаторные фигуры
         (cat='ind') с приходом fig_series.json считаются по РЕАЛЬНОМУ
         отрезку рынка — называть их «не реальные данные» после этого
         неверно ровно так же, как называть схему настоящей. Остальные
         семейства (candle/chart/smc) по-прежнему рисуются генератором, и
         метка у них остаётся. */
      function метка() {
        var шапка = el.querySelector('.sbf-fig-schema-tag');
        if (!шапка) return;
        var ряд = window.SBFFigSeries && window.SBFFigSeries();
        var пример = window.SBFFigExample && window.SBFFigExample(el.dataset.key);
        if ((el.dataset.cat === 'candle' || el.dataset.cat === 'chart') && пример) {
          var д = new Date(пример['пример']['ts'] * 1000);
          шапка.textContent = пример['пример']['имя'] + ' · ' + пример['пример']['tf'] + ' · ' +
            ('0'+д.getUTCDate()).slice(-2)+'.'+('0'+(д.getUTCMonth()+1)).slice(-2)+'.'+д.getUTCFullYear();
          шапка.classList.add('sbf-fig-real-tag');
        } else if (el.dataset.cat === 'smc' && ряд && ряд['поиск'] &&
                   window.SBFFigSMC && window.SBFFigSMC(
                     el.dataset.key === 'structure' ? 'hh' : el.dataset.key)) {
          шапка.textContent = ряд['поиск']['показ'] + ' · ' + ряд['поиск']['tf'] +
                              ' · ' + ряд['поиск']['от'] + '…' + ряд['поиск']['до'];
          шапка.classList.add('sbf-fig-real-tag');
        } else if (el.dataset.cat === 'ind' && ряд) {
          шапка.textContent = ряд['показ'] + ' · ' + ряд['tf'] + ' · ' +
                              ряд['от'] + '…' + ряд['до'];
          шапка.classList.add('sbf-fig-real-tag');
        } else {
          шапка.textContent = schemaLabel;
          шапка.classList.remove('sbf-fig-real-tag');
        }
      }
      render(); el._sbf = true;
      // Ряд приходит по сети уже после первой отрисовки — перерисовываемся.
      window.addEventListener('sbf-fig-series', render);
      // 🔴 Схема — настоящее управление: по нажатию она проигрывается заново.
      // Но была обычным <div> с курсором-пальцем: мышью работает, с
      // клавиатуры недоступна, диктор её управлением не называет. Замер нашёл
      // 17 таких схем по главам — все из этой одной строки.
      //
      // role + tabindex + обработка Enter/Space — минимум, который делает
      // элемент управлением по-настоящему. Тег не меняем: внутри разметка
      // схемы, а <button> с произвольным содержимым ведёт себя по-разному в
      // разных браузерах.
      var подпись = t('eduindex.embed.click_to_replay', 'нажми, чтобы проиграть заново');
      el.title = подпись;
      el.setAttribute('role', 'button');
      el.setAttribute('tabindex', '0');
      el.setAttribute('aria-label', cap + ' — ' + подпись);
      el.addEventListener('click', render);
      el.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
          ev.preventDefault();
          render();
        }
      });
    });
  }

  // ---- 3. построитель «технической карточки» (стиль lp) ----
  // sbfTechCard({sym:'EURUSD', bias:'bull'|'bear'|'flat', levels:[['PP','1.0850'],['R1','1.0900']], note:'…'})
  window.sbfTechCard = function (d) {
    var bc = d.bias === 'bull' ? 'bull' : d.bias === 'bear' ? 'bear' : 'flat';
    var bl = d.bias === 'bull' ? t('eduindex.embed.bias_bull', 'бычий') : d.bias === 'bear' ? t('eduindex.embed.bias_bear', 'медвежий') : t('eduindex.embed.bias_flat', 'нейтр.');
    var lvs = (d.levels || []).map(function (l) { return '<div class="lv"><span>' + l[0] + '</span><b>' + l[1] + '</b></div>'; }).join('');
    return '<div class="sbf-tcard"><div class="hd"><span class="sym">' + (d.sym || '') + '</span><span class="bias ' + bc + '">' + bl + '</span></div>' + lvs + (d.note ? '<div class="note">' + d.note + '</div>' : '') + '</div>';
  };

  // ---- 4. открыть паттерн в «Технический» (урок в iframe → родитель web-app) ----
  window.sbfOpenGrafik = function (cat, key) {
    if (window.parent !== window) {
      window.parent.postMessage({ type: 'sbf-grafik', cat: cat, key: key }, '*');
    } else {
      window.open('/#tech/' + cat + '/' + key, '_blank');
    }
  };

  // ---- 5. автозапуск ----
  function boot() { mountFigures(document); }
  if (document.readyState !== 'loading') boot(); else document.addEventListener('DOMContentLoaded', boot);
  window.sbfMountFigures = mountFigures; // на случай динамической подгрузки контента урока
})();
