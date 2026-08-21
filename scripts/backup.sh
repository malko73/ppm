#!/bin/bash

################################################################################
# PPM Backup Script - Issue #3 Step 1
# 
# Purpose:
#   Daily backup of Application State (DB, media, .env)
#   with SHA-256 checksum validation and remote storage
#
# Usage:
#   ./scripts/backup.sh [--dry-run] [--local-only]
#
# Schedule:
#   Daily at 02:00 via cron or systemd timer
#
# Backup Structure:
#   ppm_backup_YYYYMMDD/
#   ├── ppm_db_YYYYMMDD.sql
#   ├── ppm_db_YYYYMMDD.sql.sha256
#   ├── media_YYYYMMDD.tar.gz
#   ├── media_YYYYMMDD.tar.gz.sha256
#   ├── .env.gpg
#   ├── .env.gpg.sha256
#   └── backup.log
#
################################################################################

set -euo pipefail

# ===== Configuration =====

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly BACKUP_DIR="${PROJECT_ROOT}/backups"
readonly LOG_DIR="${BACKUP_DIR}/logs"
readonly TIMESTAMP=$(date +%Y%m%d_%H%M%S)
readonly DATE=$(date +%Y%m%d)
readonly BACKUP_SET_DIR="${BACKUP_DIR}/ppm_backup_${DATE}"

# Database
readonly DB_NAME="${DB_NAME:-ppm}"
readonly DB_USER="${DB_USER:-postgres}"
readonly DB_HOST="${DB_HOST:-localhost}"
readonly DB_PORT="${DB_PORT:-5432}"
readonly DB_DUMP_FILE="${BACKUP_SET_DIR}/ppm_db_${DATE}.sql"
readonly DB_CHECKSUM_FILE="${DB_DUMP_FILE}.sha256"

# Media
readonly MEDIA_DIR="${PROJECT_ROOT}/media"
readonly MEDIA_ARCHIVE="${BACKUP_SET_DIR}/media_${DATE}.tar.gz"
readonly MEDIA_CHECKSUM_FILE="${MEDIA_ARCHIVE}.sha256"

# .env (encryption)
readonly ENV_FILE="${PROJECT_ROOT}/.env"
readonly ENV_ENCRYPTED="${BACKUP_SET_DIR}/.env.gpg"
readonly ENV_CHECKSUM_FILE="${ENV_ENCRYPTED}.sha256"
readonly GPG_RECIPIENT="${GPG_RECIPIENT:-}"

# Remote storage (S3)
readonly AWS_S3_BUCKET="${AWS_S3_BUCKET:-}"
readonly AWS_S3_PREFIX="ppm-backups/${DATE}"
readonly AWS_REGION="${AWS_REGION:-ap-northeast-1}"

# Logging
readonly LOG_FILE="${LOG_DIR}/backup_${TIMESTAMP}.log"

# Flags
DRY_RUN=false
LOCAL_ONLY=false

# ===== Functions =====

log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${timestamp}] [${level}] ${message}" | tee -a "${LOG_FILE}"
}

log_info() {
    log "INFO" "$@"
}

log_warn() {
    log "WARN" "$@"
}

log_error() {
    log "ERROR" "$@"
}

create_directories() {
    log_info "Creating backup directories..."
    mkdir -p "${BACKUP_SET_DIR}"
    mkdir -p "${LOG_DIR}"
    log_info "Directories created: ${BACKUP_SET_DIR}"
}

backup_postgresql() {
    log_info "Starting PostgreSQL backup..."
    
    if [[ "${DRY_RUN}" == "true" ]]; then
        log_info "[DRY-RUN] Would dump PostgreSQL to ${DB_DUMP_FILE}"
        return 0
    fi
    
    if ! pg_dump \
        -h "${DB_HOST}" \
        -p "${DB_PORT}" \
        -U "${DB_USER}" \
        -d "${DB_NAME}" \
        -F plain \
        > "${DB_DUMP_FILE}"; then
        log_error "PostgreSQL dump failed"
        return 1
    fi
    
    log_info "PostgreSQL backup completed: $(ls -lh "${DB_DUMP_FILE}" | awk '{print $5}')"
}

