"""Parse, validate, and restore Rakuten product blocks in Markdown articles."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from providers.rakuten_provider import RakutenProduct


PRODUCT_IMAGE_LINK_PATTERN = re.compile(
    r"\[!\[(?P<name>[^\]]+)\]\((?P<img>[^)]+)\)\]\((?P<url>[^)]+)\)",
)
HTML_PRODUCT_LINK_PATTERN = re.compile(
    r'<a\s[^>]*href="(?P<url>https://hb\.afl\.rakuten\.co\.jp[^"]+)"[^>]*>\s*'
    r'<img\s[^>]*src="(?P<img>[^"]+)"[^>]*alt="(?P<name>[^"]*)"[^>]*>\s*</a>',
    re.IGNORECASE | re.DOTALL,
)
PRODUCT_BLOCK_PATTERN = re.compile(
    r"\[!\[(?P<name>[^\]]+)\]\((?P<img>[^)]+)\)\]\((?P<url>[^)]+)\)\s*\n(?:\s*\n)*"
    r"(?:\*\s+\*\*商品名\*\*:\s*(?P<full_name>[^\n]+)\n(?:\s*\n)*)?"
    r"\*\s+\*\*価格\*\*:\s*(?P<price>[^\n]+)\n"
    r"(?:\*\s+\*\*おすすめ度\*\*:\s*[^\n]+\n)?"
    r"\*\s+\*\*レビュー(?:評価)?\*\*:\s*(?P<review>[0-9.]+)"
    r"[^\n]*?(?:件数:\s*)?(?P<count>[0-9,]+)\s*件",
    re.DOTALL,
)
PRODUCT_SECTION_TITLE_PATTERN = re.compile(
    r"^###\s+(?:\d+位[：:]|\d+[\.．]\s*)(.+)$",
    re.MULTILINE,
)
QUOTED_PRODUCT_NAME_PATTERN = re.compile(r"「([^」]+)」")
PRODUCT_NAME_LINE_PATTERN = re.compile(r"^[-*]\s+\*\*商品名\*\*\s*[：:]\s*(.+)$", re.MULTILINE)
PRICE_LINE_PATTERN = re.compile(
    r"^[-*]?\s*\*\*(?:通常|参考|税込|販売)?価格\*\*\s*[：:]"
)
REVIEW_LINE_PATTERN = re.compile(r"^[-*]?\s*\*\*レビュー(?:評価)?\*\*\s*[：:]")
RECOMMEND_LINE_PATTERN = re.compile(r"^[-*]?\s*\*\*おすすめ度\*\*\s*[：:]")
PRICE_LABEL_NORMALIZE_PATTERN = re.compile(
    r"^([-*]?\s*)\*\*(?:通常|参考|税込|販売)?価格\*\*\s*[：:]",
    re.MULTILINE,
)
RANKING_RECOMMEND_SCORES = (5.0, 4.8, 4.6, 4.4, 4.2)
PRODUCT_SECTION_HEADING_PATTERN = re.compile(
    r"^###\s+(?:\d+[\.．]|\d+位|[0-9]+[\.．])"
)
PRODUCT_DETAIL_BULLET_PATTERN = re.compile(
    r"^\*\s+\*\*(特徴|メリット|デメリット|初心者向け説明)\*\*:\s*(.*)$",
    re.MULTILINE,
)
AFFILIATE_URL_MARKER = "hb.afl.rakuten.co.jp"


@dataclass(frozen=True)
class ProductBlock:
    """One Rakuten affiliate product block extracted from Markdown or HTML."""

    name: str
    url: str
    image_url: str
    price: str | None = None
    review_average: str | None = None
    review_count: str | None = None


def normalize_affiliate_blocks_in_markdown(content: str) -> str:
    """Convert embedded HTML affiliate image links to Markdown image links."""

    def replace(match: re.Match[str]) -> str:
        alt = _short_product_name(match.group("name") or "楽天商品")
        return f"[![{alt}]({match.group('img')})]({match.group('url')})"

    return HTML_PRODUCT_LINK_PATTERN.sub(replace, content)


def format_product_image_link(block: ProductBlock) -> str:
    """Return one Markdown affiliate image link line."""
    alt_text = _short_product_name(block.name)
    return f"[![{alt_text}]({block.image_url})]({block.url})"


def _short_product_name(name: str) -> str:
    """Return a shorter alt text safe for Markdown image syntax."""
    cleaned = re.sub(r"\s+", " ", name).strip()
    # []() break [![alt](img)](url) parsing/counting; strip them from alt only.
    cleaned = re.sub(r"[\[\]\(\)]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= 48:
        return cleaned or "楽天商品"
    return cleaned[:45] + "..."


def count_affiliate_image_links(content: str) -> int:
    """Return how many Rakuten affiliate image links exist in Markdown or HTML."""
    normalized = normalize_affiliate_blocks_in_markdown(content)
    well_formed = len(PRODUCT_IMAGE_LINK_PATTERN.findall(normalized))
    # Fallback counts image→affiliate pairs even when alt text contains brackets.
    loose = len(
        re.findall(
            r"\]\([^)\n]+\)\]\(https://hb\.afl\.rakuten\.co\.jp[^)\n]*\)",
            normalized,
        )
    )
    return max(well_formed, loose)


def has_product_blocks(content: str, minimum: int = 1) -> bool:
    """Return whether Markdown contains enough Rakuten product image links."""
    return count_affiliate_image_links(content) >= minimum


def parse_products_from_markdown(content: str) -> list[RakutenProduct]:
    """Read Rakuten product metadata blocks from Markdown text."""
    normalized = normalize_affiliate_blocks_in_markdown(content)
    products: list[RakutenProduct] = []
    for match in PRODUCT_BLOCK_PATTERN.finditer(normalized):
        price_digits = re.sub(r"\D", "", match.group("price"))
        count_digits = re.sub(r"\D", "", match.group("count"))
        products.append(
            RakutenProduct(
                name=(match.group("full_name") or match.group("name")).strip(),
                price=int(price_digits) if price_digits else 0,
                url=match.group("url"),
                image_url=match.group("img"),
                review_average=float(match.group("review")),
                review_count=int(count_digits) if count_digits else 0,
            )
        )
    return products


def format_product_name_line(block: ProductBlock) -> str:
    """Return a Markdown line with the full product name."""
    return f"* **商品名**: {block.name}"


def normalize_product_price_lines(content: str) -> str:
    """Normalize Gemini price labels so affiliate blocks can be injected."""
    normalized = PRICE_LABEL_NORMALIZE_PATTERN.sub(r"* **価格**:", content)
    # Gemini sometimes uses fullwidth digits/periods in product headings.
    return re.sub(
        r"^###\s+([0-9]+)．",
        lambda match: f"### {match.group(1)}.",
        normalized,
        flags=re.MULTILINE,
    )


def normalize_product_detail_sections(content: str) -> str:
    """Convert inline 特徴/メリット/デメリット bullets into #### headings."""
    if not PRODUCT_DETAIL_BULLET_PATTERN.search(content):
        return content

    lines = content.splitlines()
    result: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        match = PRODUCT_DETAIL_BULLET_PATTERN.match(line.strip())
        if not match:
            result.append(line)
            index += 1
            continue

        label, inline_text = match.group(1), match.group(2).strip()
        index += 1

        if label == "初心者向け説明":
            paragraphs = _collect_detail_paragraphs(inline_text, lines, index)
            index = paragraphs[1]
            if paragraphs[0]:
                _append_to_last_feature_section(result, paragraphs[0])
            continue

        if label == "特徴":
            result.append("#### 特徴")
            feature_lines = []
            if inline_text:
                feature_lines.append(inline_text)
            extra_lines, index = _collect_plain_detail_lines(lines, index)
            feature_lines.extend(extra_lines)
            result.extend(feature_lines)
            result.append("")
            continue

        if label in {"メリット", "デメリット"}:
            result.append(f"#### {label}")
            items: list[str] = []
            if inline_text:
                items.append(inline_text)
            while index < len(lines):
                stripped = lines[index].strip()
                if not stripped:
                    index += 1
                    continue
                if _is_detail_section_boundary(stripped):
                    break
                if stripped.startswith("*") and not PRODUCT_DETAIL_BULLET_PATTERN.match(
                    stripped
                ):
                    items.append(re.sub(r"^\*\s*", "", stripped).strip())
                    index += 1
                    continue
                break
            for item in items:
                result.append(f"* {item}")
            result.append("")
            continue

    return "\n".join(result).strip() + "\n"


