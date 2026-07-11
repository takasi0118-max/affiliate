# AIアフィリエイトサイト開発フレームワーク

Pythonでアフィリエイトサイト向けの記事生成・投稿を支援する半自動システムです。
Version1.0では防災グッズ専門サイトを対象にしつつ、将来ほかのジャンルへ展開できる構成にします。

## 目的

- SEOを意識した記事を生成する
- 楽天APIから商品を取得する
- WordPressへ下書き投稿する
- 投稿前に必ず人が確認する
- サイト別設定を切り替えて再利用できる構成にする

## システムの流れ

1. テーマ入力
2. 楽天APIから商品取得
3. OpenAIで記事生成
4. Markdown保存
5. 人が確認
6. WordPress下書き投稿
7. X投稿（Version1ではprintのみ）

## 使用技術

- Python 3.13.5
- OpenAI API
- 楽天市場API
- WordPress REST API
- requests
- python-dotenv
- BeautifulSoup
- Markdown
- pandas
- Git / GitHub
- Cursor / VSCode

## フォルダ構成

```text
affiliate-system/
├── README.md
├── main.py
├── requirements.txt
├── .env.example
├── .gitignore
├── docs/
│   ├── README.md
│   ├── specs/
│   │   └── Cursor実装指示書_Version1.0.txt
│   └── development/
│       ├── 開発の進め方.md
│       ├── Cursor開発ルール.md
│       ├── Git運用ルール.md
│       ├── コーディング規約.md
│       └── トラブルシューティング.md
├── config/
├── providers/
├── services/
├── prompts/
│   ├── common/
│   └── disaster/
├── sites/
│   └── disaster/
│       ├── themes.txt
│       ├── categories.json
│       ├── tags.json
│       ├── history.json
│       └── output/
├── logs/
├── tests/
└── utils/
```

## フォルダの役割

- `docs/`: 仕様書、開発手順、運用ルール
- `config/`: 環境変数やサイト設定の読み込み
- `providers/`: OpenAI、楽天API、WordPressなど外部API通信
- `services/`: 商品取得、記事生成、保存、投稿などの業務ロジック
- `prompts/`: OpenAIへ渡すプロンプト
- `sites/`: サイト別のテーマ、カテゴリ、タグ、生成履歴、出力先
- `utils/`: ログ、リトライ、ファイル操作などの共通処理
- `tests/`: テストコード
- `logs/`: 実行ログ

## 開発ルール

必ずSTEP01から順番に実装します。
1STEP完成したら、動作確認、Gitコミット、GitHubへPushを行ってから次へ進みます。

## コーディングルール

- Python 3.13.5
- PEP8
- 型ヒント必須
- docstring必須
- 複雑な処理にはコメントを書く
- 例外処理を書く
- ログを出力する
- 責務を分離する

## 完成目標

`main.py` を実行するだけで、テーマ入力、楽天取得、記事生成、Markdown保存、確認、WordPress投稿、X投稿まで実行できるシステムを完成させます。
