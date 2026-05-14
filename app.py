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
        params={"interval": "1d", "range": "2d"},
        timeout=8
    )
    r.raise_for_status()

    meta = r.json()["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice") or meta.get("previousClose")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose") or price

    change = round(price - prev, 2) if price and prev else 0
    change_pct = round(change / prev * 100, 2) if prev else 0
    name = meta.get("shortName") or meta.get("longName") or symbol

    return {
        "price": price,
        "change": change,
        "changePct": change_pct,
        "name": name
    }


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
            results.append({
                "ticker": symbol.upper(),
                "price": round(q["price"], 2),
                "change": q["change"],
                "changePct": q["changePct"],
                "name": q["name"],
            })
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

            stocks.append({
                "ticker": sym,
                "type": p.get("type", "hold"),
                "update": f"{name} at {price:.2f} ({pct:+.2f}%)",
                "outlook": "Monitor catalysts.",
                "sentiment": "bullish" if pct > 0 else "bearish" if pct < 0 else "neutral",
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


# ── DELIVERY (EMAIL ONLY) ──────────────────────────────────────────────────

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

        if delivery.get("email"):
            _send_email(delivery["email"], text)

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


# ── HOME ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)