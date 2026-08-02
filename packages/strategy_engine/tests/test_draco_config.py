from strategy_engine.bots.draco_config import (
    DracoConfig,
    draco_config_from_dict,
    validate_draco_config,
)


def test_draco_config_defaults_are_valid():
    config = DracoConfig(universe=["AAPL", "MSFT"])
    assert validate_draco_config(config) == []


def test_validate_draco_config_flags_empty_universe():
    config = DracoConfig(universe=[])
    errors = validate_draco_config(config)
    assert any("universe must not be empty" in e for e in errors)


def test_validate_draco_config_flags_fallback_ticker_inside_universe():
    config = DracoConfig(universe=["QQQ", "AAPL"], fallback_ticker="QQQ")
    errors = validate_draco_config(config)
    assert any("fallbackTicker must not also appear in universe" in e for e in errors)


def test_validate_draco_config_flags_duplicate_tickers():
    config = DracoConfig(universe=["AAPL", "AAPL", "MSFT"])
    errors = validate_draco_config(config)
    assert any("duplicate tickers" in e for e in errors)


def test_validate_draco_config_flags_out_of_range_exposure_and_stop_loss():
    config = DracoConfig(universe=["AAPL"], target_gross_exposure=1.5, stop_loss_percent=0.0)
    errors = validate_draco_config(config)
    assert any("targetGrossExposure" in e for e in errors)
    assert any("stopLossPercent" in e for e in errors)


def test_draco_config_from_dict_uses_defaults_when_empty():
    config = draco_config_from_dict({})
    assert config.fallback_ticker == "QQQ"
    assert config.benchmark_ticker == "SPY"
    assert config.universe == []


def test_draco_config_from_dict_reads_top_level_and_params_fields():
    data = {
        "universe": ["AAPL", "MSFT", "NVDA"],
        "fallback_ticker": "VOO",
        "params": {
            "maxPositions": 5,
            "targetGrossExposure": 0.8,
            "stopLossPercent": 0.12,
        },
    }
    config = draco_config_from_dict(data)
    assert config.universe == ["AAPL", "MSFT", "NVDA"]
    assert config.fallback_ticker == "VOO"
    assert config.max_positions == 5
    assert config.target_gross_exposure == 0.8
    assert config.stop_loss_percent == 0.12


def test_draco_config_from_dict_excludes_fallback_ticker_from_universe():
    data = {"universe": ["AAPL", "VOO", "MSFT"], "fallback_ticker": "VOO"}
    config = draco_config_from_dict(data)
    assert "VOO" not in config.universe
    assert config.universe == ["AAPL", "MSFT"]


def test_draco_config_from_dict_caps_max_positions_at_ten():
    data = {"universe": ["A", "B"], "params": {"maxPositions": 999}}
    config = draco_config_from_dict(data)
    assert config.max_positions == 10
