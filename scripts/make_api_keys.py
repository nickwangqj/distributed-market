"""Generate a local, git-ignored data/config/api_keys.json.

The real venue receives this file from a Kubernetes Secret. For local work it maps a plaintext
development key to each account in accounts.seed.json — the two must agree, or the ledger
refuses to start (.claude/docs/05-account-ledger.md §10).
"""

from __future__ import annotations

import hashlib
import json
import pathlib

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "config"
SEED_FILE = CONFIG_DIR / "accounts.seed.json"
KEYS_FILE = CONFIG_DIR / "api_keys.json"


def main() -> None:
    accounts = json.loads(SEED_FILE.read_text())
    keys: dict[str, str] = {}
    for account in accounts:
        plaintext = f"sk_test_{account['label']}"
        digest = hashlib.sha256(plaintext.encode()).hexdigest()
        keys[f"sha256:{digest}"] = account["account_id"]
        print(f"{plaintext:20s} -> {account['account_id']} ({account['label']})")

    KEYS_FILE.write_text(json.dumps(keys, indent=2) + "\n")
    print(f"\nwrote {KEYS_FILE.relative_to(pathlib.Path.cwd())}")


if __name__ == "__main__":
    main()
