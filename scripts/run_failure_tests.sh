#!/bin/bash
#
# PPM Issue #2: Runtime Failure Gate Test Suite
# Execute Test A, B, C in sequence
#
# Usage: sudo bash run_failure_tests.sh
#

set -u

REPORT_DIR="/tmp/ppm_failure_tests_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$REPORT_DIR"

echo "=========================================="
echo "PPM Issue #2: Runtime Failure Gate Tests"
echo "=========================================="
echo "Report directory: $REPORT_DIR"
echo ""

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

log_test "C: Normal PDF Generation (baseline)"
curl -s -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | head -15 > "$REPORT_DIR/test_c_baseline.txt"
HTTP_CODE=$(grep "HTTP" "$REPORT_DIR/test_c_baseline.txt" | head -1 | awk '{print $2}')
echo "Baseline HTTP code: $HTTP_CODE (expected: 200 or 302)" | tee -a "$REPORT_DIR/summary.log"

if [[ "$HTTP_CODE" == "200" ]]; then
    log_result "C: Baseline PASS (PDF generation works)"
else
    log_result "C: Baseline WARNING (HTTP $HTTP_CODE, might be auth redirect)"
fi

echo ""
echo "=========================================="
echo "TEST A: Redis Broker DOWN"
echo "=========================================="

log_section "TEST A: Stopping Redis"
log_test "A: Stop Redis"
sudo systemctl stop redis 2>&1 | tee "$REPORT_DIR/test_a_redis_stop.log"
sleep 3

log_test "A: Verify Redis is DOWN"
redis-cli ping 2>&1 | tee -a "$REPORT_DIR/test_a_redis_down_verify.log" || echo "Redis: Connection refused (expected)" | tee -a "$REPORT_DIR/test_a_redis_down_verify.log"

log_test "A: Attempt PDF request with Redis DOWN"
curl -v -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | tee "$REPORT_DIR/test_a_pdf_request.log"
HTTP_CODE_A=$(grep "^HTTP" "$REPORT_DIR/test_a_pdf_request.log" | head -1 | awk '{print $2}')
echo "Test A HTTP Code: $HTTP_CODE_A" | tee -a "$REPORT_DIR/summary.log"

# Verify no PDF in response
if grep -q "application/pdf" "$REPORT_DIR/test_a_pdf_request.log"; then
    log_result "A: FAIL — PDF was generated (sync fallback detected!)"
else
    if [[ "$HTTP_CODE_A" == "5"* ]] || [[ "$HTTP_CODE_A" == "503" ]]; then
        log_result "A: PASS — 5xx error returned, no PDF sync fallback"
    else
        log_result "A: WARNING — HTTP $HTTP_CODE_A (expected 5xx)"
    fi
fi

# Check system logs
log_test "A: Check system logs for OOM or errors"
tail -10 /var/log/httpd/error_log 2>&1 | tee "$REPORT_DIR/test_a_httpd_errors.log"
journalctl -u celery-ppm --since '5 min ago' 2>&1 | tail -20 | tee "$REPORT_DIR/test_a_celery_logs.log"
dmesg | grep -i "oom\|killed" | tail -5 2>&1 | tee "$REPORT_DIR/test_a_dmesg.log" || echo "No OOM events" | tee "$REPORT_DIR/test_a_dmesg.log"

log_test "A: Restart Redis"
sudo systemctl start redis 2>&1 | tee "$REPORT_DIR/test_a_redis_start.log"
sleep 3

log_test "A: Verify PDF works again (Redis recovered)"
curl -s -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | head -15 > "$REPORT_DIR/test_a_recovery.txt"
HTTP_CODE_A_RECOVERY=$(grep "HTTP" "$REPORT_DIR/test_a_recovery.txt" | head -1 | awk '{print $2}')
echo "Test A Recovery HTTP Code: $HTTP_CODE_A_RECOVERY (expected: 200)" | tee -a "$REPORT_DIR/summary.log"

if [[ "$HTTP_CODE_A_RECOVERY" == "200" ]]; then
    log_result "A: Recovery PASS"
else
    log_result "A: Recovery WARNING (HTTP $HTTP_CODE_A_RECOVERY)"
fi

echo ""
echo "=========================================="
echo "TEST B: Celery Worker DOWN (Redis UP)"
echo "=========================================="

log_section "TEST B: Stopping Celery"
log_test "B: Stop Celery"
sudo systemctl stop celery-ppm 2>&1 | tee "$REPORT_DIR/test_b_celery_stop.log"
sleep 3

log_test "B: Verify Celery is DOWN"
sudo systemctl is-active celery-ppm 2>&1 | tee "$REPORT_DIR/test_b_celery_down_verify.log"

