# Stock Scanner

A command-line breakout scanner that flags stocks meeting a Minervini/Darvas-style
consolidation-breakout setup, gives you systematic entry/stop/target levels, and
tracks your open positions so it can tell you when to exit.

> **Important:** This is a screening tool, not financial advice. Most "breakouts"
> fail. The edge — if any — comes from cutting losses fast and letting winners run,
> not from prediction accuracy. Backtest before risking real money.

## What it does

- **`scan`** — screens a universe (default: S&P 500) for breakout setups today and
  prints the candidates plus suggested entry / stop-loss / target levels.
- **`enter`** — adds a position to the local tracker once you've actually opened it.
- **`positions`** — checks every open position against the exit rules and tells you
  which to **HOLD**, which to **EXIT**, and why.
- **`close`** — removes a position from the tracker.

## Strategy

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
stockscanner scan                 # scan default universe (S&P 500)
stockscanner scan --watchlist tickers.txt
stockscanner scan --top 25        # show only the strongest 25 candidates
stockscanner enter AAPL --shares 50 --price 178.40
stockscanner positions            # check all open positions for exit signals
stockscanner close AAPL
```

A typical workflow: run `scan` after the close → if anything qualifies, place the
order; once filled, run `enter`. Run `positions` daily after the close — when it
says EXIT, you exit the next session.

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
