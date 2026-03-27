"""
Polymarket Whale Watcher 🐋
Polls Polymarket for large trades and sends Telegram alerts.
Designed to run on GitHub Actions every 5 minutes — free forever.
"""

import os
import json
import logging
import requests
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────
#  CONFIG — set these as GitHub Secrets (never hardcode them)
# ─────────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Minimum trade size in USD to trigger an alert
WHALE_THRESHOLD_USD = int(os.environ.get("WHALE_THRESHOLD_USD", "10000"))

# Optional: only alert if market question contains one of these keywords.
# Leave as empty string "" to track ALL markets.
# Example: "bitcoin,trump,fed,eth" 
MARKET_KEYWORDS_RAW = os.environ.get("MARKET_KEYWORDS", "")
MARKET_KEYWORDS = [k.strip().lower() for k in MARKET_KEYWORDS_RAW.split(",") if k.strip()]

# ─────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────

GAMMA_API      = "https://gamma-api.polymarket.com"
DATA_API       = "https://data-api.polymarket.com"
SEEN_FILE      = "seen_trades.json"
MAX_SEEN       = 2000   # cap memory to avoid repo bloat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  PERSISTENCE  (seen trade IDs stored in repo as JSON)
# ─────────────────────────────────────────────────────────────

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE) as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_seen(seen: set) -> None:
    trimmed = list(seen)[-MAX_SEEN:]
    with open(SEEN_FILE, "w") as f:
        json.dump(trimmed, f)
    log.info(f"Saved {len(trimmed)} seen trade IDs.")


# ─────────────────────────────────────────────────────────────
#  POLYMARKET  (uses the public Data API — no auth needed)
# ─────────────────────────────────────────────────────────────

def fetch_recent_trades(limit: int = 500) -> list[dict]:
    """
    Fetch recent trades from Polymarket's Data API.
    Returns list of trade dicts sorted newest-first.
    """
    try:
        resp = requests.get(
            f"{DATA_API}/trades",
            params={"limit": limit},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        # API may return a list directly or wrap it
        if isinstance(data, list):
            return data
        return data.get("data", data.get("trades", []))
    except Exception as e:
        log.warning(f"Failed to fetch trades: {e}")
        return []


def get_market_question(condition_id: str) -> str:
    """Look up a human-readable market question from the Gamma API."""
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"conditionIds": condition_id},
            timeout=10,
        )
        if resp.status_code == 200:
            markets = resp.json()
            if markets:
                return markets[0].get("question", condition_id)
    except Exception:
        pass
    return condition_id


def trade_usd_value(trade: dict) -> float:
    """
    USD value of a trade = size (shares) × price (USDC per share).
    Both fields may come in as strings from the API.
    """
    try:
        size  = float(trade.get("size",  trade.get("tradeSize",  0)))
        price = float(trade.get("price", trade.get("tradePrice", 0)))
        return size * price
    except (TypeError, ValueError):
        return 0.0


def is_whale(trade: dict) -> bool:
    return trade_usd_value(trade) >= WHALE_THRESHOLD_USD


def passes_keyword_filter(question: str) -> bool:
    if not MARKET_KEYWORDS:
        return True
    q = question.lower()
    return any(kw in q for kw in MARKET_KEYWORDS)


# ─────────────────────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials not set. Check your GitHub Secrets.")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "text":       message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            log.info("Telegram message sent.")
            return True
        log.warning(f"Telegram error {resp.status_code}: {resp.text}")
    except Exception as e:
        log.warning(f"Telegram request failed: {e}")
    return False


def format_alert(trade: dict, question: str, usd_value: float) -> str:
    side        = trade.get("side", trade.get("outcome", "?")).upper()
    price       = float(trade.get("price", trade.get("tradePrice", 0)))
    maker_addr  = trade.get("maker", trade.get("makerAddress", "unknown"))
    taker_addr  = trade.get("taker", trade.get("takerAddress", "unknown"))
    ts_raw      = trade.get("timestamp", trade.get("matchTime", ""))

    # Pretty-print timestamp
    try:
        ts = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
        ts_str = ts.strftime("%H:%M UTC  %d %b %Y")
    except Exception:
        ts_str = str(ts_raw)

    # Shorten wallet addresses
    def short(addr: str) -> str:
        return f"{addr[:6]}…{addr[-4:]}" if len(addr) > 12 else addr

    # Implied probability from price
    prob_pct = round(price * 100, 1)

    whale_size = ""
    if usd_value >= 100_000:
        whale_size = "🐳🐳 MEGA WHALE"
    elif usd_value >= 50_000:
        whale_size = "🐳 BIG WHALE"
    else:
        whale_size = "🐋 WHALE"

    return (
        f"{whale_size} — Polymarket Alert\n\n"
        f"<b>Market:</b> {question}\n\n"
        f"<b>Side:</b>  {side}   "
        f"<b>Price:</b> ${price:.3f} ({prob_pct}% implied)\n"
        f"<b>Size:</b>  ${usd_value:,.0f}\n\n"
        f"<b>Maker:</b> <code>{short(maker_addr)}</code>\n"
        f"<b>Taker:</b> <code>{short(taker_addr)}</code>\n"
        f"<b>Time:</b>  {ts_str}\n\n"
        f"🔗 polymarket.com"
    )


# ─────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────

def main():
    log.info(f"Starting whale watcher. Threshold: ${WHALE_THRESHOLD_USD:,}")
    if MARKET_KEYWORDS:
        log.info(f"Keyword filter active: {MARKET_KEYWORDS}")

    seen      = load_seen()
    trades    = fetch_recent_trades()
    log.info(f"Fetched {len(trades)} recent trades.")

    alerts_sent = 0

    for trade in trades:
        trade_id = trade.get("id", trade.get("tradeId", ""))
        if not trade_id or trade_id in seen:
            continue

        seen.add(trade_id)

        usd_value = trade_usd_value(trade)
        if usd_value < WHALE_THRESHOLD_USD:
            continue

        # Resolve market question
        condition_id = trade.get("conditionId", trade.get("market", ""))
        question     = get_market_question(condition_id) if condition_id else "Unknown market"

        if not passes_keyword_filter(question):
            continue

        log.info(f"Whale found: ${usd_value:,.0f} on '{question[:60]}'")

        message = format_alert(trade, question, usd_value)
        if send_telegram(message):
            alerts_sent += 1

    save_seen(seen)
    log.info(f"Done. {alerts_sent} alert(s) sent.")


if __name__ == "__main__":
    main()