log_test "B: Attempt PDF request with Celery DOWN (Redis UP)"
curl -v -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | tee "$REPORT_DIR/test_b_pdf_request.log"
HTTP_CODE_B=$(grep "^HTTP" "$REPORT_DIR/test_b_pdf_request.log" | head -1 | awk '{print $2}')
echo "Test B HTTP Code: $HTTP_CODE_B (expected: 200 enqueue, but NOT PDF)" | tee -a "$REPORT_DIR/summary.log"

# Check Redis queue
log_test "B: Check Redis queue for accumulated tasks"
QUEUE_LEN=$(redis-cli -p 6379 LLEN celery 2>&1 || echo "0")
echo "Redis queue length: $QUEUE_LEN" | tee -a "$REPORT_DIR/summary.log"

if [[ "$QUEUE_LEN" -gt 0 ]]; then
    log_result "B: Queue accumulated (expected when worker is down)"
else
    log_result "B: WARNING — Queue is empty (might indicate no enqueue occurred)"
fi

# Verify response is not a PDF
if grep -q "application/pdf" "$REPORT_DIR/test_b_pdf_request.log"; then
    log_result "B: WARNING — PDF returned (worker was supposed to be down?)"
else
    log_result "B: PASS — No PDF in response when worker is down (task queued, not executed)"
fi

log_test "B: Restart Celery"
sudo systemctl start celery-ppm 2>&1 | tee "$REPORT_DIR/test_b_celery_start.log"
sleep 5

log_test "B: Verify queued task processes after Celery restart"
curl -s -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | head -15 > "$REPORT_DIR/test_b_recovery.txt"
HTTP_CODE_B_RECOVERY=$(grep "HTTP" "$REPORT_DIR/test_b_recovery.txt" | head -1 | awk '{print $2}')
echo "Test B Recovery HTTP Code: $HTTP_CODE_B_RECOVERY (expected: 200)" | tee -a "$REPORT_DIR/summary.log"

if [[ "$HTTP_CODE_B_RECOVERY" == "200" ]]; then
    log_result "B: Recovery PASS"
else
    log_result "B: Recovery WARNING (HTTP $HTTP_CODE_B_RECOVERY)"
fi

echo ""
echo "=========================================="
echo "TEST C: OOM Stress (5 Parallel PDF Requests)"
echo "=========================================="

log_section "TEST C: Baseline Memory"
free -h | tee "$REPORT_DIR/test_c_memory_before.log"

log_test "C: Launch 5 parallel PDF requests"
for i in {1..5}; do
    curl -s https://ppm.y-asahi.com/projects/1/pages/$i/pdf/ > /dev/null &
    sleep 0.5
done
echo "5 requests launched, waiting for completion..." | tee -a "$REPORT_DIR/summary.log"
wait

sleep 2

log_test "C: Memory after parallel requests"
free -h | tee "$REPORT_DIR/test_c_memory_after.log"

log_test "C: Check for OOM events"
dmesg | grep -i "oom\|killed" | tail -5 2>&1 | tee "$REPORT_DIR/test_c_oom_check.log" || echo "No OOM events (PASS)" | tee "$REPORT_DIR/test_c_oom_check.log"

# Parse memory
AVAIL_BEFORE=$(awk '/^Mem:/ {print $7}' "$REPORT_DIR/test_c_memory_before.log" | sed 's/Mi//')
AVAIL_AFTER=$(awk '/^Mem:/ {print $7}' "$REPORT_DIR/test_c_memory_after.log" | sed 's/Mi//')

if [[ -z "$AVAIL_BEFORE" ]] || [[ -z "$AVAIL_AFTER" ]]; then
    AVAIL_BEFORE="unknown"
    AVAIL_AFTER="unknown"
fi

echo "Available memory: before=$AVAIL_BEFORE available=$AVAIL_AFTER" | tee -a "$REPORT_DIR/summary.log"

if grep -q "oom\|killed" "$REPORT_DIR/test_c_oom_check.log"; then
    log_result "C: FAIL — OOM detected"
else
    log_result "C: PASS — No OOM, stress test completed"
fi

echo ""
echo "=========================================="
echo "FINAL SUMMARY"
echo "=========================================="
echo "All reports saved to: $REPORT_DIR"
echo ""
echo "Results:"
cat "$REPORT_DIR/summary.log"

echo ""
echo "Next steps:"
echo "1. Review test results in $REPORT_DIR/"
echo "2. Verify Test A, B, C all PASS"
echo "3. If all PASS, implement /health/live and /health/ready endpoints"
echo "4. Close Issue #2 after health endpoints verification"