def _collect_detail_paragraphs(
    inline_text: str,
    lines: list[str],
    index: int,
) -> tuple[str, int]:
    """Collect multiline detail text until the next section marker."""
    paragraphs: list[str] = []
    if inline_text:
        paragraphs.append(inline_text)
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if _is_detail_section_boundary(stripped):
            break
        if stripped.startswith("*"):
            stripped = re.sub(r"^\*\s*", "", stripped).strip()
        if stripped:
            paragraphs.append(stripped)
        index += 1
    return " ".join(paragraphs), index


def _collect_plain_detail_lines(
    lines: list[str],
    index: int,
) -> tuple[list[str], int]:
    """Collect non-list detail lines following an inline feature bullet."""
    collected: list[str] = []
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if _is_detail_section_boundary(stripped):
            break
        if stripped.startswith("*"):
            break
        collected.append(stripped)
        index += 1
    return collected, index


def _is_detail_section_boundary(stripped: str) -> bool:
    """Return whether a line starts the next Markdown section."""
    if PRODUCT_DETAIL_BULLET_PATTERN.match(stripped):
        return True
    if stripped.startswith("### ") or stripped.startswith("## "):
        return True
    return stripped == "---"


def _append_to_last_feature_section(result: list[str], text: str) -> None:
    """Append beginner guidance text to the most recent 特徴 section."""
    for idx in range(len(result) - 1, -1, -1):
        if result[idx].strip() != "#### 特徴":
            continue
        insert_at = idx + 1
        while insert_at < len(result) and result[insert_at].strip():
            if result[insert_at].startswith("#### "):
                break
            insert_at += 1
        result.insert(insert_at, text)
        return
    result.append(text)


