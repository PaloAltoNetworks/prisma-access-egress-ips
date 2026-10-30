'use strict';

// ── State ──────────────────────────────────────────────────────────────
let currentMode = 'single';
let lastResponse = null;   // raw API response stored for export
let activeBatchKey = null; // which node-type tab is selected in batch view
// Certificates approved in the dialog: { approval, label }. Memory only: reloading the page drops them.
let approvals = [];

// Visibility uses the hidden attribute everywhere (works for SVG too; see [hidden] in style.css)
function show(target, on) {
  const node = typeof target === 'string' ? document.getElementById(target) : target;
  node.toggleAttribute('hidden', !on);
}

// ── Mode toggle ────────────────────────────────────────────────────────
function setMode(mode) {
  currentMode = mode;
  document.getElementById('modeSingle').classList.toggle('active', mode === 'single');
  document.getElementById('modeBatch').classList.toggle('active', mode === 'batch');
  show('nodeTypeGroup', mode === 'single');
  // Location field only relevant in single mode for gw_pre
  if (mode !== 'single') {
    show('locationGroup', false);
  } else {
    onNodeTypeChange();
  }
  clearResults();
}

// ── Node type change ───────────────────────────────────────────────────
function onNodeTypeChange() {
  const isGwPre = document.getElementById('nodeType').value === 'gw_pre';
  show('locationGroup', isGwPre);
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

  for (;;) {
    clearResults();
    setLoading(true, loadingMsg);
    const tlsOpt = approvals.length ? { approved_certificates: approvals.map(a => a.approval) } : {};

    try {
      if (currentMode === 'single') {
        if (isPreAllocate) {
          const res = await apiFetch('/api/ips/pre-allocate', { api_key: apiKey, environment, location, ...tlsOpt });
          lastResponse = res;
          checkEnvironmentUpdate(res);
          renderPreAllocate(res);
        } else {
          const res = await apiFetch('/api/ips/query', { api_key: apiKey, environment, node_type: nodeType, ...tlsOpt });
          lastResponse = res;
          checkEnvironmentUpdate(res);
          renderSingle(res);
        }
      } else {
        const res = await apiFetch('/api/ips/batch', { api_key: apiKey, environment, ...tlsOpt });
        lastResponse = res;
        checkEnvironmentUpdate(res);
        renderBatch(res);
      }
      renderTlsFailures(lastResponse.tls_failures);
      document.getElementById('footerTimestamp').textContent = new Date().toLocaleString();
      show('clearBtn', true);
      return;
    } catch (err) {
      setLoading(false);
      if (err.tls && await confirmApproval(err.tls)) {
        addApproval(err.tls);
        continue;
      }
      renderTlsFailures(err.tlsFailures);
      showError(err.message || 'Request failed.');
      return;
    } finally {
      setLoading(false);
    }
  }
}

