from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models
from app.pipeline import generate_features, generate_labels, backtest, walk_forward, ensure_candidates, resample_candles, stress_test


def mkdb():
    engine = create_engine('sqlite:///:memory:', connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_m1(db, n=31):
    t = datetime(2026,1,1,0,0,0)
    p = 1.1000
    for i in range(n):
        close = p + (0.0002 if i % 2 == 0 else -0.0001)
        db.add(models.RawCandle(symbol='EURUSD', timeframe='M1', timestamp=t, open=p, high=max(p, close)+0.0001, low=min(p, close)-0.0001, close=close, volume=100+i))
        p = close; t += timedelta(minutes=1)
    db.commit()


def test_resample_m5_and_drop_incomplete():
    db = mkdb(); seed_m1(db, 12)
    r = resample_candles(db, 'M1', 'M5')
    assert r['created'] == 2 and r['dropped'] == 2


def test_resample_m15():
    db = mkdb(); seed_m1(db, 31)
    r = resample_candles(db, 'M1', 'M15')
    assert r['created'] == 2 and r['dropped'] == 1


def test_30s_unsupported_and_60s_next_close_and_tail_unsupported():
    db = mkdb(); seed_m1(db, 4)
    generate_labels(db)
    l30 = db.query(models.Label).filter_by(expiry_seconds=30).first()
    assert l30.result_high == 'unsupported'
    first = db.query(models.RawCandle).filter_by(timeframe='M1').order_by(models.RawCandle.timestamp).first()
    nextc = db.query(models.RawCandle).filter_by(timeframe='M1').order_by(models.RawCandle.timestamp).all()[1]
    l60 = db.query(models.Label).filter_by(timestamp=first.timestamp, expiry_seconds=60).first()
    assert l60.expiry_price == nextc.close
    tail = db.query(models.RawCandle).filter_by(timeframe='M1').order_by(models.RawCandle.timestamp).all()[-1]
    ltail = db.query(models.Label).filter_by(timestamp=tail.timestamp, expiry_seconds=180).first()
    assert ltail.result_high == 'unsupported'


def test_deterministic_backtest_and_stress():
    db = mkdb(); seed_m1(db, 50); ensure_candidates(db)
    generate_features(db); generate_labels(db); backtest(db); walk_forward(db)
    r1 = [(x.strategy_id, x.trade_count, x.expected_value_per_trade) for x in db.query(models.BacktestRun).order_by(models.BacktestRun.strategy_id)]
    s1 = stress_test(db)
    generate_features(db); generate_labels(db); backtest(db); walk_forward(db)
    r2 = [(x.strategy_id, x.trade_count, x.expected_value_per_trade) for x in db.query(models.BacktestRun).order_by(models.BacktestRun.strategy_id)]
    s2 = stress_test(db)
    assert r1 == r2 and s1 == s2


def test_break_even_increases_when_payout_drops():
    be08 = 1/(1+0.8)
    be07 = 1/(1+0.7)
    assert be07 > be08
