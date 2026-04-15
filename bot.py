import os
import logging
from datetime import datetime, date
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)
from supabase import create_client, Client

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Ruxsat etilgan Telegram ID lar ────────────────────────────────────────────
# .env da ALLOWED_IDS=123456789,987654321 ko'rinishida kiriting
ALLOWED_IDS = set(
    int(i.strip())
    for i in os.environ.get("ALLOWED_IDS", "").split(",")
    if i.strip()
)

def is_allowed(user_id: int) -> bool:
    return not ALLOWED_IDS or user_id in ALLOWED_IDS

# ── Conversation states ───────────────────────────────────────────────────────
XARAJAT_TURI, XARAJAT_SUMMA, XARAJAT_IZOH = range(3)

# ── Klaviatura ────────────────────────────────────────────────────────────────
def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("💸 Xarajat qo'shish")],
            [KeyboardButton("📊 Bugungi hisobot"), KeyboardButton("📋 Holat")],
        ],
        resize_keyboard=True,
    )

# ── Yordamchi: raqamni formatlash ─────────────────────────────────────────────
def fmt(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ") + " so'm"
    except Exception:
        return str(n)

# ─────────────────────────────────────────────────────────────────────────────
#  KOMANDALAR
# ─────────────────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text("⛔ Sizga ruxsat berilmagan.")
        return

    await update.message.reply_text(
        f"Salom, {user.first_name}! 👷\n"
        "Fortigen loyiha boti xizmatda.\n\n"
        "Quyidagi tugmalardan foydalaning:",
        reply_markup=main_keyboard(),
    )


async def holat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Loyihaning umumiy moliyaviy holati"""
    if not is_allowed(update.effective_user.id):
        return

    try:
        # Jami xarajatlar
        res = supabase.table("xarajatlar").select("summa").execute()
        jami_xarajat = sum(r["summa"] for r in res.data if r.get("summa"))

        # Bugungi xarajat
        bugun = date.today().isoformat()
        res2 = (
            supabase.table("xarajatlar")
            .select("summa")
            .eq("sana", bugun)
            .execute()
        )
        bugungi = sum(r["summa"] for r in res2.data if r.get("summa"))

        # Brigada soni
        res3 = supabase.table("brigadalar").select("id").execute()
        brigada_soni = len(res3.data)

        text = (
            "📊 *Loyiha holati*\n"
            "─────────────────\n"
            f"💰 Jami xarajat: *{fmt(jami_xarajat)}*\n"
            f"📅 Bugungi xarajat: *{fmt(bugungi)}*\n"
            f"👷 Faol brigadalar: *{brigada_soni} ta*\n"
            f"🕐 Yangilangan: {datetime.now().strftime('%H:%M')}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"holat xatosi: {e}")
        await update.message.reply_text("❌ Ma'lumot olishda xato yuz berdi.")


async def bugungi_hisobot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Bugungi barcha xarajatlar ro'yxati"""
    if not is_allowed(update.effective_user.id):
        return

    try:
        bugun = date.today().isoformat()
        res = (
            supabase.table("xarajatlar")
            .select("turi, summa, izoh, yaratilgan_vaqt")
            .eq("sana", bugun)
            .order("yaratilgan_vaqt", desc=True)
            .execute()
        )

        if not res.data:
            await update.message.reply_text(
                f"📋 Bugun ({bugun}) hech qanday xarajat kiritilmagan."
            )
            return

        jami = sum(r["summa"] for r in res.data if r.get("summa"))
        lines = [f"📋 *{bugun} — Bugungi xarajatlar*\n"]

        for i, r in enumerate(res.data, 1):
            izoh = f" — {r['izoh']}" if r.get("izoh") else ""
            vaqt = r.get("yaratilgan_vaqt", "")[:16].replace("T", " ") if r.get("yaratilgan_vaqt") else ""
            lines.append(f"{i}. {r.get('turi','—')} | *{fmt(r['summa'])}*{izoh} `{vaqt}`")

        lines.append(f"\n💰 *Jami: {fmt(jami)}*")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"hisobot xatosi: {e}")
        await update.message.reply_text("❌ Hisobot olishda xato.")


# ─────────────────────────────────────────────────────────────────────────────
#  XARAJAT QO'SHISH — ConversationHandler
# ─────────────────────────────────────────────────────────────────────────────

