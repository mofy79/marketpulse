import time
import concurrent.futures
from datetime import datetime
from flask import Flask, jsonify, render_template
import yfinance as yf
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

_cache = {}
_cache_ts = {}
CACHE_TTL = 3600  # 1 time

def cache_get(key):
    if key in _cache and time.time() - _cache_ts.get(key, 0) < CACHE_TTL:
        return _cache[key]
    return None

def cache_set(key, value):
    _cache[key] = value
    _cache_ts[key] = time.time()

SYMBOLS = {
    "us": {
        "S&P 500":     "^GSPC",
        "Nasdaq 100":  "^IXIC",
        "Dow Jones":   "^DJI",
        "Russell 2000":"^RUT",
        "VIX":         "^VIX",
    },
    "eu": {
        "Euro Stoxx 50": "^STOXX50E",
        "DAX":           "^GDAXI",
        "FTSE 100":      "^FTSE",
        "CAC 40":        "^FCHI",
    },
    "asia": {
        "Nikkei 225":  "^N225",
        "Hang Seng":   "^HSI",
        "Shanghai":    "000001.SS",
        "KOSPI":       "^KS11",
    },
    "commodities": {
        "Guld":        "GC=F",
        "Sølv":        "SI=F",
        "WTI Råolie":  "CL=F",
        "Brent":       "BZ=F",
        "Naturgas":    "NG=F",
        "Kobber":      "HG=F",
    },
    "forex": {
        "EUR/USD":  "EURUSD=X",
        "GBP/USD":  "GBPUSD=X",
        "USD/JPY":  "USDJPY=X",
        "USD/CHF":  "USDCHF=X",
        "AUD/USD":  "AUDUSD=X",
        "DXY":      "DX-Y.NYB",
    },
    "bonds": {
        "US 2Y":  "^IRX",
        "US 10Y": "^TNX",
        "US 30Y": "^TYX",
    },
    "futures": {
        "S&P 500 Future":  "ES=F",
        "Nasdaq Future":   "NQ=F",
        "Dow Future":      "YM=F",
        "Russell Future":  "RTY=F",
    },
    "indicators": {
        "Halvledere (SMH)":        "SMH",
        "High Yield (HYG)":        "HYG",
        "Lange Obligationer (TLT)":"TLT",
        "Skibstrafik (BDRY)":      "BDRY",
    },
    "sectors": {
        "Teknologi":        "XLK",
        "Energi":           "XLE",
        "Finans":           "XLF",
        "Sundhed":          "XLV",
        "Industri":         "XLI",
        "Forbrug (vækst)":  "XLY",
        "Forbrug (defensiv)":"XLP",
        "Forsyning":        "XLU",
        "Ejendomme":        "XLRE",
        "Materialer":       "XLB",
        "Kommunikation":    "XLC",
    },
}


def fetch_ticker(ticker: str):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="5d")
        if df.empty or len(df) < 2:
            return None
        df = df.dropna(subset=["Close"])
        if len(df) < 2:
            return None
        cur  = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        wk   = float(df["Close"].iloc[0])
        chg  = cur - prev
        pct  = (chg / prev) * 100
        wpct = ((cur - wk) / wk) * 100
        return {
            "price":      round(cur, 4),
            "change":     round(chg, 4),
            "change_pct": round(pct, 2),
            "week_pct":   round(wpct, 2),
            "direction":  "up" if chg > 0 else ("down" if chg < 0 else "flat"),
            "history":    [round(float(x), 4) for x in df["Close"].tail(5).tolist()],
            "ticker":     ticker,
        }
    except Exception as e:
        print(f"  ✗ {ticker}: {e}")
        return None


def fetch_all_markets() -> dict:
    cached = cache_get("markets")
    if cached:
        return cached

    items = []
    for cat, syms in SYMBOLS.items():
        for name, ticker in syms.items():
            items.append((cat, name, ticker))

    result = {cat: {} for cat in SYMBOLS}

    def _fetch(item):
        cat, name, ticker = item
        return cat, name, fetch_ticker(ticker)

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for cat, name, data in ex.map(_fetch, items):
            if data:
                result[cat][name] = data

    cache_set("markets", result)
    return result


