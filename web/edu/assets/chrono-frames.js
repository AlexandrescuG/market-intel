/* Кадры станций хроники по настоящим рядам — общий код глав 1 и 2.

   🔴 ЗАЧЕМ ОТДЕЛЬНЫМ ФАЙЛОМ. Рисовальщик кадра сначала жил внутри
   chrono2.js, и глава 1 к нему не дотягивалась: она грузит только
   chrono.js. А станция 1987 есть в обеих главах — это один и тот же
   чёрный понедельник, и ряд под него собран один. Копировать рисовальщик
   во второй файл значит завести вторую копию того же знания; такие копии
   в этом проекте уже расходились (подписи статусов лида, разные линейки в
   двух замерах). Поэтому код один, подключается обеими главами.

   ЧТО ЗАМЕНЯЕТ. Раньше станция без фотографии рисовалась ломаной,
   набранной координатами руками, а подпись под ломаной стояла настоящая —
   с датой и процентом. Такую картинку нельзя отличить от графика: она
   не подписана как схема и выглядит ровно так же. Теперь ряд приходит из
   web/data/edu_capsules/chrono2_frames.json, а подпись там посчитана из
   самого ряда сборщиком tools/edu_build/build_chrono2_frames.py.

   Ряды приходят асинхронно и позже первой отрисовки, поэтому по загрузке
   бросается событие "chrono2-frames" — главы на него подписаны и
   перерисовываются. Без события картина зависела бы от того, успела ли
   сеть: на быстрой машине «всё хорошо», у читателя как повезёт.
*/
(function(){
  function эск(s){
    return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
    });
  }

  /* 🔴 ПАТТЕРНЫ #hatch И #hatch2 ОБЪЯВЛЯЮТСЯ ЗДЕСЬ ЖЕ, ВНУТРИ КАДРА.
     Рисованные станции ссылались на них через url(#hatch), а объявления
     не было нигде: поиск по всему web/ не находил ни одного pattern с
     такими id. По спецификации SVG недостижимая ссылка в fill означает,
     что элемент не рисуется вовсе, — фон и «пол» отсутствовали на всех
     станциях с самого начала, молча и без ошибки в консоли. Зависимость
     от «где-то определено» и была причиной, поэтому кадр самодостаточен. */
  function defs(){
    return '<defs>'
      + '<pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse">'
      +   '<rect width="8" height="8" fill="#F6EFE2"/>'
      +   '<path d="M0 8 L8 0" stroke="#E7DFCF" stroke-width="1"/></pattern>'
      + '<pattern id="hatch2" width="6" height="6" patternUnits="userSpaceOnUse">'
      +   '<rect width="6" height="6" fill="#EDE3D1"/>'
      +   '<path d="M0 6 L6 0" stroke="#DCCFB4" stroke-width="1.2"/></pattern>'
      + '</defs>';
  }

  function кадрПоДанным(frame){
    var ряд = frame && frame['ряд'] || [];
    if (ряд.length < 2) return '';
    var L = 58, R = 24, T = 34, B = 64;
    var W = 720 - L - R, H = 400 - T - B;
    var мин = frame['мин'], макс = frame['макс'];
    var зазор = (макс - мин) * 0.08 || 1;   // чтобы линия не липла к краям
    мин -= зазор; макс += зазор;
    var x = function(i){ return L + W * i / (ряд.length - 1); };
    var y = function(v){ return T + H * (1 - (v - мин) / (макс - мин)); };

    var шаги = frame['ступенька'];
    var d = '';
    for (var i = 0; i < ряд.length; i++) {
      var X = x(i), Y = y(ряд[i].c);
      if (i === 0) { d += 'M' + X.toFixed(1) + ' ' + Y.toFixed(1); }
      else if (шаги) {
        // Ставка живёт ступенями: между заседаниями она стоит, а не ползёт.
        // Наклонная линия показала бы движение, которого не было.
        d += ' H' + X.toFixed(1) + ' V' + Y.toFixed(1);
      } else {
        d += ' L' + X.toFixed(1) + ' ' + Y.toFixed(1);
      }
    }

    // Отметка события — на дате из данных, а не «примерно тут».
    var метка = '';
    if (frame['отметка']) {
      for (var j = 0; j < ряд.length; j++) {
        if (ряд[j].t === frame['отметка']) {
          var mx = x(j).toFixed(1);
          метка = '<line x1="' + mx + '" y1="' + T + '" x2="' + mx + '" y2="' + (T + H) + '"'
            + ' stroke="#8a2f2f" stroke-width="1.4" stroke-dasharray="5 4"/>'
            + '<circle cx="' + mx + '" cy="' + y(ряд[j].c).toFixed(1) + '" r="4.5"'
            + ' fill="#8a2f2f"/>';
          break;
        }
      }
    }

    var знаков = макс < 10 ? 4 : (макс < 1000 ? 2 : 0);
    return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg"'
      + ' role="img" aria-label="' + эск(frame['подпись']) + '">'
      + defs()
      + '<rect width="720" height="400" fill="url(#hatch)"/>'
      + '<rect x="' + L + '" y="' + T + '" width="' + W + '" height="' + H + '"'
      + ' fill="#FBF6EF" stroke="#E7DFCF" stroke-width="1"/>'
      + метка
      + '<path d="' + d + '" fill="none" stroke="#2B2B33" stroke-width="2.6"'
      + ' stroke-linejoin="round" stroke-linecap="round"/>'
      // Ось подписана крайними значениями самого ряда: без них линия — просто
      // форма, по которой нельзя сказать, велик ли ход.
      + '<text x="' + (L - 8) + '" y="' + (T + 6) + '" text-anchor="end"'
      + ' font-family="monospace" font-size="11" fill="#8A8275">'
      + эск(frame['макс'].toFixed(знаков)) + '</text>'
      + '<text x="' + (L - 8) + '" y="' + (T + H) + '" text-anchor="end"'
      + ' font-family="monospace" font-size="11" fill="#8A8275">'
      + эск(frame['мин'].toFixed(знаков)) + '</text>'
      + '<text x="' + L + '" y="' + (T + H + 18) + '"'
      + ' font-family="monospace" font-size="10" fill="#8A8275">'
      + эск(frame['первая']) + '</text>'
      + '<text x="' + (720 - R) + '" y="' + (T + H + 18) + '" text-anchor="end"'
      + ' font-family="monospace" font-size="10" fill="#8A8275">'
      + эск(frame['последняя']) + '</text>'
      + '<text x="360" y="' + (T + H + 38) + '" text-anchor="middle"'
      + ' font-family="monospace" font-size="12" fill="#2B2B33">'
      + эск(frame['подпись']) + '</text>'
      + '<text x="360" y="' + (T + H + 54) + '" text-anchor="middle"'
      + ' font-family="monospace" font-size="9.5" fill="#8A8275">'
      + эск(frame['источник']) + '</text>'
      + '</svg>';
  }

  /* Кадр по ключу станции. Нет ряда — возвращаем пусто, и вызывающий сам
     решает, что показать. Подменять отсутствующие данные похожей на них
     картинкой нельзя: это то, что здесь чинится. */
  function кадр(key){
    var к = window.Chrono2Frames;
    return (к && к[key]) ? кадрПоДанным(к[key]) : '';
  }

  window.SbfChronoFrames = {кадр: кадр, рисовать: кадрПоДанным, defs: defs};

  fetch('/data/edu_capsules/chrono2_frames.json', {cache: 'no-cache'})
    .then(function(r){
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function(j){
      window.Chrono2Frames = j && j['кадры'] ? j['кадры'] : null;
      if (!window.Chrono2Frames) throw new Error('в файле нет ключа "кадры"');
      window.dispatchEvent(new Event('chrono2-frames'));
    })
    .catch(function(e){
      if (window.console && console.warn) {
        console.warn('[chrono-frames] ряды станций не загрузились (' + e.message +
          '): станции остаются иллюстрациями. Файл собирается командой ' +
          '.venv/bin/python tools/edu_build/build_chrono2_frames.py');
      }
    });
})();
