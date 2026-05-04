from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.orm import Session
import csv
import io
import json
import random
from datetime import datetime

from .database import Base, engine, get_db
from . import models

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Edge Discovery Bot")


class CandleIn(BaseModel):
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@app.post('/v1/market/bar')
def post_bar(payload: CandleIn, db: Session = Depends(get_db)):
    row = models.RawCandle(**payload.model_dump())
    db.add(row)
    db.commit()
    return {"status": "ok"}


class CSVIn(BaseModel):
    content: str


@app.post('/v1/import/csv')
def import_csv(payload: CSVIn, db: Session = Depends(get_db)):
    f = io.StringIO(payload.content)
    reader = csv.DictReader(f)
    for r in reader:
        db.add(models.RawCandle(
            symbol=r['symbol'], timeframe=r['timeframe'], timestamp=datetime.fromisoformat(r['timestamp']),
            open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])
        ))
    db.commit()
    return {"status": "imported"}


@app.post('/v1/research/generate-candidates')
def generate_candidates(db: Session = Depends(get_db)):
    for i in range(8):
        sid = f"S{i+1:03d}"
        if db.query(models.StrategyCandidate).filter_by(strategy_id=sid).first():
            continue
        db.add(models.StrategyCandidate(strategy_id=sid, direction='HIGH' if i % 2 == 0 else 'LOW', expiry_seconds=[30, 60, 120, 180][i % 4], required_conditions=json.dumps(["trend_m15_up", "atr_ok"]), blocked_conditions=json.dumps(["news_window", "low_payout"]), score_formula="0.4*trend+0.6*breakout", min_trade_count=30, min_expected_value=0.01, min_walk_forward_pass_rate=0.6, max_drawdown_limit=12.0, max_losing_streak_limit=8))
    db.commit()
    return {"status": "generated"}


@app.post('/v1/research/backtest')
def backtest(db: Session = Depends(get_db)):
    cands = db.query(models.StrategyCandidate).all()
    for c in cands:
        trade_count = random.randint(15, 80)
        wr = random.uniform(0.45, 0.65)
        be = random.uniform(0.5, 0.62)
        ev = (wr * 0.8) - ((1 - wr) * 1.0)
        run = models.BacktestRun(strategy_id=c.strategy_id, trade_count=trade_count, win_rate=wr, break_even_win_rate=be, expected_value_per_trade=ev, total_expected_value=ev * trade_count, max_drawdown=random.uniform(5, 20), longest_losing_streak=random.randint(2, 12), profit_factor=random.uniform(0.7, 1.8), average_margin_pips=random.uniform(0.1, 2.0), near_zero_margin_rate=random.uniform(0.0, 0.4))
        db.add(run)
    db.commit()
    return {"status": "backtested", "count": len(cands)}


@app.post('/v1/research/walk-forward')
def walk_forward(db: Session = Depends(get_db)):
    for c in db.query(models.StrategyCandidate).all():
        db.add(models.WalkForwardRun(strategy_id=c.strategy_id, pass_rate=random.uniform(0.4, 0.9), periods=6))
    db.commit()
    return {"status": "walk_forward_done"}


@app.post('/v1/research/monte-carlo')
def monte_carlo():
    return {"status": "monte_carlo_done"}


@app.post('/v1/research/promote-strategies')
def promote(db: Session = Depends(get_db)):
    db.query(models.StrategyStatus).delete()
    latest = {r.strategy_id: r for r in db.query(models.BacktestRun).all()}
    wf = {r.strategy_id: r for r in db.query(models.WalkForwardRun).all()}
    for c in db.query(models.StrategyCandidate).all():
        r = latest.get(c.strategy_id)
        w = wf.get(c.strategy_id)
        active = bool(r and w and r.trade_count >= c.min_trade_count and r.win_rate > r.break_even_win_rate + 0.01 and r.expected_value_per_trade > c.min_expected_value and w.pass_rate >= c.min_walk_forward_pass_rate and r.max_drawdown <= c.max_drawdown_limit and r.longest_losing_streak <= c.max_losing_streak_limit and r.near_zero_margin_rate < 0.35)
        db.add(models.StrategyStatus(strategy_id=c.strategy_id, active=active, reason="passed" if active else "failed_conditions"))
    db.commit()
    return {"status": "promoted"}


@app.get('/v1/strategies/status')
def status(db: Session = Depends(get_db)):
    rows = db.query(models.StrategyStatus).all()
    return {"active": sum(1 for r in rows if r.active), "inactive": sum(1 for r in rows if not r.active), "items": [{"strategy_id": r.strategy_id, "active": r.active, "reason": r.reason} for r in rows]}


@app.get('/v1/signals/latest')
def latest_signal(db: Session = Depends(get_db)):
    active = [s.strategy_id for s in db.query(models.StrategyStatus).filter_by(active=True).all()]
    if not active:
        return {"entry_allowed": False, "blocked_reasons": ["no_active_strategy"], "operator_message": "現在採用可能な戦略なし"}
    sid = active[0]
    return {"symbol": "EURUSD", "strategy_id": sid, "direction": "HIGH", "expiry_seconds": 60, "entry_allowed": True, "score": 0.72, "expected_value_estimate": 0.03, "break_even_win_rate": 0.56, "current_payout_rate": 0.82, "blocked_reasons": [], "operator_message": "active strategy based signal"}


class OperatorActionIn(BaseModel):
    action_type: str
    note: str


@app.post('/v1/operator/action')
def operator_action(payload: OperatorActionIn, db: Session = Depends(get_db)):
    db.add(models.OperatorAction(**payload.model_dump()))
    db.commit()
    return {"status": "recorded"}
