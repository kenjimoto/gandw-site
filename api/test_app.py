"""Tests for the account API. Stdlib only:  python -m unittest discover -s api"""
import json
import os
import sys
import unittest

os.environ["PBKDF2_ITERS"] = "1000"          # fast hashes for tests
sys.path.insert(0, os.path.dirname(__file__))

import app as api                          # noqa: E402
from mailer import LocalMailer             # noqa: E402
from store import MemoryStore              # noqa: E402


class Client:
    """Acts like one browser: keeps its own session cookie."""
    def __init__(self, app, origin="https://gandw.io"):
        self.app, self.cookies, self.origin = app, {}, origin

    def call(self, method, path, body=None, headers=None):
        h = {"x-gw-client": "1", "origin": self.origin}
        h.update(headers or {})
        r = self.app.handle(api.Request(method, path, h, dict(self.cookies),
                                        json.dumps(body) if body is not None else ""))
        for c in r.cookies:
            k, _, rest = c.partition("=")
            v = rest.split(";")[0]
            if "Max-Age=0" in c:
                self.cookies.pop(k, None)
            else:
                self.cookies[k] = v
        return r

    get = lambda s, p: s.call("GET", p)
    post = lambda s, p, b=None: s.call("POST", p, b or {})
    put = lambda s, p, b=None: s.call("PUT", p, b or {})
    patch = lambda s, p, b=None: s.call("PATCH", p, b or {})
    delete = lambda s, p: s.call("DELETE", p)


def make_app():
    store = MemoryStore()
    mail = LocalMailer(quiet=True)
    app = api.App(store, mail, notify_to="owner@example.com", cookie_secure=True)
    # bootstrap an admin the way the deploy script does: straight into the table
    store.put({"pk": "USERS", "sk": "u#boss", "name": "Boss", "pw": api.hash_password("boss-password-1"),
               "roles": ["player", "admin"], "gen": 0, "created": api.now()})
    return app, store, mail


