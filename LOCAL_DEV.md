# Running gandw.io locally

## Quick start

Open a terminal in the `site` folder:

```
cd "D:\Projects\12_Goggles & Windchimes\site"
python serve.py
```

Then open **http://127.0.0.1:8000/**

Ctrl-C stops it.

---

## Don't open index.html directly

Double-clicking `index.html` will look broken, and it isn't your fault. Every path in
the site is absolute — `/assets/css/site.css`, `/games/oon/` — because that's what
CloudFront will serve. Under `file://` there is no site root, so the stylesheet 404s
and every link goes nowhere.

**You need an HTTP server. Any HTTP server.** `serve.py` is just the one that behaves
most like production.

---

## Why not `python -m http.server`

You can use it, and it mostly works. But three behaviours differ from CloudFront, and
each one can make a validation result misleading:

| | `http.server` | `serve.py` | Production |
|---|---|---|---|
| `/games` (no slash) | 404 | 301 → `/games/` | 301 → `/games/` |
| Missing page | its own plain 404 | **your** `404.html`, status 404 | your `404.html`, status 404 |
| Caching | may cache | `no-store` | tuned per path |

The middle one matters most: with `http.server` you cannot tell whether your 404 page
actually works, because you never see it.

---

## Testing the game alongside the site

This is the part worth doing before you touch AWS. In production, VERSUS is served from
`/versus/` on this same domain — a separate deploy into the same bucket. You can
reproduce that shape locally:

```
python serve.py --versus "D:\Projects\03_Game_Dev\versus"
```

Now `/versus/` serves the game and the rest of the site serves normally, exactly as
CloudFront will route it. When the VERSUS folder has a `dist/` (from `npm run build`), the whole
`/versus/` mount is served from it, the same files production serves. **Build first:** since
November 2026 the page loads `versus-core.js` (the battle engine), which only exists in `dist/`.

Without `--versus`, the `/versus/` path 404s. **That is correct** — the game deploys from
its own repo, and its absence locally is not a broken link.

---

## Automated validation

With the server running, in a second terminal:

```
python check.py
```

It crawls every page from `/` and reports:

- HTTP status on every page, internal link and asset
- `<title>` present, unique across the site, and under 65 characters
- meta description present and under 160 characters
- exactly one `<h1>` per page
- every `<img>` has `alt` text
- `<link rel=canonical>` matches the page's own path
- leftover placeholder text — `TODO`, `FIXME`, `Lorem`, `XXXX`, or the old
  `gogglesandwindchimes.com` domain

It exits non-zero when something fails, so it drops into CI later without changes.

```
python check.py --url http://127.0.0.1:9000     # different port
python check.py --expect-404                    # when /versus IS mounted
```

Current state: **15 pages, 0 issues.**

---

## Changing content

Page copy lives in `build.py`, not in the generated HTML. Editing `games/oon/index.html`
directly will work until the next build, then be silently overwritten.

```
python build.py        # regenerate all pages
```

Leave `serve.py` running while you do it — it reads from disk on every request, so a
browser refresh is enough. No restart, no cache to clear.

---

## Other options

If you'd rather not use `serve.py`:

| Tool | Command | Note |
|---|---|---|
| Python stdlib | `python -m http.server 8000` | Works; see the caveats above |
| Node | `npx serve -l 8000` | Handles clean URLs well |
| VS Code | Live Server extension | Auto-reloads on save |

All of them beat `file://`. None of them will show you your real 404 page.

---

## Ports

`serve.py` defaults to 8000. If something else is on it:

```
python serve.py --port 8080
```

It binds to `127.0.0.1` only, so nothing on your network can reach it. To demo from a
phone on the same wifi, `--host 0.0.0.0` — then stop it again afterwards.

---

## Accounts, commissions and cloud saves (`--api`)

`/account/`, `/commissions/` and `/admin/` are static pages that talk to the account API
at `/api/`. In production that's a Lambda behind CloudFront. Locally, `serve.py` runs the
**same code** (`api/app.py`) against a JSON file instead of DynamoDB:

```
python serve.py --api --seed
python serve.py --api --seed --versus "D:/Projects/03_Game_Dev/versus"   # with VERSUS cloud save
```

- `--seed` creates admin **ken / local-admin-pw** and three sample reqs, once.
- Data lives in `.local-api.json` (git-ignored). Delete it, with the server stopped, to start over.
- Emails aren't sent. They're printed in the server window, so you can click a
  confirmation link or read an access request.
- Locally the session cookie isn't `Secure`, because there's no https. In production it is.
- `--versus` serves the VERSUS `dist/` folder, so run `npm run build` in VERSUS after editing
  `versus.html` or anything in `packages/core`.
- With `--api` too, and a built engine in the VERSUS folder (`npm run build:engine` there),
  the API's PvP engine hook (`api/engine.py`) runs it with your local `node`. Production calls
  the private `gandw-versus-engine` Lambda instead.

Without `--api`, those pages load but say the account service isn't available. That's
correct, and it's what CI checks.

API tests (stdlib, about a second): `python -m unittest discover -s api`
