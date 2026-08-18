from __future__ import annotations

import asyncio
import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import AuthKeyDuplicatedError

from main import AppConfig, ConfigError, ensure_user_authorized, ensure_user_authorized_qr, load_config


def session_file_path(session_name: str) -> Path:
    session_path = Path(session_name)
    if session_path.suffix != ".session":
        session_path = Path(f"{session_path}.session")
    return session_path


def remove_empty_session(session_name: str) -> bool:
    session_path = session_file_path(session_name)
    if not session_path.exists() or session_path.stat().st_size != 0:
        return False
    session_path.unlink()
    return True


def archive_invalid_session(session_name: str) -> Path:
    session_path = session_file_path(session_name)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = session_path.with_name(f"{session_path.name}.invalid-{timestamp}.bak")
    session_path.replace(backup_path)

    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(f"{session_path}{suffix}")
        if sidecar.exists():
            sidecar.replace(Path(f"{backup_path}{suffix}"))

    return backup_path


async def authorize(config: AppConfig, use_code: bool) -> None:
    if remove_empty_session(config.telegram.session_name):
        print("[SESSION] Удалён пустой session-файл, оставшийся после неудачного восстановления.")

    for attempt in range(2):
        client = TelegramClient(config.telegram.session_name, config.telegram.api_id, config.telegram.api_hash)
        try:
            if use_code:
                await ensure_user_authorized(client, config.telegram.phone)
            else:
                await ensure_user_authorized_qr(
                    client,
                    attempts=config.telegram.qr_login_attempts,
                    timeout_seconds=config.telegram.qr_login_timeout_seconds,
                )
            return
        except AuthKeyDuplicatedError:
            if attempt:
                raise ConfigError(
                    "Telegram снова отклонил новую сессию. Убедись, что этот session-файл не запущен "
                    "и не синхронизируется на другом компьютере/VPS."
                ) from None

            await client.disconnect()
            try:
                backup_path = archive_invalid_session(config.telegram.session_name)
            except FileNotFoundError as exc:
                raise ConfigError(
                    "Telegram аннулировал ключ сессии, но session-файл не найден для пересоздания."
                ) from exc

            print()
            print("[SESSION] Telegram аннулировал старый ключ: session-файл использовался с разных IP.")
            print(f"[SESSION] Недействительная сессия сохранена: {backup_path}")
            print("[SESSION] Создаю новую сессию и продолжаю вход...")
        finally:
            if client.is_connected():
                await client.disconnect()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize the Telethon user session.")
    parser.add_argument(
        "--code",
        action="store_true",
        help="use phone code login instead of QR login",
    )
    args = parser.parse_args()

    config = load_config()
    await authorize(config, args.code)
    print()
    print("[OK] Теперь можно запускать main.py или start.bat.")


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
