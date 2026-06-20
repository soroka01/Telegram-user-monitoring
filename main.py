from __future__ import annotations

import asyncio
import getpass
import hashlib
import html
import json
import logging
import mimetypes
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from telethon import TelegramClient, functions, types, utils
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    RPCError,
    SessionPasswordNeededError,
)


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_ADMIN_ID = 123456789
MAX_BOT_MESSAGE = 4096
SCHEMA_VERSION = 2

USERNAME_RE = re.compile(r"^@?[A-Za-z0-9_]{5,32}$")
ID_WITH_HASH_RE = re.compile(r"^(?:id:)?(?P<id>-?\d+)\s*:\s*(?P<hash>-?\d+)$", re.IGNORECASE)
ID_PREFIX_RE = re.compile(r"^id:(?P<id>-?\d+)$", re.IGNORECASE)
DAYS_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


class ConfigError(RuntimeError):
    pass


class TargetResolveError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    phone: str | None
    session_name: str
    qr_login_attempts: int
    qr_login_timeout_seconds: int


@dataclass(frozen=True)
class BotConfig:
    token: str
    admin_ids: set[int]


@dataclass(frozen=True)
class MonitorConfig:
    targets: list[str]
    interval_seconds: int
    request_delay_seconds: float
    profile_photo_limit: int
    gift_limit: int
    max_photos_per_event: int
    send_photos: bool
    notify_initial_snapshot: bool
    track_online_status: bool
    timezone_name: str
    state_path: Path
    events_path: Path
    media_dir: Path


@dataclass(frozen=True)
class AppConfig:
    telegram: TelegramConfig
    bot: BotConfig
    monitor: MonitorConfig


@dataclass
class SnapshotBundle:
    snapshot: dict[str, Any]
    photo_objects: dict[str, Any]
    music_document: Any | None = None


@dataclass
class CheckResult:
    target: str
    ok: bool
    profile_id: str | None = None
    display_name: str | None = None
    changes_count: int = 0
    baseline: bool = False
    error: str | None = None


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Не найден {path}. Скопируй config.example.json в config.json.")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Ошибка JSON в {path}: {exc}") from exc


def env_or_value(env_name: str, value: Any) -> Any:
    env_value = os.getenv(env_name)
    return env_value if env_value not in (None, "") else value


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "да"}


def parse_admin_ids(raw: Any) -> set[int]:
    if raw in (None, ""):
        return {DEFAULT_ADMIN_ID}
    if isinstance(raw, int):
        return {raw}
    if isinstance(raw, str):
        chunks = [item.strip() for item in raw.split(",")]
    else:
        chunks = [str(item).strip() for item in raw]

    ids = {int(item) for item in chunks if item}
    return ids or {DEFAULT_ADMIN_ID}


def parse_targets(raw: Any) -> list[str]:
    env_targets = os.getenv("MONITOR_TARGETS")
    if env_targets:
        raw = env_targets

    if isinstance(raw, str):
        targets = [item.strip() for item in raw.split(",")]
    else:
        targets = [str(item).strip() for item in raw or []]

    return [item for item in targets if item]


def resolve_path(raw: Any, default: str) -> Path:
    value = str(raw or default).strip()
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def validate_secret(name: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.startswith("PUT_") or text.startswith("YOUR_"):
        raise ConfigError(f"Заполни {name} в config.json или через переменную окружения.")
    return text


def load_config() -> AppConfig:
    raw = load_json(CONFIG_PATH)
    telegram_raw = raw.get("telegram", {})
    bot_raw = raw.get("bot", {})
    monitor_raw = raw.get("monitor", {})

    api_id_raw = env_or_value("TG_API_ID", telegram_raw.get("api_id"))
    try:
        api_id = int(api_id_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError("telegram.api_id должен быть числом.") from exc

    api_hash = validate_secret("telegram.api_hash", env_or_value("TG_API_HASH", telegram_raw.get("api_hash")))
    bot_token = validate_secret("bot.token", env_or_value("BOT_TOKEN", bot_raw.get("token")))

    admin_ids = parse_admin_ids(env_or_value("ADMIN_IDS", bot_raw.get("admin_ids", bot_raw.get("admin_id"))))
    targets = parse_targets(monitor_raw.get("targets", []))
    if not targets:
        raise ConfigError("Добавь хотя бы одну цель в monitor.targets.")

    session_path = resolve_path(telegram_raw.get("session_name"), "user_monitor_account")

    monitor = MonitorConfig(
        targets=targets,
        interval_seconds=max(30, int(monitor_raw.get("interval_seconds", 300))),
        request_delay_seconds=max(0.0, float(monitor_raw.get("request_delay_seconds", 1.0))),
        profile_photo_limit=max(1, int(monitor_raw.get("profile_photo_limit", 20))),
        gift_limit=max(1, int(monitor_raw.get("gift_limit", 200))),
        max_photos_per_event=max(0, int(monitor_raw.get("max_photos_per_event", 5))),
        send_photos=parse_bool(monitor_raw.get("send_photos", True), True),
        notify_initial_snapshot=parse_bool(monitor_raw.get("notify_initial_snapshot", True), True),
        track_online_status=parse_bool(monitor_raw.get("track_online_status", False), False),
        timezone_name=str(monitor_raw.get("timezone", "Asia/Yekaterinburg")),
        state_path=resolve_path(monitor_raw.get("state_path"), "state/profile_state.json"),
        events_path=resolve_path(monitor_raw.get("events_path"), "logs/profile_events.jsonl"),
        media_dir=resolve_path(monitor_raw.get("media_dir"), "media"),
    )

    return AppConfig(
        telegram=TelegramConfig(
            api_id=api_id,
            api_hash=api_hash,
            phone=str(env_or_value("TG_PHONE", telegram_raw.get("phone")) or "").strip() or None,
            session_name=str(session_path),
            qr_login_attempts=max(1, int(telegram_raw.get("qr_login_attempts", 10))),
            qr_login_timeout_seconds=max(15, int(telegram_raw.get("qr_login_timeout_seconds", 55))),
        ),
        bot=BotConfig(token=bot_token, admin_ids=admin_ids),
        monitor=monitor,
    )


def get_timezone(name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logging.warning("Unknown timezone %s, using UTC", name)
        return timezone.utc


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_now_iso(tz: timezone | ZoneInfo) -> str:
    return datetime.now(tz).isoformat(timespec="seconds")


def ensure_dirs(config: AppConfig) -> None:
    config.monitor.state_path.parent.mkdir(parents=True, exist_ok=True)
    config.monitor.events_path.parent.mkdir(parents=True, exist_ok=True)
    config.monitor.media_dir.mkdir(parents=True, exist_ok=True)


def setup_logging(config: AppConfig) -> None:
    log_path = config.monitor.events_path.parent / "monitor.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )


def sent_code_description(sent_code: Any) -> str:
    code_type = getattr(sent_code, "type", None)
    type_name = code_type.__class__.__name__ if code_type is not None else "unknown"
    next_type = getattr(sent_code, "next_type", None)
    timeout = getattr(sent_code, "timeout", None)

    if type_name == "SentCodeTypeApp":
        place = "в официальный чат Telegram на уже залогиненном устройстве"
    elif type_name == "SentCodeTypeSms":
        place = "по SMS"
    elif type_name == "SentCodeTypeCall":
        place = "звонком"
    elif type_name == "SentCodeTypeFragmentSms":
        place = "через Fragment/SMS"
    elif type_name == "SentCodeTypeFirebaseSms":
        place = "через Firebase/SMS"
    else:
        place = f"тип доставки: {type_name}"

    details = [place]
    if next_type is not None:
        details.append(f"следующий вариант: {next_type.__class__.__name__}")
    if timeout:
        details.append(f"повтор обычно доступен через {timeout} сек")
    return ", ".join(details)


async def ensure_user_authorized(client: TelegramClient, phone: str | None) -> None:
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"[OK] Telethon-сессия уже авторизована: {user_display(me)}")
        return

    if not phone:
        raise ConfigError("Для первого входа нужен telegram.phone в config.json.")

    print()
    print("Нужен вход в пользовательский Telegram-аккаунт для Telethon.")
    print("Код приходит НЕ в бота, а в официальный чат Telegram на твоих Telegram-клиентах.")
    print("Если Telegram разрешит SMS, введи sms. Для повторной отправки введи resend. Для выхода введи exit.")
    print()

    try:
        sent_code = await client.send_code_request(phone)
    except PhoneNumberInvalidError as exc:
        raise ConfigError("telegram.phone указан неверно. Нужен международный формат, например +79990000000.") from exc
    except FloodWaitError as exc:
        raise ConfigError(f"Telegram ограничил запросы кодов. Подожди {exc.seconds} сек.") from exc

    while True:
        print(f"[CODE] Код отправлен: {sent_code_description(sent_code)}")
        code = input("Введи код Telegram, sms, resend или exit: ").strip()
        command = code.lower()

        if command in {"exit", "quit", "q"}:
            raise ConfigError("Вход отменен пользователем.")

        if command in {"sms", "смс"}:
            try:
                sent_code = await client.send_code_request(phone, force_sms=True)
            except FloodWaitError as exc:
                print(f"[WAIT] Telegram просит подождать {exc.seconds} сек перед новым кодом.")
            except RPCError as exc:
                print(f"[WARN] Telegram не дал запросить SMS: {type(exc).__name__}: {exc}")
            continue

        if command in {"resend", "again", "повтор", "заново"}:
            try:
                sent_code = await client.send_code_request(phone)
            except FloodWaitError as exc:
                print(f"[WAIT] Telegram просит подождать {exc.seconds} сек перед новым кодом.")
            except RPCError as exc:
                print(f"[WARN] Повторная отправка не удалась: {type(exc).__name__}: {exc}")
            continue

        code = code.replace(" ", "").replace("-", "")
        if not code:
            continue

        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=sent_code.phone_code_hash)
        except SessionPasswordNeededError:
            password = getpass.getpass("Введи пароль 2FA Telegram: ")
            await client.sign_in(password=password)
        except PhoneCodeInvalidError:
            print("[ERROR] Неверный код. Проверь официальный чат Telegram и введи код без пробелов.")
            continue
        except PhoneCodeExpiredError:
            print("[ERROR] Код устарел. Запрашиваю новый.")
            sent_code = await client.send_code_request(phone)
            continue

        me = await client.get_me()
        print(f"[OK] Вход выполнен, сессия сохранена: {user_display(me)}")
        return


def print_qr_login_url(url: str) -> None:
    print()
    print("Открой Telegram на телефоне:")
    print("Настройки -> Устройства -> Подключить устройство")
    print("Потом отсканируй QR ниже.")
    print()
    print("Если QR не виден, открой эту ссылку из Telegram Desktop:")
    print(url)

    try:
        import qrcode
    except ImportError:
        print()
        print("Для красивого QR в консоли можно установить:")
        print(f'"{sys.executable}" -m pip install "qrcode[pil]"')
        return

    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    print()
    qr.print_ascii(invert=True)
    print()


async def ensure_user_authorized_qr(
    client: TelegramClient,
    attempts: int = 10,
    timeout_seconds: int = 55,
) -> None:
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"[OK] Telethon-сессия уже авторизована: {user_display(me)}")
        return

    print()
    print("Запускаю QR-вход вместо кода.")
    print("Это обычно надежнее, если Telegram пишет 'код отправлен в приложение', но код не появляется.")

    try:
        for attempt in range(1, attempts + 1):
            qr_login = await client.qr_login()
            print(f"\n[QR] Попытка {attempt}/{attempts}")
            print_qr_login_url(qr_login.url)

            try:
                await qr_login.wait(timeout=timeout_seconds)
                break
            except TimeoutError:
                if attempt == attempts:
                    raise ConfigError("QR устарел и попытки закончились. Запусти login.py еще раз.") from None
                print("[QR] QR устарел, создаю новый...")
            except SessionPasswordNeededError:
                password = getpass.getpass("Введи пароль 2FA Telegram: ")
                await client.sign_in(password=password)
                break
    except FloodWaitError as exc:
        raise ConfigError(f"Telegram ограничил QR-вход. Подожди {exc.seconds} сек.") from exc

    if not await client.is_user_authorized():
        raise ConfigError("QR-вход не завершился. Проверь, что сканируешь именно из Telegram: Настройки -> Устройства.")

    me = await client.get_me()
    print(f"[OK] Вход выполнен, сессия сохранена: {user_display(me)}")


