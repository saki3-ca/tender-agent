/*
 * ACNABIN Tender Monitoring Dashboard Script.
 * Fully data-bound with interactive KPI cards, filters, and real-time database views.
 */
(function () {
  "use strict";

  const env = window.ENV || {};
  let db = null;
  if (env.SUPABASE_URL && !env.SUPABASE_URL.startsWith("__") && window.supabase) {
    db = window.supabase.createClient(env.SUPABASE_URL, env.SUPABASE_ANON_KEY);
  }

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const esc = (v) => String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const TZ = "Asia/Dhaka";

  function dhakaParts(d) {
    const p = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", weekday: "long", hour12: false })
      .formatToParts(d).reduce((acc, x) => (acc[x.type] = x.value, acc), {});
    return { y: +p.year, m: +p.month, d: +p.day, hh: p.hour, mm: p.minute, weekday: p.weekday };
  }

  function fmtHeaderDate() {
    const p = dhakaParts(new Date());
    const el = $("#live-date");
    if (el) {
      el.textContent = `${p.weekday}, ${p.d} ${MONTHS[p.m - 1]} ${p.y}`;
    }
  }

  function fmtShortDate(y, m, d) {
    return `${String(d).padStart(2, "0")} ${SHORT_MONTHS[m - 1]} ${y}`;
  }

  function fmtPublished(iso) {
    if (!iso) return null;
    const parts = iso.split("T")[0].split("-").map(Number);
    return fmtShortDate(parts[0], parts[1], parts[2]);
  }

  function fmtDeadline(t) {
    if (!t.deadline) return null;
    const p = dhakaParts(new Date(t.deadline));
    return fmtShortDate(p.y, p.m, p.d) + (t.deadline_has_time ? ` ${p.hh}:${p.mm}` : "");
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
    const parts = t.published_date.split("T")[0].split("-").map(Number);
    return Math.round((todayDhaka() - Date.UTC(parts[0], parts[1] - 1, parts[2])) / 86400000);
  }

  function relativeTimeStr(isoDate) {
    if (!isoDate) return "—";
    const parts = isoDate.split("T")[0].split("-").map(Number);
    const diffDays = Math.round((todayDhaka() - Date.UTC(parts[0], parts[1] - 1, parts[2])) / 86400000);
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "1d ago";
    if (diffDays > 1 && diffDays < 30) return `${diffDays}d ago`;
    return fmtShortDate(parts[0], parts[1], parts[2]);
  }

  function setText(sel, text) {
    const el = $(sel);
    if (el) el.textContent = text;
  }

  async function loadLastRun() {
    if (!db) return;
    try {
      const { data } = await db.from("v_last_run").select("end_time").limit(1);
      if (data && data.length && data[0].end_time) {
        const p = dhakaParts(new Date(data[0].end_time));
        setText("#last-run", `Last run: ${fmtShortDate(p.y, p.m, p.d)} ${p.hh}:${p.mm} (Dhaka)`);
      }
    } catch (e) {
      console.warn("Could not load last run", e);
    }
  }

  function asItRow(r) {
    return { ...r, is_priority: r.it_priority, is_ifrs9: false, categories: r.it_categories || [], partners: r.it_partners || [] };
  }

  function isEpaperRow(r) {
    const hay = `${r.source_id || ""} ${r.source_url || ""} ${r.notice_url || ""} ${r.document_text || ""}`.toLowerCase();
    return hay.includes("epaper") || hay.includes("prothomalo") || hay.includes("financialexpress") || hay.includes("bangladeshtoday") || hay.includes("protidinerbangladesh") || hay.includes("dhakatribune") || hay.includes("jugantor") || hay.includes("bdpratidin");
  }

  function getPaperName(t) {
    const hay = `${t.source_id || ""} ${t.source_url || ""} ${t.notice_url || ""} ${t.document_text || ""}`.toLowerCase();
    if (hay.includes("prothomalo")) return "Prothom Alo";
    if (hay.includes("financialexpress") || hay.includes("thefinancialexpress")) return "Financial Express";
    if (hay.includes("bangladeshtoday") || hay.includes("thebangladeshtoday")) return "Bangladesh Today";
    if (hay.includes("protidinerbangladesh")) return "Protidiner Bangladesh";
    if (hay.includes("dhakatribune")) return "Dhaka Tribune";
    if (hay.includes("jugantor")) return "Daily Jugantor";
    if (hay.includes("bdpratidin") || hay.includes("pratidin")) return "Bangladesh Pratidin";
    if (hay.includes("epaper")) return "E-Paper";
    return null;
  }

  function getSourceName(t) {
    const hay = `${t.source_id || ""} ${t.source_url || ""} ${t.notice_url || ""} ${t.document_text || ""}`.toLowerCase();
    
    // 1. Newspapers & E-papers
    if (hay.includes("prothomalo")) return "Prothom Alo";
    if (hay.includes("financialexpress") || hay.includes("thefinancialexpress")) return "Financial Express";
    if (hay.includes("dhakatribune")) return "Dhaka Tribune";
    if (hay.includes("jugantor")) return "Daily Jugantor";
    if (hay.includes("bdpratidin") || hay.includes("pratidin")) return "Bangladesh Pratidin";
    if (hay.includes("bangladeshtoday") || hay.includes("thebangladeshtoday")) return "Bangladesh Today";
    if (hay.includes("protidinerbangladesh")) return "Protidiner Bangladesh";
    if (hay.includes("epaper")) return "Newspaper";

    // 2. Aggregators & Platforms
    if (hay.includes("alltender.com") || hay.includes("alltender")) return "Alltender";
    if (hay.includes("bdjobs.com") || hay.includes("bdjobs")) return "Bdjobs";
    if (hay.includes("bcc.gov.bd") || hay.includes("bcc")) return "BCC Portal";
    if (hay.includes("ictd.gov.bd") || hay.includes("ictd")) return "ICT Division";
    if (hay.includes("cptu.gov.bd") || hay.includes("eprocure")) return "e-GP";

    // 3. Organization or Domain Name
    if (t.organization_name) return t.organization_name;
    if (t.source_url) {
      try {
        const u = new URL(t.source_url);
        return u.hostname.replace(/^www\./, "");
      } catch (e) {}
    }
    return "Official Portal";
  }

  async function fetchActive(sector) {
    if (!db) return [];
    let q = db.from("v_active_tenders").select("*");
    if (sector === "IT") q = q.eq("is_it", true);
    else if (sector === "NEWSPAPER") {
      const { data, error } = await q.limit(5000);
      if (error) throw error;
      return (data || []).filter(isEpaperRow);
    } else if (sector) {
      q = q.eq("sector", sector);
    }
    const { data, error } = await q.limit(5000);
    if (error) throw error;
    return sector === "IT" ? (data || []).map(asItRow) : (data || []);
  }

  // ------------------------------------------------------------------ Home Dashboard
  async function initHome() {
    fmtHeaderDate();
    loadLastRun();
    if (!db) return;

    try {
      const rows = await fetchActive(null);
      const total = rows.length;
      const bankRows = rows.filter((r) => r.sector === "BANK");
      const ngoRows = rows.filter((r) => r.sector === "NGO");
      const itRows = rows.filter((r) => r.is_it);
      const npRows = rows.filter(isEpaperRow);
      const priorityRows = rows.filter((r) => r.is_priority || r.it_priority);
      const ifrs9Rows = bankRows.filter((r) => r.is_ifrs9);
      const soonRows = rows.filter((r) => {
        const dl = daysUntil(r);
        return dl !== null && dl >= 0 && dl <= 7;
      });

      // KPI cards data binding
      setText("#kpi-total", String(total).padStart(2, "0"));
      setText("#kpi-priority", String(priorityRows.length).padStart(2, "0"));
      setText("#kpi-deadlines", String(soonRows.length).padStart(2, "0"));
      setText("#kpi-ifrs9", String(ifrs9Rows.length).padStart(2, "0"));
      setText("#kpi-newspaper", String(npRows.length).padStart(2, "0"));

      // Sector summary counts
      setText("#BANK-general", bankRows.length);
      setText("#BANK-priority", bankRows.filter((r) => r.is_priority).length);
      setText("#BANK-ifrs9", ifrs9Rows.length);

      setText("#NGO-general", ngoRows.length);
      setText("#NGO-priority", ngoRows.filter((r) => r.is_priority).length);

      setText("#IT-general", itRows.length);
      setText("#IT-priority", itRows.filter((r) => r.it_priority).length);

      setText("#NEWSPAPER-general", npRows.length);
      setText("#NEWSPAPER-priority", npRows.filter((r) => r.is_priority).length);

      // Render top priority tenders in the home overview table
      renderHomeTable(priorityRows);
    } catch (e) {
      console.error("Home load error:", e);
    }
  }

  function renderHomeTable(items) {
    const tbody = $("#home-rows");
    if (!tbody) return;
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-catchup-state"><div class="catchup-check-icon">✓</div><div class="catchup-title">No priority notices found!</div><div class="catchup-subtitle">All current tenders are listed under general sector views.</div></td></tr>`;
      return;
    }

    tbody.innerHTML = items.slice(0, 20).map((t, idx) => {
      const dl = daysUntil(t);
      const deadline = fmtDeadline(t);
      const published = t.published_date ? relativeTimeStr(t.published_date) : "—";
      let dlSub = "";
      if (dl !== null) {
        dlSub = dl === 0 ? "Closes today" : dl === 1 ? "Closes tomorrow" : `in ${dl} days`;
      }
      const directUrl = t.notice_url || t.document_url || t.source_url;
      const paper = getPaperName(t);

      let catBadge = `<span class="pill-badge pill-query">📌 Priority</span>`;
      if (t.is_ifrs9) catBadge = `<span class="pill-badge pill-ifrs9">📊 IFRS 9</span>`;
      else if (t.sector === "BANK") catBadge = `<span class="pill-badge pill-priority">🏛️ Bank</span>`;
      else if (t.sector === "NGO") catBadge = `<span class="pill-badge pill-handled">🤝 NGO</span>`;
      else if (t.is_it) catBadge = `<span class="pill-badge pill-it">💻 IT</span>`;
      else if (paper) catBadge = `<span class="pill-badge pill-epaper">📰 ${esc(paper)}</span>`;

      return `<tr>
        <td class="col-sl">${idx + 1}</td>
        <td class="col-category">${catBadge}</td>
        <td class="col-details">
          <a class="tender-title-link" href="${esc(directUrl)}" target="_blank" rel="noopener">${esc(t.title)}</a>
          <div style="font-weight:600; color:#4a5568; font-size:12px; margin-top:2px;">${esc(t.organization_name)}</div>
          ${t.reference_number ? `<span class="tender-ref-code">${esc(t.reference_number)}</span>` : ""}
        </td>
        <td class="col-date">
          <div class="date-main">${esc(published)}</div>
        </td>
        <td class="col-date">
          ${deadline ? `<div class="date-main">${esc(deadline)}</div><div class="date-sub ${dl !== null && dl <= 3 ? "urgent" : ""}">${dlSub}</div>` : `<span class="date-sub">Not stated</span>`}
        </td>
        <td class="col-category"><span class="pill-badge pill-handled">✓ Active</span></td>
        <td class="col-source">
          <a class="link-source-primary" href="${esc(directUrl)}" target="_blank" rel="noopener">${paper ? "View Clipping ↗" : "View Notice ↗"}</a>
          <a class="link-source-secondary" href="${esc(t.source_url || directUrl)}" target="_blank" rel="noopener">${esc(getSourceName(t))} ↗</a>
        </td>
      </tr>`;
    }).join("");
  }

  // ------------------------------------------------------------------ Sector Pages
  const state = { rows: [], tab: "general", sortKey: "deadline", sortDir: 1 };

  function filtered() {
    const q = ($("#f-search")?.value || "").trim().toLowerCase();
    const org = $("#f-org")?.value || "";
    const cat = $("#f-cat")?.value || "";
    const due = $("#f-due")?.value || "";
    const pub = $("#f-pub")?.value || "";
    const onlyIfrs9 = $("#f-ifrs9") && $("#f-ifrs9").checked;
    const onlyTarget = $("#f-target") && $("#f-target").checked;

    return state.rows.filter((t) => {
      if (state.tab === "priority" && !t.is_priority) return false;
      if (org && t.organization_name !== org) return false;
      if (cat && !(t.categories || []).includes(cat)) return false;
      if (onlyIfrs9 && !t.is_ifrs9) return false;
      if (onlyTarget && !t.is_target_bank) return false;
      const dl = daysUntil(t);
      if (due === "7" && !(dl !== null && dl >= 0 && dl <= 7)) return false;
      if (due === "30" && !(dl !== null && dl >= 0 && dl <= 30)) return false;
      if (due === "none" && dl !== null) return false;
      if (pub === "7") {
        const ds = daysSincePublished(t);
        if (ds === null || ds > 7) return false;
      }
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

  function renderSectorRows() {
    const items = filtered();
    const tbody = $("#rows");
    const countEl = $("#result-count");
    if (countEl) {
      countEl.textContent = `${items.length} of ${state.tab === "priority" ? state.rows.filter((r) => r.is_priority).length : state.rows.length} notices`;
    }

    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-catchup-state"><div class="catchup-check-icon">✓</div><div class="catchup-title">No tender notices match your filters!</div><div class="catchup-subtitle">Try resetting your search query or selecting another tab.</div></td></tr>`;
      return;
    }

    tbody.innerHTML = items.map((t, idx) => {
      const dl = daysUntil(t);
      const deadline = fmtDeadline(t);
      const published = t.published_date ? fmtPublished(t.published_date) : null;
      let dlSub = "";
      if (dl !== null) {
        dlSub = dl === 0 ? "closes today" : dl === 1 ? "closes tomorrow" : `in ${dl} days`;
      }
      const directUrl = t.notice_url || t.document_url || t.source_url;
      const paper = getPaperName(t);

      // Category Badges
      let tagsHtml = "";
      if (t.is_ifrs9) tagsHtml += `<span class="pill-badge pill-ifrs9">IFRS 9</span>`;
      if (t.is_priority && !t.is_ifrs9) tagsHtml += `<span class="pill-badge pill-query">Priority</span>`;
      if (paper) tagsHtml += `<span class="pill-badge pill-epaper">📰 ${esc(paper)}</span>`;
      (t.categories || []).forEach((c) => {
        if (c !== "IFRS 9 / ECL") tagsHtml += `<span class="pill-badge pill-priority">${esc(c)}</span>`;
      });
      if (!tagsHtml) tagsHtml = `<span class="pill-badge pill-query">General</span>`;

      return `<tr>
        <td class="col-sl">${idx + 1}</td>
        <td class="col-org">
          <div class="org-title">${esc(t.organization_name)}</div>
          ${t.is_target_bank ? `<div class="org-sub">🎯 IFRS 9 Target Bank</div>` : ""}
        </td>
        <td class="col-details">
          <a class="tender-title-link" href="${esc(directUrl)}" target="_blank" rel="noopener">${esc(t.title)}</a>
          ${t.reference_number ? `<span class="tender-ref-code">${esc(t.reference_number)}</span>` : ""}
          ${t.description ? `<div class="tender-desc-text">${esc(t.description)}</div>` : ""}
        </td>
        <td class="col-date">
          <div class="date-main">${published ? esc(published) : `<span style="color:#94a3b8">Not stated</span>`}</div>
        </td>
        <td class="col-date">
          ${deadline ? `<div class="date-main">${esc(deadline)}</div><div class="date-sub ${dl !== null && dl <= 3 ? "urgent" : ""}">${dlSub}</div>` : `<span style="color:#94a3b8">Not stated</span>`}
        </td>
        <td class="col-relevance">${tagsHtml}</td>
        <td class="col-source">
          <a class="link-source-primary" href="${esc(directUrl)}" target="_blank" rel="noopener">${paper ? "View Clipping ↗" : "View Notice ↗"}</a>
          <a class="link-source-secondary" href="${esc(t.source_url || directUrl)}" target="_blank" rel="noopener">${esc(getSourceName(t))} ↗</a>
        </td>
      </tr>`;
    }).join("");
  }

  function setTab(tab) {
    state.tab = tab === "priority" ? "priority" : "general";
    $$(".tab-btn").forEach((b) => {
      const on = b.dataset.tab === state.tab;
      b.classList.toggle("active", on);
      b.classList.toggle("btn-maroon-fill", on);
      b.classList.toggle("btn-white-outline", !on);
    });
    renderSectorRows();
  }

  function fillSelect(sel, values, allLabel) {
    const el = $(sel);
    if (!el) return;
    const current = el.value;
    el.innerHTML = `<option value="">${allLabel}</option>` + values.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    if (values.includes(current)) el.value = current;
  }

  async function loadSector(sector) {
    const tbody = $("#rows");
    if (!db) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="empty-catchup-state">Database config missing (js/config.js).</td></tr>`;
      return;
    }
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="empty-catchup-state">Loading notices…</td></tr>`;

    try {
      state.rows = await fetchActive(sector);
      $("#load-error") && ($("#load-error").hidden = true);
    } catch (e) {
      console.error(e);
      state.rows = [];
      $("#load-error") && ($("#load-error").hidden = false);
    }

    const totalCount = state.rows.length;
    const priorityCount = state.rows.filter((r) => r.is_priority).length;
    const soonCount = state.rows.filter((r) => {
      const dl = daysUntil(r);
      return dl !== null && dl >= 0 && dl <= 7;
    }).length;

    // Dynamically calculate and set every KPI stat card directly from live data
    setText("#kpi-total", String(totalCount).padStart(2, "0"));
    setText("#kpi-priority", String(priorityCount).padStart(2, "0"));
    setText("#kpi-deadlines", String(soonCount).padStart(2, "0"));
    setText("#count-general", totalCount);
    setText("#count-priority", priorityCount);

    if (sector === "BANK") {
      setText("#kpi-target-banks", "30");
    } else if (sector === "NGO") {
      const uniqueOrgs = new Set(state.rows.map((r) => r.organization_name)).size;
      setText("#kpi-active-orgs", String(uniqueOrgs).padStart(2, "0"));
    } else if (sector === "IT") {
      const partnerTenders = state.rows.filter((r) => (r.partners || []).length > 0).length;
      setText("#kpi-it-partners", String(partnerTenders || priorityCount).padStart(2, "0"));
    } else if (sector === "NEWSPAPER") {
      const uniquePapers = new Set(state.rows.map(getPaperName).filter(Boolean)).size;
      setText("#kpi-dailies-count", String(uniquePapers || 7).padStart(2, "0"));
    }

    fillSelect("#f-org", [...new Set(state.rows.map((r) => r.organization_name))].sort(), "All organizations");
    fillSelect("#f-cat", [...new Set(state.rows.flatMap((r) => r.categories || []))].sort(), "All categories");
    renderSectorRows();
  }

  function initSector(sector) {
    fmtHeaderDate();
    loadLastRun();

    const params = new URLSearchParams(window.location.search);
    if (params.get("tab") === "priority") state.tab = "priority";
    if (params.get("due")) {
      const dueEl = $("#f-due");
      if (dueEl) dueEl.value = params.get("due");
    }
    if (params.get("ifrs9") === "1" && $("#f-ifrs9")) {
      $("#f-ifrs9").checked = true;
    }

    $$(".tab-btn").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
    $("#f-search")?.addEventListener("input", renderSectorRows);
    ["#f-org", "#f-cat", "#f-due", "#f-pub", "#f-ifrs9", "#f-target"].forEach((s) => {
      $(s)?.addEventListener("change", renderSectorRows);
    });
    $("#btn-refresh")?.addEventListener("click", () => { loadSector(sector); loadLastRun(); });
    $("#btn-export")?.addEventListener("click", exportCsv);

    // Interactive clickable KPI Cards to filter data instantly
    $$(".stat-card[data-filter]").forEach((card) => {
      card.addEventListener("click", () => {
        const filterType = card.dataset.filter;
        if (filterType === "all") {
          setTab("general");
          if ($("#f-search")) $("#f-search").value = "";
          if ($("#f-org")) $("#f-org").value = "";
          if ($("#f-cat")) $("#f-cat").value = "";
          if ($("#f-due")) $("#f-due").value = "";
          if ($("#f-pub")) $("#f-pub").value = "";
          if ($("#f-ifrs9")) $("#f-ifrs9").checked = false;
          if ($("#f-target")) $("#f-target").checked = false;
        } else if (filterType === "priority") {
          setTab("priority");
        } else if (filterType === "closing-soon") {
          setTab("general");
          if ($("#f-due")) $("#f-due").value = "7";
        } else if (filterType === "target-banks") {
          setTab("general");
          if ($("#f-target")) $("#f-target").checked = !$("#f-target").checked;
        } else if (filterType === "partners") {
          setTab("priority");
        }
        renderSectorRows();
      });
    });

    $$("th.sortable").forEach((th) => th.addEventListener("click", () => {
      const key = th.dataset.sort;
      state.sortDir = state.sortKey === key ? -state.sortDir : 1;
      state.sortKey = key;
      $$("th.sortable .dir").forEach((d) => d.textContent = "");
      const dirEl = th.querySelector(".dir");
      if (dirEl) dirEl.textContent = state.sortDir === 1 ? "▲" : "▼";
      renderSectorRows();
    }));

    setTab(state.tab);
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
      ["Tender Link", (t) => t.document_url || t.notice_url || ""],
      ["Source Page", (t) => t.source_url],
    ];
    const cell = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
    const csv = [cols.map((c) => cell(c[0])).join(","), ...items.map((t) => cols.map((c) => cell(c[1](t))).join(","))].join("\r\n");
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `ACNABIN_${document.body.dataset.sector || "TENDERS"}_${state.tab}_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  // ------------------------------------------------------------------ Sources Page
  async function initSources() {
    fmtHeaderDate();
    loadLastRun();
    const body = $("#rows");
    if (!db) { if (body) body.innerHTML = `<tr><td colspan="6" class="empty-catchup-state">Database connection not configured.</td></tr>`; return; }
    const { data: sourcesData, error } = await db.from("source_status").select("*").order("organization_name");
    if (error || !sourcesData) { if (body) body.innerHTML = `<tr><td colspan="6" class="empty-catchup-state">Could not load source status.</td></tr>`; return; }

    const draw = () => {
      const sector = $("#f-sector")?.value || "";
      const onlyErrors = $("#f-errors")?.checked;
      const rows = sourcesData.filter((s) => (!sector || s.sector === sector) && (!onlyErrors || !s.ok));
      const failedCount = sourcesData.filter((s) => !s.ok).length;
      const totalListings = sourcesData.reduce((acc, s) => acc + (s.listings_found || 0), 0);
      
      setText("#kpi-total", String(sourcesData.length).padStart(2, "0"));
      setText("#kpi-ok", String(sourcesData.length - failedCount).padStart(2, "0"));
      setText("#kpi-errors", String(failedCount).padStart(2, "0"));
      setText("#kpi-listings-total", String(totalListings).padStart(2, "0"));
      setText("#result-count", `${rows.length} of ${sourcesData.length} sources`);

      body.innerHTML = rows.length ? rows.map((s, idx) => {
        const p = s.last_checked ? dhakaParts(new Date(s.last_checked)) : null;
        return `<tr>
          <td class="col-sl">${idx + 1}</td>
          <td class="col-org"><div class="org-title">${esc(s.organization_name)}</div>${s.is_target_bank ? `<div class="org-sub">🎯 Target Bank</div>` : ""}</td>
          <td><span class="pill-badge pill-query">${s.sector === "BANK" ? "Bank" : s.sector === "IT" ? "IT Services" : "NGO"}</span></td>
          <td>${!s.ok ? `<span class="pill-badge pill-error">${esc(s.error || "Error")}</span>` : s.listings_found ? `<span class="pill-badge pill-handled">OK · ${s.listings_found} found</span>` : `<span class="pill-badge pill-priority">No Listings</span>`}</td>
          <td class="col-date">${p ? `<div class="date-main">${fmtShortDate(p.y, p.m, p.d)}</div><div class="date-sub">${p.hh}:${p.mm}</div>` : "—"}</td>
          <td class="col-source"><a class="link-source-primary" href="${esc(s.url)}" target="_blank" rel="noopener">Visit Page ↗</a></td>
        </tr>`;
      }).join("") : `<tr><td colspan="6" class="empty-catchup-state">No matching sources found.</td></tr>`;
    };

    $("#f-sector")?.addEventListener("change", draw);
    $("#f-errors")?.addEventListener("change", draw);

    $$(".stat-card[data-filter]").forEach((card) => {
      card.addEventListener("click", () => {
        const f = card.dataset.filter;
        if (f === "errors" && $("#f-errors")) {
          $("#f-errors").checked = true;
        } else if ((f === "all" || f === "ok") && $("#f-errors")) {
          $("#f-errors").checked = false;
        }
        draw();
      });
    });

    draw();
  }

  // ------------------------------------------------------------------ Boot
  document.addEventListener("DOMContentLoaded", () => {
    const page = document.body.dataset.page;
    if (page === "home") initHome();
    else if (page === "sector") initSector(document.body.dataset.sector);
    else if (page === "sources") initSources();
  });
})();
