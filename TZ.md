Технічне завдання
Алготрейдинг-бот Python для біржі BingX
На основі TradingView стратегії

“C - limit 14 SHORT (EVEN) bingX COMP”

1. Загальна архітектура системи

Бот реалізує алгоритмічну short-стратегію з DCA, яка:

відкриває початковий short
додає DCA ордери при рості ціни
виконує часткові закриття (sub-cover)
виконує повне закриття позиції (Full TP)
підтримує trailing TP
контролює максимальну частоту ордерів
2. Режими роботи (обов’язково)
1️⃣ SIMULATION / PAPER MODE

Віртуальна торгівля.

Особливості:

використовуються реальні котирування BingX
ордери не відправляються на біржу
виконання моделюється:
fill_price = close

як у TradingView.

Ведеться:

virtual balance
positions
lot structure
PnL
logs
2️⃣ LIVE TRADING MODE

Реальна торгівля через BingX API.

Особливості:

market / limit orders
синхронізація позиції
перевірка fills
відновлення стану після рестарту
3. Біржа

Біржа:

BingX Perpetual Futures

Потрібні:

API:

REST API
WebSocket API

Основні функції:

отримання OHLCV
отримання позиції
створення ордера
закриття позиції
отримання fills
4. Таймфрейм

Стратегія працює по закриттю бару.

Execution model:

Close-only execution

Всі розрахунки виконуються:

fill_price = close

Trigger:

по high/low або open/close body
5. Основні параметри стратегії
Базовий ордер
firstSellQtyCoin

або

baseOrderPctEq
equityForSizingUSDT

Режими:

1️⃣ fixed coin size
2️⃣ % від фіксованого equity

TP
tpPercent = 1.1%

Розрахунок:

tpPrice = avgPrice * (1 - tpPercent/100)
Trailing
callbackPercent = 0.2%

Алгоритм:

1️⃣ ціна торкається TP
2️⃣ активується trailing
3️⃣ фіксується minimum
4️⃣ стоп:

trailStop = trailingMin * (1 + callbackPercent/100)

Закриття:

close >= trailStop
6. DCA логіка

Стратегія відкриває нові short-ордери при рості ціни.

Наступний рівень
nextLevelPrice =
lastFillPrice * (1 + rise/100)
Nonlinear rise
lvl2 = 0.3%
lvl3 = 0.4%
lvl4 = 0.6%
lvl5 = 0.8%
lvl6 = 0.8%
after = linearRisePercent
Множники ордера
lvl2 = 1.5x
lvl3 = 1.0x
lvl4 = 2.0x
lvl5 = 3.5x
after = 1x
Максимум DCA
marginCallLimit = 244
7. Структура позиції (LIFO)

Бот зберігає кожен лот окремо.

Структура:

lot {
    id
    qty
    entry_price
    tag
    usdt_value
}

Списки:

lotIds
lotQty
lotPrice
lotTags
lotUsdt
8. Sub-cover логіка

Працює після:

numSells > 5

Закривається останній лот (LIFO).

TP для лота
lastLotTP = entryPrice * (1 - subSellTPPercent/100)
Режими підтвердження
off
breakeven
subcover_tp
Логіка
if low <= lastLotTP:
    close last lot
9. Перерахунок позиції

Після кожного ордера:

posSizeAbs += qty
posProceedsUSDT += qty * price

avgPrice = posProceedsUSDT / posSizeAbs
10. FULL TP

Умови:

low <= tpPrice

та

close <= tpPrice

(опціонально)

Закриття:

close_all_positions()
11. Обмеження частоти ордерів

Rolling window:

3 minutes

Максимум:

maxOrdersPer3Min = 14

Також:

maxFillsPerBar = 6
maxSubSellsPerBar = 10
12. EVEN BAR FILTER

Стратегія працює лише на парних барах.

barsFromAnchor % 2 == 0
13. Live sync start

Опція:

liveStartTime

При старті:

RESET ALL STATE
14. Основні модулі Python-бота
1️⃣ market_data.py

Отримання:

OHLCV
last price

через WebSocket.

2️⃣ strategy_engine.py

Повна логіка:

DCA
TP
trailing
subcover
state machine
3️⃣ order_manager.py

Інтерфейс з BingX:

place_order
close_order
close_all
get_position
get_fills
4️⃣ position_manager.py

Управління:

lots
avg price
pos size
proceeds
5️⃣ risk_manager.py

Контроль:

max orders per 3 min
max sells
max fills per bar
6️⃣ simulator.py

Paper trading.

7️⃣ config.py

Конфіг:

symbol
timeframe
equity
parameters
mode
8️⃣ logger.py

Логи:

orders
fills
TP
subcovers
PnL
15. Основний цикл бота
while True:

    receive_new_candle()

    update_state()

    check_full_tp()

    check_dca()

    check_subcover()

    execute_orders()

    log_state()
16. Структура state
state = {

posSizeAbs
posProceedsUSDT
avgPrice

numSells

lastFillPrice
nextLevelPrice

lots[]

trailingActive
trailingMin

cycleBaseQty

ordersLast3Min
}
17. Відновлення після рестарту

Бот повинен:

1️⃣ отримати позицію з BingX
2️⃣ відновити лоти
3️⃣ перерахувати:

avgPrice
nextLevel
numSells
18. Логи

Логувати:

FIRST SHORT
DCA SHORT
SUB COVER
FULL COVER
TRAILING TP
RESET CYCLE
19. Додаткові вимоги

