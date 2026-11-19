"use strict";

// ---------------------------------------------------------------- utils

const $app = document.getElementById("app");
const $nav = document.getElementById("nav");
let cleanups = [];

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("agora-theme", next); } catch {}
  renderSidebar();
}

const ICONS = {
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  chev: '<path d="m9 6 6 6-6 6"/>',
  job: '<path d="M8 4h8l4 4v12H8z"/><path d="M4 8v12h4"/>',
  play: '<path d="M7 5v14l12-7z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  note: '<path d="M5 4h14v12l-4 4H5z"/><path d="M15 20v-4h4M8 9h8M8 13h4"/>',
  pencil: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  trash: '<path d="M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13"/>',
  down: '<path d="M12 4v11m-5-4 5 5 5-5M5 20h14"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.5 3.3-5 6.5-5s5.700 1.500 6.500 5M16 5a3.500 3.500 0 0 1 0 7M18 15c2 .6 3.200 2.200 3.500 5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.500 1.500M17.500 17.500 19 19M19 5l-1.500 1.500M6.500 17.500 5 19"/>',
  moon: '<path d="M20 14.500A8 8 0 0 1 9.500 4 8 8 0 1 0 20 14.500z"/>',
  out: '<path d="M10 4H5v16h5M15 8l4 4-4 4M19 12H9"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  redo: '<path d="M20 5v5h-5M20 10a8 8 0 1 0 1 5"/>',
  back: '<path d="m15 6-6 6 6 6"/>',
  fwd: '<path d="m9 6 6 6-6 6"/>',
  reset: '<path d="M4 5v5h5M4 10a8 8 0 1 1-1 5"/>',
};
const ico = (n, size = 16) => `<svg class="i" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n]}</svg>`;
const LOGO = `<svg class="logo" viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="2" width="9" height="9" rx="2"/><rect x="13" y="2" width="9" height="9" rx="2" class="dim"/><rect x="2" y="13" width="9" height="9" rx="2" class="dim"/><rect x="13" y="13" width="9" height="9" rx="2" class="hot"/></svg>`;
document.getElementById("burger").innerHTML = ico("menu", 18);
document.getElementById("burger").addEventListener("click", () => document.body.classList.toggle("nav-open"));
document.addEventListener("click", (e) => {
  if (document.body.classList.contains("nav-open") && !e.target.closest("#side, #burger")) document.body.classList.remove("nav-open");
});

let ME = null;

const canWrite = () => ME?.role !== "viewer";
const ROLE_LABEL = { admin: "admin", corrector: "corrector", viewer: "viewer" };

function setMe(user) {
  ME = user;
  document.body.dataset.role = user?.role || "";
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function toast(msg, kind = "") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = `show ${kind}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = ""), 3500);
}

class Unauthorized extends Error {}
// Thrown when the answer to a GET arrives after the user already moved to another page: ignored everywhere.
class Stale extends Error {}

let routeSeq = 0;

async function fetchRetry(url, opts, tries) {
  for (let i = 1; ; i++) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 25000);
    try {
      const r = await fetch(url, { ...opts, signal: ctl.signal });
      if (r.status >= 502 && r.status <= 504 && i < tries) { await sleep(400 * i); continue; }
      return r;
    } catch (e) {
      if (i >= tries) throw new Error("Server unreachable, try again.");
      await sleep(400 * i);
    } finally {
      clearTimeout(t);
    }
  }
}

async function api(path, { method = "GET", json, form } = {}) {
  const opts = { method, headers: {} };
  if (json !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(json);
  } else if (form) opts.body = form;
  const seq = routeSeq, get = method === "GET";
  // Only idempotent reads are retried: a POST must never run twice.
  const r = await fetchRetry(`/api${path}`, opts, get ? 3 : 1);
  if (get && seq !== routeSeq) throw new Stale();
  if (r.status === 401 && path !== "/login") {
    setMe(null);
    location.hash = "#/login";
    throw new Unauthorized();
  }
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const d = (await r.json()).detail;
      msg = typeof d === "string" ? d : JSON.stringify(d);
    } catch {}
    throw new Error(msg);
  }
  return r.headers.get("content-type")?.includes("json") ? r.json() : r;
}

function fmtDate(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const today = new Date().toDateString() === d.toDateString();
  return today
    ? d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : d.toLocaleString("en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function fmtDur(b) {
  if (!b || !b.started_at) return "—";
  const s = Math.max(0, Math.round((b.finished_at || Date.now() / 1000) - b.started_at));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`;
}

const STATUS_LABEL = {
  queued: "queued", running: "running", success: "passed", failed: "failed",
  timeout: "timeout", cancelled: "cancelled", error: "error",
};
const badge = (s) => `<span class="badge s-${s || "none"}"><i></i>${s ? STATUS_LABEL[s] || s : "never run"}</span>`;
const isActive = (s) => s === "queued" || s === "running";
const isKo = (s) => s === "failed" || s === "timeout" || s === "error";
const shortRepo = (url) => url.replace(/^(https:\/\/github\.com\/|git@github\.com:)/, "").replace(/\.git$/, "");

function avatar(name) {
  const parts = name.split(/[\s._-]+/).filter(Boolean);
  const ini = ((parts[0] || "?")[0] + (parts[1] ? parts[1][0] : parts[0]?.[1] || "")).toUpperCase();
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `<span class="avatar" style="--h:${h}">${esc(ini)}</span>`;
}

// "27/129" -> 20.9 ; "85%" -> 85 ; otherwise null
function scorePct(score) {
  if (!score) return null;
  let m = score.match(/(-?[\d.]+)\s*\/\s*([\d.]+)/);
  if (m && +m[2] > 0) return Math.max(0, Math.min(100, (100 * m[1]) / m[2]));
  m = score.match(/([\d.]+)\s*%/);
  return m ? Math.min(100, +m[1]) : null;
}
const lvl = (p) => (p >= 100 ? "lvl-hi" : p >= 50 ? "lvl-mid" : "lvl-lo");

function scoreCell(score) {
  const p = scorePct(score);
  if (p === null) return esc(score || "");
  return `<div class="scorecell ${lvl(p)}"><div class="meter"><b style="width:${p}%"></b></div><span class="score" style="color:inherit">${esc(score)}</span></div>`;
}

function stackBar(ok, ko, run, total) {
  const w = (n) => (total ? (100 * n) / total : 0);
  return `<div class="stack"><span class="ok" style="width:${w(ok)}%"></span><span class="ko" style="width:${w(ko)}%"></span><span class="run" style="width:${w(run)}%"></span></div>`;
}

function every(ms, fn) {
  let stop = false;
  (async () => {
    while (!stop) {
      await sleep(ms);
      if (stop) break;
      try { await fn(); } catch (e) { if (e instanceof Unauthorized || e instanceof Stale) break; }
    }
  })();
  cleanups.push(() => (stop = true));
}

function onKey(fn) {
  const h = (e) => {
    if (e.target.closest("input, textarea, select") || e.ctrlKey || e.metaKey || e.altKey) return;
    fn(e);
  };
  document.addEventListener("keydown", h);
  cleanups.push(() => document.removeEventListener("keydown", h));
}

// ---------------------------------------------------------------- router

