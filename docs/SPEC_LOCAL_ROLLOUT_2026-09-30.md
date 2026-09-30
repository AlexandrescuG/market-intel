# SPEC — выкатка правок аудита ИИ-видимости на прод (для чата с доступом к локальным файлам)

**Дата:** 30.09.2026
**Источник:** облачная сессия Claude Code. Аудит — `market-intel/docs/AI_VISIBILITY_AUDIT_2026-09.md`.
**Исполнитель:** локальный чат с доступом к серверу и файлам (`/mnt/sbfdata/...`).
**Затронутые зоны:** 🟣 «Сайт и Контент» (sbf-nexus = sbfconsult.com) и 🟢 «Платформа/Боты» (market_intel = lp.sbfconsult.com, SBFAcademy_bot). Если в каждой зоне свой чат — раздел A выполняет «Сайт/Контент», разделы B и C — «Платформа/Боты». Разделы D–F общие.

---

## 0. Что уже сделано и где лежит

| Репозиторий | Ветка | Что внутри |
|---|---|---|
| `AlexandrescuG/sbf-nexus` | `claude/project-audit-improvements-kzr6xz` | регуляторные формулировки, переименование в SBF Company, JSON-LD, `server.py` (301/404), `robots.txt`, `?lang=` в `i18n.js`, ключ IndexNow |
| `AlexandrescuG/market-intel` | `claude/project-audit-improvements-kzr6xz` | `robots.txt` lp, noindex платных глав, sitemap без глав 6–15 и `/register`, фиксы брифа, `tools/indexnow.py` + ключ, переименование, `llms.txt`, аудит и эта спека |
| `AlexandrescuG/sbfacademy-bot` | `claude/project-audit-improvements-kzr6xz` | переименование в SBF Company в текстах бота |

**Решения владельца (не пересматривать):**
- Бренд — **SBF Company**. Домен **sbfconsult.com остаётся**. Терминал — **SBF Intelligence**. Логотип (включая словесный знак «SBF CONSULT ● MANAGEMENT» в шапке) **не меняется**.
- Главы курса 6–15 доступны только после регистрации. Их не открываем, а убираем из индекса.
- Пропуски выпусков брифа 18–28.09 были из-за неоплаты Claude. Это не баг кода.
- Владелец уже вошёл в Bing Webmaster Tools.

**Ключ IndexNow:** `7a03d9d8dbb9e212c083081e54ad5773` (публичный по устройству протокола).

---

## 1. ГЛАВНЫЙ РИСК: прод ≠ git

При аудите выяснилось, что на проде есть то, чего нет в репозиториях:

- **sbfconsult.com:** `robots.txt`, `sitemap.xml`, `llms.txt`, `risk.html`, папка `brief/` с выпусками, генератор архива брифов (страницы `/brief/YYYY-MM-DD.html` с «Разбор сделан утром… архивная копия»). Кроме того, **`index.html` на проде новее, чем в git**: в живом JSON-LD есть IDNO, `ro` и Telegram в `sameAs`, а в репозитории их не было. Поведение сервера тоже не совпадает с `server.py` из git: `/ro` на проде уже отдаёт 301, а случайный путь — 404.
- **lp.sbfconsult.com:** до 30.09 в git не было текстового слоя, генератора sitemap и маршрутов `/ro/` `/en/`. Теперь они подтянуты владельцем. Всё равно сверить.

**Поэтому никакого `git pull` поверх прод-папки вслепую.** Порядок для каждого сайта:
1. Снимок прода в git (отдельная ветка) → 2. слияние с веткой аудита → 3. ручное разрешение конфликтов → 4. деплой → 5. проверки из раздела F.

---

## A. sbfconsult.com (репозиторий sbf-nexus) — зона «Сайт/Контент»

### A1. Найти, что реально работает на проде
```bash
systemctl cat sbfconsult-web.service          # WorkingDirectory и ExecStart
# ожидается: …/sbf-nexus и python3 server.py (порт 5001) за Cloudflare Tunnel
cd <WorkingDirectory>
git status --short                            # неотслеживаемые и изменённые файлы
git log --oneline -3
diff <(git show HEAD:server.py) server.py     # тот ли server.py запущен
```
Готово, когда: известны путь прод-папки, какой скрипт запущен и полный список файлов прода, которых нет в git.

