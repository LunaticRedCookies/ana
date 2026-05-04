import json
from collections import defaultdict
from datetime import timedelta
from statistics import mean
from typing import Dict, List

from sqlalchemy.orm import Session
from . import models

PIP_MULT = 10000
TF_MIN = {"M1": 1, "M5": 5, "M15": 15}


def _session_name(hour: int) -> str:
    if 0 <= hour < 8:
        return "asia"
    if 8 <= hour < 16:
        return "london"
    return "newyork"


def resample_candles(db: Session, source_timeframe: str = "M1", target_timeframe: str = "M5") -> Dict[str, int]:
    if source_timeframe != "M1" or target_timeframe not in ("M5", "M15"):
        return {"created": 0, "dropped": 0}
    group = 5 if target_timeframe == "M5" else 15
    by_symbol = defaultdict(list)
    rows = db.query(models.RawCandle).filter_by(timeframe="M1").order_by(models.RawCandle.symbol, models.RawCandle.timestamp).all()
    for r in rows:
        by_symbol[r.symbol].append(r)
    created = 0
    dropped = 0
    for symbol, arr in by_symbol.items():
        exist = {x.timestamp for x in db.query(models.RawCandle).filter_by(symbol=symbol, timeframe=target_timeframe).all()}
        full = len(arr) // group
        dropped += len(arr) % group
        for i in range(full):
            chunk = arr[i * group:(i + 1) * group]
            ts = chunk[0].timestamp
            if ts in exist:
                continue
            db.add(models.RawCandle(symbol=symbol, timeframe=target_timeframe, timestamp=ts, open=chunk[0].open, high=max(x.high for x in chunk), low=min(x.low for x in chunk), close=chunk[-1].close, volume=sum(x.volume for x in chunk)))
            created += 1
    db.commit()
    return {"created": created, "dropped": dropped}


def _feature_for_series(symbol: str, tf: str, arr: List[models.RawCandle], payout_rate: float):
    out = []
    closes = [x.close for x in arr]
    for i, c in enumerate(arr):
        rng = max(c.high - c.low, 1e-8)
        direction = "up" if c.close > c.open else "down" if c.close < c.open else "flat"
        streak = 1
        for j in range(i - 1, -1, -1):
            jd = "up" if arr[j].close > arr[j].open else "down" if arr[j].close < arr[j].open else "flat"
            if jd != direction:
                break
            streak += 1
        window = arr[max(0, i - 13):i + 1]
        atr = mean([max(w.high - w.low, abs(w.high - (window[idx - 1].close if idx else w.close)), abs(w.low - (window[idx - 1].close if idx else w.close))) for idx, w in enumerate(window)])
        atr_hist = [mean([(z.high - z.low) for z in arr[max(0, x-13):x+1]]) for x in range(max(0, i-99), i+1)]
        atr_pct = sum(1 for v in atr_hist if v <= atr) / len(atr_hist)
        ema5 = mean(closes[max(0, i - 4):i + 1]); ema5_prev = mean(closes[max(0, i - 5):i]) if i else ema5
        slope = ema5 - ema5_prev
        recent = arr[max(0, i - 19):i + 1]; rh = max(x.high for x in recent); rl = min(x.low for x in recent)
        out.append(models.Feature(symbol=symbol, timeframe=tf, timestamp=c.timestamp, candle_body_ratio=abs(c.close-c.open)/rng, upper_wick_ratio=(c.high-max(c.open,c.close))/rng, lower_wick_ratio=(min(c.open,c.close)-c.low)/rng, candle_direction=direction, consecutive_candle_direction=streak, recent_high_distance=(rh-c.close)*PIP_MULT, recent_low_distance=(c.close-rl)*PIP_MULT, atr=atr*PIP_MULT, atr_percentile=atr_pct, ema_slope=slope*PIP_MULT, trend_state="up" if slope > 0 else "down" if slope < 0 else "flat", breakout_state="break_high" if c.close >= rh else "break_low" if c.close <= rl else "inside", pullback_state="none", volatility_regime="high" if atr_pct >= 0.7 else "low" if atr_pct <= 0.3 else "mid", time_of_day=c.timestamp.hour, session_name=_session_name(c.timestamp.hour), payout_rate=payout_rate))
    return out


def generate_features(db: Session, payout_rate: float = 0.8):
    resample_candles(db, "M1", "M5")
    resample_candles(db, "M1", "M15")
    db.query(models.Feature).delete(); db.commit()
    by_key = defaultdict(list)
    for c in db.query(models.RawCandle).order_by(models.RawCandle.symbol, models.RawCandle.timeframe, models.RawCandle.timestamp).all():
        by_key[(c.symbol, c.timeframe)].append(c)
    for (symbol, tf), arr in by_key.items():
        for f in _feature_for_series(symbol, tf, arr, payout_rate):
            db.add(f)
    db.commit()


