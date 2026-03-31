#!/usr/bin/env python3
"""
ContractScan GitHub Action — scan.py

Bundles all Solidity files (and auto-detected dependency directories) into a
ZIP archive, then sends a single request to the ContractScan /ci/scan endpoint.
This ensures import resolution works correctly on the server side.

Sets GitHub Actions step outputs and writes a Markdown summary to
$GITHUB_STEP_SUMMARY.

Exit code 0 → scan passed threshold (or no .sol files found)
Exit code 1 → scan failed threshold / API error
"""

import io
import os
import sys
import json
import glob
import fnmatch
import pathlib
import zipfile

try:
    import httpx
except ImportError:
    print("::error::httpx not available. Ensure the 'Install dependencies' step ran.")
    sys.exit(1)


# ── Config from env ────────────────────────────────────────────────────────────

API_KEY = os.environ.get("CONTRACTSCAN_API_KEY", "")
API_URL = os.environ.get("CONTRACTSCAN_API_URL", "https://contract-scanner.raccoonworld.xyz").rstrip("/")
GLOB_PATTERN = os.environ.get("CONTRACTSCAN_PATH", "**/*.sol")
FAIL_ON = os.environ.get("CONTRACTSCAN_FAIL_ON", "Critical").strip().capitalize()
REPORT_FORMAT = os.environ.get("CONTRACTSCAN_REPORT_FORMAT", "markdown")
MAX_FILES = int(os.environ.get("CONTRACTSCAN_MAX_FILES", "300"))

GITHUB_STEP_SUMMARY = os.environ.get("GITHUB_STEP_SUMMARY", "")
GITHUB_OUTPUT = os.environ.get("GITHUB_OUTPUT", "")
GITHUB_WORKSPACE = os.environ.get("GITHUB_WORKSPACE", ".")

# Dependency directories that may contain imported .sol files.
# Auto-detected if present in the project root.
DEP_DIRS = [
    "node_modules",
    "lib",
    "dependencies",
]

# Max ZIP size in bytes (5 MB, matches server limit)
MAX_ZIP_BYTES = 5 * 1024 * 1024


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
    """Find user .sol files matching the glob pattern (excludes dependency dirs)."""
    base = pathlib.Path(workspace)
    matches = []
    for p in base.rglob("*.sol"):
        rel = str(p.relative_to(base))
        # Skip files inside dependency directories
        parts = pathlib.PurePosixPath(rel).parts
        if parts and parts[0] in DEP_DIRS:
            continue
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(p.name, pattern):
            matches.append(str(p))
    if not matches:
        matches = glob.glob(os.path.join(workspace, pattern), recursive=True)
        matches = [
            m for m in matches
            if not any(
                pathlib.PurePosixPath(os.path.relpath(m, workspace)).parts[0] == d
                for d in DEP_DIRS
            )
        ]
    return sorted(set(matches))[:max_files]


def find_dep_sol_files(workspace: str) -> list[str]:
    """Find .sol files inside auto-detected dependency directories."""
    base = pathlib.Path(workspace)
    dep_files = []
    for dep_dir in DEP_DIRS:
        dep_path = base / dep_dir
        if dep_path.is_dir():
            for p in dep_path.rglob("*.sol"):
                dep_files.append(str(p))
    return sorted(set(dep_files))


def build_project_zip(workspace: str, sol_files: list[str], dep_files: list[str]) -> bytes:
    """Bundle user .sol files and dependency .sol files into an in-memory ZIP."""
    base = pathlib.Path(workspace)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        added = set()
        for filepath in sol_files + dep_files:
            rel = os.path.relpath(filepath, workspace)
            if rel in added:
                continue
            added.add(rel)
            zf.write(filepath, rel)

        # Include remappings.txt or foundry.toml if present (helps server resolve imports)
        for config_file in ["remappings.txt", "foundry.toml", "hardhat.config.js", "hardhat.config.ts"]:
            cfg_path = base / config_file
            if cfg_path.is_file():
                rel = config_file
                if rel not in added:
                    added.add(rel)
                    zf.write(str(cfg_path), rel)

    return buf.getvalue()


