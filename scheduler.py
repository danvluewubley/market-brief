#!/usr/bin/env python3
"""
scheduler.py — EMAIL ONLY + OLLAMA AI BRIEF
Works with cron, Task Scheduler, or manual run
"""

import os
import json
import datetime
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
def fast_quote(symbol: str):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        params={"interval": "1d", "range": "2d"},
        timeout=10
    )
    r.raise_for_status()

    data = r.json()
    result = data.get("chart", {}).get("result")

    if not result:
        raise ValueError(f"No data for {symbol}")

    meta = result[0].get("meta", {})

    price = meta.get("regularMarketPrice") or meta.get("previousClose")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose") or price

    if not price or not prev:
        return 0, 0

    change = round(price - prev, 2)
    change_pct = round((change / prev) * 100, 2)

    return price, change_pct


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
            price, pct = fast_quote(sym)
        except Exception:
            price, pct = 0, 0

        asset = {
            "ticker": sym,
            "price": price,
            "pct": pct
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
        return (
            f"{a['ticker']}: ${a['price']:.2f} {arrow}{abs(a['pct']):.2f}%\n"
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

        # ── BUILD AI INPUT ───────────────────
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
                "text": body
            },
            timeout=10
        )

        log(f"Email response: {res.text}")

    except Exception as e:
        log(f"EMAIL ERROR: {e}")


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

        log("Scheduler finished successfully")

    except Exception as e:
        log(f"FATAL ERROR: {e}")
        raise