const routes = [
  [/^#\/login$/, viewLogin],
  [/^#\/users$/, viewUsers],
  [/^#\/account$/, viewAccount],
  [/^#\/f\/(.+)$/, viewJobs],
  [/^#\/jobs\/(\d+)(?:\/(\w+))?$/, viewJob],
  [/^#\/builds\/(\d+)$/, viewBuild],
  [/^#?\/?$/, viewJobs],
];

async function route() {
  cleanups.forEach((f) => f());
  cleanups = [];
  routeSeq++;
  const h = location.hash || "#/";
  if (!ME && h !== "#/login") {
    try { setMe((await api("/me")).user); } catch (e) {
      if (e instanceof Stale) return;
      $app.innerHTML = `<p class="err">Error: ${esc(e.message)}</p>`;
      return;
    }
    if (!ME) { location.hash = "#/login"; return; }
  }
  document.body.classList.toggle("auth", h === "#/login");
  delete document.body.dataset.access;
  if (h !== "#/login") renderSidebar();
  for (const [re, view] of routes) {
    const m = h.match(re);
    if (m) {
      try {
        await view(...m.slice(1));
      } catch (e) {
        if (!(e instanceof Unauthorized) && !(e instanceof Stale)) $app.innerHTML = `<p class="err">Error: ${esc(e.message)}</p>`;
      }
      return;
    }
  }
  location.hash = "#/";
}

window.addEventListener("hashchange", route);
route();

function setNav(html) {
  $nav.innerHTML = html;
}

// ---------------------------------------------------------------- sidebar

let TREE = { jobs: [], folders: [] };
const openSet = (() => {
  try { return new Set(JSON.parse(localStorage.getItem("agora-open") || "[]")); } catch { return new Set(); }
})();
const saveOpen = () => { try { localStorage.setItem("agora-open", JSON.stringify([...openSet])); } catch {} };

function jobDot(j) {
  const k = j.active ? "running" : j.ko ? "failed" : j.repo_count && j.ok === j.repo_count ? "success" : "";
  return `<i class="dot ${k ? "d-" + k : ""}"></i>`;
}

function currentDir() {
  const h = location.hash;
  let m = h.match(/^#\/f\/(.+)$/);
  if (m) return { dir: decodeURIComponent(m[1]), jobId: null };
  m = h.match(/^#\/jobs\/(\d+)/);
  if (m) {
    const j = TREE.jobs.find((x) => x.id == m[1]);
    return { dir: j?.folder || "", jobId: +m[1] };
  }
  return { dir: "", jobId: null };
}

function treeHtml(prefix, depth, cur) {
  const subs = [...new Set(TREE.folders.filter((p) => p.startsWith(prefix) && p !== prefix.slice(0, -1)).map((p) => p.slice(prefix.length).split("/")[0]))]
    .sort((x, y) => x.localeCompare(y, "fr", { sensitivity: "base" }));
  const inside = (p, base) => p === base || p.startsWith(base + "/");
  let out = "";
  for (const n of subs) {
    const full = prefix + n;
    const open = openSet.has(full) || inside(cur.dir, full);
    const count = TREE.jobs.filter((j) => inside(j.folder || "", full)).length;
    out += `<div class="tn folder ${open ? "open" : ""} ${cur.dir === full && !cur.jobId ? "on" : ""}" style="--d:${depth}">
      <button class="tw" data-toggle="${esc(full)}" aria-label="expand">${ico("chev", 12)}</button>
      <a class="nm" href="#/f/${encodeURIComponent(full)}" style="display:flex;align-items:center;gap:7px;color:inherit;text-decoration:none"><span class="fi">${ico("folder", 15)}</span><span class="nm">${esc(n)}</span></a>
      <span class="cnt">${count}</span></div>`;
    if (open) out += treeHtml(full + "/", depth + 1, cur);
  }
  for (const j of TREE.jobs.filter((j) => (j.folder || "") === prefix.slice(0, -1)).sort((a, b) => a.name.localeCompare(b.name, "fr", { sensitivity: "base" }))) {
    out += `<a class="tn job ${cur.jobId === j.id ? "on" : ""}" style="--d:${depth}" href="#/jobs/${j.id}">${jobDot(j)}<span class="nm">${esc(j.name)}</span></a>`;
  }
  return out;
}

async function renderSidebar() {
  const side = document.getElementById("side");
  if (!ME) { side.innerHTML = ""; return; }
  try {
    const [jobs, folders, me] = await Promise.all([api("/jobs"), api("/folders"), api("/me")]);
    TREE = { jobs, folders };
    if (me.user) ME = { ...ME, ...me.user };
  } catch (e) { if (e instanceof Unauthorized || e instanceof Stale) return; }
  const cur = currentDir();
  const light = document.documentElement.dataset.theme === "light";
  const path = location.hash;
  const quota = ME.role === "admin" ? "" : (() => {
    const used = ME.launch_count ?? 0, max = ME.launch_limit ?? 0, left = max - used;
    const cls = left <= 0 ? "out" : left <= 3 ? "low" : "";
    return `<div class="quota ${cls}"><div style="display:flex;justify-content:space-between"><span>launches</span><span>${used} / ${max}</span></div><div class="bar"><b style="width:${max ? Math.min(100, (100 * used) / max) : 100}%"></b></div></div>`;
  })();
  side.innerHTML = `
    <a href="#/" class="brand">${LOGO}agora</a>
    <div class="side-label"><span>jobs</span></div>
    <div class="tree" id="tree">
      <a class="tn ${path === "#/" || path === "" ? "on" : ""}" href="#/" style="--d:0"><span class="fi">${ico("job", 15)}</span><span class="nm">All jobs</span><span class="cnt">${TREE.jobs.length}</span></a>
      ${treeHtml("", 0, cur)}
    </div>
    <div class="me">
      ${quota}
      <div class="me-top">${avatar(ME.username)}<div class="who-n"><b>${esc(ME.username)}</b><span>${ROLE_LABEL[ME.role]}</span></div></div>
      <div class="me-actions">
        <a class="ghost ${path === "#/account" ? "on" : ""}" href="#/account">${ico("user", 15)}Account</a>
        ${ME.role === "admin" ? `<a class="ghost ${path === "#/users" ? "on" : ""}" href="#/users">${ico("users", 15)}Users</a>` : ""}
        <button class="ghost" id="theme-btn" title="toggle theme">${ico(light ? "moon" : "sun", 15)}${light ? "Dark" : "Light"}</button>
        <button class="ghost" id="logout">${ico("out", 15)}Sign out</button>
      </div>
    </div>`;
  document.getElementById("theme-btn").addEventListener("click", toggleTheme);
  document.getElementById("logout").addEventListener("click", async () => {
    await api("/logout", { method: "POST" });
    setMe(null);
    location.hash = "#/login";
  });
  document.getElementById("tree").addEventListener("click", (e) => {
    const t = e.target.closest("[data-toggle]");
    if (!t) return;
    e.preventDefault();
    const p = t.dataset.toggle;
    openSet.has(p) ? openSet.delete(p) : openSet.add(p);
    saveOpen();
    renderSidebar();
  });
  document.body.classList.remove("nav-open");
}

// ---------------------------------------------------------------- login

function resultField() {
  // Demo grid: one cell per repository, like on a job page.
  let seed = 7;
  const rnd = () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);
  const cols = 18, rows = 10;
  const cells = [];
  for (let i = 0; i < cols * rows; i++) {
    const r = rnd();
    cells.push(r < .6 ? "success" : r < .78 ? "failed" : r < .84 ? "running" : r < .88 ? "queued" : "none");
  }
  return `<div class="field" style="--cols:${cols}" aria-hidden="true">${cells.map((c, n) => `<span class="cell c-${c}" style="--n:${n}"></span>`).join("")}</div>`;
}

async function viewLogin() {
  setNav("");
  const light = document.documentElement.dataset.theme === "light";
  $app.innerHTML = `
    <div class="login-wrap">
      <section class="stage">
        <a class="brand" href="#/login">${LOGO}agora</a>
        <div>
          <h2>One job, every repository, one board.</h2>
          <p>Agora clones every submission, runs your tests in an isolated sandbox and files the results by job.</p>
        </div>
        ${resultField()}
        <div>
          <div class="legend">
            <span><i class="cell c-success"></i>passed</span><span><i class="cell c-failed"></i>failed</span>
            <span><i class="cell c-running"></i>running</span><span><i class="cell c-queued"></i>queued</span><span><i class="cell c-none"></i>never run</span>
          </div>
          <div class="stage-foot" style="margin-top:14px">sandbox · --network none · 512 MB · 60 s</div>
        </div>
      </section>
      <section class="login-side">
        <button class="ghost login-theme" id="lt" title="toggle theme">${ico(light ? "moon" : "sun", 15)}</button>
        <form class="login" id="f">
          <div><div class="eyebrow">restricted access</div><h1>Sign in</h1></div>
          <label for="u">Username<input id="u" name="username" autofocus autocomplete="username" required></label>
          <label for="p">Password<input id="p" type="password" name="password" autocomplete="current-password" required></label>
          <button class="btn primary">Sign in</button>
          <div class="hint">Accounts are created by the administrator.</div>
        </form>
      </section>
    </div>`;
  document.getElementById("lt").addEventListener("click", () => { toggleTheme(); viewLogin(); });
  document.getElementById("f").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      setMe(await api("/login", { method: "POST", json: { username: e.target.username.value, password: e.target.password.value } }));
      location.hash = "#/";
    } catch (err) {
      toast("Wrong username or password.", "ko");
      e.target.password.select();
    }
  });
}

// ---------------------------------------------------------------- account

async function viewAccount() {
  setNav(`<a href="#/">jobs</a> <span class="sep">/</span> <span class="crumb">account</span>`);
  $app.innerHTML = `
    <section class="head"><div><div class="eyebrow">compte</div><h1>${esc(ME.username)} <span class="chip">${ROLE_LABEL[ME.role]}</span></h1></div></section>
    <section id="ssh" class="card settings">
      <div class="eyebrow">SSH key</div>
      <p class="muted small">This key is used to clone repositories when you launch a job. The private key stays on the server;
        add the public key in GitHub → Settings → SSH and GPG keys.</p>
      <div id="sshbody"></div>
    </section>
    ${ME.role === "admin" ? "" : `<div class="muted small" style="margin:8px 0">Launches used: <b>${ME.launch_count ?? 0} / ${ME.launch_limit ?? 0}</b></div>`}
    <form id="pw" class="card settings">
      <label>Current password <input type="password" name="current" autocomplete="current-password" required></label>
      <label>New password <span class="muted small">(8 characters minimum)</span>
        <input type="password" name="next" minlength="8" autocomplete="new-password" required></label>
      <div class="toolbar"><button class="btn primary">change password</button></div>
    </form>`;
  const renderKey = async () => {
    const k = await api("/me/ssh-key");
    setMe({ ...ME, has_key: k.has_key });
    document.getElementById("sshbody").innerHTML = k.has_key
      ? `<textarea readonly rows="3" style="width:100%" id="pub">${esc(k.public_key)}</textarea>
         <div class="toolbar"><button class="btn" data-act="copy">copy</button>
         <button class="btn" data-act="regen">regenerate</button>
         <button class="btn danger" data-act="del">delete</button></div>`
      : `<div class="toolbar"><span class="muted small">No key: you cannot launch jobs.</span>
         <button class="btn primary" data-act="gen">generate my key</button></div>`;
  };
  document.getElementById("sshbody").addEventListener("click", async (e) => {
    const act = e.target.closest("button")?.dataset.act;
    if (!act) return;
    try {
      if (act === "copy") { await navigator.clipboard.writeText(document.getElementById("pub").value); toast("Copied", "ok"); return; }
      if (act === "regen" && !confirm("The old key will stop working. Continue?")) return;
      if (act === "del" && !confirm("Delete your key? You will no longer be able to launch jobs.")) return;
      await api("/me/ssh-key", { method: act === "del" ? "DELETE" : "POST" });
      await renderKey();
    } catch (err) { toast(err.message, "ko"); }
  });
  renderKey().catch((err) => toast(err.message, "ko"));
  document.getElementById("pw").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/me/password", { method: "POST", json: { current: e.target.current.value, new: e.target.next.value } });
      e.target.reset();
      toast("Password changed", "ok");
    } catch (err) { toast(err.message, "ko"); }
  });
}

// ---------------------------------------------------------------- users (admin)

async function viewUsers() {
  if (ME.role !== "admin") { location.hash = "#/"; return; }
  setNav(`<a href="#/">jobs</a> <span class="sep">/</span> <span class="crumb">users</span>`);
  const list = await api("/users");
  const roleOptions = (cur) => Object.entries(ROLE_LABEL).map(([k, l]) => `<option value="${k}" ${k === cur ? "selected" : ""}>${l}</option>`).join("");
  $app.innerHTML = `
    <section class="head"><div><div class="eyebrow">administration</div><h1>Users <span class="muted">(${list.length})</span></h1>
      <div class="muted small">admin: everything, accounts included · corrector: jobs, tests and launches · viewer: read-only</div></div></section>
    <div class="tablewrap"><table class="repos">
      <thead><tr><th>User</th><th>Role</th><th>Launches</th><th>Key</th><th>Last sign-in</th><th></th></tr></thead>
      <tbody>${list.map((u) => `
        <tr data-user="${u.id}">
          <td><div class="who">${avatar(u.username)}<div class="name">${esc(u.username)}${u.id === ME.id ? ` <span class="muted small">(you)</span>` : ""}</div></div></td>
          <td><select data-act="role" ${u.id === ME.id ? "disabled" : ""}>${roleOptions(u.role)}</select></td>
          <td>${u.role === "admin" ? `<span class="muted small">unlimited</span>` : `${u.launch_count} / <input data-act="limit" type="number" min="0" value="${u.launch_limit}" style="width:5em"> <button class="icon" data-act="resetcount" title="reset the counter to 0">${ico("reset", 14)}</button>`}</td>
          <td class="muted small">${u.has_key ? "✔" : "—"}</td>
          <td class="muted small">${u.last_login ? fmtDate(u.last_login) : "never"}</td>
          <td class="actions">
            ${u.id === ME.id ? "" : `<button class="btn" data-act="reset">password</button> <button class="icon danger" data-act="del" title="delete">${ico("trash", 15)}</button>`}
          </td>
        </tr>`).join("")}</tbody>
    </table></div>
    <form id="new" class="card settings" style="margin-top:16px">
      <div class="eyebrow">+ create an account</div>
      <div class="row">
        <label>Username <input name="username" pattern="[\\w.@\\-]{2,60}" autocomplete="off" required></label>
        <label>Password <span class="muted small">(8 min.)</span> <input type="text" name="password" minlength="8" autocomplete="off" required></label>
        <label>Role <select name="role">${roleOptions("corrector")}</select></label>
      </div>
      <div class="toolbar"><button class="btn primary">create</button></div>
    </form>`;
  const userOf = (el) => list.find((u) => u.id == el.closest("tr").dataset.user);
  $app.querySelector("tbody").addEventListener("change", async (e) => {
    const kind = e.target.dataset.act;
    if (kind !== "role" && kind !== "limit") return;
    try {
      const json = kind === "role" ? { role: e.target.value } : { launch_limit: Number(e.target.value) };
      await api(`/users/${userOf(e.target).id}`, { method: "PATCH", json });
      toast(kind === "role" ? "Role updated" : "Limit updated", "ok");
    } catch (err) { toast(err.message, "ko"); }
    route();
  });
  $app.querySelector("tbody").addEventListener("click", async (e) => {
    const act = e.target.closest("button")?.dataset.act;
    if (!act) return;
    const u = userOf(e.target);
    try {
      if (act === "resetcount") {
        await api(`/users/${u.id}`, { method: "PATCH", json: { reset_count: true } });
        toast("Counter reset to 0", "ok");
        route();
      } else if (act === "reset") {
        const password = prompt(`New password for ${u.username} (8 characters minimum):`);
        if (!password) return;
        await api(`/users/${u.id}`, { method: "PATCH", json: { password } });
        toast("Password changed", "ok");
      } else if (act === "del") {
        if (!confirm(`Delete account ${u.username}?`)) return;
        await api(`/users/${u.id}`, { method: "DELETE" });
        route();
      }
    } catch (err) { toast(err.message, "ko"); }
  });
  document.getElementById("new").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    try {
      await api("/users", { method: "POST", json: { username: f.username.value.trim(), password: f.password.value, role: f.role.value } });
      toast(`Account ${f.username.value.trim()} created`, "ok");
      route();
    } catch (err) { toast(err.message, "ko"); }
  });
}

// ---------------------------------------------------------------- jobs list

const folderCrumbs = (dir, last = true) => {
  const parts = dir ? dir.split("/") : [];
  return parts.map((p, i) => {
    const path = parts.slice(0, i + 1).join("/");
    return i === parts.length - 1 && last
      ? `<span class="sep">/</span> <span class="crumb">${esc(p)}</span>`
      : `<span class="sep">/</span> <a href="#/f/${encodeURIComponent(path)}">${esc(p)}</a>`;
  }).join(" ");
};

function resultCell(ok, ko, run, total) {
  if (!total) return `<span class="muted small">—</span>`;
  return `<div class="res">${stackBar(ok, ko, run, total)}<div class="txt"><span class="ok">${ok} ok</span><span class="ko">${ko} ko</span>${run ? `<span>${run} en cours</span>` : ""}</div></div>`;
}

async function viewJobs(dirEnc = "") {
  const dir = decodeURIComponent(dirEnc || "");
  const [jobs, folderPaths] = await Promise.all([api("/jobs"), api("/folders")]);
  setNav(dir ? `<a href="#/">jobs</a> ${folderCrumbs(dir)}` : `<span class="crumb">jobs</span>`);
  const inside = (p, base) => p === base || p.startsWith(base + "/");
  const here = jobs.filter((j) => (j.folder || "") === dir).sort((a, b) => a.name.localeCompare(b.name, "fr", { sensitivity: "base" }));
  const prefix = dir ? dir + "/" : "";
  const subs = [...new Set(folderPaths.filter((p) => p.startsWith(prefix) && p !== dir).map((p) => p.slice(prefix.length).split("/")[0]))]
    .sort((x, y) => x.localeCompare(y, "fr", { sensitivity: "base" }));
  const folderStats = (name) => {
    const full = prefix + name;
    const js = jobs.filter((j) => inside(j.folder || "", full));
    return {
      full, jobs: js.length,
      subs: new Set(folderPaths.filter((p) => p.startsWith(full + "/") && p.split("/").length === full.split("/").length + 1)).size,
      repos: js.reduce((n, j) => n + j.repo_count, 0),
      ok: js.reduce((n, j) => n + j.ok, 0), ko: js.reduce((n, j) => n + j.ko, 0), active: js.reduce((n, j) => n + j.active, 0),
      last: Math.max(0, ...js.map((j) => j.last_activity || 0)),
    };
  };
  const total = here.length + subs.length;
  $app.innerHTML = `
    <section class="head">
      <div>
        <div class="eyebrow">${dir ? "folder" : "library"}</div>
        <h1>${dir ? esc(dir.split("/").pop()) : "Jobs"}</h1>
      </div>
    </section>
    <form id="create" class="create w">
      <input name="name" id="cn" placeholder="Job or folder name" autocomplete="off" required>
      <div class="seg" role="radiogroup" aria-label="type">
        <label><input type="radio" name="kind" value="job" checked>Job</label>
        <label><input type="radio" name="kind" value="folder">Folder</label>
      </div>
      <button class="btn primary">${ico("plus", 15)}Create here</button>
    </form>
    ${total ? `<div class="list">
      <div class="lh"><span>Name</span><span>Repos</span><span>Results</span><span>Activity</span><span></span></div>
      ${subs.map((n) => {
        const st = folderStats(n);
        return `<a class="lr folder" href="#/f/${encodeURIComponent(st.full)}" data-path="${esc(st.full)}">
          <div class="nm"><span class="ficon">${ico("folder", 17)}</span><div><b>${esc(n)}</b><small>${st.subs ? st.subs + " folder" + (st.subs > 1 ? "s" : "") + " · " : ""}${st.jobs} job${st.jobs > 1 ? "s" : ""}</small></div></div>
          <span class="num">${st.repos}</span>
          ${resultCell(st.ok, st.ko, st.active, st.repos)}
          <span class="when">${st.last ? fmtDate(st.last) : ""}</span>
          <span class="acts w"><button class="icon" data-act="rename" title="rename / move">${ico("pencil", 15)}</button><button class="icon danger" data-act="del" title="delete">${ico("trash", 15)}</button></span>
        </a>`;
      }).join("")}
      ${here.map((j) => `
        <a class="lr" href="#/jobs/${j.id}">
          <div class="nm"><span class="ficon">${jobDot(j)}</span><div><b>${esc(j.name)}</b><small>${esc(j.description || "no description")}${j.owner_id !== ME.id && j.owner_name ? ` · ${ME.role === "admin" ? "owner" : "by"} ${esc(j.owner_name)}` : j.share_count ? ` · shared with ${j.share_count}` : ""}</small></div></div>
          <span class="num">${j.repo_count}</span>
          ${resultCell(j.ok, j.ko, j.active, j.repo_count)}
          <span class="when">${j.last_activity ? fmtDate(j.last_activity) : "never run"}</span>
          <span></span>
        </a>`).join("")}
    </div>` : `<div class="card empty">${LOGO}<p>${dir ? "This folder is empty." : "No jobs yet."}<br>Create a job or a folder with the field above.</p></div>`}`;
  document.getElementById("create").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = e.target.name.value.trim();
    try {
      if (e.target.kind.value === "folder") {
        await api("/folders", { method: "POST", json: { path: prefix + name } });
        route();
      } else {
        const { id } = await api("/jobs", { method: "POST", json: { name, folder: dir } });
        location.hash = `#/jobs/${id}/files`;
      }
    } catch (err) { toast(err.message, "ko"); }
  });
  $app.querySelector(".list")?.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    e.preventDefault();
    const path = btn.closest("[data-path]").dataset.path;
    try {
      if (btn.dataset.act === "rename") {
        const dst = prompt("New folder path (e.g. C/week-1):", path);
        if (!dst || dst.trim() === path) return;
        await api("/folders/move", { method: "POST", json: { src: path, dst } });
      } else {
        if (!confirm(`Delete folder "${path}" (it must be empty)?`)) return;
        await api(`/folders?path=${encodeURIComponent(path)}`, { method: "DELETE" });
      }
      route();
    } catch (err) { toast(err.message, "ko"); }
  });
}

// ---------------------------------------------------------------- job detail

async function viewJob(id, tab = "repos") {
  const job = await api(`/jobs/${id}`);
  setNav(`<a href="#/">jobs</a> ${folderCrumbs(job.folder || "", false)} <span class="sep">/</span> <span class="crumb">${esc(job.name)}</span>`);
  const tabs = [["repos", "Repositories", job.repos.length], ["failures", "Failures", null], ["files", "Test files", job.files.length]];
  document.body.dataset.access = job.access;
  if (canWrite() && job.access === "owner") tabs.push(["settings", "Settings", null]);
  const visibility = job.access === "shared"
    ? `Shared with you by ${esc(job.owner_name || "an admin")}`
    : ME.role === "admin" && job.owner_id !== ME.id
      ? `Owner: ${esc(job.owner_name || "—")}${job.shares?.length ? ` · shared with ${job.shares.length}` : ""}`
      : job.shares?.length ? `Shared with ${job.shares.length} ${job.shares.length > 1 ? "people" : "person"}` : "Private: only you and admins can see this";
  $app.innerHTML = `
    <section class="head">
      <div>
        <div class="eyebrow">${job.folder ? esc(job.folder) : "job"}</div>
        <h1>${esc(job.name)}</h1>
        ${job.description ? `<div class="muted small">${esc(job.description)}</div>` : ""}
        <div class="muted small vis">${visibility}</div>
        <div class="cmdline"><span class="prompt">$</span> ${esc(job.command)}
          <span class="chip">${esc(job.image)}</span><span class="chip">⏱ ${job.timeout}s</span><span class="chip">${job.memory_mb} MB</span></div>
      </div>
    </section>
    <div class="panel stats" id="stats"></div>
    <nav class="tabs">${tabs.map(([k, l, n]) => `<a href="#/jobs/${id}/${k}" class="${k === tab ? "on" : ""}">${l}${n !== null ? `<span class="n">${n}</span>` : ""}</a>`).join("")}</nav>
    <div id="tab"></div>`;
  renderStats(job.repos);
  if (tab !== "repos") every(3000, async () => renderStats((await api(`/jobs/${id}`)).repos));
  const el = document.getElementById("tab");
  if (tab === "files") return tabFiles(job, el);
  if (tab === "failures") return tabFailures(job, el);
  if (tab === "settings" && canWrite() && job.access === "owner") return tabSettings(job, el);
  return tabRepos(job, el);
}

function renderStats(repos) {
  const el = document.getElementById("stats");
  if (!el) return;
  const ok = repos.filter((r) => r.status === "success").length;
  const ko = repos.filter((r) => isKo(r.status)).length;
  const run = repos.filter((r) => isActive(r.status)).length;
  const pcts = repos.map((r) => scorePct(r.score)).filter((p) => p !== null);
  const avg = pcts.length ? Math.round(pcts.reduce((a, b) => a + b, 0) / pcts.length) : null;
  const cell = (r) => {
    const tip = `${r.name} · ${r.status ? STATUS_LABEL[r.status] : "never run"}${r.score ? " · " + r.score : ""}`;
    return r.build_id
      ? `<a class="cell c-${r.status}" href="#/builds/${r.build_id}" title="${esc(tip)}" aria-label="${esc(tip)}"></a>`
      : `<span class="cell c-none" title="${esc(tip)}"></span>`;
  };
  el.innerHTML = `
    <div class="figs">
      <div class="fig"><div class="v">${repos.length}</div><div class="k">repositories</div></div>
      <div class="fig ok"><div class="v">${ok}</div><div class="k">passed</div></div>
      <div class="fig ko"><div class="v">${ko}</div><div class="k">failed</div></div>
      <div class="fig run"><div class="v">${run}</div><div class="k">running</div></div>
      <div class="fig"><div class="v">${avg === null ? "—" : avg + "%"}</div><div class="k">avg score</div></div>
    </div>
    ${repos.length ? `<div class="matrix">${repos.map(cell).join("")}</div>` : ""}`;
}

// ---- repository list: filter + sort (pure helpers)

const STATUS_FILTERS = [
  ["", "all statuses"], ["ko", "failing"], ["success", "passed"], ["active", "queued / running"], ["none", "never run"],
];

function statusMatches(status, want) {
  if (!want) return true;
  if (want === "ko") return isKo(status);
  if (want === "active") return isActive(status);
  if (want === "none") return !status;
  return status === want;
}

function filterRepos(repos, q, status) {
  q = (q || "").trim().toLowerCase();
  return repos.filter((r) => statusMatches(r.status, status)
    && (!q || r.name.toLowerCase().includes(q) || r.url.toLowerCase().includes(q)));
}

const SORTS = [
  ["name", "name"], ["score", "score ↓"], ["score-asc", "score ↑"], ["status", "status"], ["date", "most recent"], ["time", "slowest"],
];

function sortRepos(repos, key) {
  const byName = (a, b) => a.name.localeCompare(b.name, "fr", { sensitivity: "base", numeric: true });
  const pct = (r) => scorePct(r.score) ?? -1;
  const order = { failed: 0, error: 1, timeout: 2, running: 3, queued: 4, cancelled: 5, success: 6 };
  const rank = (r) => (r.status ? order[r.status] ?? 7 : 8);
  const dur = (r) => (r.started_at ? (r.finished_at || Date.now() / 1000) - r.started_at : -1);
  const last = (r) => r.finished_at || r.started_at || r.queued_at || 0;
  const cmp = {
    name: byName,
    score: (a, b) => pct(b) - pct(a) || byName(a, b),
    "score-asc": (a, b) => pct(a) - pct(b) || byName(a, b),
    status: (a, b) => rank(a) - rank(b) || byName(a, b),
    date: (a, b) => last(b) - last(a) || byName(a, b),
    time: (a, b) => dur(b) - dur(a) || byName(a, b),
  }[key] || byName;
  return [...repos].sort(cmp);
}

function tabRepos(job, el) {
  el.innerHTML = `
    <div class="toolbar">
      <button class="btn primary w" data-act="run-all">${ico("play", 14)}Run all</button>
      <button class="btn w" data-act="run-shown" title="runs only the repositories shown (use the status filter to re-run the failing ones)">${ico("play", 14)}Run shown</button>
      <button class="btn w" data-act="cancel-all">${ico("stop", 14)}Cancel all</button>
      <a class="btn" href="/api/jobs/${job.id}/export.csv">${ico("down", 14)}CSV</a>
      <a class="btn" href="/api/jobs/${job.id}/archive.zip" title="CSV + raw logs of the whole history">${ico("down", 14)}Archive</a>
      <input id="filter" placeholder="⌕ filter…  ( / )" class="grow">
      <select id="f-status" title="filter by status">${STATUS_FILTERS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
      <select id="f-sort" title="sort">${SORTS.map(([v, l]) => `<option value="${v}">sort: ${l}</option>`).join("")}</select>
    </div>
    <div class="tablewrap"><table class="repos">
      <thead><tr><th>Student</th><th>Status</th><th>Score</th><th>Commit</th><th>Time</th><th>Date</th><th></th></tr></thead>
      <tbody id="rows"></tbody>
    </table></div>
    <section class="card add w own">
      <form id="sync" class="settings" style="max-width:none">
        <div class="eyebrow">repositories from GitHub</div>
        <div class="row">
          <label>Organization <input name="org" value="${esc(job.github_org || "")}" placeholder="ex: my-org" autocomplete="off"></label>
          <label>Pattern <input name="pattern" value="${esc(job.repo_pattern || "")}" placeholder="e.g. day06-*   (or re:regex)" autocomplete="off"></label>
        </div>
        <div class="toolbar"><button class="btn primary" id="sync-btn">${job.repos.length ? "update repositories" : "add repositories"}</button>
          <span class="muted small">Builds the list, then refreshes it on every press. A name you edited by hand is never overwritten.</span></div>
      </form>
    </section>
    <details class="card add w own">
      <summary>+ add repositories by hand</summary>
      <form id="add">
        <p class="muted small">One repository per line (.txt / .csv file or pasted below). Other words on the line become the display name.<br>
        <code>jean.dupont, https://github.com/my-org/day06-jean.dupont</code><br>
        <code>git@github.com:my-org/day06-marie.curie.git</code></p>
        <textarea name="text" rows="5" placeholder="https://github.com/org/repo"></textarea>
        <div class="toolbar"><input type="file" name="file" accept=".txt,.csv,text/plain,text/csv"><button class="btn primary">add</button></div>
        <pre id="add-result" class="muted small"></pre>
      </form>
    </details>`;

  const rows = document.getElementById("rows");
  const filter = document.getElementById("filter");
  const fStatus = document.getElementById("f-status"), fSort = document.getElementById("f-sort");
  try { fSort.value = localStorage.getItem("agora-sort") || "name"; } catch {}
  let repos = job.repos;
  const shown = () => sortRepos(filterRepos(repos, filter.value, fStatus.value), fSort.value);

  const render = () => {
    const list = shown();
    rows.innerHTML = list.map((r) => `
      <tr data-repo="${r.id}" ${r.build_id ? `data-build="${r.build_id}" class="clickable"` : ""}>
        <td><div class="who">${avatar(r.name)}<div><div class="name">${esc(r.name)}</div>
          ${r.note ? `<div class="note" title="${esc(r.note)}">${ico("note", 12)} ${esc(r.note)}</div>` : ""}
          <a class="repo-url" href="${esc(r.url.startsWith("git@") ? "https://github.com/" + shortRepo(r.url) : r.url.replace(/\.git$/, ""))}" target="_blank" rel="noopener">${esc(shortRepo(r.url))}</a></div></div></td>
        <td>${badge(r.status)}</td>
        <td>${scoreCell(r.score)}</td>
        <td class="sha">${r.commit_sha ? r.commit_sha.slice(0, 7) : ""}</td>
        <td class="small">${fmtDur(r)}</td>
        <td class="muted small">${fmtDate(r.finished_at || r.started_at || r.queued_at)}</td>
        <td class="actions w">
          ${isActive(r.status)
            ? `<button class="icon" data-act="cancel" title="cancel">${ico("stop", 15)}</button>`
            : `<button class="icon" data-act="run" title="run">${ico("play", 15)}</button>`}
          <button class="icon ${r.note ? "has-note" : ""}" data-act="note" title="${r.note ? "edit note" : "add a note"}">${ico("note", 15)}</button>
          <button class="icon own" data-act="rename" title="rename">${ico("pencil", 15)}</button>
          <button class="icon danger own" data-act="del" title="delete">${ico("trash", 15)}</button>
        </td>
      </tr>`).join("") || `<tr><td colspan="7" class="muted" style="text-align:center;padding:28px">No repositories — add them below.</td></tr>`;
    renderStats(repos);
  };
  render();

  const refresh = async () => {
    repos = (await api(`/jobs/${job.id}`)).repos;
    render();
  };
  every(2000, refresh);
  filter.addEventListener("input", render);
  fStatus.addEventListener("change", render);
  fSort.addEventListener("change", () => {
    try { localStorage.setItem("agora-sort", fSort.value); } catch {}
    render();
  });
  onKey((e) => { if (e.key === "/") { e.preventDefault(); filter.focus(); } });

  el.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-act]");
    const tr = e.target.closest("tr[data-repo]");
    if (!btn) {
      if (tr?.dataset.build && !e.target.closest("a")) location.hash = `#/builds/${tr.dataset.build}`;
      return;
    }
    const act = btn.dataset.act;
    try {
      if (act === "run-shown") {
        const ids = shown().map((r) => r.id);
        if (!ids.length) return toast("No repository shown");
        const { queued } = await api(`/jobs/${job.id}/run`, { method: "POST", json: { repo_ids: ids } });
        toast(`${queued} build(s) queued`, "ok");
      } else if (act === "note") {
        const r = repos.find((x) => x.id == tr.dataset.repo);
        const note = prompt(`Note on ${r.name} (empty to remove):`, r.note || "");
        if (note === null || note.trim() === (r.note || "")) return;
        await api(`/repos/${r.id}/note`, { method: "PUT", json: { note: note.trim() } });
      } else if (act === "rename") {
        const r = repos.find((x) => x.id == tr.dataset.repo);
        const name = prompt("New name:", r.name);
        if (!name || !name.trim() || name.trim() === r.name) return;
        await api(`/repos/${r.id}`, { method: "PATCH", json: { name: name.trim() } });
      } else if (act === "run-all") {
        const { queued } = await api(`/jobs/${job.id}/run`, { method: "POST", json: {} });
        toast(`${queued} build(s) queued`, "ok");
      } else if (act === "cancel-all") {
        const { cancelled } = await api(`/jobs/${job.id}/cancel`, { method: "POST" });
        toast(`${cancelled} build(s) cancelled`);
      } else if (act === "run") {
        await api(`/repos/${tr.dataset.repo}/run`, { method: "POST" });
      } else if (act === "cancel") {
        await api(`/builds/${tr.dataset.build}/cancel`, { method: "POST" });
      } else if (act === "del") {
        const r = repos.find((x) => x.id == tr.dataset.repo);
        if (!confirm(`Delete ${r.name} and its history?`)) return;
        await api(`/repos/${r.id}`, { method: "DELETE" });
      }
      await refresh();
    } catch (err) {
      if (!(err instanceof Unauthorized)) toast(err.message, "ko");
    }
  });

  document.getElementById("sync").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, btn = document.getElementById("sync-btn");
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = "syncing…";
    try {
      const r = await api(`/jobs/${job.id}/repos/sync`, { method: "POST", json: { org: f.org.value, pattern: f.pattern.value } });
      toast(`${r.total} repo(s): ${r.added} added, ${r.updated} renamed, ${r.removed} removed`, "ok");
      btn.textContent = "update repositories";
      await refresh();
    } catch (err) {
      btn.textContent = label;
      if (!(err instanceof Unauthorized)) toast(err.message, "ko");
    } finally { btn.disabled = false; }
  });

  document.getElementById("add").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const form = new FormData();
    form.append("text", f.text.value);
    if (f.file.files[0]) form.append("file", f.file.files[0]);
    try {
      const res = await api(`/jobs/${job.id}/repos`, { method: "POST", form });
      document.getElementById("add-result").textContent =
        `${res.added} added, ${res.duplicates} duplicate(s)` +
        (res.rejected.length ? `\nignored lines:\n  ${res.rejected.join("\n  ")}` : "");
      f.text.value = "";
      f.file.value = "";
      await refresh();
    } catch (err) {
      toast(err.message, "ko");
    }
  });
}

