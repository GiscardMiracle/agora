"use strict";

// ---------------------------------------------------------------- utils

const $app = document.getElementById("app");
const $nav = document.getElementById("nav");
let cleanups = [];

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

async function api(path, { method = "GET", json, form } = {}) {
  const opts = { method, headers: {} };
  if (json !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(json);
  } else if (form) opts.body = form;
  const r = await fetch(`/api${path}`, opts);
  if (r.status === 401 && path !== "/login") {
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
    ? d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function fmtDur(b) {
  if (!b || !b.started_at) return "—";
  const s = Math.max(0, Math.round((b.finished_at || Date.now() / 1000) - b.started_at));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`;
}

const STATUS_LABEL = {
  queued: "en attente", running: "en cours", success: "ok", failed: "échec",
  timeout: "timeout", cancelled: "annulé", error: "erreur",
};
const badge = (s) => `<span class="badge s-${s || "none"}"><i></i>${s ? STATUS_LABEL[s] || s : "jamais lancé"}</span>`;
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

const ASCII = String.raw`
 █████╗  ██████╗  ██████╗ ██████╗  █████╗
██╔══██╗██╔════╝ ██╔═══██╗██╔══██╗██╔══██╗
███████║██║  ███╗██║   ██║██████╔╝███████║
██╔══██║██║   ██║██║   ██║██╔══██╗██╔══██║
██║  ██║╚██████╔╝╚██████╔╝██║  ██║██║  ██║
╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝`.slice(1);

function every(ms, fn) {
  let stop = false;
  (async () => {
    while (!stop) {
      await sleep(ms);
      if (stop) break;
      try { await fn(); } catch (e) { if (e instanceof Unauthorized) break; }
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
  [/^#\/jobs\/(\d+)(?:\/(\w+))?$/, viewJob],
  [/^#\/builds\/(\d+)$/, viewBuild],
  [/^#?\/?$/, viewJobs],
];

async function route() {
  cleanups.forEach((f) => f());
  cleanups = [];
  const h = location.hash || "#/";
  for (const [re, view] of routes) {
    const m = h.match(re);
    if (m) {
      try {
        await view(...m.slice(1));
      } catch (e) {
        if (!(e instanceof Unauthorized)) $app.innerHTML = `<p class="err">Erreur : ${esc(e.message)}</p>`;
      }
      return;
    }
  }
  location.hash = "#/";
}

window.addEventListener("hashchange", route);
route();

function setNav(html) {
  $nav.innerHTML = html + (location.hash === "#/login" ? "" : ` <button class="link" id="logout">déconnexion</button>`);
  document.getElementById("logout")?.addEventListener("click", async () => {
    await api("/logout", { method: "POST" });
    location.hash = "#/login";
  });
}

// ---------------------------------------------------------------- login

async function viewLogin() {
  setNav("");
  $app.innerHTML = `
    <form class="login card" id="f">
      <pre class="ascii">${ASCII}</pre>
      <div class="muted small">évaluation des projets · soutenances</div>
      <div class="term-line"><span class="prompt">$</span> sudo agora --login<span class="cursor"></span></div>
      <label>[sudo] mot de passe :
        <input type="password" name="password" autofocus autocomplete="current-password">
      </label>
      <button class="btn primary" style="justify-content:center">entrer ⏎</button>
    </form>`;
  document.getElementById("f").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/login", { method: "POST", json: { password: e.target.password.value } });
      location.hash = "#/";
    } catch (err) {
      toast("Sorry, try again.", "ko");
      e.target.password.select();
    }
  });
}

// ---------------------------------------------------------------- jobs list

async function viewJobs() {
  setNav(`<span class="crumb">jobs</span>`);
  const jobs = await api("/jobs");
  $app.innerHTML = `
    <section class="head">
      <div>
        <div class="eyebrow">~/jobs</div>
        <h1>Sets de tests <span class="muted">(${jobs.length})</span></h1>
      </div>
      <form id="new" class="inline new-job">
        <input name="name" placeholder="nouveau job, ex: my_printf" required>
        <button class="btn primary">+ créer</button>
      </form>
    </section>
    <div class="grid">
      ${jobs.map((j) => `
        <a class="card job" href="#/jobs/${j.id}">
          <div class="job-name">${esc(j.name)}</div>
          <div class="muted small">${esc(j.description || "aucune description")}</div>
          ${stackBar(j.ok, j.ko, j.active, j.repo_count)}
          <div class="job-meta">
            <span>${j.repo_count} dépôt${j.repo_count > 1 ? "s" : ""}</span>
            <span class="ok">✔ ${j.ok}</span><span class="ko">✘ ${j.ko}</span>
            ${j.active ? badge("running") : ""}
            <span class="grow"></span>
            <span>${j.last_activity ? fmtDate(j.last_activity) : ""}</span>
          </div>
        </a>`).join("") || `<div class="card empty"><pre class="ascii" style="display:inline-block;text-align:left">${ASCII}</pre><p>Aucun job pour l'instant. Crée ton premier set de tests ci-dessus.</p></div>`}
    </div>`;
  document.getElementById("new").addEventListener("submit", async (e) => {
    e.preventDefault();
    const { id } = await api("/jobs", { method: "POST", json: { name: e.target.name.value } });
    location.hash = `#/jobs/${id}/files`;
  });
}

