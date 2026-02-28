#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# run.sh — Remote Runner for Synology Space Analyzer
#
# Orchestrates a full analysis session from your local machine:
#   1. Deploys scripts to the NAS via SSH (tar pipe, no scp needed)
#   2. Runs analyze.sh on the NAS (with sudo for full access)
#   3. Generates reports (report.py + treemap.py) on the NAS
#   4. Pulls report artifacts back to ./reports/ locally
#   5. Opens the treemap in your browser (macOS `open`)
#   6. Optionally launches interactive cleanup over SSH
#
# Usage:
#   ./run.sh user@synology                 # Full analysis + treemap
#   ./run.sh user@synology --cleanup       # Analysis + interactive cleanup
#   ./run.sh user@synology --dry-run       # Analysis + dry-run cleanup
#   ./run.sh user@synology --module docker # Run a single module
#   ./run.sh user@synology --report-only   # Pull existing reports only
#
# Prerequisites: SSH access to the NAS, bash, python3 on the NAS
# Tip: ssh-copy-id user@nas to avoid repeated password prompts
# ─────────────────────────────────────────────────────────────
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCAL_REPORT_DIR="${SCRIPT_DIR}/reports"
REMOTE_DIR="/tmp/synology-space-analyzer"
REMOTE_REPORT_DIR="/tmp/synology-space-report"

# ─── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[LOCAL]${RESET} $1"; }
success() { echo -e "${GREEN}[LOCAL]${RESET} $1"; }
warn()    { echo -e "${YELLOW}[LOCAL]${RESET} $1"; }
error()   { echo -e "${RED}[LOCAL]${RESET} $1"; }

usage() {
    echo -e "${BOLD}Synology Space Analyzer — Remote Runner${RESET}"
    echo ""
    echo "Usage: $0 <user@host> [OPTIONS]"
    echo ""
    echo "Arguments:"
    echo "  user@host           SSH target (e.g. admin@192.168.1.100)"
    echo ""
    echo "Options:"
    echo "  --cleanup           Run interactive cleanup after analysis"
    echo "  --dry-run           Run cleanup in dry-run mode (no changes)"
    echo "  --module <name>     Run a specific analysis module only"
    echo "  --report-only       Skip analysis; pull existing reports"
    echo "  --no-sudo           Don't use sudo (when SSH user is already root)"
    echo "  --no-open           Don't auto-open treemap in browser"
    echo "  --setup-keys        Set up SSH keys for passwordless login and exit"
    echo "  --port <port>       SSH port (default: 22)"
    echo "  --help              Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 admin@nas                    # Analyze and view treemap"
    echo "  $0 admin@nas --cleanup          # Analyze + guided cleanup"
    echo "  $0 admin@nas --module docker    # Docker analysis only"
    echo "  $0 admin@nas --port 2222        # Custom SSH port"
    echo "  $0 root@nas --no-sudo           # SSH as root directly"
    echo ""
    echo "Tip: Set up SSH keys to avoid repeated password prompts:"
    echo "  ssh-copy-id -p <port> user@nas"
}

# ─── Parse args ───────────────────────────────────────────────
if [ $# -lt 1 ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    usage
    exit 0
fi

SSH_TARGET="$1"
shift

RUN_CLEANUP=false
DRY_RUN=false
REPORT_ONLY=false
AUTO_OPEN=true
SSH_PORT=22
SPECIFIC_MODULE=""
USE_SUDO=true
SETUP_KEYS=false

while [ $# -gt 0 ]; do
    case "$1" in
        --cleanup)    RUN_CLEANUP=true; shift ;;
        --dry-run)    RUN_CLEANUP=true; DRY_RUN=true; shift ;;
        --report-only) REPORT_ONLY=true; shift ;;
        --no-open)    AUTO_OPEN=false; shift ;;
        --no-sudo)    USE_SUDO=false; shift ;;
        --setup-keys) SETUP_KEYS=true; shift ;;
        --port)
            if [ $# -lt 2 ]; then error "--port requires a value"; exit 1; fi
            SSH_PORT="$2"; shift 2 ;;
        --module)
            if [ $# -lt 2 ]; then error "--module requires a name"; exit 1; fi
            SPECIFIC_MODULE="$2"; shift 2 ;;
        *) error "Unknown option: $1"; usage; exit 1 ;;
    esac
done

SSH_CMD="ssh -p ${SSH_PORT} -o ConnectTimeout=10"

# ─── Handle --setup-keys (post-parse, needs SSH_TARGET) ──────
if [ "$SETUP_KEYS" = true ]; then
    info "Setting up SSH keys for ${SSH_TARGET}..."
    ssh-copy-id -p ${SSH_PORT} "${SSH_TARGET}"
    success "SSH keys configured! You can now run without password prompts."
    exit 0
fi

# ─── SSH key detection ───────────────────────────────────────
if ! ssh -p ${SSH_PORT} -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new "${SSH_TARGET}" "true" 2>/dev/null; then
    warn "No SSH key configured for ${SSH_TARGET}."
    info "You'll be prompted for your password multiple times."
    info "To set up passwordless SSH (recommended):"
    echo "    ssh-copy-id -p ${SSH_PORT} ${SSH_TARGET}"
    echo "    # or: $0 ${SSH_TARGET} --setup-keys"
    echo ""
fi

SUDO_CMD=""
if [ "$USE_SUDO" = true ]; then
    SUDO_CMD="sudo"
fi

