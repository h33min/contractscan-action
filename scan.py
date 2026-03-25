#!/usr/bin/env python3
"""
ContractScan GitHub Action — scan.py

Scans all Solidity files matching the configured glob pattern by calling the
ContractScan /ci/scan API endpoint. Sets GitHub Actions step outputs and
writes a Markdown summary to $GITHUB_STEP_SUMMARY.

Exit code 0 → all files passed threshold (or no .sol files found)
Exit code 1 → one or more files failed threshold / API error
"""

import os
import sys
import json
import glob
import fnmatch
import pathlib
import textwrap

try:
    import httpx
except ImportError:
    print("::error::httpx not available. Ensure the 'Install dependencies' step ran.")
    sys.exit(1)


# ── Config from env ────────────────────────────────────────────────────────────

API_KEY = os.environ.get("CONTRACTSCAN_API_KEY", "")
API_URL = os.environ.get("CONTRACTSCAN_API_URL", "https://contractscan.io").rstrip("/")
GLOB_PATTERN = os.environ.get("CONTRACTSCAN_PATH", "**/*.sol")
FAIL_ON = os.environ.get("CONTRACTSCAN_FAIL_ON", "Critical").strip().capitalize()
REPORT_FORMAT = os.environ.get("CONTRACTSCAN_REPORT_FORMAT", "markdown")
MAX_FILES = int(os.environ.get("CONTRACTSCAN_MAX_FILES", "20"))

GITHUB_STEP_SUMMARY = os.environ.get("GITHUB_STEP_SUMMARY", "")
GITHUB_OUTPUT = os.environ.get("GITHUB_OUTPUT", "")
GITHUB_WORKSPACE = os.environ.get("GITHUB_WORKSPACE", ".")


def set_output(name: str, value: str):
    if GITHUB_OUTPUT:
        with open(GITHUB_OUTPUT, "a") as f:
            f.write(f"{name}={value}\n")
    else:
        print(f"::set-output name={name}::{value}")


def write_summary(content: str):
    if GITHUB_STEP_SUMMARY:
        with open(GITHUB_STEP_SUMMARY, "a") as f:
            f.write(content + "\n")
    else:
        print(content)


def find_sol_files(workspace: str, pattern: str, max_files: int) -> list[str]:
    """Find all .sol files matching the glob pattern."""
    base = pathlib.Path(workspace)
    matches = []
    for p in base.rglob("*.sol"):
        rel = str(p.relative_to(base))
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(p.name, pattern):
            matches.append(str(p))
    # Also support direct glob
    if not matches:
        matches = glob.glob(os.path.join(workspace, pattern), recursive=True)
    return sorted(set(matches))[:max_files]


