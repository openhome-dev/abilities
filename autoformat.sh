#!/usr/bin/env bash

# -----------------------------------------------------------------------------
# MIT License
#
# Copyright (c) 2025 OpenHome
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# -----------------------------------------------------------------------------

set -e
set -u
set -o pipefail

# ------------------------------------------------------------
# Usage:
#   ./autoformat.sh --check [target]   # just check formatting
#   ./autoformat.sh --fix [target]     # auto-fix formatting
#   target defaults to current directory if not provided
# ------------------------------------------------------------

MODE=""
if [[ "${1:-}" == "--check" ]]; then
  MODE="check"
elif [[ "${1:-}" == "--fix" ]]; then
  MODE="fix"
else
  echo "Usage: $0 --check | --fix [target]"
  exit 1
fi

TARGET="${2:-.}"

section() {
  echo ""
  echo "── $1 ──"
}

# Black
section "Black"
if [[ "$MODE" == "check" ]]; then
  black --check "$TARGET"
else
  black "$TARGET"
fi

# isort
section "isort"
if [[ "$MODE" == "check" ]]; then
  isort --check-only "$TARGET"
else
  isort "$TARGET"
fi

# autoflake
section "autoflake"
if [[ "$MODE" == "check" ]]; then
  autoflake --check --recursive "$TARGET"
else
  autoflake --remove-all-unused-imports \
            --remove-unused-variables \
            --recursive \
            --in-place "$TARGET"
fi

# flake8
section "flake8"
flake8 --extend-ignore=E203,W391 "$TARGET"

# mypy
section "mypy"
mypy --ignore-missing-imports "$TARGET"

# validate abilities (only if running whole repo)
if [[ "$TARGET" == "." ]] && [[ -f "validate_ability.py" ]]; then
  ABILITY_DIRS=$(find community official templates -mindepth 1 -maxdepth 1 -type d 2>/dev/null | tr '\n' ' ')
  if [[ -n "$ABILITY_DIRS" ]]; then
    section "validate_ability.py"
    python validate_ability.py $ABILITY_DIRS
  fi
fi