# PPM Issue #2: Recovery Hardening Progress

**Status**: Preparation phase complete — awaiting VPS boot  
**Last Updated**: 2026-08-21  
**Committed**: dc5f1a2, 3f94f03

---

## Current State: Pre-VPS Verification

### ✅ Preparation Complete

1. **Phase 1 Audit Script** (`scripts/phase1_runtime_audit.sh`)
   - Ready to run immediately after VPS boot
   - Captures: OS info, memory/swap, Python/Django/DB versions, Apache MPM, Celery systemd status
   - Output format: Human-readable text file for Issue comments

2. **Phase 2 Inspection Script** (`scripts/phase2_celery_inspection.py`)
   - Analyzes codebase for Celery task patterns
   - Detects danger configs (CELERY_TASK_ALWAYS_EAGER, etc.)
   - Verifies fallback mechanisms
   - Tested locally — runs successfully

3. **Code Review Findings (Phase 2 local analysis)**

   | Finding | Status | Details |
   |---------|--------|---------|
   | PDF task definition | ✅ CORRECT | `@shared_task` in `projects/tasks.py:25` — async-only |
   | Task queueing | ✅ CORRECT | `.delay()` call in `projects/views.py:422` — no sync fallback detected |
   | Celery config | ✅ VERIFIED | `config/celery.py:10-19` — no `CELERY_TASK_ALWAYS_EAGER` in code |
   | Error handling | ✅ PRESENT | `projects/tasks.py:40-42` — explicit exception handling with retry |
   | Broker URL | ✅ CONFIGURED | `redis://localhost:6379/0` (env-configurable) |
   | systemd service | ❓ PENDING | Need VPS boot to verify `celery-ppm` enabled/active |

4. **Documentation**
   - `docs/PPM_DOMAIN_MODEL.md` — entity relationships, validation rules
   - `docs/PPM_DOMAIN_ERD.drawio.md` — visual diagram
   - Both now tracked in Git

5. **Configuration Cleanup**
   - Removed duplicate `config/settings.py.vps` (identical to `config/settings.py`)

---

## Verification Checklist (Ready for VPS Boot)

### Phase 1 — Runtime Audit
- [ ] AlmaLinux / kernel version
- [ ] RAM / Swap capacity & enabled status
- [ ] Swap persistence in `/etc/fstab`
- [ ] Python 3.12 exact version
- [ ] Django 5.2 exact patch version
- [ ] MariaDB exact version
- [ ] Redis PING response
- [ ] Apache MPM worker settings
- [ ] `systemctl is-enabled celery-ppm` = enabled
- [ ] `systemctl is-active celery-ppm` = active

### Phase 2 — Code Analysis (Already done locally)
- [x] PDF generation task defined
- [x] `.delay()` usage pattern identified
- [x] No `CELERY_TASK_ALWAYS_EAGER` in settings
- [x] Exception handling present in task
- [x] Broker URL configured via env

### Critical P0 Checks (After VPS boot)
- [ ] Celery unavailable → PDF request returns 503 (NOT sync PDF generation)
- [ ] `build_pages_zip.delay()` fails gracefully when broker is down
- [ ] No OOM on task queue overflow
- [ ] Swap auto-activates after reboot
- [ ] All services (apache, mariadb, redis, celery) auto-start

---

## Next Steps (VPS Boot Sequence)

1. **Immediately after VPS boot** (1st terminal session):
   ```bash
   cd /home/tadashi/ppm
   bash scripts/phase1_runtime_audit.sh > /tmp/ppm_phase1_$(date +%Y%m%d_%H%M%S).txt
   ```

2. **Verify Celery broker connectivity**:
   ```bash
   redis-cli ping
   celery -A config worker -l info --timeout=60
   ```

3. **Run Phase 2 inspection**:
   ```bash
   python3 scripts/phase2_celery_inspection.py --project-root .
   ```

4. **Execute failure test** (if Celery is running):
   ```bash
   # Terminal 1: Celery worker
   celery -A config worker
   
   # Terminal 2: Test task queueing with broker available
   python manage.py shell
   >>> from projects.tasks import build_pages_zip
   >>> build_pages_zip.delay(1, 'test_key')  # Should queue
   
   # Terminal 3: Stop Celery, then retry
   # Kill Terminal 1
   # In manage.py shell:
   >>> build_pages_zip.delay(2, 'test_key2')  # Should FAIL (not sync fallback)
   # Expected: ConnectionError or similar, NOT sync PDF generation
   ```

5. **Report Phase 1 + Phase 2 results** → New Issue comment

---

## Risk Matrix (Current Assessment)

| Risk | Confidence | Evidence |
|------|-----------|----------|
| Celery unavailable → sync PDF fallback (OOM) | **Medium** | Code shows no sync fallback, but systemd state unknown |
| Swap disabled after reboot | **Medium** | `/etc/fstab` not yet verified |
| Apache WSGI memory leak | **Low** | Settings look correct, but worker config needs verification |
| PDF task retry storm | **Low** | `max_retries=3, default_retry_delay=5` configured appropriately |

**Target after VPS verification**: All risks → **Low** or **Resolved**

---

## Definition of Done for Issue #2

- [ ] Phase 1 audit executed successfully
- [ ] Phase 2 inspection completed
- [ ] Celery unavailable → 503 error (fail-closed, no sync fallback)
- [ ] Swap enabled & persistent ≥1GB
- [ ] All services auto-recover after reboot
- [ ] `/health/live` + `/health/ready` endpoints operational
- [ ] OOM scenario tested and passed
- [ ] Issue #2 marked CLOSED after final verification

---

## Appendix: Script Usage

### Running Phase 1 audit
```bash
./scripts/phase1_runtime_audit.sh
# Saves output to stdout → redirect to file for record
```

### Running Phase 2 inspection
```bash
python3 scripts/phase2_celery_inspection.py --project-root . --json
# Outputs findings in JSON for programmatic parsing
```

### Quick check: Is Celery task queueing safe?
```bash
grep -r "\.delay(" --include="*.py" .
grep -r "CELERY_TASK_ALWAYS_EAGER" --include="*.py" config/
redis-cli -p 6379 ping
```
