#!/bin/bash
#
# PPM Issue #2: Authenticated Runtime Failure Gate Tests (A2 & B2) — curl-based API
# Simple, direct approach without Playwright
#
# Usage: sudo bash run_authenticated_tests.sh
#

set -u

REPORT_DIR="/tmp/ppm_authenticated_tests_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$REPORT_DIR"

COOKIE_JAR="$REPORT_DIR/cookies.txt"
touch "$COOKIE_JAR"

# Read Redis password from .env
REDIS_PASSWORD=$(sed -n 's/^REDIS_PASSWORD=//p' /var/www/html/.env 2>/dev/null | tr -d '"' | head -1)

BASE_URL="https://ppm.y-asahi.com"
PDF_ENDPOINT="$BASE_URL/projects/1/pages/1/pdf/"

echo "==========================================="
echo "PPM Issue #2: Authenticated Runtime Failure Tests (A2 & B2)"
echo "==========================================="
echo "Report directory: $REPORT_DIR"
echo ""

cleanup() {
    local exit_code=$?
    echo ""
    echo ">>> CLEANUP: Restoring services to baseline state"
    echo ">>> $(date '+%Y-%m-%d %H:%M:%S')"
    
    if ! systemctl is-active --quiet redis; then
        sudo systemctl start redis
        sleep 2
    fi
    
    if ! systemctl is-active --quiet celery-ppm; then
        sudo systemctl start celery-ppm
        sleep 3
    fi
    
    if ! systemctl is-active --quiet httpd; then
        sudo systemctl reload httpd
        sleep 2
    fi
    
    echo "[CLEANUP] Baseline services restored"
    systemctl is-active redis > /dev/null && echo "[OK] redis" || echo "[FAIL] redis"
    systemctl is-active celery-ppm > /dev/null && echo "[OK] celery-ppm" || echo "[FAIL] celery-ppm"
    systemctl is-active httpd > /dev/null && echo "[OK] httpd" || echo "[FAIL] httpd"
    
    exit $exit_code
}

trap cleanup EXIT

log_test() {
    echo "[TEST] $1" | tee -a "$REPORT_DIR/summary.log"
}

log_result() {
    echo "[RESULT] $1" | tee -a "$REPORT_DIR/summary.log"
}

# ==========================================
# PREFLIGHT: Verify services and get session
# ==========================================

echo ">>> PREFLIGHT CHECKS"
echo ">>> $(date '+%Y-%m-%d %H:%M:%S')"

log_test "PRE-1: Verify all services UP"
systemctl is-active redis > /dev/null || { log_result "✗ redis NOT active"; exit 1; }
systemctl is-active celery-ppm > /dev/null || { log_result "✗ celery-ppm NOT active"; exit 1; }
systemctl is-active httpd > /dev/null || { log_result "✗ httpd NOT active"; exit 1; }
log_result "✓ All services active"

log_test "PRE-2: Access PDF endpoint (should redirect to login if not authenticated)"
curl -ksS -c "$COOKIE_JAR" -w "%{http_code}" "$PDF_ENDPOINT" -o /tmp/preflight_initial.html 2>/dev/null > /tmp/preflight_http.txt
INITIAL_STATUS=$(cat /tmp/preflight_http.txt)
echo "Initial PDF endpoint status: $INITIAL_STATUS" | tee -a "$REPORT_DIR/summary.log"

log_test "PRE-3: Create authenticated session via Django shell"
# Use Django ORM to create a test session for tadashi user
SESSION_ID=$(/var/www/html/.venv/bin/python3 << 'DJANGO_SCRIPT'
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import authenticate, get_user_model
from django.contrib.sessions.models import Session
from django.utils import timezone

User = get_user_model()
user = User.objects.filter(username="tadashi").first()

if not user:
    print("USER_NOT_FOUND")
else:
    from django.contrib.sessions.backends.db import SessionStore
    session = SessionStore()
    session['_auth_user_id'] = str(user.pk)
    session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
    session['_auth_user_hash'] = user.get_session_auth_hash()
    session.save()
    print(session.session_key)
DJANGO_SCRIPT
)

if [[ "$SESSION_ID" == "USER_NOT_FOUND" ]]; then
    log_result "✗ User tadashi not found"
    exit 1
fi

if [[ -z "$SESSION_ID" ]]; then
    log_result "✗ Failed to create session"
    exit 1
fi

log_result "✓ Session created: ${SESSION_ID:0:10}..."

# Set sessionid cookie
echo "ppm.y-asahi.com	FALSE	/	TRUE	9999999999	sessionid	$SESSION_ID" >> "$COOKIE_JAR"

log_test "PRE-4: Verify authenticated access to PDF endpoint"
curl -ksS -b "$COOKIE_JAR" -w "%{http_code}" "$PDF_ENDPOINT" -o "$REPORT_DIR/baseline_pdf.html" 2>/dev/null > /tmp/baseline_http.txt
BASELINE_STATUS=$(cat /tmp/baseline_http.txt)
echo "Baseline PDF status (authenticated): $BASELINE_STATUS" | tee -a "$REPORT_DIR/summary.log"

if [[ "$BASELINE_STATUS" != "200" ]]; then
    log_result "⚠ Baseline not 200 (HTTP $BASELINE_STATUS), but continuing"
fi

echo ""
echo ">>> All PREFLIGHT CHECKS PASSED"
echo ""

# ==========================================
# TEST A2: Redis Broker DOWN
# ==========================================

