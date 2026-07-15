# docs

このフォルダは、実装コードではなく開発用ドキュメントを管理します。

## 構成

```text
docs/
├── README.md
├── specs/
│   └── Cursor実装指示書_Version1.0.txt
└── development/
    ├── 開発の進め方.md
    ├── Cursor開発ルール.md
    ├── Git運用ルール.md
    ├── コーディング規約.md
    ├── トラブルシューティング.md
    └── WordPress記事更新手順.md
```

## 役割

- `specs/`: システム全体の仕様や実装指示書を置く
- `development/`: 日々の開発手順、Git運用、Cursor利用ルール、トラブル対応を置く

コード実装に直接使うファイルは、ルート直下や `config/`, `providers/`, `services/`, `sites/` などに置きます。