Обов’язково:

async architecture
websocket price feed
persistent state (SQLite / JSON)
error recovery
retry API
20. Рекомендований стек

Python:

Python 3.11+

Бібліотеки:

ccxt
websockets
aiohttp
pandas
numpy
asyncio
21. Очікувана структура проекту
bot/

config.py
main.py

exchange/
    bingx_client.py

engine/
    strategy_engine.py
    position_manager.py
    risk_manager.py

execution/
    order_manager.py

simulation/
    paper_engine.py

data/
    market_stream.py

utils/
    logger.py
    storage.py
	
	22. Telegram інтеграція (обов’язково)

Усі торгові події повинні не тільки записуватись у журнал, але й дублюватись у Telegram.

Це дозволяє користувачам у реальному часі бачити роботу бота.

23. Telegram бот

Бот створений через
BotFather

Після створення отримується:

TELEGRAM_BOT_TOKEN
24. Підписка користувачів

Будь-який користувач може отримувати результати.

Алгоритм:

1️⃣ користувач знаходить Telegram бота
2️⃣ натискає

/start

3️⃣ його chat_id зберігається у базі

Таблиця підписників

SQLite таблиця:

subscribers

id
chat_id
username
first_name
created_at
is_active
25. Telegram команди

Мінімальний набір:

/start      -> підписка
/stop       -> відписка
/status     -> стан бота
/position   -> поточна позиція
/pnl        -> PnL
26. Події які відправляються в Telegram

Кожен ордер повинен відправляти повідомлення.

Типи повідомлень:

FIRST SHORT
FIRST SHORT

Symbol: BTCUSDT
Price: 64320
Qty: 0.09
Cycle: 1
DCA SHORT
DCA SHORT

Level: 4
Trigger: 65100
Fill: 65140

Qty: 0.18
Avg Price: 64520
Total Size: 0.63
SUB COVER
SUB COVER

Lot: ds7
Entry: 65400
Close: 64800

Qty: 0.09
Profit: 54 USDT
FULL COVER
FULL COVER

Close price: 64100

Total PnL: +137 USDT
Cycle completed
TRAILING TP
Trailing TP Activated

TP touch: 64000
Trailing callback: 0.2%
ERROR
ERROR

Exchange API failed
Retrying...
27. Telegram повідомлення при запуску

При старті бота:

BOT STARTED

Mode: LIVE / SIMULATION
Symbol: BTCUSDT
Timeframe: 1m
Equity: 100 USDT
28. Telegram throttling

Щоб уникнути спаму:

max_messages_per_second = 10
29. Telegram модуль

Файл:

telegram_notifier.py

Функції:

send_message(text)
broadcast(text)
register_user(chat_id)
remove_user(chat_id)
30. Структура повідомлення

Кожне повідомлення повинно містити:

timestamp
symbol
event_type
price
qty
position_size
avg_price
pnl
31. .env файл

Всі конфігурації повинні зберігатись у .env.

Кожен параметр повинен мати коментар.

Приклад .env
###########################################
# BINGX API CONFIG
###########################################

# BingX API key
BINGX_API_KEY=

# BingX API secret
BINGX_API_SECRET=

# Use testnet or live
BINGX_TESTNET=false


###########################################
# TRADING CONFIG
###########################################

# Trading symbol
SYMBOL=BTC-USDT

# Strategy timeframe
TIMEFRAME=1m

# Bot mode:
# simulation -> paper trading
# live       -> real trading
MODE=simulation


###########################################
# STRATEGY PARAMETERS
###########################################

# Initial short order size in coin
FIRST_SELL_QTY=0.09

# Minimum order size allowed
MIN_ORDER_QTY=0.09

# TP percent for full cover
TP_PERCENT=1.1

# Trailing callback percent
TRAILING_CALLBACK=0.2

# Sub-cover TP percent
SUB_SELL_TP_PERCENT=1.3

# Maximum number of short levels
MARGIN_CALL_LIMIT=244


###########################################
# RISK LIMITS
###########################################

# Maximum orders per 3 minutes
MAX_ORDERS_3MIN=14

# Maximum DCA fills per bar
MAX_DCA_PER_BAR=6

# Maximum subcovers per bar
MAX_SUBCOVER_PER_BAR=10


###########################################
# TELEGRAM CONFIG
###########################################

# Telegram bot token created via BotFather
TELEGRAM_BOT_TOKEN=

# SQLite database for subscribers
TELEGRAM_DB=telegram_subscribers.db

# Send notifications
TELEGRAM_ENABLED=true


###########################################
# LOGGING
###########################################

# Log level
LOG_LEVEL=INFO

# Log file
LOG_FILE=bot.log
32. Повідомлення повинні надсилатись у двох випадках

1️⃣ кожен ордер
2️⃣ кожна подія

Події:

FIRST
DCA
SUBCOVER
FULL_TP
TRAILING
RESET
ERROR
33. Архітектура Telegram
bot/

telegram/
    telegram_notifier.py
    telegram_bot.py
34. Робота з Telegram

Використати бібліотеку:

python-telegram-bot

або

aiogram

(рекомендовано aiogram для async)

35. Логи

Кожне повідомлення Telegram також записується у лог.

Приклад:

2026-04-05 12:44:21
EVENT=DCA
PRICE=65120
QTY=0.18
AVG=64510
POSITION=0.63
36. Захист від падіння

Telegram модуль не повинен зупиняти бота, якщо:

Telegram API error
timeout
network error