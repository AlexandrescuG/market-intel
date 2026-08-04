---
purpose: промты для генерации 26 иконок взамен emoji на платформе lp.sbfconsult.com
created: 2026-07-15
zone: 🟢 Платформа и Боты
status: ожидает генерации пользователем
---

# Промты для генерации иконок — lp.sbfconsult.com

## Как этим пользоваться

1. Каждый промт ниже — целиком в генератор (Flow или другой), по одному изображению за раз.
2. Сохранить результат под именем из колонки **Файл** (это важно — по имени я потом автоматически сопоставлю иконку с её местом в коде).
3. Сложить все файлы в одну папку и сказать мне путь — я вырежу фон (`rembg`, уже установлен), приведу к единому размеру и заменю ими все ~400 мест использования emoji в 19 файлах.
4. Фон в промте специально задан однотонным белым — так вырезание получится чистым, без артефактов по краям.

## Единый стиль (одинаков во всех 26 промтах, меняется только предмет)

```
Minimalist flat vector icon, single centered symbol, plain solid white
background, no shadow, no gradient, no text, no photorealism. Clean
geometric line-art style, medium consistent stroke weight, slightly
rounded corners. Two-color palette only: dark charcoal (#2B2B33) for
the main line and silhouette, gold (#C9A227) used as one small accent
highlight within the icon. Square 1:1 composition with generous even
padding around the symbol so it stays legible at small UI size (~32px).
Icon subject: {SUBJECT}
```

Палитра — фирменная для этой платформы (уже используется в `edu/calendar.html`), не выдумана заново.

---

## 26 иконок — по убыванию частоты использования

| # | Emoji | Файл | Встречается | Промт (SUBJECT) |
|---|---|---|---|---|
| 1 | ✅ | `icon-check.png` | 50× | a simple checkmark inside a rounded square outline |
| 2 | 📊 | `icon-bar-chart.png` | 44× | three vertical bar chart columns of increasing height |
| 3 | 📈 | `icon-trend-up.png` | 43× | an upward-sloping trend line with an arrowhead pointing up-right |
| 4 | 🎯 | `icon-target.png` | 32× | a target / bullseye with three concentric rings and a center dot |
| 5 | ⚡ | `icon-lightning.png` | 28× | a single lightning bolt |
| 6 | 🚀 | `icon-rocket.png` | 21× | a simple rocket ship pointing upward with a small flame trail |
| 7 | 📉 | `icon-trend-down.png` | 20× | a downward-sloping trend line with an arrowhead pointing down-right |
| 8 | 🔴 | `icon-alert-dot.png` | 17× | a single filled circle, solid and bold, used as an alert marker |
| 9 | ⚠️ | `icon-warning.png` | 16× | a warning triangle with an exclamation mark inside |
| 10 | 🛡️ | `icon-shield.png` | 15× | a shield silhouette, front-facing, symmetrical |
| 11 | 🔥 | `icon-flame.png` | 14× | a single stylized flame |
| 12 | 💡 | `icon-idea.png` | 14× | a lightbulb with a few short radiating lines suggesting light |
| 13 | 💬 | `icon-quote.png` | 13× | a rounded speech bubble, empty inside |
| 14 | 🧠 | `icon-mindset.png` | 13× | a simplified brain silhouette, front view, minimal detail |
| 15 | 💰 | `icon-money.png` | 9× | a money bag with a dollar sign, simplified silhouette |
| 16 | 🏆 | `icon-trophy.png` | 9× | a trophy cup on a small base, front view |
| 17 | 🔒 | `icon-lock.png` | 7× | a padlock, closed, front view |
| 18 | 📅 | `icon-calendar.png` | 7× | a calendar page with a single highlighted date square |
| 19 | 📚 | `icon-books.png` | 6× | a small stack of two or three closed books, side view |
| 20 | ⭐ | `icon-star.png` | 6× | a single five-point star, filled |
| 21 | 💼 | `icon-briefcase.png` | 4× | a briefcase, front view, with a simple handle |
| 22 | 🌍 | `icon-globe.png` | 4× | a globe with simplified longitude/latitude lines, no continents detail |
| 23 | 📌 | `icon-pin.png` | 3× | a map pin / teardrop marker with a small circle at the top |
| 24 | 🏠 | `icon-house.png` | 3× | a simple house silhouette, front view, triangular roof |
| 25 | 🛍️ | `icon-shopping.png` | 1× | two shopping bags side by side, simplified silhouettes |
| 26 | 🧘 | `icon-mindfulness.png` | 1× | a person seated in a simple meditation pose, minimal silhouette |

---

## Что дальше (после того как файлы будут готовы)

1. Скинуть путь к папке с 26 файлами
2. Я: `rembg` → прозрачный фон → привожу к единому размеру (SVG-подобный transparent PNG, ~64×64 или 128×128)
3. Кладу в `market_intel/web/assets/icons/`
4. Систематическая замена всех ~400 emoji на `<img>`/inline-иконки по таблице выше, во всех 19 файлах: `journal.html`, `survey.html`, `edu/index.html`, `book/edu_book_1..15.html`, `book/edu_book_cover.html`
5. Визуальная проверка через локальный serve.py перед тем как считать готовым

## Связанные заметки

- [[Core — Координация между чатами]] — лог
- [[Projects Map]] — раздел market_intel
