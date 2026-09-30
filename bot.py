import datetime
import os
import sqlite3
import threading
import time
import urllib.request

# --- مكتبات توليد الـ PDF ودعم اللغة العربية ---
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import telebot
from telebot import types

TOKEN ='8798815717:AAFK2_Cm6xPhqhJD9Mgnm02b4tiMIM18Ikc'
bot = telebot.TeleBot(TOKEN)

# تخزين الجلسات النشطة
authenticated_chats = set()
temp_custom_items = {}

# --- إعداد مسار قاعدة البيانات ---
DATA_DIR = os.getenv('DATA_DIR', '.')
if DATA_DIR != '.' and not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, 'syp_store.db')
FONT_PATH = os.path.join(DATA_DIR, 'Amiri-Regular.ttf')


def get_db_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


# --- إعداد الخط العربي لـ PDF ---
def setup_arabic_font():
    """تنزيل خط عربي وإعداده لضمان طباعة الأحرف العربية بشكل صحيح في PDF."""
    if not os.path.exists(FONT_PATH):
        try:
            url = 'https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Regular.ttf'
            urllib.request.urlretrieve(url, FONT_PATH)
        except Exception as e:
            print(f'Warning: Could not download font automatically: {e}')

    if os.path.exists(FONT_PATH):
        pdfmetrics.registerFont(TTFont('ArabicFont', FONT_PATH))
        return 'ArabicFont'
    return 'Helvetica'


FONT_NAME = setup_arabic_font()


def ar(text):
    """دالة إعادة تشكيل النصوص العربية لاتجاه اليمين لليسار في PDF."""
    if text is None:
        return ''
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)


def check_cancel_command(message):
    if message.text and message.text.startswith('/'):
        bot.clear_step_handler_by_chat_id(message.chat.id)
        if message.text.split()[0] == '/start':
            send_welcome(message)
        return True
    return False


# --- 1. إعداد قاعدة البيانات ---
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            balance REAL DEFAULT 0,
            debt REAL DEFAULT 0,
            loyalty_points INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('PRAGMA table_info(users)')
    columns = [column[1] for column in cursor.fetchall()]
    if 'loyalty_points' not in columns:
        cursor.execute(
            'ALTER TABLE users ADD COLUMN loyalty_points INTEGER DEFAULT 0'
        )

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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recharges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            points_earned INTEGER DEFAULT 0,
            date TEXT DEFAULT (datetime('now', 'localtime'))
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE,
            effect_type TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            amount REAL,
            notes TEXT,
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