def fetch_crypto() -> dict:
    cached = cache_get("crypto")
    if cached:
        return cached
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 12,
                "page": 1,
                "sparkline": False,
                "price_change_percentage": "24h,7d",
            },
            timeout=15,
        )
        result = {}
        for c in r.json():
            result[c["symbol"].upper()] = {
                "name":       c["name"],
                "price":      c["current_price"],
                "change_pct": round(c.get("price_change_percentage_24h") or 0, 2),
                "week_pct":   round(c.get("price_change_percentage_7d_in_currency") or 0, 2),
                "market_cap": c["market_cap"],
                "volume":     c["total_volume"],
                "direction":  "up" if (c.get("price_change_percentage_24h") or 0) > 0 else "down",
                "image":      c["image"],
                "rank":       c["market_cap_rank"],
            }
        cache_set("crypto", result)
        return result
    except Exception as e:
        print(f"Crypto error: {e}")
        return {}


def fetch_fear_greed() -> dict:
    cached = cache_get("fg")
    if cached:
        return cached
    try:
        data = requests.get("https://api.alternative.me/fng/?limit=2", timeout=10).json()["data"]
        result = {
            "today":     {"value": int(data[0]["value"]), "label": data[0]["value_classification"]},
            "yesterday": {"value": int(data[1]["value"]), "label": data[1]["value_classification"]} if len(data) > 1 else None,
        }
        cache_set("fg", result)
        return result
    except:
        return {"today": {"value": 50, "label": "Neutral"}, "yesterday": None}


def fetch_economic_calendar():
    cached = cache_get("calendar")
    if cached:
        return cached
    try:
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            timeout=10, headers={"User-Agent": "Mozilla/5.0"}
        )
        events = r.json()
        filtered = [e for e in events if
                    e.get("impact") in ("High", "Medium") and
                    e.get("country") in ("USD", "EUR", "GBP", "JPY", "CNY")]
        filtered.sort(key=lambda x: x.get("date", ""))
        cache_set("calendar", filtered)
        return filtered
    except Exception as e:
        print(f"Calendar error: {e}")
        return []


def fetch_btc_dominance():
    cached = cache_get("btc_dom")
    if cached:
        return cached
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        d = r.json()["data"]
        result = {
            "btc":        round(d["market_cap_percentage"].get("btc", 0), 1),
            "eth":        round(d["market_cap_percentage"].get("eth", 0), 1),
            "total_mcap": d["total_market_cap"].get("usd", 0),
            "change_24h": round(d.get("market_cap_change_percentage_24h_usd", 0), 2),
        }
        cache_set("btc_dom", result)
        return result
    except Exception as e:
        print(f"BTC dominance error: {e}")
        return {}


def fetch_insider_trades():
    cached = cache_get("insider")
    if cached:
        return cached
    try:
        url = (
            "http://openinsider.com/screener?s=&o=&pl=5&ph=&ll=&lh=&fd=7&fdr=&td=0"
            "&tdr=&fdlv=&fdlh=&ddt=1&ddl=&ddh=&xs=1&vl=500&vh=&ocl=&och="
            "&sic1=-1&sicl=100&sich=9999&grp=0&nfl=&nfh=&nil=&nih=&nol=&noh="
            "&v2l=&v2h=&oc2l=&oc2h=&sortcol=0&cnt=20&page=1"
        )
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        trades = []
        table = soup.find("table", {"class": "tinytable"})
        if table:
            for row in table.find_all("tr")[1:21]:
                cols = row.find_all("td")
                if len(cols) >= 12:
                    ttype = cols[8].text.strip()
                    trades.append({
                        "date":    cols[1].text.strip(),
                        "ticker":  cols[3].text.strip(),
                        "company": cols[4].text.strip()[:35],
                        "insider": cols[5].text.strip()[:25],
                        "title":   cols[6].text.strip()[:20],
                        "type":    ttype,
                        "price":   cols[9].text.strip(),
                        "qty":     cols[10].text.strip(),
                        "value":   cols[11].text.strip(),
                        "is_buy":  "P" in ttype or "Buy" in ttype,
                    })
        cache_set("insider", trades)
        return trades
    except Exception as e:
        print(f"Insider error: {e}")
        return []


