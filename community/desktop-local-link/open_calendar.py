import subprocess
import sys

URL = "https://calendar.google.com"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    chrome = run(["open", "-a", "Google Chrome", URL])
    if chrome.returncode == 0:
        print("Opened Google Calendar in Chrome.")
        return 0

    default = run(["open", URL])
    if default.returncode == 0:
        print("Opened Google Calendar in the default browser.")
        return 0

    print("Failed to open Google Calendar.")
    print(chrome.stderr.strip())
    print(default.stderr.strip())
    return 1


if __name__ == "__main__":
    sys.exit(main())
