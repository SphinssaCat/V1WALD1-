#!/usr/bin/env python3
"""
Вивальди (Ви) — бот-собеседник на базе DeepSeek.
GitHub Actions + Telegram + DeepSeek API.
"""

import os
import json
import time
import random
import requests
from datetime import datetime, timezone, timedelta

# ──────────────────────────────────────────────
# КОНФИГУРАЦИЯ
# ──────────────────────────────────────────────

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
# По умолчанию ставим 6 (Омск), если переменная не задана
USER_TZ_OFFSET = int(os.environ.get("USER_TIMEZONE", "6"))

MODEL = "deepseek-chat"
API_URL = "https://api.deepseek.com/v1/chat/completions"
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

PROMPT_FILE = "character_prompt.txt"
HISTORY_FILE = "dialogue_history.json"
OFFSET_FILE = "tg_offset.json"
PROACTIVE_FILE = "last_proactive.json"
MAX_HISTORY = 40

# Проактивные сообщения
MIN_HOURS = 2
MAX_HOURS = 8
PROACTIVE_CHANCE = 0.20
NIGHT_START = 23
NIGHT_END = 8

# Веб-поиск
WEB_SEARCH_ENABLED = True


# ──────────────────────────────────────────────
# ВРЕМЯ И ПОГОДА
# ──────────────────────────────────────────────

def get_user_time():
    """Текущее время в часовом поясе пользователя."""
    tz = timezone(timedelta(hours=USER_TZ_OFFSET))
    return datetime.now(tz)

def time_of_day_str(dt):
    """Возвращает описание времени суток."""
    h = dt.hour
    if 5 <= h < 8:
        return "раннее утро, солнце только встаёт"
    elif 8 <= h < 12:
        return "утро"
    elif 12 <= h < 17:
        return "день"
    elif 17 <= h < 20:
        return "вечер, солнце садится"
    elif 20 <= h < 23:
        return "поздний вечер"
    else:
        return "ночь"

def is_night(dt):
    """Проверяет, сейчас ли 'ночь' для проактивных сообщений."""
    return dt.hour >= NIGHT_START or dt.hour < NIGHT_END

def get_weather():
    """Получает текущую погоду через Open-Meteo."""
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": 54.99,
            "longitude": 73.37,
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "timezone": "Asia/Omsk"
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        temp = data["current"]["temperature_2m"]
        code = data["current"]["weather_code"]
        wind = data["current"]["wind_speed_10m"]

        weather_map = {
            0: "ясно", 1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно",
            45: "туман", 48: "изморозь", 51: "слабая морось", 53: "морось", 55: "сильная морось",
            61: "небольшой дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь", 67: "сильный ледяной дождь",
            71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа",
            80: "ливень", 81: "сильный ливень", 82: "очень сильный ливень",
            85: "снежные заряды", 86: "сильные снежные заряды",
            95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
        }

        desc = weather_map.get(code, "неизвестная погода")
        return f"Погода в Омске: {desc}, температура {int(temp)}°C, ветер {int(wind)} м/с"
    except Exception as e:
        return f"Погода: не удалось получить ({e})"

def build_context_block():
    """Собирает блок контекста: время, погода, дата."""
    now = get_user_time()
    tod = time_of_day_str(now)
    weather = get_weather()

    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    months = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]

    date_str = f"{now.day} {months[now.month - 1]}, {weekdays[now.weekday()]}"

    holidays = {
        (1, 1): "Новый год", (1, 7): "Рождество", (2, 23): "День защитника Отечества",
        (3, 8): "Международный женский день", (5, 1): "Праздник Весны и Труда",
        (5, 9): "День Победы", (6, 12): "День России", (11, 4): "День народного единства",
        (12, 31): "Канун Нового года",
    }
    holiday = holidays.get((now.month, now.day), None)

    block = f"""## Текущий контекст
Сейчас: {tod}.
Дата: {date_str}.
Время: {now.strftime('%H:%M')}.
{weather}"""
    if holiday:
        block += f"\nСегодня праздник: {holiday}. Можешь поздравить, если уместно."

    return block


# ──────────────────────────────────────────────
# ВЕБ-ПОИСК
# ──────────────────────────────────────────────

def web_search(query):
    """Поиск через DuckDuckGo Instant Answer API."""
    if not WEB_SEARCH_ENABLED:
        return ""
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        results = []
        if data.get("AbstractText"):
            results.append(data["AbstractText"])
        if data.get("Answer"):
            results.append(data["Answer"])
        for topic in data.get("RelatedTopics", [])[:3]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(topic["Text"][:200])

        if results:
            return "Найдено в интернете:\n" + "\n".join(results[:3])
        return ""
    except Exception:
        return ""


# ──────────────────────────────────────────────
# DEEPSEEK API
# ──────────────────────────────────────────────

def call_deepseek(messages, temperature=0.8):
    """Вызывает DeepSeek API и возвращает ответ."""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 500,
    }

    resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)

    if resp.status_code == 429:
        print("⚠️ Лимит запросов DeepSeek исчерпан")
        return None
    if resp.status_code != 200:
        print(f"❌ ОШИБКА API: {resp.status_code} {resp.text[:300]}")
        return None

    data = resp.json()
    
    # ИСПРАВЛЕНИЕ: правильный доступ к списку choices
    if "choices" in data and len(data["choices"]) > 0:
        return data["choices"][0]["message"]["content"]
    
    print("❌ Не удалось извлечь ответ из API")
    return None


# ──────────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────────

