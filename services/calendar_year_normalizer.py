"""Normalize outdated calendar-year markers in article text."""

from __future__ import annotations

from datetime import date
import re


def current_calendar_year() -> str:
    """Return the current calendar year as a string."""
    return str(date.today().year)


def normalize_article_calendar_year(
    content: str,
    current_year: str | None = None,
) -> str:
    """Replace outdated calendar-year markers with the current year.

    Geminiは学習データの影響で【2024年】などを出しやすいため、記事の年表記を矯正する。
    「5年保存」のような年数表現や、賞味期限の未来年、歴史的事実の年はそのまま残す。
    """
    if not content:
        return content
    year_text = current_year or current_calendar_year()
    year = int(year_text)

    def _replace_bracket(match: re.Match[str]) -> str:
        found = int(match.group(1))
        if found == year or found > year:
            return match.group(0)
        return f"【{year_text}年】"

    def _replace_edition(match: re.Match[str]) -> str:
        found = int(match.group(1))
        if found == year or found > year:
            return match.group(0)
        return f"{year_text}年版"

    def _replace_plain(match: re.Match[str]) -> str:
        found = int(match.group(1))
        if found == year or not _is_replaceable_calendar_year(found, year):
            return match.group(0)
        return f"{year_text}年"

    content = re.sub(r"【(20\d{2})年】", _replace_bracket, content)
    content = re.sub(r"(?<![0-9])(20\d{2})年版", _replace_edition, content)
    # タイトル・リードで使われやすい「2024年最新」などを置換。歴史年や期限年は除外。
    content = re.sub(
        r"(?<![0-9])(20\d{2})年(?=最新|おすすめ|比較|ランキング|決定版|完全版|保存版|注目)",
        _replace_plain,
        content,
    )
    return content


def _is_replaceable_calendar_year(found: int, current: int) -> bool:
    """Return whether a year looks like a stale 'current year' marker."""
    # 直近数年の誤記だけ直す。2011年の震災など歴史年や、期限の未来年は残す。
    return current - 5 <= found < current


def strip_calendar_year_from_title(title: str) -> str:
    """Remove calendar-year markers from an article title.

    悩み記事のSEOタイトルでは年表記を使わない方針のため、【2026年】などを除去する。
    """
    if not title:
        return title
    cleaned = title.strip()
    cleaned = re.sub(r"【20\d{2}年】\s*", "", cleaned)
    cleaned = re.sub(r"(?<![0-9])20\d{2}年版\s*", "", cleaned)
    cleaned = re.sub(
        r"(?<![0-9])20\d{2}年(?=最新|おすすめ|比較|ランキング|決定版|完全版|保存版|注目)",
        "",
        cleaned,
    )
    cleaned = re.sub(r"^20\d{2}年\s*", "", cleaned)
    return cleaned.strip(" 　")


def strip_calendar_year_from_seo_title_fields(content: str) -> str:
    """Strip calendar years from SEO title fields inside generated Markdown."""
    if not content:
        return content

    def _replace_labeled(match: re.Match[str]) -> str:
        return f"{match.group(1)}{strip_calendar_year_from_title(match.group(2))}"

    content = re.sub(
        r"^((?:SEOタイトル|SEO タイトル|seo_title|title|タイトル)\s*[:：]\s*)(.+)$",
        _replace_labeled,
        content,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    content = re.sub(
        r'^(seo_title:\s*)(["\']?)(.+?)(\2)\s*$',
        lambda match: (
            f"{match.group(1)}{match.group(2)}"
            f"{strip_calendar_year_from_title(match.group(3))}"
            f"{match.group(4)}"
        ),
        content,
        flags=re.MULTILINE,
    )
    return content
