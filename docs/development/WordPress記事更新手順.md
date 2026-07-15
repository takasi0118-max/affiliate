# WordPress記事更新手順

既存のWordPress投稿を、保存済みMarkdownから再反映する手順です。
Cursorがなくても、コマンドだけで実行できます。

## いつ使うか

| 方法 | 用途 |
|------|------|
| `main.py` | 新しいテーマで記事を**新規生成**し、下書きとして投稿する |
| `scripts/update_wordpress_posts.py` | Markdownを編集したあと、**既存投稿を上書き更新**する |

関連ドキュメント: [新規テーマ記事作成手順.md](新規テーマ記事作成手順.md)

`main.py` は Gemini API と楽天 API を使いますが、この更新スクリプトは **WordPress API だけ** を使います。

## 前提

- プロジェクト直下（`affiliate` フォルダ）で実行する
- `.env` に WordPress の接続情報が設定されている
- 更新対象の Markdown は `sites/disaster/output/` にある

## 登録済みの投稿

投稿IDとMarkdownの対応は `sites/disaster/history.json` から自動で読み込みます。
`main.py` で新規テーマを作成すると、WordPress投稿ID付きで履歴に追記されます。

現在の手動管理対象（履歴未登録時のフォールバック）:

| 投稿ID | 記事タイプ | Markdownファイル |
|--------|-----------|------------------|
| 8 | 悩み記事（problem） | `sites/disaster/output/problem-emergency-backpack-how-to-choose.md` |
| 9 | 商品紹介（product） | `sites/disaster/output/product-bousai-rucksack-select.md` |
| 10 | ランキング（ranking） | `sites/disaster/output/ranking-bousai-backpack-ranking.md` |

一覧を確認する:

```powershell
python scripts\update_wordpress_posts.py --list
```

## 基本的な流れ

1. `sites/disaster/output/` の Markdown を編集する
2. 更新コマンドを実行する
3. WordPress 管理画面で表示を確認する

## コマンド例

プロジェクト直下で実行します。`PYTHONPATH` の設定は不要です。

```powershell
# 登録済み一覧を表示
python scripts\update_wordpress_posts.py --list

# 9 だけ更新
python scripts\update_wordpress_posts.py 9

# 8 と 10 だけ更新
python scripts\update_wordpress_posts.py 8 10

# 8, 9, 10 すべて更新（IDを省略）
python scripts\update_wordpress_posts.py

# ヘルプを表示
python scripts\update_wordpress_posts.py --help
```

Windows では、プロジェクト直下のバッチファイルでも同じです。

```powershell
update-wordpress.bat 9
update-wordpress.bat 8 10
update-wordpress.bat
```

## 記事タイプごとの注意

### 悩み記事（ID 8）

商品カード用の価格・画像・リンクは、商品紹介記事の Markdown から自動で読み込みます。
商品情報を変えた場合は、`product-bousai-rucksack-select.md` も合わせて更新してください。

### 商品紹介・ランキング（ID 9, 10）

本文内の商品ブロック（画像・価格・レビュー）をそのままカード化して反映します。

## スクリプトが行うこと

1. Markdown を読み込む
2. `services/article_format_service.py` で HTML に変換する
3. WordPress REST API で投稿の本文・タイトル・slug・抜粋を更新する

公開状態（`publish`）は変えず、内容だけ差し替えます。

## 新しい投稿を追加するとき

通常は `main.py` で新規テーマを作成すれば、`history.json` に自動登録されます。
手動で追記する必要はありません。

`wordpress_post_id` が空の履歴レコードは、更新コマンドの対象外です。
WordPress下書き作成に失敗した場合は、`history.json` の `wordpress_post_id` を手動で補完してください。

記事タイプは次のいずれかです。

- `problem`（悩み記事）
- `product`（商品紹介）
- `ranking`（ランキング）

悩み記事で商品カードが必要な場合は、`needs_products=True` を指定します。

## よくあるエラー

### `Unknown post ID(s): 99`

登録されていない投稿 ID を指定しています。`--list` で登録済み ID を確認してください。

### `Markdown file not found`

`history.json` の `markdown_path` が間違っているか、Markdown が存在しません。

### WordPress 接続エラー

`.env` の `WORDPRESS_URL`、`WORDPRESS_USERNAME`、`WORDPRESS_APP_PASSWORD` を確認してください。
