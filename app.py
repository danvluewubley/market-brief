import os, json, threading, smtplib, datetime, time
from pathlib import Path
from flask import Flask, jsonify, request, render_template
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
DATA_FILE = Path("data/portfolio.json")
DELIVERY_FILE = Path("data/delivery.json")
DATA_FILE.parent.mkdir(exist_ok=True)

FMP_BASE = "https://financialmodelingprep.com/stable"


# ── API KEY HELPERS ─────────────────────────────────────────────────────────

def fmp_key():
    key = os.environ.get("FMP_API_KEY", "")
    if not key:
        raise RuntimeError("FMP_API_KEY environment variable not set")
    return key


def load_json(path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))


# ── FMP HELPERS ─────────────────────────────────────────────────────────────

def fmp_get(path: str, params: dict = {}, retries: int = 3):
    params = {**params, "apikey": fmp_key()}

    for attempt in range(retries):
        try:
            r = requests.get(
                f"{FMP_BASE}/{path}",
                params=params,
                timeout=10
            )

            if r.status_code != 200:
                raise Exception(f"FMP Error {r.status_code}: {r.text}")

            return r.json()

        except Exception:
            if attempt < retries - 1:
                time.sleep(1.5 ** attempt)
            else:
                raise


def company_profile(symbol: str):
    data = fmp_get("profile", {"symbol": symbol})

    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}


# ── FAST QUOTE ──────────────────────────────────────────────────────────────

def fast_quote(symbol: str):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        params={"interval": "1d", "range": "60d"},  # Increased range for technical indicators
        timeout=8
    )
    r.raise_for_status()

    result = r.json()["chart"]["result"][0]
    meta = result["meta"]
    price = meta.get("regularMarketPrice") or meta.get("previousClose")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose") or price

    change = round(price - prev, 2) if price and prev else 0
    change_pct = round(change / prev * 100, 2) if prev else 0
    name = meta.get("shortName") or meta.get("longName") or symbol

    # Extract historical data for technical indicators
    timestamps = result["timestamp"]
    indicators = result["indicators"]
    quote = indicators["quote"][0]

    # Get close prices for the last 20 days (enough for RSI, MACD, MA)
    close_prices = quote["close"][-20:] if len(quote["close"]) >= 20 else quote["close"]
    # Filter out None values
    close_prices = [p for p in close_prices if p is not None]

    # Calculate simple moving averages
    sma_5 = sum(close_prices[-5:]) / 5 if len(close_prices) >= 5 else None
    sma_20 = sum(close_prices) / len(close_prices) if close_prices else None

    # Calculate RSI (Relative Strength Index)
    rsi = None
    if len(close_prices) >= 14:
        deltas = [close_prices[i] - close_prices[i-1] for i in range(1, len(close_prices))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else sum(losses) / len(losses) if losses else 0
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

    # Calculate MACD (Moving Average Convergence Divergence)
    macd = None
    macd_signal = None
    macd_hist = None
    if len(close_prices) >= 26:
        # Calculate 12-period EMA
        ema_12 = calculate_ema(close_prices, 12)
        # Calculate 26-period EMA
        ema_26 = calculate_ema(close_prices, 26)
        if ema_12 is not None and ema_26 is not None:
            macd = ema_12 - ema_26
            # Calculate 9-period EMA of MACD (signal line)
            macd_values = [macd]  # Simplified - in practice we'd need historical MACD values
            macd_signal = calculate_ema(macd_values, 9) if len(macd_values) >= 9 else macd
            macd_hist = macd - (macd_signal or 0)

    return {
        "price": price,
        "change": change,
        "changePct": change_pct,
        "name": name,
        "sma_5": sma_5,
        "sma_20": sma_20,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist
    }


def calculate_ema(prices, period):
    """Calculate Exponential Moving Average"""
    if len(prices) < period:
        return None

    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period  # Start with SMA

    for price in prices[period:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))

    return ema


# ── PORTFOLIO ───────────────────────────────────────────────────────────────

@app.route("/api/portfolio", methods=["GET"])
def get_portfolio():
    return jsonify(load_json(DATA_FILE, []))


@app.route("/api/portfolio", methods=["POST"])
def save_portfolio():
    save_json(DATA_FILE, request.json)
    return jsonify({"ok": True})


# ── PRICES ──────────────────────────────────────────────────────────────────

@app.route("/api/prices", methods=["POST"])
def get_prices():
    tickers = request.json.get("tickers", [])
    if not tickers:
        return jsonify([])

    results = []

    for symbol in tickers:
        try:
            q = fast_quote(symbol)
            result = {
                "ticker": symbol.upper(),
                "price": round(q["price"], 2),
                "change": q["change"],
                "changePct": q["changePct"],
                "name": q["name"],
            }
            # Add technical indicators if available
            if q.get("sma_5") is not None:
                result["sma_5"] = round(q["sma_5"], 2)
            if q.get("sma_20") is not None:
                result["sma_20"] = round(q["sma_20"], 2)
            if q.get("rsi") is not None:
                result["rsi"] = round(q["rsi"], 2)
            if q.get("macd") is not None:
                result["macd"] = round(q["macd"], 4)
            if q.get("macd_signal") is not None:
                result["macd_signal"] = round(q["macd_signal"], 4)
            if q.get("macd_hist") is not None:
                result["macd_hist"] = round(q["macd_hist"], 4)

            results.append(result)
        except Exception as e:
            results.append({
                "ticker": symbol.upper(),
                "price": None,
                "change": None,
                "changePct": None,
                "name": symbol,
                "error": str(e),
            })

    return jsonify(results)