# --- 2. دالة إنتاج تقرير الـ PDF اليومي الشامل ---
def generate_daily_pdf():
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    pdf_filename = f'Daily_Report_{today_str}.pdf'

    doc = SimpleDocTemplate(
        pdf_filename,
        pagesize=A4,
        rightMargin=20,
        leftMargin=20,
        topMargin=20,
        bottomMargin=20,
    )
    elements = []

    style_sheet = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=style_sheet['Heading1'],
        fontName=FONT_NAME,
        fontSize=18,
        alignment=1,  # Center
        textColor=colors.HexColor('#1A237E'),
        spaceAfter=12,
    )
    sub_title_style = ParagraphStyle(
        'SubTitleStyle',
        parent=style_sheet['Normal'],
        fontName=FONT_NAME,
        fontSize=11,
        alignment=1,
        textColor=colors.HexColor('#424242'),
        spaceAfter=15,
    )
    section_style = ParagraphStyle(
        'SectionStyle',
        parent=style_sheet['Heading2'],
        fontName=FONT_NAME,
        fontSize=13,
        alignment=2,  # Right
        textColor=colors.HexColor('#0D47A1'),
        spaceBefore=10,
        spaceAfter=6,
    )
    cell_style = ParagraphStyle(
        'CellStyle',
        parent=style_sheet['Normal'],
        fontName=FONT_NAME,
        fontSize=9,
        alignment=1,  # Center
    )
    cell_header = ParagraphStyle(
        'CellHeader',
        parent=style_sheet['Normal'],
        fontName=FONT_NAME,
        fontSize=10,
        alignment=1,
        textColor=colors.white,
    )

    elements.append(
        Paragraph(ar(f'تقرير العمليات اليومي الشامل - {today_str}'), title_style)
    )

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
    cashier_bal = cursor.fetchone()[0] or 0.0

    elements.append(
        Paragraph(
            ar(f'رصيد الكاشير الحالي في النظام: {cashier_bal:,.0f} SYP'),
            sub_title_style,
        )
    )

    def create_pdf_table(data_list, col_widths):
        table = Table(data_list, colWidths=col_widths)
        table.setStyle(
            TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#283593')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#BDBDBD')),
                (
                    'ROWBACKGROUNDS',
                    (0, 1),
                    (-1, -1),
                    [colors.HexColor('#F5F5F5'), colors.white],
                ),
            ])
        )
        return table

    # أ. جدول ملخص كافة المستخدمين
    elements.append(
        Paragraph(
            ar('1. كشف السجل العام لكافة المستخدمين (نسخة احتياطية):'),
            section_style,
        )
    )
    cursor.execute(
        'SELECT name, balance, debt, loyalty_points FROM users ORDER BY id ASC'
    )
    users = cursor.fetchall()

    u_data = [[
        Paragraph(ar('نقاط الولاء'), cell_header),
        Paragraph(ar('الديون (SYP)'), cell_header),
        Paragraph(ar('الرصيد (SYP)'), cell_header),
        Paragraph(ar('اسم المستخدم'), cell_header),
    ]]
    if users:
        for u in users:
            u_data.append([
                Paragraph(ar(str(u[3] or 0)), cell_style),
                Paragraph(ar(f'{u[2]:,.0f}'), cell_style),
                Paragraph(ar(f'{u[1]:,.0f}'), cell_style),
                Paragraph(ar(u[0]), cell_style),
            ])
    else:
        u_data.append([
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('لا يوجد مستخدمين مسجلين'), cell_style),
        ])
    elements.append(create_pdf_table(u_data, [100, 130, 130, 180]))
    elements.append(Spacer(1, 10))

    # ب. عمليات الشحن اليومية
    elements.append(Paragraph(ar('2. عمليات الشحن اليومية:'), section_style))
    cursor.execute(
        '''
        SELECT u.name, r.amount, r.points_earned, r.date 
        FROM recharges r JOIN users u ON r.user_id = u.id 
        WHERE date(r.date) = date('now', 'localtime')
        ORDER BY r.id DESC
    '''
    )
    recharges = cursor.fetchall()

    r_data = [[
        Paragraph(ar('الوقت'), cell_header),
        Paragraph(ar('النقاط المكتسبة'), cell_header),
        Paragraph(ar('المبلغ (SYP)'), cell_header),
        Paragraph(ar('المستخدم'), cell_header),
    ]]
    if recharges:
        for r in recharges:
            r_data.append([
                Paragraph(ar(r[3].split()[1] if ' ' in r[3] else r[3]), cell_style),
                Paragraph(ar(str(r[2])), cell_style),
                Paragraph(ar(f'{r[1]:,.0f}'), cell_style),
                Paragraph(ar(r[0]), cell_style),
            ])
    else:
        r_data.append([
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('لا توجد عمليات شحن اليوم'), cell_style),
        ])
    elements.append(create_pdf_table(r_data, [100, 100, 140, 200]))
    elements.append(Spacer(1, 10))

    # جـ. عمليات السحب اليومية
    elements.append(Paragraph(ar('3. عمليات السحب اليومية:'), section_style))
    cursor.execute(
        '''
        SELECT u.name, w.amount, w.fee, w.net_amount, w.date 
        FROM withdrawals w JOIN users u ON w.user_id = u.id 
        WHERE date(w.date) = date('now', 'localtime')
        ORDER BY w.id DESC
    '''
    )
    withdrawals = cursor.fetchall()

    w_data = [[
        Paragraph(ar('الوقت'), cell_header),
        Paragraph(ar('الصافي للمستخدم'), cell_header),
        Paragraph(ar('العمولة (10%)'), cell_header),
        Paragraph(ar('المبلغ الكلي'), cell_header),
        Paragraph(ar('المستخدم'), cell_header),
    ]]
    if withdrawals:
        for w in withdrawals:
            w_data.append([
                Paragraph(ar(w[4].split()[1] if ' ' in w[4] else w[4]), cell_style),
                Paragraph(ar(f'{w[3]:,.0f}'), cell_style),
                Paragraph(ar(f'{w[2]:,.0f}'), cell_style),
                Paragraph(ar(f'{w[1]:,.0f}'), cell_style),
                Paragraph(ar(w[0]), cell_style),
            ])
    else:
        w_data.append([
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('لا توجد عمليات سحب اليوم'), cell_style),
        ])
    elements.append(create_pdf_table(w_data, [80, 110, 100, 110, 140]))
    elements.append(Spacer(1, 10))

    # د. المصاريف والأرباح اليومية
    elements.append(
        Paragraph(ar('4. المصاريف والأرباح المسجلة اليوم:'), section_style)
    )
    cursor.execute(
        "SELECT amount, reason, date FROM expenses WHERE date(date) = date('now', 'localtime') ORDER BY id DESC"
    )
    expenses = cursor.fetchall()

    cursor.execute(
        "SELECT amount, reason, date FROM profits WHERE date(date) = date('now', 'localtime') ORDER BY id DESC"
    )
    profits = cursor.fetchall()

    ep_data = [[
        Paragraph(ar('الوقت'), cell_header),
        Paragraph(ar('الوصف / السبب'), cell_header),
        Paragraph(ar('المبلغ (SYP)'), cell_header),
        Paragraph(ar('النوع'), cell_header),
    ]]

    for e in expenses:
        ep_data.append([
            Paragraph(ar(e[2].split()[1] if ' ' in e[2] else e[2]), cell_style),
            Paragraph(ar(e[1]), cell_style),
            Paragraph(ar(f'-{e[0]:,.0f}'), cell_style),
            Paragraph(ar('مصروف'), cell_style),
        ])
    for p in profits:
        ep_data.append([
            Paragraph(ar(p[2].split()[1] if ' ' in p[2] else p[2]), cell_style),
            Paragraph(ar(p[1]), cell_style),
            Paragraph(ar(f'+{p[0]:,.0f}'), cell_style),
            Paragraph(ar('ربح / عمولة'), cell_style),
        ])

    if len(ep_data) == 1:
        ep_data.append([
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('لا توجد مصاريف أو أرباح جديدة اليوم'), cell_style),
            Paragraph(ar('-'), cell_style),
            Paragraph(ar('-'), cell_style),
        ])

    elements.append(create_pdf_table(ep_data, [80, 240, 120, 100]))

    conn.close()

    doc.build(elements)
    return pdf_filename


