import logging
import os
import tempfile
from threading import Thread

from dotenv import load_dotenv
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from news_fetcher import fetch_latest_items, get_image_and_source, download_image
from rewriter import rewrite_caption
from buffer_publisher import publish_to_instagram
from image_host import upload_image

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID = os.environ["ADMIN_CHAT_ID"]
RSS_FEED_URLS = [u.strip() for u in os.environ["RSS_FEED_URLS"].split(",") if u.strip()]
AI_API_KEY = os.environ["AI_API_KEY"]
AI_API_URL = os.environ["AI_API_URL"]
AI_MODEL = os.environ["AI_MODEL"]
BUFFER_API_KEY = os.environ["BUFFER_API_KEY"]
BUFFER_CHANNEL_ID = os.environ["BUFFER_CHANNEL_ID"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_ITEMS_TO_CHECK = 8
MAX_POSTS_TO_SEND = 3
TELEGRAM_CAPTION_LIMIT = 1024

pending_posts: dict[str, dict] = {}

web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is active!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

def _trim_caption(caption: str, source_block: str) -> str:
    max_caption_len = TELEGRAM_CAPTION_LIMIT - len(source_block) - 5
    if len(caption) > max_caption_len:
        caption = caption[:max_caption_len].rstrip() + "…"
    return caption

async def send_preview(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    image_path: str,
    image_url: str,
    caption_body: str,
    source_block: str,
    source_link: str,
) -> None:
    full_caption_preview = caption_body + source_block
    with open(image_path, "rb") as photo:
        sent_message = await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=full_caption_preview,
        )

    post_id = str(sent_message.message_id)
    pending_posts[post_id] = {
        "image_path": image_path,
        "image_url": image_url,
        "caption_body": caption_body,
        "source_block": source_block,
        "source_link": source_link,
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📌 با منبع", callback_data=f"approve_src:{post_id}"),
            InlineKeyboardButton("🚫 بدون منبع", callback_data=f"approve_nosrc:{post_id}"),
        ],
        [InlineKeyboardButton("❌ لغو", callback_data=f"reject:{post_id}")],
    ])
    await context.bot.edit_message_reply_markup(
        chat_id=chat_id, message_id=sent_message.message_id, reply_markup=keyboard
    )

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("در حال گرفتن و بررسی اخبار...")

    items = fetch_latest_items(RSS_FEED_URLS, limit=MAX_ITEMS_TO_CHECK)
    if not items:
        await update.message.reply_text("خبری پیدا نشد.")
        return

    sent_count = 0
    failed_count = 0
    error_details = []

    for item in items:
        if sent_count >= MAX_POSTS_TO_SEND:
            break

        try:
            img_info = get_image_and_source(item)

            caption = rewrite_caption(
                title=item["title"],
                summary=item["summary"],
                api_key=AI_API_KEY,
                api_url=AI_API_URL,
                model=AI_MODEL,
            )

            source_block = (
                f"\n\nمنبع عکس: {img_info['site_name']}\n"
                f"منبع خبر: {item['link']}"
            )
            caption_body = _trim_caption(caption, source_block)

            tmp_path = os.path.join(
                tempfile.gettempdir(), f"news_image_{sent_count}.jpg"
            )
            download_image(img_info["image_url"], tmp_path)

            await send_preview(
                context, chat_id, tmp_path, img_info["image_url"],
                caption_body, source_block, item["link"],
            )
            sent_count += 1

        except Exception as e:
            logger.warning(f"رد شدن از خبر '{item.get('title')}' به‌خاطر خطا: {e}")
            failed_count += 1
            error_details.append(f"«{item['title'][:40]}»: {e}")
            continue

    if sent_count == 0:
        summary = (
            f"هیچ خبری با موفقیت آماده نشد (از {len(items)} خبر بررسی‌شده، "
            f"{failed_count} تاش خطا داشت یا عکس نداشت).\n\nجزئیات خطاها:\n"
        )
    else:
        summary = (
            f"{sent_count} خبر آماده شد ({failed_count} تا رد شدن به‌خاطر خطا یا نبود عکس).\n\n"
            f"جزئیات خبرهای رد‌شده:\n"
        )

    details_text = "\n".join(error_details[:10])
    await update.message.reply_text(summary + details_text)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, post_id = query.data.split(":", 1)
    post = pending_posts.get(post_id)

    if not post:
        await query.edit_message_caption(caption="این پیشنهاد دیگه معتبر نیست.")
        return

    preview_caption = post["caption_body"] + post["source_block"]

    if action in ("approve_src", "approve_nosrc"):
        include_source = action == "approve_src"
        final_caption = (
            post["caption_body"] + post["source_block"]
            if include_source
            else post["caption_body"]
        )

        await query.edit_message_caption(
            caption=preview_caption + "\n\n⏳ در حال ارسال به بافر برای انتشار در اینستاگرام..."
        )
        try:
            result = publish_to_instagram(
                caption=final_caption,
                image_url=post["image_url"],
                channel_id=BUFFER_CHANNEL_ID,
                api_key=BUFFER_API_KEY,
            )
            logger.info(f"پست با موفقیت تو بافر ساخته شد: {result}")
            note = "با منبع" if include_source else "بدون منبع"
            await query.edit_message_caption(
                caption=preview_caption
                + f"\n\n✅ تایید شد ({note}) و برای انتشار در اینستاگرام به بافر فرستاده شد"
            )
        except Exception as e:
            logger.warning(f"ارسال پست به بافر با خطا مواجه شد: {e}")
            await query.edit_message_caption(
                caption=preview_caption + f"\n\n⚠️ تایید شد ولی ارسال به بافر خطا داد:\n{e}"
            )
    else:
        await query.edit_message_caption(caption=preview_caption + "\n\n❌ لغو شد")

    pending_posts.pop(post_id, None)

