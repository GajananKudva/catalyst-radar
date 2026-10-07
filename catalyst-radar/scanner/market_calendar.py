"""IST clock helpers and the run gate used by GitHub Actions.

NSE holidays are not hard-coded: the scanner treats a day as a trading day only
if Nifty 50 (^NSEI) has a bar for it. This module only does the cheap
weekday / time-of-day check so off-hours Actions runs exit in seconds.

CLI (used in the workflows):
    python -m scanner.market_calendar --job intraday
prints run=true|false and appends it to $GITHUB_OUTPUT when present.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, time, timedelta

import config


def now_ist() -> datetime:
    return datetime.now(config.IST)


def _t(hm: tuple[int, int]) -> time:
    return time(hm[0], hm[1])


def market_phase(now: datetime | None = None) -> str:
    """Return 'weekend', 'pre', 'open', 'closing' or 'post' for an IST datetime."""
    now = now or now_ist()
    if now.weekday() >= 5:
        return "weekend"
    t = now.time()
    open_t = _t(config.MARKET_OPEN)
    close_t = _t(config.MARKET_CLOSE)
    grace_end = (datetime.combine(now.date(), close_t) + timedelta(minutes=config.INTRADAY_GRACE_MIN)).time()
    if t < open_t:
        return "pre"
    if t <= close_t:
        return "open"
    if t <= grace_end:
        return "closing"
    return "post"


def elapsed_fraction(now: datetime | None = None) -> float:
    """Share of the trading session elapsed (0.05 .. 1.0); used for volume pace."""
    now = now or now_ist()
    start = datetime.combine(now.date(), _t(config.MARKET_OPEN), tzinfo=now.tzinfo)
    minutes = (now - start).total_seconds() / 60
    return float(min(1.0, max(0.05, minutes / config.SESSION_MINUTES)))


def should_run(job: str, now: datetime | None = None) -> bool:
    phase = market_phase(now)
    if job == "intraday":
        return phase in ("open", "closing")
    if job == "nightly":
        return phase not in ("weekend",)
    raise ValueError(f"unknown job {job!r}")


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", choices=["intraday", "nightly"], required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    run = args.force or should_run(args.job)
    line = f"run={'true' if run else 'false'}"
    print(f"{line}  (IST now {now_ist():%Y-%m-%d %H:%M}, phase={market_phase()})")
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


if __name__ == "__main__":
    _main()
