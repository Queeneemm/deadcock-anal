# Deadlock Scout Bot

Telegram-бот на Python 3.11+ для отслеживания матчей Deadlock, аналитики и отправки PNG-карточек.

## Что было исправлено в интеграции API

Ранее проект использовал неподтверждённые маршруты `players/...`:
- `/players/search?q=...`
- `/players/recent-matches?player_id=...`
- `/players/{id}`

Эти маршруты удалены из кода. Теперь клиент использует только подтверждённые пути:
- `/match-history/{account_id}`
- `/steam-profile/{account_id}`

Проект переведён на поток `account_id` (вместо вымышленных player endpoints). SteamID64 поддерживается и автоматически преобразуется в `account_id`.

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
- `/addplayer <account_id|steam_profile_url>`
- `/players`
- `/removeplayer <account_id>`
- `/track <account_id> <on|off>`
- `/lastmatch <account_id>`
- `/profile <account_id>`

## Поток идентификаторов
- Основной идентификатор внутри проекта: `account_id`.
- Если пользователь вводит SteamID64, бот преобразует его в `account_id`.
- Если пользователь вводит ссылку `steamcommunity.com/profiles/...` или `steamcommunity.com/id/...`, бот извлекает SteamID64 и затем преобразует его в `account_id`.
- В БД исторически используется имя поля `player_id`, но фактически в нём хранится `account_id`.

## Обработка ошибок API

В клиенте добавлены типизированные исключения:
- `DeadlockApiError` — базовая ошибка API.
- `DeadlockApiNotFoundError` — 404.
- `DeadlockApiTemporaryError` — 429/5xx и сетевые проблемы (с retry).
- `DeadlockApiUnsupportedRouteError` — неподтверждённый маршрут.

Поведение:
- Хендлеры `/addplayer`, `/lastmatch`, `/profile` не падают при API-ошибках.
- Polling не спамит одинаковыми 404 в логах (повторные предупреждения подавляются).
- При неподтверждённом маршруте деталей матча используется мягкий fallback на данные из `match-history`.

## Что делать, если маршруты API отличаются от ожидаемых

1. Откройте `app/clients/deadlock_api.py`.
2. Измените только структуру `DeadlockApiRoutes`.
3. Не добавляйте маршруты «наугад». Сначала подтвердите их по документации/источнику.
4. Если новый маршрут не подтверждён, оставьте `None` и используйте fallback через `DeadlockApiUnsupportedRouteError`.

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
