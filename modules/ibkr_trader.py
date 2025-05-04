# ✅ ibkr_trader.py (مُحدث بالكامل مع البيع اليدوي وتسجيل الصفقات وتريلينق ستوب ذكي)
from ib_insync import IB, Stock, MarketOrder, StopOrder, LimitOrder
import json
import os
from datetime import datetime
import pytz
import asyncio
from modules.notifier import broadcast_message

KSA = pytz.timezone("Asia/Riyadh")
ib = IB()

connected = False
executed_symbols = {}
TRADES_LOG_DIR = "data/trades"
os.makedirs(TRADES_LOG_DIR, exist_ok=True)

# ⚙️ الاتصال بـ Derayah Gateway

def connect_ib():
    global connected
    try:
        if not connected:
            print("🔌 محاولة الاتصال بـ IBKR...")
            ib.connect('127.0.0.1', 4001, clientId=2)
            connected = True
            print("✅ تم الاتصال بـ IBKR Gateway")

        # ✅ استخراج الرصيد بطريقة موثوقة
        account_values = ib.accountValues()
        cash = None
        for val in account_values:
            if val.tag == 'NetLiquidation' and val.currency == 'USD':
                cash = float(val.value)
                break

        # ✍️ طباعة الرصيد داخل ملف لقراءة خارجية (مثل عند الضغط على زر تلغرام)
        with open("data/ibkr_cash_balance.txt", "w", encoding="utf-8") as f:
            if cash is None:
                f.write("تعذر استخراج الرصيد من IBKR\n")
                print("⚠️ تعذر استخراج الرصيد من IBKR.")
            else:
                f.write(f"رصيد IBKR الحالي: ${cash:.2f}\n")
                print(f"💵 الرصيد الحالي: ${cash:.2f}")

        return True

    except Exception as e:
        print("❌ فشل الاتصال بـ IBKR:", str(e))
        return False

# ✅ باقي الدوال كما هي...


# ✅ فحص السوق

def is_us_market_open():
    now = datetime.now(KSA)
    return now.weekday() < 5 and 16 <= now.hour < 23

# ✅ قراءة الأسهم

