"""Article type specific HTML formatting service."""

from dataclasses import dataclass
import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
import markdown

from providers.rakuten_provider import RakutenProduct
from services.calendar_year_normalizer import normalize_article_calendar_year
from services.markdown_product_block_service import (
    link_product_names_in_summary,
    normalize_affiliate_blocks_in_markdown,
    resolve_products_for_article,
)
from services.article_toc_service import (
    convert_detail_subheadings,
    normalize_list_entry_headings,
)


@dataclass(frozen=True)
class ArticleFormat:
    """Display settings for one article type."""

    # article_typeはproblem/product/rankingのような記事種別。
    article_type: str
    # labelはWordPress側で見た時に分かりやすい表示名。
    label: str
    # descriptionは記事上部に表示する短い説明文。
    description: str
    # wrapper_classはCSSで記事タイプごとの見た目を変えるためのclass。
    wrapper_class: str


@dataclass(frozen=True)
class ProductAffiliate:
    """Affiliate link and image information for one product."""

    # nameは楽天APIから取得した商品名。本文との照合に使う。
    name: str
    # urlは楽天アフィリエイトURL。
    url: str
    # image_urlは記事内に表示する楽天商品画像。
    image_url: str | None
    # priceは楽天APIから取得した商品価格。取れない場合はNone。
    price: int | None = None
    # review_averageは楽天レビュー平均。取れない場合はNone。
    review_average: float | None = None
    # review_countは楽天レビュー件数。取れない場合はNone。
    review_count: int | None = None


class ArticleFormatService:
    """Format generated Markdown into WordPress-friendly HTML by article type."""

    def format_article(
        self,
        article_type: str,
        markdown_content: str,
        products: list[RakutenProduct] | None = None,
    ) -> str:
        """Return formatted HTML for one article type."""
        # Geminiの出力はMarkdownで残し、WordPressへ送る直前だけHTMLレイアウトへ変換する。
        article_format = _get_article_format(article_type)
        cleaned_content = clean_generated_markdown(
            normalize_affiliate_blocks_in_markdown(markdown_content)
        )
        if article_type in {"product", "ranking"}:
            cleaned_content = link_product_names_in_summary(cleaned_content)
        body_html = _markdown_to_html(cleaned_content)
        product_affiliates = _build_product_affiliates(
            resolve_products_for_article(cleaned_content, products, article_type)
        )
        return _apply_article_layout(body_html, article_format, product_affiliates)


def markdown_to_wordpress_html(
    content: str,
    article_type: str = "default",
    products: list[RakutenProduct] | None = None,
) -> str:
    """Convert Markdown content into formatted WordPress HTML."""
    # 既存コードからも呼びやすいように、関数形式の入口も用意する。
    return ArticleFormatService().format_article(article_type, content, products)


def clean_generated_markdown(content: str) -> str:
    """Remove generated metadata wrappers before HTML formatting."""
    # SEOメタ情報やコードフェンスは管理用なので、本文HTMLには含めない。
    lines = content.strip().splitlines()
    for _ in range(4):
        previous_lines = lines
        lines = _strip_json_metadata_block(lines)
        lines = _strip_front_matter_block(lines)
        lines = _strip_wrapping_code_fence(lines)
        lines = _strip_labeled_metadata_lines(lines)
        if lines == previous_lines:
            break
    cleaned = "\n".join(lines).strip()
    cleaned = ensure_markdown_heading_separators(cleaned)
    return normalize_article_calendar_year(cleaned)


_HEADING_SECTION_SPLIT = re.compile(r"(?=^#{2,3} )", re.MULTILINE)
_LIST_LINE_PATTERN = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")


def ensure_paragraph_blank_lines(content: str) -> str:
    """Ensure a blank line between consecutive lines that should be separate paragraphs.

    Markdownでは単一改行だと同一段落になるため、本文の改行は空行付きにする。
    """
    if not content or not content.strip():
        return content

    lines = content.splitlines()
    result: list[str] = []
    in_code_fence = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            result.append(line)
            continue
        if in_code_fence:
            result.append(line)
            continue

        if not result:
            result.append(line)
            continue

        prev = result[-1]
        prev_stripped = prev.strip()
        if not prev_stripped or not stripped:
            result.append(line)
            continue

        if _should_insert_paragraph_blank_line(prev_stripped, stripped):
            result.append("")
        result.append(line)

    normalized = "\n".join(result)
    if content.endswith("\n"):
        return normalized + "\n"
    return normalized


def _should_insert_paragraph_blank_line(prev: str, curr: str) -> bool:
    """Return whether a blank line should separate two non-empty Markdown lines."""
    if prev == "---" or curr == "---":
        return False
    if prev.startswith("|") and curr.startswith("|"):
        return False
    if _LIST_LINE_PATTERN.match(prev) and _LIST_LINE_PATTERN.match(curr):
        return False
    # リスト行の直後1行だけは同一項目の続きとして残す。
    if _LIST_LINE_PATTERN.match(prev) and not curr.startswith(("#", "|", "<")):
        return False
    if prev.startswith("<") and curr.startswith("<"):
        return False
    return True


