// The in-app Help. Authored as data so it can be searched, tested and filled in with the live
// setup (address, provider names). Inline markup: `code`, **bold**, [text](https://url).
// The long-form versions live in docs/ in the repository.

export type Block =
  | { t: 'p'; text: string }
  | { t: 'h'; text: string }
  | { t: 'ul'; items: string[] }
  | { t: 'ol'; items: string[] }
  | { t: 'code'; text: string; label?: string }
  | { t: 'table'; head: string[]; rows: string[][] }
  | { t: 'note'; text: string; kind?: 'warn' };

export interface Section { id: string; title: string; lede: string; blocks: Block[] }

export interface Ctx {
  origin: string;
  defaultRoute: string;
  slug: string;        // a provider to use in examples
  preset: string;      // its preset, if any
  hasProvider: boolean;
}

export const DOCS = 'https://github.com/d-robin/serpent/blob/main/docs';

function example(c: Ctx): { curl: string; python: string } {
  const key = '"X-Router-Key: $SERPENT_KEY"';
  if (c.preset === 'serper') {
    return {
      curl: `curl -X POST -H ${key} -H 'Content-Type: application/json' \\\n  -d '{"q":"coffee shops austin"}' \\\n  ${c.origin}/p/${c.slug}/search`,
      python: `r = requests.post(\n    f"{BASE}/p/${c.slug}/search",\n    json={"q": query},\n    headers=HEADERS, timeout=40,\n)`,
    };
  }
  if (c.preset === 'serpapi') {
    return {
      curl: `curl -H ${key} \\\n  "${c.origin}/p/${c.slug}/search?engine=google&q=coffee+shops+austin"`,
      python: `r = requests.get(\n    f"{BASE}/p/${c.slug}/search",\n    params={"engine": "google", "q": query},\n    headers=HEADERS, timeout=40,\n)`,
    };
  }
  return {
    curl: `curl -H ${key} \\\n  "${c.origin}/p/${c.slug}/<path the provider documents>"`,
    python: `r = requests.get(\n    f"{BASE}/p/${c.slug}/<path>",\n    params={...},\n    headers=HEADERS, timeout=40,\n)`,
  };
}