backup_media() {
    log_info "Starting media backup..."
    
    if [[ ! -d "${MEDIA_DIR}" ]]; then
        log_warn "Media directory not found: ${MEDIA_DIR}"
        # Create empty archive if media dir doesn't exist
    fi
    
    if [[ "${DRY_RUN}" == "true" ]]; then
        log_info "[DRY-RUN] Would tar media to ${MEDIA_ARCHIVE}"
        return 0
    fi
    
    # tar with gzip compression
    if tar \
        -C "$(dirname "${MEDIA_DIR}")" \
        -czf "${MEDIA_ARCHIVE}" \
        "$(basename "${MEDIA_DIR}")" 2>/dev/null || true; then
        log_info "Media backup completed: $(ls -lh "${MEDIA_ARCHIVE}" | awk '{print $5}')"
    else
        log_warn "Media backup encountered warnings (this may be normal if media is empty)"
    fi
}

encrypt_env() {
    log_info "Starting .env encryption..."
    
    if [[ ! -f "${ENV_FILE}" ]]; then
        log_error ".env file not found: ${ENV_FILE}"
        return 1
    fi
    
    if [[ -z "${GPG_RECIPIENT}" ]]; then
        log_error "GPG_RECIPIENT not set - cannot encrypt .env"
        return 1
    fi
    
    if [[ "${DRY_RUN}" == "true" ]]; then
        log_info "[DRY-RUN] Would encrypt .env to ${ENV_ENCRYPTED}"
        return 0
    fi
    
    if gpg \
        --batch \
        --no-tty \
        --trust-model always \
        --encrypt \
        --recipient "${GPG_RECIPIENT}" \
        --output "${ENV_ENCRYPTED}" \
        "${ENV_FILE}"; then
        log_info ".env encryption completed: $(ls -lh "${ENV_ENCRYPTED}" | awk '{print $5}')"
    else
        log_error ".env encryption failed"
        return 1
    fi
}

generate_checksums() {
    log_info "Generating SHA-256 checksums..."
    
    if [[ "${DRY_RUN}" == "true" ]]; then
        log_info "[DRY-RUN] Would generate checksums"
        return 0
    fi
    
    cd "${BACKUP_SET_DIR}"
    
    # Generate checksums
    if [[ -f "ppm_db_${DATE}.sql" ]]; then
        sha256sum "ppm_db_${DATE}.sql" > "ppm_db_${DATE}.sql.sha256"
        log_info "Generated checksum: ppm_db_${DATE}.sql.sha256"
    fi
    
    if [[ -f "media_${DATE}.tar.gz" ]]; then
        sha256sum "media_${DATE}.tar.gz" > "media_${DATE}.tar.gz.sha256"
        log_info "Generated checksum: media_${DATE}.tar.gz.sha256"
    fi
    
    if [[ -f ".env.gpg" ]]; then
        sha256sum ".env.gpg" > ".env.gpg.sha256"
        log_info "Generated checksum: .env.gpg.sha256"
    fi
    
    cd - > /dev/null
}

