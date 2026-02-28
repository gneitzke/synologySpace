#!/usr/bin/env python3
"""
Synology Space Analyzer — Report Generator

Reads JSON output from each analysis module (in /tmp/synology-space-report/)
and produces:
  - A color-formatted terminal summary with reclaimable-space bar chart
  - An HTML report (report.html)
  - A treemap visualization (treemap.html, via treemap.py)
  - A machine-readable summary (summary.json)

Usage:
    python3 report.py           # after running analyze.sh

Requires: Python 3.9+, analysis data from analyze.sh
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPORT_DIR = Path("/tmp/synology-space-report")
SCRIPT_DIR = Path(__file__).parent


def human_readable(size_bytes: int) -> str:
    """Convert bytes to human-readable format."""
    if size_bytes >= 1099511627776:
        return f"{size_bytes / 1099511627776:.1f} TB"
    if size_bytes >= 1073741824:
        return f"{size_bytes / 1073741824:.1f} GB"
    if size_bytes >= 1048576:
        return f"{size_bytes / 1048576:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def load_module_json(module: str) -> dict | None:
    """Load JSON output from a module."""
    path = REPORT_DIR / f"{module}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def print_header(title: str):
    print()
    print(f"\033[1;36m{'═' * 60}\033[0m")
    print(f"\033[1;36m  {title}\033[0m")
    print(f"\033[1;36m{'═' * 60}\033[0m")
    print()


def print_section(title: str):
    print(f"\033[1;33m--- {title} ---\033[0m")


def report_large_files(data):
    """Report on large files."""
    if not data or not isinstance(data, list):
        return 0
    print_section("Large Files")
    total = 0
    for i, f in enumerate(data[:20], 1):
        size = f.get("size", 0)
        total += size
        print(f"  {i:3d}. {f.get('human_size', '?'):>10s}  {f.get('modified', ''):20s}  {f.get('path', '?')}")
    print(f"\n  Top 20 files total: \033[1m{human_readable(total)}\033[0m")
    print()
    return total


def report_large_dirs(data):
    """Report on large directories."""
    if not data or not isinstance(data, list):
        return 0
    print_section("Large Directories")
    for i, d in enumerate(data[:15], 1):
        print(f"  {i:3d}. {d.get('human_size', '?'):>10s}  {d.get('path', '?')}")
    print()
    return 0


def report_duplicates(data):
    """Report on duplicate files."""
    if not data or not isinstance(data, dict):
        return 0
    groups = data.get("groups", [])
    wasted = data.get("total_wasted_bytes", 0)
    print_section("Duplicate Files")
    if not groups:
        print("  No duplicates found.")
        print()
        return 0
    print(f"  Found \033[1m{len(groups)}\033[0m duplicate groups")
    print(f"  Total wasted space: \033[1;31m{human_readable(wasted)}\033[0m")
    print()
    for i, group in enumerate(groups[:10], 1):
        print(f"  Group {i}: {human_readable(group.get('size', 0))} × {group.get('count', 0)} copies "
              f"(wasted: {human_readable(group.get('wasted', 0))})")
        for fp in group.get("files", [])[:5]:
            print(f"    - {fp}")
        if len(group.get("files", [])) > 5:
            print(f"    ... and {len(group['files']) - 5} more")
    print()
    return wasted


def report_snapshots(data):
    """Report on Btrfs snapshots."""
    if not data:
        return 0
    if not data.get("available", False):
        print_section("Btrfs Snapshots")
        print("  Btrfs not available or not accessible.")
        print()
        return 0
    total = data.get("total", 0)
    old = data.get("old_count", 0)
    print_section(f"Btrfs Snapshots ({total} total, {old} old)")
    old_size = 0
    for snap in data.get("snapshots", []):
        if snap.get("is_old"):
            old_size += snap.get("exclusive_bytes", 0)
            marker = "\033[31m[OLD]\033[0m "
        else:
            marker = "      "
        print(f"  {marker}ID: {snap.get('id', '?'):6s}  "
              f"Date: {snap.get('date', 'unknown'):20s}  "
              f"Path: {snap.get('path', '?')}")
    if old > 0:
        print(f"\n  Reclaimable from old snapshots: \033[1;31m{human_readable(old_size)}\033[0m")
    print()
    return old_size


def report_docker(data):
    """Report on Docker usage."""
    if not data or not data.get("available", False):
        print_section("Docker")
        print("  Docker not available.")
        print()
        return 0
    print_section("Docker")
    print(f"  Dangling images:    {data.get('dangling_images', 0)}")
    print(f"  Stopped containers: {data.get('stopped_containers', 0)}")
    print(f"  Unused volumes:     {data.get('unused_volumes', 0)}")
    print()
    return 0


def report_recycle_bins(data):
    """Report on recycle bins."""
    if not data:
        return 0
    total = data.get("total_size_bytes", 0)
    total_files = data.get("total_files", 0)
    print_section(f"Recycle Bins ({total_files} files)")
    for b in data.get("bins", []):
        print(f"  {b.get('share', '?'):<30s}  {b.get('human_size', '?'):>10s}  ({b.get('file_count', 0)} files)")
    if total > 0:
        print(f"\n  Total reclaimable: \033[1;31m{human_readable(total)}\033[0m")
    else:
        print("  Recycle bins are empty.")
    print()
    return total


def report_logs(data):
    """Report on log files."""
    if not data:
        return 0
    total = data.get("total_size_bytes", 0)
    count = data.get("oversized_count", 0)
    print_section(f"Log Files ({count} oversized)")
    for log in data.get("logs", [])[:15]:
        safe = "\033[32m[SAFE]\033[0m " if log.get("safe_to_clean") else "       "
        print(f"  {safe}{log.get('human_size', '?'):>10s}  {log.get('path', '?')}")
    if total > 0:
        print(f"\n  Total oversized logs: \033[1;31m{human_readable(total)}\033[0m")
    else:
        print("  No oversized log files.")
    print()
    return total


def generate_html_report(summary: dict):
    """Generate a multi-tab HTML dashboard with treemap, file table, and reclaimable space."""
    html_path = REPORT_DIR / "report.html"

    # Load all module data for the dashboard
    large_files = load_module_json("large_files") or []
    large_dirs = load_module_json("large_dirs") or []
    duplicates = load_module_json("duplicates") or {}
    recycle = load_module_json("recycle_bins") or {}
    logs = load_module_json("logs") or {}
    docker = load_module_json("docker") or {}
    snapshots = load_module_json("snapshots") or {}

    # Build treemap categories from large_dirs (top-level volume children)
    treemap_data = _build_treemap_data(large_dirs)
    treemap_json = json.dumps(treemap_data)

    # Build files list
    files_json = json.dumps(large_files[:50] if isinstance(large_files, list) else [])

    # Build large dirs list
    dirs_json = json.dumps(large_dirs[:30] if isinstance(large_dirs, list) else [])

    # Build reclaimable summary
    categories = summary.get("categories", {})
    total_reclaimable = summary.get("total_reclaimable", 0)

    # Category color assignments
    cat_colors = {
        "Duplicate Files": "#e94560",
        "Large Files (top 20)": "#e67e22",
        "Old Snapshots": "#9b59b6",
        "Recycle Bins": "#2ecc71",
        "Log Files": "#3498db",
    }

    reclaim_cards_json = json.dumps([
        {"name": cat, "size": human_readable(size), "color": cat_colors.get(cat, "#636e72")}
        for cat, size in sorted(categories.items(), key=lambda x: x[1], reverse=True) if size > 0
    ])

    # Duplicate groups for reclaimable detail
    dup_groups = duplicates.get("groups", []) if isinstance(duplicates, dict) else []
    dup_detail = []
    for g in dup_groups[:20]:
        files = g.get("files", [])
        if len(files) > 1:
            dup_detail.append({
                "size": human_readable(g.get("wasted", 0)),
                "what": f"{g.get('count', 0)} copies of {human_readable(g.get('size', 0))} file",
                "where": files[0] if files else "",
                "why": "Duplicate — keep one, delete the rest"
            })

    # Recycle bin items
    recycle_items = []
    for b in recycle.get("bins", []):
        if b.get("size_bytes", 0) > 0:
            recycle_items.append({
                "size": b.get("human_size", "?"),
                "what": f"Recycle bin ({b.get('file_count', 0)} files)",
                "where": b.get("share", ""),
                "why": "Emptying recycle bin is safe"
            })

    # Log items
    log_items = []
    for log in logs.get("logs", [])[:10]:
        if log.get("safe_to_clean", False):
            log_items.append({
                "size": log.get("human_size", "?"),
                "what": "Oversized log file",
                "where": log.get("path", ""),
                "why": "Safe to truncate or rotate"
            })

    all_reclaim = dup_detail + recycle_items + log_items
    reclaim_items_json = json.dumps(all_reclaim)

    html = _DASHBOARD_TEMPLATE.format(
        total_used=treemap_data.get("human_size", "?"),
        total_reclaimable=human_readable(total_reclaimable),
        treemap_json=treemap_json,
        files_json=files_json,
        dirs_json=dirs_json,
        reclaim_cards_json=reclaim_cards_json,
        reclaim_items_json=reclaim_items_json,
    )

    with open(html_path, "w") as f:
        f.write(html)
    print(f"  HTML dashboard: {html_path}")


def _build_treemap_data(large_dirs: list) -> dict:
    """Build a treemap hierarchy from large_dirs data."""
    if not large_dirs or not isinstance(large_dirs, list):
        return {"name": "NAS", "size": 0, "human_size": "0 B", "children": []}

    # Find the root volume
    root = large_dirs[0] if large_dirs else {}
    root_path = root.get("path", "/volume1")
    root_size = root.get("size_kb", root.get("size", 0))

    # Find direct children of root (one level below root_path)
    children = []
    for d in large_dirs[1:]:
        path = d.get("path", "")
        # Direct child: exactly one path component after root
        rel = path[len(root_path):]
        if rel.startswith("/"):
            rel = rel[1:]
        if "/" not in rel and rel:
            children.append({
                "name": _friendly_name(rel),
                "size": d.get("size_kb", d.get("size", 0)),
                "human_size": d.get("human_size", "?"),
            })

    return {
        "name": root_path.split("/")[-1] or "NAS",
        "size": root_size,
        "human_size": root.get("human_size", "?"),
        "children": children,
    }


def _friendly_name(dirname: str) -> str:
    """Convert internal directory names to friendly labels."""
    names = {
        "@synologydrive": "Synology Drive",
        "surveillance": "Surveillance",
        "photo": "Photos",
        "homes": "User Homes",
        "downloads": "Downloads",
        "iCloudBackup": "iCloud Backup",
        "Time Machine": "Time Machine",
        "docker": "Docker",
        "music": "Music",
        "video": "Video",
        "web": "Web Station",
    }
    return names.get(dirname, dirname)


_DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Synology NAS — Space Analysis</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0f0f1a; color:#e0e0e0; }}

.header {{ background:linear-gradient(135deg,#1a1a2e,#16213e); padding:24px 32px; border-bottom:2px solid #e94560; display:flex; justify-content:space-between; align-items:center; }}
.header h1 {{ font-size:22px; color:#fff; }}
.header h1 span {{ color:#e94560; }}
.header .stats {{ display:flex; gap:32px; }}
.header .stat {{ text-align:right; }}
.header .stat .big {{ font-size:28px; font-weight:bold; color:#e94560; }}
.header .stat .big.green {{ color:#2ecc71; }}
.header .stat .label {{ font-size:12px; color:#888; }}

.tabs {{ display:flex; background:#16213e; border-bottom:1px solid #0f3460; }}
.tab {{ padding:12px 24px; cursor:pointer; color:#888; font-size:14px; font-weight:600; border-bottom:3px solid transparent; transition:all 0.2s; }}
.tab:hover {{ color:#ccc; }}
.tab.active {{ color:#e94560; border-bottom-color:#e94560; }}

.content {{ padding:24px 32px; }}

.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; margin-bottom:32px; }}
.card {{ background:#16213e; border-radius:10px; padding:20px; border:1px solid #0f3460; position:relative; overflow:hidden; }}
.card .bar {{ position:absolute; bottom:0; left:0; height:4px; border-radius:0 2px 0 10px; }}
.card .name {{ font-size:13px; color:#888; margin-bottom:4px; }}
.card .size {{ font-size:24px; font-weight:bold; }}
.card .pct {{ font-size:12px; color:#888; margin-top:4px; }}

#treemap-wrap {{ background:#16213e; border-radius:10px; border:1px solid #0f3460; overflow:hidden; margin-bottom:32px; }}
#treemap-header {{ padding:16px 20px; border-bottom:1px solid #0f3460; display:flex; justify-content:space-between; align-items:center; }}
#treemap-header h2 {{ font-size:16px; color:#fff; }}
#treemap {{ width:100%; height:420px; position:relative; }}
.tm-node {{ position:absolute; overflow:hidden; cursor:pointer; transition:opacity 0.15s; display:flex; flex-direction:column; justify-content:center; align-items:center; }}
.tm-node:hover {{ opacity:0.8; z-index:10; }}
.tm-label {{ font-size:12px; color:#fff; text-shadow:0 1px 3px rgba(0,0,0,0.8); text-align:center; pointer-events:none; padding:4px; }}
.tm-label .sz {{ font-size:11px; opacity:0.8; }}

.table-wrap {{ background:#16213e; border-radius:10px; border:1px solid #0f3460; overflow:hidden; margin-bottom:32px; }}
.table-wrap h2 {{ padding:16px 20px; font-size:16px; color:#fff; border-bottom:1px solid #0f3460; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; padding:10px 16px; font-size:12px; color:#888; text-transform:uppercase; letter-spacing:0.5px; border-bottom:1px solid #0f3460; }}
td {{ padding:10px 16px; font-size:13px; border-bottom:1px solid rgba(15,52,96,0.5); }}
td.sz {{ font-weight:600; color:#e94560; white-space:nowrap; text-align:right; }}
td.path {{ color:#aaa; word-break:break-all; max-width:600px; }}
td.date {{ color:#666; white-space:nowrap; }}
tr:hover {{ background:rgba(233,69,96,0.05); }}

.tooltip {{ position:fixed; background:#1a1a2e; border:1px solid #e94560; border-radius:8px; padding:14px 18px; font-size:13px; pointer-events:none; z-index:1000; display:none; max-width:350px; box-shadow:0 8px 32px rgba(0,0,0,0.6); }}
.tooltip .tt-name {{ font-weight:bold; color:#fff; font-size:14px; }}
.tooltip .tt-size {{ color:#e94560; font-size:18px; font-weight:bold; margin:4px 0; }}
.tooltip .tt-pct {{ color:#888; font-size:12px; }}

.panel {{ display:none; }}
.panel.active {{ display:block; }}

.bar-chart {{ margin:16px 0; }}
.bar-row {{ display:flex; align-items:center; margin:6px 0; }}
.bar-name {{ width:180px; font-size:13px; color:#ccc; text-align:right; padding-right:12px; }}
.bar-track {{ flex:1; height:28px; background:#0f0f1a; border-radius:4px; overflow:hidden; position:relative; }}
.bar-fill {{ height:100%; border-radius:4px; display:flex; align-items:center; padding:0 10px; font-size:12px; color:#fff; font-weight:600; min-width:fit-content; white-space:nowrap; }}
.bar-value {{ width:90px; font-size:13px; color:#888; padding-left:12px; text-align:right; }}

.empty-state {{ text-align:center; padding:60px 20px; color:#666; }}
.empty-state h3 {{ color:#888; margin-bottom:8px; }}
</style>
</head>
<body>

<div class="header">
    <h1>📊 Synology NAS — <span>Space Analysis</span></h1>
    <div class="stats">
        <div class="stat">
            <div class="big green">{total_reclaimable}</div>
            <div class="label">Reclaimable</div>
        </div>
        <div class="stat">
            <div class="big">{total_used}</div>
            <div class="label">Total Used</div>
        </div>
    </div>
</div>

<div class="tabs">
    <div class="tab active" onclick="showPanel('overview')">Overview</div>
    <div class="tab" onclick="showPanel('treemap')">Treemap</div>
    <div class="tab" onclick="showPanel('files')">Largest Files</div>
    <div class="tab" onclick="showPanel('reclaimable')">Reclaimable Space</div>
</div>

<div class="content">

<div class="panel active" id="panel-overview">
<div class="cards" id="cards"></div>
<div class="table-wrap">
<h2>Storage Breakdown</h2>
<div class="bar-chart" id="bar-chart"></div>
</div>
</div>

<div class="panel" id="panel-treemap">
<div id="treemap-wrap">
    <div id="treemap-header"><h2>Disk Usage Treemap</h2></div>
    <div id="treemap"></div>
</div>
</div>

<div class="panel" id="panel-files">
<div class="table-wrap">
    <h2>Largest Files</h2>
    <table id="file-table">
        <thead><tr><th>Size</th><th>File Path</th><th>Modified</th></tr></thead>
        <tbody id="file-tbody"></tbody>
    </table>
</div>
</div>

<div class="panel" id="panel-reclaimable">
<div class="cards" id="reclaim-cards"></div>
<div class="table-wrap">
    <h2>Reclaimable Items</h2>
    <table>
        <thead><tr><th>Size</th><th>What</th><th>Where</th><th>Why</th></tr></thead>
        <tbody id="reclaim-tbody"></tbody>
    </table>
</div>
</div>

</div>

<div class="tooltip" id="tooltip">
    <div class="tt-name"></div>
    <div class="tt-size"></div>
    <div class="tt-pct"></div>
</div>

<script>
const TREEMAP = {treemap_json};
const FILES = {files_json};
const RECLAIM_CARDS = {reclaim_cards_json};
const RECLAIM_ITEMS = {reclaim_items_json};
const TOTAL = TREEMAP.size || 1;

const AUTO_COLORS = ['#e74c3c','#e67e22','#3498db','#2ecc71','#9b59b6','#1abc9c','#f39c12','#e94560','#636e72','#d35400','#27ae60','#2980b9'];
const COLORS = {{}};
(TREEMAP.children || []).sort((a,b)=>b.size-a.size).forEach((c,i) => {{ COLORS[c.name] = AUTO_COLORS[i % AUTO_COLORS.length]; }});

function humanSize(kb) {{
    const b = kb * 1024;
    if (b >= 1e12) return (b/1e12).toFixed(1) + ' TB';
    if (b >= 1e9) return (b/1e9).toFixed(1) + ' GB';
    if (b >= 1e6) return (b/1e6).toFixed(1) + ' MB';
    return (b/1e3).toFixed(1) + ' KB';
}}

function pct(part, whole) {{ return ((part / whole) * 100).toFixed(1); }}

function showPanel(name) {{
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('panel-' + name).classList.add('active');
    event.target.classList.add('active');
    if (name === 'treemap') renderTreemap();
}}

function renderCards() {{
    const el = document.getElementById('cards');
    const cats = (TREEMAP.children || []).sort((a,b) => b.size - a.size);
    if (!cats.length) {{ el.innerHTML = '<div class="empty-state"><h3>No directory data</h3><p>Run analysis with sudo for full results</p></div>'; return; }}
    let html = '';
    cats.forEach(c => {{
        const p = pct(c.size, TOTAL);
        const color = COLORS[c.name] || '#636e72';
        html += '<div class="card"><div class="bar" style="width:' + p + '%;background:' + color + '"></div>' +
            '<div class="name">' + c.name + '</div><div class="size" style="color:' + color + '">' + c.human_size + '</div>' +
            '<div class="pct">' + p + '% of total</div></div>';
    }});
    el.innerHTML = html;
}}

function renderBarChart() {{
    const el = document.getElementById('bar-chart');
    const cats = (TREEMAP.children || []).sort((a,b) => b.size - a.size);
    if (!cats.length) return;
    const maxSize = cats[0].size;
    let html = '';
    cats.forEach(c => {{
        const p = pct(c.size, TOTAL);
        const barW = (c.size / maxSize * 100).toFixed(1);
        const color = COLORS[c.name] || '#636e72';
        html += '<div class="bar-row"><div class="bar-name">' + c.name + '</div>' +
            '<div class="bar-track"><div class="bar-fill" style="width:' + barW + '%;background:' + color + '">' + p + '%</div></div>' +
            '<div class="bar-value">' + c.human_size + '</div></div>';
    }});
    el.innerHTML = html;
}}

function squarify(items, x, y, w, h) {{
    if (!items.length) return [];
    const rects = [];
    const totalSize = items.reduce((s,i) => s + i.size, 0);
    if (totalSize <= 0) return [];
    let rem = [...items], cx=x, cy=y, cw=w, ch=h;
    while (rem.length > 0) {{
        const isWide = cw >= ch;
        const sideLen = isWide ? ch : cw;
        const remaining = rem.reduce((s,i) => s + i.size, 0);
        let row = [rem[0]], rowSize = rem[0].size;
        rem = rem.slice(1);
        function worst(row, rs, sl) {{
            const rl = (rs/remaining)*(isWide?cw:ch);
            if (rl<=0) return Infinity;
            let w=0;
            for (const it of row) {{ const ia=(it.size/remaining)*sl*(isWide?cw:ch); const il=ia/rl; w=Math.max(w,Math.max(rl/il,il/rl)); }}
            return w;
        }}
        while (rem.length > 0) {{
            const nr=[...row,rem[0]], ns=rowSize+rem[0].size;
            if (worst(nr,ns,sideLen)<=worst(row,rowSize,sideLen)) {{ row=nr; rowSize=ns; rem=rem.slice(1); }}
            else break;
        }}
        const rt = (rowSize/remaining)*(isWide?cw:ch);
        let off=0;
        for (const it of row) {{
            const il = sideLen*(it.size/rowSize);
            if (isWide) rects.push({{item:it,x:cx,y:cy+off,w:rt,h:il}});
            else rects.push({{item:it,x:cx+off,y:cy,w:il,h:rt}});
            off += il;
        }}
        if (isWide) {{ cx+=rt; cw-=rt; }} else {{ cy+=rt; ch-=rt; }}
    }}
    return rects;
}}

function renderTreemap() {{
    const container = document.getElementById('treemap');
    container.innerHTML = '';
    const W = container.clientWidth, H = container.clientHeight;
    const sorted = [...(TREEMAP.children||[])].sort((a,b)=>b.size-a.size);
    if (!sorted.length) {{ container.innerHTML = '<div class="empty-state"><h3>No data for treemap</h3></div>'; return; }}
    const rects = squarify(sorted, 0, 0, W, H);
    rects.forEach(r => {{
        if (r.w < 2 || r.h < 2) return;
        const div = document.createElement('div');
        div.className = 'tm-node';
        div.style.cssText = 'left:'+r.x+'px;top:'+r.y+'px;width:'+r.w+'px;height:'+r.h+'px;background:'+(COLORS[r.item.name]||'#636e72')+';border:2px solid rgba(0,0,0,0.3);';
        if (r.w > 60 && r.h > 36) {{
            div.innerHTML = '<div class="tm-label">' + r.item.name + '<br><span class="sz">' + r.item.human_size + '</span></div>';
        }}
        div.addEventListener('mousemove', e => showTip(e, r.item));
        div.addEventListener('mouseleave', hideTip);
        container.appendChild(div);
    }});
}}

function showTip(e, item) {{
    const tt = document.getElementById('tooltip');
    tt.style.display='block';
    tt.querySelector('.tt-name').textContent = item.name;
    tt.querySelector('.tt-size').textContent = item.human_size;
    tt.querySelector('.tt-pct').textContent = pct(item.size, TOTAL) + '% of total storage';
    let tx=e.clientX+15, ty=e.clientY+15;
    if (tx+300>window.innerWidth) tx=e.clientX-310;
    if (ty+80>window.innerHeight) ty=e.clientY-90;
    tt.style.left=tx+'px'; tt.style.top=ty+'px';
}}
function hideTip() {{ document.getElementById('tooltip').style.display='none'; }}

function renderFiles() {{
    const tbody = document.getElementById('file-tbody');
    if (!FILES.length) {{ tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:#666;padding:40px">No large files data</td></tr>'; return; }}
    let html = '';
    FILES.forEach(f => {{
        html += '<tr><td class="sz">' + (f.human_size||'?') + '</td>' +
            '<td class="path">' + (f.path||'?') + '</td>' +
            '<td class="date">' + (f.modified||'') + '</td></tr>';
    }});
    tbody.innerHTML = html;
}}

function renderReclaimable() {{
    const tbody = document.getElementById('reclaim-tbody');
    const cards = document.getElementById('reclaim-cards');

    if (RECLAIM_ITEMS.length) {{
        let html = '';
        RECLAIM_ITEMS.forEach(i => {{
            html += '<tr><td class="sz">' + i.size + '</td><td>' + i.what + '</td><td class="path">' + i.where + '</td><td>' + i.why + '</td></tr>';
        }});
        tbody.innerHTML = html;
    }} else {{
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#666;padding:40px">No reclaimable items found</td></tr>';
    }}

    if (RECLAIM_CARDS.length) {{
        let chtml = '';
        RECLAIM_CARDS.forEach(c => {{
            chtml += '<div class="card"><div class="bar" style="width:100%;background:' + c.color + '"></div>' +
                '<div class="name">' + c.name + '</div><div class="size" style="color:' + c.color + '">' + c.size + '</div></div>';
        }});
        cards.innerHTML = chtml;
    }}
}}

renderCards();
renderBarChart();
renderFiles();
renderReclaimable();
window.addEventListener('resize', () => {{ if (document.getElementById('panel-treemap').classList.contains('active')) renderTreemap(); }});
</script>
</body>
</html>"""


