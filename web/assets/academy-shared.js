/*
 * academy-shared.js — общий "хром" книги SBF Academy (SPEC_academy_chapter3_
 * integration.md §5/§7). Раньше C/Mono/Chip/Rule/MSG_TR/AskAnalystPopup/
 * AskAnalystBtn/getChUrl/GlossWord/тест-на-воспроизведение существовали в
 * ТРЁХ независимых копиях (edu_book_1/2/3.html) — уже разошедшихся на
 * практике (в Главе 3 своя, более простая версия попапа аналитика).
 *
 * ВАЖНО: подключается обычным <script src="/assets/academy-shared.js">,
 * БЕЗ type="text/babel" — компиляция глав (_precompile_all() в serve.py)
 * обрабатывает только инлайновый <script type="text/babel"> каждой главы;
 * babel.min.js вообще вырезается из уже скомпилированных страниц. Поэтому
 * здесь пишем ТОЛЬКО React.createElement(...), никакого JSX.
 *
 * Инъекция — в <head>, ДО тегов react/react-dom/babel в <body> (см.
 * _build_edu_page() в serve.py). Значит верхний уровень этого файла НЕ
 * должен обращаться к window.React в момент выполнения — только внутри
 * тел функций, которые реально вызываются намного позже (когда React уже
 * точно загружен). INITIAL_LANG — const внутри инлайн-скрипта каждой
 * главы, из отдельного <script> тега не виден — поэтому getChUrl/
 * AskAnalystBtn принимают lang явным аргументом/пропом, а не читают
 * глобальную переменную.
 */