# ── BRIEF ───────────────────────────────────────────────────────────────────

def _build_brief_data(portfolio: list):
    index_syms = [("S&P 500", "SPY"), ("NASDAQ", "QQQ"), ("Dow Jones", "DIA")]

    market_lines = []
    changes = []

    for name, sym in index_syms:
        try:
            q = fast_quote(sym)
            pct = q["changePct"]
            changes.append(pct)

            arrow = "▲" if pct >= 0 else "▼"
            market_lines.append(f"{name}: {q['price']:.2f} {arrow}{abs(pct):.2f}%")
        except Exception:
            pass

    avg = sum(changes) / len(changes) if changes else 0
    sentiment = "bullish" if avg > 0.5 else ("bearish" if avg < -0.5 else "neutral")

    stocks = []
    for p in portfolio:
        sym = p["ticker"]

        try:
            q = fast_quote(sym)
            price = q["price"]
            pct = q["changePct"]

            prof = company_profile(sym)
            name = prof.get("companyName") or q["name"] or sym

            # Build technical summary
            tech_parts = []
            if q.get("sma_5") is not None and q.get("sma_20") is not None:
                if price > q["sma_5"] > q["sma_20"]:
                    tech_parts.append("bullish MA alignment")
                elif price < q["sma_5"] < q["sma_20"]:
                    tech_parts.append("bearish MA alignment")
                else:
                    tech_parts.append("mixed MA signals")

            if q.get("rsi") is not None:
                if q["rsi"] > 70:
                    tech_parts.append(f"RSI overbought ({q['rsi']:.1f})")
                elif q["rsi"] < 30:
                    tech_parts.append(f"RSI oversold ({q['rsi']:.1f})")
                else:
                    tech_parts.append(f"RSI neutral ({q['rsi']:.1f})")

            if q.get("macd") is not None and q.get("macd_signal") is not None:
                if q["macd"] > q["macd_signal"]:
                    tech_parts.append("MACD bullish crossover")
                else:
                    tech_parts.append("MACD bearish crossover")

            tech_summary = " | ".join(tech_parts) if tech_parts else "no technical signals"

            stocks.append({
                "ticker": sym,
                "type": p.get("type", "hold"),
                "update": f"{name} at {price:.2f} ({pct:+.2f}%)",
                "outlook": f"Technicals: {tech_summary}",
                "sentiment": "bullish" if pct > 0 else "bearish" if pct < 0 else "neutral",
                "technical": {
                    "sma_5": q.get("sma_5"),
                    "sma_20": q.get("sma_20"),
                    "rsi": q.get("rsi"),
                    "macd": q.get("macd"),
                    "macd_signal": q.get("macd_signal"),
                    "macd_hist": q.get("macd_hist")
                }
            })

        except Exception as e:
            stocks.append({
                "ticker": sym,
                "type": p.get("type", "hold"),
                "update": f"Error: {e}",
                "outlook": "N/A",
                "sentiment": "neutral",
            })

    return {
        "market_overview": {
            "summary": ", ".join(market_lines),
            "sentiment": sentiment,
            "key_events": "Check earnings calendar.",
        },
        "stocks": stocks,
    }


@app.route("/api/brief", methods=["POST"])
def generate_brief():
    body = request.json
    portfolio = body.get("portfolio", [])

    return jsonify(_build_brief_data(portfolio))


# ── DELIVERY (EMAIL & SMS) ──────────────────────────────────────────────────

@app.route("/api/delivery", methods=["GET"])
def get_delivery():
    return jsonify(load_json(DELIVERY_FILE, {}))


@app.route("/api/delivery", methods=["POST"])
def save_delivery():
    save_json(DELIVERY_FILE, request.json)
    return jsonify({"ok": True})


@app.route("/api/delivery/test", methods=["POST"])
def test_delivery():
    delivery = load_json(DELIVERY_FILE, {})
    portfolio = load_json(DATA_FILE, [])

    def run():
        data = _build_brief_data(portfolio)

        text = f"Market Brief — {datetime.date.today().strftime('%B %d, %Y')}\n\n"
        text += data["market_overview"]["summary"] + "\n\n"

        for s in data["stocks"]:
            text += f"{s['ticker']} — {s['update']}\n"

        # Send email if configured
        if delivery.get("email"):
            _send_email(delivery["email"], text)

        # Send SMS if configured
        if delivery.get("phone"):
            _send_sms(delivery["phone"], text)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})


# ── EMAIL ──────────────────────────────────────────────────────────────────

def _send_email(to_addr, body):
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_addr = os.environ.get("EMAIL_FROM", "brief@resend.dev")

    if not api_key:
        print("[email] missing RESEND_API_KEY")
        return

    try:
        import requests

        res = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "from": from_addr,
                "to": to_addr,
                "subject": "Market Brief",
                "text": body
            }
        )

        print("[email]", res.text)

    except Exception as e:
        print(f"[email] error {e}")


# ── SMS ───────────────────────────────────────────────
def _send_sms(to_number, body):
    account_sid = os.environ.get("TWILIO_SID", "")
    auth_token = os.environ.get("TWILIO_TOKEN", "")
    from_number = os.environ.get("TWILIO_FROM", "")

    if not (account_sid and auth_token and from_number):
        print("[sms] missing Twilio credentials")
        return

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)

        message = client.messages.create(
            body=body,
            from_=from_number,
            to=to_number
        )
        print(f"[sms] sent to {to_number}: {message.sid}")

    except Exception as e:
        print(f"[sms] error: {e}")


# ── HOME ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)