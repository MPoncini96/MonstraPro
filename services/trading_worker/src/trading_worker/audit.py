"""Cycle-replay audit: verifies a past trading cycle two independent ways.

    python -m trading_worker.audit --list
    python -m trading_worker.audit --index 0

This is a different check from monstra.pro's device-review page ("Expected"
vs "Real"): that compares a live snapshot (server-computed target weights vs
current Alpaca positions) and can't tell you *why* they differ - rebalance
timing, locked stocks, and price drift are all legitimate reasons for a
mismatch there, not necessarily bugs. This script instead replays one
specific past cycle's own recorded inputs through the same code that
produced it, so a mismatch here points at an actual bug in a specific layer
instead of normal drift:

  1. Algorithm fidelity - re-run strategy_engine.run_<bot>(config, state)
     with the inputs that cycle actually had, and diff the result against
     what got persisted to the `signal` table for that cycle.
  2. Execution fidelity - recompute the netted order plan
     (trading_worker.rebalance.compute_order_plan) from that cycle's
     recorded per-bot allocations and account/position snapshots, and diff
     it against what's actually in the `order` table.

WHAT COUNTS AS "A CYCLE" HERE: a distinct point in time the device actually
submitted orders (clustered from the `order` table's submitted_at values,
bot_slug=NETTED_ORDER_BOT_SLUG). account_snapshot rows are NOT usable as the
cycle anchor even though there's one "per cycle" conceptually - main.py's
_record_snapshots() also writes one every ~60s regardless of whether a real
trading cycle ran that tick, so most account_snapshot rows aren't cycles at
all. Orders, by contrast, are written exclusively by run_cycle() (see
loop.py), so a cluster of them unambiguously marks one real cycle. This does
mean a cycle where every bot HOLDs (nothing to trade) currently isn't
individually addressable - not a loss for this tool's purpose, since
"verify the trades match expectations" has nothing to check on a no-trade
cycle anyway.

KNOWN LIMITATIONS (surfaced in every report's `caveats`, never hidden):

  - Algorithm replay re-fetches "current" market data - every bot's lookback
    window is anchored to *today's* date (see
    strategy_engine.market_data.provider and each bots.<name>.py's
    `datetime.now(timezone.utc).date()`), not the historical date of the
    audited cycle. Replay is only a strict correctness check for a cycle
    from *today*; for an older cycle, a mismatch may just be normal price
    drift, not a bug.
  - Stateful bots (draco) only have their CURRENT state persisted
    (device_core.BotState keeps no history) - algorithm replay is only
    possible for that bot's very first-ever recorded cycle (prior_state was
    genuinely None); every later cycle is reported SKIPPED rather than
    silently replayed against the wrong prior state.
  - Locked stocks and each bot's params/equity_weight are read as configured
    *now* - neither device_core.ManualHolding nor StrategyConfig keep
    history, so if either changed since the audited cycle, the
    execution-fidelity replay uses today's values instead of the cycle's.
  - manageable_position_values is reconstructed from the nearest
    position_snapshot heartbeat (main.py's separate ~60s poll, not
    run_cycle()'s own live fetch) at or before the cycle - it can be up to
    ~60s stale relative to what run_cycle() actually saw, so a real position
    change in that gap can show up as a small notional_mismatch that isn't
    really a bug.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from device_core.core import DeviceCore
from strategy_engine.bot_identity import BOT_TYPE_ALPHA1, BOT_TYPE_APTET
from strategy_engine.registry import get_algorithm, get_runner

from trading_worker.loop import NETTED_ORDER_BOT_SLUG
from trading_worker.rebalance import OrderPlanItem, compute_order_plan, exclude_locked_symbols

logger = logging.getLogger(__name__)

# alpha1 ("force") and aptet never receive/return a `state` - only draco is
# stateful (see loop.py's _run_one_bot and BotStateRepository's docstring).
STATELESS_BOT_TYPES = {BOT_TYPE_ALPHA1, BOT_TYPE_APTET}

# How close an allocation/position/order row's timestamp has to be to a
# cycle's account_snapshot.ts to count as belonging to that same cycle.
# account_snapshot.record(), every bot's allocations.replace(), and the
# resulting orders.record() calls all happen within one run_cycle() call, so
# in practice they land within milliseconds to a few seconds of each other -
# this window is generous headroom, not a tight tolerance.
CORRELATION_WINDOW_SECONDS = 90

WEIGHT_TOLERANCE = 0.005  # 0.5 percentage points
DOLLAR_TOLERANCE = 1.0  # matches compute_order_plan's own min_trade_dollars default


def _as_utc(ts: datetime) -> datetime:
    """SQLite drops tz info on round-trip - a naive datetime read back from
    the DB is UTC, never local (see services/display/src/display/timeutil.py
    for the same normalization, applied there for the same reason)."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _weights_close(a: dict[str, float], b: dict[str, float], tol: float = WEIGHT_TOLERANCE) -> bool:
    symbols = set(a) | set(b)
    return all(abs(a.get(symbol, 0.0) - b.get(symbol, 0.0)) <= tol for symbol in symbols)


