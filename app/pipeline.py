import json
from collections import defaultdict
from datetime import timedelta
from statistics import mean
from sqlalchemy.orm import Session
from . import models

PIP_MULT=10000
TF_DELTA={"M1":timedelta(minutes=1),"M5":timedelta(minutes=5),"M15":timedelta(minutes=15)}

OPS={"==":lambda a,b:a==b,"!=":lambda a,b:a!=b,">":lambda a,b:a>b,">=":lambda a,b:a>=b,"<":lambda a,b:a<b,"<=":lambda a,b:a<=b,"in":lambda a,b:a in b,"not in":lambda a,b:a not in b}

def parse_conditions(s):
    if not s: return []
    if s.strip().startswith('['): return json.loads(s)
    return [x.strip() for x in s.split('&&') if x.strip()]

def eval_condition(expr, ctx):
    for op in [" not in "," in ",">=","<=","==","!=",">","<"]:
        if op.strip() in [">=","<=","==","!=",">","<"] and op not in expr: continue
        if op in expr:
            l,r=[x.strip() for x in expr.split(op,1)]
            lv=ctx.get(l)
            rv = json.loads(r.lower().replace("'",'"')) if r.lower() in ('true','false') or r.startswith('[') or r.startswith('"') or r.startswith("'") else (float(r) if r.replace('.','',1).replace('-','',1).isdigit() else r)
            return OPS[op.strip()](lv,rv)
    return False

def match_conditions(required, blocked, ctx):
    return all(eval_condition(c,ctx) for c in parse_conditions(required)) and not any(eval_condition(c,ctx) for c in parse_conditions(blocked))

def resample_candles(db, source_timeframe='M1', target_timeframe='M5'):
    group=5 if target_timeframe=='M5' else 15
    rows=db.query(models.RawCandle).filter_by(timeframe=source_timeframe).order_by(models.RawCandle.symbol,models.RawCandle.bar_start_time).all()
    by=defaultdict(list)
    for r in rows: by[r.symbol].append(r)
    created=dropped=0
    for symbol,arr in by.items():
        full=len(arr)//group; dropped += len(arr)%group
        for i in range(full):
            ck=arr[i*group:(i+1)*group]; st=ck[0].bar_start_time; et=st+TF_DELTA[target_timeframe]
            if db.query(models.RawCandle).filter_by(symbol=symbol,timeframe=target_timeframe,bar_start_time=st).first(): continue
            db.add(models.RawCandle(symbol=symbol,timeframe=target_timeframe,timestamp=st,bar_start_time=st,bar_end_time=et,source_timeframe=source_timeframe,generated_from='resample',open=ck[0].open,high=max(x.high for x in ck),low=min(x.low for x in ck),close=ck[-1].close,volume=sum(x.volume for x in ck))); created +=1
    db.commit(); return {"created":created,"dropped":dropped}

def generate_features(db,payout_rate=0.8):
    resample_candles(db,'M1','M5'); resample_candles(db,'M1','M15')
    db.query(models.Feature).delete(); db.commit()
    by=defaultdict(list)
    for c in db.query(models.RawCandle).order_by(models.RawCandle.symbol,models.RawCandle.timeframe,models.RawCandle.bar_start_time): by[(c.symbol,c.timeframe)].append(c)
    for (sym,tf),arr in by.items():
        closes=[x.close for x in arr]
        for i,c in enumerate(arr):
            rng=max(c.high-c.low,1e-8); recent=arr[max(0,i-19):i+1]
            atr=mean([x.high-x.low for x in arr[max(0,i-13):i+1]])
            atrs=[mean([z.high-z.low for z in arr[max(0,k-13):k+1]]) for k in range(max(0,i-99),i+1)]
            atr_pct=sum(1 for v in atrs if v<=atr)/len(atrs)
            ema=mean(closes[max(0,i-4):i+1]); prev=mean(closes[max(0,i-5):i]) if i else ema; slope=ema-prev
            db.add(models.Feature(symbol=sym,timeframe=tf,timestamp=c.bar_start_time,bar_start_time=c.bar_start_time,bar_end_time=c.bar_end_time,candle_body_ratio=abs(c.close-c.open)/rng,upper_wick_ratio=(c.high-max(c.open,c.close))/rng,lower_wick_ratio=(min(c.open,c.close)-c.low)/rng,candle_direction='up' if c.close>c.open else 'down' if c.close<c.open else 'flat',consecutive_candle_direction=1,recent_high_distance=(max(x.high for x in recent)-c.close)*PIP_MULT,recent_low_distance=(c.close-min(x.low for x in recent))*PIP_MULT,atr=atr*PIP_MULT,atr_percentile=atr_pct,ema_slope=slope*PIP_MULT,trend_state='up' if slope>0 else 'down' if slope<0 else 'flat',breakout_state='inside',pullback_state='none',volatility_regime='high' if atr_pct>=0.7 else 'low' if atr_pct<=0.3 else 'mid',time_of_day=c.bar_start_time.hour,session_name='asia',payout_rate=payout_rate))
    db.commit()

