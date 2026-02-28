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
    """Generate an HTML report file."""
    html_path = REPORT_DIR / "report.html"
    categories = summary.get("categories", {})

    rows = ""
    for cat, size in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        rows += f"<tr><td>{cat}</td><td>{human_readable(size)}</td></tr>\n"

    html = f"""<!DOCTYPE html>
<html><head><title>Synology Space Report</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; }}
h1 {{ color: #2c3e50; }}
table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #ddd; }}
th {{ background-color: #3498db; color: white; }}
tr:hover {{ background-color: #f5f5f5; }}
.total {{ font-weight: bold; font-size: 1.2em; color: #e74c3c; }}
</style></head><body>
<h1>Synology Space Analysis Report</h1>
<p class="total">Total reclaimable: {human_readable(summary.get('total_reclaimable', 0))}</p>
<table><tr><th>Category</th><th>Reclaimable</th></tr>
{rows}
</table></body></html>"""

    with open(html_path, "w") as f:
        f.write(html)
    print(f"  HTML report: {html_path}")


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