def _is_first_signal(core: DeviceCore, bot_id: str, bot_type: str, signal_row: dict[str, Any]) -> bool:
    earlier = core.signals.as_of(bot_id, bot_type, _as_utc(signal_row["ts"]) - timedelta(microseconds=1))
    return earlier is None


@dataclass
class AlgorithmAuditResult:
    bot_slug: str
    bot_type: str
    status: str  # "match" | "mismatch" | "skipped" | "error"
    detail: str
    recorded_signal: str | None = None
    replayed_signal: str | None = None
    recorded_target_weights: dict[str, float] = field(default_factory=dict)
    replayed_target_weights: dict[str, float] = field(default_factory=dict)
    stale_replay: bool = False


@dataclass
class OrderDiffLine:
    symbol: str
    side: str
    expected_notional: float | None
    actual_notional: float | None
    status: str  # "match" | "notional_mismatch" | "missing" | "unexpected"


@dataclass
class ExecutionAuditResult:
    status: str  # "match" | "mismatch" | "no_orders_expected_or_found"
    lines: list[OrderDiffLine]
    manageable_equity: float
    locked_symbols: list[str]


@dataclass
class CycleAuditReport:
    cycle_ts: str
    algorithm_results: list[AlgorithmAuditResult]
    execution_result: ExecutionAuditResult
    caveats: list[str]


def _cluster_order_timestamps(timestamps: list[datetime]) -> list[datetime]:
    """Groups timestamps within CORRELATION_WINDOW_SECONDS of their
    cluster's latest member - real cycles are scheduled roughly an hour
    apart (see trading_worker.main.scheduled_cycle_times_et), far wider
    than this window, so orders from the same cycle reliably cluster
    together and distinct cycles reliably don't. Returns one representative
    timestamp (each cluster's latest member) per
    cluster, most-recent-first."""
    ordered = sorted(timestamps, reverse=True)
    clusters: list[datetime] = []
    for ts in ordered:
        if clusters and (clusters[-1] - ts).total_seconds() <= CORRELATION_WINDOW_SECONDS:
            continue
        clusters.append(ts)
    return clusters


def _account_snapshot_as_of(core: DeviceCore, ts: datetime, *, search_limit: int = 2000) -> dict[str, Any] | None:
    for row in core.account_snapshots.recent(limit=search_limit):
        if _as_utc(row["ts"]) <= ts:
            return row
    return None


def list_recent_cycles(core: DeviceCore, *, limit: int = 10, search_limit: int = 1000) -> list[dict[str, Any]]:
    """Lists real trading cycles - see module docstring for why this means
    "order-submission clusters", not account_snapshot rows. `equity`/`cash`
    are the closest account_snapshot at or before each cycle, for display
    only (search_limit bounds how many recent orders are scanned to build
    the clusters)."""
    orders = core.orders.recent(bot_slug=NETTED_ORDER_BOT_SLUG, limit=search_limit)
    timestamps = [_as_utc(order["submitted_at"]) for order in orders]
    cycle_timestamps = _cluster_order_timestamps(timestamps)[:limit]

    cycles: list[dict[str, Any]] = []
    for ts in cycle_timestamps:
        account_snapshot = _account_snapshot_as_of(core, ts)
        cycles.append(
            {
                "ts": ts,
                "equity": account_snapshot["equity"] if account_snapshot else None,
                "cash": account_snapshot["cash"] if account_snapshot else None,
            }
        )
    return cycles


