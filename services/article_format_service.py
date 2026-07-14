"""Article type specific HTML formatting service."""

from dataclasses import dataclass
import re

from bs4 import BeautifulSoup, Tag
import markdown


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


class ArticleFormatService:
    """Format generated Markdown into WordPress-friendly HTML by article type."""

    def format_article(self, article_type: str, markdown_content: str) -> str:
        """Return formatted HTML for one article type."""
        # Geminiの出力はMarkdownで残し、WordPressへ送る直前だけHTMLレイアウトへ変換する。
        article_format = _get_article_format(article_type)
        cleaned_content = clean_generated_markdown(markdown_content)
        body_html = _markdown_to_html(cleaned_content)
        return _apply_article_layout(body_html, article_format)


def markdown_to_wordpress_html(content: str, article_type: str = "default") -> str:
    """Convert Markdown content into formatted WordPress HTML."""
    # 既存コードからも呼びやすいように、関数形式の入口も用意する。
    return ArticleFormatService().format_article(article_type, content)


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
    return "\n".join(lines).strip()


def _get_article_format(article_type: str) -> ArticleFormat:
    """Return layout settings for an article type."""
    formats = {
        "problem": ArticleFormat(
            article_type="problem",
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


def _apply_article_layout(body_html: str, article_format: ArticleFormat) -> str:
    """Apply an article-type layout wrapper to generated HTML."""
    soup = BeautifulSoup(body_html, "html.parser")
    _add_common_classes(soup)
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
            '<header class="affiliate-article__header">',
            f'<p class="affiliate-article__type">{article_format.label}</p>',
            f'<p class="affiliate-article__description">{article_format.description}</p>',
            "</header>",
            '<div class="affiliate-article__body">',
            body,
            "</div>",
            "</article>",
        ]
    )


def _add_common_classes(soup: BeautifulSoup) -> None:
    """Add common CSS classes to converted Markdown HTML."""
    for heading in soup.find_all("h2"):
        _append_class(heading, "affiliate-section-heading")
        _mark_emergency_heading(heading)
    for heading in soup.find_all("h3"):
        _append_class(heading, "affiliate-subheading")
        _mark_emergency_heading(heading)
    for table in soup.find_all("table"):
        _append_class(table, "affiliate-comparison-table")
    for link in soup.find_all("a"):
        _append_class(link, "affiliate-link")
        _append_class(link, "affiliate-button")


def _add_article_type_classes(soup: BeautifulSoup, article_type: str) -> None:
    """Add CSS classes that reflect the role of each article type."""
    if article_type == "problem":
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


def _mark_headings(soup: BeautifulSoup, keyword: str, class_name: str) -> None:
    """Add a class to sections whose heading contains a keyword."""
    for heading in soup.find_all(["h2", "h3"]):
        if keyword in heading.get_text(strip=True):
            _append_class(heading, class_name)


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


def _article_style_block() -> str:
    """Return scoped CSS for the affiliate article layout."""
    # 青を信頼感のあるメインカラー、オレンジを行動ボタン、赤を緊急情報に限定して使う。
    return """<style>
.affiliate-article {
  --main-blue: #1e5aa8;
  --main-blue-dark: #17457f;
  --soft-blue: #eef6ff;
  --soft-gray: #f6f7f9;
  --border-gray: #e3e7ee;
  --button-orange: #f28c28;
  --button-orange-dark: #d96f08;
  --emergency-red: #d93025;
  background: #ffffff;
  color: #1f2933;
  line-height: 1.9;
  padding: 24px;
  border: 1px solid var(--border-gray);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(30, 90, 168, 0.08);
}
.affiliate-article__header {
  background: linear-gradient(135deg, var(--main-blue), var(--main-blue-dark));
  color: #ffffff;
  padding: 20px;
  border-radius: 14px;
  margin-bottom: 28px;
}
.affiliate-article__type {
  display: inline-block;
  background: rgba(255, 255, 255, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.38);
  border-radius: 999px;
  padding: 4px 14px;
  margin: 0 0 10px;
  font-weight: 700;
}
.affiliate-article__description {
  margin: 0;
}
.affiliate-article__body {
  background: var(--soft-gray);
  padding: 20px;
  border-radius: 14px;
}
.affiliate-article__body > p,
.affiliate-article__body > ul,
.affiliate-article__body > ol,
.affiliate-article__body > table {
  background: #ffffff;
  border-radius: 12px;
  padding: 16px;
}
.affiliate-section-heading {
  color: var(--main-blue);
  background: var(--soft-blue);
  border-left: 6px solid var(--main-blue);
  padding: 12px 16px;
  border-radius: 10px;
  margin-top: 32px;
}
.affiliate-subheading {
  color: var(--main-blue-dark);
  border-bottom: 2px solid var(--border-gray);
  padding-bottom: 6px;
}
.affiliate-button {
  display: inline-block;
  background: var(--button-orange);
  color: #ffffff !important;
  padding: 10px 16px;
  border-radius: 999px;
  text-decoration: none;
  font-weight: 700;
  box-shadow: 0 4px 12px rgba(242, 140, 40, 0.24);
}
.affiliate-button:hover {
  background: var(--button-orange-dark);
  color: #ffffff !important;
}
.emergency-section {
  color: var(--emergency-red) !important;
  background: #fff3f2 !important;
  border-left-color: var(--emergency-red) !important;
}
.affiliate-comparison-table {
  width: 100%;
  border-collapse: collapse;
  overflow: hidden;
}
.affiliate-comparison-table th {
  background: var(--main-blue);
  color: #ffffff;
}
.affiliate-comparison-table th,
.affiliate-comparison-table td {
  border: 1px solid var(--border-gray);
  padding: 10px;
}
</style>"""


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
