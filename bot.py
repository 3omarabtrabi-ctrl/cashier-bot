import sqlite3
import telebot
from telebot import types

TOKEN = '8979814406:AAHsI3k3ZrwGyK9n9LkjRjr-SxNMajTLXMM'

bot = telebot.TeleBot(TOKEN)

# تخزين الجلسات النشطة بعد إدخال كلمة المرور
authenticated_chats = set()


# دالة عامة لإلغاء أي عملية حالية فور كتابة أي أمر يبدأ بـ / (مثل /start)
def check_cancel_command(message):
  if message.text and message.text.startswith('/'):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    if message.text.split()[0] == '/start':
      send_welcome(message)
    return True
  return False


# 1. إعداد قاعدة البيانات الشاملة
def init_db():
  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            balance REAL DEFAULT 0,
            debt REAL DEFAULT 0
        )
    ''')
  cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            cashier_balance REAL DEFAULT 0
        )
    ''')
  cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL,
            reason TEXT,
            date TEXT DEFAULT (datetime('now', 'localtime'))
        )
    ''')
  cursor.execute('''
        CREATE TABLE IF NOT EXISTS profits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL,
            reason TEXT,
            date TEXT DEFAULT (datetime('now', 'localtime'))
        )
    ''')
  cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            fee REAL,
            net_amount REAL,
            date TEXT DEFAULT (datetime('now', 'localtime'))
        )
    ''')
  cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
  if not cursor.fetchone():
    cursor.execute(
        'INSERT INTO settings (id, cashier_balance) VALUES (1, ?)', (0.0,)
    )
  conn.commit()
  conn.close()


init_db()


# القائمة الرئيسية للأزرار
def get_main_markup():
  markup = types.InlineKeyboardMarkup(row_width=2)
  markup.add(
      types.InlineKeyboardButton('➕ إضافة مستخدم', callback_data='user_add'),
      types.InlineKeyboardButton('❌ حذف مستخدم', callback_data='user_del_list'),
  )
  markup.add(
      types.InlineKeyboardButton('💳 شحن', callback_data='menu_recharge'),
      types.InlineKeyboardButton('💸 سحب', callback_data='menu_withdraw'),
  )
  markup.add(
      types.InlineKeyboardButton('📝 دين', callback_data='menu_debt'),
      types.InlineKeyboardButton(
          '💵 تسديد الدين', callback_data='menu_repay_debt'
      ),
  )
  markup.add(
      types.InlineKeyboardButton(
          '💰 شحن الكاشير', callback_data='menu_cashier'
      ),
      types.InlineKeyboardButton('💸 المصاريف', callback_data='menu_expenses'),
  )
  markup.add(
      types.InlineKeyboardButton('📊 الأرباح', callback_data='menu_profits'),
      types.InlineKeyboardButton(
          '📊 كشف حساب', callback_data='menu_statement'
      ),
  )
  return markup


def send_main_menu(chat_id, message_id=None):
  bot.clear_step_handler_by_chat_id(chat_id)

  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute('SELECT COUNT(*) FROM users')
  user_count = cursor.fetchone()[0]
  cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
  cashier = cursor.fetchone()[0]
  conn.close()

  text = (
      f'💼 **رصيد الكاشير الحالي:** `{cashier:,.0f} SYP`\n'
      f'📊 **إجمالي المستخدمين المحفوظين:** `{user_count}`\n'
      f'━━━━━━━━━━━━━━━\n'
      f'اختر العملية المطلوبة:'
  )

  markup = get_main_markup()

  if message_id:
    try:
      bot.edit_message_text(
          text,
          chat_id,
          message_id,
          reply_markup=markup,
          parse_mode='Markdown',
      )
      return
    except Exception:
      pass
  bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')


# --- نظام الحماية بكلمة المرور وبداية التشغيل ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
  chat_id = message.chat.id
  bot.clear_step_handler_by_chat_id(chat_id)
  remove_markup = types.ReplyKeyboardRemove()
  if chat_id in authenticated_chats:
    bot.send_message(
        chat_id, 'أهلاً بك من جديد.', reply_markup=remove_markup
    )
    send_main_menu(chat_id)
  else:
    msg = bot.send_message(
        chat_id,
        '🔐 **مرحباً بك.**\nيرجى إدخال كلمة المرور للوصول إلى النظام:',
        reply_markup=remove_markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, verify_password)


