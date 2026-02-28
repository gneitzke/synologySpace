#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# colors.sh — Terminal color definitions
# Part of Synology Space Analyzer
#
# Provides ANSI color variables used by all scripts. Gracefully
# degrades to empty strings when the terminal lacks color support.
#
# Sourced by: lib/utils.sh
# ─────────────────────────────────────────────────────────────

# Set color codes only if the terminal supports at least 8 colors
if [ -t 1 ] && command -v tput &>/dev/null && [ "$(tput colors 2>/dev/null)" -ge 8 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    MAGENTA='\033[0;35m'
    CYAN='\033[0;36m'
    WHITE='\033[1;37m'
    BOLD='\033[1m'
    DIM='\033[2m'
    RESET='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    MAGENTA=''
    CYAN=''
    WHITE=''
    BOLD=''
    DIM=''
    RESET=''
fi
