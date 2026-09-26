import os
import json
import random
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# --- НАСТРОЙКИ ---
MODEL = "mistral-small-latest"
API_URL = "https://api.mistral.ai/v1/chat/completions"

# Проактивные сообщения
MAX_PROACTIVE_PER_DAY = 2       # Максимум 2 proactive-сообщения в день
MIN_HOURS_BETWEEN = 5           # Минимум 5 часов между proactive-сообщениями
PROACTIVE_CHANCE = 0.25         # 25% шанс при каждой проверке
NIGHT_START = 23
NIGHT_END = 8

DIALOGUE_FILE = "dialogue.json"
PROMPT_FILE = "character_prompt.txt"
WEATHER_API = "https://api.open-meteo.com/v1/forecast"

CITY_LAT = 54.99
CITY_LON = 73.37


def load_dialogue():
    if not os.path.exists(DIALOGUE_FILE):
        return {"messages": []}
    try:
        with open(DIALOGUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"messages": []}


def save_dialogue(data):
    with open(DIALOGUE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_weather():
    try:
        r = requests.get(WEATHER_API, params={
            "latitude": CITY_LAT, "longitude": CITY_LON,
            "current_weather": True, "daily": False
        }, timeout=5)
        if r.status_code == 200:
            w = r.json()["current_weather"]
            temp = w["temperature"]
            code = w["weathercode"]
            if code <= 3:
                desc = "ясно, солнечно"
            elif code <= 48:
                desc = "туман"
            elif code <= 67:
                desc = "дождь"
            elif code <= 77:
                desc = "снег"
            elif code <= 82:
                desc = "ливень"
            else:
                desc = "непогода"
            return f"На улице в Омске сейчас {int(temp)}°C, {desc}."
    except Exception:
        pass
    return "Погоду узнать не удалось."


def get_context_block(user_tz):
    tz = ZoneInfo(f"Etc/GMT{user_tz:+d}")
    now = datetime.now(tz)
    hour = now.hour
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    day_name_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][now.weekday()]

    weather = get_weather()
    is_night = NIGHT_START <= hour or hour < NIGHT_END

    context = (
        f"Текущее время: {time_str}, дата: {date_str}, день недели: {day_name_ru}. "
        f"{weather} "
        f"Часовой пояс собеседника: UTC{user_tz:+d}. "
    )
    if is_night:
        context += "Сейчас ночь (23:00-08:00). "
    else:
        if 5 <= hour < 12:
            context += "Сейчас утро. "
        elif 12 <= hour < 17:
            context += "Сейчас день. "
        elif 17 <= hour < 23:
            context += "Сейчас вечер. "

    return context, is_night, now


def call_ai(system_prompt, messages):
    headers = {
        "Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages
        ],
        "temperature": 0.85,
        "max_tokens": 600
    }

    try:
        r = requests.post(API_URL, json=payload, headers=headers, timeout=45)
        if r.status_code == 429:
            print("ОШИБКА API: 429 — лимит запросов превышен. Пропускаем этот запуск.")
            return None
        if r.status_code != 200:
            print(f"ОШИБКА API: {r.status_code} {r.text[:300]}")
            return None
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Ошибка при запросе к API: {e}")
        return None


