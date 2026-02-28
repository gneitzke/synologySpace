#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# duplicates.sh — Detect duplicate files by size + MD5 checksum
# Part of Synology Space Analyzer
#
# Two-pass algorithm to find duplicates efficiently:
#   1. Group all files by size (fast inode scan via find)
#   2. For size groups with >1 file, compute MD5 checksums
#   3. Files sharing both size and hash are true duplicates
#
# Only files >= MIN_SIZE (default 1 MB) are checked, since
# small-file duplicates rarely matter for disk reclamation.
#
# Supports: md5sum (Linux/Synology), md5 (macOS), openssl
#
# Usage: bash duplicates.sh [MIN_SIZE_BYTES]
# Requires: find, sort, awk, uniq, md5sum|md5|openssl
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/utils.sh"

MODULE="duplicates"
MIN_SIZE="${1:-1048576}"  # Default: only check files >= 1MB

main() {
    print_header "Duplicate Files Analysis"

    local HASH_CMD=""
    if command -v md5sum &>/dev/null; then
        HASH_CMD="md5sum"
    elif command -v md5 &>/dev/null; then
        HASH_CMD="md5 -r"
    elif command -v openssl &>/dev/null; then
        HASH_CMD="openssl dgst -md5 -r"
    else
        warn "No hashing tool found (md5sum/md5/openssl). Skipping duplicate detection."
        write_json "$MODULE" '{"groups":[],"total_wasted_bytes":0,"error":"no_hash_tool"}'
        return
    fi

    info "Scanning for duplicate files (min size: $(human_readable $MIN_SIZE))..."

    local volumes
    read -ra volumes <<< "$(detect_volumes)"

    # Temp directory for intermediate data; cleaned up on exit
    local tmpdir
    tmpdir=$(mktemp -d)
    trap "rm -rf '$tmpdir'" EXIT

    local size_list="$tmpdir/sizes.txt"    # all files: "size path"
    local dup_sizes="$tmpdir/dup_sizes.txt" # sizes appearing more than once
    local hash_list="$tmpdir/hashes.txt"    # "hash size path" for candidates

    # Step 1: Catalog every file's size across all volumes
    info "Step 1/3: Cataloging file sizes..."
    for vol in "${volumes[@]}"; do
        $FIND "$vol" -xdev -type f -size +"${MIN_SIZE}c" \
            ! -path '*/@eaDir/*' \
            ! -path '*/#recycle/*' \
            ! -path '*/#snapshot/*' \
            -printf '%s %p\n' 2>/dev/null
    done | $SORT -n > "$size_list"

    # Step 2: Extract sizes that appear more than once (potential dupes)
    info "Step 2/3: Finding files with matching sizes..."
    awk '{print $1}' "$size_list" | uniq -d > "$dup_sizes"

    local dup_count
    dup_count=$(wc -l < "$dup_sizes")
    if [ "$dup_count" -eq 0 ]; then
        success "No potential duplicates found."
        write_json "$MODULE" '{"groups":[],"total_wasted_bytes":0}'
        return
    fi

    info "Found ${dup_count} size groups with potential duplicates."

    # Step 3: Hash only the candidate files (same-size groups)
    info "Step 3/3: Computing checksums (this may take a while)..."
    local total_wasted=0
    local json_groups=""
    local text_output=""

    while IFS= read -r dup_size; do
        # Get all files with this size
        grep "^${dup_size} " "$size_list" | awk '{print $2}' | while IFS= read -r filepath; do
            local hash
            hash=$($HASH_CMD "$filepath" 2>/dev/null | awk '{print $1}')
            echo "${hash} ${dup_size} ${filepath}"
        done
    done < "$dup_sizes" | $SORT > "$hash_list"

    # Aggregate files sharing the same hash into duplicate groups
    local prev_hash=""
    local group_files=()
    local group_size=0

    while IFS= read -r line; do
        local hash size filepath
        hash=$(printf '%s\n' "$line" | awk '{print $1}')
        size=$(printf '%s\n' "$line" | awk '{print $2}')
        filepath=$(printf '%s\n' "$line" | awk '{for(i=3;i<=NF;i++) printf "%s ", $i; print ""}' | sed 's/ *$//')

        # When the hash changes, emit the previous group if it had duplicates
        if [ "$hash" != "$prev_hash" ] && [ -n "$prev_hash" ] && [ ${#group_files[@]} -gt 1 ]; then
            local wasted=$(( group_size * (${#group_files[@]} - 1) ))  # all copies minus the original
            total_wasted=$((total_wasted + wasted))

            text_output+="$(printf "\nDuplicate group (hash: %.8s..., %s each, %d copies, %s wasted):\n" \
                "$prev_hash" "$(human_readable $group_size)" "${#group_files[@]}" "$(human_readable $wasted)")"
            local files_json=""
            for f in "${group_files[@]}"; do
                text_output+="  $f\n"
                files_json+="\"$(echo "$f" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g')\","
            done
            files_json="${files_json%,}"
            json_groups+="$(printf '{"hash":"%s","size":%s,"count":%d,"wasted":%d,"files":[%s]},' \
                "$prev_hash" "$group_size" "${#group_files[@]}" "$wasted" "$files_json")"

            group_files=()
        fi

        if [ "$hash" != "$prev_hash" ]; then
            group_files=()
            group_size=$size
        fi

        group_files+=("$filepath")
        prev_hash=$hash
    done < "$hash_list"

    # Flush the final group (the loop above only emits on hash change)
    if [ ${#group_files[@]} -gt 1 ]; then
        local wasted=$(( group_size * (${#group_files[@]} - 1) ))
        total_wasted=$((total_wasted + wasted))
        text_output+="$(printf "\nDuplicate group (hash: %.8s..., %s each, %d copies, %s wasted):\n" \
            "$prev_hash" "$(human_readable $group_size)" "${#group_files[@]}" "$(human_readable $wasted)")"
        local files_json=""
        for f in "${group_files[@]}"; do
            text_output+="  $f\n"
            files_json+="\"$(echo "$f" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g')\","
        done
        files_json="${files_json%,}"
        json_groups+="$(printf '{"hash":"%s","size":%s,"count":%d,"wasted":%d,"files":[%s]},' \
            "$prev_hash" "$group_size" "${#group_files[@]}" "$wasted" "$files_json")"
    fi

    json_groups="${json_groups%,}"

    print_subheader "Duplicate Files Found"
    echo -e "$text_output"
    echo ""
    echo -e "${BOLD}Total wasted space: $(human_readable $total_wasted)${RESET}"

    write_json "$MODULE" "$(printf '{"groups":[%s],"total_wasted_bytes":%d}' "$json_groups" "$total_wasted")"
    echo -e "$text_output" > "${REPORT_DIR}/${MODULE}.txt"
    echo "Total wasted: $(human_readable $total_wasted)" >> "${REPORT_DIR}/${MODULE}.txt"

    success "Results written to ${REPORT_DIR}/${MODULE}.json"
}

main