# ─── Deploy scripts (tar pipe, no TTY needed) ────────────────
if [ "$REPORT_ONLY" = false ]; then
    info "[1/3] Deploying scripts to ${SSH_TARGET} (port ${SSH_PORT})..."

    # COPYFILE_DISABLE=1 suppresses macOS resource-fork ._* files in tar
    COPYFILE_DISABLE=1 tar cf - -C "${SCRIPT_DIR}" \
        analyze.sh report.py treemap.py cleanup.py \
        lib/utils.sh lib/colors.sh \
        modules/large_files.sh modules/large_dirs.sh modules/duplicates.sh \
        modules/snapshots.sh modules/docker.sh modules/recycle_bins.sh modules/logs.sh \
    | ${SSH_CMD} "${SSH_TARGET}" "
        mkdir -p '${REMOTE_DIR}/modules' '${REMOTE_DIR}/lib' && \
        tar xf - -C '${REMOTE_DIR}' && \
        chmod +x '${REMOTE_DIR}/analyze.sh' '${REMOTE_DIR}'/modules/*.sh '${REMOTE_DIR}'/lib/*.sh '${REMOTE_DIR}'/*.py
    "

    if [ $? -ne 0 ]; then
        error "Deploy failed. Check SSH connectivity."
        exit 1
    fi
    success "Scripts deployed"

    # ─── Run analysis + generate reports (same SSH session) ──
    echo ""
    info "[2/3] Running analysis (you may be prompted for your sudo password)..."
    echo ""

    ANALYZE_ARGS=""
    if [ -n "$SPECIFIC_MODULE" ]; then
        ANALYZE_ARGS="--module ${SPECIFIC_MODULE}"
    fi

    # -tt forces TTY allocation for sudo password prompt
    # Report generation runs in the same SSH session to reduce password prompts
    ${SSH_CMD} -tt "${SSH_TARGET}" "cd '${REMOTE_DIR}' && ${SUDO_CMD} bash analyze.sh ${ANALYZE_ARGS}; python3 report.py 2>&1; python3 treemap.py 2>&1" || {
        warn "Analysis exited with errors (some modules may require root)."
    }

    success "Analysis complete"
fi

# ─── Pull reports back to Mac ─────────────────────────────────
echo ""
info "[3/3] Pulling reports to ${LOCAL_REPORT_DIR}..."
mkdir -p "${LOCAL_REPORT_DIR}"

${SSH_CMD} "${SSH_TARGET}" "
    if [ -d '${REMOTE_REPORT_DIR}' ]; then
        tar cf - -C '${REMOTE_REPORT_DIR}' . 2>/dev/null
    else
        echo 'NO_REPORTS' >&2
    fi
" > "${LOCAL_REPORT_DIR}/.download.tar" 2>/dev/null

if [ -s "${LOCAL_REPORT_DIR}/.download.tar" ]; then
    tar xf "${LOCAL_REPORT_DIR}/.download.tar" -C "${LOCAL_REPORT_DIR}/" 2>/dev/null
    rm -f "${LOCAL_REPORT_DIR}/.download.tar"
    success "Reports saved to ${LOCAL_REPORT_DIR}/"

    echo ""
    info "Downloaded reports:"
    ls -lh "${LOCAL_REPORT_DIR}/" 2>/dev/null | tail -n +2 | while read -r line; do
        fname=$(echo "$line" | awk '{print $NF}')
        fsize=$(echo "$line" | awk '{print $5}')
        printf "  %-40s %s\n" "$fname" "$fsize"
    done
else
    rm -f "${LOCAL_REPORT_DIR}/.download.tar"
    warn "No reports found on NAS. Run analysis first (without --report-only)."
fi

# ─── Open treemap locally ────────────────────────────────────
TREEMAP_FILE="${LOCAL_REPORT_DIR}/treemap.html"
if [ -f "$TREEMAP_FILE" ] && [ "$AUTO_OPEN" = true ]; then
    echo ""
    success "Opening treemap in browser..."
    open "$TREEMAP_FILE"
fi

# ─── Interactive cleanup (over SSH) ──────────────────────────
if [ "$RUN_CLEANUP" = true ]; then
    echo ""
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}${CYAN}  Interactive Cleanup on ${SSH_TARGET}${RESET}"
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════${RESET}"
    echo ""

    CLEANUP_ARGS=""
    if [ "$DRY_RUN" = true ]; then
        CLEANUP_ARGS="--dry-run"
    fi

    ${SSH_CMD} -t "${SSH_TARGET}" "cd ${REMOTE_DIR} && ${SUDO_CMD} python3 cleanup.py ${CLEANUP_ARGS}"

    # Pull updated disk info after cleanup
    echo ""
    info "Post-cleanup disk usage:"
    ${SSH_CMD} "${SSH_TARGET}" "df -h | grep -E '^/dev/|^Filesystem'" || true
fi

# ─── Clean up remote temp files ──────────────────────────────
if [ "$REPORT_ONLY" = false ]; then
    ${SSH_CMD} "${SSH_TARGET}" "rm -rf '${REMOTE_DIR}'" 2>/dev/null || true
fi

# ─── Summary ─────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  Done!${RESET}"
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "  Reports:  ${LOCAL_REPORT_DIR}/"
[ -f "$TREEMAP_FILE" ] && echo -e "  Treemap:  file://${TREEMAP_FILE}"
echo -e "  Summary:  ${LOCAL_REPORT_DIR}/summary.json"
echo ""
echo -e "  Re-run:   $0 ${SSH_TARGET}"
echo -e "  Cleanup:  $0 ${SSH_TARGET} --cleanup"
echo -e "  Dry run:  $0 ${SSH_TARGET} --dry-run"
echo ""
echo -e "  ${BOLD}Tip:${RESET} Set up SSH keys to skip password prompts:"
echo -e "    ssh-copy-id -p ${SSH_PORT} ${SSH_TARGET}"
echo ""