async function tabFailures(job, el) {
  const { graded, tests } = await api(`/jobs/${job.id}/failures`);
  if (!tests.length) {
    el.innerHTML = `<p class="muted" style="padding:24px;text-align:center">No failed test recorded yet.
      Run the repositories first. Tests are read from the log: a "✘ label" line is a failure, a "━━ name" line opens a section.</p>`;
    return;
  }
  el.innerHTML = `<div class="muted small" style="margin:12px 0">Most-failed tests across the latest build of each repository (${graded} graded).</div>
    <div class="tablewrap"><table class="repos fail-table"><thead><tr><th>Test</th><th>Failing</th><th>Who</th></tr></thead><tbody>
    ${tests.map((t) => {
      const pct = graded ? Math.round((100 * t.count) / graded) : 0;
      return `<tr><td><div class="muted small">${esc(t.section || "")}</div><div class="name">${esc(t.label)}</div></td>
        <td style="white-space:nowrap"><b>${t.count}</b> <span class="muted small">${pct}%</span><div class="bar"><b style="width:${pct}%"></b></div></td>
        <td class="small">${t.repos.slice(0, 12).map((r) => `<a href="#/builds/${r.build_id}">${esc(r.name)}</a>`).join(", ")}${t.repos.length > 12 ? ` <span class="muted">+${t.repos.length - 12}</span>` : ""}</td></tr>`;
    }).join("")}</tbody></table></div>`;
}

