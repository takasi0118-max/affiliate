"""Regenerate product and ranking articles for one theme with a shared product set."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_settings
from config.site_config import load_site_config
from providers.gemini_provider import GeminiProvider
from providers.rakuten_provider import RakutenProvider
from providers.wordpress_provider import WordPressProvider
from services.article_consistency_service import (
    ArticleConsistencyError,
    ArticleConsistencyService,
)
from services.article_link_sanitizer import sanitize_article_references
from services.article_product_block_builder import (
    inject_and_validate_affiliate_blocks,
)
from services.inline_related_link_service import InlineRelatedLinkService, load_theme_article_links
from services.post_target_registry import load_allowed_slugs_by_theme
from services.prompt_manager import PromptManager
from services.product_ranking_service import (
    ThemeProductSet,
    fetch_theme_product_set,
    format_product_names_list,
    format_products_for_prompt,
    load_theme_product_set,
    save_theme_product_set,
    theme_product_set_path,
)
from services.seo_service import SeoService
from services.wordpress_post_service import WordPressPostService


@dataclass(frozen=True)
class ThemeArticleConfig:
    """Paths and metadata for one theme's product/ranking regeneration."""

    theme: str
    keyword: str
    output_dir: Path
    problem_md: Path
    product_md: Path
    ranking_md: Path
    product_post_id: int
    ranking_post_id: int
    product_seo_title: str
    product_meta_description: str
    product_slug: str
    ranking_seo_title: str
    ranking_meta_description: str
    ranking_slug: str


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(
        description="Regenerate product/ranking articles for one theme.",
    )
    parser.add_argument(
        "--theme",
        required=True,
        help="Theme name (must exist in history.json).",
    )
    parser.add_argument(
        "--keyword",
        default="",
        help="Rakuten search keyword (defaults to theme name).",
    )
    parser.add_argument(
        "--skip-wordpress",
        action="store_true",
        help="Only regenerate Markdown files.",
    )
    parser.add_argument(
        "--use-catalog",
        action="store_true",
        help="Reuse saved product catalog instead of fetching Rakuten again.",
    )
    parser.add_argument(
        "--skip-consistency",
        action="store_true",
        help="Skip cross-article consistency check (for debugging).",
    )
    return parser


def load_theme_config(theme: str, keyword: str) -> ThemeArticleConfig:
    """Load theme paths and SEO metadata from site history."""
    settings = load_settings()
    site_config = load_site_config(
        site_key=settings.site_key,
        output_dir=settings.output_dir,
    )
    records = {
        str(record.get("theme", "")): record
        for record in site_config.history
        if isinstance(record, dict)
    }
    by_type: dict[str, dict] = {}
    for record in site_config.history:
        if not isinstance(record, dict) or record.get("theme") != theme:
            continue
        by_type[str(record.get("article_type", ""))] = record

    missing = [name for name in ("problem", "product", "ranking") if name not in by_type]
    if missing:
        raise SystemExit(
            f"Theme '{theme}' is missing history records for: {', '.join(missing)}"
        )

    def _md_path(record: dict) -> Path:
        raw = str(record.get("markdown_path", ""))
        path = Path(raw)
        if path.is_absolute():
            try:
                return PROJECT_ROOT / path.relative_to(PROJECT_ROOT)
            except ValueError:
                return path
        return PROJECT_ROOT / path

    product_record = by_type["product"]
    ranking_record = by_type["ranking"]
    problem_record = by_type["problem"]

    product_md = _md_path(product_record)
    ranking_md = _md_path(ranking_record)
    problem_md = _md_path(problem_record)

    product_seo = _read_front_matter(product_md) if product_md.exists() else {}
    ranking_seo = _read_front_matter(ranking_md) if ranking_md.exists() else {}

    return ThemeArticleConfig(
        theme=theme,
        keyword=keyword or theme,
        output_dir=site_config.output_dir,
        problem_md=problem_md,
        product_md=product_md,
        ranking_md=ranking_md,
        product_post_id=int(product_record.get("wordpress_post_id", 0)),
        ranking_post_id=int(ranking_record.get("wordpress_post_id", 0)),
        product_seo_title=_with_10_select(
            product_seo.get("seo_title", f"【初心者向け】{theme}おすすめ10選")
        ),
        product_meta_description=product_seo.get(
            "meta_description",
            f"{theme}の選び方とおすすめ10選を初心者向けに解説します。",
        ),
        product_slug=str(product_record.get("slug", product_seo.get("slug", ""))),
        ranking_seo_title=str(
            ranking_record.get("title", ranking_seo.get("seo_title", f"{theme}比較ランキング5選"))
        ),
        ranking_meta_description=ranking_seo.get(
            "meta_description",
            f"人気{theme}5商品を比較表とランキング形式で解説します。",
        ),
        ranking_slug=str(ranking_record.get("slug", ranking_seo.get("slug", ""))),
    )


