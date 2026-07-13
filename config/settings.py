"""Application settings loaded from environment variables."""

from dataclasses import dataclass
from pathlib import Path
from typing import Final
import os

from dotenv import load_dotenv


PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
ENV_PATH: Final[Path] = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class Settings:
    """Application-wide settings loaded from the .env file."""

    # Geminiで記事本文を作るためのAPIキーとモデル名。
    gemini_api_key: str
    gemini_model: str
    # 楽天APIから商品情報を取得し、アフィリエイトURLを使うための認証情報。
    rakuten_application_id: str
    rakuten_access_key: str
    rakuten_affiliate_id: str
    # WordPressへ下書き投稿する時に使う接続情報。後続STEPで利用する。
    wordpress_url: str
    wordpress_username: str
    wordpress_app_password: str
    # どのサイト設定を使うか、生成した記事をどこへ保存するかを決める。
    site_key: str
    output_dir: Path
    # INFOやDEBUGなど、ログの詳しさを.envから切り替える。
    log_level: str


def _get_required_env(name: str) -> str:
    """Return a required environment variable or raise a clear error."""
    # 必須設定はここで一元チェックし、設定漏れを起動直後に検出する。
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable is missing: {name}")
    return value


def load_settings() -> Settings:
    """Load application settings from .env."""
    # プロジェクト直下の.envを読み込み、外部APIキーや出力先をSettingsへ集約する。
    # ここで読み込んだ値は、main.pyから各Provider/Serviceへ配られる。
    load_dotenv(ENV_PATH)

    # OUTPUT_DIRはプロジェクトルートからの相対パスとして扱う。
    output_dir = PROJECT_ROOT / _get_required_env("OUTPUT_DIR")

    # Settingsにまとめることで、os.getenvをアプリのあちこちに書かずに済む。
    return Settings(
        gemini_api_key=_get_required_env("GEMINI_API_KEY"),
        gemini_model=_get_required_env("GEMINI_MODEL"),
        rakuten_application_id=_get_required_env("RAKUTEN_APPLICATION_ID"),
        rakuten_access_key=_get_required_env("RAKUTEN_ACCESS_KEY"),
        rakuten_affiliate_id=_get_required_env("RAKUTEN_AFFILIATE_ID"),
        wordpress_url=_get_required_env("WORDPRESS_URL"),
        wordpress_username=_get_required_env("WORDPRESS_USERNAME"),
        wordpress_app_password=_get_required_env("WORDPRESS_APP_PASSWORD"),
        site_key=_get_required_env("SITE_KEY"),
        output_dir=output_dir,
        log_level=_get_required_env("LOG_LEVEL"),
    )
