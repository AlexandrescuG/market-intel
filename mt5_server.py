#!/usr/bin/env python3
"""
mt5_server.py — rpyc Slave Server для mt5linux.

Этот скрипт запускается ВНУТРИ Wine Python (Windows окружение).
Слушает порт 18812 и предоставляет доступ к MetaTrader5 Python API.

Запуск (внутри Wine):
    python.exe mt5_server.py
или через start_mt5_server.sh (с нужным WINEPREFIX).

После запуска MT5 терминал должен быть открыт в той же бутылке.
"""
import sys
import rpyc
from rpyc.utils.server import ThreadedServer
from rpyc.core import SlaveService

HOST = "127.0.0.1"
PORT = 18812


# Консоль Wine/Windows по умолчанию в cp1252 (не UTF-8) — кириллица здесь
# роняла процесс с UnicodeEncodeError ДО того, как сервер успевал забиндить
# порт. Только ASCII в print() внутри этого файла.
print(f"mt5_server: starting rpyc SlaveService on {HOST}:{PORT}", flush=True)
print("Ctrl+C to stop.", flush=True)

t = ThreadedServer(
    SlaveService,
    hostname=HOST,
    port=PORT,
    reuse_addr=True,
)
t.start()