def inject_missing_product_blocks(content: str, blocks: list[ProductBlock]) -> str:
    """Insert affiliate image links before price lists in numbered product sections."""
    if not blocks:
        return content

    lines = content.splitlines()
    result: list[str] = []
    block_index = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        result.append(line)

        if not PRODUCT_SECTION_HEADING_PATTERN.match(line.strip()):
            index += 1
            continue

        section_lines: list[str] = []
        index += 1
        while index < len(lines) and not PRODUCT_SECTION_HEADING_PATTERN.match(
            lines[index].strip()
        ):
            if lines[index].startswith("## ") and not lines[index].startswith("### "):
                break
            section_lines.append(lines[index])
            index += 1

        if block_index >= len(blocks):
            result.extend(section_lines)
            continue

        section_text = "\n".join(section_lines)
        price_line_index = next(
            (
                section_index
                for section_index, section_line in enumerate(section_lines)
                if PRICE_LINE_PATTERN.match(section_line.strip())
            ),
            None,
        )
        if price_line_index is None:
            result.extend(section_lines)
            continue

        block = blocks[block_index]
        block_index += 1
        # Only skip when a countable image affiliate link already exists.
        # Plain URL text alone should not block injection.
        if count_affiliate_image_links(section_text) > 0:
            result.extend(section_lines)
            continue
        result.extend(section_lines[:price_line_index])
        if price_line_index > 0 and section_lines[price_line_index - 1].strip():
            result.append("")
        result.append(format_product_image_link(block))
        result.append("")
        if not re.search(r"^[-*]\s+\*\*商品名\*\*\s*[：:]", section_text, re.MULTILINE):
            result.append(format_product_name_line(block))
            result.append("")
        result.extend(section_lines[price_line_index:])

    return "\n".join(result).strip() + "\n"


def diagnose_product_section_injection(content: str) -> dict[str, int]:
    """Return counts that explain why affiliate injection may under-fill."""
    headings = 0
    headings_with_price = 0
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        if not PRODUCT_SECTION_HEADING_PATTERN.match(lines[index].strip()):
            index += 1
            continue
        headings += 1
        index += 1
        section_lines: list[str] = []
        while index < len(lines) and not PRODUCT_SECTION_HEADING_PATTERN.match(
            lines[index].strip()
        ):
            if lines[index].startswith("## ") and not lines[index].startswith("### "):
                break
            section_lines.append(lines[index])
            index += 1
        if any(PRICE_LINE_PATTERN.match(line.strip()) for line in section_lines):
            headings_with_price += 1
    return {
        "numbered_headings": headings,
        "headings_with_price": headings_with_price,
        "affiliate_image_links": count_affiliate_image_links(content),
    }


