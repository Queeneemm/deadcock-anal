# Deadlock Scout Bot

Telegram-бот на Python 3.11+ для отслеживания матчей Deadlock, аналитики и отправки PNG-карточек.

## Что актуально по интеграции API

Проект использует только подтверждённый маршрут истории матчей:
- `GET /v1/players/{account_id}/match-history`

Подтверждённые сервисные маршруты для ручной проверки:
- `/openapi.json`
- `/docs`
- `/v1/info`

Неподтверждённые/старые маршруты больше не используются:
- `/players/search`
- `/players/recent-matches`
- `/players/{id}`
- `/match-history/{account_id}`
- `/steam-profile/{account_id}`

Профиль игрока в боте теперь строится по истории матчей (fallback-режим), а расширенные детали матча также работают в fallback-режиме без выдуманных данных.

## Возможности
- Отслеживание нескольких игроков на одного Telegram-пользователя.
- Автоматический polling новых матчей.
- Отправка отчётов без дублей.
- Аналитика и генерация карточек матча.
- Inline-кнопки для быстрого управления.

## Стек
- Python 3.11+
- aiogram 3.x
- httpx
- sqlite3
- Pillow
- pydantic / pydantic-settings

## Установка и запуск

### 1) Виртуальное окружение
```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### 2) Установка зависимостей
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3) Настройка переменных окружения
```bash
cp .env.example .env
```

Заполните `.env`:
- `BOT_TOKEN` — токен Telegram-бота
- `DEADLOCK_API_BASE_URL` — базовый URL Deadlock API
- `DEADLOCK_ASSETS_BASE_URL` — базовый URL API ассетов
- `DATABASE_URL=sqlite:///data/bot.db`
- `POLL_INTERVAL_SECONDS` — интервал автоопроса
- `REQUEST_TIMEOUT_SECONDS` — таймаут запросов
- `ASSET_CACHE_DIR` — локальный кэш ассетов
- `CARD_OUTPUT_DIR` — папка PNG-карточек
- `LOG_LEVEL` — уровень логирования

### 4) Запуск
```bash
python -m app.bot
```

## Команды бота
- `/addplayer <account_id|Steam64|steam_profile_url>`
- `/players`
- `/removeplayer <account_id>`
- `/track <account_id> <on|off>`
- `/lastmatch <account_id>`
- `/profile <account_id>`

> Поиск игрока по нику через API отключён: используйте только `account_id`, `Steam64` или ссылку `steamcommunity`.

## Поток идентификаторов
- Основной идентификатор внутри проекта: `account_id`.
- Если пользователь вводит SteamID64, бот преобразует его в `account_id`.
- Если пользователь вводит ссылку `steamcommunity.com/profiles/...` или `steamcommunity.com/id/...`, бот извлекает SteamID64 и затем преобразует его в `account_id`.
- В БД исторически используется имя поля `player_id`, но фактически в нём хранится `account_id`.

## Как вручную проверить API через curl

Пусть:
- `BASE_URL` — базовый URL (например, `https://deadlock-api.example.com`)
- `ACCOUNT_ID` — numeric account_id

```bash
curl -sS "$BASE_URL/v1/info"
curl -sS "$BASE_URL/openapi.json"
curl -sS "$BASE_URL/docs"
curl -sS "$BASE_URL/v1/players/$ACCOUNT_ID/match-history"
```

Примеры поддерживаемого ввода для `/addplayer`:
- `123456789` (account_id)
- `7656119...` (Steam64, будет конвертирован)
- `https://steamcommunity.com/profiles/7656119...`
- `https://steamcommunity.com/id/vanity_name`

## Обработка ошибок API

В клиенте добавлены типизированные исключения:
- `DeadlockApiError` — базовая ошибка API.
- `DeadlockApiNotFoundError` — 404.
- `DeadlockApiTemporaryError` — 429/5xx и сетевые проблемы (с retry).
- `DeadlockApiUnsupportedRouteError` — неподтверждённый маршрут.

Поведение:
- Хендлеры `/addplayer`, `/lastmatch`, `/profile` не падают при API-ошибках.
- Polling не спамит одинаковыми 404 в логах (повторные предупреждения подавляются).
- Если деталей матча нет, используется parsing из `match-history`.

## Структура проекта
```text
app/
  bot.py
  config.py
  db.py
  models.py
  repositories/
    users.py
    players.py
    matches.py
  clients/
    deadlock_api.py
    assets.py
  services/
    polling.py
    analytics.py
    cards.py
  handlers/
    start.py
    players.py
    reports.py
  keyboards/
    inline.py
  utils/
    logging.py
    image.py
README.md
```
