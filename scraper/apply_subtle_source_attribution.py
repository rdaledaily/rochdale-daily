#!/usr/bin/env python3
"""Patch Rochdale Daily for subtle, generic source attribution.

This keeps Roch Valley Radio as an allowed source while preventing its brand
from appearing in public headlines, excerpts, captions, body copy and source
footers. The original article URL remains available through a generic link.
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRAPER = ROOT / "scraper" / "scraper.py"
GENERATOR = ROOT / "scraper" / "generate_pages.py"
SOURCE_MODULE = ROOT / "scraper" / "source_presentation.py"
ARTICLES_JSON = ROOT / "articles.json"
ARTICLES_DIR = ROOT / "articles"


class PatchError(RuntimeError):
    pass


def parse(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise PatchError(f"Could not parse {path}: {exc}") from exc


def write(path: Path, tree: ast.Module) -> None:
    ast.fix_missing_locations(tree)
    rendered = ast.unparse(tree) + "\n"
    compile(rendered, str(path), "exec")
    path.write_text(rendered, encoding="utf-8")


def has_import(tree: ast.Module, module: str, name: str) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == module
        and any(alias.name == name for alias in node.names)
        for node in tree.body
    )


def add_import(tree: ast.Module, module: str, names: list[str]) -> None:
    existing: ast.ImportFrom | None = None
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            existing = node
            break

    if existing is not None:
        current = {alias.name for alias in existing.names}
        for name in names:
            if name not in current:
                existing.names.append(ast.alias(name=name))
        return

    node = ast.ImportFrom(
        module=module,
        names=[ast.alias(name=name) for name in names],
        level=0,
    )
    insert_at = 0
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        insert_at = 1
    while (
        insert_at < len(tree.body)
        and isinstance(tree.body[insert_at], ast.ImportFrom)
        and tree.body[insert_at].module == "__future__"
    ):
        insert_at += 1
    tree.body.insert(insert_at, node)


def function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise PatchError(f"Could not locate {name}()")


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
    return ""


def contains_call(node: ast.AST, name: str) -> bool:
    return any(call_name(child) == name for child in ast.walk(node))


def patch_scraper() -> None:
    tree = parse(SCRAPER)
    add_import(
        tree,
        "source_presentation",
        [
            "clean_candidate_public_text",
            "is_subtle_source",
            "sanitise_article",
        ],
    )

    cache_fn = function(tree, "cache_source_image")
    if not contains_call(cache_fn, "is_subtle_source"):
        guard = ast.parse(
            '''
if is_subtle_source(candidate.source_name, candidate.source_url):
    fallback = CATEGORY_STOCK_IMAGES.get(category, CATEGORY_STOCK_IMAGES["news"])
    return fallback, "Rochdale Daily category image"
'''
        ).body
        cache_fn.body = guard + cache_fn.body

    rewrite_fn = function(tree, "rewrite_candidate")
    if not contains_call(rewrite_fn, "clean_candidate_public_text"):
        rewrite_fn.body.insert(
            0,
            ast.Expr(
                value=ast.Call(
                    func=ast.Name(id="clean_candidate_public_text", ctx=ast.Load()),
                    args=[ast.Name(id="candidate", ctx=ast.Load())],
                    keywords=[],
                )
            ),
        )

    recent_fn = function(tree, "recent_existing_articles")
    if not contains_call(recent_fn, "sanitise_article"):
        for node in ast.walk(recent_fn):
            if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                if node.target.id == "article":
                    for index, statement in enumerate(node.body):
                        if (
                            isinstance(statement, ast.Expr)
                            and isinstance(statement.value, ast.Call)
                            and isinstance(statement.value.func, ast.Attribute)
                            and statement.value.func.attr == "append"
                            and isinstance(statement.value.func.value, ast.Name)
                            and statement.value.func.value.id == "kept"
                        ):
                            node.body.insert(
                                index,
                                ast.Assign(
                                    targets=[ast.Name(id="article", ctx=ast.Store())],
                                    value=ast.Call(
                                        func=ast.Name(id="sanitise_article", ctx=ast.Load()),
                                        args=[ast.Name(id="article", ctx=ast.Load())],
                                        keywords=[],
                                    ),
                                ),
                            )
                            break

    main_fn = function(tree, "main")

    # Sanitise every newly generated record immediately after future.result().
    def patch_statement_lists(node: ast.AST) -> None:
        for field_name in ("body", "orelse", "finalbody"):
            body = getattr(node, field_name, None)
            if not isinstance(body, list):
                continue
            index = 0
            while index < len(body):
                statement = body[index]
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id == "article"
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Attribute)
                    and statement.value.func.attr == "result"
                ):
                    next_is_patch = (
                        index + 1 < len(body)
                        and contains_call(body[index + 1], "sanitise_article")
                    )
                    if not next_is_patch:
                        body.insert(
                            index + 1,
                            ast.If(
                                test=ast.Name(id="article", ctx=ast.Load()),
                                body=[
                                    ast.Assign(
                                        targets=[ast.Name(id="article", ctx=ast.Store())],
                                        value=ast.Call(
                                            func=ast.Name(id="sanitise_article", ctx=ast.Load()),
                                            args=[ast.Name(id="article", ctx=ast.Load())],
                                            keywords=[],
                                        ),
                                    )
                                ],
                                orelse=[],
                            ),
                        )
                        index += 1
                patch_statement_lists(statement)
                index += 1

        handlers = getattr(node, "handlers", None)
        if isinstance(handlers, list):
            for handler in handlers:
                patch_statement_lists(handler)

    patch_statement_lists(main_fn)

    # Sanitise old and new records before they are merged and republished.
    for node in ast.walk(main_fn):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "article":
            continue
        if not isinstance(node.iter, ast.BinOp) or not isinstance(node.iter.op, ast.Add):
            continue
        names = {
            child.id
            for child in ast.walk(node.iter)
            if isinstance(child, ast.Name)
        }
        if not {"existing", "new_articles"}.issubset(names):
            continue
        if not node.body or not contains_call(node.body[0], "sanitise_article"):
            node.body.insert(
                0,
                ast.Assign(
                    targets=[ast.Name(id="article", ctx=ast.Store())],
                    value=ast.Call(
                        func=ast.Name(id="sanitise_article", ctx=ast.Load()),
                        args=[ast.Name(id="article", ctx=ast.Load())],
                        keywords=[],
                    ),
                ),
            )
        break

    write(SCRAPER, tree)


def patch_generator() -> None:
    tree = parse(GENERATOR)
    add_import(
        tree,
        "source_presentation",
        ["generic_sources_markup", "sanitise_article"],
    )

    sources_fn = function(tree, "sources_markup")
    sources_fn.body = [
        ast.Return(
            value=ast.Call(
                func=ast.Name(id="generic_sources_markup", ctx=ast.Load()),
                args=[ast.Name(id="article", ctx=ast.Load())],
                keywords=[],
            )
        )
    ]

    load_fn = function(tree, "load_articles")
    if not contains_call(load_fn, "sanitise_article"):
        for node in ast.walk(load_fn):
            if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
                continue
            if node.target.id != "article":
                continue
            for index, statement in enumerate(node.body):
                if (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Attribute)
                    and statement.value.func.attr == "append"
                    and isinstance(statement.value.func.value, ast.Name)
                    and statement.value.func.value.id == "published"
                ):
                    node.body.insert(
                        index,
                        ast.Assign(
                            targets=[ast.Name(id="article", ctx=ast.Store())],
                            value=ast.Call(
                                func=ast.Name(id="sanitise_article", ctx=ast.Load()),
                                args=[ast.Name(id="article", ctx=ast.Load())],
                                keywords=[],
                            ),
                        ),
                    )
                    break

    # Existing pages must be rewritten so old publisher-heavy captions and
    # source footers disappear after this patch.
    main_fn = function(tree, "main")
    for node in ast.walk(main_fn):
        if not isinstance(node, ast.If):
            continue
        if not (
            isinstance(node.test, ast.Call)
            and isinstance(node.test.func, ast.Attribute)
            and node.test.func.attr == "exists"
            and isinstance(node.test.func.value, ast.Name)
            and node.test.func.value.id == "out_path"
        ):
            continue
        node.body = [
            statement
            for statement in node.body
            if not isinstance(statement, ast.Continue)
        ]

    write(GENERATOR, tree)


def clean_articles_json() -> int:
    if not ARTICLES_JSON.exists():
        return 0

    # Imported only after the new module has been placed in scraper/.
    import sys

    sys.path.insert(0, str(ROOT / "scraper"))
    from source_presentation import sanitise_article  # type: ignore

    payload = json.loads(ARTICLES_JSON.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        articles = payload
        wrapper: dict[str, Any] | None = None
    elif isinstance(payload, dict) and isinstance(payload.get("articles"), list):
        articles = payload["articles"]
        wrapper = payload
    else:
        raise PatchError("articles.json has an unsupported structure")

    changed = 0
    cleaned = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        before = json.dumps(article, ensure_ascii=False, sort_keys=True)
        article = sanitise_article(article)
        after = json.dumps(article, ensure_ascii=False, sort_keys=True)
        changed += int(before != after)
        cleaned.append(article)

    output: Any
    if wrapper is None:
        output = cleaned
    else:
        wrapper["articles"] = cleaned
        output = wrapper

    ARTICLES_JSON.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return changed


def remove_old_article_pages() -> int:
    if not ARTICLES_DIR.exists():
        return 0
    removed = 0
    for path in ARTICLES_DIR.glob("*.html"):
        path.unlink()
        removed += 1
    return removed


def main() -> int:
    for required in (SCRAPER, GENERATOR, SOURCE_MODULE):
        if not required.exists():
            raise PatchError(f"Required file is missing: {required}")

    patch_scraper()
    patch_generator()
    changed = clean_articles_json()
    removed = remove_old_article_pages()

    print("Subtle source attribution patch applied.")
    print(f"Cleaned {changed} existing article record(s).")
    print(f"Removed {removed} old static article page(s) for regeneration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
