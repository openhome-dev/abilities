import subprocess

result = subprocess.run(
    ["shortcuts", "run", "DNDOn"],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("Do Not Disturb enabled.")
else:
    print("Failed to enable Do Not Disturb.")
    printkt(result.stderr)