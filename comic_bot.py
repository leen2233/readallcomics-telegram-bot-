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

# Configuration
DOWNLOAD_DOMAIN = os.environ.get("DOWNLOAD_DOMAIN", "")
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "./downloads")
TELEGRAM_FILE_SIZE_LIMIT = 50 * 1024 * 1024  # 50MB in bytes

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Conversation states
URL = range(1)

scraper = cloudscraper.create_scraper()


def parse_message_with_flags(text: str) -> tuple:
    """
    Parse message text to extract URL and flags.
    Returns: (url, flags) where flags is a set of flag strings
    """
    parts = text.strip().split()
    url = None
    flags = set()

    for part in parts:
        if part.startswith("-") and part.startswith("http"):
            # Handle cases like "-webhttps://..." - add space before http
            url = part[part.index("http"):]
            flags.add(part[:part.index("http")])
        elif part.startswith("-"):
            flags.add(part.lower())
        elif not url and "http" in part:
            url = part

    return url, flags


def cleanup_old_files(directory: str, max_age_days: int = 7) -> None:
    """
    Remove files older than max_age_days from the specified directory.
    """
    import time

    try:
        current_time = time.time()
        max_age_seconds = max_age_days * 24 * 60 * 60

        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath):
                file_age = current_time - os.path.getmtime(filepath)
                if file_age > max_age_seconds:
                    try:
                        os.remove(filepath)
                        print(f"Removed old file: {filename}")
                    except Exception as e:
                        print(f"Error removing {filename}: {e}")
    except Exception as e:
        print(f"Error during cleanup: {e}")


def save_file_to_server(source_path: str, filename: str) -> str:
    """
    Save file to server directory and return download URL.
    """
    import shutil

    # Sanitize filename
    safe_filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).strip()
    if not safe_filename:
        safe_filename = "comic.cbz"

    dest_path = os.path.join(DOWNLOAD_DIR, safe_filename)

    # Copy file to download directory
    shutil.copy2(source_path, dest_path)

    # Build URL
    if DOWNLOAD_DOMAIN:
        # Remove trailing slash from domain if present
        domain = DOWNLOAD_DOMAIN.rstrip("/")
        return f"{domain}/{safe_filename}"
    else:
        return f"File saved to: {dest_path}"


def get_file_size(filepath: str) -> int:
    """Get file size in bytes"""
    return os.path.getsize(filepath)


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


def create_zip_from_chapters(chapters: List[dict], output_filename: str, status_callback=None) -> str:
    """
    Download all chapters and create a single ZIP file containing all CBZ files.
    """
    import zipfile

    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for i, chapter in enumerate(chapters, 1):
            chapter_url = chapter["url"]
            chapter_name = chapter["name"]

            if status_callback:
                status_callback(f"📥 [{i}/{len(chapters)}] {chapter_name}")

            try:
                # Get images for this chapter
                urls = get_comic_images(chapter_url)

                if not urls:
                    print(f"Skipped: {chapter_name} (no images found)")
                    continue

                # Create CBZ in memory
                import io
                cbz_buffer = io.BytesIO()

                with zipfile.ZipFile(cbz_buffer, 'w', zipfile.ZIP_DEFLATED) as cbz:
                    for j, url in enumerate(urls, 1):
                        try:
                            response = scraper.get(url, timeout=30)
                            response.raise_for_status()
                            img_filename = f"{j:03d}.jpg"
                            cbz.writestr(img_filename, response.content)
                        except Exception as e:
                            print(f"Error downloading image {j} for {chapter_name}: {e}")
                            continue

                # Verify CBZ has images
                cbz_buffer.seek(0)
                with zipfile.ZipFile(cbz_buffer, 'r') as cbz_check:
                    if len(cbz_check.namelist()) == 0:
                        print(f"Skipped: {chapter_name} (no images successfully downloaded)")
                        continue

                # Sanitize chapter name for filename
                safe_chapter_name = "".join(c for c in chapter_name if c.isalnum() or c in (' ', '-', '_')).strip()
                if not safe_chapter_name:
                    safe_chapter_name = f"chapter_{i}"

                # Add CBZ to ZIP
                cbz_buffer.seek(0)
                zip_filename = f"{safe_chapter_name}.cbz"
                zip_file.writestr(zip_filename, cbz_buffer.getvalue())

            except Exception as e:
                print(f"Error processing {chapter_name}: {e}")
                import traceback
                traceback.print_exc()
                continue

    # Verify the ZIP has files
    with zipfile.ZipFile(output_filename, 'r') as zip_file:
        if len(zip_file.namelist()) == 0:
            raise ValueError("No chapters were successfully downloaded")

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


