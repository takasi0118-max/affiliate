"""Related-link helpers for standalone problem-only articles."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import Path
import re

from services.article_generator import GeneratedArticle
from services.article_link_models import ArticleLink
from services.article_link_sanitizer import sanitize_article_references
from services.calendar_year_normalizer import (
    normalize_article_calendar_year,
    strip_calendar_year_from_title,
)
from services.theme_path_service import load_theme_slugs

_INLINE_RELATED_PATTERN = re.compile(
    r"(?:\n[ \t]*---[ \t]*)?\s*"
    r'<div class="affiliate-inline-related"[^>]*>.*?</div>\s*',
    re.IGNORECASE | re.DOTALL,
)
_RELATED_SECTION_PATTERN = re.compile(
    r"\n##\s*関連記事\s*\n[\s\S]*$",
    re.IGNORECASE,
)
_PREFERRED_ARTICLE_TYPES = ("problem", "product", "ranking")


def select_related_article_links(
    history: list[dict],
    theme: str,
    site_dir: Path,
    *,
    target_count: int = 5,
) -> list[ArticleLink]:
    """Pick existing articles relevant to the problem-only theme.

    悩み・商品紹介・ランキングをできるだけ均等に混ぜ、同じテーマの重複も抑える。
    """
    product_themes = list(load_theme_slugs(site_dir).keys())
    matched_themes = [name for name in product_themes if name and name in theme]

    by_type: dict[str, list[tuple[int, str, ArticleLink]]] = {
        article_type: [] for article_type in _PREFERRED_ARTICLE_TYPES
    }
    seen_slugs: set[str] = set()
    for record in history:
        if not isinstance(record, dict):
            continue
        article_type = str(record.get("article_type") or "").strip()
        if article_type not in by_type:
            continue
        title = str(record.get("title") or "").strip()
        slug = str(record.get("slug") or "").strip().strip("/")
        record_theme = str(record.get("theme") or "").strip()
        if not title or not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        score = _score_related_candidate(
            theme=theme,
            title=title,
            record_theme=record_theme,
            article_type=article_type,
            product_themes=product_themes,
            matched_themes=matched_themes,
        )
        by_type[article_type].append(
            (
                score,
                record_theme,
                ArticleLink(
                    article_type=article_type,
                    title=_normalize_related_title(article_type, title),
                    url=f"/{slug}/",
                ),
            )
        )

    for article_type in by_type:
        by_type[article_type].sort(key=lambda item: (-item[0], item[1], item[2].title))

    quotas = _balanced_type_quotas(target_count, by_type)
    selected = _pick_balanced_links(by_type, quotas, prefer_unique_themes=True)
    if len(selected) < target_count:
        selected.extend(
            _pick_balanced_links(
                by_type,
                _remaining_type_quotas(target_count - len(selected), by_type, selected),
                prefer_unique_themes=False,
                already_selected=selected,
            )
        )
    return selected[:target_count]


def _normalize_related_title(article_type: str, title: str) -> str:
    """Normalize related-link titles; strip years from problem article titles."""
    normalized = normalize_article_calendar_year(title)
    if article_type in {"problem", "problem_only"}:
        return strip_calendar_year_from_title(normalized)
    return normalized


def _score_related_candidate(
    *,
    theme: str,
    title: str,
    record_theme: str,
    article_type: str,
    product_themes: list[str],
    matched_themes: list[str],
) -> int:
    """Score how well one history article matches the problem-only theme."""
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
    # 種別ボーナスは小さめにし、関連度のあとにラウンドロビンで均等化する。
    score += {"problem": 3, "product": 2, "ranking": 1}.get(article_type, 0)
    return score


def _balanced_type_quotas(
    target_count: int,
    by_type: dict[str, list[tuple[int, str, ArticleLink]]],
) -> dict[str, int]:
    """Return per-type quotas that stay as even as available candidates allow."""
    available = {
        article_type: len(candidates)
        for article_type, candidates in by_type.items()
    }
    quotas = {article_type: 0 for article_type in _PREFERRED_ARTICLE_TYPES}
    if target_count <= 0:
        return quotas

    remaining = target_count
    while remaining > 0:
        progressed = False
        for article_type in _PREFERRED_ARTICLE_TYPES:
            if remaining <= 0:
                break
            if quotas[article_type] >= available[article_type]:
                continue
            quotas[article_type] += 1
            remaining -= 1
            progressed = True
        if not progressed:
            break
    return quotas


def _remaining_type_quotas(
    remaining_count: int,
    by_type: dict[str, list[tuple[int, str, ArticleLink]]],
    already_selected: list[ArticleLink],
) -> dict[str, int]:
    """Build fill-up quotas while keeping type counts as balanced as possible."""
    selected_counts: dict[str, int] = defaultdict(int)
    for link in already_selected:
        selected_counts[link.article_type] += 1
    available = {
        article_type: max(0, len(candidates) - selected_counts[article_type])
        for article_type, candidates in by_type.items()
    }
    quotas = {article_type: 0 for article_type in _PREFERRED_ARTICLE_TYPES}
    remaining = remaining_count
    while remaining > 0:
        ordered = sorted(
            _PREFERRED_ARTICLE_TYPES,
            key=lambda article_type: (
                selected_counts[article_type] + quotas[article_type],
                _PREFERRED_ARTICLE_TYPES.index(article_type),
            ),
        )
        progressed = False
        for article_type in ordered:
            if remaining <= 0:
                break
            if quotas[article_type] >= available[article_type]:
                continue
            quotas[article_type] += 1
            remaining -= 1
            progressed = True
            break
        if not progressed:
            break
    return quotas


def _pick_balanced_links(
    by_type: dict[str, list[tuple[int, str, ArticleLink]]],
    quotas: dict[str, int],
    *,
    prefer_unique_themes: bool,
    already_selected: list[ArticleLink] | None = None,
) -> list[ArticleLink]:
    """Pick links round-robin by type according to quotas."""
    selected: list[ArticleLink] = []
    already_selected = already_selected or []
    used_urls = {link.url.strip("/") for link in already_selected}
    used_themes = {
        _theme_from_link(link, by_type)
        for link in already_selected
    }
    used_themes.discard("")
    type_counts = {article_type: 0 for article_type in _PREFERRED_ARTICLE_TYPES}
    cursors = {article_type: 0 for article_type in _PREFERRED_ARTICLE_TYPES}

    while True:
        progressed = False
        for article_type in _PREFERRED_ARTICLE_TYPES:
            if type_counts[article_type] >= quotas.get(article_type, 0):
                continue
            candidates = by_type.get(article_type) or []
            while cursors[article_type] < len(candidates):
                _score, record_theme, link = candidates[cursors[article_type]]
                cursors[article_type] += 1
                url_key = link.url.strip("/")
                if not url_key or url_key in used_urls:
                    continue
                if prefer_unique_themes and record_theme and record_theme in used_themes:
                    continue
                selected.append(link)
                used_urls.add(url_key)
                if record_theme:
                    used_themes.add(record_theme)
                type_counts[article_type] += 1
                progressed = True
                break
        if not progressed:
            break
    return selected


def _theme_from_link(
    link: ArticleLink,
    by_type: dict[str, list[tuple[int, str, ArticleLink]]],
) -> str:
    """Best-effort theme lookup for an already selected link."""
    for _score, record_theme, candidate in by_type.get(link.article_type, []):
        if candidate.url.strip("/") == link.url.strip("/"):
            return record_theme
    return ""


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
    """Return disjoint inline/footer lists, keeping article types balanced in both."""
    unique_links: list[ArticleLink] = []
    seen_urls: set[str] = set()
    for link in links:
        key = link.url.strip("/")
        if not key or key in seen_urls:
            continue
        seen_urls.add(key)
        unique_links.append(link)

    if not unique_links:
        return [], []

    by_type: dict[str, list[ArticleLink]] = {
        article_type: [] for article_type in _PREFERRED_ARTICLE_TYPES
    }
    leftovers: list[ArticleLink] = []
    for link in unique_links:
        if link.article_type in by_type:
            by_type[link.article_type].append(link)
        else:
            leftovers.append(link)

    # 関連記事（フッター）は種別を均等に先取りする。
    footer_links: list[ArticleLink] = []
    while len(footer_links) < footer_count:
        progressed = False
        ordered = sorted(
            _PREFERRED_ARTICLE_TYPES,
            key=lambda article_type: (
                sum(1 for item in footer_links if item.article_type == article_type),
                _PREFERRED_ARTICLE_TYPES.index(article_type),
            ),
        )
        for article_type in ordered:
            if len(footer_links) >= footer_count:
                break
            if not by_type[article_type]:
                continue
            footer_links.append(by_type[article_type].pop(0))
            progressed = True
            break
        if not progressed:
            if leftovers:
                footer_links.append(leftovers.pop(0))
                continue
            break

    remaining = [
        link
        for article_type in _PREFERRED_ARTICLE_TYPES
        for link in by_type[article_type]
    ] + leftovers
    max_inline = min(5, max(0, inline_count), len(remaining))
    if len(remaining) >= 3:
        max_inline = max(max_inline, min(3, len(remaining)))
    max_inline = min(max_inline, len(remaining), 5)
    inline_links = remaining[:max_inline]
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
    text = re.sub(r"(?:\n[ \t]*---[ \t]*)+\s*$", "", section_text.rstrip()).rstrip()
    # 区切り線は「あわせて読みたい」の直前だけ。直後には付けない。
    return f"{text}\n\n---\n\n{block}"


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
