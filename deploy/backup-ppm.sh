#!/bin/bash
# PPM MariaDB backup — GPG-encrypted (set 2026-10-17)
# Cron: /etc/cron.d/ppm-backup -> 0 6 * * * root /usr/local/bin/backup-ppm.sh
#
# Properties:
#   * dump is verified (gzip integrity + "Dump completed" trailer) before encryption
#   * only the encrypted artifact is kept; the plaintext temp is 0600, in the backup
#     dir, and removed by trap on every exit path
#   * private key NEVER lives on this host — only the public key in /root/.gnupg-ppm
#   * failures are logged and exit non-zero (cron would otherwise fail silently)
set -euo pipefail
umask 077

BACKUP_DIR="/var/backups/ppm"
ENV_FILE="/var/www/html/.env"
RETENTION_DAYS=14
LOG_FILE="/var/log/ppm-backup.log"
GPG_HOME="/root/.gnupg-ppm"
GPG_RECIPIENT="2894659F30D57F5A59F7D24E18073F5C40179CA3"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }
fail() { log "FAILED: $*"; exit 1; }

[ -r "$ENV_FILE" ] || fail ".env not readable: $ENV_FILE"
[ -d "$GPG_HOME" ] || fail "GPG home missing: $GPG_HOME"

DB_PASSWORD=$(grep -m1 '^MYSQL_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)
DB_NAME=$(grep -m1 '^MYSQL_DATABASE=' "$ENV_FILE" | cut -d= -f2-)
[ -n "${DB_NAME:-}" ] || fail "MYSQL_DATABASE not found in $ENV_FILE"
# root authenticates over the unix socket on this host (unix_socket plugin), so the
# password is only used if that is ever switched back to password auth.
[ -n "${DB_PASSWORD:-}" ] || log "note: MYSQL_PASSWORD empty — assuming unix_socket auth"

STAMP=$(date +%Y%m%d_%H%M%S)
PLAIN=$(mktemp "$BACKUP_DIR/.ppm_${STAMP}_XXXXXX.sql.gz.part")
ENCRYPTED="$BACKUP_DIR/ppm_${STAMP}.sql.gz.gpg"
cleanup() { rm -f "$PLAIN"; }
trap cleanup EXIT

log "Starting backup: db=$DB_NAME"

if ! mysqldump --single-transaction --routines --triggers \
        -u root -p"$DB_PASSWORD" "$DB_NAME" | gzip -c > "$PLAIN"; then
    fail "mysqldump/gzip pipeline returned non-zero"
fi

gzip -t "$PLAIN" || fail "gzip integrity check failed"
gzip -dc "$PLAIN" | tail -3 | grep -q 'Dump completed' \
    || fail "dump truncated (no 'Dump completed' trailer)"
PLAIN_SIZE=$(stat -c%s "$PLAIN")

gpg --homedir "$GPG_HOME" --batch --yes --trust-model always \
    --recipient "$GPG_RECIPIENT" --encrypt --output "$ENCRYPTED" "$PLAIN" \
    || fail "gpg encryption failed"
chmod 600 "$ENCRYPTED"
rm -f "$PLAIN"

# On this host there is no private key, so `--list-packets` exits 2 after printing
# the packets ("public key decryption failed: No secret key"). Inspect the packets
# instead of trusting the exit code (this bit us once).
PACKETS=$(gpg --homedir "$GPG_HOME" --batch --list-packets "$ENCRYPTED" 2>/dev/null || true)
echo "$PACKETS" | grep -q '^:pubkey enc packet' \
    || fail "encrypted file is not an OpenPGP public-key message"
echo "$PACKETS" | grep -q "$GPG_RECIPIENT\|C2729BF5A69B81D8" \
    || fail "encrypted file is not addressed to the expected recipient"
ln -sfn "$ENCRYPTED" "$BACKUP_DIR/ppm_latest.sql.gz.gpg"

DELETED=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.sql.gz.gpg' \
    -mtime +"$RETENTION_DAYS" -print -delete | wc -l)
log "OK: $ENCRYPTED (plaintext ${PLAIN_SIZE}B, retention deleted ${DELETED})"
