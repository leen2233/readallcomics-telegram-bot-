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

from booklet_converter import BookletConverter, FlipOption

# Load environment variables from .env file
load_dotenv()

# Conversation states
URL, ASK_BOOKLET, MARGINS, FLIP_OPTION, CONFIRM = range(5)

scraper = cloudscraper.create_scraper()


def get_comic_images(url: str) -> tuple[List[str], str]:
    """Extract image URLs and title from comic page"""
    base = scraper.get(url)
    soup = BS(base.content, "html.parser")
    pages = soup.select("center p img")
    urls = []

    for page in pages:
        source = page.get("src")
        if source:
            urls.append(source)

    # Extract title - try multiple selectors
    title = None
    title_selectors = [
        "body > div.center > center > h3",
        "h3",
        "center h3",
        ".center h3",
        "title",
    ]

    for selector in title_selectors:
        title_elem = soup.select_one(selector)
        if title_elem:
            extracted_title = title_elem.get_text(strip=True)
            if extracted_title and len(extracted_title) > 3:  # Ensure meaningful title
                title = extracted_title
                break

    # Fallback: extract from URL
    if not title:
        from urllib.parse import urlparse
        path = urlparse(url).path.strip('/')
        # Remove file extension and trailing slash
        path = path.rstrip('/')
        # Get the last part of the path
        parts = path.split('/')
        if parts:
            slug = parts[-1]
            # Convert slug to title: replace hyphens with spaces, capitalize each word
            title = ' '.join(word.capitalize() for word in slug.split('-'))

    if not title:
        title = "comic"

    return urls, title


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


def download_images_to_pdf(urls: List[str], output_filename: str) -> str:
    """
    Download images from URLs and convert them to an A4-sized PDF.
    """
    # A4 size in pixels at 300 DPI
    A4_WIDTH = 2480
    A4_HEIGHT = 3508

    downloaded_images = []

    for i, url in enumerate(urls, 1):
        try:
            response = scraper.get(url, timeout=30)
            response.raise_for_status()

            img = Image.open(io.BytesIO(response.content))

            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Resize to fit A4 while maintaining aspect ratio
            img.thumbnail((A4_WIDTH, A4_HEIGHT), Image.Resampling.LANCZOS)
            downloaded_images.append(img)

        except Exception as e:
            print(f"Error downloading image {i}: {e}")
            continue

    if not downloaded_images:
        raise ValueError("No images were successfully downloaded")

    # Save as PDF
    downloaded_images[0].save(
        output_filename,
        save_all=True,
        append_images=downloaded_images[1:],
        resolution=300.0,
        quality=95
    )

    return output_filename


# Telegram Bot Handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation and ask for the comic URL"""
    await update.message.reply_text(
        "📚 Welcome to the Comic Booklet Bot!\n\n"
        "I can download comics from readallcomics.com and convert them to "
        "printable booklets.\n\n"
        "Please send me the URL of the comic you want to download."
    )
    return URL


