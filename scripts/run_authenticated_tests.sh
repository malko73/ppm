#!/bin/bash
#
# PPM Issue #2: Authenticated Runtime Failure Gate Tests (A2 & B2) — FIXED v2
# With proper login result detection
#
# Usage: sudo bash run_authenticated_tests.sh
#

set -u

REPORT_DIR="/tmp/ppm_authenticated_tests_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$REPORT_DIR"

# Create temporary cookie jar
COOKIE_JAR="$REPORT_DIR/cookies.txt"
touch "$COOKIE_JAR"

# Read Redis password from .env (safe extraction)
REDIS_PASSWORD=$(sed -n 's/^REDIS_PASSWORD=//p' /var/www/html/.env 2>/dev/null | tr -d '"' | head -1)

echo "==========================================="
echo "PPM Issue #2: Authenticated Runtime Failure Tests (A2 & B2)"
echo "==========================================="
echo "Report directory: $REPORT_DIR"
echo "Test User: tadashi (info@marukoshiki.net)"
echo ""

# Cleanup function — ensures services are always restored to good state
cleanup() {
    local exit_code=$?
    echo ""
    echo ">>> CLEANUP: Restoring services to baseline state"
    echo ">>> $(date '+%Y-%m-%d %H:%M:%S')"
    
    # Ensure Redis is running
    if ! systemctl is-active --quiet redis; then
        echo "[CLEANUP] Starting Redis..."
        sudo systemctl start redis
        sleep 2
    fi
    
    # Ensure Celery is running
    if ! systemctl is-active --quiet celery-ppm; then
        echo "[CLEANUP] Starting Celery..."
        sudo systemctl start celery-ppm
        sleep 3
    fi
    
    # Ensure Apache is running
    if ! systemctl is-active --quiet httpd; then
        echo "[CLEANUP] Starting Apache..."
        sudo systemctl reload httpd
        sleep 2
    fi
    
    echo "[CLEANUP] Baseline services restored"
    
    # Verify all services are active
    systemctl is-active redis > /dev/null && echo "[OK] redis" || echo "[FAIL] redis"
    systemctl is-active celery-ppm > /dev/null && echo "[OK] celery-ppm" || echo "[FAIL] celery-ppm"
    systemctl is-active httpd > /dev/null && echo "[OK] httpd" || echo "[FAIL] httpd"
    
    exit $exit_code
}

# Register cleanup trap for EXIT signal
trap cleanup EXIT

# Helper functions
log_section() {
    echo ""
    echo ">>> $1"
    echo ">>> $(date '+%Y-%m-%d %H:%M:%S')"
}

log_test() {
    echo "[TEST] $1" | tee -a "$REPORT_DIR/summary.log"
}

log_result() {
    echo "[RESULT] $1" | tee -a "$REPORT_DIR/summary.log"
}

log_preflight() {
    echo "[PREFLIGHT] $1" | tee -a "$REPORT_DIR/summary.log"
}

# ==========================================
# PREFLIGHT CHECKS
# ==========================================

log_section "PREFLIGHT CHECKS"

# PRE-1: Check all services are UP
log_preflight "PRE-1: Verify all services UP"
systemctl is-active redis > /dev/null && log_preflight "  ✓ redis active" || { log_preflight "  ✗ redis NOT active"; exit 1; }
systemctl is-active celery-ppm > /dev/null && log_preflight "  ✓ celery-ppm active" || { log_preflight "  ✗ celery-ppm NOT active"; exit 1; }
systemctl is-active httpd > /dev/null && log_preflight "  ✓ httpd active" || { log_preflight "  ✗ httpd NOT active"; exit 1; }

# PRE-2: Get login page and extract CSRF token
log_preflight "PRE-2: Fetch login page and extract CSRF token"
LOGIN_URL="https://ppm.y-asahi.com/accounts/login/"

