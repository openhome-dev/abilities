import sys
from datetime import datetime
from pathlib import Path

NOTES_FILE = Path("notes.md")


def main() -> int:
    note = " ".join(sys.argv[1:]).strip()
    if not note:
        print("No note provided. Usage: python3 take_note.py \"your note here\"")
        return 1

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not NOTES_FILE.exists():
        NOTES_FILE.write_text("# Notes\n\n", encoding="utf-8")

    with NOTES_FILE.open("a", encoding="utf-8") as f:
        f.write(f"- {timestamp}: {note}\n")

    print(f"Saved note to {NOTES_FILE}: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
