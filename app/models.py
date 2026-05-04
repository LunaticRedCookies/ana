from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from .database import Base


class RawCandle(Base):
    __tablename__ = "raw_candles"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    timeframe = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)


class Feature(Base):
    __tablename__ = "features"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    timeframe = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    candle_body_ratio = Column(Float)
    upper_wick_ratio = Column(Float)
    lower_wick_ratio = Column(Float)
    candle_direction = Column(String)
    consecutive_candle_direction = Column(Integer)
    recent_high_distance = Column(Float)
    recent_low_distance = Column(Float)
    atr = Column(Float)
    atr_percentile = Column(Float)
    ema_slope = Column(Float)
    trend_state = Column(String)
    breakout_state = Column(String)
    pullback_state = Column(String)
    volatility_regime = Column(String)
    time_of_day = Column(Integer)
    session_name = Column(String)
    payout_rate = Column(Float, default=0.8)


class Label(Base):
    __tablename__ = "labels"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    timeframe = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    expiry_seconds = Column(Integer, index=True)
    entry_price = Column(Float)
    expiry_price = Column(Float)
    result_high = Column(String)
    result_low = Column(String)
    margin_pips = Column(Float)
    max_adverse_excursion = Column(Float)
    max_favorable_excursion = Column(Float)
    close_distance_from_entry = Column(Float)


class StrategyCandidate(Base):
    __tablename__ = "strategy_candidates"
    id = Column(Integer, primary_key=True)
    strategy_id = Column(String, unique=True, index=True)
    direction = Column(String)
    expiry_seconds = Column(Integer)
    required_conditions = Column(Text)
    blocked_conditions = Column(Text)
    score_formula = Column(Text)
    min_trade_count = Column(Integer)
    min_expected_value = Column(Float)
    min_walk_forward_pass_rate = Column(Float)
    max_drawdown_limit = Column(Float)
    max_losing_streak_limit = Column(Integer)
    max_near_zero_margin_rate = Column(Float, default=0.40)
    required_edge = Column(Float, default=0.01)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id = Column(Integer, primary_key=True)
    strategy_id = Column(String, index=True, unique=True)
    trade_count = Column(Integer)
    win_count = Column(Integer)
    loss_count = Column(Integer)
    draw_count = Column(Integer)
    win_rate = Column(Float)
    break_even_win_rate = Column(Float)
    expected_value_per_trade = Column(Float)
    total_expected_value = Column(Float)
    max_drawdown = Column(Float)
    longest_losing_streak = Column(Integer)
    profit_factor = Column(Float)
    average_margin_pips = Column(Float)
    near_zero_margin_rate = Column(Float)


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    id = Column(Integer, primary_key=True)
    strategy_id = Column(String, index=True)
    symbol = Column(String)
    timeframe = Column(String)
    timestamp = Column(DateTime, index=True)
    direction = Column(String)
    expiry_seconds = Column(Integer)
    payout_rate = Column(Float)
    result = Column(String)
    margin_pips = Column(Float)


class WalkForwardRun(Base):
    __tablename__ = "walk_forward_runs"
    id = Column(Integer, primary_key=True)
    strategy_id = Column(String, index=True, unique=True)
    pass_rate = Column(Float)
    periods = Column(Integer)
    detail_json = Column(Text)


class LiveSignal(Base):
    __tablename__ = "live_signals"
    id = Column(Integer, primary_key=True)
    symbol = Column(String)
    strategy_id = Column(String)
    direction = Column(String)
    expiry_seconds = Column(Integer)
    entry_allowed = Column(Boolean)
    score = Column(Float)
    expected_value_estimate = Column(Float)
    break_even_win_rate = Column(Float)
    current_payout_rate = Column(Float)
    blocked_reasons = Column(Text)
    operator_message = Column(Text)


class OperatorAction(Base):
    __tablename__ = "operator_actions"
    id = Column(Integer, primary_key=True)
    action_type = Column(String)
    note = Column(Text)


class StrategyStatus(Base):
    __tablename__ = "strategy_status"
    id = Column(Integer, primary_key=True)
    strategy_id = Column(String, unique=True, index=True)
    active = Column(Boolean, default=False)
    reason = Column(Text)


class RegimeStat(Base):
    __tablename__ = "regime_stats"
    id = Column(Integer, primary_key=True)
    strategy_id = Column(String, index=True)
    regime = Column(String)
    win_rate = Column(Float)
    ev = Column(Float)
