"""Notification channel. Default: Telegram Bot API.

Secrets come from env (set as MotherDuck Flight secrets / GitHub secrets):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
If the token is absent, falls back to console output (handy for dev/tests).
"""
from __future__ import annotations

import os
import sys

import requests


class Notifier:
    def send(self, text: str) -> bool:
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    def send(self, text: str) -> bool:
        msg = "[NOTIFY]\n" + text
        try:
            print(msg)
        except UnicodeEncodeError:  # narrow dev consoles (e.g. Windows cp1252)
            enc = sys.stdout.encoding or "ascii"
            print(msg.encode(enc, "replace").decode(enc, "replace"))
        return True


class TelegramNotifier(Notifier):
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send(self, text: str) -> bool:
        r = requests.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=20,
        )
        if not r.ok:
            print(f"[telegram] send failed {r.status_code}: {r.text[:200]}")
        return r.ok


def get_notifier() -> Notifier:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return TelegramNotifier(token, chat_id)
    print("[notify] TELEGRAM_BOT_TOKEN/CHAT_ID not set — using console notifier")
    return ConsoleNotifier()
