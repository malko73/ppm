# PPM Disaster Recovery Playbook

## Overview

Complete procedure to recover PPM (Portable PDF Manager) on a new VPS from backup artifacts.

**Target RTO**: 4 hours from new VPS provisioning to PDF output confirmation  
**Target RPO**: 24 hours (daily backups at 02:00)

**Prerequisites**:
- New Ubuntu/Debian VPS (22.04 LTS or later)
- Access to backup artifacts (S3/GCS bucket)
- Access to encryption keys (KMS/Vault/YubiKey)
- Basic system administration skills

---

> ## ⚠️ READ FIRST — IMPLEMENTED REALITY (verified 2026-10-17)
>
> **Phases 1–5 below describe a TARGET architecture (S3/GCS + KMS/Vault + `/var/lib/ppm` + media
> tarballs + `*.sha256` sidecars + 02:00 schedule) that is NOT implemented.** Following them today
> will fail. The verified, actually-running procedure is this section.
>
> ### What exists
>
> | Item | Reality |
> |---|---|
> | Schedule | `/etc/cron.d/ppm-backup` → `0 6 * * * root /usr/local/bin/backup-ppm.sh` (06:00 JST daily) |
> | Script | `/usr/local/bin/backup-ppm.sh` (0700 root). Previous version: `backup-ppm.sh.pre-gpg-20261017` |
> | Artifacts | `/var/backups/ppm/` (dir `0700 root`), `ppm_YYYYmmdd_HHMMSS.sql.gz.gpg` (files `0600 root`) |
> | Latest pointer | `/var/backups/ppm/ppm_latest.sql.gz.gpg` → newest artifact |
> | Encryption | GPG public-key only on the host: recipient `2894659F30D57F5A59F7D24E18073F5C40179CA3` (`ppm-backup@y-asahi.local`, expires 2028-10-16), pubkey ring `/root/.gnupg-ppm` (`0700`) |
> | Private key | **Never on the VPS.** Mac `~/.gnupg-ppm` (`0700`), passphrase `~/.ppm-backup-passphrase` (`0600`) |
> | Retention | 14 days (`-mtime +14`), only `*.sql.gz.gpg` |
> | Log | `/var/log/ppm-backup.log` (`0600 root`) — `OK:` / `FAILED:` lines with timestamps |
> | Database | MariaDB `appsdb`; root uses **unix_socket** auth, so the `.env` password is not what authenticated the dump |
> | Legacy plaintext | 16 pre-2026-10-17 dumps moved to `/var/backups/ppm-legacy-plaintext-20261017/` (`0700 root`, files `0600`). Hashes: `/root/ppm-legacy-plaintext-sha256-20261017.txt`. **Not deleted** — decision pending. |
>
> Script guarantees: `set -euo pipefail`; dump verified with `gzip -t` and the
> `-- Dump completed` trailer before encryption; plaintext temp is `0600` in the backup dir and
> removed by `trap` on every exit path; encrypted output validated as an OpenPGP
> `:pubkey enc packet` addressed to the expected recipient; **any failure exits non-zero and logs
> `FAILED:`** (verified by injecting a bogus database name).
>
> ### Restore procedure (verified drill, 2026-10-17)
>
> ```bash
> # 1. Fetch the newest artifact (root-only file → stream it)
> ssh sakura-vps 'sudo cat /var/backups/ppm/ppm_latest.sql.gz.gpg' > ppm.sql.gz.gpg
> ssh sakura-vps 'sudo sha256sum /var/backups/ppm/ppm_latest.sql.gz.gpg'   # compare both sides
>
> # 2. Decrypt on a machine that holds the private key
> export GNUPGHOME="$HOME/.gnupg-ppm"
> gpg --batch --pinentry-mode loopback --passphrase-file "$HOME/.ppm-backup-passphrase" \
>     --decrypt ppm.sql.gz.gpg > ppm.sql.gz
>
> # 3. Verify BEFORE importing (never import an unverified dump)
> gzip -t ppm.sql.gz
> gzip -dc ppm.sql.gz | tail -1        # must be: -- Dump completed on <timestamp>
> gzip -dc ppm.sql.gz | grep -c '^CREATE TABLE'
>
> # 4. Import
> gzip -dc ppm.sql.gz | mysql -u root appsdb
> ```
>
> Measurement of the 2026-10-17 drill: encrypted 62,427 B → plaintext 62,224 B → 308,700 B SQL,
> 16 `CREATE TABLE`, 16 `INSERT INTO`, trailer `-- Dump completed on 2026-10-17 15:13:38`,
> `projects_project` / `projects_page` / `accounts_customuser` / `projects_projecttemplate` present,
> SHA-256 identical on both sides.
>
> ### media archive (uploaded PDFs / images)
>
> | Item | Reality |
> |---|---|
> | Script | `/usr/local/bin/backup-ppm-media.sh` — repo source of truth `deploy/backup-ppm-media.sh` |
> | Schedule | `/etc/cron.d/ppm-backup-media` → `30 6 * * 0` (Sundays 06:30, after the DB run) |
> | Artifact | `/var/backups/ppm-media/ppm_media_YYYYmmdd_HHMMSS.tar.gpg` (`0600`), 3 generations kept |
> | Sidecar | `ppm_media_*.meta` (`0600`, plaintext metadata only): `file_count`, `total_bytes`, `manifest_sha256`, `gpg_sha256` |
> | Content | `tar -C /var/www/html -cf - media` — **no compression** (payload is PDF/PNG/JPEG) |
> | Change detection | sorted manifest of `path/size/mtime` hashed; identical hash ⇒ the run logs `SKIP` and writes nothing |
> | Measured | 58 files / 201,885,111 bytes → 196,837,802 B encrypted in ~9 s |
>
> ### Off-site copy (Mac → Google Drive)
>
> The VPS holds **no cloud credentials**. `~/.hermes/scripts/ppm_offsite.sh` runs on the Mac
> (which holds the private key) and pulls the encrypted artifacts over SSH:
>
> | Hermes cron | Schedule | Mode | Destination |
> |---|---|---|---|
> | `ppm-offsite-daily` | `10 7 * * *` | `daily` | `gdrive:ppm-backup/db/` (30 generations) |
> | `ppm-offsite-weekly` | `40 7 * * 0` | `weekly` | adds `gdrive:ppm-backup/media/` (3 generations) |
> | `ppm-offsite-audit` | `0 8 1 * *` | `audit` | decrypts the newest Drive copy, asserts generations and heartbeat |
>
> Verification chain per upload: VPS `sha256sum` == local `sha256sum` → **decrypt** → `gzip -t` →
> `-- Dump completed` trailer → `rclone copyto` → read-back size **and** md5 must match.
> Media additionally: compare `gpg_sha256` with the sidecar, decrypt, extract, and require
> `file_count` **and** `total_bytes` parity before upload. Everything happens in a `0700` temp dir
> removed by `trap`; the plaintext tar is never outside it.
>
> Retention is explicit: generations are sorted and only the oldest beyond the keep-count are
> deleted by name (`rclone deletefile`). `rclone delete --min-age` is deliberately **not** used,
> because the `hermes-backup` remote silently kept ~3 days against a configured 60.
>
> Successful daily runs produce no stdout (silent); weekly/audit print a summary line.
> Failures exit non-zero with a `FAILED ppm-offsite(...)` line first, which is what Discord shows.
>
> ### What is NOT covered (known gaps)
>
> 1. **No PITR.** RPO is 24 h for the DB and 7 days for `media/`, and only if the 06:00 run succeeded.
> 2. **Private-key escrow is not yet verified off-device.** Losing the Mac's `~/.gnupg-ppm` makes
>    every artifact — local and on Drive — permanently unreadable.
> 3. The GPG passphrase file lives on the same host as the private key.
> 4. **The Mac is a single point of failure for the upload** (sleep/offline ⇒ no off-site copy that day;
>    the VPS keeps 14 days of DB artifacts so short gaps are recoverable).
> 5. Drive is the same account used by `hermes-backup`, so a Drive-side incident affects both.
> 6. **No import-into-scratch-DB drill on the VPS.** Decryption, integrity and content parity are
>    proven; a full `mysql <dump>` restore onto a throwaway database has not been executed.
>
> ### Key escrow (2026-10-17, drill-proven)
>
> | Piece | Where |
> |---|---|
> | Secret key (armored, passphrase-protected) | `gdrive:ppm-backup/keys/ppm-backup-secret.asc` — 951 B, sha256 `b6e2ddb4d6bfaf1efbe972e375bb7e19180e9799eed61692aa91be1612c8472e` |
> | Key fingerprint | `2894659F30D57F5A59F7D24E18073F5C40179CA3` (`ppm-backup@y-asahi.local`, expires 2028-10-16) |
> | Live secret key | Mac `~/.gnupg-ppm` (`0700`) |
> | Passphrase | **ESCROW INCOMPLETE as of 2026-10-17 20:01.** `op item get "PPM backup GPG passphrase"` returns *"isn't an item"* on the signed-in account, so no such item is visible there. The value still exists only as `~/.ppm-backup-passphrase` (`0600`, 48 chars, sha256 `c3d07a44…388cee`) on the Mac. |
>
> The exported key carries `iter+salt S2K, algo 7 (AES-256), skey: [v4 protected]`, so the Drive copy
> alone is useless without the passphrase. **Because the passphrase is still single-host, losing the
> Mac still loses every artifact** — the escrow only counts once an off-device copy is confirmed.
>
> **Integrity cross-check for the passphrase** (safe to publish — the value is 288 random
> bits, so the digest is not invertible):
>
> ```bash
> shasum -a 256 < ~/.ppm-backup-passphrase
> # c3d07a442001077dc74ae4ef5a44e16961023247ecdc2b0dde998ad260388cee  (48 chars, no newline)
> ```
>
> To close the escrow: create the item (a ready-to-import template can be generated from the local
> file, so the value never has to be typed or pasted into a chat), then confirm with
>
> ```bash
> op item get "PPM backup GPG passphrase" --fields label=password | tr -d '\n' | shasum -a 256
> # must equal the digest above; anything else means the item holds a different value
> ```
>
> Two failed verification attempts are recorded so nobody repeats them:
> `e3b0c442…b855` is the sha256 of **empty input** (the CLI errored and emitted nothing), and
> `6e0f0047…` was a digest of 642 bytes of **terminal prompt text** that was in the clipboard —
> neither attempt ever hashed the passphrase, so neither says anything about the stored value.
>
> Restore drill that was actually run (fresh `GNUPGHOME`, key pulled back **from Drive**):
>
> ```bash
> CHECK=$(mktemp -d); chmod 700 "$CHECK"
> rclone copyto gdrive:ppm-backup/keys/ppm-backup-secret.asc "$CHECK/k.asc"
> GNUPGHOME="$CHECK" gpg --batch --import "$CHECK/k.asc"
> # no passphrase -> must fail (exit 2, "パスフレーズが与えられていません")
> GNUPGHOME="$CHECK" gpg --batch --pinentry-mode loopback --passphrase '' --decrypt artifact.gpg > /dev/null
> # real passphrase -> succeeds, plaintext sha256 475f6d39…93a8eb27, trailer "-- Dump completed on 2026-10-17 15:13:38"
> GNUPGHOME="$CHECK" gpg --batch --pinentry-mode loopback --passphrase-file PASSPHRASE --decrypt artifact.gpg > out.sql.gz
> ```
>
> Transfer integrity: Drive md5 `668b89611358fd16eed0f1209d54bd38` == local md5. Only the encrypted,
> passphrase-protected export is stored; no unprotected copy of the secret key exists off the Mac.


