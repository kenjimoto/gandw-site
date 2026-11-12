"""The VERSUS engine, as seen from the account API.

The rules of a battle live in JavaScript (VERSUS packages/core). The API calls them through
the private gandw-versus-engine Lambda rather than re-implementing them in Python, so the
server can never disagree with the game. See versus_pvp_backend_plan.md in the Vs repo.

    Engine.from_env().call("validate", creature=...)   -> {"ok":..., "tier":..., ...}
    Engine.from_env().call("duel", attacker=..., defender=..., seed=..., actions=[...])

Where it runs:
  * ENGINE_FUNCTION set (production): boto3 Lambda invoke, synchronous.
  * ENGINE_LOCAL set to a built dist-engine/index.mjs (serve.py --api --versus <repo>):
    runs it with the local `node`, one process per call. Slow, fine for development.
  * neither: calls raise EngineUnavailable, and endpoints should answer 503 engine_unavailable.

Nothing calls this yet: the PvP endpoints arrive in step 4. Stdlib + boto3 only.
"""
import json
import os
import subprocess

TIMEOUT_S = 8
MAX_PAYLOAD = 240 * 1024


class EngineUnavailable(Exception):
    pass


class EngineError(Exception):
    def __init__(self, error, message=""):
        super().__init__(f"{error}: {message}")
        self.error, self.message = error, message


class Engine:
    def __init__(self, invoke):
        self._invoke = invoke          # dict -> dict

    @classmethod
    def from_env(cls):
        fn = os.environ.get("ENGINE_FUNCTION")
        if fn:
            return cls(_lambda_invoker(fn))
        local = os.environ.get("ENGINE_LOCAL")
        if local:
            return cls(_node_invoker(local))
        return cls(_unavailable)

    def call(self, action, **payload):
        event = dict(payload, action=action)
        body = json.dumps(event, separators=(",", ":"))
        if len(body) > MAX_PAYLOAD:
            raise EngineError("bad_input", "payload too large")
        result = self._invoke(event)
        if not isinstance(result, dict):
            raise EngineError("engine_error", "the engine returned something that isn't an object")
        if result.get("error") in ("bad_input", "engine_error"):
            raise EngineError(result["error"], result.get("message", ""))
        return result


def _unavailable(event):
    raise EngineUnavailable("no ENGINE_FUNCTION or ENGINE_LOCAL configured")


def _lambda_invoker(function_name):
    import boto3
    from botocore.config import Config
    client = boto3.client("lambda", config=Config(read_timeout=TIMEOUT_S, retries={"max_attempts": 1}))

    def invoke(event):
        r = client.invoke(FunctionName=function_name, InvocationType="RequestResponse",
                          Payload=json.dumps(event).encode("utf-8"))
        payload = r["Payload"].read().decode("utf-8")
        if r.get("FunctionError"):
            raise EngineError("engine_error", payload[:300])
        return json.loads(payload)
    return invoke


def _node_invoker(bundle_path):
    bundle = os.path.abspath(bundle_path)
    script = ("import(process.argv[1]).then(async m=>{let s='';for await(const c of process.stdin)s+=c;"
              "process.stdout.write(JSON.stringify(await m.handler(JSON.parse(s))));})")

    def invoke(event):
        try:
            r = subprocess.run(["node", "--input-type=module", "-e", script, "file://" + bundle],
                               input=json.dumps(event), capture_output=True, text=True, timeout=TIMEOUT_S)
        except FileNotFoundError as e:
            raise EngineUnavailable("node is not installed") from e
        except subprocess.TimeoutExpired as e:
            raise EngineError("engine_error", "timed out") from e
        if r.returncode != 0:
            raise EngineError("engine_error", (r.stderr or "")[-300:])
        return json.loads(r.stdout)
    return invoke
