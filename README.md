# Deadlock Scout Bot

Production-ready MVP Telegram-бота на Python 3.11+ для отслеживания матчей Deadlock, аналитики и отправки визуальных PNG-карточек.

## Что делает проект
- Отслеживает одного или нескольких игроков Deadlock для каждого Telegram-пользователя.
- Автоматически находит новые завершённые матчи.
- Не склеивает отчёты: отправляет каждый пропущенный матч отдельно и по порядку.
- Анализирует матч (слабые стороны, улучшения, анти-тильт, лучший герой недели).
- Генерирует карточку 1080x1350 (Pillow) с ассетами героев/предметов.
- Отправляет карточку в Telegram с inline-кнопками.

## Стек
- Python 3.11+
- aiogram 3.x
- httpx
- asyncio
- sqlite3 (SQLite)
- Pillow
- pydantic / pydantic-settings
- python-dotenv
- структурированное логирование (JSON)

## Установка и запуск

### 1) Создание виртуального окружения
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
- `/start`
- `/help`
- `/addplayer <player_id|ник>`
- `/players`
- `/removeplayer <player_id>`
- `/track <player_id> on|off`
- `/lastmatch <player_id>`
- `/profile <player_id>`

## Автоотслеживание
- Бот периодически опрашивает всех игроков с включённым `auto_reports_enabled`.
- Для каждого игрока собирает список матчей и отправляет все неотправленные в хронологическом порядке.
- Проверка дублей идёт через таблицу `sent_reports`.
- Глобальный лимит: не больше 1 запроса/сек на Deadlock API.
- При рестарте бот догоняет пропущенные матчи.

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
cache/
  assets/
cards/
data/
README.md
requirements.txt
.env.example
```

## База данных
Инициализируется автоматически при старте. Таблицы:
- `users`
- `tracked_players`
- `player_match_history`
- `matches_cache`
- `sent_reports`

## Как адаптировать эндпоинты API
В проекте централизован клиент `app/clients/deadlock_api.py`.
Если документация Deadlock API отличается:
1. Обновите пути в методах:
   - `get_player_recent_matches`
   - `get_match`
   - `get_player_profile`
   - `resolve_player`
2. Обновите парсер `parse_match_for_player`.
3. Сверьте формат ассетов в `app/clients/assets.py`.

В коде оставлены TODO в местах, где может отличаться реальная схема API.

## Генерация карточек
`CardRenderer` создаёт многослойную тёмную карточку:
- фон: арт героя (Assets API)
- полупрозрачные панели
- акцент победы/поражения
- метрики K/D/A, Souls, Damage
- аналитические блоки
- иконки предметов (до 6)
- watermark бота

Если ассет отсутствует, используется локальная заглушка.

## Пример сценария
1. `/addplayer 123456`
2. `/players`
3. Бот автоматически отправляет карточки новых матчей
4. Внизу карточки доступны кнопки: «Подробнее», «Прошлый матч», «Профиль», «Отключить автоотслеживание»

## Ограничения MVP
- Поиск по нику при неоднозначном результате пока просит ручной `player_id`.
- Для production рекомендуется добавить миграции, тесты и метрики.
