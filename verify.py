"""Replay the public offline evidence and return a JSON verdict. Python 3.9+."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def replay(script, expected_file):
    result = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT,
                            check=True, capture_output=True, text=True)
    actual = json.loads(result.stdout)
    if actual != json.loads((ROOT / expected_file).read_text()):
        raise ValueError(f"{script} disagrees with {expected_file}")
    return actual


def main():
    window = replay("window.py", "window-result.json")
    receipts = replay("check-receipts.py", "three-receipts.json")
    subprocess.run([sys.executable, "test_receipts.py"], cwd=ROOT,
                   check=True, capture_output=True, text=True)
    print(json.dumps({
        "status": "PASS",
        "blocks": window["blocks"],
        "non_coinbase": window["non_coinbase"],
        "original_fee_mismatches": window["original_discrepancies"],
        "corrected_match": sum(row["corrected_zat"] == row["reference_zat"]
                               for row in window["transactions"] if row["status"] != "COINBASE"),
        "independent_explorer_receipts": len(receipts),
        "regression_checks": "PASS",
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc),
                          "detail": getattr(exc, "stderr", "") or ""}))
        sys.exit(1)
