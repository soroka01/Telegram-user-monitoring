# User Monitor

Монитор Telegram-профилей на Telethon и aiogram. Пользовательская Telethon-сессия читает профиль, а бот пишет админу о смене имени, фамилии, username, premium emoji status, описания, музыки профиля, бизнес-графика, канала в профиле, аватарок и видимых подарков.

Админ по умолчанию: указывается в конфиге.

## Что отслеживается

- имя, фамилия, основной `@username` и дополнительные публичные username;
- Telegram Premium и emoji status около имени;
- описание профиля, день рождения, цвета/тема/обои профиля;
- музыка профиля: название, исполнитель, длительность, document id, имя файла и отправка самого аудио ботом, если Telegram отдает файл;
- бизнес-график, бизнес-адрес, intro, greeting/away настройки;
- канал в профиле и сообщение канала, если Telegram их отдает;
- текущая аватарка, personal/fallback photo и список видимых аватарок;
- `stargifts_count` из full profile;
- видимые подарки профиля через `payments.GetSavedStarGiftsRequest`;
- по каждому видимому подарку: отправитель, дата, подпись, saved_id/msg_id, тип подарка, unique slug, номер, владелец, стоимость/тираж, original details и raw JSON.

Подарки читаются с `exclude_unsaved=true`, поэтому монитор ловит ситуацию, когда пользователь включил отображение старого подарка в профиле: для монитора он именно "появится".

## Настройка

1. Запусти `start.bat` один раз. Он создаст `config.json` из примера.
2. Заполни:

```json
{
  "telegram": {
    "api_id": "PUT_API_ID_HERE",
    "api_hash": "PUT_API_HASH_HERE",
    "phone": "+79990000000"
  },
  "bot": {
    "token": "PUT_BOT_TOKEN_HERE",
    "admin_ids": [123456789]
  },
  "monitor": {
    "targets": [
      {"id": 123456789, "username": "@username"},
      {"id": 987654321, "username": null}
    ]
  }
}
```

`api_id` и `api_hash` берутся на `https://my.telegram.org` в `API development tools`.

Цели можно задавать:

- объектом `{"id": 123456789, "username": "@username"}` - рекомендуемый формат;
- `@username`;
- числовым id без `@`, например `979807884`, если Telethon-сессия уже знает этот аккаунт или он есть в контактах;
- расширенно как `user_id:access_hash` или `id:user_id:access_hash`, если нужно закрепиться за аккаунтом без username.

После первого успешного снимка монитор сохраняет `id/access_hash` и дальше старается следить за тем же аккаунтом, даже если username сменился. Также он сам обновляет `monitor.targets` в `config.json` до актуальных `id` и `@username`, если цель была указана старым username или голым id.

## Запуск

```bat
Telegram-user-monitoring\start.bat
```

Или вручную:

```powershell
cd Telegram-user-monitoring
python -m pip install -r requirements.txt
python main.py
```

При первом запуске Telethon попросит код входа и пароль 2FA, если он включен. Файл `user_monitor_account.session` нельзя публиковать.

Самый надежный вход:

```bat
login.bat
```

По умолчанию он покажет QR. Открой Telegram на телефоне: `Настройки -> Устройства -> Подключить устройство`, затем отсканируй QR из консоли. Если нужен старый вход кодом:

```powershell
python login.py --code
```

Если код не пришел:

- смотри не бота, а официальный чат `Telegram` в уже открытом Telegram на телефоне/ПК;
- проверь `telegram.phone` в `config.json`: нужен формат `+79990000000`;
- лучше используй QR-вход: `login.bat`;
- в новом prompt можно ввести `sms`, если Telegram разрешит SMS, или `resend` для повторной отправки.

## Команды бота

- `/status` - состояние мониторинга;
- `/watchlist` - цели из config и последние снимки;
- `/check` - проверить все цели сейчас;
- `/check @username` - разовая проверка одной цели;
- `/snapshot @username_or_id` - показать последний снимок из `state`.

## КД проверки

Периодическая проверка задается в `config.json`:

```json
"interval_seconds": 300
```

`300` секунд - это раз в 5 минут. Обычно это нормальный режим. Если целей много или у профилей много подарков/аватарок, лучше не опускаться ниже 60-120 секунд, чтобы не словить FloodWait от Telegram.

## Где лежат данные

- `state/profile_state.json` - последний снимок каждого профиля;
- `logs/profile_events.jsonl` - история baseline/change/error событий с полным JSON;
- `logs/monitor.log` - технический лог;
- `media/<user_id>/` - скачанные новые аватарки и музыка профиля в `media/<user_id>/music/`.

## Важные ограничения Telegram

Монитор не обходит приватность Telegram. Он видит только то, что доступно пользовательскому аккаунту Telethon. Числовой id без `access_hash` может не резолвиться, если аккаунта нет в контактах, диалогах или кеше сессии.
