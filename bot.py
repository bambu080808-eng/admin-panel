import os
import random
import json
import asyncio
import requests
import google.generativeai as genai
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# ==================== API KALITLAR ====================
BOT_TOKEN = os.environ["BOT_TOKEN"]
IMGBB_API_KEY = os.environ["IMGBB_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Gemini sozlamalari
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash')

# Bot holatlari
IDLE_STATE, P1_STATE, P2_STATE, P3_STATE = range(4)

GEMINI_PROMPT = """Sana yuborilayotgan ushbu rasmlar e-commerce platformasi (Taobao/Pinduoduo/1688) uchun mahsulotning xarakteristikalari va tavsiflaridir.
Rasmlardagi barcha matnlarni, jadvallarni va ma'lumotlarni sinchkovlik bilan o'qib chiqib, quyidagi qat'iy qoidalar bo'yicha JSON formatida javob ber:

QOIDALAR:
1. TIL VA TARJIMA: Barcha matnlar, xususiyatlar, tavsif va sharhlar faqat va faqat sof, ravon va tushunarli O'zbek tilida bo'lishi shart. Inglizcha yoki xitoycha so'z va atamalardan foydalanma (masalan: "Printed" -> "Naqshli", "Slip-on" -> "Yengil kiyiladigan poyabzal", "Rubber" -> "Kauchuk/Rezina").
2. VARIANT VA O'LCHAMLAR: Variant rasmlari yoki skrinshotlarini sinchkovlik bilan tahlil qil. Faqat sotuvda bor (faol, to'q shriftli) rang va o'lchamlarni ajratib ol. Xira, tugmasi faolsizlashtirilgan yoki tugagan variantlarni BUTUNLAY CHIQARIB TASHLA.
3. KATALOG VA TYPE: 'catalog' va 'type' qiymatlarini faqat tasdiqlangan standart ro'yxat bo'yicha belgilang (Poyabzallar, Kiyim-kechak, Sumka va Aksessuarlar, Uy-ro'zg'or buyumlari, Maishiy texnika va h.k.).
4. SHARHLAR (REVIEWS): Rasmlardagi ma'lumotlar va mahsulot xususiyatidan kelib chiqib, xaridori juda xursand bo'lgan 6-8 ta har xil va tabiiy chiroyli O'zbekcha sharhlar (text) generatsiya qilib ber.

JAVOBNI QAT'IYAN QUYIDAGI JSON FORMATIDA QAYTAR (ORTIQCHA MATN YOZMA):

{
  "price": "20.71",
  "name": "Mahsulotning o'zbekcha nomi",
  "catalog": "Poyabzallar",
  "type": "Ayollar poyabzali",
  "description": "Mahsulot haqida batafsil va jozibador O'zbekcha tavsif...",
  "variants": {
    "Rang": ["Oq", "Moviy", "Xaki"],
    "Olcham": ["35", "36", "37", "38", "39", "40"]
  },
  "stats": {
    "rating": "4.9",
    "reviews": "7000",
    "views": "15000",
    "likes": "7669",
    "sold": "9436"
  },
  "extras": {
    "Brend": "KaiQi",
    "Ustki material": "PU teri",
    "Taglik materiali": "Kauchuk / Rezina",
    "Uslub": "Kundalik / Sport",
    "Poshta balandligi": "3cm-5cm",
    "Yopilish turi": "Bog'ichli (Ipli)"
  },
  "reviews_text": [
    "Oq krossovkalarni qabul qilib oldim va kiyib ko'rdim. O'lchami juda mos keldi, dizayni ajoyib!",
    "Poyabzal juda bejirim va oyoqqa juda mos keladi. Qalin tagligi sirpanishga qarshi yaxshi...",
    "Bu poyabzallar juda go'zal va kiyishga juda qulay. Ajoyib juftlik!",
    "Bu poyabzalni olib hayratda qoldim! Sifatli tikilgan, ortiqcha iplari yo'q.",
    "Juda qulay va zamonaviy, tavsiya qilaman!",
    "Toza, yangi va kiyishga qulay. Narxiga to'liq arziydi!"
  ],
  "instagram_caption": "💣 Ayollar uchun yangi va zamonaviy krossovkalar!..."
}
"""


# ==================== YORDAMCHI FUNKSIYALAR ====================

def upload_to_imgbb_sync(image_bytes):
    """Bloklovchi (sync) ImgBB yuklash funksiyasi — thread ichida chaqiriladi."""
    url = "https://api.imgbb.com/1/upload"
    payload = {"key": IMGBB_API_KEY}
    files = {"image": bytes(image_bytes)}
    try:
        response = requests.post(url, data=payload, files=files, timeout=30).json()
        if response.get("success"):
            return response["data"]["url"]
        print(f"ImgBB javobida xatolik: {response}")
    except Exception as e:
        print(f"ImgBB yuklashda xatolik: {e}")
    return None


async def upload_to_imgbb(image_bytes):
    """Botni bloklamaslik uchun alohida threadda ishga tushiriladi."""
    return await asyncio.to_thread(upload_to_imgbb_sync, image_bytes)


def call_gemini_sync(contents):
    """Bloklovchi (sync) Gemini chaqiruvi — thread ichida ishlaydi."""
    return gemini_model.generate_content(contents)


async def call_gemini(contents):
    return await asyncio.to_thread(call_gemini_sync, contents)


def build_html(data, p1_urls, p2_urls):
    images_html = "\n".join([f'    <img src="{url}">' for url in p1_urls])

    variants_html = ""
    if "variants" in data and isinstance(data["variants"], dict):
        for var_type, items in data["variants"].items():
            spans = "".join([f'<span>{item}</span>' for item in items])
            variants_html += f'  <div class="variant" data-type="{var_type}">\n    {spans}\n  </div>\n'

    stats = data.get("stats", {})
    stats_html = (
        f'  <div class="stats">\n'
        f'    <span data-key="rating">{stats.get("rating", "4.9")}</span>\n'
        f'    <span data-key="reviews">{stats.get("reviews", "100")}</span>\n'
        f'    <span data-key="views">{stats.get("views", "1000")}</span>\n'
        f'    <span data-key="likes">{stats.get("likes", "500")}</span>\n'
        f'    <span data-key="sold">{stats.get("sold", "200")}</span>\n'
        f'  </div>'
    )

    extras_html = ""
    if "extras" in data and isinstance(data["extras"], dict):
        for key, val in data["extras"].items():
            extras_html += f'  <div class="extra" data-key="{key}">{val}</div>\n'

    reviews_html = ""
    reviews_text = data.get("reviews_text", [])
    img_idx = 0
    total_review_imgs = len(p2_urls)

    for text in reviews_text:
        rand_id = random.randint(1000000000, 9999999999)
        review_item = f'  <div class="review">\n    <span class="author">ID: {rand_id}</span>\n    <span class="text">{text}</span>\n'

        if img_idx < total_review_imgs:
            take_count = random.randint(1, 3)
            attached_urls = p2_urls[img_idx: img_idx + take_count]
            img_idx += take_count

            if attached_urls:
                review_imgs = "\n".join([f'      <img src="{u}">' for u in attached_urls])
                review_item += f'    <div class="review-images">\n{review_imgs}\n    </div>\n'

        review_item += '  </div>\n'
        reviews_html += review_item

    full_html = f"""<div class="product">
  <div class="images">
{images_html}
  </div>
  <span class="price">{data.get("price", "0.00")}</span>
  <h2 class="name">{data.get("name", "Mahsulot nomi")}</h2>
{variants_html}  <p class="desc">{data.get("description", "")}</p>
  <span class="catalog">{data.get("catalog", "Poyabzallar")}</span>
  <span class="type">{data.get("type", "Ayollar poyabzali")}</span>
{stats_html}
{extras_html}
{reviews_html}</div>"""

    return full_html


def chunk_text(text, size=4000):
    """Uzun matnni Telegram limitiga (4096) mos bo'laklarga bo'ladi."""
    return [text[i:i + size] for i in range(0, len(text), size)]


# ==================== HANDLERLAR ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p1_urls"] = []
    context.user_data["p2_urls"] = []
    context.user_data["p3_bytes"] = []

    markup = ReplyKeyboardMarkup([["📸 1-Partiya (P1)"]], resize_keyboard=True)
    await update.message.reply_text(
        "Botga xush kelibsiz!\n\nBoshlash uchun <b>'📸 1-Partiya (P1)'</b> tugmasini bosing.",
        parse_mode="HTML",
        reply_markup=markup
    )
    return IDLE_STATE


async def go_to_p1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    markup = ReplyKeyboardMarkup([["💬 2-Partiya (P2)"]], resize_keyboard=True)
    await update.message.reply_text(
        "<b>1-PARTIYA (P1):</b> Mahsulotning asosiy galereya rasmlarini yuboring "
        "(albom ko'rinishida yoki bittalab yuborishingiz mumkin).\n\n"
        "Yuklab bo'lgach, <b>'💬 2-Partiya (P2)'</b> tugmasini bosing.",
        parse_mode="HTML",
        reply_markup=markup
    )
    return P1_STATE


async def handle_p1_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()

    url = await upload_to_imgbb(image_bytes)
    if url:
        context.user_data["p1_urls"].append(url)
        count = len(context.user_data["p1_urls"])
        print(f"P1 rasmi saqlandi: {count} ta")
        await update.message.reply_text(f"✅ P1: {count} ta rasm qabul qilindi.")
    else:
        await update.message.reply_text("⚠️ Rasmni yuklashda xatolik yuz berdi, qaytadan yuboring.")


async def go_to_p2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("p1_urls"):
        await update.message.reply_text("⚠️ Avval kamida bitta P1 rasmini yuboring.")
        return P1_STATE

    markup = ReplyKeyboardMarkup([["ℹ️ 3-Partiya (P3)"]], resize_keyboard=True)
    await update.message.reply_text(
        "<b>2-PARTIYA (P2):</b> P1 yopildi.\nEndi sharhlar (komentariyalar) uchun rasmlarni yuboring.\n\n"
        "Tugagach, <b>'ℹ️ 3-Partiya (P3)'</b> tugmasini bosing.",
        parse_mode="HTML",
        reply_markup=markup
    )
    return P2_STATE


async def handle_p2_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()

    url = await upload_to_imgbb(image_bytes)
    if url:
        context.user_data["p2_urls"].append(url)
        count = len(context.user_data["p2_urls"])
        print(f"P2 rasmi saqlandi: {count} ta")
        await update.message.reply_text(f"✅ P2: {count} ta rasm qabul qilindi.")
    else:
        await update.message.reply_text("⚠️ Rasmni yuklashda xatolik yuz berdi, qaytadan yuboring.")


async def go_to_p3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    markup = ReplyKeyboardMarkup([["✅ Kodni tayyorlash"]], resize_keyboard=True)
    await update.message.reply_text(
        "<b>3-PARTIYA (P3):</b> P2 yopildi.\nEndi mahsulot ma'lumotlari aks etgan (Info skrinshot) rasmlarni yuboring.\n\n"
        "Tugagach, <b>'✅ Kodni tayyorlash'</b> tugmasini bosing.",
        parse_mode="HTML",
        reply_markup=markup
    )
    return P3_STATE


async def handle_p3_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()

    context.user_data["p3_bytes"].append({"mime_type": "image/jpeg", "data": bytes(image_bytes)})
    count = len(context.user_data["p3_bytes"])
    print(f"P3 rasmi saqlandi: {count} ta")
    await update.message.reply_text(f"✅ P3: {count} ta rasm qabul qilindi.")


async def generate_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("p3_bytes"):
        await update.message.reply_text("⚠️ Avval kamida bitta P3 (info skrinshot) rasmini yuboring.")
        return P3_STATE

    await update.message.reply_text(
        "⏳ Tugmalar yopildi. AI rasmlarni tahlil qilmoqda va HTML kod tayyorlanmoqda, kuting...",
        reply_markup=ReplyKeyboardRemove()
    )

    try:
        contents = [GEMINI_PROMPT] + context.user_data["p3_bytes"]
        response = await call_gemini(contents)

        raw_text = response.text.strip()
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        data = json.loads(raw_text)

        html_code = build_html(data, context.user_data["p1_urls"], context.user_data["p2_urls"])

        output_path = f"product_card_{update.effective_user.id}.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_code)

        with open(output_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="product_card.html",
                caption="✅ Tayyor HTML kartochka kodi!"
            )

        # Xom HTML kodini matn ko'rinishida ham yuborish (kerak bo'lsa bo'laklab)
        for chunk in chunk_text(html_code, 4000):
            await update.message.reply_text(f"<code>{chunk}</code>", parse_mode="HTML")

        try:
            os.remove(output_path)
        except OSError:
            pass

    except json.JSONDecodeError as e:
        await update.message.reply_text(f"❌ AI javobini o'qishda xatolik (JSON noto'g'ri): {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik yuz berdi: {e}")

    # Botni boshidan boshlash uchun tugma
    markup = ReplyKeyboardMarkup([["📸 1-Partiya (P1)"]], resize_keyboard=True)
    context.user_data["p1_urls"] = []
    context.user_data["p2_urls"] = []
    context.user_data["p3_bytes"] = []
    await update.message.reply_text(
        "Yangi mahsulot qo'shish uchun <b>'📸 1-Partiya (P1)'</b> tugmasini bosing.",
        parse_mode="HTML",
        reply_markup=markup
    )

    return IDLE_STATE


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kutilmagan xabar turlariga (matn/hujjat va h.k.) javob berish."""
    await update.message.reply_text(
        "⚠️ Iltimos, joriy bosqichga mos rasm yuboring yoki menyudagi tugmalardan foydalaning."
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Jarayon bekor qilindi. Qaytadan boshlash uchun /start buyrug'ini yuboring.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# ==================== BOTNI ISHGA TUSHIRISH ====================

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            IDLE_STATE: [
                MessageHandler(filters.Regex("^📸 1-Partiya \\(P1\\)$"), go_to_p1),
            ],
            P1_STATE: [
                MessageHandler(filters.Regex("^💬 2-Partiya \\(P2\\)$"), go_to_p2),
                MessageHandler(filters.PHOTO, handle_p1_photo),
                MessageHandler(filters.ALL & ~filters.COMMAND, unknown_message),
            ],
            P2_STATE: [
                MessageHandler(filters.Regex("^ℹ️ 3-Partiya \\(P3\\)$"), go_to_p3),
                MessageHandler(filters.PHOTO, handle_p2_photo),
                MessageHandler(filters.ALL & ~filters.COMMAND, unknown_message),
            ],
            P3_STATE: [
                MessageHandler(filters.Regex("^✅ Kodni tayyorlash$"), generate_code),
                MessageHandler(filters.PHOTO, handle_p3_photo),
                MessageHandler(filters.ALL & ~filters.COMMAND, unknown_message),
            ],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)]
    )

    app.add_handler(conv_handler)
    print("Bot muvaffaqiyatli ishga tushdi...")
    app.run_polling()
