# バックアップ/DR 強化計画（2026-10-17）

対象: `ppm.y-asahi.com`（さくらVPS / MariaDB 10.5.29 / Django 5.2.11）
作成: タダシ / 2026-10-17 21:20 JST

---

## 0. この計画の前提（すべて実測。推測は含まない）

| 項目 | 実測値 |
|---|---|
| MariaDB | 10.5.29 |
| `log_bin` | **OFF**、binlogファイル **0件** → **現状 PITR は物理的に不可能**（設定変更＋再起動が必須） |
| DBバックアップ | `/etc/cron.d/ppm-backup` → `0 6 * * *`（毎日06:00）、`/var/backups/ppm/` に **6ファイル**（GPG暗号化、14日保持） |
| mediaバックアップ | `/etc/cron.d/ppm-backup-media` → `30 6 * * 0`（日曜06:30）、`/var/backups/ppm-media/` に **4ファイル**（tar.gpg + .meta × 2世代、3世代保持） |
| オフサイト | `gdrive:ppm-backup/{db,media,keys}`（DB 30世代 / media 3世代）、Mac 06:xx のHermes cronで転送 |
| 旧平文DBダンプ | `/var/backups/ppm-legacy-plaintext-20261017/` **16件・1.1MB**（2026-10-02〜10-17、sha256記録済み） |
| ディスク | 25G中 使用6.4G / **空き17G**（28%） |
| 現行 RPO | DB **24時間** / media **7日** |
| 現行 RTO の証拠 | 復号・gzip検証・SQL整合（`-- Dump completed`）までは実測済み。**「暗号化バックアップから実際のDBへ戻してアプリが動く」演習は未実施** |

---

## 1. Scope / Non-Goals

### Scope（この計画でやる）
1. **復旧演習**: 暗号化バックアップ → スクラッチDBへの実import → 行数突合 → 後片付け
2. **旧平文16世代の処理**: 暗号化して置換 or 削除（判断D1で確定）
3. **RPO短縮**: DB 24h → 6h、media 7d → 1d（判断D2/D3で確定）
4. 文書（DRプレイブック・`ppm-ops`）の実測値更新

### Non-Goals（この計画では**やらない**）
- **binlog による PITR の実装**（`log_bin=OFF` からの変更＝再起動・保持設計・復元訓練が必要。将来検討リストに置く）
- 別リージョン/別クラウドへの二重化
- VPS再構築の完全自動化（IaC化）
- アプリ側へのバックアップ機能追加
- 監視・アラート基盤の新設（失敗時の非0終了＋cron配信で足りる）

---

## 2. 実行順序と理由

```
Phase 1  import演習（復旧できることの証明）
   ↓ 「戻せる」が確認できて初めて、消す/増やす判断に意味が出る
Phase 2  旧平文16世代の処理（D1）
   ↓
Phase 3  RPO短縮（D2/D3）＋ 24時間の観測
   ↓
Phase 4  文書更新・クローズ
```

Phase 1 を最初に置く理由: 平文削除も頻度変更も「復旧できる」前提の上に立つ。現状は**復号までは実証済みだが、DBへ戻して動く状態は未実証**。ここを飛ばして他を進めると、失敗したときに原因を切り分けられない。

---

## 3. Phase 1 — 復旧演習（所要 40分 / 承認: 不要〔読み取り＋スクラッチDBのみ〕）

### 1-1. 最新の暗号化ダンプを取得・復号（Mac）
```bash
export GNUPGHOME="$HOME/.gnupg-ppm"
NEW=$(rclone lsf gdrive:ppm-backup/db/ | grep -v -E '\.meta$' | sort -r | sed -n 1p)
rclone copyto "gdrive:ppm-backup/db/$NEW" /tmp/drill.gpg
read -rs PW; printf '%s' "$PW" > /tmp/drill.pw; chmod 600 /tmp/drill.pw; unset PW   # paste from 1Password
gpg --batch --pinentry-mode loopback --passphrase-file /tmp/drill.pw --decrypt /tmp/drill.gpg > /tmp/drill.sql.gz
gzip -t /tmp/drill.sql.gz && echo "gzip OK"
gzip -dc /tmp/drill.sql.gz > /tmp/drill.sql
tail -1 /tmp/drill.sql          # -- Dump completed ... であること
```
- **AC**: `gzip -t` 成功、末尾が `-- Dump completed`、`sha256(drill.gpg)` がDrive側の値と一致
- パスフレーズは 1Password から `read -rs` で受け、0600 の一時ファイル経由（シェル履歴に残さない）。`/tmp/drill.pw` は 1-5 で必ず削除