async def process_all_chapters(update: Update, context: ContextTypes.DEFAULT_TYPE, category_url: str) -> None:
    """Process all chapters from a category URL"""
    message = update.message
    status_message = await message.reply_text("🔍 Finding chapters...")

    try:
        # Get all chapters
        chapters = get_comic_chapters(category_url)

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
                urls, _ = get_comic_images(chapter_url)

                if not urls:
                    await message.reply_text(f"⚠️ Skipped: {chapter_name} (no images found)")
                    continue

                with tempfile.TemporaryDirectory() as temp_dir:
                    pdf_path = os.path.join(temp_dir, "comic.pdf")

                    # Sanitize filename using chapter name
                    safe_title = "".join(c for c in chapter_name if c.isalnum() or c in (' ', '-', '_')).strip()
                    if not safe_title:
                        safe_title = f"chapter_{i}"

                    # Download and create PDF
                    download_images_to_pdf(urls, pdf_path)

                    # Send PDF
                    filename = f"{safe_title}.pdf"

                    with open(pdf_path, 'rb') as f:
                        await message.reply_document(
                            document=f,
                            filename=filename,
                            caption=f"📄 {chapter_name}\n{i}/{len(chapters)}"
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
    url = update.message.text.strip()

    # Validate URL
    if "readallcomics.com" not in url:
        await update.message.reply_text(
            "❌ Please send a valid readallcomics.com URL"
        )
        return URL

    context.user_data['comic_url'] = url

    # Check if it's a category URL (contains /category/)
    if "/category/" in url:
        # Extract chapters and download all
        await process_all_chapters(update, context, url)
    else:
        # Single comic download
        await process_download(update, context, from_url=True)

    return ASK_BOOKLET


async def margins_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle margin selection"""
    query = update.callback_query
    await query.answer()

    margin_choice = query.data

    if margin_choice == "margins_custom":
        await query.edit_message_text(
            "📏 Please enter margins in this format: top,bottom,left,right\n"
            "Example: 10,10,10,10 (all in mm)"
        )
        context.user_data['waiting_for_custom_margins'] = True
        return MARGINS
    else:
        margin_value = int(margin_choice.split("_")[1])
        context.user_data['margins'] = {
            'top': margin_value,
            'bottom': margin_value,
            'left': margin_value,
            'right': margin_value
        }
        return await ask_flip_option(update, context, query=query)


async def custom_margins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom margin input"""
    if not context.user_data.get('waiting_for_custom_margins'):
        return await received_url(update, context)

    try:
        margins_str = update.message.text.strip()
        top, bottom, left, right = [float(x) for x in margins_str.split(",")]

        context.user_data['margins'] = {
            'top': top,
            'bottom': bottom,
            'left': left,
            'right': right
        }
        context.user_data['waiting_for_custom_margins'] = False

        return await ask_flip_option(update, context)

    except ValueError:
        await update.message.reply_text(
            "❌ Invalid format. Please use: top,bottom,left,right\n"
            "Example: 10,10,10,10"
        )
        return MARGINS


async def ask_flip_option(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query = None
) -> int:
    """Ask for flip option"""
    keyboard = [
        [
            InlineKeyboardButton("📖 Long Edge Flip", callback_data="flip_long"),
            InlineKeyboardButton("📕 Short Edge Flip", callback_data="flip_short"),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    message = (
        "🖨️ Select your printer's duplex binding option:\n\n"
        "• Long Edge Flip: Standard for portrait documents (like books)\n"
        "• Short Edge Flip: For landscape or calendar-style binding\n\n"
        "Most home printers use Long Edge Flip."
    )

    if query:
        await query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

    return FLIP_OPTION


async def flip_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle flip option selection and create booklet"""
    query = update.callback_query
    await query.answer()

    flip_choice = query.data
    flip_option = FlipOption.LONG_EDGE if flip_choice == "flip_long" else FlipOption.SHORT_EDGE

    context.user_data['flip_option'] = flip_option

    # Create booklet directly
    await process_download(update, context, from_url=False)

    return ConversationHandler.END


async def process_download(update: Update, context: ContextTypes.DEFAULT_TYPE, from_url: bool = False, show_booklet_prompt: bool = True) -> int:
    """Process the download and conversion"""
    if from_url:
        # Called from URL input - download original PDF only
        message = update.message
        status_message = await message.reply_text("⏳ Starting download...")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                pdf_path = os.path.join(temp_dir, "comic.pdf")

                # Get images and title
                await status_message.edit_text("🔍 Fetching comic pages...")
                urls, title = get_comic_images(context.user_data['comic_url'])

                if not urls:
                    await status_message.edit_text("❌ No images found. Please check the URL.")
                    return ConversationHandler.END

                # Store title and URLs for later booklet creation
                context.user_data['comic_title'] = title
                context.user_data['comic_urls'] = urls
                context.user_data['comic_pdf_path'] = pdf_path

                # Sanitize filename
                safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
                if not safe_title:
                    safe_title = "comic"

                # Download and create PDF
                await status_message.edit_text(f"📥 Downloading {len(urls)} pages...")
                download_images_to_pdf(urls, pdf_path)

                # Send original PDF
                await status_message.edit_text("📤 Sending your PDF...")
                filename = f"{safe_title}.pdf"

                with open(pdf_path, 'rb') as f:
                    await message.reply_document(
                        document=f,
                        filename=filename,
                        caption=f"📄 {title}\n{len(urls)} pages"
                    )

                # Ask if user wants to create booklet (only if show_booklet_prompt is True)
                if show_booklet_prompt:
                    keyboard = [
                        [
                            InlineKeyboardButton("📚 Create Booklet", callback_data="booklet_yes"),
                            InlineKeyboardButton("❌ No Thanks", callback_data="booklet_no"),
                        ],
                    ]

                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await message.reply_text(
                        "Would you like to create a printable booklet version?",
                        reply_markup=reply_markup
                    )

                await status_message.delete()

        except Exception as e:
            import traceback
            traceback.print_exc()
            await status_message.edit_text(f"❌ Error: {str(e)}")

        return ASK_BOOKLET
    else:
        # Called from confirmation - create booklet
        query = update.callback_query
        await query.answer()

        status_message = await query.edit_message_text("⏳ Creating booklet...")

        def progress_callback(msg: str):
            """Callback for progress updates"""
            import asyncio
            asyncio.create_task(status_message.edit_text(msg))

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                pdf_path = os.path.join(temp_dir, "comic.pdf")
                booklet_path = os.path.join(temp_dir, "booklet.pdf")

                # Get images
                await status_message.edit_text("🔍 Fetching comic pages...")
                urls = context.user_data.get('comic_urls')

                if not urls:
                    await status_message.edit_text("❌ No images found. Please start over with /start")
                    return ConversationHandler.END

                # Download and create PDF
                await status_message.edit_text(f"📥 Downloading {len(urls)} pages...")
                download_images_to_pdf(urls, pdf_path)

                # Create booklet
                await status_message.edit_text("📚 Creating booklet...")

                margins = context.user_data['margins']
                converter = BookletConverter(
                    margin_top=margins['top'],
                    margin_bottom=margins['bottom'],
                    margin_left=margins['left'],
                    margin_right=margins['right'],
                    flip_option=context.user_data['flip_option']
                )

                converter.create_booklet(pdf_path, booklet_path, progress_callback)

                # Send booklet
                await status_message.edit_text("📤 Sending your booklet...")

                title = context.user_data.get('comic_title', 'comic')
                safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
                if not safe_title:
                    safe_title = "comic"

                flip_text = "Long Edge" if context.user_data['flip_option'] == FlipOption.LONG_EDGE else "Short Edge"

                with open(booklet_path, 'rb') as f:
                    await query.message.reply_document(
                        document=f,
                        filename=f"{safe_title}_booklet.pdf",
                        caption=(
                            f"📚 {title} - Booklet\n\n"
                            f"Margins: {margins['top']}mm\n"
                            f"Flip: {flip_text}\n\n"
                            f"Print double-sided, fold in half, and staple!"
                        )
                    )

                await status_message.edit_text("✅ Booklet created successfully!")

        except Exception as e:
            import traceback
            traceback.print_exc()
            await status_message.edit_text(f"❌ Error: {str(e)}")

        return ConversationHandler.END


async def booklet_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle booklet choice after original PDF download"""
    query = update.callback_query
    await query.answer()

    choice = query.data

    if choice == "booklet_no":
        await query.edit_message_text("✅ Done! Send /start to download another comic.")
        return ConversationHandler.END
    else:  # booklet_yes
        # Create margin options keyboard
        keyboard = [
            [
                InlineKeyboardButton("No Margins", callback_data="margins_0"),
                InlineKeyboardButton("Small (5mm)", callback_data="margins_5"),
            ],
            [
                InlineKeyboardButton("Medium (10mm)", callback_data="margins_10"),
                InlineKeyboardButton("Large (15mm)", callback_data="margins_15"),
            ],
            [
                InlineKeyboardButton("Custom Margins", callback_data="margins_custom"),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "📏 Select margin size for the booklet:",
            reply_markup=reply_markup
        )

        return MARGINS


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
        "📚 Comic Booklet Bot Help\n\n"
        "I can download comics from readallcomics.com and convert PDFs "
        "to printable booklets!\n\n"
        "Commands:\n"
        "/start - Download a comic from URL\n"
        "/make_booklet - Convert a PDF to booklet (send PDF after this command)\n"
        "/help - Show this help message\n"
        "/cancel - Cancel current operation\n\n"
        "How to download comics:\n"
        "1. Send /start\n"
        "2. Paste a readallcomics.com URL\n"
        "   • Single issue: Direct URL to the comic page\n"
        "   • Entire series: Category URL (e.g. /category/series-name/)\n"
        "3. Receive the PDF(s)\n"
        "4. Optionally create a printable booklet\n\n"
        "How to convert PDF to booklet:\n"
        "1. Send /make_booklet\n"
        "2. Upload/forward a PDF file\n"
        "3. Select margin size\n"
        "4. Select printer flip option\n"
        "5. Get your booklet PDF!\n\n"
        "Printing the booklet:\n"
        "1. Print double-sided\n"
        "2. Fold in half\n"
        "3. Staple along the fold\n"
        "4. Enjoy!"
    )
    await update.message.reply_text(help_text)


# PDF to Booklet Conversation

BOOKLET_MARGINS, BOOKLET_FLIP = range(2)


async def make_booklet_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the booklet conversion conversation"""
    await update.message.reply_text(
        "📚 PDF to Booklet Converter\n\n"
        "Please send me the PDF file you want to convert to a booklet.\n\n"
        "You can:\n"
        "• Upload a PDF file\n"
        "• Forward a PDF message\n"
        "• Send /cancel to stop"
    )
    return BOOKLET_MARGINS


async def booklet_pdf_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle received PDF file"""
    document = update.message.document

    if not document or document.mime_type != 'application/pdf':
        await update.message.reply_text(
            "❌ Please send a PDF file. Send /cancel to stop."
        )
        return BOOKLET_MARGINS

    # Store file info for later download
    context.user_data['booklet_file_id'] = document.file_id
    context.user_data['booklet_filename'] = document.file_name

    # Create margin options keyboard
    keyboard = [
        [
            InlineKeyboardButton("No Margins", callback_data="bmargins_0"),
            InlineKeyboardButton("Small (5mm)", callback_data="bmargins_5"),
        ],
        [
            InlineKeyboardButton("Medium (10mm)", callback_data="bmargins_10"),
            InlineKeyboardButton("Large (15mm)", callback_data="bmargins_15"),
        ],
        [
            InlineKeyboardButton("Custom Margins", callback_data="bmargins_custom"),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"📄 PDF received: {document.file_name}\n\n"
        "📏 Select margin size for the booklet:",
        reply_markup=reply_markup
    )

    return BOOKLET_MARGINS  # Stay in MARGINS state to wait for button click


async def booklet_margins_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle margin selection for booklet"""
    query = update.callback_query
    await query.answer()

    margin_choice = query.data

    if margin_choice == "bmargins_custom":
        await query.edit_message_text(
            "📏 Please enter margins in this format: top,bottom,left,right\n"
            "Example: 10,10,10,10 (all in mm)"
        )
        context.user_data['booklet_waiting_custom'] = True
        return BOOKLET_MARGINS
    else:
        margin_value = int(margin_choice.split("_")[1])
        context.user_data['booklet_margins'] = {
            'top': margin_value,
            'bottom': margin_value,
            'left': margin_value,
            'right': margin_value
        }
        return await ask_booklet_flip(update, context, query=query)


async def booklet_custom_margins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom margin input for booklet"""
    if not context.user_data.get('booklet_waiting_custom'):
        return await booklet_pdf_received(update, context)

    try:
        margins_str = update.message.text.strip()
        top, bottom, left, right = [float(x) for x in margins_str.split(",")]

        context.user_data['booklet_margins'] = {
            'top': top,
            'bottom': bottom,
            'left': left,
            'right': right
        }
        context.user_data['booklet_waiting_custom'] = False

        return await ask_booklet_flip(update, context)

    except ValueError:
        await update.message.reply_text(
            "❌ Invalid format. Please use: top,bottom,left,right\n"
            "Example: 10,10,10,10\n\n"
            "Or send /cancel to stop."
        )
        return BOOKLET_MARGINS


async def ask_booklet_flip(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query = None
) -> int:
    """Ask for flip option for booklet"""
    keyboard = [
        [
            InlineKeyboardButton("📖 Long Edge Flip", callback_data="bflip_long"),
            InlineKeyboardButton("📕 Short Edge Flip", callback_data="bflip_short"),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    message = (
        "🖨️ Select your printer's duplex binding option:\n\n"
        "• Long Edge Flip: Standard for portrait documents (like books)\n"
        "• Short Edge Flip: For landscape or calendar-style binding\n\n"
        "Most home printers use Long Edge Flip."
    )

    if query:
        await query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

    return BOOKLET_FLIP


async def booklet_flip_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle flip option selection and process booklet"""
    query = update.callback_query
    await query.answer()

    flip_choice = query.data
    flip_option = FlipOption.LONG_EDGE if flip_choice == "bflip_long" else FlipOption.SHORT_EDGE

    context.user_data['booklet_flip'] = flip_option

    # Show progress
    status_message = await query.edit_message_text("⏳ Processing your PDF...")

    try:
        # Download the PDF
        file_id = context.user_data['booklet_file_id']
        file = await context.bot.get_file(file_id)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "input.pdf")
            output_path = os.path.join(temp_dir, "booklet.pdf")

            await status_message.edit_text("📥 Downloading PDF...")
            await file.download_to_drive(input_path)

            # Create booklet
            await status_message.edit_text("📚 Creating booklet...")

            margins = context.user_data['booklet_margins']
            converter = BookletConverter(
                margin_top=margins['top'],
                margin_bottom=margins['bottom'],
                margin_left=margins['left'],
                margin_right=margins['right'],
                flip_option=flip_option
            )

            def progress(msg: str):
                import asyncio
                asyncio.create_task(status_message.edit_text(msg))

            converter.create_booklet(input_path, output_path, progress)

            # Send the booklet
            await status_message.edit_text("📤 Sending your booklet...")

            original_filename = context.user_data.get('booklet_filename', 'document')
            base_name = os.path.splitext(original_filename)[0]
            booklet_filename = f"{base_name}_booklet.pdf"

            flip_text = "Long Edge" if flip_option == FlipOption.LONG_EDGE else "Short Edge"

            with open(output_path, 'rb') as f:
                await query.message.reply_document(
                    document=f,
                    filename=booklet_filename,
                    caption=(
                        f"📚 Your booklet is ready!\n\n"
                        f"Margins: {margins['top']}mm\n"
                        f"Flip: {flip_text}\n\n"
                        f"Print double-sided, fold in half, and staple!"
                    )
                )

            await status_message.edit_text("✅ Booklet created successfully!")

    except Exception as e:
        import traceback
        traceback.print_exc()
        await status_message.edit_text(f"❌ Error: {str(e)}")

    return ConversationHandler.END


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

    # Add PDF to booklet conversation handler
    booklet_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("make_booklet", make_booklet_start)],
        states={
            BOOKLET_MARGINS: [
                CallbackQueryHandler(booklet_margins_selected, pattern="^bmargins_"),
                MessageHandler(filters.Document.PDF, booklet_pdf_received),
                MessageHandler(filters.TEXT & ~filters.COMMAND, booklet_custom_margins)
            ],
            BOOKLET_FLIP: [
                CallbackQueryHandler(booklet_flip_selected, pattern="^bflip_")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(booklet_conv_handler)

    # Add URL handler for direct comic downloads (without /start)
    async def handle_direct_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle direct URL messages without /start command"""
        text = update.message.text.strip()

        if "readallcomics.com" in text:
            context.user_data['comic_url'] = text

            # Check if it's a category URL (contains /category/)
            if "/category/" in text:
                # Extract chapters and download all
                await process_all_chapters(update, context, text)
            else:
                # Single comic download - send PDF and mention booklet option
                await process_download(update, context, from_url=True, show_booklet_prompt=False)
                await update.message.reply_text(
                    "💡 Tip: Use /make_booklet to convert any PDF to a printable booklet!"
                )

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_url)
    )

    # Add conversation handler for comic download
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_url)],
            ASK_BOOKLET: [
                CallbackQueryHandler(booklet_choice, pattern="^booklet_"),
            ],
            MARGINS: [
                CallbackQueryHandler(margins_selected, pattern="^margins_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, custom_margins)
            ],
            FLIP_OPTION: [CallbackQueryHandler(flip_selected, pattern="^flip_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    # Run the bot
    print("Bot started! Send /start to begin.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
