#!/usr/bin/env python3
"""
Validation sweep for gandw.io. Crawls the running dev server and reports
anything that would embarrass you in public.

    python serve.py                 # in one terminal
    python check.py                 # in another

    python check.py --url http://127.0.0.1:9000

Checks, per page:
  · HTTP status
  · <title> present, unique, and not over-long
  · meta description present and within the ~155-char snippet window
  · exactly one <h1>
  · every <img> has alt text
  · canonical URL matches the page's own path
  · no leftover placeholder text (TODO, Lorem, XXXX)
  · every internal link and asset resolves

Exit code is non-zero if anything fails, so it drops straight into CI later.
Stdlib only.
"""
import argparse
import re
import sys
from collections import defaultdict
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

PLACEHOLDERS = [
    (re.compile(r"\bTODO\b", re.I), "TODO"),
    (re.compile(r"\blorem ipsum\b", re.I), "lorem ipsum"),
    (re.compile(r"X{4,}"), "XXXX placeholder"),
    (re.compile(r"\bFIXME\b", re.I), "FIXME"),
    (re.compile(r"gogglesandwindchimes\.com"), "old domain"),
    # Internal build notes and art placeholders must never render publicly.
    (re.compile(r"\bSLOT\b"), "art slot placeholder"),
    (re.compile(r"PARALLAX STILL|VALESIAN SPECIMEN"), "art slot placeholder"),
    (re.compile(r"To do before launch|Still to write|Ready to drop in", re.I), "internal note"),
    (re.compile(r"\baspirational\b", re.I), "internal note"),
    (re.compile(r"<em>Pending", re.I), "pending asset"),
    (re.compile(r"GM[- ]only|Secret Canon|Restricted canon", re.I), "restricted canon marker"),
    # Inline style attributes are blocked by the site's default-src 'self' CSP.
    (re.compile(r"<[a-z][^>]*\sstyle=", re.I), "inline style (blocked by CSP)"),
]


# Terms from the author-only canon that must never reach the public site. Matched against
# page text AND against scripts/data files (the atlas gazetteer lives in a .js file).
RESTRICTED = [
    (re.compile(r"GM[- ]only|Secret Canon|Restricted canon|AUTHOR_ONLY", re.I), "restricted canon marker"),
    (re.compile(r"Toffee", re.I), "restricted canon term (Toffee Corp)"),
    (re.compile(r"eighth sage|third sister", re.I), "restricted canon term"),
]


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.titles, self.h1s, self.links, self.assets = [], [], [], []
        self.desc = self.canonical = None
        self.imgs_no_alt = 0
        self._in_title = self._in_h1 = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True; self._buf = []
        elif tag == "h1":
            self._in_h1 = True; self._buf = []
        elif tag == "meta":
            if a.get("name", "").lower() == "description":
                self.desc = a.get("content", "")
        elif tag == "link":
            rel = a.get("rel", "")
            if "canonical" in rel:
                self.canonical = a.get("href")
            elif "stylesheet" in rel or "icon" in rel:
                if a.get("href"): self.assets.append(a["href"])
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "img":
            if not a.get("alt"): self.imgs_no_alt += 1
            if a.get("src"): self.assets.append(a["src"])
        elif tag == "script" and a.get("src"):
            self.assets.append(a["src"])

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self.titles.append("".join(self._buf).strip()); self._in_title = False
        elif tag == "h1" and self._in_h1:
            self.h1s.append("".join(self._buf).strip()); self._in_h1 = False

    def handle_data(self, d):
        if self._in_title or self._in_h1:
            self._buf.append(d)


