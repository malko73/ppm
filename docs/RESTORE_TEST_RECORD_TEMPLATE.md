# PPM Disaster Recovery Test Record

## Test Information

**Test Date**: YYYY-MM-DD  
**Test Time**: HH:MM - HH:MM UTC  
**Total Elapsed Time**: X hours X minutes  
**Tester**: [Name]  
**Environment**: Staging VPS (Ubuntu 22.04)  

---

## RTO Measurement (Critical)

Target: **4 hours or less**

| Phase | Start | End | Duration | Status |
|-------|-------|-----|----------|--------|
| VPS Provisioning | HH:MM | HH:MM | XXm | ✅/❌ |
| Code Restoration | HH:MM | HH:MM | XXm | ✅/❌ |
| Backup Download | HH:MM | HH:MM | XXm | ✅/❌ |
| Checksum Verify | HH:MM | HH:MM | XXm | ✅/❌ |
| Key Retrieval | HH:MM | HH:MM | XXm | ✅/❌ |
| Decryption | HH:MM | HH:MM | XXm | ✅/❌ |
| Media Extract | HH:MM | HH:MM | XXm | ✅/❌ |
| DB Restoration | HH:MM | HH:MM | XXm | ✅/❌ |
| Django Setup | HH:MM | HH:MM | XXm | ✅/❌ |
| Service Startup | HH:MM | HH:MM | XXm | ✅/❌ |
| Web Verification | HH:MM | HH:MM | XXm | ✅/❌ |
| PDF Test | HH:MM | HH:MM | XXm | ✅/❌ |
| **TOTAL** | **HH:MM** | **HH:MM** | **X:XXh** | **✅/❌** |

**RTO Target Achieved?** ✅ Yes / ❌ No  
**Comments**: [If over 4h, note delays and causes]

---

## Backup Integrity

### Checksum Verification

| Artifact | File | Checksum | Status | Notes |
|----------|------|----------|--------|-------|
| PostgreSQL | ppm_db_20260822.sql | SHA-256 | ✅/❌ | [OK / FAILED] |
| Media | media_20260822.tar.gz | SHA-256 | ✅/❌ | [OK / FAILED] |
| .env | .env.gpg | SHA-256 | ✅/❌ | [OK / FAILED] |

**All checksums verified?** ✅ Yes / ❌ No  
**Corrupted artifacts?** ✅ None / ❌ [List items]  
**Action if failed**: Did not proceed to recovery

---

## Key Management

### Encryption Key Retrieval

| Item | Source | Method | Status | Notes |
|------|--------|--------|--------|-------|
| GPG Key | [KMS/Vault/YubiKey] | [Method] | ✅/❌ | [Retrieved/Failed] |

**Key successfully retrieved from separate system?** ✅ Yes / ❌ No  
**Key location**: [KMS/Vault/YubiKey ID]  
**Time to retrieve**: X minutes  
**Issues encountered**: [None / List issues]

### Decryption Verification

```
GPG Decryption Command:
$ gpg --decrypt .env.gpg > .env.restored

Result: ✅ Success / ❌ Failed
Decrypted .env contains:
  ✅ SECRET_KEY
  ✅ DATABASE_URL
  ✅ All required variables
```

---

## Database Restoration

### PostgreSQL Dump Restore

```
Restore Command:
$ psql -U postgres -d ppm < ppm_db_20260822.sql

Result: ✅ Success / ❌ Failed
```

### Data Integrity Check

| Check | Result | Count | Status |
|-------|--------|-------|--------|
| Projects | ✅/❌ | [N] | OK/Missing |
| Pages | ✅/❌ | [N] | OK/Missing |
| Users | ✅/❌ | [N] | OK/Missing |
| Templates | ✅/❌ | [N] | OK/Missing |

**All tables restored?** ✅ Yes / ❌ No  
**Data consistency check passed?** ✅ Yes / ❌ No  
**Sample queries executed**: 
```sql
SELECT COUNT(*) FROM projects_project;  -- Result: [N]
SELECT COUNT(*) FROM projects_page;     -- Result: [N]
SELECT COUNT(*) FROM auth_user;         -- Result: [N]
```

---

## Application Verification

### Django Setup

```
Commands executed:
$ python manage.py migrate --noinput
  Result: ✅ Success / ❌ Failed
  
$ python manage.py collectstatic --noinput
  Result: ✅ Success / ❌ Failed
  
$ python manage.py check
  Result: ✅ Success / ❌ Failed
```

**All Django checks passed?** ✅ Yes / ❌ No

