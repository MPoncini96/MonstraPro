"""Market data provider.

Placeholder — ports Monstra-Worker/market_data_provider.py: Alpaca market
data as the primary source (the device already holds Alpaca credentials for
trading), yfinance as a fallback, same provider-selection logic. Should
expose at minimum:

    get_daily_bars(symbols, start, end, adjusted=False) -> pandas.DataFrame
"""
