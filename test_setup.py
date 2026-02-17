#!/usr/bin/env python3
"""
Simple environment test for Condor Server UDP Scraper.

Checks:
- Python version
- Required Python package imports
- Windows admin privileges (for packet capture)
- Npcap presence (Windows)
- Basic Scapy readiness and tiny capture test

By default on Windows, this script pauses at the end so a double-clicked
console window does not close immediately.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass


MIN_PYTHON = (3, 9)
REQUIRED_MODULES = [
    "flask",
    "psutil",
    "requests",
    "numpy",
    "scapy",
    "colorama",
    "urllib3",
]


@dataclass
class CheckResult:
    name: str
    status: str  # PASS, WARN, FAIL
    detail: str


def add_result(results: list[CheckResult], name: str, status: str, detail: str) -> None:
    results.append(CheckResult(name=name, status=status, detail=detail))


def check_python_version(results: list[CheckResult]) -> None:
    current = sys.version_info[:3]
    if current >= MIN_PYTHON:
        add_result(results, "Python Version", "PASS", f"{current[0]}.{current[1]}.{current[2]}")
    else:
        add_result(
            results,
            "Python Version",
            "FAIL",
            f"{current[0]}.{current[1]}.{current[2]} (requires {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)",
        )


def check_imports(results: list[CheckResult]) -> None:
    missing: list[str] = []
    for mod in REQUIRED_MODULES:
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)

    if not missing:
        add_result(results, "Python Dependencies", "PASS", "All required modules imported successfully")
    else:
        add_result(
            results,
            "Python Dependencies",
            "FAIL",
            f"Missing or broken modules: {', '.join(missing)}",
        )


def is_windows_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def check_admin(results: list[CheckResult]) -> None:
    if os.name != "nt":
        add_result(results, "Admin Privileges", "WARN", "Non-Windows OS detected; Windows admin check skipped")
        return

    if is_windows_admin():
        add_result(results, "Admin Privileges", "PASS", "Running as Administrator")
    else:
        add_result(
            results,
            "Admin Privileges",
            "WARN",
            "Not running as Administrator (live packet capture may fail)",
        )


def check_npcap(results: list[CheckResult]) -> None:
    if os.name != "nt":
        add_result(results, "Npcap", "WARN", "Non-Windows OS detected; Npcap check skipped")
        return

    found = False
    details: list[str] = []

    # Service check
    try:
        completed = subprocess.run(
            ["sc", "query", "npcap"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if completed.returncode == 0:
            found = True
            details.append("Service 'npcap' found")
        else:
            details.append("Service 'npcap' not found")
    except Exception as exc:
        details.append(f"Service check error: {exc}")

    # Install path check
    candidate_paths = [
        r"C:\Program Files\Npcap",
        r"C:\Windows\System32\Npcap",
    ]
    existing_paths = [p for p in candidate_paths if os.path.exists(p)]
    if existing_paths:
        found = True
        details.append(f"Install path found: {existing_paths[0]}")

    if found:
        add_result(results, "Npcap", "PASS", " | ".join(details))
    else:
        add_result(
            results,
            "Npcap",
            "FAIL",
            "Npcap not detected. Install from https://nmap.org/npcap/",
        )


def check_scapy_capture(results: list[CheckResult]) -> None:
    try:
        from scapy.all import conf, get_if_list, sniff
    except Exception as exc:
        add_result(results, "Scapy Runtime", "FAIL", f"Import failed: {exc}")
        return

    # Interface enumeration
    try:
        interfaces = get_if_list()
        if interfaces:
            add_result(results, "Scapy Interfaces", "PASS", f"{len(interfaces)} interface(s) detected")
        else:
            add_result(results, "Scapy Interfaces", "WARN", "No interfaces returned by Scapy")
    except Exception as exc:
        add_result(results, "Scapy Interfaces", "WARN", f"Failed to enumerate interfaces: {exc}")

    # Tiny capture smoke test
    try:
        sniff(timeout=1, count=1, store=False)
        pcap_mode = getattr(conf, "use_pcap", None)
        add_result(results, "Scapy Capture Test", "PASS", f"Capture initialized (use_pcap={pcap_mode})")
    except PermissionError:
        add_result(results, "Scapy Capture Test", "WARN", "Permission error (try running as Administrator)")
    except Exception as exc:
        add_result(results, "Scapy Capture Test", "FAIL", f"Capture failed: {exc}")


def print_report(results: list[CheckResult]) -> int:
    print("=" * 72)
    print("Condor UDP Scraper - Environment Test")
    print("=" * 72)
    for r in results:
        print(f"[{r.status:<4}] {r.name:<22} {r.detail}")
    print("-" * 72)

    fail_count = sum(1 for r in results if r.status == "FAIL")
    warn_count = sum(1 for r in results if r.status == "WARN")

    if fail_count == 0 and warn_count == 0:
        print("Overall: PASS")
    elif fail_count == 0:
        print(f"Overall: PASS with warnings ({warn_count} warning(s))")
    else:
        print(f"Overall: FAIL ({fail_count} failure(s), {warn_count} warning(s))")

    print("\nIf dependencies are missing, run:")
    print("  pip install -r requirements.txt")
    if os.name == "nt":
        print("If Npcap is missing, install:")
        print("  https://nmap.org/npcap/")

    return 0 if fail_count == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local setup checks for this project.")
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Do not pause at the end (useful in terminals that stay open).",
    )
    args = parser.parse_args()

    results: list[CheckResult] = []
    check_python_version(results)
    check_imports(results)
    check_admin(results)
    check_npcap(results)
    check_scapy_capture(results)

    code = print_report(results)

    if os.name == "nt" and not args.no_pause:
        try:
            input("\nPress Enter to close...")
        except EOFError:
            pass

    return code


if __name__ == "__main__":
    raise SystemExit(main())