function tabFiles(job, el) {
  el.innerHTML = `
    <div class="files">
      <aside class="card">
        <ul id="flist"></ul>
        <form id="newfile" class="inline w own"><input name="name" placeholder="new file (e.g. tests.sh)" required><button class="btn">+</button></form>
        <label class="btn upload w own">⤒ upload files<input type="file" id="up" multiple hidden></label>
        <p class="muted small">Mounted read-only in <code>/tests</code>. The student's repository is in <code>/work</code> (current directory).
        Print <code>AGORA_SCORE: 7/10</code> to fill the score column.</p>
      </aside>
      <section class="card editor">
        <div class="toolbar"><span id="fname" class="muted">← pick a file</span><span class="grow"></span>
          <button class="btn primary w own" id="save" disabled>save (ctrl+s)</button>
          <button class="btn danger w own" id="delf" disabled>delete</button></div>
        <textarea id="content" spellcheck="false" disabled></textarea>
      </section>
    </div>`;
  const flist = document.getElementById("flist");
  const ta = document.getElementById("content");
  const save = document.getElementById("save");
  const delf = document.getElementById("delf");
  const locked = job.access === "shared";
  let files = job.files, current = null, dirty = false;

  const renderList = () => {
    flist.innerHTML = files.map((f) => `<li><a href="javascript:" data-name="${esc(f.name)}" class="${f.name === current ? "on" : ""}">${esc(f.name)}</a><span class="muted small">${f.size} o</span></li>`).join("")
      || `<li class="muted">no files</li>`;
  };
  const reload = async () => { files = (await api(`/jobs/${job.id}`)).files; renderList(); };

  const open = async (name) => {
    if (dirty && !confirm("Unsaved changes. Continue?")) return;
    const f = await api(`/jobs/${job.id}/files/${encodeURI(name)}`);
    current = name;
    dirty = false;
    document.getElementById("fname").textContent = name;
    ta.value = f.binary ? "(binary file — not editable)" : f.content;
    ta.disabled = f.binary;
    ta.readOnly = !canWrite() || locked;
    save.disabled = f.binary;
    delf.disabled = false;
    renderList();
  };

  const doSave = async () => {
    if (!current || ta.disabled || !canWrite() || locked) return;
    await api(`/jobs/${job.id}/files/${encodeURI(current)}`, { method: "PUT", json: { content: ta.value } });
    dirty = false;
    toast(`${current} saved`, "ok");
    await reload();
  };

  flist.addEventListener("click", (e) => { const a = e.target.closest("a[data-name]"); if (a) open(a.dataset.name); });
  ta.addEventListener("input", () => (dirty = true));
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const s = ta.selectionStart;
      ta.setRangeText("    ", s, ta.selectionEnd, "end");
      dirty = true;
    }
  });
  const ctrlS = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); doSave().catch((err) => toast(err.message, "ko")); } };
  document.addEventListener("keydown", ctrlS);
  cleanups.push(() => document.removeEventListener("keydown", ctrlS));
  save.addEventListener("click", () => doSave().catch((err) => toast(err.message, "ko")));
  delf.addEventListener("click", async () => {
    if (!confirm(`Supprimer ${current} ?`)) return;
    await api(`/jobs/${job.id}/files/${encodeURI(current)}`, { method: "DELETE" });
    current = null; dirty = false;
    ta.value = ""; ta.disabled = true; save.disabled = delf.disabled = true;
    document.getElementById("fname").textContent = "← pick a file";
    await reload();
  });
  document.getElementById("newfile").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = e.target.name.value.trim();
    try {
      await api(`/jobs/${job.id}/files/${encodeURI(name)}`, { method: "PUT", json: { content: "" } });
      e.target.reset();
      await reload();
      await open(name);
    } catch (err) { toast(err.message, "ko"); }
  });
  document.getElementById("up").addEventListener("change", async (e) => {
    const form = new FormData();
    for (const f of e.target.files) form.append("files", f, f.name);
    try {
      const { count } = await api(`/jobs/${job.id}/files`, { method: "POST", form });
      toast(`${count} file(s) uploaded`, "ok");
      await reload();
    } catch (err) { toast(err.message, "ko"); }
    e.target.value = "";
  });
  renderList();
  if (files.length) open((files.find((f) => f.name.endsWith(".sh")) || files[0]).name);
}