def _latest_confirmed(feature_rows, ts):
    candidates = [r for r in feature_rows if r.timestamp <= ts]
    return candidates[-1] if candidates else None


def generate_labels(db: Session):
    db.query(models.Label).delete(); db.commit()
    expiries = [30, 60, 120, 180]
    by_key = defaultdict(list)
    for c in db.query(models.RawCandle).order_by(models.RawCandle.symbol, models.RawCandle.timeframe, models.RawCandle.timestamp).all():
        by_key[(c.symbol, c.timeframe)].append(c)
    for (symbol, tf), arr in by_key.items():
        for i, c in enumerate(arr):
            for exp in expiries:
                if tf == "M1" and exp == 30:
                    db.add(models.Label(symbol=symbol, timeframe=tf, timestamp=c.timestamp, expiry_seconds=30, entry_price=c.close, expiry_price=c.close, result_high="unsupported", result_low="unsupported", margin_pips=0, max_adverse_excursion=0, max_favorable_excursion=0, close_distance_from_entry=0)); continue
                target = c.timestamp + timedelta(seconds=exp)
                j = next((k for k in range(i+1, len(arr)) if arr[k].timestamp >= target), None)
                if j is None:
                    db.add(models.Label(symbol=symbol, timeframe=tf, timestamp=c.timestamp, expiry_seconds=exp, entry_price=c.close, expiry_price=c.close, result_high="unsupported", result_low="unsupported", margin_pips=0, max_adverse_excursion=0, max_favorable_excursion=0, close_distance_from_entry=0)); continue
                e = arr[j]; margin=(e.close-c.close)*PIP_MULT
                h='win' if e.close>c.close else 'loss' if e.close<c.close else 'draw'
                l='win' if e.close<c.close else 'loss' if e.close>c.close else 'draw'
                window=arr[i:j+1]
                db.add(models.Label(symbol=symbol,timeframe=tf,timestamp=c.timestamp,expiry_seconds=exp,entry_price=c.close,expiry_price=e.close,result_high=h,result_low=l,margin_pips=margin,max_adverse_excursion=min((x.low-c.close)*PIP_MULT for x in window),max_favorable_excursion=max((x.high-c.close)*PIP_MULT for x in window),close_distance_from_entry=margin))
    db.commit()


def ensure_candidates(db: Session):
    if db.query(models.StrategyCandidate).count(): return
    db.add(models.StrategyCandidate(strategy_id='S001', direction='HIGH', expiry_seconds=60, required_conditions='trend_m15_up', blocked_conditions='vol_low', score_formula='det', min_trade_count=5, min_expected_value=0, min_walk_forward_pass_rate=0.5, max_drawdown_limit=1000, max_losing_streak_limit=10, max_near_zero_margin_rate=0.8, required_edge=0.0))
    db.add(models.StrategyCandidate(strategy_id='S002', direction='LOW', expiry_seconds=60, required_conditions='trend_m15_down', blocked_conditions='vol_low', score_formula='det', min_trade_count=5, min_expected_value=0, min_walk_forward_pass_rate=0.5, max_drawdown_limit=1000, max_losing_streak_limit=10, max_near_zero_margin_rate=0.8, required_edge=0.0))
    db.commit()


def _metrics_from_results(results, payout):
    tc=len(results); w=sum(1 for r in results if r=='win'); l=sum(1 for r in results if r=='loss'); d=tc-w-l
    wr=w/tc if tc else 0; lr=l/tc if tc else 0; ev=wr*payout-lr
    pnl=[payout if r=='win' else -1 if r=='loss' else 0 for r in results]
    cum=0; peak=0; mdd=0; ls=0; maxls=0
    for x in pnl:
        cum+=x; peak=max(peak,cum); mdd=max(mdd,peak-cum); ls=ls+1 if x<0 else 0; maxls=max(maxls,ls)
    return tc,w,l,d,wr,ev,mdd,maxls,pnl


