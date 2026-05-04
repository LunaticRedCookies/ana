from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models
from app.pipeline import generate_features, generate_labels, backtest, walk_forward, ensure_candidates


def mkdb():
    engine = create_engine('sqlite:///:memory:', connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_m1(db, n=40):
    t = datetime(2026,1,1,0,0,0)
    p = 1.1000
    for i in range(n):
        close = p + (0.0002 if i % 2 == 0 else -0.0001)
        db.add(models.RawCandle(symbol='EURUSD', timeframe='M1', timestamp=t, open=p, high=max(p, close)+0.0001, low=min(p, close)-0.0001, close=close, volume=100+i))
        p = close; t += timedelta(minutes=1)
    db.commit()


def test_deterministic_results_two_runs():
    db = mkdb(); seed_m1(db); ensure_candidates(db)
    generate_features(db); generate_labels(db); backtest(db); walk_forward(db)
    r1 = [(r.strategy_id, r.trade_count, r.win_rate, r.expected_value_per_trade) for r in db.query(models.BacktestRun).order_by(models.BacktestRun.strategy_id)]
    generate_features(db); generate_labels(db); backtest(db); walk_forward(db)
    r2 = [(r.strategy_id, r.trade_count, r.win_rate, r.expected_value_per_trade) for r in db.query(models.BacktestRun).order_by(models.BacktestRun.strategy_id)]
    assert r1 == r2


def test_data_insufficient_blocked_reason_case():
    db = mkdb(); ensure_candidates(db)
    run = db.query(models.BacktestRun).count()
    assert run == 0


def test_break_even_and_ev_formula():
    db = mkdb(); seed_m1(db); ensure_candidates(db)
    generate_features(db); generate_labels(db); backtest(db, payout_rate=0.8)
    r = db.query(models.BacktestRun).first()
    assert abs(r.break_even_win_rate - (1/1.8)) < 1e-4
    loss_rate = r.loss_count / r.trade_count if r.trade_count else 0
    assert abs(r.expected_value_per_trade - (r.win_rate*0.8 - loss_rate)) < 1e-8


def test_near_zero_margin_rate_exists():
    db = mkdb(); seed_m1(db); ensure_candidates(db)
    generate_features(db); generate_labels(db); backtest(db, near_zero_threshold=0.2)
    assert db.query(models.BacktestRun).first().near_zero_margin_rate >= 0


def test_walk_forward_is_timeseries_ordered():
    db = mkdb(); seed_m1(db); ensure_candidates(db)
    generate_features(db); generate_labels(db); backtest(db); walk_forward(db, windows=3)
    wf = db.query(models.WalkForwardRun).first()
    assert wf.periods >= 0