def tg_send(text):
    """Отправляет сообщение в Telegram."""
    url = f"{TELEGRAM_URL}/sendMessage"
    if len(text) > 4096:
        text = text[:4090] + "…"
    resp = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
    }, timeout=30)
    if resp.status_code != 200:
        print(f"❌ ОШИБКА Telegram: {resp.status_code} {resp.text[:200]}")
    else:
        print("✅ Сообщение отправлено в Telegram")

def tg_get_updates(offset=None):
    """Получает новые сообщения из Telegram."""
    url = f"{TELEGRAM_URL}/getUpdates"
    params = {"timeout": 0}
    if offset:
        params["offset"] = offset
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        print(f"❌ ОШИБКА Telegram getUpdates: {resp.status_code}")
        return []
    return resp.json().get("result", [])


# ──────────────────────────────────────────────
# ФАЙЛОВАЯ СИСТЕМА (ИСТОРИЯ И СОСТОЯНИЯ)
# ──────────────────────────────────────────────

def load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_history(history):
    if len(history) > MAX_HISTORY * 2:
        history = history[-(MAX_HISTORY * 2):]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def load_prompt():
    try:
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        print("❌ Файл character_prompt.txt не найден!")
        return "Ты — дружелюбный собеседник."

def load_offset():
    try:
        with open(OFFSET_FILE, "r") as f:
            return json.load(f).get("offset", None)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        json.dump({"offset": offset}, f)

def load_last_proactive():
    try:
        with open(PROACTIVE_FILE, "r") as f:
            data = json.load(f)
            return datetime.fromisoformat(data["time"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        return None

def save_last_proactive(dt):
    with open(PROACTIVE_FILE, "w") as f:
        json.dump({"time": dt.isoformat()}, f)


# ──────────────────────────────────────────────
# ОСНОВНАЯ ЛОГИКА
# ──────────────────────────────────────────────

def build_messages(history, context_block, extra_context=""):
    prompt = load_prompt()
    system_content = prompt + "\n\n" + context_block
    if extra_context:
        system_content += "\n\n" + extra_context

    messages = [{"role": "system", "content": system_content}]
    messages.extend(history)
    return messages

def process_user_message(text, history):
    print(f"📨 Получено сообщение: {text[:100]}")

    if text.strip().lower() == "/reset":
        save_history([])
        tg_send("История очищена. Начинаем с чистого листа.")
        return []

    if text.strip().lower() == "/time":
        now = get_user_time()
        tg_send(f"Сейчас {now.strftime('%H:%M')}, {time_of_day_str(now)}.")
        return history

    search_keywords = ["новость", "новости", "погода", "сегодня", "что происходит",
                       "актуальн", "последн", "свеж", "кто победил", "результат",
                       "сколько стоит", "курс", "найди", "поищи", "узнай"]
    extra_context = ""
    if any(kw in text.lower() for kw in search_keywords):
        print("🔍 Запущен веб-поиск...")
        search_result = web_search(text)
        if search_result:
            extra_context = search_result
            print(f"   Найдено: {search_result[:100]}")

    context_block = build_context_block()
    history.append({"role": "user", "content": text})

    messages = build_messages(history, context_block, extra_context)
    reply = call_deepseek(messages)

    if reply:
        history.append({"role": "assistant", "content": reply})
        tg_send(reply)
    else:
        tg_send("...что-то я завис. Попробуй ещё раз?")
        history.pop()

    return history

def maybe_proactive(history):
    now = get_user_time()

    if is_night(now):
        print("🌙 Ночное время — пропускаем proactive")
        return

    last_proactive = load_last_proactive()
    hours_passed = None
    if last_proactive:
        hours_passed = (now - last_proactive).total_seconds() / 3600

    if hours_passed is not None and hours_passed < MIN_HOURS:
        print(f"⏱ Прошло {hours_passed:.1f} ч — слишком рано для proactive")
        return

    should_write = False
    if hours_passed is None or hours_passed >= MAX_HOURS:
        should_write = True
    else:
        should_write = random.random() < PROACTIVE_CHANCE

    if not should_write:
        print("🎲 Кубик сказал не писать")
        return

    print("✍️ Пишу proactive-сообщение...")
    context_block = build_context_block()

    prompt_msg = {
        "role": "user",
        "content": "[Система: собеседник пока молчит, но ты можешь написать ему первым. Напиши что-нибудь естественное — может быть, реакцию на время суток, погоду, или просто мысль, которая пришла в голову. Не задавай вопрос ради вопроса. Будь естественным.]"
    }

    temp_history = history + [prompt_msg]
    messages = build_messages(temp_history, context_block)

    reply = call_deepseek(messages, temperature=0.9)

    if reply:
        history.append({"role": "assistant", "content": reply})
        tg_send(reply)
        save_last_proactive(now)

    return history


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    print("═══════════════════════════════════════")
    print("  Вивальди (Ви) — запуск")
    print("═══════════════════════════════════════")
    print(f"Время пользователя: {get_user_time().strftime('%Y-%m-%d %H:%M:%S')}")

    if not DEEPSEEK_API_KEY:
        print("❌ ОШИБКА: DEEPSEEK_API_KEY не задан")
        return
    if not TELEGRAM_TOKEN:
        print("❌ ОШИБКА: TELEGRAM_TOKEN не задан")
        return
    if not CHAT_ID:
        print("❌ ОШИБКА: CHAT_ID не задан")
        return

    history = load_history()
    print(f"📖 История: {len(history)} сообщений")

    offset = load
