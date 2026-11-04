"""Run the 8 BRD demo scenarios through the HTTP API and print a readable report.

Usage (stack running):  make demo
   or: python scripts/run_demo.py --base-url http://localhost:8080/api
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("E2E_BASE_URL", "http://localhost:8080/api"))
    ap.add_argument("--email", default="admin@example.com")
    ap.add_argument("--password", default=os.environ.get("DEMO_PASSWORD", "Recovery#2026"))
    args = ap.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=120) as c:
        tok = c.post("/auth/login", json={"email": args.email, "password": args.password}).json()["access_token"]
        r = c.post("/demo/scenarios/run-all", headers={"Authorization": f"Bearer {tok}"}).json()

    for res in r["results"]:
        mark = "PASS" if res["passed"] else "FAIL"
        print(f"\n[{mark}] Scenario {res['scenario']}: {res['title']}")
        print(f"       {res['description']}")
        for s in res["steps"]:
            print(f"   {'✓' if s['passed'] else '✗'} {s['step']}: expected={json.dumps(s['expected'])} "
                  f"actual={json.dumps(s['actual'])}")
    ok = r["passed"]
    print(f"\n{'ALL SCENARIOS PASSED' if ok else 'SOME SCENARIOS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
