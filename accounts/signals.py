import logging
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db import transaction
from django.dispatch import receiver
from django.utils import timezone

from .models import AuthEventLog

logger = logging.getLogger(__name__)


def _mask_identifier(identifier: str) -> str:
    if not identifier:
        return ''
    if '@' in identifier:
        local, _, domain = identifier.partition('@')
        if len(local) <= 2:
            local_masked = '*' * len(local)
        else:
            local_masked = local[:2] + ('*' * (len(local) - 2))
        return f'{local_masked}@{domain}'
    if len(identifier) <= 4:
        return '*' * len(identifier)
    return identifier[:2] + ('*' * (len(identifier) - 4)) + identifier[-2:]


def _extract_identifier(credentials: dict | None) -> str:
    if not credentials:
        return ''
    for key in ('username', 'email'):
        value = credentials.get(key)
        if value:
            return str(value).strip()
    return ''


def _request_ip(request) -> str | None:
    if not request:
        return None
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _request_user_agent(request) -> str:
    if not request:
        return ''
    return request.META.get('HTTP_USER_AGENT', '')[:512]


def _request_id(request) -> str:
    if not request:
        return uuid.uuid4().hex
    existing = request.META.get('HTTP_X_REQUEST_ID')
    if existing:
        return str(existing)[:64]
    generated = uuid.uuid4().hex
    request.META['HTTP_X_REQUEST_ID'] = generated
    return generated


def _failed_reason(identifier: str) -> str:
    if not identifier:
        return AuthEventLog.REASON_INVALID_IDENTIFIER
    user_model = get_user_model()
    user = user_model.objects.filter(email__iexact=identifier).first()
    if user is None:
        return AuthEventLog.REASON_USER_NOT_FOUND
    if not user.is_active:
        return AuthEventLog.REASON_INACTIVE_USER
    return AuthEventLog.REASON_WRONG_PASSWORD


def _append_auth_log(*, event: str, user=None, identifier: str = '', request=None, reason: str = AuthEventLog.REASON_UNKNOWN) -> None:
    try:
        with transaction.atomic():
            previous = AuthEventLog.objects.select_for_update().order_by('-id').first()
            log = AuthEventLog(
                created_at=timezone.now(),
                event=event,
                user=user if getattr(user, 'pk', None) else None,
                identifier=_mask_identifier(identifier.strip()),
                ip_address=_request_ip(request),
                user_agent=_request_user_agent(request),
                request_id=_request_id(request),
                reason=reason,
                previous_hash=previous.entry_hash if previous else '',
            )
            log.payload_hash = log.compute_payload_hash()
            log.entry_hash = log.compute_entry_hash()
            log.save()
    except Exception:
        # 認証処理自体を止めないため、ログ記録失敗は握りつぶす。
        logger.exception('Failed to append auth event log.')


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    _append_auth_log(
        event=AuthEventLog.EVENT_LOGIN_SUCCESS,
        user=user,
        identifier=getattr(user, 'email', ''),
        request=request,
        reason=AuthEventLog.REASON_UNKNOWN,
    )


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    _append_auth_log(
        event=AuthEventLog.EVENT_LOGOUT,
        user=user,
        identifier=getattr(user, 'email', '') if user else '',
        request=request,
        reason=AuthEventLog.REASON_UNKNOWN,
    )


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request=None, **kwargs):
    identifier = _extract_identifier(credentials)
    _append_auth_log(
        event=AuthEventLog.EVENT_LOGIN_FAILED,
        user=None,
        identifier=identifier,
        request=request,
        reason=_failed_reason(identifier),
    )
