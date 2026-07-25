"""trading_worker entrypoint — systemd target monstrapro-worker.service.

Responsibilities (see ARCHITECTURE.md section 4.1), not yet implemented:

  1. Load device_core.config, open the SQLite DB, run pending migrations.
  2. Own the activation state machine:
       not activated -> poll monstra.pro device-status, emit
                         `awaiting_activation` device_event, repeat.
       activated     -> pull strategy_config + Alpaca link, enter the
                         trading loop.
  3. Trading loop, per scheduled cycle:
       fetch market data (strategy_engine.market_data.provider)
       -> run the owner's strategy via strategy_engine.registry
       -> diff target weights vs current Alpaca positions
       -> submit orders to Alpaca
       -> persist signal/order/execution_log rows
       -> emit `trade_executed` device_event on any order placed.

This is the first "foundational service" to build out after the
architecture scaffold — deliberately left unimplemented here.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("trading_worker is not yet implemented — see module docstring")


if __name__ == "__main__":
    main()
