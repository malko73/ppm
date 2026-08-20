# PPM Issue #2: Verification Gate Status & Next Actions

**Assessment Date**: 2026-08-21  
**Current Status**: P0 Recovery PASS / Runtime Failure Gate PENDING

---

## Current Gate Status

| Gate | Result | Evidence | Status |
|------|--------|----------|--------|
| **Phase 1 Runtime Audit** | ✅ PASS | AlmaLinux 9.7, Swap 1.0Gi persistent, all services auto-start | Complete |
| **Phase 2 Static Code Inspection** | ✅ PASS | `@shared_task`, `.delay()` only, no `CELERY_TASK_ALWAYS_EAGER`, no sync fallback | Complete |
| **systemd Auto Recovery** | ✅ PASS | Celery/Apache/MariaDB/Redis all enabled+active after boot | Complete |
| **Swap Persistence** | ✅ PASS | `/etc/fstab` entry confirmed, 1.0Gi active | Complete |
| **PDF Async Architecture** | ✅ PASS | Async-only task design, no dangerous configs detected | Complete |
| **Redis Broker Failure** | ⏳ **PENDING** | Must test: Redis STOP → PDF request → verify no sync PDF, no OOM | Critical |
| **Celery Worker Failure** | ⏳ **PENDING** | Must test: Celery STOP (Redis UP) → PDF request → verify queue safety | Critical |
| **OOM Stress Test** | ⏳ **PENDING** | Must test: 5 parallel PDF requests → memory behavior → no OOM kill | Critical |
| **Health Endpoints** | ⏳ **PENDING** | `/health/live` + `/health/ready` implementation | P1 |
| **MRRA Confidence** | Medium → ? | Will reach **High** after failure path tests | Contingent |

**Issue #2 Overall**: **OPEN** (DoD incomplete)

---

## Critical Clarification: Broker Unavailability vs Worker Unavailability

### Static Analysis Limitation

The code inspection confirmed:
- `projects/tasks.py`: `@shared_task` with `.delay()` call
- No sync PDF generation in codebase
- `CELERY_TASK_ALWAYS_EAGER` not set

**However**, this does NOT guarantee fail-closed behavior in Redis broker failure scenario:

```python
# projects/views.py line 422
build_pages_zip.delay(project_id, cache_key)  # ← If Redis is DOWN, what happens?
```

When `Redis is DOWN`:
- `.delay()` internally tries to connect to broker
- Connection fails → raises exception
- **Question**: Does the exception propagate as 503?
- **Or**: Does something synchronously render PDF as fallback?
- **Or**: Does OOM occur during exception handling?

**This cannot be determined by static analysis alone.**

### Test Matrix Required

| Scenario | Redis | Celery Worker | Test Goal |
|----------|-------|---------------|-----------|
| **A: Broker Failure** | ❌ STOP | ✅ RUNNING | Verify `.delay()` exception → managed HTTP error (not sync PDF, not crash) |
| **B: Worker Queue Overflow** | ✅ RUNNING | ❌ STOP | Verify queue accumulation doesn't cause OOM or sync execution |
| **C: Normal Operation** | ✅ RUNNING | ✅ RUNNING | Baseline: PDF async generation works end-to-end |

---

## Runtime Failure Gate: Implementation Plan

### Test A — Redis Broker DOWN

```bash
# Pre-check
curl -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/
# Expected: 200 + PDF (baseline)

# Stop Redis
sudo systemctl stop redis
sleep 2

# Attempt PDF request
RESPONSE=$(curl -i -X GET https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1)
HTTP_CODE=$(echo "$RESPONSE" | head -1 | awk '{print $2}')

# Verify results
echo "HTTP Code: $HTTP_CODE"
echo "Expected: 500 or 503 (managed error, NOT 200)"

# Check system state
free -h && dmesg | grep -i "oom\|killed" | tail -3

# Restart Redis
sudo systemctl start redis
sleep 2

# Verify recovery
curl -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/
# Expected: 200 + PDF (normal operation restored)
```

**Pass Criteria:**
- HTTP response is 5xx (NOT 200)
- No PDF generated
- No OOM in dmesg
- No sync PDF rendering in logs
- Redis restarts and PDF works again

### Test B — Celery Worker DOWN (Redis UP)

```bash
# Pre-check: Verify task queues to Redis
sudo systemctl stop celery-ppm
sleep 2

# Attempt PDF request (Redis is live, can queue)
RESPONSE=$(curl -i -X GET https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1)
HTTP_CODE=$(echo "$RESPONSE" | head -1 | awk '{print $2}')

echo "HTTP Code: $HTTP_CODE"
# Expected: 200 (enqueue successful, user sees "pending" or redirect)

# Verify Redis queue has task
redis-cli -p 6379 LLEN celery
# Expected: > 0 (task in queue, NOT executed)

# Verify HTTP response is NOT PDF
echo "$RESPONSE" | grep -i "pdf\|content-type: application"
# Expected: (no output — not a PDF)

# Restart Celery, verify task executes
sudo systemctl start celery-ppm
sleep 5
curl -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/
# Expected: 200 + PDF (delayed but successful)
```

**Pass Criteria:**
- HTTP response on worker-down is 200 (enqueue succeeded)
- But response is NOT a PDF (pending notification, not content)
- Task stays in Redis queue
- When Celery restarts, task processes normally
- No sync PDF rendering
- No OOM

### Test C — OOM Stress (5 Parallel PDF Requests)

