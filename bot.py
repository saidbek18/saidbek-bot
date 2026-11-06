# -*- coding: utf-8 -*-
"""SAIDBEK DIGITAL Telegram boti (pyTelegramBotAPI + SQLite, webhook/polling)."""
import os, json, time, sqlite3
from html import escape
import telebot
from telebot import types
from flask import Flask, request, abort

# ====== SOZLAMALAR ======
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise SystemExit("BOT_TOKEN o'rnatilmagan! Environment variable sifatida kiriting.")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CONTACT = "@kamolovsaidbek"
PORTFOLIO = "Namunalar tez orada qo'shiladi. Hozircha " + CONTACT + " ga yozing."

# Majburiy obuna kanallari. Bot har bir kanalda ADMIN bo'lishi shart!
CHANNELS = [
    ("@saikokamalov", "https://t.me/saikokamalov"),
]
# =========================

DB = os.getenv("DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.db")
bot = telebot.TeleBot(TOKEN, parse_mode="HTML", threaded=False)

SERVICES = {
    "edu": ("📚 Ta'lim", ["PowerPoint prezentatsiya", "Ochiq dars va seminar slaydlari",
                          "Dars ishlanmalari", "Testlar va tarqatma materiallar"]),
    "des": ("🎨 Dizayn", ["Logo va bannerlar", "Sertifikat va tashakkurnomalar",
                          "Diplom va faxriy yorliqlar", "Reklama postlari",
                          "YouTube va Telegram dizaynlari"]),
    "pc": ("💻 Kompyuter", ["Word va Excel hujjatlari", "PDF bilan ishlash",
                            "CV va rezyume", "Hisobot va jadvallar"]),
    "it": ("🤖 IT", ["Telegram bot", "Buyurtma qabul qiluvchi bot", "Test boti",
                     "Oddiy veb-sayt"]),
    "vid": ("🎬 Video", ["Video montaj", "Reels va Shorts", "Intro va reklama roliklari",
                         "Subtitr va effektlar"]),
}
STATUS = {"new": "🆕 Yangi", "acc": "✅ Qabul qilindi", "prog": "🔄 Jarayonda",
          "done": "🏁 Tayyor", "rej": "❌ Rad etildi", "cnc": "🚫 Bekor qilindi"}
FAQ = [
    ("💳 To'lov qanday?", "Oldindan to'lov asosida ishlaymiz. Rekvizitlar buyurtma kelishilgach yuboriladi."),
    ("⏱ Muddat qancha?", "Muddat ish hajmiga qarab har bir buyurtma uchun alohida kelishiladi."),
    ("📦 Ish qanday topshiriladi?", "Tayyor ish elektron shaklda, Telegram orqali yuboriladi."),
    ("💰 Narx qancha?", "Narx har bir buyurtma uchun alohida kelishiladi."),
]
CANCEL = "❌ Bekor qilish"
DONE = "✅ Tayyor"
SKIP = "⏭ O'tkazib yuborish"
_me = {}