def audit_algorithm_layer(
    core: DeviceCore, cycle_ts: datetime, *, today: datetime | None = None
) -> list[AlgorithmAuditResult]:
    cycle_ts = _as_utc(cycle_ts)
    today = today or datetime.now(timezone.utc)
    stale_replay = cycle_ts.date() != today.date()

    results: list[AlgorithmAuditResult] = []
    for row in core.strategies.get_active():
        bot_slug = row["bot_slug"]
        engine_slug = row.get("bot_type") or bot_slug  # loop.py's own fallback for pre-sync rows
        algorithm = get_algorithm(engine_slug)
        runner = get_runner(engine_slug) if algorithm is not None else None
        if runner is None or algorithm is None:
            results.append(
                AlgorithmAuditResult(
                    bot_slug=bot_slug,
                    bot_type=engine_slug,
                    status="error",
                    detail=f"No strategy_engine runner registered for bot_type={engine_slug!r}.",
                )
            )
            continue

        # The `signal` table's bot_type column is the runner's own reported
        # identity (e.g. "alpha1" for the "force" engine slug) - not
        # necessarily the same string as engine_slug. See AlgorithmEntry's
        # docstring in strategy_engine/registry.py.
        signal_bot_type = algorithm.bot_type

        recorded = core.signals.as_of(bot_slug, signal_bot_type, cycle_ts)
        if recorded is None:
            results.append(
                AlgorithmAuditResult(
                    bot_slug=bot_slug,
                    bot_type=signal_bot_type,
                    status="skipped",
                    detail="No recorded signal at or before this cycle.",
                )
            )
            continue

        prior_state: dict[str, Any] | None = None
        if signal_bot_type not in STATELESS_BOT_TYPES:
            if not _is_first_signal(core, bot_slug, signal_bot_type, recorded):
                results.append(
                    AlgorithmAuditResult(
                        bot_slug=bot_slug,
                        bot_type=signal_bot_type,
                        status="skipped",
                        detail=(
                            "Stateful bot: device_core.BotState only retains the CURRENT state, not "
                            "the state that was actually in effect entering this cycle, so replay "
                            "can't be verified for any cycle after this bot's very first one."
                        ),
                        recorded_signal=recorded["signal"],
                    )
                )
                continue
            # This genuinely is the bot's first-ever recorded cycle, so
            # prior_state really was None - safe to replay.

        equity_history = core.account_snapshots.equity_history_as_of(cycle_ts)
        config = {**(row.get("params_json") or {}), "bot_id": bot_slug, "equity_history": equity_history}

        try:
            replayed = runner(config, prior_state)
        except Exception as exc:  # noqa: BLE001 - report, don't crash the whole audit
            results.append(
                AlgorithmAuditResult(
                    bot_slug=bot_slug,
                    bot_type=signal_bot_type,
                    status="error",
                    detail=f"Replay raised {exc.__class__.__name__}: {exc}",
                    recorded_signal=recorded["signal"],
                )
            )
            continue

        recorded_weights = (recorded.get("payload_json") or {}).get("target_weights") or {}
        replayed_weights = (replayed.get("payload") or {}).get("target_weights") or {}
        matches = replayed["signal"] == recorded["signal"] and _weights_close(recorded_weights, replayed_weights)

        status = "match" if matches else "mismatch"
        detail = (
            "Replayed signal/target_weights match what was recorded."
            if matches
            else "Replayed output differs from what was recorded - see recorded_* vs replayed_* fields."
        )
        if stale_replay and not matches:
            detail += (
                " NOTE: this cycle isn't from today, so replay used newer market data than the "
                "original run saw - this mismatch may be normal price drift, not a bug."
            )

        results.append(
            AlgorithmAuditResult(
                bot_slug=bot_slug,
                bot_type=signal_bot_type,
                status=status,
                detail=detail,
                recorded_signal=recorded["signal"],
                replayed_signal=replayed["signal"],
                recorded_target_weights=recorded_weights,
                replayed_target_weights=replayed_weights,
                stale_replay=stale_replay,
            )
        )

    return results


