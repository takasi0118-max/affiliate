"""Entry point for the affiliate article generation system."""

from config.settings import load_settings
from config.site_config import load_site_config


def main() -> None:
    """Run the application."""
    settings = load_settings()
    site_config = load_site_config(
        site_key=settings.site_key,
        output_dir=settings.output_dir,
    )

    print("Affiliate system config is ready.")
    print(f"Site: {site_config.site_key}")
    print(f"Themes: {len(site_config.themes)}")
    print(f"Categories: {len(site_config.categories)}")
    print(f"Tags: {len(site_config.tags)}")


if __name__ == "__main__":
    main()
