#!/usr/bin/env python3
"""
validate_ability.py — Validates an OpenHome Ability for SDK compliance.

Usage:
    python validate_ability.py community/my-ability/
    python validate_ability.py official/weather/

Checks:
    - Required files exist (main.py, README.md, __init__.py)
    - Folder name uses only hyphens (no underscores or spaces)
    - main.py follows SDK patterns
    - #{{register capability}} tag is present
    - No blocked imports or patterns
    - resume_normal_flow() is called
    - No print() statements
    - No raw open() calls
    - No assert statements
    - No weak hashes (MD5)

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

REQUIRED_FILES = ["main.py", "README.md", "__init__.py"]

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
    (r"\bopen\s*\(", "raw open() is not allowed — use capability_worker file helpers (read_file, write_file, etc.) instead"),
    (r"\bassert\s+", "assert statements are not allowed — use proper error handling instead"),
    (r"\bhashlib\.md5\s*\(", "MD5 is a weak hash and not allowed — use a stronger algorithm like SHA-256"),
]

REQUIRED_PATTERNS = [
    (r"resume_normal_flow\s*\(", "resume_normal_flow() must be called — without it, the Personality gets stuck"),
    (r"class\s+\w+.*MatchingCapability", "Class must extend MatchingCapability"),
    (r"def\s+call\s*\(", "Must have a call() method"),
    (r"worker\s*:\s*AgentWorker\s*=\s*None", "Must declare 'worker: AgentWorker = None' as a class attribute"),
    (r"capability_worker\s*:\s*CapabilityWorker\s*=\s*None", "Must declare 'capability_worker: CapabilityWorker = None' as a class attribute"),
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

    # --- Check folder name format (community folders only) ---
    folder_name = os.path.basename(path)
    parent_dir = os.path.basename(os.path.dirname(os.path.abspath(path)))

    if parent_dir == "community":
        if re.search(r'[_ ]', folder_name):
            suggested = re.sub(r'[_ ]+', '-', folder_name)
            result.error(
                f"Folder name '{folder_name}' contains underscores or spaces — "
                f"only hyphens (-) are allowed. Rename to: '{suggested}'"
            )

    # --- Check required files ---
    for f in REQUIRED_FILES:
        if not os.path.isfile(os.path.join(path, f)):
            result.error(f"Missing required file: {f}")

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

        # ----------------------------------------------------------
        # Check for register capability tag
        # ----------------------------------------------------------
        has_register_tag = bool(re.search(r"#\{\{register capability\}\}", code))

        if not has_register_tag:
            result.error(
                "Missing register capability tag — add the following line to your class:\n"
                "    #{{register capability}}\n"
                "See: https://docs.openhome.com/how_to_build_an_ability"
            )

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
    output_lines = []

    for path in paths:
        header = f"\n📋 Validating: {path}"
        print(header)
        output_lines.append(header)

        if not os.path.isdir(path):
            msg = f"  ❌ Not a directory: {path}"
            print(msg)
            output_lines.append(msg)
            all_passed = False
            continue

        result = validate_ability(path)

        if result.errors:
            for e in result.errors:
                print(e)
                output_lines.append(e)
        if result.warnings:
            for w in result.warnings:
                print(w)
                output_lines.append(w)

        if result.passed:
            msg = "  ✅ All checks passed!"
            print(msg)
            output_lines.append(msg)
        else:
            all_passed = False
            msg = f"  ❌ {len(result.errors)} error(s) found"
            print(msg)
            output_lines.append(msg)

    # --- Write output for PR comment ---
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "")
    output_file = os.environ.get("VALIDATION_OUTPUT", "validation_output.txt")

    full_output = "\n".join(output_lines)

    with open(output_file, "w") as f:
        f.write(full_output)

    if summary_file:
        with open(summary_file, "a") as f:
            f.write("## 🔍 Ability Validation Results\n\n")
            f.write("```\n")
            f.write(full_output)
            f.write("\n```\n")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
