"""Regenerate product and ranking articles for one theme with a shared product set."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_settings
from providers.gemini_provider import GeminiProvider
from providers.rakuten_provider import RakutenProvider
from services.article_consistency_service import (
    ArticleConsistencyError,
    ArticleConsistencyService,
)
from services.article_product_block_builder import inject_and_validate_affiliate_blocks
from services.prompt_manager import PromptManager
from services.product_ranking_service import (
    RankedProduct,
    ThemeProductSet,
    fetch_theme_product_set,
    format_product_names_list,
    format_products_for_prompt,
    load_theme_product_set,
    save_theme_product_set,
    theme_product_set_path,
)
from services.seo_service import SeoService
from services.inline_related_link_service import InlineRelatedLinkService, load_theme_article_links
from services.article_link_sanitizer import sanitize_article_references
from services.wordpress_post_service import WordPressPostService
from providers.wordpress_provider import WordPressProvider
from services.post_target_registry import load_allowed_slugs_by_theme, load_post_targets


THEME = "防災リュック"
KEYWORD = "防災リュック"
OUTPUT_DIR = PROJECT_ROOT / "sites/disaster/output"
CATALOG_PATH = theme_product_set_path(OUTPUT_DIR, THEME)
PRODUCT_MD = OUTPUT_DIR / "product-bousai-rucksack-select.md"
RANKING_MD = OUTPUT_DIR / "ranking-bousai-backpack-ranking.md"
PROBLEM_MD = OUTPUT_DIR / "problem-emergency-backpack-how-to-choose.md"
PRODUCT_POST_ID = 9
RANKING_POST_ID = 10


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(description="Regenerate product/ranking articles.")
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
    return parser


def _product_names_list(products: list[RankedProduct]) -> str:
    """Return numbered product names for prompts."""
    return format_product_names_list(products)


def _generate_product_article(
    provider: GeminiProvider,
    product_set: ThemeProductSet,
) -> str:
    """Generate the 10-product introduction article."""
    display_products = list(product_set.product_display_order)
    ranking_summary = format_products_for_prompt(list(product_set.ranking_top5))
    prompt = f"""
あなたは防災グッズに詳しいアフィリエイトサイト編集者です。
テーマ「{product_set.theme}」の商品紹介記事をMarkdownで書いてください。

## 記事方針
- 商品は10個すべて紹介する（10選）
- 比較ランキング記事より文章量を抑え、簡潔に書く
- 比較ランキングの1位〜5位と同じ順番で並べない（指定順を守る）
- 各商品セクションは短く: 特徴2〜3文、メリット2項目、デメリット1項目
- 価格・レビュー評価は箇条書きで書く（後から商品画像リンクが自動挿入される）
- URLやMarkdownリンクは書かない
- 関連記事セクションは書かない

## 必須構成
1. 導入（現状の悩みと記事の目的）※短め
2. ## 防災リュック選びでよくある読者の悩み
3. ## 初心者が失敗しない防災リュックの選び方（3ポイント程度）
4. ## おすすめ防災リュック10選
5. 以下の順番どおりに ### 1. 〜 ### 10. の商品セクションを書く

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
{_product_names_list(display_products)}

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
    top5 = list(product_set.ranking_top5)
    prompt = f"""
あなたは防災グッズに詳しいアフィリエイトサイト編集者です。
テーマ「{product_set.theme}」の比較ランキング記事をMarkdownで書いてください。

## 記事方針
- 対象商品は5個だけ（1位〜5位）
- 順位は以下の指定どおり変更しない
- 商品紹介記事より詳しく書く
- おすすめ度は色付き星として ★ と ☆ を使う（例: ★★★★☆ (4.5)）
- URLやMarkdownリンクは書かない
- 関連記事セクションは書かない
- 商品紹介記事に10商品ある旨に触れてもよい（リンクなし）

## 必須構成
1. 導入（購入直前の読者向け）※短め
2. ## 防災リュック選びでよくある悩み
3. ## 失敗しない防災リュックの選び方
4. ## 人気防災リュック5選 比較表（Markdown表）
5. ## 防災リュックおすすめランキング
6. 1位〜5位を ### 1位：{{見出し}} 形式で詳述

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
{_product_names_list(top5)}

## 商品情報
{format_products_for_prompt(top5)}

## 文字数
- 導入・選び方・比較表・FAQ・まとめなど、ランキング各商品の詳細（### 1位：〜 以降）**以外**は合計2000〜3000文字程度（ぶれてOK）
- 1位〜5位の各商品詳細は目安に含めない

出力はMarkdown本文のみ。
"""
    return provider.generate_text(prompt)