def verify_password(message):
  if check_cancel_command(message):
    return
  chat_id = message.chat.id
  if message.text == '5555':
    authenticated_chats.add(chat_id)
    bot.send_message(
        chat_id,
        '✅ تم التحقق بنجاح من كلمة المرور.',
        parse_mode='Markdown',
    )
    send_main_menu(chat_id)
  else:
    msg = bot.send_message(
        chat_id,
        '⚠️ كلمة المرور خاطئة. أعد إدخال كلمة المرور الصحيحة:',
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, verify_password)


@bot.callback_query_handler(func=lambda call: call.data == 'back_to_main')
def back_to_main_callback(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  bot.answer_callback_query(call.id)
  send_main_menu(call.message.chat.id, call.message.message_id)


# --- 1. إدارة المستخدمين (إضافة / حذف) ---
@bot.callback_query_handler(func=lambda call: call.data == 'user_add')
def add_user_step(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  markup = types.InlineKeyboardMarkup()
  markup.add(
      types.InlineKeyboardButton(
          '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
      )
  )
  msg = bot.send_message(
      call.message.chat.id,
      'أدخل اسم المستخدم الجديد (يجب أن يحتوي على `@om` سواء كانت حروف كبيرة أو'
      ' صغيرة):\n*(مثال: Ali@om)*',
      reply_markup=markup,
      parse_mode='Markdown',
  )
  bot.register_next_step_handler(msg, save_new_user)
  try:
    bot.delete_message(call.message.chat.id, call.message.message_id)
  except Exception:
    pass


def save_new_user(message):
  if check_cancel_command(message):
    return
  name = message.text.strip()

  # التحقق من أن الاسم ينتهي بـ @om (سواء كابيتال أو سمول)
  if not name.lower().endswith('@om'):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    msg = bot.send_message(
        message.chat.id,
        '⚠️ **خطأ:** يجب أن يحتوي اسم المستخدم على `@om` (سواء كانت حروف كبيرة'
        ' أو صغيرة).\nأعد إدخال الاسم الصحيح:',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, save_new_user)
    return

  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  try:
    cursor.execute('INSERT INTO users (name) VALUES (?)', (name,))
    conn.commit()
    bot.send_message(
        message.chat.id,
        f'✅ تم حفظ المستخدم: **{name}** في القاعدة بنجاح!',
        parse_mode='Markdown',
    )
    send_main_menu(message.chat.id)
  except sqlite3.IntegrityError:
    bot.send_message(
        message.chat.id,
        '⚠️ هذا المستخدم موجود مسبقاً!',
        parse_mode='Markdown',
    )
    send_main_menu(message.chat.id)
  finally:
    conn.close()


@bot.callback_query_handler(func=lambda call: call.data == 'user_del_list')
def delete_user_list(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute('SELECT id, name FROM users')
  users = cursor.fetchall()
  conn.close()

  markup = types.InlineKeyboardMarkup()
  if not users:
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    bot.edit_message_text(
        '⚠️ لا يوجد أي مستخدمين مسجلين للحذف.',
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )
    return

  for user in users:
    markup.add(
        types.InlineKeyboardButton(
            f'❌ {user[1]}', callback_data=f'deluser_{user[0]}'
        )
    )
  markup.add(
      types.InlineKeyboardButton(
          '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
      )
  )
  bot.edit_message_text(
      'اختر المستخدم المراد حذفه نهائياً:',
      call.message.chat.id,
      call.message.message_id,
      reply_markup=markup,
  )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('deluser_')
)
def delete_user_confirm(call):
  user_id = call.data.split('_')[1]
  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute('SELECT name FROM users WHERE id = ?', (user_id,))
  user = cursor.fetchone()
  if user:
    name = user[0]
    cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, f'تم حذف {name}')
    bot.send_message(
        call.message.chat.id,
        f'🗑️ تم حذف المستخدم **{name}** نهائياً من قاعدة البيانات.',
        parse_mode='Markdown',
    )
  else:
    conn.close()
  send_main_menu(call.message.chat.id)


# --- 2. شحن رصيد الكاشير ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_cashier')
def cashier_recharge_start(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  markup = types.InlineKeyboardMarkup()
  markup.add(
      types.InlineKeyboardButton(
          '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
      )
  )
  msg = bot.send_message(
      call.message.chat.id,
      '💰 **شحن رصيد الكاشير**\nأدخل المبلغ المراد إضافته إلى رصيد'
      ' الكاشير:\n*(مثال: 500.000)*',
      reply_markup=markup,
      parse_mode='Markdown',
  )
  bot.register_next_step_handler(msg, process_cashier_recharge)
  try:
    bot.delete_message(call.message.chat.id, call.message.message_id)
  except Exception:
    pass


def process_cashier_recharge(message):
  if check_cancel_command(message):
    return
  try:
    amount = float(message.text.replace('.', '').replace(',', ''))
    conn = sqlite3.connect('syp_store.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE settings SET cashier_balance = cashier_balance + ? WHERE id = 1',
        (amount,),
    )
    conn.commit()
    cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
    new_cashier = cursor.fetchone()[0]
    conn.close()

    bot.send_message(
        message.chat.id,
        f'✅ **تم شحن الكاشير بنجاح!**\nمبلغ الإضافة: **{amount:,.0f}'
        f' SYP**\n💼 الرصيد الحالي: **{new_cashier:,.0f} SYP**',
        parse_mode='Markdown',
    )
    send_main_menu(message.chat.id)
  except ValueError:
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    msg = bot.send_message(
        message.chat.id,
        '⚠️ يرجى إدخال رقم صحيح للمبلغ. أعد المحاولة:',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, process_cashier_recharge)


# --- 3. المصاريف ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_expenses')
def expenses_start(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  markup = types.InlineKeyboardMarkup()
  markup.add(
      types.InlineKeyboardButton(
          '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
      )
  )
  msg = bot.send_message(
      call.message.chat.id,
      '💸 **تسجيل مصروف جديد**\nأدخل المبلغ المراد خصمه من الكاشير (بالـ'
      ' SYP):\n*(مثال: 50.000)*',
      reply_markup=markup,
      parse_mode='Markdown',
  )
  bot.register_next_step_handler(msg, process_expense_amount)
  try:
    bot.delete_message(call.message.chat.id, call.message.message_id)
  except Exception:
    pass


def process_expense_amount(message):
  if check_cancel_command(message):
    return
  try:
    amount = float(message.text.replace('.', '').replace(',', ''))
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    msg = bot.send_message(
        message.chat.id,
        f'💵 المبلغ المدخل: **{amount:,.0f} SYP**\n\n📝 الآن أدخل سبب أو وصف'
        ' المصروف (مثال: بونص، أجور...):',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, process_expense_reason, amount)
  except ValueError:
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    msg = bot.send_message(
        message.chat.id,
        '⚠️ يرجى إدخال رقم صحيح للمبلغ. أعد المحاولة:',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, process_expense_amount)


def process_expense_reason(message, amount):
  if check_cancel_command(message):
    return
  reason = message.text.strip()
  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      'UPDATE settings SET cashier_balance = cashier_balance - ? WHERE id = 1',
      (amount,),
  )
  cursor.execute(
      'INSERT INTO expenses (amount, reason) VALUES (?, ?)', (amount, reason)
  )
  conn.commit()
  cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
  new_cashier = cursor.fetchone()[0]
  conn.close()

  bot.send_message(
      message.chat.id,
      f'✅ **تم تسجيل المصروف بنجاح!**\n\n'
      f'📌 الوصف / السبب: **{reason}**\n'
      f'💵 المبلغ المسحوب: **{amount:,.0f} SYP**\n'
      f'💼 رصيد الكاشير المتبقي: **{new_cashier:,.0f} SYP**',
      parse_mode='Markdown',
  )
  send_main_menu(message.chat.id)


# --- 4. الأرباح ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_profits')
def show_profits_menu(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute('SELECT SUM(amount) FROM profits')
  total_profits = cursor.fetchone()[0] or 0.0

  cursor.execute(
      'SELECT amount, reason, date FROM profits ORDER BY id DESC LIMIT 15'
  )
  profits_list = cursor.fetchall()
  conn.close()

  text = (
      f'📊 **قسم الأرباح والعمولات**\n'
      f'━━━━━━━━━━━━━━━\n'
      f'💰 إجمالي الأرباح: **{total_profits:,.0f} SYP**\n\n'
      f'📝 **آخر العمليات:**\n'
  )

  if profits_list:
    for p in profits_list:
      text += f'• `{p[2]}` | **+{p[0]:,.0f} SYP**\n  ↳ _{p[1]}_\n'
  else:
    text += '_لا توجد أرباح مسجلة حتى الآن._\n'

  markup = types.InlineKeyboardMarkup()
  markup.add(
      types.InlineKeyboardButton(
          '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
      )
  )

  bot.edit_message_text(
      text,
      call.message.chat.id,
      call.message.message_id,
      reply_markup=markup,
      parse_mode='Markdown',
  )


# --- 5. عمليات السحب ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_withdraw')
def withdraw_users_list(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute('SELECT id, name FROM users')
  users = cursor.fetchall()
  conn.close()

  markup = types.InlineKeyboardMarkup()
  if not users:
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    bot.edit_message_text(
        '⚠️ لا يوجد مستخدمين مسجلين لإجراء سحب لهم.',
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )
    return

  for user in users:
    markup.add(
        types.InlineKeyboardButton(
            f'👤 {user[1]}', callback_data=f'withdrawuser_{user[0]}'
        )
    )
  markup.add(
      types.InlineKeyboardButton(
          '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
      )
  )

  bot.edit_message_text(
      '🏧 **قسم عمليات السحب**\nاختر المستخدم المراد إجراء عملية سحب له:',
      call.message.chat.id,
      call.message.message_id,
      reply_markup=markup,
      parse_mode='Markdown',
  )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('withdrawuser_')
)
def withdraw_amount_prompt(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  user_id = call.data.split('_')[1]
  markup = types.InlineKeyboardMarkup()
  markup.add(
      types.InlineKeyboardButton('🔙 رجوع', callback_data='menu_withdraw')
  )
  msg = bot.send_message(
      call.message.chat.id,
      '💵 **أدخل مبلغ السحب الأساسي** (بالـ SYP):\n*(ملاحظة: سيتم خصم عمولة'
      ' 10% تلقائياً وتضاف للأرباح)*\n*(مثال: 100.000)*',
      reply_markup=markup,
      parse_mode='Markdown',
  )
  bot.register_next_step_handler(msg, process_withdrawal_calculation, user_id)
  try:
    bot.delete_message(call.message.chat.id, call.message.message_id)
  except Exception:
    pass


def process_withdrawal_calculation(message, user_id):
  if check_cancel_command(message):
    return
  try:
    amount = float(message.text.replace('.', '').replace(',', ''))
    fee = amount * 0.10
    net_amount = amount - fee

    conn = sqlite3.connect('syp_store.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()

    if not user:
      bot.send_message(
          message.chat.id, '⚠️ المستخدم غير موجود.', parse_mode='Markdown'
      )
      conn.close()
      send_main_menu(message.chat.id)
      return

    name = user[0]

    cursor.execute(
        'INSERT INTO withdrawals (user_id, amount, fee, net_amount) VALUES (?,'
        ' ?, ?, ?)',
        (user_id, amount, fee, net_amount),
    )

    profit_reason = f'عمولة سحب (10%) بمبلغ أساسي {amount:,.0f} SYP للمستخدم {name}'
    cursor.execute(
        'INSERT INTO profits (amount, reason) VALUES (?, ?)',
        (fee, profit_reason),
    )

    cursor.execute(
        'UPDATE settings SET cashier_balance = cashier_balance + ? WHERE id = 1',
        (amount,),
    )

    conn.commit()
    cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
    new_cashier = cursor.fetchone()[0]
    conn.close()

    bot.send_message(
        message.chat.id,
        f'✅ **تمت عملية السحب بنجاح!**\n\n'
        f'👤 اسم المستخدم: **{name}**\n'
        f'━━━━━━━━━━━━━━━\n'
        f'💵 مبلغ السحب: **{amount:,.0f} SYP**\n'
        f'📉 رسوم السحب (10% أرباح): **{fee:,.0f} SYP**\n'
        f'💰 الصافي للمستخدم: **{net_amount:,.0f} SYP**\n'
        f'💼 رصيد الكاشير الجديد: **{new_cashier:,.0f} SYP**',
        parse_mode='Markdown',
    )
    send_main_menu(message.chat.id)

  except ValueError:
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    msg = bot.send_message(
        message.chat.id,
        '⚠️ يرجى إدخال رقم صحيح للمبلغ. أعد المحاولة:',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, process_withdrawal_calculation, user_id)


# --- 6. زر الشحن ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_recharge')
def recharge_users_list(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute('SELECT id, name FROM users')
  users = cursor.fetchall()
  conn.close()

  markup = types.InlineKeyboardMarkup()
  if not users:
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    bot.edit_message_text(
        '⚠️ لا يوجد مستخدمين مسجلين للشحن لهم.',
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )
    return

  for user in users:
    markup.add(
        types.InlineKeyboardButton(
            f'💳 {user[1]}', callback_data=f'rechargeuser_{user[0]}'
        )
    )
  markup.add(
      types.InlineKeyboardButton(
          '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
      )
  )

  bot.edit_message_text(
      '💳 **قسم شحن رصيد المستخدمين**\nاختر المستخدم المراد شحن رصيده:',
      call.message.chat.id,
      call.message.message_id,
      reply_markup=markup,
      parse_mode='Markdown',
  )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('rechargeuser_')
)
def recharge_amount_prompt(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  user_id = call.data.split('_')[1]
  markup = types.InlineKeyboardMarkup()
  markup.add(
      types.InlineKeyboardButton('🔙 رجوع', callback_data='menu_recharge')
  )
  msg = bot.send_message(
      call.message.chat.id,
      '💵 **أدخل مبلغ الشحن** (بالـ SYP):\n*(ملاحظة: سيتم خصم المبلغ من رصيد'
      ' الكاشير تلقائياً)*\n*(مثال: 50.000)*',
      reply_markup=markup,
      parse_mode='Markdown',
  )
  bot.register_next_step_handler(msg, process_recharge_save, user_id)
  try:
    bot.delete_message(call.message.chat.id, call.message.message_id)
  except Exception:
    pass


def process_recharge_save(message, user_id):
  if check_cancel_command(message):
    return
  try:
    amount = float(message.text.replace('.', '').replace(',', ''))
    conn = sqlite3.connect('syp_store.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute(
        'UPDATE settings SET cashier_balance = cashier_balance - ? WHERE id ='
        ' 1',
        (amount,),
    )
    cursor.execute(
        'UPDATE users SET balance = balance + ? WHERE id = ?', (amount, user_id)
    )

    cursor.execute('SELECT name, balance FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()

    cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
    new_cashier = cursor.fetchone()[0]

    conn.commit()
    conn.close()

    if user:
      bot.send_message(
          message.chat.id,
          f'✅ **تم شحن رصيد المستخدم بنجاح!**\n\n'
          f'👤 المستخدم: **{user[0]}**\n'
          f'💵 المبلغ المضاف: **{amount:,.0f} SYP**\n'
          f'💼 رصيد المستخدم الجديد: **{user[1]:,.0f} SYP**\n'
          f'📉 رصيد الكاشير المتبقي: **{new_cashier:,.0f} SYP**',
          parse_mode='Markdown',
      )
    send_main_menu(message.chat.id)
  except ValueError:
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    msg = bot.send_message(
        message.chat.id,
        '⚠️ يرجى إدخال رقم صحيح للمبلغ. أعد المحاولة:',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, process_recharge_save, user_id)


# --- 7. زر الدين ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_debt')
def debt_users_list(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute('SELECT id, name FROM users')
  users = cursor.fetchall()
  conn.close()

  markup = types.InlineKeyboardMarkup()
  if not users:
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    bot.edit_message_text(
        '⚠️ لا يوجد مستخدمين مسجلين.',
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )
    return

  for user in users:
    markup.add(
        types.InlineKeyboardButton(
            f'📝 {user[1]}', callback_data=f'debtuser_{user[0]}'
        )
    )
  markup.add(
      types.InlineKeyboardButton(
          '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
      )
  )

  bot.edit_message_text(
      '📝 **تسجيل دين على المستخدم**\nاختر المستخدم:',
      call.message.chat.id,
      call.message.message_id,
      reply_markup=markup,
      parse_mode='Markdown',
  )


@bot.callback_query_handler(func=lambda call: call.data.startswith('debtuser_'))
def debt_amount_prompt(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  user_id = call.data.split('_')[1]
  markup = types.InlineKeyboardMarkup()
  markup.add(types.InlineKeyboardButton('🔙 رجوع', callback_data='menu_debt'))
  msg = bot.send_message(
      call.message.chat.id,
      '💵 **أدخل مبلغ الدين** (بالـ SYP):\n*(ملاحظة: سيتم تنقيصه من رصيد'
      ' الكاشير)*',
      reply_markup=markup,
      parse_mode='Markdown',
  )
  bot.register_next_step_handler(msg, process_debt_save, user_id)
  try:
    bot.delete_message(call.message.chat.id, call.message.message_id)
  except Exception:
    pass


def process_debt_save(message, user_id):
  if check_cancel_command(message):
    return
  try:
    amount = float(message.text.replace('.', '').replace(',', ''))
    conn = sqlite3.connect('syp_store.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute(
        'UPDATE users SET debt = debt + ? WHERE id = ?', (amount, user_id)
    )
    cursor.execute(
        'UPDATE settings SET cashier_balance = cashier_balance - ? WHERE id = 1',
        (amount,),
    )

    cursor.execute('SELECT name, debt FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
    new_cashier = cursor.fetchone()[0]

    conn.commit()
    conn.close()

    if user:
      bot.send_message(
          message.chat.id,
          f'✅ **تم تسجيل الدين بنجاح!**\n\n👤 المستخدم: **{user[0]}**\n💵 مبلغ الدين:'
          f' **{amount:,.0f} SYP**\n📊 إجمالي الدين الجديد:'
          f' **{user[1]:,.0f} SYP**\n💼 رصيد الكاشير الجديد:'
          f' **{new_cashier:,.0f} SYP**',
          parse_mode='Markdown',
      )
    send_main_menu(message.chat.id)
  except ValueError:
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    msg = bot.send_message(
        message.chat.id,
        '⚠️ يرجى إدخال رقم صحيح للمبلغ.',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, process_debt_save, user_id)


# --- 8. زر تسديد الدين ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_repay_debt')
def repay_debt_users_list(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute('SELECT id, name, debt FROM users WHERE debt > 0')
  users = cursor.fetchall()
  conn.close()

  markup = types.InlineKeyboardMarkup()
  if not users:
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    bot.edit_message_text(
        '⚠️ لا يوجد أي ديون مستحقة على المستخدمين حالياً.',
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )
    return

  for user in users:
    markup.add(
        types.InlineKeyboardButton(
            f'💵 {user[1]} (دين: {user[2]:,.0f})',
            callback_data=f'repayuser_{user[0]}',
        )
    )
  markup.add(
      types.InlineKeyboardButton(
          '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
      )
  )

  bot.edit_message_text(
      '💵 **تسديد الدين**\nاختر المستخدم لتسديد دينه:',
      call.message.chat.id,
      call.message.message_id,
      reply_markup=markup,
      parse_mode='Markdown',
  )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('repayuser_')
)
def repay_amount_prompt(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  user_id = call.data.split('_')[1]
  markup = types.InlineKeyboardMarkup()
  markup.add(
      types.InlineKeyboardButton('🔙 رجوع', callback_data='menu_repay_debt')
  )
  msg = bot.send_message(
      call.message.chat.id,
      '💵 **أدخل مبلغ التسديد** (بالـ SYP):\n*(ملاحظة: سيتم إضافته إلى رصيد'
      ' الكاشير)*',
      reply_markup=markup,
      parse_mode='Markdown',
  )
  bot.register_next_step_handler(msg, process_repay_save, user_id)
  try:
    bot.delete_message(call.message.chat.id, call.message.message_id)
  except Exception:
    pass


def process_repay_save(message, user_id):
  if check_cancel_command(message):
    return
  try:
    amount = float(message.text.replace('.', '').replace(',', ''))
    conn = sqlite3.connect('syp_store.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute(
        'UPDATE users SET debt = MAX(0, debt - ?) WHERE id = ?',
        (amount, user_id),
    )
    cursor.execute(
        'UPDATE settings SET cashier_balance = cashier_balance + ? WHERE id = 1',
        (amount,),
    )

    cursor.execute('SELECT name, debt FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
    new_cashier = cursor.fetchone()[0]

    conn.commit()
    conn.close()

    if user:
      bot.send_message(
          message.chat.id,
          f'✅ **تم تسديد الدين بنجاح!**\n\n👤 المستخدم: **{user[0]}**\n💵 المبلغ'
          f' المسدد: **{amount:,.0f} SYP**\n📊 الدين المتبقي: **{user[1]:,.0f}'
          f' SYP**\n💼 رصيد الكاشير الجديد: **{new_cashier:,.0f} SYP**',
          parse_mode='Markdown',
      )
    send_main_menu(message.chat.id)
  except ValueError:
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    msg = bot.send_message(
        message.chat.id,
        '⚠️ يرجى إدخال رقم صحيح للمبلغ.',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, process_repay_save, user_id)


# --- 9. زر كشف حساب ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_statement')
def statement_users_list(call):
  bot.clear_step_handler_by_chat_id(call.message.chat.id)
  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute('SELECT id, name, balance, debt FROM users')
  users = cursor.fetchall()
  conn.close()

  markup = types.InlineKeyboardMarkup()
  if not users:
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )
    bot.edit_message_text(
        '⚠️ لا يوجد مستخدمين مسجلين.',
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )
    return

  for user in users:
    markup.add(
        types.InlineKeyboardButton(
            '📊 ' + user[1], callback_data=f'statuser_{user[0]}'
        )
    )
  markup.add(
      types.InlineKeyboardButton(
          '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
      )
  )

  bot.edit_message_text(
      '📊 **كشف حساب المستخدمين**\nاختر المستخدم لعرض تفاصيله:',
      call.message.chat.id,
      call.message.message_id,
      reply_markup=markup,
      parse_mode='Markdown',
  )


@bot.callback_query_handler(func=lambda call: call.data.startswith('statuser_'))
def show_user_statement(call):
  user_id = call.data.split('_')[1]
  conn = sqlite3.connect('syp_store.db', check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute('SELECT name, balance, debt FROM users WHERE id = ?', (user_id,))
  user = cursor.fetchone()
  conn.close()

  markup = types.InlineKeyboardMarkup()
  markup.add(
      types.InlineKeyboardButton(
          '🔙 رجوع للقائمة', callback_data='menu_statement'
      ),
      types.InlineKeyboardButton(
          '🏠 القائمة الرئيسية', callback_data='back_to_main'
      ),
  )

  if user:
    text = (
        f'📊 **كشف حساب المستخدم:** `{user[0]}`\n'
        f'━━━━━━━━━━━━━━━\n'
        f'💳 الرصيد الحالي: **{user[1]:,.0f} SYP**\n'
        f'📝 إجمالي الديون: **{user[2]:,.0f} SYP**'
    )
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )
  else:
    bot.answer_callback_query(call.id, 'المستخدم غير موجود')
    send_main_menu(call.message.chat.id)


print('Bot is running with updated error message and clean /start handler...')
bot.infinity_polling()
