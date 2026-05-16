#!/usr/bin/env python3
"""
scheduler.py — EMAIL ONLY + OLLAMA AI BRIEF
Works with cron, Task Scheduler, or manual run
"""

import os
import json
import datetime
import re
from pathlib import Path
import requests

# ── PATHS ────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "portfolio.json"
DELIVERY_FILE = BASE_DIR / "data" / "delivery.json"
LOG_FILE = BASE_DIR / "scheduler_log.txt"


# ── LOGGING ──────────────────────────────────────────────
def log(msg: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── LOAD JSON ────────────────────────────────────────────
def load_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return default
    except Exception as e:
        log(f"ERROR loading {path}: {e}")
        return default


# ── MARKET DATA ──────────────────────────────────────────
def calculate_ema(prices, period):
    """Calculate Exponential Moving Average"""
    if len(prices) < period:
        return None

    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period

    for price in prices[period:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))

    return ema


def fast_quote(symbol: str):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        params={"interval": "1d", "range": "60d"},
        timeout=10
    )
    r.raise_for_status()

    data = r.json()
    result = data.get("chart", {}).get("result")

    if not result:
        raise ValueError(f"No data for {symbol}")

    item = result[0]
    indicators = item.get("indicators", {})
    quote = indicators.get("quote", [{}])[0] if indicators.get("quote") else {}

    close_prices = quote.get("close", [])
    close_prices = [p for p in close_prices if p is not None]

    # Always derive price and change from the close array for accuracy
    if len(close_prices) < 2:
        return 0, 0, {}, {}

    price = close_prices[-1]
    prev  = close_prices[-2]
    change = round(price - prev, 2)
    change_pct = round((change / prev) * 100, 2)

    sma_5 = sum(close_prices[-5:]) / 5 if len(close_prices) >= 5 else None
    sma_20 = sum(close_prices[-20:]) / 20 if len(close_prices) >= 20 else None

    rsi = None
    if len(close_prices) >= 14:
        deltas = [close_prices[i] - close_prices[i-1] for i in range(1, len(close_prices))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        avg_gain = sum(gains[-14:]) / 14
        avg_loss = sum(losses[-14:]) / 14
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = round(100 - (100 / (1 + rs)), 1)

    macd = macd_signal = macd_hist = None
    if len(close_prices) >= 26:
        ema_12 = calculate_ema(close_prices, 12)
        ema_26 = calculate_ema(close_prices, 26)
        if ema_12 is not None and ema_26 is not None:
            macd = ema_12 - ema_26
            macd_signal = macd * 0.9
            macd_hist = macd - macd_signal

    return price, change_pct, {
        "sma_5": sma_5,
        "sma_20": sma_20,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist
    }, {}


# ── OLLAMA ───────────────────────────────────────────────
def ask_ollama(prompt):
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3.1",
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        return response.json().get("response", "").strip()
    except Exception as e:
        return f"Ollama unavailable: {e}"


# ── BRIEF GENERATION ─────────────────────────────────────
def generate_brief(portfolio):
    date_str = datetime.date.today().strftime("%A, %B %d, %Y")

    holdings = []
    watchlist = []

    for p in portfolio:
        sym = p.get("ticker", "").upper()

        try:
            price, pct, technicals, _ = fast_quote(sym)
        except Exception:
            price, pct = 0, 0
            technicals = {}

        asset = {
            "ticker": sym,
            "price": price,
            "pct": pct,
            "technicals": technicals
        }

        if p.get("type") == "hold":
            holdings.append(asset)
        else:
            watchlist.append(asset)

    # ── helpers ─────────────────────────────
    def sentiment(pct):
        if pct > 2:
            return "Strong positive momentum"
        if pct > 0:
            return "Mild upward movement"
        if pct > -2:
            return "Slight weakness / consolidation"
        return "Significant downside pressure"

    def format_asset(a):
        arrow = "▲" if a["pct"] >= 0 else "▼"
        tech_lines = []

        technicals = a.get("technicals", {})
        if technicals.get("sma_5") is not None and technicals.get("sma_20") is not None:
            price = a["price"]
            sma_5 = technicals["sma_5"]
            sma_20 = technicals["sma_20"]
            if price > sma_5 > sma_20:
                tech_lines.append("Bullish MA alignment (price > SMA5 > SMA20)")
            elif price < sma_5 < sma_20:
                tech_lines.append("Bearish MA alignment (price < SMA5 < SMA20)")
            else:
                tech_lines.append("Mixed MA signals")

        if technicals.get("rsi") is not None:
            rsi = technicals["rsi"]
            if rsi > 70:
                tech_lines.append(f"RSI overbought ({rsi:.1f})")
            elif rsi < 30:
                tech_lines.append(f"RSI oversold ({rsi:.1f})")
            else:
                tech_lines.append(f"RSI neutral ({rsi:.1f})")

        if technicals.get("macd") is not None and technicals.get("macd_signal") is not None:
            macd = technicals["macd"]
            macd_signal = technicals["macd_signal"]
            if macd > macd_signal:
                tech_lines.append("MACD bullish crossover")
            else:
                tech_lines.append("MACD bearish crossover")

        tech_section = ""
        if tech_lines:
            tech_section = "Technicals: " + " | ".join(tech_lines) + "\n"

        return (
            f"{a['ticker']}: ${a['price']:.2f} {arrow}{abs(a['pct']):.2f}%\n"
            f"{tech_section}"
            f"Insight: {sentiment(a['pct'])}\n"
        )

    # ── BASE BRIEF ─────────────────────────
    lines = [
        f"Market Brief — {date_str}",
        "",
        "📊 MARKET SUMMARY",
        "Markets are driven by risk sentiment and sector rotation today.",
        "",
        "📈 HOLDINGS ANALYSIS"
    ]

    for h in holdings:
        lines.append(format_asset(h))

    if watchlist:
        lines.append("\n👀 WATCHLIST")
        for w in watchlist:
            lines.append(format_asset(w))

    # ── RISK SNAPSHOT ───────────────────────
    all_assets = holdings + watchlist
    ai_input = ""

    if all_assets:
        avg = sum(a["pct"] for a in all_assets) / len(all_assets)

        lines += [
            "\n⚠️ PORTFOLIO RISK SNAPSHOT",
            f"Average movement: {avg:.2f}%",
        ]

        if avg < -2:
            lines.append("Broad downward pressure across portfolio.")
        elif avg > 2:
            lines.append("Strong bullish momentum across holdings.")
        else:
            lines.append("Mixed or neutral market conditions.")

        ai_input = "\n".join(
            f"{a['ticker']}: price={a['price']}, change={a['pct']}%"
            for a in all_assets
        )

    # ── OLLAMA AI INSIGHT ──────────────────
    ai_insight = ""

    if ai_input:
        prompt = f"""
You are a senior equity research analyst at a top-tier investment bank.

Write a concise daily portfolio note based on the data below.

PORTFOLIO DATA:
{ai_input}

REQUIREMENTS:
- Use a professional financial analyst tone (not casual, not AI-like)
- Be concise and institutional in style
- Focus on risk, positioning, and market context
- Avoid fluff or motivational language
- Do NOT repeat raw numbers unless relevant
- Interpret what the moves MEAN, not just what happened

STRUCTURE:

1. MARKET VIEW (2–3 sentences)
Summarize overall risk sentiment and what is driving markets.

2. PORTFOLIO POSITIONING
Discuss exposure concentration, correlation risk, and sector bias.

3. KEY MOVERS
Highlight 1–3 most important assets and explain WHY they matter.

4. RISK NOTE
Identify the most important risk in the portfolio right now.

5. OUTLOOK (1 sentence)
Give a forward-looking institutional-style takeaway.

STYLE:
- Think: Goldman Sachs / Morgan Stanley research note
- Clear, direct, professional tone
- No emojis
"""

        ai_insight = ask_ollama(prompt)

    # ── APPEND AI SECTION ───────────────────
    if ai_insight:
        lines += [
            "",
            "🧠 AI INSIGHT (Ollama)",
            ai_insight
        ]

    lines += [
        "",
        "Generated automatically by Market Brief AI scheduler."
    ]

    return "\n".join(lines)


# ── EMAIL ────────────────────────────────────────────────
def to_html(text):
    # Convert **bold** to <strong>
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    # Convert * bullet points to <li>
    text = re.sub(r'^\* (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)

    lines = text.split("\n")
    html_lines = []
    for line in lines:
        if line.strip() == "":
            html_lines.append("<br>")
        else:
            html_lines.append(f"<p style='margin:2px 0'>{line}</p>")

    return f"""
    <html>
    <body style='font-family:monospace;font-size:14px;max-width:700px;margin:auto;padding:20px;color:#111;line-height:1.6'>
    {''.join(html_lines)}
    </body>
    </html>
    """


def send_email(to_addr, body):
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_addr = os.environ.get("EMAIL_FROM", "brief@resend.dev")

    if not api_key:
        log("RESEND_API_KEY missing — email skipped")
        return

    try:
        res = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "from": from_addr,
                "to": to_addr,
                "subject": "Market Brief (AI Powered)",
                "text": body,
                "html": to_html(body)
            },
            timeout=10
        )

        log(f"Email response: {res.text}")

    except Exception as e:
        log(f"EMAIL ERROR: {e}")


