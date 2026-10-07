import smtplib
import ssl
from html import escape
from email.message import EmailMessage
from email.utils import formataddr

from talkative_backend.config import PUBLIC_SITE_URL, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME


class EmailConfigurationError(RuntimeError):
    pass


class EmailDeliveryError(RuntimeError):
    pass


def send_otp_email(recipient, code, purpose):
    sender = SMTP_FROM or SMTP_USERNAME
    if not SMTP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD or not sender:
        raise EmailConfigurationError("SMTP email settings are incomplete")
    if not 1 <= SMTP_PORT <= 65535:
        raise EmailConfigurationError("SMTP_PORT must be between 1 and 65535")

    message = EmailMessage()
    message["Subject"] = "Your Talkative verification code"
    message["From"] = formataddr(("Talkative", sender))
    message["To"] = recipient
    escaped_purpose = escape(purpose)
    escaped_code = escape(code)
    message.set_content(
        f"Your Talkative {purpose} verification code is {code}.\n\n"
        "This code expires in 10 minutes. If you did not request it, you can ignore this email."
    )
    message.add_alternative(
        f"""\
<!doctype html>
<html lang="en">
<body style="margin:0;padding:32px 16px;background:#f4f6f8;font-family:Arial,sans-serif;color:#17202a">
  <div style="max-width:520px;margin:0 auto;padding:30px 28px;background:#fff;border:1px solid #d5dfdc;border-radius:16px">
    <div style="text-align:center;padding-bottom:22px;border-bottom:1px solid #e5e9e7">
      <img src="{escape(PUBLIC_SITE_URL, quote=True)}/static/logo/Talkative_Banner_Black_on_Transparent_2400x720.png" width="180" alt="Talkative" style="display:block;width:180px;height:auto;margin:0 auto">
    </div>
    <h1 style="margin:24px 0 8px;font-size:22px;text-align:center">Your verification code</h1>
    <p style="margin:0;text-align:center;color:#52645a">Use this code to complete your Talkative {escaped_purpose} verification.</p>
    <div style="margin:24px auto;padding:16px;background:#e8f0ed;border:1px solid #d5dfdc;border-radius:12px;text-align:center">
      <span style="font-size:32px;font-weight:700;letter-spacing:8px;color:#126b61">{escaped_code}</span>
    </div>
    <p style="margin:0;text-align:center;color:#52645a">This code expires in 10 minutes.</p>
    <p style="margin:20px 0 0;text-align:center;color:#78827d;font-size:12px">If you did not request this code, you can ignore this email.</p>
  </div>
</body>
</html>""",
        subtype="html",
    )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise EmailDeliveryError("SMTP could not deliver the verification email") from error
