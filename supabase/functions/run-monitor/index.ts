// "Run now" for the Admin page.
// GET  -> state of the latest monitoring run on GitHub Actions
// POST -> starts the monitor workflow (unless one is already queued or running)
// Only signed-in users on the admin allow-list (am_i_admin) may call it. The GitHub token
// stays in the function secrets (GH_DISPATCH_TOKEN) and is never sent to the browser.
import { createClient } from "npm:@supabase/supabase-js@2";

const REPO = Deno.env.get("GH_REPO") ?? "saki3-ca/tender-agent";
const WORKFLOW = "monitor.yml";
const GH = `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}`;

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } });

function gh(path: string, init: RequestInit = {}) {
  return fetch(`${GH}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${Deno.env.get("GH_DISPATCH_TOKEN")}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "acnabin-tender-monitor",
    },
  });
}

async function latestRun() {
  const res = await gh("/runs?per_page=1");
  if (!res.ok) throw new Error(`GitHub ${res.status}`);
  const run = (await res.json()).workflow_runs?.[0];
  if (!run) return null;
  return {
    status: run.status,            // queued | in_progress | completed
    conclusion: run.conclusion,    // success | failure | cancelled | null
    started_at: run.run_started_at ?? run.created_at,
    updated_at: run.updated_at,
    event: run.event,              // schedule | workflow_dispatch
    url: run.html_url,
  };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });

  const auth = req.headers.get("Authorization") ?? "";
  const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!, {
    global: { headers: { Authorization: auth } },
  });
  const { data: isAdmin, error } = await db.rpc("am_i_admin");
  if (error || !isAdmin) return json({ error: "Not allowed" }, 403);
  if (!Deno.env.get("GH_DISPATCH_TOKEN")) return json({ error: "GH_DISPATCH_TOKEN is not configured" }, 500);

  try {
    const run = await latestRun();
    if (req.method === "GET") return json({ run });
    if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);

    if (run && run.status !== "completed") return json({ started: false, reason: "already_running", run });
    const res = await gh("/dispatches", { method: "POST", body: JSON.stringify({ ref: "main" }) });
    if (res.status !== 204) return json({ error: `GitHub refused the request (${res.status})` }, 502);
    return json({ started: true });
  } catch (e) {
    return json({ error: String(e) }, 502);
  }
});