def compact_json(value: Any, limit: int = 700) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


VOLATILE_COMPARE_KEYS = {
    "raw",
    "file_reference",
    "stripped_thumb",
    "bytes_len",
    "hex_prefix",
    "availability_issued",
    "availability_total",
    "value_amount",
    "value_currency",
    "value_usd_amount",
    "resell_amount",
    "offer_min_stars",
    "resell_min_stars",
    "availability_resale",
}


def strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_volatile(item)
            for key, item in value.items()
            if key not in VOLATILE_COMPARE_KEYS
        }
    if isinstance(value, list):
        return [strip_volatile(item) for item in value]
    if isinstance(value, tuple):
        return [strip_volatile(item) for item in value]
    return value


def profile_compare_value(path: str, value: Any) -> Any:
    value = strip_volatile(value)
    if path == "personal_channel" and isinstance(value, dict):
        return {key: item for key, item in value.items() if key not in {"message_id", "link"}}
    return value


def tl_to_plain(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return repr(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, bytes):
        return {"bytes_len": len(value), "hex_prefix": value[:16].hex()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): tl_to_plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [tl_to_plain(item, depth + 1) for item in value]
    if hasattr(value, "to_dict"):
        try:
            return tl_to_plain(value.to_dict(), depth + 1)
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {
            key: tl_to_plain(item, depth + 1)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return repr(value)


def html_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def one_line(value: Any, limit: int = 240) -> str:
    if value is None:
        return "нет"
    if value == "":
        return "пусто"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (dict, list)):
        text = compact_json(value, limit)
    else:
        text = str(value)
    text = text.replace("\n", " ").strip()
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def format_value(value: Any, limit: int = 260) -> str:
    return f"<code>{html_escape(one_line(value, limit))}</code>"


def text_with_entities(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    text = getattr(value, "text", None)
    if text is None:
        return {"text": str(value), "entities": []}
    return {"text": text, "entities": tl_to_plain(getattr(value, "entities", []))}


def document_summary(document: Any) -> dict[str, Any] | None:
    if document is None:
        return None
    attrs = []
    alt = None
    title = None
    performer = None
    duration = None
    voice = None
    file_name = None
    for attr in getattr(document, "attributes", []) or []:
        attr_name = attr.__class__.__name__
        attr_data = {"type": attr_name}
        if hasattr(attr, "alt"):
            alt = getattr(attr, "alt")
            attr_data["alt"] = alt
        if hasattr(attr, "duration"):
            duration = getattr(attr, "duration")
            attr_data["duration"] = duration
        if hasattr(attr, "voice"):
            voice = bool(getattr(attr, "voice"))
            attr_data["voice"] = voice
        if hasattr(attr, "title"):
            title = getattr(attr, "title")
            attr_data["title"] = title
        if hasattr(attr, "performer"):
            performer = getattr(attr, "performer")
            attr_data["performer"] = performer
        if hasattr(attr, "file_name"):
            file_name = getattr(attr, "file_name")
            attr_data["file_name"] = file_name
        if hasattr(attr, "stickerset"):
            attr_data["stickerset"] = tl_to_plain(getattr(attr, "stickerset"))
        attrs.append(attr_data)

    return {
        "id": str(getattr(document, "id", "")),
        "mime_type": getattr(document, "mime_type", None),
        "size": getattr(document, "size", None),
        "dc_id": getattr(document, "dc_id", None),
        "alt": alt,
        "title": title,
        "performer": performer,
        "duration": duration,
        "voice": voice,
        "file_name": file_name,
        "attributes": attrs,
    }


def user_display(user: Any) -> str:
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    username = getattr(user, "username", None)
    name = " ".join(part for part in (first, last) if part).strip()
    parts = []
    if name:
        parts.append(name)
    if username:
        parts.append(f"@{username}")
    if not parts:
        parts.append(f"id {getattr(user, 'id', 'unknown')}")
    return " ".join(parts)


def chat_display(chat: Any) -> str:
    title = getattr(chat, "title", None)
    username = getattr(chat, "username", None)
    parts = []
    if title:
        parts.append(title)
    if username:
        parts.append(f"@{username}")
    if not parts:
        parts.append(f"id {getattr(chat, 'id', 'unknown')}")
    return " ".join(parts)


def normalize_public_usernames(user: Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    primary = getattr(user, "username", None)
    if primary:
        seen.add(primary.lower())
        items.append({"username": primary, "primary": True, "active": True, "editable": None})

    for item in getattr(user, "usernames", []) or []:
        username = getattr(item, "username", None)
        if not username or username.lower() in seen:
            continue
        seen.add(username.lower())
        items.append(
            {
                "username": username,
                "primary": False,
                "active": bool(getattr(item, "active", False)),
                "editable": bool(getattr(item, "editable", False)),
            }
        )
    return items


def normalize_emoji_status(status: Any) -> dict[str, Any] | None:
    if status is None or isinstance(status, types.EmojiStatusEmpty):
        return None
    data: dict[str, Any] = {"type": status.__class__.__name__}
    for field in (
        "document_id",
        "collectible_id",
        "title",
        "slug",
        "pattern_document_id",
        "center_color",
        "edge_color",
        "pattern_color",
        "text_color",
    ):
        if hasattr(status, field):
            value = getattr(status, field)
            data[field] = str(value) if field.endswith("_id") or field == "document_id" else value
    until = getattr(status, "until", None)
    if until:
        data["until"] = tl_to_plain(until)
    return data


def emoji_status_html(data: dict[str, Any] | None) -> str:
    if not data:
        return "нет"
    document_id = data.get("document_id")
    if document_id:
        badge = f'<tg-emoji emoji-id="{html_escape(document_id)}">⭐</tg-emoji>'
        details = [f"id {document_id}"]
        if data.get("until"):
            details.append(f"до {data['until']}")
        return f"{badge} ({html_escape(', '.join(details))})"

    badge = ""
    title = data.get("title") or data.get("type") or "есть"
    details = []
    if data.get("until"):
        details.append(f"до {data['until']}")
    tail = f" ({', '.join(details)})" if details else ""
    return f"{badge}{html_escape(title)}{html_escape(tail)}"


def normalize_peer_color(color: Any) -> dict[str, Any] | None:
    if color is None:
        return None
    return {
        "color": getattr(color, "color", None),
        "background_emoji_id": str(getattr(color, "background_emoji_id", "")) or None,
        "raw": tl_to_plain(color),
    }


def minute_to_day_time(total_minutes: int) -> tuple[str, str]:
    day_idx = (total_minutes // 1440) % 7
    minute = total_minutes % 1440
    return DAYS_RU[day_idx], f"{minute // 60:02d}:{minute % 60:02d}"


def normalize_work_hours(work_hours: Any) -> dict[str, Any] | None:
    if work_hours is None:
        return None
    weekly = []
    for item in getattr(work_hours, "weekly_open", []) or []:
        start_day, start_time = minute_to_day_time(int(getattr(item, "start_minute", 0)))
        end_day, end_time = minute_to_day_time(int(getattr(item, "end_minute", 0)))
        weekly.append(
            {
                "start_minute": getattr(item, "start_minute", None),
                "end_minute": getattr(item, "end_minute", None),
                "human": f"{start_day} {start_time} - {end_day} {end_time}",
            }
        )
    return {
        "timezone_id": getattr(work_hours, "timezone_id", None),
        "open_now": bool(getattr(work_hours, "open_now", False)),
        "weekly_open": weekly,
    }


def build_chat_map(chats: Iterable[Any]) -> dict[int, Any]:
    return {int(getattr(chat, "id")): chat for chat in chats if getattr(chat, "id", None) is not None}


def build_user_map(users: Iterable[Any]) -> dict[int, Any]:
    return {int(getattr(user, "id")): user for user in users if getattr(user, "id", None) is not None}


def peer_key(peer: Any) -> str | None:
    if peer is None:
        return None
    if isinstance(peer, types.PeerUser):
        return f"user:{peer.user_id}"
    if isinstance(peer, types.PeerChat):
        return f"chat:{peer.chat_id}"
    if isinstance(peer, types.PeerChannel):
        return f"channel:{peer.channel_id}"
    return compact_json(tl_to_plain(peer), 160)


def peer_label(peer: Any, user_map: dict[int, Any], chat_map: dict[int, Any]) -> str | None:
    if peer is None:
        return None
    if isinstance(peer, types.PeerUser):
        user = user_map.get(int(peer.user_id))
        return user_display(user) if user else f"user id {peer.user_id}"
    if isinstance(peer, types.PeerChat):
        chat = chat_map.get(int(peer.chat_id))
        return chat_display(chat) if chat else f"chat id {peer.chat_id}"
    if isinstance(peer, types.PeerChannel):
        chat = chat_map.get(int(peer.channel_id))
        return chat_display(chat) if chat else f"channel id {peer.channel_id}"
    return one_line(tl_to_plain(peer), 160)


def normalize_personal_channel(full_user: Any, chat_map: dict[int, Any]) -> dict[str, Any] | None:
    channel_id = getattr(full_user, "personal_channel_id", None)
    message_id = getattr(full_user, "personal_channel_message", None)
    if channel_id is None and message_id is None:
        return None

    chat = chat_map.get(int(channel_id)) if channel_id is not None else None
    username = getattr(chat, "username", None) if chat else None
    return {
        "id": channel_id,
        "message_id": message_id,
        "title": getattr(chat, "title", None) if chat else None,
        "username": username,
        "link": f"https://t.me/{username}/{message_id}" if username and message_id else None,
    }


def normalize_birthday(birthday: Any) -> dict[str, Any] | None:
    if birthday is None:
        return None
    return {
        "day": getattr(birthday, "day", None),
        "month": getattr(birthday, "month", None),
        "year": getattr(birthday, "year", None),
    }


def normalize_business_intro(intro: Any) -> dict[str, Any] | None:
    if intro is None:
        return None
    return {
        "title": getattr(intro, "title", None),
        "description": getattr(intro, "description", None),
        "sticker": document_summary(getattr(intro, "sticker", None)),
    }


def normalize_business_location(location: Any) -> dict[str, Any] | None:
    if location is None:
        return None
    return {
        "address": getattr(location, "address", None),
        "geo_point": tl_to_plain(getattr(location, "geo_point", None)),
    }


def normalize_photo(photo: Any) -> dict[str, Any]:
    sizes = []
    for size in getattr(photo, "sizes", []) or []:
        sizes.append(
            {
                "type": getattr(size, "type", None),
                "w": getattr(size, "w", None),
                "h": getattr(size, "h", None),
                "size": getattr(size, "size", None),
            }
        )
    return {
        "id": str(getattr(photo, "id", "")),
        "date": tl_to_plain(getattr(photo, "date", None)),
        "dc_id": getattr(photo, "dc_id", None),
        "has_stickers": bool(getattr(photo, "has_stickers", False)),
        "sizes": sizes,
    }


def normalize_profile_photo(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    photo_id = getattr(value, "photo_id", None) or getattr(value, "id", None)
    return {
        "id": str(photo_id) if photo_id is not None else None,
        "dc_id": getattr(value, "dc_id", None),
        "has_video": bool(getattr(value, "has_video", False)),
        "personal": bool(getattr(value, "personal", False)),
    }


def normalize_flags(user: Any, full_user: Any) -> dict[str, Any]:
    user_flags = [
        "deleted",
        "bot",
        "verified",
        "restricted",
        "scam",
        "fake",
        "premium",
        "contact_require_premium",
        "stories_hidden",
        "stories_unavailable",
        "bot_business",
    ]
    full_flags = [
        "blocked",
        "phone_calls_available",
        "phone_calls_private",
        "video_calls_available",
        "voice_messages_forbidden",
        "translations_disabled",
        "stories_pinned_available",
        "blocked_my_stories_from",
        "wallpaper_overridden",
        "contact_require_premium",
        "read_dates_private",
        "display_gifts_button",
        "noforwards_my_enabled",
        "noforwards_peer_enabled",
        "unofficial_security_risk",
    ]
    return {
        "user": {field: bool(getattr(user, field, False)) for field in user_flags},
        "full": {field: bool(getattr(full_user, field, False)) for field in full_flags},
    }


def normalize_status(status: Any) -> dict[str, Any] | None:
    if status is None:
        return None
    data = {"type": status.__class__.__name__}
    for field in ("expires", "was_online", "by_me"):
        if hasattr(status, field):
            data[field] = tl_to_plain(getattr(status, field))
    return data


def normalize_profile(
    user: Any,
    full_user: Any,
    chat_map: dict[int, Any],
    track_online_status: bool,
) -> dict[str, Any]:
    profile = {
        "first_name": getattr(user, "first_name", None),
        "last_name": getattr(user, "last_name", None),
        "username": getattr(user, "username", None),
        "public_usernames": normalize_public_usernames(user),
        "premium": bool(getattr(user, "premium", False)),
        "emoji_status": normalize_emoji_status(getattr(user, "emoji_status", None)),
        "bio": getattr(full_user, "about", None),
        "birthday": normalize_birthday(getattr(full_user, "birthday", None)),
        "personal_channel": normalize_personal_channel(full_user, chat_map),
        "business_work_hours": normalize_work_hours(getattr(full_user, "business_work_hours", None)),
        "business_location": normalize_business_location(getattr(full_user, "business_location", None)),
        "business_intro": normalize_business_intro(getattr(full_user, "business_intro", None)),
        "business_greeting_message": tl_to_plain(getattr(full_user, "business_greeting_message", None)),
        "business_away_message": tl_to_plain(getattr(full_user, "business_away_message", None)),
        "profile_color": normalize_peer_color(getattr(user, "profile_color", None)),
        "name_color": normalize_peer_color(getattr(user, "color", None)),
        "theme": tl_to_plain(getattr(full_user, "theme", None)),
        "wallpaper": tl_to_plain(getattr(full_user, "wallpaper", None)),
        "main_tab": tl_to_plain(getattr(full_user, "main_tab", None)),
        "saved_music": document_summary(getattr(full_user, "saved_music", None)),
        "note": text_with_entities(getattr(full_user, "note", None)),
        "stargifts_count": getattr(full_user, "stargifts_count", None),
        "stars_rating": tl_to_plain(getattr(full_user, "stars_rating", None)),
        "send_paid_messages_stars": getattr(full_user, "send_paid_messages_stars", None),
        "common_chats_count": getattr(full_user, "common_chats_count", None),
        "current_photo": normalize_profile_photo(getattr(user, "photo", None)),
        "profile_photo": normalize_profile_photo(getattr(full_user, "profile_photo", None)),
        "personal_photo": normalize_profile_photo(getattr(full_user, "personal_photo", None)),
        "fallback_photo": normalize_profile_photo(getattr(full_user, "fallback_photo", None)),
        "flags": normalize_flags(user, full_user),
    }
    if track_online_status:
        profile["online_status"] = normalize_status(getattr(user, "status", None))
    return profile


def gift_sticker_alt(gift: Any) -> str | None:
    sticker = getattr(gift, "sticker", None)
    if sticker is None:
        return None
    alt = getattr(sticker, "alt", None)
    if alt:
        return alt
    for attr in getattr(sticker, "attributes", []) or []:
        if hasattr(attr, "alt"):
            return getattr(attr, "alt")
    return None


def gift_title(gift: Any) -> str:
    if isinstance(gift, types.StarGiftUnique):
        title = getattr(gift, "title", None) or "Unique gift"
        num = getattr(gift, "num", None)
        return f"{title} #{num}" if num is not None else title
    title = getattr(gift, "title", None)
    if title:
        return title
    alt = gift_sticker_alt(gift)
    if alt:
        return alt
    gift_id = getattr(gift, "id", None)
    return f"Gift {gift_id}" if gift_id is not None else "Gift"


def normalize_original_details(attr: Any, user_map: dict[int, Any], chat_map: dict[int, Any]) -> dict[str, Any]:
    return {
        "sender": peer_label(getattr(attr, "sender_id", None), user_map, chat_map),
        "sender_peer": peer_key(getattr(attr, "sender_id", None)),
        "recipient": peer_label(getattr(attr, "recipient_id", None), user_map, chat_map),
        "recipient_peer": peer_key(getattr(attr, "recipient_id", None)),
        "date": tl_to_plain(getattr(attr, "date", None)),
        "message": text_with_entities(getattr(attr, "message", None)),
    }


def normalize_gift_attributes(gift: Any, user_map: dict[int, Any], chat_map: dict[int, Any]) -> list[dict[str, Any]]:
    items = []
    for attr in getattr(gift, "attributes", []) or []:
        attr_type = attr.__class__.__name__
        if isinstance(attr, types.StarGiftAttributeOriginalDetails):
            items.append({"type": attr_type, **normalize_original_details(attr, user_map, chat_map)})
        elif isinstance(attr, (types.StarGiftAttributeModel, types.StarGiftAttributePattern)):
            items.append(
                {
                    "type": attr_type,
                    "name": getattr(attr, "name", None),
                    "rarity": tl_to_plain(getattr(attr, "rarity", None)),
                    "document": document_summary(getattr(attr, "document", None)),
                    "crafted": bool(getattr(attr, "crafted", False)),
                }
            )
        elif isinstance(attr, types.StarGiftAttributeBackdrop):
            items.append(
                {
                    "type": attr_type,
                    "name": getattr(attr, "name", None),
                    "backdrop_id": getattr(attr, "backdrop_id", None),
                    "center_color": getattr(attr, "center_color", None),
                    "edge_color": getattr(attr, "edge_color", None),
                    "pattern_color": getattr(attr, "pattern_color", None),
                    "text_color": getattr(attr, "text_color", None),
                    "rarity": tl_to_plain(getattr(attr, "rarity", None)),
                }
            )
        else:
            items.append(tl_to_plain(attr))
    return items


def normalize_gift(saved: Any, user_map: dict[int, Any], chat_map: dict[int, Any]) -> dict[str, Any]:
    gift = getattr(saved, "gift", None)
    gift_data: dict[str, Any] = {
        "type": gift.__class__.__name__ if gift is not None else None,
        "title": gift_title(gift) if gift is not None else None,
        "sticker_emoji": gift_sticker_alt(gift) if gift is not None else None,
        "raw": tl_to_plain(gift),
    }

    if isinstance(gift, types.StarGiftUnique):
        gift_data.update(
            {
                "id": getattr(gift, "id", None),
                "gift_id": getattr(gift, "gift_id", None),
                "slug": getattr(gift, "slug", None),
                "num": getattr(gift, "num", None),
                "availability_issued": getattr(gift, "availability_issued", None),
                "availability_total": getattr(gift, "availability_total", None),
                "owner": peer_label(getattr(gift, "owner_id", None), user_map, chat_map)
                or getattr(gift, "owner_name", None),
                "owner_peer": peer_key(getattr(gift, "owner_id", None)),
                "owner_address": getattr(gift, "owner_address", None),
                "gift_address": getattr(gift, "gift_address", None),
                "value_amount": getattr(gift, "value_amount", None),
                "value_currency": getattr(gift, "value_currency", None),
                "value_usd_amount": getattr(gift, "value_usd_amount", None),
                "attributes": normalize_gift_attributes(gift, user_map, chat_map),
            }
        )
    elif gift is not None:
        gift_data.update(
            {
                "id": getattr(gift, "id", None),
                "stars": getattr(gift, "stars", None),
                "convert_stars": getattr(gift, "convert_stars", None),
                "limited": bool(getattr(gift, "limited", False)),
                "sold_out": bool(getattr(gift, "sold_out", False)),
                "birthday": bool(getattr(gift, "birthday", False)),
                "require_premium": bool(getattr(gift, "require_premium", False)),
                "availability_remains": getattr(gift, "availability_remains", None),
                "availability_total": getattr(gift, "availability_total", None),
                "availability_resale": getattr(gift, "availability_resale", None),
                "upgrade_stars": getattr(gift, "upgrade_stars", None),
                "resell_min_stars": getattr(gift, "resell_min_stars", None),
                "released_by": peer_label(getattr(gift, "released_by", None), user_map, chat_map),
                "background": tl_to_plain(getattr(gift, "background", None)),
                "sticker": document_summary(getattr(gift, "sticker", None)),
            }
        )

    message = text_with_entities(getattr(saved, "message", None))
    data = {
        "key": "",
        "saved_id": getattr(saved, "saved_id", None),
        "msg_id": getattr(saved, "msg_id", None),
        "date": tl_to_plain(getattr(saved, "date", None)),
        "from": peer_label(getattr(saved, "from_id", None), user_map, chat_map),
        "from_peer": peer_key(getattr(saved, "from_id", None)),
        "message": message,
        "name_hidden": bool(getattr(saved, "name_hidden", False)),
        "unsaved": bool(getattr(saved, "unsaved", False)),
        "refunded": bool(getattr(saved, "refunded", False)),
        "can_upgrade": bool(getattr(saved, "can_upgrade", False)),
        "pinned_to_top": bool(getattr(saved, "pinned_to_top", False)),
        "upgrade_separate": bool(getattr(saved, "upgrade_separate", False)),
        "convert_stars": getattr(saved, "convert_stars", None),
        "upgrade_stars": getattr(saved, "upgrade_stars", None),
        "transfer_stars": getattr(saved, "transfer_stars", None),
        "collection_id": getattr(saved, "collection_id", None),
        "gift_num": getattr(saved, "gift_num", None),
        "gift": gift_data,
        "raw": tl_to_plain(saved),
    }

    slug = gift_data.get("slug")
    if slug:
        data["key"] = f"unique:{slug}"
    elif data["saved_id"] is not None:
        data["key"] = f"saved:{data['saved_id']}"
    elif data["msg_id"] is not None and data["from_peer"]:
        data["key"] = f"msg:{data['from_peer']}:{data['msg_id']}"
    else:
        data["key"] = "gift:" + stable_hash(
            {
                "gift": gift_data.get("id") or gift_data.get("gift_id"),
                "date": data["date"],
                "from": data["from_peer"],
                "message": message,
            }
        )
    data["digest"] = stable_hash(strip_volatile({key: value for key, value in data.items() if key != "digest"}))
    return data


class StateStore:
    def __init__(self, path: Path, events_path: Path) -> None:
        self.path = path
        self.events_path = events_path
        self.data = self._load()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "created_at": utc_now_iso(),
            "updated_at": None,
            "profiles": {},
            "target_index": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_state()
        try:
            text = self.path.read_text(encoding="utf-8-sig").strip()
            if not text:
                logging.warning("State file %s is empty, starting with a clean state", self.path)
                return self._empty_state()
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            backup_path = self.path.with_suffix(self.path.suffix + f".broken-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
            try:
                self.path.replace(backup_path)
                logging.error("State file %s is invalid JSON. Moved it to %s", self.path, backup_path)
            except OSError:
                logging.exception("Cannot move broken state file")
            return self._empty_state()
        except Exception as exc:
            logging.exception("Cannot read state file")
            raise ConfigError(f"Не удалось прочитать state-файл {self.path}: {exc}") from exc
        data.setdefault("schema", SCHEMA_VERSION)
        data.setdefault("profiles", {})
        data.setdefault("target_index", {})
        return data

    def save(self) -> None:
        self.data["updated_at"] = utc_now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def append_event(self, event: dict[str, Any]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        event.setdefault("created_at", utc_now_iso())
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def profile(self, profile_id: str) -> dict[str, Any] | None:
        return self.data.get("profiles", {}).get(str(profile_id))

    def upsert_profile(self, target: str, snapshot: dict[str, Any]) -> None:
        profile_id = str(snapshot["identity"]["id"])
        self.data.setdefault("profiles", {})[profile_id] = snapshot
        access_hash = snapshot["identity"].get("access_hash")
        self.data.setdefault("target_index", {})[target] = {
            "id": snapshot["identity"]["id"],
            "access_hash": access_hash,
            "display": snapshot["identity"].get("display"),
            "username": snapshot["identity"].get("username"),
            "updated_at": utc_now_iso(),
        }
        self.save()

    def indexed_target(self, target: str) -> dict[str, Any] | None:
        return self.data.get("target_index", {}).get(target)

    def find_profile(self, query: str) -> dict[str, Any] | None:
        normalized = query.strip().lstrip("@").lower()
        for profile in self.data.get("profiles", {}).values():
            identity = profile.get("identity", {})
            if str(identity.get("id")) == query.strip():
                return profile
            if str(identity.get("username") or "").lower() == normalized:
                return profile
            for item in profile.get("profile", {}).get("public_usernames", []) or []:
                if str(item.get("username") or "").lower() == normalized:
                    return profile
        return None

    def all_profiles(self) -> list[dict[str, Any]]:
        return list(self.data.get("profiles", {}).values())


class ProfileReader:
    def __init__(self, client: TelegramClient, config: AppConfig, store: StateStore) -> None:
        self.client = client
        self.config = config
        self.store = store
        self.tz = get_timezone(config.monitor.timezone_name)

    async def read(self, target: str) -> SnapshotBundle:
        entity = await self._resolve_target(target)
        full_result = await self.client(functions.users.GetFullUserRequest(entity))
        full_user = getattr(full_result, "full_user", None)
        if full_user is None:
            raise RuntimeError("Telegram не вернул full_user.")

        user_map = build_user_map(getattr(full_result, "users", []) or [])
        chat_map = build_chat_map(getattr(full_result, "chats", []) or [])
        user = user_map.get(int(getattr(full_user, "id", 0))) or entity
        if not isinstance(user, types.User):
            users = list(getattr(full_result, "users", []) or [])
            if users:
                user = users[0]

        photos_result = await self.client(
            functions.photos.GetUserPhotosRequest(
                user_id=user,
                offset=0,
                max_id=0,
                limit=self.config.monitor.profile_photo_limit,
            )
        )
        photos = list(getattr(photos_result, "photos", []) or [])
        photo_objects = {str(getattr(photo, "id", "")): photo for photo in photos}
        music_document = getattr(full_user, "saved_music", None)

        gifts = await self._read_gifts(user, user_map, chat_map)
        profile = normalize_profile(user, full_user, chat_map, self.config.monitor.track_online_status)
        photo_items = [normalize_photo(photo) for photo in photos]

        identity = {
            "id": int(getattr(user, "id")),
            "access_hash": str(getattr(user, "access_hash", "")) or None,
            "display": user_display(user),
            "username": getattr(user, "username", None),
            "bot": bool(getattr(user, "bot", False)),
            "profile_url": f"https://t.me/{getattr(user, 'username')}" if getattr(user, "username", None) else None,
        }
        snapshot = {
            "schema": SCHEMA_VERSION,
            "target": target,
            "taken_at": local_now_iso(self.tz),
            "identity": identity,
            "profile": profile,
            "photos": {
                "count": getattr(photos_result, "count", len(photo_items)),
                "checked_limit": self.config.monitor.profile_photo_limit,
                "ids": [item["id"] for item in photo_items],
                "items": photo_items,
            },
            "gifts": gifts,
            "raw": {
                "user": tl_to_plain(user),
                "full_user": tl_to_plain(full_user),
                "chats": tl_to_plain(getattr(full_result, "chats", [])),
            },
        }
        return SnapshotBundle(snapshot=snapshot, photo_objects=photo_objects, music_document=music_document)

    async def _resolve_target(self, target: str) -> Any:
        target = target.strip()
        indexed = self.store.indexed_target(target)
        if indexed and indexed.get("id") and indexed.get("access_hash"):
            try:
                return types.InputUser(int(indexed["id"]), int(indexed["access_hash"]))
            except Exception:
                logging.warning("Saved input user for %s is not usable, falling back", target)

        id_with_hash = ID_WITH_HASH_RE.match(target)
        if id_with_hash:
            return types.InputUser(int(id_with_hash.group("id")), int(id_with_hash.group("hash")))

        id_prefix = ID_PREFIX_RE.match(target)
        if id_prefix:
            target = id_prefix.group("id")

        if target.lstrip("-").isdigit():
            saved_profile = self.store.profile(target)
            access_hash = (saved_profile or {}).get("identity", {}).get("access_hash")
            if access_hash:
                return types.InputUser(int(target), int(access_hash))

        normalized = normalize_target(target)
        try:
            return await self.client.get_entity(normalized)
        except ValueError as exc:
            if isinstance(normalized, int):
                raise TargetResolveError(
                    f"Не удалось найти пользователя по id {normalized}. "
                    "Для голого id Telethon должен уже знать этот аккаунт. "
                    f"Укажи цель как {normalized}:ACCESS_HASH, используй @username "
                    "или сначала открой/добавь этот аккаунт в Telegram-сессии монитора."
                ) from exc
            raise TargetResolveError(f"Не удалось найти цель {target}. Проверь @username или замени цель на id:access_hash.") from exc

    async def _read_gifts(self, user: Any, user_map: dict[int, Any], chat_map: dict[int, Any]) -> dict[str, Any]:
        request_class = getattr(functions.payments, "GetSavedStarGiftsRequest", None)
        if request_class is None:
            return {
                "available": False,
                "error": "В этой версии Telethon нет payments.GetSavedStarGiftsRequest.",
                "visible_count": None,
                "listed_count": 0,
                "items": [],
            }

        input_peer = utils.get_input_peer(user)
        offset = ""
        all_items = []
        total_count = None
        next_offset = None
        raw_pages = 0
        remaining = self.config.monitor.gift_limit

        try:
            while remaining > 0:
                limit = min(100, remaining)
                result = await self.client(
                    request_class(
                        peer=input_peer,
                        offset=offset,
                        limit=limit,
                        exclude_unsaved=True,
                    )
                )
                raw_pages += 1
                user_map.update(build_user_map(getattr(result, "users", []) or []))
                chat_map.update(build_chat_map(getattr(result, "chats", []) or []))

                gifts = list(getattr(result, "gifts", []) or [])
                all_items.extend(gifts)
                remaining -= len(gifts)
                total_count = getattr(result, "count", total_count)
                next_offset = getattr(result, "next_offset", None)
                if not gifts or not next_offset:
                    break
                offset = next_offset
        except RPCError as exc:
            return {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
                "visible_count": total_count,
                "listed_count": len(all_items),
                "items": [normalize_gift(item, user_map, chat_map) for item in all_items],
            }

        normalized = [normalize_gift(item, user_map, chat_map) for item in all_items]
        return {
            "available": True,
            "error": None,
            "visible_count": total_count if total_count is not None else len(normalized),
            "listed_count": len(normalized),
            "limit": self.config.monitor.gift_limit,
            "next_offset": next_offset,
            "pages": raw_pages,
            "items": normalized,
        }


def normalize_target(target: str) -> str | int:
    value = target.strip()
    if value.startswith("https://t.me/"):
        value = value.removeprefix("https://t.me/").split("/", 1)[0]
    elif value.startswith("t.me/"):
        value = value.removeprefix("t.me/").split("/", 1)[0]

    id_prefix = ID_PREFIX_RE.match(value)
    if id_prefix:
        return int(id_prefix.group("id"))
    if value.lstrip("-").isdigit():
        return int(value)
    if USERNAME_RE.match(value):
        return value if value.startswith("@") else f"@{value}"
    return value


LEAF_PROFILE_KEYS = {
    "public_usernames",
    "emoji_status",
    "birthday",
    "personal_channel",
    "business_work_hours",
    "business_location",
    "business_intro",
    "business_greeting_message",
    "business_away_message",
    "profile_color",
    "name_color",
    "theme",
    "wallpaper",
    "main_tab",
    "saved_music",
    "note",
    "current_photo",
    "profile_photo",
    "personal_photo",
    "fallback_photo",
    "stars_rating",
    "online_status",
}


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        items: dict[str, Any] = {}
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            if not prefix and key in LEAF_PROFILE_KEYS:
                items[child_prefix] = child
            elif isinstance(child, dict) and len(compact_json(child, 1200)) < 1200:
                items.update(flatten(child, child_prefix))
            else:
                items[child_prefix] = child
        return items
    return {prefix: value}


FIELD_LABELS = {
    "first_name": "имя",
    "last_name": "фамилия",
    "username": "основной @username",
    "public_usernames": "публичные username",
    "premium": "Premium",
    "emoji_status": "премиум emoji-статус",
    "bio": "описание",
    "birthday": "день рождения",
    "personal_channel": "канал в профиле",
    "business_work_hours": "график работы",
    "business_location": "бизнес-адрес",
    "business_intro": "бизнес-интро",
    "business_greeting_message": "приветствие бизнеса",
    "business_away_message": "автоответ бизнеса",
    "profile_color": "цвет профиля",
    "name_color": "цвет имени",
    "theme": "тема профиля",
    "wallpaper": "обои профиля",
    "main_tab": "главная вкладка",
    "saved_music": "музыка профиля",
    "note": "заметка",
    "stargifts_count": "количество подарков",
    "stars_rating": "Stars-рейтинг",
    "send_paid_messages_stars": "цена платных сообщений",
    "common_chats_count": "общие чаты",
    "current_photo": "текущая аватарка",
    "profile_photo": "profile photo",
    "personal_photo": "personal photo",
    "fallback_photo": "fallback photo",
    "flags": "флаги профиля",
    "online_status": "онлайн-статус",
}


def label_for(path: str) -> str:
    first = path.split(".", 1)[0]
    base = FIELD_LABELS.get(first, first)
    if "." in path and first in {"flags"}:
        return f"{base}: {path.split('.', 1)[1]}"
    return base


def gift_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["key"]: item for item in snapshot.get("gifts", {}).get("items", []) if item.get("key")}


def gift_digest(item: dict[str, Any]) -> str:
    return stable_hash(strip_volatile({key: value for key, value in item.items() if key != "digest"}))


def diff_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    old_profile = flatten(previous.get("profile", {}))
    new_profile = flatten(current.get("profile", {}))
    profile_changes = []

    for path in sorted(set(old_profile) | set(new_profile)):
        old_value = profile_compare_value(path, old_profile.get(path))
        new_value = profile_compare_value(path, new_profile.get(path))
        if old_value != new_value:
            profile_changes.append(
                {
                    "path": path,
                    "label": label_for(path),
                    "old": old_value,
                    "new": new_value,
                }
            )

    old_photo_ids = set(previous.get("photos", {}).get("ids", []))
    new_photo_ids = set(current.get("photos", {}).get("ids", []))

    old_gifts = gift_map(previous)
    new_gifts = gift_map(current)
    added_gift_keys = sorted(set(new_gifts) - set(old_gifts))
    removed_gift_keys = sorted(set(old_gifts) - set(new_gifts))
    changed_gift_keys = sorted(
        key
        for key in set(old_gifts) & set(new_gifts)
        if gift_digest(old_gifts[key]) != gift_digest(new_gifts[key])
    )

    gift_meta_changes = []
    for path in ("available", "error", "visible_count", "listed_count"):
        old_value = previous.get("gifts", {}).get(path)
        new_value = current.get("gifts", {}).get(path)
        if old_value != new_value:
            gift_meta_changes.append({"path": path, "old": old_value, "new": new_value})

    return {
        "profile_changes": profile_changes,
        "photo_added": sorted(new_photo_ids - old_photo_ids),
        "photo_removed": sorted(old_photo_ids - new_photo_ids),
        "gift_added": [new_gifts[key] for key in added_gift_keys],
        "gift_removed": [old_gifts[key] for key in removed_gift_keys],
        "gift_changed": [new_gifts[key] for key in changed_gift_keys],
        "gift_meta_changes": gift_meta_changes,
    }


def diff_has_changes(diff: dict[str, Any]) -> bool:
    return any(
        diff.get(key)
        for key in (
            "profile_changes",
            "photo_added",
            "photo_removed",
            "gift_added",
            "gift_removed",
            "gift_changed",
            "gift_meta_changes",
        )
    )


def diff_change_count(diff: dict[str, Any]) -> int:
    return sum(
        len(diff.get(key, []))
        for key in (
            "profile_changes",
            "photo_added",
            "photo_removed",
            "gift_added",
            "gift_removed",
            "gift_changed",
            "gift_meta_changes",
        )
    )


def target_header(snapshot: dict[str, Any]) -> str:
    identity = snapshot.get("identity", {})
    display = identity.get("display") or f"id {identity.get('id')}"
    username = identity.get("username")
    link = f"https://t.me/{username}" if username else identity.get("profile_url")
    if link:
        return f'<a href="{html_escape(link)}">{html_escape(display)}</a> <code>{html_escape(identity.get("id"))}</code>'
    return f'{html_escape(display)} <code>{html_escape(identity.get("id"))}</code>'


def target_ref_html(target: Any) -> str:
    text = str(target or "").strip()
    if not text:
        return "<code>unknown</code>"

    if text.startswith("https://t.me/") or text.startswith("http://t.me/"):
        username = text.rstrip("/").rsplit("/", 1)[-1]
        return f'<a href="{html_attr(text)}">@{html_escape(username.lstrip("@"))}</a>'

    if text.startswith("t.me/"):
        username = text.rstrip("/").rsplit("/", 1)[-1]
        return f'<a href="{html_attr("https://" + text)}">@{html_escape(username.lstrip("@"))}</a>'

    if USERNAME_RE.match(text) and not text.lstrip("@").isdigit():
        username = text.lstrip("@")
        return f'<a href="https://t.me/{html_attr(username)}">@{html_escape(username)}</a>'

    return f"<code>{html_escape(text)}</code>"


def format_msk_datetime(value: Any) -> str:
    if not value:
        return "нет"
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%y %H:%M МСК")
    except (TypeError, ValueError):
        return one_line(value, 80)


def format_gift(gift: dict[str, Any], prefix: str = "Подарок") -> str:
    gift_info = gift.get("gift", {})
    title = gift_info.get("title") or "Gift"
    is_unique_gift = bool(gift_info.get("slug"))
    slug = str(gift_info["slug"]) if gift_info.get("slug") else None
    if slug:
        title_html = f'<a href="{html_attr(f"https://t.me/nft/{slug}")}">{html_escape(title)}</a>'
    else:
        title_html = html_escape(title)
    lines = [f"<b>{html_escape(prefix)}:</b> {title_html}"]

    sticker_emoji = gift_info.get("sticker_emoji")
    if sticker_emoji and str(sticker_emoji).strip() != str(title).strip():
        lines[0] += f" {html_escape(sticker_emoji)}"
    if gift_info.get("id") is not None:
        lines.append(f"id: <code>{html_escape(gift_info['id'])}</code>")
    if gift.get("saved_id") is not None:
        lines.append(f"saved_id: <code>{html_escape(gift['saved_id'])}</code>")
    if not is_unique_gift and gift.get("from"):
        lines.append(f"от кого: {html_escape(gift['from'])}")
    elif not is_unique_gift and gift.get("name_hidden"):
        lines.append("от кого: скрыто")
    if gift.get("date"):
        lines.append(f"когда: <code>{html_escape(format_msk_datetime(gift['date']))}</code>")
    message = (gift.get("message") or {}).get("text")
    if message:
        lines.append(f"подпись: {html_escape(message)}")
    if gift_info.get("stars") is not None:
        lines.append(f"стоимость: <code>{html_escape(gift_info['stars'])} Stars</code>")
    if not is_unique_gift and gift_info.get("availability_total") is not None:
        remains = gift_info.get("availability_remains")
        total = gift_info.get("availability_total")
        if remains is not None and total is not None:
            lines.append(f"тираж: <code>{html_escape(remains)}/{html_escape(total)}</code>")
    if gift_info.get("owner"):
        lines.append(f"владелец: {html_escape(gift_info['owner'])}")
    if not is_unique_gift and gift_info.get("value_amount") is not None:
        currency = gift_info.get("value_currency") or ""
        lines.append(f"оценка: <code>{html_escape(gift_info['value_amount'])} {html_escape(currency)}</code>")

    original_details = [
        item
        for item in gift_info.get("attributes", []) or []
        if isinstance(item, dict) and item.get("type") == "StarGiftAttributeOriginalDetails"
    ]
    for details in original_details[:1]:
        if details.get("sender"):
            lines.append(f"исходный отправитель: {html_escape(details['sender'])}")
        if details.get("date"):
            lines.append(f"исходная дата: <code>{html_escape(format_msk_datetime(details['date']))}</code>")
        original_message = (details.get("message") or {}).get("text")
        if original_message:
            lines.append(f"исходная подпись: {html_escape(original_message)}")

    flags = []
    for key, title in (
        ("pinned_to_top", "закреплен"),
        ("can_upgrade", "можно улучшить"),
        ("refunded", "возврат"),
        ("unsaved", "скрыт"),
        ("name_hidden", "имя скрыто"),
    ):
        if is_unique_gift and key == "name_hidden":
            continue
        if gift.get(key):
            flags.append(title)
    if flags:
        lines.append("флаги: " + ", ".join(flags))
    return "\n".join(lines)


def code_text(value: Any, limit: int = 500) -> str:
    return f"<code>{html_escape(one_line(value, limit))}</code>"


def format_duration(value: Any) -> str:
    if value is None:
        return "нет"
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return one_line(value, 40)
    if seconds < 0:
        return str(seconds)
    minutes, rest = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{rest:02d}"
    return f"{minutes}:{rest:02d}"


def format_file_size(value: Any) -> str:
    if value is None:
        return "нет"
    try:
        size = int(value)
    except (TypeError, ValueError):
        return one_line(value, 40)
    units = ("B", "KB", "MB", "GB")
    amount = float(size)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{size} B"


def music_title(music: dict[str, Any] | None) -> str:
    if not music:
        return "нет"
    title = music.get("title")
    performer = music.get("performer")
    file_name = music.get("file_name")
    alt = music.get("alt")
    parts = [str(item).strip() for item in (performer, title) if str(item or "").strip()]
    if parts:
        return " - ".join(parts)
    if file_name:
        return str(file_name)
    if alt:
        return str(alt)
    if music.get("id"):
        return f"document {music.get('id')}"
    return "без названия"


def format_music_html(music: dict[str, Any] | None, label: str = "Музыка профиля") -> str:
    if not music:
        return f"<b>{html_escape(label)}:</b> {code_text('нет')}"

    lines = [f"<b>{html_escape(label)}:</b> {code_text(music_title(music), 300)}"]
    if music.get("duration") is not None:
        lines.append(f"<b>Длительность:</b> {code_text(format_duration(music.get('duration')))}")
    if music.get("file_name"):
        lines.append(f"<b>Файл:</b> {code_text(music.get('file_name'), 220)}")
    if music.get("size") is not None:
        lines.append(f"<b>Размер:</b> {code_text(format_file_size(music.get('size')))}")
    if music.get("mime_type"):
        lines.append(f"<b>MIME:</b> {code_text(music.get('mime_type'), 80)}")
    if music.get("id"):
        lines.append(f"<b>Document ID:</b> {code_text(music.get('id'), 80)}")
    return "\n".join(lines)


def music_caption(snapshot: dict[str, Any]) -> str:
    music = snapshot.get("profile", {}).get("saved_music")
    lines = [
        "<b>Музыка профиля</b>",
        target_header(snapshot),
    ]
    if music:
        lines.append(f"трек: {code_text(music_title(music), 220)}")
        if music.get("duration") is not None:
            lines.append(f"длительность: {code_text(format_duration(music.get('duration')))}")
    return "\n".join(lines)


def music_file_extension(music: dict[str, Any] | None) -> str:
    if not music:
        return ""
    file_name = str(music.get("file_name") or "")
    suffix = Path(file_name).suffix.lower()
    if suffix and re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        return suffix
    mime_type = music.get("mime_type")
    if mime_type:
        return mimetypes.guess_extension(str(mime_type)) or ""
    return ""


def has_saved_music_change(diff: dict[str, Any]) -> bool:
    return any(change.get("path") == "saved_music" for change in diff.get("profile_changes", []))


def html_attr(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def format_channel_html(channel: dict[str, Any] | None) -> str:
    if not channel:
        return f"<b>Канал:</b> {code_text('нет')}"

    title = channel.get("title")
    username = channel.get("username")
    channel_id = channel.get("id")

    parts = []
    if title:
        parts.append(code_text(title, 180))
    if username:
        parts.append(html_escape("@" + str(username)))
    if not parts and channel_id is not None:
        parts.append(f"id {code_text(channel_id)}")

    lines = [f"<b>Канал:</b> {' '.join(parts) if parts else code_text(channel, 260)}"]
    if channel_id is not None:
        lines.append(f"<b>ID канала:</b> {code_text(channel_id)}")
    return "\n".join(lines)


def minutes_to_hhmm(total_minutes: int) -> str:
    minute = total_minutes % 1440
    return f"{minute // 60:02d}:{minute % 60:02d}"


def day_range_text(start_day: int, end_day: int) -> str:
    if start_day == end_day:
        return DAYS_RU[start_day]
    return f"{DAYS_RU[start_day]}-{DAYS_RU[end_day]}"


def compact_work_hours_lines(work_hours: dict[str, Any]) -> list[str]:
    weekly = work_hours.get("weekly_open") or []
    day_items: list[tuple[int, str]] = []
    extra_items: list[str] = []

    for item in weekly:
        try:
            start_minute = int(item.get("start_minute", 0))
            end_minute = int(item.get("end_minute", 0))
        except (TypeError, ValueError):
            extra_items.append(str(item.get("human") or item))
            continue

        start_day = start_minute // 1440
        end_day = end_minute // 1440
        if 0 <= start_day <= 6 and start_day == end_day:
            day_items.append((start_day, f"{minutes_to_hhmm(start_minute)}-{minutes_to_hhmm(end_minute)}"))
        else:
            extra_items.append(str(item.get("human") or f"{start_minute}-{end_minute}"))

    day_items.sort(key=lambda item: item[0])
    compacted: list[str] = []
    idx = 0
    while idx < len(day_items):
        start_day, hours = day_items[idx]
        end_day = start_day
        idx += 1
        while idx < len(day_items) and day_items[idx][0] == end_day + 1 and day_items[idx][1] == hours:
            end_day = day_items[idx][0]
            idx += 1
        compacted.append(f"{day_range_text(start_day, end_day)}: {hours}")

    return compacted + extra_items


def format_work_hours_html(work_hours: dict[str, Any] | None) -> str:
    if not work_hours:
        return f"<b>График:</b> {code_text('нет')}"

    schedule = compact_work_hours_lines(work_hours)
    if schedule:
        lines = ["<b>График:</b> " + "; ".join(code_text(item, 80) for item in schedule)]
    else:
        lines = [f"<b>График:</b> {code_text('не указан')}"]

    timezone_id = work_hours.get("timezone_id")
    if timezone_id:
        lines.append(f"<b>Часовой пояс:</b> {code_text(timezone_id)}")
    if "open_now" in work_hours:
        lines.append(f"<b>Сейчас:</b> {code_text('открыто' if work_hours.get('open_now') else 'закрыто')}")
    return "\n".join(lines)


def format_snapshot_gifts(snapshot: dict[str, Any]) -> str:
    gifts = snapshot.get("gifts", {})
    items = gifts.get("items") or []
    if not items and gifts.get("available", True):
        return ""

    lines = ["", f"<b>Текущие подарки профиля: {len(items)}</b>"]
    if not gifts.get("available", True):
        lines.append(f"<b>Подарки API:</b> <code>{html_escape(gifts.get('error') or 'недоступно')}</code>")
    if not items:
        return "\n".join(lines)

    for gift in items:
        lines.append("")
        lines.append(format_gift(gift, "Подарок"))
    return "\n".join(lines)


def format_pretty_profile_change(change: dict[str, Any]) -> str | None:
    label = html_escape(change["label"])
    path = change["path"]
    if path == "emoji_status":
        return f"<b>{label}</b>: {emoji_status_html(change['old'])} -&gt; {emoji_status_html(change['new'])}"
    if path == "personal_channel":
        return (
            f"<b>{label}</b>:\n"
            f"было:\n{format_channel_html(change['old'])}\n"
            f"стало:\n{format_channel_html(change['new'])}"
        )
    if path == "business_work_hours":
        return (
            f"<b>{label}</b>:\n"
            f"было:\n{format_work_hours_html(change['old'])}\n"
            f"стало:\n{format_work_hours_html(change['new'])}"
        )
    if path == "saved_music":
        return (
            f"<b>{label}</b>:\n"
            f"было:\n{format_music_html(change['old'])}\n"
            f"стало:\n{format_music_html(change['new'])}"
        )
    return None


def format_diff(snapshot: dict[str, Any], diff: dict[str, Any]) -> str:
    lines = [
        "<b>Изменения профиля</b>",
        target_header(snapshot),
        f"снимок: <code>{html_escape(snapshot.get('taken_at'))}</code>",
        "",
    ]

    for change in diff.get("profile_changes", [])[:30]:
        pretty_change = format_pretty_profile_change(change)
        if pretty_change:
            lines.append(pretty_change)
        else:
            label = change["label"]
            lines.append(
                f"<b>{html_escape(label)}</b>: "
                f"{format_value(change['old'])} -&gt; {format_value(change['new'])}"
            )
    hidden_profile_changes = max(0, len(diff.get("profile_changes", [])) - 30)
    if hidden_profile_changes:
        lines.append(f"Еще изменений полей: <b>{hidden_profile_changes}</b>. Полный JSON есть в events log.")

    if diff.get("gift_meta_changes"):
        lines.append("")
        lines.append("<b>Счетчики подарков</b>")
        for change in diff["gift_meta_changes"]:
            lines.append(
                f"{html_escape(change['path'])}: {format_value(change['old'])} -&gt; {format_value(change['new'])}"
            )

    if diff.get("photo_added") or diff.get("photo_removed"):
        lines.append("")
        lines.append("<b>Аватарки</b>")
        if diff.get("photo_added"):
            lines.append("появились: " + ", ".join(f"<code>{html_escape(item)}</code>" for item in diff["photo_added"]))
        if diff.get("photo_removed"):
            lines.append("пропали: " + ", ".join(f"<code>{html_escape(item)}</code>" for item in diff["photo_removed"]))

    if diff.get("gift_added"):
        lines.append("")
        lines.append(f"<b>Подарки появились в профиле: {len(diff['gift_added'])}</b>")
        for gift in diff["gift_added"]:
            lines.append("")
            lines.append(format_gift(gift, "Появился"))

    if diff.get("gift_removed"):
        lines.append("")
        lines.append(f"<b>Подарки пропали из профиля: {len(diff['gift_removed'])}</b>")
        for gift in diff["gift_removed"]:
            lines.append(f"• {html_escape((gift.get('gift') or {}).get('title') or gift.get('key'))}")

    if diff.get("gift_changed"):
        lines.append("")
        lines.append(f"<b>Подарки изменились: {len(diff['gift_changed'])}</b>")
        for gift in diff["gift_changed"]:
            lines.append("")
            lines.append(format_gift(gift, "Текущие детали"))

    return "\n".join(lines)


def format_snapshot_summary(snapshot: dict[str, Any], title: str = "Снимок профиля") -> str:
    profile = snapshot.get("profile", {})
    gifts = snapshot.get("gifts", {})
    photos = snapshot.get("photos", {})
    username = profile.get("username")
    gift_items = gifts.get("items") or []
    stargifts_count = profile.get("stargifts_count")
    listed_count = gifts.get("listed_count")
    visible_count = gifts.get("visible_count")

    lines = [
        f"<b>{html_escape(title)}</b>",
        target_header(snapshot),
        f"снят: <code>{html_escape(snapshot.get('taken_at'))}</code>",
        "",
        f"<b>Имя:</b> {code_text(profile.get('first_name') or 'нет')}",
        f"<b>Фамилия:</b> {code_text(profile.get('last_name') or 'нет')}",
        f"<b>Username:</b> {html_escape('@' + username) if username else code_text('нет')}",
        f"<b>Premium:</b> {code_text('да' if profile.get('premium') else 'нет')}",
        f"<b>Emoji status:</b> {emoji_status_html(profile.get('emoji_status'))}",
        f"<b>Описание:</b> {code_text(profile.get('bio') or 'нет', 500)}",
        format_music_html(profile.get("saved_music")),
        format_channel_html(profile.get("personal_channel")),
        format_work_hours_html(profile.get("business_work_hours")),
        f"<b>Аватарок видно:</b> <code>{html_escape(photos.get('count'))}</code>",
    ]
    if gift_items:
        lines.extend(
            [
                f"<b>Подарков в full profile:</b> <code>{html_escape(stargifts_count)}</code>",
                f"<b>Подарков прочитано:</b> <code>{html_escape(listed_count)}</code> из <code>{html_escape(visible_count)}</code>",
            ]
        )
    else:
        if any(value not in (None, 0) for value in (stargifts_count, listed_count, visible_count)):
            lines.append(
                f"<b>Подарки:</b> видимых нет, full profile: <code>{html_escape(stargifts_count)}</code>, "
                f"прочитано <code>{html_escape(listed_count)}</code> из <code>{html_escape(visible_count)}</code>"
            )
        else:
            lines.append("<b>Подарки:</b> <code>нет видимых</code>")
    if gifts.get("error"):
        lines.append(f"<b>Подарки API:</b> <code>{html_escape(gifts['error'])}</code>")
    gift_details = format_snapshot_gifts(snapshot)
    if gift_details:
        lines.append(gift_details)
    return "\n".join(lines)


def format_results(results: list[CheckResult]) -> str:
    ok = sum(1 for item in results if item.ok)
    changed = sum(1 for item in results if item.changes_count)
    baseline = sum(1 for item in results if item.baseline)
    lines = [
        "<b>Проверка завершена</b>",
        f"целей: <code>{len(results)}</code>, успешно: <code>{ok}</code>, с изменениями: <code>{changed}</code>, новых снимков: <code>{baseline}</code>",
        "",
    ]
    for item in results:
        name = item.display_name or item.target
        if item.ok:
            if item.baseline:
                status = "первый снимок"
            elif item.changes_count:
                status = f"изменений: {item.changes_count}"
            else:
                status = "без изменений"
            lines.append(f"• {html_escape(name)}: {html_escape(status)}")
        else:
            lines.append(f"• {html_escape(item.target)}: ошибка <code>{html_escape(item.error)}</code>")
    return "\n".join(lines)


class ProfileMonitor:
    def __init__(self, client: TelegramClient, bot: Bot, config: AppConfig, store: StateStore) -> None:
        self.client = client
        self.bot = bot
        self.config = config
        self.store = store
        self.reader = ProfileReader(client, config, store)
        self.lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.last_started_at: str | None = None
        self.last_finished_at: str | None = None
        self.last_error: str | None = None
        self.last_results: list[CheckResult] = []

    async def run_loop(self) -> None:
        await self.send_admin_text(self.startup_text())
        while not self.stop_event.is_set():
            try:
                await self.run_once(manual=False, notify_no_changes=False)
            except Exception as exc:
                logging.exception("Monitor loop failed")
                self.last_error = f"{type(exc).__name__}: {exc}"
                await self.send_admin_text(f"<b>Ошибка цикла мониторинга</b>\n<code>{html_escape(self.last_error)}</code>")

            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.config.monitor.interval_seconds)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self.stop_event.set()

    def startup_text(self) -> str:
        targets = "\n".join(f"• {target_ref_html(target)}" for target in self.config.monitor.targets)
        return (
            "<b>User Monitor запущен</b>\n"
            f"Интервал: <code>{self.config.monitor.interval_seconds} сек</code>\n"
            f"Целей: <code>{len(self.config.monitor.targets)}</code>\n\n"
            f"{targets}"
        )

    async def run_once(
        self,
        manual: bool,
        notify_no_changes: bool,
        only_target: str | None = None,
    ) -> list[CheckResult]:
        if self.lock.locked():
            return [CheckResult(target=only_target or "all", ok=False, error="Проверка уже идет.")]

        async with self.lock:
            self.last_started_at = utc_now_iso()
            self.last_error = None
            targets = [only_target] if only_target else self.config.monitor.targets
            results: list[CheckResult] = []

            for index, target in enumerate(targets):
                if index and self.config.monitor.request_delay_seconds:
                    await asyncio.sleep(self.config.monitor.request_delay_seconds)
                result = await self.check_target(target, manual=manual, notify_no_changes=notify_no_changes)
                results.append(result)

            self.last_finished_at = utc_now_iso()
            self.last_results = results
            return results

    async def check_target(self, target: str, manual: bool, notify_no_changes: bool) -> CheckResult:
        logging.info("Checking target %s", target)
        try:
            bundle = await self.reader.read(target)
            snapshot = bundle.snapshot
            profile_id = str(snapshot["identity"]["id"])
            previous = self.store.profile(profile_id)

            if previous is None:
                self.store.upsert_profile(target, snapshot)
                self.store.append_event(
                    {
                        "type": "baseline",
                        "target": target,
                        "profile_id": profile_id,
                        "snapshot": snapshot,
                    }
                )
                if self.config.monitor.notify_initial_snapshot or manual:
                    await self.send_admin_text(format_snapshot_summary(snapshot, "Первый снимок сохранен"))
                    await self.send_profile_music(snapshot, bundle.music_document)
                return CheckResult(
                    target=target,
                    ok=True,
                    profile_id=profile_id,
                    display_name=snapshot["identity"].get("display"),
                    baseline=True,
                )

            diff = diff_snapshots(previous, snapshot)
            self.store.upsert_profile(target, snapshot)

            if diff_has_changes(diff):
                self.store.append_event(
                    {
                        "type": "change",
                        "target": target,
                        "profile_id": profile_id,
                        "diff": diff,
                        "snapshot": snapshot,
                    }
                )
                await self.notify_diff(snapshot, diff, bundle.photo_objects, bundle.music_document)
            elif notify_no_changes:
                await self.send_admin_text(
                    f"<b>Без изменений</b>\n{target_header(snapshot)}\nснимок: <code>{html_escape(snapshot.get('taken_at'))}</code>"
                )

            return CheckResult(
                target=target,
                ok=True,
                profile_id=profile_id,
                display_name=snapshot["identity"].get("display"),
                changes_count=diff_change_count(diff),
            )
        except FloodWaitError as exc:
            wait_seconds = int(getattr(exc, "seconds", 0))
            error = f"FloodWait: Telegram попросил подождать {wait_seconds} сек."
            logging.warning("%s for %s", error, target)
            await asyncio.sleep(min(wait_seconds, 60))
            await self.send_admin_text(f"<b>Telegram FloodWait</b>\n<code>{html_escape(target)}</code>\n{html_escape(error)}")
            return CheckResult(target=target, ok=False, error=error)
        except TargetResolveError as exc:
            error = str(exc)
            logging.warning("Failed to resolve %s: %s", target, error)
            self.store.append_event({"type": "error", "target": target, "error": error})
            await self.send_admin_text(f"<b>Цель не найдена</b>\n<code>{html_escape(target)}</code>\n{html_escape(error)}")
            return CheckResult(target=target, ok=False, error=error)
        except Exception as exc:
            logging.exception("Failed to check %s", target)
            error = f"{type(exc).__name__}: {exc}"
            self.store.append_event({"type": "error", "target": target, "error": error})
            await self.send_admin_text(f"<b>Ошибка проверки профиля</b>\n<code>{html_escape(target)}</code>\n<code>{html_escape(error)}</code>")
            return CheckResult(target=target, ok=False, error=error)

    async def notify_diff(
        self,
        snapshot: dict[str, Any],
        diff: dict[str, Any],
        photo_objects: dict[str, Any],
        music_document: Any | None,
    ) -> None:
        await self.send_admin_text(format_diff(snapshot, diff))
        if has_saved_music_change(diff):
            await self.send_profile_music(snapshot, music_document)

        if not self.config.monitor.send_photos or self.config.monitor.max_photos_per_event <= 0:
            return

        added = diff.get("photo_added", [])[: self.config.monitor.max_photos_per_event]
        for photo_id in added:
            photo = photo_objects.get(str(photo_id))
            if photo is None:
                continue
            try:
                path = await self.download_photo(snapshot, photo_id, photo)
                caption = (
                    "<b>Новая аватарка</b>\n"
                    f"{target_header(snapshot)}\n"
                    f"photo_id: <code>{html_escape(photo_id)}</code>"
                )
                await self.send_admin_photo(path, caption)
            except Exception as exc:
                logging.exception("Failed to send photo %s", photo_id)
                await self.send_admin_text(
                    f"<b>Не удалось отправить аватарку</b>\n"
                    f"photo_id: <code>{html_escape(photo_id)}</code>\n"
                    f"<code>{html_escape(type(exc).__name__)}: {html_escape(exc)}</code>"
                )

    async def download_photo(self, snapshot: dict[str, Any], photo_id: str, photo: Any) -> Path:
        profile_id = str(snapshot["identity"]["id"])
        target_dir = self.config.monitor.media_dir / profile_id
        target_dir.mkdir(parents=True, exist_ok=True)

        existing = list(target_dir.glob(f"profile_{photo_id}.*"))
        if existing:
            return existing[0]

        result = await self.client.download_media(photo, file=str(target_dir / f"profile_{photo_id}"))
        if not result:
            raise RuntimeError("Telethon не вернул путь к скачанной аватарке.")
        return Path(result)

    async def send_profile_music(self, snapshot: dict[str, Any], music_document: Any | None) -> None:
        music = snapshot.get("profile", {}).get("saved_music")
        if not music:
            return
        if music_document is None:
            await self.send_admin_text(
                "<b>Музыка профиля есть, но файл недоступен</b>\n"
                f"{target_header(snapshot)}\n"
                f"{format_music_html(music)}"
            )
            return

        try:
            path = await self.download_music(snapshot, music_document)
            await self.send_admin_audio(path, music_caption(snapshot), music)
        except Exception as exc:
            logging.exception("Failed to send profile music")
            await self.send_admin_text(
                "<b>Не удалось отправить музыку профиля</b>\n"
                f"{target_header(snapshot)}\n"
                f"{format_music_html(music)}\n"
                f"<code>{html_escape(type(exc).__name__)}: {html_escape(exc)}</code>"
            )

    async def download_music(self, snapshot: dict[str, Any], music_document: Any) -> Path:
        profile_id = str(snapshot["identity"]["id"])
        music = snapshot.get("profile", {}).get("saved_music") or {}
        document_id = str(music.get("id") or getattr(music_document, "id", "music"))
        target_dir = self.config.monitor.media_dir / profile_id / "music"
        target_dir.mkdir(parents=True, exist_ok=True)

        exact_path = target_dir / f"music_{document_id}"
        if exact_path.exists():
            return exact_path
        existing = list(target_dir.glob(f"music_{document_id}.*"))
        if existing:
            return existing[0]

        extension = music_file_extension(music)
        result = await self.client.download_media(music_document, file=str(target_dir / f"music_{document_id}{extension}"))
        if not result:
            raise RuntimeError("Telethon не вернул путь к скачанной музыке.")
        return Path(result)

    async def send_admin_text(self, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        chunks = split_message(text)
        for index, chunk in enumerate(chunks):
            for admin_id in self.config.bot.admin_ids:
                try:
                    await self.bot.send_message(
                        admin_id,
                        chunk,
                        disable_web_page_preview=True,
                        reply_markup=reply_markup if index == len(chunks) - 1 else None,
                    )
                except TelegramAPIError:
                    logging.exception("Failed to send message to admin %s", admin_id)

    async def send_admin_photo(self, path: Path, caption: str) -> None:
        for admin_id in self.config.bot.admin_ids:
            try:
                await self.bot.send_photo(admin_id, FSInputFile(path), caption=caption)
            except TelegramAPIError:
                logging.exception("Failed to send photo to admin %s", admin_id)

    async def send_admin_audio(self, path: Path, caption: str, music: dict[str, Any]) -> None:
        duration = None
        try:
            if music.get("duration") is not None:
                duration = int(music["duration"])
        except (TypeError, ValueError):
            duration = None

        for admin_id in self.config.bot.admin_ids:
            try:
                await self.bot.send_audio(
                    admin_id,
                    FSInputFile(path),
                    caption=caption,
                    title=music.get("title") or None,
                    performer=music.get("performer") or None,
                    duration=duration,
                )
            except TelegramAPIError:
                logging.exception("Failed to send audio to admin %s, trying document", admin_id)
                try:
                    await self.bot.send_document(admin_id, FSInputFile(path), caption=caption)
                except TelegramAPIError:
                    logging.exception("Failed to send music document to admin %s", admin_id)

    def status_text(self) -> str:
        running = "идет проверка" if self.lock.locked() else "ожидает"
        lines = [
            "<b>Статус мониторинга</b>",
            f"Состояние: <b>{running}</b>",
            f"Целей в config: <code>{len(self.config.monitor.targets)}</code>",
            f"Интервал: <code>{self.config.monitor.interval_seconds} сек</code>",
            f"Последний старт: <code>{html_escape(self.last_started_at or 'нет')}</code>",
            f"Последнее завершение: <code>{html_escape(self.last_finished_at or 'нет')}</code>",
            f"State: <code>{html_escape(self.config.monitor.state_path)}</code>",
            f"Events: <code>{html_escape(self.config.monitor.events_path)}</code>",
        ]
        if self.last_error:
            lines.append(f"Последняя ошибка: <code>{html_escape(self.last_error)}</code>")
        if self.last_results:
            lines.append("")
            lines.append(format_results(self.last_results))
        return "\n".join(lines)

    def watchlist_text(self) -> str:
        lines = ["<b>Цели из config</b>"]
        for target in self.config.monitor.targets:
            indexed = self.store.indexed_target(target) or {}
            display = indexed.get("display") or "пока не снят"
            profile_id = indexed.get("id") or "нет"
            lines.append(f"• {target_ref_html(target)} -&gt; {html_escape(display)} <code>{html_escape(profile_id)}</code>")

        profiles = self.store.all_profiles()
        if profiles:
            lines.append("")
            lines.append("<b>Снимки в state</b>")
            for profile in profiles[:30]:
                identity = profile.get("identity", {})
                lines.append(
                    f"• {html_escape(identity.get('display') or identity.get('id'))} "
                    f"<code>{html_escape(identity.get('id'))}</code>, "
                    f"снят <code>{html_escape(profile.get('taken_at'))}</code>"
                )
        return "\n".join(lines)


def split_message(text: str) -> list[str]:
    if len(text) <= MAX_BOT_MESSAGE:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > MAX_BOT_MESSAGE:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        if line_len > MAX_BOT_MESSAGE:
            chunks.append(line[: MAX_BOT_MESSAGE - 3] + "...")
            continue
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Статус", callback_data="um:status"),
                InlineKeyboardButton(text="Проверить сейчас", callback_data="um:check"),
            ],
            [
                InlineKeyboardButton(text="Цели", callback_data="um:watchlist"),
                InlineKeyboardButton(text="Помощь", callback_data="um:help"),
            ],
        ]
    )


def help_text() -> str:
    return (
        "<b>User Monitor</b>\n"
        "Команды:\n"
        "/status - состояние мониторинга\n"
        "/watchlist - цели и последние снимки\n"
        "/check - проверить все цели сейчас\n"
        "/check @username - разово проверить одну цель\n"
        "/snapshot @username_or_id - показать последний снимок из state\n\n"
        "Цели для постоянного мониторинга задаются в <code>config.json</code>."
    )


def is_admin(config: AppConfig, message_or_query: Message | CallbackQuery) -> bool:
    user = message_or_query.from_user
    return bool(user and user.id in config.bot.admin_ids)


def command_args(message: Message) -> str:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def build_router(monitor: ProfileMonitor, config: AppConfig) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        await message.answer(help_text(), reply_markup=main_keyboard())

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        await message.answer(help_text(), reply_markup=main_keyboard())

    @router.message(Command("status"))
    async def on_status(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        await message.answer(monitor.status_text(), reply_markup=main_keyboard())

    @router.message(Command("watchlist"))
    async def on_watchlist(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        await message.answer(monitor.watchlist_text(), reply_markup=main_keyboard())

    @router.message(Command("snapshot"))
    async def on_snapshot(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        args = command_args(message)
        if not args:
            await message.answer("Укажи цель: <code>/snapshot @username</code> или <code>/snapshot 123456789</code>")
            return
        snapshot = monitor.store.find_profile(args)
        if snapshot is None:
            await message.answer("В state пока нет снимка для этой цели. Запусти <code>/check</code>.")
            return
        await message.answer(format_snapshot_summary(snapshot), reply_markup=main_keyboard())

    @router.message(Command("check"))
    async def on_check(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        args = command_args(message) or None
        status = await message.answer("Проверяю профильные данные...")
        results = await monitor.run_once(manual=True, notify_no_changes=True, only_target=args)
        try:
            await status.edit_text(format_results(results), reply_markup=main_keyboard())
        except TelegramBadRequest:
            await message.answer(format_results(results), reply_markup=main_keyboard())

    @router.callback_query(F.data == "um:status")
    async def cb_status(query: CallbackQuery) -> None:
        if not is_admin(config, query):
            await query.answer("Нет доступа.", show_alert=True)
            return
        await query.answer()
        await query.message.edit_text(monitor.status_text(), reply_markup=main_keyboard())

    @router.callback_query(F.data == "um:watchlist")
    async def cb_watchlist(query: CallbackQuery) -> None:
        if not is_admin(config, query):
            await query.answer("Нет доступа.", show_alert=True)
            return
        await query.answer()
        await query.message.edit_text(monitor.watchlist_text(), reply_markup=main_keyboard())

    @router.callback_query(F.data == "um:help")
    async def cb_help(query: CallbackQuery) -> None:
        if not is_admin(config, query):
            await query.answer("Нет доступа.", show_alert=True)
            return
        await query.answer()
        await query.message.edit_text(help_text(), reply_markup=main_keyboard())

    @router.callback_query(F.data == "um:check")
    async def cb_check(query: CallbackQuery) -> None:
        if not is_admin(config, query):
            await query.answer("Нет доступа.", show_alert=True)
            return
        await query.answer("Запускаю проверку.")
        if query.message:
            await query.message.edit_text("Проверяю профильные данные...", reply_markup=main_keyboard())
        results = await monitor.run_once(manual=True, notify_no_changes=True)
        if query.message:
            await query.message.edit_text(format_results(results), reply_markup=main_keyboard())

    return router


async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="status", description="статус мониторинга"),
            BotCommand(command="watchlist", description="цели и снимки"),
            BotCommand(command="check", description="проверить сейчас"),
            BotCommand(command="snapshot", description="последний снимок цели"),
            BotCommand(command="help", description="помощь"),
        ]
    )


async def main() -> None:
    config = load_config()
    ensure_dirs(config)
    setup_logging(config)

    logging.info("Starting Telethon client")
    client = TelegramClient(config.telegram.session_name, config.telegram.api_id, config.telegram.api_hash)
    await ensure_user_authorized(client, config.telegram.phone)

    bot = Bot(config.bot.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    store = StateStore(config.monitor.state_path, config.monitor.events_path)
    monitor = ProfileMonitor(client, bot, config, store)
    dp.include_router(build_router(monitor, config))

    monitor_task = asyncio.create_task(monitor.run_loop())
    try:
        await set_bot_commands(bot)
        await dp.start_polling(bot)
    finally:
        monitor.stop()
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigError as exc:
        print(f"[CONFIG] {exc}")
        raise SystemExit(1)