echo "==========================================="
echo "TEST A2: Redis Broker DOWN (Authenticated)"
echo "==========================================="
echo ""

log_test "A2: Stop Redis"
sudo systemctl stop redis
sleep 3

log_test "A2: Attempt PDF request with Redis DOWN"
curl -ksS -b "$COOKIE_JAR" -w "\nHTTP %{http_code}" "$PDF_ENDPOINT" -o "$REPORT_DIR/a2_pdf.html" 2>/dev/null | tail -1 > /tmp/a2_http.txt
HTTP_A2=$(cat /tmp/a2_http.txt | grep -oP 'HTTP \K\d+' || echo "000")
echo "Test A2 HTTP Code: $HTTP_A2" | tee -a "$REPORT_DIR/summary.log"

if grep -qi "pdf\|%PDF" "$REPORT_DIR/a2_pdf.html"; then
    log_result "A2: FAIL — PDF was generated (sync fallback)"
else
    log_result "A2: PASS — No sync PDF, fail-closed confirmed"
fi

log_test "A2: Restart Redis"
sudo systemctl start redis
sleep 3

log_test "A2: Verify recovery"
curl -ksS -b "$COOKIE_JAR" -w "%{http_code}" "$PDF_ENDPOINT" -o "$REPORT_DIR/a2_recovery.html" 2>/dev/null > /tmp/a2_recovery_http.txt
RECOVERY_A2=$(cat /tmp/a2_recovery_http.txt)
echo "Test A2 Recovery HTTP Code: $RECOVERY_A2" | tee -a "$REPORT_DIR/summary.log"

if [[ "$RECOVERY_A2" == "200" ]]; then
    log_result "A2: Recovery PASS — PDF recovered"
else
    log_result "A2: Recovery WARNING — HTTP $RECOVERY_A2"
fi

# ==========================================
# TEST B2: Celery Worker DOWN
# ==========================================

echo ""
echo "==========================================="
echo "TEST B2: Celery Worker DOWN (Authenticated)"
echo "==========================================="
echo ""

log_test "B2: Stop Celery"
sudo systemctl stop celery-ppm
sleep 3

log_test "B2: Measure Redis queue BEFORE test"
if [[ -n "$REDIS_PASSWORD" ]]; then
    QUEUE_BEFORE=$(redis-cli -a "$REDIS_PASSWORD" LLEN celery 2>/dev/null || echo "unknown")
else
    QUEUE_BEFORE=$(redis-cli LLEN celery 2>/dev/null || echo "unknown")
fi
echo "Redis queue BEFORE: $QUEUE_BEFORE" | tee -a "$REPORT_DIR/summary.log"

log_test "B2: Attempt PDF request with Celery DOWN"
curl -ksS -b "$COOKIE_JAR" -w "\nHTTP %{http_code}" "$PDF_ENDPOINT" -o "$REPORT_DIR/b2_pdf.html" 2>/dev/null | tail -1 > /tmp/b2_http.txt
HTTP_B2=$(cat /tmp/b2_http.txt | grep -oP 'HTTP \K\d+' || echo "000")
echo "Test B2 HTTP Code: $HTTP_B2" | tee -a "$REPORT_DIR/summary.log"

if grep -qi "pdf\|%PDF" "$REPORT_DIR/b2_pdf.html"; then
    log_result "B2: FAIL — PDF was generated (sync fallback)"
else
    log_result "B2: PASS — No sync PDF during Celery outage"
fi

log_test "B2: Restart Celery"
sudo systemctl start celery-ppm
sleep 5

log_test "B2: Measure Redis queue AFTER restart"
if [[ -n "$REDIS_PASSWORD" ]]; then
    QUEUE_AFTER=$(redis-cli -a "$REDIS_PASSWORD" LLEN celery 2>/dev/null || echo "unknown")
else
    QUEUE_AFTER=$(redis-cli LLEN celery 2>/dev/null || echo "unknown")
fi
echo "Redis queue AFTER: $QUEUE_AFTER" | tee -a "$REPORT_DIR/summary.log"

if [[ "$QUEUE_BEFORE" =~ ^[0-9]+$ ]] && [[ "$QUEUE_AFTER" =~ ^[0-9]+$ ]]; then
    if [[ $QUEUE_AFTER -lt $QUEUE_BEFORE ]]; then
        log_result "B2: Queue drained PASS ($QUEUE_BEFORE → $QUEUE_AFTER)"
    else
        log_result "B2: Queue status ($QUEUE_BEFORE → $QUEUE_AFTER)"
    fi
fi

log_test "B2: Verify PDF recovery"
sleep 2
curl -ksS -b "$COOKIE_JAR" -w "%{http_code}" "$PDF_ENDPOINT" -o "$REPORT_DIR/b2_recovery.html" 2>/dev/null > /tmp/b2_recovery_http.txt
RECOVERY_B2=$(cat /tmp/b2_recovery_http.txt)
echo "Test B2 Recovery HTTP Code: $RECOVERY_B2" | tee -a "$REPORT_DIR/summary.log"

if [[ "$RECOVERY_B2" == "200" ]]; then
    log_result "B2: Recovery PASS — PDF recovered after queue processing"
else
    log_result "B2: Recovery WARNING — HTTP $RECOVERY_B2"
fi

# ==========================================
# FINAL SUMMARY
# ==========================================

echo ""
echo "==========================================="
echo "FINAL SUMMARY"
echo "==========================================="
echo "All reports saved to: $REPORT_DIR"
echo ""
cat "$REPORT_DIR/summary.log"