# ── SMS ────────────────────────────────────────────────
def send_sms(to_number, body):
    account_sid = os.environ.get("TWILIO_SID", "")
    auth_token = os.environ.get("TWILIO_TOKEN", "")
    from_number = os.environ.get("TWILIO_FROM", "")

    if not (account_sid and auth_token and from_number):
        log("Twilio credentials missing — SMS skipped")
        return

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)

        message = client.messages.create(
            body=body,
            from_=from_number,
            to=to_number
        )
        log(f"SMS sent to {to_number}: {message.sid}")

    except Exception as e:
        log(f"SMS ERROR: {e}")


# ── MAIN ────────────────────────────────────────────────
if __name__ == "__main__":
    log("Scheduler started")

    try:
        portfolio = load_json(DATA_FILE, [])
        delivery = load_json(DELIVERY_FILE, {})

        if not portfolio:
            log("No portfolio found — exiting")
            exit(0)

        log(f"Generating brief for {len(portfolio)} positions")

        brief = generate_brief(portfolio)

        log("Brief generated successfully")

        print("\n" + brief + "\n")

        email = delivery.get("email")
        if email:
            send_email(email, brief)
        else:
            log("No email set in delivery.json")

        phone = delivery.get("phone")
        if phone:
            send_sms(phone, brief)
        else:
            log("No phone set in delivery.json")

        log("Scheduler finished successfully")

    except Exception as e:
        log(f"FATAL ERROR: {e}")
        raise