curl -ksS \
  -c "$COOKIE_JAR" \
  "$LOGIN_URL" \
  -o "$REPORT_DIR/login_page.html" 2>/dev/null

CSRF_TOKEN=$(grep -oP 'name="csrfmiddlewaretoken" value="\K[^"]+' "$REPORT_DIR/login_page.html" 2>/dev/null | head -1)

if [[ -z "$CSRF_TOKEN" ]]; then
    log_preflight "  ✗ CSRF token NOT found"
    exit 1
fi
log_preflight "  ✓ CSRF token extracted: ${CSRF_TOKEN:0:10}..."

# PRE-3: Login POST with CSRF token
log_preflight "PRE-3: Perform login POST"
curl -ksS \
  -b "$COOKIE_JAR" \
  -c "$COOKIE_JAR" \
  -e "$LOGIN_URL" \
  -X POST "$LOGIN_URL" \
  -d "username=tadashi&password=Asahiimc00&csrfmiddlewaretoken=$CSRF_TOKEN" \
  -o "$REPORT_DIR/login_response.html" 2>/dev/null

# Check login result: if response contains login form again, it failed
if grep -q 'name="csrfmiddlewaretoken"' "$REPORT_DIR/login_response.html"; then
    log_preflight "  ✗ Login form still present (authentication failed)"
    exit 1
fi

log_preflight "  ✓ Login form not present (likely successful)"

# PRE-4: Verify authenticated session (access protected page)
log_preflight "PRE-4: Verify authenticated session"
AUTH_CHECK=$(curl -ksS \
  -b "$COOKIE_JAR" \
  -w "%{http_code}" \
  -o "$REPORT_DIR/auth_check.html" \
  "https://ppm.y-asahi.com/projects/" 2>/dev/null)

if [[ "$AUTH_CHECK" == "200" ]]; then
    log_preflight "  ✓ Authenticated session confirmed (projects page returned 200)"
elif [[ "$AUTH_CHECK" == "302" ]]; then
    log_preflight "  ✗ Still being redirected to login (HTTP 302)"
    exit 1
else
    log_preflight "  ✗ Unexpected HTTP response: $AUTH_CHECK"
    exit 1
fi

# PRE-5: Verify Redis AUTH
log_preflight "PRE-5: Verify Redis authentication"
if [[ -z "$REDIS_PASSWORD" ]]; then
    log_preflight "  ⚠ REDIS_PASSWORD not found in .env (may be optional)"
    REDIS_AUTH_AVAILABLE=0
else
    REDIS_PING=$(redis-cli -a "$REDIS_PASSWORD" PING 2>/dev/null)
    if [[ "$REDIS_PING" == "PONG" ]]; then
        log_preflight "  ✓ Redis AUTH successful"
        REDIS_AUTH_AVAILABLE=1
    else
        log_preflight "  ✗ Redis AUTH failed"
        exit 1
    fi
fi

# PRE-6: Baseline PDF endpoint access
log_preflight "PRE-6: Test authenticated PDF endpoint access"
BASELINE_PDF=$(curl -ksS \
  -b "$COOKIE_JAR" \
  -w "%{http_code}" \
  -o "$REPORT_DIR/baseline_pdf.html" \
  "https://ppm.y-asahi.com/projects/1/pages/1/pdf/" 2>/dev/null)

if [[ "$BASELINE_PDF" == "200" ]]; then
    log_preflight "  ✓ PDF endpoint accessible (HTTP 200)"
    if grep -q "application/pdf\|PDF" "$REPORT_DIR/baseline_pdf.html"; then
        log_preflight "    ✓ PDF content detected"
    fi
elif [[ "$BASELINE_PDF" == "404" ]]; then
    log_preflight "  ⚠ PDF endpoint returned 404 (project may not exist, but auth passed)"
else
    log_preflight "  ✗ PDF endpoint returned HTTP $BASELINE_PDF"
    exit 1
fi

echo ""
echo ">>> All PREFLIGHT CHECKS PASSED"
echo ""