def latest_confirmed_feature(db,symbol,tf,decision_time):
    return db.query(models.Feature).filter_by(symbol=symbol,timeframe=tf).filter(models.Feature.bar_end_time <= decision_time).order_by(models.Feature.bar_end_time.desc()).first()

def get_mtf_context(db,symbol,m1_candle):
    f5=latest_confirmed_feature(db,symbol,'M5',m1_candle.bar_start_time)
    f15=latest_confirmed_feature(db,symbol,'M15',m1_candle.bar_start_time)
    if not (f5 and f15): return None
    return {"trend_m5":f5.trend_state,"trend_m15":f15.trend_state,"ema_slope_m5":f5.ema_slope,"ema_slope_m15":f15.ema_slope,"volatility_regime_m5":f5.volatility_regime,"volatility_regime_m15":f15.volatility_regime,"confirmed_m5_bar_start_time":f5.bar_start_time,"confirmed_m5_bar_end_time":f5.bar_end_time,"confirmed_m15_bar_start_time":f15.bar_start_time,"confirmed_m15_bar_end_time":f15.bar_end_time}

def generate_labels(db):
    db.query(models.Label).delete(); db.commit(); expiries=[30,60,120,180]
    rows=db.query(models.RawCandle).filter_by(timeframe='M1').order_by(models.RawCandle.symbol,models.RawCandle.bar_start_time).all(); by=defaultdict(list)
    for r in rows: by[r.symbol].append(r)
    for sym,arr in by.items():
        for i,c in enumerate(arr):
            for exp in expiries:
                j= i+1 if exp==60 else next((k for k in range(i+1,len(arr)) if arr[k].bar_start_time >= c.bar_start_time+timedelta(seconds=exp)),None)
                if exp==30 or j is None:
                    db.add(models.Label(symbol=sym,timeframe='M1',timestamp=c.bar_start_time,bar_start_time=c.bar_start_time,bar_end_time=c.bar_end_time,expiry_seconds=exp,entry_price=c.close,expiry_price=c.close,result_high='unsupported',result_low='unsupported',margin_pips=0,max_adverse_excursion=0,max_favorable_excursion=0,close_distance_from_entry=0)); continue
                e=arr[j]; m=(e.close-c.close)*PIP_MULT
                db.add(models.Label(symbol=sym,timeframe='M1',timestamp=c.bar_start_time,bar_start_time=c.bar_start_time,bar_end_time=c.bar_end_time,expiry_seconds=exp,entry_price=c.close,expiry_price=e.close,result_high='win' if m>0 else 'loss' if m<0 else 'draw',result_low='win' if m<0 else 'loss' if m>0 else 'draw',margin_pips=m,max_adverse_excursion=min((x.low-c.close)*PIP_MULT for x in arr[i:j+1]),max_favorable_excursion=max((x.high-c.close)*PIP_MULT for x in arr[i:j+1]),close_distance_from_entry=m))
    db.commit()

def ensure_candidates(db):
    if db.query(models.StrategyCandidate).count(): return
    parts=[('trend_m15 == "up"','trend_m5 == "up"'),('trend_m15 == "down"','trend_m5 == "down"')]
    idx=1
    for direction in ['HIGH','LOW']:
        for exp in [60,120,180]:
            for a,b in parts:
                db.add(models.StrategyCandidate(strategy_id=f'S{idx:03d}',direction=direction,expiry_seconds=exp,required_conditions=json.dumps([a,b,'atr_percentile >= 0.3','atr_percentile <= 0.8']),blocked_conditions=json.dumps(['upper_wick_ratio > 0.3']),score_formula='dsl',min_trade_count=5,min_expected_value=0,min_walk_forward_pass_rate=0.5,max_drawdown_limit=1000,max_losing_streak_limit=10,max_near_zero_margin_rate=0.8,required_edge=0.0)); idx+=1
    db.commit()

def _metrics(results,p):
    tc=len(results); w=sum(r=='win' for r in results); l=sum(r=='loss' for r in results); d=tc-w-l; wr=w/tc if tc else 0; lr=l/tc if tc else 0; ev=wr*p-lr
    pnl=[p if r=='win' else -1 if r=='loss' else 0 for r in results]; cum=peak=mdd=0; ls=maxls=0
    for x in pnl: cum+=x; peak=max(peak,cum); mdd=max(mdd,peak-cum); ls=ls+1 if x<0 else 0; maxls=max(maxls,ls)
    return tc,w,l,d,wr,ev,mdd,maxls,pnl

