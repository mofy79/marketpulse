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


def fetch_insider_trades() -> list:
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
    }


@app.route("/")
def index():
    return render_template("marketpulse.html")


@app.route("/api/data")
def api_data():
    markets  = fetch_all_markets()
    crypto   = fetch_crypto()
    fg       = fetch_fear_greed()
    insider  = fetch_insider_trades()
    analysis = generate_analysis(markets, crypto, fg)
    return jsonify({
        "markets":       markets,
        "crypto":        crypto,
        "fear_greed":    fg,
        "insider_trades": insider,
        "analysis":      analysis,
        "updated":       datetime.now().strftime("%d. %b %Y kl. %H:%M"),
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print("\nMarketPulse starter...")
    print(f"Abn: http://localhost:{port}\n")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
