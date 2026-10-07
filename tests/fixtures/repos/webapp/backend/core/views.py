"""HTTP views for sign-in, registration and email codes."""

from django.conf import settings
from django.core.mail import send_mail
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import EmailCode

CODE_COPY = {
    "verify_email": {
        "subject": "Your Platform verification code {code}",
        "heading": "Confirm your email",
        "lead": "use this code to confirm your email address.",
    },
    "reset_password": {
        "subject": "Reset your Platform password ({code})",
        "heading": "Reset your password",
        "lead": "use this code to choose a new password.",
    },
}


def _send_code_email(user, code, purpose):
    """Send a 6-digit code as a plain-text email."""
    copy = CODE_COPY[purpose]
    name = user.first_name or "there"
    minutes = EmailCode.LIFETIME_MINUTES
    text = (
        f"Hi {name}, {copy['lead']}\n\n    {code}\n\n"
        f"The code expires in {minutes} minutes.\n\n- Platform"
    )
    send_mail(
        copy["subject"].format(code=code),
        text,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
    )


def _issue_code(user, purpose):
    """Issue and email a code, returning the cooldown and expiry for the client."""
    wait = EmailCode.seconds_until_resend(user, purpose)
    if wait:
        return {"resend_in": wait}
    _, code = EmailCode.issue(user, purpose)
    _send_code_email(user, code, purpose)
    return {
        "resend_in": EmailCode.RESEND_COOLDOWN_SECONDS,
        "expires_in": EmailCode.LIFETIME_MINUTES * 60,
    }


class LoginView(APIView):
    def post(self, request):
        user = request.user
        if not user.is_authenticated:
            return Response({"error": {"message": "Invalid credentials"}}, status=401)
        if not user.profile.email_verified:
            return Response(_issue_code(user, "verify_email"), status=403)
        return Response({"token": "..."})


class VerifyEmailView(APIView):
    def post(self, request):
        ok, reason = EmailCode.verify(request.user, "verify_email", request.data.get("code"))
        if not ok:
            return Response({"error": {"message": reason}}, status=400)
        return Response({"verified": True})
