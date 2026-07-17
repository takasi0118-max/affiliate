"""Remove references and links to articles that are not yet published."""

from __future__ import annotations

import re


_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_SLUG_PATTERN = re.compile(r"/([a-z0-9-]+)/?$", re.IGNORECASE)


def sanitize_article_references(content: str, allowed_slugs: set[str]) -> str:
    """Remove body references to articles outside the allowed slug set."""
    normalized_allowed = {_normalize_slug(slug) for slug in allowed_slugs if slug}
    if not normalized_allowed:
        return content.strip()

    lines = content.splitlines()
    cleaned_lines: list[str] = []
    pending_intro_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        if stripped == "```" and not cleaned_lines:
            continue

        if _should_drop_line(stripped, normalized_allowed):
            pending_intro_lines.clear()
            continue

        if _looks_like_link_intro(stripped):
            pending_intro_lines.append(line)
            continue

        if pending_intro_lines:
            cleaned_lines.extend(pending_intro_lines)
            pending_intro_lines.clear()

        cleaned_lines.append(line)

    cleaned_lines = _remove_orphan_link_intros(cleaned_lines, normalized_allowed)

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"


def _normalize_slug(slug: str) -> str:
    """Return a slug without surrounding slashes."""
    return slug.strip().strip("/").lower()


def _extract_slug(url: str) -> str | None:
    """Extract an article slug from a relative or absolute URL."""
    if "example.com" in url.lower():
        return None

    match = _SLUG_PATTERN.search(url.strip())
    if match:
        return match.group(1).lower()

    if url.startswith("/"):
        parts = [part for part in url.split("/") if part]
        if parts:
            return parts[-1].lower()
    return None


def _is_internal_article_url(url: str) -> bool:
    """Return whether a URL points to a site article rather than an external resource."""
    normalized = url.strip()
    if not normalized:
        return False
    if normalized.startswith(("/", "#")):
        return True
    if "://" not in normalized:
        return True
    return False


def _should_drop_line(line: str, allowed_slugs: set[str]) -> bool:
    """Return whether one line should be removed."""
    stripped = line.strip()
    if not line:
        return False

    if stripped == "```":
        return True

    if "内部リンク予定地" in line:
        return True

    if "example.com" in line.lower():
        return True

    if _is_placeholder_reference(line):
        return True

    for _text, url in _LINK_PATTERN.findall(line):
        if not _is_internal_article_url(url):
            continue
        slug = _extract_slug(url)
        if slug is None or slug not in allowed_slugs:
            return True

    return False


def _is_placeholder_reference(line: str) -> bool:
    """Return whether a line is a placeholder article reference without a valid URL."""
    if _LINK_PATTERN.search(line):
        return False

    markers = (
        "あわせて読みたい",
        "→ [",
        "👉 [",
        "[→ ",
    )
    if any(marker in line for marker in markers) and line.startswith(("[", "→", "👉")):
        return True

    if line.startswith("[") and line.endswith("]") and "http" not in line and "/" not in line:
        return True

    return False


def _remove_orphan_link_intros(
    lines: list[str],
    allowed_slugs: set[str],
) -> list[str]:
    """Drop intro lines that no longer have a valid related-article link below."""
    result: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _looks_like_link_intro(line.strip()):
            has_valid_link = False
            for lookahead in lines[index + 1 : index + 4]:
                stripped = lookahead.strip()
                if stripped.startswith("##"):
                    break
                for _text, url in _LINK_PATTERN.findall(lookahead):
                    if not _is_internal_article_url(url):
                        continue
                    slug = _extract_slug(url)
                    if slug and slug in allowed_slugs:
                        has_valid_link = True
                        break
                if has_valid_link:
                    break
            if not has_valid_link:
                index += 1
                continue
        result.append(line)
        index += 1
    return result


def _looks_like_link_intro(line: str) -> bool:
    """Return whether a line introduces a related article link below."""
    intro_markers = (
        "以下の記事では",
        "次の記事も参考",
        "次の記事もぜひ",
        "次の記事も",
        "ぜひ次の記事",
        "ぜひ参考にしてください",
        "ぜひ合わせてチェック",
        "合わせてチェック",
        "参考にしてください。",
        "詳しく紹介しています",
        "詳しく比較しています",
    )
    return any(marker in line for marker in intro_markers)
