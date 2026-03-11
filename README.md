# Deadlock Scout Bot

Telegram-бот на Python (aiogram + SQLite) для персонального трекинга игроков Deadlock: история матчей, профиль, аналитика, карточки матча, мета и статистика по героям.

## Какие маршруты Deadlock API реально используются

Только подтверждённые маршруты:

- `GET /v1/players/steam?account_ids=`
- `GET /v1/players/steam-search?search_query=`
- `GET /v1/players/{account_id}/match-history`
- `GET /v1/players/hero-stats?account_ids=`
- `GET /v1/players/{account_id}/enemy-stats`
- `GET /v1/players/{account_id}/mate-stats`
- `GET /v1/players/{account_id}/party-stats`
- `GET /v1/players/mmr?account_ids=`
- `GET /v1/leaderboard/{region}`
- `GET /v1/analytics/hero-synergy-stats`
- `GET /v1/analytics/hero-counter-stats`
- `GET /v1/analytics/hero-stats`
- `GET /v1/info`
- `GET /v1/patches`

Служебно доступны: `/docs`, `/openapi.json`.

❌ Старые неверные маршруты удалены из логики (`/players/search`, `/players/recent-matches`, `/players/{id}`, `/match-history/{account_id}`).

## Как работает поиск игрока

`/addplayer` принимает:

- `account_id`
- `Steam64`
- `https://steamcommunity.com/profiles/...`
- `https://steamcommunity.com/id/...`
- обычный Steam nickname

Логика:

1. Числовой ввод нормализуется до `account_id` (Steam64 -> account_id).
2. Steam URL парсится, vanity URL резолвится через Steam XML профиль.
3. Ник ищется через `/v1/players/steam-search`.
4. Если найдено несколько профилей — бот предлагает `/pickplayer N`.
5. В БД канонически сохраняется `account_id`, а также `display_name` и `steam_profile_url` (если есть).


## Шрифты для PNG-карточек (русский текст)

Чтобы русский текст в PNG отображался корректно, положите TTF-файлы в `assets/fonts/`:

- `NotoSans-Regular.ttf`
- `NotoSans-Bold.ttf`

Рекомендуемый источник: семейство **Noto Sans** (поддерживает кириллицу).
Можно также использовать DejaVu (`DejaVuSans.ttf` / `DejaVuSans-Bold.ttf`).

## Команды

- `/addplayer`
- `/pickplayer`
- `/players`
- `/lastmatch [account_id]`
- `/profile [account_id]`
- `/heroes [account_id]`
- `/besthero [account_id]`
- `/hero <account_id> <hero_id>`
- `/teammates [account_id]`
- `/enemies [account_id]`
- `/party [account_id]`
- `/meta`
- `/synergy <hero_id>`
- `/counter <hero_id>`
- `/leaderboard <region>`
- `/patches`

Если `account_id` не передан, бот сначала ищет среди сохранённых игроков пользователя. Если профилей несколько — предлагает выбрать нужный через кнопку.

## History-only режим

Когда недоступны детальные данные матча, всё строится честно по `match-history`:

- `hero_name`: fallback `Hero #id`
- `souls = net_worth`
- `damage = 0`, если поле отсутствует
- `items = []`
- `start_time -> ISO UTC`

Карточки и аналитика продолжают работать без выдуманных полей.

## Где используются Steam endpoints

- `/v1/players/steam-search` — поиск по нику.
- `/v1/players/steam` — обогащение account_id до `personaname` + `profile_url`.

Это используется в `/addplayer`, `/players`, `/profile`, `/teammates`, `/enemies`, `/leaderboard` для кликабельных имён в Telegram.

## Важно про имена героев

Подтверждённого справочника hero_id -> hero_name сейчас нет.
Поэтому отображается fallback: `Hero #13`.
Отдельный helper `app/services/heroes.py` подготовлен с TODO для будущего подключения словаря.

## Быстрая ручная проверка API (curl)

```bash
BASE_URL="https://your-deadlock-api"
ACCOUNT_ID="162968642"

curl -sS "$BASE_URL/v1/info"
curl -sS "$BASE_URL/docs"
curl -sS "$BASE_URL/openapi.json"

curl -sS "$BASE_URL/v1/players/steam?account_ids=$ACCOUNT_ID"
curl -sS "$BASE_URL/v1/players/steam-search?search_query=nickname"
curl -sS "$BASE_URL/v1/players/$ACCOUNT_ID/match-history"
curl -sS "$BASE_URL/v1/players/hero-stats?account_ids=$ACCOUNT_ID"
curl -sS "$BASE_URL/v1/players/$ACCOUNT_ID/mate-stats"
curl -sS "$BASE_URL/v1/players/$ACCOUNT_ID/enemy-stats"
curl -sS "$BASE_URL/v1/players/$ACCOUNT_ID/party-stats"
curl -sS "$BASE_URL/v1/players/mmr?account_ids=$ACCOUNT_ID"

curl -sS "$BASE_URL/v1/analytics/hero-stats"
curl -sS "$BASE_URL/v1/analytics/hero-synergy-stats"
curl -sS "$BASE_URL/v1/analytics/hero-counter-stats"
curl -sS "$BASE_URL/v1/leaderboard/Europe"
curl -sS "$BASE_URL/v1/patches"
```
