"""
Compact ServerHistory by reducing row density in older time zones.

Zone definitions (hardcoded):
  Daily   : [today-30d,  today]       → never touched
  Weekly  : [today-70d,  today-30d)   → one row per (server, app) per Sunday
  Monthly : [oldest,     today-70d)   → one row per (server, app) per 1st of month

Algorithm per (SERVER_ID, APP_NAME_VALUE) per zone:
  1. Take a snapshot at each reference date (Sunday / 1st).
  2. Collapse consecutive identical snapshots into a single row.
  3. Delete closed rows completely contained in the zone.
  4. Trim any pre-zone row whose valid_to falls inside the zone.
  5. Insert the new compacted rows.

Rows that span a zone boundary are never split.
Open rows (valid_to IS NULL) are only deleted when the last compacted row
is also open (i.e., the server is still alive and we're taking over).
"""
import hashlib
import json
import logging
from collections import defaultdict
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Min, Q

from inventory.models import ServerHistory

logger_w = logging.getLogger('compact.weekly')
logger_m = logging.getLogger('compact.monthly')

# ── Hardcoded thresholds ──────────────────────────────────────────────────────
DAILY_KEEP  = 30   # days kept at full (daily) resolution
WEEKLY_KEEP = 70   # days = 10 weeks; older than this goes to monthly

TRACKED_FIELDS = [
    'APP_CRITICALITY', 'APP_OWNERBUSINESSLINE',
    'ENVIRONMENT', 'INFRAVERSION', 'ECOSYSTEM', 'PERIMETER',
    'OSSHORTNAME', 'OSFAMILY', 'PAMELA_PRODUCT',
    'REGION', 'SNOW_DATACENTER', 'MACHINE_TYPE', 'MANUFACTURER', 'MODEL',
    'SNOW_SUPPORTGROUP', 'SNOW_STATUS',
    'CPU', 'RAM',
]
# Fields shown in the HTML report detail table (subset for readability)
DISPLAY_FIELDS = ['ENVIRONMENT', 'OSSHORTNAME', 'SNOW_DATACENTER', 'MACHINE_TYPE', 'SNOW_STATUS']

_ROW_FIELDS = ('id', 'SERVER_ID', 'APP_NAME_VALUE', 'valid_from', 'valid_to', *TRACKED_FIELDS)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _attrs_hash(attrs):
    parts = [str(attrs.get(f) or '') for f in TRACKED_FIELDS]
    return hashlib.md5('|'.join(parts).encode()).hexdigest()


def _display_attrs(attrs):
    return {f: str(attrs.get(f) or '') for f in DISPLAY_FIELDS}


def _row_rec(r):
    attrs = {f: r[f] for f in TRACKED_FIELDS}
    return {
        'f': str(r['valid_from']),
        't': str(r['valid_to']) if r['valid_to'] else None,
        'h': _attrs_hash(attrs)[:6],
        'a': _display_attrs(attrs),
    }


def _group_rec(g):
    return {
        'f': str(g['valid_from']),
        't': str(g['valid_to']) if g['valid_to'] else None,
        'h': _attrs_hash(g['attrs'])[:6],
        'a': _display_attrs(g['attrs']),
    }


def _sundays_between(start, end):
    """All Sundays S with start <= S < end."""
    days_ahead = (6 - start.weekday()) % 7
    d = start + timedelta(days=days_ahead)
    result = []
    while d < end:
        result.append(d)
        d += timedelta(weeks=1)
    return result


def _firsts_between(start, end):
    """All 1st-of-month dates d with start <= d < end."""
    if start.day == 1:
        d = start
    else:
        m = start.month % 12 + 1
        y = start.year + (1 if start.month == 12 else 0)
        d = date(y, m, 1)
    result = []
    while d < end:
        result.append(d)
        m = d.month % 12 + 1
        y = d.year + (1 if d.month == 12 else 0)
        d = date(y, m, 1)
    return result


def _state_at(rows_sorted, ref_date):
    """Return attrs dict valid at ref_date, or None if server didn't exist."""
    for row in reversed(rows_sorted):
        if row['valid_from'] <= ref_date:
            if row['valid_to'] is None or row['valid_to'] > ref_date:
                return {f: row[f] for f in TRACKED_FIELDS}
    return None