def scan_project_zip(zip_bytes: bytes, project_name: str) -> dict:
    """POST a project ZIP to /ci/scan and return the JSON response."""
    headers = {"X-Fail-On": FAIL_ON}
    if API_KEY:
        headers["X-Api-Key"] = API_KEY
    resp = httpx.post(
        f"{API_URL}/ci/scan",
        files={"file": (f"{project_name}.zip", zip_bytes, "application/zip")},
        headers=headers,
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()


def severity_emoji(sev: str) -> str:
    return {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🔵", "Info": "⚪"}.get(sev, "⚫")


def build_markdown_summary(result: dict, sol_count: int, dep_count: int) -> str:
    lines = [
        "## ContractScan Results",
        "",
    ]

    findings_count = result.get("findings_count", 0)
    sev_summary = result.get("severity_summary", {})
    total_critical = sev_summary.get("Critical", 0)
    passed = result.get("passed", True)

    status_icon = "PASSED" if passed else "FAILED"
    lines += [
        f"**Status**: {status_icon}  ",
        f"**Source files**: {sol_count} (+ {dep_count} dependency files auto-detected)  ",
        f"**Total findings**: {findings_count}  ",
        f"**Critical**: {total_critical}  ",
        f"**Fail threshold**: {FAIL_ON}",
        "",
        "---",
        "",
    ]

    contract_name = result.get("contract_name", "project")
    sev_str = " / ".join(
        f"{severity_emoji(s)} {s}: {n}"
        for s, n in sev_summary.items()
        if n > 0
    ) or "No findings"

    lines += [
        f"### `{contract_name}`",
        "",
        f"**Findings**: {findings_count} — {sev_str}",
    ]

    if result.get("fail_reason"):
        lines.append(f"**Fail reason**: {result['fail_reason']}")

    findings = result.get("findings", [])
    if findings:
        lines += ["", "<details><summary>View findings</summary>", ""]
        lines.append("| Severity | Title | SWC |")
        lines.append("|----------|-------|-----|")
        for f in findings:
            swc = f.get("swc_id") or "-"
            lines.append(f"| {severity_emoji(f['severity'])} {f['severity']} | {f['title']} | {swc} |")
        lines += ["", "</details>"]

    lines.append("")

    lines += [
        "---",
        "",
        "> ContractScan detects known vulnerability patterns via Slither + Semgrep + AI.",
        "> It does **not** replace a professional security audit.",
        "",
    ]

    return "\n".join(lines)


def main():
    if not API_KEY:
        print("::notice::No API key set — using free tier (3 scans per IP). Set CONTRACTSCAN_API_KEY for unlimited scans.")

    sol_files = find_sol_files(GITHUB_WORKSPACE, GLOB_PATTERN, MAX_FILES)

    if not sol_files:
        write_summary("## ContractScan\n\nNo Solidity files found matching `" + GLOB_PATTERN + "`. Skipping scan.")
        set_output("findings-count", "0")
        set_output("critical-count", "0")
        set_output("passed", "true")
        print(f"No .sol files found matching '{GLOB_PATTERN}'. Nothing to scan.")
        sys.exit(0)

    # Auto-detect dependency .sol files for import resolution
    dep_files = find_dep_sol_files(GITHUB_WORKSPACE)

    print(f"ContractScan: {len(sol_files)} source file(s), {len(dep_files)} dependency file(s) (threshold: {FAIL_ON})")
    for f in sol_files:
        print(f"  src: {os.path.relpath(f, GITHUB_WORKSPACE)}")
    if dep_files:
        dep_dirs_found = set()
        for f in dep_files:
            rel = os.path.relpath(f, GITHUB_WORKSPACE)
            top = pathlib.PurePosixPath(rel).parts[0]
            dep_dirs_found.add(top)
        print(f"  deps: {', '.join(sorted(dep_dirs_found))} ({len(dep_files)} .sol files)")

    # Derive project name from the workspace directory
    project_name = pathlib.Path(GITHUB_WORKSPACE).name or "project"

    # Bundle into ZIP
    print("  Bundling project ZIP ...", end=" ", flush=True)
    zip_bytes = build_project_zip(GITHUB_WORKSPACE, sol_files, dep_files)

    if len(zip_bytes) > MAX_ZIP_BYTES:
        print(f"ERROR")
        print(f"::error::Project ZIP is too large ({len(zip_bytes)} bytes, max {MAX_ZIP_BYTES}). "
              f"Reduce the number of files or exclude large dependency directories.")
        sys.exit(1)

    zip_kb = len(zip_bytes) / 1024
    print(f"done ({zip_kb:.0f} KB)")

    # Send single ZIP request
    print(f"  Scanning project ...", end=" ", flush=True)
    try:
        result = scan_project_zip(zip_bytes, project_name)
        passed = result.get("passed", True)
        print("PASSED" if passed else "FAILED")
    except httpx.HTTPStatusError as e:
        print(f"ERROR ({e.response.status_code})")
        print(f"::error::ContractScan API error {e.response.status_code}: {e.response.text[:300]}")
        set_output("findings-count", "0")
        set_output("critical-count", "0")
        set_output("passed", "false")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR")
        print(f"::error::ContractScan scan failed: {e}")
        set_output("findings-count", "0")
        set_output("critical-count", "0")
        set_output("passed", "false")
        sys.exit(1)

    findings_count = result.get("findings_count", 0)
    sev_summary = result.get("severity_summary", {})
    total_critical = sev_summary.get("Critical", 0)
    passed = result.get("passed", True)

    set_output("findings-count", str(findings_count))
    set_output("critical-count", str(total_critical))
    set_output("passed", str(passed).lower())

    if REPORT_FORMAT == "json":
        write_summary("```json\n" + json.dumps(result, indent=2) + "\n```")
    else:
        write_summary(build_markdown_summary(result, len(sol_files), len(dep_files)))

    if not passed:
        fail_reason = result.get("fail_reason", "threshold exceeded")
        print(f"\nContractScan FAILED: {fail_reason}")
        sys.exit(1)

    print(f"\nContractScan PASSED: {findings_count} finding(s), none exceeded {FAIL_ON} threshold.")
    sys.exit(0)


if __name__ == "__main__":
    main()
