import requests

def test_quote(symbol: str):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        params={"interval": "1d", "range": "5d"},
        timeout=10
    )

    data = r.json()
    item = data["chart"]["result"][0]
    meta = item["meta"]
    quote = item["indicators"]["quote"][0]

    close_prices = [p for p in quote.get("close", []) if p is not None]
    timestamps = item.get("timestamp", [])

    print(f"\n{symbol}")
    print(f"  meta regularMarketPrice : {meta.get('regularMarketPrice')}")
    print(f"  meta chartPreviousClose : {meta.get('chartPreviousClose')}")
    print(f"  last 3 closes          : {close_prices[-3:]}")

    if len(close_prices) >= 2:
        price = close_prices[-1]
        prev  = close_prices[-2]
        pct   = round((price - prev) / prev * 100, 2)
        print(f"  close[-1] vs close[-2] : {price} vs {prev} = {pct:+.2f}%")

for sym in ["TSLA", "NVDX", "BNC", "PLTR", "HOOX"]:
    test_quote(sym)