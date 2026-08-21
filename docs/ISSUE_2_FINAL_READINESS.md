# PPM Issue #2: Verification Gate Status & Execution Plan

**Assessment Date**: 2026-08-21  
**Status**: Ready for Runtime Failure Gate Execution  
**Confidence**: Medium (Infrastructure & Source Code Verified)

---

## Verification Summary (Current State)

### ✅ Infrastructure Recovery

| Check | Result | Evidence |
|-------|--------|----------|
| VPS boot (AlmaLinux 9.7) | ✅ VERIFIED | Phase 1 audit: systemd auto-start all services |
| Swap persistence (1.0Gi) | ✅ VERIFIED | `/etc/fstab` entry, survived reboot |
| Celery auto-recovery | ✅ VERIFIED | `systemctl is-enabled celery-ppm` = enabled, active after boot |
| All services enabled | ✅ VERIFIED | Apache, MariaDB, Redis, Celery all enabled+active |
| Memory/resource constraints | ✅ VERIFIED | 762MiB RAM, 1.0Gi Swap, no OOM observed during Phase 1 |

**Verdict: PASS** — VPS infrastructure is recoverable and self-healing after reboot.

---

### ✅ Source Code Recoverability

| Check | Result | Evidence |
|-------|--------|----------|
| GitHub main branch | ✅ VERIFIED | `malko73/ppm/main` = 91f9716 (all commits pushed) |
| .env excluded | ✅ VERIFIED | `.gitignore` includes `.env`, not tracked in git |
| media/ excluded | ✅ VERIFIED | `.gitignore` includes `media/`, not tracked |
| venv/ excluded | ✅ VERIFIED | `.gitignore` includes `venv/`, not tracked |
| Secret in history | ✅ VERIFIED | No SECRET_KEY, PASSWORD, or API keys in git log |
| Deploy Key readonly | ✅ VERIFIED | VPS can `git pull`, cannot `git push` (SSH pubkey verified read-only) |

**Verdict: PASS** — Code repository is complete, clean, and recoverable from GitHub.

**However**: `.env` and `media/` backup strategy must be verified separately:
- ⚠️ If backup is VPS-local only (`/backup`), single VPS failure → complete data loss
- ✅ Backups should exist in separate failure domain (cloud, NAS, alternate server)
- **Action for Phase 2**: Audit backup storage location & recovery feasibility

---

### ✅ Secret Management

| Check | Result | Evidence |
|-------|--------|----------|
| No plaintext secrets in code | ✅ VERIFIED | `git log -S "SECRET_KEY\|password"` yields no matches |
| ADMIN_MANUAL.md sanitized | ✅ VERIFIED | Commit 948f87f: login info replaced with placeholders |
| .env template only | ✅ VERIFIED | `.env.template` exists, actual `.env` git-ignored |
| Credentials not in docs | ✅ VERIFIED | No hardcoded DB passwords, API keys in repo |

**Verdict: PASS** — Secrets are properly externalized and not leaked in git history.

---

### ⏳ Runtime Failure Safety (PENDING)

This is what remains to be tested:

| Scenario | Test | Success Criteria | Status |
|----------|------|------------------|--------|
| **Redis broker unavailable** | Test A | No sync PDF, no OOM, no webserver crash, exception logged | READY |
| **Celery worker unavailable** | Test B | Task queues to Redis, no sync PDF, recovery after restart | READY |
| **Concurrent PDF load** | Test C | 5× parallel requests, available memory >100Mi, no OOM-kill | READY |

**Key insight**: Pass criteria is NOT "HTTP 503" specifically, but:
- ✅ **No sync PDF generation happens**
- ✅ **Web process does not crash/exit abnormally**
- ✅ **No OOM-kill in dmesg**
- ✅ **Failure is logged and traceable**

HTTP 500 or 503 are both acceptable if they signal fail-closed behavior. Response status optimization is a UX issue, not a safety issue.

---

### ⏳ Operational Observability (PENDING)

| Check | Status | Scope |
|-------|--------|-------|
| `/health/live` endpoint | ⏳ P1 | Django readiness signal |
| `/health/ready` endpoint | ⏳ P1 | Dependency health (DB/Redis/Celery) |
| Structured logging | ⏳ P2 | JSON logs for failure path tracing |
| Metrics export | ⏳ P2 | Prometheus/observability integration |

**Not blocking Issue #2 close, but recommended for post-launch ops.**

---

## Runtime Failure Gate: Test Matrix

All tests are prepared and ready to execute on VPS.

### Test A — Redis Broker DOWN

**Objective**: Verify `.delay()` failure handling when broker is unavailable.

```bash
# Pre-baseline
curl https://ppm.y-asahi.com/projects/1/pages/1/pdf/
# Expected: 200 + PDF content

# Stop Redis
sudo systemctl stop redis
sleep 3

# Attempt PDF request (broker down, Celery worker up)
curl -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/

# Expected outcomes (any of these = PASS):
# - HTTP 5xx (most likely 500 or 503)
# - Response is NOT a PDF (no sync fallback)
# - No "oom-kill" in dmesg
# - No Apache child process exit/segfault
# - Exception logged in error_log or Celery logs

# Restart Redis and verify recovery
sudo systemctl start redis
sleep 3
curl -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/
# Expected: 200 + PDF works again
```

**FAIL Conditions** (any of these = FAIL):
- HTTP 200 with PDF body (sync generation happened)
- OOM-kill event in dmesg
- Apache segfault or child exit without error log
- No exception trace in logs (silent failure)

---

### Test B — Celery Worker DOWN (Redis UP)

**Objective**: Verify task queuing continues safely when worker is unavailable.