function tabSettings(job, el) {
  el.innerHTML = `
    <form id="s" class="card settings">
      <label>Name <input name="name" value="${esc(job.name)}" required></label>
      <label>Description <input name="description" value="${esc(job.description)}"></label>
      <label>Folder <span class="muted small">(e.g. C/week-1 — empty = root)</span><input name="folder" value="${esc(job.folder || "")}" autocomplete="off"></label>
      <label>Command <span class="muted small">(run with sh -c in /work)</span><input name="command" value="${esc(job.command)}" required></label>
      <label>Docker image <input name="image" value="${esc(job.image)}" required></label>
      <div class="row">
        <label>Timeout (s) <input name="timeout" type="number" min="1" max="3600" value="${job.timeout}"></label>
        <label>Memory (MB) <input name="memory_mb" type="number" min="64" max="4096" value="${job.memory_mb}"></label>
      </div>
      <div class="toolbar">
        <button class="btn primary">save</button>
        <span class="grow"></span>
        <button type="button" class="btn" id="dup">duplicate job</button>
        <button type="button" class="btn danger" id="del">delete job</button>
      </div>
    </form>
    <section class="card settings" id="share">
      <div class="eyebrow">sharing</div>
      <p class="muted small">New jobs are private: only you and the admins can see them. Pick who else can see this one.
        People you share with can browse results and launch builds with their own SSH key; only you can edit or delete the job.</p>
      <div id="people" class="people muted small">loading…</div>
      <div class="toolbar"><button class="btn primary" id="saveshare" disabled>save sharing</button></div>
    </section>`;
  api("/directory").then((people) => {
    const box = document.getElementById("people");
    const on = new Set(job.shares || []);
    box.className = "people";
    box.innerHTML = people.map((u) => `<label class="pick"><input type="checkbox" value="${u.id}" ${on.has(u.id) ? "checked" : ""}>${avatar(u.username)}<span>${esc(u.username)}</span><span class="muted small">${ROLE_LABEL[u.role]}</span></label>`).join("")
      || `<span class="muted small">No other users yet.</span>`;
    document.getElementById("saveshare").disabled = false;
  }).catch((err) => { if (!(err instanceof Unauthorized)) toast(err.message, "ko"); });
  document.getElementById("saveshare").addEventListener("click", async () => {
    const ids = [...document.querySelectorAll("#people input:checked")].map((i) => +i.value);
    try {
      await api(`/jobs/${job.id}/shares`, { method: "PUT", json: { user_ids: ids } });
      toast("Sharing saved", "ok");
    } catch (err) { toast(err.message, "ko"); }
  });
  const f = document.getElementById("s");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api(`/jobs/${job.id}`, { method: "PUT", json: {
        name: f.name.value, description: f.description.value, folder: f.folder.value, command: f.command.value,
        image: f.image.value, timeout: +f.timeout.value, memory_mb: +f.memory_mb.value,
      } });
      toast("Settings saved", "ok");
      route();
    } catch (err) { toast(err.message, "ko"); }
  });
  document.getElementById("dup").addEventListener("click", async () => {
    const { id } = await api(`/jobs/${job.id}/duplicate`, { method: "POST" });
    location.hash = `#/jobs/${id}/settings`;
  });
  document.getElementById("del").addEventListener("click", async () => {
    if (!confirm(`Permanently delete "${job.name}", its repositories and all history?`)) return;
    await api(`/jobs/${job.id}`, { method: "DELETE" });
    location.hash = "#/";
  });
}