# --- 3. جدولة الإرسال التلقائي نهاية كل يوم (23:59) ---
def daily_auto_pdf_scheduler():
    last_sent_date = None
    while True:
        now = datetime.datetime.now()
        current_date = now.strftime('%Y-%m-%d')

        if (
            now.hour == 23
            and now.minute == 59
            and last_sent_date != current_date
        ):
            if authenticated_chats:
                try:
                    pdf_file = generate_daily_pdf()
                    for chat_id in list(authenticated_chats):
                        try:
                            with open(pdf_file, 'rb') as doc:
                                bot.send_document(
                                    chat_id,
                                    doc,
                                    caption=(
                                        '📊 **التقرير اليومي الأوتوماتيكي**\nتم'
                                        ' إرفاق ملف الـ PDF الشامل لكافة عمليات'
                                        f' اليوم ({current_date}).'
                                    ),
                                    parse_mode='Markdown',
                                )
                        except Exception as ex:
                            print(
                                f'Failed to send daily report to {chat_id}: {ex}'
                            )
                    last_sent_date = current_date
                except Exception as e:
                    print(f'Error generating scheduled PDF: {e}')
            time.sleep(60)
        time.sleep(30)


threading.Thread(target=daily_auto_pdf_scheduler, daemon=True).start()


# --- القائمة الرئيسية للمستخدم ---
def get_main_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('➕ إضافة مستخدم', callback_data='user_add'),
        types.InlineKeyboardButton(
            '❌ حذف مستخدم', callback_data='user_del_list'
        ),
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
    markup.add(
        types.InlineKeyboardButton(
            '⚙️ البنود المخصصة', callback_data='menu_custom_items'
        ),
        types.InlineKeyboardButton(
            '🎁 نقاط الولاء', callback_data='menu_loyalty'
        ),
    )
    # زر استخراج التقرير الفوري بصيغة PDF
    markup.add(
        types.InlineKeyboardButton(
            '📄 تقرير اليوم الشامل (PDF)', callback_data='get_daily_pdf_now'
        )
    )
    return markup


def send_main_menu(chat_id, message_id=None):
    bot.clear_step_handler_by_chat_id(chat_id)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    user_count = cursor.fetchone()[0]
    cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
    cashier = cursor.fetchone()[0]
    conn.close()

    text = (
        f'💼 رصيد الكاشير الحالي: {cashier:,.0f} SYP\n'
        f'📊 إجمالي المستخدمين المحفوظين: {user_count}\n'
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


# --- زر استخراج تقرير اليوم يدوي بأي وقت ---
@bot.callback_query_handler(func=lambda call: call.data == 'get_daily_pdf_now')
def send_daily_pdf_manual(call):
    bot.answer_callback_query(call.id, 'جارٍ إعداد تقرير PDF...')
    try:
        pdf_file = generate_daily_pdf()
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        with open(pdf_file, 'rb') as doc:
            bot.send_document(
                call.message.chat.id,
                doc,
                caption=f'📄 **تقرير اليوم الشامل ({today_str})** بصيغة PDF.',
                parse_mode='Markdown',
            )
    except Exception as e:
        bot.send_message(
            call.message.chat.id,
            f'⚠️ حدث خطأ أثناء إنشاء الملف: {e}',
            parse_mode='Markdown',
        )


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
            '🔐 مرحباً بك.\nيرجى إدخال كلمة المرور للوصول إلى النظام:',
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


# --- إضافة وحذف المستخدمين ---
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
        'أدخل اسم المستخدم الجديد (يجب أن يحتوي على @om سواء كانت حروف كبيرة أو صغيرة):\n*(مثال: Ali@om)*',
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

    if not name.lower().endswith('@om'):
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
            )
        )
        msg = bot.send_message(
            message.chat.id,
            '⚠️ خطأ: يجب أن ينتهي اسم المستخدم بـ @om (سواء كانت حروف كبيرة أو صغيرة).\nأعد إدخال الاسم الصحيح:',
            reply_markup=markup,
            parse_mode='Markdown',
        )
        bot.register_next_step_handler(msg, save_new_user)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (name) VALUES (?)', (name,))
        conn.commit()
        bot.send_message(
            message.chat.id,
            f'✅ تم حفظ المستخدم: {name} في القاعدة بنجاح!',
            parse_mode='Markdown',
        )
        send_main_menu(message.chat.id)
    except sqlite3.IntegrityError:
        bot.send_message(
            message.chat.id,
            '⚠ هذا المستخدم موجود مسبقاً!',
            parse_mode='Markdown',
        )
        send_main_menu(message.chat.id)
    finally:
        conn.close()


@bot.callback_query_handler(func=lambda call: call.data == 'user_del_list')
def delete_user_list(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    conn = get_db_connection()
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
            '⚠ لا يوجد أي مستخدمين مسجلين للحذف.',
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


@bot.callback_query_handler(func=lambda call: call.data.startswith('deluser_'))
def delete_user_confirm(call):
    user_id = call.data.split('_')[1]
    conn = get_db_connection()
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
            f'🗑️ تم حذف المستخدم {name} نهائياً من قاعدة البيانات.',
            parse_mode='Markdown',
        )
    else:
        conn.close()
    send_main_menu(call.message.chat.id)


# --- شحن الكاشير والمصاريف والأرباح ---
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
        '💰 شحن رصيد الكاشير\nأدخل المبلغ المراد إضافته إلى رصيد الكاشير:\n*(مثال: 500.000)*',
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
        conn = get_db_connection()
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
            f'✅ تم شحن الكاشير بنجاح!\nمبلغ الإضافة: {amount:,.0f} SYP\n💼 الرصيد الحالي: {new_cashier:,.0f} SYP',
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
        '💸 تسجيل مصروف جديد\nأدخل المبلغ المراد خصمه من الكاشير (بالـ SYP):\n*(مثال: 50.000)*',
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
            f'💵 المبلغ المدخل: {amount:,.0f} SYP\n\n📝 الآن أدخل سبب أو وصف المصروف (مثال: بونص، أجور...):',
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
    conn = get_db_connection()
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
        f'✅ تم تسجيل المصروف بنجاح!\n\n'
        f'📌 الوصف / السبب: {reason}\n'
        f'💵 المبلغ المسحوب: {amount:,.0f} SYP\n'
        f'💼 رصيد الكاشير المتبقي: {new_cashier:,.0f} SYP',
        parse_mode='Markdown',
    )
    send_main_menu(message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data == 'menu_profits')
