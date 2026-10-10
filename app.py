from datetime import datetime, time, timedelta
import logging
import os
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

TOKEN = os.environ.get('TOKEN')
PORT = int(os.environ.get('PORT', '10000'))
WEBHOOK_URL = os.environ.get('RENDER_EXTERNAL_HOSTNAME')

print(f'DEBUG: TOKEN present = {bool(TOKEN)}')
print(f'DEBUG: PORT = {PORT}')
print(f'DEBUG: RENDER_EXTERNAL_HOSTNAME = {WEBHOOK_URL}')


def init_db():
  conn = sqlite3.connect('birthdays.db')
  cursor = conn.cursor()
  cursor.execute('''
        CREATE TABLE IF NOT EXISTS birthdays (
            chat_id INTEGER,
            user_id INTEGER,
            name TEXT,
            day INTEGER,
            month INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
  conn.commit()
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
        'Вкажіть дату у форматі ДД.ММ (наприклад, /set_bd 24.08)'
    )
    return

  date_str = context.args[0]
  try:
    day, month = map(int, date_str.split('.'))
    if not (1 <= day <= 31 and 1 <= month <= 12):
      raise ValueError()
  except ValueError:
    await update.message.reply_text(
        'Неправильний формат! Використовуйте ДД.ММ (наприклад, /set_bd 24.08)'
    )
    return

  user = update.effective_user
  name = user.first_name
  chat_id = update.effective_chat.id
  user_id = user.id

  conn = sqlite3.connect('birthdays.db')
  cursor = conn.cursor()
  cursor.execute(
      '''
        INSERT OR REPLACE INTO birthdays (chat_id, user_id, name, day, month)
        VALUES (?, ?, ?, ?, ?)
    ''',
      (chat_id, user_id, name, day, month),
  )
  conn.commit()
  conn.close()

  await update.message.reply_text(
      f'✅ День народження для {name} ({day:02d}.{month:02d}) збережено!'
  )


async def list_birthdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if update.effective_chat.type not in ['group', 'supergroup']:
    await update.message.reply_text(
        'Цю команду можна використовувати лише в груповому чаті!'
    )
    return

  chat_id = update.effective_chat.id
  conn = sqlite3.connect('birthdays.db')
  cursor = conn.cursor()
  cursor.execute(
      'SELECT name, day, month FROM birthdays WHERE chat_id = ? ORDER BY month,'
      ' day',
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
    name, day, month = row
    text += f'• {name} — {day:02d}.{month:02d}\n'

  await update.message.reply_text(text)


# Функція, яка щодня перевіряє дні народження
async def check_birthdays(context: ContextTypes.DEFAULT_TYPE):
  now = datetime.now()
  today_day = now.day
  today_month = now.month

  # Дата через 2 дні
  future = now + timedelta(days=2)
  future_day = future.day
  future_month = future.month

  conn = sqlite3.connect('birthdays.db')
  cursor = conn.cursor()

  # Шукаємо тих, у кого день народження СЬОГОДНІ
  cursor.execute(
      'SELECT chat_id, name FROM birthdays WHERE day = ? AND month = ?',
      (today_day, today_month),
  )
  today_bds = cursor.fetchall()

  # Шукаємо тих, у кого день народження ЧЕРЕЗ 2 ДНІ
  cursor.execute(
      'SELECT chat_id, name FROM birthdays WHERE day = ? AND month = ?',
      (future_day, future_month),
  )
  future_bds = cursor.fetchall()
  conn.close()

  # Надсилаємо сповіщення на день народження
  for chat_id, name in today_bds:
    try:
      await context.bot.send_message(
          chat_id=chat_id,
          text=f'🎉 Спеціальне нагадування: Сьогодні день народження у {name}! Вітаємо! 🥳',
      )
    except Exception as e:
      logging.error(f'Failed to send today notification to {chat_id}: {e}')

  # Надсилаємо сповіщення за 2 дні
  for chat_id, name in future_bds:
    try:
      await context.bot.send_message(
          chat_id=chat_id,
          text=f'⏳ Нагадування: через 2 дні ({future_day:02d}.{future_month:02d}) день народження у {name}! Готуйте подарунки! 🎁',
      )
    except Exception as e:
      logging.error(f'Failed to send future notification to {chat_id}: {e}')


def main():
  app = Application.builder().token(TOKEN).build()

  app.add_handler(CommandHandler('set_bd', set_birthday))
  app.add_handler(CommandHandler('list_bd', list_birthdays))

  # Додаємо автоматичну задачу на виконання щодня о 00:01
  job_queue = app.job_queue
  job_queue.run_daily(check_birthdays, time=time(hour=0, minute=1, second=0))

  if WEBHOOK_URL:
    webhook_uri = f'https://{WEBHOOK_URL}/webhook'
    print(f'DEBUG: Setting webhook to {webhook_uri}')

    app.run_webhook(
        listen='0.0.0.0',
        port=PORT,
        webhook_url=webhook_uri,
        url_path='webhook',
        drop_pending_updates=True,
    )
  else:
    print('DEBUG: WEBHOOK_URL is missing, running polling!')
    app.run_polling()


if __name__ == '__main__':
  main()