class Accounts(unittest.TestCase):
    def setUp(self):
        self.app, self.store, self.mail = make_app()
        self.c = Client(self.app)

    def test_register_stores_no_email_by_default(self):
        r = self.c.post("/api/auth/register", {"username": "Pip", "password": "long-enough-pw"})
        self.assertEqual(r.status, 201)
        u = self.store.get("USERS", "u#pip")
        self.assertEqual(set(u) - {"pk", "sk"}, {"name", "pw", "roles", "gen", "created", "last_login"})
        self.assertTrue(u["pw"].startswith("pbkdf2_sha256$"))
        self.assertNotIn("long-enough-pw", json.dumps(u))
        self.assertEqual(self.c.get("/api/me").body["user"]["username"], "Pip")

    def test_session_cookie_flags(self):
        r = self.c.post("/api/auth/register", {"username": "Pip", "password": "long-enough-pw"})
        ck = r.cookies[0]
        for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/api"):
            self.assertIn(flag, ck)
        self.assertEqual(len(self.store.query("SESS#" + api.sha(self.c.cookies["gw_session"]))), 1)

    def test_duplicate_username_case_insensitive(self):
        self.c.post("/api/auth/register", {"username": "Pip", "password": "long-enough-pw"})
        r = Client(self.app).post("/api/auth/register", {"username": "pIP", "password": "long-enough-pw"})
        self.assertEqual(r.status, 409)

    def test_validation(self):
        for body, code in (({"username": "a", "password": "long-enough-pw"}, "bad_username"),
                           ({"username": "admin", "password": "long-enough-pw"}, "bad_username"),
                           ({"username": "Pip", "password": "short"}, "weak_password"),
                           ({"username": "Pip", "password": "long-enough-pw", "updates": True,
                             "email": "nope"}, "bad_email")):
            self.assertEqual(self.c.post("/api/auth/register", body).body["error"], code)

    def test_honeypot_creates_nothing(self):
        r = self.c.post("/api/auth/register", {"username": "Bot", "password": "long-enough-pw", "website": "x"})
        self.assertEqual(r.status, 200)
        self.assertIsNone(self.store.get("USERS", "u#bot"))

    def test_login_logout(self):
        self.c.post("/api/auth/register", {"username": "Pip", "password": "long-enough-pw"})
        self.c.post("/api/auth/logout")
        self.assertEqual(self.c.get("/api/me").status, 401)
        self.assertEqual(self.c.post("/api/auth/login", {"username": "pip", "password": "wrong-password"}).status, 401)
        self.assertEqual(self.c.post("/api/auth/login", {"username": "nobody", "password": "x"}).body["error"], "bad_login")
        self.assertEqual(self.c.post("/api/auth/login", {"username": "pip", "password": "long-enough-pw"}).status, 200)
        self.assertEqual(self.c.get("/api/me").status, 200)

    def test_login_rate_limit(self):
        self.c.post("/api/auth/register", {"username": "Pip", "password": "long-enough-pw"})
        codes = [self.c.post("/api/auth/login", {"username": "pip", "password": "bad-password!"}).status
                 for _ in range(11)]
        self.assertEqual(codes[-1], 429)

    def test_csrf_header_and_origin(self):
        r = self.app.handle(api.Request("POST", "/api/auth/login", {}, {}, "{}"))
        self.assertEqual(r.body["error"], "csrf")
        r = Client(self.app, origin="https://evil.example").post("/api/auth/login", {})
        self.assertEqual(r.body["error"], "csrf")

    def test_origin_secret(self):
        self.app.origin_secret = "s3cret"
        self.assertEqual(self.c.get("/api/me").body["error"], "direct_access")
        r = self.c.call("GET", "/api/me", headers={"x-gw-origin": "s3cret"})
        self.assertEqual(r.body["error"], "signed_out")

    def test_never_403_or_404(self):
        self.assertEqual(self.c.get("/api/nope").status, 400)
        self.c.post("/api/auth/register", {"username": "Pip", "password": "long-enough-pw"})
        self.assertEqual(self.c.get("/api/admin/users").status, 401)
        self.assertEqual(self.c.get("/api/games/zelda/save").status, 400)

    def test_password_change_signs_out_other_devices(self):
        self.c.post("/api/auth/register", {"username": "Pip", "password": "long-enough-pw"})
        other = Client(self.app)
        other.post("/api/auth/login", {"username": "pip", "password": "long-enough-pw"})
        r = self.c.post("/api/me/password", {"current": "long-enough-pw", "new": "another-long-pw"})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.c.get("/api/me").status, 200)
        self.assertEqual(other.get("/api/me").status, 401)

    def test_updates_opt_in_verify_and_opt_out(self):
        r = self.c.post("/api/auth/register", {"username": "Pip", "password": "long-enough-pw",
                                               "updates": True, "email": "pip@example.com"})
        self.assertEqual(r.body["verification"], "sent")
        self.assertEqual(r.body["user"]["updates"]["email"], "p***@example.com")
        link = self.mail.outbox[-1]["text"]
        tok = link.split("?t=")[1].split()[0]
        self.assertEqual(self.c.post("/api/email/verify", {"token": tok}).status, 200)
        self.assertEqual(self.store.get("USERS", "u#pip")["email_status"], "verified")
        self.assertEqual(self.c.post("/api/email/verify", {"token": tok}).status, 400)   # single use
        self.c.patch("/api/me", {"updates": False})
        u = self.store.get("USERS", "u#pip")
        self.assertNotIn("email", u)
        self.assertNotIn("pip@example.com", json.dumps(list(self.store._d.values())))

    def test_opt_out_before_verifying_leaves_no_trace(self):
        self.c.post("/api/auth/register", {"username": "Pip", "password": "long-enough-pw",
                                           "updates": True, "email": "pip@example.com"})
        self.c.patch("/api/me", {"updates": False})
        self.assertNotIn("pip@example.com", json.dumps(list(self.store._d.values())))

    def test_delete_account_removes_everything(self):
        self.c.post("/api/auth/register", {"username": "Pip", "password": "long-enough-pw"})
        self.c.put("/api/games/versus/save", {"data": {"roster": [1]}, "base_rev": None})
        self.assertEqual(self.c.post("/api/me/delete", {"password": "nope-nope-nope"}).status, 401)
        self.assertEqual(self.c.post("/api/me/delete", {"password": "long-enough-pw"}).status, 200)
        self.assertIsNone(self.store.get("USERS", "u#pip"))
        self.assertEqual(self.store.query("SAVE#pip"), [])


