# Terminal UI

A full-screen interface for everything the command line can do, without remembering any
commands. It runs in your terminal, over SSH, on a Raspberry Pi; it needs nothing installed
beyond Serpent itself.

## Launch it

```bash
cd /path/to/serpent       # the folder you cloned
./serpent
```

On the very first run `./serpent` sets Serpent up and opens the web interface instead; from the
second run it opens this UI. `./serpent tui` always opens it. It needs a real terminal (in a
script or pipe use the plain commands, `./serpent --help`) and Python's `curses`, which exists on
macOS and Linux but not Windows. If you symlinked the launcher onto your PATH
(`ln -s "$PWD/serpent" ~/.local/bin/serpent`) then just `serpent` works from anywhere.

## The layout

```
 ◆ SERPENT  ›  Accounts                                            ● running :8971
  1 Overview  2 Providers  3 Accounts  4 Chains  5 Keys  6 Requests  7 Logs  8 Manage
 ──────────────────────────────────────────────────────────────────────────────────
   period 2026-11     (* = cooling down)
 ▌  1  main     serpapi   ● active  ████░░░░░░░░░░  62/250  ****1111
    2  backup   serper    ● active  ░░░░░░░░░░░░░░   0/100  ****2222

  a add   e on/off   r reset quota   v reveal key   d delete   / filter   : commands   ? help
```

Top: the server state. Then the tabs. Then the screen. Bottom: the keys that work right now.

## Keys

| Key | Does |
| --- | --- |
| `1`–`8`, `Tab`, `Shift-Tab`, `←` `→` | switch screen |
| `↑` `↓` or `j` `k` | move; `PgUp` `PgDn` page; `g` `G` top and bottom |
| `Enter` | act on the highlighted row (usually opens its menu) |
| `/` | filter the list as you type; `Enter` keeps it, `Esc` clears it |
| `:` or `Ctrl-P` | **command palette**: type part of any action ("add acc", "backup", "uninstall") and press Enter |
| `?` | every key, including this screen's own shortcuts |
| `m` | mouse on or off (off lets you select and copy text in the terminal) |
| `q` | quit |
| `Esc` | close a dialog; clear a filter |

Mouse: click a tab to switch, click a row to select it (click it again to act), scroll with the
wheel. Each screen lists its own single-letter shortcuts on the bottom line (for example `a`
add, `e` enable or disable, `d` delete).

## The screens

| Screen | What it is for |
| --- | --- |
| **1 Overview** | Is it running, where, how many credits are used (gauge), how recent traffic looks (sparkline, success rate, median time). Start, stop, restart, open Snake Charmer, health check. |
| **2 Providers** | Add (from a preset or a custom URL), enable or disable, delete, choose the default route. |
| **3 Accounts** | Every API key with a usage gauge and status. Add (with the multiple-accounts reminder), enable or disable, reset usage, reveal, move to another provider, delete. |
| **4 Chains** | Fallback chains and the default route. Reminds you that a chain sends the same request to every step. |
| **5 Keys** | Router keys and provider keys, masked. Reveal, copy to the clipboard, replace a router key, copy the Snake Charmer sign-in link. |
| **6 Requests** | The last 300 calls, newest first, coloured by result. Filter by path, provider or account. |
| **7 Logs** | The server log, following the newest lines; errors in red. |
| **8 Manage** | Diagnostics, settings, data, deployment, and uninstall (below). |

## Manage

Housekeeping that otherwise needs a command you would have to look up. Nothing runs without
asking, and anything destructive asks first.

| Group | Action | What it does |
| --- | --- | --- |
| Diagnose | Doctor | Checks the environment and the server (same as `serpent doctor`). |
| | Last fault | What went wrong most recently, with a hint. |
| | Self-test | Boots a scratch copy on a throwaway database and checks the endpoints; takes about 10 seconds and touches none of your data. |
| | Install details | Folder, port, install time and version, and every file Serpent created with its size. |
| Settings | Rotation, retries, cooldowns, timeouts | Edit the runtime settings (strategy, extra accounts to try, credits kept in reserve, limit for new accounts, cooldowns, refund rules, provider timeout). Saved in the database; offers to restart the server so it takes effect. |
| Data | Back up the database | Online SQLite backup into `backups/` (private; safe while running; contains your provider keys). Same as `serpent backup`. |
| | Reset this month's usage | Zero the counters of every account. |
| | Clear the request history | Empties the list of past calls; credits are unaffected. |
| Deploy | Start at boot (systemd) | Writes a unit file with this machine's real paths and shows the `sudo` commands; Serpent never runs `sudo`. Linux only. |
| | Copy or move this install | Guided: destination (folder or `user@host:/path`), copy or move, include data and `.env`; shows the plan first, then asks again. |
| About | Version and paths | |
| Danger zone | **Uninstall Serpent…** | See below. |

### Uninstall from the terminal UI

1. It scans what the install created: the server, database, `.env`, backups, logs, runtime
   files, the virtual environment it made, any generated service file and the install record.
2. It asks **"Keep my data and settings?"**. Keeping (the default) preserves the database,
   `.env` and backups so you can redeploy elsewhere without re-entering anything. Deleting
   shows the size and later asks you to type `delete`.
3. It shows the plan (KEEP, REMOVE, STOP, MANUAL for each item) and asks for confirmation.
4. It removes what was agreed, **checks every item again** and shows OK or FAIL for each, then
   closes the UI.

It never deletes the source folder and never runs `sudo`; for system pieces (a systemd
service, a pip or pipx package) it prints the command for you to run. The same flow is
`serpent uninstall` on the command line.

## Appearance

It uses 256 colours when the terminal has them, 8 otherwise, and plain ASCII borders if the
terminal is not UTF-8. Set `NO_COLOR=1` for no colour. It needs at least 64×16 characters.

## Limits

- Screens refresh every few seconds on their own; the Requests and Logs screens follow new
  entries.
- The Settings editor saves to the database; the running server applies them after a restart
  (the web interface's Settings page applies them live).
- It cannot add Windows support: `curses` is not part of Windows Python.
