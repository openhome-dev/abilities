import subprocess
import sys

SHORTCUT_NAMES = ["DNDOff", "Stop Focus", "Turn Off Focus"]

for shortcut_name in SHORTCUT_NAMES:
    result = subprocess.run(
        ["shortcuts", "run", shortcut_name],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("Do Not Disturb disabled.")
        sys.exit(0)

print("Failed to disable Do Not Disturb. Create a Shortcut named DNDOff that sets Do Not Disturb off.")
sys.exit(1)