# ---------- Ma'lumotlar bazasi ----------
def q(sql, args=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.execute(sql, args)
    res = cur.fetchall() if sql.lstrip().upper().startswith("SELECT") else cur.lastrowid
    con.commit()
    con.close()
    return res


q("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, username TEXT, "
  "state TEXT, data TEXT, joined INTEGER, ref INTEGER)")
q("CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, "
  "service TEXT, name TEXT, phone TEXT, details TEXT, deadline TEXT, status TEXT, created INTEGER)")
try:  # eski bazada 'ref' ustuni bo'lmasa qo'shamiz
    q("ALTER TABLE users ADD COLUMN ref INTEGER")
except sqlite3.OperationalError:
    pass


def save_user(m):
    """Yangi foydalanuvchi bo'lsa True qaytaradi."""
    u = m.from_user
    if q("SELECT id FROM users WHERE id=?", (u.id,)):
        return False
    q("INSERT INTO users(id,name,username,state,data,joined) VALUES(?,?,?,?,?,?)",
      (u.id, u.full_name, u.username or "", None, "{}", int(time.time())))
    return True


def get_state(uid):
    r = q("SELECT state,data FROM users WHERE id=?", (uid,))
    if not r:
        return None, {}
    return r[0]["state"], json.loads(r[0]["data"] or "{}")


def set_state(uid, state, data=None):
    q("UPDATE users SET state=?, data=? WHERE id=?", (state, json.dumps(data or {}), uid))


def notify_admin(text, kb=None):
    if ADMIN_ID:
        try:
            bot.send_message(ADMIN_ID, text, reply_markup=kb)
        except Exception:
            pass


def bot_username():
    if "u" not in _me:
        _me["u"] = bot.get_me().username
    return _me["u"]


# ---------- Majburiy obuna ----------
def not_subscribed(uid):
    bad = []
    for ch, url in CHANNELS:
        try:
            st = bot.get_chat_member(ch, uid).status
            if st not in ("member", "administrator", "creator"):
                bad.append((ch, url))
        except Exception:
            pass  # bot kanalda admin bo'lmasa tekshirib bo'lmaydi, o'tkazib yuboramiz
    return bad


def blocked(uid):
    """Obuna bo'lmagan bo'lsa, xabar yuboradi va True qaytaradi."""
    if uid == ADMIN_ID or not CHANNELS:
        return False
    bad = not_subscribed(uid)
    if not bad:
        return False
    kb = types.InlineKeyboardMarkup(row_width=1)
    for ch, url in bad:
        kb.add(types.InlineKeyboardButton("📢 " + str(ch), url=url))
    kb.add(types.InlineKeyboardButton("✅ Tekshirish", callback_data="chk"))
    bot.send_message(uid, "⚠️ Botdan foydalanish uchun avval quyidagi kanallarga obuna bo'ling, "
                          "keyin <b>«Tekshirish»</b> tugmasini bosing 👇", reply_markup=kb)
    return True


# ---------- Klaviaturalar ----------
def menu_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("🛍 Xizmatlar", "📝 Buyurtma berish", "💰 Narxlar", "🖼 Namunalar",
           "📦 Buyurtmalarim", "🎁 Do'stlarni taklif qilish", "⭐ Fikr bildirish",
           "❓ Savol-javob", "📞 Aloqa")
    return kb


def cancel_kb(extra=None, contact=False):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if contact:
        kb.add(types.KeyboardButton("📱 Raqamni yuborish", request_contact=True))
    if extra:
        kb.add(extra)
    kb.add(CANCEL)
    return kb


def cats_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    for key, (title, _) in SERVICES.items():
        kb.add(types.InlineKeyboardButton(title, callback_data="cat:" + key))
    return kb


def svc_kb(key):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for i, s in enumerate(SERVICES[key][1]):
        kb.add(types.InlineKeyboardButton(s, callback_data=f"ord:{key}:{i}"))
    kb.add(types.InlineKeyboardButton("↩️ Orqaga", callback_data="cats"))
    return kb


def admin_order_kb(oid, uid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(*[types.InlineKeyboardButton(STATUS[s], callback_data=f"st:{oid}:{s}")
             for s in ("acc", "prog", "done", "rej")])
    kb.add(types.InlineKeyboardButton("💬 Mijozga javob", callback_data=f"reply:{uid}"))
    return kb


# ---------- /start ----------
def send_welcome(user, chat_id):
    bot.send_message(
        chat_id,
        f"👋 Salom, <b>{escape(user.first_name or 'do‘st')}</b>!\n\n"
        "🚀 <b>SAIDBEK DIGITAL</b> — barcha raqamli xizmatlar bir joyda!\n"
        "Sifatli, zamonaviy va chiroyli dizayndagi ishlarni kelishilgan muddatda tayyorlaymiz.\n\n"
        "Quyidagi menyudan tanlang 👇", reply_markup=menu_kb())


@bot.message_handler(commands=["start", "menu"])
def cmd_start(m):
    uid = m.from_user.id
    new = save_user(m)
    parts = (m.text or "").split()
    if new and len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            ref = int(parts[1][4:])
        except ValueError:
            ref = 0
        if ref and ref != uid and q("SELECT id FROM users WHERE id=?", (ref,)):
            q("UPDATE users SET ref=? WHERE id=?", (ref, uid))
            try:
                bot.send_message(ref, "🎉 Sizning havolangiz orqali yangi foydalanuvchi qo'shildi!")
            except Exception:
                pass
    set_state(uid, None)
    if blocked(uid):
        return
    send_welcome(m.from_user, m.chat.id)


@bot.message_handler(commands=["admin"])
def cmd_admin(m):
    if m.from_user.id != ADMIN_ID:
        return
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("📊 Statistika", callback_data="adm:stats"),
           types.InlineKeyboardButton("📋 Oxirgi buyurtmalar", callback_data="adm:orders"),
           types.InlineKeyboardButton("📢 Hammaga xabar yuborish", callback_data="adm:bc"))
    bot.send_message(m.chat.id, "🛠 <b>Admin panel</b>", reply_markup=kb)


# ---------- Buyurtma ----------
def finish_order(uid, d):
    oid = q("INSERT INTO orders(user_id,service,name,phone,details,deadline,status,created) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (uid, d["service"], d["name"], d["phone"], d["details"], d["deadline"], "new", int(time.time())))
    set_state(uid, None)
    bot.send_message(uid, f"✅ Buyurtmangiz qabul qilindi! Raqami: <b>#{oid}</b>\n"
                          f"Tez orada siz bilan bog'lanamiz.", reply_markup=menu_kb())
    notify_admin(f"🆕 <b>Yangi buyurtma #{oid}</b>\n"
                 f"Xizmat: {escape(d['service'])}\nIsm: {escape(d['name'])}\nTel: {escape(d['phone'])}\n"
                 f"Muddat: {escape(d['deadline'])}\nIzoh: {escape(d['details'] or '-')}",
                 admin_order_kb(oid, uid))
    if ADMIN_ID:
        for mid in d.get("msgs", []):
            try:
                bot.copy_message(ADMIN_ID, uid, mid)
            except Exception:
                pass


def handle_state(m, state, d):
    uid, text = m.from_user.id, (m.text or "").strip()
    if state == "o_name":
        d["name"] = text
        set_state(uid, "o_phone", d)
        bot.send_message(uid, "📱 Telefon raqamingiz? (tugma orqali yoki yozib yuboring)",
                         reply_markup=cancel_kb(contact=True))
    elif state == "o_phone":
        d["phone"] = m.contact.phone_number if m.contact else text
        set_state(uid, "o_details", d)
        bot.send_message(uid, "📝 Buyurtma haqida batafsil yozing, kerak bo'lsa rasm/fayl yuboring.\n"
                              "Tugagach <b>✅ Tayyor</b> tugmasini bosing.", reply_markup=cancel_kb(DONE))
    elif state == "o_details":
        if text == DONE:
            if not d["details"] and not d["msgs"]:
                return bot.send_message(uid, "Iltimos, avval ma'lumot yoki fayl yuboring.")
            set_state(uid, "o_deadline", d)
            return bot.send_message(uid, "⏱ Qachongacha tayyor bo'lishi kerak?", reply_markup=cancel_kb())
        if m.text:
            d["details"] += text + "\n"
        else:
            d["msgs"].append(m.message_id)
        set_state(uid, "o_details", d)
        bot.send_message(uid, "Qabul qilindi. Yana yuborishingiz yoki ✅ Tayyor bosishingiz mumkin.")
    elif state == "o_deadline":
        d["deadline"] = text or "-"
        finish_order(uid, d)
    elif state == "ask":
        set_state(uid, None)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💬 Javob yozish", callback_data=f"reply:{uid}"))
        notify_admin(f"❓ <b>Savol</b> — {escape(m.from_user.full_name)} "
                     f"(@{m.from_user.username or '-'}, ID {uid})", kb)
        if ADMIN_ID:
            bot.copy_message(ADMIN_ID, uid, m.message_id)
        bot.send_message(uid, "✅ Xabaringiz yuborildi. Javobni shu yerda olasiz.", reply_markup=menu_kb())
    elif state == "fb":
        set_state(uid, None)
        comment = "" if text == SKIP else (text or "[fayl]")
        notify_admin(f"⭐ <b>Fikr: {d.get('r', '?')}/5</b> — {escape(m.from_user.full_name)} "
                     f"(@{m.from_user.username or '-'})\n{escape(comment)}")
        bot.send_message(uid, "🙏 Fikringiz uchun rahmat!", reply_markup=menu_kb())
    elif state == "bc" and uid == ADMIN_ID:
        set_state(uid, None)
        ok = 0
        for r in q("SELECT id FROM users"):
            try:
                bot.copy_message(r["id"], uid, m.message_id)
                ok += 1
                time.sleep(0.05)
            except Exception:
                pass
        bot.send_message(uid, f"📢 {ok} ta foydalanuvchiga yuborildi.", reply_markup=menu_kb())
    elif state.startswith("reply:") and uid == ADMIN_ID:
        target = int(state.split(":")[1])
        set_state(uid, None)
        try:
            bot.send_message(target, "💬 <b>SAIDBEK DIGITAL</b> javobi:")
            bot.copy_message(target, uid, m.message_id)
            bot.send_message(uid, "✅ Yuborildi.", reply_markup=menu_kb())
        except Exception as e:
            bot.send_message(uid, f"Xatolik: {e}")


# ================= AVTO-JAVOB (Telegram Business) =================
AUTO_TEXT = ("👋 Assalomu alaykum! Men Saidbekning <b>clone botiman</b>.\n"
             "Saidbek hozir band, imkon topishi bilan o'zi javob beradi.\n\n"
             "Nima uchun yozayotganingizni tanlang 👇")
NOTIFY_GAP = 600  # bir chatdan sizga bildirishnoma oralig'i (soniya)
REASONS = {
    "msg": ("✍️ Xabar qoldirish", "Xabaringizni shu yerga yozib qoldiring, Saidbekka yetkazaman ✍️"),
    "ord": ("🛍 Buyurtma berish", "Buyurtma haqida batafsil yozib qoldiring, Saidbek tez orada bog'lanadi 🛍"),
    "price": ("💰 Narx so'rash", "Qaysi xizmat narxi kerakligini yozib qoldiring 💰"),
    "ask": ("❓ Savol bor", "Savolingizni yozib qoldiring, Saidbek javob beradi ❓"),
    "urgent": ("🔥 Shoshilinch", "Shoshilinch deb belgilab yetkazdim. Qisqacha yozib qoldiring 🔥"),
}

q("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)")
q("CREATE TABLE IF NOT EXISTS greeted(chat_id INTEGER PRIMARY KEY)")
q("CREATE TABLE IF NOT EXISTS bchat(chat_id INTEGER PRIMARY KEY, conn TEXT, "
  "reason TEXT, last_notify INTEGER)")
q("CREATE TABLE IF NOT EXISTS bconn(id TEXT PRIMARY KEY, owner INTEGER, "
  "can_reply INTEGER, enabled INTEGER)")
_err_ts = {}  # xato xabarlari spam bo'lmasligi uchun


def auto_on():
    """Standart holatda YOQILGAN. Faqat /autooff yozsangiz o'chadi."""
    r = q("SELECT v FROM settings WHERE k='auto'")
    return not r or r[0]["v"] != "0"


def can_reply_of(c):
    """Kutubxona versiyasiga qarab 'javob berish' ruxsatini topadi."""
    rights = getattr(c, "rights", None)
    if rights is not None:
        return bool(getattr(rights, "can_reply", False))
    return bool(getattr(c, "can_reply", False))


def save_conn(c):
    q("INSERT OR REPLACE INTO bconn(id,owner,can_reply,enabled) VALUES(?,?,?,?)",
      (c.id, c.user.id, 1 if can_reply_of(c) else 0, 1 if getattr(c, "is_enabled", True) else 0))


def owners():
    s = {ADMIN_ID}
    for r in q("SELECT owner FROM bconn"):
        s.add(r["owner"])
    return s


def reasons_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(*[types.InlineKeyboardButton(v[0], callback_data="bz:" + k) for k, v in REASONS.items()])
    return kb


def user_btn(u):
    if u.username:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💬 Chatni ochish", url="https://t.me/" + u.username))
        return kb
    return None


def err_hint(e, conn):
    """Xatoga qarab, nima qilish kerakligini aytadi."""
    s = str(e)
    lines = [f"⚠️ Avto-javob yuborilmadi:\n<code>{escape(s)}</code>"]
    try:
        bc = bot.get_business_connection(conn)
        lines.append(f"Ulanish: egasi {bc.user.id}, faol: {getattr(bc, 'is_enabled', '?')}, "
                     f"javob berish ruxsati: <b>{can_reply_of(bc)}</b>")
        if not can_reply_of(bc):
            lines.append("👉 Telegram → Sozlamalar → Business → Chatbotlar → botni oching → "
                         "<b>«Xabarlarga javob berish»</b> ni yoqing.")
    except Exception as ex:
        lines.append(f"Ulanishni o'qib bo'lmadi: {escape(str(ex))}")
    if "PEER_INVALID" in s:
        lines.append("Ruxsat yoqilgan bo'lsa: bu odam Chatbotlar → «Istisnolar» ro'yxatida "
                     "turgan bo'lishi, yoki u 24 soat ichida yozmagan bo'lishi mumkin. "
                     "Botni uzib, qayta ulab ko'ring.")
    return "\n".join(lines)


@bot.message_handler(commands=["autoon", "autooff", "autoreset", "autostatus"])
def cmd_auto(m):
    if m.from_user.id != ADMIN_ID:
        return
    cmd = m.text.split()[0].split("@")[0]
    if cmd == "/autoreset":
        q("DELETE FROM greeted")
        q("DELETE FROM bchat")
        return bot.send_message(m.chat.id, "♻️ Hamma uchun salomlashish qayta boshlandi.")
    if cmd == "/autostatus":
        rows = q("SELECT * FROM bconn")
        txt = f"🤖 Avto-javob: <b>{'YOQILGAN' if auto_on() else 'O‘CHIQ'}</b>\n"
        if not rows:
            txt += ("\nHali hech qanday Business ulanishi ko'rinmadi.\n"
                    "Botni Telegram → Business → Chatbotlar'dan qayta ulang.")
        for r in rows:
            txt += (f"\nUlanish: egasi {r['owner']}, faol: {bool(r['enabled'])}, "
                    f"javob berish ruxsati: <b>{bool(r['can_reply'])}</b>")
        txt += f"\nSalomlashilgan chatlar: {len(q('SELECT 1 FROM greeted'))}"
        return bot.send_message(m.chat.id, txt)
    on = cmd == "/autoon"
    q("INSERT OR REPLACE INTO settings(k,v) VALUES('auto',?)", ("1" if on else "0",))
    bot.send_message(m.chat.id, "🤖 Avto-javob YOQILDI" if on else "⏸ Avto-javob O'CHIRILDI")


@bot.business_connection_handler(func=lambda c: True)
def on_bconn(c):
    save_conn(c)
    ok = can_reply_of(c)
    notify_admin(("✅ Business ulandi" if getattr(c, "is_enabled", True) else "⛔ Business uzildi")
                 + f"\nJavob berish ruxsati: <b>{ok}</b>"
                 + ("" if ok else "\n👉 Chatbotlar sozlamasida «Xabarlarga javob berish» ni yoqing."))


def send_greeting(cid, conn):
    """Salom yuboradi. Faqat muvaffaqiyatli bo'lsa True qaytaradi."""
    try:
        bot.send_message(cid, AUTO_TEXT, reply_markup=reasons_kb(), business_connection_id=conn)
        return True
    except Exception as e:
        first = e
    # Sozlama muammosi bo'lsa, tugmasiz qayta urinishning foydasi yo'q
    if "PEER_INVALID" not in str(first):
        try:
            bot.send_message(cid, AUTO_TEXT, business_connection_id=conn)
            return True
        except Exception:
            pass
    now = int(time.time())
    if now - _err_ts.get(cid, 0) > 3600:
        _err_ts[cid] = now
        notify_admin(err_hint(first, conn))
    print("SALOM XATO:", cid, first)
    return False


@bot.business_message_handler(content_types=["text", "photo", "document", "video", "voice",
                                             "audio", "sticker", "video_note"])
def on_business(m):
    u = m.from_user
    if u.is_bot or u.id in owners() or not auto_on():
        return
    cid, conn, now = m.chat.id, m.business_connection_id, int(time.time())

    row = q("SELECT * FROM bchat WHERE chat_id=?", (cid,))
    if not row:
        q("INSERT INTO bchat(chat_id,conn,reason,last_notify) VALUES(?,?,?,?)", (cid, conn, "", 0))
        row = q("SELECT * FROM bchat WHERE chat_id=?", (cid,))
    q("UPDATE bchat SET conn=? WHERE chat_id=?", (conn, cid))
    reason, last = row[0]["reason"], row[0]["last_notify"]

    # 1) salomlashish: har bir odamga faqat bir marta
    if not q("SELECT 1 FROM greeted WHERE chat_id=?", (cid,)):
        if send_greeting(cid, conn):
            q("INSERT OR IGNORE INTO greeted(chat_id) VALUES(?)", (cid,))

    # 2) sizga bildirishnoma: har chatdan 10 daqiqada bittadan
    if now - last >= NOTIFY_GAP:
        q("UPDATE bchat SET last_notify=? WHERE chat_id=?", (now, cid))
        body = (m.text or m.caption or "[fayl/media]")[:300]
        why = f"\nSabab: {REASONS[reason][0]}" if reason in REASONS else ""
        notify_admin(f"💬 <b>{escape(u.full_name)}</b> (@{u.username or '-'}, ID {u.id}) yozdi{why}\n"
                     f"{escape(body)}", user_btn(u))


@bot.callback_query_handler(func=lambda c: c.data.startswith("bz:"))
def on_reason(c):
    u, key = c.from_user, c.data[3:]
    if key not in REASONS:
        return bot.answer_callback_query(c.id)
    bot.answer_callback_query(c.id, "✅ Qabul qilindi")
    cid, now = u.id, int(time.time())
    row = q("SELECT conn FROM bchat WHERE chat_id=?", (cid,))
    conn = row[0]["conn"] if row else getattr(c.message, "business_connection_id", None)
    q("UPDATE bchat SET reason=?, last_notify=? WHERE chat_id=?", (key, now, cid))
    try:
        bot.send_message(cid, REASONS[key][1], business_connection_id=conn)
    except Exception as e:
        notify_admin(f"⚠️ Tugma javobi yuborilmadi: {escape(str(e))}")
    notify_admin(f"🔔 <b>{escape(u.full_name)}</b> (@{u.username or '-'}, ID {u.id}) tanladi: "
                 f"<b>{REASONS[key][0]}</b>", user_btn(u))


# ================= ODDIY BOT: MENYU VA TUGMALAR =================
# DIQQAT: bu handlerlar komandalardan KEYIN ro'yxatdan o'tishi kerak.
@bot.message_handler(content_types=["text", "photo", "document", "video", "voice",
                                    "audio", "contact", "sticker", "video_note"])
def on_any(m):
    uid = m.from_user.id
    save_user(m)
    if blocked(uid):
        return
    text = (m.text or "").strip()

    if text == CANCEL:
        set_state(uid, None)
        return bot.send_message(uid, "Bekor qilindi.", reply_markup=menu_kb())

    state, d = get_state(uid)
    if state:
        d.setdefault("details", "")
        d.setdefault("msgs", [])
        return handle_state(m, state, d)

    if text in ("🛍 Xizmatlar", "📝 Buyurtma berish"):
        bot.send_message(uid, "Xizmat turini tanlang 👇", reply_markup=cats_kb())
    elif text == "💰 Narxlar":
        bot.send_message(uid, "💰 Narx har bir buyurtma hajmiga qarab alohida kelishiladi.\n"
                              f"Aniq narx uchun buyurtma bering yoki {CONTACT} ga yozing.")
    elif text == "🖼 Namunalar":
        bot.send_message(uid, PORTFOLIO)
    elif text == "📦 Buyurtmalarim":
        rows = q("SELECT id,service,status FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
        if not rows:
            return bot.send_message(uid, "Hozircha buyurtmalaringiz yo'q.")
        lines = [f"#{r['id']} — {escape(r['service'])}\n    {STATUS.get(r['status'], r['status'])}"
                 for r in rows]
        bot.send_message(uid, "📦 <b>Buyurtmalaringiz:</b>\n\n" + "\n\n".join(lines))
    elif text == "🎁 Do'stlarni taklif qilish":
        link = f"https://t.me/{bot_username()}?start=ref_{uid}"
        n = len(q("SELECT id FROM users WHERE ref=?", (uid,)))
        bot.send_message(uid, f"🎁 Do'stlaringizni shu havola orqali taklif qiling:\n{link}\n\n"
                              f"Siz taklif qilganlar: <b>{n}</b> ta")
    elif text == "⭐ Fikr bildirish":
        kb = types.InlineKeyboardMarkup(row_width=5)
        kb.add(*[types.InlineKeyboardButton("⭐" * i, callback_data=f"rate:{i}") for i in range(1, 6)])
        bot.send_message(uid, "Xizmatimizni baholang:", reply_markup=kb)
    elif text == "❓ Savol-javob":
        kb = types.InlineKeyboardMarkup(row_width=1)
        for i, (qs, _) in enumerate(FAQ):
            kb.add(types.InlineKeyboardButton(qs, callback_data=f"faq:{i}"))
        kb.add(types.InlineKeyboardButton("✍️ Savol yozish", callback_data="askq"))
        bot.send_message(uid, "Ko'p beriladigan savollar 👇", reply_markup=kb)
    elif text == "📞 Aloqa":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✍️ Savol yozish", callback_data="askq"))
        bot.send_message(uid, f"📞 Aloqa: {CONTACT}", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: not c.data.startswith("bz:"))
def on_callback(c):
    uid, data = c.from_user.id, c.data
    chat, mid = c.message.chat.id, c.message.message_id

    if data == "chk":
        if blocked(uid):
            return bot.answer_callback_query(c.id, "Hali obuna bo'lmadingiz", show_alert=True)
        bot.answer_callback_query(c.id, "✅ Rahmat!")
        return send_welcome(c.from_user, chat)

    if data == "cats":
        bot.answer_callback_query(c.id)
        return bot.edit_message_text("Xizmat turini tanlang 👇", chat, mid, reply_markup=cats_kb())

    if data.startswith("cat:"):
        key = data[4:]
        if key not in SERVICES:
            return bot.answer_callback_query(c.id)
        bot.answer_callback_query(c.id)
        return bot.edit_message_text(f"{SERVICES[key][0]} — xizmatni tanlang 👇", chat, mid,
                                     reply_markup=svc_kb(key))

    if data.startswith("ord:"):
        _, key, i = data.split(":")
        try:
            title, items = SERVICES[key]
            service = f"{title} — {items[int(i)]}"
        except (KeyError, IndexError, ValueError):
            return bot.answer_callback_query(c.id)
        bot.answer_callback_query(c.id)
        set_state(uid, "o_name", {"service": service, "details": "", "msgs": []})
        return bot.send_message(uid, f"Tanlandi: <b>{escape(service)}</b>\n\n👤 Ismingiz?",
                                reply_markup=cancel_kb())

    if data.startswith("faq:"):
        try:
            qs, ans = FAQ[int(data[4:])]
        except (IndexError, ValueError):
            return bot.answer_callback_query(c.id)
        bot.answer_callback_query(c.id)
        return bot.send_message(uid, f"<b>{qs}</b>\n{ans}")

    if data == "askq":
        bot.answer_callback_query(c.id)
        set_state(uid, "ask", {})
        return bot.send_message(uid, "✍️ Savolingizni yozing (rasm/fayl ham bo'ladi):",
                                reply_markup=cancel_kb())

    if data.startswith("rate:"):
        bot.answer_callback_query(c.id)
        set_state(uid, "fb", {"r": data[5:]})
        return bot.send_message(uid, "Izoh yozing yoki o'tkazib yuboring:", reply_markup=cancel_kb(SKIP))

    # ---- Faqat admin uchun ----
    if uid != ADMIN_ID:
        return bot.answer_callback_query(c.id)

    if data.startswith("st:"):
        _, oid, s = data.split(":")
        row = q("SELECT user_id FROM orders WHERE id=?", (oid,))
        if not row or s not in STATUS:
            return bot.answer_callback_query(c.id, "Topilmadi")
        q("UPDATE orders SET status=? WHERE id=?", (s, oid))
        bot.answer_callback_query(c.id, STATUS[s])
        try:
            bot.send_message(row[0]["user_id"],
                             f"📦 Buyurtma <b>#{oid}</b> holati: <b>{STATUS[s]}</b>")
        except Exception:
            pass
        return

    if data.startswith("reply:"):
        bot.answer_callback_query(c.id)
        set_state(uid, data, {})
        return bot.send_message(uid, "✍️ Mijozga javobingizni yozing (rasm/fayl ham bo'ladi):",
                                reply_markup=cancel_kb())

    if data == "adm:stats":
        bot.answer_callback_query(c.id)
        users = len(q("SELECT id FROM users"))
        total = len(q("SELECT id FROM orders"))
        new = len(q("SELECT id FROM orders WHERE status='new'"))
        done = len(q("SELECT id FROM orders WHERE status='done'"))
        return bot.send_message(uid, f"📊 <b>Statistika</b>\n\n👥 Foydalanuvchilar: {users}\n"
                                     f"📦 Buyurtmalar: {total}\n🆕 Yangi: {new}\n🏁 Tayyor: {done}")

    if data == "adm:orders":
        bot.answer_callback_query(c.id)
        rows = q("SELECT id,service,name,status FROM orders ORDER BY id DESC LIMIT 10")
        if not rows:
            return bot.send_message(uid, "Buyurtmalar yo'q.")
        return bot.send_message(uid, "📋 <b>Oxirgi buyurtmalar:</b>\n\n" + "\n".join(
            f"#{r['id']} {STATUS.get(r['status'], '')} — {escape(r['name'] or '-')}, "
            f"{escape(r['service'])}" for r in rows))

    if data == "adm:bc":
        bot.answer_callback_query(c.id)
        set_state(uid, "bc", {})
        return bot.send_message(uid, "📢 Hammaga yuboriladigan xabarni yuboring:",
                                reply_markup=cancel_kb())


# ================= FLASK (webhook) =================
app = Flask(__name__)
SECRET = os.getenv("WEBHOOK_SECRET", "maxfiy123")  # faqat harf, raqam, _ va -
BASE_URL = os.getenv("RENDER_EXTERNAL_URL")  # Render o'zi beradi
ALLOWED = ["message", "callback_query", "business_connection", "business_message"]


@app.route("/")
@app.route("/health")
def health():
    return "ok", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET:
        abort(403)
    update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "", 200


if BASE_URL:  # Render'da: webhook
    bot.remove_webhook()
    bot.set_webhook(url=BASE_URL + "/webhook", secret_token=SECRET, allowed_updates=ALLOWED)

if __name__ == "__main__" and not BASE_URL:  # kompyuteringizda: polling
    bot.remove_webhook()
    bot.infinity_polling(allowed_updates=ALLOWED)