async def process_all_chapters_zip(update: Update, context: ContextTypes.DEFAULT_TYPE, category_url: str) -> None:
    """Process all chapters from a category URL and create a single ZIP file"""
    message = update.message or update.channel_post
    status_message = await message.reply_text("🔍 Finding chapters...")

    try:
        # Cleanup old files
        cleanup_old_files(DOWNLOAD_DIR)

        # Get all chapters
        chapters = get_comic_chapters(category_url)
        # Reverse to download from first chapter first
        chapters.reverse()

        if not chapters:
            await status_message.edit_text("❌ No chapters found. Please check the URL.")
            return

        await status_message.edit_text(f"📚 Found {len(chapters)} chapters. Creating ZIP...")

        # Get title from URL for ZIP filename
        title = get_title_from_url(category_url)
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        if not safe_title:
            safe_title = "comic"

        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, f"{safe_title}.zip")

            # Create ZIP with all chapters
            def status_callback(msg):
                import asyncio
                asyncio.create_task(status_message.edit_text(msg))

            create_zip_from_chapters(chapters, zip_path, status_callback)

            # Get file size
            file_size = get_file_size(zip_path)
            size_mb = file_size / (1024 * 1024)

            # Save to server and get URL
            await status_message.edit_text("📤 Saving to server...")
            download_url = save_file_to_server(zip_path, f"{safe_title}.zip")

            await status_message.edit_text(
                f"✅ ZIP file created!\n"
                f"📁 {len(chapters)} chapters\n"
                f"📦 {size_mb:.1f} MB\n"
                f"🔗 {download_url}"
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        await status_message.edit_text(f"❌ Error: {str(e)}")


async def process_all_chapters(update: Update, context: ContextTypes.DEFAULT_TYPE, category_url: str, flags: set = None) -> None:
    """Process all chapters from a category URL"""
    if flags is None:
        flags = set()

    # If -zip flag is present, create single ZIP
    if "-zip" in flags:
        await process_all_chapters_zip(update, context, category_url)
        return

    message = update.message or update.channel_post
    status_message = await message.reply_text("🔍 Finding chapters...")

    try:
        # Cleanup old files
        cleanup_old_files(DOWNLOAD_DIR)

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

                    # Get file size
                    file_size = get_file_size(cbz_path)
                    filename = f"{safe_title}.cbz"

                    # Check if we should send to Telegram or save to server
                    if "-web" in flags or file_size > TELEGRAM_FILE_SIZE_LIMIT:
                        # Save to server
                        download_url = save_file_to_server(cbz_path, filename)
                        await message.reply_text(
                            f"📚 {chapter_name}\n"
                            f"🔗 {download_url}\n"
                            f"📦 {file_size / (1024 * 1024):.1f} MB"
                        )
                    else:
                        # Send to Telegram
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
    text = message.text.strip()

    # Parse URL and flags
    url, flags = parse_message_with_flags(text)

    # Validate URL
    if not url or "readallcomics.com" not in url:
        await message.reply_text(
            "❌ Please send a valid readallcomics.com URL"
        )
        return URL

    # Check if it's a category URL (contains /category/)
    if "/category/" in url:
        # Extract chapters and download all
        await process_all_chapters(update, context, url, flags)
    else:
        # Single comic download
        await process_single_comic(update, context, url, flags)

    return ConversationHandler.END


async def process_single_comic(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, flags: set = None) -> None:
    """Process single comic download"""
    if flags is None:
        flags = set()

    message = update.message or update.channel_post
    status_message = await message.reply_text("⏳ Starting download...")

    try:
        # Cleanup old files
        cleanup_old_files(DOWNLOAD_DIR)

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

            # Get file size
            file_size = get_file_size(cbz_path)
            size_mb = file_size / (1024 * 1024)
            filename = f"{safe_title}.cbz"

            # Check if we should send to Telegram or save to server
            if "-web" in flags or file_size > TELEGRAM_FILE_SIZE_LIMIT:
                # Save to server
                await status_message.edit_text("📤 Saving to server...")
                download_url = save_file_to_server(cbz_path, filename)
                await status_message.edit_text(
                    f"✅ Download complete!\n"
                    f"📚 {title}\n"
                    f"📦 {size_mb:.1f} MB • {len(urls)} pages\n"
                    f"🔗 {download_url}"
                )
            else:
                # Send to Telegram
                await status_message.edit_text("📤 Sending your CBZ...")
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
        "1. Send /start or directly send a URL\n"
        "2. Send a readallcomics.com URL with optional flags:\n"
        "   • Single issue: Direct URL to the comic page\n"
        "   • Entire series: Category URL (e.g. /category/series-name/)\n\n"
        "Available flags:\n"
        "• -web : Force save to server and return download link\n"
        "• -zip : For category URLs, create a single ZIP with all chapters\n\n"
        "Examples:\n"
        "• https://readallcomics.com/spiderman-001/\n"
        "• https://readallcomics.com/category/spiderman/ -web\n"
        "• https://readallcomics.com/category/spiderman/ -zip\n\n"
        "Note: Files over 50MB are automatically saved to server.\n\n"
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
            # Parse URL and flags
            url, flags = parse_message_with_flags(text)

            if not url:
                await message.reply_text("❌ Could not parse URL from message")
                return

            # Check if it's a category URL (contains /category/)
            if "/category/" in url:
                # Extract chapters and download all
                await process_all_chapters(update, context, url, flags)
            else:
                # Single comic download
                await process_single_comic(update, context, url, flags)

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
