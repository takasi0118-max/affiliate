"""Insert contextual related-article links into article Markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass

from config.settings import load_settings
from config.site_config import load_site_config
from services.article_link_models import ArticleLink
from services.calendar_year_normalizer import (
    normalize_article_calendar_year,
    strip_calendar_year_from_title,
)


INLINE_RELATED_BLOCK_PATTERN = re.compile(
    r"(?:\n[ \t]*---[ \t]*)?\s*"
    r'<div class="affiliate-inline-related"[^>]*>.*?</div>\s*',
    re.DOTALL,
)
ORPHAN_INLINE_COMMENT_PATTERN = re.compile(
    r"<!--\s*affiliate-inline-related:[^>]+-->\s*",
    re.IGNORECASE,
)
H2_HEADING_PATTERN = re.compile(r"^##\s+(?!#)")


@dataclass(frozen=True)
class InlineLinkPlacement:
    """One contextual inline link insertion rule."""

    heading_keywords: tuple[str, ...]
    target_type: str
    intro: str
    closing: str = "も参考にしてください。"


INLINE_PLACEMENTS: dict[str, tuple[InlineLinkPlacement, ...]] = {
    "problem": (
        InlineLinkPlacement(
            heading_keywords=("解決", "おすすめ", "選び方"),
            target_type="product",
            intro="具体的なおすすめ商品の特徴や中身を詳しく知りたい方は、",
        ),
        InlineLinkPlacement(
            heading_keywords=("FAQ", "よくある質問"),
            target_type="ranking",
            intro="複数商品を比較表とランキング形式で見たい方は、",
        ),
    ),
    "product": (
        InlineLinkPlacement(
            heading_keywords=("解決", "選び方", "失敗しない"),
            target_type="problem",
            intro="選び方の基本やよくある失敗を整理したい方は、",
        ),
        InlineLinkPlacement(
            heading_keywords=("おすすめ", "厳選", "ランキング"),
            target_type="ranking",
            intro="人気商品をランキング形式で比較したい方は、",
            closing="もあわせてご覧ください。",
        ),
    ),
    "ranking": (
        InlineLinkPlacement(
            heading_keywords=("解決", "選び方"),
            target_type="problem",
            intro="まず「何から備えればよいか」を整理したい方は、",
        ),
        InlineLinkPlacement(
            heading_keywords=("比較", "ランキング"),
            target_type="product",
            intro="各商品の特徴やメリット・デメリットを詳しく知りたい方は、",
        ),
    ),
}


def load_theme_article_links() -> dict[str, dict[str, ArticleLink]]:
    """Return related article links grouped by theme and article type."""
    settings = load_settings()
    site_config = load_site_config(
        site_key=settings.site_key,
        output_dir=settings.output_dir,
    )
    links_by_theme: dict[str, dict[str, ArticleLink]] = {}
    for record in site_config.history:
        if not isinstance(record, dict):
            continue
        theme = str(record.get("theme", "")).strip()
        article_type = str(record.get("article_type", "")).strip()
        title = str(record.get("title", "")).strip()
        slug = str(record.get("slug", "")).strip().strip("/")
        if not theme or article_type not in {"problem", "product", "ranking"}:
            continue
        if not title or not slug:
            continue
        link_title = normalize_article_calendar_year(title)
        if article_type == "problem":
            link_title = strip_calendar_year_from_title(link_title)
        links_by_theme.setdefault(theme, {})[article_type] = ArticleLink(
            article_type=article_type,
            title=link_title,
            url=f"/{slug}/",
        )
    return links_by_theme


class InlineRelatedLinkService:
    """Insert natural inline related links and a footer related section."""

    def apply(
        self,
        content: str,
        article_type: str,
        theme: str,
        theme_links: dict[str, dict[str, ArticleLink]] | None = None,
    ) -> str:
        """Return Markdown with inline and footer related links."""
        links = (theme_links or load_theme_article_links()).get(theme, {})
        if len(links) < 2:
            return content

        cleaned = _strip_inline_related_blocks(content)
        cleaned = _strip_footer_related_section(cleaned)
        with_inline = _insert_inline_links(cleaned, article_type, links)
        return _append_footer_related_section(with_inline, article_type, links)


def _strip_inline_related_blocks(content: str) -> str:
    """Remove previously inserted inline related link blocks."""
    cleaned = ORPHAN_INLINE_COMMENT_PATTERN.sub("", content)
    cleaned = INLINE_RELATED_BLOCK_PATTERN.sub("", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _strip_footer_related_section(content: str) -> str:
    """Remove an existing footer related-article section."""
    lines = content.splitlines()
    result: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() == "## 関連記事":
            break
        result.append(lines[index])
        index += 1
    while result and not result[-1].strip():
        result.pop()
    return "\n".join(result).strip()


def _insert_inline_links(
    content: str,
    article_type: str,
    links: dict[str, ArticleLink],
) -> str:
    """Insert contextual inline related links based on article type."""
    placements = INLINE_PLACEMENTS.get(article_type, ())
    if not placements:
        return content

    lines = content.splitlines()
    insertion_points: list[tuple[int, InlineLinkPlacement]] = []
    used_targets: set[str] = set()

    for placement in placements:
        target_link = links.get(placement.target_type)
        if target_link is None or placement.target_type in used_targets:
            continue
        insert_at = _find_insert_index(lines, placement.heading_keywords)
        if insert_at is None:
            continue
        insertion_points.append((insert_at, placement))
        used_targets.add(placement.target_type)

    for insert_at, placement in sorted(insertion_points, key=lambda item: item[0], reverse=True):
        target_link = links[placement.target_type]
        block = _format_inline_block(
            target_type=placement.target_type,
            link=target_link,
        )
        # 直前のセクション末尾 --- はブロック側で付けるので重複させない。
        trim_at = insert_at
        while trim_at > 0 and not lines[trim_at - 1].strip():
            trim_at -= 1
        if trim_at > 0 and lines[trim_at - 1].strip() == "---":
            del lines[trim_at - 1 : insert_at]
            insert_at = trim_at - 1
        block_lines = block.splitlines()
        if insert_at < len(lines) and lines[insert_at].strip():
            block_lines.append("")
        lines[insert_at:insert_at] = block_lines

    return "\n".join(lines).strip()


def _find_insert_index(lines: list[str], heading_keywords: tuple[str, ...]) -> int | None:
    """Return the line index before the next H2 heading after a matched section."""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not H2_HEADING_PATTERN.match(stripped):
            continue
        if not any(keyword in stripped for keyword in heading_keywords):
            continue
        for next_index in range(index + 1, len(lines)):
            next_line = lines[next_index].strip()
            if H2_HEADING_PATTERN.match(next_line):
                return next_index
        return len(lines)
    return None


def _format_inline_block(
    target_type: str,
    link: ArticleLink,
) -> str:
    """Return one styled inline related link block."""
    # 区切り線はブロック直前。直後の --- は付けない。
    return (
        "---\n\n"
        f'<div class="affiliate-inline-related" data-related-type="{target_type}">'
        '<span class="affiliate-inline-related__label">あわせて読みたい</span> '
        f'<a class="affiliate-link" href="{link.url}">{link.title}</a>'
        "</div>"
    )


def _append_footer_related_section(
    content: str,
    article_type: str,
    links: dict[str, ArticleLink],
) -> str:
    """Append a footer related-article section for the other two article types."""
    related_links = [
        link
        for link_type, link in links.items()
        if link_type != article_type
    ]
    if not related_links:
        return content

    section = "\n".join(
        [
            "",
            "## 関連記事",
            "",
            *[link.to_markdown() for link in related_links],
            "",
        ]
    )
    return f"{content.rstrip()}\n{section}"
