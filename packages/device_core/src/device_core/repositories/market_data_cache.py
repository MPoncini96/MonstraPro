"""MarketDataCacheRepository: cached OHLC bars per (symbol, slide),
refreshed by trading_worker.stock_bar_sync - see
device_core.db.models.MarketDataCache's docstring for why this overwrites
in place rather than accumulating history like the other snapshot tables.

    core.market_data.save(symbol="AAPL", slide="1h", bars=[...])
    core.market_data.get("AAPL", "1h")
    core.market_data.list_symbols()               # the current selection
    core.market_data.replace_selection({"AAPL", "MSFT"})
"""

from __future__ import annotations

from typing import Any

from device_core.db.models import MarketDataCache, utcnow
from device_core.db.session import Database


def _row_to_dict(row: MarketDataCache) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class MarketDataCacheRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, *, symbol: str, slide: str, bars: list[dict[str, Any]]) -> None:
        """Idempotent per (symbol, slide): a second call overwrites the
        existing row's bars rather than creating a duplicate."""
        with self._db.session() as session:
            row = session.query(MarketDataCache).filter_by(symbol=symbol, slide=slide).first()
            if row is None:
                row = MarketDataCache(symbol=symbol, slide=slide)
                session.add(row)
            row.bars_json = bars
            row.fetched_at = utcnow()

    def get(self, symbol: str, slide: str) -> dict[str, Any] | None:
        with self._db.session() as session:
            row = session.query(MarketDataCache).filter_by(symbol=symbol, slide=slide).first()
            return _row_to_dict(row) if row is not None else None

    def list_symbols(self) -> list[str]:
        """Distinct cached symbols, oldest-cached first - this IS the
        current stock-view selection (trading_worker.stock_bar_sync owns
        picking which symbols to track; display just shows whatever's
        here, it does no ranking of its own)."""
        with self._db.session() as session:
            rows = (
                session.query(MarketDataCache.symbol, MarketDataCache.id)
                .order_by(MarketDataCache.id.asc())
                .all()
            )
            symbols: list[str] = []
            for symbol, _id in rows:
                if symbol not in symbols:
                    symbols.append(symbol)
            return symbols

    def replace_selection(self, symbols: set[str]) -> None:
        """Drops cached rows for any symbol NOT in `symbols`, so a symbol
        that falls out of the top-3-by-position/top-2-by-movement
        selection doesn't linger in display's rotation forever."""
        with self._db.session() as session:
            session.query(MarketDataCache).filter(~MarketDataCache.symbol.in_(symbols)).delete(
                synchronize_session=False
            )
