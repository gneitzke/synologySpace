#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# docker.sh — Analyze Docker disk usage on Synology
# Part of Synology Space Analyzer
#
# Reports reclaimable Docker resources: dangling images, stopped
# containers, unused volumes, and build cache. Requires Docker
# to be installed and the daemon to be running.
#
# Usage: bash docker.sh
# Requires: docker CLI, running Docker daemon
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/utils.sh"

MODULE="docker"

main() {
    print_header "Docker Disk Usage Analysis"

    if ! command -v docker &>/dev/null; then
        warn "Docker is not installed. Skipping Docker analysis."
        write_json "$MODULE" '{"available":false}'
        return
    fi

    # Check if Docker daemon is running
    if ! docker info &>/dev/null; then
        warn "Docker daemon is not running. Skipping Docker analysis."
        write_json "$MODULE" '{"available":false,"reason":"daemon_not_running"}'
        return
    fi

    local json_output=""
    local text_output=""

    # Overall disk usage
    print_subheader "Docker System Disk Usage"
    local system_df
    system_df=$(docker system df 2>/dev/null)
    echo "$system_df"
    echo ""
    text_output+="$system_df\n\n"

    # Verbose disk usage
    local system_df_v
    system_df_v=$(docker system df -v 2>/dev/null)

    # Dangling images
    print_subheader "Dangling Images (no tag, no container reference)"
    local dangling
    dangling=$(docker images -f "dangling=true" --format "{{.ID}}\t{{.Size}}\t{{.CreatedSince}}" 2>/dev/null)
    if [ -n "$dangling" ]; then
        echo -e "${BOLD}$(printf "%-15s  %-12s  %s" "IMAGE ID" "SIZE" "CREATED")${RESET}"
        echo "────────────────────────────────────────────"
        echo "$dangling" | while IFS=$'\t' read -r id size created; do
            printf "%-15s  %-12s  %s\n" "$id" "$size" "$created"
        done
        text_output+="Dangling images:\n$dangling\n\n"
    else
        info "No dangling images found."
    fi
    echo ""

    # Stopped containers
    print_subheader "Stopped Containers"
    local stopped
    stopped=$(docker ps -a -f "status=exited" -f "status=dead" -f "status=created" \
        --format "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Size}}\t{{.Status}}" 2>/dev/null)
    if [ -n "$stopped" ]; then
        echo -e "${BOLD}$(printf "%-15s  %-25s  %-25s  %-12s  %s" "CONTAINER" "NAME" "IMAGE" "SIZE" "STATUS")${RESET}"
        echo "──────────────────────────────────────────────────────────────────────────────"
        echo "$stopped" | while IFS=$'\t' read -r id name image size status; do
            printf "%-15s  %-25s  %-25s  %-12s  %s\n" "$id" "$name" "$image" "$size" "$status"
        done
        text_output+="Stopped containers:\n$stopped\n\n"
    else
        info "No stopped containers found."
    fi
    echo ""

    # Unused volumes
    print_subheader "Unused Volumes"
    local unused_vols
    unused_vols=$(docker volume ls -f "dangling=true" --format "{{.Name}}\t{{.Driver}}" 2>/dev/null)
    if [ -n "$unused_vols" ]; then
        echo -e "${BOLD}$(printf "%-60s  %s" "VOLUME" "DRIVER")${RESET}"
        echo "────────────────────────────────────────────────────────────────────"
        echo "$unused_vols" | while IFS=$'\t' read -r name driver; do
            printf "%-60s  %s\n" "$name" "$driver"
        done
        text_output+="Unused volumes:\n$unused_vols\n\n"
    else
        info "No unused volumes found."
    fi
    echo ""

    # Build cache
    print_subheader "Build Cache"
    local build_cache
    build_cache=$(docker builder du 2>/dev/null | tail -1)
    if [ -n "$build_cache" ]; then
        echo "$build_cache"
        text_output+="Build cache:\n$build_cache\n"
    else
        info "No build cache info available."
    fi

    # Reclaimable space estimate
    echo ""
    print_subheader "Reclaimable Space Estimate"
    local reclaimable
    reclaimable=$(docker system df --format "{{.Type}}\t{{.Reclaimable}}" 2>/dev/null)
    if [ -n "$reclaimable" ]; then
        echo -e "${BOLD}$(printf "%-15s  %s" "TYPE" "RECLAIMABLE")${RESET}"
        echo "────────────────────────────────"
        echo "$reclaimable" | while IFS=$'\t' read -r dtype recl; do
            printf "%-15s  %s\n" "$dtype" "$recl"
        done
    fi

    # Build JSON output
    local dangling_count stopped_count unused_vol_count
    dangling_count=$(docker images -f "dangling=true" -q 2>/dev/null | wc -l | tr -d ' ')
    stopped_count=$(docker ps -a -f "status=exited" -f "status=dead" -f "status=created" -q 2>/dev/null | wc -l | tr -d ' ')
    unused_vol_count=$(docker volume ls -f "dangling=true" -q 2>/dev/null | wc -l | tr -d ' ')

    write_json "$MODULE" "$(printf '{"available":true,"dangling_images":%d,"stopped_containers":%d,"unused_volumes":%d}' \
        "$dangling_count" "$stopped_count" "$unused_vol_count")"
    echo -e "$text_output" > "${REPORT_DIR}/${MODULE}.txt"

    success "Results written to ${REPORT_DIR}/${MODULE}.json"
}

main