export function sections(c: Ctx): Section[] {
  const ex = example(c);
  return [
    {
      id: 'start', title: 'Start and run', lede: 'Get it running, and keep it running.',
      blocks: [
        { t: 'code', label: 'first run, from the folder you cloned', text: './serpent' },
        { t: 'p', text: 'The first run creates a private environment, generates your router keys, starts the server and opens this interface already signed in. Run `./serpent` again in a terminal and it opens the **terminal UI**.' },
        { t: 'table', head: ['Command', 'Does'], rows: [
          ['`./serpent up`', 'start (or report it is already running) and print the sign-in link'],
          ['`serpent status`', 'pid, address, uptime, memory, accounts, last fault'],
          ['`serpent stop` / `restart`', 'stop, or stop then start (after editing `.env`)'],
          ['`serpent log -f`', 'follow the server log'],
          ['`serpent doctor`', 'check the environment and the server'],
          ['`serpent keys`', 'show or recover keys (`--reveal` for full values)'],
        ] },
        { t: 'p', text: '**One folder, one server, one port.** Each install remembers its port (it starts at `8971` and moves up if busy). Starting it again reports that it is already running.' },
        { t: 'h', text: 'Which way to run it' },
        { t: 'table', head: ['How', 'Survives a reboot', 'Good for'], rows: [
          ['`./serpent up` (background)', 'No', 'a laptop, trying it out'],
          ['`serpent run` (foreground)', 'No', 'debugging'],
          ['systemd (`serpent systemd --out serpent.service`)', 'Yes', 'a Raspberry Pi or Linux server'],
          ['Docker (`--restart unless-stopped`)', 'Yes', 'containers, NAS, cloud'],
        ] },
        { t: 'note', text: 'After a reboot a background copy is **not** running. Start it again with `./serpent up`, or use systemd or Docker.' },
      ],
    },
    {
      id: 'connect', title: 'Connect an app', lede: 'Everything an app needs: an address, a client key and a route.',
      blocks: [
        { t: 'table', head: ['You need', 'Where it comes from'], rows: [
          ['Address', `\`${c.origin}\` (from this page; \`serpent status\` prints it)`],
          ['A **client key**', '`serpent keys --reveal`, or `.env`. Not the admin key, and never a provider key.'],
          ['A route', c.hasProvider ? `\`/p/${c.slug}/…\` for the provider you added (see **Providers**)` : 'add a provider first (**Providers**), then use `/p/<slug>/…`'],
        ] },
        { t: 'p', text: 'Keep the key in an environment variable, never in source code or chat:' },
        { t: 'code', text: `export SERPENT_URL=${c.origin}\nexport SERPENT_KEY=<your client key>` },
        { t: 'h', text: 'A first call' },
        { t: 'code', label: 'curl', text: ex.curl },
        { t: 'code', label: 'python', text: `import os, requests\nBASE, KEY = os.environ["SERPENT_URL"], os.environ["SERPENT_KEY"]\nHEADERS = {"X-Router-Key": KEY}\n\n${ex.python}\nif r.status_code == 429:          # nothing left to spend, or rate limited\n    raise RuntimeError("retry after " + r.headers.get("Retry-After", "?") + " s")\nr.raise_for_status()\nprint(r.json())` },
        { t: 'ul', items: [
          'Send the key as `X-Router-Key: <key>` or `Authorization: Bearer <key>`.',
          '`/p/<slug>/…` goes to that provider or chain. `/v1/…` goes to the **default route** (' + (c.defaultRoute ? `currently \`${c.defaultRoute}\`` : 'none yet') + '). Prefer the explicit form.',
          '**Serpent does not translate between providers.** Send each route the request that provider documents; the response is the provider\'s own, unchanged.',
        ] },
        { t: 'h', text: 'Errors' },
        { t: 'table', head: ['Status', 'Meaning', 'Do this'], rows: [
          ['401 / 403', 'wrong or missing key / role too low', 'check the header and the key'],
          ['404', 'no such route, or the provider rejected the path', 'check the slug and the provider\'s docs'],
          ['429', 'no credits left, or the rate limit', 'stop and wait for `Retry-After`; never loop'],
          ['502', 'the provider could not be reached', 'retry later with backoff'],
          ['503', 'no provider, or none enabled on the route', 'fix the setup'],
        ] },
        { t: 'p', text: 'Useful response headers: `X-Router-Provider`, `X-Router-Account`, `X-Quota-Remaining`, `X-Quota-Reset-In`, `X-Cache: HIT`, `X-Request-Id`. Before a batch, `POST /v1/quota/check {"count": 50}` answers `409` if you cannot afford it.' },
        { t: 'p', text: `More languages and habits: [Connect apps and agents](${DOCS}/connecting.md).` },
      ],
    },
    {
      id: 'agents', title: 'Connect an AI agent', lede: 'Give it the contract, a small tool and a budget.',
      blocks: [
        { t: 'ol', items: [
          `**Hand it the contract, not guesses.** \`${c.origin}/v1/contract\` is generated from this setup: routes, parameters, examples, errors. It needs the client key (add \`?format=json\` for JSON). \`/llms.txt\` is an open pointer for AI tools.`,
          'Open **Integrate** for a ready-to-paste prompt (it contains no key) or the full contract text.',
          'Define **one small tool** (for example `web_search(query, engine)`) that calls the route above. Read the key from the environment inside the tool; the model never sees it.',
          'Put limits in the tool: a maximum number of calls per task, stop on `429`, return errors to the model instead of retrying.',
        ] },
        { t: 'code', label: 'tool definition (JSON schema style)', text: '{\n  "name": "web_search",\n  "description": "Search the web through the Serpent router. Each call costs one credit.",\n  "input_schema": {\n    "type": "object",\n    "properties": { "query": { "type": "string" } },\n    "required": ["query"]\n  }\n}' },
        { t: 'note', kind: 'warn', text: `A router on \`127.0.0.1\` can only be reached by software on this computer. A cloud-hosted agent cannot call it: run the agent locally, expose Serpent deliberately (see **Deploy**), or paste the contract text instead of a URL. Serpent does not ship an MCP server; wrap the HTTP tool if your framework wants one.` },
      ],
    },
    {
      id: 'how', title: 'How it works', lede: 'The parts, and what happens to one request.',
      blocks: [
        { t: 'p', text: 'One Python process, one SQLite file. Apps call Serpent with **one router key**; Serpent picks one of your provider accounts, adds that account\'s key, forwards the request, retries on another account if it fails, and counts every credit.' },
        { t: 'ol', items: [
          '**Authenticate** the caller (client role), rate-limit, validate the path and size.',
          '**Resolve the route** (`/p/<slug>` or the default) to an ordered list of enabled providers; a chain has several.',
          '**Cache** (optional, off by default): an identical request costs nothing.',
          '**Reserve** one credit from a healthy account in a `BEGIN IMMEDIATE` SQLite transaction, so two callers can never overshoot a limit.',
          '**Forward** with that account\'s key. On success keep the credit; on a failure refund it, cool the account down and retry another.',
          '**Respond** with the provider\'s answer plus headers saying who answered and how many credits remain.',
        ] },
        { t: 'table', head: ['Term', 'Meaning'], rows: [
          ['Provider', 'one search API: its address and how its key is attached'],
          ['Account', 'one API key at a provider, with the limit **you** set'],
          ['Chain', 'providers tried in order; the same request goes to every step'],
          ['Router key', 'what apps and people use to talk to Serpent (`read`, `client`, `admin`)'],
          ['Home', 'the folder holding one install\'s settings and data'],
        ] },
        { t: 'p', text: 'An install is one folder: `.env` (settings, router keys), `data/serpent.db` (accounts, provider keys, usage, history), `logs/`, `run/`, `backups/`, `.venv/`. Provider keys are stored on this machine in a file only your user can read; they are never shown in full by the UI or API.' },
        { t: 'p', text: `Deeper: [Architecture](${DOCS}/architecture.md).` },
      ],
    },
    {
      id: 'deploy', title: 'Deploy', lede: 'Laptop, Raspberry Pi, server or container.',
      blocks: [
        { t: 'code', label: 'systemd (Linux)', text: 'serpent stop                              # the service will run it instead\nserpent systemd --out serpent.service\nsudo cp serpent.service /etc/systemd/system/serpent.service\nsudo systemctl daemon-reload\nsudo systemctl enable --now serpent\njournalctl -u serpent -f' },
        { t: 'code', label: 'Docker', text: 'docker build -t serpent .\ndocker run -d --name serpent -p 8971:8971 \\\n  -v serpent-data:/data \\\n  -e ROUTER_KEYS=\'admin-key:admin,client-key:client\' \\\n  --restart unless-stopped serpent' },
        { t: 'ul', items: [
          'Run it **one way at a time** per install; two would want the same port.',
          'Serpent listens on `127.0.0.1`. For the LAN use `--host 0.0.0.0` (or `BIND_HOST`); for the internet put HTTPS in front (Caddy or nginx) and set `TRUST_PROXY=true`. Keys travel in headers, so never plain HTTP over the internet.',
          'About 60 to 70 MB idle; one worker handles hundreds of requests a minute. `--workers 2` is safe because credits are reserved in SQLite.',
          'In Docker keep the `/data` volume: it holds your accounts.',
        ] },
        { t: 'p', text: `Details: [Deploying](${DOCS}/deploying.md) and [Run and operate](${DOCS}/operations.md).` },
      ],
    },
    {
      id: 'logs', title: 'Logs and monitoring', lede: 'Where to look, and what is (and is not) recorded.',
      blocks: [
        { t: 'table', head: ['Setup', 'Read the log with'], rows: [
          ['background daemon', '`serpent log -f` or `logs/router.log` (rotated at 2 MB)'],
          ['foreground', 'your terminal'],
          ['systemd', '`journalctl -u serpent -f`'],
          ['Docker', '`docker logs -f serpent`'],
          ['terminal UI', 'the **Logs** tab'],
          ['this interface', '**Requests** (every call) and **Overview**'],
        ] },
        { t: 'p', text: 'One JSON object per line, with a `request_id` to follow a call end to end (`grep <id> logs/router.log`). Provider keys, request bodies and responses are **never** logged; the Requests tab shows method, path and query (credential-like parameters removed), provider, account, status and time. Set `LOG_LEVEL=debug` in `.env` for more.' },
        { t: 'table', head: ['Endpoint', 'Meaning'], rows: [
          ['`/healthz`', 'the process is up (always 200)'],
          ['`/readyz`', '200 when at least one credit is spendable, else 503'],
          ['`/metrics`', 'Prometheus text (a read key when authentication is on)'],
          ['`/v1/quota`', 'totals and reset time'],
        ] },
        { t: 'p', text: '`serpent fault` shows the last start or stop problem with a hint; `serpent doctor` checks everything at once.' },
      ],
    },
    {
      id: 'troubleshoot', title: 'Troubleshooting', lede: 'Symptom, likely cause, fix.',
      blocks: [
        { t: 'code', label: 'start with these', text: 'serpent status\nserpent doctor\nserpent fault\nserpent log -n 80' },
        { t: 'table', head: ['Symptom', 'Fix'], rows: [
          ['`already running`', 'It is up. `serpent status` shows where; `./serpent up` prints the sign-in link.'],
          ['started on another port', 'The first was busy. Use the printed address, or pin one with `--port`.'],
          ['`401` from a call', 'Wrong or missing router key. Send `X-Router-Key: <client key>`.'],
          ['`404` from a call', 'Wrong slug, or the request shape is wrong for that provider (SerpApi is GET with the query in the URL; Serper is POST with a JSON body).'],
          ['`429` straight away', 'Out of credits, or accounts are cooling down or invalid. Open **Accounts** and read the status column.'],
          ['an account is **invalid**', 'The provider rejected its key. Fix the key, then enable the account.'],
          ['"No capacity"', 'No account can serve right now. See **Accounts**.'],
          ['Search shows no results', 'Open **Raw response**. Providers differ; set the request under *Request options*.'],
          ['not running after a reboot', 'Background copies do not survive one. Use systemd or Docker, or start it again.'],
          ['lost the admin key', '`serpent keys --reveal`, or `serpent keys rotate admin` and restart.'],
          ['UI says "isn\'t built yet"', 'A checkout without the bundle: `cd ui && npm ci && npm run build`.'],
        ] },
        { t: 'p', text: `More, including Docker, systemd and the terminal UI: [Troubleshooting](${DOCS}/troubleshooting.md). To ask for help, share \`serpent version\`, \`serpent doctor --json\` and the request id of a failing call; never share keys or the sign-in link.` },
      ],
    },
    {
      id: 'move', title: 'Back up, move and upgrade', lede: 'Your data is two things: `data/` and `.env`.',
      blocks: [
        { t: 'code', text: 'serpent backup        # online copy into backups/ (safe while running; contains provider keys)' },
        { t: 'code', label: 'move to another folder or machine', text: 'serpent move user@host:/opt/serpent --with-data --with-env --dry-run   # preview first\nserpent move user@host:/opt/serpent --with-data --with-env             # then do it' },
        { t: 'ul', items: [
          '`--with-data` carries the database (accounts, usage); `--with-env` carries `.env` (router keys). Without them the new copy starts fresh.',
          '`--move` removes the original only after the new copy boots and verifies. Stop Serpent before `--with-data`.',
          'To restore a backup: stop, put the file at `data/serpent.db` (delete stale `-wal`/`-shm` files), start.',
        ] },
        { t: 'code', label: 'upgrade', text: 'git pull\n.venv/bin/pip install -e .    # only if dependencies changed\nserpent restart\nserpent doctor' },
      ],
    },
    {
      id: 'uninstall', title: 'Uninstall', lede: 'Removes only what the install created, and checks that it did.',
      blocks: [
        { t: 'code', text: 'serpent uninstall            # asks, removes, then verifies\nserpent uninstall --dry-run  # preview only' },
        { t: 'ol', items: [
          'It lists what it found: the server, database, `.env`, backups, logs, runtime files, the environment it created, any generated service file and the install record.',
          'It asks whether to **keep your data** (default). Keeping it lets you redeploy elsewhere without re-entering anything. Deleting needs `--delete-data` or typing `delete`.',
          'It removes what was agreed, **re-checks every item** and prints OK or FAIL for each.',
        ] },
        { t: 'p', text: 'It never deletes the source folder and never runs `sudo`; for a systemd service or a pip/pipx package it prints the command for you to run. The terminal UI has the same flow under **Manage → Uninstall**.' },
      ],
    },
    {
      id: 'keys', title: 'Keys and security', lede: 'Two kinds of keys, three roles.',
      blocks: [
        { t: 'table', head: ['Role', 'Can'], rows: [
          ['`read`', 'look at status, quota and history'],
          ['`client`', 'also send requests through the router and read the contract'],
          ['`admin`', 'also change providers, accounts, chains and settings'],
        ] },
        { t: 'ul', items: [
          '**Router keys** (yours, in `.env`) let callers use Serpent. **Provider keys** (in the database) are used only by the server and never sent to callers.',
          'The sign-in link contains the admin key. Anyone who sees it is an admin. Rotate with `serpent keys rotate admin` if it leaks.',
          'Provider keys are stored as plain text in a file only your user can read. Treat `data/` and `backups/` like a password file, and keep them out of sync folders and git.',
          'If `ROUTER_KEYS` is empty there is no authentication at all; this page shows a warning when that is the case.',
        ] },
        { t: 'p', text: `More: [Things to know](${DOCS}/important-things.md).` },
      ],
    },
    {
      id: 'shortcuts', title: 'Shortcuts and tips', lede: 'Faster ways around this interface.',
      blocks: [
        { t: 'table', head: ['Keys', 'Does'], rows: [
          ['`Ctrl` / `Cmd` + `K`', 'command palette: jump anywhere or run an action'],
          ['`g` then `o` `s` `r` `p` `a` `c` `i` `w` `e` `h`', 'go to Overview, Search, Requests, Providers, Accounts, Chains, Integrate, Raw request, Settings, Help'],
          ['`/`', 'go to Search'],
          ['`Esc`', 'close a panel or dialog'],
        ] },
        { t: 'ul', items: [
          'The sun/moon button switches between light and dark. Light is the default.',
          'Prefer a terminal? Run `./serpent` for the terminal UI, which does the same jobs.',
        ] },
      ],
    },
  ];
}

/** Plain text of a section, for searching. */
export function plain(s: Section): string {
  const parts: string[] = [s.title, s.lede];
  for (const b of s.blocks) {
    if (b.t === 'p' || b.t === 'h' || b.t === 'note' || b.t === 'code') parts.push(b.text);
    else if (b.t === 'ul' || b.t === 'ol') parts.push(...b.items);
    else if (b.t === 'table') parts.push(...b.head, ...b.rows.flat());
  }
  return parts.join(' ').replace(/[`*]/g, '').toLowerCase();
}

/** Escape, then apply the small inline markup. Output is safe for {@html}. */
export function inline(text: string): string {
  const esc = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return esc
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}