async function apiFetch(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const { detail } = await res.json().catch(() => ({ detail: res.statusText }));
    if (detail?.code === 'tls_verify_failed') {
      throw Object.assign(new Error(detail.message), { tls: detail });
    }
    if (detail?.code === 'key_rejected') {
      throw Object.assign(new Error(detail.message), { tlsFailures: detail.tls_failures });
    }
    const message = typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map(d => d.msg).join('; ')
      : '';
    throw new Error(message || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Certificate verification failure ──────────────────────────────────
function isApproved(approval) {
  return approvals.some(({ approval: a }) =>
    a.kind === approval.kind && a.pem === approval.pem && a.host === approval.host);
}

function addApproval(info) {
  approvals.push({ approval: info.approval, label: info.approval_label });
  renderApprovals();
}

function renderApprovals() {
  const list = document.getElementById('tlsApprovalsList');
  list.replaceChildren();
  for (const entry of approvals) {
    const item = document.createElement('li');
    const label = document.createElement('span');
    label.textContent = entry.label;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'link-btn';
    remove.textContent = 'Remove';
    remove.addEventListener('click', () => {
      approvals = approvals.filter(a => a !== entry);
      renderApprovals();
    });
    item.append(label, remove);
    list.append(item);
  }
  show('tlsSessionNotice', approvals.length > 0);
}

// Certificate fields come from the remote server: render with textContent only.
function renderTlsCertificate(cert) {
  const setFact = (id, value) => {
    const dd = document.getElementById(id);
    dd.textContent = value || '';
    show(dd, !!value);
    show(dd.previousElementSibling, !!value);
  };
  setFact('tlsDialogSubject', cert?.subject);
  setFact('tlsDialogAltNames', cert?.alt_names?.join(', '));
  setFact('tlsDialogValidity', cert && cert.not_before && `${cert.not_before} to ${cert.not_after}`);
  setFact('tlsDialogFingerprint', cert?.sha256);

  const chain = document.getElementById('tlsDialogChain');
  chain.replaceChildren();
  for (const link of cert?.chain || []) {
    const item = document.createElement('li');
    const subject = document.createElement('span');
    subject.className = 'tls-chain-subject';
    subject.textContent = link.subject;
    const issuer = document.createElement('span');
    issuer.className = 'tls-chain-issuer';
    issuer.textContent = `issued by ${link.issuer}`;
    item.append(subject, issuer);
    chain.append(item);
  }
  show('tlsDialogChainSection', !!cert?.chain?.length);
  show('tlsDialogNoDetails', !cert);
}

// Hosts skipped during environment auto-detection; each can open the full dialog.
function renderTlsFailures(failures) {
  const list = document.getElementById('tlsFailuresList');
  list.replaceChildren();
  for (const failure of failures || []) {
    const item = document.createElement('li');
    const host = document.createElement('span');
    host.className = 'tls-failures-host';
    host.textContent = failure.host;
    const reason = document.createElement('span');
    reason.className = 'tls-failures-reason';
    reason.textContent = failure.reason;
    const view = document.createElement('button');
    view.type = 'button';
    view.className = 'link-btn';
    view.textContent = 'View details';
    view.addEventListener('click', async () => {
      if (await confirmApproval(failure)) {
        addApproval(failure);
        runQuery();
      }
    });
    item.append(host, reason, view);
    list.append(item);
  }
  show('tlsFailures', !!failures?.length);
}

const APPROVAL_SCOPE = {
  anchor: 'Certificates it issues are accepted for any host until this page is reloaded or closed. Hostnames and expiry dates are still checked.',
  leaf: 'Only this exact certificate is accepted, and only for this host, until this page is reloaded or closed.',
};

// Resolves true only if the certificate can be approved and the user ticks the
// acknowledgement and chooses to retry.
function confirmApproval(info) {
  const dialog = document.getElementById('tlsDialog');
  document.getElementById('tlsDialogMessage').textContent = info.message;
  document.getElementById('tlsDialogHost').textContent = info.host;
  document.getElementById('tlsDialogReason').textContent = info.reason;
  renderTlsCertificate(info.certificate);

  const approvable = info.approval && !isApproved(info.approval);
  const noApproval = document.getElementById('tlsDialogNoApproval');
  noApproval.textContent = !info.approval
    ? "This certificate can't be approved because its details couldn't be retrieved."
    : approvable ? '' : 'This certificate is already approved for this session, but verification still failed.';
  show(noApproval, !approvable);
  show('tlsDialogApproval', approvable);
  show('tlsDialogRetry', approvable);
  if (approvable) {
    document.getElementById('tlsDialogApprovalLabel').textContent = info.approval_label;
    document.getElementById('tlsDialogApprovalScope').textContent = APPROVAL_SCOPE[info.approval.kind];
    // A CA approval trusts the top certificate presented: show its fingerprint, not the leaf's
    const top = info.certificate?.chain?.at(-1);
    const fingerprint = info.approval.kind === 'anchor' && top?.sha256;
    const fingerprintEl = document.getElementById('tlsDialogAnchorFingerprint');
    fingerprintEl.textContent = fingerprint ? `SHA-256 of ${top.subject}: ${fingerprint}` : '';
    show(fingerprintEl, !!fingerprint);
  }
  document.getElementById('tlsDialogConfirm').checked = false;
  document.getElementById('tlsDialogRetry').disabled = true;
  dialog.returnValue = '';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'retry'), { once: true });
    dialog.showModal();
  });
}

document.getElementById('tlsDialogConfirm').addEventListener('change', e => {
  document.getElementById('tlsDialogRetry').disabled = !e.target.checked;
});

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

  show('nodeTabs', false);
  show('resultsSection', true);
}

// ── Pre-allocate render ────────────────────────────────────────────────
function renderPreAllocate(res) {
  const ipCount   = res.data.reduce((n, z) => n + z.addresses.length, 0);
  const zoneCount = res.data.filter(z => z.addresses.length > 0).length;

  document.getElementById('resultsTitle').textContent =
    `gw_pre (pre-allocate) · ${res.environment} · ${res.location} · ${ipCount} IP${ipCount !== 1 ? 's' : ''} · ${zoneCount} zone${zoneCount !== 1 ? 's' : ''}`;

  renderIPTable(res.data, 'gw_pre');
  show('nodeTabs', false);
  show('resultsSection', true);
}

