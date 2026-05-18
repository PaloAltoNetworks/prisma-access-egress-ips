'use strict';

// ── State ──────────────────────────────────────────────────────────────
let currentMode = 'single';
let lastResponse = null;   // raw API response stored for export
let activeBatchKey = null; // which node-type tab is selected in batch view

// ── Mode toggle ────────────────────────────────────────────────────────
function setMode(mode) {
  currentMode = mode;
  document.getElementById('modeSingle').classList.toggle('active', mode === 'single');
  document.getElementById('modeBatch').classList.toggle('active', mode === 'batch');
  document.getElementById('nodeTypeGroup').style.display = mode === 'single' ? '' : 'none';
  // Location field only relevant in single mode for gw_pre
  if (mode !== 'single') {
    document.getElementById('locationGroup').style.display = 'none';
  } else {
    onNodeTypeChange();
  }
  clearResults();
}

// ── Node type change ───────────────────────────────────────────────────
function onNodeTypeChange() {
  const isGwPre = document.getElementById('nodeType').value === 'gw_pre';
  document.getElementById('locationGroup').style.display = isGwPre ? '' : 'none';
  if (!isGwPre) {
    document.getElementById('location').value = '';
  }
}

// ── Query ──────────────────────────────────────────────────────────────
async function runQuery() {
  const apiKey      = document.getElementById('apiKey').value.trim();
  const environment = document.getElementById('environment').value;
  const nodeType    = document.getElementById('nodeType').value;
  const location    = document.getElementById('location').value.trim();

  if (!apiKey) { showError('API key is required.'); return; }

  const isPreAllocate = currentMode === 'single' && nodeType === 'gw_pre' && location;
  const loadingMsg = currentMode === 'batch'
    ? 'Fetching all node types…'
    : isPreAllocate
      ? `Pre-allocating IPs for ${location}…`
      : `Fetching ${nodeType}…`;

  setLoading(true, loadingMsg);
  clearResults();

  try {
    if (currentMode === 'single') {
      if (isPreAllocate) {
        const res = await apiFetch('/api/ips/pre-allocate', { api_key: apiKey, environment, location });
        lastResponse = res;
        checkEnvironmentUpdate(res);
        renderPreAllocate(res);
      } else {
        const res = await apiFetch('/api/ips/query', { api_key: apiKey, environment, node_type: nodeType });
        lastResponse = res;
        checkEnvironmentUpdate(res);
        renderSingle(res);
      }
    } else {
      const res = await apiFetch('/api/ips/batch', { api_key: apiKey, environment });
      lastResponse = res;
      checkEnvironmentUpdate(res);
      renderBatch(res);
    }
    document.getElementById('footerTimestamp').textContent = new Date().toLocaleString();
    document.getElementById('clearBtn').style.display = '';
  } catch (err) {
    showError(err.message || 'Request failed.');
  } finally {
    setLoading(false);
  }
}

async function apiFetch(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Single mode render ─────────────────────────────────────────────────
function renderSingle(res) {
  const isRN = res.node_type === 'rn' || res.node_type === 'rn_all';
  const ipCount = res.data.reduce((n, z) => n + z.addresses.length, 0);
  const zoneCount = res.data.filter(z => z.addresses.length > 0).length;

  document.getElementById('resultsTitle').textContent =
    `${res.node_type} · ${res.environment} · ${ipCount} IP${ipCount !== 1 ? 's' : ''} · ${zoneCount} zone${zoneCount !== 1 ? 's' : ''}`;

  if (isRN && res.rn_site_details?.length) {
    renderRNTable(res.rn_site_details);
  } else {
    renderIPTable(res.data, res.node_type);
  }

  document.getElementById('nodeTabs').style.display = 'none';
  document.getElementById('resultsSection').style.display = '';
}

// ── Pre-allocate render ────────────────────────────────────────────────
function renderPreAllocate(res) {
  const ipCount   = res.data.reduce((n, z) => n + z.addresses.length, 0);
  const zoneCount = res.data.filter(z => z.addresses.length > 0).length;

  document.getElementById('resultsTitle').textContent =
    `gw_pre (pre-allocate) · ${res.environment} · ${res.location} · ${ipCount} IP${ipCount !== 1 ? 's' : ''} · ${zoneCount} zone${zoneCount !== 1 ? 's' : ''}`;

  renderIPTable(res.data, 'gw_pre');
  document.getElementById('nodeTabs').style.display = 'none';
  document.getElementById('resultsSection').style.display = '';
}

// ── Batch mode render ──────────────────────────────────────────────────
function renderBatch(res) {
  // Build tab list: individual node types + composites
  const tabs = document.getElementById('nodeTabs');
  tabs.innerHTML = '';
  tabs.style.display = 'flex';

  const allKeys = [...Object.keys(res.results), 'all', 'all_deployed'];

  allKeys.forEach((key, i) => {
    const data = key === 'all' ? res.all
               : key === 'all_deployed' ? res.all_deployed
               : res.results[key];
    const count = data ? data.reduce((n, z) => n + z.addresses.length, 0) : 0;

    const btn = document.createElement('button');
    btn.className = 'node-tab' + (i === 0 ? ' active' : '');
    btn.dataset.key = key;
    btn.innerHTML = `${key}<span class="count">${count}</span>`;
    btn.onclick = () => selectBatchTab(key, res);
    tabs.appendChild(btn);
  });

  const firstKey = allKeys[0];
  activeBatchKey = firstKey;
  const allZones = res.all || [];
  const totalIPs = allZones.reduce((n, z) => n + z.addresses.length, 0);
  const totalZones = allZones.filter(z => z.addresses.length > 0).length;
  document.getElementById('resultsTitle').textContent =
    `Batch · ${res.environment} · ${totalIPs} total IPs · ${totalZones} zones`;

  selectBatchTab(firstKey, res);
  document.getElementById('resultsSection').style.display = '';
}

function selectBatchTab(key, res) {
  activeBatchKey = key;
  document.querySelectorAll('.node-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.key === key);
  });

  const data = key === 'all' ? res.all
             : key === 'all_deployed' ? res.all_deployed
             : res.results[key];

  const isRN = (key === 'rn' || key === 'rn_all');
  if (isRN && res.rn_site_details?.[key]?.length) {
    renderRNTable(res.rn_site_details[key]);
  } else {
    renderIPTable(data || [], key);
  }
}

