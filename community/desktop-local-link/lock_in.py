import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_script(script_name: str, *args: str) -> int:
    path = HERE / script_name
    result = subprocess.run([sys.executable, str(path), *args], capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0 and result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


def main() -> int:
    print("Starting lock-in setup.")

    run_script("do_not_disturb_on.py")
    run_script("clean_workspace.py")
    run_script("spotify.py", "deep", "focus")
    run_script("pomodoro.py", "25")

    print("Lock-in setup complete: DND, clean workspace, focus music, and Pomodoro timer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
