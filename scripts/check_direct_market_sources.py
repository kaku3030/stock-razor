#!/usr/bin/env python3
"""Read-only smoke check for Tencent/Sina research fallbacks.

This script performs no trading or persistence. It is intentionally opt-in because
both providers are public endpoints and may be rate-limited.
"""
from __future__ import annotations

import argparse
from typing import Iterable

from data_provider import SinaResearchFetcher, TencentFetcher


def check(fetchers: Iterable[object], symbol: str, days: int) -> int:
    failures = 0
    for fetcher in fetchers:
        name = getattr(fetcher, "name", type(fetcher).__name__)
        try:
            frame = fetcher.get_daily_data(symbol, days=days)
            print(f"{name}: rows={len(frame)} columns={','.join(frame.columns)}")
        except Exception as exc:  # diagnostic script: report all providers
            failures += 1
            print(f"{name}: ERROR {type(exc).__name__}: {exc}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="600000", help="A-share code, e.g. 600000")
    parser.add_argument("--days", type=int, default=5)
    args = parser.parse_args()
    if args.days <= 0:
        parser.error("--days must be positive")
    return check((TencentFetcher(), SinaResearchFetcher()), args.symbol, args.days)


if __name__ == "__main__":
    raise SystemExit(main())
