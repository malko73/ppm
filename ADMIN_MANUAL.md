# PPM 管理者マニュアル

最終更新: 2026-02-17
対象システム: PPM (PDF Project Manager) 6.2

## 1. 本書の対象
本マニュアルは、PPM の運用管理者（システム管理者・業務管理者）向けです。

想定読者:
- サーバー管理者（環境変数、DB、Redis、S3 などを管理）
- アプリ管理者（ユーザー作成、権限付与、業務運用）

---

## 2. システム概要
PPM は、テンプレート PDF にテキスト・画像を差し込み、ページ単位で編集/出力する Django アプリです。

主な機能:
- ログイン認証（メールアドレス + パスワード）
- プロジェクト作成/編集/削除
- ページ追加/編集/削除/並び替え
- 単ページ PDF 出力（校正確認）
- 全ページ結合 PDF 出力（軽量）
- ページ別 PDF の ZIP 出力（印刷用 350dpi）

---

## 3. 権限とロール
### 3.1 ユーザー種別
- 一般ユーザー
  - ログイン、担当プロジェクトの操作が可能
- スタッフユーザー（`is_staff=True`）
  - Django 管理画面 `/admin/` にアクセス可能
  - プロジェクト編集時に「参加者」指定が可能
- スーパーユーザー（`is_superuser=True`）
  - 管理画面で全権限を保持

### 3.2 プロジェクトアクセス
プロジェクトを閲覧・操作できるのは以下です。
- プロジェクト作成者（owner）
- `participants` に追加されたユーザー

---

## 4. 初期導入手順（管理者）
### 4.1 前提
- Python 3.11 以上
- MySQL 8.x
- 任意: Redis（Celery 利用時）

### 4.2 アプリ初期化
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### 4.3 `.env` 設定（主要項目）
```env
DJANGO_SECRET_KEY=change-me
DEBUG=False
ALLOWED_HOSTS=example.com

MYSQL_DATABASE=appsdb
MYSQL_USER=app_user
MYSQL_PASSWORD=strong_password
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306

USE_S3=False
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_STORAGE_BUCKET_NAME=
AWS_S3_REGION_NAME=ap-northeast-1

CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
```

補足:
- 本番では `DEBUG=False` を必須としてください。
- HTTPS 前提設定（`SECURE_SSL_REDIRECT=True`）のため、リバースプロキシ配下での運用を推奨します。

### 4.4 Celery（任意）
```bash
celery -A config worker -l info
```

---

## 5. 日常運用フロー
### 5.1 ログイン
1. `/accounts/login/` にアクセス
2. メールアドレスとパスワードでログイン

### 5.2 ユーザー管理（管理者）
1. `/admin/` にアクセス
2. `Accounts > Custom users` を開く
3. 必要な操作を実行
   - 新規作成
   - 有効/無効切り替え（`is_active`）
   - スタッフ化（`is_staff`）
   - スーパーユーザー化（`is_superuser`）

推奨運用:
- 通常業務ユーザーは `is_staff=False`
- 業務管理者のみ `is_staff=True`
- `is_superuser` は最小人数に限定

### 5.3 プロジェクト作成
1. プロジェクト一覧 `/` から「新規プロジェクト」
2. 以下を入力して保存
   - タイトル
   - テンプレート PDF（100MB 以下）
   - 説明
   - 参加者（スタッフユーザーにのみ表示）
3. 必要に応じて「テキスト配置」「画像配置」を追加/調整

配置定義ルール:
- キーは英字開始、英数字/アンダースコアのみ
- テキストと画像で同じキーは使用不可
- 少なくとも 1 項目（テキスト or 画像）が必要

### 5.4 ページ運用
1. プロジェクト詳細から「ページ追加」
2. ページ名、各テキスト項目、画像項目を入力
3. 保存後、一覧で順序をドラッグして並び替え
4. 必要時は各ページの「編集」「削除」「校正確認」を使用

画像制限:
- 1 ファイル 20MB 以下
- 1 ページ合計 50MB 以下

### 5.5 出力運用
- 全ページ結合PDF（軽量）
  - 画面確認・社内回覧向け
- 全ページZIP（印刷用350dpi）
  - 印刷入稿向け
- 校正確認（単ページ PDF）
  - ページ単位のチェック向け

---

## 6. Django 管理画面の使い方
### 6.1 Project
- 確認項目
  - タイトル
  - 所有者（`user`）
  - 更新日時
- 検索
  - タイトル
  - 所有者メール
- 参加者
  - `participants` で複数指定

### 6.2 Page
- 確認項目
  - プロジェクト
  - ページ番号
  - 並び順
  - ページ名
  - 更新日時

### 6.3 PageImage
- 確認項目
  - 対象ページ
  - キー
  - 更新日時
- 用途
  - 動的画像キーの格納状況確認

---

## 7. 障害対応（一次切り分け）
### 7.1 ログインできない
確認順:
1. 対象ユーザーが `is_active=True` か
2. メールアドレスが正しいか
3. パスワードリセットが必要か
4. セッション/Cookie がブロックされていないか

### 7.2 プロジェクトが見えない
- ユーザーがそのプロジェクトの owner か `participants` に含まれているか確認

### 7.3 PDF アップロード失敗
- 100MB を超えていないか
- 有効な PDF 形式か
- ページを含む PDF か

### 7.4 画像アップロード失敗
- 単体 20MB / 合計 50MB を超えていないか
- 画像形式が一般的な形式（JPEG/PNG など）か

### 7.5 本番でリダイレクトループ
- `SECURE_SSL_REDIRECT=True` 前提のため、プロキシで HTTPS ヘッダが正しく転送されているか確認
- `X-Forwarded-Proto: https` が渡されているか確認

### 7.6 フォント崩れ（日本語）
- `NOTO_SANS_JP_FONT_PATH` を設定し、Noto Sans JP の実体ファイルを指定
- 明朝を使う場合は `NOTO_SERIF_JP_FONT_PATH` を指定
- 本番は固定パス運用を推奨（URL配信フォントは非推奨）
- 未設定時は CID フォントへフォールバック

---

## 8. バックアップ/保守
### 8.1 バックアップ対象
- MySQL データベース
- アップロードファイル
  - ローカル運用: `media/`
  - S3 運用: 対象バケット
- `.env`（機密情報は安全に保管）

### 8.2 推奨保守
- Django / 依存パッケージの定期更新
- 不要ユーザーの無効化
- 管理者権限（`is_staff` / `is_superuser`）の棚卸し

---

## 9. 運用ルール（推奨）
- 本番作業は管理者アカウントを個人別に発行し、共有アカウントを避ける
- 参加者付与は最小権限で運用する
- 印刷用データは ZIP（350dpi）を正本とし、軽量PDFは確認用途とする
- テンプレート変更時は、既存プロジェクトへの影響を事前検証する

---

## 10. 連絡テンプレート（例）
### 10.1 アカウント発行完了
件名: PPM アカウント発行完了

本文:
- ログインURL: `https://<your-domain>/accounts/login/`
- ログインID: メールアドレス
- 初期パスワード: 別送
- 初回ログイン後にパスワード変更をお願いします。

### 10.2 障害一次報告
件名: PPM 障害一次報告

本文:
- 発生日時:
- 影響範囲:
- 症状:
- 再現手順:
- 画面URL:
- ログ抜粋:
- 暫定対応:
