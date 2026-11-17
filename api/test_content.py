"""VERSUS published content (content framework step 3): upload, stage, publish, roll back.
python -m unittest discover -s api"""
import json
import os
import sys
import unittest

os.environ["PBKDF2_ITERS"] = "1000"
sys.path.insert(0, os.path.dirname(__file__))

import app as api                          # noqa: E402
import content as vcontent                 # noqa: E402
from mailer import LocalMailer             # noqa: E402
from store import MemoryStore              # noqa: E402
from test_app import Client                # noqa: E402

BASE = "c946ec46daec4459"


def sample(title="Welcome"):
    return {"npcs": [{"id": "vendor", "name": "Sketch", "em": "🧢"}],
            "quests": [{"id": "welcome", "title": title, "giver": "vendor", "type": "gofer", "desc": "",
                        "objectives": [{"t": "talk", "npc": "vendor"}], "rewards": {"coins": 20}}],
            "items": {"medkit": {"name": "Medkit", "em": "🩹", "type": "consumable", "use": "heal", "heal": 30, "price": 12, "desc": ""}},
            "bosses": [], "lootTables": {"common": [{"item": "medkit", "w": 1, "min": 1, "max": 1}]},
            "enemies": [], "schedules": {"night": {"a": "phase", "in": [3]}}}


