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
    r"\*\s+\*\*価格\*\*:\s*(?P<price>[^\n]+)\n"
    r"\*\s+\*\*レビュー(?:評価)?\*\*:\s*(?P<review>[0-9.]+)[^\n]*件数:\s*(?P<count>[0-9,]+)\s*件",
    re.DOTALL,
)
PRICE_LINE_PATTERN = re.compile(r"^\*\s+\*\*価格\*\*:")
PRODUCT_SECTION_HEADING_PATTERN = re.compile(r"^###\s+(?:\d+\.|\d+位)")
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
    return HTML_PRODUCT_LINK_PATTERN.sub(
        r"[![\g<name>](\g<img>)](\g<url>)",
        content,
    )


def count_affiliate_image_links(content: str) -> int:
    """Return how many Rakuten affiliate image links exist in Markdown or HTML."""
    normalized = normalize_affiliate_blocks_in_markdown(content)
    return len(PRODUCT_IMAGE_LINK_PATTERN.findall(normalized))


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
                name=match.group("name"),
                price=int(price_digits) if price_digits else 0,
                url=match.group("url"),
                image_url=match.group("img"),
                review_average=float(match.group("review")),
                review_count=int(count_digits) if count_digits else 0,
            )
        )
    return products


def format_product_image_link(block: ProductBlock) -> str:
    """Return one Markdown affiliate image link line."""
    return f"[![{block.name}]({block.image_url})]({block.url})"


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
        if AFFILIATE_URL_MARKER in section_text or PRODUCT_IMAGE_LINK_PATTERN.search(
            section_text
        ):
            result.extend(section_lines)
            continue

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
        result.extend(section_lines[:price_line_index])
        if price_line_index > 0 and section_lines[price_line_index - 1].strip():
            result.append("")
        result.append(format_product_image_link(block))
        result.append("")
        result.extend(section_lines[price_line_index:])

    return "\n".join(result).strip() + "\n"


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