def _build_after_zone_map(zone_end):
    """
    One query: for every (SERVER_ID, APP_NAME_VALUE), the earliest valid_from
    that falls at or after zone_end (i.e. in the daily zone).
    Returns {(sid, app): date}.
    """
    rows = (
        ServerHistory.objects
        .filter(valid_from__gte=zone_end)
        .values('SERVER_ID', 'APP_NAME_VALUE')
        .annotate(first_after=Min('valid_from'))
    )
    return {(r['SERVER_ID'], r['APP_NAME_VALUE']): r['first_after'] for r in rows}


def _load_pairs(zone_start, zone_end):
    """
    Load rows in and around [zone_start, zone_end), grouped by
    (SERVER_ID, APP_NAME_VALUE).  Includes:
      - rows starting before zone_start that extend into the zone
      - rows starting inside the zone
    """
    qs = (
        ServerHistory.objects
        .filter(
            Q(valid_from__lt=zone_start, valid_to__gt=zone_start)   # spanning into zone
            | Q(valid_from__gte=zone_start, valid_from__lt=zone_end)  # inside zone
        )
        .values(*_ROW_FIELDS)
        .order_by('SERVER_ID', 'APP_NAME_VALUE', 'valid_from')
    )

    pairs = defaultdict(list)
    for row in qs.iterator(chunk_size=5000):
        pairs[(row['SERVER_ID'], row['APP_NAME_VALUE'])].append(row)

    return {
        key: rows for key, rows in pairs.items()
        if any(zone_start <= r['valid_from'] < zone_end for r in rows)
    }


# ── Core compaction ───────────────────────────────────────────────────────────

def _compact_zone(pairs, zone_start, zone_end, ref_dates, after_zone_map,
                  dry_run, logger, records=None, zone_tag=''):
    """
    Compact all (SERVER_ID, APP_NAME_VALUE) pairs for a zone.
    If records list is provided, append one dict per pair for the HTML report.
    Returns (total_deleted, total_inserted).
    """
    n_del = n_ins = n_skip = 0

    for (sid, app), rows in pairs.items():
        rows_sorted = sorted(rows, key=lambda r: r['valid_from'])

        # If a single row spans the entire zone, state didn't change → skip
        if any(
            r['valid_from'] < zone_start and (r['valid_to'] is None or r['valid_to'] >= zone_end)
            for r in rows_sorted
        ):
            n_skip += 1
            if records is not None:
                records.append({'sid': sid, 'app': app or '', 's': 'skip', 'z': zone_tag})
            continue

        # Snapshots at each reference date (None = server didn't exist yet)
        snapshots = [(d, _state_at(rows_sorted, d)) for d in ref_dates]
        snapshots = [(d, s) for d, s in snapshots if s is not None]
        if not snapshots:
            n_skip += 1
            if records is not None:
                records.append({'sid': sid, 'app': app or '', 's': 'skip', 'z': zone_tag})
            continue

        # Collapse consecutive identical states
        groups = []
        for ref_date, attrs in snapshots:
            if groups and _attrs_hash(groups[-1]['attrs']) == _attrs_hash(attrs):
                pass  # same state — current group naturally extends to this date
            else:
                groups.append({'valid_from': ref_date, 'attrs': attrs, 'valid_to': None})

        # valid_to for each group except the last
        for i in range(len(groups) - 1):
            groups[i]['valid_to'] = groups[i + 1]['valid_from']

        # Last group valid_to: first row at or after zone_end (pre-fetched map)
        groups[-1]['valid_to'] = after_zone_map.get((sid, app))

        # Pre-zone row whose valid_to falls inside the zone (spanning_into)
        spanning_into = next(
            (r for r in rows_sorted
             if r['valid_from'] < zone_start
             and r['valid_to'] is not None
             and zone_start < r['valid_to'] <= zone_end),
            None,
        )
        if spanning_into:
            groups[0]['valid_from'] = zone_start

        # IDs to delete: closed rows completely inside the zone
        del_ids = [
            r['id'] for r in rows_sorted
            if zone_start <= r['valid_from'] < zone_end
            and r['valid_to'] is not None
            and r['valid_to'] <= zone_end
        ]
        # Open rows starting in zone: delete only if last compacted row is also open
        if groups[-1]['valid_to'] is None:
            del_ids += [
                r['id'] for r in rows_sorted
                if zone_start <= r['valid_from'] < zone_end and r['valid_to'] is None
            ]

        pair_del = len(del_ids)
        pair_ins = len(groups)

        # Collect for HTML report
        if records is not None:
            zone_bef = [r for r in rows_sorted if zone_start <= r['valid_from'] < zone_end]
            records.append({
                'sid': sid, 'app': app or '', 's': 'compact', 'z': zone_tag,
                'del': pair_del, 'ins': pair_ins,
                'B': [_row_rec(r) for r in zone_bef],
                'A': [_group_rec(g) for g in groups],
            })

        logger.debug('%s / %s  del=%d ins=%d', sid, app or '—', pair_del, pair_ins)

        if not dry_run:
            with transaction.atomic():
                if spanning_into:
                    ServerHistory.objects.filter(id=spanning_into['id']).update(valid_to=zone_start)
                if del_ids:
                    ServerHistory.objects.filter(id__in=del_ids).delete()
                ServerHistory.objects.bulk_create([
                    ServerHistory(
                        SERVER_ID=sid,
                        APP_NAME_VALUE=app,
                        valid_from=g['valid_from'],
                        valid_to=g['valid_to'],
                        **g['attrs'],
                    )
                    for g in groups
                ])

        n_del += pair_del
        n_ins += pair_ins

    logger.info(
        'zone [%s → %s)  pairs=%d  skipped=%d  deleted=%d  inserted=%d%s',
        zone_start, zone_end, len(pairs), n_skip, n_del, n_ins,
        '  [DRY RUN]' if dry_run else '',
    )
    return n_del, n_ins


