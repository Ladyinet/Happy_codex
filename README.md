# BingX Short Bot v1 Skeleton

This repository contains the initial project skeleton for the v1 implementation.

Source-of-truth documents:
- `TZ_rewritten.txt`
- `IMPLEMENTATION_DECISIONS_V1.txt`

Current scope of this step:
- project directories and files
- configuration skeleton
- SQLite schema
- enums, dataclasses, and model definitions
- empty interfaces and placeholder classes
- test skeleton

Out of scope for this step:
- live trading implementation
- BingX API calls
- full trading logic
- exchange reconciliation logic details

## Runtime modes

Only these runtime modes are valid:
- `backtest`
- `dry_run`
- `live`

The implementation path for v1 is intentionally staged:
1. storage, config, shared models
2. market data and shared normalization layer
3. strategy engine
4. `backtest`
5. `dry_run`
6. Telegram commands over local state
7. safe-stop and recovery flow
8. only then `live`

## Project layout

```text
bot/
  main.py
  config.py
  data/
  engine/
  exchange/
  execution/
  simulation/
  storage/
  telegram/
  utils/
  tests/
```

## Notes

- `position_manager.py` stays in `bot/engine/`.
- `order_manager.py` in `bot/execution/` owns order lifecycle, reconcile, order state machine, and executor-to-storage wiring.
- `backtest_engine.py` must reuse the same `strategy_engine`, `position_manager`, `risk_manager`, and shared rounding layer as the rest of the project.
