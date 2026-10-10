import asyncio
from datetime import datetime, time, timedelta
import logging
import os
from flask import Flask, request
import psycopg2
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

TOKEN = os.environ.get('TOKEN')
PORT = int(os.environ.get('PORT', '10000'))
WEBHOOK_URL = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
DATABASE_URL = os.environ.get('DATABASE_URL')

print(f'DEBUG: TOKEN present = {bool(TOKEN)}')
print(f'DEBUG: PORT = {PORT}')
print(f'DEBUG: RENDER_EXTERNAL_HOSTNAME = {WEBHOOK_URL}')
print(f'DEBUG: DATABASE_URL present = {bool(DATABASE_URL)}')

flask_app = Flask(__name__)


@flask_app.route('/')
def index():
  return 'Bot is alive!', 200


application = Application.builder().token(TOKEN).build()


def get_db_connection():
  return psycopg2.connect(DATABASE_URL, sslmode='require')


def init_db():
  conn = get_db_connection()
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS birthdays (
            chat_id BIGINT,
            user_id BIGINT,
            name TEXT,
            day INTEGER,
            month INTEGER,
            year INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
  conn.commit()
  cursor.close()
  conn.close()


init_db()


async def set_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if update.effective_chat.type not in ['group', 'supergroup']:
    await update.message.reply_text(
        'Цю команду можна використовувати лише в груповому чаті!'
    )
    return

  if not context.args:
    await update.message.reply_text(
        'Вкажіть дату у форматі ДД.ММ.РРРР (наприклад, /set 24.08.2000)'
    )
    return

  date_str = context.args[0]
  try:
    day, month, year = map(int, date_str.split('.'))
    if not (
        1 <= day <= 31
        and 1 <= month <= 12
        and 1900 <= year <= datetime.now().year
    ):
      raise ValueError()
  except ValueError:
    await update.message.reply_text(
        'Неправильний формат! Використовуйте ДД.ММ.РРРР (наприклад, /set'
        ' 24.08.2000)'
    )
    return

  user = update.effective_user
  name = user.first_name
  chat_id = update.effective_chat.id
  user_id = user.id

  conn = get_db_connection()
  cursor = conn.cursor()
  cursor.execute(
      """
        INSERT INTO birthdays (chat_id, user_id, name, day, month, year)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (chat_id, user_id) 
        DO UPDATE SET name = EXCLUDED.name, day = EXCLUDED.day, month = EXCLUDED.month, year = EXCLUDED.year
    """,
      (chat_id, user_id, name, day, month, year),
  )
  conn.commit()
  cursor.close()
  conn.close()

  await update.message.reply_text(
      f'✅ День народження для {name} ({day:02d}.{month:02d}.{year}) збережено!'
  )


async def list_birthdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if update.effective_chat.type not in ['group', 'supergroup']:
    await update.message.reply_text(
        'Цю команду можна використовувати лише в груповому чаті!'
    )
    return

  chat_id = update.effective_chat.id
  conn = get_db_connection()
  cursor = conn.cursor()
  cursor.execute(
      'SELECT name, day, month, year FROM birthdays WHERE chat_id = %s ORDER BY'
      ' month, day',
      (chat_id,),
  )
  rows = cursor.fetchall()
  conn.close()

  if not rows:
    await update.message.reply_text(
        'У цьому чаті поки немає збережених днів народжень.'
    )
    return

  text = '📅 Дні народження учасників цього чату:\n\n'
  for row in rows:
    name, day, month, year = row
    text += f'• {name} — {day:02d}.{month:02d}.{year}\n'

  await update.message.reply_text(text)


async def check_birthdays(context: ContextTypes.DEFAULT_TYPE):
  now = datetime.now()
  today_day = now.day
  today_month = now.month

  future = now + timedelta(days=2)
  future_day = future.day
  future_month = future.month

  conn = get_db_connection()
  cursor = conn.cursor()

  cursor.execute(
      'SELECT chat_id, name FROM birthdays WHERE day = %s AND month = %s',
      (today_day, today_month),
  )
  today_bds = cursor.fetchall()

  cursor.execute(
      'SELECT chat_id, name FROM birthdays WHERE day = %s AND month = %s',
      (future_day, future_month),
  )
  future_bds = cursor.fetchall()
  conn.close()

  for chat_id, name in today_bds:
    try:
      await context.bot.send_message(
          chat_id=chat_id,
          text=f'🎉 Спеціальне нагадування: Сьогодні день народження у {name}! Вітаємо! 🥳',
      )
    except Exception as e:
      logging.error(f'Failed to send today notification to {chat_id}: {e}')

  for chat_id, name in future_bds:
    try:
      await context.bot.send_message(
          chat_id=chat_id,
          text=f'⏳ Нагадування: через 2 дні ({future_day:02d}.{future_month:02d}) день народження у {name}! Готуйте подарунки! 🎁',
      )
    except Exception as e:
      logging.error(f'Failed to send future notification to {chat_id}: {e}')


application.add_handler(CommandHandler('set', set_birthday))
application.add_handler(CommandHandler('list', list_birthdays))

job_queue = application.job_queue
job_queue.run_daily(check_birthdays, time=time(hour=0, minute=1, second=0))


@flask_app.route('/webhook', methods=['POST', 'GET'])
def webhook():
  if request.method == 'GET':
    return 'Bot is running', 200

  if request.headers.get('content-type') == 'application/json':
    json_string = request.get_data().decode('utf-8')
    update = Update.de_json(json_string, application.bot)

    async def process():
      await application.initialize()
      await application.process_update(update)

    asyncio.run(process())
    return 'OK', 200
  return 'Forbidden', 403


if __name__ == '__main__':
  if WEBHOOK_URL:
    webhook_uri = f'https://{WEBHOOK_URL}/webhook'
    response = requests.get(
        f'https://api.telegram.org/bot{TOKEN}/setWebhook?url={webhook_uri}'
    )
    print(f'DEBUG: Set webhook response -> {response.text}')

  flask_app.run(host='0.0.0.0', port=PORT)