def scan_file(filepath: str) -> dict:
    """POST a single .sol file to /ci/scan and return the JSON response."""
    with open(filepath, "rb") as f:
        content = f.read()

    filename = os.path.basename(filepath)
    resp = httpx.post(
        f"{API_URL}/ci/scan",
        files={"file": (filename, content, "text/plain")},
        headers={
            "X-Api-Key": API_KEY,
            "X-Fail-On": FAIL_ON,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def severity_emoji(sev: str) -> str:
    return {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🔵", "Info": "⚪"}.get(sev, "⚫")


def build_markdown_summary(results: list[dict]) -> str:
    lines = [
        "## 🔍 ContractScan Results",
        "",
    ]

    total_findings = sum(r.get("findings_count", 0) for r in results)
    total_critical = sum(r.get("severity_summary", {}).get("Critical", 0) for r in results)
    all_passed = all(r.get("passed", True) for r in results)

    status_icon = "✅" if all_passed else "❌"
    lines += [
        f"**Status**: {status_icon} {'PASSED' if all_passed else 'FAILED'}  ",
        f"**Files scanned**: {len(results)}  ",
        f"**Total findings**: {total_findings}  ",
        f"**Critical**: {total_critical}  ",
        f"**Fail threshold**: {FAIL_ON}",
        "",
        "---",
        "",
    ]

    for r in results:
        filename = r.get("contract_name", "unknown")
        passed = r.get("passed", True)
        icon = "✅" if passed else "❌"
        sev_summary = r.get("severity_summary", {})
        sev_str = " · ".join(
            f"{severity_emoji(s)} {s}: {n}"
            for s, n in sev_summary.items()
            if n > 0
        ) or "No findings"

        lines += [
            f"### {icon} `{filename}`",
            "",
            f"**Findings**: {r.get('findings_count', 0)} — {sev_str}",
        ]

        if r.get("fail_reason"):
            lines.append(f"**Fail reason**: {r['fail_reason']}")

        findings = r.get("findings", [])
        if findings:
            lines += ["", "<details><summary>View findings</summary>", ""]
            lines.append("| Severity | Title | SWC |")
            lines.append("|----------|-------|-----|")
            for f in findings:
                swc = f.get("swc_id") or "—"
                lines.append(f"| {severity_emoji(f['severity'])} {f['severity']} | {f['title']} | {swc} |")
            lines += ["", "</details>"]

        lines.append("")

    lines += [
        "---",
        "",
        "> ⚠️ ContractScan detects known static vulnerability patterns via Slither.",
        "> It does **not** replace a professional security audit.",
        "",
    ]

    return "\n".join(lines)


def main():
    if not API_KEY:
        print("::error::CONTRACTSCAN_API_KEY is not set. Add it as a repository secret and pass via api-key input.")
        sys.exit(1)

    sol_files = find_sol_files(GITHUB_WORKSPACE, GLOB_PATTERN, MAX_FILES)

    if not sol_files:
        write_summary("## 🔍 ContractScan\n\nNo Solidity files found matching `" + GLOB_PATTERN + "`. Skipping scan.")
        set_output("findings-count", "0")
        set_output("critical-count", "0")
        set_output("passed", "true")
        print(f"No .sol files found matching '{GLOB_PATTERN}'. Nothing to scan.")
        sys.exit(0)

    print(f"ContractScan: found {len(sol_files)} file(s) to scan (threshold: {FAIL_ON})")

    results = []
    any_error = False

    for filepath in sol_files:
        rel = os.path.relpath(filepath, GITHUB_WORKSPACE)
        print(f"  Scanning {rel} ...", end=" ", flush=True)
        try:
            result = scan_file(filepath)
            result["_filepath"] = rel
            results.append(result)
            status = "PASSED" if result.get("passed") else "FAILED"
            print(status)
        except httpx.HTTPStatusError as e:
            print(f"ERROR ({e.response.status_code})")
            print(f"::error file={rel}::ContractScan API error {e.response.status_code}: {e.response.text[:200]}")
            any_error = True
        except Exception as e:
            print(f"ERROR")
            print(f"::error file={rel}::ContractScan scan failed: {e}")
            any_error = True

    total_findings = sum(r.get("findings_count", 0) for r in results)
    total_critical = sum(r.get("severity_summary", {}).get("Critical", 0) for r in results)
    all_passed = all(r.get("passed", True) for r in results) and not any_error

    set_output("findings-count", str(total_findings))
    set_output("critical-count", str(total_critical))
    set_output("passed", str(all_passed).lower())

    if REPORT_FORMAT == "json":
        write_summary("```json\n" + json.dumps(results, indent=2) + "\n```")
    else:
        write_summary(build_markdown_summary(results))

    failed_files = [r for r in results if not r.get("passed", True)]
    if failed_files:
        print(f"\n❌ ContractScan FAILED: {len(failed_files)} file(s) exceeded {FAIL_ON} threshold.")
        for r in failed_files:
            name = r.get("_filepath", r.get("contract_name", "?"))
            print(f"   - {name}: {r.get('fail_reason', 'threshold exceeded')}")
        sys.exit(1)

    if any_error:
        print("\n❌ ContractScan encountered errors during scanning.")
        sys.exit(1)

    print(f"\n✅ ContractScan PASSED: {len(results)} file(s) scanned, {total_findings} finding(s), none exceeded {FAIL_ON} threshold.")
    sys.exit(0)


if __name__ == "__main__":
    main()
