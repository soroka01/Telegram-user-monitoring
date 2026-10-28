# 👤 Telegram User Monitor

> A Telethon and aiogram monitor for Telegram profiles with change notifications, local history, and storage of available media.

🌐 **Language / Язык:** [English](README.md) · [Русский](README_RU.md)

![Python 3.14+](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)
![Telethon](https://img.shields.io/badge/Telethon-user_session-0088CC?logo=telegram&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-Telegram_bot-26A5E4?logo=telegram&logoColor=white)
![MIT License](https://img.shields.io/badge/License-MIT-2EA44F.svg)

## 📌 Overview

Telegram User Monitor uses a Telethon user session to read available profile data and a separate Telegram bot for notifications and commands. It stores snapshots, compares them by stable user ID, and informs administrators about changes to profiles, photos, music, and visible gifts.

> [!NOTE]
> The project does not bypass Telegram privacy: it sees only what Telegram exposes to the authorized user account.

## ✨ Features

- first name, last name, primary username, and additional public usernames;
- Premium and regular or collectible emoji status;
- bio, birthday, note, common chats count, personal channel;
- business hours, location, intro, greeting, and away settings;
- profile/name colors, theme, wallpaper, main tab, profile flags;
- optional online status;
- photos (current, profile, personal, fallback) with added and removed photo detection;
- profile music: metadata, download, and delivery;
- `stargifts_count`, Stars rating, paid-message price;
- visible regular and unique gifts through `GetSavedStarGiftsRequest`;
- raw TL data in local state and event history;
- binding to `id`/`access_hash` and automatic synchronization of the current username into config;
- global and per-account JSONL events;
- administrator-only bot commands and an inline keyboard;
- enabling and disabling targets without removing them from config (`active` / `inactive`).

## 🏗️ How it works

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

A username is used only for initial resolution; later checks use the stable user ID and the saved `access_hash`, so a username change will not switch monitoring to a different account.

## 🚀 Quick start

### Requirements

- Python 3.14+ (the latest 3.14.6 patch is recommended);
- a Telegram user account;
- an `api_id` and `api_hash` from [Telegram API development tools](https://my.telegram.org);
- a bot token from [@BotFather](https://t.me/BotFather) and the Telegram user ID of each administrator;
- at least one monitoring target.

| Package | Purpose |
| --- | --- |
| `telethon` | User session and MTProto requests |
| `aiogram` | Bot API, commands, and media delivery |
| `qrcode[pil]` | Console QR login |
| `tzdata` | IANA time zones on systems without a system database |

### Installation

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

Linux or macOS:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.json config.json
```

### Configuration

In `config.json`, fill in `telegram.api_id`, `telegram.api_hash`, `bot.token`, `bot.admin_ids`, and `monitor.targets`. `telegram.phone` is needed only for code login; replace the example `+79990000000` with your own number. Be sure to replace the `123456789` placeholder in `admin_ids`: it is a syntactically valid Telegram ID.

### Run

Authorize the user session (QR login is recommended):

```bash
python login.py
```

On your phone, open `Settings → Devices → Link Desktop Device` and scan the QR code from the console. If 2FA is enabled, Telethon also asks for the password.

Code login instead of QR:

```bash
python login.py --code
```

The code arrives in the official **Telegram** chat on an already authorized device, not in the bot you created. The prompt also supports `sms`, `resend`, and `exit` when Telegram allows the corresponding method.

Start the monitor:

```bash
python main.py
```

`main.py` can also request a login code interactively when the session is not authorized, but the dedicated QR flow is usually more reliable.

> [!WARNING]
> `login.bat` creates `.venv`, installs dependencies, and runs `login.py`. The current `start.bat` does not start `main.py`: it is a compatibility link to the sibling project `..\telegram_username_checker`. Use `python main.py` to run the monitor.

## ⚙️ Configuration

### Telegram session (`telegram`)

| Field | Default | Description |
| --- | ---: | --- |
| `api_id` | — | API application ID; required |
| `api_hash` | — | API application hash; required |
| `phone` | — | International-format number for code login |
| `session_name` | `user_monitor_account` | Telethon session name or path without `.session` |
| `qr_login_attempts` | `10` | Maximum number of QR refreshes |
| `qr_login_timeout_seconds` | `55` | Lifetime of one QR attempt; minimum 15 seconds |

### Bot (`bot`)

| Field | Default | Description |
| --- | ---: | --- |
| `token` | — | Bot token from BotFather |
| `admin_ids` | — | Users who receive alerts and can run commands |

### Monitor (`monitor`)

| Field | Default | Description |
| --- | ---: | --- |
| `targets` | — | Targets (`active` / `inactive`); at least one entry is required |
| `interval_seconds` | `300` | Check interval; minimum 30 seconds |
| `request_delay_seconds` | `1.0` | Delay between targets |
| `profile_photo_limit` | `20` | Number of recent photos to compare |
| `gift_limit` | `200` | Maximum visible gifts per snapshot |
| `max_photos_per_event` | `5` | Maximum new photos sent per event |
| `send_photos` | `true` | Download and send newly visible photos |
| `notify_initial_snapshot` | `true` | Send the baseline and available profile music |
| `track_online_status` | `false` | Include volatile online status in comparisons |
| `timezone` | `Asia/Yekaterinburg` | Time zone used for snapshot `taken_at` |
| `state_path` | `state/profile_state.json` | State path |
| `events_path` | `logs/profile_events.jsonl` | JSONL history path |
| `media_dir` | `media` | Downloaded photo and music directory |

### Environment variables

They take precedence over `config.json`.

| Variable | Config field |
| --- | --- |
| `TG_API_ID` | `telegram.api_id` |
| `TG_API_HASH` | `telegram.api_hash` |
| `TG_PHONE` | `telegram.phone` |
| `BOT_TOKEN` | `bot.token` |
| `ADMIN_IDS` | `bot.admin_ids`, comma-separated |
| `MONITOR_TARGETS` | `monitor.targets`, comma-separated |

### Monitoring targets

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

`active` targets are checked on schedule; `inactive` ones stay in config and state but are not monitored. Switch them with the bot commands `/enable` and `/disable`. Supported target formats:

| Format | Example | Requirement |
| --- | --- | --- |
| Username | `@username` | Public or otherwise visible to the session |
| Link | `https://t.me/username` | Resolved as a username |
| User ID | `123456789` | The session already knows the entity |
| ID + access hash | `123456789:987654321012345678` | Stable binding without a username |
| Prefix + ID + hash | `id:123456789:987654321012345678` | The same binding in explicit form |

After a successful snapshot, the monitor may rewrite the target entry in `config.json` as an object containing the current `id` and `username` (additional keys are preserved). The file is not synchronized when `MONITOR_TARGETS` is used.

### Bot commands

Available only to users in `admin_ids`; everyone else receives an access-denied response.

| Command | Action |
| --- | --- |
| `/start` | Help and inline keyboard |
| `/help` | Help |
| `/status` | Cycle state, paths, and last result |
| `/watchlist` | Targets and saved snapshots |
| `/check` | Check every target immediately |
| `/check @username` | Check one target once |
| `/enable @username_or_id` | Enable a target for continuous monitoring |
| `/disable @username_or_id` | Disable a target, keeping it in config and state |
| `/snapshot @username_or_id` | Show the latest snapshot from state |

### Intervals and FloodWait

A 60–120 second interval may be reasonable for a small list, but the safe value depends on photo count, gift count, and Telegram API availability. On `FloodWait`, the monitor waits for at most 60 seconds inside the current check, informs the administrator, and returns to its normal loop. Do not run several copies with one session.

## 🗂️ Project structure

```text
.
├── main.py                 # monitor: Telethon snapshots, diff, aiogram bot
├── login.py                # user session authorization (QR or --code)
├── login.bat               # Windows: .venv + dependencies + login.py
├── start.bat               # compatibility link to ..\telegram_username_checker
├── config.example.json     # configuration template
├── requirements.txt        # dependencies
├── LICENSE                 # MIT
├── config.json             # your config (not committed)
├── user_monitor_account.session  # Telethon session (not committed)
├── state/
│   └── profile_state.json  # latest snapshot of each profile
├── logs/
│   ├── profile_events.jsonl                       # global baseline/change/error history
│   ├── accounts/{active,inactive}/<id_username>/  # per-account history
│   └── monitor.log         # technical runtime log
└── media/
    └── <user_id>/          # photos; music/ holds profile music
```

The `state/`, `logs/`, and `media/` directories are created at runtime and excluded via `.gitignore`. The actual session filename depends on `telegram.session_name`.

## 🔒 Security & privacy

- Never commit `config.json`, `.env`, `*.session`, or `*.session-journal`.
- A user session grants access to your Telegram account: protect it like a password.
- State and events contain raw profile, chat, and gift data visible to that session.
- Media may preserve photos and music that the owner later removes.
- Configure only your own administrator ID and verify the recipient before the first run.
- Revoke leaked bot tokens or API credentials immediately.
- Use the monitor lawfully and with respect for other people's privacy.

## ⚠️ Limitations

- A numeric ID without an `access_hash` may not resolve when the entity is absent from contacts, dialogs, and the session cache.
- Only the first `profile_photo_limit` photos and up to `gift_limit` gifts are compared.
- `exclude_unsaved = true`: gifts hidden by the user are not part of the visible list.
- Some newer Telegram fields depend on the installed Telethon version and available API layer.
- Stored `taken_at` uses the configured time zone, while current Telegram event timestamps are formatted in Moscow time.
- Bot messages and runtime logs are primarily in Russian.
- There are no automated tests or CI; end-to-end verification requires a real user session and the Bot API.

Common problems:

- **Config error:** check placeholders and JSON syntax.
- **Session database is locked:** stop the other Python process using the same session file.
- **No login code:** check the official Telegram chat or use QR login.
- **Target not found:** use `@username`, make the entity known to the session, or provide `id:access_hash`.
- **FloodWait:** increase `interval_seconds` and `request_delay_seconds`.
- **No bot messages:** verify the token, `admin_ids`, and that you have started a chat with the bot.

## 📄 License

This project is distributed under the [MIT License](LICENSE).

## 💬 Support

If the project is useful to you, give it a ⭐ on [GitHub](https://github.com/soroka01/Telegram-user-monitoring) or fork it and adapt it to your needs.

---

with love ❤️
