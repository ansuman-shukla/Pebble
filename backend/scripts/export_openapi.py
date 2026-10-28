"""Write the API's OpenAPI schema to a file (the frontend generates its client from it)."""

import json
import sys
from pathlib import Path

from app.main import app


def main() -> None:
    target = Path(sys.argv[1])
    target.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
