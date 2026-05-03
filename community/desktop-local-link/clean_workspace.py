import subprocess
import sys


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def osascript(script: str):
    return run(["osascript", "-e", script])


def main() -> int:
    # Keep this conservative: hide/quit common distractions, then open work tools.
    actions = [
        ("Quit Messages", ["osascript", "-e", 'quit app "Messages"']),
        ("Quit Slack", ["osascript", "-e", 'quit app "Slack"']),
        ("Open VS Code", ["open", "-a", "Visual Studio Code"]),
        ("Open Terminal", ["open", "-a", "Terminal"]),
    ]

    failures = []
    for label, cmd in actions:
        result = run(cmd)
        if result.returncode != 0:
            failures.append(label)

    print("Clean workspace setup complete.")
    if failures:
        print("Some actions may have failed or apps may not exist: " + ", ".join(failures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
