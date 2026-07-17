"""Shared models for internal article links."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ArticleLink:
    """Internal link information for one generated article."""

    article_type: str
    title: str
    url: str

    def to_markdown(self) -> str:
        """Return the link as a Markdown list item."""
        return f"- [{self.title}]({self.url})"
