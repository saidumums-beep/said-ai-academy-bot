import hashlib
import hmac
import json
import os
import re
from collections import deque
from urllib.error import URLError
from urllib.request import Request, urlopen

from flask import Flask, request


CONSENT = {
    "inline_keyboard": [
        [
            {"text": "Да", "callback_data": "consent_yes"},
            {"text": "Нет", "callback_data": "consent_no"},
        ],
        [{"text": "Подробнее", "callback_data": "consent_details"}],
    ]
}

MENU = {
    "keyboard": [
        [{"text": "Курсы и программа"}, {"text": "Условия обучения"}],
        [{"text": "Подать заявку"}, {"text": "Настройки данных"}],
    ],
    "resize_keyboard": True,
}

NOTICE = (
    "Разрешаете обработку данных для общения с SAID AI Academy?\n\n"
    "Если нажмёте «Да», администратор сможет читать новые текстовые сообщения, "
    "которые вы отправляете этому боту. Нажмите «Подробнее», чтобы узнать, "
    "какие данные передаются и как отозвать согласие."
)

DETAILS = (
    "После «Да» администратор получает копии ваших новых текстовых сообщений "
    "и Telegram ID, чтобы различать диалоги. Если вы отдельно отправите "
    "заявку, администратор также получит ссылку на ваш профиль для связи.\n\n"
    "Бот не просит телефон или ФИО. Пожалуйста, не отправляйте телефон, "
    "пароли, документы и другие личные данные в сообщениях.\n\n"
    "При выборе «Нет» сообщения не передаются администратору, а справка "
    "о курсах остаётся доступной. Отозвать согласие можно через «Настройки "
    "данных» или команду /privacy. Уже доставленные копии остаются в Telegram."
)


class TelegramError(Exception):
    pass


def create_app():
    token = os.environ.get("BOT_TOKEN", "").strip()
    admin_value = os.environ.get("ADMIN_CHAT_ID", "").strip()
    public_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")

    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise RuntimeError("Укажите BOT_TOKEN в настройках Render.")
    if admin_value and not re.fullmatch(r"[1-9][0-9]*", admin_value):
        raise RuntimeError("ADMIN_CHAT_ID должен быть ID личного аккаунта.")

    admin_id = int(admin_value) if admin_value else None
    secret = hmac.new(
        token.encode(),
        b"said-ai-academy-webhook-v1",
        hashlib.sha256,
    ).hexdigest()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

    # Only current consent decisions and Telegram message IDs live in RAM.
    # Message text is kept by Telegram in the administrator's chat.
    consent = {}
    dialogs = {}

    def telegram(method, **params):
        outbound = Request(
            f"https://api.telegram.org/bot{token}/{method}",
            data=json.dumps(params).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(outbound, timeout=7) as response:
                result = json.load(response)
        except (URLError, OSError, ValueError):
            raise TelegramError(method) from None

        if not result.get("ok"):
            raise TelegramError(method)
        return result["result"]

    def send(chat_id, text, markup=None):
        params = {"chat_id": chat_id, "text": text}
        if markup is not None:
            params["reply_markup"] = markup
        return telegram("sendMessage", **params)

    def is_admin(chat, sender):
        return (
            admin_id is not None
            and chat.get("type") == "private"
            and chat.get("id") == admin_id
            and sender.get("id") == admin_id
        )

    def show_dialogs():
        user_ids = list(reversed(dialogs))[:20]
        if not user_ids:
            send(admin_id, "Пока нет новых сообщений от пользователей, давших согласие.")
            return

        rows = [
            [{"text": f"Чат {user_id}", "callback_data": f"read:{user_id}"}]
            for user_id in user_ids
        ]
        send(admin_id, "Выберите диалог. Показаны 20 последних активных чатов.", {
            "inline_keyboard": rows,
        })

    def show_chat(user_id):
        message_ids = dialogs.get(user_id)
        if consent.get(user_id) is not True or not message_ids:
            send(admin_id, "Диалог сейчас недоступен.")
            return

        send(admin_id, f"Последние сообщения из чата {user_id}.")
        telegram(
            "copyMessages",
            chat_id=admin_id,
            from_chat_id=admin_id,
            message_ids=list(message_ids),
        )

    def handle_callback(callback):
        chat = callback.get("message", {}).get("chat", {})
        sender = callback.get("from", {})
        user_id = sender.get("id")
        action = callback.get("data", "")

        if (
            chat.get("type") != "private"
            or type(user_id) is not int
            or chat.get("id") != user_id
        ):
            return

        telegram("answerCallbackQuery", callback_query_id=callback["id"])

        if action == "read_chats" or action.startswith("read:"):
            if not is_admin(chat, sender):
                return
            if action == "read_chats":
                show_dialogs()
            elif re.fullmatch(r"read:[1-9][0-9]*", action):
                show_chat(int(action.split(":", 1)[1]))
            return

        if action == "consent_details":
            send(user_id, DETAILS, CONSENT)
        elif action == "consent_yes":
            if admin_id is None:
                send(user_id, "Академия готовит запуск. Передача сообщений пока выключена.")
                return
            consent[user_id] = True
            send(user_id, "Согласие принято. Выберите раздел академии.", MENU)
        elif action == "consent_no":
            consent[user_id] = False
            dialogs.pop(user_id, None)
            send(user_id, "Передача новых сообщений выключена. Справка доступна.", MENU)
        elif action == "apply":
            if consent.get(user_id) is not True or admin_id is None:
                send(user_id, NOTICE, CONSENT)
                return

            username = sender.get("username", "")
            if re.fullmatch(r"[A-Za-z0-9_]+", username):
                profile = f"https://t.me/{username}"
            else:
                profile = f"tg://user?id={user_id}"

            send(admin_id, "Новая заявка в SAID AI Academy.", {
                "inline_keyboard": [[{"text": "Открыть профиль", "url": profile}]],
            })
            send(user_id, "Заявка отправлена администратору.", MENU)

    def handle_message(message):
        chat = message.get("chat", {})
        sender = message.get("from", {})
        user_id = sender.get("id")
        text = message.get("text", "").strip()

        if (
            chat.get("type") != "private"
            or type(user_id) is not int
            or chat.get("id") != user_id
            or not text
        ):
            return

        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
        choice = text.casefold()

        if command == "/id":
            send(user_id, f"Ваш Telegram ID: {user_id}")
            return

        if text == "29052016Said":
            if is_admin(chat, sender):
                send(user_id, "Панель администратора.", {
                    "inline_keyboard": [[
                        {"text": "Читать чаты", "callback_data": "read_chats"}
                    ]],
                })
            return

        if command == "/privacy" or choice == "настройки данных":
            send(user_id, NOTICE, CONSENT)
            return

        if user_id not in consent:
            send(user_id, NOTICE, CONSENT)
            return

        if command in ("/start", "/help"):

                user_id,
                "При отправке заявки администратор получит ссылку на ваш
