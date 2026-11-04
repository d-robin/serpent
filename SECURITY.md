# Security policy

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting
(Security tab -> *Report a vulnerability*) on this repository, or email the
maintainer address listed on the GitHub profile of the repository owner. You will
get an acknowledgement within a few days.

## Supported versions

Only the latest release receives fixes while the project is pre-2.0.

## Deployment guidance

- Set `ROUTER_KEYS` before exposing Serpent beyond localhost. With it empty,
  everything is unauthenticated (the server logs a warning).
- Serpent speaks plain HTTP. Put Caddy, nginx or a tunnel in front for TLS and set
  `TRUST_PROXY=true` only behind a proxy you control.
- Provider keys are stored **unencrypted** in the SQLite file (`data/`). Keep it
  out of sync folders and backups you do not trust; `.env` should be mode 600.
- Use a `client` key in applications and keep the `admin` key for Snake Charmer
  and the CLI.
- Snake Charmer keeps the admin key in `sessionStorage` of that tab only.
