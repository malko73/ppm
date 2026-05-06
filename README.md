# PPM (MACKs) — PDF Project Manager

**v1.0.11** (2026-05-06)  
テンプレートPDFにテキスト・画像を差し込み、ページ単位で編集・出力するDjango Webアプリ。
冊子・カタログ制作向け。

## 技術スタック

- Python 3.11+ / Django 5.1+
- MySQL 8.x / Celery + Redis（非同期PDF生成）
- Bootstrap 5 / HTMX / Sortable.js
- pypdf / reportlab / Pillow / S3対応

## 主な機能

| 機能 | 説明 |
|---|---|
| **プロジェクト管理** | 作成・編集・削除・コピー・参加者管理 |
| **ページ編集** | 追加・編集・削除・校了・ドラッグ並び替え |
| **PDF出力** | 単ページプレビュー / 全結合PDF / ZIPダウンロード |
| **CSV入出力** | データ出力・フォーマットDL・取込 |
| **認証** | メールアドレスログイン、HMAC-SHA256改ざん検知監査ログ |

## 構成

- `config/` — Django設定・Celery
- `accounts/` — カスタムユーザー・監査ログ
- `projects/` — コアドメインモデル・ビュー・PDFレンダラ

## 更新ログ
### 1.0.11 - 2026-05-06
- ログイン500エラー（MariaDB停止＋settings.py CACHES条件不整合）を修正
- MariaDB自動起動設定確認（既にenabled）
- CACHESのRedis切り替え条件分岐を除去（LocMemCache固定化）
- APP_VERSION 1.0.10 → 1.0.11

## 関連ドキュメント

- `ADMIN_MANUAL.md` — 管理者マニュアル