def sync_product_section_metadata(
    content: str,
    products: list,
    *,
    is_ranking: bool = False,
) -> str:
    """Replace price and review lines in product sections with catalog values."""
    if not products:
        return content

    lines = content.splitlines()
    result: list[str] = []
    product_index = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        result.append(line)

        if not PRODUCT_SECTION_HEADING_PATTERN.match(line.strip()):
            index += 1
            continue

        section_lines: list[str] = []
        index += 1
        while index < len(lines) and not PRODUCT_SECTION_HEADING_PATTERN.match(
            lines[index].strip()
        ):
            if lines[index].startswith("## ") and not lines[index].startswith("### "):
                break
            section_lines.append(lines[index])
            index += 1

        if product_index >= len(products):
            result.extend(section_lines)
            continue

        section_text = "\n".join(section_lines)
        has_price_line = any(
            PRICE_LINE_PATTERN.match(section_line.strip()) for section_line in section_lines
        )
        if not has_price_line:
            result.extend(section_lines)
            continue

        product = products[product_index]
        product_index += 1
        result.extend(_sync_section_metadata_lines(section_lines, product, is_ranking=is_ranking))

    return "\n".join(result).strip() + "\n"


def _sync_section_metadata_lines(
    section_lines: list[str],
    product,
    *,
    is_ranking: bool,
) -> list[str]:
    """Return section lines with authoritative Rakuten metadata."""
    synced: list[str] = []
    for line in section_lines:
        if PRICE_LINE_PATTERN.match(line.strip()):
            synced.append(f"* **価格**: {product.price:,}円（税込）")
            continue
        if REVIEW_LINE_PATTERN.match(line.strip()):
            review_average = product.review_average if product.review_average else 0.0
            review_count = product.review_count if product.review_count else 0
            if is_ranking:
                synced.append(
                    f"* **レビュー**: {review_average}（{review_count:,}件）"
                )
            else:
                synced.append(
                    f"* **レビュー評価**: {review_average}（件数: {review_count:,}件）"
                )
            continue
        if is_ranking and RECOMMEND_LINE_PATTERN.match(line.strip()):
            score = _ranking_recommend_score(product.rank)
            synced.append(f"* **おすすめ度**: {_format_star_rating(score)} ({score:.1f})")
            continue
        synced.append(line)
    return synced


def _ranking_recommend_score(rank: int) -> float:
    """Return a descending recommend score that matches rank order."""
    if rank <= 0:
        return RANKING_RECOMMEND_SCORES[-1]
    if rank <= len(RANKING_RECOMMEND_SCORES):
        return RANKING_RECOMMEND_SCORES[rank - 1]
    return RANKING_RECOMMEND_SCORES[-1]


def _format_star_rating(score: float) -> str:
    """Return colored star characters for one numeric score."""
    full_stars = min(5, max(0, int(round(score))))
    empty_stars = 5 - full_stars
    return ("★" * full_stars) + ("☆" * empty_stars)


SUMMARY_HEADING_PATTERN = re.compile(r"^##\s*.*まとめ", re.MULTILINE)
NEXT_H2_PATTERN = re.compile(r"^##\s+", re.MULTILINE)
LATIN_BRAND_PATTERN = re.compile(r"[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*")
LATIN_ALIAS_BLOCKLIST = {
    "NEW",
    "PRO",
    "PLUS",
    "SET",
    "USB",
    "LED",
    "UPS",
    "ITEM",
    "HTTP",
    "HTTPS",
    "RIVER",
}


def resolve_products_for_article(
    content: str,
    products: list[RakutenProduct] | None,
    article_type: str,
) -> list[RakutenProduct]:
    """Return Rakuten products from arguments or Markdown blocks."""
    if products:
        return products
    if article_type in {"product", "ranking"}:
        return parse_products_from_markdown(content)
    return []


