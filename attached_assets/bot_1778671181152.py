# -*- coding: utf-8 -*-
import sys
import os

# Читаем файл бота
filepath = 'attached_assets/bot_1778671181152.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Правильный русский текст с эмодзи
correct_text = '''    caption_text = (
        f"<blockquote>\U0001F947 <b>Добро пожаловать в {BOT_NAME}</b></blockquote>\\n\\n"
        "<blockquote>\u2705 Здесь заключаются безопасные сделки между продавцами и покупателями.</blockquote>\\n\\n"
        f"<blockquote>\U0001F4B0 Комиссия сервиса: 1%</blockquote>\\n\\n"
        f"<blockquote>\U0001F198 По вопросам: {SUPPORT_USERNAME}</blockquote>"
    )'''

# Старый битый текст (с вопросительными знаками)
old_text_1 = '''    caption_text = (
        f"<blockquote>\U0001F947 <b>????? ?????????? ? {BOT_NAME}</b></blockquote>\\n\\n"
        "<blockquote>\u2705 ????? ??????????? ?????????? ?????? ????? ?????????? ? ????????????.</blockquote>\\n\\n"
        f"<blockquote>\U0001F4B0 ???????? ???????: 1%</blockquote>\\n\\n"
        f"<blockquote>\U0001F198 ?? ????????: {SUPPORT_USERNAME}</blockquote>"
    )'''

# Пробуем оба варианта
count1 = content.count(old_text_1)
print(f"Variant 1 found: {count1}")

if count1 > 0:
    content = content.replace(old_text_1, correct_text)
    print("Replaced variant 1")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done!")
