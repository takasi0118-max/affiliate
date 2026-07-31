"""SEO metadata extraction and checklist service."""

from dataclasses import dataclass
import json
import re


@dataclass(frozen=True)
class SeoAnalysis:
    """SEO information extracted from a generated Markdown article."""

    # Geminiが出力した記事から取り出したSEOメタ情報。
    seo_title: str
    meta_description: str
    slug: str
    # 見出しやFAQの数を数え、最低限の記事構成があるか確認する。
    h2_count: int
    h3_count: int
    faq_count: int
    has_summary: bool

    @property
    def is_ready(self) -> bool:
        """Return whether the article has the minimum SEO elements."""
        # STEP09では、公開前チェックの土台として最低限のSEO要素だけ判定する。
        return all(
            [
                self.seo_title,
                self.meta_description,
                self.slug,
                self.h2_count > 0,
                self.h3_count > 0,
                self.faq_count >= 3,
                self.has_summary,
            ]
        )


def replace_seo_slug(seo: SeoAnalysis, slug: str) -> SeoAnalysis:
    """Return a copy of SeoAnalysis with a forced slug."""
    return SeoAnalysis(
        seo_title=seo.seo_title,
        meta_description=seo.meta_description,
        slug=slug,
        h2_count=seo.h2_count,
        h3_count=seo.h3_count,
        faq_count=seo.faq_count,
        has_summary=seo.has_summary,
    )


class SeoService:
    """Analyze generated Markdown articles for SEO readiness."""

    def analyze_article(self, article: str) -> SeoAnalysis:
        """Extract SEO metadata and checklist values from an article."""
        # Geminiの出力を人が確認しやすいよう、機械的に拾える項目だけを集計する。
        lines = article.splitlines()
        json_metadata = _extract_json_metadata(lines)
        yaml_metadata = _extract_yaml_front_matter(lines)
        return SeoAnalysis(
            seo_title=(
                yaml_metadata.get("seo_title", "")
                or json_metadata.get("title", "")
                or _extract_labeled_value(
                    lines,
                    ("SEOタイトル", "SEO タイトル", "seo title", "seo_title", "title", "タイトル"),
                )
            ),
            meta_description=(
                yaml_metadata.get("meta_description", "")
                or json_metadata.get("description", "")
                or json_metadata.get("meta_description", "")
                or _extract_labeled_value(
                    lines,
                    ("meta description", "meta_description", "メタディスクリプション"),
                )
            ),
            slug=(
                yaml_metadata.get("slug", "")
                or json_metadata.get("slug", "")
                or _extract_labeled_value(lines, ("slug", "スラッグ"))
            ),
            h2_count=sum(1 for line in lines if line.startswith("## ")),
            h3_count=sum(1 for line in lines if line.startswith("### ")),
            faq_count=_count_faq_items(lines),
            has_summary=_has_summary_heading(lines),
        )


def _extract_labeled_value(lines: list[str], labels: tuple[str, ...]) -> str:
    """Extract a value written as 'label: value' from Markdown lines."""
    # SEOタイトル: xxx のような行を探す。全角コロンにも対応する。
    for line in lines:
        normalized_line = line.strip().lstrip("-*").strip()
        for label in labels:
            pattern = rf"^{re.escape(label)}\s*[:：]\s*(.+)$"
            match = re.match(pattern, normalized_line, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
    return ""


def _extract_yaml_front_matter(lines: list[str]) -> dict[str, str]:
    """Extract key-value metadata from a leading YAML front matter block."""
    if not lines or lines[0].strip() != "---":
        return {}

    metadata: dict[str, str] = {}
    for line in lines[1:]:
        stripped_line = line.strip()
        if stripped_line == "---":
            break
        if not stripped_line or stripped_line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.+)$", stripped_line)
        if match:
            metadata[match.group(1).lower()] = match.group(2).strip()
    return metadata


def _extract_json_metadata(lines: list[str]) -> dict[str, str]:
    """Extract SEO metadata when Gemini returns it as a JSON code block."""
    # Geminiは指示通りの「SEOタイトル: ...」ではなく、JSONで返すことがある。
    # その場合もtitle/description/slugを拾えるよう、先頭付近のJSONだけ解析する。
    in_json_block = False
    json_lines: list[str] = []
    for line in lines[:30]:
        stripped_line = line.strip()
        if stripped_line.startswith("```json"):
            in_json_block = True
            json_lines = []
            continue
        if in_json_block and stripped_line.startswith("```"):
            return _parse_json_metadata("\n".join(json_lines))
        if in_json_block:
            json_lines.append(line)

    return {}


def _parse_json_metadata(raw_json: str) -> dict[str, str]:
    """Parse a JSON metadata block into string values."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}

    return {
        str(key): str(value).strip()
        for key, value in data.items()
        if isinstance(key, str) and value is not None
    }


def _count_faq_items(lines: list[str]) -> int:
    """Count likely FAQ questions in an article."""
    faq_count = 0
    in_faq_section = False

    for line in lines:
        stripped_line = line.strip()
        if stripped_line.startswith("## ") and "FAQ" in stripped_line.upper():
            in_faq_section = True
            continue
        if in_faq_section and stripped_line.startswith("## "):
            in_faq_section = False

        # FAQ見出し配下にある「Q:」「Q1:」「？」を質問として数える。
        if in_faq_section and _looks_like_question(stripped_line):
            faq_count += 1

    if faq_count:
        return faq_count

    # FAQ見出しが無い場合でも、記事全体から質問らしい行を拾って最低限判定する。
    return sum(1 for line in lines if _looks_like_question(line.strip()))


def _looks_like_question(line: str) -> bool:
    """Return whether a line looks like an FAQ question."""
    if not line:
        return False
    normalized_line = line.lstrip("#-*0123456789. ").strip()
    return bool(
        re.match(r"^Q\d*\s*[:：.]", normalized_line, flags=re.IGNORECASE)
        or "?" in normalized_line
        or "？" in normalized_line
    )


def _has_summary_heading(lines: list[str]) -> bool:
    """Return whether the article contains a summary section."""
    # 「まとめ」または英語のSummary見出しがあれば、記事の締めがあると判定する。
    # SEO向けにテーマ語入りの締め見出し（「〜整えよう」等）も許可する。
    closing_keywords = (
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
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line.startswith(("## ", "### ")):
            continue
        lower = stripped_line.lower()
        if "summary" in lower:
            return True
        if any(keyword in stripped_line for keyword in closing_keywords):
            return True
    return False
