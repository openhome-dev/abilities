"""
Demo helper for the P2 watch demo: a killable website on :8080.

Equivalent to `python3 -m http.server 8080` but with a clear banner and a tiny
page, so the "site just went down" moment is obvious on stage.

Run:   python demo_site.py
Stop:  Ctrl+C  → watch_worker should then fire "…just went down"

Dev aid / demo asset, not part of the pushed ability logic.
"""

import http.server
import socketserver

PORT = 8080
PAGE = b"""<!doctype html><html><head><title>Jarvis Demo Site</title></head>
<body style="font-family:sans-serif;text-align:center;padding-top:15vh">
<h1>Demo site is UP</h1><p>Kill this server to trigger the watcher.</p></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Demo site UP on http://localhost:{PORT}  (Ctrl+C to take it down)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDemo site DOWN — watcher should fire on its next poll.")
