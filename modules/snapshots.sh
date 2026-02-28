#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# snapshots.sh — Analyze Btrfs snapshots on Synology
# Part of Synology Space Analyzer
#
# Enumerates Btrfs snapshot subvolumes on each volume, reports
# creation dates and exclusive (unique) space consumed. Flags
# snapshots older than MAX_AGE_DAYS for potential removal.
#
# Requires btrfs-progs and root access. Gracefully skips if
# btrfs is unavailable or the user is not root.
#
# Usage: bash snapshots.sh [MAX_AGE_DAYS]
# Requires: btrfs, root access
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/utils.sh"

MODULE="snapshots"
MAX_AGE_DAYS="${1:-30}"

main() {
    print_header "Btrfs Snapshots Analysis"

    # Check if btrfs is available
    if ! command -v btrfs &>/dev/null; then
        warn "btrfs command not found. Skipping snapshot analysis."
        write_json "$MODULE" '{"available":false,"snapshots":[]}'
        return
    fi

    check_root || {
        error "Root access required for snapshot analysis."
        return
    }

    local volumes
    read -ra volumes <<< "$(detect_volumes)"

    local json_entries=""
    local text_output=""
    local total_snapshots=0
    local old_snapshots=0
    # GNU date (-d) vs BSD/macOS date (-v) for portability
    local cutoff_date
    cutoff_date=$(date -d "-${MAX_AGE_DAYS} days" +%Y-%m-%d 2>/dev/null || \
                  date -v-${MAX_AGE_DAYS}d +%Y-%m-%d 2>/dev/null || true)

    for vol in "${volumes[@]}"; do
        info "Checking snapshots on ${vol}..."

        # List btrfs subvolumes (snapshots are a type of subvolume)
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            local snap_id gen top_level path
            snap_id=$(echo "$line" | awk '{print $2}')
            gen=$(echo "$line" | awk '{print $4}')
            top_level=$(echo "$line" | awk '{print $6}')
            path=$(printf '%s\n' "$line" | awk '{for(i=9;i<=NF;i++) printf "%s%s", (i>9?" ":""), $i; print ""}')

            # Try to get snapshot creation date
            local snap_date=""
            local snap_info
            if snap_info=$(btrfs subvolume show "${vol}/${path}" 2>/dev/null); then
                snap_date=$(echo "$snap_info" | grep -i "creation time" | awk -F: '{print $2":"$3":"$4}' | xargs)
            fi

            # Exclusive size via qgroup — only available if quotas are enabled
            local exclusive_size="unknown"
            local exclusive_bytes=0
            if btrfs qgroup show "${vol}" &>/dev/null; then
                local qgroup_line
                qgroup_line=$(btrfs qgroup show -r "${vol}" 2>/dev/null | grep "0/${snap_id}" | head -1)
                if [ -n "$qgroup_line" ]; then
                    exclusive_bytes=$(echo "$qgroup_line" | awk '{print $3}')
                    exclusive_size=$(human_readable "$exclusive_bytes")
                fi
            fi

            total_snapshots=$((total_snapshots + 1))

            # Check if snapshot is old
            local is_old="false"
            if [ -n "$snap_date" ] && [ -n "$cutoff_date" ]; then
                local snap_date_short
                snap_date_short=$(echo "$snap_date" | awk '{print $1}')
                if [[ "$snap_date_short" < "$cutoff_date" ]]; then
                    is_old="true"
                    old_snapshots=$((old_snapshots + 1))
                fi
            fi

            local age_marker=""
            [ "$is_old" = "true" ] && age_marker="${RED}[OLD]${RESET} "

            text_output+="$(printf "  %sID: %-6s  Path: %-40s  Date: %-20s  Exclusive: %s\n" \
                "$age_marker" "$snap_id" "$path" "${snap_date:-unknown}" "$exclusive_size")"

            json_entries+="$(printf '{"id":"%s","path":"%s","volume":"%s","date":"%s","exclusive_bytes":%s,"is_old":%s},' \
                "$snap_id" "$(echo "$path" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g')" "$vol" "${snap_date:-unknown}" "$exclusive_bytes" "$is_old")"

        done < <(btrfs subvolume list -s "$vol" 2>/dev/null)
    done

    print_subheader "Snapshots Summary"
    echo -e "  Total snapshots: ${BOLD}${total_snapshots}${RESET}"
    echo -e "  Snapshots older than ${MAX_AGE_DAYS} days: ${BOLD}${RED}${old_snapshots}${RESET}"
    echo ""

    if [ -n "$text_output" ]; then
        print_subheader "Snapshot Details"
        echo -e "$text_output"
    else
        info "No snapshots found."
    fi

    json_entries="${json_entries%,}"
    write_json "$MODULE" "$(printf '{"available":true,"total":%d,"old_count":%d,"max_age_days":%d,"snapshots":[%s]}' \
        "$total_snapshots" "$old_snapshots" "$MAX_AGE_DAYS" "$json_entries")"
    echo -e "$text_output" > "${REPORT_DIR}/${MODULE}.txt"

    success "Results written to ${REPORT_DIR}/${MODULE}.json"
}

main