>
> `gpg --list-packets <artifact>` exits **2** on the VPS ("public key decryption failed: No secret
> key") while still printing the packets — that is expected, not a corrupt file.

---

## Phase 0: Environment Setup (Est. 5 minutes)

### 0.1 Export Required Variables

Before starting recovery, set the following environment variables to match your backup configuration:

```bash
# AWS Configuration (REQUIRED)
export AWS_S3_BUCKET="ppm-backups"           # S3 bucket name
export AWS_S3_PREFIX="ppm-backups"           # S3 prefix/folder path
export AWS_REGION="ap-northeast-1"           # AWS region (e.g., ap-northeast-1, us-west-1)

# Verify configuration
echo "AWS_S3_BUCKET: ${AWS_S3_BUCKET}"
echo "AWS_S3_PREFIX: ${AWS_S3_PREFIX}"
echo "AWS_REGION: ${AWS_REGION}"
```

**Expected output**: Your S3 bucket configuration should be displayed.

### 0.2 Verify AWS Credentials

Ensure AWS credentials are configured and valid:

```bash
# Check AWS CLI is installed
aws --version

# Verify credentials
aws sts get-caller-identity --region ${AWS_REGION}

# Expected output: Valid AWS account information
# {
#     "UserId": "...",
#     "Account": "123456789012",
#     "Arn": "arn:aws:iam::123456789012:user/..."
# }
```

**Note**: If this command fails, configure AWS credentials:
```bash
aws configure
# or set environment variables:
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
```

---

## Phase 1: New VPS Provisioning (Est. 30 minutes)

### 1.1 VPS Setup

```bash
# SSH into new VPS
ssh root@NEW_VPS_IP

# Update system
apt-get update
apt-get upgrade -y

# Install essential tools (including web server)
apt-get install -y \
    git \
    curl \
    wget \
    postgresql-client \
    postgresql \
    python3.11 \
    python3-pip \
    python3-venv \
    gpg \
    tar \
    gzip \
    awscli \
    apache2 \
    libapache2-mod-wsgi-py3

# Enable Apache modules for WSGI
a2enmod wsgi
a2enmod proxy
a2enmod proxy_http

# Verify tools installed
pg_dump --version
gpg --version
aws --version
```

### 1.2 System Configuration

```bash
# Create application user
useradd -m -s /bin/bash ppm
usermod -aG sudo ppm

# Create application directories
mkdir -p /home/ppm/ppm
mkdir -p /var/lib/ppm/backups
chown -R ppm:ppm /home/ppm/ppm
chown -R ppm:ppm /var/lib/ppm

# Configure database user (if PostgreSQL local)
sudo -u postgres psql << EOF
CREATE USER ppm WITH PASSWORD 'CHANGE_THIS_PASSWORD';
CREATE DATABASE ppm OWNER ppm;
ALTER DATABASE ppm SET timezone = 'UTC';
EOF
```

### 1.3 PostgreSQL Configuration

#### Using .pgpass for Secure Password Handling

Instead of hardcoding passwords in commands or environment variables, use PostgreSQL's `.pgpass` file:

```bash
# Set PGPASSFILE to use standard location
export PGPASSFILE="$HOME/.pgpass"

# Create .pgpass file in standard location
touch ~/.pgpass
chmod 600 ~/.pgpass

# Add credentials:
# Format: hostname:port:database:username:password
cat >> ~/.pgpass << EOF
localhost:5432:ppm:ppm:YOUR_SECURE_PASSWORD
EOF

# Verify .pgpass
cat ~/.pgpass
# Expected: localhost:5432:ppm:ppm:YOUR_SECURE_PASSWORD
```

#### Setup PostgreSQL User and Database

```bash
# CRITICAL: Password in psql must match .pgpass entry
export PGPASSFILE="$HOME/.pgpass"

# Create user WITH PASSWORD (must match .pgpass)
sudo -u postgres psql << EOF
CREATE USER ppm WITH PASSWORD 'YOUR_SECURE_PASSWORD';
CREATE DATABASE ppm OWNER ppm;
ALTER DATABASE ppm SET timezone = 'UTC';
EOF

# Test connection using .pgpass (should not prompt for password)
psql -h localhost -U ppm -d ppm -c "SELECT 1;"
# Expected: no password prompt, returns "1"
```

**Key Points**:
- Export `PGPASSFILE="$HOME/.pgpass"` before any psql command
- `CREATE USER ppm WITH PASSWORD 'YOUR_SECURE_PASSWORD'` must match .pgpass entry
- Never use passwords in CLI: `psql -U ppm -W ...` (interactive) or `PGPASSWORD=... psql`
- .pgpass file requires 600 permissions
- After recovery, verify no secrets in logs: `grep -q "password" /var/log/postgresql/*.log || echo "✓ No password exposure in logs"`

### 1.4 Firewall & Network (if applicable)

```bash
# Allow SSH, HTTP, HTTPS
ufw allow 22
ufw allow 80
ufw allow 443
ufw enable

# Or adjust based on your security model
```

**Elapsed time: ~30 minutes**

---

## Phase 2: Code Restoration (Est. 15 minutes)

### 2.1 Clone Repository

```bash
# Switch to ppm user
sudo -u ppm -H bash

# Clone from GitHub
cd /home/ppm
git clone https://github.com/malko73/ppm.git
cd ppm

# Checkout known stable commit (or latest tag)
git checkout fdfb61e  # or latest stable tag

# Verify clone
git log --oneline -1
git status
```

### 2.2 Install Dependencies

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# Verify installations
python -c "import django; print(django.get_version())"
python -c "import psycopg2; print(psycopg2.__version__)"
```

**Elapsed time: ~15 minutes**

---

## Phase 3: Backup Restoration (Est. 45 minutes)

### 3.1 Download Backup Set from S3

```bash
# Set target backup date (e.g., latest available)
export BACKUP_DATE=20260822

# Create temporary directory
mkdir -p /var/lib/ppm/restore/${BACKUP_DATE}
cd /var/lib/ppm/restore/${BACKUP_DATE}

# Download backup set from S3
# Uses environment variables from Phase 0: AWS_S3_BUCKET, AWS_S3_PREFIX, AWS_REGION
# Requires AWS credentials configured (via ~/.aws/credentials or IAM role)

aws s3 cp \
    s3://${AWS_S3_BUCKET}/${AWS_S3_PREFIX}/${BACKUP_DATE}/ \
    . \
    --recursive \
    --region ${AWS_REGION}

# Verify files downloaded
ls -lh

# Expected files:
# - ppm_db_YYYYMMDD.sql
# - ppm_db_YYYYMMDD.sql.sha256
# - media_YYYYMMDD.tar.gz
# - media_YYYYMMDD.tar.gz.sha256
# - .env.gpg
# - .env.gpg.sha256
```

### 3.2 Verify Checksums

```bash
# Verify each artifact against checksum
# **CRITICAL**: Do not proceed if any checksum fails

echo "=== Verifying Backup Integrity ==="

# Verify PostgreSQL dump
if sha256sum -c ppm_db_${BACKUP_DATE}.sql.sha256; then
    echo "✓ PostgreSQL dump checksum OK"
else
    echo "✗ PostgreSQL dump checksum FAILED - ABORT RECOVERY"
    exit 1
fi

# Verify media archive
if sha256sum -c media_${BACKUP_DATE}.tar.gz.sha256; then
    echo "✓ Media archive checksum OK"
else
    echo "✗ Media archive checksum FAILED - ABORT RECOVERY"
    exit 1
fi

# Verify encrypted .env
if sha256sum -c .env.gpg.sha256; then
    echo "✓ Encrypted .env checksum OK"
else
    echo "✗ Encrypted .env checksum FAILED - ABORT RECOVERY"
    exit 1
fi

echo "=== All checksums verified ==="
```

### 3.3 Retrieve Encryption Key

```bash
# **CRITICAL**: Key must be retrieved from separate system
# Do NOT store key in same VPS or S3 bucket as backup

echo "=== Retrieving Encryption Key ==="

# Option A: AWS KMS
# aws kms decrypt \
#     --ciphertext-blob fileb://key.encrypted \
#     --query Plaintext \
#     --output text | base64 -d > /tmp/gpg_key.asc

# Option B: HashiCorp Vault
# vault kv get -field=gpg_key secret/ppm/backup > /tmp/gpg_key.asc

# Option C: Manual (from secure location)
# Import from YubiKey or secure USB
# gpg --import /mnt/secure/gpg_key.asc

# Verify key is available
if gpg --list-secret-keys | grep -q backup; then
    echo "✓ Secret key is available"
    KEY_STATUS="READY"
else
    echo "✗ Secret key NOT found - ABORT RECOVERY"
    exit 1
fi

if [[ $? -ne 0 ]]; then
    echo "✗ GPG key not found - ABORT RECOVERY"
    exit 1
fi

echo "✓ Encryption key retrieved"
```

### 3.4 Decrypt .env

```bash
echo "=== Decrypting .env ==="

# Decrypt .env from backup
gpg --decrypt .env.gpg > .env.restored

if [[ ! -f .env.restored ]] || [[ ! -s .env.restored ]]; then
    echo "✗ .env decryption failed or file empty - ABORT RECOVERY"
    exit 1
fi

# Verify .env structure (without displaying secrets)
if grep -q "^SECRET_KEY=" .env.restored && \
   grep -q "^DATABASE_URL=" .env.restored; then
    echo "✓ .env decrypted and verified (secrets not displayed)"
else
    echo "✗ .env missing required variables - ABORT RECOVERY"
    exit 1
fi

# Copy to application directory (will be done in Phase 4)
```

### 3.5 Extract Media Archive

```bash
echo "=== Extracting Media Files ==="

# Create media target directory
mkdir -p /home/ppm/ppm/media

# Extract archive
tar xzf media_${BACKUP_DATE}.tar.gz -C /home/ppm/ppm/

# Verify extraction
if [[ -d /home/ppm/ppm/media ]] && [[ "$(ls /home/ppm/ppm/media | wc -l)" -gt 0 ]]; then
    echo "✓ Media files extracted: $(ls /home/ppm/ppm/media | wc -l) items"
else
    echo "⚠ Media directory empty (this may be normal if no media was present)"
fi

# Fix permissions
chown -R ppm:ppm /home/ppm/ppm/media
chmod -R 755 /home/ppm/ppm/media
```

**Elapsed time: ~45 minutes**

---

## Phase 4: Database Restoration (Est. 30 minutes)

### 4.1 Restore PostgreSQL Dump

```bash
echo "=== Restoring PostgreSQL Database ==="

# Switch to postgres user if needed
# Note: You may need to restore as superuser depending on permissions

# Option A: Restore to local PostgreSQL
psql -U postgres -d ppm < ppm_db_${BACKUP_DATE}.sql

# Option B: Restore to remote PostgreSQL
# psql -h DB_HOST -U postgres -d ppm < ppm_db_${BACKUP_DATE}.sql

# Verify restoration
psql -U postgres -d ppm -c "SELECT COUNT(*) FROM projects_project;"
psql -U postgres -d ppm -c "SELECT COUNT(*) FROM projects_page;"

echo "✓ PostgreSQL database restored"
```

### 4.2 Verify Database Integrity

```bash
echo "=== Verifying Database Integrity ==="

psql -U postgres -d ppm << EOF
-- Check essential tables
\dt projects_*
\dt auth_*

-- Sample queries
SELECT COUNT(*) as project_count FROM projects_project;
SELECT COUNT(*) as page_count FROM projects_page;
SELECT COUNT(*) as user_count FROM auth_user;

-- Check for corruption
PRAGMA integrity_check;
EOF
```

**Elapsed time: ~30 minutes**

---

## Phase 5: Application Setup (Est. 45 minutes)

### 5.1 Configure Environment

```bash
echo "=== Configuring Application Environment ==="

# Copy decrypted .env to application
cd /home/ppm/ppm
cp /var/lib/ppm/restore/${BACKUP_DATE}/.env.restored .env

# Verify critical settings (secrets not displayed in logs)
grep -q '^SECRET_KEY=' .env && echo "✓ SECRET_KEY: PRESENT"
grep -q '^DATABASE_URL=' .env && echo "✓ DATABASE_URL: PRESENT"

# Set file permissions
chmod 600 .env
chown ppm:ppm .env
```

### 5.2 Django Migrations & Setup

```bash
echo "=== Running Django Setup ==="

# Activate virtual environment
source venv/bin/activate

# Run migrations (should be idempotent if already applied)
python manage.py migrate --noinput

# Collect static files
python manage.py collectstatic --noinput --clear

# Create superuser (if needed - optional for recovery)
# python manage.py createsuperuser

# Run health check
python manage.py check
```

### 5.3 Verify Application

```bash
echo "=== Verifying Application State ==="

# Check database connection
python manage.py dbshell << EOF
SELECT 1;
\q
EOF

# Verify migrations applied
python manage.py showmigrations --plan | tail -5

# Check static files
ls -lh staticfiles/ | head -10
```

**Elapsed time: ~45 minutes**

---

## Phase 6: Service Startup (Est. 15 minutes)

### 6.1 Configure Web Server (Apache/Nginx)

```bash
# Example for Apache with mod_wsgi
# Adapt based on your actual web server configuration

# Copy Apache config
sudo cp deploy/apache-ppm.conf /etc/apache2/sites-available/ppm.conf

# Enable site
sudo a2ensite ppm

# Enable required modules
sudo a2enmod wsgi
sudo a2enmod proxy
sudo a2enmod proxy_http

# Test configuration
sudo apache2ctl configtest

# Restart Apache
sudo systemctl restart apache2
sudo systemctl status apache2
```

### 6.2 Start Background Services

```bash
# If using Celery
# sudo systemctl start ppm-celery
# sudo systemctl status ppm-celery

# If using other background services
# ... start as configured

echo "✓ Services started"
```

### 6.3 Verify Web Server

```bash
# Test HTTP connection
curl -v http://localhost/health/

# Or if HTTPS configured
# curl -v https://localhost/health/

# Expected: HTTP 200 OK
```

**Elapsed time: ~15 minutes**

---

## Phase 7: Verification (Est. 30 minutes)

### 7.1 Web UI Confirmation

```bash
echo "=== Verifying Web UI ==="

# Access application
curl -I http://localhost/projects/
# Expected: HTTP 200 OK

# Check Django admin
curl -I http://localhost/admin/
# Expected: HTTP 200 OK or 302 (redirect to login)
```

### 7.2 Database Content Verification

```bash
echo "=== Verifying Application Data ==="

python manage.py shell << EOF
from projects.models import Project, Page

# Count projects and pages
projects = Project.objects.count()
pages = Page.objects.count()

print(f"Projects: {projects}")
print(f"Pages: {pages}")

# Sample data
if projects > 0:
    p = Project.objects.first()
    print(f"Sample project: {p.name} (ID: {p.id})")
    print(f"  Pages: {p.page_set.count()}")
    print(f"  Templates: {p.templates.count()}")
EOF
```

### 7.3 Media Files Verification

```bash
echo "=== Verifying Media Files ==="

# Check media directory
ls -lh /home/ppm/ppm/media/ | head -20

# Verify file count
file_count=$(find /home/ppm/ppm/media -type f | wc -l)
echo "Media files: ${file_count}"

# Check for common issues
du -sh /home/ppm/ppm/media/
```

**Elapsed time: ~30 minutes**

---

## Phase 8: PDF Output Test (Est. 30 minutes)

### 8.1 Create Test Data (if needed)

```bash
echo "=== Setting Up PDF Test ==="

python manage.py shell << EOF
from projects.models import Project, ProjectTemplate, Page

# Create or use existing project
project, created = Project.objects.get_or_create(
    name="Recovery Test Project",
    defaults={"owner_id": 1}  # Adjust to valid user
)

print(f"Project: {project.name} (ID: {project.id})")

# Use first available template or create one
if project.templates.exists():
    template = project.templates.first()
    print(f"Using template: {template.name}")
else:
    template = ProjectTemplate.objects.create(
        project=project,
        name="Test Template",
        width_mm=210,
        height_mm=297
    )
    print(f"Created template: {template.name}")
EOF
```

### 8.2 Trigger PDF Generation

```bash
echo "=== Generating PDF ==="

# Access a page and trigger PDF generation
# This can be done via:
# 1. Django shell
# 2. Web UI
# 3. Management command (if available)

python manage.py shell << EOF
from projects.models import Page
from projects.services.pdf_renderer import PDFRenderService

# Get a test page
page = Page.objects.first()

if page:
    print(f"Generating PDF for page: {page.page_name}")
    
    # Generate PDF
    renderer = PDFRenderService(page)
    pdf_bytes = renderer.generate()
    
    print(f"✓ PDF generated: {len(pdf_bytes)} bytes")
    
    # Verify PDF structure
    if pdf_bytes[:4] == b'%PDF':
        print("✓ PDF header verified")
    else:
        print("✗ PDF header invalid")
EOF
```

### 8.3 Verify PDF Output

```bash
echo "=== Verifying PDF Output ==="

# Check PDF can be downloaded via HTTP
curl -o /tmp/test.pdf http://localhost/projects/1/pages/1/pdf/

# Verify PDF file
file /tmp/test.pdf
# Expected: PDF document, version 1.4 (or similar)

# Check file size (should not be 0 or suspiciously small)
ls -lh /tmp/test.pdf

# Optional: Open in viewer to inspect
# (requires graphical environment or headless PDF viewer)
```

### 8.4 Coordinate System Verification

```bash
echo "=== Verifying Coordinate System (Issue #5) ==="

# This validates that the mm→px→pt transformation is correct
# and that recovered template data produces identical PDFs

python manage.py shell << EOF
from projects.models import ProjectTemplate
from projects.utils.coordinates import CoordinateConverter

# Get a template
template = ProjectTemplate.objects.first()

if template and template.default_positions:
    positions = template.default_positions
    
    # Verify coordinate structure
    print("Template coordinates (mm):")
    for text in positions.get('text_layout', []):
        print(f"  {text['key']}: x={text['x']}, y={text['y']}, w={text['w']}, h={text['h']}")
    
    # Test coordinate conversion
    coords = CoordinateConverter(
        templateWidthMm=template.width_mm,
        templateHeightMm=template.height_mm
    )
    
    # Convert sample coordinate
    x_mm = 105.0
    x_px = coords.mmToPx(x_mm, 'x')
    x_mm_back = coords.pxToMm(x_px, 'x')
    
    print(f"\nCoordinate conversion test:")
    print(f"  {x_mm} mm → {x_px} px → {x_mm_back} mm")
    
    if abs(x_mm - x_mm_back) < 0.01:
        print("✓ Coordinate conversion OK (round-trip accurate)")
    else:
        print("✗ Coordinate conversion ERROR (precision loss)")
EOF
```

**Elapsed time: ~30 minutes**

---

## Recovery Complete

### Summary

**Total Elapsed Time**: ~3.75 hours (Target: 4 hours) ✓

If all phases completed successfully:

✅ New VPS provisioned and configured  
✅ Code restored from GitHub  
✅ Backup artifacts verified (checksum)  
✅ Encryption key retrieved (separate system)  
✅ Database restored and verified  
✅ Application configured and tested  
✅ Web services running  
✅ PDF generation confirmed  
✅ Coordinate system (mm→px→pt) validated  

**RPO Achieved**: Latest backup (within 24 hours)  
**RTO Achieved**: < 4 hours from new VPS to PDF output ✓

---

## Troubleshooting

### If checksum fails
```bash
# Do NOT proceed - backup may be corrupted
# 1. Verify network connection to S3
# 2. Re-download backup from S3
# 3. If still fails, use previous day's backup
```

### If decryption fails
```bash
# Verify GPG key is available
gpg --list-keys

# Re-import key from separate system
gpg --import /path/to/key

# Retry decryption
gpg --decrypt .env.gpg
```

### If database restore fails
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Verify dump file integrity
head -5 ppm_db_*.sql
# Should show SQL header

# Retry with verbose output
psql -U postgres -d ppm -v ON_ERROR_STOP=on < ppm_db_*.sql
```

### If PDF generation fails
```bash
# Check Django logs
tail -f /var/log/ppm/django.log

# Run health check
python manage.py check

# Test database connection
python manage.py dbshell
```

---

## Post-Recovery

### 1. Update DNS/Load Balancer
```bash
# Point traffic to new VPS
# Update DNS A records or load balancer target
```

### 2. Verify Traffic
```bash
# Monitor application logs
tail -f /var/log/apache2/access.log
tail -f /var/log/ppm/django.log

# Check no error spikes
curl -v https://ppm.yourdomain.com/
```

### 3. Backup Status Reset
```bash
# Clear old backup metadata (if needed)
# New backups will start at 02:00 next day
systemctl status ppm-backup.timer
```

---

## Related Documentation

- Issue #3 Step 1: `docs/BACKUP_STEP1.md`
- Coordinate System: `docs/COORDINATE_SYSTEM.md` (Issue #5)
- Setup Guide: `README.md`
- GitHub Issue: https://github.com/malko73/ppm/issues/3

---

**Recovery Playbook Version**: 1.0  
**Last Updated**: 2026-08-22  
**Contact**: devops@ppm.local