// ---------------------------------------------------------------- job detail

async function viewJob(id, tab = "repos") {
  const job = await api(`/jobs/${id}`);
  setNav(`<a href="#/">jobs</a> <span class="sep">/</span> <span class="crumb">${esc(job.name)}</span>`);
  const tabs = [["repos", "Dépôts", job.repos.length], ["files", "Fichiers de test", job.files.length], ["settings", "Paramètres", null]];
  $app.innerHTML = `
    <section class="head">
      <div>
        <div class="eyebrow">~/jobs/${esc(job.name)}</div>
        <h1>${esc(job.name)}</h1>
        ${job.description ? `<div class="muted small">${esc(job.description)}</div>` : ""}
        <div class="cmdline"><span class="prompt">$</span> ${esc(job.command)}
          <span class="chip">${esc(job.image)}</span><span class="chip">⏱ ${job.timeout}s</span><span class="chip">${job.memory_mb} Mo</span></div>
      </div>
    </section>
    <div class="stats" id="stats"></div>
    <nav class="tabs">${tabs.map(([k, l, n]) => `<a href="#/jobs/${id}/${k}" class="${k === tab ? "on" : ""}">${l}${n !== null ? `<span class="n">${n}</span>` : ""}</a>`).join("")}</nav>
    <div id="tab"></div>`;
  renderStats(job.repos);
  if (tab !== "repos") every(3000, async () => renderStats((await api(`/jobs/${id}`)).repos));
  const el = document.getElementById("tab");
  if (tab === "files") return tabFiles(job, el);
  if (tab === "settings") return tabSettings(job, el);
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
  el.innerHTML = `
    <div class="card stat"><div class="v">${repos.length}</div><div class="k">dépôts</div></div>
    <div class="card stat ok"><div class="v">${ok}</div><div class="k">réussis</div></div>
    <div class="card stat ko"><div class="v">${ko}</div><div class="k">échoués</div></div>
    <div class="card stat run"><div class="v">${run}</div><div class="k">en cours / file</div></div>
    <div class="card stat avg"><div class="v">${avg === null ? "—" : avg + "%"}</div><div class="k">score moyen</div></div>`;
}