def show_profits_menu(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(amount) FROM profits')
    total_profits = cursor.fetchone()[0] or 0.0

    cursor.execute(
        'SELECT amount, reason, date FROM profits ORDER BY id DESC LIMIT 15'
    )
    profits_list = cursor.fetchall()
    conn.close()

    text = (
        f'📊 قسم الأرباح والعمولات\n'
        f'━━━━━━━━━━━━━━━\n'
        f'💰 إجمالي الأرباح: {total_profits:,.0f} SYP\n\n'
        f'📝 آخر العمليات:\n'
    )

    if profits_list:
        for p in profits_list:
            text += f'• {p[2]} | +{p[0]:,.0f} SYP\n ↳ {p[1]}\n'
    else:
        text += 'لا توجد أرباح مسجلة حتى الآن.\n'

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '➕ إضافة ربح يدوي', callback_data='add_manual_profit'
        )
    )
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


@bot.callback_query_handler(func=lambda call: call.data == 'add_manual_profit')
def manual_profit_start(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للأرباح', callback_data='menu_profits'
        )
    )
    msg = bot.send_message(
        call.message.chat.id,
        '💰 إضافة ربح يدوي\nأدخل مبلغ الربح (بالـ SYP):\n*(مثال: 25.000)*',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, process_manual_profit_amount)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass


def process_manual_profit_amount(message):
    if check_cancel_command(message):
        return
    try:
        amount = float(message.text.replace('.', '').replace(',', ''))
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                '🔙 رجوع للأرباح', callback_data='menu_profits'
            )
        )
        msg = bot.send_message(
            message.chat.id,
            f'💵 المبلغ المدخل: {amount:,.0f} SYP\n\n📝 الآن أدخل سبب أو وصف الربح اليدوي:',
            reply_markup=markup,
            parse_mode='Markdown',
        )
        bot.register_next_step_handler(
            msg, process_manual_profit_reason, amount
        )
    except ValueError:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                '🔙 رجوع للأرباح', callback_data='menu_profits'
            )
        )
        msg = bot.send_message(
            message.chat.id,
            '⚠️ يرجى إدخال رقم صحيح للمبلغ. أعد المحاولة:',
            reply_markup=markup,
            parse_mode='Markdown',
        )
        bot.register_next_step_handler(msg, process_manual_profit_amount)


def process_manual_profit_reason(message, amount):
    if check_cancel_command(message):
        return
    reason = message.text.strip()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        'INSERT INTO profits (amount, reason) VALUES (?, ?)',
        (amount, f'ربح يدوي: {reason}'),
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
        f'✅ تمت إضافة الربح اليدوي وتحديث الكاشير بنجاح!\n\n'
        f'📌 السبب: {reason}\n'
        f'💵 مبلغ الربح: {amount:,.0f} SYP\n'
        f'💼 رصيد الكاشير الجديد: {new_cashier:,.0f} SYP',
        parse_mode='Markdown',
    )
    send_main_menu(message.chat.id)


# --- عمليات السحب ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_withdraw')
def withdraw_users_list(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    conn = get_db_connection()
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
        '🏧 قسم عمليات السحب\nاختر المستخدم المراد إجراء عملية سحب له:',
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
        '💵 أدخل مبلغ السحب الأساسي (بالـ SYP):\n*(ملاحظة: سيتم خصم عمولة 10% تلقائياً وتضاف للأرباح)\n(مثال: 100.000)*',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(
        msg, process_withdrawal_calculation, user_id
    )
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

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()

        if not user:
            bot.send_message(
                message.chat.id, '⚠ المستخدم غير موجود.', parse_mode='Markdown'
            )
            conn.close()
            send_main_menu(message.chat.id)
            return

        name = user[0]

        cursor.execute(
            'INSERT INTO withdrawals (user_id, amount, fee, net_amount) VALUES (?, ?, ?, ?)',
            (user_id, amount, fee, net_amount),
        )

        profit_reason = (
            f'عمولة سحب (10%) بمبلغ أساسي {amount:,.0f} SYP للمستخدم {name}'
        )
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
            f'✅ تمت عملية السحب بنجاح!\n\n'
            f'👤 اسم المستخدم: {name}\n'
            f'━━━━━━━━━━━━━━━\n'
            f'💵 مبلغ السحب: {amount:,.0f} SYP\n'
            f'📉 رسوم السحب (10% أرباح): {fee:,.0f} SYP\n'
            f'💰 الصافي للمستخدم: {net_amount:,.0f} SYP\n'
            f'💼 رصيد الكاشير الجديد: {new_cashier:,.0f} SYP',
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
        bot.register_next_step_handler(
            msg, process_withdrawal_calculation, user_id
        )


# --- عمليات الشحن (تم إصلاح الخطأ البرمجي هنا) ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_recharge')
def recharge_users_list(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    conn = get_db_connection()
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
        '💳 قسم شحن رصيد المستخدمين\nاختر المستخدم المراد شحن رصيده:',
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
        '💵 أدخل مبلغ الشحن (بالـ SYP):\n*(كل 1,000 SYP تعطي نقطة ولاء واحدة تلقائياً)*\n*(مثال: 50.000)*',
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
        earned_points = int(amount // 1000)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            'UPDATE settings SET cashier_balance = cashier_balance - ? WHERE id = 1',
            (amount,),
        )
        cursor.execute(
            'UPDATE users SET balance = balance + ?, loyalty_points = loyalty_points + ? WHERE id = ?',
            (amount, earned_points, user_id),
        )
        # تصحيح جملة SQL للإدخال بنجاح
        cursor.execute(
            'INSERT INTO recharges (user_id, amount, points_earned) VALUES (?, ?, ?)',
            (user_id, amount, earned_points),
        )

        cursor.execute(
            'SELECT name, balance, loyalty_points FROM users WHERE id = ?',
            (user_id,),
        )
        user = cursor.fetchone()

        cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
        new_cashier = cursor.fetchone()[0]

        conn.commit()
        conn.close()

        if user:
            name, balance, total_points = user
            bot.send_message(
                message.chat.id,
                f'✅ تم شحن رصيد المستخدم بنجاح!\n\n'
                f'👤 المستخدم: {name}\n'
                f'⭐ نقاط الولاء: {total_points} نقطة (+{earned_points})\n'
                f'━━━━━━━━━━━━━━━\n'
                f'💵 المبلغ المضاف: {amount:,.0f} SYP\n'
                f'💼 رصيد المستخدم الجديد: {balance:,.0f} SYP\n'
                f'📉 رصيد الكاشير المتبقي: {new_cashier:,.0f} SYP',
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
    except Exception as e:
        bot.send_message(
            message.chat.id,
            f'⚠️ حدث خطأ في النظام: {e}',
            parse_mode='Markdown',
        )
        send_main_menu(message.chat.id)


# --- نقاط الولاء ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_loyalty')
def loyalty_menu(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            '🔄 استبدال نقاط الولاء', callback_data='loyalty_redeem_list'
        ),
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        ),
    )

    text = (
        '🎁 **قسم نقاط الولاء**\n'
        '━━━━━━━━━━━━━━━\n'
        'يمكنك هنا استبدال نقاط الولاء المجمعة لدى المستخدمين برصيد مباشر داخل البوت.\n\n'
        'اضغط على زر الاستبدال للبدء:'
    )
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )


