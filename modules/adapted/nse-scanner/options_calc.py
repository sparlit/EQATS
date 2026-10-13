import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
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


import datetime
import gzip
import json
import os
import time

import requests

TOKEN = os.environ["UPSTOX_TOKEN"]
HDR = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
STRIKES_EACH_SIDE = 6

INSTR_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
CHAIN_URL = "https://api.upstox.com/v2/option/chain"


def load_fo_map():
    r = requests.get(INSTR_URL, timeout=120)
    data = json.loads(gzip.decompress(r.content))
    by_und = {}
    eq_keys = {}
    for d in data:
        seg = d.get("segment", "")
        if seg == "NSE_EQ" and d.get("instrument_type") == "EQ":
            eq_keys[d.get("trading_symbol")] = d.get("instrument_key")
        if seg == "NSE_FO" and d.get("instrument_type") == "FUT":
            name = d.get("name") or d.get("underlying_symbol")
            exp = d.get("expiry")
            if name:
                by_und.setdefault(name, set()).add(exp)
    return eq_keys, by_und


def next_month_expiry(expiries):
    today = datetime.datetime.now(IST).date()
    parsed = []
    for e in expiries:
        try:
            d = (
                datetime.datetime.fromtimestamp(e / 1000, IST).date()
                if isinstance(e, (int, float))
                else datetime.datetime.strptime(e, "%Y-%m-%d").date()
            )
            if d >= today:
                parsed.append(d)
        except Exception:
            continue
    if not parsed:
        return None
    parsed.sort()
    cur_month = parsed[0].month
    later = [d for d in parsed if d.month != cur_month]
    return (later[0] if later else parsed[-1]).isoformat()


def fetch_chain(instrument_key, expiry_date):
    for _ in range(3):
        try:
            r = requests.get(
                CHAIN_URL,
                headers=HDR,
                params={"instrument_key": instrument_key, "expiry_date": expiry_date},
                timeout=25,
            )
            if r.status_code == 200:
                return r.json().get("data", [])
        except Exception:
            pass
        time.sleep(2)
    return []


def nearest_rows(rows, spot, n):
    rows = sorted(rows, key=lambda x: abs(x.get("strike_price", 0) - spot))
    return sorted(rows[: n * 2], key=lambda x: x.get("strike_price", 0))


def build_options(hit_symbols, eq_keys, fo_map, spot_by_sym):
    out = {}
    for sym in hit_symbols:
        if sym not in fo_map or sym not in eq_keys:
            continue
        expiry = next_month_expiry(fo_map[sym])
        if not expiry:
            continue
        rows = fetch_chain(eq_keys[sym], expiry)
        if not rows:
            continue
        spot = spot_by_sym.get(sym) or rows[0].get("underlying_spot_price", 0)
        sel = nearest_rows(rows, spot, STRIKES_EACH_SIDE)
        days = (datetime.date.fromisoformat(expiry) - datetime.datetime.now(IST).date()).days
        strikes = []
        for row in sel:
            ce, pe = row.get("call_options", {}), row.get("put_options", {})
            cg, pg = ce.get("option_greeks", {}), pe.get("option_greeks", {})
            strikes.append(
                {
                    "strike": row.get("strike_price"),
                    "ce_ltp": ce.get("market_data", {}).get("ltp"),
                    "ce_iv": cg.get("iv"),
                    "ce_delta": cg.get("delta"),
                    "ce_theta": cg.get("theta"),
                    "ce_gamma": cg.get("gamma"),
                    "ce_vega": cg.get("vega"),
                    "pe_ltp": pe.get("market_data", {}).get("ltp"),
                    "pe_iv": pg.get("iv"),
                    "pe_delta": pg.get("delta"),
                    "pe_theta": pg.get("theta"),
                    "pe_gamma": pg.get("gamma"),
                    "pe_vega": pg.get("vega"),
                }
            )
        out[sym] = {"expiry": expiry, "days": days, "spot": spot, "strikes": strikes}
    return out


