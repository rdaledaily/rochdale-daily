"""Generate the site with the freshness-first front-page policy installed."""
from __future__ import annotations

import runpy
from pathlib import Path

from fresh_frontpage_policy import install


def main() -> None:
    install()
    runpy.run_path(str(Path(__file__).with_name("generate_pages.py")), run_name="__main__")


if __name__ == "__main__":
    main()