def _read_front_matter(path: Path) -> dict[str, str]:
    """Return YAML front matter fields from one Markdown file."""
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def _with_10_select(title: str) -> str:
    """Ensure product article title mentions 10選 instead of 5選."""
    return title.replace("5選", "10選").replace("５選", "10選")


def _generate_product_article(
    provider: GeminiProvider,
    product_set: ThemeProductSet,
) -> str:
    """Generate the 10-product introduction article."""
    theme = product_set.theme
    display_products = list(product_set.product_display_order)
    ranking_summary = format_products_for_prompt(list(product_set.ranking_top5))
    prompt = f"""
あなたは防災・備蓄に詳しいアフィリエイトサイト編集者です。
テーマ「{theme}」の商品紹介記事をMarkdownで書いてください。

## 記事方針
- 商品は10個すべて紹介する（10選）
- 比較ランキング記事より文章量を抑え、簡潔に書く
- 比較ランキングの1位〜5位と同じ順番で並べない（指定順を守る）
- 各商品セクションは短く: 特徴2〜3文、メリット2項目、デメリット1項目
- 価格・レビュー評価は箇条書きで書く（後から商品画像リンクが自動挿入される）
- URLやMarkdownリンクは書かない
- 関連記事セクションは書かない
- YAML front matterやコードフェンスは書かない

## 必須構成
1. 導入（現状の悩みと記事の目的）※短め
2. ## {theme}選びでよくある読者の悩み
3. ## 初心者が失敗しない{theme}の選び方（3ポイント程度）
4. ## おすすめ{theme}10選
5. 以下の順番どおりに ### 1. 〜 ### 10. の商品セクションを書く
6. ## よくある質問（FAQ）3件以上
7. ## まとめ

## 商品セクションの書式（各商品）
### {{番号}}. {{短い見出し}}

{{1文の導入}}

* **価格**: {{価格}}円（税込）
* **レビュー評価**: {{平均}}（件数: {{件数}}件）

#### 特徴
{{2〜3文}}

#### メリット
* {{1項目}}
* {{1項目}}

#### デメリット
* {{1項目}}

---

## 紹介順（この順番を厳守）
{format_product_names_list(display_products)}

## 参考: 比較ランキング上位5（順位付けの参考。記事内ではこの順番に並べないこと）
{ranking_summary}

## 文字数
- 導入・選び方・FAQ・まとめなど、各商品紹介セクション（### 1. 〜 以降）**以外**は合計2000〜3000文字程度（ぶれてOK）
- 10商品分の紹介本文は目安に含めない

出力はMarkdown本文のみ。
"""
    return provider.generate_text(prompt)


def _generate_ranking_article(
    provider: GeminiProvider,
    product_set: ThemeProductSet,
) -> str:
    """Generate the top-5 ranking article."""
    theme = product_set.theme
    top5 = list(product_set.ranking_top5)
    prompt = f"""
あなたは防災・備蓄に詳しいアフィリエイトサイト編集者です。
テーマ「{theme}」の比較ランキング記事をMarkdownで書いてください。

## 記事方針
- 対象商品は5個だけ（1位〜5位）
- 順位は以下の指定どおり変更しない
- 商品紹介記事より詳しく書く
- おすすめ度は色付き星として ★ と ☆ を使う（例: ★★★★☆ (4.5)）
- URLやMarkdownリンクは書かない
- 関連記事セクションは書かない
- 商品紹介記事に10商品ある旨に触れてもよい（リンクなし）
- YAML front matterやコードフェンスは書かない

## 必須構成
1. 導入（購入直前の読者向け）※短め
2. ## {theme}選びでよくある悩み
3. ## 失敗しない{theme}の選び方
4. ## 人気{theme}5選 比較表（Markdown表）
5. ## {theme}おすすめランキング
6. 1位〜5位を ### 1位：{{見出し}} 形式で詳述
7. ## よくある質問（FAQ）3件以上
8. ## まとめ

## ランキング各商品の書式
### {{順位}}位：{{短い見出し}}

{{1〜2文のリード}}

* **価格**: {{価格}}円（税込）
* **おすすめ度**: ★★★★★ (5.0) の形式
* **レビュー**: {{平均}}（{{件数}}件）

#### おすすめ理由
{{4〜6文}}

#### メリット
* {{2〜3項目}}

#### デメリット
* {{1〜2項目}}

---

## ランキング順（厳守）
{format_product_names_list(top5)}

## 商品情報
{format_products_for_prompt(top5)}

## 文字数
- 導入・選び方・比較表・FAQ・まとめなど、ランキング各商品の詳細（### 1位：〜 以降）**以外**は合計2000〜3000文字程度（ぶれてOK）
- 1位〜5位の各商品詳細は目安に含めない

出力はMarkdown本文のみ。
"""
    return provider.generate_text(prompt)