class Saves(unittest.TestCase):
    def setUp(self):
        self.app, self.store, _ = make_app()
        self.a = Client(self.app)
        self.a.post("/api/auth/register", {"username": "Pip", "password": "long-enough-pw"})
        self.b = Client(self.app)                        # same account, second device
        self.b.post("/api/auth/login", {"username": "pip", "password": "long-enough-pw"})

    def test_roundtrip_and_summary(self):
        self.assertIsNone(self.a.get("/api/games/versus/save").body["save"])
        r = self.a.put("/api/games/versus/save", {"data": {"roster": [{"name": "Blob"}] * 6, "wins": 4},
                                                  "summary": {"house": 6, "wins": 4, "x": 1.5}, "base_rev": None})
        self.assertEqual(r.body["rev"], 1)
        s = self.b.get("/api/games/versus/save").body["save"]
        self.assertEqual(len(s["data"]["roster"]), 6)
        self.assertEqual(s["summary"], {"house": 6, "wins": 4})          # floats dropped
        self.assertEqual(self.a.get("/api/me").body["games"][0]["game"], "versus")

    def test_conflict_detection(self):
        self.a.put("/api/games/versus/save", {"data": {"v": 1}, "base_rev": None})
        self.b.put("/api/games/versus/save", {"data": {"v": 2}, "base_rev": 1})
        r = self.a.put("/api/games/versus/save", {"data": {"v": 3}, "base_rev": 1})
        self.assertEqual(r.status, 409)
        self.assertEqual(r.body["save"]["rev"], 2)
        r = self.a.put("/api/games/versus/save", {"data": {"v": 3}, "base_rev": 1, "force": True})
        self.assertEqual(r.body["rev"], 3)

    def test_size_cap_and_unknown_game(self):
        r = self.a.put("/api/games/versus/save", {"data": "x" * (api.MAX_SAVE + 10)})
        self.assertEqual(r.status, 413)
        self.assertEqual(self.a.put("/api/games/other/save", {"data": {}}).body["error"], "no_game")

    def test_saves_are_per_account(self):
        self.a.put("/api/games/versus/save", {"data": {"mine": True}, "base_rev": None})
        c = Client(self.app)
        c.post("/api/auth/register", {"username": "Other", "password": "long-enough-pw"})
        self.assertIsNone(c.get("/api/games/versus/save").body["save"])


