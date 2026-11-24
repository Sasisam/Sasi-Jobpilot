'use strict';
/* JobPilot Pro — unique multi-portal auto-apply dashboard */
const $ = s => document.querySelector(s);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(c));
  return el;
}

async function api(path, opt = {}) {
  if (opt.json !== undefined) { opt.method = opt.method || 'POST'; opt.headers = { 'Content-Type': 'application/json' }; opt.body = JSON.stringify(opt.json); }
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}
let toastT;
function toast(m) { const t = $('#toast'); t.textContent = m; t.classList.add('on'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('on'), 3400); }
const guard = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message || 'Something went wrong'); } };

/* ---------------- state ---------------- */
let S = null, jobs = [], jobsKey = '';
let view = (location.hash || '#jobs').slice(1);
let roles = [], cities = [], portalPick = [], modes = [], tiers = [], types = [];
let empMode = 'direct', filtersOpen = window.innerWidth >= 768;
let filter = 'all';
const sel = new Set();
let searching = false;
const MODES = [['remote', 'Remote'], ['hybrid', 'Hybrid'], ['wfo', 'On-site']];
const TIERS = [
  ['tier1', 'Tier 1 — Top / large'],
  ['tier2', 'Tier 2 — Mid-size'],
  ['tier3', 'Tier 3 — Startup / small'],
];
const TYPES = [['mnc', 'MNC'], ['product', 'Product'], ['startup', 'Startup'], ['service', 'IT services']];
const EMP_MODES = [
  ['direct', 'No contract / C2H'],
  ['strict', 'Permanent only (strict)'],
  ['any', 'Show everything'],
];
const EMP_HINT = {
  direct: 'Skips C2H, contract, third-party payroll and staffing-agency posts. Jobs that do not state a type are kept (checked again on the job page before applying).',
  strict: 'Only jobs that clearly say permanent / direct payroll, or that come from the company’s own career page. Fewest jobs, fewest C2H calls.',
  any: 'No job-type filtering. C2H / contract jobs are shown with a red tag and ranked lower.',
};
const EMP_TAG = {
  permanent: ['Permanent', 'good'], c2h: ['C2H', 'bad'], contract: ['Contract', 'bad'], agency: ['Agency', 'bad'], unknown: ['Type unverified', ''],
};
const ICONS = {
  jobs: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="18" height="13" rx="2.5"/><path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3 13h18"/></svg>',
  resume: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/></svg>',
  portals: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1"/></svg>',
  settings: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></svg>',
  usage: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 3v18M5 12h14"/><circle cx="12" cy="12" r="9"/></svg>',
  owner: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
};
const icon = k => { const el = document.createElement('span'); el.className = 'ico'; el.innerHTML = ICONS[k] || ''; return el; };

const STATUS = {
  new: ['Ready to apply', ''], applying: ['Applying…', ''], ready: ['Form ready', 'Approve & submit'],
  needs_human: ['Needs you', ''], applied: ['Applied', ''], failed: ['Failed', ''], skipped: ['Skipped', ''], manual: ['You apply', ''],
};
const FILTERS = [['all', 'All'], ['new', 'To apply'], ['wait', 'Waiting'], ['applied', 'Applied'], ['skipped', 'Skipped']];
const inFilter = (j, f) => f === 'all' || (f === 'new' && ['new', 'applying'].includes(j.status)) ||
  (f === 'wait' && ['ready', 'needs_human', 'failed', 'manual'].includes(j.status)) || (f === 'applied' && j.status === 'applied') || (f === 'skipped' && j.status === 'skipped');

/* ---------------- theme ---------------- */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('jp-theme', t); } catch (e) {}
  document.querySelectorAll('#theme-picker button').forEach(b => b.classList.toggle('active', b.dataset.t === t));
}
document.getElementById('theme-picker')?.addEventListener('click', e => {
  const b = e.target.closest('button[data-t]');
  if (b) setTheme(b.dataset.t);
});
setTheme(document.documentElement.dataset.theme || 'ocean');

/* ---------------- header + nav ---------------- */
const TABS = [
  ['jobs', 'Jobs', 'Search · match · auto-apply'],
  ['resume', 'Resume', 'Upload once — profile auto-fills'],
  ['portals', 'Portals', 'Connect logins for auto-apply'],
  ['usage', 'Usage', 'Tokens · history · balance'],
  ['owner', 'Owner', 'Users · top-up · admin'],
  ['settings', 'Settings', 'Limits · notifications · behaviour'],
];
function renderNav() {
  const nav = $('#nav');
  nav.replaceChildren(...TABS.map(([id, label]) =>
    h('button', { 'aria-current': view === id ? 'page' : null, onclick: () => go(id) }, icon(id), h('span', { class: 'lbl' }, label))));
  document.querySelectorAll('.view').forEach(v => v.hidden = v.id !== 'v-' + view);
  const tab = TABS.find(t => t[0] === view) || TABS[0];
  const title = $('#page-title'); const sub = $('#page-sub');
  if (title) title.textContent = tab[1];
  if (sub) sub.textContent = tab[2];
}
function go(v) { view = v; location.hash = v; renderNav(); renderView(); updateDock(); closeCfg(); window.scrollTo({ top: 0 }); }
window.addEventListener('hashchange', () => { const v = location.hash.slice(1); if (v && v !== view && TABS.some(t => t[0] === v)) go(v); });

function renderLeds() {
  const led = (on, label, key) => h('button', {
    class: 'led' + (on ? ' on' : ''),
    type: 'button',
    title: 'Configure ' + label,
    onclick: () => openCfg(key),
  }, h('i', { class: 'dot' + (on ? ' on' : '') }), label);
  $('#leds').replaceChildren(
    led(S.ai_enabled, 'AI', 'ai'),
    led(S.email_enabled, 'Email', 'email'),
    led(S.push_enabled, 'Alert', 'alert'),
  );
}
$('#log-btn').onclick = () => { closeCfg(); const p = $('#logpane'); p.hidden = !p.hidden; renderLog(); };
$('#log-close').onclick = () => $('#logpane').hidden = true;
function renderLog() {
  if ($('#logpane').hidden) return;
  const pre = $('#logtext'), atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
  pre.textContent = S.log.join('\n') || 'No activity yet. Start a search to see steps here.';
  if (atEnd) pre.scrollTop = pre.scrollHeight;
}

/* ---------------- config pane (AI / Email / Alert) ---------------- */
function closeCfg() { $('#cfgpane').hidden = true; }
$('#cfg-close').onclick = closeCfg;

