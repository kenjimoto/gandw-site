#!/usr/bin/env python3
"""
Create (or reset) an admin account directly in the gandw-accounts table.
Use it once to make the first admin, or if every admin is locked out.

    python api/make_admin.py Ken

Prints a temporary password; you'll be asked to change it on first sign-in.
Needs the AWS CLI with credentials that can PutItem on gandw-accounts. Stdlib only.
"""
import json
import subprocess
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from app import hash_password, temp_password, validate_username, ApiError  # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    validate_username(name) if name.lower() != "admin" else None
except ApiError as e:
    sys.exit(e.message)

pw = temp_password()
item = {
    "pk": {"S": "USERS"}, "sk": {"S": "u#" + name.lower()}, "name": {"S": name},
    "pw": {"S": hash_password(pw)}, "roles": {"L": [{"S": "player"}, {"S": "admin"}]},
    "gen": {"N": str(int(time.time()))},     # new generation: signs out any old sessions
    "created": {"N": str(int(time.time()))}, "must_change": {"BOOL": True},
}
subprocess.run(["aws", "dynamodb", "put-item", "--region", "us-east-1", "--table-name", "gandw-accounts",
                "--item", json.dumps(item)], check=True)
print(f"\n  Admin '{name}' is ready.\n  Temporary password: {pw}\n  Sign in at https://gandw.io/account/ and set your own.\n")
