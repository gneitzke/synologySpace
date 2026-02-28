#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# run.sh — Remote Runner for Synology Space Analyzer
#
# Just run it:
#   ./run.sh admin@your-nas       # first time — remembers the target
#   ./run.sh                      # re-run — uses saved target
#   ./run.sh --cleanup            # re-run with guided cleanup
#
# What it does:
#   1. Deploys scripts to the NAS via SSH
#   2. Runs analysis (with sudo for full disk access)
#   3. Generates reports + treemap on the NAS
#   4. Pulls everything back and opens the dashboard in your browser
#
# Prerequisites: SSH access to the NAS, python3 on the NAS
# ─────────────────────────────────────────────────────────────
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCAL_REPORT_DIR="${SCRIPT_DIR}/reports"
REMOTE_DIR="/tmp/synology-space-analyzer"
REMOTE_REPORT_DIR="/tmp/synology-space-report"
TARGET_FILE="${SCRIPT_DIR}/.target"

# ─── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

info()    { echo -e "${CYAN}›${RESET} $1"; }
success() { echo -e "${GREEN}✓${RESET} $1"; }
warn()    { echo -e "${YELLOW}⚠${RESET} $1"; }
error()   { echo -e "${RED}✗${RESET} $1"; }

usage() {
    echo -e "${BOLD}Synology Space Analyzer${RESET}"
    echo ""
    echo "Usage: $0 [user@host] [OPTIONS]"
    echo ""
    echo "  If user@host is omitted, the last-used target is reused."
    echo "  On first run, you'll be prompted to enter it."
    echo ""
    echo "Options:"
    echo "  --cleanup           Run interactive cleanup after analysis"
    echo "  --dry-run           Run cleanup in dry-run mode (no changes)"
    echo "  --module <name>     Run a specific analysis module only"
    echo "  --report-only       Skip analysis; pull existing reports"
    echo "  --no-sudo           Don't use sudo (SSH user is root)"
    echo "  --no-open           Don't auto-open dashboard in browser"
    echo "  --setup-keys        Set up SSH keys for passwordless login"
    echo "  --port <port>       SSH port (default: 22)"
    echo "  --help              Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 admin@nas              # First run"
    echo "  $0                        # Re-run (remembers target)"
    echo "  $0 --cleanup              # Re-run + cleanup"
    echo "  $0 admin@nas --port 2222  # Custom SSH port"
}

# ─── Parse args ───────────────────────────────────────────────
RUN_CLEANUP=false
DRY_RUN=false
REPORT_ONLY=false
AUTO_OPEN=true
SSH_PORT=22
SPECIFIC_MODULE=""
USE_SUDO=true
SETUP_KEYS=false
SSH_TARGET=""

while [ $# -gt 0 ]; do
    case "$1" in
        --cleanup)     RUN_CLEANUP=true; shift ;;
        --dry-run)     RUN_CLEANUP=true; DRY_RUN=true; shift ;;
        --report-only) REPORT_ONLY=true; shift ;;
        --no-open)     AUTO_OPEN=false; shift ;;
        --no-sudo)     USE_SUDO=false; shift ;;
        --setup-keys)  SETUP_KEYS=true; shift ;;
        --help|-h)     usage; exit 0 ;;
        --port)
            if [ $# -lt 2 ]; then error "--port requires a value"; exit 1; fi
            SSH_PORT="$2"; shift 2 ;;
        --module)
            if [ $# -lt 2 ]; then error "--module requires a name"; exit 1; fi
            SPECIFIC_MODULE="$2"; shift 2 ;;
        -*)
            error "Unknown option: $1"; usage; exit 1 ;;
        *)
            # Positional arg = SSH target
            if [ -z "$SSH_TARGET" ]; then
                SSH_TARGET="$1"; shift
            else
                error "Unexpected argument: $1"; usage; exit 1
            fi ;;
    esac
done

# ─── Resolve SSH target (saved or prompted) ──────────────────
if [ -z "$SSH_TARGET" ]; then
    # Try saved target
    if [ -f "$TARGET_FILE" ]; then
        SSH_TARGET=$(cat "$TARGET_FILE")
        info "Using saved target: ${BOLD}${SSH_TARGET}${RESET}"
    else
        echo -e "${BOLD}Synology Space Analyzer${RESET}"
        echo ""
        echo -n "Enter your NAS SSH target (e.g. admin@192.168.1.100): "
        read -r SSH_TARGET
        if [ -z "$SSH_TARGET" ]; then
            error "No target provided."
            exit 1
        fi
    fi
fi

