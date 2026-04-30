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
`%USERPROFILE%\.stockscanner\` (cache, positions, last scan, API keys).

## Real-time data (optional but strongly recommended for `warrior`)

Yahoo's free feed is ~15 minutes delayed, which means you usually see Warrior-style
gappers after the first leg of the move. Wire in **Finnhub's free tier** for
real-time prices:

1. Sign up at https://finnhub.io/register (free)
2. Copy your API key from the dashboard
3. Run once: `stockscanner config --finnhub-key YOUR_KEY_HERE`

The watch loop now uses Finnhub for live prices (~1s latency) and falls back to
yfinance for the 50-day average volume baseline (still 15-min delayed — Finnhub's
free tier doesn't expose intraday volume). The price-driven parts of the strategy
(gap %, intraday range, current price vs. levels) become real-time, which is the
piece that matters most for catching a setup before it runs.

The free tier caps you at 60 API calls/minute; the scanner self-throttles to 55.
A 50-ticker watchlist polled every minute fits comfortably. If you want to scan
the full S&P 500 in real-time, you'd need Finnhub's paid plan or Polygon.io.

```
stockscanner config --show              # check current settings
stockscanner config --clear-finnhub-key # back to delayed yfinance only
```

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

## Universe & watchlists

There are three ways to tell the scanner what to scan, in priority order:

1. **`--screen <name>`** — pull a live universe from Yahoo's predefined screens
   (`day_gainers`, `most_actives`, `small_cap_gainers`, etc.). The list refreshes
   every cycle, so the scanner automatically follows the stocks moving today.
   This is the recommended setup for Warrior-style day trading.
2. **`--watchlist <name-or-path>`** — your own static list.
3. **`%USERPROFILE%\.stockscanner\watchlists\default.txt`** — auto-loaded if it
   exists and you didn't pass `--screen` or `--watchlist`.
4. **S&P 500** — fallback when nothing else is configured.

**Default double-click behavior**: `watch --strategy warrior --screen day_gainers`.
You don't need to set anything up — open the .exe and the scanner tracks the
day's top gainers, alerting when one matches the Warrior gap+volume setup.

To see all available screens:

```
stockscanner watch --list-screens
```

Common picks:
- `day_gainers` — biggest % gainers today (default)
- `most_actives` — heaviest volume today
- `small_cap_gainers` — small-cap names up the most
- `most_shorted_stocks` — squeeze candidates

You don't have to pass a full path for static lists. Drop your `.txt` files into
`%USERPROFILE%\.stockscanner\watchlists\` and reference them by name:

```
stockscanner watch --watchlist warrior_lowfloat
stockscanner watch --watchlist my_movers.txt
```

Easiest way to seed that folder:

```
stockscanner watchlists --install-sample
```

That copies the bundled `warrior_lowfloat.txt` to your watchlists folder AND
sets it as the double-click default (`default.txt`). After that, double-clicking
`stockscanner.exe` runs the watch loop on that list automatically.

To list / inspect what's there:

```
stockscanner watchlists
```

Watchlist file format: one ticker per line. Blank lines and lines starting with
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
