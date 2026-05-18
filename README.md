# trustlyDeal Bot 

Telegram escrow бот для безопасных сделок между продавцами и покупателями.

## Возможности

- Создание сделок (продавец > escrow > покупатель)
- Поддержка методов оплаты: Stars, TON, USDT, Card/SBP
- Логирование в Telegram канал
- Управление доверенными пользователями
- Автоматическая публикация сделок в канал

## Деплой

1. Скопируйте \.env.example\ в \.env\ и заполните переменные:

```
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_ID=your_telegram_user_id
DEALS_CHANNEL_ID=@your_channel_username
```

2. Установите зависимости:

```
pip install -r requirements.txt
```

3. Запустите бота:

```
python main.py
```

### Деплой на Railway/Heroku

Просто подключите репозиторий к Railway/Heroku. Платформа автоматически определит Python и запустит \main.py\.

### Деплой через Docker

```
docker build -t trustlydeal-bot .
docker run -d --env-file .env trustlydeal-bot
```

## Команды

- \/start\ — Главное меню
- \/help\ — Справка
- \/buy #hash\ — Быстрая покупка по хешу
- \/setlog CHANNEL_ID\ — Установить канал логов (админ)
- \/logstatus\ — Статус канала логов (админ)
- \/grant USER_ID\ — Дать доступ (админ)
- \/revoke USER_ID\ — Забрать доступ (админ) 

  
