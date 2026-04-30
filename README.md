# Stock Scanner

A trading-discipline tool that screens for setups, sizes positions, tracks
open trades, and journals every alert so you can prove (or disprove) that
the strategy works for *you*.

> **Important:** This is a screening + discipline tool, not financial advice.
> Most retail day/swing traders lose money. Edge comes from cutting losses
> fast, sizing small, and following written rules — not from picking better
> stocks. Paper-trade for at least 30 alerts before risking real money.

## Philosophy

- **The scanner is ~5% of the picture.** Position sizing, stop discipline,
  and an honest journal are the rest.
- **Default = swing breakouts.** Multi-day to multi-week holds work on free
  Yahoo data and don't trigger the PDT rule (which makes active day trading
  impossible under $25k).
- **Day-trading mode (`warrior`) is bundled** but optional. Free 15-min
  delayed data is a real handicap there; serious day traders pay for Trade
  Ideas + Benzinga Pro.

## The daily workflow

After the close each day, double-click `stockscanner.exe` (or run
`stockscanner review` from cmd). You'll see:

```
================================================================
DAILY REVIEW
================================================================

Open positions
----------------------------------------------------------------
TICKER  ACTION   LAST     P/L%    STOP   TARGET  REASON
NVDA    HOLD     176.40   +5.2%  165.27  211.04  above stop, target, 20MA

Journal — auto-resolving pending alerts...
  3 alert(s) resolved this run.

New breakout candidates
----------------------------------------------------------------
TICKER     ENTRY      STOP    TARGET   RISK%    VOLx  52W-DIST
AVGO      178.40    165.27   211.04    7.4%    1.84      -1.2%
                size 30 sh  notional $5,352 (5.4% acct)  risk $99

Performance
----------------------------------------------------------------
  last 30 days   alerts  18  resolved  14  win  57.1%  avg +0.42R  best +3.00R  worst -1.00R
  last 90 days   alerts  47  resolved  43  win  53.5%  avg +0.31R  best +3.00R  worst -1.00R
  all time       alerts  47  resolved  43  win  53.5%  avg +0.31R  best +3.00R  worst -1.00R
```

That's the complete process. Three numbers tell you everything: **win rate**,
**average R-multiple**, **drawdown**. If the average R is positive over 30+
resolved trades, the strategy is working for you — graduate to live trading
with small size.

## First-time setup

```cmd
:: Tell the scanner about your account so it can size trades for you.
stockscanner config --account-size 10000 --risk-per-trade 1
```

That's it. Risk per trade defaults to **1%** of account (a $10k account →
$100 max loss per trade); max position size to 25% of account; daily loss
limit to 3% (after which you should manually stop trading for the day).
Override any of those:

```cmd
stockscanner config --risk-per-trade 0.5    :: more conservative
stockscanner config --max-position 20       :: max 20% of account per name
stockscanner config --max-daily-loss 2      :: tighter circuit breaker
stockscanner config --show                  :: see current settings
```

Optional: real-time prices via Finnhub (free tier: 60 calls/min, see
"Real-time data" below). Without it the scanner uses yfinance — fine for
a daily review workflow.

## Commands

```
stockscanner                       # daily review (default on double-click)
stockscanner review                # same as above, runs once
stockscanner scan                  # one-shot screen with sized shares
stockscanner enter NVDA --price 178.40
stockscanner positions             # check open positions for HOLD/EXIT
stockscanner journal               # see logged alerts + outcomes
stockscanner journal --resolve     # re-check all PENDING entries
stockscanner close NVDA            # remove a position from the tracker
stockscanner watch                 # live polling loop (intraday)
stockscanner config --show
```

`enter` auto-sizes when you've configured your account — just give it a
ticker and price:

```
stockscanner enter NVDA --price 178.40
  sizing: 30 sh, $5,352 notional (5.4% acct), risk $99
  Recorded 30 shares of NVDA @ 178.40 (stop 165.27, target 211.04).
```