@bot.callback_query_handler(
    func=lambda call: call.data == 'loyalty_redeem_list'
)
def loyalty_redeem_users_list(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, loyalty_points FROM users')
    users = cursor.fetchall()
    conn.close()

    markup = types.InlineKeyboardMarkup()
    if not users:
        markup.add(
            types.InlineKeyboardButton(
                '🔙 رجوع', callback_data='menu_loyalty'
            )
        )
        bot.edit_message_text(
            '⚠️ لا يوجد مستخدمين مسجلين للاستبدال.',
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='Markdown',
        )
        return

    for user in users:
        pts = user[2] or 0
        markup.add(
            types.InlineKeyboardButton(
                f'👤 {user[1]} ({pts} نقطة)',
                callback_data=f'redeemuser_{user[0]}',
            )
        )

    markup.add(
        types.InlineKeyboardButton('🔙 رجوع', callback_data='menu_loyalty')
    )
    bot.edit_message_text(
        '🔄 **اختر المستخدم لاستبدال نقاطه:**',
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('redeemuser_')
)
def loyalty_redeem_tiers_prompt(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    user_id = call.data.split('_')[1]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT name, loyalty_points, balance FROM users WHERE id = ?',
        (user_id,),
    )
    user = cursor.fetchone()
    conn.close()

    if not user:
        bot.answer_callback_query(call.id, 'المستخدم غير موجود.')
        send_main_menu(call.message.chat.id)
        return

    name, points, balance = user
    points = points or 0

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            '🎁 200 نقطة ⬅️ 10,000 SYP',
            callback_data=f'dotier_{user_id}_200_10000',
        ),
        types.InlineKeyboardButton(
            '🎁 300 نقطة ⬅️ 18,000 SYP',
            callback_data=f'dotier_{user_id}_300_18000',
        ),
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة', callback_data='loyalty_redeem_list'
        ),
    )

    text = (
        f'🔄 **استبدال نقاط الولاء للمستخدم:** `{name}`\n'
        f'⭐ **النقاط الحالية:** {points} نقطة\n'
        f'💼 **الرصيد الحالي:** {balance:,.0f} SYP\n'
        f'━━━━━━━━━━━━━━━\n'
        f'اختر فئة الاستبدال المطلوبة:'
    )

    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('dotier_'))
def process_loyalty_redemption(call):
    parts = call.data.split('_')
    user_id = parts[1]
    required_points = int(parts[2])
    reward_amount = float(parts[3])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT name, loyalty_points, balance FROM users WHERE id = ?',
        (user_id,),
    )
    user = cursor.fetchone()

    if not user:
        conn.close()
        bot.answer_callback_query(call.id, 'المستخدم غير موجود.')
        return

    name, current_points, current_balance = user
    current_points = current_points or 0

    if current_points < required_points:
        conn.close()
        bot.answer_callback_query(
            call.id,
            f'⚠️ رصيد النقاط غير كافٍ! (المتوفر: {current_points} نقطة)',
            show_alert=True,
        )
        return

    new_points = current_points - required_points
    new_balance = current_balance + reward_amount

    cursor.execute(
        'UPDATE users SET loyalty_points = ?, balance = ? WHERE id = ?',
        (new_points, new_balance, user_id),
    )

    cursor.execute(
        'UPDATE settings SET cashier_balance = cashier_balance - ? WHERE id = 1',
        (reward_amount,),
    )

    conn.commit()

    cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
    new_cashier = cursor.fetchone()[0]

    conn.close()

    bot.answer_callback_query(call.id, '✅ تم استبدال النقاط بنجاح!')
    bot.send_message(
        call.message.chat.id,
        f'✅ **تمت عملية استبدال النقاط بنجاح!**\n\n'
        f'👤 **المستخدم:** {name}\n'
        f'📉 **النقاط المخصومة:** {required_points} نقطة\n'
        f'⭐ **النقاط المتبقية:** {new_points} نقطة\n'
        f'━━━━━━━━━━━━━━━\n'
        f'🎁 **المكافأة المضافة للمستخدم:** +{reward_amount:,.0f} SYP\n'
        f'💼 **رصيد المستخدم الجديد:** {new_balance:,.0f} SYP\n'
        f'📉 **رصيد الكاشير المتبقي:** {new_cashier:,.0f} SYP',
        parse_mode='Markdown',
    )
    send_main_menu(call.message.chat.id)


