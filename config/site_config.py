"""Site-specific configuration loading."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import PROJECT_ROOT
from utils.file_io import load_json_file, read_text_lines


@dataclass(frozen=True)
class SiteConfig:
    """Configuration files for a single affiliate site."""

    # site_keyは「disaster」などのサイト識別名。sites/{site_key}/を読むために使う。
    site_key: str
    # site_dirは、そのサイト専用ファイルが置かれているフォルダ。
    site_dir: Path
    # output_dirは、生成したMarkdown記事を保存する予定のフォルダ。
    output_dir: Path
    # themesは記事化したいテーマ一覧。themes.txtから読み込む。
    themes: list[str]
    # categories/tagsはWordPress投稿や記事プロンプトで使う分類情報。
    categories: dict[str, Any]
    tags: dict[str, Any]
    # historyは過去に生成した記事の記録。同じテーマを何度も処理しないために使う。
    history: list[dict[str, Any]]

def load_site_config(site_key: str, output_dir: Path) -> SiteConfig:
    """Load site-specific configuration for the given site key."""
    # SITE_KEYごとにthemes/categories/tags/historyを切り替えられる構成にする。
    site_dir = PROJECT_ROOT / "sites" / site_key
    if not site_dir.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    # サイト固有の入力データをまとめて読み込み、後続サービスへ渡す。
    # JSONは分類情報や履歴、txtは記事テーマ一覧という役割分担にしている。
    categories = load_json_file(site_dir / "categories.json")
    tags = load_json_file(site_dir / "tags.json")
    history = load_json_file(site_dir / "history.json")
    themes = read_text_lines(site_dir / "themes.txt", ignore_comments=True)

    # 設定ファイルの形が崩れている場合は、記事生成前に分かりやすく止める。
    if not isinstance(categories, dict):
        raise TypeError("categories.json must contain a JSON object.")
    if not isinstance(tags, dict):
        raise TypeError("tags.json must contain a JSON object.")
    if not isinstance(history, list):
        raise TypeError("history.json must contain a JSON array.")

    return SiteConfig(
        site_key=site_key,
        site_dir=site_dir,
        output_dir=output_dir,
        themes=themes,
        categories=categories,
        tags=tags,
        history=history,
    )