Override the auto-size with `--shares N` if you want manual control. Override
the auto-stop / auto-target with `--stop X --target Y`.

## How the journal works

Every time you run `scan` (or `review`), each candidate gets logged to the
journal as **PENDING**. On the next run, the scanner pulls the price history
since each pending alert and decides:

- **WIN** if the high since alert reached the target → records `+target R`
- **LOSS** if the low since alert touched the stop → records `-1.00R`
- **BREAKEVEN** if neither happened within 30 days → records actual P&L

Journal lives at `%USERPROFILE%\.stockscanner\journal.json` — plain JSON,
human-readable, safe to back up.

This gives you ground truth on whether the strategy works **for your
account, on your watchlist, in this market**, not on someone else's
backtest.

## Strategy: breakout (default)

**Setup** (must be true to qualify):
- Price within 5% of its 52-week high
- Last 20 days of consolidation: tight range (`(high - low) / close ≤ 12%`)
- Volume contracting during consolidation (20-day avg vol < 50-day avg vol)

**Entry signal** (today's bar must satisfy all):
- Today's close > highest close of the prior 20 days
- Today's volume ≥ 1.5 × 50-day average
- Today's close above the 50-day SMA

**Stop**: 7.5% below entry, or below the consolidation low — whichever is
tighter.

**Target**: entry + 3 × initial risk.

**Position exit rules** (any one triggers EXIT):
- Stop hit
- Target hit
- 20-day SMA broken on a daily close
- Trailing stop: 7.5% below the highest close since entry

## Strategy: warrior (day-trading mode)

Bundled but not the default. See `README` history for the rationale — short
version: free 15-min delayed Yahoo data + the PDT rule make this hard for
small accounts. Use `--strategy warrior` if you want it.

## Real-time data (optional)

Yahoo's free feed lags ~15 minutes. For most users running a daily `review`
workflow that doesn't matter. If you also want intraday `watch` to alert
in near-real-time:

1. Sign up at https://finnhub.io/register (free)
2. Save your key once: `stockscanner config --finnhub-key YOUR_KEY`

The watch loop will use Finnhub for live prices (~1s latency) and yfinance
for the volume baseline. Free-tier cap is 60 calls/min; the scanner
self-throttles to 55. Stay under ~50 tickers per minute.

## Universe selection

```
stockscanner watch --screen day_gainers       # live universe — Yahoo's day gainers
stockscanner scan --watchlist my_list         # static list (file in app dir)
stockscanner watch --list-screens             # all available screens
```

For swing trading the default S&P 500 universe is fine. For day-trading
mode the dynamic Yahoo screens (`--screen day_gainers`,
`--screen most_actives`, etc.) follow the day's leadership automatically.

## Install (Windows)

You don't need Python.

- **Easy:** push this repo to GitHub → Actions → download
  `stockscanner-windows` artifact from the most recent successful run.
- **Local build:** double-click `build_windows.bat` (one-time Python 3.10+
  needed; the resulting `dist\stockscanner.exe` is self-contained).

State and settings live in `%USERPROFILE%\.stockscanner\`:
- `config.json` — your account settings + API keys
- `positions.json` — currently open positions
- `journal.json` — every alert ever logged + outcomes
- `watchlists/` — your custom ticker lists

## Files

- `main.py` — entry point. Double-click runs `review`.
- `scanner/cli.py` — all subcommands.
- `scanner/strategy.py` — breakout strategy + position exit rules.
- `scanner/warrior.py` — Warrior-style day-trading filters.
- `scanner/sizing.py` — fixed-fractional position sizer.
- `scanner/journal.py` — alert logging + auto-resolution.
- `scanner/config.py` — persisted account + API settings.
- `scanner/positions.py` — open-position tracker.
- `scanner/data.py` — yfinance bulk fetch.
- `scanner/finnhub.py` — Finnhub real-time client.
- `scanner/screeners.py` — Yahoo predefined screens.
- `scanner/watch.py` — intraday polling loop.
- `scanner/universe.py` — S&P 500 + watchlist loading.
