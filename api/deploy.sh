#!/usr/bin/env bash
# Publish the account API code to the gandw-api Lambda.
#
#   bash api/deploy.sh
#
# Needs AWS credentials for account 584453982080 (us-east-1) that can call
# lambda:UpdateFunctionCode on gandw-api. The function, table, URL and mail settings are
# owned by the gandw-api CloudFormation stack (infra/gandw-api.yaml); this only swaps code.
set -euo pipefail
cd "$(dirname "$0")"

python3 -m unittest discover -s . -q          # never ship a red build

zip_file="$(mktemp -d)/gandw-api.zip"
python3 - "$zip_file" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as z:
    for f in ("app.py", "store.py", "mailer.py", "engine.py"):
        z.write(f)
PY

aws lambda update-function-code --region us-east-1 --function-name gandw-api \
  --zip-file "fileb://${zip_file}" --query 'LastModified' --output text
aws lambda wait function-updated --region us-east-1 --function-name gandw-api

# smoke test through CloudFront: signed-out /api/me must be a JSON 401
code=$(curl -s -o /tmp/gandw-api-smoke.json -w '%{http_code}' https://gandw.io/api/me)
if [ "$code" = "401" ] && grep -q '"signed_out"' /tmp/gandw-api-smoke.json; then
  echo "live: https://gandw.io/api/ answers (401 signed_out, as expected)"
else
  echo "WARNING: https://gandw.io/api/me returned ${code}: $(cat /tmp/gandw-api-smoke.json)" >&2
  exit 1
fi
