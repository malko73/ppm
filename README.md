# PPM (MACKs) — PDF Project Manager

**v1.0.12** (2026-08-21)  
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
| **ヘルスチェック** | `/health/live`, `/health/ready` エンドポイント |

## 構成

- `config/` — Django設定・Celery・ヘルスチェック URL ルーティング
- `accounts/` — カスタムユーザー・監査ログ・ヘルスチェック views
- `projects/` — コアドメインモデル・ビュー・PDFレンダラ
- `scripts/` — テスト・検証スクリプト
- `docs/` — Issue #2 (Runtime Failure Gate) 仕様書・結果

## ヘルスチェック エンドポイント

### `/health/live`
**Liveness Probe** — Django プロセスが応答可能か  
- 外部依存チェックなし
- 常に HTTP 200 を返す
- 応答例: `{"status": "ok"}`

### `/health/ready`
**Readiness Probe** — すべての依存関係が正常か  
- Database (MySQL) 接続確認
- Redis/Celery broker 接続確認
- 全て OK で HTTP 200、1つでも error なら HTTP 503
- 応答例:
  ```json
  {
    "status": "ok",
    "database": "ok",
    "redis": "ok",
    "celery": "ok"
  }
  ```

## 運用・監視

### Runtime Failure Gate (Issue #2)

**ステータス**: ✅ PASS / MRRA Confidence: High / VERIFIED

外部依存（Redis/Celery）が停止した場合、PPM は安全に fail-closed する設計を検証済み：

- **Test A2** (Redis DOWN): 認証済み PDF エンドポイントは同期生成しない ✓
- **Test B2** (Celery DOWN): 認証済み PDF エンドポイントは同期生成しない ✓
- **Service Recovery**: Redis/Celery 再起動後、機能復旧確認 ✓

詳細は `docs/ISSUE2_A2_B2_VERDICT_CRITERIA.md` 参照。

### ログ・監視

- 監査ログ: `auth_log` テーブル（全ユーザー操作を記録）
- エラーログ: Apache / Django ログ → `/var/log/httpd/`
- ヘルスチェック: `curl https://ppm.y-asahi.com/health/ready/`

## インストール

### 前提条件

- Python 3.11+
- MySQL 8.x
- Redis 7.x
- Celery worker (systemd 管理)

### セットアップ

```bash
# リポジトリクローン
git clone https://github.com/malko73/ppm.git
cd ppm

# 環境変数設定
cp .env.template .env
# .env を編集（DB接続情報、Django SECRET_KEY など）

# venv 作成・インストール
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# DB マイグレーション
python3 manage.py migrate

# スタティックファイル収集
python3 manage.py collectstatic --noinput

# 開発サーバー起動
python3 manage.py runserver
```

### 本番デプロイ

VPS (ConoHa AlmaLinux 9) 向けデプロイスクリプト：
```bash
# deploy.sh が git root に存在
sudo bash deploy.sh
```

デプロイパス: `/var/www/html/` (Apache wsgi 経由)

## 更新ログ

### 1.0.12 - 2026-08-21
- **Issue #2 (Runtime Failure Gate)** PASS / MRRA Confidence: High / VERIFIED
  - A2/B2 テスト（Redis/Celery 障害時）で fail-closed 動作確認
  - Health Endpoints (`/health/live`, `/health/ready`) 実装
  - Authenticated session injection テスト完了
- 健康チェックエンドポイントの追加と動作確認
- GitHub CI/CD 統合（全テスト green）

### 1.0.11 - 2026-05-06
- ログイン500エラー（MariaDB停止＋settings.py CACHES条件不整合）を修正
- MariaDB自動起動設定確認（既にenabled）
- CACHESのRedis切り替え条件分岐を除去（LocMemCache固定化）
- APP_VERSION 1.0.10 → 1.0.11

## 関連ドキュメント

- `ADMIN_MANUAL.md` — 管理者マニュアル
- `docs/ISSUE2_RUNTIME_FAILURE_GATE.md` — Issue #2 仕様
- `docs/ISSUE2_A2_B2_VERDICT_CRITERIA.md` — A2/B2 判定基準
- `docs/ISSUE2_FINAL_STATUS.md` — 最終状態報告

## ライセンス

内部プロジェクト (Proprietary)

## 問い合わせ

Mark7 (marukoshiki) — Project Lead