# ── HTML report ───────────────────────────────────────────────────────────────

def _write_html_report(records, meta, path):
    data_json = json.dumps(records, separators=(',', ':'))
    meta_json = json.dumps(meta,    separators=(',', ':'))
    html = _REPORT_HTML.replace('__DATA__', data_json).replace('__META__', meta_json)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(html)


_REPORT_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>compact_server_history — report</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f2f8;color:#2d3436;padding:24px}
header{background:#fff;border-radius:10px;padding:20px 24px;margin-bottom:16px;box-shadow:0 1px 6px rgba(0,0,0,.07)}
h1{font-size:1.2rem;font-weight:700;margin-bottom:4px}
.meta{font-size:.8rem;color:#636e72;margin-bottom:14px}
.dry-badge{display:inline-block;background:#ffeaa7;color:#e17055;font-weight:700;font-size:.7rem;padding:2px 8px;border-radius:10px;margin-left:8px;vertical-align:middle}
.stats{display:flex;gap:14px;flex-wrap:wrap}
.stat{background:#f8f9ff;border-radius:6px;padding:10px 16px;min-width:90px;text-align:center}
.sv{display:block;font-size:1.3rem;font-weight:800}
.sl{font-size:.72rem;color:#636e72;margin-top:2px}
.red{color:#d63031}.green{color:#00b894}.blue{color:#0984e3}
.toolbar{background:#fff;border-radius:8px;padding:12px 16px;margin-bottom:12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;box-shadow:0 1px 4px rgba(0,0,0,.06)}
#search{padding:6px 10px;border:1px solid #dfe6e9;border-radius:5px;font-size:.85rem;width:280px}
#search:focus{outline:none;border-color:#0984e3}
.toolbar label{font-size:.83rem;color:#636e72;display:flex;align-items:center;gap:5px;cursor:pointer}
.toolbar select{padding:5px 8px;border:1px solid #dfe6e9;border-radius:5px;font-size:.82rem}
#count{margin-left:auto;font-size:.78rem;color:#636e72}
.table-wrap{background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.06);overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:.82rem}
thead{background:#f8f9ff}
th{padding:9px 10px;text-align:left;font-weight:700;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:#636e72;border-bottom:2px solid #e8eaf2;white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid #f0f2f8;vertical-align:middle}
tr.row-compact{cursor:pointer}
tr.row-compact:hover td{background:#f8f9ff}
tr.row-compact.open td{background:#e8f4ff}
tr.row-skip td{color:#b2bec3}
tr.detail-row td{padding:0;background:#f0f4ff}
.detail-inner{padding:16px 20px;overflow-x:auto}
.mono{font-family:'Cascadia Code','Consolas','Courier New',monospace;font-size:.78rem}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.7rem;font-weight:700}
.badge.compact{background:#d4eaff;color:#0984e3}
.badge.skip{background:#f0f2f8;color:#b2bec3}
.badge.W{background:#d4eaff;color:#0984e3}
.badge.M{background:#e8e0ff;color:#6c5ce7}
.num{text-align:right;font-variant-numeric:tabular-nums}
.mt{width:180px;height:16px;border-radius:3px;overflow:hidden;display:flex;gap:1px;cursor:default}
.mt-empty{color:#b2bec3;font-size:.78rem}
.detail-table{border-collapse:collapse;font-size:.78rem;margin-top:10px;width:100%}
.detail-table th{background:#e8eaf2;padding:5px 8px;font-weight:700;text-align:left;white-space:nowrap}
.detail-table td{padding:4px 8px;border-bottom:1px solid #e8eaf2;white-space:nowrap}
.detail-table td.changed{background:#fff3cd;font-weight:700}
.detail-table .open-val{color:#00b894;font-style:italic}
.sec-label{font-size:.7rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em;padding:10px 0 3px;color:#636e72}
#pagination{padding:14px 0;display:flex;gap:8px;align-items:center;justify-content:center;font-size:.83rem}
#pagination button{padding:5px 14px;border:1px solid #dfe6e9;border-radius:5px;background:#fff;cursor:pointer}
#pagination button:hover{background:#f0f2f8}
</style>
</head>
<body>
<header>
  <h1>compact_server_history — detailed report<span id="dry-badge"></span></h1>
  <div class="meta" id="meta-line"></div>
  <div class="stats" id="stats"></div>
</header>
<div class="toolbar">
  <input type="search" id="search" placeholder="Filter by SERVER_ID or APP…">
  <label><input type="checkbox" id="show-skips"> Include skips</label>
  <label>Zone: <select id="zone-filter"><option value="">All</option><option value="W">Weekly</option><option value="M">Monthly</option></select></label>
  <span id="count"></span>
</div>
<div class="table-wrap">
<table>
  <thead>
    <tr>
      <th>SERVER_ID</th><th>APP</th><th>Zone</th><th>Status</th>
      <th style="text-align:right">Del</th>
      <th style="text-align:right">Ins</th>
      <th style="text-align:right">Net</th>
      <th>Avant</th><th>Après</th>
    </tr>
  </thead>
  <tbody id="tbody"></tbody>
</table>
</div>
<div id="pagination"></div>

<script>
const DATA = __DATA__;
const META = __META__;

function hColor(h){
  if(!h) return '#b2bec3';
  const hue=parseInt(h.slice(0,4),16)%360;
  return `hsl(${hue},58%,52%)`;
}
function hColorLight(h){
  if(!h) return '#f0f2f8';
  const hue=parseInt(h.slice(0,4),16)%360;
  return `hsl(${hue},60%,93%)`;
}

function miniTimeline(rows){
  if(!rows||!rows.length) return '<span class="mt-empty">—</span>';
  const d0=new Date(META.zone_start), dE=new Date(META.zone_end);
  const tot=(dE-d0)/86400000;
  let s='';
  for(const r of rows){
    const from=new Date(r.f), to=r.t?new Date(r.t):dE;
    const days=Math.max(0.5,(to-from)/86400000);
    const tip=`${r.f} → ${r.t||'open'}\n${Object.entries(r.a).filter(([,v])=>v).map(([k,v])=>k+': '+v).join('\n')}`;
    s+=`<div style="flex:${days};background:${hColor(r.h)}" title="${tip.replace(/"/g,'&quot;')}"></div>`;
  }
  return `<div class="mt">${s}</div>`;
}

function buildDetail(r){
  const d0=new Date(META.zone_start), dE=new Date(META.zone_end);
  const tot=(dE-d0)/86400000;
  const W=820,TS=120,TW=W-TS-10,RH=26,RG=5;
  const F="-apple-system,'Segoe UI',sans-serif";

  function xOf(ds){
    const d=new Date(ds);
    return TS+Math.max(0,Math.min(1,(d-d0)/86400000/tot))*TW;
  }
  function xE(ds){return xOf(ds||META.zone_end);}

  function svgRows(rows,startY,op){
    let o='';
    rows.forEach((row,i)=>{
      const y=startY+i*(RH+RG);
      const x1=xOf(row.f),x2=xE(row.t),bw=Math.max(2,x2-x1-1);
      const c=hColor(row.h);
      const lbl=Object.values(row.a).filter(Boolean).slice(0,2).join(' / ');
      o+=`<rect x="${x1}" y="${y}" width="${bw}" height="${RH}" fill="${c}" rx="3" opacity="${op}"/>`;
      if(bw>50) o+=`<text x="${x1+bw/2}" y="${y+RH/2+4}" text-anchor="middle" font-size="9.5" fill="white" font-weight="600" font-family="${F}">${lbl}</text>`;
      o+=`<text x="${x1+2}" y="${y-3}" font-size="8" fill="#636e72" font-family="${F}">${row.f.slice(5)}</text>`;
      if(row.t) o+=`<text x="${x2-1}" y="${y-3}" text-anchor="end" font-size="8" fill="#636e72" font-family="${F}">${row.t.slice(5)}</text>`;
    });
    return o;
  }

  const bH=r.B.length*(RH+RG), aH=r.A.length*(RH+RG), SEP=34;
  const svgH=bH+SEP+aH+4;
  let svg=`<svg width="${W}" height="${svgH}" xmlns="http://www.w3.org/2000/svg" style="font-family:${F};display:block">`;
  svg+=`<rect x="${TS}" y="0" width="${TW}" height="${svgH}" fill="#f8f9ff" rx="3"/>`;
  svg+=`<text x="${TS-6}" y="${bH/2}" text-anchor="end" dominant-baseline="middle" font-size="11" font-weight="800" fill="#2d3436" font-family="${F}">BEFORE (${r.B.length})</text>`;
  svg+=svgRows(r.B,0,0.78);
  const sepY=bH+SEP/2;
  svg+=`<line x1="0" y1="${sepY}" x2="${W}" y2="${sepY}" stroke="#dfe6e9"/>`;
  svg+=`<text x="${W/2}" y="${sepY+1}" text-anchor="middle" dominant-baseline="middle" font-size="10" font-weight="700" fill="#0984e3" font-family="${F}">▼  compaction  ▼</text>`;
  const aTop=bH+SEP;
  svg+=`<text x="${TS-6}" y="${aTop+aH/2}" text-anchor="end" dominant-baseline="middle" font-size="11" font-weight="800" fill="#2d3436" font-family="${F}">AFTER (${r.A.length})</text>`;
  svg+=svgRows(r.A,aTop,1);
  svg+='</svg>';

  function tbl(rows){
    let h=`<table class="detail-table"><thead><tr><th>valid_from</th><th>valid_to</th>`;
    META.display_fields.forEach(f=>h+=`<th>${f}</th>`);
    h+='</tr></thead><tbody>';
    rows.forEach((row,i)=>{
      const prev=i>0?rows[i-1]:null;
      h+=`<tr style="background:${hColorLight(row.h)}">`;
      h+=`<td class="mono">${row.f}</td><td class="mono ${!row.t?'open-val':''}">${row.t||'open ∞'}</td>`;
      META.display_fields.forEach(f=>{
        const v=row.a[f]||'—', chg=prev&&prev.a[f]!==row.a[f];
        h+=`<td${chg?' class="changed"':''}>${v}</td>`;
      });
      h+='</tr>';
    });
    return h+'</tbody></table>';
  }

  return `<div class="detail-inner">${svg}
    <div class="sec-label">Before — ${r.B.length} rows (in zone)</div>${tbl(r.B)}
    <div class="sec-label">After — ${r.A.length} compacted rows</div>${tbl(r.A)}
  </div>`;
}

// ── State ─────────────────────────────────────────────────────────────────────
let filtered=[], page=0;
const PG=50;

function filter(){
  const q=document.getElementById('search').value.toLowerCase().trim();
  const skips=document.getElementById('show-skips').checked;
  const zone=document.getElementById('zone-filter').value;
  filtered=DATA.filter(r=>{
    if(!skips&&r.s==='skip') return false;
    if(zone&&r.z!==zone) return false;
    if(q) return r.sid.toLowerCase().includes(q)||r.app.toLowerCase().includes(q);
    return true;
  });
  page=0; render();
}

function render(){
  const start=page*PG, slice=filtered.slice(start,start+PG);
  document.getElementById('tbody').innerHTML=slice.map((r,i)=>{
    const gi=start+i;
    const zb=r.z?`<span class="badge ${r.z}">${r.z==='W'?'weekly':'monthly'}</span>`:'';
    if(r.s==='skip'){
      return `<tr class="row-skip"><td class="mono">${r.sid}</td><td class="mono">${r.app||'—'}</td><td>${zb}</td><td><span class="badge skip">skip</span></td><td colspan="5" style="color:#b2bec3;font-size:.78rem">constant state — nothing to compact</td></tr>`;
    }
    const net=r.ins-r.del, nc=net<0?'red':net>0?'green':'';
    return `<tr class="row-compact" onclick="toggle(this,${gi})">
      <td class="mono">${r.sid}</td><td class="mono">${r.app||'—'}</td><td>${zb}</td>
      <td><span class="badge compact">compact</span></td>
      <td class="num red">${r.del}</td><td class="num green">${r.ins}</td>
      <td class="num ${nc}">${net>0?'+':''}${net}</td>
      <td>${miniTimeline(r.B)}</td><td>${miniTimeline(r.A)}</td>
    </tr>
    <tr class="detail-row" id="dr-${gi}" style="display:none"><td colspan="9"></td></tr>`;
  }).join('');

  const comp=filtered.filter(r=>r.s==='compact');
  const tDel=comp.reduce((s,r)=>s+r.del,0), tIns=comp.reduce((s,r)=>s+r.ins,0);
  document.getElementById('count').textContent=
    `${filtered.length.toLocaleString()} pairs · ${comp.length.toLocaleString()} compacted · ${tDel.toLocaleString()} del / ${tIns.toLocaleString()} ins`;
  renderPag();
}

function toggle(tr,gi){
  const dr=document.getElementById('dr-'+gi); if(!dr) return;
  const open=dr.style.display!=='none';
  if(!open&&!dr.querySelector('.detail-inner')){
    const rec=filtered[gi];
    dr.querySelector('td').innerHTML=rec.s==='compact'?buildDetail(rec):'<div style="padding:10px;color:#b2bec3">skipped — no detail</div>';
  }
  dr.style.display=open?'none':''; tr.classList.toggle('open',!open);
}

function renderPag(){
  const tot=Math.ceil(filtered.length/PG), pag=document.getElementById('pagination');
  if(tot<=1){pag.innerHTML='';return;}
  let h='';
  if(page>0) h+=`<button onclick="goPage(${page-1})">← Prev.</button>`;
  h+=`<span>Page ${page+1} / ${tot} &nbsp;(${filtered.length.toLocaleString()} pairs)</span>`;
  if(page<tot-1) h+=`<button onclick="goPage(${page+1})">Next →</button>`;
  pag.innerHTML=h;
}
function goPage(p){page=p;render();window.scrollTo(0,0);}

// ── Header ────────────────────────────────────────────────────────────────────
if(META.dry_run) document.getElementById('dry-badge').innerHTML='<span class="dry-badge">DRY RUN</span>';
document.getElementById('meta-line').textContent=
  `Zone ${META.zone} · [${META.zone_start} → ${META.zone_end}] · Generated ${META.generated}`;

const aC=DATA.filter(r=>r.s==='compact');
const aS=DATA.filter(r=>r.s==='skip').length;
const aD=aC.reduce((s,r)=>s+r.del,0), aI=aC.reduce((s,r)=>s+r.ins,0), aN=aI-aD;
document.getElementById('stats').innerHTML=`
  <div class="stat"><span class="sv">${DATA.length.toLocaleString()}</span><span class="sl">total pairs</span></div>
  <div class="stat"><span class="sv blue">${aC.length.toLocaleString()}</span><span class="sl">compacted</span></div>
  <div class="stat"><span class="sv">${aS.toLocaleString()}</span><span class="sl">skipped</span></div>
  <div class="stat"><span class="sv red">${aD.toLocaleString()}</span><span class="sl">rows deleted</span></div>
  <div class="stat"><span class="sv green">${aI.toLocaleString()}</span><span class="sl">rows inserted</span></div>
  <div class="stat"><span class="sv ${aN<0?'red':aN>0?'green':''}">${aN>0?'+':''}${aN.toLocaleString()}</span><span class="sl">net</span></div>`;

document.getElementById('search').addEventListener('input',filter);
document.getElementById('show-skips').addEventListener('change',filter);
document.getElementById('zone-filter').addEventListener('change',filter);
filter();
</script>
</body>
</html>"""


# ── Management command ────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = 'Compact ServerHistory: reduce row density in weekly and monthly zones.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would change without writing to the database.',
        )
        parser.add_argument(
            '--zone', choices=['weekly', 'monthly', 'all'], default='all',
            help='Which zone to compact (default: all).',
        )
        parser.add_argument(
            '--report', metavar='PATH',
            help='Générer un rapport HTML détaillé (debug) à ce chemin.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        zone    = options['zone']
        today   = date.today()

        daily_cutoff  = today - timedelta(days=DAILY_KEEP)
        weekly_cutoff = today - timedelta(days=WEEKLY_KEEP)

        records = [] if options.get('report') else None

        if zone in ('weekly', 'all'):
            self._compact_weekly(daily_cutoff, weekly_cutoff, dry_run, records)

        if zone in ('monthly', 'all'):
            self._compact_monthly(weekly_cutoff, dry_run, records)

        if records is not None and options.get('report'):
            oldest = (
                ServerHistory.objects
                .order_by('valid_from')
                .values_list('valid_from', flat=True)
                .first()
            )
            meta = {
                'zone':           zone.upper(),
                'zone_start':     str(oldest or weekly_cutoff),
                'zone_end':       str(daily_cutoff),
                'generated':      str(today),
                'dry_run':        dry_run,
                'display_fields': DISPLAY_FIELDS,
            }
            _write_html_report(records, meta, options['report'])
            self.stdout.write(f'Report written: {options["report"]}')

    # ── Weekly ────────────────────────────────────────────────────────────────

    def _compact_weekly(self, zone_end, zone_start, dry_run, records):
        ref_dates = _sundays_between(zone_start, zone_end)
        logger_w.info(
            'Starting — zone [%s → %s)  Sundays=%d  dry_run=%s',
            zone_start, zone_end, len(ref_dates), dry_run,
        )
        self.stdout.write(f'Weekly [{zone_start} → {zone_end})  {len(ref_dates)} Sundays')

        if not ref_dates:
            logger_w.info('No Sundays in zone — nothing to do.')
            return

        pairs = _load_pairs(zone_start, zone_end)
        after_zone_map = _build_after_zone_map(zone_end)
        logger_w.info('Pairs to process: %d', len(pairs))
        self.stdout.write(f'  {len(pairs):,} pairs')

        n_del, n_ins = _compact_zone(
            pairs, zone_start, zone_end, ref_dates, after_zone_map,
            dry_run, logger_w, records=records, zone_tag='W',
        )

        msg = f'Weekly done — deleted {n_del:,}, inserted {n_ins:,}'
        if dry_run:
            msg += '  [DRY RUN]'
            self.stdout.write(self.style.WARNING(msg))
        else:
            self.stdout.write(self.style.SUCCESS(msg))

    # ── Monthly ───────────────────────────────────────────────────────────────

    def _compact_monthly(self, zone_end, dry_run, records):
        oldest = (
            ServerHistory.objects
            .order_by('valid_from')
            .values_list('valid_from', flat=True)
            .first()
        )
        if not oldest:
            logger_m.info('No ServerHistory data — skipping.')
            return

        zone_start = oldest
        ref_dates  = _firsts_between(zone_start, zone_end)
        logger_m.info(
            'Starting — zone [%s → %s)  1sts=%d  dry_run=%s',
            zone_start, zone_end, len(ref_dates), dry_run,
        )
        self.stdout.write(f'Monthly [{zone_start} → {zone_end})  {len(ref_dates)} 1sts')

        if not ref_dates:
            logger_m.info('No 1sts-of-month in zone — nothing to do.')
            return

        pairs = _load_pairs(zone_start, zone_end)
        after_zone_map = _build_after_zone_map(zone_end)
        logger_m.info('Pairs to process: %d', len(pairs))
        self.stdout.write(f'  {len(pairs):,} pairs')

        n_del, n_ins = _compact_zone(
            pairs, zone_start, zone_end, ref_dates, after_zone_map,
            dry_run, logger_m, records=records, zone_tag='M',
        )

        msg = f'Monthly done — deleted {n_del:,}, inserted {n_ins:,}'
        if dry_run:
            msg += '  [DRY RUN]'
            self.stdout.write(self.style.WARNING(msg))
        else:
            self.stdout.write(self.style.SUCCESS(msg))
