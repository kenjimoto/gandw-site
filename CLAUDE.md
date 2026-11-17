# gandw.io — context for Claude

The Goggles & Windchimes publisher site (static HTML from `build.py`) plus the account API
(`api/`, one Python Lambda). It is also where VERSUS is served, at `/versus/`, but **the game
deploys from its own repo (kenjimoto/Vs)**, never from here. Ken Bewley owns both. Read
`README.md` and `LOCAL_DEV.md` for the site itself; this file is about shipping changes.

## How a deploy happens

Merging to `main` deploys. There is no other route to production, and no manual step.
`.github/workflows/deploy.yml`:

1. **Build and validate** (also runs on every PR, which is the review gate):
   `python -m unittest discover -s api` → `python build.py` → the generated HTML must equal what
   is committed → `serve.py` + `check.py` crawl every page and asset.
2. **Publish** (pushes to `main` only), as the `gandw-site-deploy` role via GitHub OIDC (no keys):
   - `aws s3 sync . s3://gandw-io-site-584453982080 --delete`, minus `versus/*` and everything in
     `.deployignore` (sources, `api/`, this file);
   - `bash api/deploy.sh`: zips the API and swaps the **code only** of the `gandw-api` Lambda,
     then smoke-tests `https://gandw.io/api/me` (must be a JSON 401);
   - invalidates CloudFront `E1ZG4YKGXF4XLH` (`/*`) and checks `/`, `/games/`, `/versus/` are 200
     and a missing page is 404.

The game (kenjimoto/Vs) does the same on a push to its `master`: builds `dist/`, syncs it to
`s3://…/versus/` (HTML no-cache, everything else 1 hour), invalidates. Its engine Lambda job
(`gandw-versus-engine`) stays off until the repo variable `ENGINE_LAMBDA=on`.

Infrastructure (CloudFormation: `gandw-api.yaml`, the site stack, the deploy roles, the planned
`gandw-versus-engine.yaml`) lives in Ken's project folder `D:\Projects\12_Goggles & Windchimes\infra`,
not in this repo. The deploy roles can only do what the steps above need; anything else
(new tables, permissions, Lambda settings) is a reviewed change set Ken applies.

## Rules that keep deploys safe

- **Never hand-edit generated HTML.** Page copy lives in `build.py`; run `python build.py` and
  commit its output, or CI fails.
- **`api/deploy.sh` ships a fixed list of files.** A new `api/*.py` module must be added to that
  list. `api/test_deploy.py` fails the build if one is missing (it caught `content.py`).
- **Anything that must not be public goes in `.deployignore`.** The sync uploads the whole repo
  otherwise.
- **Never write under `versus/` from here.** The role is denied it anyway, and `--delete` is
  scoped away from it.
- **Status codes:** CloudFront turns every 403/404 into the site's 404 page, `/api/*` included, so
  the API uses 401 and 400 with a JSON `{error, message}` body. Keep it that way.
- **Order across the two repos:** when the game starts calling a new API route, merge the site
  change first. The game copes with a missing route, but players get a console error until the
  site catches up.
- Before opening a PR: `python -m unittest discover -s api`, `python build.py`, then
  `python serve.py --port 8000` and `python check.py` in another shell.

## Working here as Claude

- GitHub's GraphQL API is blocked from Claude sessions: use REST (`gh api repos/kenjimoto/gandw-site/pulls …`).
  The default branch is `main` (Vs uses `master`).
- Ken reviews and merges every PR himself. Don't merge unless he asks.
- On Ken's PC this repo's working copy is under `D:\Projects\12_Goggles & Windchimes`. The device bridge
  refuses to write `.github/workflows/*`; workflow changes go through a PR from a clone.
- End commits with the session's `Co-Authored-By` / `Claude-Session` lines.

## VERSUS content (the upload page)

`/admin/versus/` (author or admin role) checks a content workbook with the game's own checker
(`/versus/content/workbook-check.js`, `/versus/content/workbook.json`), then stages or publishes it.
The game loads `/api/games/versus/content.js` before it starts and uses published content only
while it was made from the deployed build's workbook (same `base`), so a game update that changes
the workbook sets older publishes aside until they're published again. After a final publish,
sync its "Download" zip into the Vs repo's `content/workbook/` so the repo stays the source.
Grant the role: Admin → Accounts → **Make author**. Code: `api/content.py`,
`assets/js/versus-content.js`; tests `api/test_content.py`.

## Pending deploy (16 Nov 2026): content framework steps 2–4 and phase 5b

Five stacked PRs, nothing merged yet. Merge in this order, letting each deploy go green first:

1. **Vs #25**: content framework step 2, the rules language (game only).
2. **Vs #26**: step 4, the sun (stacked on #25).
3. **gandw-site #8**: the upload page and its API (this repo). Includes the `deploy.sh` fix
   above. After it deploys: `curl -s https://gandw.io/api/games/versus/content.js` should say
   `/* no published content … */`, and `/admin/versus/` should say the checker didn't load until
   Vs #27 is live. That's expected.
4. **Vs #27**: step 3, game side (loads published content; ships the checker).
5. **Vs #28**: phase 5b, core 2.4 (cenotes, delves, the Fey Herald, favours, bypass tools).

Stacked PRs: when a base PR merges and its branch is deleted, GitHub retargets the next one to
`master`. If it doesn't, change the next PR's base to `master` before merging it.

After all five are live:
- open `/admin/versus/` as an author: the status panel shows core 2.4.0 and the workbook's base;
- download the game's workbook from there and re-import it into the Claude Sheet "VERSUS content
  workbook" (its Read me and Lists tabs still describe step 1);
- the PvP engine Lambda is still not deployed. When it is, it must be rebuilt from Vs `master`
  (core 2.4: Guild Ranked refuses A Story From Earth and keeps the schools' rules).
