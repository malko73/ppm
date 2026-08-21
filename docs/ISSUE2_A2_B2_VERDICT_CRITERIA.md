# PPM Issue #2: A2/B2 FINAL VERDICT CRITERIA

**Status**: `READY — Authenticated Runtime Failure Gate Pending`

**Decision Point**: A2/B2 execution results only

---

## Test A2: Redis Broker DOWN (Authenticated PDF Endpoint)

### Success Path

```
認証済みPDF endpoint到達
  ↓ (Redis stopping)
Redis DOWN確認
  ↓
同期PDFなし（fail-closed）
  ↓
OOMなし（memory safe）
  ↓
service crashなし（resilient）
  ↓
Redis再起動
  ↓
PDF復旧確認（recovery works）
  = PASS
```

### Verdict

✅ **PASS** if all steps confirmed:
- PDF endpoint reached (authenticated)
- No sync PDF generation during Redis outage
- No OOM-kill in dmesg
- No service crash/exit
- Redis restart successful
- PDF generates after recovery

❌ **FAIL** if any of:
- Sync PDF was generated
- OOM-kill detected
- Service crashed

---

## Test B2: Celery Worker DOWN (Authenticated, Queue Verification)

### Success Path (CRITICAL)

```
認証済みPDF endpoint到達
  ↓
Celery DOWN確認
  ↓
同期PDFなし（async-only）
  ↓
Redis queue > 0（task accumulated）← KEY MEASUREMENT
  ↓
Celery再起動
  ↓
queue処理（tasks draining）← KEY MEASUREMENT
  ↓
最終PDF生成（recovery complete）
  = PASS
```

### Verdict

✅ **PASS** if all steps confirmed:
- PDF endpoint reached (authenticated)
- Celery worker stopped confirmed
- No sync PDF during outage
- Redis queue shows > 0 tasks accumulated (measured with Redis AUTH)
- Celery restart successful
- Queue drains (measurements show task count decreasing)
- PDF generates successfully after restart

⚠️ **PARTIAL EVIDENCE** (insufficient for full PASS):
- "NOAUTH Authentication required" on queue check
  - Does NOT prevent PASS if PDF was not generated
  - But reduces confidence in queue verification
  - Separate ops issue to address

❌ **FAIL** if any of:
- Sync PDF was generated during Celery outage
- Queue never accumulated (> 0 not observed)
- Queue remained after Celery restart (tasks not processed)
- Service crash/OOM

---

## Overall Verdict: Runtime Safety Gate

### Conditions for `High / VERIFIED`

Both A2 AND B2 must PASS:

| Test | Evidence Required | Gate Status |
|------|-------------------|-------------|
| **A2** | Fail-closed at Redis loss | Must PASS |
| **B2** | Queue accumulation → processing | Must PASS |
| **A2 Recovery** | Service resumes | Must PASS |
| **B2 Recovery** | Queue drains + PDF | Must PASS |
| **No OOM** | Both tests | Must PASS |
| **No Crashes** | Both tests | Must PASS |

**If BOTH A2 and B2 PASS** → MRRA Confidence: **High / VERIFIED**

**If EITHER fails** → Investigate root cause → Separate fix issue

---

## After A2/B2 PASS

Proceed immediately to:

1. **Health endpoints implementation** (1 hour)
   - `/health/live`
   - `/health/ready` (DB + Cache checks)

2. **Deploy & verify** (30 minutes)
   - Push to GitHub
   - Pull on VPS
   - Test both endpoints

3. **Issue #2 CLOSE** ✓

No new improvements or investigations unless A2/B2 surface blocking issues.

---

## Current Focus

**A2/B2 execution results only**

- No new features
- No scope changes
- Collect evidence, measure queue, verify fail-closed behavior
- Goal: Prove async-safe architecture with actual measurements

---

## Success Indicators

✅ **Strong** (confirms design intent):
- B2 queue > 0 during Celery DOWN
- B2 queue drains after Celery UP
- A2 no sync PDF during Redis DOWN

✅ **Acceptable** (doesn't block PASS):
- HTTP status varies (5xx, 503, 200 all acceptable if no PDF)
- Redis AUTH unavailable (separate ops fix)

❌ **Blocking Issues** (require investigation):
- Sync PDF generated
- Queue never accumulates
- OOM-kill
- Service crash

---

## Timeline

| Phase | Status | Action |
|-------|--------|--------|
| Phase 1-2 + Secrets | ✅ Done | - |
| Unauthenticated A/B/C | ✅ Done | - |
| **A2/B2 Execution** | ⏳ Pending | Run scripts, collect results |
| Health endpoints | ⏳ Next | Implement after A2/B2 PASS |
| Issue #2 CLOSE | ⏳ Final | After health endpoints verified |

---

## End State

✅ Infrastructure Recovery verified  
✅ Source Code Recoverability verified  
✅ Secret Management verified  
✅ Unauthenticated paths tested  
✅ **Authenticated paths tested (A2/B2)** ← Gate point  
✅ Health endpoints deployed  
✅ MRRA Confidence: High / VERIFIED  
✅ **Issue #2: CLOSED**