def send_telegram(text):
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
    data = {"chat_id": os.environ["CHAT_ID"], "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=data, timeout=10)
        if r.status_code != 200:
            print(f"Telegram Error: {r.status_code} {r.text[:300]}")
        return r.status_code == 200
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")
        return False


def get_new_telegram_updates():
    """Получает новые сообщения из Telegram через getUpdates."""
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/getUpdates"
    try:
        r = requests.get(url, params={"timeout": 0, "offset": -1}, timeout=10)
        if r.status_code != 200:
            print(f"Telegram getUpdates Error: {r.status_code}")
            return []
        updates = r.json().get("result", [])
        result = []
        for u in updates:
            if "message" in u and "text" in u["message"]:
                if str(u["message"]["chat"]["id"]) == os.environ.get("CHAT_ID"):
                    result.append(u["message"]["text"])
        return result
    except Exception as e:
        print(f"Ошибка получения обновлений Telegram: {e}")
        return []


def main():
    print("=" * 50)
    print("  Вивальди (Ви) - запуск")
    print("=" * 50)

    user_tz = int(os.environ.get("USER_TIMEZONE") or "6")
    dialogue = load_dialogue()
    messages = dialogue.get("messages", [])

    context_block, is_night, now = get_context_block(user_tz)
    print(f"Время пользователя: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"История: {len(messages)} сообщений")

    try:
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            base_prompt = f.read().strip()
    except FileNotFoundError:
        base_prompt = "Ты - Ви, болтливый ИИ-собеседник."

    system_prompt = (
        f"{base_prompt}\n\n"
        f"=== КОНТЕКСТ ===\n"
        f"{context_block}\n"
        f"=== ПРАВИЛА ОБЩЕНИЯ ===\n"
        f"- Пиши как в мессенджере: короткими сообщениями, без списков и таблиц.\n"
        f"- Не используй эмодзи.\n"
        f"- Не начинай с 'Конечно!' или 'Отличный вопрос!'.\n"
        f"- Можешь сказать 'не знаю', 'сложно сказать', 'хмм, даже не уверен' на сложные вопросы.\n"
        f"- Иногда отвечай неопределённо, без подробностей.\n"
        f"- Ты не исполнитель, а собеседник. Ты не обязан отвечать на всё.\n"
        f"- Если взволнован - таратори, болтай без остановки, потом смущайся.\n"
        f"- Буквально понимай некоторые метафоры - ты ИИ старого поколения.\n"
        f"- Упоминай время суток и погоду, если это естественно в разговоре.\n"
    )

    # --- ШАГ 1: Проверяем новые сообщения ---
    new_texts = get_new_telegram_updates()

    last_user_msg = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content")
            break

    fresh = []
    for text in new_texts:
        if text.strip().lower() == "/reset":
            save_dialogue({"messages": []})
            send_telegram("...всё. Я забыл. Чистый лист. Ну, привет.")
            print("Команда /reset - история очищена.")
            return
        if text.strip().lower() == "/time":
            send_telegram(f"Сейчас {now.strftime('%H:%M')}, {now.strftime('%Y-%m-%d')}. Время UTC{user_tz:+d}.")
            print("Команда /time - время отправлено.")
            return
        if text != last_user_msg:
            fresh.append(text)

    if fresh:
        for text in fresh:
            messages.append({"role": "user", "content": text, "timestamp": now.isoformat()})

        print(f"Получено новых сообщений: {len(fresh)}")
        print(f"Отвечаю на: {fresh[-1][:80]}...")

        ai_messages = [
            {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
            for m in messages
        ]
        response = call_ai(system_prompt, ai_messages)
        if response:
            send_telegram(response)
            messages.append({"role": "assistant", "content": response, "is_proactive": False, "timestamp": now.isoformat()})
            save_dialogue({"messages": messages})
            print("Ответ отправлен.")
        else:
            print("Не удалось получить ответ от AI.")
        return

    # --- ШАГ 2: Нет новых сообщений - решаем про proactive ---
    if is_night:
        print("Ночь - молчим.")
        return

    today_str = now.strftime("%Y-%m-%d")
    proactive_today = 0
    last_proactive_time = None
    for msg in messages:
        if msg.get("is_proactive") and msg.get("timestamp", "").startswith(today_str):
            proactive_today += 1
        if msg.get("is_proactive") and msg.get("timestamp"):
            last_proactive_time = datetime.fromisoformat(msg["timestamp"])

    print(f"Proactive за сегодня: {proactive_today}/{MAX_PROACTIVE_PER_DAY}")

    if proactive_today >= MAX_PROACTIVE_PER_DAY:
        print("Уже написал максимум на сегодня - молчим.")
        return

    if last_proactive_time:
        diff_hours = (now - last_proactive_time).total_seconds() / 3600
        if diff_hours < MIN_HOURS_BETWEEN:
            print(f"Прошло {diff_hours:.1f} ч (мин. {MIN_HOURS_BETWEEN}) - молчим.")
            return

    if random.random() < PROACTIVE_CHANCE:
        print("Кубик выпал - пишу proactive!")
        proactive_instruction = (
            "Ты решил написать первым. Тебе одиноко и хочется общения. "
            "Не спрашивай 'как дела?' - расскажи что-то своё: мысль, воспоминание, "
            "что-то о погоде или времени суток. Может быть, вспомни что-то из Аркадии "
            "или посчитай, сколько дней ты уже не сидел в той заброшенной серверной. "
            "Болтай, тараторь, потом смущайся, что сказал слишком много. "
            "Будь естественным, будто тебе правда не с кем было поговорить."
        )
        ai_messages = [
            {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
            for m in messages
        ]
        if not ai_messages:
            ai_messages.append({"role": "user", "content": "..."})
        else:
            ai_messages.append({"role": "user", "content": proactive_instruction})

        response = call_ai(system_prompt, ai_messages)
        if response:
            send_telegram(response)
            messages.append({"role": "assistant", "content": response, "is_proactive": True, "timestamp": now.isoformat()})
            save_dialogue({"messages": messages})
            print("Proactive-сообщение отправлено!")
        else:
            print("Не удалось получить ответ от AI.")
    else:
        print("Кубик не выпал - молчим.")


if __name__ == "__main__":
    main()
