from __future__ import annotations

import pandas as pd

BAR_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Trade Count", "VWAP"]


def make_bars_frame(prices: dict[str, list[float]], *, start: str = "2020-01-01") -> pd.DataFrame:
    """Build a DataFrame in the same shape strategy_engine.market_data.provider.get_daily_bars
    returns, so bot modules that call get_daily_bars can be tested against a monkeypatched
    version of it without hitting the network.

    `prices` maps symbol -> list of daily closes (chronological). All symbols must have the
    same length; every OHLC field is set to the same close value (tests here only care about
    Close-derived returns).
    """
    symbols = list(prices.keys())
    n = len(next(iter(prices.values())))
    dates = pd.date_range(start=start, periods=n, freq="B")

    if len(symbols) == 1:
        symbol = symbols[0]
        frame = pd.DataFrame(
            {col: prices[symbol] for col in BAR_COLUMNS},
            index=dates,
        )
        frame.index.name = "Date"
        return frame

    columns = pd.MultiIndex.from_product([BAR_COLUMNS, symbols])
    frame = pd.DataFrame(index=dates, columns=columns, dtype="float64")
    for symbol in symbols:
        for col in BAR_COLUMNS:
            frame[(col, symbol)] = prices[symbol]
    frame.index.name = "Date"
    return frame.sort_index(axis=1, level=[0, 1])


def geometric_series(start_price: float, daily_return: float, n: int) -> list[float]:
    """Deterministic price path: start_price * (1 + daily_return) ** t for t in [0, n)."""
    return [start_price * (1.0 + daily_return) ** t for t in range(n)]
