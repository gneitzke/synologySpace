#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# utils.sh — Shared utility functions for Synology Space Analyzer
#
# Provides common helpers used by all analysis modules:
#   - Volume detection, root checks, disk usage queries
#   - Human-readable size formatting
#   - Formatted output (headers, info/warn/error messages)
#   - JSON and text report output helpers
#
# Sourced by: analyze.sh, modules/*.sh
# Requires:  bash 4+, awk, df
# ─────────────────────────────────────────────────────────────

_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_LIB_DIR}/colors.sh"

# Prefer full GNU coreutils over BusyBox (Synology ships both)
if [ -x /usr/bin/find ]; then
    FIND=/usr/bin/find
else
    FIND=find
fi
if [ -x /usr/bin/stat ]; then
    STAT=/usr/bin/stat
else
    STAT=stat
fi
if [ -x /usr/bin/sort ]; then
    SORT=/usr/bin/sort
else
    SORT=sort
fi
if [ -x /usr/bin/du ]; then
    DU=/usr/bin/du
else
    DU=du
fi

REPORT_DIR="/tmp/synology-space-report"

# Ensure report directory exists with restricted permissions
ensure_report_dir() {
    mkdir -p "$REPORT_DIR"
    chmod 700 "$REPORT_DIR" 2>/dev/null || true
}

# Convert bytes to human-readable format
human_readable() {
    local bytes=$1
    if [ "$bytes" -ge 1099511627776 ] 2>/dev/null; then
        echo "$(awk "BEGIN {printf \"%.1f TB\", $bytes/1099511627776}")"
    elif [ "$bytes" -ge 1073741824 ] 2>/dev/null; then
        echo "$(awk "BEGIN {printf \"%.1f GB\", $bytes/1073741824}")"
    elif [ "$bytes" -ge 1048576 ] 2>/dev/null; then
        echo "$(awk "BEGIN {printf \"%.1f MB\", $bytes/1048576}")"
    elif [ "$bytes" -ge 1024 ] 2>/dev/null; then
        echo "$(awk "BEGIN {printf \"%.1f KB\", $bytes/1024}")"
    else
        echo "${bytes} B"
    fi
}

# Print a section header
print_header() {
    local title="$1"
    echo ""
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}${CYAN}  $title${RESET}"
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════${RESET}"
    echo ""
}

# Print a sub-header
print_subheader() {
    local title="$1"
    echo -e "${BOLD}${YELLOW}--- $title ---${RESET}"
}

# Print an info message
info() {
    echo -e "${BLUE}[INFO]${RESET} $1"
}

# Print a warning message
warn() {
    echo -e "${YELLOW}[WARN]${RESET} $1"
}

# Print an error message
error() {
    echo -e "${RED}[ERROR]${RESET} $1"
}

# Print a success message
success() {
    echo -e "${GREEN}[OK]${RESET} $1"
}

# Detect Synology volumes
detect_volumes() {
    local volumes=()
    for v in /volume[0-9]*; do
        [ -d "$v" ] && volumes+=("$v")
    done
    if [ ${#volumes[@]} -eq 0 ]; then
        warn "No /volumeN directories found. Using / as fallback."
        volumes=("/")
    fi
    echo "${volumes[@]}"
}

# Check if running as root
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        warn "Not running as root. Some results may be incomplete."
        warn "Re-run with: sudo $0"
        return 1
    fi
    return 0
}

# Write JSON output for a module
write_json() {
    local module="$1"
    local content="$2"
    ensure_report_dir
    echo "$content" > "${REPORT_DIR}/${module}.json"
}

# Write text output for a module
write_text() {
    local module="$1"
    local content="$2"
    ensure_report_dir
    echo "$content" > "${REPORT_DIR}/${module}.txt"
}

# Get disk usage summary for a path
get_disk_usage() {
    local path="$1"
    df -h "$path" 2>/dev/null | tail -1
}
