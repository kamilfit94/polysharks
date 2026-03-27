"""
Penny Stock Reversal Screener
Finds overextended penny stocks with high reversal probability.
Sends top candidates to Telegram every morning.
Runs free on GitHub Actions — no API key needed.
"""

import os
import logging
import requests
from datetime import datetime, timezone

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_GAIN_PCT      = float(os.environ.get("MIN_GAIN_PCT",   "100"))   # 5-day gain %
MIN_RSI           = float(os.environ.get("MIN_RSI",        "75"))    # RSI threshold
MAX_PRICE         = float(os.environ.get("MAX_PRICE",      "5.0"))   # max stock price
MIN_VOLUME        = int(os.environ.get("MIN_VOLUME",       "300000")) # min daily volume
TOP_N             = int(os.environ.get("TOP_N",            "5"))      # alerts per run

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  DATA  (Yahoo Finance — free, no API key)
# ─────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def get_screener_candidates() -> list[str]:
    """
    Pull penny stock candidates from Yahoo Finance's most-active
    and day-gainers screener pages. Returns a list of tickers.
    """
    urls = [
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers&count=100",
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=most_actives&count=100",
    ]
    tickers = set()
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
            quotes = (data.get("finance", {})
                         .get("result", [{}])[0]
                         .get("quotes", []))
            for q in quotes:
                sym = q.get("symbol", "")
                price = q.get("regularMarketPrice", 999)
                if price and price <= MAX_PRICE and "." not in sym and len(sym) <= 5:
                    tickers.add(sym)
        except Exception as e:
            log.warning(f"Screener fetch failed: {e}")
    log.info(f"Got {len(tickers)} candidate tickers from Yahoo screeners.")
    return list(tickers)