def _diff_orders(expected_plan: list[OrderPlanItem], actual_orders: list[dict[str, Any]]) -> list[OrderDiffLine]:
    expected_by_key = {(item.symbol, item.side): item.notional for item in expected_plan}
    actual_by_key: dict[tuple[str, str], float | None] = {}
    for order in actual_orders:
        actual_by_key[(order["symbol"], order["side"])] = order.get("notional")

    lines: list[OrderDiffLine] = []
    for key in sorted(set(expected_by_key) | set(actual_by_key)):
        symbol, side = key
        expected = expected_by_key.get(key)
        actual = actual_by_key.get(key)

        if expected is not None and actual is not None:
            line_status = "match" if abs(expected - actual) <= DOLLAR_TOLERANCE else "notional_mismatch"
        elif expected is not None and actual is None:
            line_status = "missing"
        else:
            line_status = "unexpected"

        lines.append(OrderDiffLine(symbol=symbol, side=side, expected_notional=expected, actual_notional=actual, status=line_status))

    return lines


def audit_execution_layer(core: DeviceCore, cycle_ts: datetime) -> ExecutionAuditResult:
    cycle_ts = _as_utc(cycle_ts)
    active_rows = core.strategies.get_active()
    locked_symbols = {row["symbol"] for row in core.manual_holdings.list_all()}

    account_snapshot = _account_snapshot_as_of(core, cycle_ts)
    account_equity = account_snapshot["equity"] if account_snapshot else 0.0

    positions_as_of = core.positions.as_of(cycle_ts)
    all_position_values = {symbol: data["market_value"] for symbol, data in positions_as_of.items()}
    locked_value = sum(value for symbol, value in all_position_values.items() if symbol in locked_symbols)
    manageable_position_values = {
        symbol: value for symbol, value in all_position_values.items() if symbol not in locked_symbols
    }
    manageable_equity = max(account_equity - locked_value, 0.0)

    contributions: list[tuple[dict[str, Any], dict[str, float]]] = []
    for row in active_rows:
        allocation = core.allocations.as_of(row["bot_slug"], cycle_ts)
        target_weights = (allocation or {}).get("target_weights_json") or {}
        contributions.append((row, exclude_locked_symbols(target_weights, locked_symbols)))

    total_weight = (
        sum((row.get("equity_weight") if row.get("equity_weight") is not None else 1.0) for row, _ in contributions)
        or 1.0
    )

    combined_target_values: dict[str, float] = {}
    for row, weights in contributions:
        weight = row.get("equity_weight") if row.get("equity_weight") is not None else 1.0
        bot_equity = manageable_equity * (weight / total_weight)
        for symbol, symbol_weight in weights.items():
            combined_target_values[symbol] = combined_target_values.get(symbol, 0.0) + symbol_weight * bot_equity

    combined_target_weights = (
        {symbol: value / manageable_equity for symbol, value in combined_target_values.items()}
        if manageable_equity > 0
        else {}
    )

    expected_plan = compute_order_plan(
        target_weights=combined_target_weights,
        current_position_values=manageable_position_values,
        account_equity=manageable_equity,
    )

    window_start = cycle_ts - timedelta(seconds=CORRELATION_WINDOW_SECONDS)
    window_end = cycle_ts + timedelta(seconds=CORRELATION_WINDOW_SECONDS)
    actual_orders = core.orders.in_window(start=window_start, end=window_end, bot_slug=NETTED_ORDER_BOT_SLUG)

    lines = _diff_orders(expected_plan, actual_orders)
    if not lines:
        status = "no_orders_expected_or_found"
    else:
        status = "match" if all(line.status == "match" for line in lines) else "mismatch"

    return ExecutionAuditResult(
        status=status, lines=lines, manageable_equity=manageable_equity, locked_symbols=sorted(locked_symbols)
    )