def load_stocks(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    return data[:3]  # فقط 3 أسهم
            except:
                pass
    return []

# ✅ حفظ صفقة في سجل يومي

def log_trade(symbol, entry_price, stop_price, quantity):
    date = datetime.now(KSA).strftime('%Y-%m-%d')
    path = os.path.join(TRADES_LOG_DIR, f"trades_log_{date}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = []

    data.append({
        "symbol": symbol,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "quantity": quantity,
        "timestamp": datetime.now(KSA).strftime('%Y-%m-%d %H:%M')
    })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ✅ تسجيل تحديث الوقف

def log_stop_update(symbol, new_stop):
    date = datetime.now(KSA).strftime('%Y-%m-%d')
    path = os.path.join(TRADES_LOG_DIR, f"trades_log_{date}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = []

    data.append({
        "symbol": symbol,
        "update_type": "stop_update",
        "new_stop": new_stop,
        "timestamp": datetime.now(KSA).strftime('%Y-%m-%d %H:%M')
    })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ✅ تنفيذ أمر Market + إعداد وقف خسارة + حفظ في سجل الصفقات

def place_buy_with_stop(symbol, entry_price, stop_price):
    if symbol in executed_symbols:
        print(f"⏸️ تم تنفيذ شراء سابق لهذا السهم: {symbol}")
        return

    try:
        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)

        account = ib.reqAccountSummary()
        try:
            available_cash = float(account.loc['NetLiquidation'].value)
        except Exception as e:
            print(f"⚠️ تعذر استخراج الرصيد من IBKR: {e}")
            return

        investment_per_trade = 100

        if available_cash < investment_per_trade:
            print(f"⛔ لا يوجد رصيد كافٍ. الرصيد الحالي: {available_cash:.2f}")
            return

        quantity = int(investment_per_trade / entry_price)
        if quantity == 0:
            print(f"⛔ سعر السهم مرتفع جدًا بالنسبة لـ ${investment_per_trade}")
            return

        order = MarketOrder('BUY', quantity)
        trade = ib.placeOrder(contract, order)

        ib.sleep(2)
        status = trade.orderStatus.status

        if status == 'Filled':
            print(f"✅ تم شراء {symbol} بسعر تقريبي {entry_price:.2f}")
            stop_order = StopOrder('SELL', quantity, stop_price)
            ib.placeOrder(contract, stop_order)
            print(f"🔻 تم وضع وقف خسارة عند {stop_price:.2f}")
            executed_symbols[symbol] = {
                "entry_price": entry_price,
                "stop_price": stop_price,
                "quantity": quantity
            }
            log_trade(symbol, entry_price, stop_price, quantity)
            asyncio.create_task(broadcast_message(ib, f"🤖 تم شراء <b>{symbol}</b> بسعر {entry_price:.2f} ووقف {stop_price:.2f}"))
        else:
            print(f"⚠️ لم يتم تنفيذ {symbol} - الحالة: {status}")

    except Exception as e:
        print(f"❌ فشل في تنفيذ {symbol}: {e}")


# ✅ تحديث الوقف تلقائيًا بمستويات متعددة وHard Stop

def update_trailing_stops():
    for symbol, info in executed_symbols.items():
        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        market_data = ib.reqMktData(contract, '', False, False)
        ib.sleep(2)

        current_price = market_data.last
        if not current_price:
            continue

        entry = info['entry_price']
        current_stop = info['stop_price']
        new_stop = None

        if current_price >= entry * 1.1:
            new_stop = round(entry * 0.95, 2)
        if current_price >= entry * 1.25:
            new_stop = round(entry * 1.05, 2)
        if current_price >= entry * 1.5:
            new_stop = round(entry * 1.2, 2)
        if current_price >= entry * 1.75:
            new_stop = round(entry * 1.45, 2)
        if current_price >= entry * 2.0:
            new_stop = round(entry * 1.6, 2)

        if new_stop and new_stop > current_stop:
            print(f"📈 {symbol} ارتفع - تحديث الوقف إلى {new_stop}")
            stop_order = StopOrder('SELL', info['quantity'], new_stop)
            ib.placeOrder(contract, stop_order)
            executed_symbols[symbol]['stop_price'] = new_stop
            log_stop_update(symbol, new_stop)
            asyncio.create_task(broadcast_message(ib, f"🔄 تحديث وقف <b>{symbol}</b> إلى {new_stop:.2f}"))

# ✅ شراء تلقائي من التوصيات

async def buy_from_recommended_lists():
    if not is_us_market_open():
        print("⏸️ السوق مغلق")
        return
    if not connect_ib():
        return

    pump_stocks = load_stocks("data/pump_stocks.json")
    high_movement = load_stocks("data/high_movement_stocks.json")

    all_stocks = pump_stocks + high_movement
    for stock in all_stocks:
        symbol = stock.get("symbol")
        entry = float(stock.get("close", 0))
        stop = round(entry * 0.78, 2)

        if symbol and entry:
            place_buy_with_stop(symbol, entry, stop)

# ✅ شراء يدوي

async def manual_buy(symbol):
    if not connect_ib():
        return
    try:
        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        market_data = ib.reqMktData(contract, '', False, False)
        ib.sleep(2)
        current_price = market_data.last
        if not current_price:
            print(f"⚠️ لا يمكن الحصول على سعر {symbol}")
            return

        stop_price = round(current_price * 0.78, 2)
        place_buy_with_stop(symbol, current_price, stop_price)

    except Exception as e:
        print(f"❌ فشل الشراء اليدوي لـ {symbol}: {e}")

# ✅ بيع يدوي

def sell_manual(symbol):
    if not connect_ib():
        return
    try:
        if symbol not in executed_symbols:
            print(f"⚠️ {symbol} غير موجود في الصفقات النشطة")
            return

        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        quantity = executed_symbols[symbol]['quantity']

        sell_order = MarketOrder('SELL', quantity)
        trade = ib.placeOrder(contract, sell_order)
        trade.waitUntilDone(timeout=10)
        status = trade.orderStatus.status

        if status == 'Filled':
            print(f"✅ تم بيع {symbol} يدويًا")
            asyncio.create_task(broadcast_message(ib, f"📤 تم بيع <b>{symbol}</b> يدويًا من IBKR"))
            del executed_symbols[symbol]
        else:
            print(f"⚠️ لم يتم تنفيذ بيع {symbol} - الحالة: {status}")
    except Exception as e:
        print(f"❌ فشل تنفيذ البيع لـ {symbol}: {e}")

# ✅ إلغاء جميع أوامر الشراء المعلقة في IBKR

def cancel_pending_orders():
    if not connect_ib():
        return 0
    try:
        open_orders = ib.reqAllOpenOrders()
        count = 0
        for trade in open_orders:
            if trade.order.action == 'BUY' and trade.order.orderType == 'MKT':
                ib.cancelOrder(trade.order)
                count += 1
        print(f"❌ تم إلغاء {count} أمر شراء معلق.")
        return count
    except Exception as e:
        print(f"❌ فشل في إلغاء الأوامر: {e}")
        return 0

def get_pending_buy_orders():
    if not connect_ib():
        return []
    try:
        open_orders = ib.reqAllOpenOrders()
        return [t.contract.symbol for t in open_orders if t.order.action == 'BUY']
    except:
        return []

def cancel_single_order(symbol):
    if not connect_ib():
        return False
    try:
        open_orders = ib.reqAllOpenOrders()
        for trade in open_orders:
            if trade.contract.symbol == symbol and trade.order.action == 'BUY':
                print(f"🔄 محاولة إلغاء أمر الشراء لـ {symbol}...")
                ib.cancelOrder(trade.order)

                # 🔁 تحقق كل ثانية لمدة 5 ثوانٍ
                for _ in range(5):
                    ib.sleep(1)
                    updated_orders = ib.reqAllOpenOrders()
                    still_exists = any(
                        t.contract.symbol == symbol and t.order.action == 'BUY'
                        for t in updated_orders
                    )
                    if not still_exists:
                        print(f"✅ تم إلغاء أمر الشراء لـ {symbol}.")
                        return True

                print(f"⚠️ فشل في إلغاء أمر الشراء لـ {symbol} - لا زال موجودًا.")
                return False
        print(f"⚠️ لم يتم العثور على أمر شراء معلق لـ {symbol}.")
        return False
    except Exception as e:
        print(f"❌ خطأ أثناء إلغاء {symbol}: {e}")
        return False


def get_trades_details():
    from datetime import datetime
    import pytz
    import os
    import json

    KSA = pytz.timezone("Asia/Riyadh")
    date = datetime.now(KSA).strftime('%Y-%m-%d')
    path = f"data/trades/trades_log_{date}.json"

    if not os.path.exists(path):
        return "❌ لا توجد صفقات اليوم."

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    completed = [x for x in data if "exit_price" in x]
    if not completed:
        return "❌ لا توجد صفقات مكتملة اليوم."

    msg = f"📋 تفاصيل صفقات {date}:\n\n"
    for t in completed:
        symbol = t["symbol"]
        entry = t["entry_price"]
        exit_ = t["exit_price"]
        qty = t["quantity"]
        profit = round((exit_ - entry) * qty, 2)
        msg += f"🔹 {symbol} | 🎯 {entry} → 🏁 {exit_} | 📦 {qty} | 💰 {profit}\n"

    return msg.strip()

# ✅ تقرير صفقات اليوم (الاحتفاظ بالدالة الأصلية كما هي)

def generate_daily_summary():
    import json
    import os
    from datetime import datetime
    import pytz

    KSA = pytz.timezone("Asia/Riyadh")
    date = datetime.now(KSA).strftime('%Y-%m-%d')
    path = f"data/trades/trades_log_{date}.json"

    print("🔌 محاولة الاتصال بـ IBKR من generate_daily_summary()...")
    if not connect_ib():
        return "❌ فشل الاتصال بـ IBKR."

    try:
        account_values = ib.accountValues()
        cash = None
        for val in account_values:
            if val.tag == 'NetLiquidation' and val.currency == 'USD':
                cash = float(val.value)
                break

        if cash is None:
            print("⚠️ تعذر استخراج الرصيد من IBKR.")
            return "⚠️ تعذر استخراج الرصيد من IBKR."
        else:
            print(f"💵 الرصيد الحالي: ${cash:.2f}")

    except Exception as e:
        return f"⚠️ تعذر الاتصال بـ IBKR لحساب الرصيد: {e}"

    if not os.path.exists(path):
        return f"""
📅 {date}
❌ لا توجد صفقات منفذة اليوم.
💼 الرصيد الحالي في IBKR: ${cash:.2f}
""".strip()

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    completed = [x for x in data if "exit_price" in x]
    total_profit = 0

    for t in completed:
        buy = t["entry_price"]
        sell = t["exit_price"]
        qty = t["quantity"]
        total_profit += (sell - buy) * qty

    msg = f"""
📊 تقرير صفقات اليوم ({date}):

📈 عدد الصفقات المكتملة: {len(completed)}
💵 إجمالي الربح/الخسارة: {total_profit:.2f} دولار
💼 الرصيد الحالي في IBKR: ${cash:.2f}
""".strip()

    return msg