function openCfg(which) {
  $('#logpane').hidden = true;
  const pane = $('#cfgpane');
  pane.hidden = false;
  const title = { ai: 'AI scoring', email: 'Email notifications', alert: 'Phone / push alerts' }[which] || 'Configure';
  $('#cfg-title').textContent = title;
  const body = $('#cfg-body');
  const n = S.notify || {};

  if (which === 'ai') {
    body.replaceChildren(
      h('p', { class: 'hint' }, S.ai_enabled
        ? 'AI is on. JobPilot blends keyword match with Claude scoring and can write short cover notes on company forms.'
        : 'AI is off. Add an Anthropic API key in your .env file (ANTHROPIC_API_KEY=…) and restart JobPilot for smarter match scores + cover notes.'),
      h('div', { class: 'field' },
        h('label', {}, 'Status'),
        h('input', { value: S.ai_enabled ? 'Enabled' : 'Keyword-only (no API key)', disabled: true })),
      h('p', { class: 'hint', style: 'margin-top:12px' }, 'Edit the .env next to the app, then restart. Model can be set with LLM_MODEL.'),
    );
    return;
  }

  if (which === 'alert') {
    body.replaceChildren(
      h('p', { class: 'hint' }, 'Free push alerts via ntfy.sh — install the ntfy app on your phone, create a private topic, paste it below. No phone number needed.'),
      h('div', { class: 'field' },
        h('label', {}, 'ntfy topic'),
        h('input', { id: 'cfg-ntfy', value: n.ntfy_topic || '', placeholder: 'e.g. my-jobpilot-secret' })),
      h('div', { class: 'cfg-actions' },
        h('button', { class: 'go', onclick: guard(saveAlertCfg) }, 'Save'),
        h('button', { class: 'btn', onclick: guard(testNotify) }, 'Send test')),
      h('p', { class: 'hint', style: 'margin-top:14px' }, 'When a job is auto-applied or needs your help, you get a push on that topic.'),
    );
    return;
  }

  // email
  body.replaceChildren(
    h('p', { class: 'hint' }, 'Configure your email once. Every successful auto-apply (and batch finish / needs-you events) is mailed to you.'),
    h('div', { class: 'field' },
      h('label', {}, 'SMTP host'),
      h('input', { id: 'cfg-host', value: n.smtp_host || 'smtp.gmail.com', placeholder: 'smtp.gmail.com' })),
    h('div', { class: 'field' },
      h('label', {}, 'SMTP port'),
      h('input', { id: 'cfg-port', type: 'number', value: n.smtp_port || 587 })),
    h('div', { class: 'field' },
      h('label', {}, 'SMTP user (login email)'),
      h('input', { id: 'cfg-user', value: n.smtp_user || '', placeholder: 'you@gmail.com', autocomplete: 'username' })),
    h('div', { class: 'field' },
      h('label', {}, 'SMTP password / app password'),
      h('input', { id: 'cfg-pass', type: 'password', value: '', placeholder: n.has_pass ? '•••••••• (leave blank to keep)' : 'App password', autocomplete: 'new-password' })),
    h('div', { class: 'field' },
      h('label', {}, 'Send notifications to'),
      h('input', { id: 'cfg-to', value: n.notify_email || '', placeholder: 'same as login or another inbox' })),
    h('div', { class: 'cfg-actions' },
      h('button', { class: 'go', onclick: guard(saveEmailCfg) }, 'Save email'),
      h('button', { class: 'btn', onclick: guard(testNotify) }, 'Send test')),
    h('p', { class: 'hint', style: 'margin-top:14px' }, 'Gmail: enable 2FA → create an App Password → paste it here. Settings are stored only on your PC (data/notify.json).'),
  );
}

async function saveEmailCfg() {
  const data = {
    smtp_host: $('#cfg-host').value.trim(),
    smtp_port: +$('#cfg-port').value || 587,
    smtp_user: $('#cfg-user').value.trim(),
    notify_email: $('#cfg-to').value.trim(),
  };
  const pass = $('#cfg-pass').value;
  if (pass) data.smtp_pass = pass;
  await api('/api/notify', { method: 'PUT', json: { data } });
  toast('Email settings saved');
  await refresh();
  openCfg('email');
}

async function saveAlertCfg() {
  await api('/api/notify', { method: 'PUT', json: { data: { ntfy_topic: $('#cfg-ntfy').value.trim() } } });
  toast('Alert topic saved');
  await refresh();
  openCfg('alert');
}

async function testNotify() {
  const r = await api('/api/test-notify', { method: 'POST' });
  toast(r.sent ? 'Test sent — check your inbox / ntfy app' : 'Could not send. Check email / topic settings.');
}

/* ---------------- autopilot (progress + STOP) ---------------- */
function renderAutopilot() {
  const box = $('#auto'), r = S.run;
  if (!r.running) { box.hidden = true; box.replaceChildren(); return; }
  box.hidden = false;
  const pct = r.total ? Math.min(100, Math.round(100 * r.done / r.total)) : 0;
  const title = r.stopping ? 'Stopping…' : r.label || 'Working…';
  const isLogin = (r.phase === 'login') || /log in/i.test(r.label || '') || /log in/i.test(r.current || '');
  const kids = [
    h('div', {}, h('b', {}, title), h('small', {}, r.current || (isLogin ? 'Complete login in the browser window (OTP / captcha ok)' : ''))),
    h('div', { class: 'ap-actions' },
      isLogin && h('button', { class: 'go', onclick: guard(confirmLoggedIn) }, "I'm logged in"),
      h('button', { class: 'stop', disabled: r.stopping, onclick: guard(stopAll) }, h('i'), 'Stop')),
    h('div', { class: 'track' }, h('div', { class: 'fill', style: `width:${pct}%` })),
  ];
  if (isLogin) {
    kids.push(h('div', { class: 'login-hint' },
      '1) Browser window opens → 2) Log in on Naukri / foundit / etc. → 3) Come back here and press ',
      h('b', {}, "I'm logged in")));
  }
  box.replaceChildren(h('div', { class: 'ap' }, ...kids));
}
async function stopAll() { await api('/api/stop', { method: 'POST' }); toast('Stopping…'); await refresh(); }

/* ---------------- Jobs view ---------------- */
function chipToggle(list, key, label, onchange) {
  const pressed = list.includes(key);
  return h('button', { class: 'chip', 'aria-pressed': pressed ? 'true' : 'false', onclick: e => {
    const i = list.indexOf(key); i < 0 ? list.push(key) : list.splice(i, 1);
    e.currentTarget.setAttribute('aria-pressed', list.includes(key) ? 'true' : 'false');
    onchange && onchange();
  } }, label);
}

