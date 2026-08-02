from datetime import datetime, timedelta, timezone

from display.candles import Candle, build_candles

_T0 = datetime(2026, 1, 5, 14, 0, 0, tzinfo=timezone.utc)


def _snap(equity: float, ts: datetime) -> dict:
    return {"equity": equity, "ts": ts}


def test_empty_input_returns_no_candles():
    assert build_candles([]) == []


def test_single_snapshot_is_a_flat_candle():
    candles = build_candles([_snap(1000.0, _T0)], bucket_seconds=300)

    assert len(candles) == 1
    candle = candles[0]
    assert candle.open == candle.high == candle.low == candle.close == 1000.0


def test_multiple_snapshots_in_one_bucket_produce_real_ohlc():
    snapshots = [
        _snap(1000.0, _T0),
        _snap(1050.0, _T0 + timedelta(minutes=1)),  # high
        _snap(980.0, _T0 + timedelta(minutes=2)),  # low
        _snap(1020.0, _T0 + timedelta(minutes=3)),  # close
    ]

    [candle] = build_candles(snapshots, bucket_seconds=300)

    assert candle.open == 1000.0
    assert candle.high == 1050.0
    assert candle.low == 980.0
    assert candle.close == 1020.0


def test_snapshots_spanning_multiple_buckets_produce_multiple_candles_in_order():
    snapshots = [
        _snap(1000.0, _T0),
        _snap(1010.0, _T0 + timedelta(minutes=2)),
        _snap(1100.0, _T0 + timedelta(minutes=6)),  # next 5-minute bucket
        _snap(1120.0, _T0 + timedelta(minutes=8)),
    ]

    candles = build_candles(snapshots, bucket_seconds=300)

    assert len(candles) == 2
    assert candles[0].bucket_start < candles[1].bucket_start
    assert candles[0].close == 1010.0
    assert candles[1].open == 1100.0
    assert candles[1].close == 1120.0


def test_out_of_order_input_is_sorted_before_bucketing():
    snapshots = [
        _snap(1020.0, _T0 + timedelta(minutes=3)),  # most-recent-first, as recent() returns
        _snap(1000.0, _T0),
    ]

    [candle] = build_candles(snapshots, bucket_seconds=300)

    assert candle.open == 1000.0
    assert candle.close == 1020.0


def test_max_candles_keeps_only_the_most_recent_buckets():
    snapshots = [_snap(1000.0 + i, _T0 + timedelta(minutes=5 * i)) for i in range(10)]

    candles = build_candles(snapshots, bucket_seconds=300, max_candles=3)

    assert len(candles) == 3
    assert candles[-1].close == 1009.0  # newest bucket kept
    assert candles[0].bucket_start > _T0  # oldest buckets dropped


def test_naive_datetime_is_treated_as_utc_not_local_time():
    naive = _T0.replace(tzinfo=None)

    candles = build_candles([_snap(1000.0, naive)], bucket_seconds=300)

    assert candles[0].bucket_start.tzinfo is not None


def test_return_type_is_candle_dataclass():
    [candle] = build_candles([_snap(1000.0, _T0)])
    assert isinstance(candle, Candle)


def test_value_key_selects_a_different_field():
    snapshots = [
        {"ts": _T0, "value": 50.0},
        {"ts": _T0 + timedelta(minutes=1), "value": 60.0},
    ]

    [candle] = build_candles(snapshots, value_key="value", bucket_seconds=300)

    assert candle.open == 50.0
    assert candle.close == 60.0
