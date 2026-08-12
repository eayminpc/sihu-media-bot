import os
import re
import asyncio
import tempfile
import logging
import shutil
from urllib.parse import urlparse

import yt_dlp

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.constants import ChatAction

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = "8743030512:AAHX-OTu9NSjtLpGRfybgrLBQP7bpW6spoI"

PORT = int(os.getenv("PORT", "10000"))

RENDER_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")

WEBHOOK_SECRET = os.getenv(
    "WEBHOOK_SECRET",
    "sihu-media-webhook"
)

MAX_FILE_SIZE = 49 * 1024 * 1024

DOWNLOAD_LIMIT = 2

download_semaphore = None


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("sihu-media-bot")


# =========================================================
# SUPPORTED DOMAINS
# =========================================================

SUPPORTED_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "tiktok.com",
    "vm.tiktok.com",
    "instagram.com",
    "facebook.com",
    "fb.watch",
    "twitter.com",
    "x.com",
)


# =========================================================
# URL FUNCTIONS
# =========================================================

def is_supported_url(url: str) -> bool:
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        host = parsed.netloc.lower().split(":")[0]

        return any(
            host == domain or host.endswith("." + domain)
            for domain in SUPPORTED_DOMAINS
        )

    except Exception:
        return False


def clean_url(url: str) -> str:
    return url.strip().rstrip(").,]}>") 


# =========================================================
# START COMMAND
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = (
        "🎬 *Sihu Media Bot*\n\n"
        "YouTube • TikTok • Facebook • Instagram • X\n\n"
        "📥 Send me a video link and choose:\n"
        "🎥 Video\n"
        "🎵 Audio\n\n"
        "⚡ Fast & Simple"
    )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
    )


# =========================================================
# HELP COMMAND
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = (
        "📖 *How to use Sihu Media Bot*\n\n"
        "1️⃣ Copy a video link\n"
        "2️⃣ Send it here\n"
        "3️⃣ Choose Video or Audio\n\n"
        "Supported:\n"
        "• YouTube\n"
        "• TikTok\n"
        "• Facebook\n"
        "• Instagram\n"
        "• X / Twitter"
    )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
    )