async def xarajat_boshlash(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return ConversationHandler.END

    try:
        res = supabase.table("xarajat_turlari").select("nomi").execute()
        turlar = [r["nomi"] for r in res.data if r.get("nomi")]
    except Exception:
        turlar = []

    if not turlar:
        turlar = ["Material", "Transport", "Mehnat haqi", "Boshqa"]

    # Har qatorda 2 ta tugma
    keyboard = [[turlar[i], turlar[i+1]] if i+1 < len(turlar) else [turlar[i]]
                for i in range(0, len(turlar), 2)]
    keyboard.append(["❌ Bekor qilish"])

    ctx.user_data["xarajat"] = {}
    await update.message.reply_text(
        "💸 *Xarajat turi?*\nTanlang yoki yozing:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )
    return XARAJAT_TURI


async def xarajat_turi_olindi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Bekor qilish":
        await update.message.reply_text("Bekor qilindi.", reply_markup=main_keyboard())
        return ConversationHandler.END

    ctx.user_data["xarajat"]["turi"] = text
    await update.message.reply_text(
        f"✅ Tur: *{text}*\n\n💰 Summani kiriting (so'mda):\nMasalan: `500000`",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True),
    )
    return XARAJAT_SUMMA


async def xarajat_summa_olindi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "❌ Bekor qilish":
        await update.message.reply_text("Bekor qilindi.", reply_markup=main_keyboard())
        return ConversationHandler.END

    # Raqam tekshirish
    summa_str = text.replace(" ", "").replace(",", "")
    try:
        summa = int(summa_str)
        if summa <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri summa. Faqat raqam kiriting:")
        return XARAJAT_SUMMA

    ctx.user_data["xarajat"]["summa"] = summa
    await update.message.reply_text(
        f"✅ Summa: *{fmt(summa)}*\n\n📝 Izoh kiriting (ixtiyoriy):\n"
        "Yoki o'tkazib yuborish uchun — kiriting",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [["— (izohsiz)"], ["❌ Bekor qilish"]], resize_keyboard=True
        ),
    )
    return XARAJAT_IZOH


async def xarajat_saqlash(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Bekor qilish":
        await update.message.reply_text("Bekor qilindi.", reply_markup=main_keyboard())
        return ConversationHandler.END

    izoh = "" if text == "— (izohsiz)" else text
    xarajat = ctx.user_data.get("xarajat", {})

    try:
        user = update.effective_user
        # Telegam user nomini topish
        brigadir_nomi = user.full_name or user.username or str(user.id)

        supabase.table("xarajatlar").insert({
            "turi": xarajat["turi"],
            "summa": xarajat["summa"],
            "izoh": izoh,
            "sana": date.today().isoformat(),
            "brigadir": brigadir_nomi,
            "telegram_id": str(user.id),
            "yaratilgan_vaqt": datetime.utcnow().isoformat(),
        }).execute()

        await update.message.reply_text(
            f"✅ *Xarajat saqlandi!*\n\n"
            f"📌 Tur: {xarajat['turi']}\n"
            f"💰 Summa: *{fmt(xarajat['summa'])}*\n"
            f"📝 Izoh: {izoh or '—'}\n"
            f"👷 Brigadir: {brigadir_nomi}",
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )
    except Exception as e:
        logger.error(f"saqlash xatosi: {e}")
        await update.message.reply_text(
            "❌ Saqlashda xato yuz berdi. Qayta urinib ko'ring.",
            reply_markup=main_keyboard(),
        )

    return ConversationHandler.END


async def bekor_qilish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Bekor qilindi.", reply_markup=main_keyboard())
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
#  MATN TUGMALARI
# ─────────────────────────────────────────────────────────────────────────────

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📊 Bugungi hisobot":
        await bugungi_hisobot(update, ctx)
    elif text == "📋 Holat":
        await holat(update, ctx)
    else:
        await update.message.reply_text(
            "Tugmalardan foydalaning 👇", reply_markup=main_keyboard()
        )


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    token = os.environ["BOT_TOKEN"]
    app = Application.builder().token(token).build()

    # Xarajat conversation
    xarajat_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^💸 Xarajat qo'shish$"), xarajat_boshlash),
            CommandHandler("xarajat", xarajat_boshlash),
        ],
        states={
            XARAJAT_TURI:  [MessageHandler(filters.TEXT & ~filters.COMMAND, xarajat_turi_olindi)],
            XARAJAT_SUMMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, xarajat_summa_olindi)],
            XARAJAT_IZOH:  [MessageHandler(filters.TEXT & ~filters.COMMAND, xarajat_saqlash)],
        },
        fallbacks=[CommandHandler("bekor", bekor_qilish)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("holat", holat))
    app.add_handler(CommandHandler("hisobot", bugungi_hisobot))
    app.add_handler(xarajat_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Bot ishga tushdi ✅")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