def audit_cycle(core: DeviceCore, *, cycle_index: int = 0) -> CycleAuditReport:
    """cycle_index: 0 = most recent cycle that submitted orders, 1 = the one
    before that, etc. See module docstring for what "cycle" means here."""
    cycles = list_recent_cycles(core, limit=cycle_index + 1)
    if len(cycles) <= cycle_index:
        raise ValueError(f"No cycle at index {cycle_index} - only {len(cycles)} recorded.")
    cycle_ts = cycles[cycle_index]["ts"]

    algorithm_results = audit_algorithm_layer(core, cycle_ts)
    execution_result = audit_execution_layer(core, cycle_ts)

    caveats = [
        "Algorithm replay re-fetches CURRENT market data, not historical-as-of - only trustworthy "
        "for a cycle from today; mismatches on older cycles may just be price drift.",
        "Locked stocks and each bot's params/equity_weight are read as configured NOW, not as of "
        "this cycle - neither keeps history.",
        "manageable_position_values comes from the nearest ~60s position_snapshot heartbeat, not "
        "run_cycle()'s own live fetch - can be slightly stale, showing as a small notional_mismatch "
        "that isn't necessarily a bug.",
    ]
    if any(result.status == "skipped" and "Stateful bot" in result.detail for result in algorithm_results):
        caveats.append(
            "One or more stateful bots (e.g. draco) were skipped for algorithm replay - only their "
            "very first-ever recorded cycle is verifiable (device_core.BotState keeps no history)."
        )

    return CycleAuditReport(
        cycle_ts=cycle_ts.isoformat(),
        algorithm_results=algorithm_results,
        execution_result=execution_result,
        caveats=caveats,
    )


def _print_report(report: CycleAuditReport) -> None:
    print(f"Cycle audit for {report.cycle_ts}")
    print()
    print("Algorithm fidelity (recorded signal/target_weights vs. re-run algorithm):")
    for result in report.algorithm_results:
        print(f"  [{result.status.upper():8}] {result.bot_slug} ({result.bot_type}): {result.detail}")
        if result.status == "mismatch":
            print(f"             recorded: {result.recorded_signal} {result.recorded_target_weights}")
            print(f"             replayed: {result.replayed_signal} {result.replayed_target_weights}")
    print()

    execution = report.execution_result
    print(f"Execution fidelity (recomputed order plan vs. actual orders): {execution.status.upper()}")
    print(f"  manageable_equity=${execution.manageable_equity:,.2f} locked_symbols={execution.locked_symbols}")
    for line in execution.lines:
        marker = "OK" if line.status == "match" else line.status.upper()
        print(f"  [{marker:16}] {line.side:4} {line.symbol:8} expected={line.expected_notional} actual={line.actual_notional}")
    if not execution.lines:
        print("  (no trades expected or found for this cycle)")
    print()

    print("Caveats:")
    for caveat in report.caveats:
        print(f"  - {caveat}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay a past trading cycle and verify it against the device's own recorded data."
    )
    parser.add_argument(
        "--index", type=int, default=0, help="0 = most recent completed cycle, 1 = the one before that, etc."
    )
    parser.add_argument("--list", action="store_true", help="List recent cycles instead of auditing one.")
    parser.add_argument("--limit", type=int, default=10, help="How many recent cycles to show with --list.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON instead of plain text.")
    args = parser.parse_args()

    core = DeviceCore.load()
    try:
        if args.list:
            for i, row in enumerate(list_recent_cycles(core, limit=args.limit)):
                ts = row["ts"].isoformat()
                equity = f"${row['equity']:,.2f}" if row["equity"] is not None else "unknown"
                cash = f"${row['cash']:,.2f}" if row["cash"] is not None else "unknown"
                print(f"[{i}] {ts}  equity={equity} cash={cash}")
            return

        report = audit_cycle(core, cycle_index=args.index)
        if args.json:
            print(json.dumps(asdict(report), indent=2, default=str))
        else:
            _print_report(report)
    finally:
        core.close()


if __name__ == "__main__":
    main()