# ==========================================
# TEST A2: Redis Broker DOWN (Authenticated)
# ==========================================

echo "==========================================="
echo "TEST A2: Redis Broker DOWN (Authenticated)"
echo "==========================================="

log_section "TEST A2: Stopping Redis"
log_test "A2: Stop Redis"
sudo systemctl stop redis 2>&1 | tee "$REPORT_DIR/a2_redis_stop.log"
sleep 3

log_test "A2: Verify Redis is DOWN"
redis-cli ping 2>&1 | tee -a "$REPORT_DIR/a2_redis_down_verify.log" || echo "Redis: Connection refused (expected)" | tee -a "$REPORT_DIR/a2_redis_down_verify.log"

log_test "A2: Attempt PDF request with Redis DOWN (authenticated)"
curl -ksS \
  -b "$COOKIE_JAR" \
  -w "\nHTTP %{http_code}" \
  -o "$REPORT_DIR/a2_pdf_redis_down.html" \
  "https://ppm.y-asahi.com/projects/1/pages/1/pdf/" 2>/dev/null | tee "$REPORT_DIR/a2_pdf_request.log"

HTTP_A2=$(tail -1 "$REPORT_DIR/a2_pdf_request.log" | grep -oP 'HTTP \K\d+' || echo "000")
echo "Test A2 HTTP Code: $HTTP_A2" | tee -a "$REPORT_DIR/summary.log"

# Verify no sync PDF
if grep -q "application/pdf\|PDF" "$REPORT_DIR/a2_pdf_redis_down.html"; then
    log_result "A2: FAIL — PDF was generated (sync fallback detected!)"
else
    log_result "A2: PASS — No sync PDF generation, fail-closed confirmed"
fi

# Check logs for OOM
dmesg | grep -i "oom\|killed" | tail -5 2>&1 | tee "$REPORT_DIR/a2_dmesg.log" || echo "No OOM events" | tee "$REPORT_DIR/a2_dmesg.log"

log_test "A2: Restart Redis"
sudo systemctl start redis 2>&1 | tee "$REPORT_DIR/a2_redis_start.log"
sleep 3

log_test "A2: Verify PDF works again (Redis recovered)"
RECOVERY_A2=$(curl -ksS \
  -b "$COOKIE_JAR" \
  -w "%{http_code}" \
  -o "$REPORT_DIR/a2_recovery.html" \
  "https://ppm.y-asahi.com/projects/1/pages/1/pdf/" 2>/dev/null)

echo "Test A2 Recovery HTTP Code: $RECOVERY_A2" | tee -a "$REPORT_DIR/summary.log"

if [[ "$RECOVERY_A2" == "200" ]]; then
    log_result "A2: Recovery PASS — PDF generated after Redis recovery"
else
    log_result "A2: Recovery WARNING (HTTP $RECOVERY_A2, expected 200)"
fi

# ==========================================
# TEST B2: Celery Worker DOWN (Authenticated)
# ==========================================

echo ""
echo "==========================================="
echo "TEST B2: Celery Worker DOWN (Authenticated, Redis UP)"
echo "==========================================="

log_section "TEST B2: Stopping Celery"
log_test "B2: Stop Celery"
sudo systemctl stop celery-ppm 2>&1 | tee "$REPORT_DIR/b2_celery_stop.log"
sleep 3

log_test "B2: Verify Celery is DOWN"
sudo systemctl is-active celery-ppm 2>&1 | tee "$REPORT_DIR/b2_celery_down_verify.log"

log_test "B2: Attempt PDF request with Celery DOWN (Redis UP, authenticated)"
curl -ksS \
  -b "$COOKIE_JAR" \
  -w "\nHTTP %{http_code}" \
  -o "$REPORT_DIR/b2_pdf_celery_down.html" \
  "https://ppm.y-asahi.com/projects/1/pages/1/pdf/" 2>/dev/null | tee "$REPORT_DIR/b2_pdf_request.log"