def fetch(url):
    try:
        with urlopen(Request(url, headers={"User-Agent": "gandw-check"}), timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.headers.get_content_type()
    except HTTPError as e:
        return e.code, "", ""
    except URLError as e:
        return None, str(e.reason), ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--expect-404", nargs="*", default=["/versus/"],
                    help="paths that SHOULD 404 locally (the game deploys separately)")
    args = ap.parse_args()
    base = args.url.rstrip("/")

    status, _, _ = fetch(base + "/")
    if status is None:
        sys.exit(f"Can't reach {base} — is serve.py running?")

    seen, queue = set(), ["/"]
    problems = defaultdict(list)
    titles = defaultdict(list)
    pages = assets_ok = 0
    checked_assets = set()

    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)

        status, body, ctype = fetch(base + path)
        expected_404 = path in args.expect_404 or path.rstrip("/") + "/" in args.expect_404

        if status != 200:
            if expected_404 and status == 404:
                pass                       # correct behaviour, not a problem
            else:
                problems[path].append(f"HTTP {status}")
            continue
        if "html" not in ctype:
            continue

        pages += 1
        p = Page(); p.feed(body)

        # --- metadata ---
        if not p.titles:
            problems[path].append("no <title>")
        else:
            t = p.titles[0]
            titles[t].append(path)
            if len(t) > 65:
                problems[path].append(f"title {len(t)} chars (>65 truncates in search results)")
        if not p.desc:
            problems[path].append("no meta description")
        elif len(p.desc) > 160:
            problems[path].append(f"meta description {len(p.desc)} chars (>160 truncates)")
        if len(p.h1s) != 1:
            problems[path].append(f"{len(p.h1s)} <h1> elements (want exactly 1)")
        if p.imgs_no_alt:
            problems[path].append(f"{p.imgs_no_alt} <img> without alt")
        if p.canonical:
            want = urlparse(p.canonical).path
            if want.rstrip("/") != path.rstrip("/"):
                problems[path].append(f"canonical points to {want}, page is {path}")

        # --- placeholder text ---
        text = re.sub(r"<[^>]+>", " ", body)
        for rx, label in RESTRICTED:
            if rx.search(text):
                problems[path].append(label)
        for rx, label in PLACEHOLDERS:
            haystack = body if label.startswith("inline style") else text
            if rx.search(haystack):
                problems[path].append(f"placeholder text: {label}")

        # --- social card ---
        m = re.search(r'<meta property="og:image" content="([^"]+)"', body)
        if not m:
            problems[path].append("no og:image (shared links show a blank card)")
        else:
            p.assets.append(urlparse(m.group(1)).path)

        # --- links ---
        for href in p.links:
            if href.startswith(("http://", "https://", "mailto:", "tel:", "#")):
                continue
            target = urlparse(urljoin(path, href)).path
            if target not in seen:
                queue.append(target)

        # --- assets ---
        for src in p.assets:
            if src.startswith(("http://", "https://", "data:")):
                continue
            a = urlparse(urljoin(path, src)).path
            if a in checked_assets:
                continue
            checked_assets.add(a)
            st, abody, actype = fetch(base + a)
            if st == 200:
                assets_ok += 1
                if a.endswith((".js", ".json")):
                    for rx, label in RESTRICTED:
                        if rx.search(abody):
                            problems[a].append(f"{label}")
            else:
                problems[path].append(f"asset {a} -> HTTP {st}")

    # ---------------------------------------------------------------- report
    print(f"\n  gandw.io validation — {base}\n")
    print(f"  pages crawled   {pages}")
    print(f"  assets checked  {len(checked_assets)}  ({assets_ok} ok)")

    dupes = {t: ps for t, ps in titles.items() if len(ps) > 1}
    if dupes:
        for t, ps in dupes.items():
            problems[ps[0]].append(f"duplicate <title> \"{t}\" also on {', '.join(ps[1:])}")

    if not problems:
        print("\n  No issues. \n")
        return 0

    print(f"\n  {sum(len(v) for v in problems.values())} issue(s):\n")
    for path in sorted(problems):
        print(f"  {path}")
        for issue in problems[path]:
            print(f"      · {issue}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