def backtest(db: Session, near_zero_threshold: float = 0.2, payout_rate: float = 0.8):
    db.query(models.BacktestRun).delete(); db.query(models.BacktestTrade).delete(); db.commit(); ensure_candidates(db)
    feats = defaultdict(dict)
    for f in db.query(models.Feature).all(): feats[(f.symbol,f.timeframe)][f.timestamp]=f
    m5f = defaultdict(list); m15f=defaultdict(list)
    for f in db.query(models.Feature).filter(models.Feature.timeframe=='M5').order_by(models.Feature.timestamp): m5f[f.symbol].append(f)
    for f in db.query(models.Feature).filter(models.Feature.timeframe=='M15').order_by(models.Feature.timestamp): m15f[f.symbol].append(f)
    labels=db.query(models.Label).filter(models.Label.timeframe=='M1').all()
    for s in db.query(models.StrategyCandidate).all():
        results=[]; margins=[]
        for l in labels:
            if l.expiry_seconds!=s.expiry_seconds or l.result_high=='unsupported': continue
            f1=feats[(l.symbol,'M1')].get(l.timestamp); f5=_latest_confirmed(m5f[l.symbol], l.timestamp); f15=_latest_confirmed(m15f[l.symbol], l.timestamp)
            if not (f1 and f5 and f15): continue
            if s.direction=='HIGH' and not (f5.trend_state=='up' and f15.trend_state=='up'): continue
            if s.direction=='LOW' and not (f5.trend_state=='down' and f15.trend_state=='down'): continue
            r = l.result_high if s.direction=='HIGH' else l.result_low
            results.append(r); margins.append(abs(l.margin_pips))
            db.add(models.BacktestTrade(strategy_id=s.strategy_id,symbol=l.symbol,timeframe='M1',timestamp=l.timestamp,direction=s.direction,expiry_seconds=s.expiry_seconds,payout_rate=payout_rate,result=r,margin_pips=l.margin_pips))
        tc,w,lss,d,wr,ev,mdd,maxls,pnl=_metrics_from_results(results,payout_rate)
        if tc==0:
            db.add(models.BacktestRun(strategy_id=s.strategy_id,trade_count=0,win_count=0,loss_count=0,draw_count=0,win_rate=0,break_even_win_rate=1/(1+payout_rate),expected_value_per_trade=0,total_expected_value=0,max_drawdown=0,longest_losing_streak=0,profit_factor=0,average_margin_pips=0,near_zero_margin_rate=0)); continue
        gp=sum(x for x in pnl if x>0); gl=abs(sum(x for x in pnl if x<0)); pf=gp/gl if gl>0 else 0
        nz=sum(1 for m in margins if m<=near_zero_threshold)/tc
        db.add(models.BacktestRun(strategy_id=s.strategy_id,trade_count=tc,win_count=w,loss_count=lss,draw_count=d,win_rate=wr,break_even_win_rate=1/(1+payout_rate),expected_value_per_trade=ev,total_expected_value=ev*tc,max_drawdown=mdd,longest_losing_streak=maxls,profit_factor=pf,average_margin_pips=mean(margins),near_zero_margin_rate=nz))
    db.commit()


def walk_forward(db: Session, train_window: int = 30, test_window: int = 10, payout_rate: float = 0.8):
    db.query(models.WalkForwardRun).delete(); db.commit()
    for s in db.query(models.StrategyCandidate).all():
        trades = db.query(models.BacktestTrade).filter_by(strategy_id=s.strategy_id).order_by(models.BacktestTrade.timestamp).all()
        idx = train_window; details=[]; pass_count=0
        while idx + test_window <= len(trades):
            seg = trades[idx:idx+test_window]
            tc,w,lss,d,wr,ev,mdd,maxls,_=_metrics_from_results([x.result for x in seg], payout_rate)
            ok = tc>=s.min_trade_count and ev>0 and wr>=(1/(1+payout_rate)+s.required_edge) and mdd<=s.max_drawdown_limit and maxls<=s.max_losing_streak_limit
            details.append({"start": seg[0].timestamp.isoformat(),"end": seg[-1].timestamp.isoformat(),"trade_count": tc,"win_rate": wr,"expected_value_per_trade": ev,"max_drawdown": mdd,"longest_losing_streak": maxls,"pass": ok})
            pass_count += 1 if ok else 0
            idx += test_window
        periods=len(details); pr=pass_count/periods if periods else 0
        db.add(models.WalkForwardRun(strategy_id=s.strategy_id,pass_rate=pr,periods=periods,detail_json=json.dumps(details)))
    db.commit()


def stress_test(db: Session, payout_scenarios=(0.8,0.75,0.7)):
    out = {}
    for s in db.query(models.StrategyCandidate).all():
        trades = db.query(models.BacktestTrade).filter_by(strategy_id=s.strategy_id).order_by(models.BacktestTrade.timestamp).all()
        results=[t.result for t in trades]
        worst = sorted(results, key=lambda x: 0 if x=='loss' else 1 if x=='draw' else 2)
        _,_,_,_,_,_,worst_mdd,_,_=_metrics_from_results(worst,0.8)
        payout_evs={}
        for p in payout_scenarios:
            tc,w,l,_,wr,ev,_,_,_=_metrics_from_results(results,p)
            payout_evs[str(p)] = {"trade_count": tc, "expected_value_per_trade": ev, "break_even_win_rate": 1/(1+p)}
        out[s.strategy_id] = {"worst_case_max_drawdown": worst_mdd, "payout_scenarios": payout_evs}
    return out
