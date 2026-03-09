# Comic Booklet Telegram Bot

A Telegram bot that downloads comics from readallcomics.com and converts them to printable 2-up saddle stitch booklets.

## Features

- 📥 Download comics from readallcomics.com
- 📚 Convert to 2-up saddle stitch booklet format
- 📏 Configurable margins (preset or custom)
- 🖨️ Support for long-edge and short-edge duplex printers
- 📤 Get both original PDF and booklet PDF

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a Telegram bot:
   - Open Telegram and search for @BotFather
   - Send `/newbot` and follow the instructions
   - Copy the bot token

3. Set up environment:
```bash
cp .env.example .env
# Edit .env and add your bot token
export TELEGRAM_BOT_TOKEN='your_token_here'
```

4. Run the bot:
```bash
python comic_bot.py
```

## Usage

1. Start a chat with your bot on Telegram
2. Send `/start` to begin
3. Paste a readallcomics.com URL
4. Select margin size (or enter custom like: `10,10,10,10`)
5. Select printer flip option:
   - **Long Edge Flip**: Standard for portrait documents (most printers)
   - **Short Edge Flip**: For landscape or calendar-style binding
6. Confirm and wait for your files!

## Printing the Booklet

1. Print the booklet PDF double-sided
2. Fold all pages in half
3. Staple along the fold
4. Trim if needed

## Options

### Margin Presets
- **No Margins**: 0mm on all sides
- **Small**: 5mm on all sides
- **Medium**: 10mm on all sides (default)
- **Large**: 15mm on all sides
- **Custom**: Enter your own (top,bottom,left,right in mm)

### Printer Flip Options
- **Long Edge Flip**: Pages flip along the long edge (standard portrait)
- **Short Edge Flip**: Pages flip along the short edge (landscape binding)

## Commands

- `/start` - Start downloading a comic
- `/help` - Show help message
- `/cancel` - Cancel current operation

## Files

- `comic_bot.py` - Main Telegram bot
- `booklet_converter.py` - PDF to booklet converter
- `scripts.py` - Original comic downloader
- `requirements.txt` - Python dependencies
