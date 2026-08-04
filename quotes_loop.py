#!/usr/bin/env python3
"""Лёгкий долгоживущий цикл: пишет quotes.json каждые N секунд для живой строки/цены.
Дешевле, чем systemd-таймер раз в 15с. Запускать своим сервисом (Restart=always)."""
import time
from core.logging_setup import setup
import publish

setup("quotes")
INTERVAL = 15
while True:
    try:
        publish.publish_quotes()
    except Exception as e:
        print("quotes error:", e)
    time.sleep(INTERVAL)
