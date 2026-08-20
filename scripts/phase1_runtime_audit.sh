#!/bin/bash
#
# PPM Issue #2: Phase 1 — Read-only runtime audit
# VPS起動直後に実行し、実環境の状態を採取する
#
# Usage: ./phase1_runtime_audit.sh > /tmp/ppm_phase1_audit_$(date +%Y%m%d_%H%M%S).txt
#

set -u

echo "=================================================================================="
echo "PPM Phase 1 Runtime Audit"
echo "Executed: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "Host: $(hostname)"
echo "=================================================================================="
echo ""

# 1. OS Information
echo "[1] OS Information"
echo "---"
echo "OS Release:"
cat /etc/redhat-release 2>/dev/null || cat /etc/os-release 2>/dev/null
echo ""
echo "Kernel:"
uname -a
echo ""

# 2. Memory & Swap
echo "[2] Memory & Swap"
echo "---"
free -h
echo ""
echo "Swap configuration:"
swapon --show 2>/dev/null || echo "(no swap currently enabled)"
echo ""
echo "fstab swap entries:"
grep swap /etc/fstab || echo "(no swap in fstab)"
echo ""

# 3. Python Environment
echo "[3] Python Environment"
echo "---"
python --version 2>&1 || python3 --version 2>&1
echo ""
echo "Django version:"
python -m django --version 2>&1 || echo "Django not found"
echo ""
echo "Celery installed:"
python -c "import celery; print(celery.__version__)" 2>&1 || echo "Celery not installed"
echo ""

# 4. Database
echo "[4] MariaDB / MySQL"
echo "---"
echo "Version:"
mariadb --version 2>&1 || mysql --version 2>&1 || echo "MariaDB/MySQL not installed"
echo ""
echo "Service status:"
systemctl status mariadb --no-pager 2>&1 | grep -E "(Active|Loaded)" || echo "Service query failed"
echo ""
echo "Connectivity test:"
mariadb -e "SELECT 1 AS alive;" 2>&1 || echo "Connection failed"
echo ""

# 5. Redis
echo "[5] Redis"
echo "---"
echo "Version:"
redis-server --version 2>&1 || echo "Redis not installed"
echo ""
echo "Service status:"
systemctl status redis --no-pager 2>&1 | grep -E "(Active|Loaded)" || systemctl status redis-server --no-pager 2>&1 | grep -E "(Active|Loaded)" || echo "Service query failed"
echo ""
echo "Connectivity test (PING):"
redis-cli ping 2>&1 || echo "Redis not responding"
echo ""

# 6. Apache / HTTPD
echo "[6] Apache HTTP Server"
echo "---"
echo "Version:"
httpd -v 2>&1 | head -1 || echo "Apache not installed"
echo ""
echo "MPM module:"
httpd -V 2>&1 | grep -i "mpm" || echo "Cannot determine MPM"
echo ""
echo "Service status:"
systemctl status httpd --no-pager 2>&1 | grep -E "(Active|Loaded)" || echo "Service query failed"
echo ""
echo "Apache modules (mod_wsgi, ssl, etc.):"
httpd -M 2>&1 | grep -E "(wsgi|ssl)" || echo "Relevant modules not found"
echo ""

# 7. Celery
echo "[7] Celery Service"
echo "---"
echo "celery-ppm status:"
systemctl status celery-ppm --no-pager 2>&1 || echo "celery-ppm service not found"
echo ""
echo "Enabled:"
systemctl is-enabled celery-ppm 2>&1 || echo "Not configured"
echo ""
echo "Active:"
systemctl is-active celery-ppm 2>&1 || echo "Inactive/not found"
echo ""

# 8. Running Services Summary
echo "[8] Running Services Summary"
echo "---"
systemctl list-units --type=service --state=running --no-pager 2>/dev/null | grep -E "(httpd|mariadb|redis|celery|python)" || echo "No matching services found"
echo ""

# 9. Disk & Inodes
echo "[9] Disk Usage"
echo "---"
df -h /
echo ""

# 10. System Load & Process Count
echo "[10] System Load"
echo "---"
uptime
echo ""
ps aux | wc -l
echo "  Total processes"
echo ""

echo "=================================================================================="
echo "Audit complete. Save this output for Phase 2 analysis."
echo "================================================================================="
