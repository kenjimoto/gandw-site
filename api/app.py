"""
gandw.io account API: one Goggles & Windchimes account, shared by every game and by the
artist-commissions tracker.

Runs as one AWS Lambda behind CloudFront at /api/*, and locally inside serve.py. Python
standard library only (plus boto3, which the Lambda runtime already ships).

What an account holds, and nothing more:
  username, a salted PBKDF2 password hash, roles, created date, last sign-in date,
  and an email address ONLY if the person opted in to update emails.
No real names, no IP addresses, no analytics. Game saves hang off the account by game id.

Roles
  player   everyone
  artist   granted by an admin; can see and earmark commission reqs
  admin    can manage reqs and accounts

Status codes: the CloudFront distribution rewrites 403 and 404 responses into the site's
404 page for EVERY path, including /api/*. So this API never returns 403 or 404. It uses
401 for "not signed in" and "not allowed", and 400 for "no such thing", always with a
JSON {"error": code, "message": text} body that clients branch on.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import parse_qs

from store import Conflict

# --------------------------------------------------------------------------- settings

SESSION_DAYS = 30
COOKIE = "gw_session"
PBKDF2_ITERS = int(os.environ.get("PBKDF2_ITERS", "210000"))
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,19}$")
RESERVED = {"admin", "administrator", "root", "gandw", "goggles", "windchimes", "support",
            "staff", "mod", "moderator", "system", "null", "undefined", "api", "noreply"}
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,}$")
MAX_BODY = 300_000            # bytes of JSON per request
MAX_SAVE = 256_000            # bytes per game save
MAX_SUMMARY = 2_000           # bytes of the small public-ish summary a game may attach
MAX_EARMARKS = 3              # open earmarks one artist may hold at once
REQ_STATUSES = ("open", "earmarked", "done", "closed")

# Rate limits: (max events, window seconds). Keys never contain IPs or emails.
LIMITS = {
    "login": (10, 900),       # per username
    "register": (30, 3600),   # site-wide
    "contact": (20, 3600),    # site-wide
    "contact_user": (3, 3600),  # per username named in the form
    "verify_send": (5, 86400),  # per account
}


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def bad(code, message, status=400):
    return ApiError(status, code, message)


def now():
    return int(time.time())


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


# --------------------------------------------------------------------------- passwords

def hash_password(pw, iters=None):
    iters = iters or PBKDF2_ITERS
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, iters)
    b = lambda x: base64.b64encode(x).decode()
    return f"pbkdf2_sha256${iters}${b(salt)}${b(dk)}"


def check_password(pw, stored):
    try:
        algo, iters, salt, dk = stored.split("$")
        assert algo == "pbkdf2_sha256"
        got = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except Exception:
        return False


# A hash to check against when the username doesn't exist, so a missing account takes
# as long to reject as a wrong password (no username probing by timing).
_DUMMY = None


def dummy_hash():
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(secrets.token_hex(8))
    return _DUMMY


def temp_password():
    # 4 groups of 4 from an unambiguous alphabet: easy to read out or type from an email
    alpha = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alpha) for _ in range(4)) for _ in range(4))


def validate_password(pw):
    if not isinstance(pw, str) or len(pw) < 10:
        raise bad("weak_password", "Use at least 10 characters for your password.")
    if len(pw) > 128:
        raise bad("weak_password", "That password is too long (128 characters max).")


def validate_username(name):
    if not isinstance(name, str) or not USERNAME_RE.match(name):
        raise bad("bad_username", "Usernames are 3-20 letters, numbers, - or _, starting with a letter or number.")
    if name.lower() in RESERVED:
        raise bad("bad_username", "That username is reserved. Pick another.")


def clean_email(e):
    e = (e or "").strip()
    if len(e) > 254 or not EMAIL_RE.match(e):
        raise bad("bad_email", "That doesn't look like an email address.")
    return e


def text(v, field, maxlen, required=False):
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise bad("bad_input", f"{field} must be text.")
    v = v.replace("\r\n", "\n").strip()
    if required and not v:
        raise bad("bad_input", f"{field} is required.")
    if len(v) > maxlen:
        raise bad("bad_input", f"{field} is too long ({maxlen} characters max).")
    return v


def mask_email(e):
    if not e:
        return None
    local, _, dom = e.partition("@")
    return (local[:1] + "***@" + dom) if local else e


# --------------------------------------------------------------------------- request

class Request:
    def __init__(self, method, path, headers=None, cookies=None, body=None, query=None):
        self.method = method.upper()
        self.path = path
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.cookies = cookies or {}
        self.raw = body or ""
        self.query = query or {}
        self._json = None

    def json(self):
        if self._json is None:
            if len(self.raw) > MAX_BODY:
                raise bad("too_large", "That request is too large.", 413)
            try:
                self._json = json.loads(self.raw) if self.raw else {}
            except ValueError:
                raise bad("bad_json", "Request body must be JSON.")
            if not isinstance(self._json, dict):
                raise bad("bad_json", "Request body must be a JSON object.")
        return self._json


class Response:
    def __init__(self, status=200, body=None, cookies=None):
        self.status = status
        self.body = body if body is not None else {}
        self.cookies = cookies or []


# --------------------------------------------------------------------------- the app

class App:
    def __init__(self, store, mailer, *, notify_to=None, site_origin="https://gandw.io",
                 games=("versus",), origin_secret=None, cookie_secure=True):
        self.db = store
        self.mail = mailer
        self.notify_to = notify_to
        self.site = site_origin.rstrip("/")
        self.games = set(games)
        self.origin_secret = origin_secret
        self.cookie_secure = cookie_secure
        self.routes = []
        R = self.route
        R("POST", r"/api/auth/register", self.register)
        R("POST", r"/api/auth/login", self.login)
        R("POST", r"/api/auth/logout", self.logout)
        R("GET", r"/api/me", self.me, auth=True)
        R("PATCH", r"/api/me", self.update_me, auth=True)
        R("POST", r"/api/me/password", self.change_password, auth=True)
        R("POST", r"/api/me/delete", self.delete_me, auth=True)
        R("POST", r"/api/me/email/resend", self.resend_verify, auth=True)
        R("POST", r"/api/email/verify", self.verify_email)
        R("POST", r"/api/contact", self.contact)
        R("GET", r"/api/games/(?P<game>[a-z0-9-]+)/save", self.get_save, auth=True)
        R("PUT", r"/api/games/(?P<game>[a-z0-9-]+)/save", self.put_save, auth=True)
        R("DELETE", r"/api/games/(?P<game>[a-z0-9-]+)/save", self.delete_save, auth=True)
        R("GET", r"/api/commissions/reqs", self.list_reqs, role="artist")
        R("GET", r"/api/commissions/reqs/(?P<rid>[a-z0-9]+)", self.get_req, role="artist")
        R("POST", r"/api/commissions/reqs/(?P<rid>[a-z0-9]+)/earmark", self.earmark, role="artist")
        R("POST", r"/api/commissions/reqs/(?P<rid>[a-z0-9]+)/release", self.release, role="artist")
        R("GET", r"/api/admin/reqs", self.admin_list_reqs, role="admin")
        R("POST", r"/api/admin/reqs", self.admin_create_req, role="admin")
        R("PATCH", r"/api/admin/reqs/(?P<rid>[a-z0-9]+)", self.admin_update_req, role="admin")
        R("DELETE", r"/api/admin/reqs/(?P<rid>[a-z0-9]+)", self.admin_delete_req, role="admin")
        R("GET", r"/api/admin/users", self.admin_list_users, role="admin")
        R("POST", r"/api/admin/users", self.admin_create_user, role="admin")
        R("PATCH", r"/api/admin/users/(?P<name>[A-Za-z0-9_-]+)", self.admin_update_user, role="admin")
        R("DELETE", r"/api/admin/users/(?P<name>[A-Za-z0-9_-]+)", self.admin_delete_user, role="admin")
        R("GET", r"/api/admin/subscribers", self.admin_subscribers, role="admin")

    def route(self, method, pattern, fn, auth=False, role=None):
        self.routes.append((method, re.compile("^" + pattern + "/?$"), fn, auth or bool(role), role))

    # ------------------------------------------------------------------ dispatch
    def handle(self, req):
        try:
            if self.origin_secret and not hmac.compare_digest(
                    req.headers.get("x-gw-origin", ""), self.origin_secret):
                raise bad("direct_access", "Use https://gandw.io/api/.", 401)
            if req.method not in ("GET", "HEAD", "OPTIONS"):
                # CSRF: browsers only send custom headers on same-origin requests (anything
                # cross-origin needs a CORS preflight, which this API never grants).
                if req.headers.get("x-gw-client") != "1":
                    raise bad("csrf", "Missing client header.", 400)
                origin = req.headers.get("origin")
                if origin and origin.rstrip("/") != self.site:
                    raise bad("csrf", "Cross-site request refused.", 400)
            allowed = []
            for method, rx, fn, auth, role in self.routes:
                m = rx.match(req.path)
                if not m:
                    continue
                allowed.append(method)
                if method != req.method:
                    continue
                user = self.current_user(req) if auth else None
                if auth and not user:
                    raise bad("signed_out", "Please sign in.", 401)
                if role and role not in user["roles"] and "admin" not in user["roles"]:
                    raise bad("forbidden", "Your account doesn't have access to that.", 401)
                req.user = user
                return fn(req, **m.groupdict())
            if allowed:
                raise bad("method", "Method not allowed.", 405)
            raise bad("not_found", "No such API endpoint.", 400)
        except ApiError as e:
            return Response(e.status, {"error": e.code, "message": e.message})

    # ------------------------------------------------------------------ sessions
    def current_user(self, req):
        tok = req.cookies.get(COOKIE)
        if not tok or len(tok) > 100:
            return None
        s = self.db.get("SESS#" + sha(tok), "-")
        if not s:
            return None
        u = self.db.get("USERS", "u#" + s["user"])
        if not u or u.get("gen", 0) != s.get("gen", 0):
            return None
        u["_sess"] = sha(tok)
        return u

    def _cookie(self, value, max_age):
        flags = f"Path=/api; HttpOnly; SameSite=Strict; Max-Age={max_age}"
        if self.cookie_secure:
            flags += "; Secure"
        return f"{COOKIE}={value}; {flags}"

    def _start_session(self, user):
        tok = secrets.token_urlsafe(32)
        exp = now() + SESSION_DAYS * 86400
        self.db.put({"pk": "SESS#" + sha(tok), "sk": "-", "user": user["sk"][2:],
                     "gen": user.get("gen", 0), "ttl": exp})
        self.db.update("USERS", user["sk"], {"last_login": now()})
        return self._cookie(tok, SESSION_DAYS * 86400)

    def _limit(self, kind, key=""):
        n, window = LIMITS[kind]
        bucket = now() // window
        try:
            self.db.incr(f"RL#{kind}#{key}#{bucket}", "-", ttl=(bucket + 1) * window + 60, limit=n)
        except Conflict:
            raise bad("rate_limited", "Too many attempts. Wait a while and try again.", 429)

    # ------------------------------------------------------------------ public views
    def public_user(self, u):
        return {
            "username": u["name"],
            "roles": u.get("roles", ["player"]),
            "created": iso(u.get("created")),
            "must_change_password": bool(u.get("must_change")),
            "updates": {
                "opted_in": bool(u.get("email")),
                "email": mask_email(u.get("email")),
                "verified": u.get("email_status") == "verified",
            },
        }

    def _user(self, name):
        u = self.db.get("USERS", "u#" + (name or "").lower())
        if not u:
            raise bad("no_user", "No account with that username.")
        return u

    # ------------------------------------------------------------------ auth
    def register(self, req):
        b = req.json()
        if b.get("website"):            # honeypot: real people never see this field
            return Response(200, {"ok": True})
        name = b.get("username", "")
        validate_username(name)
        validate_password(b.get("password"))
        email = None
        if b.get("updates"):
            email = clean_email(b.get("email"))
        self._limit("register")
        user = {"pk": "USERS", "sk": "u#" + name.lower(), "name": name,
                "pw": hash_password(b["password"]), "roles": ["player"], "gen": 0,
                "created": now()}
        try:
            self.db.put(user, cond=("absent",))
        except Conflict:
            raise bad("taken", "That username is taken.", 409)
        out = {"ok": True}
        if email:
            out["verification"] = self._set_email(user, email)
            user = self.db.get("USERS", user["sk"])
        cookie = self._start_session(user)
        out["user"] = self.public_user(user)
        return Response(201, out, [cookie])

    def login(self, req):
        b = req.json()
        name = b.get("username") or ""
        pw = b.get("password") or ""
        if not isinstance(name, str) or not isinstance(pw, str) or len(name) > 40 or len(pw) > 128:
            raise bad("bad_login", "Wrong username or password.", 401)
        self._limit("login", name.lower())
        u = self.db.get("USERS", "u#" + name.lower())
        ok = check_password(pw, u["pw"] if u else dummy_hash())
        if not (u and ok):
            raise bad("bad_login", "Wrong username or password.", 401)
        cookie = self._start_session(u)
        return Response(200, {"ok": True, "user": self.public_user(u)}, [cookie])

    def logout(self, req):
        tok = req.cookies.get(COOKIE)
        if tok and len(tok) <= 100:
            self.db.delete("SESS#" + sha(tok), "-")
        return Response(200, {"ok": True}, [self._cookie("", 0)])

    # ------------------------------------------------------------------ my account
    def me(self, req):
        u = req.user
        games = []
        for s in self.db.query("SAVE#" + u["sk"][2:]):
            games.append({"game": s["sk"], "updated": iso(s.get("updated")),
                          "rev": s.get("rev"), "summary": s.get("summary") or {}})
        return Response(200, {"user": self.public_user(u), "games": games})

    def update_me(self, req):
        b = req.json()
        u = req.user
        out = {"ok": True}
        if "updates" in b:
            if b["updates"]:
                email = clean_email(b.get("email") or u.get("email"))
                if email != u.get("email"):
                    out["verification"] = self._set_email(u, email)
            else:
                # opting out deletes the address outright: nothing is kept "just in case"
                self.db.update("USERS", u["sk"], removes=["email", "email_status", "email_at"])
        u = self.db.get("USERS", u["sk"])
        out["user"] = self.public_user(u)
        return Response(200, out)

    def change_password(self, req):
        b = req.json()
        u = req.user
        if not check_password(b.get("current") or "", u["pw"]):
            raise bad("bad_password", "Your current password is wrong.", 401)
        validate_password(b.get("new"))
        gen = u.get("gen", 0) + 1     # signs out every other device
        u = self.db.update("USERS", u["sk"], {"pw": hash_password(b["new"]), "gen": gen},
                           removes=["must_change"])
        self.db.delete("SESS#" + req.user["_sess"], "-")
        cookie = self._start_session(u)
        return Response(200, {"ok": True, "user": self.public_user(u)}, [cookie])

    def delete_me(self, req):
        b = req.json()
        u = req.user
        if not check_password(b.get("password") or "", u["pw"]):
            raise bad("bad_password", "That password is wrong.", 401)
        if "admin" in u.get("roles", []) and len(
                [x for x in self.db.query("USERS", "u#") if "admin" in x.get("roles", [])]) <= 1:
            raise bad("last_admin", "You're the only admin. Make another admin first.", 409)
        self._purge_user(u)
        return Response(200, {"ok": True}, [self._cookie("", 0)])

    def _purge_user(self, u):
        name = u["sk"][2:]
        for s in self.db.query("SAVE#" + name):
            self.db.delete(s["pk"], s["sk"])
        for r in self.db.query("REQS", "r#"):
            if r.get("earmarked_by") == name and r.get("status") == "earmarked":
                self.db.update("REQS", r["sk"], {"status": "open", "updated": now()},
                               removes=["earmarked_by", "earmarked_at"])
        self.db.delete("USERS", u["sk"])

    # ------------------------------------------------------------------ update emails
    def _set_email(self, u, email):
        """Store an opted-in address as pending and send a confirmation link."""
        self.db.update("USERS", u["sk"], {"email": email, "email_status": "pending", "email_at": now()})
        return self._send_verify(u["sk"][2:], u["name"], email)

    def _send_verify(self, key, display, email):
        self._limit("verify_send", key)
        tok = secrets.token_urlsafe(24)
        # the token row holds a hash of the address, never the address itself
        self.db.put({"pk": "VERIFY#" + sha(tok), "sk": "-", "user": key, "email_sha": sha(email.lower()),
                     "ttl": now() + 7 * 86400})
        link = f"{self.site}/account/verify/?t={tok}"
        try:
            self.mail.send(email, "Confirm your Goggles & Windchimes updates",
                           f"Hi {display},\n\nYou asked for occasional emails about Goggles & Windchimes "
                           f"games. Confirm this address here:\n\n  {link}\n\nIf this wasn't you, ignore "
                           f"this message and the address will never be used.\n\nTo stop at any time, "
                           f"untick updates on {self.site}/account/ and the address is deleted.\n")
            return "sent"
        except Exception:
            # SES sandbox (or an outage). The address stays pending; it can be resent later.
            return "pending"

    def resend_verify(self, req):
        u = req.user
        if not u.get("email"):
            raise bad("no_email", "You haven't opted in to updates.")
        if u.get("email_status") == "verified":
            return Response(200, {"ok": True, "verification": "verified"})
        return Response(200, {"ok": True, "verification": self._send_verify(u["sk"][2:], u["name"], u["email"])})

    def verify_email(self, req):
        tok = req.json().get("token") or ""
        if not isinstance(tok, str) or len(tok) > 100:
            raise bad("bad_token", "That confirmation link isn't valid.")
        v = self.db.get("VERIFY#" + sha(tok), "-")
        if not v:
            raise bad("bad_token", "That confirmation link has expired or was already used.")
        self.db.delete(v["pk"], "-")
        u = self.db.get("USERS", "u#" + v["user"])
        if not u or not u.get("email") or sha(u["email"].lower()) != v.get("email_sha"):
            raise bad("bad_token", "That address was changed or removed since the link was sent.")
        try:
            self.db.update("USERS", u["sk"], {"email_status": "verified"}, cond=("eq", "email", u["email"]))
        except Conflict:
            raise bad("bad_token", "That address was changed or removed since the link was sent.")
        return Response(200, {"ok": True})

    # ------------------------------------------------------------------ contact form
    def contact(self, req):
        """Emails the site owner. Stores nothing: the address only exists in that email."""
        b = req.json()
        if b.get("website"):
            return Response(200, {"ok": True})
        kind = b.get("kind")
        subjects = {"commission-access": "Commission access request",
                    "account-help": "Account help request"}
        if kind not in subjects:
            raise bad("bad_input", "Unknown form.")
        name = text(b.get("username"), "Username", 20, required=True)
        email = clean_email(b.get("email"))
        note = text(b.get("note"), "Message", 2000)
        self._limit("contact")
        self._limit("contact_user", name.lower())
        exists = self.db.get("USERS", "u#" + name.lower())
        state = "has an account" if exists else "NO ACCOUNT with this username yet"
        if exists and "artist" in exists.get("roles", []):
            state += " (already an artist)"
        if not self.notify_to:
            raise bad("unavailable", "This form isn't set up yet.", 503)
        body = (f"{subjects[kind]} from gandw.io\n\n"
                f"Username: {name}  ({state})\n"
                f"Reply to: {email}\n\n"
                f"{note or '(no message)'}\n\n"
                f"-- \nReply to this email to answer them. The site did not store their address.\n"
                f"Manage accounts at {self.site}/admin/\n")
        try:
            self.mail.send(self.notify_to, f"{subjects[kind]}: {name}", body, reply_to=email)
        except Exception:
            raise bad("mail_failed", "Sorry, the message couldn't be sent. Try again later.", 502)
        return Response(200, {"ok": True})

    # ------------------------------------------------------------------ game saves
    def _game(self, game):
        if game not in self.games:
            raise bad("no_game", "Unknown game.")
        return game

    def get_save(self, req, game):
        self._game(game)
        s = self.db.get("SAVE#" + req.user["sk"][2:], game)
        if not s:
            return Response(200, {"save": None})
        return Response(200, {"save": {"data": json.loads(s["data"]), "rev": s["rev"],
                                       "updated": iso(s["updated"]), "summary": s.get("summary") or {}}})

    def put_save(self, req, game):
        self._game(game)
        b = req.json()
        if "data" not in b:
            raise bad("bad_input", "Missing save data.")
        data = json.dumps(b["data"], separators=(",", ":"))
        if len(data) > MAX_SAVE:
            raise bad("too_large", "That save is too large.", 413)
        summary = b.get("summary") or {}
        if not isinstance(summary, dict):
            raise bad("bad_input", "summary must be an object.")
        summary = {str(k)[:40]: v for k, v in summary.items()
                   if isinstance(v, (str, int, bool)) and not isinstance(v, float)}
        summary = {k: (v[:80] if isinstance(v, str) else v) for k, v in summary.items()}
        if len(json.dumps(summary)) > MAX_SUMMARY:
            raise bad("too_large", "That summary is too large.", 413)
        pk = "SAVE#" + req.user["sk"][2:]
        base = b.get("base_rev")
        cur = self.db.get(pk, game)
        if cur and not b.get("force") and base != cur["rev"]:
            return Response(409, {"error": "conflict",
                                  "message": "The cloud save changed on another device.",
                                  "save": {"rev": cur["rev"], "updated": iso(cur["updated"]),
                                           "summary": cur.get("summary") or {}}})
        rev = (cur["rev"] if cur else 0) + 1
        item = {"pk": pk, "sk": game, "data": data, "rev": rev, "updated": now(), "summary": summary}
        try:
            # optimistic lock: the rev we read must still be the rev in the table
            self.db.put(item, cond=("eq", "rev", cur["rev"]) if cur else ("absent",))
        except Conflict:
            raise bad("conflict", "The cloud save changed while saving. Try again.", 409)
        return Response(200, {"ok": True, "rev": rev, "updated": iso(item["updated"])})

    def delete_save(self, req, game):
        self._game(game)
        self.db.delete("SAVE#" + req.user["sk"][2:], game)
        return Response(200, {"ok": True})

    # ------------------------------------------------------------------ commissions
    def _req_view(self, r, me=None, full=False, admin=False):
        out = {"id": r["sk"][2:], "title": r["title"], "summary": r.get("summary", ""),
               "fee": r.get("fee", ""), "due": r.get("due", ""), "status": r["status"],
               "created": iso(r.get("created")), "updated": iso(r.get("updated")),
               "mine": bool(me and r.get("earmarked_by") == me)}
        if full:
            out["description"] = r.get("description", "")
        if admin:
            out["earmarked_by"] = r.get("earmarked_by")
            out["earmarked_at"] = iso(r.get("earmarked_at"))
            out["description"] = r.get("description", "")
        return out

    def _get_req(self, rid):
        r = self.db.get("REQS", "r#" + rid)
        if not r:
            raise bad("no_req", "No such req.")
        return r

    def list_reqs(self, req):
        me = req.user["sk"][2:]
        rs = [r for r in self.db.query("REQS", "r#")
              if r["status"] == "open" or (r["status"] == "earmarked" and r.get("earmarked_by") == me)]
        rs.sort(key=lambda r: r.get("created", 0), reverse=True)
        return Response(200, {"reqs": [self._req_view(r, me) for r in rs],
                              "max_earmarks": MAX_EARMARKS})

    def get_req(self, req, rid):
        me = req.user["sk"][2:]
        r = self._get_req(rid)
        visible = r["status"] == "open" or r.get("earmarked_by") == me or "admin" in req.user["roles"]
        if not visible:
            raise bad("taken", "That req has been taken or closed.")
        return Response(200, {"req": self._req_view(r, me, full=True)})

    def earmark(self, req, rid):
        me = req.user["sk"][2:]
        self._get_req(rid)
        held = [r for r in self.db.query("REQS", "r#")
                if r["status"] == "earmarked" and r.get("earmarked_by") == me]
        if len(held) >= MAX_EARMARKS:
            raise bad("too_many", f"You can hold {MAX_EARMARKS} reqs at once. Release one first.", 409)
        try:
            r = self.db.update("REQS", "r#" + rid,
                               {"status": "earmarked", "earmarked_by": me, "earmarked_at": now(),
                                "updated": now()},
                               cond=("eq", "status", "open"))
        except Conflict:
            raise bad("taken", "Someone else earmarked that req first.", 409)
        return Response(200, {"ok": True, "req": self._req_view(r, me, full=True)})

    def release(self, req, rid):
        me = req.user["sk"][2:]
        self._get_req(rid)
        try:
            r = self.db.update("REQS", "r#" + rid, {"status": "open", "updated": now()},
                               removes=["earmarked_by", "earmarked_at"],
                               cond=("eq", "earmarked_by", me))
        except Conflict:
            raise bad("not_yours", "You don't hold that req.", 409)
        return Response(200, {"ok": True, "req": self._req_view(r, me, full=True)})

    # ------------------------------------------------------------------ admin: reqs
    def _req_fields(self, b, partial):
        f = {}
        for key, label, n in (("title", "Title", 120), ("summary", "Summary", 300),
                              ("description", "Description", 8000), ("fee", "Fee", 80),
                              ("due", "Due", 40)):
            if key in b or not partial:
                f[key] = text(b.get(key), label, n, required=(key == "title"))
        return f

    def admin_list_reqs(self, req):
        rs = self.db.query("REQS", "r#")
        rs.sort(key=lambda r: r.get("created", 0), reverse=True)
        names = {u["sk"][2:]: u["name"] for u in self.db.query("USERS", "u#")}
        out = []
        for r in rs:
            v = self._req_view(r, admin=True)
            if v["earmarked_by"]:
                v["earmarked_by"] = names.get(v["earmarked_by"], v["earmarked_by"])
            out.append(v)
        return Response(200, {"reqs": out})

    def admin_create_req(self, req):
        f = self._req_fields(req.json(), partial=False)
        rid = secrets.token_hex(4)
        item = {"pk": "REQS", "sk": "r#" + rid, "status": "open", "created": now(), "updated": now(), **f}
        self.db.put(item, cond=("absent",))
        return Response(201, {"ok": True, "req": self._req_view(item, admin=True)})

    def admin_update_req(self, req, rid):
        b = req.json()
        cur = self._get_req(rid)
        f = self._req_fields(b, partial=True)
        removes = []
        if "status" in b:
            st = b["status"]
            if st not in REQ_STATUSES:
                raise bad("bad_input", "Unknown status.")
            if st == "earmarked" and not cur.get("earmarked_by"):
                raise bad("bad_input", "Only an artist can earmark a req.")
            if st == "open":
                removes = ["earmarked_by", "earmarked_at"]   # "clear" an earmark
            f["status"] = st
        f["updated"] = now()
        r = self.db.update("REQS", "r#" + rid, f, removes=removes, cond=("present",))
        return Response(200, {"ok": True, "req": self._req_view(r, admin=True)})

    def admin_delete_req(self, req, rid):
        self._get_req(rid)
        self.db.delete("REQS", "r#" + rid)
        return Response(200, {"ok": True})

    # ------------------------------------------------------------------ admin: accounts
    def _admin_user_view(self, u):
        return {"username": u["name"], "roles": u.get("roles", []), "created": iso(u.get("created")),
                "last_login": iso(u.get("last_login")), "must_change_password": bool(u.get("must_change")),
                "updates": bool(u.get("email")), "holding": 0}

    def admin_list_users(self, req):
        users = self.db.query("USERS", "u#")
        holding = {}
        for r in self.db.query("REQS", "r#"):
            if r["status"] == "earmarked":
                holding[r.get("earmarked_by")] = holding.get(r.get("earmarked_by"), 0) + 1
        out = []
        for u in sorted(users, key=lambda u: u["sk"]):
            v = self._admin_user_view(u)
            v["holding"] = holding.get(u["sk"][2:], 0)
            out.append(v)
        return Response(200, {"users": out})

    def _roles(self, roles):
        if not isinstance(roles, list) or any(r not in ("player", "artist", "admin") for r in roles):
            raise bad("bad_input", "Roles must be a list of player, artist, admin.")
        return sorted(set(roles) | {"player"})

    def admin_create_user(self, req):
        b = req.json()
        name = b.get("username", "")
        validate_username(name)
        roles = self._roles(b.get("roles") or ["player", "artist"])
        pw = temp_password()
        user = {"pk": "USERS", "sk": "u#" + name.lower(), "name": name, "pw": hash_password(pw),
                "roles": roles, "gen": 0, "created": now(), "must_change": True}
        try:
            self.db.put(user, cond=("absent",))
        except Conflict:
            raise bad("taken", "That username is taken.", 409)
        return Response(201, {"ok": True, "user": self._admin_user_view(user), "temp_password": pw})

    def admin_update_user(self, req, name):
        b = req.json()
        u = self._user(name)
        sets, out = {}, {"ok": True}
        if "roles" in b:
            roles = self._roles(b["roles"])
            if u["sk"] == req.user["sk"] and "admin" not in roles:
                raise bad("self_demote", "You can't remove your own admin role.", 409)
            sets["roles"] = roles
            if "artist" not in roles and "admin" not in roles:
                for r in self.db.query("REQS", "r#"):
                    if r.get("earmarked_by") == u["sk"][2:] and r["status"] == "earmarked":
                        self.db.update("REQS", r["sk"], {"status": "open", "updated": now()},
                                       removes=["earmarked_by", "earmarked_at"])
        if b.get("reset_password"):
            pw = temp_password()
            sets.update({"pw": hash_password(pw), "must_change": True, "gen": u.get("gen", 0) + 1})
            out["temp_password"] = pw
        if sets:
            u = self.db.update("USERS", u["sk"], sets)
        out["user"] = self._admin_user_view(u)
        return Response(200, out)

    def admin_delete_user(self, req, name):
        u = self._user(name)
        if u["sk"] == req.user["sk"]:
            raise bad("self_delete", "Delete your own account from the account page.", 409)
        self._purge_user(u)
        return Response(200, {"ok": True})

    def admin_subscribers(self, req):
        subs = [{"username": u["name"], "email": u["email"], "status": u.get("email_status"),
                 "since": iso(u.get("email_at"))}
                for u in self.db.query("USERS", "u#") if u.get("email")]
        return Response(200, {"subscribers": subs,
                              "verified": sum(1 for s in subs if s["status"] == "verified")})


# --------------------------------------------------------------------------- Lambda glue

def to_lambda(resp):
    return {
        "statusCode": resp.status,
        "headers": {"content-type": "application/json; charset=utf-8",
                    "cache-control": "no-store", "x-content-type-options": "nosniff"},
        "cookies": resp.cookies,
        "body": json.dumps(resp.body),
    }


def from_lambda(event):
    http = event.get("requestContext", {}).get("http", {})
    cookies = {}
    for c in event.get("cookies") or []:
        k, _, v = c.partition("=")
        cookies[k.strip()] = v.strip()
    body = event.get("body") or ""
    if event.get("isBase64Encoded") and body:
        body = base64.b64decode(body).decode("utf-8", "replace")
    query = {k: v[0] for k, v in parse_qs(event.get("rawQueryString") or "").items()}
    return Request(http.get("method", "GET"), event.get("rawPath", "/"),
                   event.get("headers") or {}, cookies, body, query)


_APP = None


def handler(event, context):
    global _APP
    if _APP is None:
        from store import DynamoStore
        from mailer import SesMailer
        _APP = App(DynamoStore(os.environ["TABLE_NAME"]),
                   SesMailer(os.environ.get("MAIL_FROM", "Goggles & Windchimes <noreply@gandw.io>")),
                   notify_to=os.environ.get("NOTIFY_TO") or None,
                   site_origin=os.environ.get("SITE_ORIGIN", "https://gandw.io"),
                   games=tuple(g for g in os.environ.get("GAMES", "versus").split(",") if g),
                   origin_secret=os.environ.get("ORIGIN_SECRET") or None)
    return to_lambda(_APP.handle(from_lambda(event)))