def build_product_link_aliases(
    products: list[RakutenProduct],
    content: str = "",
) -> list[tuple[str, str]]:
    """Build summary link aliases from product names, sections, and URLs."""
    alias_pairs: list[tuple[str, str, int]] = []

    for product in products:
        if not product.url:
            continue

        section_text = _product_section_text(content, product.url) if content else ""
        full_name = _extract_product_name_from_section(section_text) or product.name
        combined = f"{full_name}\n{section_text}"
        alias_pairs.extend(_collect_alias_pairs(combined, product.url))

    seen_aliases: set[str] = set()
    aliases: list[tuple[str, str]] = []
    for alias, url, _priority in sorted(alias_pairs, key=lambda item: item[2], reverse=True):
        if alias in seen_aliases:
            continue
        seen_aliases.add(alias)
        aliases.append((alias, url))
    return aliases


def _collect_alias_pairs(source_text: str, url: str) -> list[tuple[str, str, int]]:
    """Collect alias candidates from one product's text."""
    alias_pairs: list[tuple[str, str, int]] = []
    name = source_text

    for match in LATIN_BRAND_PATTERN.finditer(name):
        token = match.group(0).strip()
        if len(token) < 3:
            continue
        if token.upper() in LATIN_ALIAS_BLOCKLIST:
            continue
        if " " not in token and len(token) < 6:
            continue
        alias_pairs.append((token, url, len(token)))

    for match in PRODUCT_SECTION_TITLE_PATTERN.finditer(source_text):
        title = match.group(1).strip()
        if len(title) >= 4:
            alias_pairs.append((title, url, len(title)))
            shortened = re.sub(
                r"\s+\d+(?:\.\d+)?(?:Wh|W|Ah)(?:\s*/\s*\d+(?:\.\d+)?(?:Wh|W|Ah))*"
                r"(?:\s+\d+(?:\.\d+)?(?:Wh|W|Ah))*\s*$",
                "",
                title,
            ).strip()
            if shortened and shortened != title and len(shortened) >= 4:
                alias_pairs.append((shortened, url, len(shortened)))

    if "SHELTER" in name or "シェルター" in name:
        if "2人用" in name:
            alias_pairs.append(("SHELTER プレミアム 2人用", url, 18))
            alias_pairs.append(("SHELTER 2人用", url, 12))
        elif "1人用" in name:
            alias_pairs.append(("SHELTER プレミアム 1人用", url, 18))
            alias_pairs.append(("SHELTER 1人用", url, 12))
        alias_pairs.append(("SHELTER", url, len("SHELTER")))

    if "シュラフ" in name:
        alias_pairs.append(("シュラフ付きセット", url, len("シュラフ付きセット")))

    return alias_pairs


def _extract_product_name_from_section(section_text: str) -> str:
    """Return the full product name from a section metadata line."""
    match = PRODUCT_NAME_LINE_PATTERN.search(section_text)
    if not match:
        return ""
    return match.group(1).strip()


def _product_section_text(content: str, url: str) -> str:
    """Return the Markdown section that contains one product affiliate URL."""
    index = content.find(url)
    if index == -1:
        return ""

    section_start = content.rfind("\n### ", 0, index)
    if section_start == -1:
        section_start = max(content.rfind("\n## ", 0, index), 0)

    section_end = len(content)
    next_heading = re.search(r"\n### ", content[index:])
    next_section = re.search(r"\n## ", content[index:])
    if next_heading:
        section_end = min(section_end, index + next_heading.start())
    if next_section:
        section_end = min(section_end, index + next_section.start())

    return content[section_start:section_end]


def link_product_names_in_summary(content: str) -> str:
    """Add Rakuten affiliate links to product names in the summary section."""
    products = parse_products_from_markdown(content)
    if not products:
        return content

    match = SUMMARY_HEADING_PATTERN.search(content)
    if not match:
        return content

    section_start = match.start()
    section_body_start = match.end()
    next_heading = NEXT_H2_PATTERN.search(content, section_body_start)
    section_end = next_heading.start() if next_heading else len(content)

    before = content[:section_start]
    summary_section = content[section_start:section_end]
    after = content[section_end:]
    # まとめは「商品名」表記が中心なので、短いブランド別名より引用名マッチを優先する。
    linked_summary = _link_quoted_product_names(summary_section, products, content)
    return before + linked_summary + after


