"""Verified mailbox registration; SMTP credentials stay in server configuration."""
import asyncio
from email.message import EmailMessage
from email.utils import parseaddr
import hashlib
import hmac
import os
import re
import smtplib
import ssl


def normalize_email(value):
    if not isinstance(value, str):
        raise ValueError('邮箱格式不正确。')
    value = value.strip().lower()
    if (len(value) > 254 or not re.fullmatch(
            r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@"
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+", value)
            or len(value.split('@')[0]) > 64):
        raise ValueError('邮箱格式不正确。')
    return value


def code_identity(email, purpose, csrf, code=''):
    key = hashlib.sha256((purpose + '\0' + email + '\0' + csrf).encode()).hexdigest()
    proof = hmac.new(csrf.encode(), (key + '\0' + code).encode(), hashlib.sha256).hexdigest()
    return key, proof


class VerificationMailer:
    def __init__(self):
        self.slots = asyncio.Semaphore(2)

    @property
    def ready(self):
        security = os.getenv('SMTP_SECURITY', 'ssl')
        try:
            normalize_email(parseaddr(os.getenv('SMTP_FROM', ''))[1])
            port = int(os.getenv('SMTP_PORT', '465' if security == 'ssl' else '587'))
        except (ValueError, IndexError):
            return False
        return bool(os.getenv('SMTP_HOST') and 1 <= port <= 65535
                    and security in ('ssl', 'starttls')
                    and (not os.getenv('SMTP_USERNAME') or os.getenv('SMTP_PASSWORD')))

    @property
    def registration_open(self):
        return os.getenv('REGISTRATION_ENABLED', 'true').lower() == 'true' and self.ready

    def _send(self, recipient, code):
        sender = os.environ['SMTP_FROM']
        normalize_email(parseaddr(sender)[1])
        message = EmailMessage()
        message['Subject'] = 'Resource Hub 邮箱验证码'
        message['From'] = sender
        message['To'] = recipient
        message.set_content(f'你的邮箱验证码是：{code}\n\n10 分钟内有效。请勿向他人提供验证码。\n如果不是你本人操作，请忽略此邮件。')
        security = os.getenv('SMTP_SECURITY', 'ssl')
        port = int(os.getenv('SMTP_PORT', '465' if security == 'ssl' else '587'))
        context = ssl.create_default_context()
        if security == 'ssl':
            client = smtplib.SMTP_SSL(os.environ['SMTP_HOST'], port, timeout=10, context=context)
        elif security == 'starttls':
            client = smtplib.SMTP(os.environ['SMTP_HOST'], port, timeout=10)
        else:
            raise ValueError('SMTP requires TLS')
        with client:
            if security == 'starttls':
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            username = os.getenv('SMTP_USERNAME')
            if username:
                client.login(username, os.environ['SMTP_PASSWORD'])
            if client.send_message(message):
                raise ValueError('SMTP recipient refused')

    async def send(self, recipient, code):
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=2)
        except asyncio.TimeoutError:
            raise ValueError('mail busy') from None
        try:
            await asyncio.to_thread(self._send, recipient, code)
        finally:
            self.slots.release()