// ── Table renderers ────────────────────────────────────────────────────
function renderIPTable(zoneData, nodeType) {
  document.getElementById('tableHead').innerHTML = `
    <tr>
      <th>Zone</th>
      <th>IP Address</th>
      <th>Type</th>
    </tr>`;

  const rows = [];
  for (const zone of zoneData) {
    for (const addr of zone.addresses) {
      rows.push(`<tr>
        <td class="zone-cell">${esc(zone.zone)}</td>
        <td class="ip-cell">${esc(addr)}</td>
        <td class="type-cell">${esc(nodeType)}</td>
      </tr>`);
    }
  }

  document.getElementById('tableBody').innerHTML =
    rows.length ? rows.join('') : '<tr><td colspan="3" style="text-align:center;color:var(--text-muted);padding:32px;">No IPs returned</td></tr>';
}

function renderRNTable(siteDetails) {
  document.getElementById('tableHead').innerHTML = `
    <tr>
      <th>Zone</th>
      <th>IP Address</th>
      <th>Node</th>
      <th>Sites</th>
    </tr>`;

  const rows = siteDetails.map(d => `<tr>
    <td class="zone-cell">${esc(d.zone)}</td>
    <td class="ip-cell">${esc(d.address)}</td>
    <td class="type-cell" style="font-family:var(--font-mono);font-size:0.75rem;">${esc(d.node_name)}</td>
    <td>${renderSiteChips(d.sites)}</td>
  </tr>`);

  document.getElementById('tableBody').innerHTML =
    rows.length ? rows.join('') : '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);padding:32px;">No data</td></tr>';
}

function renderSiteChips(sites) {
  if (!sites?.length) return '<span style="color:var(--text-muted);font-size:0.72rem;">—</span>';
  return `<div class="site-list">${sites.map(s => `<span class="site-chip">${esc(s)}</span>`).join('')}</div>`;
}

// ── Export ─────────────────────────────────────────────────────────────
function copyIPs() {
  const ips = collectCurrentIPs();
  navigator.clipboard.writeText(ips.join('\n')).then(() => {
    flashMsg('Copied ' + ips.length + ' IPs to clipboard');
  });
}

function downloadCSV() {
  const isRNSingle = currentMode === 'single' && lastResponse?.rn_site_details?.length;
  const isRNBatch  = currentMode === 'batch'
                     && (activeBatchKey === 'rn' || activeBatchKey === 'rn_all')
                     && lastResponse?.rn_site_details?.[activeBatchKey]?.length;

  if (isRNSingle || isRNBatch) {
    const details  = isRNSingle
      ? lastResponse.rn_site_details
      : lastResponse.rn_site_details[activeBatchKey];
    const nodeType = isRNSingle ? (lastResponse.node_type || 'rn') : activeBatchKey;
    const rows     = details.map(d =>
      [d.zone, d.address, nodeType, d.node_name, (d.sites || []).join('; ')].map(csvCell).join(',')
    );
    download('egress-ips.csv', ['Zone,IPAddress,Type,Node,Sites', ...rows].join('\n'), 'text/csv');
  } else {
    const rows = collectCurrentIPRows();
    const csv  = ['Zone,IPAddress,Type', ...rows.map(r => `${csvCell(r.zone)},${csvCell(r.ip)},${csvCell(r.type)}`)].join('\n');
    download('egress-ips.csv', csv, 'text/csv');
  }
}