class ContentTest(unittest.TestCase):
    def setUp(self):
        self.app = api.App(MemoryStore(), LocalMailer())
        self.ken = Client(self.app)
        self.make("ken", ["player", "admin"])
        self.login(self.ken, "ken")
        self.writer = Client(self.app)
        self.make("wren", ["player", "author"])
        self.login(self.writer, "wren")
        self.player = Client(self.app)
        self.make("pat", ["player"])
        self.login(self.player, "pat")
        self.anon = Client(self.app)

    def make(self, name, roles):
        self.app.db.put({"pk": "USERS", "sk": "u#" + name, "name": name, "pw": api.hash_password("correct horse 1"),
                         "roles": roles, "gen": 0, "created": api.now()})

    def login(self, c, name):
        r = c.post("/api/auth/login", {"username": name, "password": "correct horse 1"})
        self.assertEqual(r.status, 200, r.body)

    def upload(self, c, content=None, base=BASE, core="2.3.0", note=""):
        return c.post("/api/admin/versus/content", {"content": content or sample(), "base": base, "core": core, "note": note})

    def script(self, c):
        r = c.get("/api/games/versus/content.js")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.ctype.startswith("application/javascript"))
        self.assertEqual(r.cache, "no-store")
        t = r.payload()
        if not t.startswith("window.VERSUS_LIVE="):
            return None
        return json.loads(t[len("window.VERSUS_LIVE="):].rstrip().rstrip(";"))

    def test_only_authors_and_admins_can_upload(self):
        self.assertEqual(self.upload(self.player).status, 401)
        self.assertEqual(self.upload(self.anon).status, 401)
        self.assertEqual(self.upload(self.writer).status, 200)
        self.assertEqual(self.upload(self.ken).status, 200)
        self.assertEqual(self.player.get("/api/admin/versus/content").status, 401)

    def test_nothing_published_means_the_game_keeps_its_own(self):
        self.assertIsNone(self.script(self.anon))
        self.assertEqual(self.anon.get("/api/games/versus/content").body, {"version": None})

    def test_staged_content_is_seen_only_by_its_author_until_published(self):
        r = self.upload(self.writer, sample("Staged hello"), note="first try")
        self.assertEqual(r.body, {"version": "v1", "staged": True})
        mine = self.script(self.writer)
        self.assertEqual((mine["version"], mine["staged"], mine["by"]), ("v1", True, "wren"))
        self.assertEqual(mine["content"]["quests"][0]["title"], "Staged hello")
        self.assertIsNone(self.script(self.player), "players see nothing staged")
        self.assertIsNone(self.script(self.ken), "nor does another author or admin")
        self.assertEqual(self.writer.post("/api/admin/versus/content/v1/publish").body, {"live": "v1"})
        for c in (self.player, self.anon, self.ken, self.writer):
            got = self.script(c)
            self.assertEqual((got["version"], got["staged"]), ("v1", False))
            self.assertIsNone(got["by"])
        self.assertEqual(self.anon.get("/api/games/versus/content").body["version"], "v1")

    def test_publishing_an_older_version_rolls_back(self):
        self.upload(self.writer, sample("one"))
        self.writer.post("/api/admin/versus/content/v1/publish")
        self.upload(self.writer, sample("two"))
        self.writer.post("/api/admin/versus/content/v2/publish")
        self.assertEqual(self.script(self.player)["content"]["quests"][0]["title"], "two")
        self.writer.post("/api/admin/versus/content/v1/publish")
        self.assertEqual(self.script(self.player)["content"]["quests"][0]["title"], "one")
        lst = self.writer.get("/api/admin/versus/content").body
        self.assertEqual(lst["live"], "v1")
        self.assertEqual([v["version"] for v in lst["versions"]], ["v2", "v1"])
        self.assertEqual(lst["versions"][1]["published_by"], "wren")
        self.assertEqual(lst["versions"][0]["counts"]["quests"], 1)
        self.assertNotIn("content", lst["versions"][0])
        self.assertEqual(self.writer.post("/api/admin/versus/content/v9/publish").status, 400)

    def test_staging_and_unstaging(self):
        self.upload(self.writer, sample("one"))
        self.writer.post("/api/admin/versus/content/v1/publish")
        self.upload(self.writer, sample("two"))
        self.assertEqual(self.script(self.writer)["content"]["quests"][0]["title"], "two")
        self.assertEqual(self.writer.delete("/api/admin/versus/stage").body, {"staged": None})
        self.assertEqual(self.script(self.writer)["content"]["quests"][0]["title"], "one")
        self.writer.post("/api/admin/versus/content/v2/stage")
        self.assertEqual(self.script(self.writer)["version"], "v2")
        self.assertEqual(self.writer.get("/api/admin/versus/content").body["staged"], "v2")
        full = self.writer.get("/api/admin/versus/content/v2").body
        self.assertEqual(full["content"]["quests"][0]["title"], "two")

    def test_the_shape_is_checked_again_here(self):
        bad = [
            ({"quests": []}, "missing npcs"),
            ({**sample(), "spells": []}, "doesn't know"),
            ({**sample(), "quests": {"a": 1}}, "must be a list"),
            ({**sample(), "quests": [{"id": "a b"}]}, "id of letters"),
            ({**sample(), "quests": [{"id": "a"}, {"id": "a"}]}, "appears twice"),
            ({**sample(), "items": {"bad id": {}}}, "not a valid id"),
            ({**sample(), "lootTables": {"t": {}}}, "list of rows"),
            ({**sample(), "npcs": [{"id": "x", "name": "y" * 260_000}]}, "too large"),
        ]
        for content, why in bad:
            r = self.upload(self.writer, content)
            self.assertEqual(r.status, 400, why)
            self.assertIn(why, r.body["message"])
        self.assertIn("fingerprint", self.upload(self.writer, base="nope").body["message"])
        self.assertIn("version like", self.upload(self.writer, core="two").body["message"])

    def test_the_script_cannot_break_out(self):
        t = vcontent.as_script({"content": {"x": "</script><script>alert(1)</script> "}})
        self.assertNotIn("</script>", t)
        self.assertNotIn(" ", t)
        self.assertTrue(t.startswith("window.VERSUS_LIVE="))

    def test_admins_can_grant_the_author_role(self):
        r = self.ken.patch("/api/admin/users/pat", {"roles": ["player", "author"]})
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual(self.upload(self.player).status, 200)


if __name__ == "__main__":
    unittest.main()
