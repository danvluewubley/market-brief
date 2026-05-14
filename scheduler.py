#!/usr/bin/env python3
"""
scheduler.py — EMAIL ONLY production-safe scheduler
Works with cron, Task Scheduler, or manual run
"""

import os
import json
import datetime
from pathlib import Path
import requests

# ── FIX: always resolve paths relative to script location ──
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "portfolio.json"
DELIVERY_FILE = BASE_DIR / "data" / "delivery.json"
LOG_FILE = BASE_DIR / "scheduler_log.txt"


# ── LOGGING ────────────────────────────────────────────────

def log(msg: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── LOAD DATA ──────────────────────────────────────────────

def load_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return default
    except Exception as e:
        log(f"ERROR loading {path}: {e}")
        return default


# ── MARKET DATA ────────────────────────────────────────────

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


# ── BRIEF GENERATION ───────────────────────────────────────

def generate_brief(portfolio):
    date_str = datetime.date.today().strftime("%A, %B %d, %Y")

    lines = [
        f"Market Brief — {date_str}",
        "",
        "PORTFOLIO UPDATE"
    ]

    for p in portfolio:
        sym = p.get("ticker", "").upper()

        try:
            price, pct = fast_quote(sym)
            arrow = "▲" if pct >= 0 else "▼"
            lines.append(f"{sym}: {price:.2f} {arrow}{abs(pct):.2f}%")
        except Exception as e:
            lines.append(f"{sym}: unavailable ({e})")

    lines.append("")
    lines.append("Generated automatically by Market Brief scheduler.")

    return "\n".join(lines)


# ── EMAIL (RESEND API) ────────────────────────────────────

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
                "subject": "Market Brief (Scheduled)",
                "text": body
            },
            timeout=10
        )

        log(f"Email response: {res.text}")

    except Exception as e:
        log(f"EMAIL ERROR: {e}")


# ── MAIN ───────────────────────────────────────────────────

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