#!/usr/bin/env python3
"""
Synology Space Analyzer — Interactive Treemap Visualization

Generates a self-contained HTML treemap (WinDirStat-style) from the
JSON data produced by analyze.sh. The treemap uses a squarified layout
algorithm rendered entirely client-side — no external dependencies.

Categories visualized: large files (by directory), recycle bins,
duplicate files (wasted space), and oversized log files.

Usage:
    python3 treemap.py              # Generate treemap.html
    python3 treemap.py --open       # Generate and open in browser

Requires: Python 3.9+, analysis data in /tmp/synology-space-report/
"""
from __future__ import annotations

import json
import os
import sys
import webbrowser
from pathlib import Path

REPORT_DIR = Path("/tmp/synology-space-report")


def human_readable(size_bytes: int) -> str:
    if size_bytes >= 1099511627776:
        return f"{size_bytes / 1099511627776:.1f} TB"
    if size_bytes >= 1073741824:
        return f"{size_bytes / 1073741824:.1f} GB"
    if size_bytes >= 1048576:
        return f"{size_bytes / 1048576:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def load_json(module: str) -> dict | list | None:
    path = REPORT_DIR / f"{module}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def build_directory_tree(files: list[dict]) -> dict:
    """Build a nested directory tree from flat file list."""
    root = {"name": "/", "children": {}, "size": 0}

    for f in files:
        path = f.get("path", "")
        size = f.get("size", 0)
        if not path or size <= 0:
            continue

        parts = path.strip("/").split("/")
        node = root

        # Build intermediate directories
        for i, part in enumerate(parts[:-1]):
            if part not in node["children"]:
                node["children"][part] = {"name": part, "children": {}, "size": 0}
            node = node["children"][part]
            node["size"] += size

        # Add the file itself
        filename = parts[-1] if parts else path
        node["children"][filename] = {
            "name": filename,
            "size": size,
            "path": path,
            "modified": f.get("modified", ""),
        }

    root["size"] = sum(
        c.get("size", 0) for c in root["children"].values()
    )
    return root


def tree_to_treemap_json(node: dict, depth: int = 0, max_depth: int = 5) -> dict:
    """Convert directory tree to the format needed by the treemap renderer."""
    result = {
        "name": node.get("name", "?"),
        "size": node.get("size", 0),
        "human_size": human_readable(node.get("size", 0)),
    }

    if "path" in node:
        result["path"] = node["path"]
        result["modified"] = node.get("modified", "")
        return result

    children = node.get("children", {})
    if children and depth < max_depth:
        child_list = []
        for child in sorted(children.values(), key=lambda c: c.get("size", 0), reverse=True):
            child_list.append(tree_to_treemap_json(child, depth + 1, max_depth))
        result["children"] = child_list

    return result


def build_category_data() -> list[dict]:
    """Build treemap data from all analysis categories."""
    categories = []

    # Large files → directory tree
    large_files = load_json("large_files")
    if large_files and isinstance(large_files, list) and len(large_files) > 0:
        tree = build_directory_tree(large_files)
        treemap_data = tree_to_treemap_json(tree)
        treemap_data["name"] = "Files by Directory"
        treemap_data["category"] = "files"
        categories.append(treemap_data)

    # Recycle bins
    recycle = load_json("recycle_bins")
    if recycle and isinstance(recycle, dict):
        bins = recycle.get("bins", [])
        if bins:
            children = []
            for b in bins:
                children.append({
                    "name": b.get("share", "unknown") + "/#recycle",
                    "size": b.get("size_bytes", 0),
                    "human_size": human_readable(b.get("size_bytes", 0)),
                    "file_count": b.get("file_count", 0),
                })
            categories.append({
                "name": "Recycle Bins",
                "category": "recycle",
                "size": recycle.get("total_size_bytes", 0),
                "human_size": human_readable(recycle.get("total_size_bytes", 0)),
                "children": children,
            })

    # Log files
    logs = load_json("logs")
    if logs and isinstance(logs, dict):
        log_entries = logs.get("logs", [])
        if log_entries:
            children = []
            for l in log_entries:
                children.append({
                    "name": os.path.basename(l.get("path", "?")),
                    "path": l.get("path", ""),
                    "size": l.get("size_bytes", 0),
                    "human_size": human_readable(l.get("size_bytes", 0)),
                    "safe": l.get("safe_to_clean", False),
                })
            categories.append({
                "name": "Log Files",
                "category": "logs",
                "size": logs.get("total_size_bytes", 0),
                "human_size": human_readable(logs.get("total_size_bytes", 0)),
                "children": children,
            })

    # Duplicates
    dupes = load_json("duplicates")
    if dupes and isinstance(dupes, dict):
        groups = dupes.get("groups", [])
        if groups:
            children = []
            for g in groups:
                files = g.get("files", [])
                children.append({
                    "name": f"{len(files)} copies ({human_readable(g.get('size', 0))} each)",
                    "size": g.get("wasted", 0),
                    "human_size": human_readable(g.get("wasted", 0)),
                    "files": files[:5],
                })
            categories.append({
                "name": "Duplicate Files (wasted)",
                "category": "duplicates",
                "size": dupes.get("total_wasted_bytes", 0),
                "human_size": human_readable(dupes.get("total_wasted_bytes", 0)),
                "children": children,
            })

    return categories


