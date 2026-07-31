"""Related-link helpers for standalone problem-only articles."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

from services.article_generator import GeneratedArticle
from services.article_link_models import ArticleLink
from services.article_link_sanitizer import sanitize_article_references
from services.theme_path_service import load_theme_slugs

_INLINE_RELATED_PATTERN = re.compile(
    r'<div class="affiliate-inline-related"[^>]*>.*?</div>\s*',
    re.IGNORECASE | re.DOTALL,
)
_RELATED_SECTION_PATTERN = re.compile(
    r"\n##\s*関連記事\s*\n[\s\S]*$",
    re.IGNORECASE,
)


def select_related_article_links(
    history: list[dict],
    theme: str,
    site_dir: Path,
    *,
    target_count: int = 5,
) -> list[ArticleLink]:
    """Pick existing articles relevant to the problem-only theme."""
    product_themes = list(load_theme_slugs(site_dir).keys())
    matched_themes = [name for name in product_themes if name and name in theme]

    scored: list[tuple[int, str, ArticleLink]] = []
    seen_slugs: set[str] = set()
    for record in history:
        if not isinstance(record, dict):
            continue
        article_type = str(record.get("article_type") or "").strip()
        if article_type == "problem_only":
            continue
        title = str(record.get("title") or "").strip()
        slug = str(record.get("slug") or "").strip().strip("/")
        record_theme = str(record.get("theme") or "").strip()
        if not title or not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        score = 0
        if record_theme in matched_themes:
            score += 100
        for name in matched_themes:
            if name in title:
                score += 20
        for name in product_themes:
            token = name.replace("防災", "").replace("用", "")
            if len(token) >= 2 and token in theme:
                if record_theme == name:
                    score += 40
                elif token in title:
                    score += 10
        type_bonus = {"problem": 3, "product": 2, "ranking": 1}.get(article_type, 0)
        score += type_bonus
        scored.append(
            (
                score,
                record_theme,
                ArticleLink(
                    article_type=article_type or "related",
                    title=title,
                    url=f"/{slug}/",
                ),
            )
        )

    scored.sort(key=lambda item: (-item[0], item[1], item[2].title))
    selected: list[ArticleLink] = []
    used_themes: set[str] = set()
    used_types: set[str] = set()

    for score, record_theme, link in scored:
        if len(selected) >= target_count:
            break
        if record_theme in used_themes:
            continue
        if link.article_type in used_types and len(used_types) < 3:
            continue
        selected.append(link)
        used_themes.add(record_theme)
        used_types.add(link.article_type)

    if len(selected) < target_count:
        for _, record_theme, link in scored:
            if link in selected:
                continue
            if record_theme not in used_themes or len(selected) >= target_count - 1:
                selected.append(link)
                used_themes.add(record_theme)
            if len(selected) >= target_count:
                break

    if len(selected) < target_count:
        for _, _, link in scored:
            if link in selected:
                continue
            selected.append(link)
            if len(selected) >= target_count:
                break

    return selected[:target_count]


def apply_related_article_links(
    article: GeneratedArticle,
    links: list[ArticleLink],
    *,
    footer_count: int = 3,
    inline_count: int = 5,
) -> GeneratedArticle:
    """Inject inline related boxes and a footer related section."""
    if not links:
        return article

    content = _strip_existing_related_markup(article.content)
    inline_links, footer_links = _split_inline_and_footer_links(
        links,
        footer_count=footer_count,
        inline_count=inline_count,
    )

    content = _inject_inline_related_links(content, inline_links)
    content = _append_footer_related_section(content, footer_links)
    allowed_slugs = {
        link.url.strip("/").split("/")[-1]
        for link in [*inline_links, *footer_links]
        if link.url
    }
    content = sanitize_article_references(content, allowed_slugs)
    return replace(article, content=content)


def _split_inline_and_footer_links(
    links: list[ArticleLink],
    *,
    footer_count: int,
    inline_count: int,
) -> tuple[list[ArticleLink], list[ArticleLink]]:
    """Return disjoint inline/footer link lists (no shared articles)."""
    unique_links: list[ArticleLink] = []
    seen_urls: set[str] = set()
    for link in links:
        key = link.url.strip("/")
        if not key or key in seen_urls:
            continue
        seen_urls.add(key)
        unique_links.append(link)

    # Prefer filling inline first (3–5), then footer (3) from remaining links.
    max_inline = min(5, max(3, inline_count), len(unique_links))
    # Keep at least footer_count for the footer when enough links exist.
    if len(unique_links) >= footer_count + 3:
        max_inline = min(max_inline, len(unique_links) - footer_count)
    max_inline = max(0, min(max_inline, len(unique_links)))

    inline_links = unique_links[:max_inline]
    used = {link.url.strip("/") for link in inline_links}
    footer_links = [
        link for link in unique_links if link.url.strip("/") not in used
    ][:footer_count]
    return inline_links, footer_links


def _strip_existing_related_markup(content: str) -> str:
    """Remove previously injected related boxes and the footer section."""
    content = _INLINE_RELATED_PATTERN.sub("", content)
    content = _RELATED_SECTION_PATTERN.sub("", content)
    return content.rstrip() + "\n"


def _inject_inline_related_links(content: str, links: list[ArticleLink]) -> str:
    """Insert 3–5 'あわせて読みたい' boxes at the end of H2 sections."""
    if not links:
        return content

    sections = _split_h2_sections(content)
    if not sections:
        return content

    # Skip intro (before first H2), FAQ, summary-like closings, and 関連記事.
    candidate_indexes: list[int] = []
    for index, (heading, _body) in enumerate(sections):
        if not heading.startswith("## "):
            continue
        if _should_skip_inline_heading(heading):
            continue
        candidate_indexes.append(index)

    if not candidate_indexes:
        return content

    # Prefer 3–5 mid-article sections (not only the first ones).
    max_inline = min(5, len(links), len(candidate_indexes))
    min_inline = min(3, max_inline)
    chosen_indexes = candidate_indexes[:max_inline]
    if len(chosen_indexes) < min_inline:
        return content

    rebuilt: list[str] = []
    link_iter = iter(links[: len(chosen_indexes)])
    chosen_set = set(chosen_indexes)
    for index, (heading, body) in enumerate(sections):
        section_text = f"{heading}\n{body}".strip("\n") if heading else body.strip("\n")
        if index in chosen_set:
            link = next(link_iter, None)
            if link is not None:
                section_text = _append_inline_block_to_section(section_text, link)
        rebuilt.append(section_text)

    return "\n\n".join(part for part in rebuilt if part).rstrip() + "\n"


def _split_h2_sections(content: str) -> list[tuple[str, str]]:
    """Split Markdown into (heading, body) pairs. Intro has empty heading."""
    lines = content.splitlines(keepends=True)
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_body: list[str] = []

    for line in lines:
        if re.match(r"^##\s+", line):
            sections.append((current_heading, "".join(current_body)))
            current_heading = line.rstrip("\n")
            current_body = []
        else:
            current_body.append(line)

    sections.append((current_heading, "".join(current_body)))
    return sections


def _should_skip_inline_heading(heading: str) -> bool:
    """Return whether an H2 should not receive an inline related box."""
    text = heading.lstrip("# ").strip()
    skip_keywords = (
        "関連記事",
        "FAQ",
        "よくある質問",
        "まとめ",
        "おわりに",
        "最後に",
        "総括",
        "押さえよう",
        "整えよう",
        "始めよう",
        "確認しよう",
        "進めよう",
    )
    return any(keyword in text for keyword in skip_keywords)


def _append_inline_block_to_section(section_text: str, link: ArticleLink) -> str:
    """Append one related box at the end of an H2 section body."""
    block = _inline_related_block(link)
    text = section_text.rstrip()
    # Keep a trailing horizontal rule if the section already ends with one.
    if text.endswith("\n---") or text.endswith("\n---\n"):
        text = text.rstrip()
        if text.endswith("---"):
            without_rule = text[: -len("---")].rstrip()
            return f"{without_rule}\n\n{block}\n\n---"
    return f"{text}\n\n{block}"


def _inline_related_block(link: ArticleLink) -> str:
    return (
        f'<div class="affiliate-inline-related" data-related-type="{link.article_type}">'
        '<span class="affiliate-inline-related__label">あわせて読みたい</span> '
        f'<a class="affiliate-link" href="{link.url}">{link.title}</a>'
        "</div>"
    )


def _append_footer_related_section(content: str, links: list[ArticleLink]) -> str:
    """Append a related-article list with three links."""
    if not links:
        return content
    if "## 関連記事" in content:
        return content
    section = "\n".join(
        [
            "",
            "## 関連記事",
            "",
            *[link.to_markdown() for link in links],
            "",
        ]
    )
    return f"{content.rstrip()}\n{section}"
