# gandw.io — Goggles & Windchimes

The publisher site. Static HTML, no framework, no build toolchain, no external requests.

## Why it's built this way

The site is the **deployment target for VERSUS**, not a separate property. `versus/DEPLOY.md`
expects the game to be served from `/versus/` on this domain, behind the same CloudFront
distribution. Keeping the site dependency-free means:

- It can be served straight from S3 with no origin logic
- It runs under a strict `default-src 'self'` CSP — VERSUS needs a looser one for Leaflet
  and Twemoji, so the two get separate response-header policies
- There is nothing to break, patch, or audit. No npm tree, no CVE surface.

No cookies, no analytics, no webfonts, no trackers.

## Build

```
python3 build.py
```

Regenerates every page from the content blocks in `build.py`. Page copy lives in that file
as HTML strings — edit there, not in the generated `index.html` files, which are overwritten.

## Preview

```
python3 -m http.server 8899
# http://127.0.0.1:8899
```

## Structure

```
index.html              Home
games/                  Catalogue index
  versus/               VERSUS landing page  (the game itself deploys to /versus/)
  abyssfall/            In development
  oon/                  Published 2025
  archive/              The Shelf
tabletop/
  avb/                  A Vale Beyond
  yarr/                 The Yarr System — heritage
vale/                   The Vale Universe — atlas, script, directories
press/                  Press kit
about/                  The imprint
credits/                Third-party licences
404.html
assets/
  css/site.css          The whole design system, one file
  favicon.svg
  downloads/            Public PDFs (Oon rulebook + publication)
  img/                  Screenshots and key art — currently empty
```

## Important: `/versus/` is not in this repo

`/games/versus/` is the **landing page**. `/versus/` is the **game**, deployed independently
from the VERSUS repo by its own GitHub Actions pipeline into the same S3 bucket under the
`versus/` key prefix. A local preview will 404 on `/versus/` — that is correct.

## Design system

Two accents, one for each half of the name:

| Token | Value | Stands for |
|---|---|---|
| `--brass` | `#D9A441` | Goggles — workshop, machinery, comedy |
| `--verdigris` | `#6FAE9C` | Windchimes — myth, ecology, quiet |

Card top-borders alternate between them, so the catalogue reads as one system with two
temperaments rather than two competing brands. Typography is a system serif for display and
a system sans for interface — no font loading, no layout shift.

## Before launch

- [ ] Capture VERSUS screenshots → `assets/img/`, drop into the four slots on the VERSUS page
- [ ] Export AbyssFall parallax previews → three slots on the AbyssFall page
- [ ] Flatten and export three Vale maps → the atlas slots
- [ ] Set the Valesian specimen in `ValesianCipher-Regular.ttf`
- [ ] Real logo pack → `press/`
- [ ] Working press email (currently `press@gandw.io`, aspirational)
- [ ] Real ISBN for Oon (published edition carries a placeholder)
- [ ] Write the AI-provenance statement on `/credits/`
- [ ] Build an `og.png` social card for the site itself