(function () {
  var C = {
    gold:"#c9973a", goldDark:"#b8832a", goldLight:"#f4d49f", goldPale:"#f7f0e3",
    black:"#18181a", ink:"#18181a", inkMid:"#555555",
    inkSoft:"rgba(24,24,26,0.58)", inkFaint:"rgba(24,24,26,0.28)",
    white:"#ffffff", surface:"#faf8f5", surfaceMid:"#f0ebe0",
    border:"rgba(24,24,26,0.1)", borderGold:"rgba(201,151,58,0.25)",
    dark:"#18181a",
    green:"#2d7a4f", greenPale:"#eaf5ee", red:"#c0392b", redPale:"#fdecea",
    blue:"#2563eb", bluePale:"#eff6ff", orange:"#d97706",
    // Яркие "биржевые" (TradingView-подобные) цвета для графиков/лент сделок
    // -- Глава 4 -- намеренно отдельные от green/red выше: те используются
    // как приглушённый индикатор "хорошо/плохо" в обычном UI, эти -- для
    // визуализации цены/свечей, семантически разные вещи с похожими именами.
    chartGreen:"#089981", chartRed:"#f23645", chartBg:"#131722",
  };

  // Сетка вариантов ответа QuizBlock -- SPEC_ch2_debug_and_chart_engine.md §1.5
  // ("сетка 2×2 кнопками... на мобильном 1 колонка"), применено ко всем главам,
  // не только к главе 2. Инлайновые React-стили не умеют в media query, а
  // .g2/.g3 определены не во всех edu_book_N.html (нет в 1-3) -- поэтому стиль
  // самодостаточный, инжектится этим файлом один раз, не зависит от хост-страницы.
  if (typeof document !== "undefined" && !document.getElementById("academy-quiz-optgrid-style")) {
    var _qgStyle = document.createElement("style");
    _qgStyle.id = "academy-quiz-optgrid-style";
    _qgStyle.textContent =
      ".quiz-optgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}" +
      "@media(max-width:640px){.quiz-optgrid{grid-template-columns:1fr}}";
    document.head.appendChild(_qgStyle);
  }

  function Mono(props) {
    var children = props.children, size = props.size == null ? 13 : props.size,
        color = props.color || C.inkSoft, spacing = props.spacing == null ? 3 : props.spacing,
        style = props.style || {}, className = props.className || "";
    return React.createElement('span', {className: className, style: Object.assign(
      {fontFamily:"'Courier New',monospace", fontSize:size, letterSpacing:spacing, color:color}, style
    )}, children);
  }

  function Chip(props) {
    var color = props.color || C.gold;
    return React.createElement('span', {style:{
      fontFamily:"'Courier New',monospace", fontSize:11, letterSpacing:3, color:color,
      border:"1px solid " + color, padding:"4px 11px", display:"inline-block", textTransform:"uppercase"
    }}, props.children);
  }

  function Rule(props) {
    var w = props.w || "50%", my = props.my == null ? 32 : props.my;
    return React.createElement('div', {style:{
      height:1, background:"linear-gradient(90deg,transparent," + C.gold + ",transparent)",
      width:w, margin: my + "px auto", opacity:0.4
    }});
  }

  // ── Глоссарий-тултип. glossary передаётся пропом (словарь термина —
  // контент главы, не механизм) — GLOSSARY каждой главы остаётся локальным.
  function GlossWord(props) {
    var glossary = props.glossary, word = props.word, lang = props.lang, children = props.children;
    var open = React.useState(false), isOpen = open[0], setOpen = open[1];
    var d = glossary && glossary[lang] && glossary[lang][word];
    if (!d) {
      return React.createElement('span', {style:{color:C.gold, fontWeight:600, borderBottom:"1px dashed " + C.gold, cursor:"pointer"}}, children);
    }
    return React.createElement('span', {style:{position:"relative", display:"inline"}},
      React.createElement('span', {
        onClick: function(e){ e.stopPropagation(); setOpen(function(o){ return !o; }); },
        style:{color:C.gold, borderBottom:"1px dashed " + C.gold, cursor:"pointer", fontWeight:600}
      }, children),
      isOpen && React.createElement(React.Fragment, {},
        React.createElement('div', {
          onClick: function(e){ e.stopPropagation(); setOpen(false); },
          style:{position:"fixed", inset:0, zIndex:199}
        }),
        React.createElement('span', {
          onClick: function(e){ e.stopPropagation(); },
          style:{position:"absolute", bottom:"130%", left:"50%", transform:"translateX(-50%)",
                 width:360, background:C.white, border:"1px solid " + C.border,
                 boxShadow:"0 10px 40px rgba(0,0,0,0.15)", padding:"20px 23px", zIndex:200, display:"block"}
        },
          React.createElement(Mono, {size:13, color:C.gold, spacing:2, style:{display:"block", marginBottom:8}}, word.toUpperCase()),
          React.createElement('span', {style:{display:"block", fontSize:16, color:C.ink, marginBottom:10, lineHeight:1.6, fontWeight:600}}, d.s),
          React.createElement('span', {style:{display:"block", fontSize:15, color:C.inkSoft, marginBottom:10, lineHeight:1.5, fontStyle:"italic"}}, d.a),
          React.createElement('span', {style:{display:"block", fontSize:15, color:C.gold, lineHeight:1.5}}, "→ " + d.e),
          React.createElement('span', {
            onClick: function(e){ e.stopPropagation(); setOpen(false); },
            style:{position:"absolute", top:10, right:12, cursor:"pointer", color:C.inkFaint, fontSize:20, lineHeight:1}
          }, "×")
        )
      )
    );
  }

  // Оборачивает КАЖДОЕ из pairs=[{term,word}] (term встречается в text не
  // больше 1 раза) ссылкой на глоссарий -- нужен, когда термин нужно
  // вставить в готовую строку из STRINGS (не JSX-фрагмент), напр. описание
  // центробанка или вводную строку перед интерактивом (см. Главы 2/3).
  function withGlossTerms(text, pairs, glossary, lang) {
    var esc = function(s){ return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); };
    var re = new RegExp('(' + pairs.map(function(p){ return esc(p.term); }).join('|') + ')');
    return text.split(re).map(function(part, i){
      var pair = pairs.filter(function(p){ return p.term === part; })[0];
      return pair ? React.createElement(GlossWord, {key:i, glossary:glossary, word:pair.word, lang:lang}, part) : part;
    });
  }

  // ── Попап "Спросить аналитика" — канонизировано на версию Глав 1/2
  // (имитация переписки, инлайн-SVG, rel=noreferrer, hover) -- Глава 3
  // получает апгрейд до неё же (её собственная версия была проще).
  var MSG_TR = {
    ru: { tag:"НАПИСАТЬ НАМ", title:"Предпочитаете мессенджер?",
          sub:"Напишите в Telegram или WhatsApp — сообщение уже готово, просто нажмите Отправить.",
          tgInc:"Привет 👋 Чем можем помочь? Оставьте заявку и мы пришлём материалы.",
          waInc:"Добрый день! Напишите что вас интересует <img class='mi-icon' style='vertical-align:middle' src='/assets/icons/icon-bar-chart.png' alt='' width='20' height='20' />",
          btnTg:"ОТКРЫТЬ TELEGRAM", btnWa:"ОТКРЫТЬ WHATSAPP", you:"Вы", online:"онлайн", justNow:"только что" },
    en: { tag:"CONTACT US", title:"Prefer a messenger?",
          sub:"Write us on Telegram or WhatsApp — the message is pre-filled, just click Send.",
          tgInc:"Hi 👋 How can we help? Leave a request and we'll send the materials.",
          waInc:"Good day! Tell us what you're interested in <img class='mi-icon' style='vertical-align:middle' src='/assets/icons/icon-bar-chart.png' alt='' width='20' height='20' />",
          btnTg:"OPEN TELEGRAM", btnWa:"OPEN WHATSAPP", you:"You", online:"online", justNow:"just now" },
    ro: { tag:"CONTACTAȚI-NE", title:"Preferați un messenger?",
          sub:"Scrieți pe Telegram sau WhatsApp — mesajul este pregătit, doar apăsați Trimite.",
          tgInc:"Bună 👋 Cu ce vă putem ajuta? Lăsați o cerere și vă trimitem materialele.",
          waInc:"Bună ziua! Spuneți-ne ce vă interesează <img class='mi-icon' style='vertical-align:middle' src='/assets/icons/icon-bar-chart.png' alt='' width='20' height='20' />",
          btnTg:"DESCHIDE TELEGRAM", btnWa:"DESCHIDE WHATSAPP", you:"Dvs.", online:"online", justNow:"chiar acum" },
  };

  function AskAnalystPopup(props) {
    var chapterNum = props.chapterNum, lang = props.lang, onClose = props.onClose;
    var tr = MSG_TR[lang] || MSG_TR.ru;
    var prefillRu = "Здравствуйте, есть вопрос по главе " + chapterNum;
    var prefillEn = "Hello, I have a question about chapter " + chapterNum;
    var prefillRo = "Bună ziua, am o întrebare despre capitolul " + chapterNum;
    var msgText = lang === 'ru' ? prefillRu : lang === 'en' ? prefillEn : prefillRo;
    var tgLink = "https://t.me/SBF_Support?text=" + encodeURIComponent(msgText);
    var waLink = "https://api.whatsapp.com/send/?phone=37369005200&text=" + encodeURIComponent(msgText) + "&type=phone_number&app_absent=0";
    var e = React.createElement;

    return e('div', {style:{position:"fixed", inset:0, zIndex:500, display:"flex", alignItems:"center", justifyContent:"center", padding:20, overflowY:"auto"}, onClick:onClose},
      e('div', {style:{position:"fixed", inset:0, background:"rgba(250,248,245,0.98)"}}),
      e('div', {onClick:function(ev){ ev.stopPropagation(); }, style:{position:"relative", width:"100%", maxWidth:900, zIndex:1, margin:"auto", padding:"40px 0"}},
        e('button', {onClick:onClose, style:{position:"absolute", top:0, right:10, background:"none", border:"none", fontSize:35, cursor:"pointer", color:C.inkFaint, lineHeight:1}}, "×"),
        e('div', {style:{marginBottom:40, padding:"0 10px"}},
          e(Mono, {size:13, color:C.gold, spacing:3, style:{display:"block", marginBottom:15}}, "— " + tr.tag),
          e('h2', {style:{fontSize:"clamp(30px,5vw,42px)", fontWeight:700, color:C.black, marginBottom:15, fontFamily:"'DM Serif Display',serif"}}, tr.title),
          e('p', {style:{fontSize:18, color:C.inkMid, lineHeight:1.6}}, tr.sub)
        ),
        e('div', {className:"messenger-grid"},
          e('div', {style:{background:"#ffffff", border:"1px solid #e0e0e0", borderRadius:12, padding:"30px 25px", display:"flex", flexDirection:"column", boxShadow:"0 10px 30px rgba(0,0,0,0.03)"}},
            e('div', {style:{display:"flex", alignItems:"center", gap:15, marginBottom:30}},
              e('div', {style:{width:50, height:50, borderRadius:"50%", background:"#e1f3fb", display:"flex", alignItems:"center", justifyContent:"center"}},
                e('svg', {width:24, height:24, viewBox:"0 0 24 24", fill:"none", xmlns:"http://www.w3.org/2000/svg"},
                  e('path', {d:"M20.665 3.717l-17.73 6.837c-1.21.486-1.203 1.161-.222 1.462l4.552 1.42 10.532-6.645c.498-.303.953-.14.579.192l-8.533 7.701h-.002l.002.002-.314 4.692c.46 0 .663-.211.921-.46l2.211-2.15 4.599 3.397c.848.467 1.457.227 1.668-.785l3.019-14.228c.309-1.239-.473-1.8-1.282-1.435z", fill:"#0088cc"})
                )
              ),
              e('div', {},
                e('div', {style:{fontSize:18, fontWeight:700, color:C.black}}, "SBF Support"),
                e('div', {style:{fontSize:14, color:C.inkFaint}}, "Telegram · " + tr.online)
              )
            ),
            e('div', {style:{background:"#f7f7f7", padding:"15px 20px", borderRadius:"12px 12px 12px 0", marginBottom:20, alignSelf:"flex-start", maxWidth:"90%"}},
              e('div', {style:{fontSize:16, color:C.black, lineHeight:1.5, marginBottom:8}}, tr.tgInc),
              e('div', {style:{fontSize:11, color:C.inkFaint}}, "SBF Support · " + tr.justNow)
            ),
            e('div', {style:{background:"#0088cc", padding:"15px 20px", borderRadius:"12px 12px 0 12px", marginBottom:30, alignSelf:"flex-end", maxWidth:"90%"}},
              e('div', {style:{fontSize:16, color:"#ffffff", lineHeight:1.5, marginBottom:8}}, msgText),
              e('div', {style:{fontSize:11, color:"rgba(255,255,255,0.7)", textAlign:"right"}}, tr.you + " · ✓✓")
            ),
            e('a', {href:tgLink, target:"_blank", rel:"noreferrer",
                    style:{marginTop:"auto", display:"block", background:"#0088cc", color:"#fff", textAlign:"center", padding:"18px 20px", borderRadius:8, fontSize:15, letterSpacing:1.5, fontFamily:"monospace", fontWeight:700, textDecoration:"none", transition:"opacity 0.2s"},
                    onMouseEnter:function(ev){ ev.currentTarget.style.opacity=0.85; }, onMouseLeave:function(ev){ ev.currentTarget.style.opacity=1; }},
              e('span', {style:{display:"inline-block", width:12, height:12, borderRadius:"50%", background:"#fff", marginRight:10, verticalAlign:"middle"}}),
              tr.btnTg
            )
          ),
          e('div', {style:{background:"#ffffff", border:"1px solid #e0e0e0", borderRadius:12, padding:"30px 25px", display:"flex", flexDirection:"column", boxShadow:"0 10px 30px rgba(0,0,0,0.03)"}},
            e('div', {style:{display:"flex", alignItems:"center", gap:15, marginBottom:30}},
              e('div', {style:{width:50, height:50, borderRadius:"50%", background:"#e8f5ed", display:"flex", alignItems:"center", justifyContent:"center"}},
                e('svg', {width:24, height:24, viewBox:"0 0 24 24", fill:"none", xmlns:"http://www.w3.org/2000/svg"},
                  e('path', {d:"M20.52 3.449C18.24 1.245 15.24 0 12.042 0 5.463 0 .104 5.334.101 11.893c-.001 2.093.546 4.14 1.587 5.945L.041 24l6.335-1.652c1.745.943 3.71 1.444 5.71 1.445h.005c6.577 0 11.938-5.336 11.94-11.897.002-3.174-1.229-6.158-3.511-8.447zm-8.473 17.51h-.004c-1.774-.001-3.513-.475-5.038-1.373l-.361-.213-3.744.977.994-3.633-.235-.373c-1.01-1.603-1.543-3.453-1.542-5.36.002-5.541 4.536-10.057 10.106-10.057 2.697.001 5.234 1.048 7.137 2.943 1.905 1.897 2.955 4.418 2.954 7.108-.002 5.542-4.538 10.058-10.108 10.058zm5.552-7.532c-.304-.152-1.799-.884-2.078-.985-.279-.101-.482-.152-.685.152-.203.303-.787.985-.964 1.187-.178.203-.356.228-.66.076-1.554-.775-2.73-1.564-3.76-3.32-.102-.178-.011-.274.141-.426.136-.136.304-.354.456-.532.152-.177.203-.303.304-.506.102-.203.051-.38-.025-.532-.076-.152-.685-1.643-.938-2.251-.247-.591-.497-.512-.685-.521-.177-.008-.38-.01-.582-.01-.203 0-.532.076-.811.38-.279.304-1.065 1.036-1.065 2.527s1.09 2.932 1.242 3.134c.152.202 2.146 3.262 5.197 4.577.726.313 1.292.5 1.734.64.729.231 1.393.198 1.916.12.585-.088 1.799-.733 2.053-1.442.253-.708.253-1.314.177-1.442-.076-.126-.279-.202-.583-.354z", fill:"#25d366"})
                )
              ),
              e('div', {},
                e('div', {style:{fontSize:18, fontWeight:700, color:C.black}}, "SBF Company"),
                e('div', {style:{fontSize:14, color:C.inkFaint}}, "WhatsApp · " + tr.online)
              )
            ),
            e('div', {style:{background:"#f7f7f7", padding:"15px 20px", borderRadius:"12px 12px 12px 0", marginBottom:20, alignSelf:"flex-start", maxWidth:"90%"}},
              e('div', {style:{fontSize:16, color:C.black, lineHeight:1.5, marginBottom:8}, dangerouslySetInnerHTML:{__html: tr.waInc}}),
              e('div', {style:{fontSize:11, color:C.inkFaint}}, "SBF · " + tr.justNow)
            ),
            e('div', {style:{background:"#25d366", padding:"15px 20px", borderRadius:"12px 12px 0 12px", marginBottom:30, alignSelf:"flex-end", maxWidth:"90%"}},
              e('div', {style:{fontSize:16, color:"#ffffff", lineHeight:1.5, marginBottom:8}}, msgText),
              e('div', {style:{fontSize:11, color:"rgba(255,255,255,0.8)", textAlign:"right"}}, tr.you + " · ✓✓")
            ),
            e('a', {href:waLink, target:"_blank", rel:"noreferrer",
                    style:{marginTop:"auto", display:"block", background:"#25d366", color:"#fff", textAlign:"center", padding:"18px 20px", borderRadius:8, fontSize:15, letterSpacing:1.5, fontFamily:"monospace", fontWeight:700, textDecoration:"none", transition:"opacity 0.2s"},
                    onMouseEnter:function(ev){ ev.currentTarget.style.opacity=0.85; }, onMouseLeave:function(ev){ ev.currentTarget.style.opacity=1; }},
              e('span', {style:{display:"inline-block", marginRight:10, verticalAlign:"middle"}},
                e('img', {className:"mi-icon", style:{verticalAlign:"middle"}, src:"/assets/icons/icon-quote.png", alt:"", width:20, height:20})
              ),
              tr.btnWa
            )
          )
        )
      )
    );
  }

  function AskAnalystBtn(props) {
    var tr = props.tr, chapterNum = props.chapterNum, lang = props.lang;
    var s = React.useState(false), open = s[0], setOpen = s[1];
    return React.createElement('span', {},
      React.createElement('span', {
        onClick: function(){ setOpen(true); },
        style:{fontSize:15, color:C.inkSoft, fontFamily:"monospace", letterSpacing:1, borderBottom:"1px solid " + C.border, paddingBottom:2, cursor:"pointer", display:"inline-block"}
      }, tr.askAnalyst),
      open && React.createElement(AskAnalystPopup, {chapterNum:chapterNum, lang:lang, onClose:function(){ setOpen(false); }})
    );
  }

  // ── getChUrl -- lang передаётся явно (INITIAL_LANG главы не виден
  // из этого отдельно загруженного файла).
  function getChUrl(ch, lang) {
    var p = new URLSearchParams(window.location.search).get('path') || 'explorer';
    var base = lang === 'ru' ? '/edu/b' : ('/edu/' + lang + '/b');
    return ch === 'start' ? (base + '?path=' + p) : (base + '/' + ch + '?path=' + p);
  }

  // ── Тест на воспроизведение (параметризованный: questions/levelId/lang/
  // copy). Паттерн подтверждён дважды (Главы 1 и 2) -- quizIdx/quizAnswers/
  // quizSelected, БЕЗ медали (тот паттерн -- из мёртвого edu_book_cover.html,
  // в реальной книге никогда не существовал).
  function QuizBlock(props) {
    var questions = props.questions, levelId = props.levelId, lang = props.lang, copy = props.copy;
    var onProgress = props.onProgress; // необязательный (answered, total) -- напр. для sticky-прогресс-бара главы
    var s1 = React.useState(0), quizIdx = s1[0], setQuizIdx = s1[1];
    var s2 = React.useState({}), quizAnswers = s2[0], setQuizAnswers = s2[1];
    var s3 = React.useState(null), quizSelected = s3[0], setQuizSelected = s3[1];
    var e = React.createElement;

    function postQuizAttempt(question_id, correct) {
      var doFetch = (window.sbfAuth && window.sbfAuth.isLoggedIn && window.sbfAuth.isLoggedIn())
        ? window.sbfAuth.fetch : fetch;
      doFetch('/api/academy/quiz-attempt', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({level_id:levelId, question_id:question_id, correct:correct}),
      }).catch(function(){});
    }

    function answerQuiz(optIdx) {
      if (quizSelected !== null) return;
      var q = questions[quizIdx];
      var correct = !!q.options[optIdx].correct;
      setQuizSelected(optIdx);
      setQuizAnswers(function(a){ var n = Object.assign({}, a); n[q.id] = correct; return n; });
      if (onProgress) onProgress(Object.keys(quizAnswers).length + 1, questions.length);
      postQuizAttempt(q.id, correct);
    }

    function nextQuiz() {
      setQuizSelected(null);
      setQuizIdx(function(i){ return i + 1; });
    }

    var header = [
      e(Mono, {key:"k", size:11, color:C.gold, spacing:4, style:{display:"block", textAlign:"center", marginBottom:12}}, copy.kicker),
      e('h3', {key:"t", style:{fontFamily:"'DM Serif Display',serif", fontSize:26, color:C.black, fontWeight:400, textAlign:"center", marginBottom:28}}, copy.title),
    ];

    if (quizIdx < questions.length) {
      var q = questions[quizIdx];
      return e('div', {style:{marginBottom:60}}, header,
        e('div', {style:{border:"1px solid " + C.border, padding:"30px 5vw"}},
          e('div', {style:{fontFamily:"monospace", fontSize:12, color:C.inkFaint, marginBottom:14}}, (quizIdx+1) + " / " + questions.length),
          e('p', {style:{fontSize:20, fontWeight:700, color:C.black, marginBottom:22}}, q.prompt),
          e('div', {className:"quiz-optgrid"},
            q.options.map(function(opt, i){
              var showState = quizSelected !== null;
              var isSelected = quizSelected === i;
              var bg = showState ? (opt.correct ? C.goldPale : (isSelected ? C.redPale : C.white)) : C.white;
              var bd = showState ? (opt.correct ? C.gold : (isSelected ? C.red : C.border)) : C.border;
              return e('div', {key:i, onClick:function(){ answerQuiz(i); },
                       style:{padding:"14px 18px", border:"1px solid " + bd, background:bg, cursor:showState?"default":"pointer", transition:"all 0.2s", display:"flex", alignItems:"center", minHeight:24}},
                e('span', {style:{fontSize:16, color:C.inkMid, textAlign:"left"}}, opt.text)
              );
            })
          ),
          quizSelected !== null && e('div', {style:{marginTop:18, padding:"14px 18px", background:q.options[quizSelected].correct?C.goldPale:C.redPale}},
            e('p', {style:{margin:0, fontSize:15, lineHeight:1.6, color:C.inkMid}}, q.options[quizSelected].correct ? q.feedbackCorrect : q.feedbackWrong)
          ),
          quizSelected !== null && e('button', {
            onClick: nextQuiz,
            style:{background:C.black, color:C.white, border:"none", padding:"12px 28px", cursor:"pointer", fontFamily:"monospace", fontSize:13, letterSpacing:2, fontWeight:700, marginTop:18},
            onMouseEnter:function(ev){ ev.target.style.background=C.gold; },
            onMouseLeave:function(ev){ ev.target.style.background=C.black; }
          }, copy.next)
        )
      );
    }

    var missed = questions.filter(function(q){ return quizAnswers[q.id] === false; })[0];
    var correctCount = Object.keys(quizAnswers).filter(function(k){ return quizAnswers[k]; }).length;
    var allCorrect = Object.keys(quizAnswers).length > 0 && Object.keys(quizAnswers).every(function(k){ return quizAnswers[k]; });
    return e('div', {style:{marginBottom:60}}, header,
      e('div', {style:{border:"1px solid " + C.gold, background:C.goldPale, padding:"30px 5vw", textAlign:"center"}},
        e('p', {style:{fontSize:22, fontWeight:700, color:C.black, marginBottom:8}}, correctCount + " / " + questions.length),
        e('p', {style:{fontSize:15, color:C.inkMid, marginBottom: allCorrect ? 0 : 16}}, allCorrect ? copy.stuckAll : copy.stuckSome),
        missed ? e('a', {href:"#" + missed.section, style:{color:"#a8851f", fontFamily:"monospace", fontSize:13}}, copy.backToSection) : null
      )
    );
  }

  // ── Матрица влияния/силы — общий компонент глав 2 и 6 (SPEC_ch2_debug_and_
  // chart_engine.md §2.2: "тот же компонент, что «матрица силы» в спеке главы
  // 6 -- одинаковая логика, одинаковый вид, один код"). Ждёт УЖЕ ATR/дневной-
  // диапазон-нормированные значения в cell.norm (нормировку каждая глава
  // считает своим build-скриптом на своих данных, здесь только отрисовка):
  // rows=[{key,label,cells:{SYM:{norm,n,raw?,rawUnit?,tooltip?}}}],
  // columns=[{key,label}], minCases=число, copy={rowHead,naLabel,lowSampleLegend}.
  // Малая выборка и "нет данных" -- визуально (приглушение+штриховка), а не
  // повторным текстом в каждой клетке (§2.2, "восемь повторов -> одна строка").
  function ImpactMatrix(props) {
    var rows = props.rows, columns = props.columns, minCases = props.minCases, copy = props.copy;
    var e = React.createElement;
    var hatch = "repeating-linear-gradient(45deg, rgba(24,24,26,0.055), rgba(24,24,26,0.055) 4px, transparent 4px, transparent 9px)";

    var sorted = rows.slice().sort(function (a, b) {
      var strength = function (row) {
        return columns.reduce(function (m, c) {
          var cell = row.cells[c.key];
          return (cell && cell.norm != null) ? Math.max(m, cell.norm) : m;
        }, -1);
      };
      return strength(b) - strength(a);
    });

    function cellBody(cell) {
      if (!cell || cell.n === 0 || cell.norm == null) {
        return e('div', { title: (cell && cell.tooltip) || undefined },
          e('div', { style: { fontFamily: "monospace", fontWeight: 700, color: C.inkFaint } }, "—"),
          e('div', { style: { fontSize: 10, color: C.inkFaint, fontFamily: "monospace" } }, copy.naLabel)
        );
      }
      var small = cell.n < minCases;
      return e('div', { title: cell.tooltip || undefined },
        e('div', { style: { fontFamily: "monospace", fontWeight: 700, fontSize: 15, color: small ? C.inkMid : C.black } }, cell.norm.toFixed(1)),
        cell.raw != null ? e('div', { style: { fontSize: 10, color: C.inkFaint, fontFamily: "monospace" } }, cell.raw.toFixed(1) + (cell.rawUnit || "")) : null,
        e('div', { style: { fontSize: 10, color: small ? "#a8851f" : C.inkFaint, fontFamily: "monospace" } }, "n=" + cell.n)
      );
    }

    return e('div', {},
      e('div', { style: { overflowX: "auto", marginBottom: 10 } },
        e('table', { style: { width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 480 } },
          e('thead', {},
            e('tr', {},
              e('th', { style: { textAlign: "left", padding: "8px 10px", fontSize: 10.5, fontFamily: "monospace", color: C.inkFaint, textTransform: "uppercase", borderBottom: "1px solid " + C.border } }, copy.rowHead),
              columns.map(function (c) {
                return e('th', { key: c.key, style: { textAlign: "center", padding: "8px 10px", fontSize: 10.5, fontFamily: "monospace", color: C.inkFaint, textTransform: "uppercase", borderBottom: "1px solid " + C.border, whiteSpace: "nowrap" } }, c.label);
              })
            )
          ),
          e('tbody', {},
            sorted.map(function (row) {
              return e('tr', { key: row.key, style: { borderBottom: "1px solid " + C.border } },
                e('td', { style: { padding: "10px", fontWeight: 700, color: C.black, whiteSpace: "nowrap" } }, row.label),
                columns.map(function (c) {
                  var cell = row.cells[c.key];
                  var muted = !cell || cell.n === 0 || cell.norm == null || cell.n < minCases;
                  return e('td', { key: c.key, style: Object.assign({ padding: "10px", textAlign: "center" }, muted ? { backgroundImage: hatch } : {}) }, cellBody(cell));
                })
              );
            })
          )
        )
      ),
      e('p', { style: { fontSize: 11, color: C.inkFaint, lineHeight: 1.6 } }, copy.lowSampleLegend)
    );
  }

  // ── Переключатель «Просто / Как есть» (SPEC_ch2_debug_and_chart_engine.md
  // §3) -- читает/пишет window.SbfSimpleLang (simple-lang.js, грузится
  // глобально ДО этого файла не гарантированно, поэтому все обращения --
  // внутри тела компонента/эффекта, не на верхнем уровне модуля). simplified/
  // total -- честный счётчик прогресса главы ("упрощены N из M", §3.2), а не
  // выдумка: считает его сам вызывающий (edu_book_N.html), этот компонент
  // только показывает то, что ему передали.
  function SimpleLangToggle(props) {
    var lang = props.lang, simplified = props.simplified, total = props.total;
    var e = React.createElement;
    var s = React.useState(function () { return (window.SbfSimpleLang && window.SbfSimpleLang.get()) || "pro"; });
    var mode = s[0], setMode = s[1];
    React.useEffect(function () {
      if (!window.SbfSimpleLang) return undefined;
      return window.SbfSimpleLang.subscribe(setMode);
    }, []);
    var L = ({
      ru: { simple: "Просто", pro: "Как есть", progress: function (n, m) { return "упрощены " + n + " из " + m; } },
      ro: { simple: "Simplu", pro: "Ca atare", progress: function (n, m) { return "simplificate " + n + " din " + m; } },
      en: { simple: "Simple", pro: "As-is", progress: function (n, m) { return "simplified " + n + " of " + m; } },
    })[lang] || { simple: "Просто", pro: "Как есть", progress: function (n, m) { return "упрощены " + n + " из " + m; } };
    function btn(key, text) {
      var active = mode === key;
      return e('button', {
        key: key,
        onClick: function () { window.SbfSimpleLang && window.SbfSimpleLang.set(key); },
        style: {
          fontFamily: "monospace", fontSize: 11.5, letterSpacing: 1, padding: "6px 14px", border: "1px solid " + (active ? C.gold : C.border),
          background: active ? C.gold : "transparent", color: active ? C.black : C.inkSoft, cursor: "pointer",
          borderRadius: key === "simple" ? "16px 0 0 16px" : "0 16px 16px 0", transition: "all .15s",
        },
      }, text);
    }
    return e('div', { style: { display: "inline-flex", flexDirection: "column", alignItems: "flex-start", gap: 4 } },
      e('div', { style: { display: "inline-flex" } }, btn("simple", L.simple), btn("pro", L.pro)),
      total ? e('span', { style: { fontSize: 10, color: C.inkFaint, fontFamily: "monospace" } }, L.progress(simplified, total)) : null
    );
  }

  // ── Комплаенс-дисклеймер (SPEC_academy_chapter3_integration.md §6,
  // решение А: оставляем RR/WinRate-математику как общую арифметику точки
  // безубыточности, добавляем один системный дисклеймер во все главы).
  var COMPLIANCE_TEXT = {
    ru: "Иллюстративные данные, используются в образовательных целях. Не является индивидуальной инвестиционной рекомендацией.",
    en: "Illustrative data, used for educational purposes. Not personalized investment advice.",
    ro: "Date ilustrative, utilizate în scopuri educaționale. Nu reprezintă o recomandare de investiții personalizată.",
  };
  function ComplianceFootnote(props) {
    var lang = props.lang;
    return React.createElement('p', {
      style:{fontFamily:"monospace", fontSize:11, color:C.inkFaint, textAlign:"center", lineHeight:1.6, margin:"32px auto 0", maxWidth:640}
    }, COMPLIANCE_TEXT[lang] || COMPLIANCE_TEXT.ru);
  }

  // Русское склонение числительных (SPEC_site_fixes_2026-07-28.md P2.1):
  // "61 дней" вместо "61 день" — числа теперь везде приходят из JSON
  // (бары/дни/периоды бэкфилла), такие места будут появляться постоянно
  // во всех главах, поэтому одна общая функция, а не разовая правка строки.
  function pluralRu(n, forms) {
    // forms = [один, немного (2-4), много (5-20, 0)] -- например
    // ["день","дня","дней"] или ["торговый день","торговых дня","торговых дней"].
    var mod10 = Math.abs(n) % 10, mod100 = Math.abs(n) % 100;
    if (mod10 === 1 && mod100 !== 11) return forms[0];
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1];
    return forms[2];
  }
  function declineRu(n, forms) {
    return n + ' ' + pluralRu(n, forms);
  }
  // Румынский: "de" перед мн.ч. существительным при числе >=20 ("61 de zile"),
  // без "de" для 2-19 ("19 zile") и ед.ч. для 1 ("1 zi"). [ДОПУЩЕНИЕ] упрощённое
  // правило -- не покрывает более редкие морфологические случаи, но верно для
  // всех числительных, встречающихся в курсе (дни/бары/периоды бэкфилла).
  function declineRo(n, singular, plural) {
    if (Math.abs(n) === 1) return n + ' ' + singular;
    return n + (Math.abs(n) >= 20 ? ' de ' : ' ') + plural;
  }
  // Английский: 1 -> singular, иначе plural (никакой другой развилки нет).
  function declineEn(n, singular, plural) {
    return n + ' ' + (Math.abs(n) === 1 ? singular : plural);
  }

  // ── ColdStart — единый интерактив "вопрос → действие → настоящий ответ"
  // (SPEC_coldstart_interactives_ch6_15.md §1). Один компонент на все главы
  // 6-15, отличаются только пропсы. Жёсткие правила спеки, которые компонент
  // соблюдает сам, а не понадеявшись на вызывающую главу:
  //  - ответ (reveal) не рендерится, пока action не зафиксирован (committed);
  //  - один жест на действие: choice -- клик по кнопке, slider -- отпускание
  //    указателя, numberInput -- Enter/blur, chartTap -- клик по свече;
  //  - bridge и reveal показываются вместе, после commit, единым блоком.
  // action.type: 'choice' | 'slider' | 'numberInput' | 'chartTap' | 'custom'.
  // reveal может быть строкой/нодой или функцией (answer) => нода -- удобно,
  // когда текст раскрытия зависит от того, что выбрал читатель.
  function ColdStart(props) {
    var tag = props.tag, ask = props.ask, action = props.action,
        reveal = props.reveal, bridge = props.bridge;
    var e = React.createElement;
    var s1 = React.useState(false), committed = s1[0], setCommitted = s1[1];
    var s2 = React.useState(null), answer = s2[0], setAnswer = s2[1];

    function commit(value) {
      if (committed) return;
      setAnswer(value);
      setCommitted(true);
    }

    var revealContent = committed ? (typeof reveal === "function" ? reveal(answer) : reveal) : null;

    return e('div', {style:{background:C.black, padding:"64px 5vw 52px", color:"#fff"}},
      tag ? e(Mono, {size:11, color:C.gold, spacing:4, style:{display:"block", marginBottom:22, textAlign:"center"}}, tag) : null,
      e('p', {style:{fontFamily:"'DM Serif Display',serif", fontSize:"clamp(21px,3.2vw,28px)", color:"#fff",
                     textAlign:"center", maxWidth:680, margin:"0 auto 30px", lineHeight:1.42}}, ask),
      e('div', {style:{maxWidth:660, margin:"0 auto"}},
        ColdStartAction({action: action, committed: committed, answer: answer, commit: commit})
      ),
      committed && revealContent ? e('div', {style:{maxWidth:640, margin:"26px auto 0", padding:"20px 24px",
                    background:"rgba(201,151,58,0.1)", border:"1px solid rgba(201,151,58,0.3)", borderRadius:6}},
        e('div', {style:{fontSize:16, lineHeight:1.62, color:"#fff"}}, revealContent)
      ) : null,
      committed && bridge ? e('p', {style:{textAlign:"center", fontFamily:"monospace", fontSize:12,
                    color:C.gold, letterSpacing:0.5, marginTop:22, marginBottom:0}}, bridge) : null
    );
  }

  function ColdStartAction(p) {
    var action = p.action, committed = p.committed, answer = p.answer, commit = p.commit;
    var e = React.createElement;
    if (!action) return null;
    if (action.type === "choice") return ColdStartChoice({options: action.options, committed: committed, answer: answer, commit: commit});
    if (action.type === "slider") return ColdStartSlider({cfg: action.slider, committed: committed, commit: commit});
    if (action.type === "numberInput") return ColdStartNumberInput({cfg: action.numberInput, committed: committed, commit: commit});
    if (action.type === "chartTap") return ColdStartChartTap({cfg: action.chart, committed: committed, commit: commit});
    if (action.type === "custom" && typeof action.render === "function") return action.render(commit, committed, answer);
    return null;
  }

  function ColdStartChoice(p) {
    var options = p.options, committed = p.committed, answer = p.answer, commit = p.commit;
    var e = React.createElement;
    return e('div', {style:{display:"flex", gap:10, flexWrap:"wrap", justifyContent:"center"}},
      options.map(function (opt, i) {
        var isPicked = committed && answer === opt.value;
        return e('button', {
          key: i, disabled: committed,
          onClick: function () { commit(opt.value); },
          style: {
            fontFamily:"monospace", fontSize:14, fontWeight:700, letterSpacing:0.5,
            padding:"14px 22px", borderRadius:4, cursor: committed ? "default" : "pointer",
            background: isPicked ? C.gold : "rgba(255,255,255,0.06)",
            color: isPicked ? C.black : "#fff",
            border:"1px solid " + (isPicked ? C.gold : "rgba(255,255,255,0.22)"),
            opacity: committed && !isPicked ? 0.45 : 1, transition:"all .15s", minWidth:96,
          }
        }, opt.label);
      })
    );
  }

  function ColdStartSlider(p) {
    var cfg = p.cfg, committed = p.committed, commit = p.commit;
    var e = React.createElement;
    var s = React.useState(cfg.default), val = s[0], setVal = s[1];
    var fmt = cfg.format || function (v) { return String(v); };
    function release() { if (!committed) commit(val); }
    return e('div', {style:{textAlign:"center"}},
      e('div', {style:{fontFamily:"monospace", fontSize:28, fontWeight:700, color:C.gold, marginBottom:14}}, fmt(val)),
      e('input', {
        type:"range", min:cfg.min, max:cfg.max, step:cfg.step || 1, value:val, disabled:committed,
        onChange: function (ev) { setVal(+ev.target.value); },
        onMouseUp: release, onTouchEnd: release, onKeyUp: function (ev) { if (ev.key === "Enter") release(); },
        style:{width:"100%", accentColor:C.gold, cursor: committed ? "default" : "pointer"}
      })
    );
  }

  function ColdStartNumberInput(p) {
    var cfg = p.cfg, committed = p.committed, commit = p.commit;
    var e = React.createElement;
    var s = React.useState(cfg.default != null ? String(cfg.default) : ""), val = s[0], setVal = s[1];
    function submit() {
      if (committed) return;
      var n = parseFloat(val);
      if (!isNaN(n)) commit(n);
    }
    return e('div', {style:{display:"flex", gap:10, justifyContent:"center", alignItems:"center"}},
      e('input', {
        type:"number", value:val, disabled:committed, placeholder:cfg.placeholder || "",
        onChange: function (ev) { setVal(ev.target.value); },
        onKeyDown: function (ev) { if (ev.key === "Enter") submit(); },
        onBlur: submit,
        style:{fontFamily:"monospace", fontSize:20, padding:"12px 16px", width:120, textAlign:"center",
               background:"rgba(255,255,255,0.06)", color:"#fff", border:"1px solid rgba(255,255,255,0.22)", borderRadius:4}
      }),
      cfg.unit ? e('span', {style:{fontFamily:"monospace", fontSize:14, color:"rgba(255,255,255,0.6)"}}, cfg.unit) : null,
      !committed ? e('button', {
        onClick: submit,
        style:{fontFamily:"monospace", fontSize:14, fontWeight:700, padding:"12px 18px", borderRadius:4,
               cursor:"pointer", background:C.gold, color:C.black, border:"none"}
      }, "→") : null
    );
  }

  // Тап по свече на реальном LightweightCharts-графике с закрытой правой
  // частью -- тот же механизм, что уже проверен в SqueezeTrainer (Глава 6,
  // SPEC_charts_and_interactivity_standard.md §2/§2.1): реальные бары,
  // ценовая/временная ось, data-source, штора вместо нарисованного будущего.
  // cfg = {candles:[{time,open,high,low,close}], visibleCount, dataSource,
  //        isCorrect:(time)=>bool, height}.
  function ColdStartChartTap(p) {
    var cfg = p.cfg, committed = p.committed, commit = p.commit;
    var e = React.createElement;
    var containerRef = React.useRef(null);
    var chartRef = React.useRef(null);
    var seriesRef = React.useRef(null);
    var tapHandlerRef = React.useRef(null);
    var s = React.useState(false), missed = s[0], setMissed = s[1];

    tapHandlerRef.current = function (time) {
      if (committed) return;
      if (cfg.isCorrect(time)) { setMissed(false); commit(time); }
      else { setMissed(true); setTimeout(function () { setMissed(false); }, 500); }
    };

    React.useEffect(function () {
      if (!containerRef.current || chartRef.current || typeof LightweightCharts === "undefined") return undefined;
      var chart = LightweightCharts.createChart(containerRef.current, {
        width: containerRef.current.clientWidth, height: cfg.height || 300,
        layout: { background: { color: C.chartBg }, textColor: "rgba(255,255,255,0.55)" },
        grid: { vertLines: { color: "rgba(255,255,255,0.05)" }, horzLines: { color: "rgba(255,255,255,0.05)" } },
        rightPriceScale: { borderColor: "rgba(255,255,255,0.15)" },
        timeScale: { borderColor: "rgba(255,255,255,0.15)", timeVisible: true, secondsVisible: false },
      });
      var series = chart.addCandlestickSeries({
        upColor: C.chartGreen, downColor: C.chartRed, borderUpColor: C.chartGreen, borderDownColor: C.chartRed,
        wickUpColor: C.chartGreen, wickDownColor: C.chartRed,
      });
      chartRef.current = chart; seriesRef.current = series;
      chart.subscribeClick(function (param) { if (param.time != null && tapHandlerRef.current) tapHandlerRef.current(param.time); });
      var ro = new ResizeObserver(function (entries) { if (entries[0]) chart.applyOptions({ width: entries[0].contentRect.width }); });
      ro.observe(containerRef.current);
      return function () { ro.disconnect(); chart.remove(); chartRef.current = null; };
    }, []);

    React.useEffect(function () {
      var series = seriesRef.current;
      if (!series || !cfg.candles || !cfg.candles.length) return;
      var visibleCount = committed ? cfg.candles.length : Math.min(cfg.visibleCount, cfg.candles.length);
      series.setData(cfg.candles.slice(0, visibleCount).map(function (c) {
        return { time: c.time, open: +c.open, high: +c.high, low: +c.low, close: +c.close };
      }));
      if (committed && cfg.markerTime != null) {
        series.setMarkers([{ time: cfg.markerTime, position:"aboveBar", color:C.gold, shape:"arrowDown", text: cfg.markerText || "" }]);
      } else {
        series.setMarkers([]);
      }
      chartRef.current.timeScale().fitContent();
    }, [cfg.candles, cfg.visibleCount, committed, cfg.markerTime]);

    return e('div', {style:{position:"relative", borderRadius:6, overflow:"hidden",
                            border: missed ? "1px solid " + C.red : "1px solid transparent", transition:"border .2s",
                            cursor: committed ? "default" : "crosshair"}},
      e('div', {ref:containerRef, "data-source":cfg.dataSource}),
      !committed ? e('div', {style:{position:"absolute", top:0, right:0, bottom:0,
                    width: (100 - (cfg.visibleCount / cfg.candles.length * 100)) + "%",
                    background:"rgba(19,23,34,0.92)", pointerEvents:"none"}}) : null
    );
  }

  /* ── АНТИ-МИФ: слои снимаются по одному ────────────────────────────────
   *
   * ЗАЧЕМ. Замер 10.09.2026 по всем пятнадцати главам: в главах 6-15 вдвое
   * меньше интерактивных элементов при том же объёме текста, а медиана куска
   * текста между двумя действиями — 1064 знака против 401 в главах 2-5. Причём
   * рубрика «АНТИ-МИФ» стоит в начале самого длинного куска в ШЕСТИ главах из
   * десяти: 6, 7, 8, 9, 10, 12.
   *
   * В главе 5 та же рубрика — компонент с двумя кнопками. В главах 6-14 её
   * скопировали как три-четыре подряд идущих <p> на 900-1300 знаков. Один
   * шаблон испортил статистику половине курса.
   *
   * ПОЧЕМУ ИМЕННО «ПО ОДНОМУ СЛОЮ», а не вкладки и не аккордеон. Так устроен
   * сам текст рубрики: «миф здесь слоёный, и снимать надо по одному» (гл. 7),
   * «у этой главы миф двусторонний» (гл. 5). Первый абзац — ходовое
   * заблуждение, последний — что остаётся после разбора. Порядок в этой
   * рубрике несёт смысл, поэтому и раскрытие последовательное.
   *
   * 🔴 Уже раскрытое НЕ прячется обратно. Соблазн сделать «одна карточка за
   * раз» велик — так метрика была бы ещё лучше, — но читателю нужно вернуться
   * глазами к предыдущему слою, когда он читает следующий: они спорят друг с
   * другом. Прятать прочитанное ради красивого числа значит чинить замер, а
   * не главу.
   */
  var ANTIMYTH_COPY = {
    ru: {next:"Снять следующий слой →", last:"Что остаётся →", of:"слой %1 из %2",
         done:"слои сняты"},
    ro: {next:"Înlătură stratul următor →", last:"Ce rămâne →",
         of:"stratul %1 din %2", done:"straturi înlăturate"},
    en: {next:"Peel the next layer →", last:"What remains →",
         of:"layer %1 of %2", done:"layers peeled"}
  };

  function antiMythBodies(data) {
    // В главах структура разная: где-то body, где-то body1..body4.
    if (!data) return [];
    if (data.bodies && data.bodies.length) return data.bodies;
    var out = [];
    if (data.body) out.push(data.body);
    for (var i = 1; i <= 8; i++) {
      if (data["body" + i]) out.push(data["body" + i]);
    }
    return out;
  }

  function AntiMythBlock(props) {
    var e = React.createElement;
    var data = props.data || {};
    var lang = props.lang || "ru";
    var copy = ANTIMYTH_COPY[lang] || ANTIMYTH_COPY.ru;
    var bodies = antiMythBodies(data);
    var st = React.useState(1), shown = st[0], setShown = st[1];
    var всего = bodies.length;
    var последний = shown >= всего;

    // Внешний отступ приходит из главы: в разных главах блок стоит в разном
    // окружении (28 у одних, 48 у других), и зашитое здесь число ломало бы
    // вертикальный ритм страницы.
    return e('div', {style: props.style || {marginBottom:28}},
      data.tag ? e(Mono, {size:11, color:C.gold, spacing:3,
                          style:{display:"block", marginBottom:10}}, data.tag) : null,
      e('div', {style:{background:C.surface, border:"1px solid " + C.border,
                       borderRadius:8, padding:"22px 26px"}},
        data.title ? e('p', {style:{fontWeight:600, fontSize:14.5, color:C.black,
                                    marginBottom:16}}, data.title) : null,
        bodies.slice(0, shown).map(function (b, i) {
          return e('p', {key:i, style:{fontSize:13.5, color: i === всего - 1 ? C.black : C.inkMid,
                                       lineHeight:1.7, marginBottom:12,
                                       fontWeight: i === всего - 1 && всего > 1 ? 600 : 400}}, b);
        }),
        всего > 1 ? e('div', {style:{display:"flex", alignItems:"center", gap:12,
                                     marginTop:6, flexWrap:"wrap"}},
          !последний ? e('button', {
            onClick: function () { setShown(shown + 1); },
            style:{fontFamily:"monospace", fontSize:11.5, padding:"9px 16px", cursor:"pointer",
                   background:C.gold, color:"#18181a", border:"none", borderRadius:4,
                   fontWeight:700}
          }, shown === всего - 1 ? copy.last : copy.next) : null,
          e(Mono, {size:10.5, color:C.inkFaint},
            последний ? copy.done
                      : copy.of.replace("%1", String(shown)).replace("%2", String(всего)))
        ) : null
      )
    );
  }

  window.AcademyShared = {
    AntiMythBlock: AntiMythBlock,
    C: C, Mono: Mono, Chip: Chip, Rule: Rule,
    GlossWord: GlossWord, withGlossTerms: withGlossTerms,
    AskAnalystPopup: AskAnalystPopup, AskAnalystBtn: AskAnalystBtn,
    getChUrl: getChUrl,
    QuizBlock: QuizBlock,
    ImpactMatrix: ImpactMatrix,
    SimpleLangToggle: SimpleLangToggle,
    ComplianceFootnote: ComplianceFootnote,
    pluralRu: pluralRu,
    declineRu: declineRu,
    declineRo: declineRo,
    declineEn: declineEn,
    ColdStart: ColdStart,
  };
})();
