// "Run now" for the Admin page, and the hourly trigger that does not depend on GitHub's cron.
// GET  -> state of the latest run of the workflow on GitHub Actions
// POST -> starts the workflow (unless one is already queued or running)
// ?workflow=monitor (default) or ?workflow=epaper chooses which workflow.
// Allowed callers: Task Tracker Admins (the portal's bridge token, x-tracker-token, is checked by ta_admin_check)
// and the Supabase scheduled job (x-cron-secret equal to the secret kept in the database Vault, checked by
// ta_cron_check; a CRON_SECRET function secret with the same value is accepted too). The GitHub token
// stays in the function secrets (GH_DISPATCH_TOKEN) and is never sent to the browser.
import { createClient } from "npm:@supabase/supabase-js@2";

const REPO = Deno.env.get("GH_REPO") ?? "saki3-ca/tender-agent";
const WORKFLOWS: Record<string, string> = { monitor: "monitor.yml", epaper: "epaper.yml" };

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-tracker-token",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } });

/** Compares two secrets without stopping at the first difference. */
function sameSecret(a: string, b: string): boolean {
  const x = new TextEncoder().encode(a);
  const y = new TextEncoder().encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

/** The scheduled job's secret: the CRON_SECRET function secret, or the one in the database Vault (ta_cron_check). */
async function isScheduledCall(given: string): Promise<boolean> {
  if (given.length < 16) return false;
  const cronSecret = Deno.env.get("CRON_SECRET") ?? "";
  if (cronSecret.length >= 16 && sameSecret(given, cronSecret)) return true;
  const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!);
  const { data, error } = await db.rpc("ta_cron_check", { p_secret: given });
  return !error && data === true;
}

function gh(workflow: string, path: string, init: RequestInit = {}) {
  return fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${Deno.env.get("GH_DISPATCH_TOKEN")}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "acnabin-tender-monitor",
    },
  });
}

async function latestRun(workflow: string) {
  const res = await gh(workflow, "/runs?per_page=1");
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

  const workflow = WORKFLOWS[new URL(req.url).searchParams.get("workflow") ?? "monitor"];
  if (!workflow) return json({ error: "Unknown workflow" }, 400);

  const isSchedule = await isScheduledCall(req.headers.get("x-cron-secret") ?? "");
  if (!isSchedule) {
    const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!);
    const { data: isAdmin, error } = await db.rpc("ta_admin_check", { p_token: req.headers.get("x-tracker-token") ?? "" });
    if (error || !isAdmin) return json({ error: "Not allowed" }, 403);
  }
  if (!Deno.env.get("GH_DISPATCH_TOKEN")) return json({ error: "GH_DISPATCH_TOKEN is not configured" }, 500);

  try {
    const run = await latestRun(workflow);
    if (req.method === "GET") return json({ run });
    if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);

    if (run && run.status !== "completed") return json({ started: false, reason: "already_running", run });
    const res = await gh(workflow, "/dispatches", { method: "POST", body: JSON.stringify({ ref: "main" }) });
    if (res.status !== 204) return json({ error: `GitHub refused the request (${res.status})` }, 502);
    return json({ started: true });
  } catch (e) {
    return json({ error: String(e) }, 502);
  }
});
