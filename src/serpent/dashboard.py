"""Server-rendered status dashboard.  No CDN, no build step, no fonts to fetch."""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Serpent</title>
<style>
  :root {
    --bg:#0b0f14; --panel:#121a23; --panel2:#0e151d; --line:#22303d;
    --text:#e6edf3; --dim:#8b9cad; --accent:#4fd1c5; --accent2:#7c9cff;
    --warn:#f6ad55; --bad:#f56565; --ok:#48bb78;
    --mono: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  a { color:var(--accent2); text-decoration:none; }
  .wrap { max-width:1180px; margin:0 auto; padding:22px 18px 60px; }
  header { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; margin-bottom:18px; }
  h1 { font-size:19px; margin:0; letter-spacing:.2px; font-weight:600; }
  h1 span { color:var(--accent); }
  .sub { color:var(--dim); font-size:12px; font-family:var(--mono); }
  .spacer { flex:1; }
  .keybox { display:flex; gap:6px; align-items:center; }
  input, button, select {
    background:var(--panel2); color:var(--text); border:1px solid var(--line);
    border-radius:7px; padding:7px 10px; font-size:12.5px; font-family:inherit;
  }
  input:focus, select:focus { outline:none; border-color:var(--accent2); }
  button { cursor:pointer; transition:border-color .15s, background .15s; }
  button:hover { border-color:var(--accent2); }
  button.primary { background:#1b3a4b; border-color:#2b5b74; }
  button.tiny { padding:3px 8px; font-size:11.5px; }
  button.danger:hover { border-color:var(--bad); color:var(--bad); }
  .grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fit, minmax(190px,1fr)); }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:11px; padding:14px 15px; }
  .card .label { color:var(--dim); font-size:11px; text-transform:uppercase; letter-spacing:.7px; }
  .card .value { font-size:25px; font-weight:600; margin-top:5px; font-variant-numeric:tabular-nums; }
  .card .foot { color:var(--dim); font-size:11.5px; margin-top:3px; font-family:var(--mono); }
  .bar { height:7px; border-radius:4px; background:#1d2833; overflow:hidden; margin-top:10px; }
  .bar > i { display:block; height:100%; border-radius:4px; background:linear-gradient(90deg,var(--accent),var(--accent2)); }
  .bar.warn > i { background:linear-gradient(90deg,#f6ad55,#ed8936); }
  .bar.bad > i { background:linear-gradient(90deg,#f56565,#c53030); }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.9px; color:var(--dim);
       margin:30px 0 10px; font-weight:600; }
  table { width:100%; border-collapse:collapse; background:var(--panel);
          border:1px solid var(--line); border-radius:11px; overflow:hidden; }
  th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.6px;
       color:var(--dim); font-weight:600; padding:10px 11px; background:var(--panel2);
       border-bottom:1px solid var(--line); white-space:nowrap; }
  td { padding:10px 11px; border-bottom:1px solid #1a232d; font-size:13px; vertical-align:middle; }
  tr:last-child td { border-bottom:none; }
  td.num { font-family:var(--mono); font-variant-numeric:tabular-nums; }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px;
          font-weight:600; letter-spacing:.3px; }
  .pill.active { background:#14301f; color:var(--ok); }
  .pill.disabled { background:#2a2a2a; color:var(--dim); }
  .pill.invalid { background:#3a1c1c; color:var(--bad); }
  .pill.cooling { background:#3a2c14; color:var(--warn); }
  .muted { color:var(--dim); }
  .mono { font-family:var(--mono); }
  .row-actions { display:flex; gap:5px; justify-content:flex-end; }
  .empty { padding:26px; text-align:center; color:var(--dim); }
  .form { display:none; gap:9px; flex-wrap:wrap; margin-top:12px;
          background:var(--panel); border:1px solid var(--line); border-radius:11px; padding:14px; }
  .form.open { display:flex; }
  .form input[type=text], .form input[type=password] { flex:1 1 200px; }
  .hint { color:var(--dim); font-size:11.5px; margin-top:8px; font-family:var(--mono); }
  #toast { position:fixed; bottom:18px; left:50%; transform:translateX(-50%);
           background:#1c2833; border:1px solid var(--line); border-radius:9px;
           padding:10px 16px; font-size:12.5px; opacity:0; pointer-events:none;
           transition:opacity .2s; z-index:50; }
  #toast.show { opacity:1; }
  .dot { width:7px; height:7px; border-radius:50%; background:var(--ok); display:inline-block;
         margin-right:6px; animation:pulse 2s infinite; }
  .dot.off { background:var(--bad); animation:none; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
  .scroll { overflow-x:auto; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span>SERP</span> Router</h1>
    <div class="sub" id="upstream">&mdash;</div>
    <div class="spacer"></div>
    <a href="/ui/" style="font-size:12.5px">Snake Charmer &rarr;</a>
    <div class="keybox">
      <input type="password" id="key" placeholder="admin key" style="width:170px">
      <button id="savekey" class="tiny">Save</button>
      <button id="addbtn" class="tiny primary">+ Account</button>
    </div>
  </header>

  <div class="grid" id="summary"></div>

  <div class="form" id="addform">
    <input type="text" id="f-label" placeholder="label (e.g. acme-1)">
    <input type="password" id="f-key" placeholder="provider api key">
    <input type="text" id="f-limit" placeholder="limit (250)" style="width:110px">
    <button class="primary" id="f-save">Add account</button>
    <button id="f-cancel">Cancel</button>
  </div>

  <h2>Accounts</h2>
  <div class="scroll">
  <table>
    <thead>
      <tr>
        <th>#</th><th>Label</th><th>Status</th><th>Key</th>
        <th style="width:190px">Quota</th><th>Used</th><th>Avail</th>
        <th>In&nbsp;flight</th><th>OK</th><th>Fail</th><th>Avg&nbsp;ms</th>
        <th>Last used</th><th></th>
      </tr>
    </thead>
    <tbody id="accounts"><tr><td colspan="13" class="empty">loading&hellip;</td></tr></tbody>
  </table>
  </div>
  <div class="hint" id="strategy"></div>

  <h2>Recent requests</h2>
  <div class="scroll">
  <table>
    <thead><tr><th>Time</th><th>Method</th><th>Path</th><th>Status</th>
      <th>Account</th><th>ms</th><th>Client</th><th>Note</th></tr></thead>
    <tbody id="requests"><tr><td colspan="8" class="empty">no requests yet</td></tr></tbody>
  </table>
  </div>

  <div class="hint" id="footer"></div>
</div>
<div id="toast"></div>
<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtTime = (iso) => {
  if (!iso) return "\\u2014";
  const d = new Date(iso);
  if (isNaN(d)) return esc(iso);
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s/60) + "m ago";
  if (s < 86400) return Math.floor(s/3600) + "h ago";
  return d.toLocaleString();
};
const fmtEta = (sec) => {
  if (sec == null) return "\\u2014";
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  if (d) return d + "d " + h + "h";
  if (h) return h + "h " + m + "m";
  return m + "m";
};
const toast = (msg, bad) => {
  const t = $("toast");
  t.textContent = msg;
  t.style.borderColor = bad ? "var(--bad)" : "var(--line)";
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 2600);
};
const getKey = () => sessionStorage.getItem("serpent_key") || $("key").value.trim();
const headers = () => {
  const k = getKey();
  return k ? {"X-Router-Key": k, "Content-Type": "application/json"} : {"Content-Type": "application/json"};
};

async function api(path, opts) {
  const r = await fetch(path, Object.assign({headers: headers()}, opts || {}));
  if (r.status === 401 || r.status === 403) throw new Error("admin key required");
  if (!r.ok) {
    let detail = "HTTP " + r.status;
    try { const j = await r.json(); detail = j.detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return r.status === 204 ? null : r.json();
}

function summaryCards(s) {
  const pct = s.quota_limit_total ? Math.round(100 * s.quota_used_total / s.quota_limit_total) : 0;
  const barClass = pct > 90 ? "bar bad" : pct > 70 ? "bar warn" : "bar";
  const cards = [
    ["Accounts", s.accounts_total, s.accounts_active + " active \\u00b7 " + s.accounts_usable + " usable"],
    ["Quota available", s.quota_available_total,
     s.quota_used_total + " used of " + s.quota_limit_total + " \\u00b7 " +
     s.accounts_usable + "/" + s.accounts_total + " accounts usable"],
    ["Resets in", fmtEta(s.resets_in_seconds), new Date(s.resets_at).toLocaleString()],
    ["Served", s.requests_ok, s.requests_failed + " failed \\u00b7 " + s.requests_refunded + " refunded"],
  ];
  let html = cards.map(([label, value, foot]) =>
    '<div class="card"><div class="label">' + label + '</div><div class="value">' +
    esc(value) + '</div><div class="foot">' + esc(foot) + '</div>' +
    (label === "Quota available"
      ? '<div class="' + barClass + '"><i style="width:' + pct + '%"></i></div>'
      : "") + '</div>').join("");
  if (!s.can_serve) {
    html += '<div class="card" style="border-color:var(--bad)"><div class="label" style="color:var(--bad)">Attention</div>' +
            '<div class="value" style="font-size:15px">No usable accounts</div>' +
            '<div class="foot">requests will return 429 until quota resets</div></div>';
  }
  $("summary").innerHTML = html;
  $("upstream").textContent = s.upstream + "  \\u00b7  period " + s.period +
    "  \\u00b7  up " + fmtEta(s.uptime_seconds);
  $("strategy").textContent = "strategy: " + s.strategy +
    "  \\u00b7  retries: " + s.max_retries +
    "  \\u00b7  refund on: " + (s.refund_on || []).join(",") +
    "  \\u00b7  reserve: " + s.quota_reserve + "/account" +
    "  \\u00b7  cache: " + (s.cache.enabled ? s.cache.entries + "/" + s.cache.capacity + " entries, ttl " + s.cache.ttl_seconds + "s" : "off") +
    "  \\u00b7  rate limit: " + (s.ratelimit.enabled ? s.ratelimit.per_minute + "/min" : "off") +
    "  \\u00b7  trace: " + fmtEta(s.resets_in_seconds) + " to rollover";
  $("footer").textContent = "v" + s.version + "  \\u00b7  " + s.routes.join("  ") +
    "  \\u00b7  auto-refresh 5s";
}

function accountRows(s) {
  if (!s.accounts.length) {
    $("accounts").innerHTML = '<tr><td colspan="13" class="empty">no accounts configured \\u2014 add one above or set SERP_ACCOUNTS</td></tr>';
    return;
  }
  $("accounts").innerHTML = s.accounts.map((a) => {
    const pct = a.quota_limit ? Math.min(100, Math.round(100 * a.used / a.quota_limit)) : 0;
    const barClass = pct > 90 ? "bar bad" : pct > 70 ? "bar warn" : "bar";
    let status = '<span class="pill ' + esc(a.status) + '">' + esc(a.status) + '</span>';
    if (a.on_cooldown) status += ' <span class="pill cooling">cooldown</span>';
    const toggle = a.status === "active" ? "disable" : "enable";
    return '<tr>' +
      '<td class="num muted">' + a.id + '</td>' +
      '<td>' + esc(a.label) + '</td>' +
      '<td>' + status + '</td>' +
      '<td class="mono muted">' + esc(a.key_hint) + '</td>' +
      '<td><div class="' + barClass + '"><i style="width:' + pct + '%"></i></div></td>' +
      '<td class="num">' + a.used + ' / ' + a.quota_limit + '</td>' +
      '<td class="num" style="color:' + (a.available > 0 ? "var(--accent)" : "var(--dim)") + '">' + a.available + '</td>' +
      '<td class="num">' + a.in_flight + '</td>' +
      '<td class="num">' + a.ok + '</td>' +
      '<td class="num">' + a.failed + '</td>' +
      '<td class="num">' + (a.avg_latency_ms == null ? "\\u2014" : a.avg_latency_ms) + '</td>' +
      '<td class="muted mono">' + fmtTime(a.last_used_at) + '</td>' +
      '<td><div class="row-actions">' +
        '<button class="tiny" data-act="toggle" data-id="' + a.id + '" data-status="' + esc(a.status) + '">' + toggle + '</button>' +
        '<button class="tiny" data-act="reset" data-id="' + a.id + '">reset</button>' +
        '<button class="tiny danger" data-act="delete" data-id="' + a.id + '">del</button>' +
      '</div></td>' +
    '</tr>';
  }).join("");
}

function requestRows(s) {
  if (!s.recent.length) {
    $("requests").innerHTML = '<tr><td colspan="8" class="empty">no requests yet</td></tr>';
    return;
  }
  $("requests").innerHTML = s.recent.map((r) => {
    const color = r.status >= 500 || r.status === 429 ? "var(--bad)"
      : r.status >= 400 ? "var(--warn)" : "var(--ok)";
    return '<tr>' +
      '<td class="muted mono">' + fmtTime(r.ts) + '</td>' +
      '<td class="mono">' + esc(r.method) + '</td>' +
      '<td class="mono">' + esc(r.path) + '</td>' +
      '<td class="num" style="color:' + color + '">' + r.status +
        (r.cached ? ' <span class="pill cooling">cache</span>' : '') + '</td>' +
      '<td class="muted">' + esc(r.account || "\\u2014") + '</td>' +
      '<td class="num">' + (r.latency_ms == null ? "\\u2014" : r.latency_ms) + '</td>' +
      '<td class="mono muted">' + esc(r.client) + '</td>' +
      '<td class="muted">' + esc(r.error || "") + '</td>' +
    '</tr>';
  }).join("");
}

let last = null;
async function refresh() {
  try {
    const s = await api("/api/status");
    last = s;
    summaryCards(s);
    accountRows(s);
    requestRows(s);
    $("upstream").insertAdjacentHTML("afterbegin", '<span class="dot"></span>');
  } catch (e) {
    $("upstream").innerHTML = '<span class="dot off"></span>dashboard unavailable: ' + esc(e.message);
  }
}

$("savekey").onclick = () => {
  sessionStorage.setItem("serpent_key", $("key").value.trim());
  toast("key saved");
  refresh();
};
$("addbtn").onclick = () => $("addform").classList.toggle("open");
$("f-cancel").onclick = () => $("addform").classList.remove("open");
$("f-save").onclick = async () => {
  const body = {
    label: $("f-label").value.trim(),
    api_key: $("f-key").value.trim(),
    quota_limit: parseInt($("f-limit").value, 10) || 250,
  };
  if (!body.api_key) return toast("api key is required", true);
  try {
    await api("/admin/accounts", {method: "POST", body: JSON.stringify(body)});
    $("f-key").value = ""; $("f-label").value = "";
    $("addform").classList.remove("open");
    toast("account added");
    refresh();
  } catch (e) { toast(e.message, true); }
};

$("accounts").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.dataset.id, act = btn.dataset.act;
  try {
    if (act === "toggle") {
      const status = btn.dataset.status === "active" ? "disabled" : "active";
      await api("/admin/accounts/" + id, {method: "PATCH", body: JSON.stringify({status})});
      toast("account " + status);
    } else if (act === "reset") {
      if (!confirm("Reset quota for account " + id + "?")) return;
      await api("/admin/accounts/" + id + "/reset", {method: "POST"});
      toast("quota reset");
    } else if (act === "delete") {
      if (!confirm("Delete account " + id + "? This cannot be undone.")) return;
      await api("/admin/accounts/" + id, {method: "DELETE"});
      toast("account deleted");
    }
    refresh();
  } catch (e) { toast(e.message, true); }
});

$("key").value = sessionStorage.getItem("serpent_key") || "";
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""
