import hashlib
import hmac
import json

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self) -> str:
        return self.email


class AuthEventLog(models.Model):
    EVENT_LOGIN_SUCCESS = 'login_success'
    EVENT_LOGIN_FAILED = 'login_failed'
    EVENT_LOGOUT = 'logout'
    EVENT_CHOICES = (
        (EVENT_LOGIN_SUCCESS, 'Login Success'),
        (EVENT_LOGIN_FAILED, 'Login Failed'),
        (EVENT_LOGOUT, 'Logout'),
    )

    REASON_UNKNOWN = 'unknown'
    REASON_WRONG_PASSWORD = 'wrong_password'
    REASON_USER_NOT_FOUND = 'user_not_found'
    REASON_INACTIVE_USER = 'inactive_user'
    REASON_INVALID_IDENTIFIER = 'invalid_identifier'
    REASON_CHOICES = (
        (REASON_UNKNOWN, 'Unknown'),
        (REASON_WRONG_PASSWORD, 'Wrong Password'),
        (REASON_USER_NOT_FOUND, 'User Not Found'),
        (REASON_INACTIVE_USER, 'Inactive User'),
        (REASON_INVALID_IDENTIFIER, 'Invalid Identifier'),
    )

    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    event = models.CharField(max_length=32, choices=EVENT_CHOICES, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='auth_event_logs',
    )
    identifier = models.CharField(max_length=255, blank=True, default='')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default='')
    request_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    reason = models.CharField(max_length=64, choices=REASON_CHOICES, default=REASON_UNKNOWN)

    previous_hash = models.CharField(max_length=64, blank=True, default='')
    payload_hash = models.CharField(max_length=64, editable=False)
    entry_hash = models.CharField(max_length=64, unique=True, editable=False, db_index=True)

    class Meta:
        ordering = ('id',)
        verbose_name = 'Auth Event Log'
        verbose_name_plural = 'Auth Event Logs'

    def __str__(self) -> str:
        return f'{self.created_at} {self.event} {self.identifier or "-"}'

    def _payload_dict(self) -> dict:
        return {
            'created_at': self.created_at.isoformat() if self.created_at else '',
            'event': self.event,
            'user_id': self.user_id,
            'identifier': self.identifier,
            'ip_address': self.ip_address or '',
            'user_agent': self.user_agent,
            'request_id': self.request_id,
            'reason': self.reason,
        }

    def compute_payload_hash(self) -> str:
        canonical = json.dumps(self._payload_dict(), sort_keys=True, ensure_ascii=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def compute_entry_hash(self) -> str:
        signing_key = getattr(settings, 'AUTH_LOG_SIGNING_KEY', settings.SECRET_KEY)
        message = f'{self.previous_hash}|{self.payload_hash}'.encode('utf-8')
        return hmac.new(signing_key.encode('utf-8'), message, hashlib.sha256).hexdigest()
