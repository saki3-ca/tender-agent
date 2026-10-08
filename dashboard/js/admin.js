/*
 * Admin page: manage tender source URLs (table admin_sources).
 * Writing requires a Supabase sign-in by a user listed in app_users; the database enforces this.
 */
(function () {
  "use strict";

  const env = window.ENV || {};
  let db = null;
  if (env.SUPABASE_URL && !env.SUPABASE_URL.startsWith("__") && window.supabase) {
    db = window.supabase.createClient(env.SUPABASE_URL, env.SUPABASE_ANON_KEY);
  }

  const $ = (s) => document.querySelector(s);
  const esc = (v) => String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const NEW_ORG = "__new__";

  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
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

  let statuses = [];   // source_status rows (last run result per source)
  let managed = [];    // admin_sources rows

  function msg(sel, text, isError) {
    const el = $(sel);
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("error", !!isError);
  }

  function validUrl(value) {
    try {
      const u = new URL(value.trim());
      return (u.protocol === "http:" || u.protocol === "https:") && u.hostname.includes(".");
    } catch (e) {
      return false;
    }
  }

  function fmt(ts) {
    if (!ts) return "—";
    return new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Dhaka", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(ts));
  }

  function statusTag(st) {
    if (!st) return `<span class="pill-badge pill-query">Not checked</span>`;
    if (!st.ok) return `<span class="pill-badge pill-error">${esc(st.error || "Error")}</span>`;
    if (!st.listings_found) return `<span class="pill-badge pill-priority">No Listings</span>`;
    return `<span class="pill-badge pill-handled">OK · ${st.listings_found} found</span>`;
  }

  // -------------------------------------------------------------- auth
  async function showState() {
    fmtHeaderDate();
    if (!db) {
      $("#signin-panel").hidden = false;
      $("#admin-area").hidden = true;
      return;
    }

    const { data: { session } } = await db.auth.getSession();
    if (!session) {
      $("#signin-panel").hidden = false;
      $("#admin-area").hidden = false; // keep preview visible
      $("#admin-user-name").textContent = "GUEST ADMIN";
      $("#admin-user-email").textContent = "✉ Not Signed In";
      $("#signout-btn").textContent = "Sign In";
      $("#signout-btn").onclick = () => { $("#signin-panel").hidden = false; $("#si-email").focus(); };
      await loadData();
      return;
    }

    const email = session.user.email;
    $("#admin-user-name").textContent = email.split("@")[0].toUpperCase();
    $("#admin-user-email").textContent = `✉ ${email}`;
    $("#admin-user-id").textContent = `# User ID: ${session.user.id.slice(0, 8)}`;
    $("#signout-btn").textContent = "Sign Out";
    $("#signout-btn").onclick = async () => { await db.auth.signOut(); showState(); };

    const { data: isAdmin, error } = await db.rpc("am_i_admin");
    if (error || !isAdmin) {
      $("#signin-panel").hidden = false;
      $("#signin-form").hidden = true;
      msg("#signin-msg", `Signed in as ${email}, but this account is not on the admin list (table app_users).`, true);
      return;
    }

    $("#signin-panel").hidden = true;
    $("#admin-area").hidden = false;
    refreshRun();
    await loadData();
  }

  $("#signin-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg("#signin-msg", "Signing in…");
    const { error } = await db.auth.signInWithPassword({ email: $("#si-email").value.trim(), password: $("#si-password").value });
    if (error) { msg("#signin-msg", error.message, true); return; }
    msg("#signin-msg", "");
    showState();
  });

  // -------------------------------------------------------------- data
  async function loadData() {
    if (!db) return;
    try {
      const [st, ad, activeTenders] = await Promise.all([
        db.from("source_status").select("*").order("organization_name"),
        db.from("admin_sources").select("*").order("created_at", { ascending: false }),
        db.from("v_active_tenders").select("count", { count: "exact", head: true })
      ]);
      statuses = st.data || [];
      managed = ad.data || [];
      if (activeTenders && activeTenders.count != null) {
        const countEl = $("#profile-total-tenders");
        if (countEl) countEl.textContent = activeTenders.count;
      }
      fillOrgs();
      renderBroken();
      renderManaged();
    } catch (e) {
      console.warn("Error loading admin data", e);
    }
  }

  function orgList() {
    const orgs = new Map();
    for (const s of statuses) orgs.set(s.organization_id, { id: s.organization_id, name: s.organization_name, sector: s.sector });
    for (const m of managed) if (m.organization_id && !orgs.has(m.organization_id)) orgs.set(m.organization_id, { id: m.organization_id, name: m.organization_name, sector: m.sector });
    return [...orgs.values()].sort((a, b) => a.name.localeCompare(b.name));
  }

  function fillOrgs() {
    const el = $("#a-org");
    if (!el) return;
    const orgs = orgList();
    const group = (sector, label) => `<optgroup label="${label}">` + orgs.filter((o) => o.sector === sector)
      .map((o) => `<option value="${esc(o.id)}">${esc(o.name)}</option>`).join("") + "</optgroup>";
    el.innerHTML = `<option value="">Select organization…</option><option value="${NEW_ORG}">+ New organization…</option>`
      + group("BANK", "Banks") + group("NGO", "NGOs");
  }

  $("#a-org")?.addEventListener("change", () => {
    const isNew = $("#a-org").value === NEW_ORG;
    $("#a-name-wrap").hidden = !isNew;
    $("#a-sector-wrap").hidden = !isNew;
    $("#a-name").required = isNew;
  });

  // -------------------------------------------------------------- add
  $("#add-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!db) return;
    const url = $("#a-url").value.trim();
    if (!validUrl(url)) { msg("#add-msg", "Enter a full web address starting with https:// or http://", true); return; }
    const known = statuses.find((s) => s.url === url) || managed.find((m) => m.url === url);
    if (known) { msg("#add-msg", "This URL is already monitored.", true); return; }

    let row;
    if ($("#a-org").value === NEW_ORG) {
      const name = $("#a-name").value.trim();
      if (!name) { msg("#add-msg", "Enter the organization name.", true); return; }
      row = { organization_id: null, organization_name: name, sector: $("#a-sector").value };
    } else {
      const org = orgList().find((o) => o.id === $("#a-org").value);
      if (!org) { msg("#add-msg", "Select an organization.", true); return; }
      row = { organization_id: org.id, organization_name: org.name, sector: org.sector };
    }
    Object.assign(row, {
      url,
      notes: $("#a-notes").value.trim() || null,
      requires_js: $("#a-js").checked,
      verify_ssl: !$("#a-ssl").checked,
      country_filter: $("#a-country").checked,
      enabled: true,
    });
    const { error } = await db.from("admin_sources").insert(row);
    if (error) { msg("#add-msg", `Could not save: ${error.message}`, true); return; }
    msg("#add-msg", "Saved. The page will be checked in the next monitoring run.");
    $("#add-form").reset();
    $("#a-name-wrap").hidden = true;
    $("#a-sector-wrap").hidden = true;
    loadData();
  });

  // -------------------------------------------------------------- broken sources
  function renderBroken() {
    const tbody = $("#broken-rows");
    if (!tbody) return;
    const corrected = new Set(managed.map((m) => m.source_id));
    const q = ($("#broken-search")?.value || "").trim().toLowerCase();
    const sector = $("#broken-sector")?.value || "";
    const rows = statuses.filter((s) => (!s.ok || !s.listings_found) && !corrected.has(s.source_id)
      && (!sector || s.sector === sector) && (!q || s.organization_name.toLowerCase().includes(q)));

    tbody.innerHTML = rows.length ? rows.map((s) => `
      <tr data-id="${esc(s.source_id)}">
        <td class="col-org"><div class="org-title">${esc(s.organization_name)}</div><div class="org-sub">${s.sector === "BANK" ? "Bank" : "NGO"}</div></td>
        <td>${statusTag(s)}</td>
        <td style="max-width:240px; word-break:break-all;"><a class="link-source-secondary" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a></td>
        <td><input type="url" class="url-input" placeholder="https://…" style="width:100%; min-width:200px;"></td>
        <td><button class="btn-ctrl btn-primary" data-action="fix" type="button">Save</button></td>
      </tr>`).join("") : `<tr><td colspan="5" class="empty-catchup-state"><div class="catchup-check-icon">✓</div><div class="catchup-title">All sources healthy!</div><div class="catchup-subtitle">Every monitored portal responded successfully.</div></td></tr>`;
  }

  $("#broken-search")?.addEventListener("input", renderBroken);
  $("#broken-sector")?.addEventListener("change", renderBroken);

  $("#broken-rows")?.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action=fix]");
    if (!btn || !db) return;
    const tr = btn.closest("tr");
    const input = tr.querySelector(".url-input");
    const url = input.value.trim();
    if (!validUrl(url)) { input.style.borderColor = "var(--color-rose)"; input.focus(); return; }
    const s = statuses.find((x) => x.source_id === tr.dataset.id);
    btn.disabled = true;
    const { error } = await db.from("admin_sources").upsert({
      source_id: s.source_id, url, organization_id: s.organization_id,
      organization_name: s.organization_name, sector: s.sector, enabled: true,
    });
    btn.disabled = false;
    if (error) { alert(`Could not save: ${error.message}`); return; }
    loadData();
  });

  // -------------------------------------------------------------- managed sources
  function renderManaged() {
    const tbody = $("#managed-rows");
    if (!tbody) return;
    const byId = new Map(statuses.map((s) => [s.source_id, s]));
    tbody.innerHTML = managed.length ? managed.map((m) => {
      const st = byId.get(m.source_id);
      const checkedAfterSave = st && st.last_checked && st.url === m.url && new Date(st.last_checked) >= new Date(m.updated_at);
      return `
      <tr data-id="${esc(m.source_id)}">
        <td class="col-org"><div class="org-title">${esc(m.organization_name)}</div>
          <div class="org-sub">${m.sector === "BANK" ? "Bank" : "NGO"} · ${m.source_id && m.source_id.startsWith("src_admin_") ? "added" : "corrected"} ${esc(fmt(m.created_at))}</div></td>
        <td style="max-width:280px; word-break:break-all;"><a class="link-source-primary" href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.url)}</a>${m.notes ? `<div style="font-size:11.5px; color:var(--text-muted); margin-top:2px;">${esc(m.notes)}</div>` : ""}</td>
        <td>${checkedAfterSave ? `${statusTag(st)}<div style="font-size:11.5px; color:var(--text-dim); margin-top:2px;">${esc(fmt(st.last_checked))}</div>` : `<span class="pill-badge pill-query">Queued</span>`}</td>
        <td><label class="check"><input type="checkbox" data-action="toggle" ${m.enabled ? "checked" : ""}> Enabled</label></td>
        <td><button class="btn-ctrl" data-action="remove" type="button" style="color:var(--color-rose);">Remove</button></td>
      </tr>`;
    }).join("") : `<tr><td colspan="5" class="empty-catchup-state">No custom URLs added yet.</td></tr>`;
  }

  $("#managed-rows")?.addEventListener("change", async (e) => {
    if (e.target.dataset.action !== "toggle" || !db) return;
    const id = e.target.closest("tr").dataset.id;
    const { error } = await db.from("admin_sources").update({ enabled: e.target.checked }).eq("source_id", id);
    if (error) { alert(`Could not save: ${error.message}`); }
    loadData();
  });

  $("#managed-rows")?.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action=remove]");
    if (!btn || !db) return;
    const id = btn.closest("tr").dataset.id;
    if (!confirm("Remove this URL from monitoring?")) return;
    const { error } = await db.from("admin_sources").delete().eq("source_id", id);
    if (error) { alert(`Could not remove: ${error.message}`); }
    loadData();
  });

  // -------------------------------------------------------------- run now
  const RUN_FN = `${env.SUPABASE_URL}/functions/v1/run-monitor`;
  let pollTimer = null;

  async function callRunFn(method) {
    if (!db) throw new Error("No database connection");
    const { data: { session } } = await db.auth.getSession();
    if (!session) throw new Error("Please sign in as an admin to trigger scraper runs.");
    const res = await fetch(RUN_FN, {
      method,
      headers: { Authorization: `Bearer ${session.access_token}`, apikey: env.SUPABASE_ANON_KEY },
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    return body;
  }

  async function lastCompleted() {
    if (!db) return;
    try {
      const { data } = await db.from("v_last_run").select("end_time").limit(1);
      const end = data && data[0] && data[0].end_time;
      const el = $("#run-last");
      if (el) el.textContent = end ? `Last completed: ${fmt(end)} (Dhaka)` : "";
    } catch (e) {}
  }

  function showRun(run) {
    const btn = $("#run-now");
    const busy = run && run.status !== "completed";
    if (btn) btn.disabled = !!busy;
    const stateEl = $("#run-state");
    if (!stateEl) return busy;
    if (!run) { stateEl.textContent = "Ready to launch crawler pipeline."; return busy; }
    let text;
    if (run.status === "queued") text = "Run queued — starting shortly…";
    else if (run.status === "in_progress") text = `Running since ${fmt(run.started_at)} — approx 10–15 minutes.`;
    else if (run.conclusion === "success") text = `Last run finished ${fmt(run.updated_at)}.`;
    else text = `Last run ${run.conclusion || "ended"} (${fmt(run.updated_at)}).`;
    stateEl.innerHTML = `${esc(text)} ${run.url ? `<a href="${esc(run.url)}" target="_blank" rel="noopener">Details ↗</a>` : ""}`;
    return busy;
  }

  async function refreshRun() {
    clearTimeout(pollTimer);
    lastCompleted();
    try {
      const { run } = await callRunFn("GET");
      const wasBusy = $("#run-now") && $("#run-now").disabled;
      const busy = showRun(run);
      if (busy) pollTimer = setTimeout(refreshRun, 20000);
      else if (wasBusy) { msg("#run-msg", "Run completed successfully. Refresh the Bank / NGO pages to view the new tenders."); loadData(); }
    } catch (e) {
      $("#run-state") && ($("#run-state").textContent = "Ready to launch crawler pipeline.");
    }
  }

  $("#run-now")?.addEventListener("click", async () => {
    const btn = $("#run-now");
    if (btn) btn.disabled = true;
    msg("#run-msg", "Initiating crawler pipeline…");
    try {
      const r = await callRunFn("POST");
      msg("#run-msg", r.started ? "Monitoring run started! This status updates automatically." : "A run is already in progress.");
      setTimeout(refreshRun, 5000);
    } catch (e) {
      if (btn) btn.disabled = false;
      msg("#run-msg", e.message, true);
    }
  });

  document.addEventListener("DOMContentLoaded", showState);
})();