function downloadJSON() {
  download('egress-ips.json', JSON.stringify(lastResponse, null, 2), 'application/json');
}

function downloadTXT() {
  if (!lastResponse) return;

  const lines = [];
  lines.push(`# ${document.getElementById('resultsTitle').textContent}`);
  lines.push(`# Generated: ${new Date().toLocaleString()}`);
  lines.push('#');

  if (currentMode === 'batch') {
    const key = activeBatchKey;
    const data = key === 'all' ? lastResponse.all
               : key === 'all_deployed' ? lastResponse.all_deployed
               : lastResponse.results[key];
    appendZoneTXT(lines, data || []);
  } else if (lastResponse.rn_site_details?.length) {
    appendRNTXT(lines, lastResponse.rn_site_details);
  } else {
    appendZoneTXT(lines, lastResponse.data || []);
  }

  download('egress-ips.txt', lines.join('\n'), 'text/plain');
}

function appendZoneTXT(lines, zoneData) {
  for (const zone of zoneData) {
    if (!zone.addresses.length) continue;
    lines.push(`# ${zone.zone}`);
    for (const addr of zone.addresses) lines.push(addr);
    lines.push('#');
  }
}

function appendRNTXT(lines, siteDetails) {
  const byZone = {};
  for (const d of siteDetails) {
    (byZone[d.zone] ||= []).push(d);
  }
  for (const [zone, details] of Object.entries(byZone)) {
    lines.push(`# ${zone}`);
    for (const d of details) {
      const sites = d.sites?.length ? ` — ${d.sites.join(', ')}` : '';
      lines.push(`# ${d.node_name}${sites}`);
      lines.push(d.address);
    }
    lines.push('#');
  }
}

function collectCurrentIPs() {
  return Array.from(document.querySelectorAll('#tableBody .ip-cell')).map(td => td.textContent);
}

function collectCurrentIPRows() {
  return Array.from(document.querySelectorAll('#tableBody tr')).map(tr => {
    const cells = tr.querySelectorAll('td');
    return { zone: cells[0]?.textContent || '', ip: cells[1]?.textContent || '', type: cells[2]?.textContent || '' };
  }).filter(r => r.ip);
}

function download(filename, content, mime) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content], { type: mime }));
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ── UI helpers ─────────────────────────────────────────────────────────
function clearResults() {
  lastResponse = null;
  activeBatchKey = null;
  document.getElementById('resultsSection').style.display = 'none';
  document.getElementById('nodeTabs').style.display = 'none';
  document.getElementById('clearBtn').style.display = 'none';
  hideBanner();
}

function setLoading(on, msg) {
  document.getElementById('queryBtn').disabled = on;
  if (on) {
    const banner = document.getElementById('statusBanner');
    banner.className = 'status-banner loading';
    document.getElementById('statusSpinner').style.display = '';
    document.getElementById('statusMsg').textContent = msg || 'Loading…';
  } else {
    hideBanner();
  }
}

function showError(msg) {
  const banner = document.getElementById('statusBanner');
  banner.className = 'status-banner error';
  document.getElementById('statusSpinner').style.display = 'none';
  document.getElementById('statusMsg').textContent = msg;
}

function hideBanner() {
  const banner = document.getElementById('statusBanner');
  banner.className = 'status-banner';
}

function flashMsg(msg) {
  const banner = document.getElementById('statusBanner');
  banner.className = 'status-banner loading';
  document.getElementById('statusSpinner').style.display = 'none';
  document.getElementById('statusMsg').textContent = msg;
  setTimeout(hideBanner, 2500);
}

function esc(str) {
  return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function csvCell(val) {
  const s = String(val ?? '');
  return s.includes(',') || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s;
}

// ── Environment auto-correct ───────────────────────────────────────────
function checkEnvironmentUpdate(res) {
  const select = document.getElementById('environment');
  if (res.environment && res.environment !== select.value) {
    select.value = res.environment;
    flashMsg(`Environment auto-corrected to ${res.environment}`);
  }
}

// ── API key visibility toggle ──────────────────────────────────────────
function toggleApiKey() {
  const input = document.getElementById('apiKey');
  const visible = input.type === 'text';
  input.type = visible ? 'password' : 'text';
  document.getElementById('eyeOn').style.display  = visible ? '' : 'none';
  document.getElementById('eyeOff').style.display = visible ? 'none' : '';
}

// ── Enter key submits ──────────────────────────────────────────────────
document.getElementById('apiKey').addEventListener('keydown', e => {
  if (e.key === 'Enter') runQuery();
});
