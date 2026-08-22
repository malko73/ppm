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

## Phase 1: New VPS Provisioning (Est. 30 minutes)

### 1.1 VPS Setup

```bash
# SSH into new VPS
ssh root@NEW_VPS_IP

# Update system
apt-get update
apt-get upgrade -y

# Install essential tools
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
    awscli

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

### 1.3 Firewall & Network (if applicable)

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
# Requires AWS credentials configured (via ~/.aws/credentials or IAM role)

aws s3 cp \
    s3://ppm-backups/ppm-backups/${BACKUP_DATE}/ \
    . \
    --recursive \
    --region ap-northeast-1

# Verify files downloaded
ls -lh
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
gpg --list-keys | grep -i backup

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

# Verify .env structure
if grep -q "^SECRET_KEY=" .env.restored && \
   grep -q "^DATABASE_URL=" .env.restored; then
    echo "✓ .env decrypted and verified"
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

# Verify critical settings
grep -E "^(SECRET_KEY|DEBUG|ALLOWED_HOSTS|DATABASE_URL)" .env

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