function buildJobsView() {
  const v = $('#v-jobs');

  const cityRow = h('div', { class: 'chips', id: 'city-row' });
  const portalRow = h('div', { class: 'chips', id: 'portal-row' });
  const empRow = h('div', { class: 'chips', id: 'emp-row' });
  const empHint = h('p', { class: 'tier-hint', id: 'emp-hint' }, EMP_HINT[empMode]);
  const renderEmp = () => {
    empRow.replaceChildren(...EMP_MODES.map(([k, l]) => h('button', { class: 'chip', 'aria-pressed': empMode === k ? 'true' : 'false', onclick: () => {
      empMode = k; renderEmp(); empHint.textContent = EMP_HINT[k]; } }, l)));
  };
  renderEmp();
  const panel = h('div', { class: 'panel' + (filtersOpen ? ' open' : '') },
    h('button', { class: 'panel-toggle', type: 'button', 'aria-expanded': String(filtersOpen), onclick: e => {
      filtersOpen = !filtersOpen; panel.classList.toggle('open', filtersOpen); e.currentTarget.setAttribute('aria-expanded', String(filtersOpen)); } },
      h('span', {}, 'Filters'), h('small', {}, 'job type · cities · company'), h('i', { class: 'chev' })),
    h('div', { class: 'card' },
      h('div', { class: 'grp' }, h('h3', {}, 'Job type'), empRow, empHint),
      h('div', { class: 'grp' }, h('h3', {}, 'Cities'), cityRow),
      h('div', { class: 'grp' }, h('h3', {}, 'Work style'), h('div', { class: 'chips' }, ...MODES.map(([k, l]) => chipToggle(modes, k, l)))),
      h('div', { class: 'grp' },
        h('h3', {}, 'Company tier'),
        h('div', { class: 'chips' }, ...TIERS.map(([k, l]) => chipToggle(tiers, k, l))),
        h('p', { class: 'tier-hint' }, 'Tier 1 = FAANG / large product & MNC · Tier 2 = mid-size · Tier 3 = startups & small firms. Leave all on to search everything.')),
      h('div', { class: 'grp' }, h('h3', {}, 'Company type'), h('div', { class: 'chips' }, ...TYPES.map(([k, l]) => chipToggle(types, k, l)))),
      h('div', { class: 'grp' }, h('h3', {}, 'Search on'), portalRow),
    ));

  const input = h('input', { id: 'role-in', placeholder: roles.length ? 'Add another role…' : 'e.g. Backend Engineer, DevOps', 'aria-label': 'Job role', onkeydown: e => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addRole(input.value); input.value = ''; }
    if (e.key === 'Backspace' && !input.value && roles.length) { roles.pop(); renderRoleChips(); }
  } });
  const chips = h('div', { class: 'chips', id: 'role-chips' });
  const sugg = h('div', { class: 'suggest', id: 'sugg' });

  const hero = h('div', { class: 'hero' },
    h('h2', {}, 'Multi-location job search'),
    h('p', {}, 'Search once across cities · match to your resume · auto-apply on portals & company career pages.'),
    h('div', { class: 'role-row', style: 'margin-bottom:10px' },
      h('span', { style: 'font-size:12px;font-weight:700;color:var(--mute)' }, 'Roles'),
      chips, input),
    h('div', { class: 'role-row' },
      h('span', { style: 'font-size:12px;font-weight:700;color:var(--mute)' }, 'Locations'),
      h('span', { id: 'loc-label', style: 'font-size:12px;color:var(--mute)' }, cities.length ? cities.join(', ') : 'Pick cities in the left panel (multi-location)'),
      h('button', { class: 'go', id: 'go', onclick: guard(doSearch) }, 'Search jobs')),
    sugg);

  const right = h('div', {}, hero, h('div', { class: 'bar', id: 'bar' }), h('div', { id: 'list' }));
  v.replaceChildren(h('div', { class: 'jobs-layout' }, panel, right));
  renderRoleChips(); renderCities(); renderPortalPick(); renderJobs();
}

function renderRoleChips() {
  const el = $('#role-chips');
  if (!el) return;
  el.replaceChildren(...roles.map(r => h('span', { class: 'chip role' }, r,
    h('button', { 'aria-label': 'Remove ' + r, onclick: () => { roles = roles.filter(x => x !== r); renderRoleChips(); } }, '×'))));
  const have = new Set(roles.map(r => r.toLowerCase()));
  const ideas = (S.profile.target_roles || []).filter(r => !have.has(r.toLowerCase()));
  const s = $('#sugg'); if (!s) return;
  s.replaceChildren();
  if (ideas.length) s.append('From your resume: ', ...ideas.slice(0, 6).map(r => h('button', { onclick: () => addRole(r) }, '+ ' + r)));
  else if (!S.resume) s.append(h('span', {}, 'Upload your resume first for role suggestions. '), h('a', { href: '#resume' }, 'Go to Resume'));
}
function addRole(r) { r = r.trim().replace(/,$/, ''); if (r && !roles.some(x => x.toLowerCase() === r.toLowerCase())) roles.push(r); renderRoleChips(); }

function updateLocLabel() {
  const el = $('#loc-label');
  if (el) el.textContent = cities.length ? cities.join(', ') : 'Pick cities in the left panel (multi-location)';
}

function renderCities() {
  const el = $('#city-row'); if (!el) return;
  const presets = new Set((S.city_presets || []).map(c => c.toLowerCase()));
  const custom = cities.filter(c => !presets.has(c.toLowerCase()));
  el.replaceChildren(
    ...(S.city_presets || []).map(c => chipToggle(cities, c, c, () => { updateLocLabel(); })),
    ...custom.map(c => h('button', { class: 'chip', 'aria-pressed': 'true', onclick: () => {
      cities = cities.filter(x => x.toLowerCase() !== c.toLowerCase());
      renderCities();
    } }, c, ' ×')),
    h('input', { class: 'chip', style: 'width:120px;cursor:text', placeholder: '+ city', 'aria-label': 'Add city', onkeydown: e => {
      if (e.key === 'Enter' && e.target.value.trim()) {
        const v = e.target.value.trim();
        if (!cities.some(x => x.toLowerCase() === v.toLowerCase())) cities.push(v);
        renderCities();
      }
    }})
  );
  updateLocLabel();
}

function renderPortalPick() {
  const el = $('#portal-row'); if (!el) return;
  const auto = S.portals.filter(p => p.auto);
  el.replaceChildren(
    ...auto.map(p => h('button', { class: 'chip', 'aria-pressed': portalPick.includes(p.id) ? 'true' : 'false', onclick: e => {
      const i = portalPick.indexOf(p.id); i < 0 ? portalPick.push(p.id) : portalPick.splice(i, 1);
      e.currentTarget.setAttribute('aria-pressed', portalPick.includes(p.id) ? 'true' : 'false'); } },
      h('i', { class: 'dot' + (p.connected ? ' on' : '') }), p.name)),
    h('button', { class: 'chip', 'aria-pressed': 'true', title: 'Always included', style: 'opacity:.85' },
      h('i', { class: 'dot on' }), 'Company pages'),
    h('a', { href: '#portals', style: 'font-size:12px;font-weight:600;margin-left:4px' }, 'Connect →'));
}