async def handle_reply_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_to = update.message.reply_to_message
    if not reply_to:
        return

    ref_id = str(reply_to.message_id)
    post = pending_posts.get(ref_id)
    if not post:
        await update.message.reply_text("این پیش‌نمایش دیگه معتبر نیست (یا قبلاً تایید/رد شده).")
        return

    chat_id = update.effective_chat.id

    photo_file = await update.message.photo[-1].get_file()
    tmp_path = os.path.join(
        tempfile.gettempdir(), f"news_image_reply_{update.message.message_id}.jpg"
    )
    await photo_file.download_to_drive(tmp_path)

    try:
        new_image_url = upload_image(tmp_path)
    except Exception as e:
        logger.warning(f"آپلود عکس جایگزین به هاست عمومی خطا داد: {e}")
        await update.message.reply_text(f"آپلود عکس با خطا مواجه شد:\n{e}")
        return

    if update.message.caption:
        source_block = f"\n\nمنبع خبر: {post['source_link']}"
        new_caption_body = _trim_caption(update.message.caption, source_block)
    else:
        new_caption_body = post["caption_body"]
        source_block = post["source_block"]

    await send_preview(
        context, chat_id, tmp_path, new_image_url, new_caption_body, source_block, post["source_link"]
    )
    pending_posts.pop(ref_id, None)

async def handle_reply_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_to = update.message.reply_to_message
    if not reply_to:
        return

    ref_id = str(reply_to.message_id)
    post = pending_posts.get(ref_id)
    if not post:
        await update.message.reply_text("این پیش‌نمایش دیگه معتبر نیست (یا قبلاً تایید/رد شده).")
        return

    chat_id = update.effective_chat.id

    source_block = f"\n\nمنبع خبر: {post['source_link']}"
    new_caption_body = _trim_caption(update.message.text, source_block)

    await send_preview(
        context, chat_id, post["image_path"], post["image_url"],
        new_caption_body, source_block, post["source_link"],
    )
    pending_posts.pop(ref_id, None)

def main():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.REPLY & filters.PHOTO, handle_reply_photo))
    app.add_handler(
        MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, handle_reply_text)
    )
    logger.info("بات روشن شد...")
    app.run_polling()

if __name__ == "__main__":
    main()
