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

FLOW_TITLE = "SAID AI Academy · 15-й учебный поток"
FLOW_PRICE = "Стоимость обучения — 15 000 ₽ за один поток."
FLOW_TIME = "Занятия проходят через день в 18:00 по московскому времени."
FLOW_START = "15-й поток начнётся, когда наберётся 50 участников."
FLOW_FORMAT = "Формат — онлайн. Подключиться можно из любого города."
FLOW_BONUSES = "Участников ждут бонусы и призы."
NOTICE = (
    "Разрешаете обработку данных для общения с SAID AI Academy?\n\n"
    "Если нажмёте «Да», администратор сможет читать новые текстовые сообщения, "
    "которые вы отправляете этому боту.
