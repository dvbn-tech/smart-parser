# Настройка Instagram Graph API и локального сбора через VPN

Источник — официальный Instagram Graph API (Business Discovery): наш бизнес-аккаунт
запрашивает публичные данные бизнес- и авторских аккаунтов по нику — профиль,
публикации, просмотры Reels (`view_count`), лайки, комментарии. Личные и закрытые
аккаунты API не видит — такие задачи падают с понятной причиной.

## 0. VPN
- VPN с постоянным IP (dedicated/static) в одной стране; иначе Meta может поставить проверку на аккаунт.
- Шаги 1–4 делайте с включённым VPN той же страны.

## 1. Бизнес-аккаунт
1. Instagram @15.wear → Настройки → «Тип аккаунта и инструменты» → профессиональный → Бизнес.
2. Создайте страницу Facebook и привяжите к ней Instagram (Настройки страницы → Связанные аккаунты).

## 2. Приложение Meta
1. https://developers.facebook.com → My Apps → Create App → тип Business.
2. Добавьте продукты Facebook Login for Business и Instagram (API setup with Facebook login).
3. Настройки → Основное: App ID и App Secret в `.env` (`SP_META_APP_ID`, `SP_META_APP_SECRET`).
Режим разработки, проверка Meta не нужна.

## 3. Токен
1. Graph API Explorer: https://developers.facebook.com/tools/explorer/ → ваше приложение → User Token.
2. Права: instagram_basic, instagram_manage_insights, pages_show_list, pages_read_engagement, business_management.
3. Generate Access Token, затем: `uv run smart-parser meta-token <ТОКЕН> --save`
   (запишет в .env долгоживущий токен ~60 дней и id бизнес-аккаунта).

## 4. Проверка
`uv run smart-parser meta-check --username waistline_shop`

## 5. Сбор
```
make up
uv run smart-parser work --once     # первый сбор ~164 запроса, ~1–1,5 ч
uv run smart-parser recompute
```

## 6. Расписание на Mac
`scripts/macos/install-schedule.sh` (удаление — с `--remove`). Mac на зарядке без сна, запущены Docker Desktop и VPN.
