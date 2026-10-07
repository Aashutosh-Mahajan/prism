"""Account models: verification codes, payments and the admin audit log."""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone


class EmailCode(models.Model):
    """A short numeric code mailed to a user to verify an address or reset a password.

    One code is live per (user, purpose); issuing a new one retires the old one.
    """

    PURPOSES = ("verify_email", "reset_password")
    LIFETIME_MINUTES = 10
    MAX_ATTEMPTS = 5
    RESEND_COOLDOWN_SECONDS = 60

    user = models.ForeignKey("auth.User", on_delete=models.CASCADE)
    purpose = models.CharField(max_length=20)
    code_hash = models.CharField(max_length=64)
    attempts = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)

    @staticmethod
    def _hash(user_id, purpose, code):
        return hashlib.sha256(f"{user_id}:{purpose}:{code}".encode()).hexdigest()

    @classmethod
    def issue(cls, user, purpose):
        now = timezone.now()
        cls.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(used_at=now)
        code = f"{secrets.randbelow(1_000_000):06d}"
        instance = cls.objects.create(
            user=user,
            purpose=purpose,
            code_hash=cls._hash(user.pk, purpose, code),
            expires_at=now + timedelta(minutes=cls.LIFETIME_MINUTES),
        )
        return instance, code

    @classmethod
    def seconds_until_resend(cls, user, purpose):
        latest = cls.objects.filter(user=user, purpose=purpose).order_by("-created_at").first()
        if not latest:
            return 0
        elapsed = (timezone.now() - latest.created_at).total_seconds()
        return max(0, int(cls.RESEND_COOLDOWN_SECONDS - elapsed))

    @classmethod
    def verify(cls, user, purpose, code):
        """Validate a submitted code. Returns (ok, reason); reason is invalid, expired or
        too_many_attempts on failure."""
        live = cls.objects.filter(user=user, purpose=purpose, used_at__isnull=True).first()
        if live is None or timezone.now() >= live.expires_at:
            return False, "expired"
        if live.attempts >= cls.MAX_ATTEMPTS:
            return False, "too_many_attempts"
        if not hmac.compare_digest(live.code_hash, cls._hash(user.pk, purpose, str(code).strip())):
            live.attempts += 1
            live.save(update_fields=["attempts"])
            return False, "invalid"
        live.used_at = timezone.now()
        live.save(update_fields=["used_at"])
        return True, None


class Payment(models.Model):
    """A simulated payment for an order."""

    user = models.ForeignKey("auth.User", on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, default="pending")
    transaction_id = models.CharField(max_length=255, null=True)

    def simulate_payment(self):
        """Simulate a payment. Always succeeds in development."""
        self.transaction_id = f"SIM-{secrets.token_hex(6).upper()}"
        self.status = "completed"
        self.save()
        return self


class AuditLog(models.Model):
    """Immutable log of admin actions. Rows are only ever created."""

    actor = models.ForeignKey("auth.User", on_delete=models.PROTECT)
    action = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)
