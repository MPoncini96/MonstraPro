"""trading_worker entrypoint — systemd target monstrapro-worker.service.

Responsibilities (see ARCHITECTURE.md section 4.1):

  1. Load device_core.config, open the SQLite DB, run pending migrations.
  2. Own the activation state machine (see activation.py): on real hardware,
     HTTPActivationClient registers with and polls monstra.pro's device API
     (_build_activation_client); LocalActivationClient (local DB only) is
     used for offline/simulated dev and tests.
       not activated -> emit `awaiting_activation` device_event on *every*
                         poll (not just once - see _wait_for_activation's
                         docstring for why a one-shot publish is fragile to
                         a display restart), poll again after
                         ACTIVATION_POLL_INTERVAL_SECONDS.
       activated     -> enter the trading loop (_run_trading_loop).
     _run_trading_loop keeps re-verifying activation with monstra.pro on
     every tick (ACCOUNT_SNAPSHOT_INTERVAL_SECONDS - see
     activation.py's HTTPActivationClient._recheck_activated) rather than
     trusting the local flag forever - this is what makes a website-side
     disconnect (NextJS_Monsta's POST /api/devices/[deviceId]/disconnect)
     actually stop an already-running device, instead of only taking
     effect the next time this service restarts. If it detects
     deactivation, _run_trading_loop returns and main()'s outer loop calls
     _wait_for_activation again - no service restart needed to re-pair.
  3. Once activated, _build_alpaca_client syncs Alpaca credentials from
     monstra.pro on demand if none exist locally yet (alpaca_sync.py) -
     the device-side half of the connect flow in NextJS_Monsta's
     /devices/alpaca page. Only ever touches the network while local
     credentials are missing; once synced, relies on its own local Vault.
  4. Trading loop, per scheduled cycle (TRADING_CYCLE_INTERVAL_SECONDS) or
     immediately if the owner requested an out-of-schedule run from
     monstra.pro (NextJS_Monsta's POST /api/devices/[deviceId]/run-now,
     polled here via run_request.check_run_requested and market-hours
     gated on both sides):
       reconcile_manual_holdings (manual_holdings.py) - buy up to each
         locked individual stock's target_qty, never sell
       -> run_cycle (loop.py) - fetch market data -> run the owner's
         strategies via strategy_engine -> diff target weights vs current
         Alpaca positions (locked symbols excluded) -> submit orders ->
         persist signal/order/execution_log rows -> emit `trade_executed`.

Known gap: which Alpaca credential row (paper vs live) is "the" active one
isn't modeled anywhere yet (no `device`/settings column for it) — `_load_alpaca_credentials`
below prefers "live" over "paper" if both are connected. This needs a real
answer once Track B's activation flow defines how mode selection reaches
the device; tracked here rather than silently guessed elsewhere.

Account-equity, per-position, and per-bot-value snapshots (for display's
idle-screen rotation - portfolio / bot / stock candlestick views, see
services/display/src/display/idle_rotation.py) are recorded together on
their own ACCOUNT_SNAPSHOT_INTERVAL_SECONDS cadence, independent of both
the slower trading-cycle cadence and market-open gating — equity is
legitimately flat while the market's closed, and that flat stretch is real
data the charts should show, not a gap to skip recording during.

Per-bot value is an approximation (current_weights-sum x account equity),
not a true segregated per-bot sub-account - see
device_core.db.models.BotValueSnapshot's docstring for why.
"""

from __future__ import annotations

import logging
import os
import platform
import time
from typing import Callable

from device_core.core import DeviceCore
from device_core.events import EventType
from strategy_engine.market_data import provider as market_data_provider

from trading_worker.activation import (
    ActivationClient,
    ActivationStatus,
    HTTPActivationClient,
    LocalActivationClient,
)
from trading_worker.alpaca_client import AlpacaClient
from trading_worker.alpaca_sync import sync_alpaca_credentials_if_missing
from trading_worker.loop import run_cycle
from trading_worker.manual_holdings import reconcile_manual_holdings
from trading_worker.run_request import ack_run_request, check_run_requested

logger = logging.getLogger(__name__)

ACTIVATION_POLL_INTERVAL_SECONDS = 60
ACCOUNT_SNAPSHOT_INTERVAL_SECONDS = 60
TRADING_CYCLE_INTERVAL_SECONDS = 300


