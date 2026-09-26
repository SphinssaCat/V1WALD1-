echo "Проверяю DEEPSEEK_API_KEY..."

if [ -z "\$DEEPSEEK_API_KEY" ]; then
  echo "❌ ОШИБКА: Переменная DEEPSEEK_API_KEY пуста!"
  exit 1
else
  echo "✅ Ключ найден (первые 10 символов): \${DEEPSEEK_API_KEY:0:10}..."
fi

echo "Теперь пробуем запрос к DeepSeek..."
curl -s -H "Authorization: Bearer \$DEEPSEEK_API_KEY" \
     https://api.deepseek.com/v1/models | head -n 5