def main():
    if not REPORT_DIR.exists():
        print(f"Error: Report directory not found: {REPORT_DIR}")
        print("Run analyze.sh first to generate analysis data.")
        sys.exit(1)

    print_header("Synology Space Analysis Report")

    categories = {}

    # Load and report each module
    large_files_data = load_module_json("large_files")
    categories["Large Files (top 20)"] = report_large_files(large_files_data)

    report_large_dirs(load_module_json("large_dirs"))

    categories["Duplicate Files"] = report_duplicates(load_module_json("duplicates"))
    categories["Old Snapshots"] = report_snapshots(load_module_json("snapshots"))
    report_docker(load_module_json("docker"))
    categories["Recycle Bins"] = report_recycle_bins(load_module_json("recycle_bins"))
    categories["Log Files"] = report_logs(load_module_json("logs"))

    # Summary
    total_reclaimable = sum(v for v in categories.values() if v > 0)
    print_header("Summary - Reclaimable Space by Category")
    for cat, size in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        if size > 0:
            bar_len = min(40, max(1, int(40 * size / max(total_reclaimable, 1))))
            bar = "█" * bar_len
            print(f"  {cat:<25s}  {human_readable(size):>10s}  {bar}")
    print(f"\n  \033[1mTotal reclaimable: \033[31m{human_readable(total_reclaimable)}\033[0m")

    summary = {"total_reclaimable": total_reclaimable, "categories": categories}
    generate_html_report(summary)

    # Generate treemap
    try:
        import treemap as tm
        tm_categories = tm.build_category_data()
        if tm_categories:
            tm_html = tm.generate_html(tm_categories)
            tm_path = REPORT_DIR / "treemap.html"
            with open(tm_path, "w") as f:
                f.write(tm_html)
            print(f"  Treemap:     {tm_path}")
    except Exception:
        script_dir = Path(__file__).parent
        print(f"  Treemap:     run python3 {script_dir}/treemap.py")

    # Save summary JSON
    summary_path = REPORT_DIR / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  JSON summary: {summary_path}")
    print()


if __name__ == "__main__":
    main()