### A2. Снимок прода в git (до любых правок)
```bash
git checkout -b prod-snapshot-2026-09-30
git add -A          # ПЕРЕД этим проверить .gitignore: не добавлять .env, токены, логи, node_modules, _archive/
git commit -m "Снимок прода sbfconsult.com на 30.09.2026 (до выкатки аудита)"
git push -u origin prod-snapshot-2026-09-30
```
Если в `index.html` на проде есть `window.SBF_BOT_TOKEN` с **настоящим** токеном (а не `PLACEHOLDER_BOT_TOKEN`), в git его не коммитить: заменить на плейсхолдер, а токен отозвать в @BotFather.

### A3. Слить ветку аудита
```bash
git fetch origin claude/project-audit-improvements-kzr6xz
git merge origin/claude/project-audit-improvements-kzr6xz
```
Ожидаемые конфликты и как решать:

| Файл | Как решать |
|---|---|
| `index.html` | **Базой брать прод-версию** (она новее). Перенести из ветки аудита: (1) весь блок `<script type="application/ld+json">` — целиком версию из ветки; (2) `<title>`, `meta description`, `og:*`, `twitter:*` — с «SBF Company» и без «EU-лицензированные»; (3) `langMap`: `'/ro': 'ro'`; (4) тексты hero, `hero-trust`, карточки NAGA/InstaForex, дисклеймеры доверительного управления (две копии: desktop и mobile); (5) `alt="SBF Company логотип"`. Словесный знак `SBF CONSULT <strong>●</strong> MANAGEMENT` **не трогать** |
| `robots.txt` | Взять версию из ветки. Если на проде были дополнительные `Disallow`, добавить их **во все три группы** |
| `js/i18n.js` | Взять ветку, затем проверить, что прод-правки i18n (если были) не потеряны: `git diff prod-snapshot-2026-09-30 -- js/i18n.js` |
| `server.py` | См. A4 |

Проверка синтаксиса после слияния:
```bash
node -e "new Function(require('fs').readFileSync('js/i18n.js','utf8'))" && echo i18n ok
python3 - <<'EOF'
import json,re
s=open('index.html').read()
for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', s, re.S): json.loads(b)
print('json-ld ok')
EOF
grep -rIn -i "лицензиями ЕС\|EU-licensed\|EU-лиценз\|licențiați UE\|autorizați UE\|регулируемых в ЕС" --exclude-dir=.git --exclude-dir=_archive . && echo "✗ остались EU-формулировки" || echo "✓ EU-формулировок нет"
grep -rIn "SBF Consult" --exclude-dir=.git --exclude-dir=_archive . | grep -v alternateName
```
Последний grep должен выдать только `alternateName` в JSON-LD (это намеренно: склеивает старые упоминания с новой сущностью) и `llms.txt` с фразой «прежнее название — SBF Consult», если она там будет.

### A4. Сервер: 301 для старых адресов и честный 404
Логика в `server.py` ветки аудита:
- `REDIRECTS` (301): `/ru|/en|/ro` → `/?lang=…`, `/uk|/be|/kk` → `/?lang=ru`, `/blank-2` → `/risk.html`, `/index.html` → `/`;
- `PREFIX_REDIRECTS` (301): `/service-page/*` и `/book*` → `https://lp.sbfconsult.com/edu/`;
- `PRIVATE_PREFIXES` → 404: `/.git`, `/_archive`, `/node_modules`, `/docs`, `/tools`, `/hero-preview`, `CLAUDE.md`, `README.md`, `server.py`, `dev.sh`, `package*.json`, `.sbf-zone`, `.gitignore`;
- всё остальное без файла → 404 (никакой подмены на `index.html`).

Если на проде работает **другой** сервер (A1 это покажет), перенести в него эти три таблицы, сохранив его остальное поведение. Проверить, что `/brief/`, `/brief/<дата>.html`, `/risk.html`, `/cons-kz/`, `/sitemap.xml`, `/llms.txt`, `/robots.txt`, `/7a03d9d8dbb9e212c083081e54ad5773.txt` отдают 200.