async function doSearch() {
  if (!roles.length) { const v = $('#role-in')?.value; if (v?.trim()) addRole(v); }
  if (!roles.length) return toast('Add at least one role first');
  if (S.run.running) return toast('Already running. Stop it first.');
  searching = true;
  // Clear previous unapplied jobs so results match the current location / tier / type filters
  try { await api('/api/jobs/clear', { method: 'POST' }); jobs = []; sel.clear(); } catch (e) {}
  const portals = portalPick.length ? portalPick : S.portals.filter(p => p.auto).map(p => p.id);
  const r = await api('/api/search', { json: {
    roles,
    locations: cities.slice(),
    work_modes: modes.length ? modes.slice() : ['remote', 'hybrid', 'wfo'],
    company_tiers: tiers.length ? tiers.slice() : ['tier1', 'tier2', 'tier3'],
    company_types: types.length ? types.slice() : ['mnc', 'product', 'startup', 'service'],
    portals: portals.slice(),
    employment_mode: empMode,
  }});
  toast(r.started ? 'Searching — contract / C2H jobs will be filtered out…' : 'Busy. Try again shortly.');
  if (window.innerWidth < 768) { filtersOpen = false; $('#v-jobs .panel')?.classList.remove('open'); }
  await refresh(true);
}

function scoreColor(n) { return n >= 75 ? 'var(--green)' : n >= 55 ? 'var(--teal)' : 'var(--amber)'; }
function pass(j) {
  const [label] = STATUS[j.status] || [j.status];
  const portal = S.portals.find(p => p.id === j.source);
  const canSel = j.apply_mode === 'auto' && ['new', 'failed', 'needs_human'].includes(j.status);
  const srcName = portal ? portal.name : (j.source || '').startsWith('greenhouse') || (j.source || '').startsWith('lever') || (j.source || '').startsWith('ashby')
    ? 'Company site' : (j.source || '').split(':')[0];
  const emp = EMP_TAG[j.emp_type] || null;
  const tags = [
    emp && h('span', { class: 'tag emp ' + emp[1], title: j.emp_note || '' }, emp[0]),
    j.location && h('span', { class: 'tag' }, j.location),
    j.work_mode && h('span', { class: 'tag ' + j.work_mode }, { remote: 'Remote', hybrid: 'Hybrid', wfo: 'On-site' }[j.work_mode] || j.work_mode),
    j.exp && h('span', { class: 'tag' }, j.exp),
    j.salary && h('span', { class: 'tag' }, j.salary),
    j.company_tier && h('span', { class: 'tag' }, j.company_tier.replace('tier', 'T')),
    h('span', { class: 'tag src' }, srcName),
  ];
  const canBlock = ['new', 'manual', 'needs_human', 'failed', 'ready'].includes(j.status);
  const acts = [
    h('a', { class: 'btn', href: j.url, target: '_blank', rel: 'noopener' }, 'Open'),
    j.status === 'ready' && h('button', { class: 'btn pri', onclick: guard(() => act(`/api/jobs/${j.id}/approve`, 'Submitting…')) }, 'Approve & submit'),
    ['failed', 'needs_human'].includes(j.status) && j.apply_mode === 'auto' && h('button', { class: 'btn', onclick: guard(() => act(`/api/jobs/${j.id}/retry`, 'Retrying…')) }, 'Retry'),
    ['new', 'manual', 'needs_human', 'ready', 'failed'].includes(j.status) && h('button', { class: 'btn', onclick: guard(() => setStatus(j.id, 'applied')) }, 'I applied'),
    ['new', 'manual', 'needs_human', 'failed'].includes(j.status) && h('button', { class: 'btn ghost', onclick: guard(() => setStatus(j.id, 'skipped')) }, 'Skip'),
    canBlock && h('button', { class: 'btn ghost', title: 'Never apply to ' + j.company, onclick: guard(() => avoidCompany(j.company)) }, 'Block company'),
    j.status === 'skipped' && h('button', { class: 'btn', onclick: guard(() => setStatus(j.id, 'new')) }, 'Restore'),
    ['ready', 'applied', 'needs_human', 'failed'].includes(j.status) && j.apply_mode === 'auto' && h('a', { class: 'btn ghost', href: `/shots/job_${j.id}.png`, target: '_blank' }, 'Screenshot'),
  ];
  const note = j.note || (j.reason && j.status === 'new' ? j.reason : '');
  return h('article', { class: `pass s-${j.status}` + (sel.has(j.id) ? ' sel-on' : '') },
    h('div', { class: 'sel' }, canSel ? h('input', { type: 'checkbox', 'aria-label': 'Select ' + j.title, checked: sel.has(j.id), onchange: e => { e.target.checked ? sel.add(j.id) : sel.delete(j.id); renderJobs(); } }) : null),
    h('div', { class: 'main' }, h('h3', {}, j.title), h('p', { class: 'co' }, j.company), h('div', { class: 'tags' }, tags),
      j.matched && j.matched.length ? h('div', { class: 'kw' }, 'Matched skills: ', h('b', {}, j.matched.slice(0, 6).join(', '))) : null),
    h('div', { class: 'score' }, h('div', { class: 'ring', style: `--p:${j.score};--c:${scoreColor(j.score)}`, title: 'Match score' }, h('span', {}, j.score)),
      h('div', { class: 'score-t' }, h('div', { class: 'state' }, label), h('span', { class: 'badge ' + j.apply_mode }, j.apply_mode === 'auto' ? 'Auto' : 'Manual'))),
    h('div', { class: 'rest' },
      note ? h('div', { class: 'note' }, note) : null,
      j.applied_by ? h('div', { class: 'note' }, j.applied_by === 'ai' ? 'Applied by JobPilot' : 'Applied by you') : null,
      h('div', { class: 'acts' }, acts)));
}
async function avoidCompany(name) {
  if (!confirm(`Never apply to "${name}" again? Its open jobs move to Skipped. (Undo in Settings.)`)) return;
  const r = await api('/api/avoid', { json: { company: name } });
  toast(`Blocked ${name}` + (r.skipped ? ` · ${r.skipped} job(s) skipped` : ''));
  await refresh(true);
}
async function act(path, msg) { const r = await api(path, { method: 'POST' }); toast(r.started ? msg : 'Busy. Try again.'); await refresh(true); }
async function setStatus(id, s) { await api(`/api/jobs/${id}/status`, { json: { status: s } }); await refresh(true); }

function renderJobs() {
  if (!$('#list')) return;
  const counts = Object.fromEntries(FILTERS.map(([k]) => [k, jobs.filter(j => inFilter(j, k)).length]));
  $('#bar').replaceChildren(
    h('h2', {}, jobs.length ? `${jobs.length} jobs` : 'Jobs'),
    ...FILTERS.map(([k, l]) => h('button', { class: 'pill', 'aria-pressed': filter === k, onclick: () => { filter = k; renderJobs(); } }, l, h('b', {}, counts[k]))),
    jobs.some(j => j.status !== 'applied') ? h('button', { class: 'btn danger', onclick: guard(clearJobs) }, 'Clear unapplied') : null);
  const list = jobs.filter(j => inFilter(j, filter));
  const el = $('#list');
  if (!list.length) {
    el.replaceChildren(h('div', { class: 'empty' },
      h('b', {}, jobs.length ? 'Nothing in this filter' : 'No jobs yet'),
      jobs.length ? 'Try another filter or run a new search.' : 'Add roles, pick Tier 1 / 2 / 3 companies you want, then press Find jobs.'));
  } else {
    el.replaceChildren(...list.map(pass));
  }
  updateDock();
}

