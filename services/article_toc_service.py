"""Table of contents helpers for affiliate articles."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

DETAIL_SUBHEADING_LABELS = (
    "特徴",
    "メリット",
    "デメリット",
    "おすすめ理由",
)

DETAIL_SUBHEADING_PATTERN = re.compile(
    r"^(特徴|メリット|デメリット|おすすめ理由)(?:と.*?)?$",
)
FAQ_HEADING_PATTERN = re.compile(r"^Q\d*[\.\s:：]", re.IGNORECASE)
RANKING_HEADING_PATTERN = re.compile(r"^\d+位[：:]")
NUMBERED_HEADING_PATTERN = re.compile(r"^(\d+)\.\s+(.+)$")


def convert_detail_subheadings(soup: BeautifulSoup) -> None:
    """Turn product detail h4 headings into styled paragraphs excluded from TOC."""
    for heading in list(soup.find_all(["h3", "h4"])):
        label = heading.get_text(" ", strip=True)
        if not _is_detail_subheading(label):
            continue

        paragraph = soup.new_tag("p")
        paragraph["class"] = ["affiliate-detail-heading"]
        strong = soup.new_tag("strong")
        strong.string = _normalize_detail_label(label)
        paragraph.append(strong)
        heading.replace_with(paragraph)


def insert_table_of_contents(soup: BeautifulSoup) -> None:
    """Insert an in-article table of contents before the first section heading."""
    body = _find_article_body(soup)

    entries = _collect_toc_entries(body)
    if not entries:
        return

    toc = _build_toc_element(soup, entries)
    insert_before = _find_toc_insertion_point(body)
    insert_before.insert_before(toc)


def _find_article_body(soup: BeautifulSoup) -> Tag:
    """Return the article body container."""
    body = soup.find("div", class_="affiliate-article__body")
    if isinstance(body, Tag):
        return body
    return soup


def _find_toc_insertion_point(body: Tag) -> Tag:
    """Return the node before which the TOC should be inserted."""
    for child in body.children:
        if not isinstance(child, Tag):
            continue
        if child.name in {"h2", "hr"}:
            return child
    for child in body.children:
        if isinstance(child, Tag):
            return child
    return body


def _collect_toc_entries(body: Tag) -> list[tuple[str, str, int]]:
    """Collect TOC entries as (heading_id, label, level)."""
    entries: list[tuple[str, str, int]] = []
    h2_counter = 0

    for heading in body.find_all(["h2", "h3"]):
        if not isinstance(heading, Tag):
            continue
        if heading.find_parent("details", class_="affiliate-faq-item"):
            continue

        label = heading.get_text(" ", strip=True)
        if heading.name == "h3" and _is_detail_subheading(label):
            continue
        if heading.name == "h3" and FAQ_HEADING_PATTERN.match(label):
            continue

        heading_id = str(heading.get("id", "")).strip()
        if not heading_id:
            continue

        display_label = _toc_display_label(label, heading.name)
        if not display_label:
            continue

        if heading.name == "h2":
            h2_counter += 1
            entries.append((heading_id, f"{h2_counter}. {display_label}", 2))
            continue

        entries.append((heading_id, display_label, 3))

    return entries


def _build_toc_element(soup: BeautifulSoup, entries: list[tuple[str, str, int]]) -> Tag:
    """Build the TOC container element."""
    container = soup.new_tag("div")
    container["class"] = ["affiliate-toc"]

    summary = soup.new_tag("p")
    summary["class"] = ["affiliate-toc__summary"]
    summary.string = "目次"
    container.append(summary)

    list_tag = soup.new_tag("ul")
    list_tag["class"] = ["affiliate-toc__list"]
    for heading_id, label, level in entries:
        item = soup.new_tag("li")
        item["class"] = ["affiliate-toc__item"]
        if level == 3:
            item["class"].append("affiliate-toc__item--sub")
        link = soup.new_tag("a", href=f"#{heading_id}")
        link.string = label
        item.append(link)
        list_tag.append(item)
    container.append(list_tag)
    return container


def _is_detail_subheading(label: str) -> bool:
    """Return whether a heading label is a product detail subsection."""
    normalized = label.strip()
    if normalized in DETAIL_SUBHEADING_LABELS:
        return True
    return bool(DETAIL_SUBHEADING_PATTERN.match(normalized))


def _normalize_detail_label(label: str) -> str:
    """Return a short label for detail subheadings."""
    for candidate in DETAIL_SUBHEADING_LABELS:
        if label.startswith(candidate):
            return candidate
    return label


def _is_product_or_ranking_entry(label: str) -> bool:
    """Return whether a heading looks like a product or ranking entry."""
    if RANKING_HEADING_PATTERN.match(label):
        return True
    if NUMBERED_HEADING_PATTERN.match(label):
        return True
    return False


def _toc_display_label(label: str, tag_name: str) -> str:
    """Return TOC text without duplicated numbering prefixes."""
    cleaned = label.strip()
    if RANKING_HEADING_PATTERN.match(cleaned):
        return cleaned
    cleaned = FAQ_HEADING_PATTERN.sub("", cleaned).strip()
    cleaned = NUMBERED_HEADING_PATTERN.sub(r"\2", cleaned).strip()
    return cleaned


def normalize_list_entry_headings(soup: BeautifulSoup) -> None:
    """Remove duplicate numeric prefixes from product and ranking entry headings."""
    for section_heading in soup.find_all("h2"):
        section_title = section_heading.get_text(" ", strip=True)
        if not re.search(r"(選|ランキング)", section_title):
            continue

        for heading in _section_headings_until_next_h2(section_heading):
            if heading.name != "h3":
                continue
            label = heading.get_text(" ", strip=True)
            if RANKING_HEADING_PATTERN.match(label):
                _append_class(heading, "affiliate-list-entry-heading")
                continue

            number_match = NUMBERED_HEADING_PATTERN.match(label)
            if not number_match:
                continue

            heading["data-ordinal"] = number_match.group(1)
            heading.clear()
            heading.append(NavigableString(number_match.group(2).strip()))
            _append_class(heading, "affiliate-list-entry-heading")


def _section_headings_until_next_h2(section_heading: Tag):
    """Yield headings until the next h2 sibling section."""
    for sibling in section_heading.find_next_siblings():
        if isinstance(sibling, Tag) and sibling.name == "h2":
            break
        if isinstance(sibling, Tag) and sibling.name in {"h3", "h4"}:
            yield sibling


def _append_class(tag: Tag, class_name: str) -> None:
    """Append a CSS class to a BeautifulSoup tag."""
    classes = list(tag.get("class", []))
    if class_name not in classes:
        classes.append(class_name)
    tag["class"] = classes