HTTP_B2=$(tail -1 "$REPORT_DIR/b2_pdf_request.log" | grep -oP 'HTTP \K\d+' || echo "000")
echo "Test B2 HTTP Code: $HTTP_B2" | tee -a "$REPORT_DIR/summary.log"

# Measure queue BEFORE celery restart
log_test "B2: Measure Redis queue (Celery still DOWN)"
if [[ $REDIS_AUTH_AVAILABLE -eq 1 ]]; then
    QUEUE_BEFORE=$(redis-cli -a "$REDIS_PASSWORD" LLEN celery 2>/dev/null || echo "unknown")
else
    QUEUE_BEFORE=$(redis-cli LLEN celery 2>/dev/null || echo "unknown")
fi
echo "Redis queue BEFORE restart: $QUEUE_BEFORE" | tee -a "$REPORT_DIR/summary.log"

if [[ "$QUEUE_BEFORE" =~ ^[0-9]+$ ]] && [[ "$QUEUE_BEFORE" -gt 0 ]]; then
    log_result "B2: Queue accumulated PASS (queue > 0: $QUEUE_BEFORE tasks)"
else
    log_result "B2: Queue check showed: $QUEUE_BEFORE (may indicate Redis AUTH issue)"
fi

# Verify no sync PDF
if grep -q "application/pdf\|PDF" "$REPORT_DIR/b2_pdf_celery_down.html"; then
    log_result "B2: FAIL — PDF was generated (sync fallback detected!)"
else
    log_result "B2: PASS — No sync PDF generation during Celery outage"
fi

log_test "B2: Restart Celery"
sudo systemctl start celery-ppm 2>&1 | tee "$REPORT_DIR/b2_celery_start.log"
sleep 5

log_test "B2: Measure Redis queue (Celery now UP)"
sleep 3
if [[ $REDIS_AUTH_AVAILABLE -eq 1 ]]; then
    QUEUE_AFTER=$(redis-cli -a "$REDIS_PASSWORD" LLEN celery 2>/dev/null || echo "unknown")
else
    QUEUE_AFTER=$(redis-cli LLEN celery 2>/dev/null || echo "unknown")
fi
echo "Redis queue AFTER restart: $QUEUE_AFTER" | tee -a "$REPORT_DIR/summary.log"

if [[ "$QUEUE_AFTER" =~ ^[0-9]+$ ]] && [[ "$QUEUE_BEFORE" =~ ^[0-9]+$ ]]; then
    if [[ $QUEUE_AFTER -lt $QUEUE_BEFORE ]]; then
        log_result "B2: Queue drained PASS ($QUEUE_BEFORE → $QUEUE_AFTER)"
    else
        log_result "B2: Queue not draining (still $QUEUE_AFTER, was $QUEUE_BEFORE)"
    fi
fi

log_test "B2: Verify PDF generates after queue processing"
sleep 2
RECOVERY_B2=$(curl -ksS \
  -b "$COOKIE_JAR" \
  -w "%{http_code}" \
  -o "$REPORT_DIR/b2_recovery.html" \
  "https://ppm.y-asahi.com/projects/1/pages/1/pdf/" 2>/dev/null)

echo "Test B2 Recovery HTTP Code: $RECOVERY_B2" | tee -a "$REPORT_DIR/summary.log"

if [[ "$RECOVERY_B2" == "200" ]]; then
    if grep -q "application/pdf\|PDF" "$REPORT_DIR/b2_recovery.html"; then
        log_result "B2: Recovery PASS — Queue processed, PDF generated"
    else
        log_result "B2: Recovery WARNING — HTTP 200 but PDF content not found"
    fi
else
    log_result "B2: Recovery WARNING (HTTP $RECOVERY_B2, expected 200)"
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
echo "Results:"
cat "$REPORT_DIR/summary.log"

echo ""
echo ">>> CLEANUP: Restoring services"
