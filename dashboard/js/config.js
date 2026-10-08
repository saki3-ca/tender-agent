// Supabase Dashboard Config
window.ENV = {
  SUPABASE_URL: "https://lhlklttxkchknbjplbvn.supabase.co",
  SUPABASE_ANON_KEY: "sb_publishable_MpVRbNQCuLlXyU1czkf6aw_Jh1zt9mo"
};

// Embedded inside the ACNABIN Task Tracker portal (iframe): lets the stylesheet hide the dashboard's own
// header so it sits under the portal's header. "?embed=1" forces it, e.g. for previews. The iframe check
// survives page-to-page navigation inside the dashboard.
(function () {
  try {
    var embedded = window.self !== window.top || /[?&]embed=1\b/.test(window.location.search);
    if (embedded) document.documentElement.classList.add("embedded");
  } catch (e) {
    document.documentElement.classList.add("embedded"); // cross-origin parent: definitely framed
  }
})();

// Embedded: portal-style line icons for the view links, and report the page height to the portal so it can
// size the frame to fit (no inner scrollbar). The portal checks the sender, so only the height is shared.
(function () {
  var ICONS = {
    "index.html": '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
    "bank.html": '<line x1="3" x2="21" y1="22" y2="22"/><line x1="6" x2="6" y1="18" y2="11"/><line x1="10" x2="10" y1="18" y2="11"/><line x1="14" x2="14" y1="18" y2="11"/><line x1="18" x2="18" y1="18" y2="11"/><polygon points="12 2 20 7 4 7"/>',
    "ngo.html": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "it.html": '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>',
    "newspaper.html": '<path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/>',
    "admin.html": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
    "sources.html": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>'
  };
  function start() {
    if (!document.documentElement.classList.contains("embedded")) return;
    var links = document.querySelectorAll(".nav-tabs a.tab-btn");
    for (var i = 0; i < links.length; i++) {
      var path = ICONS[links[i].getAttribute("href")];
      var icon = links[i].querySelector(".tab-icon");
      if (path && icon) icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + path + "</svg>";
    }
    var last = 0;
    function report() {
      var h = Math.ceil(document.body.getBoundingClientRect().height);
      if (h === last || window.parent === window) return;
      last = h;
      window.parent.postMessage({ type: "tender-agent-height", height: h }, "*");
    }
    if (window.ResizeObserver) new ResizeObserver(report).observe(document.body);
    window.addEventListener("load", report);
    window.addEventListener("resize", report);
    report();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();

// Admin section: shown only when the portal says the signed-in Task Tracker user is an Admin. This is a display
// control only; changing tender sources still needs the allow-listed Supabase sign-in, which the database enforces.
// Outside the portal nobody is an admin, so the Admin page sends the visitor back to the Overview.
(function () {
  var embedded = document.documentElement.classList.contains("embedded");
  var admin = false;
  try { admin = embedded && sessionStorage.getItem("ta_admin") === "1"; } catch (e) {}

  function apply() {
    document.documentElement.classList.toggle("ta-admin", admin);
    var els = document.querySelectorAll("[data-admin-only]");
    for (var i = 0; i < els.length; i++) els[i].hidden = !admin;
  }
  function setAdmin(on) {
    admin = on;
    try { sessionStorage.setItem("ta_admin", on ? "1" : "0"); } catch (e) {}
    apply();
  }
  function onAdminPage() { return document.body && document.body.getAttribute("data-page") === "admin"; }

  var answered = false;
  window.addEventListener("message", function (e) {
    if (e.source !== window.parent || !e.data || e.data.type !== "tender-agent-role") return;
    answered = true;
    setAdmin(e.data.admin === true);
    if (!admin && onAdminPage()) location.replace("index.html");
  });

  function start() {
    apply();
    if (embedded && window.parent !== window) window.parent.postMessage({ type: "tender-agent-hello" }, "*");
    if (onAdminPage()) {
      if (!embedded) { location.replace("index.html"); return; }
      setTimeout(function () { if (!answered) location.replace("index.html"); }, 2500);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
