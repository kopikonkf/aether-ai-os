const state = {
  token: sessionStorage.getItem("aether.operator.token") || "",
  gateway: sessionStorage.getItem("aether.gateway.url") || window.location.origin,
  snapshot: null,
  timer: null,
};

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

function apiUrl(path) {
  const base = (state.gateway || window.location.origin).replace(/\/$/, "");
  return `${base}${path}`;
}

async function request(path, options = {}) {
  if (!state.token) throw new Error("Operator token is required");
  const headers = { "X-Aether-Operator-Token": state.token, ...(options.headers || {}) };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(apiUrl(path), { ...options, headers });
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch { payload = { detail: text }; }
  if (!response.ok) throw new Error(payload.detail || `${response.status} ${response.statusText}`);
  return payload;
}

function badge(value, tone) {
  return `<span class="badge ${tone}">${escapeHtml(value)}</span>`;
}
function tone(value) {
  const v = String(value || "").toLowerCase();
  if (["healthy", "available", "passed", "active", "completed", "resolved"].includes(v)) return "success";
  if (["critical", "failed", "expired", "stale", "quota-exhausted", "authentication-failed", "unavailable"].includes(v)) return "danger";
  if (["degraded", "warning", "high", "rate-limited", "missing", "renewal-due", "acknowledged"].includes(v)) return "warning";
  return "neutral";
}
function pct(value, limit) {
  if (!limit) return 0;
  return Math.max(0, Math.min(100, (Number(value) / Number(limit)) * 100));
}
function time(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? escapeHtml(value) : date.toLocaleString();
}
function toast(message, isError = false) {
  const node = $("toast");
  node.textContent = message;
  node.style.borderColor = isError ? "rgba(255,107,122,.5)" : "rgba(85,214,190,.35)";
  node.classList.add("visible");
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.classList.remove("visible"), 3500);
}