Перезапуск: `sudo systemctl restart sbfconsult-web`. **НИКОГДА не делать `pkill -f cloudflared`**: в одном процессе живут несколько туннелей.

### A5. Файлы, которых нет в git: исправить тем же образом
```bash
grep -rIln -i "sbf consult\|лицензиями ЕС\|EU-licensed\|регулируемых в ЕС\|FCA, CySEC" risk.html llms.txt brief/ sitemap.xml 2>/dev/null
```
- **`risk.html`:** проверить регуляторные формулировки по правилу «FCA — Великобритания, не ЕС; юрлицо и регулятор брокера зависят от страны клиента». Бренд → SBF Company. Дату обновления поставить сегодняшнюю.
- **`llms.txt` sbfconsult.com:** заголовок `# SBF Company`, строка «прежнее название бренда — SBF Consult», юрлицо `«SBF COMPANY» S.R.L.`, IDNO, LEI. Офисы — **только те, что указаны в контактах сайта** (сейчас MD, CH, PT, AE; KZ и ZA — только если есть адрес). Языки: ru, en, ro.
- **Уже опубликованные брифы `brief/*.html`:** архив не переписываем (так заявлено на странице). Единственное исключение — техническая замена `"name": "SBF Consult"` → `"SBF Company"` в JSON-LD `author`/`publisher` и в шапке `SBF Consult · бриф`: это не содержание разбора. Выпуск 17.09 с заголовком «Соцсети: ФРС подняла ставку…» оставить, но добавить под H1 блок `<p class="note"><b>Уточнение от 30.09.2026:</b> заголовок этого выпуска взят из непроверенных сообщений соцсетей; подтверждения в котировках и СМИ в выпуске не было.</p>` (если в тот день ставку действительно подняли — написать это вместо уточнения).

### A6. Генератор архива брифов (найти и поправить)
```bash
grep -rl "архивная копия\|Все выпуски" /mnt/sbfdata --include=*.py --include=*.js --include=*.html 2>/dev/null | grep -v "/brief/20"
```
В генераторе:
1. `author`/`publisher` в JSON-LD: `{"@type":"Organization","@id":"https://sbfconsult.com/#org","name":"SBF Company"}`. Шапка страницы: `SBF Company · бриф`.
2. **Защита заголовка:** если `headline` пуст или совпадает с текстом пункта `context` с `confidence == "social_unverified"`, то H1, `<title>` и `description` собирать из блока котировок (например, «Золото 4 137,70 (+0,25%), S&P 500 −0,21%, VIX 16,07»). Промпт уже запрещает слухи в headline (`analyze/prompt.md`), это вторая линия обороны.
3. После записи страницы и обновления `sitemap.xml` вызвать `python3 <market_intel>/tools/indexnow.py --url https://sbfconsult.com/brief/<дата>.html --url https://sbfconsult.com/brief/`. Скрипт лежит в market_intel, путь указать абсолютный.
4. `sitemap.xml` sbfconsult.com: каждый выпуск — со своим `lastmod`. Это уже так, проверить.
5. Алерт в Telegram, если к 07:00 (Кишинёв) выпуска за сегодня нет. Причина прошлых пропусков — оплата Claude, а алерт поймает и её.

### A7. Коммит
```bash
git add -A && git commit -m "Выкатка аудита ИИ-видимости: регуляторы, SBF Company, 301/404, robots, IndexNow"
git push origin HEAD
```
В лог `/mnt/sbfdata/sbfcrm/obsidian/Onsidian/SBF/Core — Координация между чатами.md` дописать строку о выкатке.

---

## B. lp.sbfconsult.com (market_intel) — зона «Платформа/Боты»

### B1. Слияние
```bash
cd <market_intel>
git status --short                       # прод-изменения вне git — сначала закоммитить в prod-snapshot-2026-09-30 (как A2)
git fetch origin claude/project-audit-improvements-kzr6xz
git merge origin/claude/project-audit-improvements-kzr6xz
```
Изменённые файлы: `analyze/build_brief_v2.py`, `analyze/prompt.md`, `serve.py`, `tools/build_sitemap.py`, `tools/build_llms.py`, `tools/indexnow.py` (новый), `web/robots.txt`, `web/sitemap.xml`, `web/llms.txt`, `web/index.html`, `web/journal.html`, `i18n/site/{ru,en,ro}.json`, `web/7a03d9d8dbb9e212c083081e54ad5773.txt` (новый), `.gitignore`, `docs/*`.