def write_page(opt_data):
    meta = datetime.datetime.now(IST).strftime("%d %b %Y %H:%M IST")
    sorted(opt_data.keys())
    html = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Option Calculator</title>
<style>body{font-family:Arial;background:#111;color:#eee;margin:8px;font-size:13px}
select,input{background:#222;color:#eee;border:1px solid #444;padding:6px;margin:2px;width:100%;box-sizing:border-box}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}.row>div{flex:1;min-width:110px}
label{font-size:11px;color:#999;display:block}
table{border-collapse:collapse;width:100%;margin-top:10px}
th,td{border-bottom:1px solid #333;padding:6px;text-align:left}
th{background:#1c1c1c}.g{color:#4caf50}.r{color:#f44336}.n{color:#888;font-size:11px}</style></head><body>
<h3>Option Premium + Greeks Calculator</h3><div class="n">__META__ | data: Upstox option chain, next-month expiry</div>
<div class="row"><div><label>Stock</label><select id="sym"></select></div>
<div><label>Type</label><select id="typ"><option value="ce">CALL</option><option value="pe">PUT</option></select></div>
<div><label>Strike</label><select id="strike"></select></div></div>
<div class="row"><div><label>Target move %</label><input id="tgt" type="number" value="5" step="0.5"></div>
<div><label>Days from now</label><input id="days" type="number" value="10"></div>
<div><label>Risk-free rate %</label><input id="rf" type="number" value="6.5" step="0.1"></div></div>
<table id="out"></table>
<script>
const D=__DATA__;const $=id=>document.getElementById(id);
const symSel=$("sym");Object.keys(D).sort().forEach(s=>symSel.add(new Option(s,s)));
function ncdf(x){return 0.5*(1+erf(x/Math.SQRT2))}
function erf(x){const s=x<0?-1:1;x=Math.abs(x);const a1=.254829592,a2=-.284496736,a3=1.421413741,a4=-1.453152027,a5=1.061405429,p=.3275911;
const t=1/(1+p*x);const y=1-(((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t*Math.exp(-x*x);return s*y}
function bs(S,K,T,r,sig,type){
 if(T<=0)T=0.0001;
 const d1=(Math.log(S/K)+(r+sig*sig/2)*T)/(sig*Math.sqrt(T));
 const d2=d1-sig*Math.sqrt(T);
 const Nd1=ncdf(d1),Nd2=ncdf(d2);
 let price,delta;
 if(type=="ce"){price=S*Nd1-K*Math.exp(-r*T)*Nd2;delta=Nd1;}
 else{price=K*Math.exp(-r*T)*ncdf(-d2)-S*ncdf(-d1);delta=Nd1-1;}
 const gamma=Math.exp(-d1*d1/2)/(S*sig*Math.sqrt(2*Math.PI*T));
 const vega=S*Math.exp(-d1*d1/2)/Math.sqrt(2*Math.PI)*Math.sqrt(T)/100;
 const theta=(type=="ce"
   ? (-S*Math.exp(-d1*d1/2)*sig/(2*Math.sqrt(2*Math.PI*T))-r*K*Math.exp(-r*T)*Nd2)
   : (-S*Math.exp(-d1*d1/2)*sig/(2*Math.sqrt(2*Math.PI*T))+r*K*Math.exp(-r*T)*ncdf(-d2)))/365;
 return {price,delta,gamma,vega,theta};
}
function fillStrikes(){
 const info=D[symSel.value];$("strike").innerHTML="";
 info.strikes.forEach(s=>$("strike").add(new Option(s.strike,s.strike)));
 const atm=info.strikes.reduce((a,b)=>Math.abs(b.strike-info.spot)<Math.abs(a.strike-info.spot)?b:a);
 $("strike").value=atm.strike;
 calc();
}
function calc(){
 const info=D[symSel.value];const type=$("typ").value;
 const strikeVal=Number($("strike").value);
 const row=info.strikes.reduce((a,b)=>Math.abs(b.strike-strikeVal)<Math.abs(a.strike-strikeVal)?b:a);
 const iv=(type=="ce"?row.ce_iv:row.pe_iv)/100;
 const ltp=(type=="ce"?row.ce_ltp:row.pe_ltp);
 const r=Number($("rf").value)/100;
 const T0=info.days/365;
 const now=bs(info.spot,row.strike,T0,r,iv,type);
 const tgtPct=Number($("tgt").value)/100;
 const daysFwd=Number($("days").value);
 const Tf=Math.max(info.days-daysFwd,0)/365;
 const Sf=info.spot*(1+(type=="ce"?tgtPct:-tgtPct));
 const proj=bs(Sf,row.strike,Tf,r,iv,type);
 const flat=bs(info.spot,row.strike,Tf,r,iv,type);
 const pnlProj=((proj.price-ltp)/ltp*100).toFixed(1);
 const pnlFlat=((flat.price-ltp)/ltp*100).toFixed(1);
 $("out").innerHTML=`
 <tr><th>Metric</th><th>Now</th><th>If target hit (${daysFwd}d)</th><th>If flat (${daysFwd}d, decay only)</th></tr>
 <tr><td>Spot / Target</td><td>${info.spot}</td><td>${Sf.toFixed(1)}</td><td>${info.spot}</td></tr>
 <tr><td>Premium (₹)</td><td>${ltp}</td><td class="${pnlProj>=0?'g':'r'}">${proj.price.toFixed(2)} (${pnlProj}%)</td><td class="${pnlFlat>=0?'g':'r'}">${flat.price.toFixed(2)} (${pnlFlat}%)</td></tr>
 <tr><td>Delta</td><td>${now.delta.toFixed(3)}</td><td>${proj.delta.toFixed(3)}</td><td>${flat.delta.toFixed(3)}</td></tr>
 <tr><td>Gamma</td><td>${now.gamma.toFixed(5)}</td><td>${proj.gamma.toFixed(5)}</td><td>${flat.gamma.toFixed(5)}</td></tr>
 <tr><td>Theta (₹/day)</td><td>${now.theta.toFixed(2)}</td><td>${proj.theta.toFixed(2)}</td><td>${flat.theta.toFixed(2)}</td></tr>
 <tr><td>Vega</td><td>${now.vega.toFixed(3)}</td><td>${proj.vega.toFixed(3)}</td><td>${flat.vega.toFixed(3)}</td></tr>
 <tr><td>IV used</td><td colspan="3">${(iv*100).toFixed(1)}%</td></tr>
 <tr><td>Days to expiry</td><td colspan="3">${info.days} (expiry ${info.expiry})</td></tr>
 <tr><td>Max loss if wrong</td><td colspan="3">100% of premium (₹${ltp}) if held to expiry OTM</td></tr>`;
}
symSel.onchange=fillStrikes;["typ","strike","tgt","days","rf"].forEach(id=>$(id).onchange=calc);
if(symSel.options.length)fillStrikes();
</script></body></html>"""
    html = html.replace("__DATA__", json.dumps(opt_data)).replace("__META__", meta)
    with open("docs/options.html", "w", encoding="utf-8") as f:
        f.write(html)


def main():
    hits_path = "docs/hits.json"
    if not os.path.exists(hits_path):
        print("no hits.json found, skipping options calc")
        return
    hits = json.load(open(hits_path))
    hit_symbols = sorted({h["symbol"] for h in hits if h["kind"] in ("CROSS", "NEAR")})
    spot_by_sym = {h["symbol"]: h["cur"] for h in hits if "cur" in h}
    eq_keys, fo_map = load_fo_map()
    opt_data = build_options(hit_symbols, eq_keys, fo_map, spot_by_sym)
    write_page(opt_data)
    print(f"options page built for {len(opt_data)} stocks")


main()