def _build_metadata_header(config: ThemeArticleConfig, article_type: str) -> str:
    """Return YAML front matter for one article type."""
    if article_type == "product":
        return "\n".join(
            [
                "---",
                f"theme: {config.theme}",
                "article_type: product",
                f"seo_title: {config.product_seo_title}",
                f"meta_description: {config.product_meta_description}",
                f"slug: {config.product_slug}",
                "---",
                "",
            ]
        )
    return "\n".join(
        [
            "---",
            f"theme: {config.theme}",
            "article_type: ranking",
            f"seo_title: {config.ranking_seo_title}",
            f"meta_description: {config.ranking_meta_description}",
            f"slug: {config.ranking_slug}",
            "---",
            "",
        ]
    )


def regenerate(
    config: ThemeArticleConfig,
    skip_wordpress: bool,
    use_catalog: bool,
    skip_consistency: bool = False,
) -> None:
    """Regenerate Markdown and optionally update WordPress."""
    settings = load_settings()
    rakuten = RakutenProvider(
        settings.rakuten_application_id,
        settings.rakuten_access_key,
        settings.rakuten_affiliate_id,
    )
    gemini = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    catalog_path = theme_product_set_path(config.output_dir, config.theme)

    if use_catalog and catalog_path.exists():
        product_set = load_theme_product_set(catalog_path)
        print(f"Loaded catalog: {catalog_path}")
    else:
        product_set = fetch_theme_product_set(
            rakuten,
            config.theme,
            config.keyword,
            hits=10,
        )
        save_theme_product_set(catalog_path, product_set)
        print(f"Saved catalog: {catalog_path}")

    print(
        f"Products: {len(product_set.products)} / "
        f"Top5 ranks: {[product.rank for product in product_set.ranking_top5]}"
    )

    print("Generating product article (Gemini)...")
    product_body = _generate_product_article(gemini, product_set)
    product_body = inject_and_validate_affiliate_blocks(
        product_body,
        list(product_set.product_display_order),
        "product",
    )

    print("Generating ranking article (Gemini)...")
    ranking_body = _generate_ranking_article(gemini, product_set)
    ranking_body = inject_and_validate_affiliate_blocks(
        ranking_body,
        list(product_set.ranking_top5),
        "ranking",
    )

    if not config.problem_md.exists():
        raise FileNotFoundError(
            f"Problem article not found for consistency check: {config.problem_md}"
        )

    prompt_manager = PromptManager(settings.site_key)
    consistency_service = ArticleConsistencyService(prompt_manager, gemini)
    problem_content = config.problem_md.read_text(encoding="utf-8")
    products_text = format_products_for_prompt(list(product_set.products))
    print("Running cross-article consistency check (Gemini)...")
    if skip_consistency:
        print("Skipped consistency check (--skip-consistency).")
    else:
        consistency_service.require_consistent_article_set(
            theme=config.theme,
            problem_article=problem_content,
            product_article=product_body,
            ranking_article=ranking_body,
            products=products_text,
        )
        print("Consistency check passed.")

    config.product_md.write_text(
        _build_metadata_header(config, "product") + product_body.strip() + "\n",
        encoding="utf-8",
    )
    print(f"Saved: {config.product_md}")
    config.ranking_md.write_text(
        _build_metadata_header(config, "ranking") + ranking_body.strip() + "\n",
        encoding="utf-8",
    )
    print(f"Saved: {config.ranking_md}")

    if skip_wordpress:
        return

    provider = WordPressProvider(
        settings.wordpress_url,
        settings.wordpress_username,
        settings.wordpress_app_password,
    )
    service = WordPressPostService(provider)
    seo_service = SeoService()
    inline_service = InlineRelatedLinkService()
    theme_links = load_theme_article_links()
    allowed_slugs = load_allowed_slugs_by_theme().get(config.theme, set())

    for post_id, md_path, article_type in (
        (config.product_post_id, config.product_md, "product"),
        (config.ranking_post_id, config.ranking_md, "ranking"),
    ):
        if post_id <= 0:
            print(f"Skip WordPress update: invalid post ID for {article_type}")
            continue
        content = md_path.read_text(encoding="utf-8")
        if allowed_slugs:
            content = sanitize_article_references(content, allowed_slugs)
        content = inline_service.apply(content, article_type, config.theme, theme_links)
        seo = seo_service.analyze_article(content)
        products = (
            product_set.all_products if article_type == "product" else product_set.top5_products
        )
        updated_id = service.update_post_with_markdown(
            post_id=post_id,
            markdown_content=content,
            seo=seo,
            article_type=article_type,
            products=products if article_type == "product" else None,
        )
        print(f"WordPress post {updated_id} ({article_type}) updated")


def main() -> None:
    """Run CLI."""
    args = build_parser().parse_args()
    config = load_theme_config(args.theme, args.keyword)
    try:
        regenerate(
            config,
            skip_wordpress=args.skip_wordpress,
            use_catalog=args.use_catalog,
            skip_consistency=args.skip_consistency,
        )
    except ArticleConsistencyError as error:
        print("Consistency check failed. Markdown was not saved.")
        print(error.result.summary)
        for issue in error.result.issues:
            articles = ", ".join(issue.affected_articles) or "n/a"
            print(f"- [{issue.severity}] {issue.category} ({articles}): {issue.description}")
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