def _apply_product_links_to_text(
    text: str,
    products: list[RakutenProduct],
    content: str = "",
) -> str:
    """Wrap known product aliases in Markdown affiliate links."""
    linked_text = _link_quoted_product_names(text, products, content)
    for alias, url in build_product_link_aliases(products, content):
        if len(alias) < 4:
            continue
        linked_text = _replace_alias_outside_markdown_links(linked_text, alias, url)
    return linked_text


def _replace_alias_outside_markdown_links(text: str, alias: str, url: str) -> str:
    """Replace an alias only outside existing Markdown links and URLs."""
    parts = re.split(r"(\[[^\]]*\]\([^)]+\)|https?://[^\s)]+)", text)
    pattern = rf"(?<!\[){re.escape(alias)}(?!\]\()"
    replaced: list[str] = []
    for part in parts:
        if part.startswith("[") and "](" in part:
            replaced.append(part)
            continue
        if part.startswith("http://") or part.startswith("https://"):
            replaced.append(part)
            continue
        if f"[{alias}](" in part:
            replaced.append(part)
            continue
        replaced.append(re.sub(pattern, rf"[\g<0>]({url})", part))
    return "".join(replaced)


def _link_quoted_product_names(
    text: str,
    products: list[RakutenProduct],
    content: str,
) -> str:
    """Link product names written inside Japanese quotation marks."""
    product_sources: list[tuple[str, str]] = []
    for product in products:
        if not product.url:
            continue
        section_text = _product_section_text(content, product.url) if content else ""
        full_name = _extract_product_name_from_section(section_text) or product.name
        product_sources.append((f"{full_name}\n{section_text}", product.url))

    def replace_quote(match: re.Match[str]) -> str:
        quoted = match.group(1).strip()
        if not quoted or match.group(0).startswith("「["):
            return match.group(0)
        best_url = ""
        best_score = 0
        for source_text, url in product_sources:
            score = _quote_match_score(quoted, source_text)
            if score > best_score:
                best_score = score
                best_url = url
        if not best_url or best_score < 2:
            return match.group(0)
        return f"「[{quoted}]({best_url})」"

    return QUOTED_PRODUCT_NAME_PATTERN.sub(replace_quote, text)


def _quote_match_score(quote: str, source_text: str) -> int:
    """Score how well a quoted summary name matches one product section."""
    cleaned_quote = re.sub(r"[（(].*?[）)]", "", quote).strip()
    if cleaned_quote and cleaned_quote in source_text:
        return len(cleaned_quote) + 100
    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9]+|[\u3040-\u30ff\u4e00-\u9fff]+", cleaned_quote)
        if len(token) >= 2
    ]
    if not tokens:
        return 0
    if all(token in source_text for token in tokens):
        return sum(len(token) for token in tokens)
    return 0


def extract_product_blocks_from_wordpress_html(html: str) -> list[ProductBlock]:
    """Extract Rakuten product blocks from saved WordPress HTML."""
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[ProductBlock] = []

    for heading in soup.find_all("h3"):
        heading_text = heading.get_text(strip=True)
        if not re.match(r"^\d+\.", heading_text):
            continue

        image_link = None
        for node in heading.find_all_next():
            if node.name in ("h2", "h3") and node is not heading:
                break
            if node.name != "a":
                continue
            href = str(node.get("href", ""))
            if AFFILIATE_URL_MARKER not in href or not node.find("img"):
                continue
            image_link = node
            break

        if image_link is None:
            continue

        image = image_link.find("img")
        if image is None:
            continue

        price = review_average = review_count = None
        for node in image_link.find_all_next():
            if node.name in ("h2", "h3"):
                break
            if node.name not in ("ul", "ol"):
                continue
            text = node.get_text(" ", strip=True)
            price_match = re.search(r"(\d[\d,]*)\s*円", text)
            review_match = re.search(
                r"(\d+\.\d+).*?件数:\s*([\d,]+)\s*件",
                text,
            )
            if price_match:
                price = price_match.group(1)
            if review_match:
                review_average = review_match.group(1)
                review_count = review_match.group(2)
            break

        blocks.append(
            ProductBlock(
                name=str(image.get("alt") or heading_text),
                url=str(image_link.get("href", "")),
                image_url=str(image.get("src", "")),
                price=price,
                review_average=review_average,
                review_count=review_count,
            )
        )

    return blocks
