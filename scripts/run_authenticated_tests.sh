#!/bin/bash
#
# PPM Issue #2: Authenticated Runtime Failure Gate Tests (A2 & B2)
# Tests Redis and Celery failures with actual PDF endpoint access
#
# Prerequisites:
# - User: tadashi / email: info@marukoshiki.net / password from .env
# - Project #1 exists and user has access
# - Redis authentication configured (if needed)
#
# Usage: sudo bash run_authenticated_tests.sh
#

set -u

REPORT_DIR="/tmp/ppm_authenticated_tests_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$REPORT_DIR"

# Read Redis password from .env (for queue verification)
REDIS_PASSWORD=$(grep "^REDIS_PASSWORD=" /var/www/html/.env 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "")

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

# Baseline: Check all services are up
log_section "BASELINE: All Services UP"
systemctl status redis --no-pager | grep "Active:" | tee "$REPORT_DIR/baseline_redis.log"
systemctl status celery-ppm --no-pager | grep "Active:" | tee "$REPORT_DIR/baseline_celery.log"
systemctl status httpd --no-pager | grep "Active:" | tee "$REPORT_DIR/baseline_httpd.log"

echo ""
echo "==========================================="
echo "TEST A2: Redis Broker DOWN (Authenticated)"
echo "==========================================="

log_section "TEST A2: Baseline authenticated PDF request"
log_test "A2: Normal PDF GET (authenticated, baseline)"

# First, get the login page to extract CSRF token and set session cookie
curl -s -i -k -c "$REPORT_DIR/cookies.txt" https://ppm.y-asahi.com/accounts/login/ 2>&1 | head -20 > "$REPORT_DIR/a2_login_page.log"

# Extract CSRF token
CSRF_TOKEN=$(grep -oP '(?<=csrftoken=)[^;]*' "$REPORT_DIR/cookies.txt" 2>/dev/null || echo "")
echo "CSRF Token (from cookies): $CSRF_TOKEN" | tee -a "$REPORT_DIR/summary.log"

