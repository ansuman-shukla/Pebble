"""Copy saved logins from the main devin-switch into Pebble's private one.

The source is only read. Each account is registered with Pebble's `ds add`, then its credentials.toml is copied
(0600). Re-run to pick up new or re-logged-in accounts. Credential contents are never printed.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path.home() / ".local/share/devin-switch/accounts"
TARGET = ROOT / ".runtime/ds/accounts"
DS = ROOT / "scripts/ds.sh"


def main() -> None:
    imported, skipped = [], []
    for account in sorted(p for p in SOURCE.iterdir() if p.is_dir()):
        credentials = account / "data/devin/credentials.toml"
        if credentials.is_symlink() or not credentials.is_file() or credentials.stat().st_size == 0:
            skipped.append(account.name)
            continue
        if not (TARGET / account.name / "account.json").exists():
            subprocess.run([str(DS), "add", account.name], check=True, capture_output=True)
        destination = TARGET / account.name / "data/devin/credentials.toml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(credentials, destination)
        destination.chmod(0o600)
        imported.append(account.name)
    print(f"imported {len(imported)} logins; skipped {len(skipped)} without a saved login: {skipped}")


if __name__ == "__main__":
    sys.exit(main())