async function clearJobs() {
  if (!confirm('Remove all jobs that are not marked Applied?')) return;
  await api('/api/jobs/clear', { method: 'POST' });
  jobs = []; sel.clear(); toast('Cleared'); await refresh();
}

/* ---------------- dock: select + full auto apply ---------------- */
function updateDock() {
  const dock = $('#dock');
  if (view !== 'jobs' || !jobs.length) { dock.hidden = true; dock.replaceChildren(); return; }
  dock.hidden = false;
  const autoJobs = jobs.filter(j => j.apply_mode === 'auto' && ['new', 'failed', 'needs_human'].includes(j.status));
  const strong = autoJobs.filter(j => j.score >= (S.prefs?.min_score || 55));
  const n = sel.size;
  const autoOn = !!(S.prefs?.auto_submit);
  dock.replaceChildren(
    h('span', { class: 'count' }, n ? `${n} selected` : `${autoJobs.length} ready`),
    h('button', { class: 'btn', onclick: () => { strong.forEach(j => sel.add(j.id)); renderJobs(); } }, 'Select strong'),
    h('button', { class: 'btn alt', onclick: () => { autoJobs.forEach(j => sel.add(j.id)); renderJobs(); } }, 'Select all auto'),
    h('button', { class: 'btn ghost alt', onclick: () => { sel.clear(); renderJobs(); } }, 'Clear'),
    h('button', {
      class: 'go',
      disabled: !n || S.run.running,
      onclick: guard(autoApply),
      title: autoOn ? 'Fills profile fields + uploads resume + submits automatically' : 'Fills forms, then waits for your Approve',
    }, autoOn ? 'Auto apply (fill + submit)' : 'Fill forms (review mode)'),
    h('label', { class: 'switch' },
      h('input', {
        type: 'checkbox',
        checked: autoOn,
        onchange: guard(async e => {
          const data = { ...S.prefs, auto_submit: e.target.checked };
          await api('/api/prefs', { method: 'PUT', json: { data } });
          toast(e.target.checked ? 'Full auto-submit ON — bot will submit after filling' : 'Review mode — bot fills, you approve');
          await refresh();
        }),
      }),
      'Full auto-submit'),
    h('span', { class: 'hint' }, autoOn
      ? 'Bot fills every field from your resume and submits. Success emails go to your configured inbox.'
      : 'Bot fills the form and pauses. Press Approve & submit on each job.'),
  );
}

async function autoApply() {
  if (!sel.size) return toast('Select jobs first');
  if (S.run.running) return toast('Already running');
  const submit = !!(S.prefs?.auto_submit);
  const r = await api('/api/apply', { json: { ids: [...sel], submit } });
  toast(r.started
    ? (submit ? 'Auto-applying: filling forms + submitting…' : 'Filling forms (review mode)…')
    : 'Busy. Try again.');
  sel.clear();
  await refresh(true);
}

/* ---------------- Resume view ---------------- */
const FIELDS = [
  ['first_name', 'First name'], ['last_name', 'Last name'], ['email', 'Email'], ['phone', 'Phone'],
  ['linkedin', 'LinkedIn URL'], ['github', 'GitHub'], ['website', 'Portfolio / website'],
  ['location', 'Current city'], ['current_company', 'Current company'], ['current_title', 'Current title'],
  ['years_experience', 'Years of experience'], ['notice_period', 'Notice period'],
  ['current_ctc', 'Current CTC'], ['expected_ctc', 'Expected CTC'],
];

function fieldVal(p, k) {
  const v = p[k];
  if (v == null || v === '') return '';
  return String(v);
}
function isFilled(p, k) {
  const v = p[k];
  if (Array.isArray(v)) return v.length > 0;
  return v != null && String(v).trim() !== '' && v !== 0;
}
function buildResumeView() {
  const v = $('#v-resume');
  const r = S.resume;
  const p = S.profile || {};
  const filledCount = FIELDS.filter(([k]) => isFilled(p, k)).length
    + (isFilled(p, 'skills') ? 1 : 0) + (isFilled(p, 'target_roles') ? 1 : 0);
  const totalFields = FIELDS.length + 2;

  const fileIn = h('input', { type: 'file', accept: '.pdf,.docx,.txt', hidden: true, onchange: e => guard(upload)(e.target.files[0]) });
  const drop = h('div', {
    class: 'drop',
    onclick: () => fileIn.click(),
    ondragover: e => { e.preventDefault(); drop.classList.add('over'); },
    ondragleave: () => drop.classList.remove('over'),
    ondrop: e => { e.preventDefault(); drop.classList.remove('over'); guard(upload)(e.dataTransfer.files[0]); },
  },
    h('b', {}, r ? 'Drop a new resume to replace' : 'Drop your resume here'),
    'PDF · DOCX · TXT — we extract name, email, phone, skills, roles, CTC & notice automatically');
  drop.append(fileIn);

  const left = h('div', {},
    h('h2', { class: 'section-title' }, 'Resume file'),
    h('p', { class: 'section-sub' }, 'Upload once. Every apply form is filled from this profile — no re-typing.'),
    r ? h('div', { class: 'file' },
      h('div', { class: 'ext' }, (r.ext || 'pdf').toUpperCase()),
      h('div', { style: 'min-width:0;flex:1' },
        h('b', {}, r.name),
        h('div', { class: 'muted', style: 'font-size:12px' }, `${r.kb} KB · ${r.modified}`),
        h('div', { class: 'row', style: 'margin-top:8px' },
          h('a', { class: 'btn', href: '/api/resume/file' }, 'Download'),
          h('button', { class: 'btn', onclick: () => fileIn.click() }, 'Replace'))))
      : null,
    drop,
    filledCount > 2 ? h('div', { class: 'profile-banner', style: 'margin-top:14px' },
      h('div', {},
        h('strong', {}, `Profile loaded · ${filledCount}/${totalFields} fields`),
        'Edit anything below if needed, then Save. Target roles feed the Jobs search suggestions.'))
      : null);

  const fields = h('div', { class: 'card' },
    h('h2', { class: 'section-title' }, 'Auto-loaded profile'),
    h('p', { class: 'section-sub' }, 'Parsed from your resume. Highlighted fields were filled automatically.'),
    (p.summary ? h('div', { class: 'field filled', style: 'margin-bottom:12px' },
      h('label', {}, 'Summary'),
      h('textarea', { rows: 2, value: p.summary || '', 'data-k': 'summary', onchange: e => p.summary = e.target.value })) : null),
    (p.education ? h('div', { class: 'field filled', style: 'margin-bottom:12px' },
      h('label', {}, 'Education'),
      h('input', { value: p.education || '', 'data-k': 'education', onchange: e => p.education = e.target.value })) : null),
    h('div', { class: 'grid2' }, ...FIELDS.map(([k, lab]) =>
      h('div', { class: 'field' + (isFilled(p, k) ? ' filled' : '') },
        h('label', {}, lab),
        h('input', { value: fieldVal(p, k), 'data-k': k, onchange: e => p[k] = e.target.value })))),
    h('div', { class: 'field' + (isFilled(p, 'skills') ? ' filled' : ''), style: 'margin-top:12px' },
      h('label', {}, 'Skills (comma separated)'),
      h('textarea', { rows: 3, value: (p.skills || []).join(', '), onchange: e => p.skills = e.target.value.split(',').map(s => s.trim()).filter(Boolean) })),
    h('div', { class: 'field' + (isFilled(p, 'target_roles') ? ' filled' : ''), style: 'margin-top:12px' },
      h('label', {}, 'Target roles (auto-suggested from resume)'),
      h('textarea', { rows: 2, value: (p.target_roles || []).join(', '), onchange: e => p.target_roles = e.target.value.split(',').map(s => s.trim()).filter(Boolean) })),
    h('div', { class: 'row', style: 'margin-top:16px' },
      h('button', { class: 'go', onclick: guard(saveProfile) }, 'Save profile'),
      filledCount > 2 ? h('button', { class: 'btn pri', onclick: () => go('jobs') }, 'Continue to Jobs →') : null));

  v.replaceChildren(h('div', { class: 'resume-grid' }, left, fields));
}
async function upload(f) {
  if (!f) return;
  toast('Parsing resume… extracting full profile');
  const fd = new FormData(); fd.append('file', f);
  const res = await fetch('/api/resume', { method: 'POST', body: fd });
  const r = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(r.detail || r.error || 'Upload failed');
  await refresh(true);
  const p = S.profile || {};
  const n = ['first_name','email','phone','skills','target_roles','years_experience']
    .filter(k => (Array.isArray(p[k]) ? p[k].length : p[k])).length;
  toast(n >= 3
    ? `Resume loaded — ${n}+ profile fields filled automatically`
    : 'Resume uploaded. Review & complete any empty fields.');
  go('resume');
}
async function saveProfile() {
  const p = S.profile || {};
  document.querySelectorAll('[data-k]').forEach(el => { p[el.dataset.k] = el.value; });
  await api('/api/profile', { method: 'PUT', json: { data: p } });
  toast('Profile saved'); await refresh();
}