def _build_activation_client(core: DeviceCore) -> ActivationClient:
    """Same Linux-real/non-Linux-simulated split as
    device_agent.main._build_network_manager, for the same reason: never let
    a dev machine's test run make a real HTTP call to monstra.pro."""
    if platform.system() == "Linux" and os.environ.get("TRADING_WORKER_SIMULATE_ACTIVATION") != "1":
        return HTTPActivationClient(core)
    logger.warning("using LocalActivationClient (non-Linux host or TRADING_WORKER_SIMULATE_ACTIVATION=1)")
    return LocalActivationClient(core)


def _load_alpaca_credentials(core: DeviceCore) -> dict[str, str] | None:
    return core.credentials.get("live") or core.credentials.get("paper")


def _configure_market_data(core: DeviceCore) -> None:
    credentials = _load_alpaca_credentials(core)
    if credentials is None:
        logger.warning("no Alpaca credentials connected yet; market data falls back to yfinance")
        return
    market_data_provider.configure(
        alpaca_api_key=credentials["api_key"],
        alpaca_secret_key=credentials["api_secret"],
    )


def _build_alpaca_client(core: DeviceCore) -> AlpacaClient | None:
    credentials = _load_alpaca_credentials(core)
    if credentials is None and sync_alpaca_credentials_if_missing(core):
        # A fresh sync just populated the local Vault - reload, and also
        # give _configure_market_data (only ever called once, right after
        # activation, before this loop starts) a second chance now that
        # credentials actually exist, rather than leaving market data
        # permanently on its yfinance fallback for the rest of this
        # process's lifetime.
        credentials = _load_alpaca_credentials(core)
        if credentials is not None:
            _configure_market_data(core)
    if credentials is None:
        return None
    return AlpacaClient(
        api_key=credentials["api_key"],
        api_secret=credentials["api_secret"],
        base_url=credentials["base_url"],
    )


def _record_snapshots(core: DeviceCore, alpaca: AlpacaClient) -> None:
    """One round of local snapshots per call, all sharing a single
    get_account()/list_positions() pair of Alpaca calls:

      - account_snapshot: feeds draco's circuit breaker (equity_history)
        and display's portfolio candlestick view.
      - position_snapshot: one row per currently-held symbol, feeds
        display's last-trade P&L and top-movers stock candlestick view.
      - bot_value_snapshot: one row per active bot that (a) has rebalanced
        at least once, so a target_weights allocation exists, and (b) has
        at least one target symbol currently held and priced. Deliberately
        uses `target_weights_json` (bot-specific), not
        `current_weights_json` (computed account-wide across every
        currently-held position, not scoped to this bot at all - see
        loop.py's `_run_one_bot`) - using the latter would make every
        bot's value converge to ~the whole account's equity, which isn't a
        per-bot signal at all. See device_core.db.models.BotValueSnapshot's
        docstring for exactly what this index means and its one known gap.

    Called on its own fast cadence by main()'s loop, separate from
    run_cycle()'s own account_snapshot write (which still happens too, at
    cycle time - harmless: two close-in-time snapshots just land in the
    same candle bucket).
    """
    account = alpaca.get_account()
    core.account_snapshots.record(equity=account.equity, cash=account.cash)

    positions = alpaca.list_positions()
    current_prices = {position.symbol: position.current_price for position in positions}

    for position in positions:
        core.positions.record(
            symbol=position.symbol,
            qty=position.qty,
            avg_entry_price=position.avg_entry_price,
            current_price=position.current_price,
            market_value=position.market_value,
            unrealized_pl=position.unrealized_pl,
            unrealized_plpc=position.unrealized_plpc,
            unrealized_intraday_plpc=position.unrealized_intraday_plpc,
        )

    for row in core.strategies.get_active():
        bot_slug = row["bot_slug"]
        allocation = core.allocations.latest(bot_slug)
        if allocation is None:
            continue
        target_weights = allocation.get("target_weights_json") or {}
        weighted_price = sum(
            weight * current_prices[symbol] for symbol, weight in target_weights.items() if symbol in current_prices
        )
        if weighted_price <= 0:
            continue
        core.bot_values.record(bot_slug=bot_slug, value=weighted_price)


