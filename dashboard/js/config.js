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