/* ---------------- Portals view ---------------- */
function buildPortalsView() {
  const v = $('#v-portals');
  const auto = S.portals.filter(p => p.auto);
  const manual = S.portals.filter(p => !p.auto);
  v.replaceChildren(
    h('h2', { class: 'section-title' }, 'Job portals'),
    h('p', { class: 'section-sub' }, 'Click Connect → a real Chrome window opens → log in yourself (OTP fine) → press I’m logged in on the purple banner. Password is never stored by JobPilot.'),
    h('h3', { style: 'font-size:14px;margin:16px 0 10px;color:var(--mute)' }, 'Auto-apply portals'),
    h('div', { class: 'portal-grid' }, ...auto.map(p =>
      h('div', { class: 'portal-card' },
        h('h3', {}, h('i', { class: 'dot' + (p.connected ? ' on' : '') }), p.name),
        h('p', {}, p.blurb || ''),
        h('span', { class: 'status ' + (p.connected ? 'ok' : 'off') }, p.connected ? 'Connected' : 'Not connected'),
        h('div', { class: 'row', style: 'margin-top:12px' },
          h('button', { class: 'btn pri', onclick: guard(() => connectPortal(p.id)) }, p.connected ? 'Reconnect' : 'Connect'),
          p.connected && h('button', { class: 'btn', onclick: guard(() => disconnectPortal(p.id)) }, 'Disconnect'))))),
    h('h3', { style: 'font-size:14px;margin:24px 0 10px;color:var(--mute)' }, 'Manual search links (no auto-apply)'),
    h('div', { class: 'portal-grid' }, ...manual.map(p =>
      h('div', { class: 'portal-card' },
        h('h3', {}, p.name),
        h('p', {}, p.blurb || 'Opens a pre-filled search. You apply yourself.'),
        h('a', { class: 'btn', href: '#jobs', onclick: () => go('jobs') }, 'Use from Jobs page')))));
}
async function connectPortal(id) {
  toast('Opening browser… complete login there (OTP ok)');
  const r = await api(`/api/portals/${id}/connect`, { method: 'POST' });
  // started is async — poll will show "I'm logged in" banner
  if (r.started === false) toast('Busy — stop current task first');
  else toast('Browser opening — log in, then press I’m logged in below');
  await refresh();
}
async function confirmLoggedIn() {
  await api('/api/portals/done', { method: 'POST' });
  toast('Checking login…');
  await refresh(true);
}
async function disconnectPortal(id) {
  await api(`/api/portals/${id}/disconnect`, { method: 'POST' });
  toast('Disconnected'); await refresh();
}

