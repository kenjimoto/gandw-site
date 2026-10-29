#!/usr/bin/env python3
"""
Goggles & Windchimes — static site builder.

Emits a complete, dependency-free static site into ./ (alongside this script).
No frameworks, no build toolchain, no external requests. Every page is plain
HTML that CloudFront can serve straight from S3.

    python3 build.py
"""
from pathlib import Path
import html
import shutil

ROOT = Path(__file__).parent
SITE = "Goggles & Windchimes"
DOMAIN = "gandw.io"

NAV = [
    ("Games", "/games/"),
    ("Tabletop", "/tabletop/"),
    ("The Vale Universe", "/vale/"),
    ("Press", "/press/"),
    ("About", "/about/"),
]

FOOTER = [
    ("Games", [
        ("VERSUS", "/games/versus/"),
        ("AbyssFall", "/games/abyssfall/"),
        ("Oon", "/games/oon/"),
        ("Concord", "/games/concord/"),
        ("Miniatures & McGuffins", "/games/mcguffins/"),
        ("Archive", "/games/archive/"),
    ]),
    ("Tabletop", [
        ("A Vale Beyond", "/tabletop/avb/"),
        ("The Yarr System", "/tabletop/yarr/"),
    ]),
    ("The World", [
        ("The Vale Universe", "/vale/"),
        ("Maps & Atlas", "/vale/#atlas"),
        ("The Valesian Script", "/vale/#script"),
    ]),
    ("Imprint", [
        ("About", "/about/"),
        ("Press Kit", "/press/"),
        ("Credits & Licences", "/credits/"),
    ]),
]

# The logo mark: a lens (goggles) and three struck tubes (windchimes).
MARK = """<svg class="logo__mark" width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true">
  <circle cx="8.5" cy="9" r="5.2" stroke="#D9A441" stroke-width="1.5"/>
  <path d="M13.7 9h2.2" stroke="#D9A441" stroke-width="1.5" stroke-linecap="round"/>
  <path d="M17.5 4.5v8M21 4.5v12M24 4.5v6" stroke="#6FAE9C" stroke-width="1.5" stroke-linecap="round"/>
  <path d="M16.6 4.5h8.2" stroke="#6FAE9C" stroke-width="1.5" stroke-linecap="round"/>
  <circle cx="8.5" cy="9" r="1.6" fill="#D9A441"/>
</svg>"""


