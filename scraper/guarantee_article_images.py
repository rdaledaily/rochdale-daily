#!/usr/bin/env python3
"""Compatibility wrapper for the cards-only article image policy.

All article-image resolution is owned by ensure_article_images.py. This wrapper
exists because older publishing workflows call guarantee_article_images.py.
"""
from __future__ import annotations

import sys

from ensure_article_images import main


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "articles.json"
    raise SystemExit(main(["--articles", target]))
