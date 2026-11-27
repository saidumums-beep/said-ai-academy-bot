import hashlib
import hmac
import json
import os
import re
from collections import deque
from urllib.error import URLError
from urllib.request import Request, urlopen

from flask import Flask, request


INSTAGRAM_URL = "https://www.instagram.com/said688886/"

CONSENT = {
    "inline_keyboard": [
        [
            {"text": "Да", "callback_data": "consent_yes"},
            {"text": "Нет", "callback_data": "consent_no"},
        ],
        [{"text": "Подробнее", "callback_data": "consent_details"}],
    ]
}

MAIN_KEYBOARD = {
    "keyboard": [[{"text": "Меню"}]],
    "resize_keyboard": True,
    "is_persistent": True,
}

MENU = {
    "keyboard": [
        [{"text": "Дата"}, {"text": "Месяц"}, {"text": "Цены"}],
        [{"text": "Чему учим"}, {"text": "Дата, время, место"}],
        [{"text": "Владелец"}, {"text": "Администратор"}],
        [{"text": "Номер администратора"}, {"text": "Instagram"}],
        [{"text": "Подать заявку"}, {"text": "Настройки данных"}],
        [{"text": "Меню"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

WELCOME = "Приветствуем вас на курсах по ИИ школы Саид AI Studio!"

FLOW_TITLE = "SAID AI Academy · Учебный поток"
FLOW_PRICE = "Стоимость обучения — 15 000 ₽ за один поток."
FLOW_TIME = "Занятия проходят через день в 18:00 по московскому времени."
FLOW_START = "Поток начнётся, когда наберётся 50 участников."
FLOW_FORMAT = "Формат — онлайн. Подключиться можно из любого города."
FLOW_BONUSES = "Участников ждут бонусы и призы."
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
    admin_name = os.environ.get("ACADEMY_ADMIN_NAME", "").strip()
    admin_phone = os.environ.get("ACADEMY_ADMIN_PHONE", "").strip()
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

    def send_flow_details(user_id):
        send(
            user_id,
            f"{FLOW_TITLE}\n\n"
            f"{FLOW_START}\n"
            f"{FLOW_TIME}\n"
            f"{FLOW_FORMAT}\n"
            f"{FLOW_PRICE}\n\n"
            f"{FLOW_BONUSES}",
            MENU,
        )

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

        if action == "flow_details":
            send_flow_details(user_id)
        elif action == "consent_details":
            send(user_id, DETAILS, CONSENT)
        elif action == "consent_yes":
            if admin_id is None:
                send(user_id, "Академия готовит запуск. Передача сообщений пока выключена.")
                return
            consent[user_id] = True
            send(user_id, f"Согласие принято.\n\n{FLOW_TITLE}\n{FLOW_PRICE}\n{FLOW_BONUSES}", MENU)
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

        if command in ("/start", "/help"):
            send(user_id, f"{WELCOME}\n\n{FLOW_START}\n{FLOW_FORMAT}", MAIN_KEYBOARD)
            if user_id not in consent:
                send(user_id, NOTICE, CONSENT)
            return

        if choice == "меню" or command == "/menu":
            send(user_id, f"{WELCOME}\nВыберите раздел.", MENU)
            return

        if choice in ("дата", "месяц"):
            send(user_id, f"Дата и месяц старта пока не назначены. {FLOW_START}", MENU)
            return

        if choice in ("цены", "цена"):
            send(user_id, f"{FLOW_PRICE}\n{FLOW_BONUSES}", MENU)
            return

        if choice == "владелец":
            send(user_id, "Владелец школы Саид AI Studio — Саид.", MENU)
            return

        if choice == "администратор":
            text = f"Администратор школы — {admin_name}." if admin_name else (
                "Имя администратора пока не указано. Для связи нажмите «Подать заявку»."
            )
            send(user_id, text, MENU)
            return

        if choice == "номер администратора":
            text = f"Номер администратора: {admin_phone}" if admin_phone else (
                "Номер для связи пока не указан. Нажмите «Подать заявку»."
            )
            send(user_id, text, MENU)
            return

        if choice in ("instagram", "инстаграм") or command == "/instagram":
            send(user_id, f"Instagram SAID AI Academy: @said688886\n{INSTAGRAM_URL}", MENU)
        elif choice in ("дата, время, место", "дата", "время", "место", "условия обучения") or any(
            word in choice for word in (
                "стоит", "стоимость", "цена", "формат", "бонус", "приз",
                "расписание", "во сколько", "когда старт", "где проходит",
            )
        ):
            send_flow_details(user_id)
        elif command == "/program" or choice == "чему учим" or "курс" in choice or "программа" in choice:
            send(
                user_id,
                f"{FLOW_TITLE}\n\n"
                "Чему будем учиться\n"
                "• Составлять запросы к ИИ и готовить тексты для постов и рекламы.\n"
                "• Создавать изображения, рекламные макеты и короткие ИИ-видео.\n"
                "• Знакомиться с созданием простых сайтов и Telegram-ботов с помощью ИИ.\n\n"
                "Как проходит обучение\n"
                "Онлайн смотрим, как выполняется задача, затем повторяем шаги на практике "
                "и разбираем получившийся результат.\n\n"
                f"{FLOW_START}\n{FLOW_TIME}",
                MENU,
            )
        elif command == "/apply" or choice == "подать заявку":
            if consent.get(user_id) is not True or admin_id is None:
                send(user_id, NOTICE, CONSENT)
                return
            send(
                user_id,
                "При отправке заявки администратор получит ссылку на ваш профиль.",
                {"inline_keyboard": [[
                    {"text": "Отправить заявку", "callback_data": "apply"}
                ]]},
            )
        else:
            send(
                user_id,
                "Я отвечаю на вопросы об обучении в SAID AI Academy. Выберите раздел в меню.",
                MENU,
            )

        if consent.get(user_id) is True and user_id != admin_id and not text.startswith("/"):
            delivered = send(admin_id, f"Чат {user_id}\n\n{text[:3900]}")
            recent = dialogs.pop(user_id, deque(maxlen=10))
            recent.append(delivered["message_id"])
            dialogs[user_id] = recent

    @app.get("/")
    @app.get("/health")
    def health():
        return "ok"

    @app.post("/telegram/webhook")
    def webhook():
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(provided.encode(), secret.encode()):
            return "", 403

        update = request.get_json(silent=True)
        if not isinstance(update, dict):
            return "", 400

        try:
            if "callback_query" in update:
                handle_callback(update["callback_query"])
            elif "message" in update:
                handle_message(update["message"])
        except TelegramError as exc:
            app.logger.warning("Telegram API failed: %s", exc)
        return "", 200

    if public_url:
        webhook_url = f"{public_url}/telegram/webhook"
        telegram(
            "setWebhook",
            url=webhook_url,
            secret_token=secret,
            allowed_updates=["message", "callback_query"],
            max_connections=1,
        )
        if telegram("getWebhookInfo").get("url") != webhook_url:
            raise RuntimeError("Telegram не подтвердил вебхук.")

    return app
