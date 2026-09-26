#!/usr/bin/env bash

echo "Проверяю DEEPSEEK_API_KEY..."

# Проверяем, не пустая ли переменная
if [ -z "$DEEPSEEK_API_KEY" ]; then
  echo "❌ ОШИБКА: Переменная DEEPSEEK_API_KEY пуста!"
  exit 1
else
  # Выводим первые 10 символов ключа БЕЗ экранирования
  echo "✅ Ключ найден (первые 10 символов): ${DEEPSEEK_API_KEY:0:10}..."
fi

echo "Теперь пробуем запрос к DeepSeek..."

# Важно: двойные кавычки и никаких слэшей перед $
curl -s -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
     https://api.deepseek.com/v1/models | head -n 5