### Web Server Status

```
Service: Apache2
Status: ✅ Running / ❌ Stopped / ❌ Failed
  
HTTP Health Check:
$ curl http://localhost/health/
  Result: ✅ 200 OK / ❌ [Error code]

Admin Panel:
$ curl http://localhost/admin/
  Result: ✅ Accessible / ❌ Not accessible
```

**Web server operational?** ✅ Yes / ❌ No

---

## PDF Output Generation

### PDF Test Execution

```
Test Page: [Project ID] / [Page ID]
Command:
$ curl -o /tmp/test.pdf http://localhost/projects/1/pages/1/pdf/

Result: ✅ Success / ❌ Failed
PDF File Size: [KB]
PDF Format Validation: ✅ Valid / ❌ Invalid
```

**PDF successfully generated?** ✅ Yes / ❌ No  
**PDF displays correctly?** ✅ Yes / ❌ No / ⚠️ Not tested  
**File size reasonable?** ✅ Yes / ❌ No

### Coordinate System Verification (Issue #5)

```
Test: mm → px → pt conversion round-trip

Test Data:
  Original X (mm): 105.0
  Converted X (px): [px_value]
  Round-trip X (mm): [mm_value]
  
Accuracy Check:
  Difference: [diff] mm
  Tolerance: ≤ 0.01mm
  Result: ✅ Pass / ❌ Fail

Template Positions Verified:
  ✅ All positions match pre-recovery
  ❌ Coordinate drift detected
  
Notes: [Any coordinate system issues]
```

**Coordinate system intact?** ✅ Yes / ❌ No  
**PDF layout matches original?** ✅ Yes / ❌ No / ⚠️ Not tested

---

## Media Files

### Media Restoration

```
Command:
$ tar xzf media_20260822.tar.gz

Result: ✅ Success / ❌ Failed
Files Extracted: [N]
Total Size: [GB]
```

**Media directory restored?** ✅ Yes / ❌ No  
**File permissions correct?** ✅ Yes / ❌ No  
**Sample files accessible?** ✅ Yes / ❌ No

---

## Issues & Findings

### Critical Issues

| Issue | Severity | Description | Resolution |
|-------|----------|-------------|-----------|
| [#] | Critical | [Description] | [Resolved/Pending] |

**Critical issues resolved before declaring recovery successful?** ✅ Yes / ❌ No

### Non-Critical Issues

| Issue | Severity | Description | Impact |
|-------|----------|-------------|--------|
| [#] | Major/Minor | [Description] | [Minor/Moderate delay] |

---

## Recommendations

### Process Improvements

- [ ] [Improvement 1]
- [ ] [Improvement 2]
- [ ] [Improvement 3]

### Documentation Updates

- [ ] [Doc section to update]
- [ ] [Add missing step]
- [ ] [Clarify procedure]

### Automation Opportunities

- [ ] [Task to automate]
- [ ] [Script to enhance]

### Testing Frequency

**Next test scheduled**: [Date]  
**Test frequency**: Monthly (1st Saturday)  
**Participants**: [Names]

---

## RPO/RTO Summary

**RPO (Recovery Point Objective)**
- Target: 24 hours
- Backup set used: 20260822 (Date-based)
- Data loss window: None (latest backup)
- **Status**: ✅ Achieved / ❌ Not achieved

**RTO (Recovery Time Objective)**
- Target: 4 hours
- Actual: X:XX hours
- Variance: [+/-] X minutes
- **Status**: ✅ Achieved / ❌ Not achieved

---

## Sign-Off

**Test Status**: ✅ PASS / ⚠️ PASS WITH NOTES / ❌ FAIL

**Tester Signature**: ________________________  
**Date**: YYYY-MM-DD  

**Review Signature**: ________________________  
**Date**: YYYY-MM-DD  

**Comments**:
```
[Summary of test execution, any issues encountered, and overall assessment]
```

---

## Appendix: Command Log

### Commands Executed (for reference)

```bash
# Phase 1: VPS Provisioning
[Paste key commands here]

# Phase 2: Code Restoration
[Paste key commands here]

# Phase 3: Backup Restoration
[Paste key commands here]

# ... etc for all phases
```

### Logs Captured

- Apache error log: `/var/log/apache2/error.log`
- Django application log: `/var/log/ppm/django.log`
- Systemd journal: `journalctl -u ppm-backup.service`

---

**Document Version**: 1.0  
**Related Issues**: malko73/ppm#3 (Step 1, 2, 3)  
**Next Review**: [Date]
