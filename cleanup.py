#!/usr/bin/env python3
"""
Synology Space Analyzer — Interactive Cleanup Tool

Guides users through reclaiming disk space with per-action confirmation
prompts. Reads analysis results from /tmp/synology-space-report/ and
offers cleanup for: recycle bins, old snapshots, Docker resources,
oversized logs, and individual large files.

SAFETY FEATURES:
  - Every destructive action requires explicit user confirmation (y/N).
  - --dry-run mode simulates all actions without modifying the filesystem.
  - Active log files are truncated (not deleted) to avoid breaking services.
  - Recycle bin paths are validated to contain '#recycle' before removal.
  - All subprocess commands have a 300-second timeout.
  - Root privilege warning is shown when running unprivileged.

Usage:
    sudo python3 cleanup.py           # Interactive cleanup
    sudo python3 cleanup.py --dry-run # Preview what would be done

Requires: Python 3.9+, root recommended, analysis data from analyze.sh
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPORT_DIR = Path("/tmp/synology-space-report")
DRY_RUN = "--dry-run" in sys.argv


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


def load_module_json(module: str) -> dict | None:
    path = REPORT_DIR / f"{module}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def confirm(prompt: str) -> bool:
    if DRY_RUN:
        print(f"  \033[33m[DRY RUN] Would ask: {prompt}\033[0m")
        return False
    while True:
        response = input(f"  {prompt} [y/N]: ").strip().lower()
        if response in ("y", "yes"):
            return True
        if response in ("n", "no", ""):
            return False
        print("  Please answer y or n.")


def run_cmd(cmd: list[str], description: str) -> bool:
    print(f"  Running: {' '.join(cmd)}")
    if DRY_RUN:
        print(f"  \033[33m[DRY RUN] Skipped: {description}\033[0m")
        return True
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print(f"  \033[32m✓ {description}\033[0m")
            if result.stdout.strip():
                for line in result.stdout.strip().split("\n")[:5]:
                    print(f"    {line}")
            return True
        else:
            print(f"  \033[31m✗ Failed: {result.stderr.strip()}\033[0m")
            return False
    except subprocess.TimeoutExpired:
        print(f"  \033[31m✗ Timed out: {description}\033[0m")
        return False


def print_header(title: str):
    print()
    print(f"\033[1;36m{'═' * 60}\033[0m")
    print(f"\033[1;36m  {title}\033[0m")
    print(f"\033[1;36m{'═' * 60}\033[0m")
    print()


def print_menu_item(num: int, title: str, detail: str = ""):
    detail_str = f" - {detail}" if detail else ""
    print(f"  \033[1m{num}.\033[0m {title}{detail_str}")


# ─── Cleanup Actions ─────────────────────────────────────────

def cleanup_recycle_bins():
    """Empty Synology recycle bins."""
    data = load_module_json("recycle_bins")
    if not data or not data.get("bins"):
        print("  No recycle bin data available. Run analyze.sh first.")
        return 0

    bins = data["bins"]
    total = data.get("total_size_bytes", 0)
    total_files = data.get("total_files", 0)

    print(f"\n  Found {len(bins)} recycle bins with {total_files} files ({human_readable(total)}):\n")
    for b in bins:
        print(f"    {b.get('share', 'unknown'):<30s}  {b.get('human_size', '?'):>10s}  ({b.get('file_count', 0)} files)")

    print()
    freed = 0

    # Option to empty all at once
    if confirm(f"Empty ALL recycle bins? ({human_readable(total)})"):
        for b in bins:
            path = b.get("path", "")
            if not path:
                continue
            if os.path.isdir(path) and "#recycle" in path:
                print(f"  Emptying {path}...")
                if not DRY_RUN:
                    for item in Path(path).iterdir():
                        try:
                            if item.is_dir():
                                shutil.rmtree(item)
                            else:
                                item.unlink()
                        except OSError as e:
                            print(f"  \033[31m  Could not remove {item}: {e}\033[0m")
                freed += b.get("size_bytes", 0)
        print(f"\n  \033[32m✓ Freed {human_readable(freed)}\033[0m")
    else:
        # Offer per-share cleanup
        for b in bins:
            if b.get("file_count", 0) > 0:
                if confirm(f"Empty {b.get('share', 'unknown')}/#recycle? ({b.get('human_size', '?')}, {b.get('file_count', 0)} files)"):
                    path = b.get("path", "")
                    if not path:
                        continue
                    if os.path.isdir(path) and "#recycle" in path:
                        if not DRY_RUN:
                            for item in Path(path).iterdir():
                                try:
                                    if item.is_dir():
                                        shutil.rmtree(item)
                                    else:
                                        item.unlink()
                                except OSError as e:
                                    print(f"    \033[31mCould not remove {item}: {e}\033[0m")
                        freed += b.get("size_bytes", 0)
        if freed > 0:
            print(f"\n  \033[32m✓ Freed {human_readable(freed)}\033[0m")

    return freed


def cleanup_snapshots():
    """Remove old Btrfs snapshots."""
    data = load_module_json("snapshots")
    if not data or not data.get("available"):
        print("  No snapshot data available.")
        return 0

    old_snaps = [s for s in data.get("snapshots", []) if s.get("is_old")]
    if not old_snaps:
        print("  No old snapshots to remove.")
        return 0

    max_age = data.get("max_age_days", 30)
    print(f"\n  Found {len(old_snaps)} snapshots older than {max_age} days:\n")
    for s in old_snaps:
        print(f"    ID: {s.get('id', '?'):6s}  Date: {s.get('date', 'unknown'):20s}  Path: {s.get('path', '?')}")

    freed = 0
    if confirm(f"Remove all {len(old_snaps)} old snapshots?"):
        for s in old_snaps:
            vol = s.get("volume", "/volume1")
            snap_path = f"{vol}/{s.get('path', '')}"
            if run_cmd(["btrfs", "subvolume", "delete", snap_path],
                       f"Deleted snapshot {s.get('id', '?')}"):
                freed += s.get("exclusive_bytes", 0)
    else:
        for s in old_snaps:
            if confirm(f"Remove snapshot {s.get('id', '?')} ({s.get('date', 'unknown')})?"):
                vol = s.get("volume", "/volume1")
                snap_path = f"{vol}/{s.get('path', '')}"
                if run_cmd(["btrfs", "subvolume", "delete", snap_path],
                           f"Deleted snapshot {s.get('id', '?')}"):
                    freed += s.get("exclusive_bytes", 0)

    if freed > 0:
        print(f"\n  \033[32m✓ Freed approximately {human_readable(freed)}\033[0m")
    return freed


def cleanup_docker():
    """Prune Docker resources."""
    data = load_module_json("docker")
    if not data or not data.get("available"):
        print("  Docker not available.")
        return 0

    print(f"\n  Docker cleanup options:")
    print(f"    Dangling images:    {data.get('dangling_images', 0)}")
    print(f"    Stopped containers: {data.get('stopped_containers', 0)}")
    print(f"    Unused volumes:     {data.get('unused_volumes', 0)}")
    print()

    freed = 0

    if data.get("dangling_images", 0) > 0:
        if confirm("Remove dangling Docker images?"):
            run_cmd(["docker", "image", "prune", "-f"], "Pruned dangling images")

    if data.get("stopped_containers", 0) > 0:
        if confirm("Remove stopped Docker containers?"):
            run_cmd(["docker", "container", "prune", "-f"], "Pruned stopped containers")

    if data.get("unused_volumes", 0) > 0:
        if confirm("Remove unused Docker volumes? (WARNING: data in volumes will be lost)"):
            run_cmd(["docker", "volume", "prune", "-f"], "Pruned unused volumes")

    if confirm("Clean Docker build cache?"):
        run_cmd(["docker", "builder", "prune", "-f"], "Pruned build cache")

    print("\n  Note: Run 'docker system df' to see updated Docker disk usage.")
    return freed


def cleanup_logs():
    """Truncate or remove oversized log files."""
    data = load_module_json("logs")
    if not data or not data.get("logs"):
        print("  No log data available.")
        return 0

    safe_logs = [l for l in data["logs"] if l.get("safe_to_clean")]
    if not safe_logs:
        print("  No logs marked as safe to clean.")
        return 0

    total = sum(l.get("size_bytes", 0) for l in safe_logs)
    print(f"\n  Found {len(safe_logs)} logs safe to clean ({human_readable(total)}):\n")
    for l in safe_logs:
        print(f"    {l.get('human_size', '?'):>10s}  {l.get('path', '?')}")

    freed = 0
    print()

    if confirm(f"Clean all {len(safe_logs)} safe log files?"):
        for l in safe_logs:
            path = l.get("path", "")
            if not path:
                continue
            size = l.get("size_bytes", 0)
            if path.endswith((".gz", ".bz2", ".xz", ".zip", ".old")):
                # Compressed/old logs: safe to delete
                print(f"  Removing {path}...")
                if not DRY_RUN:
                    try:
                        os.unlink(path)
                        freed += size
                    except OSError as e:
                        print(f"    \033[31mFailed: {e}\033[0m")
            else:
                # Active logs: truncate instead of delete
                print(f"  Truncating {path}...")
                if not DRY_RUN:
                    try:
                        with open(path, "w") as f:
                            f.truncate(0)
                        freed += size
                    except OSError as e:
                        print(f"    \033[31mFailed: {e}\033[0m")

        print(f"\n  \033[32m✓ Freed {human_readable(freed)}\033[0m")
    return freed


def cleanup_large_files():
    """Interactively review and delete large files."""
    data = load_module_json("large_files")
    if not data or not isinstance(data, list):
        print("  No large file data available.")
        return 0

    print(f"\n  Top 20 largest files:\n")
    for i, f in enumerate(data[:20], 1):
        print(f"    {i:3d}. {f.get('human_size', '?'):>10s}  {f.get('modified', ''):20s}  {f.get('path', '?')}")

    freed = 0
    print()
    print("  Enter file numbers to delete (comma-separated), or 'skip' to skip:")

    if DRY_RUN:
        print("  \033[33m[DRY RUN] Skipping interactive file selection\033[0m")
        return 0

    response = input("  > ").strip()
    if response.lower() in ("skip", "s", ""):
        return 0

    try:
        indices = [int(x.strip()) - 1 for x in response.split(",")]
    except ValueError:
        print("  Invalid input.")
        return 0

    for idx in indices:
        if 0 <= idx < min(20, len(data)):
            f = data[idx]
            path = f.get("path", "")
            size = f.get("size", 0)
            if confirm(f"Delete {path} ({f.get('human_size', '?')})?"):
                try:
                    os.unlink(path)
                    freed += size
                    print(f"    \033[32m✓ Deleted\033[0m")
                except OSError as e:
                    print(f"    \033[31mFailed: {e}\033[0m")

    if freed > 0:
        print(f"\n  \033[32m✓ Freed {human_readable(freed)}\033[0m")
    return freed


# ─── Main Menu ────────────────────────────────────────────────

def main():
    if DRY_RUN:
        print("\033[1;33m  *** DRY RUN MODE - No changes will be made ***\033[0m")

    if os.geteuid() != 0:
        print("\033[33m  Warning: Not running as root. Some cleanup operations may fail.\033[0m")
        print("\033[33m  Re-run with: sudo python3 cleanup.py\033[0m")
        print()

    if not REPORT_DIR.exists():
        print(f"Error: Report directory not found: {REPORT_DIR}")
        print("Run analyze.sh first to generate analysis data.")
        sys.exit(1)

    total_freed = 0

    while True:
        print_header("Synology Space Cleanup")

        if DRY_RUN:
            print("  \033[33m[DRY RUN MODE]\033[0m\n")

        print_menu_item(1, "Empty Recycle Bins", "Remove deleted files from #recycle folders")
        print_menu_item(2, "Remove Old Snapshots", "Delete Btrfs snapshots past retention period")
        print_menu_item(3, "Prune Docker", "Remove unused images, containers, volumes, cache")
        print_menu_item(4, "Clean Log Files", "Truncate or remove oversized logs")
        print_menu_item(5, "Review Large Files", "Interactively delete large files")
        print_menu_item(6, "Run All Cleanups", "Execute all cleanup categories sequentially")
        print_menu_item(0, "Exit", f"Total freed this session: {human_readable(total_freed)}")

        print()
        try:
            choice = input("  Select option [0-6]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "0":
            break
        elif choice == "1":
            total_freed += cleanup_recycle_bins()
        elif choice == "2":
            total_freed += cleanup_snapshots()
        elif choice == "3":
            total_freed += cleanup_docker()
        elif choice == "4":
            total_freed += cleanup_logs()
        elif choice == "5":
            total_freed += cleanup_large_files()
        elif choice == "6":
            print("\n  Running all cleanup categories...\n")
            total_freed += cleanup_recycle_bins()
            total_freed += cleanup_snapshots()
            total_freed += cleanup_docker()
            total_freed += cleanup_logs()
            total_freed += cleanup_large_files()
        else:
            print("  Invalid option. Please select 0-6.")

        input("\n  Press Enter to continue...")

    print_header("Cleanup Complete")
    print(f"  Total space freed: \033[1;32m{human_readable(total_freed)}\033[0m")
    print()


if __name__ == "__main__":
    main()
