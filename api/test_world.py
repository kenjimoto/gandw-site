"""World contracts for VERSUS:  python -m unittest discover -s api"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import world                                     # noqa: E402
from test_app import Client, make_app           # noqa: E402


class WeekContracts(unittest.TestCase):
    def test_three_tiers_three_kinds_stable(self):
        a = world.week_contracts(2900)
        self.assertEqual([c["tier"] for c in a], [1, 2, 3])
        self.assertEqual(len({c["kind"] for c in a}), 3)
        self.assertEqual(a, world.week_contracts(2900))
        self.assertTrue(all(c["kind"] != "culling" or c["param"] in world.TONES for c in a))
        kinds = {c["kind"] for w in range(2900, 2960) for c in world.week_contracts(w)}
        self.assertEqual(kinds, set(world.KIND_ORDER))

    def test_target_grows_by_three_quarters_of_base_per_player(self):
        self.assertEqual(world.target(400, 0), 400)
        self.assertEqual(world.target(400, 1), 700)
        self.assertEqual(world.target(400, 4), 1600)


class WorldApi(unittest.TestCase):
    def setUp(self):
        self.app, self.store, _ = make_app()
        self.wk = world.week_of()
        self.t0 = self.wk * world.WEEK + 3600
        self.clock = mock.patch("app.now", return_value=self.t0)
        self.clock.start()
        self.players = []
        for n in ("Pip", "Quill", "Rook"):
            c = Client(self.app); c.post("/api/auth/register", {"username": n, "password": "long-enough-pw"})
            self.players.append(c)
        self.anon = Client(self.app)

    def tearDown(self):
        self.clock.stop()

    def contract(self, tier=1):
        return next(c for c in self.anon.get("/api/games/versus/world").body["contracts"] if c["tier"] == tier)

    def test_anyone_can_look_and_nobody_owes_anything_yet(self):
        r = self.anon.get("/api/games/versus/world")
        self.assertEqual(r.status, 200)
        self.assertEqual(len(r.body["contracts"]), 3)
        c = r.body["contracts"][0]
        self.assertEqual((c["total"], c["players"], c["closed"], c["mine"]), (0, 0, False, 0))
        self.assertEqual(c["target"], c["base"])

    def test_reporting_needs_an_account(self):
        c = self.contract()
        self.assertEqual(self.anon.post(f"/api/games/versus/world/{c['id']}", {"amount": 5}).status, 401)

    def test_each_new_player_raises_the_target(self):
        c = self.contract(2)
        p0, p1 = self.players[:2]
        r = p0.post(f"/api/games/versus/world/{c['id']}", {"amount": 10}).body["contract"]
        self.assertEqual((r["total"], r["players"], r["mine"]), (10, 1, 10))
        self.assertEqual(r["target"], c["base"] + int(0.75 * c["base"] + 0.999))
        r = p0.post(f"/api/games/versus/world/{c['id']}", {"amount": 5}).body["contract"]
        self.assertEqual((r["total"], r["players"]), (15, 1), "the same player again adds no player")
        r = p1.post(f"/api/games/versus/world/{c['id']}", {"amount": 5}).body["contract"]
        self.assertEqual(r["players"], 2); self.assertEqual(r["target"], world.target(c["base"], 2))
        self.assertEqual(p1.get("/api/games/versus/world").body["contracts"][1]["mine"], 5)

    def test_daily_cap_per_player(self):
        c = self.contract(1); cap = world.daily_cap(c["base"])
        p = self.players[0]
        r = p.post(f"/api/games/versus/world/{c['id']}", {"amount": min(cap + 50, world.MAX_ADD)}).body
        self.assertEqual(r["added"], cap)
        r = p.post(f"/api/games/versus/world/{c['id']}", {"amount": 3}).body
        self.assertEqual(r["added"], 0); self.assertIn("today", r["message"])
        with mock.patch("app.now", return_value=self.t0 + 86400):
            self.assertEqual(p.post(f"/api/games/versus/world/{c['id']}", {"amount": 3}).body["added"], 3)

    def test_closes_once_the_target_is_reached(self):
        c = self.contract(1)
        with mock.patch.object(world, "daily_cap", return_value=10 ** 6):
            r = self.players[0].post(f"/api/games/versus/world/{c['id']}", {"amount": world.MAX_ADD}).body["contract"]
            need = world.target(c["base"], 1)
            while r["total"] < need:
                r = self.players[0].post(f"/api/games/versus/world/{c['id']}", {"amount": world.MAX_ADD}).body["contract"]
        self.assertTrue(r["closed"])
        after = self.players[1].post(f"/api/games/versus/world/{c['id']}", {"amount": 5}).body
        self.assertEqual(after["added"], 0); self.assertTrue(after["contract"]["closed"])
        self.assertEqual(after["contract"]["players"], 1, "a closed contract takes no new players")

    def test_bad_reports_are_refused(self):
        c = self.contract(1); p = self.players[0]
        for amt in (0, -3, 2.5, "7", True, world.MAX_ADD + 1):
            self.assertEqual(p.post(f"/api/games/versus/world/{c['id']}", {"amount": amt}).status, 400, amt)
        self.assertEqual(p.post(f"/api/games/versus/world/w{self.wk - 1}-1", {"amount": 3}).status, 409)
        self.assertEqual(p.post(f"/api/games/versus/world/w{self.wk}-9", {"amount": 3}).status, 400)


if __name__ == "__main__":
    unittest.main()