def generate_html(categories: list[dict]) -> str:
    """Generate self-contained HTML treemap page."""
    data_json = json.dumps(categories, indent=2)
    total_size = sum(c.get("size", 0) for c in categories)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Synology Space Analyzer - Treemap</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #eee; }}
.header {{ background: #16213e; padding: 20px 30px; border-bottom: 2px solid #0f3460; display: flex; justify-content: space-between; align-items: center; }}
.header h1 {{ font-size: 24px; color: #e94560; }}
.header .total {{ font-size: 18px; color: #aaa; }}
.header .total span {{ color: #e94560; font-weight: bold; }}
.controls {{ padding: 12px 30px; background: #16213e; border-bottom: 1px solid #0f3460; display: flex; gap: 10px; align-items: center; }}
.controls label {{ color: #aaa; font-size: 14px; }}
.controls select, .controls button {{ background: #0f3460; color: #eee; border: 1px solid #533483; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 14px; }}
.controls button:hover {{ background: #533483; }}
.controls button.active {{ background: #e94560; border-color: #e94560; }}
.breadcrumb {{ padding: 8px 30px; background: #1a1a2e; font-size: 13px; color: #888; }}
.breadcrumb span {{ cursor: pointer; color: #4fc3f7; }}
.breadcrumb span:hover {{ text-decoration: underline; }}
#treemap-container {{ width: 100%; height: calc(100vh - 160px); position: relative; overflow: hidden; }}
.treemap-node {{ position: absolute; overflow: hidden; border: 1px solid rgba(0,0,0,0.3); cursor: pointer; transition: opacity 0.15s; display: flex; align-items: flex-start; justify-content: flex-start; }}
.treemap-node:hover {{ opacity: 0.85; z-index: 10; }}
.treemap-label {{ padding: 4px 6px; font-size: 11px; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.8); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; pointer-events: none; line-height: 1.3; }}
.treemap-label .size {{ font-size: 10px; opacity: 0.8; display: block; }}
.tooltip {{ position: fixed; background: #16213e; border: 1px solid #533483; border-radius: 6px; padding: 12px 16px; font-size: 13px; color: #eee; pointer-events: none; z-index: 1000; max-width: 400px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); display: none; }}
.tooltip .tt-name {{ font-weight: bold; color: #4fc3f7; margin-bottom: 4px; }}
.tooltip .tt-size {{ color: #e94560; font-size: 15px; font-weight: bold; }}
.tooltip .tt-path {{ color: #888; font-size: 12px; margin-top: 4px; word-break: break-all; }}
.tooltip .tt-meta {{ color: #aaa; font-size: 12px; margin-top: 4px; }}
.legend {{ position: fixed; bottom: 20px; right: 20px; background: rgba(22,33,62,0.95); border: 1px solid #533483; border-radius: 8px; padding: 12px 16px; font-size: 12px; }}
.legend-item {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
.legend-color {{ width: 14px; height: 14px; border-radius: 3px; }}
</style>
</head>
<body>

<div class="header">
    <h1>&#x1f4ca; Synology Space Analyzer</h1>
    <div class="total">Analyzed: <span>{human_readable(total_size)}</span></div>
</div>

<div class="controls">
    <label>View:</label>
    <select id="category-select"></select>
    <button id="btn-back" onclick="navigateUp()">&#x2B06; Up</button>
    <label style="margin-left: 20px">Color by:</label>
    <select id="color-mode" onchange="render()">
        <option value="type">File Type</option>
        <option value="size">Size (heat)</option>
        <option value="category">Category</option>
    </select>
</div>

<div class="breadcrumb" id="breadcrumb"></div>
<div id="treemap-container"></div>

<div class="tooltip" id="tooltip">
    <div class="tt-name"></div>
    <div class="tt-size"></div>
    <div class="tt-path"></div>
    <div class="tt-meta"></div>
</div>

<div class="legend" id="legend"></div>

<script>
const ALL_DATA = {data_json};

const CATEGORY_COLORS = {{
    files: ['#e94560', '#c0392b', '#e74c3c', '#ff6b6b', '#d63031'],
    recycle: ['#f39c12', '#e67e22', '#d35400', '#f0932b', '#e58e26'],
    logs: ['#2ecc71', '#27ae60', '#1abc9c', '#0abde3', '#10ac84'],
    duplicates: ['#9b59b6', '#8e44ad', '#6c5ce7', '#a29bfe', '#fd79a8'],
}};

const EXT_COLORS = {{
    // Media
    jpg: '#e94560', jpeg: '#e94560', png: '#ff6b6b', gif: '#d63031', bmp: '#c0392b',
    svg: '#e74c3c', webp: '#ff7675', ico: '#fab1a0',
    mp4: '#0984e3', mkv: '#74b9ff', avi: '#0652DD', mov: '#1e90ff', wmv: '#4834d4',
    mp3: '#6c5ce7', flac: '#a29bfe', wav: '#5f27cd', aac: '#8854d0', ogg: '#9b59b6',
    // Documents
    pdf: '#d63031', doc: '#2d98da', docx: '#2d98da', xls: '#20bf6b', xlsx: '#20bf6b',
    ppt: '#f7b731', pptx: '#f7b731', txt: '#95a5a6', csv: '#26de81', md: '#778ca3',
    // Archives
    zip: '#f39c12', tar: '#e67e22', gz: '#d35400', bz2: '#e58e26', '7z': '#f0932b',
    rar: '#fa8231', xz: '#fd9644',
    // Code
    py: '#3498db', js: '#f1c40f', ts: '#2980b9', html: '#e44d26', css: '#264de4',
    java: '#b07219', go: '#00ADD8', rs: '#dea584', c: '#555555', cpp: '#f34b7d',
    sh: '#4EAA25', json: '#292929', xml: '#e37933', yaml: '#cb171e', yml: '#cb171e',
    // Data
    db: '#1abc9c', sql: '#e67e22', sqlite: '#1abc9c', log: '#2ecc71',
    // VM/Disk
    vmdk: '#e94560', qcow2: '#c0392b', iso: '#d63031', img: '#ff6b6b',
    // Default
    _default: '#636e72',
}};

let currentData = null;
let navStack = [];

function getExtension(name) {{
    const parts = name.split('.');
    return parts.length > 1 ? parts.pop().toLowerCase() : '';
}}

function getColor(node, mode, depth) {{
    if (mode === 'category') {{
        const cat = node._category || 'files';
        const colors = CATEGORY_COLORS[cat] || CATEGORY_COLORS.files;
        return colors[depth % colors.length];
    }}
    if (mode === 'size') {{
        const maxSize = currentData ? currentData.size || 1 : 1;
        const ratio = Math.min(1, (node.size || 0) / maxSize);
        const h = (1 - ratio) * 200;
        return `hsl(${{h}}, 70%, 45%)`;
    }}
    // type
    const ext = getExtension(node.name || '');
    return EXT_COLORS[ext] || EXT_COLORS._default;
}}

function squarify(items, x, y, w, h) {{
    if (!items || items.length === 0) return [];
    const rects = [];
    const totalSize = items.reduce((s, i) => s + (i.size || 0), 0);
    if (totalSize <= 0) return [];

    let remainingItems = [...items];
    let cx = x, cy = y, cw = w, ch = h;

    while (remainingItems.length > 0) {{
        const isWide = cw >= ch;
        const sideLen = isWide ? ch : cw;
        const remaining = remainingItems.reduce((s, i) => s + (i.size || 0), 0);

        let row = [remainingItems[0]];
        let rowSize = remainingItems[0].size || 0;
        remainingItems = remainingItems.slice(1);

        function worstRatio(row, rowSize, sideLen) {{
            const areaScale = (sideLen * (isWide ? cw : ch)) / remaining;
            const rowLen = (rowSize / remaining) * (isWide ? cw : ch);
            if (rowLen <= 0) return Infinity;
            let worst = 0;
            for (const item of row) {{
                const itemArea = ((item.size || 0) / remaining) * sideLen * (isWide ? cw : ch);
                const itemLen = itemArea / rowLen;
                const r = Math.max(rowLen / itemLen, itemLen / rowLen);
                worst = Math.max(worst, r);
            }}
            return worst;
        }}

        while (remainingItems.length > 0) {{
            const next = remainingItems[0];
            const newRow = [...row, next];
            const newSize = rowSize + (next.size || 0);
            if (worstRatio(newRow, newSize, sideLen) <= worstRatio(row, rowSize, sideLen)) {{
                row = newRow;
                rowSize = newSize;
                remainingItems = remainingItems.slice(1);
            }} else {{
                break;
            }}
        }}

        const rowFraction = rowSize / remaining;
        const rowThickness = (isWide ? cw : ch) * rowFraction;

        let offset = 0;
        for (const item of row) {{
            const itemFraction = (item.size || 0) / rowSize;
            const itemLen = sideLen * itemFraction;

            let rx, ry, rw, rh;
            if (isWide) {{
                rx = cx;
                ry = cy + offset;
                rw = rowThickness;
                rh = itemLen;
            }} else {{
                rx = cx + offset;
                ry = cy;
                rw = itemLen;
                rh = rowThickness;
            }}
            rects.push({{ item, x: rx, y: ry, w: rw, h: rh }});
            offset += itemLen;
        }}

        if (isWide) {{
            cx += rowThickness;
            cw -= rowThickness;
        }} else {{
            cy += rowThickness;
            ch -= rowThickness;
        }}
    }}
    return rects;
}}

function render() {{
    const container = document.getElementById('treemap-container');
    const tooltip = document.getElementById('tooltip');
    const colorMode = document.getElementById('color-mode').value;
    container.innerHTML = '';

    if (!currentData) return;
    const children = currentData.children || [];
    if (children.length === 0) return;

    const sorted = [...children].sort((a, b) => (b.size || 0) - (a.size || 0));
    const W = container.clientWidth;
    const H = container.clientHeight;
    const rects = squarify(sorted, 0, 0, W, H);

    function attachCategory(node, cat) {{
        node._category = cat;
        if (node.children) node.children.forEach(c => attachCategory(c, cat));
    }}
    sorted.forEach(s => attachCategory(s, s.category || s._category || 'files'));

    for (const r of rects) {{
        if (r.w < 2 || r.h < 2) continue;
        const div = document.createElement('div');
        div.className = 'treemap-node';
        div.style.left = r.x + 'px';
        div.style.top = r.y + 'px';
        div.style.width = r.w + 'px';
        div.style.height = r.h + 'px';
        div.style.backgroundColor = getColor(r.item, colorMode, 0);

        if (r.item.children && r.item.children.length > 0 && r.w > 40 && r.h > 30) {{
            const innerRects = squarify(
                [...r.item.children].sort((a, b) => (b.size || 0) - (a.size || 0)),
                0, 0, r.w - 2, r.h - 2
            );
            for (const ir of innerRects) {{
                if (ir.w < 3 || ir.h < 3) continue;
                const inner = document.createElement('div');
                inner.className = 'treemap-node';
                inner.style.left = (ir.x + 1) + 'px';
                inner.style.top = (ir.y + 1) + 'px';
                inner.style.width = ir.w + 'px';
                inner.style.height = ir.h + 'px';
                inner.style.backgroundColor = getColor(ir.item, colorMode, 1);

                if (ir.w > 50 && ir.h > 20) {{
                    const label = document.createElement('div');
                    label.className = 'treemap-label';
                    label.innerHTML = `${{ir.item.name}}<span class="size">${{ir.item.human_size || ''}}</span>`;
                    inner.appendChild(label);
                }}

                inner.addEventListener('mousemove', (e) => showTooltip(e, ir.item));
                inner.addEventListener('mouseleave', hideTooltip);
                inner.addEventListener('click', (e) => {{ e.stopPropagation(); drillDown(ir.item); }});
                div.appendChild(inner);
            }}
        }}

        if (r.w > 60 && r.h > 24) {{
            const label = document.createElement('div');
            label.className = 'treemap-label';
            label.style.fontWeight = 'bold';
            label.style.fontSize = '13px';
            label.innerHTML = `${{r.item.name}}<span class="size">${{r.item.human_size || ''}}</span>`;
            div.insertBefore(label, div.firstChild);
        }}

        div.addEventListener('mousemove', (e) => showTooltip(e, r.item));
        div.addEventListener('mouseleave', hideTooltip);
        div.addEventListener('click', () => drillDown(r.item));
        container.appendChild(div);
    }}

    updateBreadcrumb();
    updateLegend(colorMode, rects);
}}

function showTooltip(e, item) {{
    const tt = document.getElementById('tooltip');
    tt.style.display = 'block';
    tt.querySelector('.tt-name').textContent = item.name || '?';
    tt.querySelector('.tt-size').textContent = item.human_size || '';
    tt.querySelector('.tt-path').textContent = item.path || '';
    const meta = [];
    if (item.modified) meta.push('Modified: ' + item.modified);
    if (item.file_count) meta.push('Files: ' + item.file_count);
    if (item.safe !== undefined) meta.push(item.safe ? '✓ Safe to clean' : '⚠ Review before cleaning');
    if (item.children) meta.push(item.children.length + ' items');
    tt.querySelector('.tt-meta').textContent = meta.join(' | ');

    let tx = e.clientX + 15, ty = e.clientY + 15;
    if (tx + 350 > window.innerWidth) tx = e.clientX - 360;
    if (ty + 100 > window.innerHeight) ty = e.clientY - 110;
    tt.style.left = tx + 'px';
    tt.style.top = ty + 'px';
}}

function hideTooltip() {{
    document.getElementById('tooltip').style.display = 'none';
}}

function drillDown(item) {{
    if (!item.children || item.children.length === 0) return;
    navStack.push(currentData);
    currentData = item;
    render();
}}

function navigateUp() {{
    if (navStack.length === 0) return;
    currentData = navStack.pop();
    render();
}}

function navigateTo(index) {{
    while (navStack.length > index) {{
        currentData = navStack.pop();
    }}
    render();
}}

function updateBreadcrumb() {{
    const bc = document.getElementById('breadcrumb');
    let html = '';
    for (let i = 0; i < navStack.length; i++) {{
        html += `<span onclick="navigateTo(${{i}})">${{navStack[i].name}}</span> / `;
    }}
    html += `<strong>${{currentData.name}}</strong>`;
    bc.innerHTML = html;
}}

function updateLegend(mode, rects) {{
    const legend = document.getElementById('legend');
    if (mode === 'category') {{
        legend.innerHTML = Object.entries(CATEGORY_COLORS).map(([cat, colors]) =>
            `<div class="legend-item"><div class="legend-color" style="background:${{colors[0]}}"></div>${{cat}}</div>`
        ).join('');
    }} else if (mode === 'type') {{
        const exts = {{}};
        function collectExts(items) {{
            for (const item of (items || [])) {{
                if (item.children) collectExts(item.children);
                else {{
                    const ext = getExtension(item.name || '') || 'other';
                    if (!exts[ext]) exts[ext] = 0;
                    exts[ext] += item.size || 0;
                }}
            }}
        }}
        collectExts(currentData.children);
        const sorted = Object.entries(exts).sort((a, b) => b[1] - a[1]).slice(0, 10);
        legend.innerHTML = sorted.map(([ext, size]) =>
            `<div class="legend-item"><div class="legend-color" style="background:${{EXT_COLORS[ext] || EXT_COLORS._default}}"></div>.${{ext}}</div>`
        ).join('');
    }} else {{
        legend.innerHTML = '<div style="color:#888">Warmer = larger</div>';
    }}
}}

// Initialize
function init() {{
    const select = document.getElementById('category-select');

    // "All Categories" option
    const allOpt = document.createElement('option');
    allOpt.value = 'all';
    allOpt.textContent = 'All Categories';
    select.appendChild(allOpt);

    ALL_DATA.forEach((cat, i) => {{
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = `${{cat.name}} (${{cat.human_size}})`;
        select.appendChild(opt);
    }});

    select.addEventListener('change', () => {{
        navStack = [];
        if (select.value === 'all') {{
            currentData = {{ name: 'All Categories', size: ALL_DATA.reduce((s, c) => s + (c.size || 0), 0), human_size: '', children: ALL_DATA }};
            currentData.human_size = currentData.size > 0 ? ALL_DATA[0].human_size : '0 B'; // recalc below
        }} else {{
            currentData = ALL_DATA[parseInt(select.value)];
        }}
        render();
    }});

    // Default: all categories
    currentData = {{
        name: 'All Categories',
        size: ALL_DATA.reduce((s, c) => s + (c.size || 0), 0),
        children: ALL_DATA,
    }};
    currentData.human_size = '{human_readable(total_size)}';
    render();
}}

window.addEventListener('load', init);
window.addEventListener('resize', render);
</script>
</body>
</html>"""


def main():
    if not REPORT_DIR.exists():
        print("Error: Report directory not found. Run analyze.sh first.")
        sys.exit(1)

    categories = build_category_data()
    if not categories:
        print("No analysis data found. Run analyze.sh first.")
        sys.exit(1)

    html = generate_html(categories)
    output_path = REPORT_DIR / "treemap.html"

    with open(output_path, "w") as f:
        f.write(html)

    print(f"Treemap generated: {output_path}")
    print(f"Open in browser: file://{output_path}")

    if "--open" in sys.argv:
        webbrowser.open(f"file://{output_path}")


if __name__ == "__main__":
    main()
