#!/usr/bin/env python3
"""
Local dev server for gandw.io — behaves the way CloudFront will.

    python serve.py                     # http://127.0.0.1:8000
    python serve.py --port 9000
    python serve.py --versus "D:/Projects/03_Game_Dev/versus"
    python serve.py --api               # also run the account API at /api/ (local data file)
    python serve.py --api --seed        # ...with a local admin and three sample reqs

Why not `python -m http.server`?  Three behaviours differ from production, and
all three would make your validation results misleading:

  1. Directory URLs      /games/  ->  /games/index.html          (http.server does this too)
  2. Extensionless URLs  /games   ->  301 to /games/             (http.server 404s)
  3. Missing pages       ->  your 404.html, with a real 404      (http.server sends its own)

Plus caching is disabled here, so a hard refresh is never needed mid-test.

Stdlib only. No install, no dependencies.
"""
import argparse
import json
import os
import posixpath
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

SITE = Path(__file__).parent.resolve()


class Handler(SimpleHTTPRequestHandler):
    versus_dir = None          # set from --versus
    base_path = "/versus"
    api = None                 # set from --api: the same App the Lambda runs

    # ---------------------------------------------------------------- /api/*
    def _is_api(self):
        return self.api is not None and urlparse(self.path).path.startswith("/api/")

    def _api(self):
        from http.cookies import SimpleCookie
        from urllib.parse import parse_qs
        sys.path.insert(0, str(SITE / "api"))
        import app as api_mod
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace") if n else ""
        jar = SimpleCookie(self.headers.get("Cookie") or "")
        cookies = {k: m.value for k, m in jar.items()}
        # same-origin check uses whatever host you browsed to (127.0.0.1 or localhost)
        self.api.site = "http://" + (self.headers.get("Host") or "127.0.0.1")
        req = api_mod.Request(self.command, u.path, dict(self.headers.items()), cookies, body,
                              {k: v[0] for k, v in parse_qs(u.query).items()})
        resp = self.api.handle(req)
        out = json.dumps(resp.body).encode()
        self.send_response(resp.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Cache-Control", "no-store")
        for c in resp.cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(out)

    def do_GET(self):
        if self._is_api():
            return self._api()
        return super().do_GET()

    def do_HEAD(self):
        if self._is_api():
            return self._api()
        return super().do_HEAD()

    def do_POST(self):
        if self._is_api():
            return self._api()
        self.send_error(405)

    do_PUT = do_PATCH = do_DELETE = do_POST

    # ---------------------------------------------------------------- routing
    def translate_path(self, path):
        """Map a URL path to a file, honouring the /versus mount."""
        clean = unquote(urlparse(path).path)
        clean = posixpath.normpath(clean)

        if self.versus_dir and (clean == self.base_path or clean.startswith(self.base_path + "/")):
            rest = clean[len(self.base_path):].lstrip("/")
            if rest in ("", "index.html"):
                # the built game is index.html; the dev copy is versus.html
                for name in ("dist/index.html", "index.html", "versus.html"):
                    cand = self.versus_dir / name
                    if cand.is_file():
                        return str(cand)
            return str(self.versus_dir / rest)

        parts = [p for p in clean.split("/") if p not in ("", ".", "..")]
        return str(SITE.joinpath(*parts))

    def send_head(self):
        raw = urlparse(self.path).path

        # /versus -> /versus/  — CloudFront's rewrite function does this explicitly,
        # and the mount resolves to a file rather than a directory, so it needs
        # handling before the generic directory redirect below.
        if self.versus_dir and raw == self.base_path:
            self.send_response(301)
            self.send_header("Location", self.base_path + "/")
            self.end_headers()
            return None

        target = Path(self.translate_path(self.path))

        # /games -> /games/   (CloudFront's rewrite function does this)
        if not raw.endswith("/") and target.is_dir():
            self.send_response(301)
            self.send_header("Location", raw + "/")
            self.end_headers()
            return None

        if target.is_dir():
            index = target / "index.html"
            if index.is_file():
                return self._serve(index)
            return self._not_found()

        if target.is_file():
            return self._serve(target)

        return self._not_found()

    # ---------------------------------------------------------------- responses
    def _serve(self, path: Path, status=200):
        try:
            data = path.read_bytes()
        except OSError:
            return self._not_found()
        self.send_response(status)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Length", str(len(data)))
        # never cache in dev — stale CSS is the classic false alarm
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        import io
        return io.BytesIO(data)

    def _not_found(self):
        page = SITE / "404.html"
        if page.is_file():
            return self._serve(page, status=404)
        self.send_error(404, "Not Found")
        return None

    def log_message(self, fmt, *args):
        code = str(args[1]) if len(args) > 1 else ""
        mark = {"200": "  ", "301": "→ ", "404": "✗ "}.get(code, "  ")
        sys.stderr.write(f"{mark}{args[0]}  {code}\n")


def make_local_api(seed=False):
    """The production API code with a JSON-file store and a mailer that prints instead of sending."""
    os.environ.setdefault("PBKDF2_ITERS", "50000")   # quicker sign-in locally
    sys.path.insert(0, str(SITE / "api"))
    import app as api_mod
    from mailer import LocalMailer
    from store import MemoryStore
    store = MemoryStore(SITE / ".local-api.json")
    app = api_mod.App(store, LocalMailer(), notify_to="you@localhost", site_origin="http://127.0.0.1",
                      cookie_secure=False)       # plain http locally; production cookies are Secure
    if seed and not store.query("USERS", "u#"):
        store.put({"pk": "USERS", "sk": "u#ken", "name": "Ken", "roles": ["player", "admin"], "gen": 0,
                   "pw": api_mod.hash_password("local-admin-pw"), "created": api_mod.now()})
        samples = [
            ("Bestiary plate: the Grubbin", "One full-page ink illustration for the AVB bestiary.",
             "A burrowing scavenger about the size of a badger.\n\nBlack and white ink, 8.5x11 at 600 dpi. "
             "References and the bestiary entry are supplied once you earmark.", "$150 flat", "Mid-January"),
            ("VERSUS creature: Dumpster Drake (3 forms)", "Three evolution forms, 512px, transparent PNG.",
             "Absurdist and friendly. The game's tone is internet comedy.\nEach form should read at 64px.",
             "$90 per form", ""),
            ("Ometia regional map, line art", "Clean line art from Ken's sketch of the northern realms.",
             "Vector or 600 dpi raster. Hand-drawn feel preferred.", "Negotiable", "February"),
        ]
        for i, (t, summ, desc, fee, due) in enumerate(samples):
            store.put({"pk": "REQS", "sk": f"r#seed{i}", "title": t, "summary": summ, "description": desc,
                       "fee": fee, "due": due, "status": "open", "created": api_mod.now() - i * 86400,
                       "updated": api_mod.now()})
        print("  seeded   admin  ken / local-admin-pw   +3 sample reqs")
    return app


def main():
    ap = argparse.ArgumentParser(description="Local dev server for gandw.io")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--versus", metavar="DIR",
                    help="path to the VERSUS repo (or its dist/), mounted at /versus/")
    ap.add_argument("--base-path", default="/versus", help="mount point for the game")
    ap.add_argument("--api", action="store_true",
                    help="run the account API at /api/, storing data in .local-api.json")
    ap.add_argument("--seed", action="store_true",
                    help="with --api: create a local admin and sample reqs if the data file is empty")
    args = ap.parse_args()

    if args.api:
        Handler.api = make_local_api(seed=args.seed)

    if args.versus:
        d = Path(args.versus).expanduser().resolve()
        if not d.is_dir():
            sys.exit(f"--versus: not a directory: {d}")
        Handler.versus_dir = d
        Handler.base_path = "/" + args.base_path.strip("/")

    print(f"\n  Goggles & Windchimes — local dev\n")
    print(f"  serving  {SITE}")
    if Handler.api:
        print(f"  /api     local account API  (data: .local-api.json, mail printed here)")
    if Handler.versus_dir:
        print(f"  /versus  {Handler.versus_dir}")
    else:
        print(f"  /versus  not mounted — that path will 404 (correct; the game deploys separately)")
    print(f"\n  →  http://{args.host}:{args.port}/\n")
    print("  Ctrl-C to stop.\n")

    try:
        ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.\n")


if __name__ == "__main__":
    main()
