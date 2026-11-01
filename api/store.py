"""
Storage for the gandw.io API.

One DynamoDB table, keyed (pk, sk). Two implementations share one small interface:

  DynamoStore   production, via boto3 (bundled in the Lambda runtime; nothing to install)
  MemoryStore   local dev and tests; optionally persisted to a JSON file

Item layout
-----------
  pk="USERS"          sk="u#<name lower>"   account: name, pw, roles, gen, created, email...
  pk="SESS#<sha256>"  sk="-"                session: user, gen, ttl
  pk="SAVE#<name>"    sk="<game id>"        game save: data, rev, summary, updated
  pk="REQS"           sk="r#<id>"           commission req
  pk="VERIFY#<sha>"   sk="-"                email verification token: user, ttl
  pk="RL#<bucket>"    sk="-"                rate-limit counter: n, ttl

Items with a numeric `ttl` attribute expire on their own (DynamoDB TTL). Reads also
treat an expired item as absent, because DynamoDB deletes lazily (up to a few days late).
"""
import json
import threading
import time
from decimal import Decimal
from pathlib import Path


class Conflict(Exception):
    """A conditional write failed."""


def _expired(item):
    return item is not None and "ttl" in item and item["ttl"] <= int(time.time())


def _plain(v):
    """DynamoDB hands numbers back as Decimal; turn them into int/float."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


# Conditions are tiny tuples so both stores can evaluate them:
#   ("absent",)                 item must not exist (or be expired)
#   ("present",)                item must exist
#   ("eq", attr, value)         item exists and item[attr] == value
#   ("lt", attr, value)         item missing, or item[attr] < value (counters)


class MemoryStore:
    def __init__(self, path=None):
        self._lock = threading.RLock()
        self._path = Path(path) if path else None
        self._d = {}
        if self._path and self._path.is_file():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._d = {tuple(k.split("\x1f", 1)): v for k, v in raw.items()}

    def _flush(self):
        if self._path:
            raw = {"\x1f".join(k): v for k, v in self._d.items()}
            self._path.write_text(json.dumps(raw, indent=1), encoding="utf-8")

    def _check(self, cur, cond):
        if cur is not None and _expired(cur):
            cur = None
        if not cond:
            return
        kind = cond[0]
        ok = {
            "absent": lambda: cur is None,
            "present": lambda: cur is not None,
            "eq": lambda: cur is not None and cur.get(cond[1]) == cond[2],
            "lt": lambda: cur is None or cur.get(cond[1], 0) < cond[2],
        }[kind]()
        if not ok:
            raise Conflict(kind)

    def get(self, pk, sk):
        with self._lock:
            it = self._d.get((pk, sk))
            return None if it is None or _expired(it) else json.loads(json.dumps(it))

    def put(self, item, cond=None):
        with self._lock:
            key = (item["pk"], item["sk"])
            self._check(self._d.get(key), cond)
            self._d[key] = json.loads(json.dumps(item))
            self._flush()

    def update(self, pk, sk, sets=None, removes=(), cond=None):
        with self._lock:
            cur = self._d.get((pk, sk))
            self._check(cur, cond)
            if cur is None or _expired(cur):
                cur = {"pk": pk, "sk": sk}
            cur.update(json.loads(json.dumps(sets or {})))
            for r in removes:
                cur.pop(r, None)
            self._d[(pk, sk)] = cur
            self._flush()
            return json.loads(json.dumps(cur))

    def incr(self, pk, sk, ttl, limit):
        """Atomically add 1. Raises Conflict once the counter has reached `limit`."""
        with self._lock:
            cur = self._d.get((pk, sk))
            if cur is None or _expired(cur):
                cur = {"pk": pk, "sk": sk, "n": 0, "ttl": ttl}
            if cur["n"] >= limit:
                raise Conflict("limit")
            cur["n"] += 1
            self._d[(pk, sk)] = cur
            self._flush()
            return cur["n"]

    def delete(self, pk, sk, cond=None):
        with self._lock:
            self._check(self._d.get((pk, sk)), cond)
            self._d.pop((pk, sk), None)
            self._flush()

    def query(self, pk, prefix=""):
        with self._lock:
            out = [json.loads(json.dumps(v)) for (p, s), v in self._d.items()
                   if p == pk and s.startswith(prefix) and not _expired(v)]
            return sorted(out, key=lambda i: i["sk"])


class DynamoStore:
    def __init__(self, table_name):
        import boto3  # bundled with the Lambda Python runtime
        from boto3.dynamodb.conditions import Attr, Key
        self._t = boto3.resource("dynamodb").Table(table_name)
        self._Attr, self._Key = Attr, Key
        self._client = self._t.meta.client

    def _cond(self, cond):
        if not cond:
            return {}
        A = self._Attr
        now = int(time.time())
        not_live = A("pk").not_exists() | (A("ttl").exists() & A("ttl").lte(now))
        kind = cond[0]
        if kind == "absent":
            expr = not_live
        elif kind == "present":
            expr = A("pk").exists()
        elif kind == "eq":
            expr = A(cond[1]).eq(cond[2])
        elif kind == "lt":
            expr = A("pk").not_exists() | A(cond[1]).lt(cond[2])
        else:
            raise ValueError(kind)
        return {"ConditionExpression": expr}

    def _run(self, fn, **kw):
        try:
            return fn(**kw)
        except self._client.exceptions.ConditionalCheckFailedException as e:
            raise Conflict(str(e)) from None

    def get(self, pk, sk):
        it = self._t.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")
        return None if it is None or _expired(_plain(it)) else _plain(it)

    def put(self, item, cond=None):
        self._run(self._t.put_item, Item=item, **self._cond(cond))

    def update(self, pk, sk, sets=None, removes=(), cond=None):
        sets = sets or {}
        names, values, parts = {}, {}, []
        for i, (k, v) in enumerate(sets.items()):
            names[f"#s{i}"] = k
            values[f":s{i}"] = v
            parts.append(f"#s{i} = :s{i}")
        expr = ("SET " + ", ".join(parts)) if parts else ""
        if removes:
            for i, k in enumerate(removes):
                names[f"#r{i}"] = k
            expr += (" " if expr else "") + "REMOVE " + ", ".join(f"#r{i}" for i in range(len(removes)))
        kw = dict(Key={"pk": pk, "sk": sk}, UpdateExpression=expr,
                  ExpressionAttributeNames=names, ReturnValues="ALL_NEW")
        if values:
            kw["ExpressionAttributeValues"] = values
        c = self._cond(cond)
        if c:
            # boto3 can't mix a condition object with raw name maps, so render it ourselves
            from boto3.dynamodb.conditions import ConditionExpressionBuilder
            built = ConditionExpressionBuilder().build_expression(c["ConditionExpression"])
            kw["ConditionExpression"] = built.condition_expression
            names.update(built.attribute_name_placeholders)
            values.update(built.attribute_value_placeholders)
            kw["ExpressionAttributeValues"] = values
        return _plain(self._run(self._t.update_item, **kw)["Attributes"])

    def incr(self, pk, sk, ttl, limit):
        now = int(time.time())
        try:
            r = self._t.update_item(
                Key={"pk": pk, "sk": sk},
                UpdateExpression="SET #n = if_not_exists(#n, :z) + :one, #t = if_not_exists(#t, :ttl)",
                ConditionExpression="attribute_not_exists(#n) OR #n < :lim OR #t <= :now",
                ExpressionAttributeNames={"#n": "n", "#t": "ttl"},
                ExpressionAttributeValues={":z": 0, ":one": 1, ":ttl": ttl, ":lim": limit, ":now": now},
                ReturnValues="ALL_NEW")
        except self._client.exceptions.ConditionalCheckFailedException:
            raise Conflict("limit") from None
        it = _plain(r["Attributes"])
        if it["ttl"] <= now:
            # the window had lapsed but DynamoDB hadn't swept it yet: start a fresh window
            self._t.put_item(Item={"pk": pk, "sk": sk, "n": 1, "ttl": ttl})
            return 1
        return it["n"]

    def delete(self, pk, sk, cond=None):
        self._run(self._t.delete_item, Key={"pk": pk, "sk": sk}, **self._cond(cond))

    def query(self, pk, prefix=""):
        K = self._Key
        kc = K("pk").eq(pk) & K("sk").begins_with(prefix) if prefix else K("pk").eq(pk)
        out, kw = [], {"KeyConditionExpression": kc, "ConsistentRead": True}
        while True:
            r = self._t.query(**kw)
            out += [_plain(i) for i in r.get("Items", [])]
            if "LastEvaluatedKey" not in r:
                break
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        return [i for i in out if not _expired(i)]
