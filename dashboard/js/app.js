/**
 * ACNABIN Tender Dashboard Client Application
 * Connects via supabase-js with anon key and provides real-time filtering & client-side Excel/CSV exports.
 */

// Initialize Supabase Client if credentials injected
let supabaseClient = null;
if (window.ENV && window.ENV.SUPABASE_URL && !window.ENV.SUPABASE_URL.startsWith("__")) {
  try {
    supabaseClient = supabase.createClient(window.ENV.SUPABASE_URL, window.ENV.SUPABASE_ANON_KEY);
  } catch (e) {
    console.warn("Supabase client init error:", e);
  }
}

// Current dataset for filtering and export
let currentOpportunities = [];

async function loadKPIs() {
  if (!supabaseClient) return;
  try {
    const { data, error } = await supabaseClient.from("v_kpis").select("*").single();
    if (!error && data) {
      if (document.getElementById("kpi-monitored")) document.getElementById("kpi-monitored").innerText = data.total_organizations || 0;
      if (document.getElementById("kpi-target-banks")) document.getElementById("kpi-target-banks").innerText = data.ifrs9_target_banks || 30;
      if (document.getElementById("kpi-very-high")) document.getElementById("kpi-very-high").innerText = data.very_high_priority || 0;
      if (document.getElementById("kpi-high")) document.getElementById("kpi-high").innerText = data.high_priority || 0;
      if (document.getElementById("kpi-deadlines")) document.getElementById("kpi-deadlines").innerText = data.deadlines_within_7_days || 0;
      if (document.getElementById("kpi-new-today")) document.getElementById("kpi-new-today").innerText = data.new_today || 0;
    }
  } catch (err) {
    console.error("Error loading KPIs:", err);
  }
}

async function loadOpportunities(viewName = "v_today_priority") {
  const tbody = document.getElementById("opportunities-tbody");
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 2rem;">Loading live opportunities...</td></tr>`;

  if (!supabaseClient) {
    // Demo / offline placeholder
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="empty-state">
          <div class="empty-state-icon">📊</div>
          <h3>Running in Local/Demo Mode</h3>
          <p>Configure SUPABASE_URL and SUPABASE_ANON_KEY in settings or deploy to Cloudflare Pages to view live production data.</p>
        </td>
      </tr>
    `;
    return;
  }

  try {
    const { data, error } = await supabaseClient.from(viewName).select("*");
    if (error) throw error;

    currentOpportunities = data || [];
    renderTable(currentOpportunities);
  } catch (err) {
    console.error("Failed to load opportunities:", err);
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color: var(--color-very-high); padding: 2rem;">Error loading data from database.</td></tr>`;
  }
}

