from pathlib import Path
import re


def main() -> None:
    path = Path('scraper/ensure_article_images.py')
    text = path.read_text(encoding='utf-8')

    start = text.find('"""Enforce Rochdale Daily')
    if start < 0:
        raise SystemExit('Could not find old image-policy docstring start')
    end = text.find('"""', start + 3)
    if end < 0:
        raise SystemExit('Could not find old image-policy docstring end')
    end += 3
    new_doc = '''"""Guarantee that every published article has a usable image.\n\nA meaningful existing editorial, source or Wikimedia image is preserved. If none\nexists, the local cards library is searched for a filename-matched photograph.\nOnly when neither route produces a real image is a generated headline card used\nas the final fallback. Image relevance is the editorial objective; the cards\nfolder is a cache/fallback implementation detail, not a publication rule.\n"""'''
    text = text[:start] + new_doc + text[end:]

    marker = '\ndef strip_remote_image_metadata(article: dict[str, Any]) -> None:\n'
    if marker not in text:
        raise SystemExit('Could not find image metadata helper insertion point')
    helper = '''\n\ndef existing_meaningful_image(article: dict[str, Any], root: Path) -> bool:\n    """Keep a real image already chosen by editorial/source/Commons enrichment."""\n    value = clean(article.get("image_url") or article.get("img"))\n    if not value:\n        return False\n    low = value.lower().replace("\\\\", "/")\n    status = clean(article.get("image_status")).lower()\n    if any(token in status for token in ("generated", "placeholder")):\n        return False\n    if any(token in low for token in ("generated-card", "placeholder", "category_", "category-")):\n        return False\n    if low.startswith(("https://", "http://")):\n        return bool(\n            clean(article.get("image_credit"))\n            or clean(article.get("image_credit_url"))\n            or any(token in status for token in ("source-photo", "commons-photo", "editorial-photo"))\n        )\n    rel = low.lstrip("/")\n    candidate = root / rel\n    try:\n        return (\n            candidate.is_file()\n            and candidate.suffix.lower() in IMAGE_SUFFIXES\n            and candidate.stat().st_size > 4096\n            and not is_generated_card(candidate)\n        )\n    except OSError:\n        return False\n'''
    text = text.replace(marker, helper + marker, 1)

    old = '''def enforce_article(article: dict[str, Any], root: Path) -> str:\n    # Always re-check the local library first. This makes the matcher\n    # retrospective: uploading a new correctly named photo can repair old stories.\n    chosen = choose_filename_match(article, root)\n'''
    new = '''def enforce_article(article: dict[str, Any], root: Path) -> str:\n    # Preserve real photography already selected by an editor, source cache or\n    # Wikimedia enrichment. The cards library is a fallback, not the objective.\n    if existing_meaningful_image(article, root):\n        return "kept-existing"\n\n    chosen = choose_filename_match(article, root)\n'''
    if old not in text:
        raise SystemExit('Could not find enforce_article entry block')
    text = text.replace(old, new, 1)

    old_policy = '"policy": "assets/img/cards only; filename matched against title, slug, excerpt and body"'
    new_policy = '"policy": "preserve meaningful existing image; then filename-matched local photo; generated card only as final fallback"'
    if old_policy not in text:
        raise SystemExit('Could not find old image report policy')
    text = text.replace(old_policy, new_policy, 1)
    path.write_text(text, encoding='utf-8')

    test = Path('scraper/test_ensure_article_images.py')
    data = test.read_text(encoding='utf-8')
    data, count = re.subn(
        r'def test_non_cards_image_is_never_preserved\(\) -> None:\n.*?(?=\ndef test_curated_cards_photo_matches_full_story_phrase)',
        '''def test_meaningful_existing_local_image_is_preserved() -> None:\n    with tempfile.TemporaryDirectory() as tmp:\n        root = Path(tmp)\n        image = root / "assets/article-images/existing.jpg"\n        write_jpeg(image)\n        article = {\n            "title": "Sample Rochdale story",\n            "slug": "sample-rochdale-story",\n            "category": "community",\n            "area": "rochdale",\n            "status": "published",\n            "image_url": "assets/article-images/existing.jpg",\n            "image_credit": "Rochdale Daily",\n        }\n        result = mod.enforce_article(article, root)\n        assert result == "kept-existing"\n        assert article["image_url"] == "assets/article-images/existing.jpg"\n\n\n''',
        data,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit('Could not replace non-cards image regression test')

    data, count = re.subn(
        r'def test_run_gives_every_published_story_a_cards_image\(\) -> None:\n.*?(?=\n\nif __name__ == "__main__":)',
        '''def test_run_preserves_credited_commons_and_guarantees_other_images() -> None:\n    with tempfile.TemporaryDirectory() as tmp:\n        root = Path(tmp)\n        articles_path = root / "articles.json"\n        report_path = root / "report.json"\n        articles_path.write_text(json.dumps([\n            {\n                "title": "One",\n                "slug": "one",\n                "status": "published",\n                "category": "news",\n                "area": "rochdale",\n                "image_url": "https://upload.wikimedia.org/example.jpg",\n                "image_credit": "Wikimedia Commons",\n            },\n            {\n                "title": "Two",\n                "slug": "two",\n                "status": "published",\n                "category": "sport",\n                "area": "heywood",\n                "image_url": "",\n            },\n        ]), encoding="utf-8")\n        old_cwd = Path.cwd()\n        try:\n            os.chdir(root)\n            rc = mod.main(["--articles", str(articles_path), "--report", str(report_path)])\n        finally:\n            os.chdir(old_cwd)\n        assert rc == 0\n        saved = json.loads(articles_path.read_text(encoding="utf-8"))\n        assert saved[0]["image_url"] == "https://upload.wikimedia.org/example.jpg"\n        assert saved[1]["image_url"].startswith("assets/img/cards/")\n        assert (root / saved[1]["image_url"]).is_file()\n        report = json.loads(report_path.read_text(encoding="utf-8"))\n        assert "preserve meaningful existing image" in report["policy"]\n''',
        data,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit('Could not replace full-run image policy test')

    data = data.replace('test_non_cards_image_is_never_preserved,', 'test_meaningful_existing_local_image_is_preserved,')
    data = data.replace('test_run_gives_every_published_story_a_cards_image,', 'test_run_preserves_credited_commons_and_guarantees_other_images,')
    test.write_text(data, encoding='utf-8')


if __name__ == '__main__':
    main()
