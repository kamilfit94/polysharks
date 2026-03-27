# 🐋 Polymarket Whale Watcher

Monitors Polymarket for large trades and sends instant Telegram alerts.
Runs free on GitHub Actions every 5 minutes — no server needed.

---

## What you get

- Alerts for any trade above your threshold (default $10,000)
- Covers ALL markets (crypto, politics, finance, sports — everything)
- Tracks seen trades so you never get duplicate alerts
- Scales: WHALE 🐋 / BIG WHALE 🐳 / MEGA WHALE 🐳🐳 based on size
- Optional keyword filter (e.g. only alert on "bitcoin" or "trump" markets)

---

## Setup (15 minutes, one-time)

### Step 1 — Create your Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. `Polymarket Alerts`) and a username (e.g. `poly_whale_bot`)
4. BotFather gives you a token like `7123456789:AAFxxx...` — **copy it**

### Step 2 — Get your Telegram chat ID

1. Message your new bot anything (e.g. "hello")
2. Open this URL in your browser (replace YOUR_TOKEN):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. Find `"chat": {"id": 123456789}` — **copy that number**

### Step 3 — Create a GitHub repo

1. Go to [github.com/new](https://github.com/new)
2. Name it `polymarket-whale-watcher` (can be private)
3. Click **Create repository**

### Step 4 — Upload these files

Upload all 4 files to the root of your repo:
- `whale_watcher.py`
- `requirements.txt`
- `seen_trades.json`
- `.github/workflows/whale_watcher.yml`

**Easiest way:** drag and drop them in the GitHub web UI.

### Step 5 — Add your secrets

In your repo go to **Settings → Secrets and variables → Actions → New repository secret**

Add these 4 secrets:

| Secret name | Value | Required? |
|---|---|---|
| `TELEGRAM_TOKEN` | Your bot token from Step 1 | ✅ Yes |
| `TELEGRAM_CHAT_ID` | Your chat ID from Step 2 | ✅ Yes |
| `WHALE_THRESHOLD_USD` | e.g. `10000` | Optional (default: 10000) |
| `MARKET_KEYWORDS` | e.g. `bitcoin,trump,fed` | Optional (default: all markets) |

### Step 6 — Test it manually

1. Go to **Actions** tab in your repo
2. Click **🐋 Polymarket Whale Watcher** on the left
3. Click **Run workflow** → **Run workflow**
4. Watch the logs — if everything works you'll see "Done. X alert(s) sent."

That's it. It now runs automatically every 5 minutes forever.

---

## Example Telegram alert

```
🐳 BIG WHALE — Polymarket Alert

Market: Will Bitcoin exceed $150,000 before July 2025?

Side:  YES   Price: $0.410 (41.0% implied)
Size:  $47,200

Maker: 0xAb3f…c91a
Taker: 0x77d2…308b
Time:  14:32 UTC  18 Mar 2025

🔗 polymarket.com
```

---

## Customisation

**Change threshold:** update `WHALE_THRESHOLD_USD` secret (no code change needed)

**Filter by topic:** set `MARKET_KEYWORDS` secret to comma-separated terms, e.g.:
- `bitcoin,btc,eth,crypto` — crypto only
- `trump,election,president` — politics only
- `` (empty) — all markets

**Change frequency:** edit the cron line in `.github/workflows/whale_watcher.yml`.
`*/5 * * * *` = every 5 min (minimum). `*/15 * * * *` = every 15 min.

---

## Cost

**Free.** GitHub Actions gives unlimited minutes for public repos and 2,000 min/month
for private repos. Each run takes ~10 seconds, so 5-minute polling uses ~2,880 min/month
on a private repo — just over the free tier. Either make the repo public, or change
polling to every 10 minutes (`*/10 * * * *`) to stay well within the free limit.
