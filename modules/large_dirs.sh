#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# large_dirs.sh — Find the largest directories on Synology volumes
# Part of Synology Space Analyzer
#
# Uses `du` to measure directory sizes up to 3 levels deep on each
# volume, then reports the top N (default 30) largest directories.
#
# Usage: bash large_dirs.sh [TOP_N]
# Requires: du, sort, awk
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/utils.sh"

MODULE="large_dirs"
TOP_N="${1:-30}"

main() {
    print_header "Large Directories Analysis"
    info "Scanning for top ${TOP_N} largest directories..."

    local volumes
    read -ra volumes <<< "$(detect_volumes)"

    local results=""
    local json_entries=""

    for vol in "${volumes[@]}"; do
        info "Scanning ${vol}..."
        while IFS=$'\t' read -r size path; do
            [ -z "$size" ] && continue
            local size_bytes
            size_bytes=$(echo "$size" | awk '{print $1}')
            local hr_size
            hr_size=$(human_readable "$((size_bytes * 1024))")  # du reports in KB
            results+="$(printf "%-10s  %s" "$hr_size" "$path")\n"

            json_entries+="$(printf '{"path":"%s","size_kb":%s,"human_size":"%s"},' \
                "$(echo "$path" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g')" "$size_bytes" "$hr_size")"
        done < <($DU -x -d 3 "$vol" 2>/dev/null | \
            $SORT -rn | head -n "$TOP_N")
    done

    if [ -z "$results" ]; then
        warn "No directories found."
        return
    fi

    print_subheader "Top ${TOP_N} Largest Directories"
    echo -e "${BOLD}$(printf "%-10s  %s" "SIZE" "DIRECTORY")${RESET}"
    echo "────────────────────────────────────────────────────────────────────"
    echo -e "$results" | head -n "$TOP_N"

    json_entries="${json_entries%,}"
    write_json "$MODULE" "[${json_entries}]"
    echo -e "$results" | head -n "$TOP_N" > "${REPORT_DIR}/${MODULE}.txt"

    success "Results written to ${REPORT_DIR}/${MODULE}.json"
}

main
