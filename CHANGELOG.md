# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Providers and fallback chains: accounts belong to a provider, `/p/{slug}/*`
  routes to a provider or chain, `/v1/*` follows the configurable default route.
- Provider presets: Serper, SerpApi, ScrapingDog, VALUE SERP, Brave Search.
- Runtime tunables (strategy, retries, reserve, cooldowns, refund kinds, timeout).
- Snake Charmer web UI served at `/ui`.
- Unified `serpent` command line.
- Responsible-use guidance (`docs/responsible-use.md`) with warnings in Snake Charmer
  and the CLI when several accounts share a provider.

- `serpent uninstall`: inventories the install, asks whether to keep your data, removes
  what the installer created and verifies the result (`--dry-run`, `--yes`, `--keep-data`,
  `--delete-data`). `install.sh` records what it created.

### Changed
- No provider is preconfigured any more. A fresh install starts empty; the first provider
  you add becomes the default route, and `/v1/*` answers 503 with instructions until then.
  `UPSTREAM_BASE_URL` still works to adopt an older single-upstream setup.
- Project renamed from "SERP Router" to Serpent; Python package is `serpent`
  (`serpent-router` on PyPI); Prometheus metrics are prefixed `serpent_`.

## 1.0.0
- Initial private release as "SERP Router": quota ledger, rotation strategies,
  failover, dashboard.