function tabRepos(job, el) {
  el.innerHTML = `
    <div class="toolbar">
      <button class="btn primary" data-act="run-all">▶ tout lancer</button>
      <button class="btn" data-act="cancel-all">■ tout annuler</button>
      <a class="btn" href="/api/jobs/${job.id}/export.csv">⤓ csv</a>
      <input id="filter" placeholder="⌕ filtrer…  ( / )" class="grow">
    </div>
    <div class="tablewrap"><table class="repos">
      <thead><tr><th>Étudiant</th><th>Statut</th><th>Score</th><th>Commit</th><th>Durée</th><th>Date</th><th></th></tr></thead>
      <tbody id="rows"></tbody>
    </table></div>
    <details class="card add" ${job.repos.length ? "" : "open"}>
      <summary>+ ajouter des dépôts</summary>
      <form id="add">
        <p class="muted small">Un dépôt par ligne (fichier .txt / .csv ou collé ci-dessous). Les autres mots de la ligne deviennent le nom affiché.<br>
        <code>jean.dupont, https://github.com/my-org/day06-jean.dupont</code><br>
        <code>git@github.com:my-org/day06-marie.curie.git</code></p>
        <textarea name="text" rows="5" placeholder="https://github.com/org/repo"></textarea>
        <div class="toolbar"><input type="file" name="file" accept=".txt,.csv,text/plain,text/csv"><button class="btn primary">ajouter</button></div>
        <pre id="add-result" class="muted small"></pre>
      </form>
    </details>`;

  const rows = document.getElementById("rows");
  const filter = document.getElementById("filter");
  let repos = job.repos;

  const render = () => {
    const q = filter.value.trim().toLowerCase();
    const list = repos.filter((r) => !q || r.name.toLowerCase().includes(q) || r.url.toLowerCase().includes(q));
    rows.innerHTML = list.map((r) => `
      <tr data-repo="${r.id}" ${r.build_id ? `data-build="${r.build_id}" class="clickable"` : ""}>
        <td><div class="who">${avatar(r.name)}<div><div class="name">${esc(r.name)}</div>
          <a class="repo-url" href="${esc(r.url.startsWith("git@") ? "https://github.com/" + shortRepo(r.url) : r.url.replace(/\.git$/, ""))}" target="_blank" rel="noopener">${esc(shortRepo(r.url))}</a></div></div></td>
        <td>${badge(r.status)}</td>
        <td>${scoreCell(r.score)}</td>
        <td class="sha">${r.commit_sha ? r.commit_sha.slice(0, 7) : ""}</td>
        <td class="small">${fmtDur(r)}</td>
        <td class="muted small">${fmtDate(r.finished_at || r.started_at || r.queued_at)}</td>
        <td class="actions">
          ${isActive(r.status)
            ? `<button class="icon" data-act="cancel" title="annuler">■</button>`
            : `<button class="icon" data-act="run" title="lancer">▶</button>`}
          <button class="icon danger" data-act="del" title="supprimer">✕</button>
        </td>
      </tr>`).join("") || `<tr><td colspan="7" class="muted" style="text-align:center;padding:28px">Aucun dépôt — ajoute-les ci-dessous.</td></tr>`;
    renderStats(repos);
  };
  render();

  const refresh = async () => {
    repos = (await api(`/jobs/${job.id}`)).repos;
    render();
  };
  every(2000, refresh);
  filter.addEventListener("input", render);
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
      if (act === "run-all") {
        const { queued } = await api(`/jobs/${job.id}/run`, { method: "POST", json: {} });
        toast(`${queued} build(s) en file`, "ok");
      } else if (act === "cancel-all") {
        const { cancelled } = await api(`/jobs/${job.id}/cancel`, { method: "POST" });
        toast(`${cancelled} build(s) annulé(s)`);
      } else if (act === "run") {
        await api(`/repos/${tr.dataset.repo}/run`, { method: "POST" });
      } else if (act === "cancel") {
        await api(`/builds/${tr.dataset.build}/cancel`, { method: "POST" });
      } else if (act === "del") {
        const r = repos.find((x) => x.id == tr.dataset.repo);
        if (!confirm(`Supprimer ${r.name} et son historique ?`)) return;
        await api(`/repos/${r.id}`, { method: "DELETE" });
      }
      await refresh();
    } catch (err) {
      if (!(err instanceof Unauthorized)) toast(err.message, "ko");
    }
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
        `${res.added} ajouté(s), ${res.duplicates} doublon(s)` +
        (res.rejected.length ? `\nlignes ignorées :\n  ${res.rejected.join("\n  ")}` : "");
      f.text.value = "";
      f.file.value = "";
      await refresh();
    } catch (err) {
      toast(err.message, "ko");
    }
  });
}

