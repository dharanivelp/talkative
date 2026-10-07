import unittest
from unittest.mock import patch

from talkative_backend import emailer


class SmtpEmailTests(unittest.TestCase):
    @patch.object(emailer, "SMTP_HOST", "mail.aiccloud.in")
    @patch.object(emailer, "SMTP_PORT", 587)
    @patch.object(emailer, "SMTP_USERNAME", "sender@example.com")
    @patch.object(emailer, "SMTP_PASSWORD", "mailbox-password")
    @patch.object(emailer, "SMTP_FROM", "sender@example.com")
    @patch.object(emailer.smtplib, "SMTP")
    def test_sends_otp_using_starttls(self, smtp_class):
        server = smtp_class.return_value.__enter__.return_value

        emailer.send_otp_email("recipient@example.com", "012345", "login")

        server.starttls.assert_called_once()
        server.login.assert_called_once_with("sender@example.com", "mailbox-password")
        message = server.send_message.call_args.args[0]
        self.assertEqual(message["To"], "recipient@example.com")
        self.assertIn("012345", message.get_body(preferencelist=("plain",)).get_content())
        html = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("Talkative_Banner_Black_on_Transparent_2400x720.png", html)
        self.assertIn("012345", html)
        self.assertNotIn("mailbox-password", message.as_string())

    @patch.object(emailer, "SMTP_HOST", "")
    @patch.object(emailer.smtplib, "SMTP")
    def test_rejects_missing_smtp_configuration(self, smtp_class):
        with self.assertRaises(emailer.EmailConfigurationError):
            emailer.send_otp_email("recipient@example.com", "012345", "login")
        smtp_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
