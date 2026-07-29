const state = { token: '' };
const el = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const money = (value) => `$${Number(value ?? 0).toFixed(2)}`;
function badge(value){ return `<span class="badge ${esc(value)}">${esc(value)}</span>`; }
async function load(){
  el('error').classList.add('hidden');
  try {
    const headers = state.token ? {'X-Aether-Operator-Token': state.token} : {};
    const response = await fetch('/api/opportunity-intelligence/console', {headers});
    if (response.status === 401 || response.status === 503) {
      const token = window.prompt('Aether operator token');
      if (!token) throw new Error('Operator token is required.');
      state.token = token; return load();
    }
    const data = await response.json(); if (!response.ok) throw new Error(data.detail || response.statusText);
    if (data.secret_values_exposed !== false) throw new Error('Console response did not assert secret redaction.');
    render(data);
  } catch (error) { el('error').textContent = error.message; el('error').classList.remove('hidden'); }
}
function render(data){
  const status=data.status||{};
  const ready=(data.candidates||[]).filter(x=>x.status==='portfolio-ready').length;
  const selected=(data.decisions||[]).filter(x=>x.decision==='select').length;
  const active=(data.mandates||[]).filter(x=>x.status==='active').length;
  el('metrics').innerHTML=[
    ['Sources',status.source_manifests],['Snapshots',status.content_snapshots],['Claims',status.extracted_claims],['Portfolio ready',ready],['Active mandates',active]
  ].map(([k,v])=>`<div class="metric"><span>${esc(k)}</span><strong>${Number(v||0)}</strong></div>`).join('');
  const health=Object.fromEntries((data.source_status||[]).map(x=>[x.adapter_id,x]));
  el('source-health').textContent=`${Object.values(health).filter(x=>x.health==='healthy').length}/${data.sources.length} healthy`;
  el('sources').innerHTML=(data.sources||[]).map(item=>{const h=health[item.adapter_id]||{health:'unknown',reason:'not probed'};return `<div class="card"><h3>${esc(item.name)}</h3>${badge(h.health)} ${badge(item.kind)}<p class="meta">${esc(item.metadata?.role||item.adapter_id)}</p><p class="meta">${esc(h.reason)}</p></div>`}).join('')||'<div class="empty">No source adapters.</div>';
  el('authority').innerHTML=Object.entries(data.authority||{}).map(([k,v])=>`<div class="authority-row"><span>${esc(k.replaceAll('_',' '))}</span><span>${esc(v)}</span></div>`).join('');
  el('candidates').innerHTML=(data.candidates||[]).map(item=>`<div class="candidate"><div><h3>${esc(item.title)}</h3>${badge(item.status)} ${badge(item.category)}<p>${esc(item.problem_statement)}</p><p class="meta">${item.supporting_source_ids.length} independent sources · ${item.contradicting_claim_ids.length} contradictions · ${esc(item.risk)} risk</p></div><div class="score"><strong>${Number(item.score.utility_score).toFixed(1)}</strong><span class="meta">utility</span><div class="money">EV ${money(item.score.expected_net_value_usd)}</div></div></div>`).join('')||'<div class="empty">No synthesized candidates.</div>';
  el('runs').innerHTML=(data.runs||[]).map(item=>`<div class="event"><div><strong>${esc(item.status)}</strong><div class="meta">${item.source_ids.length} sources · ${item.snapshot_ids.length} snapshots · ${item.claim_ids.length} claims</div></div><span class="meta">${Number(item.duration_seconds).toFixed(2)}s</span></div>`).join('')||'<div class="empty">No scout runs.</div>';
  el('mandates').innerHTML=(data.mandates||[]).map(item=>`<div class="event"><div><strong>${esc(item.autonomy_level)}</strong><div class="meta">${esc(item.candidate_id)} · ${item.maximum_external_actions} external actions</div></div><div>${badge(item.status)} <span class="money">${money(item.maximum_cost_usd)}</span></div></div>`).join('')||'<div class="empty">No experiment mandates.</div>';
}
el('refresh').addEventListener('click',load); load();
