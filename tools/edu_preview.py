#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edu_preview.py — стенд для просмотра платных глав 6-15, не трогая прод.

🔴 ЗАЧЕМ. Главы 6-15 закрыты серверным гейтом: _handle_edu спрашивает
journal_auth.is_pro(user_id) и без права отдаёт пейволл. Проверять правки
в этих главах глазами было нечем, и это молча толкает к двум плохим
решениям: либо выдать себе PRO в боевой journal.db (пачкать прод ради
просмотра), либо «проверить» тем, что сборка Babel прошла, — а она
проходит и у страницы, которая падает в первый же useEffect.

Стенд делает третье: копирует journal.db во временный файл, выдаёт право
и сессию В КОПИИ и поднимает второй экземпляр serve.py на свободном порту
с SBF_JOURNAL_DB, указывающим на копию. Боевая база не открывается на
запись ни разу.

Запуск:
    python3 tools/edu_preview.py            # поднять и держать
    python3 tools/edu_preview.py --port 8099

Печатает URL и токен сессии. Токен кладётся в localStorage ключом
sbf_token — так же, как это делает сайт после входа.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
БОЕВАЯ = КОРЕНЬ / "data" / "journal.db"
ПОЛЬЗОВАТЕЛЬ = "edu-preview"


def занят(порт: int) -> bool:
    # SO_REUSEADDR — как у самого serve.py. Без него сокет, оставшийся в
    # TIME_WAIT после только что снятого стенда, считается «занятым»: стенд
    # отказывался стартовать там, где сервер стартовал бы спокойно. Проверка
    # должна отвечать на вопрос «сможет ли подняться сервер», а не «есть ли
    # тут хоть какой-то след сокета».
    с = socket.socket()
    с.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        с.bind(("127.0.0.1", порт))
        return False
    except OSError:
        return True
    finally:
        с.close()


def владельцы(порт: int) -> list[int]:
    """pid'ы прежних стендов: ищем serve.py с нужным SBF_PORT в окружении."""
    найдены = []
    for каталог in Path("/proc").iterdir():
        if not каталог.name.isdigit():
            continue
        try:
            окр = (каталог / "environ").read_bytes().decode("utf-8", "replace")
            if f"SBF_PORT={порт}\0" in окр + "\0":
                найдены.append(int(каталог.name))
        except (OSError, PermissionError):
            continue
    return найдены


def свободный_порт() -> int:
    с = socket.socket()
    с.bind(("127.0.0.1", 0))
    порт = с.getsockname()[1]
    с.close()
    return порт


def подготовить_копию() -> tuple[Path, str]:
    """Копия базы с PRO-правом и живой сессией. Возвращает путь и токен."""
    времянка = Path(tempfile.mkdtemp(prefix="sbf_edu_preview_")) / "journal.db"
    # sqlite3 .backup вместо cp: база под живым сервером, и простое
    # копирование файла может поймать её в середине транзакции.
    ист = sqlite3.connect(f"file:{БОЕВАЯ}?mode=ro", uri=True)
    коп = sqlite3.connect(времянка)
    with коп:
        ист.backup(коп)
    ист.close()

    токен = uuid.uuid4().hex
    до = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    with коп:
        коп.execute("INSERT OR IGNORE INTO users (id, email) VALUES (?,?)",
                    (ПОЛЬЗОВАТЕЛЬ, "edu-preview@localhost"))
        коп.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
                    (токен, ПОЛЬЗОВАТЕЛЬ, до))
        коп.execute("""INSERT OR REPLACE INTO entitlements
                       (user_id, tier, source, expires_ts) VALUES (?,?,?,?)""",
                    (ПОЛЬЗОВАТЕЛЬ, "pro", "survey", до))
    коп.close()
    return времянка, токен


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=0)
    a = p.parse_args()
    порт = a.port or свободный_порт()
    # 🔴 Занятый порт обязан быть слышен. Первый прогон на этом и попался:
    # прошлый стенд оставил осиротевший serve.py на 8099, новый молча не
    # смог подняться — а Playwright продолжал ходить на старый экземпляр со
    # СТАРЫМ кодом и честно показывал, что правки «не применились».
    if занят(порт):
        # Подсказка обязана быть рабочей. Первая версия советовала
        # `pkill -f 'SBF_PORT=...'`, и это не работает: переменная лежит в
        # окружении процесса, а не в его командной строке — pkill по -f её
        # не видит. Ищем владельца порта честно, через /proc.
        print(f"порт {порт} уже занят.")
        for кто in владельцы(порт):
            print(f"  это pid {кто} — снять: kill {кто}")
        print("  либо укажите другой --port")
        return 1

    копия, токен = подготовить_копию()
    окружение = dict(os.environ,
                     SBF_JOURNAL_DB=str(копия),
                     SBF_PORT=str(порт),
                     PORT=str(порт))
    # start_new_session: serve.py уходит в свою группу процессов, и её можно
    # снять целиком. Без этого pkill по имени обёртки убивал только обёртку,
    # а сервер оставался жить и держать порт.
    процесс = subprocess.Popen(
        [str(КОРЕНЬ / ".venv" / "bin" / "python"), "serve.py"],
        cwd=КОРЕНЬ, env=окружение, start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    print(f"копия базы : {копия}")
    print(f"порт       : {порт}")
    print(f"токен      : {токен}")
    print(f"адрес      : http://127.0.0.1:{порт}/edu/b/7")
    print("localStorage.setItem('sbf_token', '<токен>') — и главы 6-15 открыты")
    print("Ctrl+C — остановить и удалить копию")
    try:
        while процесс.poll() is None:
            time.sleep(0.5)
        print(процесс.stdout.read()[-2000:] if процесс.stdout else "")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.killpg(os.getpgid(процесс.pid), signal.SIGTERM)
            процесс.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
        shutil.rmtree(копия.parent, ignore_errors=True)
        print("копия удалена")
    return 0


if __name__ == "__main__":
    sys.exit(main())