class Commissions(unittest.TestCase):
    def setUp(self):
        self.app, self.store, self.mail = make_app()
        self.boss = Client(self.app)
        self.boss.post("/api/auth/login", {"username": "boss", "password": "boss-password-1"})
        self.art = Client(self.app)
        self.art.post("/api/auth/register", {"username": "Inky", "password": "long-enough-pw"})

    def new_req(self, title="Bestiary plate: Grubbin"):
        r = self.boss.post("/api/admin/reqs", {"title": title, "summary": "One ink plate",
                                               "description": "Full page.\n\nB&W.", "fee": "$80"})
        self.assertEqual(r.status, 201)
        return r.body["req"]["id"]

    def test_players_cannot_see_reqs_until_granted(self):
        self.new_req()
        self.assertEqual(self.art.get("/api/commissions/reqs").body["error"], "forbidden")
        self.boss.patch("/api/admin/users/inky", {"roles": ["player", "artist"]})
        self.assertEqual(len(self.art.get("/api/commissions/reqs").body["reqs"]), 1)

    def test_earmark_is_exclusive_and_releasable(self):
        rid = self.new_req()
        self.boss.patch("/api/admin/users/inky", {"roles": ["artist"]})
        other = Client(self.app)
        other.post("/api/auth/register", {"username": "Quill", "password": "long-enough-pw"})
        self.boss.patch("/api/admin/users/quill", {"roles": ["artist"]})
        self.assertEqual(self.art.post(f"/api/commissions/reqs/{rid}/earmark").status, 200)
        self.assertEqual(other.post(f"/api/commissions/reqs/{rid}/earmark").body["error"], "taken")
        self.assertEqual(other.get("/api/commissions/reqs").body["reqs"], [])     # hidden once taken
        self.assertTrue(self.art.get("/api/commissions/reqs").body["reqs"][0]["mine"])
        self.assertEqual(other.post(f"/api/commissions/reqs/{rid}/release").body["error"], "not_yours")
        self.assertEqual(self.art.post(f"/api/commissions/reqs/{rid}/release").status, 200)
        self.assertEqual(other.post(f"/api/commissions/reqs/{rid}/earmark").status, 200)
        listing = self.boss.get("/api/admin/reqs").body["reqs"][0]
        self.assertEqual(listing["earmarked_by"], "Quill")

    def test_earmark_cap(self):
        self.boss.patch("/api/admin/users/inky", {"roles": ["artist"]})
        ids = [self.new_req(f"Req {i}") for i in range(api.MAX_EARMARKS + 1)]
        for rid in ids[:-1]:
            self.assertEqual(self.art.post(f"/api/commissions/reqs/{rid}/earmark").status, 200)
        self.assertEqual(self.art.post(f"/api/commissions/reqs/{ids[-1]}/earmark").body["error"], "too_many")

    def test_admin_clear_done_and_role_removal_releases(self):
        rid = self.new_req()
        self.boss.patch("/api/admin/users/inky", {"roles": ["artist"]})
        self.art.post(f"/api/commissions/reqs/{rid}/earmark")
        self.boss.patch(f"/api/admin/reqs/{rid}", {"status": "done"})
        self.assertEqual(self.store.get("REQS", "r#" + rid)["status"], "done")
        self.boss.patch(f"/api/admin/reqs/{rid}", {"status": "open"})
        self.assertNotIn("earmarked_by", self.store.get("REQS", "r#" + rid))
        self.art.post(f"/api/commissions/reqs/{rid}/earmark")
        self.boss.patch("/api/admin/users/inky", {"roles": ["player"]})
        self.assertEqual(self.store.get("REQS", "r#" + rid)["status"], "open")

    def test_admin_creates_artist_with_temp_password(self):
        r = self.boss.post("/api/admin/users", {"username": "Brush", "roles": ["artist"]})
        pw = r.body["temp_password"]
        c = Client(self.app)
        me = c.post("/api/auth/login", {"username": "brush", "password": pw}).body["user"]
        self.assertTrue(me["must_change_password"])
        self.assertIn("artist", me["roles"])
        c.post("/api/me/password", {"current": pw, "new": "my-own-password"})
        self.assertFalse(c.get("/api/me").body["user"]["must_change_password"])

    def test_admin_reset_password_kills_sessions(self):
        r = self.boss.patch("/api/admin/users/inky", {"reset_password": True})
        self.assertIn("temp_password", r.body)
        self.assertEqual(self.art.get("/api/me").status, 401)

    def test_admin_guards(self):
        self.assertEqual(self.boss.patch("/api/admin/users/boss", {"roles": ["player"]}).body["error"], "self_demote")
        self.assertEqual(self.boss.delete("/api/admin/users/boss").body["error"], "self_delete")
        self.assertEqual(self.boss.post("/api/me/delete", {"password": "boss-password-1"}).body["error"], "last_admin")

    def test_access_request_emails_owner_and_stores_nothing(self):
        before = json.dumps(list(self.store._d.values()))
        anon = Client(self.app)
        r = anon.post("/api/contact", {"kind": "commission-access", "username": "Inky",
                                       "email": "inky@example.com", "note": "Portfolio: ink.example"})
        self.assertEqual(r.status, 200)
        m = self.mail.outbox[-1]
        self.assertEqual(m["to"], "owner@example.com")
        self.assertEqual(m["reply_to"], "inky@example.com")
        self.assertIn("has an account", m["text"])
        self.assertNotIn("inky@example.com", json.dumps(list(self.store._d.values())))
        self.assertNotEqual(before, json.dumps(list(self.store._d.values())))   # only a rate-limit counter changed
        for k in self.store._d:
            self.assertTrue(k[0].startswith(("USERS", "SESS#", "RL#")), k)

    def test_contact_rate_limit_per_username(self):
        anon = Client(self.app)
        body = {"kind": "account-help", "username": "Inky", "email": "a@example.com"}
        codes = [anon.post("/api/contact", body).status for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])

    def test_description_only_on_detail(self):
        rid = self.new_req()
        self.boss.patch("/api/admin/users/inky", {"roles": ["artist"]})
        self.assertNotIn("description", self.art.get("/api/commissions/reqs").body["reqs"][0])
        self.assertEqual(self.art.get(f"/api/commissions/reqs/{rid}").body["req"]["description"], "Full page.\n\nB&W.")


class LambdaGlue(unittest.TestCase):
    def test_event_roundtrip(self):
        app, _, _ = make_app()
        api._APP = app
        ev = {"rawPath": "/api/auth/register", "rawQueryString": "",
              "requestContext": {"http": {"method": "POST"}},
              "headers": {"x-gw-client": "1", "origin": "https://gandw.io"},
              "body": json.dumps({"username": "Pip", "password": "long-enough-pw"})}
        out = api.handler(ev, None)
        self.assertEqual(out["statusCode"], 201)
        self.assertTrue(out["cookies"][0].startswith("gw_session="))
        tok = out["cookies"][0].split(";")[0]
        out = api.handler({"rawPath": "/api/me", "requestContext": {"http": {"method": "GET"}},
                           "headers": {}, "cookies": [tok]}, None)
        self.assertEqual(json.loads(out["body"])["user"]["username"], "Pip")
        self.assertEqual(out["headers"]["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
