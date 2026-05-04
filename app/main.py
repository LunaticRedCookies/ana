from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.orm import Session
import csv, io
from datetime import datetime

from .database import Base, engine, get_db
from . import models
from .pipeline import generate_features, generate_labels, backtest, walk_forward, ensure_candidates, resample_candles, stress_test

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Edge Discovery Bot")

class CandleIn(BaseModel):
    symbol: str; timeframe: str; timestamp: datetime; open: float; high: float; low: float; close: float; volume: float
class CSVIn(BaseModel):
    content: str

@app.post('/v1/import/csv')
def import_csv(payload: CSVIn, db: Session = Depends(get_db)):
    for r in csv.DictReader(io.StringIO(payload.content)):
        db.add(models.RawCandle(symbol=r['symbol'], timeframe=r['timeframe'], timestamp=datetime.fromisoformat(r['timestamp']), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])))
    db.commit(); return {"status": "imported"}

@app.post('/v1/research/resample')
def api_resample(db: Session = Depends(get_db)):
    return {"m5": resample_candles(db, "M1", "M5"), "m15": resample_candles(db, "M1", "M15")}

@app.post('/v1/research/generate-features')
def api_features(db: Session = Depends(get_db)):
    generate_features(db); return {"status": "features_generated"}

@app.post('/v1/research/generate-labels')
def api_labels(db: Session = Depends(get_db)):
    generate_labels(db); return {"status": "labels_generated"}

@app.post('/v1/research/generate-candidates')
def generate_candidates(db: Session = Depends(get_db)):
    ensure_candidates(db); return {"status": "generated"}

@app.post('/v1/research/backtest')
def api_backtest(db: Session = Depends(get_db)):
    backtest(db); return {"status": "backtested"}

@app.post('/v1/research/walk-forward')
def api_walk_forward(db: Session = Depends(get_db)):
    walk_forward(db); return {"status": "walk_forward_done"}

@app.post('/v1/research/monte-carlo')
def api_stress(db: Session = Depends(get_db)):
    return {"status": "stress_done", "result": stress_test(db)}

@app.post('/v1/research/promote-strategies')
def promote(db: Session = Depends(get_db)):
    db.query(models.StrategyStatus).delete(); db.commit()
    back = {r.strategy_id: r for r in db.query(models.BacktestRun).all()}; wf={r.strategy_id: r for r in db.query(models.WalkForwardRun).all()}; stress=stress_test(db)
    for c in db.query(models.StrategyCandidate).all():
        r=back.get(c.strategy_id); w=wf.get(c.strategy_id); st=stress.get(c.strategy_id,{})
        if not r or not w or r.trade_count==0:
            active=False; reason='data_insufficient'
        else:
            payout70=st.get('payout_scenarios',{}).get('0.7',{}).get('expected_value_per_trade', -999)
            stable_windows = w.pass_rate >= c.min_walk_forward_pass_rate and w.periods > 0
            active=bool(r.trade_count>=c.min_trade_count and r.win_rate>=r.break_even_win_rate+c.required_edge and r.expected_value_per_trade>0 and stable_windows and r.max_drawdown<=c.max_drawdown_limit and r.longest_losing_streak<=c.max_losing_streak_limit and r.near_zero_margin_rate<=c.max_near_zero_margin_rate and payout70 > -0.2)
            reason='passed' if active else 'failed_conditions'
        db.add(models.StrategyStatus(strategy_id=c.strategy_id, active=active, reason=reason))
    db.commit(); return {"status": "promoted"}

@app.get('/v1/signals/latest')
def latest_signal(db: Session = Depends(get_db)):
    active=db.query(models.StrategyStatus).filter_by(active=True).all()
    if not active:
        return {"entry_allowed": False, "blocked_reasons": ["no_active_strategy"], "operator_message": "現在採用可能な戦略なし"}
    sid=active[0].strategy_id; run=db.query(models.BacktestRun).filter_by(strategy_id=sid).first(); cand=db.query(models.StrategyCandidate).filter_by(strategy_id=sid).first()
    if not run or run.trade_count==0:
        return {"entry_allowed": False, "blocked_reasons": ["data_insufficient"], "operator_message": "検証データ不足"}
    return {"symbol": "EURUSD", "strategy_id": sid, "direction": cand.direction, "expiry_seconds": cand.expiry_seconds, "entry_allowed": True, "score": run.expected_value_per_trade, "expected_value_estimate": run.expected_value_per_trade, "break_even_win_rate": run.break_even_win_rate, "current_payout_rate": 0.8, "blocked_reasons": [], "operator_message": "active strategy based signal"}
