import json
from collections import defaultdict
from datetime import timedelta
from statistics import mean

from sqlalchemy.orm import Session
from . import models

PIP_MULT = 10000


def _session_name(hour: int) -> str:
    if 0 <= hour < 8:
        return "asia"
    if 8 <= hour < 16:
        return "london"
    return "newyork"


def generate_features(db: Session, payout_rate: float = 0.8):
    db.query(models.Feature).delete()
    candles = db.query(models.RawCandle).order_by(models.RawCandle.symbol, models.RawCandle.timeframe, models.RawCandle.timestamp).all()
    by_key = defaultdict(list)
    for c in candles:
        by_key[(c.symbol, c.timeframe)].append(c)
    for (symbol, tf), arr in by_key.items():
        closes = [x.close for x in arr]
        for i, c in enumerate(arr):
            rng = max(c.high - c.low, 1e-8)
            body = abs(c.close - c.open)
            upper = c.high - max(c.open, c.close)
            lower = min(c.open, c.close) - c.low
            direction = "up" if c.close > c.open else "down" if c.close < c.open else "flat"
            prev_dir = direction if i == 0 else ("up" if arr[i-1].close > arr[i-1].open else "down" if arr[i-1].close < arr[i-1].open else "flat")
            streak = 1
            j = i - 1
            while j >= 0:
                jd = "up" if arr[j].close > arr[j].open else "down" if arr[j].close < arr[j].open else "flat"
                if jd != direction:
                    break
                streak += 1
                j -= 1
            w = arr[max(0, i - 13): i + 1]
            trs = []
            for k in range(len(w)):
                prev_close = w[k - 1].close if k > 0 else w[k].close
                trs.append(max(w[k].high - w[k].low, abs(w[k].high - prev_close), abs(w[k].low - prev_close)))
            atr = mean(trs)
            atr_hist = []
            for x in range(max(0, i-99), i+1):
                wk = arr[max(0, x-13):x+1]
                atr_hist.append(mean([(z.high-z.low) for z in wk]))
            atr_percentile = sum(1 for v in atr_hist if v <= atr) / len(atr_hist)
            ema5 = mean(closes[max(0, i-4):i+1])
            ema5_prev = mean(closes[max(0, i-5):i]) if i > 0 else ema5
            slope = ema5 - ema5_prev
            recent = arr[max(0, i-19):i+1]
            rh = max(x.high for x in recent)
            rl = min(x.low for x in recent)
            breakout = "break_high" if c.close >= rh else "break_low" if c.close <= rl else "inside"
            pullback = "pullback_up" if direction == "down" and prev_dir == "up" else "pullback_down" if direction == "up" and prev_dir == "down" else "none"
            trend = "up" if slope > 0 else "down" if slope < 0 else "flat"
            vol_regime = "high" if atr_percentile >= 0.7 else "low" if atr_percentile <= 0.3 else "mid"
            db.add(models.Feature(symbol=symbol, timeframe=tf, timestamp=c.timestamp, candle_body_ratio=body/rng, upper_wick_ratio=upper/rng, lower_wick_ratio=lower/rng, candle_direction=direction, consecutive_candle_direction=streak, recent_high_distance=(rh-c.close)*PIP_MULT, recent_low_distance=(c.close-rl)*PIP_MULT, atr=atr*PIP_MULT, atr_percentile=atr_percentile, ema_slope=slope*PIP_MULT, trend_state=trend, breakout_state=breakout, pullback_state=pullback, volatility_regime=vol_regime, time_of_day=c.timestamp.hour, session_name=_session_name(c.timestamp.hour), payout_rate=payout_rate))
    db.commit()


def generate_labels(db: Session):
    db.query(models.Label).delete()
    expiries = [30, 60, 120, 180]
    candles = db.query(models.RawCandle).order_by(models.RawCandle.symbol, models.RawCandle.timeframe, models.RawCandle.timestamp).all()
    by_key = defaultdict(list)
    for c in candles:
        by_key[(c.symbol, c.timeframe)].append(c)
    for (symbol, tf), arr in by_key.items():
        delta = timedelta(minutes=1 if tf == 'M1' else 5 if tf == 'M5' else 15)
        for i, c in enumerate(arr):
            for exp in expiries:
                if tf == 'M1' and exp == 30:
                    db.add(models.Label(symbol=symbol, timeframe=tf, timestamp=c.timestamp, expiry_seconds=30, entry_price=c.close, expiry_price=c.close, result_high='unsupported', result_low='unsupported', margin_pips=0, max_adverse_excursion=0, max_favorable_excursion=0, close_distance_from_entry=0))
                    continue
                target_t = c.timestamp + timedelta(seconds=exp)
                j = next((k for k in range(i+1, len(arr)) if arr[k].timestamp >= target_t), None)
                if j is None:
                    continue
                e = arr[j]
                margin = (e.close - c.close) * PIP_MULT
                h = 'win' if e.close > c.close else 'loss' if e.close < c.close else 'draw'
                l = 'win' if e.close < c.close else 'loss' if e.close > c.close else 'draw'
                window = arr[i:j+1]
                mae = min((x.low - c.close) * PIP_MULT for x in window)
                mfe = max((x.high - c.close) * PIP_MULT for x in window)
                db.add(models.Label(symbol=symbol, timeframe=tf, timestamp=c.timestamp, expiry_seconds=exp, entry_price=c.close, expiry_price=e.close, result_high=h, result_low=l, margin_pips=margin, max_adverse_excursion=mae, max_favorable_excursion=mfe, close_distance_from_entry=margin))
    db.commit()


