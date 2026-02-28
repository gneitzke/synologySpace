#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# logs.sh — Find oversized log files on Synology
# Part of Synology Space Analyzer
#
# Scans common log directories (/var/log, package stores, Docker
# data dirs) for log files exceeding SIZE_THRESHOLD (default 10 MB).
# Marks files as [SAFE] when they match well-known rotatable
# patterns (*.log, *.gz, syslog, etc.).
#
# Usage: bash logs.sh [SIZE_THRESHOLD_BYTES]
# Requires: find, sort, awk
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/utils.sh"

MODULE="logs"
SIZE_THRESHOLD="${1:-10485760}"  # Default: flag logs >= 10MB

main() {
    print_header "Log Files Analysis"
    info "Scanning for oversized log files (threshold: $(human_readable $SIZE_THRESHOLD))..."

    local log_dirs=(
        "/var/log"
        "/var/services/homes"
        "/var/packages"
    )

    # Add volume-specific log locations
    local volumes
    read -ra volumes <<< "$(detect_volumes)"
    for vol in "${volumes[@]}"; do
        [ -d "${vol}/@appstore" ] && log_dirs+=("${vol}/@appstore")
        [ -d "${vol}/docker" ] && log_dirs+=("${vol}/docker")
    done

    local text_output=""
    local json_entries=""
    local total_log_size=0
    local oversized_count=0

    for log_dir in "${log_dirs[@]}"; do
        [ ! -d "$log_dir" ] && continue

        while IFS= read -r line; do
            [ -z "$line" ] && continue
            local size path
            size=$(printf '%s\n' "$line" | awk '{print $1}')
            path=$(printf '%s\n' "$line" | awk '{for(i=2;i<=NF;i++) printf "%s ", $i; print ""}' | sed 's/ *$//')

            [ -z "$size" ] && continue
            [ "$size" -lt "$SIZE_THRESHOLD" ] 2>/dev/null && continue

            local hr_size
            hr_size=$(human_readable "$size")
            total_log_size=$((total_log_size + size))
            oversized_count=$((oversized_count + 1))

            # Heuristic: well-known log patterns are safe to truncate/remove
            local safe="false"
            case "$path" in
                *.log|*.log.[0-9]*|*syslog*|*messages*|*kern.log*|*auth.log*)
                    safe="true" ;;
                *.gz|*.bz2|*.xz|*.zip)
                    safe="true" ;;  # compressed old logs can be removed
            esac

            local safe_marker=""
            [ "$safe" = "true" ] && safe_marker="${GREEN}[SAFE]${RESET} "

            text_output+="$(printf "  %s%-10s  %s\n" "$safe_marker" "$hr_size" "$path")"

            json_entries+="$(printf '{"path":"%s","size_bytes":%s,"human_size":"%s","safe_to_clean":%s},' \
                "$(echo "$path" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g')" "$size" "$hr_size" "$safe")"

        done < <($FIND "$log_dir" -xdev -type f \( -name "*.log" -o -name "*.log.*" -o -name "syslog*" \
            -o -name "messages*" -o -name "*.gz" -o -name "*.old" -o -name "*.1" \
            -o -name "*.2" -o -name "*.3" -o -name "*.err" -o -name "*.out" \) \
            -printf '%s %p\n' 2>/dev/null | $SORT -rn)
    done

    print_subheader "Oversized Log Files"
    if [ "$oversized_count" -gt 0 ]; then
        echo -e "${BOLD}$(printf "  %-10s  %s" "SIZE" "PATH")${RESET}"
        echo "  ────────────────────────────────────────────────────────────"
        echo -e "$text_output"
        echo ""
        echo -e "  ${BOLD}Total log space: $(human_readable $total_log_size) across ${oversized_count} files${RESET}"
        echo -e "  ${DIM}[SAFE] = likely safe to truncate or remove${RESET}"
    else
        success "No oversized log files found."
    fi

    json_entries="${json_entries%,}"
    write_json "$MODULE" "$(printf '{"logs":[%s],"total_size_bytes":%d,"oversized_count":%d,"threshold_bytes":%d}' \
        "$json_entries" "$total_log_size" "$oversized_count" "$SIZE_THRESHOLD")"
    echo -e "$text_output" > "${REPORT_DIR}/${MODULE}.txt"

    success "Results written to ${REPORT_DIR}/${MODULE}.json"
}

main
