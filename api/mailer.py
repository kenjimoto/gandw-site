"""Outbound mail. SES in production; a local outbox (printed and kept in memory) in dev and tests."""
import sys


class SesMailer:
    def __init__(self, sender):
        import boto3
        self._ses = boto3.client("sesv2")
        self.sender = sender

    def send(self, to, subject, text, reply_to=None):
        kw = dict(
            FromEmailAddress=self.sender,
            Destination={"ToAddresses": [to]},
            Content={"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"},
                                "Body": {"Text": {"Data": text, "Charset": "UTF-8"}}}},
        )
        if reply_to:
            kw["ReplyToAddresses"] = [reply_to]
        self._ses.send_email(**kw)


class LocalMailer:
    def __init__(self, sender="Goggles & Windchimes <noreply@gandw.io>", quiet=False):
        self.sender = sender
        self.outbox = []
        self.quiet = quiet

    def send(self, to, subject, text, reply_to=None):
        self.outbox.append({"to": to, "subject": subject, "text": text, "reply_to": reply_to})
        if not self.quiet:
            bar = "-" * 60
            sys.stderr.write(f"\n{bar}\n  LOCAL MAIL (not sent)\n  To: {to}\n  Reply-To: {reply_to or '-'}\n"
                             f"  Subject: {subject}\n\n{text}\n{bar}\n")
