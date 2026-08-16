from pathlib import Path

src_path = Path('scraper/_migrate_image_policy_v2.py')
src = src_path.read_text(encoding='utf-8')
old = '''    rel = low.lstrip("/")\n    candidate = root / rel\n    try:\n        return (\n            candidate.is_file()\n            and candidate.suffix.lower() in IMAGE_SUFFIXES\n            and candidate.stat().st_size > 4096\n            and not is_generated_card(candidate)\n        )\n    except OSError:\n        return False\n'''
new = '''    rel = low.lstrip("/")\n    candidate = root / rel\n    try:\n        valid = (\n            candidate.is_file()\n            and candidate.suffix.lower() in IMAGE_SUFFIXES\n            and candidate.stat().st_size > 4096\n            and not is_generated_card(candidate)\n        )\n    except OSError:\n        return False\n    if not valid:\n        return False\n\n    real_status = any(token in status for token in ("source-photo", "commons-photo", "editorial-photo"))\n    if rel.startswith("assets/img/cards/"):\n        # Ordinary library cards still have to match the story; only a photo\n        # already identified by source/Commons/editorial enrichment bypasses\n        # filename matching.\n        return real_status\n    return bool(\n        real_status\n        or clean(article.get("image_credit"))\n        or clean(article.get("image_credit_url"))\n        or article.get("manual_article") is True\n        or clean(article.get("source_kind")).lower() == "editorial"\n    )\n'''
if old not in src:
    raise SystemExit('Expected local-image preservation template not found in v2 migration')
src = src.replace(old, new, 1)
code = compile(src, str(src_path), 'exec')
namespace = {'__name__': '__main__', '__file__': str(src_path)}
exec(code, namespace)
