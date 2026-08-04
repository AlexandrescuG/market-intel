#!/usr/bin/env python3
"""Назначить пользователя администратором.

Запуск:
  python3 tools/make_admin.py <email_or_user_id>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import journal_auth, journal_feedback


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 tools/make_admin.py <email_или_user_id>")
        sys.exit(1)

    identifier = sys.argv[1].strip()

    # Поиск по email
    import sqlite3
    db_path = Path(__file__).parent.parent / "data" / "journal.db"
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row

    if "@" in identifier:
        row = con.execute(
            "SELECT id FROM users WHERE email=?", (identifier.lower(),)
        ).fetchone()
        if not row:
            print(f"Пользователь с email '{identifier}' не найден")
            con.close()
            sys.exit(1)
        user_id = row["id"]
    else:
        row = con.execute("SELECT id FROM users WHERE id=?", (identifier,)).fetchone()
        if not row:
            print(f"Пользователь с id '{identifier}' не найден")
            con.close()
            sys.exit(1)
        user_id = row["id"]
    con.close()

    result = journal_feedback.add_admin(user_id)
    if result["ok"]:
        print(f"✓ {identifier} назначен администратором (user_id={user_id})")
    else:
        print(f"Ошибка: {result}")


if __name__ == "__main__":
    main()