def ensure_markdown_heading_separators(content: str) -> str:
    """Ensure `---` separators after intro and each H2/H3 section.

    FAQセクション内の各質問H3の間には入れず、FAQブロック全体の末尾だけに入れる。
    """
    if not content or not content.strip():
        return content

    prefix, body = _split_leading_front_matter(content)
    body = body.strip("\n")
    if not body.strip():
        return content if content.endswith("\n") else f"{content.rstrip()}\n"

    parts = _HEADING_SECTION_SPLIT.split(body)
    normalized_parts: list[str] = []
    in_faq_section = False

    for part in parts:
        part = part.strip("\n")
        if not part.strip():
            continue
        part = re.sub(r"(?:\n[ \t]*---[ \t]*)+\s*$", "", part).rstrip()
        if not part:
            continue

        first_line = part.splitlines()[0].strip()
        is_h2 = first_line.startswith("## ") and not first_line.startswith("### ")
        is_h3 = first_line.startswith("### ")
        is_faq_h2 = is_h2 and _is_faq_heading_text(first_line)

        if is_h2 and in_faq_section and not is_faq_h2:
            # FAQブロック終了 → 末尾にだけ区切り線を付ける
            _append_trailing_separator(normalized_parts)
            in_faq_section = False

        if is_faq_h2:
            in_faq_section = True
            normalized_parts.append(part)
            continue

        if in_faq_section and is_h3:
            if normalized_parts:
                normalized_parts[-1] = f"{normalized_parts[-1].rstrip()}\n\n{part}"
            else:
                normalized_parts.append(part)
            continue

        normalized_parts.append(_with_section_separator(part))

    if in_faq_section:
        _append_trailing_separator(normalized_parts)

    normalized_body = "\n\n".join(normalized_parts).rstrip() + "\n"
    normalized_body = ensure_paragraph_blank_lines(normalized_body)
    if not prefix:
        return normalized_body
    return f"{prefix.rstrip()}\n\n{normalized_body}"