def get_quote_data(ticker: str) -> dict | None:
    """Fetch summary quote data for a single ticker."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=10d"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        meta   = result[0].get("meta", {})
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        volumes = result[0].get("indicators", {}).get("quote", [{}])[0].get("volume", [])
        closes  = [c for c in closes if c is not None]
        volumes = [v for v in volumes if v is not None]
        if len(closes) < 6:
            return None
        return {
            "ticker":        ticker,
            "price":         meta.get("regularMarketPrice", closes[-1]),
            "closes":        closes,
            "volumes":       volumes,
            "currency":      meta.get("currency", "USD"),
        }
    except Exception as e:
        log.debug(f"{ticker}: fetch failed — {e}")
        return None


# ─────────────────────────────────────────────
#  INDICATORS
# ─────────────────────────────────────────────

def calc_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def calc_gain_pct(closes: list[float], days: int = 5) -> float | None:
    if len(closes) < days + 1:
        return None
    base = closes[-(days+1)]
    if base == 0:
        return None
    return round((closes[-1] - base) / base * 100, 1)


def calc_macd_bearish(closes: list[float]) -> bool:
    """True if MACD line just crossed below signal line (bearish cross)."""
    def ema(data, span):
        k = 2 / (span + 1)
        e = data[0]
        for v in data[1:]:
            e = v * k + e * (1 - k)
        return e
    if len(closes) < 26:
        return False
    fast_now  = ema(closes, 12)
    slow_now  = ema(closes, 26)
    fast_prev = ema(closes[:-1], 12)
    slow_prev = ema(closes[:-1], 26)
    macd_now  = fast_now - slow_now
    macd_prev = fast_prev - slow_prev
    signal_now  = macd_now  * (2/10)
    signal_prev = macd_prev * (2/10)
    return (macd_prev > signal_prev) and (macd_now < signal_now)


def calc_volume_fading(volumes: list[float]) -> bool:
    """True if recent volume is declining vs earlier spike."""
    if len(volumes) < 4:
        return False
    peak   = max(volumes[-5:-1]) if len(volumes) >= 5 else volumes[-2]
    recent = volumes[-1]
    return recent < peak * 0.6


def calc_above_bb(closes: list[float], period: int = 20) -> bool:
    """True if price is above upper Bollinger Band (mean + 2*std)."""
    if len(closes) < period:
        return False
    window = closes[-period:]
    mean   = sum(window) / period
    std    = (sum((x - mean)**2 for x in window) / period) ** 0.5
    upper  = mean + 2 * std
    return closes[-1] > upper


def score_stock(signals: dict, rsi: float, gain: float) -> int:
    score = 0
    if signals.get("rsi"):    score += 25
    if signals.get("volume"): score += 20
    if signals.get("macd"):   score += 20
    if signals.get("bb"):     score += 20
    if rsi  >= 85:            score += 10
    if gain >= 200:           score += 10
    return min(score, 100)


# ─────────────────────────────────────────────
#  SCREENING
# ─────────────────────────────────────────────

def screen_stock(ticker: str) -> dict | None:
    data = get_quote_data(ticker)
    if not data:
        return None

    closes  = data["closes"]
    volumes = data["volumes"]
    price   = data["price"]

    if price > MAX_PRICE or price <= 0:
        return None

    gain = calc_gain_pct(closes, days=5)
    if gain is None or gain < MIN_GAIN_PCT:
        return None

    rsi = calc_rsi(closes)
    if rsi is None or rsi < MIN_RSI:
        return None

    avg_vol = sum(volumes[-5:]) / max(len(volumes[-5:]), 1)
    if avg_vol < MIN_VOLUME:
        return None

    signals = {
        "rsi":    rsi >= MIN_RSI,
        "volume": calc_volume_fading(volumes),
        "macd":   calc_macd_bearish(closes),
        "bb":     calc_above_bb(closes),
    }

    sc = score_stock(signals, rsi, gain)
    if sc < 40:
        return None

    return {
        "ticker":   ticker,
        "price":    price,
        "gain":     gain,
        "rsi":      rsi,
        "signals":  signals,
        "score":    sc,
        "avg_vol":  int(avg_vol),
    }


# ─────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials missing.")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        log.warning(f"Telegram failed: {e}")
        return False


def risk_label(score: int) -> str:
    if score >= 80: return "EXTREME"
    if score >= 65: return "VERY HIGH"
    return "HIGH"


def format_signal_line(signals: dict) -> str:
    names = {"rsi": "RSI", "volume": "Vol fade", "macd": "MACD cross", "bb": "Above BB"}
    active = [names[k] for k, v in signals.items() if v]
    return " + ".join(active) if active else "none"


def format_message(results: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%d %b %Y  %H:%M UTC")
    lines = [
        f"<b>Reversal candidates — {now}</b>",
        f"Penny stocks up 100%+ showing exhaustion signals\n",
    ]
    for i, r in enumerate(results, 1):
        sig_line = format_signal_line(r["signals"])
        risk     = risk_label(r["score"])
        lines.append(
            f"<b>{i}. {r['ticker']}</b>  ${r['price']:.2f}\n"
            f"   Gain: +{r['gain']:.0f}%   RSI: {r['rsi']:.0f}   Score: {r['score']}/100\n"
            f"   Signals: {sig_line}\n"
            f"   Risk: {risk}\n"
        )
    lines.append("Verify on TradingView before trading. Not financial advice.")
    return "\n".join(lines)


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    log.info("Starting penny stock reversal screener...")
    log.info(f"Filters: price<=${MAX_PRICE}, gain>={MIN_GAIN_PCT}%, RSI>={MIN_RSI}, vol>={MIN_VOLUME:,}")

    candidates = get_screener_candidates()
    if not candidates:
        log.error("No candidates fetched.")
        send_telegram("Screener error: could not fetch candidates from Yahoo Finance.")
        return

    results = []
    for ticker in candidates:
        result = screen_stock(ticker)
        if result:
            log.info(f"  HIT: {ticker}  score={result['score']}  RSI={result['rsi']}  gain=+{result['gain']}%")
            results.append(result)

    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:TOP_N]

    log.info(f"Screened {len(candidates)} stocks. Found {len(results)} hits. Sending top {len(top)}.")

    if not top:
        msg = (
            f"Reversal screener — {datetime.now(timezone.utc).strftime('%d %b %Y')}\n\n"
            f"No stocks matched today's criteria:\n"
            f"Price under ${MAX_PRICE}, gain over {MIN_GAIN_PCT:.0f}%, RSI over {MIN_RSI:.0f}\n\n"
            f"Market may be quiet or criteria too strict."
        )
    else:
        msg = format_message(top)

    if send_telegram(msg):
        log.info("Telegram message sent.")
    else:
        log.error("Failed to send Telegram message.")


if __name__ == "__main__":
    main()