# =========================================================
# HANDLE MESSAGE
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    match = re.search(
        r"https?://[^\s]+",
        text,
        re.IGNORECASE,
    )

    if not match:
        await update.message.reply_text(
            "❌ Please send a valid video link."
        )
        return

    url = clean_url(match.group(0))

    if not is_supported_url(url):
        await update.message.reply_text(
            "❌ Unsupported link.\n\n"
            "Please send a YouTube, TikTok, "
            "Facebook, Instagram or X/Twitter link."
        )
        return

    context.user_data["download_url"] = url

    keyboard = [
        [
            InlineKeyboardButton(
                "🎥 Video",
                callback_data="download_video",
            ),
            InlineKeyboardButton(
                "🎵 Audio",
                callback_data="download_audio",
            ),
        ]
    ]

    await update.message.reply_text(
        "✅ Link detected!\n\n"
        "Choose download type:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# CALLBACK
# =========================================================

async def button_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    url = context.user_data.get("download_url")

    if not url:
        await query.message.reply_text(
            "❌ Link expired. Please send the link again."
        )
        return

    if query.data == "download_video":
        await download_media(
            update,
            context,
            url,
            "video",
        )

    elif query.data == "download_audio":
        await download_media(
            update,
            context,
            url,
            "audio",
        )


# =========================================================
# YT-DLP OPTIONS
# =========================================================

def get_ytdlp_options():
    return {
        "quiet": True,
        "no_warnings": True,

        "noplaylist": True,

        "retries": 5,
        "fragment_retries": 5,

        "socket_timeout": 30,

        "continuedl": True,

        "nocheckcertificate": True,

        "ignoreerrors": False,

        "overwrites": True,

        "geo_bypass": True,

        "concurrent_fragment_downloads": 1,

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/138.0.0.0 "
                "Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    }


# =========================================================
# DOWNLOAD WITH YT-DLP
# =========================================================

def download_with_ytdlp(
    url,
    mode,
    output_dir,
):
    output_template = os.path.join(
        output_dir,
        "%(title).80s.%(ext)s",
    )

    common = get_ytdlp_options()

    common["outtmpl"] = output_template

    if mode == "video":

        common["format"] = (
            "bestvideo[height<=720]+bestaudio/"
            "best[height<=720]/"
            "best"
        )

        common["merge_output_format"] = "mp4"

    else:

        common["format"] = (
            "bestaudio[ext=m4a]/"
            "bestaudio[ext=mp3]/"
            "bestaudio"
        )

    with yt_dlp.YoutubeDL(common) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        if not info:
            raise RuntimeError(
                "Unable to extract media information."
            )

        files = []

        requested = info.get(
            "requested_downloads"
        )

        if requested:

            for item in requested:

                filepath = item.get(
                    "filepath"
                )

                if filepath and os.path.isfile(filepath):
                    files.append(filepath)

        if not files:

            for filename in os.listdir(output_dir):

                filepath = os.path.join(
                    output_dir,
                    filename,
                )

                if os.path.isfile(filepath):
                    files.append(filepath)

        if not files:
            raise RuntimeError(
                "Downloaded file was not found."
            )

        files.sort(
            key=lambda x: os.path.getsize(x),
            reverse=True,
        )

        return files[0]


# =========================================================
# DOWNLOAD MEDIA
# =========================================================

async def download_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    mode: str,
):
    global download_semaphore

    query = update.callback_query

    message = query.message

    status = await message.reply_text(
        "⏳ Starting download..."
    )

    temp_dir = tempfile.mkdtemp(
        prefix="sihu_media_"
    )

    try:

        if download_semaphore is None:
            download_semaphore = asyncio.Semaphore(
                DOWNLOAD_LIMIT
            )

        async with download_semaphore:

            await status.edit_text(
                "⬇️ Downloading...\n\n"
                "Please wait."
            )

            filepath = await asyncio.wait_for(
                asyncio.to_thread(
                    download_with_ytdlp,
                    url,
                    mode,
                    temp_dir,
                ),
                timeout=300,
            )

        if not filepath or not os.path.isfile(filepath):
            raise RuntimeError(
                "Download file was not found."
            )

        file_size = os.path.getsize(filepath)

        if file_size > MAX_FILE_SIZE:

            await status.edit_text(
                "❌ File is too large for Telegram.\n\n"
                "Maximum supported size is about 49 MB.\n\n"
                "Please choose a lower quality or shorter video."
            )

            return

        await status.edit_text(
            "📤 Uploading..."
        )

        filename = os.path.basename(filepath)

        if mode == "video":

            await message.chat.send_action(
                ChatAction.UPLOAD_VIDEO
            )

            try:

                with open(
                    filepath,
                    "rb",
                ) as video_file:

                    await message.reply_video(
                        video=video_file,
                        filename=filename,
                        supports_streaming=True,
                        read_timeout=180,
                        write_timeout=180,
                        connect_timeout=30,
                        pool_timeout=30,
                    )

            except Exception:

                logger.exception(
                    "Video upload failed. Using document fallback."
                )

                with open(
                    filepath,
                    "rb",
                ) as document_file:

                    await message.reply_document(
                        document=document_file,
                        filename=filename,
                        read_timeout=180,
                        write_timeout=180,
                        connect_timeout=30,
                        pool_timeout=30,
                    )

        else:

            await message.chat.send_action(
                ChatAction.UPLOAD_DOCUMENT
            )

            with open(
                filepath,
                "rb",
            ) as audio_file:

                await message.reply_document(
                    document=audio_file,
                    filename=filename,
                    read_timeout=180,
                    write_timeout=180,
                    connect_timeout=30,
                    pool_timeout=30,
                )

        try:
            await status.delete()
        except Exception:
            pass

    except asyncio.TimeoutError:

        logger.error(
            "Download timed out."
        )

        try:
            await status.edit_text(
                "❌ Download timed out.\n\n"
                "Please try again."
            )
        except Exception:
            pass

    except Exception as error:

        logger.exception(
            "Download failed: %s",
            error,
        )

        error_text = str(error).lower()

        if (
            "sign in to confirm" in error_text
            or "not a bot" in error_text
            or "confirm you're not a bot" in error_text
        ):

            reply = (
                "❌ YouTube blocked this request.\n\n"
                "YouTube is asking for bot verification.\n\n"
                "Please try another video later."
            )

        else:

            reply = (
                "❌ Download failed.\n\n"
                "Please check the link and try again."
            )

        try:
            await status.edit_text(
                reply
            )
        except Exception:
            pass

    finally:

        try:
            shutil.rmtree(
                temp_dir,
                ignore_errors=True,
            )
        except Exception:
            pass


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "Unhandled Telegram error: %s",
        context.error,
        exc_info=True,
    )


# =========================================================
# BUILD APPLICATION
# =========================================================

def build_application():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_callback,
            pattern=r"^download_(video|audio)$",
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    application.add_error_handler(
        error_handler
    )

    return application


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is not configured."
        )

    if RENDER_HOSTNAME:

        application = build_application()

        webhook_url = (
            f"https://{RENDER_HOSTNAME}/"
            f"{WEBHOOK_SECRET}"
        )

        logger.info(
            "Starting Sihu Media Bot with Render webhook..."
        )

        logger.info(
            "Render host: %s",
            RENDER_HOSTNAME,
        )

        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_SECRET,
            webhook_url=webhook_url,
            drop_pending_updates=False,
            allowed_updates=Update.ALL_TYPES,
        )

    else:

        application = build_application()

        logger.info(
            "Starting Sihu Media Bot with polling..."
        )

        application.run_polling(
            drop_pending_updates=False,
            allowed_updates=Update.ALL_TYPES,
        )


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":
    main()