_INLINE_RELATED_TAIL_PATTERN = re.compile(
    r"(?:\n[ \t]*---[ \t]*)*"
    r"(?:\n*<div class=\"affiliate-inline-related\"[^>]*>.*?</div>[ \t]*)+"
    r"(?:\n[ \t]*---[ \t]*)*"
    r"\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _with_section_separator(part: str) -> str:
    """Append section separator, placing it before any related-link box."""
    part = re.sub(r"(?:\n[ \t]*---[ \t]*)+\s*$", "", part).rstrip()
    related_match = _INLINE_RELATED_TAIL_PATTERN.search(part)
    if related_match:
        body = part[: related_match.start()].rstrip()
        related = re.sub(
            r"(?:\n[ \t]*---[ \t]*)+",
            "\n",
            related_match.group(0),
        ).strip()
        if not body:
            return related
        return f"{body}\n\n---\n\n{related}"
    return f"{part}\n\n---"


def _append_trailing_separator(parts: list[str]) -> None:
    """Ensure the last part ends with a single `---` separator."""
    if not parts:
        return
    parts[-1] = _with_section_separator(parts[-1])


def _is_faq_heading_text(heading_line: str) -> bool:
    """Return whether an H2 line is an FAQ section heading."""
    text = heading_line.lstrip("# ").strip()
    return "FAQ" in text.upper() or "よくある質問" in text


def _split_leading_front_matter(content: str) -> tuple[str, str]:
    """Split a leading YAML front matter block from Markdown body."""
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", content

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            prefix = "".join(lines[: index + 1])
            body = "".join(lines[index + 1 :])
            return prefix, body
    return "", content


def _get_article_format(article_type: str) -> ArticleFormat:
    """Return layout settings for an article type."""
    formats = {
        "problem": ArticleFormat(
            article_type="problem",
            label="悩み解決記事",
            description="読者の悩みを整理し、原因と解決策へ自然につなげる記事です。",
            wrapper_class="affiliate-article--problem",
        ),
        "problem_only": ArticleFormat(
            article_type="problem_only",
            label="悩み解決記事",
            description="読者の悩みを整理し、原因と解決策へ自然につなげる記事です。",
            wrapper_class="affiliate-article--problem",
        ),
        "product": ArticleFormat(
            article_type="product",
            label="商品紹介記事",
            description="商品の特徴、選び方、購入前の注意点を整理する記事です。",
            wrapper_class="affiliate-article--product",
        ),
        "ranking": ArticleFormat(
            article_type="ranking",
            label="ランキング記事",
            description="複数商品を比較し、用途別に選びやすくする記事です。",
            wrapper_class="affiliate-article--ranking",
        ),
    }
    return formats.get(
        article_type,
        ArticleFormat(
            article_type=article_type or "default",
            label="記事",
            description="生成された記事本文です。",
            wrapper_class="affiliate-article--default",
        ),
    )


def _markdown_to_html(content: str) -> str:
    """Convert Markdown text to plain HTML."""
    return markdown.markdown(
        content,
        extensions=["extra", "sane_lists", "tables"],
        output_format="html5",
    )


def _apply_article_layout(
    body_html: str,
    article_format: ArticleFormat,
    products: list[ProductAffiliate],
) -> str:
    """Apply an article-type layout wrapper to generated HTML."""
    soup = BeautifulSoup(body_html, "html.parser")
    _add_common_classes(soup, products, article_format.article_type)
    _add_article_type_classes(soup, article_format.article_type)

    body = "\n".join(str(element) for element in soup.contents)
    return "\n".join(
        [
            _article_style_block(),
            (
                '<article class="affiliate-article '
                f'{article_format.wrapper_class}" '
                f'data-article-type="{article_format.article_type}">'
            ),
            '<div class="affiliate-article__body">',
            body,
            "</div>",
            (
                '<script>document.querySelectorAll("details.affiliate-faq-item[open]")'
                '.forEach((item)=>item.removeAttribute("open"));</script>'
            ),
            "</article>",
        ]
    )


def _add_common_classes(
    soup: BeautifulSoup,
    products: list[ProductAffiliate],
    article_type: str,
) -> None:
    """Add common CSS classes to converted Markdown HTML."""
    for heading in soup.find_all("h1"):
        _append_class(heading, "affiliate-article-title")
    for heading in soup.find_all("h2"):
        _append_class(heading, "affiliate-section-heading")
    for heading in soup.find_all("h3"):
        _append_class(heading, "affiliate-subheading")
        _mark_emergency_heading(heading)
    for table in soup.find_all("table"):
        _append_class(table, "affiliate-comparison-table")
    for link in soup.find_all("a"):
        _append_class(link, "affiliate-link")
    _assign_heading_ids(soup)
    convert_detail_subheadings(soup)
    normalize_list_entry_headings(soup)
    _normalize_affiliate_links(soup)
    _build_existing_product_cards(soup, article_type)
    _highlight_star_ratings(soup)
    _add_product_link_buttons(soup, products, article_type)
    _convert_faq_sections(soup)
    _style_inline_related_boxes(soup)
    _apply_inline_visual_styles(soup)


def _add_article_type_classes(soup: BeautifulSoup, article_type: str) -> None:
    """Add CSS classes that reflect the role of each article type."""
    if article_type in {"problem", "problem_only"}:
        _mark_headings(soup, "悩み", "problem-section")
        _mark_headings(soup, "原因", "cause-section")
        _mark_headings(soup, "解決", "solution-section")
    elif article_type == "product":
        _mark_headings(soup, "おすすめ", "product-pickup-section")
        _mark_headings(soup, "商品", "product-detail-section")
        _mark_headings(soup, "メリット", "product-merit-section")
    elif article_type == "ranking":
        _mark_headings(soup, "ランキング", "ranking-section")
        _mark_headings(soup, "比較", "comparison-section")
        _mark_headings(soup, "1位", "ranking-top-section")


def _mark_headings(
    soup: BeautifulSoup,
    keyword: str,
    class_name: str,
    tags: tuple[str, ...] = ("h3",),
) -> None:
    """Add a class to sections whose heading contains a keyword."""
    for heading in soup.find_all(list(tags)):
        if keyword in heading.get_text(strip=True):
            _append_class(heading, class_name)


def _assign_heading_ids(soup: BeautifulSoup) -> None:
    """Assign stable IDs to headings so TOC links can jump to sections."""
    used_ids: set[str] = set()
    for index, heading in enumerate(soup.find_all(["h2", "h3"]), start=1):
        heading_id = _slugify_heading(heading.get_text(strip=True), index)
        while heading_id in used_ids:
            heading_id = f"{heading_id}-{index}"
        heading["id"] = heading_id
        used_ids.add(heading_id)


def _slugify_heading(text: str, fallback_index: int) -> str:
    """Return a safe heading ID for in-page links."""
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if ascii_slug:
        return ascii_slug
    return f"section-{fallback_index}"


def _mark_emergency_heading(heading: Tag) -> None:
    """Mark urgent headings with a red accent class."""
    # 赤は使いすぎると読みにくいため、緊急性が高い見出しだけに付ける。
    text = heading.get_text(strip=True)
    emergency_keywords = ("緊急", "注意", "重要", "避難", "災害時", "命")
    if any(keyword in text for keyword in emergency_keywords):
        _append_class(heading, "emergency-section")


def _append_class(tag: Tag, class_name: str) -> None:
    """Append a CSS class to a BeautifulSoup tag."""
    classes = list(tag.get("class", []))
    if class_name not in classes:
        classes.append(class_name)
    tag["class"] = classes


def _add_product_link_buttons(
    soup: BeautifulSoup,
    products: list[ProductAffiliate],
    article_type: str,
) -> None:
    """Append product affiliate buttons where known product names appear."""
    if article_type != "problem":
        return

    # 悩み記事のように商品名だけが出ている箇所へ、楽天APIの商品リンクを補う。
    for product in products:
        for list_item in soup.find_all("li"):
            item_text = list_item.get_text(" ", strip=True)
            if not _matches_product(item_text=item_text, product_name=product.name):
                continue
            if list_item.find("a", href=product.url):
                continue

            mini_card = soup.new_tag("div")
            mini_card["class"] = ["affiliate-product-mini-card"]
            if product.image_url:
                image_box = soup.new_tag("div")
                image_box["class"] = ["affiliate-product-image-box"]
                image = soup.new_tag(
                    "img",
                    src=product.image_url,
                    alt=product.name,
                )
                image["class"] = ["affiliate-product-image"]
                image["loading"] = "lazy"
                image_box.append(image)
                mini_card.append(image_box)

            detail_box = soup.new_tag("div")
            detail_box["class"] = ["affiliate-product-detail-box"]
            for meta_text in _product_meta_lines(product):
                meta = soup.new_tag("p")
                meta["class"] = ["affiliate-product-meta"]
                meta.string = meta_text
                detail_box.append(meta)

            cta = soup.new_tag("p")
            cta["class"] = ["affiliate-product-cta"]
            link = soup.new_tag("a", href=product.url)
            link["class"] = ["affiliate-product-button"]
            link["target"] = "_blank"
            link["rel"] = "sponsored noopener"
            link.string = "楽天市場で探す>"
            cta.append(link)
            _style_product_button(link)
            detail_box.append(cta)
            mini_card.append(detail_box)
            list_item.append(mini_card)


def _build_product_affiliates(products: list[RakutenProduct]) -> list[ProductAffiliate]:
    """Build affiliate display data from Rakuten API products."""
    return [
        ProductAffiliate(
            name=product.name,
            url=product.url,
            image_url=product.image_url,
            price=product.price,
            review_average=product.review_average,
            review_count=product.review_count,
        )
        for product in products
        if product.name and product.url
    ]


def _matches_product(item_text: str, product_name: str) -> bool:
    """Return whether a list item appears to mention a Rakuten product."""
    normalized_item = _normalize_product_text(item_text)
    normalized_product = _normalize_product_text(product_name)
    if not normalized_item or not normalized_product:
        return False
    if normalized_item in normalized_product or normalized_product in normalized_item:
        return True

    product_tokens = _important_product_tokens(normalized_product)
    if not product_tokens:
        return False
    matched_tokens = [token for token in product_tokens if token in normalized_item]
    return len(matched_tokens) >= min(2, len(product_tokens))


def _normalize_product_text(value: str) -> str:
    """Normalize product text for loose matching."""
    return re.sub(r"\s+", " ", value.lower()).strip()


def _important_product_tokens(value: str) -> list[str]:
    """Return useful tokens for matching generated text to product names."""
    raw_tokens = re.split(r"[\s\[\]【】（）()・,、/／|｜:：\-]+", value)
    stop_words = {
        "セット",
        "防災",
        "リュック",
        "用品",
        "グッズ",
        "送料無料",
        "税込",
        "用",
    }
    return [
        token
        for token in raw_tokens
        if len(token) >= 2 and token not in stop_words and not token.isdigit()
    ][:6]


def _product_meta_lines(product: ProductAffiliate) -> list[str]:
    """Return product metadata lines for the mini card."""
    lines: list[str] = []
    if product.price is not None and product.price > 0:
        lines.append(f"価格: {product.price:,}円")
    if product.review_average is not None:
        if product.review_count is not None:
            lines.append(f"評価: {product.review_average} / 件数: {product.review_count:,}件")
        else:
            lines.append(f"評価: {product.review_average}")
    return lines


def _normalize_affiliate_links(soup: BeautifulSoup) -> None:
    """Normalize Rakuten affiliate links to a consistent button style."""
    for link in soup.find_all("a", href=True):
        href = str(link.get("href", ""))
        if "hb.afl.rakuten.co.jp" not in href:
            continue

        link["target"] = "_blank"
        link["rel"] = "sponsored noopener"
        if link.find("img"):
            _append_class(link, "affiliate-product-image-link")
            continue

        if not _is_product_metadata_link(link):
            # 用途別の本文リンクは、商品名テキストのまま通常リンクとして残す。
            continue

        link.clear()
        link.string = "楽天市場で探す>"
        _append_class(link, "affiliate-product-button")
        _style_product_button(link)
        _remove_product_link_label(link)


def _is_product_metadata_link(link: Tag) -> bool:
    """Return whether a link belongs to a product metadata list."""
    list_item = link.find_parent("li")
    if list_item is None:
        return False
    item_text = list_item.get_text(" ", strip=True)
    if "詳細リンク" in item_text or "商品リンク" in item_text:
        return True

    parent_list = list_item.find_parent(["ul", "ol"])
    return isinstance(parent_list, Tag) and _looks_like_product_meta(parent_list)


def _remove_product_link_label(link: Tag) -> None:
    """Remove labels such as '詳細リンク:' and leave only the product button."""
    list_item = link.find_parent("li")
    if list_item is None:
        return
    item_text = list_item.get_text(" ", strip=True)
    if "詳細リンク" not in item_text and "商品リンク" not in item_text:
        return

    cleaned_link = link.extract()
    list_item.clear()
    _append_class(list_item, "affiliate-product-link-item")
    list_item.append(cleaned_link)


def _build_existing_product_cards(soup: BeautifulSoup, article_type: str) -> None:
    """Turn existing product image and metadata blocks into side-by-side cards."""
    for image_link in list(soup.find_all("a", href=True)):
        if "hb.afl.rakuten.co.jp" not in str(image_link.get("href", "")):
            continue
        if not image_link.find("img"):
            continue

        image_container = image_link.find_parent("p") or image_link
        if image_container.find_parent(class_="affiliate-product-card"):
            continue

        meta_list = _find_following_meta_list(image_container)
        if meta_list is None:
            continue

        meta_only_list, detail_nodes = _split_product_metadata_list(soup, meta_list)
        if meta_only_list is None:
            continue

        card = soup.new_tag("div")
        card["class"] = ["affiliate-product-card", f"affiliate-product-card--{article_type}"]

        image_column = soup.new_tag("div")
        image_column["class"] = ["affiliate-product-card__image"]

        detail_column = soup.new_tag("div")
        detail_column["class"] = ["affiliate-product-card__detail"]
        product_url = str(image_link.get("href", ""))

        card.append(image_column)
        card.append(detail_column)
        image_container.insert_before(card)
        image_column.append(image_container.extract())
        detail_column.append(meta_only_list)
        _ensure_product_card_cta(soup, detail_column, product_url)
        _insert_nodes_after(card, detail_nodes)
        _remove_clear_div_after(image_container)
        if meta_list.parent and not meta_list.find_all("li"):
            meta_list.decompose()


def _split_product_metadata_list(
    soup: BeautifulSoup,
    meta_list: Tag,
) -> tuple[Tag | None, list[Tag]]:
    """Keep price/review metadata in the card and move detail sections outside it."""
    meta_items: list[Tag] = []
    detail_nodes: list[Tag] = []

    for list_item in list(meta_list.find_all("li", recursive=False)):
        label = _extract_product_detail_label(list_item.get_text(" ", strip=True))
        if label in _PRODUCT_DETAIL_LABELS:
            detail_nodes.extend(_convert_detail_list_item(soup, list_item, label))
            continue
        if _is_product_meta_list_item(list_item.get_text(" ", strip=True)):
            meta_items.append(list_item.extract())
            continue
        detail_nodes.append(list_item.extract())

    if not meta_items:
        return None, detail_nodes

    meta_only_list = soup.new_tag("ul")
    for item in meta_items:
        meta_only_list.append(item)
    return meta_only_list, detail_nodes


_PRODUCT_DETAIL_LABELS = ("特徴", "メリット", "デメリット", "初心者向け説明")
_PRODUCT_META_LABELS = (
    "商品名",
    "価格",
    "通常価格",
    "参考価格",
    "レビュー",
    "おすすめ度",
    "詳細リンク",
    "寄付金額",
)


def _extract_product_detail_label(text: str) -> str | None:
    """Return a product detail label when a list item uses the inline bullet format."""
    cleaned = text.strip()
    for label in _PRODUCT_DETAIL_LABELS:
        if cleaned.startswith(label):
            return label
    return None


def _is_product_meta_list_item(text: str) -> bool:
    """Return whether one list item belongs inside the product metadata card."""
    return any(label in text for label in _PRODUCT_META_LABELS)


def _convert_detail_list_item(
    soup: BeautifulSoup,
    list_item: Tag,
    label: str,
) -> list[Tag]:
    """Convert inline detail bullets into styled blocks outside the product card."""
    nodes: list[Tag] = []
    if label != "初心者向け説明":
        heading = soup.new_tag("p")
        heading["class"] = ["affiliate-detail-heading"]
        strong = soup.new_tag("strong")
        strong.string = label
        heading.append(strong)
        nodes.append(heading)

    item_text = list_item.get_text(" ", strip=True)
    inline_text = re.sub(rf"^{re.escape(label)}(?:[:：]\s*)?", "", item_text).strip()
    nested_list = list_item.find(["ul", "ol"])
    if inline_text and label in {"特徴", "初心者向け説明"}:
        paragraph = soup.new_tag("p")
        paragraph.string = inline_text
        nodes.append(paragraph)
    if nested_list is not None:
        nodes.append(nested_list.extract())
    list_item.decompose()
    return nodes


def _insert_nodes_after(anchor: Tag, nodes: list[Tag]) -> None:
    """Insert converted detail nodes immediately after one anchor element."""
    insert_after = anchor
    for node in nodes:
        insert_after.insert_after(node)
        insert_after = node


def _find_following_meta_list(start: Tag) -> Tag | None:
    """Find the nearest product metadata list after an image block."""
    for sibling in start.find_all_next():
        if not isinstance(sibling, Tag):
            continue
        if sibling.name in ("h2", "h3", "h4", "hr"):
            return None
        if sibling.name in ("ul", "ol") and _looks_like_product_meta(sibling):
            return sibling
    return None


def _looks_like_product_meta(tag: Tag) -> bool:
    """Return whether a list contains product price/review/link metadata."""
    text = tag.get_text(" ", strip=True)
    keywords = ("価格", "レビュー", "評価", "おすすめ度", "詳細リンク", "寄付金額")
    return any(keyword in text for keyword in keywords)


def _remove_clear_div_after(tag: Tag) -> None:
    """Remove old float-clearing divs after converting image blocks to cards."""
    next_tag = tag.find_next_sibling()
    if isinstance(next_tag, Tag) and next_tag.name == "div":
        style = str(next_tag.get("style", ""))
        if "clear" in style:
            next_tag.decompose()


def _ensure_product_card_cta(soup: BeautifulSoup, detail_column: Tag, product_url: str) -> None:
    """Add a Rakuten button to product cards that only had an image link."""
    if not product_url or detail_column.find("a", class_="affiliate-product-button"):
        return

    cta = soup.new_tag("p")
    cta["class"] = ["affiliate-product-cta"]
    link = soup.new_tag("a", href=product_url)
    link["class"] = ["affiliate-product-button"]
    link["target"] = "_blank"
    link["rel"] = "sponsored noopener"
    link.string = "楽天市場で探す>"
    cta.append(link)
    _style_product_button(link)
    detail_column.append(cta)


def _highlight_star_ratings(soup: BeautifulSoup) -> None:
    """Wrap star rating characters so they can be colored yellow."""
    star_pattern = re.compile(r"(★+[☆★]*)")
    for text_node in list(soup.find_all(string=star_pattern)):
        if not isinstance(text_node, NavigableString):
            continue
        text = str(text_node)
        parts = star_pattern.split(text)
        if len(parts) <= 1:
            continue
        fragment = BeautifulSoup("", "html.parser")
        for part in parts:
            if not part:
                continue
            if star_pattern.fullmatch(part):
                span = fragment.new_tag("span")
                span["class"] = ["affiliate-stars"]
                span.string = part
                fragment.append(span)
            else:
                fragment.append(NavigableString(part))
        text_node.replace_with(fragment)


def _style_inline_related_boxes(soup: BeautifulSoup) -> None:
    """Style contextual related-article callout boxes."""
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for text_node in list(soup.find_all(string=True)):
        if not isinstance(text_node, NavigableString) or isinstance(text_node, Comment):
            continue
        if "affiliate-inline-related:" not in str(text_node):
            continue
        cleaned = ORPHAN_INLINE_MARKER_PATTERN.sub("", str(text_node))
        if cleaned.strip():
            text_node.replace_with(NavigableString(cleaned))
        else:
            text_node.extract()
    for box in soup.find_all("div", class_="affiliate-inline-related"):
        for link in box.find_all("a", href=True):
            _append_class(link, "affiliate-link")


def _convert_faq_sections(soup: BeautifulSoup) -> None:
    """Convert FAQ question headings into collapsible answer blocks."""
    for heading in list(soup.find_all(["h3", "h4"])):
        if not _is_faq_question_heading(heading):
            continue

        details = soup.new_tag("details")
        details["class"] = ["affiliate-faq-item"]
        if heading.get("id"):
            details["id"] = heading["id"]

        summary = soup.new_tag("summary")
        summary["class"] = ["affiliate-faq-question"]
        summary.string = heading.get_text(" ", strip=True)

        answer = soup.new_tag("div")
        answer["class"] = ["affiliate-faq-answer"]

        details.append(summary)
        details.append(answer)
        heading.insert_before(details)

        next_node = heading.next_sibling
        heading.extract()
        while next_node is not None:
            current_node = next_node
            next_node = current_node.next_sibling
            if isinstance(current_node, Tag) and current_node.name in ("h2", "h3", "h4", "hr"):
                break
            answer.append(current_node.extract())


def _is_faq_question_heading(heading: Tag) -> bool:
    """Return whether a heading looks like a FAQ question."""
    text = heading.get_text(" ", strip=True)
    if re.match(r"^Q\d*[\.\s:：]", text, flags=re.IGNORECASE):
        return True
    # SEO向けに「〜ですか？」形式の見出しも、FAQセクション配下なら折りたたみ対象にする。
    if ("？" in text or "?" in text) and _is_under_faq_section(heading):
        return True
    return False


def _is_under_faq_section(heading: Tag) -> bool:
    """Return whether the heading sits under an FAQ H2 section."""
    for sibling in heading.previous_siblings:
        if not isinstance(sibling, Tag) or sibling.name != "h2":
            continue
        section_title = sibling.get_text(" ", strip=True)
        return "FAQ" in section_title.upper() or "よくある質問" in section_title
    return False


H1_INLINE_STYLE = "margin:0 0 1.6em;padding:0;"
DETAIL_HEADING_INLINE_STYLE = (
    "border-top:1px solid #e2e8f0;margin:20px 0 10px;padding:16px 0 0;"
)
DETAIL_LABEL_INLINE_STYLE = "font-weight:800;"
PRODUCT_BUTTON_INLINE_STYLE = (
    "display:inline-block;background:#EA7373;color:#ffffff;border:none;"
    "border-radius:0;min-width:190px;padding:6px 24px;text-align:center;"
    "text-decoration:none;font-weight:800;box-shadow:none;"
    "transition:transform 0.2s ease,box-shadow 0.2s ease,background 0.2s ease;"
)
ORPHAN_INLINE_MARKER_PATTERN = re.compile(
    r"<!--\s*affiliate-inline-related:[^>]+-->\s*",
    re.IGNORECASE,
)


def _style_product_button(link: Tag) -> None:
    """Apply inline styles so Rakuten buttons keep their appearance in WordPress."""
    classes = [class_name for class_name in link.get("class", []) if class_name != "affiliate-link"]
    link["class"] = classes
    link["style"] = PRODUCT_BUTTON_INLINE_STYLE


def _apply_inline_visual_styles(soup: BeautifulSoup) -> None:
    """Apply inline styles that survive WordPress content sanitization."""
    # H2/H3の見た目はWordPress追加CSS（article h2 / article h3）に任せる。
    for heading in soup.find_all("h1", class_="affiliate-article-title"):
        heading["style"] = H1_INLINE_STYLE
    for heading in soup.find_all("p", class_="affiliate-detail-heading"):
        heading["style"] = DETAIL_HEADING_INLINE_STYLE
        strong = heading.find("strong")
        if isinstance(strong, Tag):
            strong["style"] = DETAIL_LABEL_INLINE_STYLE
    for link in soup.find_all("a", class_="affiliate-product-button"):
        _style_product_button(link)


def _minify_css(css: str) -> str:
    """Collapse CSS to one line so WordPress does not inject br tags."""
    return re.sub(r"\s+", " ", css.strip())


def _article_style_block() -> str:
    """Return scoped CSS for the affiliate article layout."""
    # WordPressはstyle内の改行をbrへ変換するため、1行CSSで出力する。
    css = """
.affiliate-article {
  --main-blue: #1e5aa8;
  --main-blue-dark: #17457f;
  --blue-muted: #e8f1fb;
  --blue-border: #b9d4f0;
  --blue-link: #2468b2;
  --soft-gray: #f4f7fb;
  --border-gray: #d9e3ef;
  --emergency-red: #d93025;
  background: #ffffff;
  color: #1f2933;
  font-family: "Noto Sans JP", "Hiragino Sans", "Yu Gothic", Meiryo, sans-serif;
  font-size: 16px;
  line-height: 1.9;
  padding: 34px;
  border: 1px solid var(--border-gray);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(30, 90, 168, 0.08);
}
.affiliate-article__body {
  background: transparent;
  padding: 4px 2px;
  border-radius: 14px;
}
.affiliate-article hr {
  border: none;
  border-top: 1px solid var(--border-gray);
  margin: 20px 0 30px;
}
.affiliate-article__body h1.affiliate-article-title {
  margin: 0 0 1.6em;
  padding: 0;
}
.affiliate-article__body p {
  margin: 0 0 1.35em;
}
.affiliate-article__body ul,
.affiliate-article__body ol {
  margin: 0 0 1.7em;
  padding-left: 1.6em;
}
.affiliate-article__body li {
  margin-bottom: 0.75em;
}
.toc,
.toc-content {
  transition: none !important;
  animation: none !important;
}
.affiliate-inline-related {
  background: var(--blue-muted);
  border: 1px solid var(--blue-border);
  border-left: 4px solid var(--main-blue);
  border-radius: 12px;
  display: block;
  line-height: 1.8;
  margin: 28px 0;
  padding: 14px 18px;
}
.affiliate-inline-related__label {
  color: var(--main-blue-dark);
  font-size: 0.98rem;
  font-weight: 800;
  margin-right: 0.35em;
}
.affiliate-inline-related a.affiliate-link {
  color: var(--blue-link) !important;
  font-weight: 800;
  text-decoration: underline;
  text-underline-offset: 3px;
}
/* H2/H3の色・背景・余白はWordPress追加CSS（article h2 / article h3）に任せる */
.affiliate-article h2.affiliate-section-heading,
.affiliate-section-heading,
.affiliate-article h3.affiliate-subheading,
.affiliate-subheading {
  scroll-margin-top: 90px;
}
.affiliate-list-entry-heading[data-ordinal]::before {
  content: attr(data-ordinal) ". ";
  font-weight: 800;
}
.affiliate-detail-heading {
  border-top: 1px solid #e2e8f0;
  color: #111827;
  font-size: 1rem;
  font-weight: 800;
  margin: 20px 0 10px;
  padding: 16px 0 0;
}
.affiliate-detail-heading strong {
  font-weight: 800;
}
.affiliate-product-cta {
  margin: 14px 0 8px !important;
}
.affiliate-product-card,
.affiliate-product-mini-card {
  align-items: center;
  background: #fafafa;
  border: 1px solid var(--border-gray);
  display: flex;
  gap: 20px;
  margin: 18px 0 24px;
  padding: 18px;
}
.affiliate-product-card__image,
.affiliate-product-image-box {
  flex: 0 0 160px;
  margin: 0;
}
.affiliate-product-card__detail,
.affiliate-product-detail-box {
  flex: 1;
  min-width: 0;
}
.affiliate-product-image {
  display: block;
  max-width: 160px;
  width: 100%;
  height: auto;
  border: 1px solid var(--border-gray);
  background: #ffffff;
  padding: 8px;
  box-shadow: 0 4px 12px rgba(17, 24, 39, 0.08);
}
.affiliate-product-button {
  display: inline-block;
  background: #EA7373;
  color: #ffffff !important;
  border: none;
  border-radius: 0;
  min-width: 190px;
  padding: 6px 24px;
  text-align: center;
  text-decoration: none !important;
  font-weight: 800;
  box-shadow: none;
  transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}
.affiliate-product-button:hover {
  background: #d86565;
  color: #ffffff !important;
  transform: translateY(-3px);
  box-shadow: 0 6px 14px rgba(234, 115, 115, 0.35);
}
.affiliate-product-link-item {
  list-style: none;
  margin-left: 0;
}
.affiliate-product-link-item::marker {
  content: "";
}
.affiliate-link {
  color: var(--blue-link) !important;
  font-weight: 700;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.affiliate-link:hover {
  color: var(--main-blue-dark) !important;
}
.affiliate-faq-item {
  background: #ffffff;
  border: 1px solid var(--border-gray);
  margin: 14px 0;
}
.affiliate-faq-item {
  background: #ffffff;
  border: 1px solid var(--border-gray);
  margin: 14px 0;
}
.affiliate-faq-question {
  background: #eef1f5;
  color: #111827;
  cursor: pointer;
  display: block;
  font-weight: 800;
  list-style: none;
  padding: 14px 16px;
}
.affiliate-faq-question::-webkit-details-marker {
  display: none;
}
.affiliate-faq-question::after {
  content: "+";
  float: right;
  font-weight: 900;
}
.affiliate-faq-item[open] .affiliate-faq-question::after {
  content: "-";
}
.affiliate-faq-answer {
  border-top: 1px solid var(--border-gray);
  padding: 16px;
}
.affiliate-faq-answer > :last-child {
  margin-bottom: 0;
}
.affiliate-stars {
  color: #f5b301;
  font-weight: 900;
  letter-spacing: 0.04em;
}
.affiliate-comparison-table {
  width: 100%;
  border-collapse: collapse;
  overflow: hidden;
  background: #ffffff;
  box-shadow: 0 4px 14px rgba(17, 24, 39, 0.08);
}
.affiliate-comparison-table th {
  background: #4b5563;
  color: #ffffff;
}
.affiliate-comparison-table th,
.affiliate-comparison-table td {
  border: 1px solid #cfd5dd;
  padding: 12px;
  vertical-align: top;
}
.affiliate-comparison-table tr:nth-child(even) td {
  background: #f3f4f6;
}
@media (max-width: 720px) {
  .affiliate-product-card,
  .affiliate-product-mini-card {
    align-items: flex-start;
    flex-direction: column;
  }
  .affiliate-product-card__image,
  .affiliate-product-image-box {
    flex-basis: auto;
  }
}
.sns-share,
.sns-follow {
  display: none !important;
}
"""
    return f"<style>{_minify_css(css)}</style>"


def _strip_wrapping_code_fence(lines: list[str]) -> list[str]:
    """Remove a full Markdown code fence wrapper when Gemini adds one."""
    if not lines:
        return lines

    first_line = lines[0].strip().lower()
    if first_line.startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return lines


def _strip_json_metadata_block(lines: list[str]) -> list[str]:
    """Remove a leading JSON metadata code block."""
    if not lines or not lines[0].strip().startswith("```json"):
        return lines

    for index, line in enumerate(lines[1:], start=1):
        if line.strip().startswith("```"):
            return lines[index + 1 :]
    return lines


def _strip_front_matter_block(lines: list[str]) -> list[str]:
    """Remove a leading YAML-like metadata block."""
    if not lines or lines[0].strip() != "---":
        return lines

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[index + 1 :]
    return lines


def _strip_labeled_metadata_lines(lines: list[str]) -> list[str]:
    """Remove leading SEO label lines such as 'SEOタイトル: ...'."""
    metadata_pattern = re.compile(
        r"^(seo\s*title|seoタイトル|タイトル|meta\s*description|メタディスクリプション|slug|スラッグ)\s*[:：]",
        flags=re.IGNORECASE,
    )

    index = 0
    while index < len(lines):
        stripped_line = lines[index].strip()
        if not stripped_line or stripped_line == "---":
            index += 1
            continue
        if metadata_pattern.match(stripped_line):
            index += 1
            continue
        break
    return lines[index:]
