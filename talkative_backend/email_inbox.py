import imaplib
import re
import ssl
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser

from talkative_backend.config import IMAP_HOST, IMAP_PORT, SMTP_PASSWORD, SMTP_USERNAME

MAX_MESSAGES = 50
MAX_MESSAGE_BYTES = 512 * 1024


class InboxConfigurationError(RuntimeError):
    pass


class InboxUnavailableError(RuntimeError):
    pass


class MessageTooLargeError(RuntimeError):
    pass


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _text_body(message):
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeError):
        return ""
    if part.get_content_type() == "text/html":
        extractor = _TextExtractor()
        extractor.feed(content)
        content = " ".join(extractor.parts)
    return re.sub(r"\s+", " ", content).strip()


def _message_metadata(client, uid):
    status, data = client.uid(
        "fetch",
        uid,
        "(BODY.PEEK[HEADER.FIELDS (DATE FROM TO SUBJECT)] RFC822.SIZE FLAGS)",
    )
    if status != "OK":
        raise InboxUnavailableError("Could not read message metadata")
    chunks = [item for item in data if isinstance(item, tuple)]
    if not chunks:
        raise InboxUnavailableError("Message is no longer available")
    descriptor, raw_headers = chunks[0]
    match = re.search(rb"RFC822\.SIZE\s+(\d+)", descriptor, re.IGNORECASE)
    size = int(match.group(1)) if match else 0
    headers = BytesParser(policy=policy.default).parsebytes(raw_headers)
    flags_match = re.search(rb"FLAGS\s+\(([^)]*)\)", descriptor)
    flags = flags_match.group(1).split() if flags_match else []
    return {
        "uid": uid.decode("ascii") if isinstance(uid, bytes) else str(uid),
        "date": str(headers.get("Date", "")),
        "from": str(headers.get("From", "")),
        "to": str(headers.get("To", "")),
        "subject": str(headers.get("Subject", "(no subject)")),
        "size": size,
        "is_read": b"\\Seen" in flags,
    }


def _connect():
    if not IMAP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD or not 1 <= IMAP_PORT <= 65535:
        raise InboxConfigurationError("IMAP mailbox settings are incomplete")
    client = None
    try:
        client = imaplib.IMAP4_SSL(
            IMAP_HOST,
            IMAP_PORT,
            ssl_context=ssl.create_default_context(),
            timeout=15,
        )
        client.login(SMTP_USERNAME, SMTP_PASSWORD)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise InboxUnavailableError("Could not open the mailbox inbox")
        return client
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as error:
        if client is not None:
            _close(client)
        raise InboxUnavailableError("Could not connect to the support mailbox") from error
    except InboxUnavailableError:
        if client is not None:
            _close(client)
        raise


def _close(client):
    try:
        client.logout()
    except (imaplib.IMAP4.error, OSError):
        pass


def list_messages():
    client = _connect()
    try:
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise InboxUnavailableError("Could not list inbox messages")
        uids = data[0].split() if data and data[0] else []
        selected = list(reversed(uids[-MAX_MESSAGES:]))
        messages = [_message_metadata(client, uid) for uid in selected]
        return {"messages": messages, "has_more": len(uids) > len(selected)}
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as error:
        raise InboxUnavailableError("Could not read inbox messages") from error
    finally:
        _close(client)


def read_message(uid):
    if not re.fullmatch(r"\d{1,20}", uid or ""):
        raise ValueError("Invalid mailbox message ID")
    client = _connect()
    try:
        metadata = _message_metadata(client, uid.encode("ascii"))
        if metadata["size"] > MAX_MESSAGE_BYTES:
            raise MessageTooLargeError("This email is too large to display in the dashboard")
        status, data = client.uid("fetch", uid, "(BODY.PEEK[])")
        if status != "OK":
            raise InboxUnavailableError("Could not read this inbox message")
        chunks = [item for item in data if isinstance(item, tuple)]
        if not chunks:
            raise InboxUnavailableError("Message is no longer available")
        message = BytesParser(policy=policy.default).parsebytes(chunks[0][1])
        return {**metadata, "body": _text_body(message)}
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as error:
        raise InboxUnavailableError("Could not read this inbox message") from error
    finally:
        _close(client)
