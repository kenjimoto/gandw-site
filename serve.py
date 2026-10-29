#!/usr/bin/env python3
"""
Local dev server for gandw.io — behaves the way CloudFront will.

    python serve.py                     # http://127.0.0.1:8000
    python serve.py --port 9000
    python serve.py --versus "D:/Projects/03_Game_Dev/versus"

Why not `python -m http.server`?  Three behaviours differ from production, and
all three would make your validation results misleading:

  1. Directory URLs      /games/  ->  /games/index.html          (http.server does this too)
  2. Extensionless URLs  /games   ->  301 to /games/             (http.server 404s)
  3. Missing pages       ->  your 404.html, with a real 404      (http.server sends its own)

Plus caching is disabled here, so a hard refresh is never needed mid-test.

Stdlib only. No install, no dependencies.
"""
import argparse
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


def main():
    ap = argparse.ArgumentParser(description="Local dev server for gandw.io")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--versus", metavar="DIR",
                    help="path to the VERSUS repo (or its dist/), mounted at /versus/")
    ap.add_argument("--base-path", default="/versus", help="mount point for the game")
    args = ap.parse_args()

    if args.versus:
        d = Path(args.versus).expanduser().resolve()
        if not d.is_dir():
            sys.exit(f"--versus: not a directory: {d}")
        Handler.versus_dir = d
        Handler.base_path = "/" + args.base_path.strip("/")

    print(f"\n  Goggles & Windchimes — local dev\n")
    print(f"  serving  {SITE}")
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
