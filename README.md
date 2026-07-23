# 👤 Telegram User Monitor

> Монитор Telegram-профилей на Telethon и aiogram с уведомлениями об изменениях, локальной историей и сохранением доступных медиа.

🌐 **Язык:** [Русский](README.md) · [English](README_EN.md)

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Telethon](https://img.shields.io/badge/Telethon-user_session-0088CC?logo=telegram&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-Telegram_bot-26A5E4?logo=telegram&logoColor=white)
![MIT License](https://img.shields.io/badge/License-MIT-2EA44F.svg)

## ✨ Обзор

Telegram User Monitor использует пользовательскую Telethon session для чтения доступных профильных данных и отдельного Telegram-бота для уведомлений и команд. Монитор сохраняет snapshots, сравнивает их по стабильному user ID и сообщает администраторам об изменениях профиля, аватарок, музыки и видимых подарков.

Проект не обходит приватность Telegram. Он видит только те сведения, которые Telegram показывает авторизованному пользовательскому аккаунту.

## 🚀 Возможности

- имя, фамилия, основной и дополнительные публичные username;
- Telegram Premium и обычный или collectible emoji status;
- bio, birthday, note и common chats count;
- personal channel и связанное сообщение;
- business hours, location, intro, greeting и away settings;
- profile/name colors, theme, wallpaper, main tab и profile flags;
- опциональный online status;
- current, profile, personal и fallback photo;
- список доступных аватарок с обнаружением добавления и удаления;
- profile music: metadata, скачивание и отправка audio/document;
- `stargifts_count`, Stars rating и paid-message price;
- видимые обычные и unique gifts через `GetSavedStarGiftsRequest`;
- sender/recipient, date, message, saved/message IDs, slug, owner, supply, value и original details;
- raw TL data в локальном state и event history;
- сохранение `id`/`access_hash` и автоматическая синхронизация актуального username в config;
- глобальные и отдельные per-account JSONL events;
- admin-only Telegram-команды и inline keyboard.

## 🏗️ Как это работает

```text
config.json + authorized Telethon session
    │
    ▼
main.py
    ├── GetFullUser ───────── profile and business fields
    ├── GetUserPhotos ─────── profile photos
    └── GetSavedStarGifts ─── visible gifts
    │
    ▼
normalized snapshot keyed by user ID
    ├── diff + Telegram bot notifications
    ├── state/profile_state.json
    ├── global and per-account JSONL logs
    └── downloaded photos and profile music
```

Username используется для первого resolution, а стабильный user ID и сохранённый `access_hash` — для последующих проверок. Поэтому смена username не должна переключить монитор на другой аккаунт.

## 📋 Требования

- Python 3.10 или новее;
- пользовательский Telegram-аккаунт;
- `api_id` и `api_hash` из [Telegram API development tools](https://my.telegram.org);
- Telegram bot token от [@BotFather](https://t.me/BotFather);
- Telegram user ID каждого администратора;
- хотя бы одна доступная цель мониторинга.

Основные зависимости:

| Пакет | Назначение |
| --- | --- |
| `telethon` | User session и MTProto requests |
| `aiogram` | Bot API, команды и отправка media |
| `qrcode[pil]` | QR login в консоли |
| `tzdata` | IANA timezones на системах без системной базы |

## ⚙️ Установка и запуск

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/soroka01/Telegram-user-monitoring.git
cd Telegram-user-monitoring
```

### 2. Создайте config на Windows

```bat
start.bat
```

Первый запуск создаст `.venv` и `config.json`, затем остановится. Заполните `api_id`, `api_hash`, bot token, admin IDs и targets; phone нужен только для входа кодом.

### 3. Авторизуйте user session

Рекомендуемый QR-вход:

```bat
login.bat
```

Откройте Telegram на телефоне:

```text
Настройки → Устройства → Подключить устройство
```

Отсканируйте QR из консоли. Если включён 2FA, Telethon дополнительно запросит пароль.

Вход кодом вместо QR:

```powershell
.\.venv\Scripts\python.exe login.py --code
```

Код приходит в официальный чат **Telegram** на уже авторизованном устройстве, а не в созданного бота. В prompt доступны `sms`, `resend` и `exit`, если Telegram разрешает соответствующий способ.

Перед `--code` обязательно замените пример `+79990000000` в `telegram.phone` своим номером.

### 4. Запустите монитор

```bat
start.bat
```

`main.py` также умеет интерактивно запросить код, если session ещё не авторизована, но отдельный QR-вход через `login.bat` обычно надёжнее.

### Ручная установка

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
python login.py
python main.py
```

Linux или macOS:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.json config.json
python login.py
python main.py
```

## 🎯 Цели мониторинга

Рекомендуемый формат:

```json
{
  "monitor": {
    "targets": [
      {"id": 123456789, "username": "@username"},
      {"id": 987654321, "username": null}
    ]
  }
}
```

Также поддерживаются:

| Формат | Пример | Условие |
| --- | --- | --- |
| Username | `@username` | Публичный или доступный session username |
| Ссылка | `https://t.me/username` | Разрешается как username |
| User ID | `123456789` | Session уже знает entity |
| ID + access hash | `123456789:987654321012345678` | Надёжная привязка без username |
| Prefix + ID + hash | `id:123456789:987654321012345678` | То же в явном формате |

После успешного snapshot монитор может переписать соответствующую запись в `config.json` в объект с актуальными `id` и `username`. Дополнительные ключи объекта сохраняются. При использовании `MONITOR_TARGETS` файл не синхронизируется.

## ⚙️ Конфигурация

### Telegram user session

| Поле | По умолчанию | Назначение |
| --- | ---: | --- |
| `telegram.api_id` | — | API application ID; обязателен |
| `telegram.api_hash` | — | API application hash; обязателен |
| `telegram.phone` | — | Номер в международном формате для code login |
| `telegram.session_name` | `user_monitor_account` | Имя или путь Telethon session без `.session` |
| `telegram.qr_login_attempts` | `10` | Максимальное число обновлений QR |
| `telegram.qr_login_timeout_seconds` | `55` | Время жизни одной QR-попытки; минимум 15 секунд |

### Bot

| Поле | Назначение |
| --- | --- |
| `bot.token` | Bot token от BotFather |
| `bot.admin_ids` | Список пользователей, получающих alerts и имеющих доступ к командам |

Обязательно замените placeholder `123456789`: он является синтаксически допустимым Telegram ID.

### Monitor

| Поле | По умолчанию | Назначение |
| --- | ---: | --- |
| `targets` | — | Постоянные цели; обязателен хотя бы один элемент |
| `interval_seconds` | `300` | Период проверки; минимум 30 секунд |
| `request_delay_seconds` | `1.0` | Пауза между целями |
| `profile_photo_limit` | `20` | Сколько последних аватарок сравнивать |
| `gift_limit` | `200` | Максимум видимых подарков на snapshot |
| `max_photos_per_event` | `5` | Сколько новых аватарок отправлять за событие |
| `send_photos` | `true` | Скачивать и отправлять новые аватарки |
| `notify_initial_snapshot` | `true` | Отправлять baseline и доступную profile music |
| `track_online_status` | `false` | Добавлять volatile online status в сравнение |
| `timezone` | `Asia/Yekaterinburg` | Timezone, используемая в `taken_at` snapshot |
| `state_path` | `state/profile_state.json` | Путь к state |
| `events_path` | `logs/profile_events.jsonl` | Путь к JSONL history |
| `media_dir` | `media` | Каталог скачанных фото и музыки |

### Переменные окружения

| Переменная | Поле |
| --- | --- |
| `TG_API_ID` | `telegram.api_id` |
| `TG_API_HASH` | `telegram.api_hash` |
| `TG_PHONE` | `telegram.phone` |
| `BOT_TOKEN` | `bot.token` |
| `ADMIN_IDS` | `bot.admin_ids`, comma-separated |
| `MONITOR_TARGETS` | `monitor.targets`, comma-separated |

Environment values имеют приоритет над config.

## 🤖 Команды Telegram

| Команда | Действие |
| --- | --- |
| `/start` | Справка и inline keyboard |
| `/help` | Справка |
| `/status` | Состояние цикла, paths и последний результат |
| `/watchlist` | Configured targets и сохранённые snapshots |
| `/check` | Немедленно проверить все цели |
| `/check @username` | Разово проверить одну цель |
| `/snapshot @username_or_id` | Показать последний snapshot из state |

Пользователи вне `admin_ids` получают отказ в доступе.

## ⏱️ Интервалы и FloodWait

По умолчанию монитор проверяет цели раз в 300 секунд и делает паузу между ними. Частота 60–120 секунд может быть приемлемой для небольшого списка, но итоговый безопасный интервал зависит от числа фотографий, подарков и доступности Telegram API.

При `FloodWait` монитор ждёт не более 60 секунд внутри текущей проверки, уведомляет администратора и возвращается к обычному циклу. Не запускайте несколько копий с одной session и не уменьшайте интервал без необходимости.

## 💾 Локальные данные

| Путь | Содержимое |
| --- | --- |
| `config.json` | Credentials, targets и настройки; может автоматически обновляться |
| `user_monitor_account.session` | Авторизованная Telethon session |
| `state/profile_state.json` | Последний snapshot каждого profile ID и target index |
| `logs/profile_events.jsonl` | Глобальная baseline/change/error history с полным JSON |
| `logs/accounts/<id_username>/profile_events.jsonl` | История отдельного аккаунта |
| `logs/monitor.log` | Технический runtime log |
| `media/<user_id>/` | Скачанные новые аватарки |
| `media/<user_id>/music/` | Скачанная profile music |

Фактическое имя session зависит от `telegram.session_name`.

## 🔐 Безопасность и приватность

- Никогда не коммитьте `config.json`, `.env`, `*.session` или `*.session-journal`.
- User session даёт доступ вашему Telegram-аккаунту и требует парольного уровня защиты.
- State и events содержат raw profile, chat и gift data, доступные этой session.
- Media может содержать удалённые позднее аватарки и музыку.
- Укажите только собственный admin ID и проверяйте получателя до первого запуска.
- После утечки bot token или API credentials немедленно отзовите их.
- Используйте монитор только законно и с уважением к приватности людей.

## ⚠️ Ограничения

- Числовой ID без `access_hash` может не разрешиться, если entity отсутствует в contacts, dialogs или session cache.
- Сравниваются только первые `profile_photo_limit` аватарок и до `gift_limit` подарков.
- `exclude_unsaved = true` означает, что скрытые пользователем подарки не входят в видимый список.
- Часть новых Telegram fields зависит от установленной версии Telethon и доступности API layer.
- Stored `taken_at` использует config timezone, но текущие Telegram event timestamps форматируются в МСК.
- Bot messages и runtime logs преимущественно русскоязычные.

## 🧪 Проверка и диагностика

В репозитории пока нет автоматических тестов и CI. Полноценная проверка требует реальной user session и Bot API.

Частые проблемы:

- **Config error:** проверьте placeholders и JSON syntax.
- **Session database is locked:** остановите другой Python-процесс с тем же session-файлом.
- **Код не приходит:** проверьте официальный чат Telegram или используйте QR login.
- **Target not found:** используйте `@username`, прогрейте entity в session либо укажите `id:access_hash`.
- **FloodWait:** увеличьте `interval_seconds` и `request_delay_seconds`.
- **Bot не пишет:** проверьте token, `admin_ids` и начат ли диалог с ботом.

## 📄 Лицензия

Проект распространяется по лицензии [MIT](LICENSE).

---

Сделано для ответственного личного мониторинга без обхода приватности Telegram.
