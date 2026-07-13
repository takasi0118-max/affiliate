"""Site data management service."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from config.site_config import SiteConfig
from utils.file_io import ensure_directory, save_json_file


@dataclass(frozen=True)
class HistoryEntry:
    """A generated article record stored in history.json."""

    # history.jsonに保存する1記事分の記録。
    # 後で「どのテーマの記事を作ったか」「WordPressに投稿済みか」を追跡するために使う。
    theme: str
    article_type: str
    title: str
    slug: str
    markdown_path: str
    status: str
    wordpress_post_id: int | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert the entry to a JSON-serializable dictionary."""
        data = asdict(self)
        # created_at未指定の場合は、履歴保存時点のUTC時刻を自動で入れる。
        if not data["created_at"]:
            data["created_at"] = datetime.now(UTC).isoformat()
        return data


class SiteManager:
    """Manage themes, tags, categories, output, and history for one site."""

    def __init__(self, site_config: SiteConfig) -> None:
        """Initialize the manager with loaded site configuration."""
        # 読み込んだサイト設定を保持し、履歴は更新しやすいようコピーして持つ。
        self.site_config = site_config
        self._history = list(site_config.history)

    @property
    def history(self) -> list[dict[str, Any]]:
        """Return a copy of the current history records."""
        # 外部から直接_historyを書き換えられないよう、コピーを返す。
        return list(self._history)

    def ensure_output_dir(self) -> None:
        """Create the site's output directory when it does not exist."""
        # 記事保存先フォルダが無いとMarkdown保存で失敗するため、起動時に作っておく。
        ensure_directory(self.site_config.output_dir)

    def get_processed_themes(self) -> set[str]:
        """Return themes that already exist in history."""
        # history.jsonに記録済みのテーマを除外し、同じテーマの再生成を防ぐ。
        return {
            str(record["theme"])
            for record in self._history
            if isinstance(record, dict) and record.get("theme")
        }

    def get_available_themes(self) -> list[str]:
        """Return themes that have not been processed yet."""
        processed_themes = self.get_processed_themes()
        # themes.txtの並び順を維持したまま、未処理テーマだけを返す。
        return [
            theme
            for theme in self.site_config.themes
            if theme not in processed_themes
        ]

    def get_next_theme(self) -> str | None:
        """Return the next available theme, or None when none remain."""
        available_themes = self.get_available_themes()
        # 未処理テーマが無ければNoneを返し、main.py側でAPI通信をスキップする。
        if not available_themes:
            return None
        # themes.txtの先頭から順番に処理するため、最初の1件だけ返す。
        return available_themes[0]

    def get_default_category(self) -> str:
        """Return the default category for WordPress posts."""
        category = self.site_config.categories.get("default")
        # WordPress投稿で最低限必要なカテゴリが壊れていないか確認する。
        if not isinstance(category, str) or not category:
            raise ValueError("categories.json must define a default category.")
        return category

    def get_default_tags(self) -> list[str]:
        """Return default tags for WordPress posts."""
        tags = self.site_config.tags.get("default")
        # タグは複数指定を前提に、文字列リストであることを保証する。
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("tags.json must define default tags as a list of strings.")
        return tags

    def add_history_entry(self, entry: HistoryEntry) -> None:
        """Append a history entry and save history.json."""
        # メモリ上の履歴に追加したあと、history.jsonにも保存して次回起動時に反映する。
        self._history.append(entry.to_dict())
        save_json_file(self.site_config.site_dir / "history.json", self._history)