### B2. Пересобрать производные файлы
```bash
python3 tools/build_sitemap.py           # с живой проверкой на 127.0.0.1:8085 — все адреса должны дать 200
python3 tools/build_llms.py
node tools/build_text_layer.js           # в i18n сменился бренд — текстовый слой для краулеров надо пересобрать
python3 tools/consistency_check.py
python3 tools/check_schema.py 2>/dev/null; python3 tools/check_crawler_text.py 2>/dev/null
```
Ожидается: в sitemap **51** адрес (17 материалов × 3 языка), нет `/edu/b/6…15` и `/register`.

### B3. Перезапуск и проверка
Перезапустить сервис `serve.py` тем способом, которым он запущен (`systemctl --user status` / `start.sh`, уточнить по месту). Затем:
```bash
curl -s localhost:8085/edu/b/7 | grep -o '<meta name="robots"[^>]*>\|<title>[^<]*'
#  → noindex, follow  и  <title>7. <название главы> — SBF
curl -s localhost:8085/edu/b/3 | grep -o '<meta name="robots"[^>]*>'   # открытая глава — index, follow
curl -s localhost:8085/robots.txt | grep -c Disallow                     # 9
curl -s localhost:8085/7a03d9d8dbb9e212c083081e54ad5773.txt              # сам ключ
curl -s localhost:8085/ | grep -c "SBF Consult"                          # 1 (только alternateName)
```

### B4. Бриф
- `analyze/build_brief_v2.py`: блок «кто ходил шире обычного» теперь берёт только `ratio > 1` (константа `MOVERS_MIN_RATIO`). Решения по ставке одной страны с метками `rate` / `cash rate` в пределах 90 минут схлопываются (`_is_same_rate_decision`). Прогнать на сегодня: `python3 analyze/build_brief_v2.py` и проверить `web/data/brief_today.json`: в `movers.up/down` нет `ratio <= 1`, в `calendar` нет повторов RBA/ФРС.
- `analyze/prompt.md`: добавлено правило «в headline — только quotes/media». **Проверить, какой промпт использует локальный запасной путь** (`analyze/llm_context_local.py`, коммит «запасной путь модели»). Если у него свой промпт — перенести туда то же правило.

### B5. Коммит + лог координации (как A7)

---

## C. SBFAcademy_bot
```bash
cd <sbfacademy-bot>
git fetch origin claude/project-audit-improvements-kzr6xz && git merge origin/claude/project-audit-improvements-kzr6xz
python3 -c "import ast;ast.parse(open('SBFAcademy_bot.py').read())"
```
Перезапустить бота. В меню «О компании» должно стоять «SBF Company», кнопка — «🌐 Сайт SBF Company». Проверить ещё: `sbfacademy/briefing/*`, тексты Mini App (`webapp/i18n.js`), `strings.xml` Android. Если там «SBF Consult», заменить так же (в облаке эти места не нашлись, но прод может отличаться).

---

## D. Bing Webmaster Tools (владелец уже вошёл)

1. **Добавить оба сайта:** `https://sbfconsult.com/` и `https://lp.sbfconsult.com/`. Быстрее всего — «Import from Google Search Console», если сайты там подтверждены. Иначе подтверждение через DNS: CNAME в Cloudflare, запись даст сам Bing. DNS надёжнее мета-тега: мета-тег потеряется при следующей правке `index.html`.
2. **Sitemaps → Submit:** `https://sbfconsult.com/sitemap.xml`, `https://lp.sbfconsult.com/sitemap.xml`.
3. **IndexNow**, после выкатки A и B:
   ```bash
   python3 <market_intel>/tools/indexnow.py --dry-run   # сколько адресов уйдёт
   python3 <market_intel>/tools/indexnow.py --all       # первый раз — всё
   ```
   Ожидаемый ответ по каждому хосту — HTTP 200 или 202. 403 значит, что ключ-файл не отдаётся: проверить `https://<хост>/7a03d9d8dbb9e212c083081e54ad5773.txt`. Отправленные адреса запоминаются в `data/indexnow_sent.json` (в git не попадает).
   Регулярно — cron раз в час (повторов не будет, скрипт шлёт только новое):
   ```cron
   17 * * * *  cd <market_intel> && python3 tools/indexnow.py >> data/indexnow.log 2>&1
   ```
   плюс вызов из генератора брифа (A6.3).
