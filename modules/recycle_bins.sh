#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# recycle_bins.sh — Scan Synology recycle bins (#recycle dirs)
# Part of Synology Space Analyzer
#
# Synology DSM creates a #recycle directory inside each shared
# folder. This module finds them, totals their size, and reports
# reclaimable space per share.
#
# Usage: bash recycle_bins.sh
# Requires: find, du
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/utils.sh"

MODULE="recycle_bins"

main() {
    print_header "Recycle Bins Analysis"
    info "Scanning for #recycle directories..."

    local volumes
    read -ra volumes <<< "$(detect_volumes)"

    local text_output=""
    local json_entries=""
    local total_size=0
    local total_files=0

    for vol in "${volumes[@]}"; do
        # Find all #recycle directories (Synology puts one in each shared folder)
        while IFS= read -r recycle_dir; do
            [ -z "$recycle_dir" ] && continue

            local dir_size dir_size_bytes file_count parent_share
            dir_size=$($DU -sh "$recycle_dir" 2>/dev/null | awk '{print $1}')
            dir_size_bytes=$(${DU} -sk "$recycle_dir" 2>/dev/null | awk '{print $1 * 1024}')
            file_count=$($FIND "$recycle_dir" -type f 2>/dev/null | wc -l | tr -d ' ')
            parent_share=$(basename "$(dirname "$recycle_dir")")

            [ -z "$dir_size_bytes" ] && dir_size_bytes=0
            total_size=$((total_size + dir_size_bytes))
            total_files=$((total_files + file_count))

            if [ "$file_count" -gt 0 ]; then
                text_output+="$(printf "  %-30s  Size: %-10s  Files: %d\n" \
                    "$parent_share/#recycle" "$dir_size" "$file_count")"

                json_entries+="$(printf '{"share":"%s","path":"%s","size_bytes":%s,"human_size":"%s","file_count":%d},' \
                    "$parent_share" "$(echo "$recycle_dir" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g')" "$dir_size_bytes" "$dir_size" "$file_count")"
            fi
        done < <($FIND "$vol" -maxdepth 2 -name "#recycle" -type d 2>/dev/null)
    done

    print_subheader "Recycle Bin Summary"
    if [ -n "$text_output" ]; then
        echo -e "${BOLD}$(printf "  %-30s  %-16s  %s" "SHARE" "SIZE" "FILES")${RESET}"
        echo "  ────────────────────────────────────────────────────────────"
        echo -e "$text_output"
        echo ""
        echo -e "  ${BOLD}Total reclaimable: $(human_readable $total_size) across ${total_files} files${RESET}"
    else
        info "No recycle bin contents found."
    fi

    json_entries="${json_entries%,}"
    write_json "$MODULE" "$(printf '{"bins":[%s],"total_size_bytes":%d,"total_files":%d}' \
        "$json_entries" "$total_size" "$total_files")"
    echo -e "$text_output" > "${REPORT_DIR}/${MODULE}.txt"
    echo "Total: $(human_readable $total_size), ${total_files} files" >> "${REPORT_DIR}/${MODULE}.txt"

    success "Results written to ${REPORT_DIR}/${MODULE}.json"
}

main
