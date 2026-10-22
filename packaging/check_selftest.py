"""Read the frozen app's self-test report, print a summary, exit 0 only if every check passed.

usage: python packaging/check_selftest.py selftest.json
(Done in Python rather than PowerShell so the verdict is identical on PowerShell 5.1, 7 and CI.)
"""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    print(f"No self-test report at {path} - the app didn't start.")
    sys.exit(1)
try:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
except ValueError as e:
    print(f"Self-test report is unreadable ({e}). Raw contents:\n{path.read_text(errors='replace')}")
    sys.exit(1)

results = data.get("results", {})
bad = {k: v for k, v in results.items() if v != "ok"}
for name, value in results.items():
    print(f"  {name:<12} {'ok' if value == 'ok' else 'FAILED'}")
print(f"  python {data.get('python')} | office: {data.get('office_backend')} | svg tracer: {data.get('svg_tracer')}"
      f" | updater: {data.get('updater')}")
problems = []
if data.get("crash"):
    problems.append("crash:\n" + data["crash"])
for name, value in bad.items():
    problems.append(f"{name}:\n{value}")
if len(results) < 10:
    problems.append(f"only {len(results)} checks ran (expected 15+) - last step: {data.get('current_step')}")
tracer = data.get("svg_tracer")
if tracer and "fallback" in tracer:
    print("\n  Note: SVG tracing used the built-in OpenCV tracer because the vtracer library failed on this\n"
          "  machine. Conversions still work; building with Python 3.12 usually brings vtracer back.")
if problems:
    print("\nSELF-TEST FAILED\n" + "\n\n".join(problems))
    sys.exit(1)
print("Self-test passed.")
