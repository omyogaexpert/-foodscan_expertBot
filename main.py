import telebot
from telebot import types
from google import genai
from PIL import Image
import io
import re
import sqlite3
import matplotlib.pyplot as plt

TELEGRAM_TOKEN = "8917309818:AAEE44LU3q9rFlagEpXBJpSbqqb13iPYbmk"
GEMINI_API_KEY = "AQ.Ab8RN6L4puZBGvwpPKquAlFTjJj0CkyDEAF_JeFWNa4q-WFt0A"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

try:
    bot.remove_webhook()
except Exception:
    pass

# База данных
conn = sqlite3.connect('nutrition_full.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    weight REAL, height REAL, age INTEGER, goal TEXT, calorie_limit INTEGER DEFAULT 2000
)''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS food_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, cal INTEGER, p INTEGER, f INTEGER, c INTEGER, date DATE DEFAULT CURRENT_DATE
)''')
conn.commit()

user_states = {}

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📊 Мой дневник"), types.KeyboardButton("📈 График за неделю"))
    markup.add(types.KeyboardButton("⚙️ Расчет нормы и цели"), types.KeyboardButton("📸 Как пользоваться"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "👋 **Привет! Я твой персональный AI-нутрициолог.**\n\n"
        "📸 Отправляй **фото еды**\n"
        "✍️ Или пиши **текстом** (например: «съел 2 яйца и яблоко»)\n\n"
        "Воспользуйся кнопками меню ниже!",
        reply_markup=get_main_keyboard(), parse_mode="Markdown"
    )

# --- РАСЧЕТ НОРМЫ ---
@bot.message_handler(func=lambda msg: msg.text == "⚙️ Расчет нормы и цели")
def start_calc(message):
    user_states[message.from_user.id] = {'step': 'weight'}
    bot.reply_to(message, "Введите ваш вес в кг (например: 65):", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda msg: msg.from_user.id in user_states)
def process_calc(message):
    user_id = message.from_user.id
    state = user_states[user_id]['step']
    try:
        if state == 'weight':
            user_states[user_id]['weight'] = float(message.text.replace(',', '.'))
            user_states[user_id]['step'] = 'height'
            bot.reply_to(message, "Введите ваш рост в см (например: 170):")
        elif state == 'height':
            user_states[user_id]['height'] = float(message.text.replace(',', '.'))
            user_states[user_id]['step'] = 'age'
            bot.reply_to(message, "Введите ваш возраст (например: 25):")
        elif state == 'age':
            user_states[user_id]['age'] = int(message.text)
            user_states[user_id]['step'] = 'goal'
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add("📉 Похудение", "⚖️ Поддержание", "📈 Набор массы")
            bot.reply_to(message, "Выберите вашу цель:", reply_markup=markup)
        elif state == 'goal':
            goal = message.text
            weight, height, age = user_states[user_id]['weight'], user_states[user_id]['height'], user_states[user_id]['age']
            bmr = (10 * weight + 6.25 * height - 5 * age + 5) * 1.2
            norm = int(bmr * 0.85) if "Похудение" in goal else (int(bmr * 1.15) if "Набор" in goal else int(bmr))
            
            cursor.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?, ?)", (user_id, weight, height, age, goal, norm))
            conn.commit()
            del user_states[user_id]
            
            bot.reply_to(message, f"✅ Данные сохранены!\n🎯 Цель: {goal}\n🔥 Ваша суточная норма: **{norm} ккал**", reply_markup=get_main_keyboard(), parse_mode="Markdown")
    except ValueError:
        bot.reply_to(message, "Пожалуйста, введите корректное число.")

# --- ДНЕВНИК И ГРАФИК ---
@bot.message_handler(func=lambda msg: msg.text in ["📊 Мой дневник", "/stats"])
def show_stats(message):
    user_id = message.from_user.id
    cursor.execute("SELECT calorie_limit, goal FROM users WHERE user_id = ?", (user_id,))
    row_user = cursor.fetchone()
    limit = row_user[0] if row_user else 2000
    goal = row_user[1] if row_user else "Не указана"
    
    cursor.execute("SELECT SUM(cal), SUM(p), SUM(f), SUM(c), COUNT(*) FROM food_logs WHERE user_id = ? AND date = CURRENT_DATE", (user_id,))
    row = cursor.fetchone()
    
    if not row or not row[0]:
        bot.reply_to(message, f"📊 **ДНЕВНИК ЗА СЕГОДНЯ:**\n\nЗаписей пока нет.\n🎯 Цель: {goal}\n🔥 Норма: **{limit} ккал**", reply_markup=get_main_keyboard(), parse_mode="Markdown")
        return
        
    bot.reply_to(
        message, 
        f"📊 **ДНЕВНИК ЗА СЕГОДНЯ:**\n\n"
        f"🔥 **Калории:** {row[0]} / {limit} ккал\n"
        f"🥩 **Белки:** {row[1]} г\n"
        f"🥑 **Жиры:** {row[2]} г\n"
        f"🌾 **Углеводы:** {row[3]} г\n\n"
        f"Зафиксировано приемов пищи: {row[4]}", 
        parse_mode="Markdown", 
        reply_markup=get_main_keyboard()
    )

@bot.message_handler(func=lambda msg: msg.text == "📈 График за неделю")
def send_chart(message):
    cursor.execute("SELECT date, SUM(cal) FROM food_logs WHERE user_id = ? GROUP BY date ORDER BY date DESC LIMIT 7", (message.from_user.id,))
    data = cursor.fetchall()
    if not data:
        bot.reply_to(message, "Недостаточно данных для графика. Добавьте записи еды!")
        return
    dates, cals = [r[0] for r in reversed(data)], [r[1] for r in reversed(data)]
    plt.figure(figsize=(8, 4))
    plt.bar(dates, cals, color='#4CAF50')
    plt.title('Калории за неделю')
    plt.xticks(rotation=45)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    bot.send_photo(message.chat.id, photo=buf, caption="📈 Твой прогресс!", reply_markup=get_main_keyboard())

# --- ТЕКСТ И ФОТО ---
def send_analysis(message, response_text):
    cal = re.search(r'Калории:\*\* (\d+)', response_text)
    p = re.search(r'Белки:\*\* (\d+)', response_text)
    f = re.search(r'Жиры:\*\* (\d+)', response_text)
    c = re.search(r'Углеводы:\*\* (\d+)', response_text)
    
    cal_v = int(cal.group(1)) if cal else 0
    p_v = int(p.group(1)) if p else 0
    f_v = int(f.group(1)) if f else 0
    c_v = int(c.group(1)) if c else 0

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Записать в дневник", callback_data=f"add_{cal_v}_{p_v}_{f_v}_{c_v}"))
    bot.reply_to(message, response_text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text not in ["📊 Мой дневник", "📈 График за неделю", "⚙️ Расчет нормы и цели", "📸 Как пользоваться"] and not msg.text.startswith('/'))
def handle_text(message):
    bot.reply_to(message, "⏳ Считаю калории...")
    prompt = f"Еда: '{message.text}'. Оцени состав и ответь строго по шаблону:\n🍽 **Название:** <название>\n🔥 **Калории:** <число> ккал\n🥩 **Белки:** <число> г\n🥑 **Жиры:** <число> г\n🌾 **Углеводы:** <число> г\n💡 **Совет нутрициолога:** <короткая рекомендация>"
    response = client.models.generate_content(model='gemini-3.6-flash', contents=prompt)
    send_analysis(message, response.text)

@bot.message_handler(content_types=['photo', 'document'])
def handle_photo(message):
    bot.reply_to(message, "⏳ Анализирую фото...")
    try:
        file_id = message.photo[-1].file_id if message.content_type == 'photo' else message.document.file_id
        downloaded_file = bot.download_file(bot.get_file(file_id).file_path)
        img = Image.open(io.BytesIO(downloaded_file))
        prompt = "Проанализируй фото еды и ответь по шаблону:\n🍽 **Название:** <название>\n🔥 **Калории:** <число> ккал\n🥩 **Белки:** <число> г\n🥑 **Жиры:** <число> г\n🌾 **Углеводы:** <число> г\n💡 **Совет нутрициолога:** <короткая рекомендация>"
        response = client.models.generate_content(model='gemini-3.6-flash', contents=[img, prompt])
        send_analysis(message, response.text)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_'))
def callback_add(call):
    _, cal, p, f, c = call.data.split('_')
    cursor.execute("INSERT INTO food_logs (user_id, cal, p, f, c) VALUES (?, ?, ?, ?, ?)", (call.from_user.id, int(cal), int(p), int(f), int(c)))
    conn.commit()
    bot.answer_callback_query(call.id, "✅ Записано в дневник!")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

@bot.message_handler(func=lambda msg: msg.text == "📸 Как пользоваться")
def show_help(message):
    bot.reply_to(message, "1. Отправь **фото еды** или **напиши текстом** (например: «съела салат и суп»).\n2. Нажми **«➕ Записать в дневник»** под ответом.\n3. Проверяй прогресс по кнопке **«📊 Мой дневник»**.", reply_markup=get_main_keyboard())

print("🚀 Стабильный бот запущен!")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