def _build_product_metadata() -> str:
    """Return product article metadata header."""
    return "\n".join(
        [
            "---",
            f"theme: {THEME}",
            "article_type: product",
            "seo_title: 【初心者向け】防災リュックおすすめ10選！選び方と必要な中身を解説",
            "meta_description: 防災リュックの選び方を初心者向けに解説。楽天市場で人気の防災セット10選をコンパクトに紹介。1人用・2人用の特徴や失敗しない選び方もわかりやすく整理します。",
            "slug: bousai-rucksack-select",
            "---",
            "",
        ]
    )


def _build_ranking_metadata() -> str:
    """Return ranking article metadata header."""
    return "\n".join(
        [
            "---",
            f"theme: {THEME}",
            "article_type: ranking",
            "seo_title: 【2026年】防災リュックおすすめ比較ランキング5選！防災士が選ぶ選び方",
            "meta_description: 人気防災リュック5商品を比較表とランキング形式で徹底解説。1位から5位まで、用途別の選び方やメリット・デメリットを詳しく紹介します。",
            "slug: bousai-backpack-ranking",
            "---",
            "",
        ]
    )


def regenerate(skip_wordpress: bool = False, use_catalog: bool = False) -> None:
    """Regenerate Markdown and optionally update WordPress."""
    settings = load_settings()
    rakuten = RakutenProvider(
        settings.rakuten_application_id,
        settings.rakuten_access_key,
        settings.rakuten_affiliate_id,
    )
    gemini = GeminiProvider(settings.gemini_api_key, settings.gemini_model)

    if use_catalog and CATALOG_PATH.exists():
        product_set = load_theme_product_set(CATALOG_PATH)
        print(f"Loaded catalog: {CATALOG_PATH}")
    else:
        product_set = fetch_theme_product_set(rakuten, THEME, KEYWORD, hits=10)
        save_theme_product_set(CATALOG_PATH, product_set)
        print(f"Saved catalog: {CATALOG_PATH}")

    print(f"Products: {len(product_set.products)} / Top5 ranks: {[p.rank for p in product_set.ranking_top5]}")
    print("Generating product article...")
    product_body = _generate_product_article(gemini, product_set)
    product_body = inject_and_validate_affiliate_blocks(
        product_body,
        list(product_set.product_display_order),
        "product",
    )

    print("Generating ranking article...")
    ranking_body = _generate_ranking_article(gemini, product_set)
    ranking_body = inject_and_validate_affiliate_blocks(
        ranking_body,
        list(product_set.ranking_top5),
        "ranking",
    )

    prompt_manager = PromptManager(settings.site_key)
    consistency_service = ArticleConsistencyService(prompt_manager, gemini)
    if not PROBLEM_MD.exists():
        raise FileNotFoundError(
            f"Problem article not found for consistency check: {PROBLEM_MD}"
        )
    problem_content = PROBLEM_MD.read_text(encoding="utf-8")
    products_text = format_products_for_prompt(list(product_set.products))
    print("Running cross-article consistency check...")
    consistency_service.require_consistent_article_set(
        theme=THEME,
        problem_article=problem_content,
        product_article=product_body,
        ranking_article=ranking_body,
        products=products_text,
    )
    print("Consistency check passed.")

    PRODUCT_MD.write_text(_build_product_metadata() + product_body.strip() + "\n", encoding="utf-8")
    print(f"Saved: {PRODUCT_MD}")
    RANKING_MD.write_text(_build_ranking_metadata() + ranking_body.strip() + "\n", encoding="utf-8")
    print(f"Saved: {RANKING_MD}")

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
    allowed_slugs = load_allowed_slugs_by_theme().get(THEME, set())

    for post_id, md_path, article_type in (
        (PRODUCT_POST_ID, PRODUCT_MD, "product"),
        (RANKING_POST_ID, RANKING_MD, "ranking"),
    ):
        content = md_path.read_text(encoding="utf-8")
        if allowed_slugs:
            content = sanitize_article_references(content, allowed_slugs)
        content = inline_service.apply(content, article_type, THEME, theme_links)
        seo = seo_service.analyze_article(content)
        products = product_set.all_products if article_type == "product" else product_set.top5_products
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
    try:
        regenerate(skip_wordpress=args.skip_wordpress, use_catalog=args.use_catalog)
    except ArticleConsistencyError as error:
        print("Consistency check failed. Markdown was not saved.")
        print(error.result.summary)
        for issue in error.result.issues:
            articles = ", ".join(issue.affected_articles) or "n/a"
            print(f"- [{issue.severity}] {issue.category} ({articles}): {issue.description}")
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