def ensure_candidates(db: Session):
    if db.query(models.StrategyCandidate).count() > 0:
        return
    cands = [
        dict(strategy_id='S001', direction='HIGH', expiry_seconds=60, required_conditions=['trend_up'], blocked_conditions=['vol_low']),
        dict(strategy_id='S002', direction='LOW', expiry_seconds=60, required_conditions=['trend_down'], blocked_conditions=['vol_low']),
    ]
    for c in cands:
        db.add(models.StrategyCandidate(**c, score_formula='deterministic_v1', min_trade_count=5, min_expected_value=0.0, min_walk_forward_pass_rate=0.5, max_drawdown_limit=1000, max_losing_streak_limit=10, max_near_zero_margin_rate=0.8, required_edge=0.0))
    db.commit()


def backtest(db: Session, near_zero_threshold: float = 0.2, payout_rate: float = 0.8):
    db.query(models.BacktestRun).delete(); db.query(models.BacktestTrade).delete(); db.commit()
    ensure_candidates(db)
    feats = {(f.symbol, f.timeframe, f.timestamp): f for f in db.query(models.Feature).all()}
    labels = db.query(models.Label).all()
    for s in db.query(models.StrategyCandidate).all():
        trades = []
        for l in labels:
            if l.expiry_seconds != s.expiry_seconds or l.result_high == 'unsupported':
                continue
            f = feats.get((l.symbol, l.timeframe, l.timestamp))
            if not f:
                continue
            if s.direction == 'HIGH' and f.trend_state != 'up':
                continue
            if s.direction == 'LOW' and f.trend_state != 'down':
                continue
            result = l.result_high if s.direction == 'HIGH' else l.result_low
            trades.append((l, result))
            db.add(models.BacktestTrade(strategy_id=s.strategy_id, symbol=l.symbol, timeframe=l.timeframe, timestamp=l.timestamp, direction=s.direction, expiry_seconds=s.expiry_seconds, payout_rate=payout_rate, result=result, margin_pips=l.margin_pips))
        trade_count = len(trades)
        if trade_count == 0:
            db.add(models.BacktestRun(strategy_id=s.strategy_id, trade_count=0, win_count=0, loss_count=0, draw_count=0, win_rate=0, break_even_win_rate=1/(1+payout_rate), expected_value_per_trade=0, total_expected_value=0, max_drawdown=0, longest_losing_streak=0, profit_factor=0, average_margin_pips=0, near_zero_margin_rate=0))
            continue
        wins = sum(1 for _, r in trades if r == 'win'); losses = sum(1 for _, r in trades if r == 'loss'); draws = trade_count-wins-losses
        win_rate = wins / trade_count; loss_rate = losses / trade_count
        ev = win_rate * payout_rate - loss_rate
        pnl = [payout_rate if r == 'win' else -1.0 if r == 'loss' else 0.0 for _, r in trades]
        cum = 0.0; peak = 0.0; mdd = 0.0; ls = 0; max_ls = 0
        for x in pnl:
            cum += x; peak = max(peak, cum); mdd = max(mdd, peak-cum)
            if x < 0: ls += 1
            else: ls = 0
            max_ls = max(max_ls, ls)
        gp = sum(x for x in pnl if x > 0); gl = abs(sum(x for x in pnl if x < 0)); pf = gp/gl if gl > 0 else 0
        margins = [abs(t[0].margin_pips) for t in trades]
        nz = sum(1 for m in margins if m <= near_zero_threshold)/trade_count
        db.add(models.BacktestRun(strategy_id=s.strategy_id, trade_count=trade_count, win_count=wins, loss_count=losses, draw_count=draws, win_rate=win_rate, break_even_win_rate=1/(1+payout_rate), expected_value_per_trade=ev, total_expected_value=ev*trade_count, max_drawdown=mdd, longest_losing_streak=max_ls, profit_factor=pf, average_margin_pips=mean(margins), near_zero_margin_rate=nz))
    db.commit()


def walk_forward(db: Session, windows: int = 3, payout_rate: float = 0.8):
    db.query(models.WalkForwardRun).delete(); db.commit()
    for s in db.query(models.StrategyCandidate).all():
        rows = db.query(models.BacktestTrade).filter_by(strategy_id=s.strategy_id).order_by(models.BacktestTrade.timestamp).all()
        if len(rows) < windows:
            db.add(models.WalkForwardRun(strategy_id=s.strategy_id, pass_rate=0.0, periods=0, detail_json=json.dumps([]))); continue
        size = len(rows)//windows
        detail=[]; passed=0; periods=0
        for i in range(windows):
            seg = rows[i*size: (i+1)*size if i < windows-1 else len(rows)]
            if not seg: continue
            periods += 1
            tc=len(seg); w=sum(1 for x in seg if x.result=='win'); l=sum(1 for x in seg if x.result=='loss')
            wr=w/tc; lr=l/tc; ev=wr*payout_rate-lr
            cum=0; peak=0; mdd=0
            for x in seg:
                v = payout_rate if x.result=='win' else -1 if x.result=='loss' else 0
                cum += v; peak=max(peak,cum); mdd=max(mdd,peak-cum)
            ok = tc >= s.min_trade_count and ev > 0 and wr >= (1/(1+payout_rate)+s.required_edge) and mdd <= s.max_drawdown_limit
            if ok: passed += 1
            detail.append({"start": seg[0].timestamp.isoformat(), "end": seg[-1].timestamp.isoformat(), "trade_count": tc, "win_rate": wr, "expected_value_per_trade": ev, "max_drawdown": mdd, "pass": ok})
        pr = passed/periods if periods else 0
        db.add(models.WalkForwardRun(strategy_id=s.strategy_id, pass_rate=pr, periods=periods, detail_json=json.dumps(detail)))
    db.commit()