# Save target for next time
echo "$SSH_TARGET" > "$TARGET_FILE"

SSH_CMD="ssh -p ${SSH_PORT} -o ConnectTimeout=10"

# ─── Handle --setup-keys ─────────────────────────────────────
if [ "$SETUP_KEYS" = true ]; then
    info "Setting up SSH keys for ${SSH_TARGET}..."
    ssh-copy-id -p ${SSH_PORT} "${SSH_TARGET}"
    success "SSH keys configured! Future runs won't need a password."
    exit 0
fi

# ─── SSH key check + auto-offer setup ────────────────────────
HAS_KEYS=false
if ssh -p ${SSH_PORT} -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new "${SSH_TARGET}" "true" 2>/dev/null; then
    HAS_KEYS=true
else
    echo ""
    warn "No SSH keys configured — you'll be prompted for your password."
    echo -n "  Set up passwordless SSH now? [Y/n] "
    read -r REPLY
    if [ -z "$REPLY" ] || [[ "$REPLY" =~ ^[Yy] ]]; then
        ssh-copy-id -p ${SSH_PORT} "${SSH_TARGET}"
        if ssh -p ${SSH_PORT} -o BatchMode=yes "${SSH_TARGET}" "true" 2>/dev/null; then
            HAS_KEYS=true
            success "SSH keys configured!"
        else
            warn "Key setup may have failed — continuing with password prompts."
        fi
    fi
    echo ""
fi

SUDO_CMD=""
if [ "$USE_SUDO" = true ]; then
    SUDO_CMD="sudo"
fi

# ─── Banner ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}  📊 Synology Space Analyzer${RESET}"
echo -e "${DIM}  Target: ${SSH_TARGET}  Port: ${SSH_PORT}${RESET}"
echo ""

# ─── Step 1: Deploy ──────────────────────────────────────────
if [ "$REPORT_ONLY" = false ]; then
    info "[1/3] Deploying scripts..."

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

    # ─── Step 2: Analyze + report ─────────────────────────────
    info "[2/3] Running analysis..."
    echo ""

    ANALYZE_ARGS=""
    if [ -n "$SPECIFIC_MODULE" ]; then
        ANALYZE_ARGS="--module ${SPECIFIC_MODULE}"
    fi

    ${SSH_CMD} -tt "${SSH_TARGET}" "cd '${REMOTE_DIR}' && ${SUDO_CMD} bash analyze.sh ${ANALYZE_ARGS}; python3 report.py 2>&1; python3 treemap.py 2>&1" || {
        warn "Analysis exited with errors (some modules may require root)."
    }

    echo ""
fi

# ─── Step 3: Pull reports ────────────────────────────────────
info "[3/3] Downloading reports..."
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
else
    rm -f "${LOCAL_REPORT_DIR}/.download.tar"
    error "No reports found. Run without --report-only first."
    exit 1
fi

# ─── Open dashboard in browser ───────────────────────────────
DASHBOARD_FILE="${LOCAL_REPORT_DIR}/report.html"
TREEMAP_FILE="${LOCAL_REPORT_DIR}/treemap.html"

if [ "$AUTO_OPEN" = true ]; then
    if [ -f "$DASHBOARD_FILE" ]; then
        success "Opening dashboard..."
        open "$DASHBOARD_FILE" 2>/dev/null || true
    elif [ -f "$TREEMAP_FILE" ]; then
        success "Opening treemap..."
        open "$TREEMAP_FILE" 2>/dev/null || true
    fi
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

    ${SSH_CMD} -t "${SSH_TARGET}" "cd '${REMOTE_DIR}' && ${SUDO_CMD} python3 cleanup.py ${CLEANUP_ARGS}"

    echo ""
    info "Post-cleanup disk usage:"
    ${SSH_CMD} "${SSH_TARGET}" "df -h | grep -E '^/dev/|^Filesystem'" || true
fi

# ─── Clean up remote temp files ──────────────────────────────
if [ "$REPORT_ONLY" = false ]; then
    ${SSH_CMD} "${SSH_TARGET}" "rm -rf '${REMOTE_DIR}'" 2>/dev/null || true
fi

# ─── Done ────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}  ✓ Done!${RESET}  Reports: ${DIM}${LOCAL_REPORT_DIR}/${RESET}"
if [ -f "$DASHBOARD_FILE" ]; then
    echo -e "          Dashboard: ${DIM}file://${DASHBOARD_FILE}${RESET}"
fi
echo ""
echo -e "  ${DIM}Re-run:  $0${RESET}"
echo -e "  ${DIM}Cleanup: $0 --cleanup${RESET}"
echo ""
