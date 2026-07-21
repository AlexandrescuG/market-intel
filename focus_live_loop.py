#!/usr/bin/env python3
"""Лёгкий долгоживущий цикл: пересчитывает Focus Engine live-состояние
каждые N секунд (§3 "Live" контекст). Тот же шаблон, что quotes_loop.py."""
import time

from core.logging_setup import setup
import focus_live

setup("focus_live")
INTERVAL = 60
while True:
    try:
        focus_live.tick()
    except Exception as e:
        print("focus_live error:", e)
    time.sleep(INTERVAL)