function render(snapshot) {
  state.snapshot = snapshot;
  $("connectionBadge").className = `badge ${tone(snapshot.fleet_state)}`;
  $("connectionBadge").textContent = snapshot.fleet_state || "connected";
  $("generatedAt").textContent = `Updated ${time(snapshot.generated_at)}`;
  const scheduler = snapshot.scheduler || {};
  $("schedulerState").className = `badge ${scheduler.running ? "success" : scheduler.enabled ? "warning" : "neutral"}`;
  $("schedulerState").textContent = scheduler.running ? "Running" : scheduler.enabled ? "Enabled" : "Disabled";

  const budget = snapshot.budget || {};
  $("summary").innerHTML = [
    ["Routable drivers", snapshot.routing_eligible_count ?? 0],
    ["Open incidents", snapshot.open_incident_count ?? 0],
    ["Renewals due", snapshot.renewal_due_count ?? 0],
    ["Daily invocations", `${budget.invocation_count ?? 0} / ${budget.invocation_limit ?? 0}`],
    ["Known cost", `$${Number(budget.known_cost_usd || 0).toFixed(4)}`],
  ].map(([label, value]) => `<div class="summary-card"><div class="label">${escapeHtml(label)}</div><div class="value">${escapeHtml(value)}</div></div>`).join("");

  $("driversBody").innerHTML = (snapshot.drivers || []).map((driver) => {
    const reliability = driver.reliability || {};
    const receipt = driver.receipt_expires_at ? `${time(driver.receipt_expires_at)}${driver.renewal_due ? " · due" : ""}` : "—";
    return `<tr>
      <td><div class="driver-name">${escapeHtml(driver.metadata?.display_name || driver.driver_id)}</div><div class="driver-meta">${escapeHtml(driver.driver_id)} · ${escapeHtml(driver.model_id || "default")}</div></td>
      <td>${badge(driver.availability, tone(driver.availability))}</td>
      <td>${badge(driver.conformance_state, tone(driver.conformance_state))}</td>
      <td>${badge(driver.quota_state, tone(driver.quota_state))}</td>
      <td><strong>${Number(reliability.score || 0).toFixed(3)}</strong><div class="driver-meta">${reliability.consecutive_failures || 0} consecutive failures</div></td>
      <td><span class="muted">${escapeHtml(receipt)}</span></td>
      <td>${badge(driver.routing_eligible ? "eligible" : "blocked", driver.routing_eligible ? "success" : "neutral")}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="7"><div class="empty">No drivers discovered.</div></td></tr>`;

  $("jobsList").innerHTML = (snapshot.jobs || []).map((job) => `<div class="item">
    <div class="item-row">
      <div><div class="item-title">${escapeHtml(job.kind)}</div><div class="item-detail">Every ${escapeHtml(job.interval_seconds)} seconds · next ${time(job.next_run_at)}</div></div>
      <div class="item-actions">
        ${badge(job.state, tone(job.state))}
        <button class="button small secondary" data-action="run-job" data-kind="${escapeHtml(job.kind)}">Run now</button>
        <button class="button small ${job.state === "active" ? "danger" : "secondary"}" data-action="toggle-job" data-kind="${escapeHtml(job.kind)}" data-enabled="${job.state !== "active"}">${job.state === "active" ? "Pause" : "Enable"}</button>
      </div>
    </div>
  </div>`).join("");

  const invocationPct = pct(budget.invocation_count, budget.invocation_limit);
  const costPct = pct(budget.known_cost_usd, budget.cost_limit_usd);
  $("budgetPanel").innerHTML = `<div class="item">
    <div class="item-title">Invocations</div><div class="progress ${budget.invocation_budget_exceeded ? "danger" : ""}"><div style="width:${invocationPct}%"></div></div>
    <div class="metric-row"><span>${escapeHtml(budget.invocation_count || 0)} used</span><span>${escapeHtml(budget.invocation_limit || 0)} limit</span></div>
  </div><div class="item" style="margin-top:10px">
    <div class="item-title">Known provider cost</div><div class="progress ${budget.cost_budget_exceeded ? "danger" : ""}"><div style="width:${costPct}%"></div></div>
    <div class="metric-row"><span>$${Number(budget.known_cost_usd || 0).toFixed(4)}</span><span>$${Number(budget.cost_limit_usd || 0).toFixed(2)} limit</span></div>
    <div class="item-detail">${escapeHtml(budget.unknown_cost_invocations || 0)} invocation(s) have no cost evidence and are not silently counted as zero.</div>
  </div>`;

  const showResolved = $("showResolved").checked;
  const incidents = (snapshot.incidents || []).filter((item) => showResolved || item.state !== "resolved");
  $("incidentsList").innerHTML = incidents.map((incident) => `<div class="item incident-${escapeHtml(incident.severity)}">
    <div class="item-row">
      <div><div class="item-title">${escapeHtml(incident.summary)}</div><div class="item-detail">${escapeHtml(incident.kind)} · ${escapeHtml(incident.driver_id || "fleet")} · seen ${escapeHtml(incident.occurrence_count)}× · last ${time(incident.last_seen_at)}</div></div>
      <div class="item-actions">
        ${badge(incident.severity, tone(incident.severity))}${badge(incident.state, tone(incident.state))}
        ${incident.state === "open" ? `<button class="button small secondary" data-action="ack-incident" data-id="${escapeHtml(incident.incident_id)}">Acknowledge</button>` : ""}
        ${incident.state !== "resolved" ? `<button class="button small primary" data-action="resolve-incident" data-id="${escapeHtml(incident.incident_id)}">Resolve</button>` : ""}
      </div>
    </div>
  </div>`).join("") || `<div class="empty">No incidents in this view.</div>`;

  $("runsList").innerHTML = (snapshot.recent_runs || []).slice(0, 20).map((run) => `<div class="timeline-entry"><span>${time(run.started_at)}</span><span>${badge(run.status, tone(run.status))}</span><span><strong>${escapeHtml(run.kind)}</strong> · ${escapeHtml(run.summary || "")}</span></div>`).join("") || `<div class="empty">No scheduled runs yet.</div>`;
}

async function load() {
  const snapshot = await request("/api/runtime-fleet/console");
  render(snapshot);
}
async function action(path, body = {}) {
  await request(path, { method: "POST", body: JSON.stringify(body) });
  await load();
}

$("connectButton").addEventListener("click", async () => {
  state.gateway = $("gatewayInput").value.trim() || window.location.origin;
  state.token = $("tokenInput").value;
  sessionStorage.setItem("aether.gateway.url", state.gateway);
  sessionStorage.setItem("aether.operator.token", state.token);
  try { await load(); toast("Connected to Aether Gateway"); startPolling(); } catch (error) { toast(error.message, true); }
});
$("refreshButton").addEventListener("click", () => load().catch((error) => toast(error.message, true)));
$("runDueButton").addEventListener("click", () => action("/api/runtime-fleet/run-due").then(() => toast("Due jobs executed")).catch((error) => toast(error.message, true)));
$("showResolved").addEventListener("change", () => state.snapshot && render(state.snapshot));
document.body.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  button.disabled = true;
  try {
    const kind = button.dataset.kind;
    const id = button.dataset.id;
    if (button.dataset.action === "run-job") await action(`/api/runtime-fleet/jobs/${encodeURIComponent(kind)}/run`);
    if (button.dataset.action === "toggle-job") await request(`/api/runtime-fleet/jobs/${encodeURIComponent(kind)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: button.dataset.enabled === "true" }) }).then(load);
    if (button.dataset.action === "ack-incident") await action(`/api/runtime-fleet/incidents/${encodeURIComponent(id)}/acknowledge`, { reason: "Acknowledged from AionUi runtime console" });
    if (button.dataset.action === "resolve-incident") await action(`/api/runtime-fleet/incidents/${encodeURIComponent(id)}/resolve`, { reason: "Resolved by operator from AionUi runtime console" });
    toast("Fleet operation completed");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
});
function startPolling() {
  clearInterval(state.timer);
  state.timer = setInterval(() => load().catch(() => {}), 15000);
}
$("gatewayInput").value = state.gateway;
$("tokenInput").value = state.token;
if (state.token) load().then(startPolling).catch(() => {});
