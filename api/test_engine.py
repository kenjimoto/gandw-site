"""Tests for the engine hook. Stdlib only:  python -m unittest discover -s api
The local-node test runs only when a built engine bundle is available (ENGINE_LOCAL, or a
sibling VERSUS checkout with dist-engine/); the rest use a fake invoker."""
import json
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import engine  # noqa: E402


class FakeEngine(unittest.TestCase):
    def test_passes_the_action_and_payload_through(self):
        seen = []
        e = engine.Engine(lambda ev: seen.append(ev) or {"ok": True, "tier": "B"})
        self.assertEqual(e.call("validate", creature={"name": "x"}), {"ok": True, "tier": "B"})
        self.assertEqual(seen, [{"action": "validate", "creature": {"name": "x"}}])

    def test_engine_errors_become_exceptions_but_verdicts_do_not(self):
        e = engine.Engine(lambda ev: {"ok": False, "error": "bad_input", "message": "seed"})
        with self.assertRaises(engine.EngineError) as cm:
            e.call("duel")
        self.assertEqual(cm.exception.error, "bad_input")
        # an invalid creature is a verdict, not a failure
        v = engine.Engine(lambda ev: {"ok": False, "error": "attacker_invalid", "reasons": ["ATK"]}).call("duel")
        self.assertEqual(v["error"], "attacker_invalid")

    def test_oversized_payloads_never_leave_the_api(self):
        called = []
        e = engine.Engine(lambda ev: called.append(1) or {"ok": True})
        with self.assertRaises(engine.EngineError):
            e.call("validate", creature={"name": "x" * 300000})
        self.assertEqual(called, [])

    def test_unconfigured_is_unavailable(self):
        old = {k: os.environ.pop(k, None) for k in ("ENGINE_FUNCTION", "ENGINE_LOCAL")}
        try:
            with self.assertRaises(engine.EngineUnavailable):
                engine.Engine.from_env().call("ping")
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v


def _local_bundle():
    p = os.environ.get("ENGINE_LOCAL")
    if p and os.path.exists(p):
        return p
    for guess in ("../../vs/dist-engine/index.mjs", "../../Vs/dist-engine/index.mjs", "../../versus/dist-engine/index.mjs"):
        g = os.path.join(os.path.dirname(os.path.abspath(__file__)), guess)
        if os.path.exists(g):
            return g
    return None


@unittest.skipUnless(shutil.which("node") and _local_bundle(), "no node or no built engine bundle")
class LocalNodeEngine(unittest.TestCase):
    def test_the_real_engine_answers_through_node(self):
        e = engine.Engine(engine._node_invoker(_local_bundle()))
        self.assertTrue(e.call("ping")["ok"])
        r = e.call("validate", creature={"name": "x", "species": "Toaster", "level": 5,
                                         "stats": {"HP": 200, "ATK": 20, "DEF": 15, "SPD": 15, "FOCUS": 15, "AA": 10, "dodge": 9}})
        self.assertIn(r["tier"], "DCBAS")
        self.assertTrue(r["creature"]["cid"])
        with self.assertRaises(engine.EngineError):
            e.call("duel", attacker={}, defender={}, seed=-1, actions=[])


if __name__ == "__main__":
    unittest.main()