```bash
# Baseline memory
free -h

# Launch 5 parallel PDF requests
for i in {1..5}; do
  curl -X GET https://ppm.y-asahi.com/projects/1/pages/$i/pdf/ &
done
wait

# Monitor during requests
while true; do
  clear
  date
  free -h
  ps aux | grep -E "apache|wsgi|python" | head -5
  sleep 2
done

# Expected:
# - available memory stays > 100Mi
# - No OOM-kill in dmesg
# - Apache/Celery processes don't balloon to >200Mi each
```

**Pass Criteria:**
- All 5 PDFs generate successfully (or queue without sync fallback)
- No OOM-kill detected
- available memory > 100Mi throughout
- No process > 300Mi memory

---

## Implementation Sequence

### Phase 3 — Failure Path Testing

```bash
# Day 1: Test A (Redis DOWN)
ssh sakura-vps
cd /var/www/html
source .venv/bin/activate

# Execute Test A with logging
sudo systemctl stop redis
sleep 2

# Capture HTTP response + logs
curl -v https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | tee /tmp/test_a_redis_down.log
echo "---"
tail -20 /var/log/httpd/error_log | tee -a /tmp/test_a_redis_down.log
journalctl -u celery-ppm --since '5 min ago' | tee -a /tmp/test_a_redis_down.log

# Check system state
free -h >> /tmp/test_a_redis_down.log
dmesg | tail -5 >> /tmp/test_a_redis_down.log

sudo systemctl start redis
sleep 2

# Verify recovery
curl -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/ >> /tmp/test_a_redis_down.log

# Day 2: Test B (Celery DOWN)
sudo systemctl stop celery-ppm
sleep 2

curl -v https://ppm.y-asahi.com/projects/1/pages/1/pdf/ 2>&1 | tee /tmp/test_b_celery_down.log
redis-cli -p 6379 LLEN celery >> /tmp/test_b_celery_down.log
redis-cli -p 6379 LRANGE celery 0 -1 >> /tmp/test_b_celery_down.log

sudo systemctl start celery-ppm
sleep 5

# Day 3: Test C (OOM Stress)
# Run 5 parallel requests, monitor memory
```

### Phase 4 — Health Endpoints (P1)

After failure tests pass:

```python
# apps/views.py — add to urlpatterns BEFORE wagtail catch-all
from django.http import JsonResponse
from django.db import connection

def health_live(request):
    """Liveness check: Can Django handle requests?"""
    return JsonResponse({"status": "ok"})

def health_ready(request):
    """Readiness check: Are all dependencies available?"""
    try:
        # Check DB
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        # Check Redis
        from django.core.cache import cache
        cache.set("healthcheck", "ok", 10)
        cache.get("healthcheck")
        
        # Check Celery broker
        from config import celery_app
        # (Celery connection check — optional, already done if Redis OK)
        
        return JsonResponse({
            "status": "ok",
            "database": "connected",
            "cache": "connected",
            "celery": "connected"
        })
    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=503)
```

---

## Confidence & Issue Closure

### Current MRRA Confidence: **Medium**

| Component | Confidence | Reason |
|-----------|-----------|--------|
| Systemd recovery | **High** | Verified in Phase 1 |
| Code architecture | **High** | Static analysis complete |
| Redis failure path | **Medium → TBD** | Depends on Test A result |
| Worker failure path | **Medium → TBD** | Depends on Test B result |
| OOM safeguards | **Medium → TBD** | Depends on Test C result |
| Overall | **Medium** | Awaiting runtime validation |

### Issue #2 Close Criteria (Updated DoD)

- [x] Phase 1 audit executed successfully
- [x] Phase 2 inspection completed
- [ ] **Test A PASS**: Redis DOWN → 5xx HTTP (no sync PDF, no OOM)
- [ ] **Test B PASS**: Celery DOWN (Redis UP) → queue accumulates (no sync PDF)
- [ ] **Test C PASS**: 5 parallel PDF requests → no OOM, memory stable
- [ ] Health endpoints deployed (`/health/live`, `/health/ready`)
- [ ] MRRA Confidence: Medium → **High**
- [ ] Issue #2 CLOSED

---

## Appendix: Known Issues & Future Work

### MariaDB 10.5.29 — Future Upgrade

MariaDB 10.5.29 is currently running. While functional:
- Support ends May 2025 (EOL approaching)
- No immediate upgrade required for Issue #2
- **Action**: Create separate Issue for 10.5 → 10.11 LTS migration (out of scope for #2)

### Redis AUTH Configuration

Redis requires authentication (`NOAUTH` currently). Verify `.env`:
```bash
# Should contain (example):
CELERY_BROKER_URL=redis://:PASSWORD@localhost:6379/0
CACHE_URL=redis://:PASSWORD@localhost:6379/2
```

If missing, add before Test A.

### Python 3.9 System vs 3.11 venv

- System Python: 3.9.25 (old, but not used)
- Active venv: 3.11.13 with Django 5.2.11 ✅

No action needed.

---

## Summary

**Phase 1 & Phase 2 are COMPLETE and PASSING.**

**Remaining work is purely runtime validation:**
1. Redis DOWN test (1 hour)
2. Celery DOWN test (1 hour)
3. OOM stress test (30 min)
4. Health endpoints (1 hour development)

**Total time to close Issue #2: ~4 hours of focused work.**

After these tests pass, MRRA confidence will be **High** and Issue #2 can be closed with full confidence in PPM recovery hardening.
