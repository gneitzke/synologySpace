#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# large_files.sh — Find the largest files across Synology volumes
# Part of Synology Space Analyzer
#
# Scans all detected volumes for the N largest files (default 50),
# excluding Synology metadata (@eaDir), recycle bins, and snapshots.
# Outputs both a formatted table and JSON for the report generator.
#
# Usage: bash large_files.sh [TOP_N]
# Requires: GNU find (with -printf), sort, awk
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/utils.sh"

MODULE="large_files"
TOP_N="${1:-50}"

main() {
    print_header "Large Files Analysis"
    info "Scanning for top ${TOP_N} largest files..."

    local volumes
    read -ra volumes <<< "$(detect_volumes)"

    local results=""
    local json_entries=""

    for vol in "${volumes[@]}"; do
        info "Scanning ${vol}..."
        # Find files, exclude pseudo-filesystems and snapshot dirs
        while IFS= read -r line; do
            local size path mod_date
            size=$(printf '%s\n' "$line" | awk '{print $1}')
            path=$(printf '%s\n' "$line" | awk '{for(i=4;i<=NF;i++) printf "%s ", $i; print ""}' | sed 's/ *$//')
            mod_date=$(printf '%s\n' "$line" | awk '{print $2, $3}')
            local hr_size
            hr_size=$(human_readable "$size")
            results+="$(printf "%-12s  %-20s  %s" "$hr_size" "$mod_date" "$path")\n"

            # Build JSON
            json_entries+="$(printf '{"path":"%s","size":%s,"human_size":"%s","modified":"%s"},' \
                "$(echo "$path" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g')" "$size" "$hr_size" "$mod_date")"
        done < <($FIND "$vol" -xdev -type f \
            ! -path '*/@eaDir/*' \
            ! -path '*/#recycle/*' \
            ! -path '*/#snapshot/*' \
            ! -path '*/\@tmp/*' \
            -printf '%s %TY-%Tm-%Td %TH:%TM %p\n' 2>/dev/null | \
            $SORT -rn | head -n "$TOP_N")
    done

    if [ -z "$results" ]; then
        warn "No files found."
        return
    fi

    # Display results
    print_subheader "Top ${TOP_N} Largest Files"
    echo -e "${BOLD}$(printf "%-12s  %-20s  %s" "SIZE" "MODIFIED" "PATH")${RESET}"
    echo "────────────────────────────────────────────────────────────────────"
    echo -e "$results"

    # Write outputs
    json_entries="${json_entries%,}"
    write_json "$MODULE" "[${json_entries}]"
    echo -e "$results" > "${REPORT_DIR}/${MODULE}.txt"

    success "Results written to ${REPORT_DIR}/${MODULE}.json"
}

main
