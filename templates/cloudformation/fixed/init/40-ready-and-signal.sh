#!/bin/bash
# cfn-init asset: prove the platform end-to-end locally, then answer the WaitConditionHandle.
# This is the only place a deployment may declare itself ready; Golden Verification reads the
# signal as cfn_signal_received and /run/corenova-cfn-init.rc as cfn_init_completed.
set -uo pipefail

STACK="${CFNOVA_STACK_NAME:?}"
REGION="${CFNOVA_AWS_REGION:?}"
APP_NAME="${CFNOVA_APP_NAME:?}"
HEALTH_PATH="${CFNOVA_HEALTH_PATH:-/}"
HANDLE_URL="${CFNOVA_WAIT_HANDLE:?}"
# init.env carries the WaitCondition budget in minutes; leave a two minute margin so a failing
# probe still signals FAILURE before the stack itself times out.
DEADLINE=$(( $(date +%s) + ${CFNOVA_READY_DEADLINE:-1200} - 120 ))

code=000
ok=0
reason="readiness probe timed out"
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:80${HEALTH_PATH}" || echo 000)
  case "$code" in
    2*|3*) reason="nginx reverse proxy answered HTTP $code on :80"; ok=1; break ;;
  esac
  sleep 5
done

init_rc="$(cat /run/corenova-cfn-init.rc 2>/dev/null || echo unknown)"
[ "$init_rc" = "0" ] || ok=0

status=FAILURE
[ "$ok" = 1 ] && status=SUCCESS
detail="{\"Status\":\"${status}\",\"Reason\":\"${reason}; cfn-init rc=${init_rc}\",\"UniqueId\":\"${STACK}-${APP_NAME}\",\"Data\":{\"http_code\":\"${code}\",\"cfn_init_rc\":\"${init_rc}\"}}"

if command -v cfn-signal >/dev/null 2>&1; then
  # 预签名 URL 与逻辑资源（--stack/--resource）二选一，同时传会被拒绝
  # （实测 "Cannot specify both a WaitConditionHandle URL and a logical resource id"）。
  # 用 URL：无需实例凭据。
  cfn-signal -e "$([ "$ok" = 1 ] && echo 0 || echo 1)" "$HANDLE_URL" && exit 0
fi

# Fallback keeps the WaitCondition satisfiable even when aws-cfn-bootstrap failed to install:
# the handle URL is a presigned PUT, so it needs no credentials on the instance.
curl -sS -X PUT -H 'Content-Type:' -d "$detail" "$HANDLE_URL"
