# MACKs 1.0.0

冊子・カタログ制作向けの Django ベース Web アプリケーションです。  
テンプレート PDF に対して、テキストや画像をページ単位で配置し、単体 PDF・結合 PDF・ZIP を出力できます。

## 更新ルール
- 微修正を含むすべての変更でバージョンを更新する
- 変更時は `APP_VERSION` と本README先頭のバージョンを合わせる
- 変更内容は本READMEの「更新ログ」に追記する

## 更新ログ
### 1.0.0 - 2026-02-19
- 正式リリース
- アプリ名称を `MACKs` に統一
- フッターにバージョン表示を追加

## 概要
- 認証: Django 標準認証（`CustomUser` / メールアドレスログイン）
- 権限: プロジェクト作成者 + 参加者で共同編集
- 編集: ページ追加/更新/削除、ドラッグ&ドロップ並び替え（再採番あり）
- 出力: 単ページ PDF / 結合 PDF / ページ別 PDF ZIP
- ストレージ: ローカル `media/` または S3（切替可）
- 非同期: Celery + Redis（任意）

## 技術スタック
- Python 3.11+
- Django 5.1+
- MySQL 8.x
- Bootstrap 5 / HTMX / Sortable.js
- pypdf / reportlab / Pillow
- django-storages / boto3（S3 使用時）
- Celery / Redis（非同期処理使用時）

## 主な機能
### 1. プロジェクト管理
- テンプレート PDF（100MB 以下）をプロジェクト単位で管理
- テキスト・画像の配置定義（`default_positions`）を JSON で保持
- スタッフユーザーは参加者（`participants`）を指定可能

### 2. ページ管理
- ページ名 + 可変テキスト項目 + 可変画像項目を登録
- 画像バリデーション
  - 1ファイル: 20MB 以下
  - 1ページ合計: 50MB 以下
- 並び替え時に `order` / `page_number` を 1 始まりで再採番

### 3. PDF / ZIP 出力
- 単ページ PDF プレビュー出力
- 全ページ結合 PDF プレビュー出力
- ページ別 PDF 一括 ZIP ダウンロード

## 画面 / URL
- `/admin/` : 管理画面
- `/accounts/login/` : ログイン
- `/` : プロジェクト一覧

## セットアップ
### 前提
- Python 3.11 以上
- MySQL 8.x
- （任意）Redis

### 1) 依存パッケージ
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 環境変数（`.env`）
`config/settings.py` で利用している主な変数:

```env
DJANGO_SECRET_KEY=change-me
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
APP_NAME=MACKs
APP_VERSION=1.0.0

MYSQL_DATABASE=appsdb
MYSQL_USER=rocky
MYSQL_PASSWORD=your_password
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306

# S3 を使う場合のみ
USE_S3=False
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_STORAGE_BUCKET_NAME=
AWS_S3_REGION_NAME=ap-northeast-1

# Celery を使う場合のみ
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
```

### 3) DB 初期化
```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4) 起動
```bash
python manage.py runserver
```

### 5) （任意）Celery ワーカー
```bash
celery -A config worker -l info
```

## 開発メモ
- カスタムユーザー: `accounts.CustomUser`（`USERNAME_FIELD=email`）
- テンプレート寸法は先頭ページから mm 換算して表示
- 座標はポイント（pt）で保持し、フォーム入力では mm と相互変換
- `DEBUG=True` では `MEDIA_URL` を Django が配信

## ディレクトリ構成（抜粋）
```text
config/      Django 設定・URL・ASGI/WSGI・Celery
accounts/    カスタムユーザーモデル
projects/    ドメインモデル・フォーム・ビュー・PDFレンダラ
templates/   画面テンプレート
media/       アップロード先（ローカル運用時）
```

## 既知の注意点
- 本番運用時は `DEBUG=False` + 適切な `ALLOWED_HOSTS` を設定してください。
- `SECURE_SSL_REDIRECT=True` など HTTPS 前提の設定が有効なため、
  リバースプロキシ配下での運用を想定しています。
