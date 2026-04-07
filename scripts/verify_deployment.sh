#!/usr/bin/env bash
# Run this anytime to verify Dev stack is healthy.
# Does NOT touch production.
set -e

PASS=0
FAIL=0

check() {
    local label="$1"
    local result="$2"
    if [ "$result" = "pass" ]; then
        echo "  [PASS] $label"
        PASS=$((PASS+1))
    else
        echo "  [FAIL] $label"
        FAIL=$((FAIL+1))
    fi
}

echo "=== Zero-Human Dev Stack Verification ==="
echo ""

echo "--- Production services (must stay active) ---"
for svc in paperclip paperclip-dev paperclip-proxy; do
    state=$(systemctl is-active "$svc" 2>/dev/null || echo inactive)
    check "$svc is active" "$([ "$state" = 'active' ] && echo pass || echo fail)"
done

echo ""
echo "--- New Dev services ---"
for svc in zerohuman-backend-api zerohuman-celery-worker; do
    state=$(systemctl is-active "$svc" 2>/dev/null || echo inactive)
    check "$svc is active" "$([ "$state" = 'active' ] && echo pass || echo fail)"
done

echo ""
echo "--- Infrastructure ---"
redis_ping=$(redis-cli ping 2>/dev/null || echo "")
check "Redis responds to PING" "$([ "$redis_ping" = 'PONG' ] && echo pass || echo fail)"

echo ""
echo "--- API health check (port 8100) ---"
health=$(curl -s http://127.0.0.1:8100/health 2>/dev/null || echo "{}")
check "GET /health returns {status:ok}" "$(echo "$health" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("pass" if d.get("status")=="ok" else "fail")' 2>/dev/null || echo fail)"

echo ""
echo "--- End-to-end task test ---"
task_resp=$(curl -s -X POST http://127.0.0.1:8100/task \
  -H "Content-Type: application/json" \
  -d '{"issue_id":"verify-run","repo_url":"https://github.com/test/repo","user_id":"verify","metadata":{}}' 2>/dev/null || echo "{}")
task_id=$(echo "$task_resp" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("task_id",""))' 2>/dev/null || echo "")
check "POST /task returns task_id" "$([ -n "$task_id" ] && echo pass || echo fail)"

sleep 5
if [ -n "$task_id" ]; then
    status_resp=$(curl -s "http://127.0.0.1:8100/status/$task_id" 2>/dev/null || echo "{}")
    state=$(echo "$status_resp" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("state",""))' 2>/dev/null || echo "")
    check "Task completes with SUCCESS" "$([ "$state" = 'SUCCESS' ] && echo pass || echo fail)"
fi

echo ""
echo "=== Result: ${PASS} passed, ${FAIL} failed ==="
if [ "$FAIL" -eq 0 ]; then
    echo "All checks passed. Stack is healthy."
else
    echo "Some checks failed. Review above output."
    exit 1
fi
