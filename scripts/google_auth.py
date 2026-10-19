"""One-time Google consent for the test runner: Gmail inbox read-only, Lead log Sheet read/write
(n8n/sheet_setup.py creates the tabs and headers; the runner itself only reads).

Uses GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET from .env (the same OAuth client n8n uses; its
authorized redirect URIs must include http://localhost:8765/). Opens the consent page, catches
the redirect on localhost:8765 and saves GOOGLE_RUNNER_REFRESH_TOKEN to .env. Prints no secrets.

Usage: .venv/bin/python scripts/google_auth.py
"""
import json
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envfile import load_env, require, set_env  # noqa: E402
from net import SSL_CONTEXT  # noqa: E402

PORT = 8765
REDIRECT = f"http://localhost:{PORT}/"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/spreadsheets"]  # read/write: also creates the Sheet tabs


def main():
    env = load_env()
    require(env, "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
    state = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": env["GOOGLE_CLIENT_ID"], "redirect_uri": REDIRECT, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent", "state": state})
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if q.get("state") == state:
                got.update(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and go back to the terminal.")

        def log_message(self, *args):
            pass

    print("Opening Google consent in your browser (sign in with the inbox that receives the test replies)...")
    print("If it does not open, paste this URL into the browser:\n" + url)
    webbrowser.open(url)
    server = HTTPServer(("localhost", PORT), Handler)
    while not got:
        server.handle_request()
    if "code" not in got:
        raise SystemExit(f"Consent failed: {got.get('error', 'no code returned')}")
    body = urllib.parse.urlencode({"code": got["code"], "client_id": env["GOOGLE_CLIENT_ID"],
                                   "client_secret": env["GOOGLE_CLIENT_SECRET"], "redirect_uri": REDIRECT,
                                   "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=body),
                                timeout=30, context=SSL_CONTEXT) as r:
        tok = json.loads(r.read().decode())
    if not tok.get("refresh_token"):
        raise SystemExit("Google returned no refresh token. Remove the app's access at "
                         "myaccount.google.com/permissions and run again.")
    set_env("GOOGLE_RUNNER_REFRESH_TOKEN", tok["refresh_token"])
    print("Saved GOOGLE_RUNNER_REFRESH_TOKEN to .env (scopes: gmail.readonly, spreadsheets).")


if __name__ == "__main__":
    main()
