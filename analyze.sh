#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# analyze.sh — Synology Space Analyzer (main entry point)
#
# Orchestrates all analysis modules and generates a comprehensive
# disk-usage report. Designed to run directly on a Synology NAS
# (usually deployed via run.sh over SSH).
#
# Usage:
#   sudo ./analyze.sh                  # Run all modules
#   sudo ./analyze.sh --module docker  # Run a specific module
#   sudo ./analyze.sh --report         # Run analysis + Python report
#   sudo ./analyze.sh --cleanup        # Run analysis + interactive cleanup
#   sudo ./analyze.sh --help           # Show usage
#
# Output: JSON + text files in /tmp/synology-space-report/
# Requires: bash 4+, root recommended for full results
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/utils.sh"

MODULES_DIR="${SCRIPT_DIR}/modules"
REPORT_DIR="/tmp/synology-space-report"

ALL_MODULES=(
    "large_files"
    "large_dirs"
    "duplicates"
    "snapshots"
    "docker"
    "recycle_bins"
    "logs"
)

usage() {
    echo "Synology Space Analyzer"
    echo ""
    echo "Usage: sudo $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --module <name>   Run a specific module only"
    echo "  --list            List available modules"
    echo "  --report          Generate Python report after analysis"
    echo "  --cleanup         Launch interactive cleanup after analysis"
    echo "  --help            Show this help message"
    echo ""
    echo "Available modules: ${ALL_MODULES[*]}"
}

list_modules() {
    echo "Available modules:"
    for mod in "${ALL_MODULES[@]}"; do
        echo "  - $mod"
    done
}

run_module() {
    local module="$1"
    local script="${MODULES_DIR}/${module}.sh"

    if [ ! -f "$script" ]; then
        error "Module not found: $module"
        error "Available modules: ${ALL_MODULES[*]}"
        return 1
    fi

    bash "$script"
}

run_all_modules() {
    print_header "Synology Space Analyzer"

    # Show disk overview first
    print_subheader "Disk Overview"
    df -h 2>/dev/null | grep -E '^/dev/|^Filesystem' || df -h
    echo ""

    check_root

    ensure_report_dir
    info "Report directory: ${REPORT_DIR}"
    echo ""

    local failed_modules=()
    for mod in "${ALL_MODULES[@]}"; do
        echo ""
        info "Running module: ${mod}..."
        echo "────────────────────────────────────────────────────────────────────"
        if ! run_module "$mod"; then
            warn "Module '${mod}' encountered errors (continuing...)"
            failed_modules+=("$mod")
        fi
    done

    echo ""
    print_header "Analysis Complete"

    if [ ${#failed_modules[@]} -gt 0 ]; then
        warn "Modules with errors: ${failed_modules[*]}"
    fi

    info "Raw results saved to: ${REPORT_DIR}/"
    echo ""
    echo -e "${BOLD}Next steps:${RESET}"
    echo "  1. Review the analysis above"
    echo "  2. Run the report:  python3 ${SCRIPT_DIR}/report.py"
    echo "  3. View treemap:    python3 ${SCRIPT_DIR}/treemap.py --open"
    echo "  4. Start cleanup:   python3 ${SCRIPT_DIR}/cleanup.py"
    echo "  5. Dry-run cleanup: python3 ${SCRIPT_DIR}/cleanup.py --dry-run"
}

# Parse arguments
RUN_REPORT=false
RUN_CLEANUP=false
SPECIFIC_MODULE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --module)
            if [ $# -lt 2 ]; then
                error "--module requires a module name"
                exit 1
            fi
            SPECIFIC_MODULE="$2"
            shift 2
            ;;
        --list)
            list_modules
            exit 0
            ;;
        --report)
            RUN_REPORT=true
            shift
            ;;
        --cleanup)
            RUN_CLEANUP=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Execute
if [ -n "$SPECIFIC_MODULE" ]; then
    run_module "$SPECIFIC_MODULE"
else
    run_all_modules
fi

# Optional post-analysis steps
if [ "$RUN_REPORT" = true ]; then
    echo ""
    info "Generating report..."
    python3 "${SCRIPT_DIR}/report.py"
fi

if [ "$RUN_CLEANUP" = true ]; then
    echo ""
    info "Starting interactive cleanup..."
    python3 "${SCRIPT_DIR}/cleanup.py"
fi