# Login with credentials
log_test "A2: Login as tadashi"
LOGIN_RESPONSE=$(curl -s -i -k -b "$REPORT_DIR/cookies.txt" -c "$REPORT_DIR/cookies.txt" \
  -X POST \
  -d "username=info@marukoshiki.net&password=Asahiimc00&csrfmiddlewaretoken=$CSRF_TOKEN" \
  https://ppm.y-asahi.com/accounts/login/ 2>&1)

LOGIN_STATUS=$(echo "$LOGIN_RESPONSE" | grep "^HTTP" | head -1 | awk '{print $2}')
echo "Login response: HTTP $LOGIN_STATUS" | tee -a "$REPORT_DIR/summary.log"

if [[ "$LOGIN_STATUS" == "302" ]]; then
    log_result "A2: Login successful (302 redirect)"
else
    log_result "A2: WARNING — Login returned HTTP $LOGIN_STATUS (expected 302)"
fi

# Now attempt PDF with authenticated session (Redis UP)
log_test "A2: PDF request with authenticated session (baseline, Redis UP)"
curl -s -i -k -b "$REPORT_DIR/cookies.txt" https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | tee "$REPORT_DIR/a2_baseline_pdf.log"
HTTP_A2_BASELINE=$(grep "^HTTP" "$REPORT_DIR/a2_baseline_pdf.log" | head -1 | awk '{print $2}')
echo "Baseline PDF HTTP code: $HTTP_A2_BASELINE (expected: 200)" | tee -a "$REPORT_DIR/summary.log"

if grep -q "application/pdf" "$REPORT_DIR/a2_baseline_pdf.log"; then
    log_result "A2: Baseline PASS — PDF generated successfully"
else
    log_result "A2: Baseline WARNING — PDF not in response (HTTP $HTTP_A2_BASELINE)"
fi

log_section "TEST A2: Stopping Redis"
log_test "A2: Stop Redis"
sudo systemctl stop redis 2>&1 | tee "$REPORT_DIR/a2_redis_stop.log"
sleep 3

log_test "A2: Verify Redis is DOWN"
redis-cli ping 2>&1 | tee -a "$REPORT_DIR/a2_redis_down_verify.log" || echo "Redis: Connection refused (expected)" | tee -a "$REPORT_DIR/a2_redis_down_verify.log"

log_test "A2: Attempt PDF request with Redis DOWN (authenticated)"
curl -s -i -k -b "$REPORT_DIR/cookies.txt" https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | tee "$REPORT_DIR/a2_pdf_redis_down.log"
HTTP_A2=$(grep "^HTTP" "$REPORT_DIR/a2_pdf_redis_down.log" | head -1 | awk '{print $2}')
echo "Test A2 HTTP Code (Redis DOWN): $HTTP_A2" | tee -a "$REPORT_DIR/summary.log"

# Verify no PDF in response
if grep -q "application/pdf" "$REPORT_DIR/a2_pdf_redis_down.log"; then
    log_result "A2: FAIL — PDF was generated (sync fallback detected!)"
else
    if [[ "$HTTP_A2" == "5"* ]]; then
        log_result "A2: PASS — 5xx error returned (fail-closed), no PDF sync fallback"
    else
        log_result "A2: WARNING — HTTP $HTTP_A2 (expected 5xx for fail-closed)"
    fi
fi

# Check logs
log_test "A2: Check system logs for OOM or errors"
tail -10 /var/log/httpd/error_log 2>&1 | tee "$REPORT_DIR/a2_httpd_errors.log"
dmesg | grep -i "oom\|killed" | tail -5 2>&1 | tee "$REPORT_DIR/a2_dmesg.log" || echo "No OOM events" | tee "$REPORT_DIR/a2_dmesg.log"

log_test "A2: Restart Redis"
sudo systemctl start redis 2>&1 | tee "$REPORT_DIR/a2_redis_start.log"
sleep 3

log_test "A2: Verify PDF works again (Redis recovered, authenticated)"
curl -s -i -k -b "$REPORT_DIR/cookies.txt" https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | head -15 > "$REPORT_DIR/a2_recovery.txt"
HTTP_A2_RECOVERY=$(grep "^HTTP" "$REPORT_DIR/a2_recovery.txt" | head -1 | awk '{print $2}')
echo "Test A2 Recovery HTTP Code: $HTTP_A2_RECOVERY (expected: 200)" | tee -a "$REPORT_DIR/summary.log"

if [[ "$HTTP_A2_RECOVERY" == "200" ]]; then
    log_result "A2: Recovery PASS"
else
    log_result "A2: Recovery WARNING (HTTP $HTTP_A2_RECOVERY)"
fi

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
curl -s -i -k -b "$REPORT_DIR/cookies.txt" https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | tee "$REPORT_DIR/b2_pdf_celery_down.log"
HTTP_B2=$(grep "^HTTP" "$REPORT_DIR/b2_pdf_celery_down.log" | head -1 | awk '{print $2}')
echo "Test B2 HTTP Code (Celery DOWN): $HTTP_B2 (expected: 200 enqueue, but NOT PDF)" | tee -a "$REPORT_DIR/summary.log"

# Check Redis queue
log_test "B2: Check Redis queue for accumulated tasks"
if [[ -n "$REDIS_PASSWORD" ]]; then
    QUEUE_LEN=$(redis-cli -a "$REDIS_PASSWORD" -p 6379 LLEN celery 2>&1 || echo "0")
else
    QUEUE_LEN=$(redis-cli -p 6379 LLEN celery 2>&1 || echo "0")
fi
echo "Redis queue length: $QUEUE_LEN" | tee -a "$REPORT_DIR/summary.log"

if [[ "$QUEUE_LEN" =~ ^[0-9]+$ ]] && [[ "$QUEUE_LEN" -gt 0 ]]; then
    log_result "B2: Queue accumulated (expected when worker is down)"
else
    log_result "B2: WARNING — Queue shows $QUEUE_LEN (might indicate auth issue or no enqueue)"
fi

# Verify response is not a PDF
if grep -q "application/pdf" "$REPORT_DIR/b2_pdf_celery_down.log"; then
    log_result "B2: FAIL — PDF returned (sync generation happened!)"
else
    log_result "B2: PASS — No PDF in response when worker is down (task queued, not executed)"
fi

log_test "B2: Restart Celery"
sudo systemctl start celery-ppm 2>&1 | tee "$REPORT_DIR/b2_celery_start.log"
sleep 5

log_test "B2: Verify queued task processes after Celery restart (authenticated)"
curl -s -i -k -b "$REPORT_DIR/cookies.txt" https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | head -15 > "$REPORT_DIR/b2_recovery.txt"
HTTP_B2_RECOVERY=$(grep "^HTTP" "$REPORT_DIR/b2_recovery.txt" | head -1 | awk '{print $2}')
echo "Test B2 Recovery HTTP Code: $HTTP_B2_RECOVERY (expected: 200)" | tee -a "$REPORT_DIR/summary.log"

if [[ "$HTTP_B2_RECOVERY" == "200" ]]; then
    log_result "B2: Recovery PASS"
else
    log_result "B2: Recovery WARNING (HTTP $HTTP_B2_RECOVERY)"
fi

echo ""
echo "==========================================="
echo "FINAL SUMMARY"
echo "==========================================="
echo "All reports saved to: $REPORT_DIR"
echo ""
echo "Results:"
cat "$REPORT_DIR/summary.log"

echo ""
echo "Next steps:"
echo "1. Review test results in $REPORT_DIR/"
echo "2. Verify Test A2, B2 both PASS"
echo "3. If all PASS, implement /health/live and /health/ready endpoints"
echo "4. Close Issue #2 after health endpoints verification"