def _wait_for_activation(
    core: DeviceCore,
    activation: ActivationClient,
    *,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = ACTIVATION_POLL_INTERVAL_SECONDS,
    max_polls: int | None = None,
) -> ActivationStatus:
    """Blocks (production: forever; tests: up to `max_polls`) until
    activation.check_status().activated is True, re-publishing
    `awaiting_activation` on every poll rather than once on entry.

    Re-publishing matters because of how `display` derives its screen:
    state.py's StateMachine only replays *unconsumed* device_event rows
    (device_core.repositories.device_event.DeviceEventRepository.list_unconsumed),
    and consumed_at is one global flag per event, not per-consumer - once
    display consumes an event it is gone forever for every future consumer,
    including a freshly-restarted display process. A one-shot publish here
    means any restart of monstrapro-display.service after that single event
    was already consumed - e.g. a routine restart while the device happens
    to sit unactivated for a while - permanently drops the
    awaiting_activation screen back to generic idle, with no way to recover
    it short of restarting trading_worker itself. Caught live on real Pi 5
    hardware: restarting display to test an unrelated fix silently lost the
    activation screen for hours even though device.activated_at was null
    the entire time.
    """
    status = activation.check_status()
    polls = 0
    while not status.activated:
        core.events.publish(
            EventType.AWAITING_ACTIVATION,
            {"device_serial": status.device_serial, "pairing_code": status.pairing_code},
        )
        logger.info("device not yet activated (serial=%s); waiting", status.device_serial)
        polls += 1
        if max_polls is not None and polls >= max_polls:
            return status
        sleep(poll_interval_seconds)
        status = activation.check_status()
    return status


def _run_trading_loop(core: DeviceCore, activation: ActivationClient) -> None:
    """Runs snapshots + trading cycles until deactivated.

    Every tick also calls activation.check_status() - for HTTPActivationClient
    this re-verifies with monstra.pro rather than trusting the local
    activated flag forever (see activation.py's _recheck_activated), which is
    what makes a website-side disconnect
    (POST /api/devices/[deviceId]/disconnect) actually stop an
    already-running device instead of only taking effect on its next
    restart. That recheck therefore happens on the same
    ACCOUNT_SNAPSHOT_INTERVAL_SECONDS (60s) cadence as everything else in
    this loop. Returns (rather than exiting the process) once deactivated,
    so main() can loop back into _wait_for_activation and pick up a fresh
    pairing without a service restart.
    """
    last_snapshot_at = 0.0
    last_cycle_at = 0.0

    while True:
        status = activation.check_status()
        if not status.activated:
            logger.warning("device no longer activated; returning to awaiting-activation state")
            return

        alpaca = _build_alpaca_client(core)
        if alpaca is None:
            logger.warning("device activated but no Alpaca credentials connected yet; waiting")
            time.sleep(ACCOUNT_SNAPSHOT_INTERVAL_SECONDS)
            continue

        now = time.monotonic()

        if now - last_snapshot_at >= ACCOUNT_SNAPSHOT_INTERVAL_SECONDS:
            try:
                _record_snapshots(core, alpaca)
            except Exception:
                logger.exception("account snapshot poll failed")
            last_snapshot_at = now

        market_open = market_data_provider.is_market_open()
        cycle_due = now - last_cycle_at >= TRADING_CYCLE_INTERVAL_SECONDS
        run_requested = check_run_requested(core)

        if run_requested and not market_open:
            # The owner's run-now request was market-hours-gated when it was
            # made (see NextJS_Monsta's POST /api/devices/[deviceId]/run-now),
            # but the market can close in the gap before this device's next
            # poll - discard rather than leave it pending until the market
            # reopens, which would run unexpectedly with no owner action in
            # between.
            logger.info("run-now request received while market is closed; discarding")
            ack_run_request(core)
            run_requested = False

        if market_open and (cycle_due or run_requested):
            try:
                reconcile_manual_holdings(core, alpaca)
            except Exception:
                logger.exception("manual holdings reconciliation failed")
            try:
                run_cycle(core, alpaca)
            except Exception:
                logger.exception("trading cycle failed")
                core.events.publish(EventType.FATAL_ERROR, {"component": "trading_worker"}, severity="error")
            if run_requested:
                ack_run_request(core)
            last_cycle_at = now

        time.sleep(ACCOUNT_SNAPSHOT_INTERVAL_SECONDS)


def main() -> None:
    core = DeviceCore.load()
    activation = _build_activation_client(core)

    while True:
        status = _wait_for_activation(core, activation)
        core.events.publish(EventType.DEVICE_ACTIVATED, {"owner_ref": status.owner_ref})
        _configure_market_data(core)
        _run_trading_loop(core, activation)


if __name__ == "__main__":
    main()
