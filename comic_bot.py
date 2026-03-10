#!/usr/bin/env python3
"""
Telegram Bot for Comic Downloading and Booklet Conversion
"""
import io
import os
import tempfile
from typing import List

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import cloudscraper
from bs4 import BeautifulSoup as BS
from dotenv import load_dotenv
from PIL import Image

# Load environment variables from .env file
load_dotenv()

# Conversation states
URL = range(1)

scraper = cloudscraper.create_scraper()


def get_title_from_url(url: str) -> str:
    """Extract title from URL slug"""
    from urllib.parse import urlparse
    path = urlparse(url).path.strip('/')
    path = path.rstrip('/')
    parts = path.split('/')
    if parts:
        slug = parts[-1]
        # Convert slug to title: replace hyphens with spaces, capitalize each word
        title = ' '.join(word.capitalize() for word in slug.split('-'))
        return title if title else "comic"
    return "comic"


def get_comic_images(url: str) -> List[str]:
    """Extract image URLs from comic page"""
    base = scraper.get(url)
    soup = BS(base.content, "html.parser")
    pages = soup.select("center p img")
    urls = []

    for page in pages:
        source = page.get("src")
        if source:
            urls.append(source)

    return urls


def get_comic_chapters(url: str) -> List[dict]:
    """Extract all chapters from a category URL"""
    response = scraper.get(url)
    soup = BS(response.content, "html.parser")

    chapters = []
    chapters_element = soup.find(attrs={"class": "list-story"})

    if chapters_element:
        links = chapters_element.find_all("a")
        for link in links:
            name = link.get_text(strip=True)
            chapter_url = link.get("href")
            if chapter_url:
                chapters.append({"url": chapter_url, "name": name})

    return chapters


def download_images_to_cbz(urls: List[str], output_filename: str) -> str:
    """
    Download images from URLs and create a CBZ (Comic Book ZIP) file.
    """
    import zipfile

    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as cbz:
        for i, url in enumerate(urls, 1):
            try:
                response = scraper.get(url, timeout=30)
                response.raise_for_status()

                # Save image with sequential naming (e.g., 001.jpg, 002.jpg)
                img_filename = f"{i:03d}.jpg"
                cbz.writestr(img_filename, response.content)

            except Exception as e:
                print(f"Error downloading image {i}: {e}")
                continue

    # Verify the CBZ has images
    with zipfile.ZipFile(output_filename, 'r') as cbz:
        if len(cbz.namelist()) == 0:
            raise ValueError("No images were successfully downloaded")

    return output_filename


# Telegram Bot Handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation and ask for the comic URL"""
    await update.message.reply_text(
        "📚 Welcome to the Comic Download Bot!\n\n"
        "I can download comics from readallcomics.com and save them as CBZ files.\n\n"
        "Please send me the URL of the comic you want to download."
    )
    return URL


async def process_all_chapters(update: Update, context: ContextTypes.DEFAULT_TYPE, category_url: str) -> None:
    """Process all chapters from a category URL"""
    message = update.message or update.channel_post
    status_message = await message.reply_text("🔍 Finding chapters...")

    try:
        # Get all chapters
        chapters = get_comic_chapters(category_url)
        # Reverse to download from last chapter first
        chapters.reverse()

        if not chapters:
            await status_message.edit_text("❌ No chapters found. Please check the URL.")
            return

        await status_message.edit_text(f"📚 Found {len(chapters)} chapters. Downloading...")

        # Download each chapter
        for i, chapter in enumerate(chapters, 1):
            chapter_url = chapter["url"]
            chapter_name = chapter["name"]

            try:
                await status_message.edit_text(f"📥 [{i}/{len(chapters)}] {chapter_name}")

                # Get images for this chapter
                urls = get_comic_images(chapter_url)

                if not urls:
                    await message.reply_text(f"⚠️ Skipped: {chapter_name} (no images found)")
                    continue

                with tempfile.TemporaryDirectory() as temp_dir:
                    cbz_path = os.path.join(temp_dir, "comic.cbz")

                    # Sanitize filename using chapter name
                    safe_title = "".join(c for c in chapter_name if c.isalnum() or c in (' ', '-', '_')).strip()
                    if not safe_title:
                        safe_title = f"chapter_{i}"

                    # Download and create CBZ
                    download_images_to_cbz(urls, cbz_path)

                    # Send CBZ
                    filename = f"{safe_title}.cbz"

                    with open(cbz_path, 'rb') as f:
                        await message.reply_document(
                            document=f,
                            filename=filename,
                            caption=f"📚 {chapter_name}\n{i}/{len(chapters)} • {len(urls)} pages"
                        )

            except Exception as e:
                import traceback
                traceback.print_exc()
                await message.reply_text(f"❌ Error downloading {chapter_name}: {str(e)}")
                continue

        await status_message.edit_text(f"✅ Downloaded {len(chapters)} chapters!")

    except Exception as e:
        import traceback
        traceback.print_exc()
        await status_message.edit_text(f"❌ Error: {str(e)}")


