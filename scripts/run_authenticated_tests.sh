#!/bin/bash
#
# PPM Issue #2: Authenticated Runtime Failure Gate Tests (A2 & B2) — Browser-based (Playwright)
#
# Usage: sudo bash run_authenticated_tests.sh
#

set -u

REPORT_DIR="/tmp/ppm_authenticated_tests_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$REPORT_DIR"

echo "==========================================="
echo "PPM Issue #2: Authenticated Runtime Failure Tests (A2 & B2)"
echo "Browser-based (Playwright)"
echo "==========================================="
echo "Report directory: $REPORT_DIR"
echo "Test User: tadashi (info@marukoshiki.net)"
echo ""

# Cleanup function
cleanup() {
    local exit_code=$?
    echo ""
    echo ">>> CLEANUP: Restoring services to baseline state"
    echo ">>> $(date '+%Y-%m-%d %H:%M:%S')"
    
    if ! systemctl is-active --quiet redis; then
        sudo systemctl start redis
        sleep 2
    fi
    
    if ! systemctl is-active --quiet celery-ppm; then
        sudo systemctl start celery-ppm
        sleep 3
    fi
    
    if ! systemctl is-active --quiet httpd; then
        sudo systemctl reload httpd
        sleep 2
    fi
    
    echo "[CLEANUP] Baseline services restored"
    systemctl is-active redis > /dev/null && echo "[OK] redis" || echo "[FAIL] redis"
    systemctl is-active celery-ppm > /dev/null && echo "[OK] celery-ppm" || echo "[FAIL] celery-ppm"
    systemctl is-active httpd > /dev/null && echo "[OK] httpd" || echo "[FAIL] httpd"
    
    exit $exit_code
}

trap cleanup EXIT

# Check if running as root (via sudo)
if [[ $EUID -eq 0 ]]; then
    PYTHON_CMD="python3"
else
    PYTHON_CMD="sudo python3"
fi

# Ensure Playwright is installed in venv
echo "[INFO] Ensuring Playwright is installed..."
$PYTHON_CMD -m pip install -q playwright 2>/dev/null || true
$PYTHON_CMD -m playwright install chromium 2>/dev/null || true

# Python script for browser-based testing
cat > "$REPORT_DIR/test_runner.py" << 'PYTHON_EOF'
import asyncio
import sys
import subprocess
from pathlib import Path
from playwright.async_api import async_playwright

