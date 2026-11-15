"""VERSUS world contracts: Guild contracts that every player works on together.

Each week the Guild posts three world contracts, one per tier. Each one has a combined target
that grows with the number of players taking part: the tier's base, plus 0.75 x the base for
every player who has contributed (Ken, 14 Nov 2026). Once the combined total reaches the
target, the contract closes, and everyone who contributed can claim a reward in the game.

The week's contracts come from the week number alone, so every request agrees on them without
storing them. Only the totals are stored, in the accounts table:

    pk VW#<week>   sk c#<id>                 {total, players, closed}
    pk VW#<week>   sk p#<id>#<username>      {amount, day, today}

Kinds (the game counts each one itself and reports it here):
    culling    win fights against creatures of one tone       param: a tone
    travelling walk legs of road                               param: none
    donating   hand coin to a Guild board                      param: none
    gathering  hand rift ash to a Guild board                  param: none
"""
import hashlib
import math
import time

WEEK = 7 * 86400
TONES = ["Red", "Green", "Brown", "Blue", "White", "Violet", "Yellow", "Black"]
PER_PLAYER = 0.75
KINDS = {
    "culling": {"base": (150, 400, 900), "unit": "fights won",
                "title": "Cull the {param} wildlings", "desc": "Win fights against {param}-tone creatures anywhere on Sylvanos."},
    "travelling": {"base": (300, 800, 2000), "unit": "legs walked",
                   "title": "Keep the roads walked", "desc": "Walk the moon's roads. Every leg of road counts."},
    "donating": {"base": (2000, 6000, 15000), "unit": "coin given",
                 "title": "Fund the roadworks", "desc": "Hand coin to any Guild board for the repair of the cursed roads."},
    "gathering": {"base": (40, 120, 300), "unit": "rift ash handed in",
                  "title": "Gather rift ash", "desc": "Hand rift ash, left behind by rifts, to any Guild board."},
}
KIND_ORDER = ["culling", "travelling", "donating", "gathering"]
MAX_ADD = 500                 # largest single report
DAILY_SHARE = 0.25            # one player can add at most a quarter of the base per contract per day


def week_of(t=None):
    return int((t if t is not None else time.time()) // WEEK)


def _h(*parts):
    return int(hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest(), 16)


def week_contracts(week):
    """The three contracts of a week: tiers 1, 2 and 3, three different kinds."""
    kinds = sorted(KIND_ORDER, key=lambda k: _h("vw-kind", week, k))[:3]
    out = []
    for tier, kind in enumerate(kinds, start=1):
        k = KINDS[kind]
        param = TONES[_h("vw-tone", week, tier) % len(TONES)] if kind == "culling" else None
        out.append({
            "id": f"w{week}-{tier}", "week": week, "tier": tier, "kind": kind, "param": param,
            "title": k["title"].format(param=param), "desc": k["desc"].format(param=param),
            "unit": k["unit"], "base": k["base"][tier - 1],
        })
    return out


def target(base, players):
    return base + math.ceil(PER_PLAYER * base * max(0, int(players)))


def view(c, state, mine=0):
    players = int(state.get("players", 0)) if state else 0
    total = int(state.get("total", 0)) if state else 0
    closed = bool(state.get("closed")) if state else False
    return {**c, "players": players, "target": target(c["base"], players), "total": total,
            "closed": closed, "mine": int(mine)}


def daily_cap(base):
    return max(10, int(base * DAILY_SHARE))
