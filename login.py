from __future__ import annotations

import asyncio
import argparse
import sqlite3

from telethon import TelegramClient

from main import ConfigError, ensure_user_authorized, ensure_user_authorized_qr, load_config


async def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize the Telethon user session.")
    parser.add_argument(
        "--code",
        action="store_true",
        help="use phone code login instead of QR login",
    )
    args = parser.parse_args()

    config = load_config()
    client = TelegramClient(config.telegram.session_name, config.telegram.api_id, config.telegram.api_hash)
    try:
        if args.code:
            await ensure_user_authorized(client, config.telegram.phone)
        else:
            await ensure_user_authorized_qr(
                client,
                attempts=config.telegram.qr_login_attempts,
                timeout_seconds=config.telegram.qr_login_timeout_seconds,
            )
        print()
        print("[OK] Теперь можно запускать main.py или start.bat.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigError as exc:
        print(f"[CONFIG] {exc}")
        raise SystemExit(1)
    except sqlite3.OperationalError as exc:
        if "database is locked" in str(exc).lower():
            print("[SESSION] Файл сессии занят другим Python-процессом.")
            print("Останови старый запуск с ожиданием кода через Ctrl+C и запусти login.py снова.")
            raise SystemExit(1)
        raise
