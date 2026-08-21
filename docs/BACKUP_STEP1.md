# PPM Backup & Disaster Recovery - Step 1

## Overview

This directory contains the backup infrastructure for PPM (Portable PDF Manager).

**Purpose**: Daily backup of Application State (PostgreSQL DB, media files, .env secrets) with SHA-256 verification and remote S3 storage.

**Schedule**: Daily at 02:00 UTC (configurable)

**Backup Structure**:
```
backups/
├── ppm_backup_YYYYMMDD/
│   ├── ppm_db_YYYYMMDD.sql           # PostgreSQL dump
│   ├── ppm_db_YYYYMMDD.sql.sha256    # Checksum
│   ├── media_YYYYMMDD.tar.gz         # Media files archive
│   ├── media_YYYYMMDD.tar.gz.sha256  # Checksum
│   ├── .env.gpg                      # Encrypted .env
│   ├── .env.gpg.sha256               # Checksum
│   └── backup.log                    # Per-backup log
└── logs/
    └── backup_YYYYMMDD_HHMMSS.log    # Detailed logs
```

---

## Installation

### 1. Create System User

```bash
sudo useradd -m -s /bin/bash ppm
sudo mkdir -p /home/ppm/ppm
sudo chown -R ppm:ppm /home/ppm/ppm
```

### 2. Configure Environment

```bash
# Copy the template
cp .env.backup.template .env.backup

# Edit with your configuration
vi .env.backup

# Source it in systemd service (already configured)
```

### 3. Setup GPG Encryption Key

```bash
# Create or import GPG key for backup encryption
gpg --gen-key
# or
gpg --import <key-file>

# List available keys
gpg --list-keys

# Set the key ID in .env.backup
# Example: GPG_RECIPIENT=0x1234567890ABCDEF
```

### 4. Setup AWS S3 (if using remote storage)

```bash
# Create S3 bucket
aws s3 mb s3://ppm-backups --region ap-northeast-1

# Configure AWS credentials for ppm user
sudo -u ppm aws configure

# Verify access
sudo -u ppm aws s3 ls s3://ppm-backups/
```

### 5. Install Systemd Timer

```bash
# Copy service and timer files
sudo cp deploy/ppm-backup.service /etc/systemd/system/
sudo cp deploy/ppm-backup.timer /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start timer
sudo systemctl enable ppm-backup.timer
sudo systemctl start ppm-backup.timer

# Verify timer is active
sudo systemctl list-timers ppm-backup.timer
```

---

## Manual Testing

### 1. Dry Run (no actual backup)

```bash
./scripts/backup.sh --dry-run
```

Expected output:
```
[2026-08-22 15:30:45] [INFO] Creating backup directories...
[2026-08-22 15:30:45] [INFO] [DRY-RUN] Would dump PostgreSQL to ...
[2026-08-22 15:30:45] [INFO] [DRY-RUN] Would tar media to ...
...
```

### 2. Local-Only Backup (no S3 upload)

```bash
./scripts/backup.sh --local-only
```

Expected output:
```
[2026-08-22 15:31:00] [INFO] PostgreSQL backup completed: 245M
[2026-08-22 15:31:05] [INFO] Media backup completed: 1.2G
[2026-08-22 15:31:10] [INFO] .env encryption completed: 2.1K
[2026-08-22 15:31:10] [INFO] Generating SHA-256 checksums...
[2026-08-22 15:31:10] [INFO] ✓ ppm_db_20260822.sql checksum verified
[2026-08-22 15:31:10] [INFO] ✓ media_20260822.tar.gz checksum verified
[2026-08-22 15:31:10] [INFO] ✓ .env.gpg checksum verified
```

### 3. Full Backup with S3 Upload

```bash
./scripts/backup.sh
```

Expected output:
```
... (same as local-only)
[2026-08-22 15:31:12] [INFO] Uploading backup set to S3...
[2026-08-22 15:31:45] [INFO] S3 upload completed: s3://ppm-backups/ppm-backups/20260822/
```

### 4. Verify Backup Files

```bash
# List backup contents
ls -lh backups/ppm_backup_20260822/

# Verify checksums manually
cd backups/ppm_backup_20260822/
sha256sum -c ppm_db_20260822.sql.sha256
sha256sum -c media_20260822.tar.gz.sha256
sha256sum -c .env.gpg.sha256

# View backup log
cat backup.log
```

---

## Monitoring

### Check Timer Status

```bash
sudo systemctl status ppm-backup.timer
sudo systemctl list-timers ppm-backup.timer
```

### View Backup Logs

```bash
# Journal logs
sudo journalctl -u ppm-backup.service -n 50

# Or detailed logs
tail -f backups/logs/backup_*.log
```

### Verify S3 Backups

```bash
aws s3 ls s3://ppm-backups/ --recursive
```

---

## Backup Integrity

### Manual Checksum Verification

```bash
# Download from S3
aws s3 cp s3://ppm-backups/ppm-backups/20260822/ppm_db_20260822.sql .
aws s3 cp s3://ppm-backups/ppm-backups/20260822/ppm_db_20260822.sql.sha256 .

# Verify
sha256sum -c ppm_db_20260822.sql.sha256

# Expected: OK
# If NOT OK: Backup is corrupted, do not use for recovery
```

---

## Troubleshooting

### PostgreSQL dump fails

```bash
# Check PostgreSQL is running
psql -h localhost -U postgres -d ppm -c "SELECT 1"

# Check user can connect
psql -h localhost -U postgres -d ppm -c "\du"
```

### GPG encryption fails

```bash
# Verify GPG key exists
gpg --list-keys

# Test encryption
echo "test" | gpg --encrypt --recipient YOUR_KEY_ID

# Check GPG_RECIPIENT is set correctly
grep GPG_RECIPIENT .env.backup
```

### S3 upload fails

```bash
# Check AWS credentials
aws sts get-caller-identity

# Verify S3 bucket access
aws s3 ls s3://ppm-backups/

# Check AWS region
grep AWS_REGION .env.backup
```

### Checksum mismatch

```bash
# If checksum fails during backup:
# 1. Check disk space
df -h

# 2. Check file corruption
sha256sum ppm_db_*.sql
sha256sum media_*.tar.gz

# 3. Re-run backup.sh
./scripts/backup.sh --local-only
```

---

## Next Steps

1. ✅ **Step 1 (Current)**: Daily backup implementation
2. **Step 2**: Recovery Playbook creation
3. **Step 3**: Initial Restore Test on staging
4. **Step 4**: RPO/RTO measurement
5. **Step 5**: Monthly test process automation

---

## Key Principles (Absolute Guards)

✅ **Backup Set Unity**: DB, media, .env backed up as single set  
✅ **Key Separation**: GPG key stored separately from encrypted .env  
✅ **Checksum Validation**: SHA-256 on every artifact, verified before restore  
✅ **RTO Verification**: Restore Test measures actual recovery time ≤ 4 hours  

---

## References

- GitHub Issue: malko73/ppm#3
- PostgreSQL Backup: https://www.postgresql.org/docs/current/sql-dumprestore.html
- GPG Encryption: https://gnupg.org/documentation/
- AWS S3: https://docs.aws.amazon.com/s3/
