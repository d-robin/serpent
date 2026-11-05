# Contributing

Thanks for helping. Small, focused pull requests are easiest to review.

## Setup

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest && .venv/bin/ruff check src tests
cd ui && npm ci && npm test && npm run build
```

## Ground rules

- **Commit the built UI.** `src/serpent/ui_dist/` is checked in so a plain `git clone` plus
  `./serpent` works without Node. After changing anything in `ui/`, run
  `npm run build` and commit the result; CI fails if it is stale.
- **Tests with behaviour changes.** The suite never touches the network; inject an
  `httpx.MockTransport` (see `tests/conftest.py`).
- **Keep the footprint small.** No new runtime dependency without a strong reason;
  Serpent has to stay happy on a Raspberry Pi. The UI must stay offline-capable
  (no CDN, no web fonts).
- **Quota correctness is the product.** Anything touching `quota.py` needs a test
  and, if it changes reservation or settlement, a run of
  `scripts/concurrency_check.py`.
- **Never log or return provider keys.** Only `****last4` hints leave the server.
- Style: `ruff check` clean, type hints on new code, comments explain *why*.

## Pull requests

1. Open an issue first for anything larger than a bug fix.
2. Branch from `main`, one concern per PR, update `CHANGELOG.md` under *Unreleased*.
3. CI (lint, tests, UI build, Docker build) must pass.

By contributing you agree your work is licensed under Apache-2.0, as in `LICENSE`.