# --- الديون وتسديدها ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_debt')
def debt_users_list(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    conn = get_db_connection()
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
        '📝 تسجيل دين على المستخدم\nاختر المستخدم:',
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
        '💵 أدخل مبلغ الدين (بالـ SYP):\n*(ملاحظة: سيتم تنقيصه من رصيد الكاشير)*',
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
        conn = get_db_connection()
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
                f'✅ تم تسجيل الدين بنجاح!\n\n👤 المستخدم: {user[0]}\n💵 مبلغ الدين: {amount:,.0f} SYP\n📊 إجمالي الدين الجديد: {user[1]:,.0f} SYP\n💼 رصيد الكاشير الجديد: {new_cashier:,.0f} SYP',
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


@bot.callback_query_handler(func=lambda call: call.data == 'menu_repay_debt')
def repay_debt_users_list(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    conn = get_db_connection()
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
        '💵 تسديد الدين\nاختر المستخدم لتسديد دينه:',
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('repayuser_')
)
def repay_options_prompt(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    user_id = call.data.split('_')[1]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT name, debt FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        bot.answer_callback_query(call.id, 'المستخدم غير موجود')
        send_main_menu(call.message.chat.id)
        return

    name, debt = user

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            f'✅ تسديد كامل المبلغ ({debt:,.0f} SYP)',
            callback_data=f'fullrepay_{user_id}',
        ),
        types.InlineKeyboardButton(
            '🟡 تسديد جزئي', callback_data=f'partialrepay_{user_id}'
        ),
        types.InlineKeyboardButton('🔙 رجوع', callback_data='menu_repay_debt'),
    )

    bot.edit_message_text(
        f'💵 تسديد الدين للمستخدم: {name}\n'
        f'📝 إجمالي الدين الحالي: {debt:,.0f} SYP\n\n'
        f'اختر طريقة التسديد المطلوبة:',
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('fullrepay_')
)
def process_full_repay(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    user_id = call.data.split('_')[1]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT name, debt FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()

    if not user or user[1] <= 0:
        conn.close()
        bot.answer_callback_query(call.id, 'لا يوجد دين مستحق لهذا المستخدم.')
        send_main_menu(call.message.chat.id)
        return

    name, debt = user

    cursor.execute('UPDATE users SET debt = 0 WHERE id = ?', (user_id,))
    cursor.execute(
        'UPDATE settings SET cashier_balance = cashier_balance + ? WHERE id = 1',
        (debt,),
    )

    conn.commit()
    cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
    new_cashier = cursor.fetchone()[0]
    conn.close()

    bot.answer_callback_query(call.id, 'تم تسديد كامل المبلغ بنجاح!')
    bot.send_message(
        call.message.chat.id,
        f'✅ تم تسديد كامل الدين بنجاح!\n\n'
        f'👤 المستخدم: {name}\n'
        f'💵 المبلغ المسدد: {debt:,.0f} SYP\n'
        f'📊 الدين المتبقي: 0 SYP\n'
        f'💼 رصيد الكاشير الجديد: {new_cashier:,.0f} SYP',
        parse_mode='Markdown',
    )
    send_main_menu(call.message.chat.id)


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('partialrepay_')
)
def partial_repay_prompt(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    user_id = call.data.split('_')[1]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT name, debt FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        bot.answer_callback_query(call.id, 'المستخدم غير موجود')
        send_main_menu(call.message.chat.id)
        return

    name, debt = user

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع', callback_data=f'repayuser_{user_id}'
        )
    )

    msg = bot.send_message(
        call.message.chat.id,
        f'💵 تسديد جزئي للمستخدم: {name}\n'
        f'📝 الدين الحالي: {debt:,.0f} SYP\n\n'
        f'أدخل مبلغ التسديد الجزئي (بالـ SYP):',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, process_partial_repay_save, user_id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass


def process_partial_repay_save(message, user_id):
    if check_cancel_command(message):
        return
    try:
        amount = float(message.text.replace('.', '').replace(',', ''))
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT name, debt FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        if not user:
            conn.close()
            bot.send_message(
                message.chat.id, '⚠️ المستخدم غير موجود.', parse_mode='Markdown'
            )
            send_main_menu(message.chat.id)
            return

        name, current_debt = user

        if amount > current_debt:
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton(
                    '🔙 رجوع', callback_data=f'repayuser_{user_id}'
                )
            )
            msg = bot.send_message(
                message.chat.id,
                f'⚠️ المبلغ المدخل ({amount:,.0f}) أكبر من الدين الحالي ({current_debt:,.0f})!\nأدخل مبلغاً صحيحاً:',
                reply_markup=markup,
                parse_mode='Markdown',
            )
            bot.register_next_step_handler(
                msg, process_partial_repay_save, user_id
            )
            conn.close()
            return

        cursor.execute(
            'UPDATE users SET debt = debt - ? WHERE id = ?', (amount, user_id)
        )
        cursor.execute(
            'UPDATE settings SET cashier_balance = cashier_balance + ? WHERE id = 1',
            (amount,),
        )

        conn.commit()
        cursor.execute('SELECT debt FROM users WHERE id = ?', (user_id,))
        remaining_debt = cursor.fetchone()[0]

        cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
        new_cashier = cursor.fetchone()[0]
        conn.close()

        bot.send_message(
            message.chat.id,
            f'✅ تم تسديد الجزء بنجاح!\n\n'
            f'👤 المستخدم: {name}\n'
            f'💵 المبلغ المسدد: {amount:,.0f} SYP\n'
            f'📊 الدين المتبقي: {remaining_debt:,.0f} SYP\n'
            f'💼 رصيد الكاشير الجديد: {new_cashier:,.0f} SYP',
            parse_mode='Markdown',
        )
        send_main_menu(message.chat.id)
    except ValueError:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                '🔙 رجوع', callback_data=f'repayuser_{user_id}'
            )
        )
        msg = bot.send_message(
            message.chat.id,
            '⚠️ يرجى إدخال رقم صحيح للمبلغ. أعد المحاولة:',
            reply_markup=markup,
            parse_mode='Markdown',
        )
        bot.register_next_step_handler(
            msg, process_partial_repay_save, user_id
        )