def shell(*, title, desc, path, body, page_class="", og=None):
    """Wrap page body in the site chrome."""
    nav = "\n".join(
        '        <a href="{href}"{cur}>{label}</a>'.format(
            href=href,
            label=html.escape(label),
            cur=' aria-current="page"' if path.startswith(href) and href != "/" else "",
        )
        for label, href in NAV
    )

    cols = "\n".join(
        """          <div>
            <h2>{head}</h2>
            <ul>
{items}
            </ul>
          </div>""".format(
            head=html.escape(head),
            items="\n".join(
                '              <li><a href="{h}">{t}</a></li>'.format(h=h, t=html.escape(t))
                for t, h in items
            ),
        )
        for head, items in FOOTER
    )

    full_title = title if title == SITE else f"{title} · {SITE}"
    og_img = og or OG.get(path, "/assets/og.png")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(full_title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="https://{DOMAIN}{path}">
<meta property="og:site_name" content="{html.escape(SITE)}">
<meta property="og:title" content="{html.escape(full_title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="https://{DOMAIN}{path}">
<meta property="og:image" content="https://{DOMAIN}{og_img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Goggles &amp; Windchimes">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://{DOMAIN}{og_img}">
<meta name="theme-color" content="#090E15">
<link rel="stylesheet" href="/assets/css/site.css">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/assets/favicon-32.png" type="image/png" sizes="32x32">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
</head>
<body{f' class="{page_class}"' if page_class else ''}>
<a class="skip" href="#main">Skip to content</a>

<header class="masthead">
  <div class="wrap masthead__inner">
    <a class="logo" href="/">{MARK}<span>Goggles <span class="logo__amp">&amp;</span> Windchimes</span></a>
    <nav class="nav" aria-label="Primary">
{nav}
    </nav>
  </div>
</header>

<main id="main">
{body}
</main>

<footer class="foot">
  <div class="wrap">
    <div class="foot__grid">
{cols}
    </div>
    <div class="foot__legal">
      <span>&copy; 2026 Goggles &amp; Windchimes. All rights reserved.</span>
      <span>Vale, AnimaPlanet, Yarr, AbyssFall, Oon and VERSUS are marks of Goggles &amp; Windchimes.</span>
    </div>
  </div>
</footer>
</body>
</html>
"""


# Per-page social cards (1200x630). Pages not listed use the site card.
OG = {
    "/games/versus/": "/assets/img/versus/og-versus.jpg",
}


def figure(base, alt, caption=None, w=1600, h=900):
    """A responsive screenshot: base is the path without the -800/-1600.jpg suffix.

    Width/height are set so the page doesn't jump while images load; the 800px file is the
    default and the 1600px one is used on wide or high-density screens. Click opens full size.
    """
    cap = f"\n      <figcaption>{caption}</figcaption>" if caption else ""
    return f"""<figure class="shot">
      <a href="{base}-1600.jpg"><img src="{base}-800.jpg"
        srcset="{base}-800.jpg 800w, {base}-1600.jpg 1600w"
        sizes="(min-width: 46rem) 34rem, 100vw"
        width="{w}" height="{h}" loading="lazy" decoding="async"
        alt="{html.escape(alt)}"></a>{cap}
    </figure>"""


def write(path, content):
    out = ROOT / path.lstrip("/")
    if path.endswith("/"):
        out = out / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    print(f"  {out.relative_to(ROOT)}")


# ===========================================================================
# Home
# ===========================================================================

home = """
<section class="hero">
  <div class="wrap">
    <p class="eyebrow eyebrow--brass">Independent games &amp; tabletop publishing</p>
    <h1 class="hero__title">Two kinds of weather, one workshop.</h1>
    <p class="lede hero__lede">
      Goggles for the tinkering &mdash; absurd machines, creatures made of kitchen
      appliances, systems built to be taken apart. Windchimes for the rest &mdash; a
      forty-year world with its own ecology, its own history, and its own alphabet.
      We publish both on purpose.
    </p>
    <div class="btn-row">
      <a class="btn" href="/versus/">Play VERSUS</a>
      <a class="btn btn--ghost" href="/vale/">Enter the Vale Universe</a>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <p class="eyebrow">The catalogue</p>
    <h2>What we make</h2>
    <div class="grid grid--2">

      <a class="card card--brass" href="/games/versus/">
        <span class="status status--live">Play now</span>
        <span class="card__title">VERSUS &mdash; Egg to Legend</span>
        <span class="card__dek">
          Hatch an egg, raise something strange, and fight your way across a world that
          looks suspiciously like Vale. 124 forms across 50 evolution chains. Free, no
          install, no account, no ads.
        </span>
        <span class="card__meta">Browser &middot; Creature battler</span>
      </a>

      <a class="card card--verdigris" href="/games/abyssfall/">
        <span class="status status--dev">In development</span>
        <span class="card__title">AbyssFall</span>
        <span class="card__dek">
          A roguelite metroidvania set in the Vale Universe. Descend the Abyss through
          thirteen biomes and four depth layers. Death takes your Anima. Something
          always carries forward.
        </span>
        <span class="card__meta">PC &middot; Godot 4</span>
      </a>

      <a class="card card--verdigris" href="/tabletop/avb/">
        <span class="status status--soon">Seeking a publisher</span>
        <span class="card__title">A Vale Beyond</span>
        <span class="card__dek">
          An original-system tabletop RPG built on Anima &mdash; the force that gives life
          to inanimate things. Deep ecology, working languages, and a world drawn as a
          naturalist's field guide.
        </span>
        <span class="card__meta">Tabletop RPG &middot; Print</span>
      </a>

      <a class="card card--brass" href="/games/oon/">
        <span class="status status--out">Published 2025</span>
        <span class="card__title">Oon</span>
        <span class="card__dek">
          A maze pursuit game for two to four players. The die tells you how far. The card
          tells you which way. The maze decides whether you like it or not.
        </span>
        <span class="card__meta">Tabletop &middot; 2&ndash;4 players</span>
      </a>

    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">The imprint</p>
      <h2>A small press with a long memory</h2>
      <p class="dek">
        Goggles &amp; Windchimes publishes the games and worlds of Ken Bewley. Some of that
        work is four decades old &mdash; a homemade RPG about escaping a suburb, played on
        floors in Concord, California, that grew a mythology and never stopped. Some of it
        was written this year and runs in a browser tab.
      </p>
      <p class="dek">
        We think those two things belong under one roof. The tinkering is what makes the
        myth build-able; the myth is what makes the tinkering worth doing.
      </p>
      <p><a href="/about/">Read the full story &rarr;</a></p>
    </div>
  </div>
</section>
"""

# ===========================================================================
# Games index
# ===========================================================================

games = """
<section class="hero">
  <div class="wrap">
    <p class="eyebrow eyebrow--brass">Catalogue</p>
    <h1 class="hero__title">Games</h1>
    <p class="lede hero__lede">
      Everything we have published, are building, or have retired to the shelf.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="grid">

      <a class="card card--brass" href="/games/versus/">
        <span class="status status--live">Play now</span>
        <span class="card__title">VERSUS &mdash; Egg to Legend</span>
        <span class="card__dek">A free browser creature-battler that runs in a single HTML file.</span>
        <span class="card__meta">Browser &middot; Free</span>
      </a>

      <a class="card card--verdigris" href="/games/abyssfall/">
        <span class="status status--dev">In development</span>
        <span class="card__title">AbyssFall</span>
        <span class="card__dek">Roguelite metroidvania. Thirteen biomes, four depth layers, one hub town.</span>
        <span class="card__meta">PC &middot; Godot 4</span>
      </a>

      <a class="card card--brass" href="/games/oon/">
        <span class="status status--out">Published 2025</span>
        <span class="card__title">Oon</span>
        <span class="card__dek">A maze pursuit game for 2&ndash;4 players. Roll, draw, navigate, survive.</span>
        <span class="card__meta">Tabletop &middot; Print</span>
      </a>

      <a class="card card--verdigris" href="/games/concord/">
        <span class="status status--soon">Rough draft &mdash; playtesting</span>
        <span class="card__title">Concord</span>
        <span class="card__dek">A pen-and-paper escape game set in the town you actually live in.</span>
        <span class="card__meta">Tabletop &middot; One session</span>
      </a>

      <a class="card card--brass" href="/games/mcguffins/">
        <span class="status status--dev">Design draft</span>
        <span class="card__title">Miniatures &amp; McGuffins</span>
        <span class="card__dek">A dungeon roguelike played on the brick sets you already own.</span>
        <span class="card__meta">Tabletop &middot; Cards</span>
      </a>

      <a class="card" href="/games/archive/">
        <span class="status status--dev">Archive</span>
        <span class="card__title">The Shelf</span>
        <span class="card__dek">Prototypes, experiments and finished oddities that aren't part of the main line.</span>
        <span class="card__meta">Various</span>
      </a>

    </div>
  </div>
</section>
"""

# ===========================================================================
# VERSUS
# ===========================================================================

versus = """
<section class="hero">
  <div class="wrap">
    <span class="status status--live">Play now</span>
    <h1 class="hero__title hero__title--badged">VERSUS</h1>
    <p class="lede hero__lede">
      Hatch an egg. Raise something strange. Fight your way across Vale, more or less.
    </p>
    <div class="btn-row">
      <a class="btn" href="/versus/">Play free in your browser</a>
      <a class="btn btn--ghost" href="#what">What is it?</a>
    </div>
    <p class="hero__note">
      No install. No account. No ads. Plays offline once loaded.
    </p>
  </div>
</section>

<section id="what">
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow eyebrow--brass">The game</p>
      <h2>A turn-based creature battler that fits in one file</h2>
      <p class="dek">
        You start with an egg. You train it, hatch it into one of 124 forms across 50
        evolution chains, and take it out into a procedurally populated Vale &mdash; towns,
        cities, wild encounters, duelists, street vendors, and the occasional gas leak.
      </p>
      <p class="dek">
        It is not canon. Somebody took Earth, shoved the continents back into Pangaea,
        tipped it on its side and dropped it onto Ometia. New York ended up on the edge
        of the Great Desert. Nobody has told it.
      </p>
      <p class="dek">
        Your creature might become a Toaster. The Toaster might become an Air Fryer of
        Judgement. Left long enough, and with the right milestones, it might become
        The Sun, Frankly. This is a game with opinions.
      </p>
    </div>

    <ul class="facts">
      <li><div class="facts__k">Forms</div><div class="facts__v">124</div></li>
      <li><div class="facts__k">Evolution chains</div><div class="facts__v">50 (plus secrets)</div></li>
      <li><div class="facts__k">Price</div><div class="facts__v">Free</div></li>
      <li><div class="facts__k">Platform</div><div class="facts__v">Any browser</div></li>
    </ul>
  </div>
</section>

<!--SHOTS-->

<section>
  <div class="wrap">
    <p class="eyebrow">Systems</p>
    <h2>What's under it</h2>
    <ul class="stack">
      <li>
        <span class="stack__k">Elemental Pentagram</span>
        <span class="stack__v">Combat with criticals, dodges, focus, and one ultra-rare move nobody should have to read aloud.</span>
      </li>
      <li>
        <span class="stack__k">Hidden evolutions</span>
        <span class="stack__v">Paths that branch on level milestones &mdash; and decay if you let a creature get beaten half to death.</span>
      </li>
      <li>
        <span class="stack__k">Breeding</span>
        <span class="stack__v">A luck-weighted inheritance web with phenotype tags.</span>
      </li>
      <li>
        <span class="stack__k">Two scopes of ailment</span>
        <span class="stack__v">Combat statuses land on your creature. Social ones land on you. Get yourself a warrant and the bank locks you out.</span>
      </li>
      <li>
        <span class="stack__k">Weather &amp; a day clock</span>
        <span class="stack__v">Six fronts that shift elemental damage underneath you while you fight.</span>
      </li>
      <li>
        <span class="stack__k">Bosses &amp; reputation</span>
        <span class="stack__v">Quests, a bank, clout-tiered nicknames, and a final boss called AMPERSAND, the Unclosed Tag.</span>
      </li>
      <li>
        <span class="stack__k">Procedural audio</span>
        <span class="stack__v">The soundtrack is generated with Web Audio, because shipping audio files is for cowards.</span>
      </li>
    </ul>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">Credits</p>
      <h2>Built on</h2>
      <p class="dek">
        VERSUS uses Twemoji (CC-BY 4.0, Twitter), Leaflet for the map, and photography
        from Unsplash. The world map is ours. Full attribution is on the
        <a href="/credits/">credits page</a>.
      </p>
    </div>
  </div>
</section>
"""

V = "/assets/img/versus/"
versus = versus.replace("<!--SHOTS-->", f"""<section>
  <div class="wrap">
    <p class="eyebrow">Media</p>
    <h2>Screens</h2>
    <div class="shot-grid">
    {figure(V + "world-map", "The VERSUS world map: Vale terrain dotted with towns, wild zones, duel beacons and vendor carts", "Roam a world that looks a lot like Vale.")}
    {figure(V + "battle", "A VERSUS battle: Smug Sentient Goo against a Regal Passive-Aggressive Cloud, with the move list below", "Turn-based fights with moves nobody should read aloud.")}
    {figure(V + "house", "The House screen listing six creatures, from Off-Brand Nervous Hot-Air Balloon to Anxious Local Black Hole", "Keep up to six. Breed two that share a trait.")}
    {figure(V + "stats", "A creature's stat sheet with HP, attack, defence, speed, focus, AA and dodge bars and its five moves", "Every creature rolls its own stats and moves.")}
    </div>
  </div>
</section>""")

# ===========================================================================
# AbyssFall
# ===========================================================================

abyssfall = """
<section class="hero">
  <div class="wrap">
    <span class="status status--dev">In development</span>
    <h1 class="hero__title hero__title--badged">AbyssFall</h1>
    <p class="lede hero__lede">
      Descend. Die. Carry something back.
    </p>
    <div class="btn-row">
      <a class="btn btn--ghost" href="/vale/">The world it's set in</a>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">The game</p>
      <h2>A roguelite metroidvania in the Vale Universe</h2>
      <p class="dek">
        The Abyss is a void dotted with clusters of rooms, drawn procedurally from thirteen
        biomes across four depth layers. You leave the hub town of Ampersand, go down as far
        as you dare, and take what you can carry.
      </p>
      <p class="dek">
        Dying costs most of your run's Anima. It does not cost you everything &mdash; persistent
        progression carries forward, so each descent starts from a slightly better place than
        the last one ended.
      </p>
    </div>

    <ul class="facts">
      <li><div class="facts__k">Biomes</div><div class="facts__v">13</div></li>
      <li><div class="facts__k">Depth layers</div><div class="facts__v">4</div></li>
      <li><div class="facts__k">Stage</div><div class="facts__v">Pre-alpha</div></li>
      <li><div class="facts__k">Engine</div><div class="facts__v">Godot 4</div></li>
    </ul>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">Status</p>
      <h2>Where it actually is</h2>
      <p class="dek">
        Honest answer: the machinery works and the surface doesn't exist yet. The
        architecture, procedural generation, combat, save system and content pipeline are
        built. Art, audio and the content databases are the remaining work, and they're
        most of what a player would actually experience.
      </p>
      <p class="dek">
        There is no build to download and no release date. When there's something worth
        playing, it will appear here first.
      </p>
    </div>
  </div>
</section>
"""

# ===========================================================================
# Oon
# ===========================================================================

oon = """
<section class="hero">
  <div class="wrap">
    <span class="status status--out">Published 2025</span>
    <h1 class="hero__title hero__title--badged">Oon</h1>
    <p class="lede hero__lede">
      Roll. Draw. Navigate. Survive.
    </p>
    <div class="btn-row">
      <a class="btn" href="/assets/downloads/Oon_Rulebook.pdf">Download the rulebook (PDF)</a>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow eyebrow--brass">The game</p>
      <h2>A maze pursuit game for two to four players</h2>
      <p class="dek">
        A custom 12&times;12 gridded board holds a maze of single-width corridors &mdash; every
        path exactly one cell wide, every corner reachable. Players navigate by rolling a die
        and drawing a direction card. The die tells you how far. The card tells you which way.
        The maze decides whether you like it or not.
      </p>
      <p class="dek">
        Capture every rival by overtaking them on your turn. Last token standing wins.
      </p>
      <blockquote>Custom boards and pieces are encouraged.</blockquote>
    </div>

    <ul class="facts">
      <li><div class="facts__k">Players</div><div class="facts__v">2&ndash;4</div></li>
      <li><div class="facts__k">Board</div><div class="facts__v">12&times;12 grid</div></li>
      <li><div class="facts__k">Edition</div><div class="facts__v">First, 2025</div></li>
      <li><div class="facts__k">ISBN</div><div class="facts__v facts__v--sm">979-8-9888187-1-7</div></li>
    </ul>

    <div class="notice">
      <strong>Print-and-play edition.</strong> The book prints its own components &mdash; two
      tournament-legal boards, the full 55-card direction deck, four tokens and two blank
      design grids. You are licensed to photocopy those pages without limit. Cut them out,
      play until you like it, then build it in marble.
    </div>
  </div>
</section>
"""

# ===========================================================================
# Archive
# ===========================================================================

archive = """
<section class="hero">
  <div class="wrap">
    <p class="eyebrow">Catalogue</p>
    <h1 class="hero__title">The Shelf</h1>
    <p class="lede hero__lede">
      Prototypes, experiments and finished oddities. Kept because they happened, not
      because they're current.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <ul class="stack">
      <li>
        <span class="stack__k">yarr (prototype)</span>
        <span class="stack__v">
          A small top-down action prototype built in Godot 3, 2021. Shares a name with the
          tabletop system but nothing else. Retired.
        </span>
      </li>
      <li>
        <span class="stack__k">Egregious Prompts</span>
        <span class="stack__v">
          A coloring book. Published, and exactly as advertised.
        </span>
      </li>
      <li>
        <span class="stack__k">Bit Album</span>
        <span class="stack__v">
          Eight chiptune pieces written in BeepBox. Occasionally load-bearing.
        </span>
      </li>
    </ul>
  </div>
</section>
"""


# ===========================================================================
# Concord
# ===========================================================================

concord = """
<section class="hero">
  <div class="wrap">
    <span class="status status--soon">Rough draft &mdash; playtesting</span>
    <h1 class="hero__title hero__title--badged">Concord</h1>
    <p class="lede hero__lede">
      Something has gone wrong in the town you actually live in, and you have to
      get out of it tonight.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">The game</p>
      <h2>The map is the one in your head</h2>
      <p class="dek">
        Concord isn&rsquo;t set in a fantasy kingdom or on a starship. It&rsquo;s set in your town
        &mdash; the real one, where you know which gas station is open at 2 a.m. and which
        fence you can get over. The Game Master invents a reason the place has become
        uninhabitable. You run for a real exit.
      </p>
      <p class="dek">
        Five points across Mind, Body and Soul. A six-sided die, rolled under. And
        <strong>the Cone</strong> &mdash; a consequence roll that fires after every single
        action you take.
      </p>
    </div>

    <ul class="facts">
      <li><div class="facts__k">Players</div><div class="facts__v">2+</div></li>
      <li><div class="facts__k">Length</div><div class="facts__v">20&ndash;90 min</div></li>
      <li><div class="facts__k">Prep</div><div class="facts__v">None</div></li>
      <li><div class="facts__k">You need</div><div class="facts__v">One d6</div></li>
    </ul>
  </div>
</section>

<section>
  <div class="wrap">
    <p class="eyebrow">Contents</p>
    <h2>What&rsquo;s in the draft</h2>
    <ul class="stack">
      <li><span class="stack__k">Three scenarios</span><span class="stack__v">Zombies, invasion, and societal breakdown &mdash; each built out in full.</span></li>
      <li><span class="stack__k">Six seeds</span><span class="stack__v">Short premises for a game you start in five minutes.</span></li>
      <li><span class="stack__k">The Cone</span><span class="stack__v">72 consequence entries across 17 sub-tables.</span></li>
      <li><span class="stack__k">Table pack</span><span class="stack__v">GM screen, character sheet and prep sheet, print-ready.</span></li>
    </ul>
    <div class="notice">
      <strong>Status:</strong> complete rough draft at v0.4. Nothing here needs more writing
      &mdash; it needs people playing it. Two players, one die, forty minutes.
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">The engine</p>
      <h2>The grandfather of three games</h2>
      <p class="dek">
        Concord is the root of a shared rules engine. The Mind / Body / Soul triad it
        runs on turns up independently in every game we make, and everything else
        hangs off it &mdash; scaled up to a dice pool for the Vale campaign system, and
        sideways into cards for <a href="/games/mcguffins/">Miniatures &amp; McGuffins</a>.
      </p>
    </div>
  </div>
</section>
"""

# ===========================================================================
# Miniatures & McGuffins
# ===========================================================================

mcguffins = """
<section class="hero">
  <div class="wrap">
    <span class="status status--dev">Design draft</span>
    <h1 class="hero__title hero__title--badged">Miniatures &amp; McGuffins</h1>
    <p class="lede hero__lede">
      A dungeon roguelike played on the brick sets you already own. Card decks run the
      dungeon. No GM required.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">The idea</p>
      <h2>The grid is already there</h2>
      <p class="dek">
        Four studs square is one game square &mdash; a measure chosen because four divides
        evenly into every standard footprint in the hobby. The sidewalk is two squares. The
        road plate is four by four. The modular building is eight by eight. The grid was
        latent in the sets the whole time; the game just names it.
      </p>
      <p class="dek">
        Rooms are the set&rsquo;s real spaces and doorways are wherever the set put them. You
        survey a building once &mdash; ten minutes with a pencil &mdash; and it is a dungeon
        forever. The randomness lives in the decks, the monsters, and where the stair turns up.
      </p>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">The loop</p>
      <h2>Wards and McGuffins</h2>
      <p class="dek">
        Every boss carries <strong>three Wards</strong> &mdash; keyword properties &mdash; and
        takes no damage at all while any of them still stands. <strong>McGuffins</strong> are
        ordinary objects with one absurd fact attached, and the right ones break the right
        wards.
      </p>
      <p class="dek">
        Find the three that matter before the thing at the bottom finds you.
      </p>
    </div>
    <div class="notice">
      <strong>Status:</strong> design draft. The ward system and the spatial spec are solid
      enough to prototype. Least tested: whether open ground is simply too lethal to ever
      cross.
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">Compatibility</p>
      <h2>We don&rsquo;t make the bricks</h2>
      <p class="dek">
        Miniatures &amp; McGuffins is a set of cards and a surveying method. No building
        elements are manufactured and no figures are produced &mdash; the core box is a
        complete game for whatever you already have on the shelf, and expansions are keyed to
        published sets by set number.
      </p>
      <p class="fineprint">
        LEGO&reg; is a trademark of the LEGO Group of companies, which does not sponsor,
        authorize or endorse this product.
      </p>
    </div>
  </div>
</section>
"""

# ===========================================================================
# Tabletop index
# ===========================================================================

tabletop = """
<section class="hero">
  <div class="wrap">
    <p class="eyebrow">Catalogue</p>
    <h1 class="hero__title">Tabletop</h1>
    <p class="lede hero__lede">
      Where all of this started &mdash; a homemade system, a suburb to escape, and forty
      years of not stopping.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="grid">
      <a class="card card--verdigris" href="/tabletop/avb/">
        <span class="status status--soon">Seeking a publisher</span>
        <span class="card__title">A Vale Beyond</span>
        <span class="card__dek">An original-system fantasy RPG built on Anima, with the ecology worked out first.</span>
        <span class="card__meta">Core rulebook &middot; Print draft v1.4</span>
      </a>
      <a class="card card--brass" href="/tabletop/yarr/">
        <span class="status status--dev">Heritage</span>
        <span class="card__title">The Yarr System</span>
        <span class="card__dek">Yes A Lot of Recording &amp; Rolling. The engine everything else grew out of.</span>
        <span class="card__meta">System &middot; 1980s&ndash;present</span>
      </a>
    </div>
  </div>
</section>
"""

# ===========================================================================
# AVB
# ===========================================================================

avb = """
<section class="hero">
  <div class="wrap">
    <span class="status status--soon">Seeking a publisher</span>
    <h1 class="hero__title hero__title--badged">A Vale Beyond</h1>
    <p class="lede hero__lede">
      A tabletop roleplaying game about Anima &mdash; the thing that gives life to inanimate
      objects &mdash; on a world built ecology-first.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">The game</p>
      <h2>An original system, not a reskin</h2>
      <p class="dek">
        A Vale Beyond runs on its own rules, developed over decades of actual play rather
        than designed backwards from a setting. The world came with it: Vale is the dying
        heart of Thea, Earth's sister, and everything in it &mdash; the biomes, the peoples,
        the trade in materials, the ships &mdash; is worked out to the level of a naturalist's
        field guide.
      </p>
    </div>

    <ul class="facts">
      <li><div class="facts__k">Core rulebook</div><div class="facts__v">Print draft v1.4</div></li>
      <li><div class="facts__k">Supplements</div><div class="facts__v">4 drafted</div></li>
      <li><div class="facts__k">Source volumes</div><div class="facts__v">Books I&ndash;VII</div></li>
      <li><div class="facts__k">Status</div><div class="facts__v">Publisher outreach</div></li>
    </ul>
  </div>
</section>

<section>
  <div class="wrap">
    <p class="eyebrow">The line</p>
    <h2>What exists</h2>
    <ul class="stack">
      <li><span class="stack__k">Core Rulebook</span><span class="stack__v">Print draft v1.4. The complete system and setting.</span></li>
      <li><span class="stack__k">Quickstart Guide</span><span class="stack__v">A short on-ramp for a first session.</span></li>
      <li><span class="stack__k">Artificer's Companion</span><span class="stack__v">Making, binding and the rules of worked Anima.</span></li>
      <li><span class="stack__k">Shipwright's Manual</span><span class="stack__v">Vessels for the Opinne Sea, component by component.</span></li>
      <li><span class="stack__k">Loot Tables by Biome</span><span class="stack__v">Drop tables keyed to the ecology rather than to level.</span></li>
      <li><span class="stack__k">Book of Callings</span><span class="stack__v">The job system &mdash; what a life in Vale can be made of.</span></li>
    </ul>

    <div class="notice">
      <strong>For publishers and agents:</strong> a pitch packet, the v1.4 print draft and
      the quickstart are available on request.
    </div>
  </div>
</section>
"""

# ===========================================================================
# Yarr
# ===========================================================================

yarr = """
<section class="hero">
  <div class="wrap">
    <span class="status status--dev">Heritage</span>
    <h1 class="hero__title hero__title--badged">The Yarr System</h1>
    <p class="lede hero__lede">
      Yes A Lot of Recording &amp; Rolling.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">Origin</p>
      <h2>It started as a way to escape Concord</h2>
      <p class="dek">
        Yarr began in high school as a simple RPG for running impromptu games &mdash; set in
        Concord, California, a bedroom suburb in the east San Francisco Bay. The goal was
        literally to escape Concord by any means necessary, with the GM throwing every
        obstacle they could invent while still leaving a fair way out.
      </p>
      <p class="dek">
        The games were stupid, chaotic and, most importantly, fun. The mechanics got picked
        at for years &mdash; things added, things pulled out &mdash; until the system earned a
        setting of its own: Yarr, a granular, story-driven pirate sim on the Opinne Sea.
      </p>
      <p class="dek">
        Everything Goggles &amp; Windchimes publishes descends from that. Anima, the death of
        Thea, the Grey aliens who turned out to be sentient cephalopods no more foreign to
        Earth than we are &mdash; all of it accreted around a game about getting out of a
        suburb.
      </p>
      <p><a href="/vale/">Where it led &rarr;</a></p>
    </div>
  </div>
</section>
"""

# ===========================================================================
# Vale
# ===========================================================================

vale = """
<section class="hero">
  <div class="wrap">
    <p class="eyebrow">The world</p>
    <h1 class="hero__title">The Vale Universe</h1>
    <p class="lede hero__lede">
      Vale is the dying heart of Thea, Earth's sister, destroyed in our own ancient past.
      What survived is an endless ocean, a shattered geography, and Anima &mdash; the force
      that gives life to things that shouldn't have it.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">Canon</p>
      <h2>One world, several doors</h2>
      <p class="dek">
        AbyssFall, A Vale Beyond and the Yarr system are all set here. So are the novels.
        The world is documented as a single body of work &mdash; cosmology and history,
        geography and biomes, peoples and factions, biology and ecology, material culture,
        and the systems that tie them together.
      </p>
    </div>
  </div>
</section>

<section id="atlas">
  <div class="wrap">
    <p class="eyebrow">Atlas</p>
    <h2>Maps</h2>
    <div class="prose">
      <p class="dek">
        Vale is mapped the way a surveyor would want it: a full terrain plate of Ometia, a
        biome map with an eleven-class legend, a scale-and-distance chart, and named plates
        for the Easterly Kingdoms and the Westerly State. The atlas plates will be published
        here.
      </p>
    </div>
  </div>
</section>

<section id="script">
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">Language</p>
      <h2>The Valesian script</h2>
      <p class="dek">
        Vale has working languages, not decorative ones: phonologies for Annu, Nephilim and
        Theil&ndash;Dais, a linguistic history connecting them, a master lexicon, and a
        Rosetta document for the Barteeba stone.
      </p>
      <p class="dek">
        The Valesian cipher exists as a real, installable typeface with a published
        character map. It is the kind of detail that takes a world from described to
        inhabited.
      </p>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <p class="eyebrow">Reference</p>
    <h2>The directories</h2>
    <ul class="stack">
      <li><span class="stack__k">Characters</span><span class="stack__v">Who is in Vale, and what they want.</span></li>
      <li><span class="stack__k">Locations</span><span class="stack__v">Regions, continents, outer zones, settlements.</span></li>
      <li><span class="stack__k">Bestiary &amp; Peoples</span><span class="stack__v">Wyld fauna, beast-men, Aenimakind, Eldridgekind, subspecies.</span></li>
      <li><span class="stack__k">Artifacts &amp; Weapons</span><span class="stack__v">Worked Anima and what it costs to carry.</span></li>
      <li><span class="stack__k">Unified Timeline</span><span class="stack__v">Thea's destruction through the present age.</span></li>
    </ul>
  </div>
</section>
"""

# ===========================================================================
# Press
# ===========================================================================

press = """
<section class="hero">
  <div class="wrap">
    <p class="eyebrow eyebrow--brass">For media</p>
    <h1 class="hero__title">Press Kit</h1>
    <p class="lede hero__lede">
      Everything needed to write about us, in one place.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">Boilerplate</p>
      <h2>About Goggles &amp; Windchimes</h2>
      <p class="dek">
        Goggles &amp; Windchimes is an independent games and tabletop imprint founded by
        Ken Bewley, publishing browser games, PC games and tabletop roleplaying titles.
        Its catalogue spans absurdist digital design and the Vale Universe &mdash; a
        four-decade fantasy setting with its own ecology, history and constructed
        languages. The imprint published its first title, the maze pursuit game
        <em>Oon</em>, in 2025.
      </p>
    </div>

    <ul class="facts">
      <li><div class="facts__k">Founded</div><div class="facts__v">2025</div></li>
      <li><div class="facts__k">Founder</div><div class="facts__v">Ken Bewley</div></li>
      <li><div class="facts__k">Based</div><div class="facts__v">California, USA</div></li>
    </ul>
  </div>
</section>

<section>
  <div class="wrap">
    <p class="eyebrow">Assets</p>
    <h2>Downloads</h2>
    <ul class="stack">
      <li><span class="stack__k">Oon rulebook</span><span class="stack__v"><a href="/assets/downloads/Oon_Rulebook.pdf">Complete rules, PDF.</a></span></li>
      <li><span class="stack__k">Logo pack, screenshots &amp; fact sheets</span><span class="stack__v">In preparation.</span></li>
    </ul>
  </div>
</section>
"""

# ===========================================================================
# About
# ===========================================================================

about = """
<section class="hero">
  <div class="wrap">
    <p class="eyebrow">The imprint</p>
    <h1 class="hero__title">About</h1>
    <p class="lede hero__lede">
      Goggles for the tinkering. Windchimes for the rest.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">The name</p>
      <h2>Why two things</h2>
      <p class="dek">
        A publisher usually picks a lane. We didn't, and the name is the admission.
      </p>
      <p class="dek">
        <strong>Goggles</strong> is the workshop &mdash; the part that takes systems apart to see
        how they run, that finds it genuinely funny to build a rigorous combat engine and
        then populate it with kitchen appliances. VERSUS lives here.
      </p>
      <p class="dek">
        <strong>Windchimes</strong> is the other weather &mdash; slower, older, and mostly
        listening. It's where a world gets an ecology before it gets a plot, where languages
        get phonologies, where a map is redrawn for the ninth time because the currents were
        wrong. The Vale Universe lives here.
      </p>
      <p class="dek">
        They are the same instinct pointed at different problems. Neither one is the day job.
      </p>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">The founder</p>
      <h2>In his own words</h2>
      <blockquote>
        As far back as I can remember I've been a storyteller. I saw old monster movies on
        TV, giant ants and titans, evil robots and clockwork owls and rabbits of unusual
        size and lost islands and beings from space. I read books about the life of the sea
        and deserts, that looked into the mysteries of life both before and after. I existed
        in a world I didn't realize everyone else wasn't a part of.
      </blockquote>
      <p class="dek">
        The work began in earnest in high school, with a homemade RPG built so that a group
        of friends could play on short notice. It was set in their own suburb and the object
        was to escape it. Over the following decades that system acquired a sea, then a
        planet, then a mythology, and finally a name for the whole undertaking: Projekt AP,
        Project Anima Planet.
      </p>
      <blockquote>
        Now I am a father, I'm a manager, and all these things which I created dwell just
        outside a locked door I have never shown to those outside the friends I built the
        world for. These rules and stories will no longer have it. Maybe we create not for
        ourselves and others, but for the creations themselves. So that they can exist in a
        world that will have them in no other way.
      </blockquote>
      <p class="dek">
        Goggles &amp; Windchimes is that door, opened.
      </p>
      <p class="fineprint">
        Adapted from the creative preface to <em>The Vale Universe Bible</em>.
      </p>
    </div>
  </div>
</section>
"""

# ===========================================================================
# Credits
# ===========================================================================

credits = """
<section class="hero">
  <div class="wrap">
    <p class="eyebrow">Legal</p>
    <h1 class="hero__title">Credits &amp; Licences</h1>
    <p class="lede hero__lede">
      Third-party work we depend on, and the terms it comes under.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <p class="eyebrow">VERSUS</p>
    <h2>Attribution</h2>
    <ul class="stack">
      <li>
        <span class="stack__k">Twemoji</span>
        <span class="stack__v">
          Creature and interface glyphs are Twemoji, &copy; Twitter Inc. and contributors,
          licensed <a href="https://creativecommons.org/licenses/by/4.0/">CC-BY 4.0</a>.
        </span>
      </li>
      <li>
        <span class="stack__k">Unsplash</span>
        <span class="stack__v">
          Battle backdrop photography under the Unsplash Licence.
        </span>
      </li>
      <li>
        <span class="stack__k">Leaflet</span>
        <span class="stack__v">
          Map rendering by Leaflet, BSD-2-Clause.
        </span>
      </li>
    </ul>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="prose">
      <p class="eyebrow">This site</p>
      <h2>No third parties</h2>
      <p class="dek">
        This website loads no external fonts, scripts, analytics or trackers. Everything it
        needs is served from this domain. There are no cookies.
      </p>
    </div>
  </div>
</section>
"""

# ===========================================================================
# 404
# ===========================================================================

notfound = """
<section class="hero">
  <div class="wrap">
    <p class="eyebrow eyebrow--brass">404</p>
    <h1 class="hero__title">This corridor doesn't connect.</h1>
    <p class="lede hero__lede">
      Every path in Oon is exactly one cell wide and every corner is reachable. This
      page is neither.
    </p>
    <div class="btn-row">
      <a class="btn" href="/">Back to the front</a>
      <a class="btn btn--ghost" href="/games/">Browse the catalogue</a>
    </div>
  </div>
</section>
"""

FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="5" fill="#090E15"/>
  <circle cx="12" cy="17" r="6.4" fill="none" stroke="#D9A441" stroke-width="2"/>
  <circle cx="12" cy="17" r="2" fill="#D9A441"/>
  <path d="M20 8v13M24 8v9M28 8v16" stroke="#6FAE9C" stroke-width="2" stroke-linecap="round"/>
  <path d="M19 8h10" stroke="#6FAE9C" stroke-width="2" stroke-linecap="round"/>
</svg>"""

ROBOTS = f"""User-agent: *
Allow: /

Sitemap: https://{DOMAIN}/sitemap.xml
"""

PAGES = [
    ("/",                    "Goggles & Windchimes", "Independent games and tabletop publishing. VERSUS, AbyssFall, A Vale Beyond, Oon, and the Vale Universe.", home),
    ("/games/",              "Games",                "Every game published, in development, or retired by Goggles & Windchimes.", games),
    ("/games/versus/",       "VERSUS — Egg to Legend", "A free browser creature-battler. Hatch an egg, raise something strange, and fight across a world that looks a lot like Vale.", versus),
    ("/games/abyssfall/",    "AbyssFall",            "A roguelite metroidvania set in the Vale Universe. Thirteen biomes, four depth layers. In development.", abyssfall),
    ("/games/oon/",          "Oon",                  "A maze pursuit game for two to four players. Roll, draw, navigate, survive. Published 2025.", oon),
    ("/games/concord/",      "Concord",              "A pen-and-paper escape game set in the town you actually live in. 2+ players, one die, no prep.", concord),
    ("/games/mcguffins/",    "Miniatures & McGuffins", "A dungeon roguelike played on the brick sets you already own. Card decks run the dungeon.", mcguffins),
    ("/games/archive/",      "The Shelf",            "Prototypes, experiments and finished oddities from Goggles & Windchimes.", archive),
    ("/tabletop/",           "Tabletop",             "Tabletop roleplaying games from Goggles & Windchimes, including A Vale Beyond and the Yarr system.", tabletop),
    ("/tabletop/avb/",       "A Vale Beyond",        "An original-system tabletop RPG built on Anima, set in the ecology-first world of Vale.", avb),
    ("/tabletop/yarr/",      "The Yarr System",      "Yes A Lot of Recording & Rolling — the homemade RPG engine the Vale Universe grew out of.", yarr),
    ("/vale/",               "The Vale Universe",    "Vale is the dying heart of Thea. Maps, languages, bestiary and timeline of a forty-year setting.", vale),
    ("/press/",              "Press Kit",            "Press assets and boilerplate for Goggles & Windchimes.", press),
    ("/about/",              "About",                "Goggles for the tinkering. Windchimes for the rest. The story of the imprint.", about),
    ("/credits/",            "Credits & Licences",   "Third-party work used by Goggles & Windchimes titles, and its licence terms.", credits),
]


def main():
    print("Building gandw.io\n")

    for path, title, desc, body in PAGES:
        write(path, shell(title=title, desc=desc, path=path, body=body))

    write("/404.html", shell(
        title="Page not found", desc="That page doesn't exist.",
        path="/404.html", body=notfound))

    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets/favicon.svg").write_text(FAVICON, encoding="utf-8")
    print("  assets/favicon.svg")

    (ROOT / "robots.txt").write_text(ROBOTS, encoding="utf-8")
    print("  robots.txt")

    urls = "\n".join(
        f"  <url><loc>https://{DOMAIN}{p}</loc></url>" for p, _, _, _ in PAGES
    )
    (ROOT / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n',
        encoding="utf-8")
    print("  sitemap.xml")

    for d in ("assets/downloads", "assets/img"):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
        keep = ROOT / d / ".gitkeep"
        keep.write_text("", encoding="utf-8")

    print(f"\nDone. {len(PAGES) + 1} pages.")


if __name__ == "__main__":
    main()
