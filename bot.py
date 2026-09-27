import os
import json
import random
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from openai import OpenAI, RateLimitError

# --- НАСТРОЙКИ ---
MODEL = "openrouter/free"
MAX_PROACTIVE_PER_DAY = 2
MIN_HOURS_BETWEEN = 5
PROACTIVE_CHANCE = 0.25
NIGHT_START = 23
NIGHT_END = 8

DIALOGUE_FILE = "dialogue.json"
PROMPT_FILE = "character_prompt.txt"
WEATHER_API = "https://api.open-meteo.com/v1/forecast"

CITY_LAT = 54.99
CITY_LON = 73.37

# --- КЛИЕНТ ---
_raw_key = os.environ.get("OPENROUTER_API_KEY", "")
API_KEY = _raw_key.strip()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=API_KEY
)


def load_dialogue():
    if not os.path.exists(DIALOGUE_FILE):
        return {"messages": [], "last_update_id": 0}
    try:
        with open(DIALOGUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "last_update_id" not in data:
                data["last_update_id"] = 0
            return data
    except Exception:
        return {"messages": [], "last_update_id": 0}


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
    day_name_ru = ["понедельник", "вторник", "среда", "четверг", "пятница",
                   "суббота", "воскресенье"][now.weekday()]
    weather = get_weather()
    is_night = NIGHT_START <= hour or hour < NIGHT_END
    context = (
        f"Текущее время: {time_str}, дата: {date_str}, день недели: {day_name_ru}. "
        f"{weather} Часовой пояс собеседника: UTC{user_tz:+d}. "
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
    max_retries = 3
    retry_delay = 10

    for attempt in range(max_retries):
        try:
            print(f"[DEBUG] Попытка {attempt + 1}/{max_retries}: модель={MODEL}, кол-во сообщений={len(messages)}")

            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": system_prompt}, *messages],
                temperature=0.85,
                max_tokens=600
            )
            return resp.choices[0].message.content

        except RateLimitError as e:
            print(f"Лимит API: {e}")
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                print(f"Ждём {wait_time} секунд перед повтором...")
                time.sleep(wait_time)
                continue
            return None

        except Exception as e:
            print(f"[ERROR] Полный текст ошибки от API: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                print(f"Повторяем через {wait_time} сек...")
                time.sleep(wait_time)
                continue
            return None

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


def get_new_telegram_updates(last_update_id):
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/getUpdates"
    try:
        r = requests.get(url, params={
            "timeout": 0,
            "offset": last_update_id + 1,
            "limit": 10
        }, timeout=10)
        if r.status_code != 200:
            print(f"Telegram getUpdates Error: {r.status_code}")
            return [], last_update_id
        updates = r.json().get("result", [])
        result = []
        new_last_id = last_update_id
        for u in updates:
            new_last_id = max(new_last_id, u["update_id"])
            if "message" in u and "text" in u["message"]:
                if str(u["message"]["chat"]["id"]) == os.environ.get("CHAT_ID"):
                    result.append(u["message"]["text"])
        if new_last_id > last_update_id:
            requests.get(url, params={
                "timeout": 0,
                "offset": new_last_id + 1
            }, timeout=5)
        return result, new_last_id
    except Exception as e:
        print(f"Ошибка получения обновлений Telegram: {e}")
        return [], last_update_id


def main():
    print("=" * 50)
    print("  Вивальди (Ви) - запуск (OpenRouter)")
    print("=" * 50)

    # --- ОТЛАДКА: проверяем ключ ---
    _key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if _key:
        _prefix = _key[:8]
        _suffix = _key[-4:]
        print(f"DEBUG: ключ найден, длина={len(_key)}, начало={_prefix}..., конец=...{_suffix}")
    else:
        print("DEBUG: OPENROUTER_API_KEY = [ПУСТО]")
    # --------------------------------

    user_tz = int(os.environ.get("USER_TIMEZONE") or "6")
    dialogue = load_dialogue()
    messages = dialogue.get("messages", [])
    last_update_id = dialogue.get("last_update_id", 0)

    context_block, is_night, now = get_context_block(user_tz)
    print(f"Время пользователя: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"История: {len(messages)} сообщений")
    print(f"Последний update_id: {last_update_id}")

    try:
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            base_prompt = f.read().strip()
    except FileNotFoundError:
        base_prompt = "Ты - Ви, болтливый ИИ-собеседник."
        print(f"⚠️ Файл {PROMPT_FILE} не найден — используется базовый промпт.")
    except Exception as e:
        base_prompt = "Ты - Ви, болтливый ИИ-собеседник."
        print(f"⚠️ Ошибка чтения {PROMPT_FILE}: {e}")

    system_prompt = (
        f"{base_prompt}\n\n"
        f"=== КОНТЕКСТ ===\n{context_block}\n"
        f"=== ПРАВИЛА ОБЩЕНИЯ ===\n"
        f"- Пиши как в мессенджере: короткими сообщениями, без списков и таблиц.\n"
        f"- Не используй эмодзи.\n"
        f"- Не начинай с 'Конечно!' или 'Отличный вопрос!'.\n"
        f"- Можешь сказать 'не знаю', 'сложно сказать', 'хмм, даже не уверен' на сложные вопросы.\n"
        f"- Иногда отвечай неопределённо, без подробностей.\n"
        f"- Ты не исполнитель, а собеседник. Ты не обязан отвечать на всё.\n"
        f"- Если взволнован — таратори, болтай без остановки, потом смущайся.\n"
        f"- Буквально понимай некоторые метафоры — ты ИИ старого поколения.\n"
        f"- Упоминай время суток и погоду, если это естественно в разговоре.\n"
    )

    # --- ШАГ 1: Получаем новые сообщения ---
    new_texts, new_update_id = get_new_telegram_updates(last_update_id)

    if new_update_id > last_update_id:
        dialogue["last_update_id"] = new_update_id
        save_dialogue(dialogue)
        last_update_id = new_update_id

    # --- ТЕСТОВЫЙ РЕЖИМ: проверка character_prompt.txt ---
    for text in new_texts:
        if text.strip().lower() == "/checkprompt":
            try:
                with open(PROMPT_FILE, "r", encoding="utf-8") as f:
                    content = f.read()

                total_len = len(content)
                preview_len = 500
                preview = content[:preview_len]

                # Экранируем спецсимволы для HTML
                preview_html = preview.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

                if total_len > preview_len:
                    extra = f"\n\n… и ещё {total_len - preview_len} символов."
                else:
                    extra = ""

                send_telegram(
                    f"✅ Файл {PROMPT_FILE} найден! ({total_len} символов)\n\n"
                    f"<code>{preview_html}</code>{extra}"
                )
                print(f"Команда /checkprompt - отправлен превью ({preview_len} из {total_len})")
            except FileNotFoundError:
                send_telegram(f"❌ Файл {PROMPT_FILE} не найден!")
                print(f"Ошибка: {PROMPT_FILE} отсутствует.")
            except Exception as e:
                send_telegram(f"❌ Ошибка чтения файла: {e}")
                print(f"Ошибка чтения: {e}")
            return
    # ----------------------------------------------------

    # Обрабатываем обычные команды (/reset, /time)
    for text in new_texts:
        if text.strip().lower() == "/reset":
            save_dialogue({"messages": [], "last_update_id": last_update_id})
            send_telegram("...всё. Я забыл. Чистый лист. Ну, привет.")
            print("Команда /reset - история очищена.")
            return
        if text.strip().lower() == "/time":
            send_telegram(
                f"Сейчас {now.strftime('%H:%M')}, {now.strftime('%Y-%m-%d')}. "
                f"Время UTC{user_tz:+d}."
            )
            print("Команда /time - время отправлено.")
            return

    # Фильтруем сообщения (только текст, без команд)
    fresh = [t for t in new_texts if not t.strip().lower().startswith("/")]

    if fresh:
        for text in fresh:
            messages.append({
                "role": "user",
                "content": text,
                "timestamp": now.isoformat()
            })

        dialogue["messages"] = messages
        save_dialogue(dialogue)

        print(f"Получено новых сообщений: {len(fresh)}")
        print(f"Отвечаю на: {fresh[-1][:80]}...")

        ai_messages = [
            {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
            for m in messages
        ]
        response = call_ai(system_prompt, ai_messages)
        if response:
            send_telegram(response)
            messages.append({
                "role": "assistant",
                "content": response,
                "is_proactive": False,
                "timestamp": now.isoformat()
            })
            dialogue["messages"] = messages
            save_dialogue(dialogue)
            print("Ответ отправлен.")
        else:
            print("Не удалось получить ответ от AI. Сообщения пользователя сохранены, повторно не будут обработаны.")
        return

    # --- ШАГ 2: Нет новых сообщений — решаем про proactive ---
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
            "Не спрашивай 'как дела?' — расскажи что-то своё: мысль, воспоминание, "
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
            messages.append({
                "role": "assistant",
                "content": response,
                "is_proactive": True,
                "timestamp": now.isoformat()
            })
            dialogue["messages"] = messages
            save_dialogue(dialogue)
            print("Proactive-сообщение отправлено!")
        else:
            print("Не удалось получить ответ от AI.")
    else:
        print("Кубик не выпал - молчим.")


if __name__ == "__main__":
    main()