4. **URL Inspection** в Bing для `/`, `/brief/`, свежего брифа и `lp.../brokers/xm`: страница должна быть «indexed» или «discovered», без блокировки robots.
5. **Яндекс Вебмастер** — то же самое для обоих доменов (Метрика уже стоит). IndexNow Яндекс принимает через тот же `api.indexnow.org`.
6. Через 7–14 дней в Bing Webmaster → Search Performance посмотреть показы по брендовым запросам «SBF Company», «SBF Intelligence».

---

## E. Cloudflare (оба домена)
1. **AI Crawl Control / Security → Bots:** категории Search и Agent (OAI-SearchBot, ChatGPT-User, Claude-SearchBot, PerplexityBot, Bingbot) — **разрешены**. Training — по решению владельца (сейчас robots.txt разрешает).
2. **Scrape Shield → Email Address Obfuscation:** сейчас краулеры видят `[email protected]` вместо контактного email. Выключить для sbfconsult.com (email и так есть в JSON-LD) — на усмотрение владельца.
3. Проверить, что Cloudflare не кэширует `robots.txt` и `sitemap.xml` дольше часа.

---

## F. Приёмка (все команды — снаружи, с любой машины)

```bash
S=https://sbfconsult.com; L=https://lp.sbfconsult.com; K=7a03d9d8dbb9e212c083081e54ad5773
# редиректы и 404
for u in /blank-2 /ru /en /ro /service-page/kurs /qwerty-404 /CLAUDE.md /.git/HEAD; do
  printf "%-22s %s\n" "$u" "$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' $S$u)"; done
#  ожидается: /blank-2 301→/risk.html · /ru|/en|/ro 301→/?lang=… · /service-page/* 301→lp/edu/ · остальное 404
# 200 на нужном
for u in / /risk.html /brief/ /robots.txt /sitemap.xml /llms.txt /$K.txt /cons-kz/; do
  printf "%-22s %s\n" "$u" "$(curl -s -o /dev/null -w '%{http_code}' $S$u)"; done
# формулировки и бренд
curl -s $S/ | grep -c "лицензиями ЕС\|EU-лиценз"            # 0
curl -s $S/ | grep -o '"name": "[^"]*"' | head -1            # "name": "SBF Company"
curl -s $S/ | grep -o '<title>[^<]*'                         # SBF Company — …
# robots
curl -s $S/robots.txt | grep -c "^Disallow"                  # 15 (5 × 3 группы)
curl -s $L/robots.txt | grep -c "^Disallow"                  # 9  (3 × 3 группы)
# lp
curl -s $L/edu/b/7 | grep -o 'noindex, follow'              # есть
curl -s $L/sitemap.xml | grep -c "<loc>"                     # 51
curl -s $L/$K.txt; echo; curl -s $S/$K.txt; echo            # ключ на обоих
```
Дополнительно проверить руками в браузере (скилл `sbf-web-qa`, обязателен после правки видимого UI): переключатель RU/EN/RO на главной, открытие `/?lang=en` в приватном окне сразу даёт английский, карточки партнёров, модалки с лицензиями, мобильная версия дисклеймеров.

**Откат:** `git checkout prod-snapshot-2026-09-30 -- .` в прод-папке + рестарт сервиса.

---

## G. Не входит в эту выкатку (следующие шаги из аудита)
Страницы `/about`, `/team`, `/methodology`, `/partners`, `/faq` на sbfconsult.com. Настоящие URL `/en/`, `/ro/` для главной. Единый `entity.json` как источник фактов. Wikidata, Crunchbase, Google Business Profile. Публичный CSV со статистикой паттернов. PNG-картинка для og:image. Подробности — в разделах P1/P2 аудита.