function renderTable(items) {
  const tbody = document.getElementById("opportunities-tbody");
  if (!tbody) return;

  if (!items || items.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="empty-state">
          <div class="empty-state-icon">🔍</div>
          <h3>No opportunities match the criteria</h3>
          <p>Try adjusting your search query or filters.</p>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = items.map(opp => {
    const priorityClass = `badge-${(opp.priority || 'low').toLowerCase().replace(' ', '-')}`;
    const pipelineBadge = opp.pipeline === 'IFRS9_TARGET' 
      ? `<span class="badge badge-target">IFRS 9 Target</span>` 
      : `<span class="badge badge-market">General Market</span>`;

    const daysRemaining = opp.days_remaining !== null && opp.days_remaining !== undefined 
      ? `<span style="color: ${opp.days_remaining <= 3 ? 'var(--color-very-high)' : 'inherit'}; font-weight: 600;">${opp.days_remaining}d left</span>` 
      : 'N/A';

    return `
      <tr>
        <td>
          <div style="font-weight: 600; color: #fff;">${escapeHtml(opp.organization_name || 'N/A')}</div>
          <div style="font-size: 0.75rem; color: var(--text-dim);">${escapeHtml(opp.reference_number || 'No Ref')}</div>
        </td>
        <td>
          <div style="font-weight: 500;">
            <a href="opportunity.html?id=${opp.id}" style="color: #67e8f9; text-decoration: none;">${escapeHtml(opp.title)}</a>
          </div>
          <div style="font-size: 0.775rem; color: var(--text-muted); margin-top: 0.2rem;">${escapeHtml(opp.category)}</div>
        </td>
        <td>${pipelineBadge}</td>
        <td><span class="badge ${priorityClass}">${opp.priority}</span></td>
        <td style="font-weight: 700; color: #fff;">${opp.score}/100</td>
        <td>${daysRemaining}</td>
        <td>
          <a href="${opp.source_url}" target="_blank" rel="noopener" class="btn" style="padding: 0.25rem 0.6rem; font-size: 0.75rem;">Source ↗</a>
        </td>
      </tr>
    `;
  }).join("");
}

function applyFilters() {
  const search = (document.getElementById("filter-search")?.value || "").toLowerCase();
  const priority = document.getElementById("filter-priority")?.value || "ALL";
  const pipeline = document.getElementById("filter-pipeline")?.value || "ALL";

  const filtered = currentOpportunities.filter(item => {
    const matchesSearch = !search || 
      (item.title && item.title.toLowerCase().includes(search)) ||
      (item.organization_name && item.organization_name.toLowerCase().includes(search)) ||
      (item.reference_number && item.reference_number.toLowerCase().includes(search));

    const matchesPriority = priority === "ALL" || item.priority === priority;
    const matchesPipeline = pipeline === "ALL" || item.pipeline === pipeline;

    return matchesSearch && matchesPriority && matchesPipeline;
  });

  renderTable(filtered);
}

// Client-Side CSV Export (Section 24)
function exportToCSV() {
  if (!currentOpportunities || currentOpportunities.length === 0) {
    alert("No opportunities available to export.");
    return;
  }

  const headers = [
    "Organization", "Organization Type", "Pipeline", "Tender Title", "Reference",
    "Category", "Priority", "Score", "Fit Type", "Publication Date", "Deadline",
    "Scope", "Potential Service", "Eligibility", "Source URL", "Confidence", "First Seen"
  ];

  const rows = currentOpportunities.map(o => [
    `"${(o.organization_name || '').replace(/"/g, '""')}"`,
    `"${(o.organization_type || '').replace(/"/g, '""')}"`,
    `"${o.pipeline || ''}"`,
    `"${(o.title || '').replace(/"/g, '""')}"`,
    `"${(o.reference_number || '').replace(/"/g, '""')}"`,
    `"${o.category || ''}"`,
    `"${o.priority || ''}"`,
    o.score || 0,
    `"${o.fit_type || ''}"`,
    `"${o.publication_date || ''}"`,
    `"${o.submission_deadline || ''}"`,
    `"${(o.scope_of_work || o.title || '').replace(/"/g, '""')}"`,
    `"${(o.potential_acnabin_service || '').replace(/"/g, '""')}"`,
    `"${(o.eligibility || '').replace(/"/g, '""')}"`,
    `"${o.source_url || ''}"`,
    `"${o.ai_confidence || ''}"`,
    `"${o.first_seen || ''}"`
  ]);

  const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map(r => r.join(","))].join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `ACNABIN_Opportunities_${new Date().toISOString().split('T')[0]}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

// Client-Side Excel Export using SheetJS if available
function exportToExcel() {
  if (typeof XLSX === "undefined") {
    // Fallback to CSV if SheetJS CDN is offline
    exportToCSV();
    return;
  }

  const dataToExport = currentOpportunities.map(o => ({
    "Organization": o.organization_name,
    "Pipeline": o.pipeline,
    "Tender Title": o.title,
    "Reference": o.reference_number,
    "Category": o.category,
    "Priority": o.priority,
    "Score": o.score,
    "Fit Type": o.fit_type,
    "Deadline": o.submission_deadline,
    "Source URL": o.source_url
  }));

  const worksheet = XLSX.utils.json_to_sheet(dataToExport);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, worksheet, "Opportunities");
  XLSX.writeFile(workbook, `ACNABIN_Opportunities_${new Date().toISOString().split('T')[0]}.xlsx`);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

document.addEventListener("DOMContentLoaded", () => {
  loadKPIs();
  loadOpportunities();

  document.getElementById("filter-search")?.addEventListener("input", applyFilters);
  document.getElementById("filter-priority")?.addEventListener("change", applyFilters);
  document.getElementById("filter-pipeline")?.addEventListener("change", applyFilters);
  document.getElementById("btn-export-csv")?.addEventListener("click", exportToCSV);
  document.getElementById("btn-export-excel")?.addEventListener("click", exportToExcel);
});
