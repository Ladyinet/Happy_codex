"""SQLite schema for the mandatory local v1 storage backend."""

from __future__ import annotations


REQUIRED_TABLES: tuple[str, ...] = (
    "bot_state",
    "lots",
    "lot_history",
    "orders",
    "fills",
    "events",
    "subscribers",
    "safe_stop_log",
    "rolling_window_entries",
    "bar_counters",
)


SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS bot_state (
        mode TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        cycle_id INTEGER NOT NULL DEFAULT 0,
        pos_size_abs REAL NOT NULL DEFAULT 0,
        pos_proceeds_usdt REAL NOT NULL DEFAULT 0,
        avg_price REAL NOT NULL DEFAULT 0,
        num_sells INTEGER NOT NULL DEFAULT 0,
        last_fill_price REAL,
        next_level_price REAL,
        trailing_active INTEGER NOT NULL DEFAULT 0,
        trailing_min REAL,
        cycle_base_qty REAL NOT NULL DEFAULT 0,
        reset_cycle INTEGER NOT NULL DEFAULT 0,
        last_candle_time TEXT,
        last_sync_time TEXT,
        desync_detected INTEGER NOT NULL DEFAULT 0,
        safe_stop_active INTEGER NOT NULL DEFAULT 0,
        safe_stop_reason TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (mode, symbol, timeframe)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS lots (
        lot_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        cycle_id INTEGER NOT NULL,
        open_sequence INTEGER NOT NULL,
        qty REAL NOT NULL,
        entry_price REAL NOT NULL,
        tag TEXT NOT NULL,
        usdt_value REAL NOT NULL,
        created_at TEXT NOT NULL,
        source_order_id TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS lot_history (
        history_id TEXT PRIMARY KEY,
        lot_id TEXT NOT NULL,
        mode TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        cycle_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        qty REAL NOT NULL,
        price REAL NOT NULL,
        related_order_id TEXT,
        occurred_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        client_order_id TEXT UNIQUE,
        mode TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        intent_type TEXT NOT NULL,
        status TEXT NOT NULL,
        requested_qty REAL NOT NULL,
        requested_price REAL,
        normalized_qty REAL,
        normalized_price REAL,
        filled_qty REAL NOT NULL DEFAULT 0,
        avg_fill_price REAL,
        cycle_id INTEGER NOT NULL DEFAULT 0,
        reason TEXT,
        exchange_order_id TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS fills (
        fill_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fill_id TEXT,
        order_id TEXT NOT NULL,
        client_order_id TEXT,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        price REAL NOT NULL,
        qty REAL NOT NULL,
        fee REAL,
        raw_status TEXT,
        occurred_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        event_type TEXT NOT NULL,
        reason TEXT,
        price REAL,
        qty REAL,
        position_size REAL,
        avg_price REAL,
        pnl REAL,
        cycle_id INTEGER,
        payload_json TEXT,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS subscribers (
        subscriber_id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL UNIQUE,
        username TEXT,
        first_name TEXT,
        created_at TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS safe_stop_log (
        safe_stop_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        reason TEXT NOT NULL,
        details_json TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        resolved_by TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS rolling_window_entries (
        entry_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        event_type TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS bar_counters (
        mode TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        bar_time TEXT NOT NULL,
        fills_this_bar INTEGER NOT NULL DEFAULT 0,
        subcovers_this_bar INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (mode, symbol, timeframe, bar_time)
    );
    """,
)