verify_checksums_locally() {
    log_info "Verifying checksums locally..."
    
    cd "${BACKUP_SET_DIR}"
    
    local all_ok=true
    
    if [[ -f "ppm_db_${DATE}.sql.sha256" ]]; then
        if sha256sum -c "ppm_db_${DATE}.sql.sha256" > /dev/null 2>&1; then
            log_info "✓ ppm_db_${DATE}.sql checksum verified"
        else
            log_error "✗ ppm_db_${DATE}.sql checksum FAILED"
            all_ok=false
        fi
    fi
    
    if [[ -f "media_${DATE}.tar.gz.sha256" ]]; then
        if sha256sum -c "media_${DATE}.tar.gz.sha256" > /dev/null 2>&1; then
            log_info "✓ media_${DATE}.tar.gz checksum verified"
        else
            log_error "✗ media_${DATE}.tar.gz checksum FAILED"
            all_ok=false
        fi
    fi
    
    if [[ -f ".env.gpg.sha256" ]]; then
        if sha256sum -c ".env.gpg.sha256" > /dev/null 2>&1; then
            log_info "✓ .env.gpg checksum verified"
        else
            log_error "✗ .env.gpg checksum FAILED"
            all_ok=false
        fi
    fi
    
    cd - > /dev/null
    
    if [[ "${all_ok}" != "true" ]]; then
        return 1
    fi
}

upload_to_s3() {
    log_info "Uploading backup set to S3..."
    
    if [[ -z "${AWS_S3_BUCKET}" ]]; then
        log_warn "AWS_S3_BUCKET not set - skipping S3 upload"
        return 0
    fi
    
    if [[ "${LOCAL_ONLY}" == "true" ]]; then
        log_info "[LOCAL-ONLY] Skipping S3 upload"
        return 0
    fi
    
    if [[ "${DRY_RUN}" == "true" ]]; then
        log_info "[DRY-RUN] Would upload to s3://${AWS_S3_BUCKET}/${AWS_S3_PREFIX}/"
        return 0
    fi
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI not found - cannot upload to S3"
        return 1
    fi
    
    # Upload entire backup set
    if aws s3 sync \
        "${BACKUP_SET_DIR}" \
        "s3://${AWS_S3_BUCKET}/${AWS_S3_PREFIX}" \
        --region "${AWS_REGION}" \
        --no-progress; then
        log_info "S3 upload completed: s3://${AWS_S3_BUCKET}/${AWS_S3_PREFIX}"
    else
        log_error "S3 upload failed"
        return 1
    fi
}

cleanup_old_backups() {
    log_info "Cleaning up local backups older than 7 days..."
    
    if [[ "${DRY_RUN}" == "true" ]]; then
        log_info "[DRY-RUN] Would delete backups older than 7 days"
        return 0
    fi
    
    find "${BACKUP_DIR}/ppm_backup_"* -maxdepth 0 -type d -mtime +7 -exec rm -rf {} \; 2>/dev/null || true
    log_info "Local backup cleanup completed"
}

generate_summary() {
    log_info "===== Backup Summary ====="
    log_info "Backup Set: ${BACKUP_SET_DIR}"
    
    if [[ -d "${BACKUP_SET_DIR}" ]]; then
        log_info "Contents:"
        ls -lh "${BACKUP_SET_DIR}" | tail -n +2 | while read -r line; do
            log_info "  ${line}"
        done
    fi
    
    log_info "Log file: ${LOG_FILE}"
    log_info "===== End of Summary ====="
}

# ===== Main =====

main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --local-only)
                LOCAL_ONLY=true
                shift
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    log_info "=========================================="
    log_info "PPM Backup Script Started"
    log_info "=========================================="
    
    if [[ "${DRY_RUN}" == "true" ]]; then
        log_info "Running in DRY-RUN mode"
    fi
    
    if [[ "${LOCAL_ONLY}" == "true" ]]; then
        log_info "Running in LOCAL-ONLY mode (no S3 upload)"
    fi
    
    # Execute backup steps
    create_directories
    backup_postgresql || exit 1
    backup_media || exit 1
    encrypt_env || exit 1
    generate_checksums
    verify_checksums_locally || exit 1
    upload_to_s3 || exit 1
    cleanup_old_backups
    generate_summary
    
    log_info "=========================================="
    log_info "PPM Backup Completed Successfully"
    log_info "=========================================="
}

# ===== Error handling =====

trap 'log_error "Script failed at line $LINENO"; exit 1' ERR

# ===== Execute =====

main "$@"
