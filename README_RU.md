# 👤 Telegram User Monitor

> Монитор Telegram-профилей на Telethon и aiogram с уведомлениями об изменениях, локальной историей и сохранением доступных медиа.

🌐 **Язык / Language:** [Русский](README_RU.md) · [English](README.md)

![Python 3.14+](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)
![Telethon](https://img.shields.io/badge/Telethon-user_session-0088CC?logo=telegram&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-Telegram_bot-26A5E4?logo=telegram&logoColor=white)
![MIT License](https://img.shields.io/badge/License-MIT-2EA44F.svg)

## 📌 Обзор

Telegram User Monitor использует пользовательскую Telethon session для чтения доступных профильных данных и отдельного Telegram-бота для уведомлений и команд. Монитор сохраняет snapshots, сравнивает их по стабильному user ID и сообщает администраторам об изменениях профиля, аватарок, музыки и видимых подарков.

> [!NOTE]
> Проект не обходит приватность Telegram: он видит только то, что Telegram показывает авторизованному пользовательскому аккаунту.

## ✨ Возможности

- имя, фамилия, основной и дополнительные публичные username;
- Premium и обычный или collectible emoji status;
- bio, birthday, note, common chats count, personal channel;
- business hours, location, intro, greeting и away settings;
- profile/name colors, theme, wallpaper, main tab, profile flags;
- опциональный online status;
- аватарки (current, profile, personal, fallback) с обнаружением добавления и удаления;
- profile music: metadata, скачивание и отправка;
- `stargifts_count`, Stars rating, цена paid-сообщения;
- видимые обычные и unique gifts через `GetSavedStarGiftsRequest`;
- raw TL data в локальном state и истории событий;
- привязка к `id`/`access_hash` и автосинхронизация актуального username в config;
- глобальные и per-account JSONL events;
- admin-only команды бота и inline keyboard;
- включение и отключение целей без удаления из конфига (`active` / `inactive`).

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

Username нужен только для первого resolution; дальше используются стабильный user ID и сохранённый `access_hash`, поэтому смена username не переключит монитор на другой аккаунт.

## 🚀 Быстрый старт

### Требования

- Python 3.14+ (рекомендуется актуальный патч 3.14.6);
- пользовательский Telegram-аккаунт;
- `api_id` и `api_hash` из [Telegram API development tools](https://my.telegram.org);
- bot token от [@BotFather](https://t.me/BotFather) и Telegram user ID каждого администратора;
- хотя бы одна цель мониторинга.

| Пакет | Назначение |
| --- | --- |
| `telethon` | User session и MTProto requests |
| `aiogram` | Bot API, команды и отправка media |
| `qrcode[pil]` | QR login в консоли |
| `tzdata` | IANA timezones на системах без системной базы |

### Установка

```bash
git clone https://github.com/soroka01/Telegram-user-monitoring.git
cd Telegram-user-monitoring
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
```

Linux или macOS:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.json config.json
```

### Настройка

Заполните в `config.json`: `telegram.api_id`, `telegram.api_hash`, `bot.token`, `bot.admin_ids` и `monitor.targets`. `telegram.phone` нужен только для входа кодом; замените пример `+79990000000` своим номером. Placeholder `123456789` в `admin_ids` обязательно замените: это синтаксически допустимый Telegram ID.

### Запуск

Авторизуйте user session (рекомендуется QR-вход):

```bash
python login.py
```

В Telegram на телефоне откройте `Настройки → Устройства → Подключить устройство` и отсканируйте QR из консоли. При включённом 2FA Telethon дополнительно запросит пароль.

Вход кодом вместо QR:

```bash
python login.py --code
```

Код приходит в официальный чат **Telegram** на уже авторизованном устройстве, а не в созданного бота. В prompt доступны `sms`, `resend` и `exit`, если Telegram разрешает соответствующий способ.

Запуск монитора:

```bash
python main.py
```

`main.py` тоже умеет интерактивно запросить код, если session ещё не авторизована, но отдельный QR-вход обычно надёжнее.

> [!WARNING]
> `login.bat` создаёт `.venv`, ставит зависимости и запускает `login.py`. Текущий `start.bat` не запускает `main.py`: это compatibility-ссылка на соседний проект `..\telegram_username_checker`. Для запуска монитора используйте `python main.py`.

## ⚙️ Конфигурация

### Telegram session (`telegram`)

| Поле | По умолчанию | Описание |
| --- | ---: | --- |
| `api_id` | — | API application ID; обязателен |
| `api_hash` | — | API application hash; обязателен |
| `phone` | — | Номер в международном формате для code login |
| `session_name` | `user_monitor_account` | Имя или путь Telethon session без `.session` |
| `qr_login_attempts` | `10` | Максимальное число обновлений QR |
| `qr_login_timeout_seconds` | `55` | Время жизни одной QR-попытки; минимум 15 секунд |

### Bot (`bot`)

| Поле | По умолчанию | Описание |
| --- | ---: | --- |
| `token` | — | Bot token от BotFather |
| `admin_ids` | — | Пользователи, получающие alerts и имеющие доступ к командам |

### Monitor (`monitor`)

| Поле | По умолчанию | Описание |
| --- | ---: | --- |
| `targets` | — | Цели (`active` / `inactive`); нужен хотя бы один элемент |
| `interval_seconds` | `300` | Период проверки; минимум 30 секунд |
| `request_delay_seconds` | `1.0` | Пауза между целями |
| `profile_photo_limit` | `20` | Сколько последних аватарок сравнивать |
| `gift_limit` | `200` | Максимум видимых подарков на snapshot |
| `max_photos_per_event` | `5` | Сколько новых аватарок отправлять за событие |
| `send_photos` | `true` | Скачивать и отправлять новые аватарки |
| `notify_initial_snapshot` | `true` | Отправлять baseline и доступную profile music |
| `track_online_status` | `false` | Добавлять volatile online status в сравнение |
| `timezone` | `Asia/Yekaterinburg` | Timezone для `taken_at` snapshot |
| `state_path` | `state/profile_state.json` | Путь к state |
| `events_path` | `logs/profile_events.jsonl` | Путь к JSONL history |
| `media_dir` | `media` | Каталог скачанных фото и музыки |

### Переменные окружения

Имеют приоритет над `config.json`.

| Переменная | Поле config |
| --- | --- |
| `TG_API_ID` | `telegram.api_id` |
| `TG_API_HASH` | `telegram.api_hash` |
| `TG_PHONE` | `telegram.phone` |
| `BOT_TOKEN` | `bot.token` |
| `ADMIN_IDS` | `bot.admin_ids`, через запятую |
| `MONITOR_TARGETS` | `monitor.targets`, через запятую |

### Цели мониторинга

```json
{
  "monitor": {
    "targets": {
      "active": [{"id": 123456789, "username": "@username"}],
      "inactive": [{"id": 987654321, "username": null}]
    }
  }
}
```

`active` проверяются по расписанию; `inactive` остаются в конфиге и state, но не мониторятся. Переключать можно командами бота `/enable` и `/disable`. Поддерживаемые форматы записи цели:

| Формат | Пример | Условие |
| --- | --- | --- |
| Username | `@username` | Публичный или доступный session username |
| Ссылка | `https://t.me/username` | Разрешается как username |
| User ID | `123456789` | Session уже знает entity |
| ID + access hash | `123456789:987654321012345678` | Надёжная привязка без username |
| Prefix + ID + hash | `id:123456789:987654321012345678` | То же в явном формате |

После успешного snapshot монитор может переписать запись цели в `config.json` в объект с актуальными `id` и `username` (дополнительные ключи сохраняются). При использовании `MONITOR_TARGETS` файл не синхронизируется.

### Команды бота

Доступны только пользователям из `admin_ids`; остальные получают отказ.

| Команда | Действие |
| --- | --- |
| `/start` | Справка и inline keyboard |
| `/help` | Справка |
| `/status` | Состояние цикла, paths и последний результат |
| `/watchlist` | Цели и сохранённые snapshots |
| `/check` | Немедленно проверить все цели |
| `/check @username` | Разово проверить одну цель |
| `/enable @username_or_id` | Включить цель в постоянном мониторинге |
| `/disable @username_or_id` | Отключить цель, сохранив её в config и state |
| `/snapshot @username_or_id` | Показать последний snapshot из state |

### Интервалы и FloodWait

Частота 60–120 секунд может подойти для небольшого списка, но безопасный интервал зависит от числа фотографий, подарков и доступности Telegram API. При `FloodWait` монитор ждёт не более 60 секунд внутри текущей проверки, уведомляет администратора и возвращается к обычному циклу. Не запускайте несколько копий с одной session.

## 🗂️ Структура проекта

```text
.
├── main.py                 # монитор: Telethon snapshots, diff, aiogram-бот
├── login.py                # авторизация user session (QR или --code)
├── login.bat               # Windows: .venv + зависимости + login.py
├── start.bat               # compatibility-ссылка на ..\telegram_username_checker
├── config.example.json     # шаблон конфигурации
├── requirements.txt        # зависимости
├── LICENSE                 # MIT
├── config.json             # ваш конфиг (не коммитится)
├── user_monitor_account.session  # Telethon session (не коммитится)
├── state/
│   └── profile_state.json  # последний snapshot каждого профиля
├── logs/
│   ├── profile_events.jsonl                       # глобальная история baseline/change/error
│   ├── accounts/{active,inactive}/<id_username>/  # история по аккаунтам
│   └── monitor.log         # технический runtime log
└── media/
    └── <user_id>/          # аватарки; music/ — profile music
```

Каталоги `state/`, `logs/` и `media/` создаются при работе и исключены через `.gitignore`. Фактическое имя session зависит от `telegram.session_name`.

## 🔒 Безопасность и приватность

- Никогда не коммитьте `config.json`, `.env`, `*.session` или `*.session-journal`.
- User session даёт доступ к вашему Telegram-аккаунту: храните её как пароль.
- State и events содержат raw profile, chat и gift data, доступные этой session.
- Media может содержать аватарки и музыку, удалённые владельцем позднее.
- Указывайте только собственный admin ID и проверяйте получателя до первого запуска.
- После утечки bot token или API credentials немедленно отзовите их.
- Используйте монитор законно и с уважением к приватности людей.

## ⚠️ Ограничения

- Числовой ID без `access_hash` может не разрешиться, если entity нет в contacts, dialogs или session cache.
- Сравниваются только первые `profile_photo_limit` аватарок и до `gift_limit` подарков.
- `exclude_unsaved = true`: скрытые пользователем подарки не входят в видимый список.
- Часть новых Telegram fields зависит от версии Telethon и доступности API layer.
- Stored `taken_at` использует timezone из config, а текущие Telegram event timestamps форматируются в МСК.
- Сообщения бота и runtime logs преимущественно русскоязычные.
- Автоматических тестов и CI нет; полноценная проверка требует реальной user session и Bot API.

Частые проблемы:

- **Config error:** проверьте placeholders и JSON syntax.
- **Session database is locked:** остановите другой Python-процесс с тем же session-файлом.
- **Код не приходит:** проверьте официальный чат Telegram или используйте QR login.
- **Target not found:** используйте `@username`, прогрейте entity в session либо укажите `id:access_hash`.
- **FloodWait:** увеличьте `interval_seconds` и `request_delay_seconds`.
- **Бот не пишет:** проверьте token, `admin_ids` и начат ли диалог с ботом.

## 📄 Лицензия

Проект распространяется по лицензии [MIT](LICENSE).

## 💬 Поддержка

Если проект оказался полезен, поставьте ⭐ на [GitHub](https://github.com/soroka01/Telegram-user-monitoring) или сделайте fork и адаптируйте под свои задачи.

---

with love ❤️
