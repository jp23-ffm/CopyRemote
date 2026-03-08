/* ═══════════════════════════════════════════════
   Access Rights Dashboard — Engine
   Reads CONFIG, builds everything dynamically.
   ═══════════════════════════════════════════════ */

const AVA_COLORS = [
  '#5b8df9', '#3dd9a0', '#f5a623', '#f06565',
  '#a78bfa', '#38bdf8', '#fb923c', '#ec4899',
];

let CONFIG = null;
let ALL_KEYS = [];
let SEEDED = new Set();
let orig = {}, curr = {}, changes = {};
let auditLog = [];

// ── Bootstrap ──
async function init() {
  showLoading(true);
  try {
    const resp = await fetch(CONFIG_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    CONFIG = await resp.json();
  } catch (err) {
    console.error('Failed to load config:', err);
    document.getElementById('tbody').innerHTML =
      '<tr><td colspan="99" style="text-align:center;padding:32px;color:var(--err)">Failed to load configuration</td></tr>';
    showLoading(false);
    return;
  }

  // Build flat key list
  ALL_KEYS = [];
  CONFIG.apps.forEach(a => a.permissions.forEach(p => ALL_KEYS.push(`${a.key}.${p}`)));

  // Build set of seeded permissions (those that exist in DB)
  SEEDED = new Set(CONFIG.seeded || []);

  // Count unseeded for warning
  const unseeded = ALL_KEYS.filter(k => !SEEDED.has(k));

  // Init permission state
  CONFIG.users.forEach(u => {
    const o = {};
    ALL_KEYS.forEach(k => { o[k] = u.permissions.includes(k) ? 1 : 0; });
    orig[u.id] = { ...o };
    curr[u.id] = { ...o };
  });

  buildHeader();
  render();
  loadAuditLog();
  showLoading(false);

  let info = `${CONFIG.apps.length} apps · ${ALL_KEYS.length} perms · ${CONFIG.users.length} users`;
  if (unseeded.length) {
    info += ` · ⚠ ${unseeded.length} not seeded`;
  }
  document.getElementById('configInfo').textContent = info;
  if (unseeded.length) {
    document.getElementById('configInfo').style.borderColor = 'var(--warn)';
    document.getElementById('configInfo').style.color = 'var(--warn)';
  }
}

function showLoading(on) {
  const el = document.getElementById('loading');
  if (el) el.style.display = on ? '' : 'none';
}

// ── Theme ──
function getTheme() {
  return document.body.dataset.theme === 'dark' ? 'dark' : 'light';
}

function appColor(app) {
  return typeof app.color === 'object' ? app.color[getTheme()] : app.color;
}

function toggleTheme() {
  const isDark = document.body.dataset.theme === 'dark';
  if (isDark) {
    delete document.body.dataset.theme;
  } else {
    document.body.dataset.theme = 'dark';
  }
  refreshHeaderColors();
}

function refreshHeaderColors() {
  if (!CONFIG) return;
  CONFIG.apps.forEach(app => {
    const th = document.querySelector(`th[data-app="${app.key}"]`);
    if (th) th.style.color = appColor(app);
  });
}

// ── Table header ──
function buildHeader() {
  const thead = document.getElementById('thead');

  let r1 = '<tr><th rowspan="2">User</th><th rowspan="2">Last login</th>';
  CONFIG.apps.forEach(app => {
    r1 += `<th colspan="${app.permissions.length}" class="app-hdr" data-app="${app.key}" style="color:${appColor(app)}">${app.label}</th>`;
  });
  r1 += '</tr>';

  let r2 = '<tr class="sub-hdr">';
  CONFIG.apps.forEach(app => {
    app.permissions.forEach((p, i) => {
      const key = `${app.key}.${p}`;
      const seeded = SEEDED.has(key);
      const cls = i === 0 ? 'bl' : '';
      const style = seeded ? '' : ' style="color:var(--warn)"';
      const label = seeded ? cap(p) : `⚠ ${cap(p)}`;
      r2 += `<th class="${cls}"${style}>${label}</th>`;
    });
  });
  r2 += '</tr>';

  thead.innerHTML = r1 + r2;
}

// ── Table body ──
function render() {
  if (!CONFIG) return;
  const q = document.getElementById('searchInput').value.toLowerCase();

  const rows = CONFIG.users.filter(u =>
    !q || u.name.toLowerCase().includes(q) || u.username.toLowerCase().includes(q)
  );

  document.getElementById('tbody').innerHTML = rows.map((u, idx) => {
    const ini = u.name.split(' ').map(w => w[0]).join('');
    const col = AVA_COLORS[idx % AVA_COLORS.length];
    const dirty = changes[u.id] && Object.keys(changes[u.id]).length > 0;

    let cells = '';
    CONFIG.apps.forEach(app => {
      app.permissions.forEach((p, pi) => {
        const key = `${app.key}.${p}`;
        const bl = pi === 0 ? ' bl' : '';
        const seeded = SEEDED.has(key);
        const ch = curr[u.id][key] ? 'checked' : '';
        const dis = seeded ? '' : 'disabled title="Not seeded — run: python manage.py seed_permissions"';
        const cls = seeded ? 'ck' : 'ck unseeded';
        cells += `<td class="center${bl}"><span class="${cls}"><input type="checkbox" ${ch} ${dis} onchange="toggle(${u.id},'${key}',this.checked)"></span></td>`;
      });
    });

    return `<tr class="${dirty ? 'dirty' : ''}">
      <td><div class="u-cell"><div class="u-av" style="background:${col}">${ini}</div><div><div class="u-name">${u.name}</div><div class="u-id">${u.username}</div></div></div></td>
      <td><span class="login-ts">${u.last_login}</span></td>
      ${cells}
    </tr>`;
  }).join('');
}

// ── Toggle permission ──
function toggle(uid, key, val) {
  curr[uid][key] = val ? 1 : 0;
  if (!changes[uid]) changes[uid] = {};

  if (curr[uid][key] !== orig[uid][key]) {
    changes[uid][key] = val;
  } else {
    delete changes[uid][key];
    if (!Object.keys(changes[uid]).length) delete changes[uid];
  }
  updateBar();
  render();
}

// ── Save bar ──
function updateBar() {
  const n = Object.values(changes).reduce((s, c) => s + Object.keys(c).length, 0);
  document.getElementById('cnt').textContent = n;
  document.getElementById('saveBar').classList.toggle('show', n > 0);
}

// ── Save ──
async function save() {
  const payload = [];

  Object.entries(changes).forEach(([uid, perms]) => {
    Object.entries(perms).forEach(([key, val]) => {
      payload.push({
        user_id: +uid,
        permission: key,
        action: val ? 'grant' : 'revoke',
      });
    });
  });

  try {
    const resp = await fetch(UPDATE_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': CSRF_TOKEN,
      },
      body: JSON.stringify({ changes: payload }),
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const result = await resp.json();

    // Update local state
    Object.keys(curr).forEach(uid => { orig[uid] = { ...curr[uid] }; });
    changes = {};
    updateBar();
    render();
    toast(`${result.applied} permission(s) saved`);

    // Refresh audit log
    loadAuditLog();

  } catch (err) {
    console.error('Save failed:', err);
    toast('Save failed — check console');
  }
}

function discard() {
  Object.keys(orig).forEach(uid => { curr[uid] = { ...orig[uid] }; });
  changes = {};
  updateBar();
  render();
  toast('Changes discarded');
}

// ── Audit log ──
async function loadAuditLog() {
  try {
    const resp = await fetch(AUDIT_URL);
    if (!resp.ok) return;
    const data = await resp.json();
    auditLog = data.log || [];
    renderLog();
  } catch (err) {
    console.error('Failed to load audit log:', err);
  }
}

function renderLog() {
  const el = document.getElementById('logList');
  if (!auditLog.length) {
    el.innerHTML = '<div class="log-empty">No changes recorded yet.</div>';
    return;
  }
  el.innerHTML = auditLog.map(l => `
    <div class="log-entry">
      <span class="log-ts">${l.timestamp}</span>
      <span class="log-admin">${l.admin}</span>
      <span class="log-action">
        <span class="${l.action}">${l.action}</span>
        <span class="target">${l.permission}</span> → ${l.target}
      </span>
    </div>`).join('');
}

// ── Tabs ──
function switchTab(btn, tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panel-perms').style.display = tab === 'perms' ? '' : 'none';
  document.getElementById('panel-log').style.display = tab === 'log' ? '' : 'none';
  if (tab === 'log') loadAuditLog();
}

// ── Toast ──
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('on');
  setTimeout(() => t.classList.remove('on'), 2800);
}

// ── Helpers ──
function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

// ── Start ──
document.addEventListener('DOMContentLoaded', init);
