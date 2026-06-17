# market_intel — конвейер рыночной разведки

Мультиисточниковый сбор сигналов (X / Reddit / RSS) → единая БД → два потребителя:
real-time алерты в Telegram (для контента) и дневной дайджест через Claude Code
(анализ по геополитике / экономике / психологии толпы для трейдеров).

```
collectors/  twitter · reddit · rss   →   core/signals.db   →   ┌─ real-time Telegram алерты
   (нормализуют в "signal", скорят)                             └─ 06:00 build_brief → claude -p → отчёт → Telegram
core/        config · db · scoring · telegram · logging
analyze/     build_brief · prompt.md · run_daily.sh
```

## Установка

```bash
cd market_intel
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # заполни токены/логины
python3 -m core.db            # создать БД

# перенести историю из старого монитора (1144 твита, со скорингом):
python3 migrate_old_db.py /path/to/old/data/threads.db
```

⚠️ **Безопасность:** старый Telegram-токен из `monitor.log` скомпрометирован —
отзови его через @BotFather (`/revoke`) и впиши новый в `.env`. Новый
`logging_setup` больше не пишет токен в лог.

## Запуск

```bash
# 1) первый логин в X — с открытым браузером (HEADLESS=false), сессия сохранится
./run.sh --once --only twitter

# 2) боевой цикл коллекторов (сбор + алерты каждые 20 мин)
./run.sh

# отдельные источники:
./run.sh --once --only rss
./run.sh --once --only reddit
```

## Дневной отчёт в 06:00 (Claude Code headless)

Требуется установленный и авторизованный Claude Code (`claude` в PATH).
Проверь авторизацию один раз вручную: `claude -p "ok" --allowedTools "Read"`.

```bash
chmod +x analyze/run_daily.sh
# тест прямо сейчас:
./analyze/run_daily.sh
```

### cron (локальное время Кишинёва)

```cron
# сбор крутится отдельно (systemd ниже). Тут — только дневной анализ в 06:00:
0 6 * * *  /home/USER/market_intel/analyze/run_daily.sh >> /home/USER/market_intel/data/daily.log 2>&1
```

### systemd (постоянный сбор) — `~/.config/systemd/user/market-intel.service`

```ini
[Unit]
Description=market_intel collectors
After=network-online.target

[Service]
WorkingDirectory=%h/market_intel
ExecStart=%h/market_intel/run.sh
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now market-intel
journalctl --user -u market-intel -f
```

## Тюнинг

- **Анти-шум:** `STORE_MIN_ECON_RELEVANCE` в `.env` (по умолч. 0.25). Выше — строже.
- **Что считать важным:** веса `WEIGHTS` в `core/scoring.py`.
- **Лексиконы тем:** `LEXICONS` в `core/scoring.py` — добавляй термины/тикеры под свои рынки (KZ/ZA).
- **Запросы X:** `TWITTER_QUERIES` в `core/config.py`.
- **Сабреддиты:** `REDDIT_SUBS`. **Ленты:** `RSS_FEEDS`.

## Что тестировалось вживую
RSS-сбор (10 лент), скоринг, БД, миграция 1144 твитов, сборка брифа — рабочие.
Twitter/Reddit-коллекторы требуют твоих кредов/браузера для live-прогона —
логика парсинга перенесена из твоего рабочего `monitor.py`.
