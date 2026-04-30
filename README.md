# Stock Scanner

A command-line stock scanner that runs continuously, alerts on setups as they
form, and tracks open positions so it can tell you when to exit. Two strategies
are bundled:

- **`warrior`** *(default)* — Ross Cameron / Warrior Trading-style day-trading
  scanner. Looks for low-priced ($1–$20) gappers up ≥ 4% on heavy relative
  volume (≥ 5× the 50-day avg). Suggested entry = today's high, stop = today's
  low, 2:1 R/R target.
- **`breakout`** — Minervini/Darvas-style swing breakouts. Multi-week
  consolidation near the 52-week high, then break out on volume.

Switch between them with `--strategy warrior` or `--strategy breakout`.

> **Important:** This is a screening tool, not financial advice. Most "setups"
> fail. The edge — if any — comes from cutting losses fast and letting winners
> run, not from prediction accuracy. Backtest before risking real money.
>
> **Day trading is the highest-risk style** — most retail day traders lose money.
> The Warrior strategy is built for short-term momentum trading; only use risk
> capital and tight stops.
>
> **Yahoo Finance free data is ~15-min delayed.** Real-time momentum scanning
> (Trade Ideas, Finviz Elite, Benzinga Pro) requires a paid feed. This tool
> works best as a "what's in play right now" survey, not a tick-by-tick alert.

## What it does

- **`watch`** *(default on double-click)* — runs continuously, polling the universe
  every 5 minutes during US market hours and alerting (console + Windows toast)
  on each new breakout candidate. Press Ctrl-C to stop.
- **`scan`** — one-shot version of `watch`: screens the universe right now and
  prints the candidates with suggested entry / stop-loss / target levels.
- **`enter`** — adds a position to the local tracker once you've actually opened it.
- **`positions`** — checks every open position against the exit rules and tells you
  which to **HOLD**, which to **EXIT**, and why.
- **`close`** — removes a position from the tracker.

## Strategies

### Warrior (default)

Models the core of Ross Cameron's day-trading approach: catch low-priced
small-caps gapping up on huge volume, then ride the bull-flag continuation.

**Filters** (all must be true):
- Last close in `[$1, $20]`
- Today's gap-up ≥ 4% from prior close
- Today's volume ≥ 5 × the 50-day average
- Up on the day (close > open)
- Tight intraday range (`(high - low) / open ≤ 12%`) — avoids extended runners
- Recent run ≥ 5% over the prior 5 sessions (momentum confirmation)

**Suggested levels**:
- Entry = today's high (intraday breakout)
- Stop = today's low (or 5% below entry, whichever is tighter)
- Target = entry + 2 × initial risk (2:1 R/R)

**Best universe** for this strategy: a curated low-float watchlist, NOT the
S&P 500. Most large caps don't gap like small caps do. See
`sample_watchlists/warrior_lowfloat.txt` as a starter.

### Breakout

**Setup** (must be true to qualify as a candidate):
- Price within 5% of its 52-week high
- Last 20 days of consolidation: tight range (`(high - low) / close ≤ 12%`)
- Volume contracting during consolidation: 20-day avg vol < 50-day avg vol

**Entry signal** (today's bar must satisfy all):
- Today's close > highest close of the prior 20 days
- Today's volume ≥ 1.5 × 50-day average volume
- Today's close above the 50-day SMA (trend filter)

**Stop-loss**: 7.5% below entry, or below the prior consolidation low — whichever
is closer (smaller risk).

**Target**: entry + 3 × initial risk (so a 7% stop targets +21%).

**Exit rules** (any one triggers EXIT):
- Stop-loss hit
- Target hit
- 20-day SMA broken on a daily close
- Trailing stop: 7.5% below the highest close since entry

## Install (Windows)

You don't need Python. Grab the latest `stockscanner.exe`:

- **Easy:** Push this repo to GitHub → Actions → download the `stockscanner-windows`
  artifact from the most recent successful run.
- **Local build:** double-click `build_windows.bat` (requires Python 3.10+ on PATH
  the first time; the resulting `dist\stockscanner.exe` is self-contained).

Drop `stockscanner.exe` anywhere on your PC. It writes its data to
`%USERPROFILE%\.stockscanner\` (cache, positions, last scan).

## Usage

```
stockscanner                      # double-click → live warrior watch
stockscanner watch                # same as above, runs until Ctrl-C
stockscanner watch --strategy breakout
stockscanner watch --interval 10  # poll every 10 minutes instead of 5
stockscanner watch --top 5        # at most 5 alerts per cycle
stockscanner watch --watchlist sample_watchlists/warrior_lowfloat.txt
stockscanner watch --no-notifications

stockscanner scan                 # one-shot warrior scan (no loop)
stockscanner scan --strategy breakout --top 25
stockscanner enter AAPL --shares 50 --price 178.40
stockscanner positions            # check all open positions for exit signals
stockscanner close AAPL
```

A typical workflow: leave `stockscanner.exe` (or `watch`) running during the
trading day. When a toast pops up, decide if you want to take the trade; if you
do, place the order with your broker, then run `enter` to start tracking the
position. Run `positions` daily after the close — when it says EXIT, you exit
the next session.

## Universe

`scan` defaults to the S&P 500 (fetched from Wikipedia, cached for 7 days). Override
with `--watchlist path/to/tickers.txt` (one ticker per line). Lines starting with
`#` are ignored.

## Data source

Yahoo Finance via the `yfinance` package — free, no API key, ~15-min delayed
intraday but full daily/EOD coverage. Run scans **after the close** for the
cleanest signals.

## Limitations

- End-of-day daily bars only — no intraday alerts.
- Single-strategy: this is a momentum/breakout scanner. It will not flag mean-reversion
  setups, oversold bounces, or earnings plays.
- No order routing — it tells you what to do; you place the trades manually.
- Survivorship bias warning: the S&P 500 list is *current* membership. Backtests
  using this list will look better than reality.

## Files

- `main.py` — entry point used by both Python and the .exe build.
- `scanner/` — package: data, strategy, positions, universe, cli.
- `stockscanner.spec` — PyInstaller config (`--onefile`, no console deps).
- `build_windows.bat` — one-click Windows build script.
- `.github/workflows/build.yml` — CI: builds `stockscanner.exe` on every push.