/* ---------------- Settings view ---------------- */
function buildSettingsView() {
  const v = $('#v-settings');
  const p = S.prefs || {};
  const n = S.notify || {};
  v.replaceChildren(
    h('h2', { class: 'section-title' }, 'Settings'),
    h('p', { class: 'section-sub' }, 'Match threshold, daily limit, full auto-submit, and notification delivery.'),
    h('div', { class: 'auto-banner' },
      h('div', {},
        h('strong', {}, 'Full auto-apply mode'),
        ' When Full auto-submit is on, the bot opens the apply page, fills name / email / phone / CTC / notice / skills from your profile, uploads your resume, and submits — then emails you the result.')),
    h('div', { class: 'set-grid' },
      h('div', { class: 'card' },
        h('h3', { style: 'font-size:15px;margin-bottom:12px' }, 'Apply behaviour'),
        h('div', { class: 'field', style: 'margin-bottom:12px' },
          h('label', {}, 'Minimum match score (0–100)'),
          h('input', { type: 'number', min: 0, max: 100, value: p.min_score ?? 55, id: 'set-min' })),
        h('div', { class: 'field', style: 'margin-bottom:12px' },
          h('label', {}, 'Daily apply cap'),
          h('input', { type: 'number', min: 1, max: 100, value: p.daily_cap ?? 25, id: 'set-cap' })),
        h('label', { class: 'switch', style: 'margin-bottom:12px' },
          h('input', { type: 'checkbox', checked: !!p.auto_submit, id: 'set-auto' }),
          'Full auto-submit (fill + submit, no approval step)'),
        h('label', { class: 'switch' },
          h('input', { type: 'checkbox', checked: p.include_career_pages !== false, id: 'set-career' }),
          'Include company career pages'),
        h('div', { class: 'row', style: 'margin-top:16px' },
          h('button', { class: 'go', onclick: guard(saveSettings) }, 'Save settings'))),
      h('div', { class: 'card' },
        h('h3', { style: 'font-size:15px;margin-bottom:12px' }, 'Direct payroll / no C2H'),
        h('div', { class: 'field', style: 'margin-bottom:12px' },
          h('label', {}, 'Job type to apply for'),
          h('select', { id: 'set-emp' }, ...EMP_MODES.map(([k, l]) => h('option', { value: k, selected: (p.employment_mode || 'direct') === k }, l)))),
        h('p', { class: 'hint-s', id: 'set-emp-hint' }, EMP_HINT[p.employment_mode || 'direct']),
        h('label', { class: 'switch', style: 'margin:4px 0 12px' },
          h('input', { type: 'checkbox', checked: p.deep_check !== false, id: 'set-deep' }),
          'Open each job and read the full JD first'),
        h('div', { class: 'field', style: 'margin-bottom:12px' },
          h('label', {}, 'Max jobs to open per search'),
          h('input', { type: 'number', min: 0, max: 200, value: p.deep_check_limit ?? 40, id: 'set-deeplim' })),
        h('div', { class: 'field' },
          h('label', {}, 'Never apply to these companies (one per line)'),
          h('textarea', { rows: 4, id: 'set-avoid', placeholder: 'e.g. ABC Consultants', value: (p.avoid_companies || []).join('\n') })),
        h('div', { class: 'row', style: 'margin-top:14px' },
          h('button', { class: 'go', onclick: guard(saveSettings) }, 'Save'))),
      h('div', { class: 'card' },
        h('h3', { style: 'font-size:15px;margin-bottom:12px' }, 'Notifications & status'),
        h('p', { style: 'font-size:13px;color:var(--mute);margin:0 0 8px' }, `AI scoring: ${S.ai_enabled ? 'Enabled' : 'Keyword-only (add ANTHROPIC_API_KEY)'}`),
        h('p', { style: 'font-size:13px;color:var(--mute);margin:0 0 8px' }, `Email alerts: ${S.email_enabled ? 'On → ' + (n.notify_email || n.smtp_user || '') : 'Off — use Configure email below'}`),
        h('p', { style: 'font-size:13px;color:var(--mute);margin:0 0 8px' }, `Push alerts: ${S.push_enabled ? 'On' : 'Off — use Configure alerts below'}`),
        h('p', { style: 'font-size:13px;color:var(--mute);margin:0 0 14px' }, `Applied today: ${S.applied_today} / ${p.daily_cap || 25}`),
        h('div', { class: 'row' },
          h('button', { class: 'btn', onclick: () => openCfg('email') }, 'Configure email'),
          h('button', { class: 'btn', onclick: () => openCfg('alert') }, 'Configure alerts'),
          h('button', { class: 'btn', onclick: () => openCfg('ai') }, 'AI scoring'),
          h('button', { class: 'btn', onclick: guard(testNotify) }, 'Send test')))));
}
document.addEventListener('change', e => { if (e.target.id === 'set-emp') $('#set-emp-hint').textContent = EMP_HINT[e.target.value]; });
async function saveSettings() {
  const data = {
    ...S.prefs,
    min_score: +$('#set-min').value,
    daily_cap: +$('#set-cap').value,
    auto_submit: $('#set-auto').checked,
    include_career_pages: $('#set-career').checked,
    employment_mode: $('#set-emp').value,
    deep_check: $('#set-deep').checked,
    deep_check_limit: Math.max(0, +$('#set-deeplim').value || 0),
    avoid_companies: $('#set-avoid').value.split('\n').map(x => x.trim()).filter(Boolean),
  };
  empMode = data.employment_mode;
  await api('/api/prefs', { method: 'PUT', json: { data } });
  toast('Settings saved'); await refresh();
}

/* ---------------- render + refresh ---------------- */
function renderView() {
  if (view === 'jobs') buildJobsView();
  else if (view === 'resume') buildResumeView();
  else if (view === 'portals') buildPortalsView();
  else if (view === 'usage') buildUsageView();
  else if (view === 'owner') buildOwnerView();
  else if (view === 'settings') buildSettingsView();
}

function updateUserChip() {
  const el = $('#user-chip');
  if (!el || !S?.user) return;
  el.innerHTML = '';
  el.append(
    h('span', {}, h('b', {}, S.user.username || 'user'), ' · '),
    h('span', { class: 'tok' }, (S.user.tokens ?? 0) + ' tok'),
    h('button', { class: 'btn ghost', style: 'margin-left:auto;padding:2px 8px;font-size:11px', onclick: logout }, 'Logout')
  );
}

async function buildUsageView() {
  const root = $('#v-usage');
  root.replaceChildren(h('div', { class: 'pass' }, 'Loading usage…'));
  try {
    const u = await api('/api/usage');
    root.replaceChildren(
      h('div', { class: 'pass' },
        h('h2', {}, 'Token balance'),
        h('p', { class: 'page-sub' }, '1 token ≈ one search / apply batch. Admin can top-up.'),
        h('div', { style: 'font-size:28px;font-weight:800;color:#f0c14b;margin:12px 0' }, (u.tokens ?? 0) + ' tokens'),
      ),
      h('div', { class: 'pass' },
        h('h3', {}, 'Recent usage'),
        ...(u.history || []).length ? u.history.map(x => h('div', { class: 'row', style: 'display:flex;gap:12px;padding:8px 0;border-bottom:1px solid var(--border)' },
          h('span', { style: 'min-width:90px;color:var(--mute)' }, (x.created || '').slice(0, 16)),
          h('b', {}, x.action),
          h('span', {}, '-' + x.tokens),
          h('span', { class: 'mute' }, x.detail || ''),
        )) : [h('p', { class: 'mute' }, 'No usage yet.')]
      ),
      h('div', { class: 'pass' },
        h('h3', {}, 'Payments / top-ups'),
        ...(u.payments || []).length ? u.payments.map(x => h('div', { class: 'row', style: 'display:flex;gap:12px;padding:8px 0;border-bottom:1px solid var(--border)' },
          h('span', { style: 'min-width:90px;color:var(--mute)' }, (x.created || '').slice(0, 16)),
          h('span', {}, '+' + (x.tokens_added || 0) + ' tok'),
          h('span', { class: 'mute' }, x.note || x.status),
        )) : [h('p', { class: 'mute' }, 'No payments yet.')]
      ),
    );
  } catch (e) {
    root.replaceChildren(h('div', { class: 'pass' }, h('p', {}, e.message || 'Failed to load usage')));
  }
}

