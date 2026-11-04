#!/usr/bin/env python3
"""Hammer the router from many connections and verify no overshoot.

Runs against a live instance, e.g.

    python scripts/concurrency_check.py http://127.0.0.1:8971 <client-key> --requests 300

A perfect result is 250 x HTTP 200 followed by 50 x HTTP 429 when a single
account has a 250-credit limit, with `used` landing exactly on 250.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx


async def one(client: httpx.AsyncClient, url: str, key: str, index: int) -> int:
    try:
        resp = await client.post(
            f"{url}/v1/search",
            headers={"X-Router-Key": key},
            json={"q": f"concurrency probe {index}"},
        )
        return resp.status_code
    except httpx.HTTPError as exc:  # pragma: no cover
        print(f"request {index} errored: {exc}", file=sys.stderr)
        return 0


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("key")
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=40)
    args = parser.parse_args()

    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    sem = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(timeout=30, limits=limits) as client:

        async def guarded(index: int) -> int:
            async with sem:
                return await one(client, args.url, args.key, index)

        codes = await asyncio.gather(*(guarded(i) for i in range(args.requests)))

    counts: dict[int, int] = {}
    for code in codes:
        counts[code] = counts.get(code, 0) + 1

    async with httpx.AsyncClient(timeout=30) as client:
        quota = (
            await client.get(f"{args.url}/v1/quota", headers={"X-Router-Key": args.key})
        ).json()

    print("status codes :", dict(sorted(counts.items())))
    print("credits used :", quota["quota_used_total"], "/", quota["quota_limit_total"])
    print("in flight    :", quota["in_flight"])

    overshoot = quota["quota_used_total"] > quota["quota_limit_total"]
    if overshoot:
        print("FAIL: quota was overshoot")
        return 1
    if counts.get(200, 0) != quota["quota_used_total"]:
        print("FAIL: 200-count does not match the ledger")
        return 1
    print("OK: the ledger matches the number of successful calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
