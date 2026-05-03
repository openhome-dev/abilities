import json
import subprocess
from typing import List, Optional


DELIMITER = "|||"


def run_osascript(script: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return None


def parse_delimited_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(DELIMITER) if item.strip()]


def get_frontmost_app() -> Optional[str]:
    script = """
    tell application "System Events"
        set frontApp to name of first application process whose frontmost is true
    end tell
    return frontApp
    """
    return run_osascript(script)


def get_running_apps() -> List[str]:
    script = f'''
    tell application "System Events"
        set appNames to name of every application process whose background only is false
        set AppleScript's text item delimiters to "{DELIMITER}"
        return appNames as text
    end tell
    '''
    return sorted(set(parse_delimited_list(run_osascript(script))))


def get_safari_tabs() -> List[str]:
    script = f'''
    tell application "Safari"
        set tabList to {{}}
        repeat with w in windows
            repeat with t in tabs of w
                copy (name of t) to end of tabList
            end repeat
        end repeat
        set AppleScript's text item delimiters to "{DELIMITER}"
        return tabList as text
    end tell
    '''
    return parse_delimited_list(run_osascript(script))


def main() -> None:
    output = {
        "frontmost_app": get_frontmost_app(),
        "running_apps": get_running_apps(),
        "safari_tabs": get_safari_tabs(),
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()