// ---------------------------------------------------------------- build / terminal

async function viewBuild(id) {
  id = +id;
  const b = await api(`/builds/${id}`);
  const [job, repo] = await Promise.all([api(`/jobs/${b.job_id}`), api(`/repos/${b.repo_id}/builds`)]);
  setNav(`<a href="#/">jobs</a> <span class="sep">/</span> <a href="#/jobs/${job.id}">${esc(job.name)}</a> <span class="sep">/</span> <span class="crumb">${esc(b.repo_name)}</span>`);

  const ran = job.repos.filter((r) => r.build_id);
  const idx = ran.findIndex((r) => r.id === b.repo_id);
  const prev = idx > 0 ? ran[idx - 1] : null;
  const next = idx >= 0 && idx < ran.length - 1 ? ran[idx + 1] : null;

  $app.innerHTML = `
    <section class="card banner" id="banner">
      <div class="ring none" id="ring"><span id="ringtxt">—</span></div>
      ${avatar(b.repo_name)}
      <div class="grow" style="min-width:0">
        <h1>${esc(b.repo_name)} <span id="badge"></span></h1>
        <div class="muted small" id="meta"></div>
      </div>
      <button class="btn" data-go="${prev?.build_id || ""}" ${prev ? "" : "disabled"} title="previous">${ico("back", 14)}</button>
      <button class="btn primary w" id="rerun" title="re-run">${ico("redo", 14)}Re-run <span class="kbd" style="color:inherit;border-color:currentColor">r</span></button>
      <button class="btn danger w" id="cancel">${ico("stop", 14)}Cancel</button>
      <button class="btn" data-go="${next?.build_id || ""}" ${next ? "" : "disabled"} title="next">${ico("fwd", 14)}</button>
    </section>
    <section class="card fails" id="fails" hidden></section>
    <div class="build">
      <div class="terminal">
        <div class="term-bar"><i></i><i></i><i></i><span>agora@sandbox: /work — build #${id} — ${esc(shortRepo(b.repo_url))}</span>
          <label><input type="checkbox" id="follow" checked> follow</label></div>
        <pre id="term" class="term"></pre>
      </div>
      <aside class="card history">
        <div class="eyebrow">history · ${idx + 1}/${ran.length}</div>
        <ul>${repo.builds.map((h) => `
          <li class="h-${h.status} ${h.id === id ? "on" : ""}"><a href="#/builds/${h.id}">#${h.id}</a> ${badge(h.status)}
            <span class="score">${esc(h.score || "")}</span><br><span class="muted small">${fmtDate(h.queued_at)} · <span class="sha">${h.commit_sha ? h.commit_sha.slice(0, 7) : ""}</span></span></li>`).join("")}
        </ul>
      </aside>
    </div>`;

  const termEl = document.getElementById("term");
  const term = new AnsiTerm(termEl);
  const follow = document.getElementById("follow");
  const cancelBtn = document.getElementById("cancel");

  const renderMeta = (x) => {
    document.getElementById("badge").innerHTML = badge(x.status);
    document.getElementById("banner").className = `card banner st-${x.status}`;
    const ring = document.getElementById("ring");
    const p = scorePct(x.score);
    ring.className = `ring ${p === null ? "none" : lvl(p)}`;
    ring.style.setProperty("--p", p ?? 0);
    document.getElementById("ringtxt").textContent = x.score || (isActive(x.status) ? "…" : "—");
    document.getElementById("meta").innerHTML = [
      `build #${x.id}`,
      x.commit_sha ? `commit <span class="sha">${x.commit_sha.slice(0, 10)}</span>` : null,
      x.exit_code !== null && x.exit_code !== undefined ? `exit ${x.exit_code}` : null,
      `time ${fmtDur(x)}`,
      fmtDate(x.started_at || x.queued_at),
      x.error ? `<span class="err">${esc(x.error)}</span>` : null,
    ].filter(Boolean).join(" · ");
    cancelBtn.style.display = isActive(x.status) ? "" : "none";
    const fails = document.getElementById("fails"), list = x.failed_tests || [];
    fails.hidden = !list.length;
    if (list.length) {
      const by = new Map();
      for (const [sec, label] of list) (by.get(sec) || by.set(sec, []).get(sec)).push(label);
      fails.innerHTML = `<div class="eyebrow">${list.length} failed test${list.length > 1 ? "s" : ""}</div>` +
        [...by].map(([sec, labels]) => `<div class="f-sec"><b>${esc(sec || "tests")}</b><ul>${labels.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></div>`).join("");
    }
  };
  renderMeta(b);

  let alive = true;
  cleanups.push(() => (alive = false));
  (async () => {
    const dec = new TextDecoder();
    let offset = 0, lastStatus = b.status;
    while (alive) {
      let r;
      try {
        r = await api(`/builds/${id}/log?offset=${offset}`);
      } catch (e) {
        if (e instanceof Unauthorized) return;
        await sleep(2000);
        continue;
      }
      const buf = await r.arrayBuffer();
      if (!alive) return;
      offset = +r.headers.get("X-Next-Offset");
      const done = r.headers.get("X-Done") === "1";
      if (buf.byteLength) {
        term.write(dec.decode(buf, { stream: !done }));
        if (follow.checked) termEl.scrollTop = termEl.scrollHeight;
      }
      const status = r.headers.get("X-Status");
      if (status !== lastStatus || done) {
        lastStatus = status;
        renderMeta(await api(`/builds/${id}`));
      }
      if (done) {
        if (!termEl.textContent) termEl.innerHTML = `<span class="muted">(aucune sortie)</span>`;
        return;
      }
      if (buf.byteLength < 512 * 1024) await sleep(isActive(status) ? 400 : 1000);
    }
  })();

  // While running, keep the duration ticking.
  every(1000, async () => {
    if (cancelBtn.style.display !== "none") renderMeta(await api(`/builds/${id}`));
  });

  const rerun = async () => {
    try {
      const res = await api(`/repos/${b.repo_id}/run`, { method: "POST" });
      location.hash = `#/builds/${res.build_id}`;
    } catch (err) { toast(err.message, "ko"); }
  };
  document.getElementById("rerun").addEventListener("click", rerun);
  cancelBtn.addEventListener("click", () => api(`/builds/${id}/cancel`, { method: "POST" }));
  $app.querySelectorAll("[data-go]").forEach((btn) =>
    btn.addEventListener("click", () => btn.dataset.go && (location.hash = `#/builds/${btn.dataset.go}`)));
  onKey((e) => {
    if (e.key === "ArrowLeft" && prev) location.hash = `#/builds/${prev.build_id}`;
    else if (e.key === "ArrowRight" && next) location.hash = `#/builds/${next.build_id}`;
    else if (e.key === "r" && canWrite()) rerun();
  });
}