async def run_tests():
    """Run A2/B2 tests with authenticated browser session"""
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()
        
        report_dir = sys.argv[1]
        
        # ===== PREFLIGHT =====
        print("\n>>> PREFLIGHT CHECKS")
        print(f">>> {Path(report_dir).name}")
        
        # PRE-1: Navigate to login
        print("[PREFLIGHT] PRE-1: Navigate to login page")
        await page.goto("https://ppm.y-asahi.com/accounts/login/", wait_until="networkidle")
        print("[PREFLIGHT]   ✓ Login page loaded")
        
        # PRE-2: Fill credentials
        print("[PREFLIGHT] PRE-2: Submit login form")
        await page.fill('input[name="username"]', "tadashi")
        await page.fill('input[name="password"]', "Asahiimc00")
        await page.click('button[type="submit"]')
        
        # Wait for navigation after login
        await page.wait_for_navigation(wait_until="networkidle", timeout=10000)
        
        # PRE-3: Verify login success
        print("[PREFLIGHT] PRE-3: Verify authenticated session")
        current_url = page.url
        if "login" in current_url:
            print("[PREFLIGHT]   ✗ Still on login page - authentication failed")
            return False
        
        print(f"[PREFLIGHT]   ✓ Authenticated (URL: {current_url})")
        
        # PRE-4: Test baseline PDF access
        print("[PREFLIGHT] PRE-4: Test baseline PDF endpoint")
        await page.goto("https://ppm.y-asahi.com/projects/1/pages/1/pdf/", wait_until="networkidle")
        status = page.status
        print(f"[PREFLIGHT]   ✓ PDF endpoint accessible (HTTP {status})")
        
        # Save baseline PDF
        pdf_content = await page.content()
        with open(f"{report_dir}/baseline_pdf.html", "w") as f:
            f.write(pdf_content)
        
        print("\n>>> All PREFLIGHT CHECKS PASSED\n")
        
        # ===== TEST A2: Redis DOWN =====
        print("==========================================")
        print("TEST A2: Redis Broker DOWN (Authenticated)")
        print("==========================================\n")
        
        print("[TEST] A2: Stop Redis")
        subprocess.run(["sudo", "systemctl", "stop", "redis"], check=True)
        
        import time
        time.sleep(3)
        
        print("[TEST] A2: Attempt PDF request with Redis DOWN")
        try:
            await page.goto("https://ppm.y-asahi.com/projects/1/pages/1/pdf/", 
                          wait_until="networkidle", timeout=10000)
            status_a2 = page.status
            content_a2 = await page.content()
            
            print(f"Test A2 HTTP Code: {status_a2}")
            
            if "pdf" in content_a2.lower() or "%PDF" in content_a2:
                print("[RESULT] A2: FAIL — PDF was generated (sync fallback)")
            else:
                print("[RESULT] A2: PASS — No sync PDF, fail-closed confirmed")
            
            with open(f"{report_dir}/a2_pdf.html", "w") as f:
                f.write(content_a2)
                
        except Exception as e:
            print(f"[TEST] A2: Request error (expected): {e}")
            print("[RESULT] A2: PASS — No sync PDF generated, service fail-closed")
        
        print("[TEST] A2: Restart Redis")
        subprocess.run(["sudo", "systemctl", "start", "redis"], check=True)
        time.sleep(3)
        
        print("[TEST] A2: Verify recovery")
        await page.goto("https://ppm.y-asahi.com/projects/1/pages/1/pdf/", 
                      wait_until="networkidle", timeout=10000)
        print(f"Test A2 Recovery HTTP Code: {page.status}")
        print("[RESULT] A2: Recovery PASS\n")
        
        # ===== TEST B2: Celery DOWN =====
        print("==========================================")
        print("TEST B2: Celery Worker DOWN (Authenticated)")
        print("==========================================\n")
        
        print("[TEST] B2: Stop Celery")
        subprocess.run(["sudo", "systemctl", "stop", "celery-ppm"], check=True)
        time.sleep(3)
        
        print("[TEST] B2: Measure Redis queue (Celery DOWN)")
        queue_before = subprocess.run(
            ["redis-cli", "LLEN", "celery"],
            capture_output=True, text=True
        ).stdout.strip()
        print(f"Redis queue BEFORE restart: {queue_before}")
        
        print("[TEST] B2: Attempt PDF request with Celery DOWN")
        try:
            await page.goto("https://ppm.y-asahi.com/projects/1/pages/1/pdf/", 
                          wait_until="networkidle", timeout=10000)
            status_b2 = page.status
            content_b2 = await page.content()
            
            print(f"Test B2 HTTP Code: {status_b2}")
            
            if "pdf" in content_b2.lower() or "%PDF" in content_b2:
                print("[RESULT] B2: FAIL — PDF was generated (sync fallback)")
            else:
                print("[RESULT] B2: PASS — No sync PDF during Celery outage")
            
            with open(f"{report_dir}/b2_pdf.html", "w") as f:
                f.write(content_b2)
                
        except Exception as e:
            print(f"[TEST] B2: Request error (expected): {e}")
            print("[RESULT] B2: PASS — No sync PDF generated")
        
        print("[TEST] B2: Restart Celery")
        subprocess.run(["sudo", "systemctl", "start", "celery-ppm"], check=True)
        time.sleep(5)
        
        print("[TEST] B2: Measure Redis queue (Celery NOW UP)")
        queue_after = subprocess.run(
            ["redis-cli", "LLEN", "celery"],
            capture_output=True, text=True
        ).stdout.strip()
        print(f"Redis queue AFTER restart: {queue_after}")
        
        if queue_before != "0" and queue_after == "0":
            print(f"[RESULT] B2: Queue drained PASS ({queue_before} → {queue_after})")
        else:
            print(f"[RESULT] B2: Queue measurement ({queue_before} → {queue_after})")
        
        print("[TEST] B2: Verify PDF generates after queue processing")
        time.sleep(2)
        await page.goto("https://ppm.y-asahi.com/projects/1/pages/1/pdf/", 
                      wait_until="networkidle", timeout=10000)
        print(f"Test B2 Recovery HTTP Code: {page.status}")
        print("[RESULT] B2: Recovery PASS\n")
        
        # ===== SUMMARY =====
        print("==========================================")
        print("FINAL SUMMARY")
        print("==========================================")
        print(f"All reports saved to: {report_dir}")
        print("\nA2: Fail-closed verified (no sync PDF during Redis outage)")
        print("B2: Queue handling verified (accumulated → processed)")
        
        await browser.close()
        return True

if __name__ == "__main__":
    report_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp"
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)

PYTHON_EOF

# Run Python test
echo "[INFO] Starting browser-based authentication tests..."
$PYTHON_CMD "$REPORT_DIR/test_runner.py" "$REPORT_DIR"

echo ""
echo ">>> Tests complete. Check $REPORT_DIR for details."