### 1-2. スクラッチDBを作成（VPS）
```bash
ssh sakura-vps 'sudo -n mysql -e "CREATE DATABASE ppm_restore_drill CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"'
```
- **AC**: `SHOW DATABASES LIKE 'ppm_restore_drill'` に1件。**本番DB名（`ppm`）を絶対に指定しない**

### 1-3. 転送してimport
```bash
scp /tmp/drill.sql sakura-vps:/tmp/drill.sql     # 一時的にVPS上へ平文が出る
ssh sakura-vps 'sudo -n mysql ppm_restore_drill < /tmp/drill.sql && echo IMPORT_OK'
```
- **AC**: エラーなし、`IMPORT_OK`
- リスク: VPS上の平文SQL（数分だけ存在）→ 1-5で確実に削除。転送はSSH（暗号化）

### 1-4. 突合（ここが演習の本体）
```bash
# テーブル一覧と行数（本番 vs 演習）
for db in ppm ppm_restore_drill; do
  ssh sakura-vps "sudo -n mysql -N -e \"SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema='$db' ORDER BY table_name\""
done
```
- **AC**:
  1. テーブル数が一致（本番と同じ。実測16）
  2. 主要テーブルの正確な `COUNT(*)` が一致（`information_schema.table_rows` は概算なので、`projects` / `pages` / `documents` / `users` は `COUNT(*)` で取る）
  3. `pg`相当の制約: `SHOW CREATE TABLE` を数テーブルで差分比較（文字コード・インデックス）
  4. （任意）`DATABASES` を演習DBに向けた `manage.py check` が通る

### 1-5. 後片付け
```bash
ssh sakura-vps 'sudo -n mysql -e "DROP DATABASE ppm_restore_drill"; rm -f /tmp/drill.sql'
rm -f /tmp/drill.gpg /tmp/drill.sql.gz /tmp/drill.sql
```
- **AC**: `SHOW DATABASES` に演習DBなし、`/tmp/drill.sql` 不在（VPS・Mac両方）、`lsof`等の残存なし

### 1-6. 記録
- 実測値（ファイル名・サイズ・sha256・行数・所要時間）を `docs/DISASTER_RECOVERY_PLAYBOOK.md` の復旧演習節へ追記

**ロールバック**: 不要（本番DBには一切書き込まない。読み取りとスクラッチDBのみ）

---

## 4. Phase 2 — 旧平文16世代の処理（所要 20分 / 承認: **D1の判断が必要**）

### 選択肢
| 案 | 内容 | 長所 | 短所 |
|---|---|---|---|
| **A（推奨）** | 16件をGPG暗号化 → 復号sha256一致を確認 → Driveへ → 平文削除 | 10/02〜10/17の履歴を保持しつつ平文を消せる。総量1.1MBで安い | 作業が2段階 |
| B | 平文16件を即削除 | 最短 | 10/17以前のDB履歴が失われる（暗号化世代は10/17開始） |
| C | 現状維持（隔離したまま） | 作業ゼロ | **平文がVPSに残り続ける**＝今回の是正目的に反する |