def generate_analysis(markets: dict, crypto: dict, fg: dict) -> dict:
    signals = []
    buy_assets = []
    sell_assets = []

    def mget(cat, name):
        return markets.get(cat, {}).get(name, {})

    vix_val = (mget("us", "VIX") or {}).get("price", 20) or 20
    if vix_val > 30:
        signals.append({"icon": "⚠️", "text": f"VIX meget høj ({vix_val:.1f}) — markedet priser høj risiko ind", "type": "bearish"})
    elif vix_val > 20:
        signals.append({"icon": "📊", "text": f"VIX forhøjet ({vix_val:.1f}) — usikkerhed er til stede", "type": "neutral"})
    else:
        signals.append({"icon": "✅", "text": f"VIX lav ({vix_val:.1f}) — institutioner hedger ikke, roligt marked", "type": "bullish"})

    sp = mget("us", "S&P 500")
    if sp:
        wpct = sp.get("week_pct", 0)
        if wpct > 2:
            signals.append({"icon": "📈", "text": f"S&P 500 stærk uge (+{wpct:.1f}%) — momentum er bullish", "type": "bullish"})
            buy_assets.append("S&P 500 (SPY/VOO)")
        elif wpct < -2:
            signals.append({"icon": "📉", "text": f"S&P 500 svag uge ({wpct:.1f}%) — sælgere har kontrollen", "type": "bearish"})
            sell_assets.append("Aktieeksponering (reducer)")

    gold = mget("commodities", "Guld")
    if gold:
        wpct = gold.get("week_pct", 0)
        if wpct > 1.5:
            signals.append({"icon": "🥇", "text": f"Guld op +{wpct:.1f}% — institutioner søger safe haven, risk-off", "type": "risk-off"})
            buy_assets.append("Guld (GLD/IAU)")
        elif wpct < -1.5:
            signals.append({"icon": "🥇", "text": f"Guld svagt ({wpct:.1f}%) — risk-on dominerer, kapital ud af safe haven", "type": "bullish"})

    oil = mget("commodities", "WTI Råolie")
    if oil:
        wpct = oil.get("week_pct", 0)
        if wpct > 3:
            signals.append({"icon": "🛢️", "text": f"Olie +{wpct:.1f}% — energisektoren attraktiv, overvej XLE/OXY", "type": "bullish"})
            buy_assets.append("Energi ETF (XLE)")
        elif wpct < -3:
            signals.append({"icon": "🛢️", "text": f"Olie svagt ({wpct:.1f}%) — deflationært pres, reducer energi", "type": "bearish"})

    dxy = mget("forex", "DXY")
    if dxy:
        wpct = dxy.get("week_pct", 0)
        if wpct > 1:
            signals.append({"icon": "💵", "text": f"Dollar styrkes (+{wpct:.1f}%) — pres på EM, råvarer og guld", "type": "mixed"})
        elif wpct < -1:
            signals.append({"icon": "💵", "text": f"Dollar svækkes ({wpct:.1f}%) — guld & råvarer begunstiget", "type": "bullish"})
            buy_assets.append("Råvarer/Guld (svag dollar)")

    t10 = mget("bonds", "US 10Y")
    if t10:
        price = t10.get("price", 0)
        wpct  = t10.get("week_pct", 0)
        if wpct > 5:
            signals.append({"icon": "📋", "text": f"10Y rente stiger kraftigt ({price:.2f}%) — pres på aktie-valuering", "type": "bearish"})
        elif wpct < -5:
            signals.append({"icon": "📋", "text": f"10Y rente falder ({price:.2f}%) — positivt for aktier og vækst", "type": "bullish"})
            buy_assets.append("Vækstaktier / Nasdaq")

    fg_val = (fg.get("today") or {}).get("value", 50)
    if fg_val < 25:
        signals.append({"icon": "😱", "text": f"Ekstrem frygt ({fg_val}) — historisk er dette en god købsmulighed", "type": "contrarian-buy"})
        buy_assets.append("Bred markedseksponering (QQQ/SPY)")
    elif fg_val > 75:
        signals.append({"icon": "🤑", "text": f"Ekstrem grådighed ({fg_val}) — overvej at tage profit og reducere risiko", "type": "caution"})
        sell_assets.append("Reducer aktieeksponering (profit-taking)")

    btc = crypto.get("BTC", {})
    if btc:
        wpct = btc.get("week_pct", 0)
        if wpct > 10:
            signals.append({"icon": "₿", "text": f"Bitcoin +{wpct:.1f}% uge — crypto momentum stærkt, risk-on", "type": "bullish"})
            buy_assets.append("Bitcoin / Crypto (BTC/ETH)")
        elif wpct < -10:
            signals.append({"icon": "₿", "text": f"Bitcoin {wpct:.1f}% — crypto under salgspres", "type": "bearish"})

    nasdaq = mget("eu", "DAX")
    if nasdaq and nasdaq.get("week_pct", 0) > 2:
        buy_assets.append("Europa (DAX/EWG)")

    # Yield curve
    t2_price  = (mget("bonds", "US 2Y")  or {}).get("price", 0) or 0
    t10_price = (mget("bonds", "US 10Y") or {}).get("price", 0) or 0
    t30_price = (mget("bonds", "US 30Y") or {}).get("price", 0) or 0
    spread_2_10 = round(t10_price - t2_price, 2) if t2_price and t10_price else None
    if spread_2_10 is not None:
        if spread_2_10 < 0:
            signals.append({"icon": "🔴", "text": f"Rentekurven INVERTERET (spread: {spread_2_10:.2f}%) — 2Y ({t2_price:.2f}%) > 10Y ({t10_price:.2f}%). Dette er historisk det stærkeste recession-signal.", "type": "bearish"})
        elif spread_2_10 < 0.3:
            signals.append({"icon": "🟡", "text": f"Rentekurven meget flad (spread: {spread_2_10:.2f}%) — markedet er usikker på fremtidig vækst.", "type": "neutral"})
        else:
            signals.append({"icon": "🟢", "text": f"Rentekurven normal (spread: +{spread_2_10:.2f}%) — 10Y ({t10_price:.2f}%) over 2Y ({t2_price:.2f}%). Sundt tegn.", "type": "bullish"})

    bull  = sum(1 for s in signals if s["type"] in ("bullish", "contrarian-buy"))
    bear  = sum(1 for s in signals if s["type"] in ("bearish", "caution"))
    score = bull - bear

    sp_day = (mget("us", "S&P 500") or {}).get("change_pct", 0) or 0
    sp_week = (mget("us", "S&P 500") or {}).get("week_pct", 0) or 0
    gold_week = (mget("commodities", "Guld") or {}).get("week_pct", 0) or 0
    btc_week = (crypto.get("BTC") or {}).get("week_pct", 0) or 0

    if score >= 2:
        overall = "BULLISH"
        recommendation = (
            "Markedet ser fornuftigt ud lige nu. De fleste signaler peger opad, og de store professionelle investorer "
            "er ikke i panik-mode. Det betyder ikke at du skal kaste alt i markedet, men det er ikke et tidspunkt "
            "hvor du behøver at sidde på hænderne. Hold øje med dine eksisterende positioner og overvej om du "
            "mangler eksponering mod de aktiver der klarer sig bedst denne uge."
        )
        summary = (
            f"S&P 500 er {'steget' if sp_week > 0 else 'faldet'} {abs(sp_week):.1f}% denne uge. "
            f"Guld er {'op' if gold_week > 0 else 'ned'} {abs(gold_week):.1f}%. "
            f"Bitcoin {'stiger' if btc_week > 0 else 'falder'} {abs(btc_week):.1f}% på ugebasis. "
            f"Frygts-indekset viser {fg_val} — {'investorerne er nervøse, hvilket historisk er et godt tegn for contrarian-investorer' if fg_val < 40 else 'markedet er relativt roligt'}."
        )
    elif score <= -2:
        overall = "BEARISH"
        recommendation = (
            "Der er røde flag i markedet nu. De professionelle investorer reducerer risiko, og flere signaler "
            "peger nedad. Det er ikke nødvendigvis panik — men det er et tidspunkt hvor du bør tænke dig om. "
            "Overvej om du har for meget eksponering mod risikofyldte aktiver, og om det giver mening at "
            "have lidt mere cash eller guld som beskyttelse."
        )
        summary = (
            f"S&P 500 er {'steget' if sp_week > 0 else 'faldet'} {abs(sp_week):.1f}% denne uge. "
            f"Guld er {'op' if gold_week > 0 else 'ned'} {abs(gold_week):.1f}% — {'investorer søger sikkerhed' if gold_week > 0 else 'selv safe haven aktiver er under pres'}. "
            f"Bitcoin {'stiger' if btc_week > 0 else 'falder'} {abs(btc_week):.1f}% på ugebasis. "
            f"Frygt-indekset er på {fg_val} — {'ekstrem frygt i markedet' if fg_val < 25 else 'forhøjet nervøsitet blandt investorer'}."
        )
    else:
        overall = "NEUTRAL"
        recommendation = (
            "Markedet sender blandede signaler — der er hverken stærke grunde til at købe aggressivt "
            "eller til at sælge ud. Det bedste du kan gøre er at holde din nuværende strategi og undgå "
            "at reagere impulsivt på daglige udsving. Vent på et klarere signal inden du foretager "
            "større ændringer i din portefølje."
        )
        summary = (
            f"S&P 500 er {'steget' if sp_week > 0 else 'faldet'} {abs(sp_week):.1f}% denne uge — hverken imponerende eller alarmerende. "
            f"Guld er {'op' if gold_week > 0 else 'ned'} {abs(gold_week):.1f}%. "
            f"Bitcoin {'stiger' if btc_week > 0 else 'falder'} {abs(btc_week):.1f}% på ugebasis. "
            f"Frygt-indekset viser {fg_val} ({fg.get('today', {}).get('label', 'Neutral')}) — markedet er afventende."
        )

    return {
        "overall":        overall,
        "recommendation": recommendation,
        "summary":        summary,
        "signals":        signals,
        "buy_assets":     list(dict.fromkeys(buy_assets)),
        "sell_assets":    list(dict.fromkeys(sell_assets)),
        "bull_count":     bull,
        "bear_count":     bear,
        "score":          score,
        "yield_curve": {
            "t2":       round(t2_price, 2),
            "t10":      round(t10_price, 2),
            "t30":      round(t30_price, 2),
            "spread":   spread_2_10,
            "inverted": spread_2_10 < 0 if spread_2_10 is not None else False,
        },
    }


def generate_indicators(markets):
    """Early warning indicator signals — leading economic indicators"""
    indicators = []
    total_sc = 0
    max_sc   = 0

    def mget(cat, name):
        return (markets.get(cat, {}).get(name) or {})

    def sig_from_wpct(wpct, th_red, th_yellow, th_green_y, th_green, invert=False):
        v = -wpct if invert else wpct
        if v >= th_green:   return ("green",  "Positivt",  2)
        if v >= th_green_y: return ("green",  "OK",        1)
        if v >= th_yellow:  return ("neutral","Neutral",   0)
        if v >= th_red:     return ("yellow", "Forsigtig",-1)
        return                     ("red",    "Advarsel", -2)

    def add(ind, sc):
        nonlocal total_sc, max_sc
        indicators.append(ind)
        total_sc += sc
        max_sc   += 2

    # ── 1. Kobber ──────────────────────────────────────────────────
    copper = mget("commodities", "Kobber")
    if copper:
        wpct = copper.get("week_pct", 0) or 0
        sig, lbl, sc = sig_from_wpct(wpct, -4, -1.5, 0, 2)
        expl = (
            f"Kobber faldt {abs(wpct):.1f}% — svækkende global industriefterspørgsel. Institutioner sælger cykliske aktier."
            if wpct < -3 else
            f"Kobber let svagt ({wpct:.1f}%) — mild advarsel om aftagende aktivitet."
            if wpct < -1 else
            f"Kobber stiger ({wpct:.1f}%) — stærk industriefterspørgsel, positivt for global vækst og cykliske aktier."
            if wpct > 2 else
            "Kobber er stabilt. Ingen klar retning på industriefterspørgsel endnu."
        )
        add({"id":"copper","name":"Kobber","subtitle":"Dr. Copper · global industriefterspørgsel",
             "price": copper.get("price",0), "change_pct": copper.get("change_pct",0),
             "week_pct":wpct,"signal":sig,"label":lbl,"explanation":expl,"icon":"🏭"}, sc)

    # ── 2. Kobber/Guld ratio ────────────────────────────────────────
    gold   = mget("commodities", "Guld")
    silver = mget("commodities", "Sølv")
    if copper and gold:
        diff = round((copper.get("week_pct",0) or 0) - (gold.get("week_pct",0) or 0), 2)
        sig, lbl, sc = sig_from_wpct(diff, -4, -1, 1, 3)
        expl = (
            "Kobber underperformer guld kraftigt — institutioner roterer til safe haven. Recession-frygt øges."
            if diff < -3 else
            "Guld klarer sig bedre end kobber — forsigtig rotation mod sikkerhed, optimismen daler."
            if diff < 0 else
            f"Kobber (+{diff:.1f}% rel.) outperformer guld — risk-on, optimisme om global vækst dominerer."
        )
        add({"id":"cu_au","name":"Kobber vs. Guld","subtitle":"Vækstoptimisme vs. safe haven",
             "price": None,"change_pct":diff,"week_pct":diff,
             "signal":sig,"label":lbl,"explanation":expl,"icon":"⚖️","value_str":f"{diff:+.1f}% rel."}, sc)

    # ── 3. Guld/Sølv ratio ─────────────────────────────────────────
    if gold and silver:
        gp = gold.get("price",1) or 1
        sp2 = silver.get("price",1) or 1
        ratio = round(gp / sp2, 1)
        if   ratio > 90: sig,lbl,sc = "red",   "Advarsel",  -2; expl=f"Ratio meget høj ({ratio:.0f}) — sølv (industrimetal) ekstremt svagt vs guld. Industriel recession-frygt."
        elif ratio > 80: sig,lbl,sc = "yellow", "Forsigtig", -1; expl=f"Ratio forhøjet ({ratio:.0f}) — markedet favoriserer guld/sikkerhed over industrimetaller."
        elif ratio > 65: sig,lbl,sc = "neutral","Neutral",    0; expl=f"Ratio normal ({ratio:.0f}) — normal balance mellem industri og sikkerhed."
        else:            sig,lbl,sc = "green",  "Positivt",   1; expl=f"Ratio lav ({ratio:.0f}) — sølv stærkt, industriefterspørgsel god."
        add({"id":"au_ag","name":"Guld/Sølv Ratio","subtitle":"Safe haven vs. industrimetal",
             "price":None,"change_pct":0,"week_pct":0,
             "signal":sig,"label":lbl,"explanation":expl,"icon":"🥇","value_str":f"{ratio:.0f}"}, sc)

    # ── 4. Halvledere (SMH) ────────────────────────────────────────
    smh = mget("indicators", "Halvledere (SMH)")
    if smh:
        wpct = smh.get("week_pct",0) or 0
        sig, lbl, sc = sig_from_wpct(wpct, -5, -2, 0, 3)
        expl = (
            f"Halvledere ned {abs(wpct):.1f}% — tech-industrien bremser op. Institutioner sælger chip-eksponering."
            if wpct < -4 else
            f"Halvledere svagt ({wpct:.1f}%) — forsigtig rotation ud af chip-sektoren."
            if wpct < -1 else
            f"Halvledere stærke ({wpct:.1f}%) — AI og tech-demand høj. Bullish for Nasdaq og vækstaktier."
            if wpct > 2 else
            "Halvledere stable. Ingen klart signal fra tech og AI-demand."
        )
        add({"id":"smh","name":"Halvledere","subtitle":"SMH · AI & chip-efterspørgsel",
             "price":smh.get("price",0),"change_pct":smh.get("change_pct",0),
             "week_pct":wpct,"signal":sig,"label":lbl,"explanation":expl,"icon":"💾"}, sc)

    # ── 5. High Yield kreditmarked (HYG) ───────────────────────────
    hyg = mget("indicators", "High Yield (HYG)")
    if hyg:
        wpct = hyg.get("week_pct",0) or 0
        sig, lbl, sc = sig_from_wpct(wpct, -3, -1, 0, 1.5)
        expl = (
            f"HYG ned {abs(wpct):.1f}% — kreditmarkederne strammer. Institutioner frygter defaults og sælger junk bonds. Earlywarning."
            if wpct < -2 else
            f"HYG let svagt ({wpct:.1f}%) — mild stress i kreditmarkedet, hold øje."
            if wpct < -0.5 else
            f"HYG op {wpct:.1f}% — kreditmarkedet er sundt, ingen stress tegn, godt for aktier."
            if wpct > 1 else
            "High yield obligationer stabile. Kreditmarkedet normalt."
        )
        add({"id":"hyg","name":"Junk Bonds (HYG)","subtitle":"Kreditstress · risiko for defaults",
             "price":hyg.get("price",0),"change_pct":hyg.get("change_pct",0),
             "week_pct":wpct,"signal":sig,"label":lbl,"explanation":expl,"icon":"💳"}, sc)

    # ── 6. Skibstrafik (BDRY) ──────────────────────────────────────
    bdry = mget("indicators", "Skibstrafik (BDRY)")
    if bdry:
        wpct = bdry.get("week_pct",0) or 0
        sig, lbl, sc = sig_from_wpct(wpct, -8, -3, 0, 4)
        expl = (
            f"Skibstrafik ned {abs(wpct):.1f}% — global handel bremser kraftigt. Et af de tidligste recession-signaler."
            if wpct < -6 else
            f"Skibstrafik svagt ({wpct:.1f}%) — global handel er aftagende, råvareefterspørgsel falder."
            if wpct < -2 else
            f"Skibstrafik stærk ({wpct:.1f}%) — global efterspørgsel på råvarer og gods stiger. Positivt."
            if wpct > 4 else
            "Skibstrafik stabil. Global handel bevæger sig normalt."
        )
        add({"id":"bdry","name":"Skibstrafik","subtitle":"BDRY · Baltic Dry Index proxy",
             "price":bdry.get("price",0),"change_pct":bdry.get("change_pct",0),
             "week_pct":wpct,"signal":sig,"label":lbl,"explanation":expl,"icon":"🚢"}, sc)

    # ── 7. Flight to Safety (TLT) ──────────────────────────────────
    tlt = mget("indicators", "Lange Obligationer (TLT)")
    if tlt:
        wpct = tlt.get("week_pct",0) or 0
        # TLT rising = flight to safety = risk-off = bearish signal
        sig, lbl, sc = sig_from_wpct(wpct, 3, 1, -1, -3, invert=True)
        expl = (
            f"TLT op {wpct:.1f}% — institutioner søger sikkerhed i obligationer massivt. Stærkt bearish signal for risiko-aktiver."
            if wpct > 3 else
            f"Let stigning i obligationsefterspørgsel ({wpct:.1f}%) — forsigtig rotation mod sikkerhed."
            if wpct > 1 else
            f"TLT ned {abs(wpct):.1f}% — kapital roterer fra obligationer til aktier. Bullish for risiko-aktiver."
            if wpct < -2 else
            "Lange obligationer stabile. Ingen extrem flight to safety."
        )
        add({"id":"tlt","name":"Flight to Safety","subtitle":"TLT · lange US statsobligationer",
             "price":tlt.get("price",0),"change_pct":tlt.get("change_pct",0),
             "week_pct":wpct,"signal":sig,"label":lbl,"explanation":expl,"icon":"🛡️"}, sc)

    # ── 8. Rentekurven (Yield Curve) ───────────────────────────────
    t2  = (mget("bonds","US 2Y")  or {}).get("price",0) or 0
    t10 = (mget("bonds","US 10Y") or {}).get("price",0) or 0
    if t2 and t10:
        spread = round(t10 - t2, 2)
        if   spread < -0.5: sig,lbl,sc="red",   "Inverteret",  -2; expl=f"Rentekurven kraftigt inverteret ({spread:.2f}%) — historisk stærkeste recession-signal. Slår typisk igennem 12-18 mdr. efter."
        elif spread < 0:    sig,lbl,sc="yellow", "Let inverteret",-1; expl=f"Let inverteret ({spread:.2f}%) — 2Y rente over 10Y. Mild advarsel."
        elif spread < 0.5:  sig,lbl,sc="neutral","Flad",         0; expl=f"Rentekurven meget flad ({spread:.2f}%) — normaliserer sig, men ingen klar vækstforventning."
        else:               sig,lbl,sc="green",  "Normal",       1; expl=f"Rentekurven sund (+{spread:.2f}%) — 10Y over 2Y. Markedet forventer fremtidig vækst."
        add({"id":"yc","name":"Rentekurven","subtitle":"US 10Y minus 2Y — recession-barometer",
             "price":None,"change_pct":spread,"week_pct":0,
             "signal":sig,"label":lbl,"explanation":expl,"icon":"📈","value_str":f"{spread:+.2f}%"}, sc)

    # ── 9. VIX ────────────────────────────────────────────────────
    vix = mget("us","VIX")
    if vix:
        v = vix.get("price",20) or 20
        if   v > 30: sig,lbl,sc="red",   "Extrem frygt",-2; expl=f"VIX {v:.1f} — markedet priser extrem usikkerhed. Institutioner hedger aggressivt med put-optioner."
        elif v > 22: sig,lbl,sc="yellow","Forhøjet",    -1; expl=f"VIX {v:.1f} — over historisk gennemsnit (~20). Usikkerhed til stede, hold øje."
        elif v < 14: sig,lbl,sc="green", "Roligt",       1; expl=f"VIX {v:.1f} — meget lavt. Institutioner hedger ikke. Godebetingelser for bull market."
        else:        sig,lbl,sc="neutral","Normal",       0; expl=f"VIX {v:.1f} — inden for normalt range. Ingen alarmer."
        add({"id":"vix","name":"VIX","subtitle":"Markedsangst · hedge-barometer",
             "price":v,"change_pct":vix.get("change_pct",0),"week_pct":vix.get("week_pct",0),
             "signal":sig,"label":lbl,"explanation":expl,"icon":"⚡","value_str":f"{v:.1f}"}, sc)

    # ── 10. Small vs Large cap (risk appetite) ────────────────────
    rut = mget("us","Russell 2000")
    sp500 = mget("us","S&P 500")
    if rut and sp500:
        diff = round((rut.get("week_pct",0) or 0) - (sp500.get("week_pct",0) or 0), 2)
        if   diff >  1.5: sig,lbl,sc="green", "Risk-On",  2; expl=f"Småaktier outperformer (+{diff:.1f}% rel.) — klassisk risk-on. Investorer tager risiko, bullish stemning."
        elif diff >  0:   sig,lbl,sc="neutral","Let Risk-On",0; expl="Småaktier marginalt stærkere. Svagt risk-on signal."
        elif diff > -1.5: sig,lbl,sc="yellow","Risk-Off", -1; expl=f"Storkap outperformer ({diff:.1f}% rel.) — forsigtig rotation mod kvalitetsaktier."
        else:             sig,lbl,sc="red",   "Risk-Off", -2; expl=f"Storkap outperformer kraftigt ({diff:.1f}% rel.) — flight to quality. Institutioner søger stabilitet."
        add({"id":"rut_sp","name":"Lille vs. Stor Kap","subtitle":"Russell 2000 vs. S&P 500",
             "price":None,"change_pct":diff,"week_pct":diff,
             "signal":sig,"label":lbl,"explanation":expl,"icon":"🏢","value_str":f"{diff:+.1f}% rel."}, sc)

    # ── 11. Råolie ───────────────────────────────────────────────
    oil = mget("commodities","WTI Råolie")
    if oil:
        wpct = oil.get("week_pct",0) or 0
        if   wpct < -5: sig,lbl,sc="red",   "Advarsel",  -1; expl=f"Olie ned {abs(wpct):.1f}% — kraftigt fald signalerer svækkende global efterspørgsel."
        elif wpct < -2: sig,lbl,sc="yellow","Svagt",      0; expl=f"Olie svagt ({wpct:.1f}%) — mild nedgang i energiefterspørgsel."
        elif wpct >  5: sig,lbl,sc="yellow","Inflationspres",0; expl=f"Olie stiger kraftigt ({wpct:.1f}%) — kan give inflationspres, dyrere produktion."
        else:           sig,lbl,sc="neutral","Stabilt",    0; expl="Olieprisen stabil. Ingen dramatisk ændring i energiefterspørgsel."
        add({"id":"oil","name":"Råolie (WTI)","subtitle":"Energiefterspørgsel · inflationsbarometer",
             "price":oil.get("price",0),"change_pct":oil.get("change_pct",0),
             "week_pct":wpct,"signal":sig,"label":lbl,"explanation":expl,"icon":"🛢️"}, sc)

    # ── Health score 0–100 ────────────────────────────────────────
    health = round(((total_sc + max_sc) / max(2 * max_sc, 1)) * 100) if max_sc else 50

    return {"indicators": indicators, "health_score": health,
            "total_score": total_sc, "max_score": max_sc}


@app.route("/")
def index():
    return render_template("marketpulse.html")


@app.route("/api/data")
def api_data():
    markets   = fetch_all_markets()
    crypto    = fetch_crypto()
    fg        = fetch_fear_greed()
    insider   = fetch_insider_trades()
    calendar  = fetch_economic_calendar()
    btc_dom   = fetch_btc_dominance()
    analysis  = generate_analysis(markets, crypto, fg)
    early_warn = generate_indicators(markets)
    return jsonify({
        "early_warnings": early_warn,
        "markets":        markets,
        "crypto":         crypto,
        "fear_greed":     fg,
        "insider_trades": insider,
        "calendar":       calendar,
        "btc_dominance":  btc_dom,
        "analysis":       analysis,
        "updated":        datetime.now().strftime("%d. %b %Y kl. %H:%M"),
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print("\nMarketPulse starter...")
    print(f"Abn: http://localhost:{port}\n")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
