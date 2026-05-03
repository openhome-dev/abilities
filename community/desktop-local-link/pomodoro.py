import argparse
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Start a background Pomodoro timer.")
    parser.add_argument("minutes", nargs="?", type=int, default=25)
    args = parser.parse_args()

    if args.minutes <= 0:
        print("Minutes must be positive.")
        return 1

    seconds = args.minutes * 60
    title = f"Pomodoro complete"
    message = f"Your {args.minutes} minute timer is done. Take a short break."

    # The local link command runner has a short timeout, so launch the timer in the background.
    shell_cmd = (
        f"sleep {seconds}; "
        f"osascript -e 'display notification \"{message}\" with title \"{title}\"'; "
        f"say 'Pomodoro complete. Take a short break.'"
    )

    subprocess.Popen(
        ["/bin/bash", "-lc", shell_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    print(f"Started a {args.minutes} minute Pomodoro timer in the background.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