def backtest(db,near_zero_threshold=0.2,payout_rate=0.8):
    db.query(models.BacktestRun).delete(); db.query(models.BacktestTrade).delete(); db.commit(); ensure_candidates(db)
    f1={(f.symbol,f.bar_start_time):f for f in db.query(models.Feature).filter_by(timeframe='M1')}
    c1={(c.symbol,c.bar_start_time):c for c in db.query(models.RawCandle).filter_by(timeframe='M1')}
    labels=db.query(models.Label).filter_by(timeframe='M1').all()
    for s in db.query(models.StrategyCandidate).all():
        res=[]; margins=[]
        for l in labels:
            if l.expiry_seconds!=s.expiry_seconds or l.result_high=='unsupported': continue
            m1=c1.get((l.symbol,l.bar_start_time)); f=f1.get((l.symbol,l.bar_start_time)); ctx=get_mtf_context(db,l.symbol,m1) if m1 else None
            if not (ctx and f): continue
            ctx.update({'atr_percentile':f.atr_percentile,'upper_wick_ratio':f.upper_wick_ratio,'candle_body_ratio':f.candle_body_ratio,'volatility_regime_m1':f.volatility_regime,'near_recent_high':f.recent_high_distance<=2})
            if not match_conditions(s.required_conditions,s.blocked_conditions,ctx): continue
            r=l.result_high if s.direction=='HIGH' else l.result_low; res.append(r); margins.append(abs(l.margin_pips))
            db.add(models.BacktestTrade(strategy_id=s.strategy_id,symbol=l.symbol,timeframe='M1',timestamp=l.bar_start_time,direction=s.direction,expiry_seconds=s.expiry_seconds,payout_rate=payout_rate,result=r,margin_pips=l.margin_pips,trend_m5=ctx['trend_m5'],trend_m15=ctx['trend_m15'],ema_slope_m5=ctx['ema_slope_m5'],ema_slope_m15=ctx['ema_slope_m15'],volatility_regime_m5=ctx['volatility_regime_m5'],volatility_regime_m15=ctx['volatility_regime_m15'],confirmed_m5_bar_start_time=ctx['confirmed_m5_bar_start_time'],confirmed_m5_bar_end_time=ctx['confirmed_m5_bar_end_time'],confirmed_m15_bar_start_time=ctx['confirmed_m15_bar_start_time'],confirmed_m15_bar_end_time=ctx['confirmed_m15_bar_end_time']))
        tc,w,l,d,wr,ev,mdd,maxls,pnl=_metrics(res,payout_rate)
        gp=sum(x for x in pnl if x>0); gl=abs(sum(x for x in pnl if x<0)); pf=gp/gl if gl else 0; nz=(sum(m<=near_zero_threshold for m in margins)/tc) if tc else 0
        db.add(models.BacktestRun(strategy_id=s.strategy_id,trade_count=tc,win_count=w,loss_count=l,draw_count=d,win_rate=wr,break_even_win_rate=1/(1+payout_rate),expected_value_per_trade=ev,total_expected_value=ev*tc,max_drawdown=mdd,longest_losing_streak=maxls,profit_factor=pf,average_margin_pips=mean(margins) if margins else 0,near_zero_margin_rate=nz))
    db.commit()

def walk_forward(db,train_window=30,test_window=10,payout_rate=0.8):
    db.query(models.WalkForwardRun).delete(); db.commit()
    for s in db.query(models.StrategyCandidate).all():
        rows=db.query(models.BacktestTrade).filter_by(strategy_id=s.strategy_id).order_by(models.BacktestTrade.timestamp).all(); i=train_window; details=[]; passed=0
        while i+test_window<=len(rows):
            seg=rows[i:i+test_window]; tc,w,l,d,wr,ev,mdd,maxls,_=_metrics([x.result for x in seg],payout_rate); ok=tc>=s.min_trade_count and ev>0 and wr>=1/(1+payout_rate)+s.required_edge and mdd<=s.max_drawdown_limit and maxls<=s.max_losing_streak_limit
            details.append({'start':seg[0].timestamp.isoformat(),'end':seg[-1].timestamp.isoformat(),'trade_count':tc,'win_rate':wr,'expected_value_per_trade':ev,'max_drawdown':mdd,'longest_losing_streak':maxls,'pass':ok}); passed += 1 if ok else 0; i += test_window
        db.add(models.WalkForwardRun(strategy_id=s.strategy_id,pass_rate=(passed/len(details) if details else 0),periods=len(details),detail_json=json.dumps(details)))
    db.commit()

def stress_test(db,payout_scenarios=(0.8,0.75,0.7)):
    out={}
    for s in db.query(models.StrategyCandidate).all():
        rs=[t.result for t in db.query(models.BacktestTrade).filter_by(strategy_id=s.strategy_id).order_by(models.BacktestTrade.timestamp)]
        _,_,_,_,_,_,mdd,_,_=_metrics(sorted(rs,key=lambda x:0 if x=='loss' else 1 if x=='draw' else 2),0.8)
        out[s.strategy_id]={'worst_case_max_drawdown':mdd,'payout_scenarios':{str(p):{'expected_value_per_trade':_metrics(rs,p)[5],'break_even_win_rate':1/(1+p)} for p in payout_scenarios}}
    return out
