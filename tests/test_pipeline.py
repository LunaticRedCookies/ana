from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models
from app.pipeline import generate_features, generate_labels, backtest, walk_forward, ensure_candidates, resample_candles, latest_confirmed_feature, get_mtf_context


def mkdb():
    engine = create_engine('sqlite:///:memory:', connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_m1(db, n=40):
    t = datetime(2026,1,1,10,0,0); p=1.1
    for i in range(n):
        c=p+(0.0002 if i%2==0 else -0.0001)
        db.add(models.RawCandle(symbol='EURUSD',timeframe='M1',timestamp=t,bar_start_time=t,bar_end_time=t+timedelta(minutes=1),source_timeframe='csv',generated_from='csv',open=p,high=max(p,c)+0.0001,low=min(p,c)-0.0001,close=c,volume=100))
        p=c; t += timedelta(minutes=1)
    db.commit()


def test_resample_and_discard():
    db=mkdb(); seed_m1(db,12)
    r=resample_candles(db,'M1','M5')
    assert r['created']==2 and r['dropped']==2


def test_lookahead_block_and_release():
    db=mkdb(); seed_m1(db,20); generate_features(db)
    f_before = latest_confirmed_feature(db,'EURUSD','M5',datetime(2026,1,1,10,2,0))
    assert f_before is None
    f_after = latest_confirmed_feature(db,'EURUSD','M5',datetime(2026,1,1,10,5,0))
    assert f_after is not None and f_after.bar_start_time == datetime(2026,1,1,10,0,0)


def test_m15_lookahead_block():
    db=mkdb(); seed_m1(db,40); generate_features(db)
    assert latest_confirmed_feature(db,'EURUSD','M15',datetime(2026,1,1,10,14,0)) is None
    assert latest_confirmed_feature(db,'EURUSD','M15',datetime(2026,1,1,10,15,0)) is not None


def test_label_rules():
    db=mkdb(); seed_m1(db,4); generate_labels(db)
    assert db.query(models.Label).filter_by(expiry_seconds=30).first().result_high == 'unsupported'
    l = db.query(models.Label).filter_by(expiry_seconds=60).first()
    assert l.expiry_price == db.query(models.RawCandle).filter_by(timeframe='M1').order_by(models.RawCandle.bar_start_time).all()[1].close
    tail = db.query(models.Label).filter_by(expiry_seconds=180).order_by(models.Label.bar_start_time.desc()).first()
    assert tail.result_high == 'unsupported'


def test_data_insufficient_mtf_context_and_trade_log_fields():
    db=mkdb(); seed_m1(db,10); generate_features(db); generate_labels(db); ensure_candidates(db); backtest(db)
    m1 = db.query(models.RawCandle).filter_by(timeframe='M1').order_by(models.RawCandle.bar_start_time).first()
    assert get_mtf_context(db,'EURUSD',m1) is None
    t = db.query(models.BacktestTrade).first()
    if t:
        assert t.confirmed_m5_bar_end_time <= t.timestamp and t.confirmed_m15_bar_end_time <= t.timestamp


def test_deterministic_results():
    db=mkdb(); seed_m1(db,80); generate_features(db); generate_labels(db); ensure_candidates(db); backtest(db); walk_forward(db)
    r1=[(x.strategy_id,x.trade_count,x.expected_value_per_trade) for x in db.query(models.BacktestRun).order_by(models.BacktestRun.strategy_id)]
    generate_features(db); generate_labels(db); backtest(db); walk_forward(db)
    r2=[(x.strategy_id,x.trade_count,x.expected_value_per_trade) for x in db.query(models.BacktestRun).order_by(models.BacktestRun.strategy_id)]
    assert r1==r2