async function buildOwnerView() {
  const root = $('#v-owner');
  if (S?.user?.role !== 'admin') {
    root.replaceChildren(h('div', { class: 'pass' }, h('p', {}, 'Admin only. Login as sasi.')));
    return;
  }
  root.replaceChildren(h('div', { class: 'pass' }, 'Loading users…'));
  try {
    const data = await api('/api/owner/users');
    const users = data.users || [];
    root.replaceChildren(
      h('div', { class: 'pass' },
        h('h2', {}, 'Owner console'),
        h('p', { class: 'page-sub' }, 'Create users · top-up tokens · reset password · monitor balance'),
      ),
      h('div', { class: 'pass' },
        h('h3', {}, 'Users'),
        h('table', { style: 'width:100%;border-collapse:collapse;font-size:13px' },
          h('thead', {}, h('tr', {},
            h('th', { style: 'text-align:left;padding:8px' }, 'ID'),
            h('th', { style: 'text-align:left;padding:8px' }, 'Username'),
            h('th', { style: 'text-align:left;padding:8px' }, 'Role'),
            h('th', { style: 'text-align:left;padding:8px' }, 'Tokens'),
            h('th', { style: 'text-align:left;padding:8px' }, 'Action'),
          )),
          h('tbody', {}, ...users.map(u => h('tr', { style: 'border-top:1px solid var(--border)' },
            h('td', { style: 'padding:8px' }, String(u.id)),
            h('td', { style: 'padding:8px' }, u.username || '—'),
            h('td', { style: 'padding:8px' }, u.role || 'user'),
            h('td', { style: 'padding:8px;color:#f0c14b;font-weight:700' }, String(u.tokens ?? 0)),
            h('td', { style: 'padding:8px;display:flex;gap:6px;flex-wrap:wrap' },
              h('button', { class: 'btn', type: 'button', onclick: () => topupUser(u.id) }, '+50 tok'),
              h('button', { class: 'btn ghost', type: 'button', onclick: () => resetPwUser(u.id, u.username) }, 'Reset PW'),
            ),
          ))),
        ),
      ),
      h('div', { class: 'pass' },
        h('h3', {}, 'Create user'),
        h('form', { id: 'create-user-form', onsubmit: createUser, style: 'display:grid;gap:12px;max-width:360px' },
          h('div', {},
            h('label', { style: 'display:block;font-size:12px;color:var(--mute);margin-bottom:4px' }, 'Username'),
            h('input', { name: 'username', required: true, placeholder: 'newuser', style: 'width:100%;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--bg-2);color:var(--ink)' }),
          ),
          h('div', {},
            h('label', { style: 'display:block;font-size:12px;color:var(--mute);margin-bottom:4px' }, 'Password (min 6)'),
            h('input', { name: 'password', type: 'password', required: true, minlength: 6, placeholder: '••••••••', style: 'width:100%;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--bg-2);color:var(--ink)' }),
          ),
          h('div', {},
            h('label', { style: 'display:block;font-size:12px;color:var(--mute);margin-bottom:4px' }, 'Starting tokens'),
            h('input', { name: 'tokens', type: 'number', value: 50, min: 0, style: 'width:100%;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--bg-2);color:var(--ink)' }),
          ),
          h('button', { type: 'submit', class: 'btn primary' }, 'Create user'),
        ),
      ),
    );
  } catch (e) {
    root.replaceChildren(h('div', { class: 'pass' }, h('p', {}, e.message || 'Failed')));
  }
}

async function topupUser(uid) {
  try {
    await api('/api/owner/topup', { json: { user_id: uid, tokens: 50, note: 'Quick +50' } });
    toast('+50 tokens added');
    buildOwnerView();
    refresh();
  } catch (e) { toast(e.message); }
}

async function resetPwUser(uid, username) {
  const pw = prompt('New password for ' + (username || uid) + ' (min 6 chars):');
  if (!pw) return;
  if (pw.length < 6) { toast('Password must be at least 6 characters'); return; }
  try {
    await api('/api/owner/reset-password', { json: { user_id: uid, password: pw } });
    toast('Password reset for ' + (username || uid));
  } catch (e) { toast(e.message); }
}

async function createUser(ev) {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  try {
    await api('/api/owner/create-user', {
      json: {
        username: fd.get('username'),
        password: fd.get('password'),
        tokens: Number(fd.get('tokens') || 50),
      },
    });
    toast('User created');
    buildOwnerView();
  } catch (e) { toast(e.message); }
}

async function logout() {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch (e) {}
  showLogin();
}

function showLogin() {
  $('#login-screen').hidden = false;
  $('#app-shell').hidden = true;
}

function showApp() {
  $('#login-screen').hidden = true;
  $('#app-shell').hidden = false;
}

async function trySession() {
  try {
    const me = await api('/api/auth/me');
    if (me && me.id) return me;
  } catch (e) {}
  return null;
}

$('#login-form')?.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const err = $('#login-error');
  err.hidden = true;
  try {
    await api('/api/auth/login', {
      json: { username: fd.get('username'), password: fd.get('password') },
    });
    showApp();
    filtersSynced = false;
    await refresh(true);
    renderNav();
    updateUserChip();
  } catch (e) {
    err.textContent = e.message || 'Login failed';
    err.hidden = false;
  }
});

let wasRunning = false;
let filtersSynced = false;

async function refresh(forceJobs = false) {
  S = await api('/api/state');
  updateUserChip();
  if (!filtersSynced) {
    if (S.prefs.roles?.length) roles = [...S.prefs.roles];
    if (S.prefs.locations?.length) cities = [...S.prefs.locations];
    if (S.prefs.work_modes?.length) modes = [...S.prefs.work_modes];
    if (S.prefs.company_tiers?.length) tiers = [...S.prefs.company_tiers];
    if (S.prefs.company_types?.length) types = [...S.prefs.company_types];
    if (S.prefs.employment_mode) empMode = S.prefs.employment_mode;
    if (S.prefs.portals?.length) portalPick = [...S.prefs.portals];
    else portalPick = (S.portals || []).filter(p => p.auto).map(p => p.id);
    filtersSynced = true;
  }

  renderLeds(); renderAutopilot(); renderLog();

  const key = JSON.stringify(S.stats || {}) + '|' + (S.run?.last_run || '') + '|' + (S.applied_today || 0);
  const runEnded = wasRunning && !S.run.running;
  wasRunning = !!S.run.running;
  if (forceJobs || key !== jobsKey || searching || runEnded || S.run.running) {
    jobs = await api('/api/jobs').then(r => Array.isArray(r) ? r : (r.jobs || [])).catch(() => []);
    jobsKey = key;
    searching = false;
  }
  // Hide owner tab for non-admin in nav
  document.querySelectorAll('#nav button').forEach(btn => {
    const lbl = btn.querySelector('.lbl')?.textContent;
    if (lbl === 'Owner') btn.style.display = S?.user?.role === 'admin' ? '' : 'none';
  });
  renderView();
}

setInterval(() => { if (S?.run?.running || wasRunning) refresh(); }, 2000);

(async function boot() {
  const me = await trySession();
  if (me) {
    showApp();
    await refresh(true);
    renderNav();
    updateUserChip();
  } else {
    showLogin();
  }
})();
