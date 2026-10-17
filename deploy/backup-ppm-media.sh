#!/bin/bash
# PPM media (uploaded PDFs/images) backup — GPG-encrypted, weekly.
# Cron: /etc/cron.d/ppm-backup-media -> 30 6 * * 0 root /usr/local/bin/backup-ppm-media.sh
#
# Properties:
#   * the private key never exists on this host (public key only in /root/.gnupg-ppm)
#   * tar is built from a sorted manifest, so "nothing changed" is detectable and the
#     run becomes a no-op instead of re-writing 190MB every week
#   * no compression: the payload is PDF/PNG/JPEG, already compressed
#   * a plaintext .meta sidecar records file_count / total_bytes / manifest sha256 so a
#     restore can be verified by count + size parity after decryption off-host
set -euo pipefail
umask 077

BACKUP_DIR="/var/backups/ppm-media"
SOURCE_PARENT="/var/www/html"
SOURCE_DIR="media"
RETENTION=3
LOG_FILE="/var/log/ppm-backup.log"
GPG_HOME="/root/.gnupg-ppm"
GPG_RECIPIENT="2894659F30D57F5A59F7D24E18073F5C40179CA3"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [media] $*" >> "$LOG_FILE"; }
fail() { log "FAILED: $*"; exit 1; }

[ -d "$SOURCE_PARENT/$SOURCE_DIR" ] || fail "media dir missing: $SOURCE_PARENT/$SOURCE_DIR"
[ -d "$GPG_HOME" ] || fail "GPG home missing: $GPG_HOME"

MANIFEST=$(mktemp /tmp/ppm-media-manifest.XXXXXX)
trap 'rm -f "$MANIFEST"' EXIT

cd "$SOURCE_PARENT"
find "$SOURCE_DIR" -type f -printf '%p\t%s\t%T@\n' | LC_ALL=C sort > "$MANIFEST"
[ -s "$MANIFEST" ] || fail "manifest is empty"

FILE_COUNT=$(wc -l < "$MANIFEST")
TOTAL_BYTES=$(awk -F'\t' '{s+=$2} END{printf "%d", s}' "$MANIFEST")
MANIFEST_SHA=$(sha256sum "$MANIFEST" | awk '{print $1}')

LAST_META=$(find "$BACKUP_DIR" -maxdepth 1 -name '*.meta' -printf '%T@ %p\n' 2>/dev/null \
    | sort -rn | awk 'NR==1{print $2}')
if [ -n "${LAST_META:-}" ] && grep -qx "manifest_sha256=$MANIFEST_SHA" "$LAST_META"; then
    log "SKIP: media unchanged (manifest $MANIFEST_SHA, ${FILE_COUNT} files, ${TOTAL_BYTES} bytes)"
    exit 0
fi

STAMP=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/ppm_media_${STAMP}.tar.gpg"
log "Starting media backup: ${FILE_COUNT} files, ${TOTAL_BYTES} bytes"

# tar exits 1 when a file changes while being read (--warning suppresses the noise,
# not the status); with a static media tree that must not fail the backup.
set +o pipefail
tar --warning=no-file-changed -cf - "$SOURCE_DIR" 2>/dev/null \
    | gpg --homedir "$GPG_HOME" --batch --yes --trust-model always \
          --recipient "$GPG_RECIPIENT" --encrypt --output "$OUT"
# Copy the whole array first: any subsequent assignment resets PIPESTATUS to a
# single element, which then makes PIPESTATUS[1] an unbound variable under set -u.
RC=("${PIPESTATUS[@]}")
set -o pipefail
TAR_RC=${RC[0]:-99}
GPG_RC=${RC[1]:-99}
[ "$TAR_RC" -le 1 ] || fail "tar exit status $TAR_RC"
[ "$GPG_RC" -eq 0 ] || fail "gpg exit status $GPG_RC"
[ -s "$OUT" ] || fail "encrypted archive is empty"
chmod 600 "$OUT"

# No private key here: --list-packets exits 2 while still printing the packets.
PACKETS=$(gpg --homedir "$GPG_HOME" --batch --list-packets "$OUT" 2>/dev/null || true)
echo "$PACKETS" | grep -q '^:pubkey enc packet' || fail "not an OpenPGP public-key message"
echo "$PACKETS" | grep -q "$GPG_RECIPIENT\|C2729BF5A69B81D8" || fail "wrong recipient"

GPG_SHA=$(sha256sum "$OUT" | awk '{print $1}')
META="$BACKUP_DIR/ppm_media_${STAMP}.meta"
cat > "$META" <<METAEOF
created=$(date -Is)
stamp=$STAMP
file_count=$FILE_COUNT
total_bytes=$TOTAL_BYTES
manifest_sha256=$MANIFEST_SHA
gpg_sha256=$GPG_SHA
gpg_bytes=$(stat -c%s "$OUT")
recipient=$GPG_RECIPIENT
METAEOF
chmod 600 "$META"
ln -sfn "$OUT" "$BACKUP_DIR/ppm_media_latest.tar.gpg"
ln -sfn "$META" "$BACKUP_DIR/ppm_media_latest.meta"

# Retention: keep the newest $RETENTION generations, delete older ones explicitly.
mapfile -t GENS < <(find "$BACKUP_DIR" -maxdepth 1 -name 'ppm_media_*.tar.gpg' -printf '%f\n' | sort -r)
i=0
for g in "${GENS[@]}"; do
    i=$((i + 1))
    if [ "$i" -le "$RETENTION" ]; then
        continue
    fi
    rm -f "$BACKUP_DIR/$g" "$BACKUP_DIR/${g%.tar.gpg}.meta"
    log "retention: deleted $g"
done

log "OK: $OUT ($(stat -c%s "$OUT")B, sha256 ${GPG_SHA:0:12}…, ${FILE_COUNT} files)"
