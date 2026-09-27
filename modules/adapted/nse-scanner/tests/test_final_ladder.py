
import datetime
import pytz

def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone('Asia/Kolkata')
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


﻿from copy import deepcopy
import json
import sqlite3
import numpy as np
import pandas as pd
import pytest
from old_nse_hull.final_ladder.engine import selected_scores
from old_nse_hull.final_ladder.features import latest_context
from old_nse_hull.final_ladder.ledger import advance
from old_nse_hull.final_ladder.profile import CONFIG,PROFILE_ID
from old_nse_hull.final_ladder.render import daily_messages,period_message
from old_nse_hull.multi_horizon.scoring import score,HORIZONS
from scripts.build_miniapp_feed import ladder_items

CANDIDATE=dict(symbol='TEST',score=80,entry=100,entry_high=103,stop=95,target1=107.5,target2=112.5,max_stop_pct=8)
def bars(day,op=100,high=104,low=98,close=103,prior_trend=True):
    return {'TEST':dict(date=day,open=op,high=high,low=low,close=close,prev_close=100,entry_allowed=True,
        entry_blocked=False,exit_blocked=False,atr=1.,prior_10_low=104.,prior_trend=prior_trend)}
def step(path,day,b,c=(),previous=None):
    return advance(path,'Momentum Ladder',day,b,list(c),config=CONFIG,provenance=PROFILE_ID,previous_session=previous)

def test_profile_scores_only_selected_weights_and_requires_cross():
    d=pd.DataFrame([dict(symbol='A',history_sessions=400,close=110,sma50=100,sma150=90,sma200=80,
        volume_sma20=100000,volume=130000,delivery_pct=90,delivery_median60=50,
        previous_252d_high=115,rsi14=73,adx14=25,bb_width_change=.1,previous_20d_high=105,ema20=100,
        return_1m=.1,return_3m=.2,return_6m=.3,return_12m=.4,quality_window_ok=True,recent_cross=True)])
    expected=d.copy();expected['delivery_pct']=np.nan;expected['delivery_median60']=np.nan
    native=score(expected);result=selected_scores(d)
    for h in HORIZONS:assert result['score_'+h.lower()].iloc[0]==native['score_'+h.lower()].iloc[0]-18
    assert result.primary_score.iloc[0]==77 and result.qualified.iloc[0]
    d['recent_cross']=False;assert not selected_scores(d).qualified.iloc[0]
    d['quality_window_ok']=False;assert not selected_scores(d).eligible.iloc[0]

def test_features_recheck_uses_previous_completed_session():
    close=np.r_[np.full(340,100.),np.linspace(100,80,20),80.,80.,150.]
    days=pd.bdate_range('2024-01-01',periods=len(close))
    d=pd.DataFrame(dict(symbol='TEST',trade_date=days,open=close,high=close+1,low=close-1,close=close,volume=100000))
    result,calendar=latest_context(d)
    assert result.recent_cross.iloc[0]
    assert not result.prior_trend.iloc[0]
    prefix,_=latest_context(d.iloc[:-1])
    assert not prefix.recent_cross.iloc[0]

def test_pending_expiry_and_previous_trend_gate(tmp_path):
    p=tmp_path/'paper.db';step(p,'2026-01-01',{},[CANDIDATE])
    for day in ['2026-01-02','2026-01-05','2026-01-06','2026-01-07','2026-01-08']:
        s=step(p,day,bars(day,prior_trend=False));assert s['open_positions']==0
    s=step(p,'2026-01-09',bars('2026-01-09'))
    assert s['open_positions']==0 and s['pending_setups']==0

def test_trailing_after_tp1_is_next_session_and_tp2_not_exit(tmp_path):
    p=tmp_path/'paper.db';step(p,'2026-01-01',{},[CANDIDATE])
    step(p,'2026-01-02',bars('2026-01-02'))
    s=step(p,'2026-01-05',bars('2026-01-05',103,108,99,106))
    assert s['open_positions']==1 and s['positions'][0]['stop']>99
    s=step(p,'2026-01-06',bars('2026-01-06',110,118,109,117))
    assert s['open_positions']==1
    stop=s['positions'][0]['stop']
    b=bars('2026-01-07',110,113,109,112);b['TEST']['prior_10_low']=90
    s=step(p,'2026-01-07',b);assert s['positions'][0]['stop']==stop
    s=step(p,'2026-01-08',bars('2026-01-08',90,95,89,92))
    assert s['closed_positions']==1 and s['positions'][0]['exit_price']<90

def test_idempotence_session_gap_and_missing_holding_review(tmp_path):
    p=tmp_path/'paper.db';step(p,'2026-01-01',{},[CANDIDATE])
    b=bars('2026-01-02');s=step(p,'2026-01-02',b,previous='2026-01-01')
    assert step(p,'2026-01-02',b,previous='2026-01-01')==s
    changed=deepcopy(b);changed['TEST']['close']=102
    with pytest.raises(ValueError,match='inputs changed'):step(p,'2026-01-02',changed)
    with pytest.raises(ValueError,match='Missing market session'):step(p,'2026-01-06',{},previous='2026-01-05')
    s=step(p,'2026-01-05',{},previous='2026-01-02')
    assert s['positions'][0]['status']=='REVIEW' and s['open_positions']==1

def test_final_dashboard_accepts65_and_renders_watchlist():
    row=dict(symbol='TEST',discovery_score=65,hull_state='READY',close=100,primary_score=65,
             trade_levels=dict(entry_trigger=101,stop=95,target_1=110,target_2=116))
    old={'shortlist':[row]};assert not ladder_items(old)
    report={**old,'strategy_profile':PROFILE_ID,'as_of_date':'2026-09-21'}
    assert ladder_items(report)[0]['stage']=='Watch for entry'
    assert ladder_items(report)[0]['score_max']==95
    assert ladder_items(report)[0]['target2_label']=='TP2 reference'
    messages=daily_messages(report);assert 'Watch for entry' in messages[0] and 'TP1' in messages[0]
    assert 'Open TEST chart</a>' in messages[0] and 'symbol=NSE%3ATEST' in messages[0]
    assert 'Open Momentum Ladder dashboard</a>' in messages[0] and 'startapp=ladder' in messages[0]
    assert all(len(m)<3500 for m in messages)