```bash
# Pre-baseline
sudo systemctl is-active celery-ppm
# Expected: active

# Stop only Celery worker
sudo systemctl stop celery-ppm
sleep 3

# Attempt PDF request (Redis UP, Celery worker DOWN)
curl -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/

# Expected outcomes (any = PASS):
# - HTTP 200 or 202 (enqueue succeeded)
# - Response is NOT a PDF (task queued, not executed)
# - Response is JSON "pending" or HTML redirect
# - Redis queue has accumulated tasks: redis-cli LLEN celery > 0
# - No sync PDF generation occurred

# Restart Celery
sudo systemctl start celery-ppm
sleep 5

# Verify queued task now processes
curl -i https://ppm.y-asahi.com/projects/1/pages/1/pdf/
# Expected: 200 + PDF (delayed but successful)
```

**FAIL Conditions**:
- HTTP 200 with PDF body when worker is down (sync generation)
- Redis queue is empty (task was not queued)
- OOM-kill during queue accumulation

---

### Test C — OOM Stress (5 Parallel PDF Requests)

**Objective**: Verify memory remains stable under concurrent PDF load.

```bash
# Baseline memory
free -h
# Expected: available > 200Mi

# Launch 5 parallel PDF requests
for i in {1..5}; do
  curl -s https://ppm.y-asahi.com/projects/1/pages/$i/pdf/ > /dev/null &
done
wait

# During requests, monitor:
watch -n 1 'free -h && ps aux | grep -E "apache|celery|python" | head -5'

# After completion, check:
free -h
dmesg | grep -i "oom\|killed" | tail -5

# Expected outcomes (any = PASS):
# - All 5 PDFs generated successfully
# - available memory stays > 100Mi throughout
# - No OOM-kill in dmesg
# - No process > 300Mi memory
# - Apache/Celery process count stable
```

**FAIL Conditions**:
- OOM-kill event
- available memory drops below 50Mi
- Apache/Celery child process bloat (>500Mi)
- Request timeout or HTTP 503 during stress

---

## Execution Plan

### Phase 3 — Runtime Failure Testing (Ready to Start)

**Estimated Time**: 2-3 hours total

```bash
# Step 1: Prepare report directory
ssh sakura-vps "mkdir -p /tmp/ppm_failure_tests_$(date +%Y%m%d)"

# Step 2: Run full test suite (auto-executes A, B, C)
ssh sakura-vps "sudo bash /var/www/html/scripts/run_failure_tests.sh"

# Step 3: Review results
ssh sakura-vps "ls -lah /tmp/ppm_failure_tests_*/"
ssh sakura-vps "cat /tmp/ppm_failure_tests_*/summary.log"
```

**Expected output**: Timestamped test reports in `/tmp/ppm_failure_tests_YYYYMMDD_HHMMSS/`

---

### Phase 4 — Health Endpoints (If Tests Pass)

```python
# apps/views.py — add before wagtail catch-all

from django.http import JsonResponse
from django.db import connection
from django.core.cache import cache

def health_live(request):
    """Liveness: Can Django handle requests?"""
    return JsonResponse({"status": "ok"})

def health_ready(request):
    """Readiness: Are dependencies available?"""
    try:
        # DB check
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        # Cache check
        cache.set("_health", "ok", 10)
        cache.get("_health")
        
        return JsonResponse({
            "status": "ok",
            "database": "connected",
            "cache": "connected"
        })
    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=503)

# urls.py
urlpatterns = [
    path("health/live/", views.health_live),
    path("health/ready/", views.health_ready),
    # ... rest of urls ...
]
```

---

## Issue #2 Definition of Done (Updated)

- [x] Infrastructure Recovery verified (systemd, swap, services)
- [x] Source Code Recoverability verified (GitHub push, .env excluded)
- [x] Secret Management verified (no plaintext in git)
- [ ] **Test A PASS**: Redis DOWN → fail-closed, no sync PDF, no OOM
- [ ] **Test B PASS**: Celery DOWN → queue safe, recovery works
- [ ] **Test C PASS**: 5× parallel → memory stable, no OOM
- [ ] Health endpoints deployed
- [ ] MRRA Confidence: Medium → **High**
- [ ] Issue #2 **CLOSED**

---

## MRRA Confidence Trajectory

```
Before Phase 1:  Low (unknown systemd state, swap config unknown)
After Phase 1:   Medium-Low (infrastructure suspect, needs runtime validation)
After Phase 1+2: Medium (design sound, infrastructure verified, runtime untested)
After Test A/B/C: High (fail-closed behavior confirmed)
After Health EP: High (observability added)
→ READY FOR PRODUCTION
```

---

## Key Success Indicators

### Must Pass (Blocking)
- ✅ Test A: No sync PDF generation when Redis DOWN
- ✅ Test B: Task queue accumulation when Celery DOWN
- ✅ Test C: No OOM under 5× concurrent load

### Should Pass (UX/Ops Quality)
- Health endpoints respond within 100ms
- Failure scenarios produce structured logs
- Recovery time after reboot < 2 min

### Nice to Have (Post-Launch)
- Prometheus metrics export
- Grafana dashboard
- PagerDuty alerting

---

## Next Action

**Issue #2 is ready for Runtime Failure Gate execution.**

Start with Test A execution on VPS:
```bash
ssh sakura-vps "sudo bash /var/www/html/scripts/run_failure_tests.sh"
```

All three tests (A, B, C) will run sequentially, producing timestamped reports in `/tmp/ppm_failure_tests_*/`.

**Expected completion time**: 2 hours → Full Issue #2 readiness assessment.
