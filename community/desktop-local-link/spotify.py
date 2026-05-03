import argparse
import subprocess
import sys
from urllib.parse import quote_plus

DEFAULT_QUERY = "spotify"

PRESET_QUERIES = {
    "lofi": "lofi beats playlist",
    "lo-fi": "lofi beats playlist",
    "lo fi": "lofi beats playlist",
    "focus": "deep focus playlist",
    "deep focus": "deep focus playlist",
    "focus music": "focus music playlist",
    "chill": "chill playlist",
    "hype": "hype workout playlist",
    "beast mode": "beast mode workout playlist",
    "energy": "high energy playlist",
    "classical": "classical music playlist",
}


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def open_url(url: str) -> int:
    # Prefer Chrome, but fall back to the default browser if Chrome is unavailable.
    chrome_result = run(["open", "-a", "Google Chrome", url])
    if chrome_result.returncode == 0:
        return 0

    default_result = run(["open", url])
    if default_result.returncode == 0:
        return 0

    print("Failed to open Spotify URL.")
    print(chrome_result.stderr.strip())
    print(default_result.stderr.strip())
    return 1


def pause_spotify_app() -> int:
    # Spotify Web cannot be paused reliably from the command line.
    # If the Spotify app is open, this pauses it; otherwise it exits cleanly.
    result = run(["osascript", "-e", 'tell application "Spotify" to pause'])
    if result.returncode == 0:
        print("Paused Spotify app.")
        return 0
    print("Could not pause Spotify app. Spotify Web does not expose a simple CLI pause command.")
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode or 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Open Spotify Web search in Chrome/default browser.")
    parser.add_argument("query", nargs="*", help="Search terms, e.g. lofi, deep focus, classical")
    parser.add_argument("--pause", action="store_true", help="Pause the Spotify desktop app if available")
    args = parser.parse_args()

    if args.pause:
        return pause_spotify_app()

    query = " ".join(args.query).strip() or DEFAULT_QUERY
    query = PRESET_QUERIES.get(query.lower(), query)

    url = f"https://open.spotify.com/search/{quote_plus(query)}"
    print(f"Opening Spotify search for: {query}")
    return open_url(url)


if __name__ == "__main__":
    sys.exit(main())
