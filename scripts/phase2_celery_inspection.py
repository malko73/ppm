#!/usr/bin/env python3
"""
PPM Issue #2: Phase 2 — PDF & Celery failure-path inspection

VPS上で実行し、以下を確認する:
1. PDF生成タスクの呼び出し箇所と実装パターン
2. Celeryタスクの定義・キューイング・フォールバック処理
3. CELERY_TASK_ALWAYS_EAGER等の危険な設定の有無
4. Celery broker unavailable時の挙動

Usage: python3 phase2_celery_inspection.py [--project-root /path/to/ppm]
"""

import os
import sys
import re
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional

class CeleryInspector:
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.findings = {
            "pdf_task_callsites": [],
            "delay_apply_async_usage": [],
            "celery_always_eager": [],
            "fallback_mechanisms": [],
            "error_handling": [],
            "broker_unavailable_handling": [],
        }
    
    def search_files(self, pattern: str, filetypes: Optional[List[str]] = None) -> List[Tuple[Path, List[Tuple[int, str]]]]:
        """Search for pattern in project files."""
        if filetypes is None:
            filetypes = [".py", ".html", ".txt"]
        
        results = []
        regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        
        for fpath in self.project_root.rglob("*"):
            if fpath.is_file() and fpath.suffix in filetypes:
                # Skip venv, migrations, __pycache__
                if any(x in fpath.parts for x in [".venv", "venv", "migrations", "__pycache__"]):
                    continue
                
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    matches = []
                    for i, line in enumerate(content.split("\n"), 1):
                        if regex.search(line):
                            matches.append((i, line.strip()))
                    
                    if matches:
                        results.append((fpath, matches))
                except Exception as e:
                    print(f"Warning: Could not read {fpath}: {e}", file=sys.stderr)
        
        return results
    
    def find_pdf_generation(self):
        """Find PDF generation task definitions and callsites."""
        print("\n[Phase 2-1] PDF Generation Callsites")
        print("-" * 80)
        
        patterns = [
            ("generate_pdf", "PDF generation function/method"),
            ("render_pdf", "PDF rendering function"),
            ("celery.*task.*pdf", "Celery task decorator for PDF"),
            ("@task", "Celery @task decorator"),
            ("@app\\.task", "Celery @app.task decorator"),
        ]
        
        for pattern, desc in patterns:
            results = self.search_files(pattern)
            if results:
                print(f"\n✓ {desc} (pattern: {pattern})")
                for fpath, matches in results:
                    print(f"  File: {fpath.relative_to(self.project_root)}")
                    for line_no, line in matches[:3]:  # Show first 3 matches
                        print(f"    L{line_no}: {line[:100]}")
                    if len(matches) > 3:
                        print(f"    ... and {len(matches) - 3} more")
                    self.findings["pdf_task_callsites"].append({
                        "file": str(fpath.relative_to(self.project_root)),
                        "matches": len(matches),
                    })
    
    def find_task_queueing(self):
        """Find .delay() and apply_async() usage."""
        print("\n[Phase 2-2] Task Queueing Patterns")
        print("-" * 80)
        
        patterns = [
            (r"\.delay\s*\(", ".delay() calls"),
            (r"\.apply_async\s*\(", ".apply_async() calls"),
            (r"\.s\s*\(", ".s() (signature) calls"),
            (r"\.chain\s*\(", ".chain() (Celery chain)"),
        ]
        
        for pattern, desc in patterns:
            results = self.search_files(pattern)
            if results:
                print(f"\n✓ {desc}")
                for fpath, matches in results:
                    print(f"  File: {fpath.relative_to(self.project_root)}")
                    for line_no, line in matches[:2]:
                        print(f"    L{line_no}: {line[:100]}")
                    if len(matches) > 2:
                        print(f"    ... and {len(matches) - 2} more")
                    self.findings["delay_apply_async_usage"].append({
                        "file": str(fpath.relative_to(self.project_root)),
                        "pattern": desc,
                        "count": len(matches),
                    })
    
    def find_always_eager_config(self):
        """Check for CELERY_TASK_ALWAYS_EAGER and similar danger configs."""
        print("\n[Phase 2-3] Dangerous Celery Configurations")
        print("-" * 80)
        
        patterns = [
            (r"CELERY_TASK_ALWAYS_EAGER", "CELERY_TASK_ALWAYS_EAGER (DANGER!)"),
            (r"CELERY_ALWAYS_EAGER", "CELERY_ALWAYS_EAGER (legacy)"),
            (r"CELERY_EAGER_PROPAGATES_EXCEPTIONS", "CELERY_EAGER_PROPAGATES_EXCEPTIONS"),
            (r"CELERY_TASK_EAGER_PROPAGATES", "CELERY_TASK_EAGER_PROPAGATES"),
        ]
        
        found_danger = False
        for pattern, desc in patterns:
            results = self.search_files(pattern)
            if results:
                found_danger = True
                print(f"\n⚠ FOUND: {desc}")
                for fpath, matches in results:
                    print(f"  File: {fpath.relative_to(self.project_root)}")
                    for line_no, line in matches:
                        # Check if it's True/enabled
                        if any(x in line.upper() for x in ["TRUE", "= TRUE", "= 1", "YES"]):
                            print(f"    L{line_no}: {line} ❌ ENABLED")
                        else:
                            print(f"    L{line_no}: {line} (value needs verification)")
                    self.findings["celery_always_eager"].append({
                        "file": str(fpath.relative_to(self.project_root)),
                        "pattern": desc,
                        "matches": len(matches),
                    })
        
        if not found_danger:
            print("\n✓ No CELERY_TASK_ALWAYS_EAGER or similar danger patterns found")
    
    def find_fallback_mechanisms(self):
        """Search for synchronous fallback when Celery is unavailable."""
        print("\n[Phase 2-4] Synchronous Fallback Mechanisms")
        print("-" * 80)
        
        patterns = [
            (r"try.*\.delay|try.*apply_async", "try/except around task queueing"),
            (r"except.*Celery|except.*celery|except.*broker|except.*Connection", "Celery exception handling"),
            (r"if.*celery.*available|if.*broker.*available", "Celery availability check"),
            (r"CELERY_BROKER_URL.*None|broker.*disabled", "Broker disable check"),
        ]
        
        found_fallback = False
        for pattern, desc in patterns:
            results = self.search_files(pattern)
            if results:
                found_fallback = True
                print(f"\n✓ {desc}")
                for fpath, matches in results:
                    print(f"  File: {fpath.relative_to(self.project_root)}")
                    for line_no, line in matches[:2]:
                        print(f"    L{line_no}: {line[:100]}")
                self.findings["fallback_mechanisms"].append({
                    "file": str(fpath.relative_to(self.project_root)),
                    "pattern": desc,
                })
        
        if not found_fallback:
            print("\n⚠ No obvious fallback mechanisms found!")
            print("  Risk: Celery broker unavailable → task queueing fails → PDF request hangs or crashes")
    
    def find_error_handling(self):
        """Check for explicit error handling in PDF generation."""
        print("\n[Phase 2-5] Error Handling in PDF Context")
        print("-" * 80)
        
        results = self.search_files(r"(?:generate|render).*pdf.*\n.*except|except.*pdf|pdf.*except", filetypes=[".py"])
        
        if results:
            print("\n✓ Found exception handling in PDF context")
            for fpath, matches in results:
                print(f"  File: {fpath.relative_to(self.project_root)}")
                for line_no, line in matches[:3]:
                    print(f"    L{line_no}: {line[:100]}")
        else:
            print("\n⚠ No explicit exception handling around PDF tasks found")
            print("  Risk: Celery task failure → no error recovery path")
    
    def check_settings_files(self):
        """Inspect settings files for critical config."""
        print("\n[Phase 2-6] Celery Settings Files")
        print("-" * 80)
        
        settings_files = [
            "config/settings.py",
            "config/settings_base.py",
            "config/celery.py",
            "apps/celery.py",
            ".env",
            ".env.template",
        ]
        
        for sfile in settings_files:
            fpath = self.project_root / sfile
            if fpath.exists():
                print(f"\n✓ Found: {fpath.relative_to(self.project_root)}")
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    lines = content.split("\n")
                    
                    # Look for CELERY_* configs
                    celery_lines = [
                        (i+1, line) for i, line in enumerate(lines)
                        if "CELERY" in line.upper() or "BROKER" in line.upper() or "REDIS" in line.upper()
                    ]
                    
                    if celery_lines:
                        print(f"  Celery-related config (first 5):")
                        for line_no, line in celery_lines[:5]:
                            # Redact secrets
                            line_safe = re.sub(r"password.*", "password=***", line, flags=re.IGNORECASE)
                            line_safe = re.sub(r"key.*", "key=***", line_safe, flags=re.IGNORECASE)
                            print(f"    L{line_no}: {line_safe[:100]}")
                    else:
                        print(f"  No Celery config found in this file")
                except Exception as e:
                    print(f"  Error reading: {e}")
    
    def generate_report(self):
        """Generate final report."""
        print("\n" + "="*80)
        print("SUMMARY & RECOMMENDATIONS")
        print("="*80)
        
        print("\n📋 Findings:")
        print(f"  - PDF task callsites: {len(self.findings['pdf_task_callsites'])} file(s)")
        print(f"  - Task queueing patterns: {len(self.findings['delay_apply_async_usage'])} pattern(s)")
        print(f"  - Danger configs: {len(self.findings['celery_always_eager'])} issue(s)")
        print(f"  - Fallback mechanisms: {len(self.findings['fallback_mechanisms'])} found")
        
        print("\n🎯 Critical checks for Issue #2:")
        print("  [ ] Verify: Celery unavailable → PDF task fails with 503 (not sync fallback)")
        print("  [ ] Verify: No CELERY_TASK_ALWAYS_EAGER = True in production config")
        print("  [ ] Verify: systemctl celery-ppm is enabled and auto-starts")
        print("  [ ] Verify: Task queueing has explicit error handling")
        print("  [ ] Verify: PDF generation never runs synchronously on main thread")
        
        print("\n📄 Next Step:")
        print("  1. Export findings to JSON for Issue comment")
        print("  2. Run actual Celery failure test on VPS")
        print("  3. Compare findings with P0/P1 requirements in Issue #2")
        
        return self.findings

def main():
    import argparse
    parser = argparse.ArgumentParser(description="PPM Phase 2: Celery Inspection")
    parser.add_argument("--project-root", default=".", help="PPM project root directory")
    parser.add_argument("--json", action="store_true", help="Output findings as JSON")
    
    args = parser.parse_args()
    
    inspector = CeleryInspector(project_root=args.project_root)
    
    print("Starting Phase 2 Inspection...")
    inspector.find_pdf_generation()
    inspector.find_task_queueing()
    inspector.find_always_eager_config()
    inspector.find_fallback_mechanisms()
    inspector.find_error_handling()
    inspector.check_settings_files()
    findings = inspector.generate_report()
    
    if args.json:
        print("\n" + "="*80)
        print("JSON Output:")
        print("="*80)
        print(json.dumps(findings, indent=2))

if __name__ == "__main__":
    main()