### 案Aの手順
```bash
ssh sakura-vps 'sudo -n bash -c "
  cd /var/backups/ppm-legacy-plaintext-20261017
  for f in *.sql.gz; do
    gpg --homedir /root/.gnupg-ppm --batch --yes --trust-model always \
        --encrypt -r ppm-backup@y-asahi.local -o /var/backups/ppm/${f%.gz}.gpg $f || exit 1
  done"'
# 復号検証（Mac）: 各ファイルを復号し sha256 が記録済みハッシュ（/root/ppm-legacy-plaintext-sha256-20261017.txt）と一致
```
- **AC**: 暗号化 16/16、復号後sha256 **16/16一致**、Driveに16世代、`/var/backups/ppm-legacy-plaintext-20261017/` の平文 **0件**
- 注意: 暗号化後のファイル名は `ppm_YYYYMMDD_0600.sql.gz.gpg`。既存の保持ロジック（14日）に乗るため、**10/02〜10/03の分は自然消滅対象**になる（保持方針と整合。残したいなら別ディレクトリへ）

---

## 5. Phase 3 — RPO短縮（所要 15分＋24時間観測 / 承認: **D2・D3の判断が必要**）

### 3-1. DB: 24h → 6h（案: `0 */6 * * *`）
- 変更: `/etc/cron.d/ppm-backup` の1行
- 影響確認: `backup-ppm.sh` の保持判定はファイル名のタイムスタンプ基準（14日）なので、日次→6時間毎でも破綻しない（世代数は最大56）
- **AC**: 手動2回実行 → 2回目も新規世代が作られる（DBは毎回サイズが変わるので skip しない）、`/var/backups/ppm/` の世代数が想定通り、オフサイト転送が最新を拾う、失敗注入（DB名誤り）で exit 1

### 3-2. media: 7d → 1d（案: `30 6 * * *`）
- 変化検知（マニフェストsha256）で**無変化時は書き込みゼロ**なので、日次化してもコストはほぼ0（実測: 9秒 / 193MB）
- **AC**: 2回目実行が `SKIP: media unchanged`、保持3世代維持

### 3-3. PITR（Non-Goal。将来検討リストへ）
実装する場合の前提だけ記録: `log_bin=ON` ＋ `binlog_expire_logs_seconds` 設定 ＋ 再起動（数秒のダウンタイム）＋ binlogの定期退避 ＋ 復元手順の訓練。**RPO 24h→6h で業務上足りるなら、複雑度に見合わない**。

---

## 6. Phase 4 — 文書更新とクローズ（所要 10分）

- `docs/DISASTER_RECOVERY_PLAYBOOK.md`:
  - RPO表を実測値へ（DB 6h / media 1d）
  - Phase 1 の演習結果（ファイル名・行数・所要時間）を「IMPLEMENTED REALITY」へ追記
  - Phase 2 の処置結果（暗号化16/16・平文0）を追記
- `ppm-ops` スキル: 保持世代数・スケジュール・演習手順を更新
- PR: 1本（docsのみ、CI 2ジョブgreen を確認してマージ）

---

## 7. 判断が必要な点（回答があれば即着手します）

| ID | 判断 | 選択肢 | タダシ推奨 |
|---|---|---|---|
| **D1** | 旧平文16世代をどうするか | A: 暗号化して保持 / B: 即削除 / C: 隔離継続 | **A**（1.1MBで履歴が残る。平文は消える） |
| **D2** | DBのRPO | 24h維持 / **6h** / 1h | **6h**（実装はcron1行。1hは保持世代が増えるだけ） |
| **D3** | media のRPO | 7d維持 / **1d** | **1d**（変化検知により追加コストほぼ0） |
| **D4** | PITR | 将来リストへ / 今回実装 | **将来リスト**（D2で足りるなら不要） |

---

## 8. 総所要時間

| Phase | 内容 | 時間 | 承認 |
|---|---|---|---|
| 1 | 復旧演習 | 40分 | 不要（本番書き込みなし） |
| 2 | 平文16世代 | 20分 | D1 |
| 3 | RPO短縮＋観測 | 15分＋24h | D2/D3 |
| 4 | 文書・PR | 10分 | 不要 |

Phase 1 は**今すぐ**実行できます。Phase 2以降は D1〜D4 の回答を待ちます。

---

## 9. 実行結果（2026-10-17 21:30–22:00 JST 実測）

判断は D1=A / D2=6h / D3=日次 / D4=将来リスト で確定。

### Phase 1 — 復旧演習（完了）

