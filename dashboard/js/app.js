/*
 * ACNABIN Tender Monitoring dashboard.
 * Reads the Supabase view v_active_tenders (active tenders only; the ACTIVE rule is applied
 * in the database against the current time). General = all rows of a sector,
 * Priority = rows flagged is_priority.
 */
(function () {
  "use strict";

  const env = window.ENV || {};
  let db = null;
  if (env.SUPABASE_URL && !env.SUPABASE_URL.startsWith("__") && window.supabase) {
    db = window.supabase.createClient(env.SUPABASE_URL, env.SUPABASE_ANON_KEY);
  }

  // ------------------------------------------------------------------ helpers
  const $ = (sel) => document.querySelector(sel);
  const esc = (v) => String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const TZ = "Asia/Dhaka";

  function dhakaParts(d) {
    const p = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })
      .formatToParts(d).reduce((acc, x) => (acc[x.type] = x.value, acc), {});
    return { y: +p.year, m: +p.month, d: +p.day, hh: p.hour, mm: p.minute };
  }
  function fmtDate(y, m, d) { return `${String(d).padStart(2, "0")} ${MONTHS[m - 1]} ${y}`; }
  function fmtPublished(iso) {
    if (!iso) return null;
    const [y, m, d] = iso.split("-").map(Number);
    return fmtDate(y, m, d);
  }
  function fmtDeadline(t) {
    if (!t.deadline) return null;
    const p = dhakaParts(new Date(t.deadline));
    return fmtDate(p.y, p.m, p.d) + (t.deadline_has_time ? ` ${p.hh}:${p.mm}` : "");
  }
  function todayDhaka() {
    const p = dhakaParts(new Date());
    return Date.UTC(p.y, p.m - 1, p.d);
  }
  function daysUntil(t) {
    if (!t.deadline) return null;
    const p = dhakaParts(new Date(t.deadline));
    return Math.round((Date.UTC(p.y, p.m - 1, p.d) - todayDhaka()) / 86400000);
  }
  function daysSincePublished(t) {
    if (!t.published_date) return null;
    const [y, m, d] = t.published_date.split("-").map(Number);
    return Math.round((todayDhaka() - Date.UTC(y, m - 1, d)) / 86400000);
  }
  function setText(sel, text) { const el = $(sel); if (el) el.textContent = text; }

  async function loadLastRun() {
    if (!db) {
      setText("#last-run", "Live Demo Mode · Updated 07 Oct 2026 (Dhaka)");
      return;
    }
    const { data } = await db.from("v_last_run").select("end_time").limit(1);
    if (data && data.length && data[0].end_time) {
      const p = dhakaParts(new Date(data[0].end_time));
      setText("#last-run", `Last updated ${fmtDate(p.y, p.m, p.d)} ${p.hh}:${p.mm} (Dhaka)`);
    } else {
      setText("#last-run", "No completed run yet");
    }
  }

  async function fetchActive(sector) {
    if (!db) {
      const all = window.DEMO_TENDERS || [];
      return sector ? all.filter((r) => r.sector === sector) : all;
    }
    let q = db.from("v_active_tenders").select("*");
    if (sector) q = q.eq("sector", sector);
    const { data, error } = await q.limit(5000);
    if (error) throw error;
    return data || [];
  }

  // ------------------------------------------------------------------ home
  async function initHome() {
    try {
      const rows = await fetchActive(null);
      for (const sector of ["BANK", "NGO", "IT"]) {
        const s = rows.filter((r) => r.sector === sector);
        setText(`#${sector}-general`, s.length);
        setText(`#${sector}-priority`, s.filter((r) => r.is_priority).length);
        if (sector === "BANK") setText("#BANK-ifrs9", s.filter((r) => r.is_ifrs9).length);
      }
    } catch (e) {
      console.error(e);
    }
  }

  // ------------------------------------------------------------------ sector page
  const state = { rows: [], tab: "general", sortKey: "deadline", sortDir: 1 };

  function filtered() {
    const q = ($("#f-search").value || "").trim().toLowerCase();
    const org = $("#f-org").value;
    const cat = $("#f-cat").value;
    const due = $("#f-due").value;
    const pub = $("#f-pub").value;
    const onlyIfrs9 = $("#f-ifrs9") && $("#f-ifrs9").checked;
    const onlyTarget = $("#f-target") && $("#f-target").checked;
    return state.rows.filter((t) => {
      if (state.tab === "priority" && !t.is_priority) return false;
      if (org && t.organization_name !== org) return false;
      if (cat && !(t.categories || []).includes(cat)) return false;
      if (onlyIfrs9 && !t.is_ifrs9) return false;
      if (onlyTarget && !t.is_target_bank) return false;
      const dl = daysUntil(t);
      if (due === "7" && !(dl !== null && dl <= 7)) return false;
      if (due === "30" && !(dl !== null && dl <= 30)) return false;
      if (due === "none" && dl !== null) return false;
      if (pub === "7") { const ds = daysSincePublished(t); if (ds === null || ds > 7) return false; }
      if (q) {
        const hay = [t.title, t.organization_name, t.reference_number, t.description, (t.categories || []).join(" ")].join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    }).sort(compare);
  }

  function compare(a, b) {
    const k = state.sortKey, dir = state.sortDir;
    const val = (t) => {
      if (k === "deadline") return t.deadline ? Date.parse(t.deadline) : Number.MAX_SAFE_INTEGER;
      if (k === "published") return t.published_date ? -Date.parse(t.published_date) : Number.MAX_SAFE_INTEGER;
      if (k === "organization") return (t.organization_name || "").toLowerCase();
      return (t.title || "").toLowerCase();
    };
    const va = val(a), vb = val(b);
    return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
  }

  function sourceLinks(t) {
    const primary = t.document_url || t.notice_url || t.source_url;
    const label = t.document_url ? "View tender" : t.notice_url ? "View notice" : "Open source";
    let html = `<a href="${esc(primary)}" target="_blank" rel="noopener">${label} &#8599;</a>`;
    const via = /live_tenders_by_sub_category\/64/i.test(t.source_url || "") ? "via Alltender (ICT)"
      : /live_tenders_by_sub_category\/69/i.test(t.source_url || "") ? "via Alltender (Software)"
      : /live_tenders_by_sub_category/i.test(t.source_url || "") ? "via Alltender"
      : /bdjobs\.com/i.test(t.source_url || "") ? "via Bdjobs.com"
      : /alltender\.com/i.test(t.source_url || "") ? "via Alltender"
      : /bcc\.gov\.bd/i.test(t.source_url || "") ? "via BCC"
      : /ictd\.gov\.bd/i.test(t.source_url || "") ? "via ICT Division"
      : "Source page";
    if (primary !== t.source_url) html += `<a class="minor" href="${esc(t.source_url)}" target="_blank" rel="noopener">${via}</a>`;
    return html;
  }

  function relevanceCell(t) {
    if (!t.is_priority) return `<span class="muted">—</span>`;
    return (t.categories || []).map((c) =>
      `<span class="tag ${c === "IFRS 9 / ECL" ? "tag-ifrs9" : "tag-priority"}">${esc(c)}</span>`).join("");
  }

  function render() {
    const items = filtered();
    const body = $("#rows");
    setText("#result-count", `${items.length} of ${state.tab === "priority" ? state.rows.filter((r) => r.is_priority).length : state.rows.length} shown`);
    if (!items.length) {
      body.innerHTML = `<tr><td colspan="6" class="empty">No active opportunities found.</td></tr>`;
      return;
    }
    body.innerHTML = items.map((t) => {
      const dl = daysUntil(t);
      const deadline = fmtDeadline(t);
      const published = fmtPublished(t.published_date);
      let dlSub = "";
      if (dl !== null) dlSub = dl === 0 ? "closes today" : dl === 1 ? "closes tomorrow" : `in ${dl} days`;
      const target = t.is_target_bank ? `<div class="sub target">IFRS 9 target bank</div>` : "";
      return `<tr>
        <td class="org"><div class="name">${esc(t.organization_name)}</div>${target}</td>
        <td class="title">
          <div class="t">${esc(t.title)}</div>
          ${t.reference_number ? `<div class="ref">${esc(t.reference_number)}</div>` : ""}
          ${t.description ? `<div class="desc">${esc(t.description)}</div>` : ""}
        </td>
        <td class="date">${published ? esc(published) : `<span class="muted">Not stated</span>`}</td>
        <td class="date">${deadline ? `${esc(deadline)}<div class="sub ${dl !== null && dl <= 3 ? "soon" : ""}">${dlSub}</div>` : `<span class="muted">Not stated</span>`}</td>
        <td class="rel">${relevanceCell(t)}</td>
        <td class="src">${sourceLinks(t)}</td>
      </tr>`;
    }).join("");
  }

  function setTab(tab) {
    state.tab = tab === "priority" ? "priority" : "general";
    document.querySelectorAll(".tab").forEach((b) => {
      const on = b.dataset.tab === state.tab;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll("[data-note]").forEach((n) => { n.hidden = n.dataset.note !== state.tab; });
    const url = new URL(window.location.href);
    url.searchParams.set("tab", state.tab);
    history.replaceState(null, "", url);
    render();
  }

  function fillSelect(sel, values, allLabel) {
    const el = $(sel);
    const current = el.value;
    el.innerHTML = `<option value="">${allLabel}</option>` + values.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    if (values.includes(current)) el.value = current;
  }

  async function loadSector(sector) {
    const body = $("#rows");
    body.innerHTML = `<tr><td colspan="6" class="empty">Loading…</td></tr>`;
    try {
      state.rows = await fetchActive(sector);
      $("#load-error").hidden = true;
    } catch (e) {
      console.error(e);
      state.rows = [];
      $("#load-error").hidden = false;
    }
    setText("#count-general", state.rows.length);
    setText("#count-priority", state.rows.filter((r) => r.is_priority).length);
    fillSelect("#f-org", [...new Set(state.rows.map((r) => r.organization_name))].sort(), "All organizations");
    fillSelect("#f-cat", [...new Set(state.rows.flatMap((r) => r.categories || []))].sort(), "All categories");
    render();
    if (db) loadSourceErrors(sector);
    else setText("#source-summary", `Showing live tenders from monitored IT & procurement sources.`);
  }

  async function loadSourceErrors(sector) {
    const { data } = await db.from("source_status").select("source_id,ok").eq("sector", sector);
    if (!data) return;
    const failed = data.filter((s) => !s.ok).length;
    setText("#source-summary", `${data.length - failed} of ${data.length} sources read successfully in the last run.`);
    // Tenders from the Alltender subscription are readable by signed-in users only (database policy)
    const { data: { session } } = await db.auth.getSession();
    if (!session) {
      $("#source-summary").insertAdjacentHTML("beforeend",
        ` Tenders from the Alltender subscription are shown after <a href="admin.html">signing in</a>.`);
    }
  }

  function initSector(sector) {
    const params = new URLSearchParams(window.location.search);
    document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
    ["#f-search"].forEach((s) => $(s).addEventListener("input", render));
    ["#f-org", "#f-cat", "#f-due", "#f-pub", "#f-ifrs9", "#f-target"].forEach((s) => { const el = $(s); if (el) el.addEventListener("change", render); });
    $("#btn-refresh").addEventListener("click", () => { loadSector(sector); loadLastRun(); });
    $("#btn-export").addEventListener("click", exportCsv);
    document.querySelectorAll("th.sortable").forEach((th) => th.addEventListener("click", () => {
      const key = th.dataset.sort;
      state.sortDir = state.sortKey === key ? -state.sortDir : 1;
      state.sortKey = key;
      document.querySelectorAll("th.sortable .dir").forEach((d) => d.textContent = "");
      th.querySelector(".dir").textContent = state.sortDir === 1 ? "▲" : "▼";
      render();
    }));
    setTab(params.get("tab"));
    loadSector(sector);
  }

  function exportCsv() {
    const items = filtered();
    const cols = [
      ["Organization", (t) => t.organization_name],
      ["Opportunity", (t) => t.title],
      ["Reference", (t) => t.reference_number],
      ["Published", (t) => t.published_date],
      ["Deadline", (t) => fmtDeadline(t)],
      ["Priority", (t) => (t.is_priority ? "Yes" : "No")],
      ["IFRS 9", (t) => (t.is_ifrs9 ? "Yes" : "No")],
      ["Category", (t) => (t.categories || []).join("; ")],
      ["Matched keywords", (t) => (t.matched_keywords || []).join("; ")],
      ["Tender link", (t) => t.document_url || t.notice_url || ""],
      ["Source page", (t) => t.source_url],
    ];
    const cell = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
    const csv = [cols.map((c) => cell(c[0])).join(","), ...items.map((t) => cols.map((c) => cell(c[1](t))).join(","))].join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `ACNABIN_${document.body.dataset.sector}_${state.tab}_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  // ------------------------------------------------------------------ sources page
  async function initSources() {
    const body = $("#rows");
    if (!db) { body.innerHTML = `<tr><td colspan="6" class="empty">The database connection is not configured.</td></tr>`; return; }
    const { data, error } = await db.from("source_status").select("*").order("organization_name");
    if (error || !data) { body.innerHTML = `<tr><td colspan="6" class="empty">Could not load source status.</td></tr>`; return; }
    const draw = () => {
      const sector = $("#f-sector").value;
      const onlyErrors = $("#f-errors").checked;
      const rows = data.filter((s) => (!sector || s.sector === sector) && (!onlyErrors || !s.ok));
      setText("#result-count", `${rows.length} sources · ${data.filter((s) => !s.ok).length} with errors`);
      body.innerHTML = rows.length ? rows.map((s) => {
        const p = s.last_checked ? dhakaParts(new Date(s.last_checked)) : null;
        return `<tr>
          <td class="org"><div class="name">${esc(s.organization_name)}</div>${s.is_target_bank ? `<div class="sub target">IFRS 9 target bank</div>` : ""}</td>
          <td>${s.sector === "BANK" ? "Bank" : "NGO"}</td>
          <td>${!s.ok ? `<span class="tag tag-error">${esc(s.error || "Error")}</span>` : s.listings_found ? `<span class="tag tag-ok">OK</span>` : `<span class="tag tag-priority">NO LISTINGS</span>`}</td>
          <td>${s.ok ? s.listings_found : `<span class="muted">—</span>`}</td>
          <td class="date">${p ? `${fmtDate(p.y, p.m, p.d)} ${p.hh}:${p.mm}` : "—"}${!s.ok && s.consecutive_failures > 1 ? `<div class="sub">${s.consecutive_failures} failed runs</div>` : ""}</td>
          <td><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a></td>
        </tr>`;
      }).join("") : `<tr><td colspan="6" class="empty">No sources match.</td></tr>`;
    };
    $("#f-sector").addEventListener("change", draw);
    $("#f-errors").addEventListener("change", draw);
    draw();
  }

  // ------------------------------------------------------------------ boot
  document.addEventListener("DOMContentLoaded", () => {
    loadLastRun();
    const page = document.body.dataset.page;
    if (page === "home") initHome();
    else if (page === "sector") initSector(document.body.dataset.sector);
    else if (page === "sources") initSources();
  });
})();
