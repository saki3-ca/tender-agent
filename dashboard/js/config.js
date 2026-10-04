// Supabase Dashboard Config
// Values replaced during Cloudflare Pages deployment or local test
window.ENV = {
  SUPABASE_URL: window.location.hostname === "localhost" ? "" : "__SUPABASE_URL__",
  SUPABASE_ANON_KEY: window.location.hostname === "localhost" ? "" : "__SUPABASE_ANON_KEY__"
};
