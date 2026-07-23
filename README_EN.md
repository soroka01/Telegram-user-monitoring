# 👤 Telegram User Monitor

> A Telethon and aiogram monitor for Telegram profiles with change notifications, local history, and storage of available media.

🌐 **Language:** [Русский](README.md) · [English](README_EN.md)

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Telethon](https://img.shields.io/badge/Telethon-user_session-0088CC?logo=telegram&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-Telegram_bot-26A5E4?logo=telegram&logoColor=white)
![MIT License](https://img.shields.io/badge/License-MIT-2EA44F.svg)

## ✨ Overview

Telegram User Monitor uses a Telethon user session to read available profile data and a separate Telegram bot for notifications and commands. It stores snapshots, compares them by stable user ID, and informs administrators about changes to profiles, photos, music, and visible gifts.

The project does not bypass Telegram privacy. It sees only the information Telegram exposes to the authorized user account.

## 🚀 Features

- first name, last name, primary username, and additional public usernames;
- Telegram Premium and regular or collectible emoji status;
- bio, birthday, note, and common chat count;
- personal channel and its linked message;
- business hours, location, intro, greeting, and away settings;
- profile/name colors, theme, wallpaper, main tab, and profile flags;
- optional online status;
- current, profile, personal, and fallback photos;
- an available photo list with added and removed photo detection;
- profile music metadata, download, and audio/document delivery;
- `stargifts_count`, Stars rating, and paid-message price;
- visible regular and unique gifts through `GetSavedStarGiftsRequest`;
- sender/recipient, date, message, saved/message IDs, slug, owner, supply, value, and original details;
- raw TL data in local state and event history;
- saved `id`/`access_hash` values and automatic synchronization of the current username into config;
- global and per-account JSONL events;
- administrator-only Telegram commands and an inline keyboard.

## 🏗️ How It Works

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

A username is used for initial resolution, while the stable user ID and saved `access_hash` are used for later checks. A username change should therefore not switch monitoring to a different account.

## 📋 Requirements

- Python 3.10 or newer;
- a Telegram user account;
- an `api_id` and `api_hash` from [Telegram API development tools](https://my.telegram.org);
- a Telegram bot token from [@BotFather](https://t.me/BotFather);
- the Telegram user ID of each administrator;
- at least one target visible to the user session.

Main dependencies:

| Package | Purpose |
| --- | --- |
| `telethon` | User session and MTProto requests |
| `aiogram` | Bot API, commands, and media delivery |
| `qrcode[pil]` | Console QR login |
| `tzdata` | IANA time zones on systems without a system database |

## ⚙️ Installation and Running

### 1. Clone the repository

```bash
git clone https://github.com/soroka01/Telegram-user-monitoring.git
cd Telegram-user-monitoring
```

### 2. Create the config on Windows

```bat
start.bat
```

The first run creates `.venv` and `config.json`, then exits. Fill in the `api_id`, `api_hash`, bot token, administrator IDs, and targets; the phone number is needed only for code login.

### 3. Authorize the user session

Recommended QR login:

```bat
login.bat
```

On your phone, open:

```text
Settings → Devices → Link Desktop Device
```

Scan the QR code from the console. If 2FA is enabled, Telethon also asks for the password.

Code login instead of QR:

```powershell
.\.venv\Scripts\python.exe login.py --code
```

The code arrives in the official **Telegram** chat on an already authorized device, not in the bot you created. The prompt also supports `sms`, `resend`, and `exit` when Telegram allows the corresponding method.

Before using `--code`, replace the example `+79990000000` in `telegram.phone` with your own number.

### 4. Start the monitor

```bat
start.bat
```

`main.py` can also request a login code interactively when the session is not authorized, but the dedicated QR flow through `login.bat` is usually more reliable.

### Manual installation

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

Linux or macOS:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.json config.json
python login.py
python main.py
```

## 🎯 Monitoring Targets

Recommended format:

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

Other supported forms:

| Format | Example | Requirement |
| --- | --- | --- |
| Username | `@username` | Public or otherwise visible to the session |
| Link | `https://t.me/username` | Resolved as a username |
| User ID | `123456789` | The session already knows the entity |
| ID + access hash | `123456789:987654321012345678` | Stable binding without a username |
| Prefix + ID + hash | `id:123456789:987654321012345678` | The same binding in explicit form |

After a successful snapshot, the monitor may rewrite the matching `config.json` entry as an object containing the current `id` and `username`. Additional object keys are preserved. The file is not synchronized when `MONITOR_TARGETS` is used.

## ⚙️ Configuration

### Telegram user session

| Field | Default | Purpose |
| --- | ---: | --- |
| `telegram.api_id` | — | API application ID; required |
| `telegram.api_hash` | — | API application hash; required |
| `telegram.phone` | — | International-format number for code login |
| `telegram.session_name` | `user_monitor_account` | Telethon session name or path without `.session` |
| `telegram.qr_login_attempts` | `10` | Maximum number of QR refreshes |
| `telegram.qr_login_timeout_seconds` | `55` | Lifetime of one QR attempt; minimum 15 seconds |

### Bot

| Field | Purpose |
| --- | --- |
| `bot.token` | Bot token from BotFather |
| `bot.admin_ids` | Users who receive alerts and can run commands |

Replace the `123456789` placeholder. It is a syntactically valid Telegram ID.

### Monitor

| Field | Default | Purpose |
| --- | ---: | --- |
| `targets` | — | Persistent targets; at least one is required |
| `interval_seconds` | `300` | Check interval; minimum 30 seconds |
| `request_delay_seconds` | `1.0` | Delay between targets |
| `profile_photo_limit` | `20` | Number of recent photos to compare |
| `gift_limit` | `200` | Maximum visible gifts in a snapshot |
| `max_photos_per_event` | `5` | Maximum new photos sent for one event |
| `send_photos` | `true` | Download and send newly visible photos |
| `notify_initial_snapshot` | `true` | Send the baseline and available profile music |
| `track_online_status` | `false` | Include volatile online status in comparisons |
| `timezone` | `Asia/Yekaterinburg` | Time zone used for snapshot `taken_at` |
| `state_path` | `state/profile_state.json` | State path |
| `events_path` | `logs/profile_events.jsonl` | JSONL history path |
| `media_dir` | `media` | Downloaded photo and music directory |

### Environment variables

| Variable | Field |
| --- | --- |
| `TG_API_ID` | `telegram.api_id` |
| `TG_API_HASH` | `telegram.api_hash` |
| `TG_PHONE` | `telegram.phone` |
| `BOT_TOKEN` | `bot.token` |
| `ADMIN_IDS` | `bot.admin_ids`, comma-separated |
| `MONITOR_TARGETS` | `monitor.targets`, comma-separated |

Environment values take precedence over config.

## 🤖 Telegram Commands

| Command | Action |
| --- | --- |
| `/start` | Help and inline keyboard |
| `/help` | Help |
| `/status` | Cycle state, paths, and last result |
| `/watchlist` | Configured targets and saved snapshots |
| `/check` | Check every target immediately |
| `/check @username` | Check one target once |
| `/snapshot @username_or_id` | Show the latest snapshot from state |

Users outside `admin_ids` receive an access-denied response.

## ⏱️ Intervals and FloodWait

By default, the monitor checks targets every 300 seconds and pauses between them. A 60–120 second interval may be reasonable for a small list, but the safe value depends on photo count, gift count, and Telegram API availability.

On `FloodWait`, the monitor waits for at most 60 seconds inside the current check, informs the administrator, and returns to its normal loop. Do not run several copies with one session, and do not lower the interval without a reason.

## 💾 Local Data

| Path | Contents |
| --- | --- |
| `config.json` | Credentials, targets, and settings; may be updated automatically |
| `user_monitor_account.session` | Authorized Telethon session |
| `state/profile_state.json` | Latest snapshot for each profile ID and the target index |
| `logs/profile_events.jsonl` | Global baseline/change/error history with full JSON |
| `logs/accounts/<id_username>/profile_events.jsonl` | History for one account |
| `logs/monitor.log` | Technical runtime log |
| `media/<user_id>/` | Downloaded newly visible photos |
| `media/<user_id>/music/` | Downloaded profile music |

The actual session filename depends on `telegram.session_name`.

## 🔐 Security and Privacy

- Never commit `config.json`, `.env`, `*.session`, or `*.session-journal`.
- A user session grants access to your Telegram account and needs password-level protection.
- State and events contain raw profile, chat, and gift data visible to that session.
- Media may preserve photos and music that are later removed.
- Configure only your own administrator ID and verify the recipient before the first run.
- Revoke leaked bot tokens or API credentials immediately.
- Use the monitor lawfully and with respect for other people's privacy.

## ⚠️ Limitations

- A numeric ID without an `access_hash` may not resolve when the entity is absent from contacts, dialogs, and the session cache.
- Only the first `profile_photo_limit` photos and up to `gift_limit` gifts are compared.
- `exclude_unsaved = true` means gifts hidden by the user are not part of the visible list.
- Some newer Telegram fields depend on the installed Telethon version and available API layer.
- Stored `taken_at` uses the configured time zone, while current Telegram event timestamps are formatted in Moscow time.
- Bot messages and runtime logs are primarily in Russian.

## 🧪 Testing and Troubleshooting

The repository currently has no automated tests or CI. End-to-end verification requires a real user session and the Bot API.

Common problems:

- **Config error:** check placeholders and JSON syntax.
- **Session database is locked:** stop the other Python process using the same session file.
- **No login code:** check the official Telegram chat or use QR login.
- **Target not found:** use `@username`, make the entity known to the session, or provide `id:access_hash`.
- **FloodWait:** increase `interval_seconds` and `request_delay_seconds`.
- **No bot messages:** verify the token, `admin_ids`, and that you have started a chat with the bot.

## 📄 License

This project is distributed under the [MIT License](LICENSE).

---

Built for responsible personal monitoring without bypassing Telegram privacy.