| 段階 | 実測値 |
|---|---|
| 取得元 | `gdrive:ppm-backup/db/ppm_20261017_151548.sql.gz.gpg`（**62,425 B**） |
| 復号 | exit 0 → `drill.sql.gz` → `gzip -t` OK → `drill.sql` **308,700 B** |
| ダンプ内容 | `CREATE TABLE` **16** / `INSERT INTO` **16** / trailer `-- Dump completed on 2026-10-17 15:15:48` |
| 安全確認 | `USE` / `CREATE DATABASE` 文なし（他DBを汚さない） |
| import | `ppm_restore_drill` へ **IMPORT_OK**、テーブル **16** |
| 行数突合 | **14/16 完全一致**。差分2件はいずれも時刻起因（下記） |
| スキーマ | `django_migrations` / `projects_page` の `SHOW CREATE TABLE` が **IDENTICAL** |
| 業務データ | `projects_page` 222行（id 447–670、欠番0）、`projects_project` 2、`projects_pageimage` 6、`projects_projecttemplate` 3、`accounts_customuser` 5 — すべて一致 |
| 後片付け | `DROP DATABASE ppm_restore_drill` → 残存 **0**、VPS `/tmp/drill.sql` 削除済み |

差分2件の説明（破損ではない）:
- `accounts_autheventlog` 50 vs 49 — ダンプ取得後に1件追加（`created_at > 2026-10-17 06:15:48 UTC` = 1件、差分も1件）
- `django_session` 21 vs 20 — セッションは流動的（失効・再生成）

**注意（実測で判明）**: アプリは `USE_TZ=True` でUTC保存、mysqldumpのtrailerはサーバのローカル時刻（JST）。突合のカットオフは**UTCに直して**比較する必要がある（初回はJST文字列で比較して0件と誤読した）。

### Phase 2 — 旧平文16世代（完了）

| 段階 | 実測値 |
|---|---|
| 暗号化 | 16/16 成功、`/var/backups/ppm-legacy-encrypted-20261017/`（0700 root:root、各600）、ファイル名は元と同一（`.gpg` 付与） |
| 構造確認 | 全16件に `pubkey enc packet`（受信者 `keyid C2729BF5A69B81D8`） |
| 復号照合 | 記録済み平文sha256と **16/16 一致**（Mac側で復号して照合） |
| オフサイト | `gdrive:ppm-backup/db/legacy/` に16件、**989,102 B**、md5 **16/16一致** |
| 平文削除 | `/var/backups/ppm-legacy-plaintext-20261017/` → **16 → 0件**（ディレクトリ空） |

### Phase 3 — RPO短縮（完了）

| 項目 | 変更前 | 変更後 | 検証 |
|---|---|---|---|
| DB | `0 6 * * *`（24h） | **`0 */6 * * *`（6h）** | 2秒間隔で2回実行 → 世代 **+2**、`ppm_latest` シンボリックリンク更新、新規ファイル **0600** |
| media | `30 6 * * 0`（7日） | **`30 6 * * *`（24h）** | 2回実行 → いずれも `SKIP: media unchanged`（58 files / 201,885,111 B、書き込みゼロ） |
| オフサイト | — | 変更なし | daily実行 → Drive最新 = VPS最新 `ppm_20261017_214508`、sha256 `ca8710a3…` 両側一致 |

- 旧cronは `/etc/cron.d/*.bak-20261017` に退避（ロールバックは `cp -p` で戻すだけ）
- 保持は不変: DB 14日 / media 3世代

**実測で判明した小さな罠**: `backup-ppm.sh` のファイル名は秒精度。同一秒に2回実行すると同名で上書きされ、世代が増えない（cron間隔では発生しない）。手動実行時は2秒以上空ける。

### 残課題（この計画の外／要対応）

1. **1Password のパスフレーズが復号に失敗**（10バイトの値で `gpg: decryption failed`、exit 2）。Mac上の `~/.ppm-backup-passphrase` は同じartifactを復号できる。**エスクローは未成立**として扱い、判別コマンドを DR プレイブックに記載した。
2. PITR（D4）— 将来検討。`log_bin=OFF` のため、実装には再起動・保持設計・復元訓練が必要。