// ── Batch mode render ──────────────────────────────────────────────────
function renderBatch(res) {
  // Build tab list: individual node types + composites
  const tabs = document.getElementById('nodeTabs');
  tabs.replaceChildren();
  show(tabs, true);

  const allKeys = [...Object.keys(res.results), 'all', 'all_deployed'];

  allKeys.forEach((key, i) => {
    const data = key === 'all' ? res.all
               : key === 'all_deployed' ? res.all_deployed
               : res.results[key];
    const count = data ? data.reduce((n, z) => n + z.addresses.length, 0) : 0;

    const btn = document.createElement('button');
    btn.className = 'node-tab' + (i === 0 ? ' active' : '');
    btn.dataset.key = key;
    btn.append(key, el('span', { className: 'count', text: String(count) }));
    btn.addEventListener('click', () => selectBatchTab(key, res));
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
  show('resultsSection', true);
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

// ── DOM helpers ────────────────────────────────────────────────────────
// API data only ever reaches the page through textContent, so it can never become markup.
function el(tag, { text, ...props } = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  if (text !== undefined) node.textContent = text;
  node.append(...children);
  return node;
}

function setTableHead(...labels) {
  document.getElementById('tableHead').replaceChildren(el('tr', {}, ...labels.map(text => el('th', { text }))));
}

function setTableRows(rows, columns, emptyMessage) {
  const body = document.getElementById('tableBody');
  if (!rows.length) {
    body.replaceChildren(el('tr', {}, el('td', { className: 'empty-cell', colSpan: columns, text: emptyMessage })));
    return;
  }
  // A fragment avoids spreading thousands of rows into a single call
  const fragment = document.createDocumentFragment();
  for (const row of rows) fragment.append(row);
  body.replaceChildren(fragment);
}

// ── Table renderers ────────────────────────────────────────────────────
function renderIPTable(zoneData, nodeType) {
  setTableHead('Zone', 'IP Address', 'Type');
  const rows = [];
  for (const zone of zoneData) {
    for (const addr of zone.addresses) {
      rows.push(el('tr', {},
        el('td', { className: 'zone-cell', text: zone.zone }),
        el('td', { className: 'ip-cell', text: addr }),
        el('td', { className: 'type-cell', text: nodeType }),
      ));
    }
  }
  setTableRows(rows, 3, 'No IPs returned');
}

function renderRNTable(siteDetails) {
  setTableHead('Zone', 'IP Address', 'Node', 'Sites');
  const rows = siteDetails.map(d => el('tr', {},
    el('td', { className: 'zone-cell', text: d.zone }),
    el('td', { className: 'ip-cell', text: d.address }),
    el('td', { className: 'type-cell node-cell', text: d.node_name }),
    el('td', {}, renderSiteChips(d.sites)),
  ));
  setTableRows(rows, 4, 'No data');
}

function renderSiteChips(sites) {
  if (!sites?.length) return el('span', { className: 'site-none', text: '—' });
  return el('div', { className: 'site-list' }, ...sites.map(s => el('span', { className: 'site-chip', text: s })));
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
  show('resultsSection', false);
  show('nodeTabs', false);
  show('clearBtn', false);
  show('tlsFailures', false);
  hideBanner();
}

// The banner shows one state at a time: loading, error, or a short notice. Each change
// bumps bannerState, so a notice's timer never hides whatever replaced it.
let bannerState = 0;

function setBanner(kind, msg, spinner = false) {
  bannerState++;
  document.getElementById('statusBanner').className = kind ? `status-banner ${kind}` : 'status-banner';
  show('statusSpinner', spinner);
  if (msg !== undefined) document.getElementById('statusMsg').textContent = msg;
}

function setLoading(on, msg) {
  document.getElementById('queryBtn').disabled = on;
  if (on) {
    setBanner('loading', msg || 'Loading…', true);
  } else if (document.getElementById('statusBanner').classList.contains('loading')) {
    // Only end the loading state: an error or a notice set meanwhile stays visible
    hideBanner();
  }
}

function showError(msg) {
  setBanner('error', msg);
}

function hideBanner() {
  setBanner(null);
}

function flashMsg(msg) {
  setBanner('notice', msg);
  const state = bannerState;
  setTimeout(() => { if (bannerState === state) hideBanner(); }, 2500);
}

// Values come from tenant configuration (site and zone names). A leading = + - @ (or tab/CR)
// would make a spreadsheet evaluate the cell as a formula, so prefix a quote; quote any value
// with a separator, quote or line break.
function csvCell(val) {
  let s = String(val ?? '');
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
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
  show('eyeOn', visible);
  show('eyeOff', !visible);
}

// ── Event wiring (no inline handlers: the CSP allows only this script) ─
const on = (id, event, handler) => document.getElementById(id).addEventListener(event, handler);
on('apiKeyToggle', 'click', toggleApiKey);
on('modeSingle', 'click', () => setMode('single'));
on('modeBatch', 'click', () => setMode('batch'));
on('nodeType', 'change', onNodeTypeChange);
on('queryBtn', 'click', runQuery);
on('clearBtn', 'click', clearResults);
on('copyBtn', 'click', copyIPs);
on('csvBtn', 'click', downloadCSV);
on('jsonBtn', 'click', downloadJSON);
on('txtBtn', 'click', downloadTXT);
// Enter in the API key field submits
on('apiKey', 'keydown', e => {
  if (e.key === 'Enter') runQuery();
});

// ── Running version ────────────────────────────────────────────────────
// Best effort: if /health can't be reached, the footer simply shows no version.
fetch('/health')
  .then(res => res.json())
  .then(({ version }) => {
    if (version) document.getElementById('footerVersion').textContent = `v${version}`;
  })
  .catch(() => {});
