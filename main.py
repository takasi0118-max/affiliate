"""Entry point for the affiliate article generation system."""

import logging

from config.settings import PROJECT_ROOT, load_settings
from config.site_config import load_site_config
from utils.file_io import ensure_directory
from utils.logger import setup_logging


logger = logging.getLogger(__name__)


def main() -> None:
    """Run the application."""
    settings = load_settings()
    setup_logging(
        log_level=settings.log_level,
        log_file=PROJECT_ROOT / "logs" / "app.log",
    )

    site_config = load_site_config(
        site_key=settings.site_key,
        output_dir=settings.output_dir,
    )
    ensure_directory(site_config.output_dir)

    logger.info("Configuration loaded for site: %s", site_config.site_key)
    print("Affiliate system config is ready.")
    print(f"Site: {site_config.site_key}")
    print(f"Themes: {len(site_config.themes)}")
    print(f"Categories: {len(site_config.categories)}")
    print(f"Tags: {len(site_config.tags)}")


if __name__ == "__main__":
    main()