async def received_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the URL and process the download"""
    message = update.message or update.channel_post
    url = message.text.strip()

    # Validate URL
    if "readallcomics.com" not in url:
        await message.reply_text(
            "❌ Please send a valid readallcomics.com URL"
        )
        return URL

    # Check if it's a category URL (contains /category/)
    if "/category/" in url:
        # Extract chapters and download all
        await process_all_chapters(update, context, url)
    else:
        # Single comic download
        await process_single_comic(update, context, url)

    return ConversationHandler.END


async def process_single_comic(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    """Process single comic download"""
    message = update.message or update.channel_post
    status_message = await message.reply_text("⏳ Starting download...")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            cbz_path = os.path.join(temp_dir, "comic.cbz")

            # Get title from URL
            await status_message.edit_text("🔍 Fetching comic info...")
            title = get_title_from_url(url)

            # Get images
            await status_message.edit_text("🔍 Fetching comic pages...")
            urls = get_comic_images(url)

            if not urls:
                await status_message.edit_text("❌ No images found. Please check the URL.")
                return

            # Sanitize filename
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
            if not safe_title:
                safe_title = "comic"

            # Download and create CBZ
            await status_message.edit_text(f"📥 Downloading {len(urls)} pages...")
            download_images_to_cbz(urls, cbz_path)

            # Send CBZ
            await status_message.edit_text("📤 Sending your CBZ...")
            filename = f"{safe_title}.cbz"

            with open(cbz_path, 'rb') as f:
                await message.reply_document(
                    document=f,
                    filename=filename,
                    caption=f"📚 {title}\n{len(urls)} pages"
                )

            await status_message.delete()

    except Exception as e:
        import traceback
        traceback.print_exc()
        await status_message.edit_text(f"❌ Error: {str(e)}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation"""
    if update.callback_query:
        query = update.callback_query
        await query.edit_message_text("❌ Operation cancelled.")
    else:
        await update.message.reply_text("❌ Operation cancelled.")

    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help message"""
    help_text = (
        "📚 Comic Download Bot Help\n\n"
        "I can download comics from readallcomics.com and save them as CBZ files!\n\n"
        "Commands:\n"
        "/start - Download a comic from URL\n"
        "/help - Show this help message\n"
        "/cancel - Cancel current operation\n\n"
        "How to download comics:\n"
        "1. Send /start\n"
        "2. Paste a readallcomics.com URL\n"
        "   • Single issue: Direct URL to the comic page\n"
        "   • Entire series: Category URL (e.g. /category/series-name/)\n"
        "3. Receive the CBZ file(s)\n\n"
        "CBZ files can be opened with any comic reader app!"
    )
    await update.message.reply_text(help_text)


def main() -> None:
    """Run the bot."""
    # Get token from environment variable
    token = os.environ.get("TELEGRAM_BOT_TOKEN")

    if not token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set")
        print("Please set it with: export TELEGRAM_BOT_TOKEN='your_token_here'")
        return

    # Create the Application
    application = Application.builder().token(token).build()

    # Add help handler
    application.add_handler(CommandHandler("help", help_command))

    # Add conversation handler for comic download
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_url)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    # Add URL handler for direct comic downloads (without /start)
    async def handle_direct_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle direct URL messages without /start command"""
        message = update.message or update.channel_post
        text = message.text.strip()

        if "readallcomics.com" in text:
            # Check if it's a category URL (contains /category/)
            if "/category/" in text:
                # Extract chapters and download all
                await process_all_chapters(update, context, text)
            else:
                # Single comic download
                await process_single_comic(update, context, text)

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_url)
    )

    # Add handler for channel posts
    application.add_handler(
        MessageHandler(filters.ChatType.CHANNEL & filters.TEXT & ~filters.COMMAND, handle_direct_url)
    )

    # Run the bot
    print("Bot started! Send /start to begin.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