function tabFiles(job, el) {
  el.innerHTML = `
    <div class="files">
      <aside class="card">
        <ul id="flist"></ul>
        <form id="newfile" class="inline"><input name="name" placeholder="nouveau fichier (ex: tests.sh)" required><button class="btn">+</button></form>
        <label class="btn upload">⤒ uploader des fichiers<input type="file" id="up" multiple hidden></label>
        <p class="muted small">Montés en lecture seule dans <code>/tests</code>. Le dépôt de l'étudiant est dans <code>/work</code> (dossier courant).
        Affiche <code>AGORA_SCORE: 7/10</code> pour remplir la colonne score.</p>
      </aside>
      <section class="card editor">
        <div class="toolbar"><span id="fname" class="muted">← choisis un fichier</span><span class="grow"></span>
          <button class="btn primary" id="save" disabled>enregistrer (ctrl+s)</button>
          <button class="btn danger" id="delf" disabled>supprimer</button></div>
        <textarea id="content" spellcheck="false" disabled></textarea>
      </section>
    </div>`;
  const flist = document.getElementById("flist");
  const ta = document.getElementById("content");
  const save = document.getElementById("save");
  const delf = document.getElementById("delf");
  let files = job.files, current = null, dirty = false;

  const renderList = () => {
    flist.innerHTML = files.map((f) => `<li><a href="javascript:" data-name="${esc(f.name)}" class="${f.name === current ? "on" : ""}">${esc(f.name)}</a><span class="muted small">${f.size} o</span></li>`).join("")
      || `<li class="muted">aucun fichier</li>`;
  };
  const reload = async () => { files = (await api(`/jobs/${job.id}`)).files; renderList(); };

  const open = async (name) => {
    if (dirty && !confirm("Modifications non enregistrées. Continuer ?")) return;
    const f = await api(`/jobs/${job.id}/files/${encodeURI(name)}`);
    current = name;
    dirty = false;
    document.getElementById("fname").textContent = name;
    ta.value = f.binary ? "(fichier binaire — non éditable)" : f.content;
    ta.disabled = f.binary;
    save.disabled = f.binary;
    delf.disabled = false;
    renderList();
  };

  const doSave = async () => {
    if (!current || ta.disabled) return;
    await api(`/jobs/${job.id}/files/${encodeURI(current)}`, { method: "PUT", json: { content: ta.value } });
    dirty = false;
    toast(`${current} enregistré`, "ok");
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
    document.getElementById("fname").textContent = "← choisis un fichier";
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
      toast(`${count} fichier(s) uploadé(s)`, "ok");
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
      <label>Nom <input name="name" value="${esc(job.name)}" required></label>
      <label>Description <input name="description" value="${esc(job.description)}"></label>
      <label>Commande <span class="muted small">(exécutée avec sh -c dans /work)</span><input name="command" value="${esc(job.command)}" required></label>
      <label>Image Docker <input name="image" value="${esc(job.image)}" required></label>
      <div class="row">
        <label>Timeout (s) <input name="timeout" type="number" min="1" max="3600" value="${job.timeout}"></label>
        <label>Mémoire (Mo) <input name="memory_mb" type="number" min="64" max="4096" value="${job.memory_mb}"></label>
      </div>
      <div class="toolbar">
        <button class="btn primary">enregistrer</button>
        <span class="grow"></span>
        <button type="button" class="btn" id="dup">dupliquer le job</button>
        <button type="button" class="btn danger" id="del">supprimer le job</button>
      </div>
    </form>`;
  const f = document.getElementById("s");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api(`/jobs/${job.id}`, { method: "PUT", json: {
        name: f.name.value, description: f.description.value, command: f.command.value,
        image: f.image.value, timeout: +f.timeout.value, memory_mb: +f.memory_mb.value,
      } });
      toast("Paramètres enregistrés", "ok");
      route();
    } catch (err) { toast(err.message, "ko"); }
  });
  document.getElementById("dup").addEventListener("click", async () => {
    const { id } = await api(`/jobs/${job.id}/duplicate`, { method: "POST" });
    location.hash = `#/jobs/${id}/settings`;
  });
  document.getElementById("del").addEventListener("click", async () => {
    if (!confirm(`Supprimer définitivement « ${job.name} », ses dépôts et tout l'historique ?`)) return;
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
      <button class="btn" data-go="${prev?.build_id || ""}" ${prev ? "" : "disabled"} title="précédent">← <span class="kbd">←</span></button>
      <button class="btn primary" id="rerun" title="relancer">↻ relancer <span class="kbd" style="color:inherit;border-color:currentColor">r</span></button>
      <button class="btn danger" id="cancel">■ annuler</button>
      <button class="btn" data-go="${next?.build_id || ""}" ${next ? "" : "disabled"} title="suivant"><span class="kbd">→</span> →</button>
    </section>
    <div class="build">
      <div class="terminal">
        <div class="term-bar"><i></i><i></i><i></i><span>agora@sandbox: /work — build #${id} — ${esc(shortRepo(b.repo_url))}</span>
          <label><input type="checkbox" id="follow" checked> suivre</label></div>
        <pre id="term" class="term"></pre>
      </div>
      <aside class="card history">
        <div class="eyebrow">historique · ${idx + 1}/${ran.length}</div>
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
      `durée ${fmtDur(x)}`,
      fmtDate(x.started_at || x.queued_at),
      x.error ? `<span class="err">${esc(x.error)}</span>` : null,
    ].filter(Boolean).join(" · ");
    cancelBtn.style.display = isActive(x.status) ? "" : "none";
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
    else if (e.key === "r") rerun();
  });
}