# --- كشف حساب ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_statement')
def statement_users_list(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    conn = get_db_connection()
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
                '📊 ' + user[1], callback_data=f'statuser_{user[0]}'
            )
        )
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )

    bot.edit_message_text(
        '📊 كشف حساب المستخدمين\nاختر المستخدم لعرض تفاصيله:',
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('statuser_'))
def show_user_statement(call):
    user_id = call.data.split('_')[1]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        'SELECT name, debt, loyalty_points FROM users WHERE id = ?', (user_id,)
    )
    user = cursor.fetchone()

    cursor.execute(
        'SELECT SUM(amount) FROM recharges WHERE user_id = ?', (user_id,)
    )
    total_recharge = cursor.fetchone()[0] or 0.0

    cursor.execute(
        'SELECT SUM(net_amount) FROM withdrawals WHERE user_id = ?', (user_id,)
    )
    total_withdrawal = cursor.fetchone()[0] or 0.0

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
        name, debt, loyalty_points = user
        text = (
            f'📊 كشف حساب المستخدم: {name}\n'
            f'⭐ نقاط الولاء: {loyalty_points or 0} نقطة\n'
            f'━━━━━━━━━━━━━━━\n'
            f'💳 شحن: {total_recharge:,.0f} SYP\n'
            f'💸 سحب: {total_withdrawal:,.0f} SYP'
        )

        if debt > 0:
            text += f'\n📝 إجمالي الديون: {debt:,.0f} SYP'

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


# --- البنود المخصصة ---
@bot.callback_query_handler(func=lambda call: call.data == 'menu_custom_items')
def custom_items_menu(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, title, effect_type FROM custom_items')
    items = cursor.fetchall()
    conn.close()

    markup = types.InlineKeyboardMarkup(row_width=2)
    if items:
        for item in items:
            icon = '➕' if item[2] == 'add' else '➖'
            markup.add(
                types.InlineKeyboardButton(
                    f'{icon} {item[1]}', callback_data=f'exec_custom_{item[0]}'
                )
            )

    markup.add(
        types.InlineKeyboardButton(
            '➕ إضافة بند جديد', callback_data='add_custom_item'
        ),
        types.InlineKeyboardButton(
            '❌ حذف بند مخصص', callback_data='del_custom_item_list'
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للقائمة الرئيسية', callback_data='back_to_main'
        )
    )

    text = (
        '⚙️️ **قسم البنود المخصصة**\n'
        '━━━━━━━━━━━━━━━\n'
        'اختر بنداً مخصصاً لتسجيل عملية، أو قم بإنشاء بند جديد وتحديد تأثيره (زيادة أو خصم من الكاشير):'
    )
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown',
    )


@bot.callback_query_handler(func=lambda call: call.data == 'add_custom_item')
def add_custom_item_start(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للبنود المخصصة', callback_data='menu_custom_items'
        )
    )
    msg = bot.send_message(
        call.message.chat.id,
        '⚙️ **إضافة بند جديد**\nأدخل اسم البند (مثال: *عمولة إضافية*، *مكافآت*):',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(msg, process_custom_item_title)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass


def process_custom_item_title(message):
    if check_cancel_command(message):
        return
    title = message.text.strip()
    if not title:
        bot.send_message(message.chat.id, '⚠️ الاسم غير صالح. أعد المحاولة.')
        send_main_menu(message.chat.id)
        return

    temp_custom_items[message.chat.id] = title

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            '➕ يزيد من رصيد الكاشير (+)', callback_data='set_effect_add'
        ),
        types.InlineKeyboardButton(
            '➖ ينقص من رصيد الكاشير (-)', callback_data='set_effect_deduct'
        ),
        types.InlineKeyboardButton(
            '🔙 إلغاء', callback_data='menu_custom_items'
        ),
    )
    bot.send_message(
        message.chat.id,
        f'📌 البند المراد إضافته: *{title}*\nحدد تأثير هذا البند على رصيد الكاشير عند تنفيذه:',
        reply_markup=markup,
        parse_mode='Markdown',
    )


