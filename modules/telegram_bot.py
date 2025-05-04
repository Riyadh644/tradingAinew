from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import NetworkError
import asyncio
import json
import os
from datetime import datetime
from modules.handlers import manual_buy_handler
from modules.handlers import (
    start,
    top_stocks,
    pump_stocks,
    high_movement_stocks,
    update_symbols_now,
    show_daily_report,
    analyze_stock,
)
from modules.tv_data import analyze_market, fetch_data_from_tradingview
from modules.ml_model import load_model, predict_buy_signal
from modules.user_manager import save_user, get_all_users
from modules.analyze_performance import generate_report_summary
from modules.notifier import send_telegram_message, broadcast_message, safe_send_message
from modules.ibkr_trader import manual_buy, sell_manual, executed_symbols, load_stocks, cancel_single_order, generate_daily_summary
from modules.ibkr_trader import get_trades_details

BOT_TOKEN = "7994128773:AAEnoWDCi33KxYGaEaLKjm3zGq8SSI7fwN8"

async def start_telegram_bot():
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.Regex("(?i)^🌀"), top_stocks))
        app.add_handler(MessageHandler(filters.Regex("(?i)^💥"), pump_stocks))
        app.add_handler(MessageHandler(filters.Regex("(?i)^🚀"), high_movement_stocks))
        app.add_handler(MessageHandler(filters.Regex("(?i)^🔄"), update_symbols_now))
        app.add_handler(MessageHandler(filters.Regex("(?i)^📊"), show_daily_report))
        app.add_handler(MessageHandler(filters.Regex("(?i)^🛑"), manual_sell))
        app.add_handler(MessageHandler(filters.Regex("(?i)^🛒"), manual_buy_handler))
        app.add_handler(MessageHandler(filters.Regex("(?i)^❌ إلغاء شراء معلق"), cancel_pending_orders_handler))
        app.add_handler(MessageHandler(filters.Regex("(?i)^📈 ملخص اليوم"), show_trading_summary))
        app.add_handler(CallbackQueryHandler(callback=buy_button_callback, pattern=r"^buy_"))
        app.add_handler(CallbackQueryHandler(callback=sell_button_callback, pattern=r"^sell_"))
        app.add_handler(CallbackQueryHandler(callback=cancel_order_callback, pattern=r"^cancel_"))
        app.add_handler(MessageHandler(filters.Regex("(?i)^📋 تفاصيل الصفقات"), show_trades_details))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_stock))
        print("✨ بوت التليجرام يعمل الآن!")
        await app.run_polling()

    except Exception as e:
        print(f"⚠️ خطأ في البوت: {e}")
        await asyncio.sleep(10)

# زر جديد: عرض ملخص اليوم من الصفقات والأرباح
# زر جديد: عرض ملخص اليوم من الصفقات والأرباح
async def show_trading_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from modules.ibkr_trader import generate_daily_summary
    summary = generate_daily_summary()
    if summary:
        await update.message.reply_text(summary)
    else:
        await update.message.reply_text("⚠️ لم يتم توليد تقرير اليوم.")


# زر جديد: عرض أوامر الشراء المعلقة لاختيار واحدة لإلغائها
async def cancel_pending_orders_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from modules.ibkr_trader import get_pending_buy_orders
    orders = get_pending_buy_orders()
    if not orders:
        await update.message.reply_text("⚠️ لا توجد أوامر شراء معلقة حاليًا.")
        return
    keyboard = [
        [InlineKeyboardButton(symbol, callback_data=f"cancel_{symbol}")]
        for symbol in orders
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("❌ اختر السهم الذي تريد إلغاء أمر شرائه:", reply_markup=reply_markup)

# عند اختيار سهم لإلغاء أمره
async def cancel_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    symbol = query.data.replace("cancel_", "")
    await query.answer()
    result = cancel_single_order(symbol)
    if result:
        await query.edit_message_text(f"❌ تم إلغاء أمر الشراء المعلق لـ {symbol}.")
    else:
        await query.edit_message_text(f"⚠️ لم يتم العثور على أمر شراء معلق لـ {symbol}.")

async def manual_buy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    pump = load_stocks("data/pump_stocks.json")
    high = load_stocks("data/high_movement_stocks.json")
    all_stocks = pump + high

    for stock in all_stocks:
        symbol = stock.get("symbol")
        if symbol:
            keyboard.append([InlineKeyboardButton(symbol, callback_data=f"buy_{symbol}")])

    if keyboard:
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🛒 اختر السهم الذي تريد شراءه يدويًا:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("⚠️ لا توجد توصيات حالياً للشراء.")

async def manual_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for symbol in executed_symbols.keys():
        keyboard.append([InlineKeyboardButton(symbol, callback_data=f"sell_{symbol}")])

    if keyboard:
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🛑 اختر السهم الذي ترغب في بيعه:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("⚠️ لا توجد صفقات نشطة للبيع.")

async def buy_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    symbol = query.data.replace("buy_", "")
    await query.answer(f"جاري تنفيذ شراء {symbol} ...")
    await manual_buy(symbol)
    await query.edit_message_text(f"✅ تم تنفيذ شراء {symbol} يدويًا.")

async def sell_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    symbol = query.data.replace("sell_", "")
    await query.answer(f"جاري تنفيذ بيع {symbol} ...")
    sell_manual(symbol)
    await query.edit_message_text(f"📤 تم تنفيذ بيع {symbol} يدويًا.")

async def show_trades_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    report = get_trades_details()
    await update.message.reply_text(report)
