#!/usr/bin/env python3
"""
validate_ability.py — Validates an OpenHome Ability for SDK compliance.

Usage:
    python validate_ability.py community/my-ability/
    python validate_ability.py official/weather/

Checks:
    - Required files exist (main.py, config.json, README.md)
    - config.json has required fields
    - main.py follows SDK patterns
    - No blocked imports or patterns
    - resume_normal_flow() is called
    - No print() statements

Exit codes:
    0 = All checks passed
    1 = One or more checks failed
"""

import os
import sys
import json
import re

# ============================================================================
# CONFIGURATION
# ============================================================================

REQUIRED_FILES = ["main.py", "config.json", "README.md"]

REQUIRED_CONFIG_KEYS = ["unique_name", "matching_hotwords"]

BLOCKED_IMPORTS = [
    "redis",
    "from src.utils.db_handler",
    "connection_manager",
    "user_config",
]

BLOCKED_PATTERNS = [
    (r"\bprint\s*\(", "Use self.worker.editor_logging_handler instead of print()"),
    (r"\basyncio\.sleep\s*\(", "Use self.worker.session_tasks.sleep() instead of asyncio.sleep()"),
    (r"\basyncio\.create_task\s*\(", "Use self.worker.session_tasks.create() instead of asyncio.create_task()"),
    (r"\bexec\s*\(", "exec() is not allowed for security reasons"),
    (r"\beval\s*\(", "eval() is not allowed for security reasons"),
    (r"\bpickle\.", "pickle is not allowed for security reasons"),
    (r"\bdill\.", "dill is not allowed for security reasons"),
    (r"\bshelve\.", "shelve is not allowed for security reasons"),
    (r"\bmarshal\.", "marshal is not allowed for security reasons"),
]

REQUIRED_PATTERNS = [
    (r"resume_normal_flow\s*\(", "resume_normal_flow() must be called — without it, the Personality gets stuck"),
    (r"class\s+\w+.*MatchingCapability", "Class must extend MatchingCapability"),
    (r"def\s+register_capability", "Must have a register_capability() classmethod"),
    (r"def\s+call\s*\(", "Must have a call() method"),
]


# ============================================================================
# VALIDATION LOGIC
# ============================================================================

class ValidationResult:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, msg):
        self.errors.append(f"  ❌ {msg}")

    def warn(self, msg):
        self.warnings.append(f"  ⚠️  {msg}")

    @property
    def passed(self):
        return len(self.errors) == 0


def validate_ability(path: str) -> ValidationResult:
    result = ValidationResult()
    path = path.rstrip("/")

    # --- Check required files ---
    for f in REQUIRED_FILES:
        if not os.path.isfile(os.path.join(path, f)):
            result.error(f"Missing required file: {f}")

    # --- Validate config.json ---
    config_path = os.path.join(path, "config.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                config = json.load(f)

            for key in REQUIRED_CONFIG_KEYS:
                if key not in config:
                    result.error(f"config.json missing required key: '{key}'")

            if "matching_hotwords" in config:
                hotwords = config["matching_hotwords"]
                if not isinstance(hotwords, list) or len(hotwords) == 0:
                    result.error("matching_hotwords must be a non-empty list")

            if "unique_name" in config:
                name = config["unique_name"]
                if not re.match(r"^[a-z][a-z0-9_]*$", name):
                    result.warn("unique_name should be lowercase snake_case (e.g., 'my_ability')")

            # Check community submissions have maintainer/status
            if "community" in path:
                if "maintainer" not in config:
                    result.warn("Community abilities should have a 'maintainer' field (e.g., 'github:username')")
                if config.get("status") != "community":
                    result.warn("Community abilities should have '\"status\": \"community\"' in config.json")

        except json.JSONDecodeError as e:
            result.error(f"config.json is not valid JSON: {e}")

    # --- Validate main.py ---
    main_path = os.path.join(path, "main.py")
    if os.path.isfile(main_path):
        with open(main_path) as f:
            code = f.read()

        # Check blocked imports
        for blocked in BLOCKED_IMPORTS:
            if blocked in code:
                result.error(f"Blocked import found: '{blocked}'")

        # Check blocked patterns
        for pattern, msg in BLOCKED_PATTERNS:
            if re.search(pattern, code):
                result.error(msg)

        # Check required patterns
        for pattern, msg in REQUIRED_PATTERNS:
            if not re.search(pattern, code):
                result.error(msg)

        # Check for hardcoded API keys (common patterns)
        key_patterns = [
            r'["\']sk_[a-zA-Z0-9]{20,}["\']',
            r'["\']sk-[a-zA-Z0-9]{20,}["\']',
            r'["\']key_[a-zA-Z0-9]{20,}["\']',
        ]
        for kp in key_patterns:
            if re.search(kp, code):
                result.warn("Possible hardcoded API key detected — use placeholders instead")

        # Check for only one class
        classes = re.findall(r"^class\s+\w+", code, re.MULTILINE)
        if len(classes) > 1:
            result.warn(f"Found {len(classes)} classes — only one class per main.py is recommended")

    return result


# ============================================================================
# CLI
# ============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_ability.py <ability-folder>")
        print("  e.g.: python validate_ability.py community/my-ability/")
        sys.exit(1)

    paths = sys.argv[1:]
    all_passed = True

    for path in paths:
        print(f"\n📋 Validating: {path}")

        if not os.path.isdir(path):
            print(f"  ❌ Not a directory: {path}")
            all_passed = False
            continue

        result = validate_ability(path)

        if result.errors:
            for e in result.errors:
                print(e)
        if result.warnings:
            for w in result.warnings:
                print(w)

        if result.passed:
            print("  ✅ All checks passed!")
        else:
            all_passed = False
            print(f"  ❌ {len(result.errors)} error(s) found")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