@bot.callback_query_handler(
    func=lambda call: call.data in ['set_effect_add', 'set_effect_deduct']
)
def save_custom_item_effect(call):
    chat_id = call.message.chat.id
    title = temp_custom_items.get(chat_id)

    if not title:
        bot.answer_callback_query(call.id, 'حدث خطأ، يرجى إعادة المحاولة.')
        send_main_menu(chat_id)
        return

    effect = 'add' if call.data == 'set_effect_add' else 'deduct'

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO custom_items (title, effect_type) VALUES (?, ?)',
            (title, effect),
        )
        conn.commit()
        bot.answer_callback_query(call.id, 'تمت إضافة البند بنجاح!')
        effect_str = 'زيادة (+)' if effect == 'add' else 'خصم (-)'
        bot.send_message(
            chat_id,
            f'✅ تم إنشاء البند المخصص: *{title}*\nالتأثير على الكاشير: *{effect_str}*',
            parse_mode='Markdown',
        )
    except sqlite3.IntegrityError:
        bot.send_message(
            chat_id, '⚠ هذا البند موجود مسبقاً!', parse_mode='Markdown'
        )
    finally:
        conn.close()
        temp_custom_items.pop(chat_id, None)

    send_main_menu(chat_id)


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('exec_custom_')
)
def exec_custom_item_prompt(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    item_id = call.data.split('_')[2]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, title, effect_type FROM custom_items WHERE id = ?',
        (item_id,),
    )
    item = cursor.fetchone()
    conn.close()

    if not item:
        bot.answer_callback_query(call.id, 'البند غير موجود.')
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للبنود', callback_data='menu_custom_items'
        )
    )

    effect_text = 'يزيد الكاشير (+)' if item[2] == 'add' else 'ينقص الكاشير (-)'
    msg = bot.send_message(
        call.message.chat.id,
        f'📌 تنفيذ عملية: *{item[1]}*\n(تأثير البند: {effect_text})\n\nأدخل المبلغ المراد تسجيله (بالـ SYP):\n*(مثال: 15.000)*',
        reply_markup=markup,
        parse_mode='Markdown',
    )
    bot.register_next_step_handler(
        msg, process_custom_trans_amount, item[0], item[1], item[2]
    )
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass


def process_custom_trans_amount(message, item_id, item_title, effect_type):
    if check_cancel_command(message):
        return
    try:
        amount = float(message.text.replace('.', '').replace(',', ''))
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                '🔙 إلغاء', callback_data='menu_custom_items'
            )
        )

        msg = bot.send_message(
            message.chat.id,
            f'💵 المبلغ المدخل: {amount:,.0f} SYP\n\n📝 أدخل سبب/وصف أو ملاحظة للعملية:',
            reply_markup=markup,
            parse_mode='Markdown',
        )
        bot.register_next_step_handler(
            msg,
            process_custom_trans_save,
            item_id,
            item_title,
            effect_type,
            amount,
        )
    except ValueError:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                '🔙 رجوع', callback_data='menu_custom_items'
            )
        )
        msg = bot.send_message(
            message.chat.id,
            '⚠️ يرجى إدخال رقم صحيح للمبلغ. أعد المحاولة:',
            reply_markup=markup,
            parse_mode='Markdown',
        )
        bot.register_next_step_handler(
            msg, process_custom_trans_amount, item_id, item_title, effect_type
        )


def process_custom_trans_save(
    message, item_id, item_title, effect_type, amount
):
    if check_cancel_command(message):
        return
    notes = message.text.strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    if effect_type == 'add':
        cursor.execute(
            'UPDATE settings SET cashier_balance = cashier_balance + ? WHERE id = 1',
            (amount,),
        )
    else:
        cursor.execute(
            'UPDATE settings SET cashier_balance = cashier_balance - ? WHERE id = 1',
            (amount,),
        )

    cursor.execute(
        'INSERT INTO custom_transactions (item_id, amount, notes) VALUES (?, ?, ?)',
        (item_id, amount, notes),
    )
    conn.commit()

    cursor.execute('SELECT cashier_balance FROM settings WHERE id = 1')
    new_cashier = cursor.fetchone()[0]
    conn.close()

    effect_symbol = '➕' if effect_type == 'add' else '➖'
    bot.send_message(
        message.chat.id,
        f'✅ تم تسجيل العملية بنجاح!\n\n'
        f'📌 البند: *{item_title}*\n'
        f'📝 الوصف / ملاحظات: {notes}\n'
        f'💵 المبلغ: {effect_symbol} {amount:,.0f} SYP\n'
        f'💼 رصيد الكاشير الجديد: {new_cashier:,.0f} SYP',
        parse_mode='Markdown',
    )
    send_main_menu(message.chat.id)


@bot.callback_query_handler(
    func=lambda call: call.data == 'del_custom_item_list'
)
def del_custom_item_list(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, title FROM custom_items')
    items = cursor.fetchall()
    conn.close()

    markup = types.InlineKeyboardMarkup()
    if not items:
        markup.add(
            types.InlineKeyboardButton(
                '🔙 رجوع للبنود', callback_data='menu_custom_items'
            )
        )
        bot.edit_message_text(
            '⚠️ لا يوجد بنود مخصصة مسجلة للحذف.',
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='Markdown',
        )
        return

    for item in items:
        markup.add(
            types.InlineKeyboardButton(
                f'❌ {item[1]}', callback_data=f'delcustom_{item[0]}'
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            '🔙 رجوع للبنود المخصصة', callback_data='menu_custom_items'
        )
    )
    bot.edit_message_text(
        'اختر البند المخصص المراد حذفه نهائياً:',
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('delcustom_'))
def del_custom_item_confirm(call):
    item_id = call.data.split('_')[1]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT title FROM custom_items WHERE id = ?', (item_id,))
    item = cursor.fetchone()

    if item:
        title = item[0]
        cursor.execute('DELETE FROM custom_items WHERE id = ?', (item_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, f'تم حذف البند {title}')
        bot.send_message(
            call.message.chat.id,
            f'🗑️ تم حذف البند المخصص *{title}* بنجاح.',
            parse_mode='Markdown',
        )
    else:
        conn.close()

    send_main_menu(call.message.chat.id)


print('Bot running with fixed recharge logic and daily PDF features...')
bot.infinity_polling()
# force redeploy
