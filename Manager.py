"""
ملف: Manager.py
الوظيفة: إدارة عملية التداول — الحلقة الرئيسية للبوت
المسار: Super_Trader/Manager.py
"""

import os
import time
import sys
import datetime
import requests

# ══════════════════════════════════════════════
#   نظام التسجيل (Logging) — يسجّل كل حدث في Log.txt
#   مع الطابع الزمني، ويضيف للملف دون حذف أي محتوى سابق،
#   وينشئ الملف تلقائياً إن لم يكن موجوداً.
#   (يُعرَّف هنا في أعلى الملف عمداً كي يكون متاحاً حتى أثناء
#   كتل استيراد ملفات المشروع أدناه، والتي قد تستخدمه عند الفشل)
# ══════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "Log.txt")


def _log(message: str):
    """
    تسجّل الرسالة في الطرفية (كما كان الحال سابقاً عبر print) وأيضاً
    تُلحقها بنهاية ملف Log.txt مع طابع زمني دقيق. أي فشل في الكتابة
    بالملف (مثلاً مشكلة صلاحيات) لا يوقف تشغيل الروبوت إطلاقاً —
    فقط يُطبع تحذير في الطرفية.
    """
    print(message)

    timestamp     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_message = message.strip("\n")

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as log_file:
            log_file.write(f"[{timestamp}] {clean_message}\n")
    except Exception as e:
        print(f"[Manager] ⚠️ فشل الكتابة في Log.txt: {e}")


# ══════════════════════════════════════════════
#   استيراد الإعدادات
# ══════════════════════════════════════════════
try:
    import Settings
except ImportError:
    _log("❌ تعذّر استيراد Settings.py — تأكد من وجوده في نفس المجلد.")
    sys.exit(1)

# ══════════════════════════════════════════════
#   استيراد ملفات المشروع
# ══════════════════════════════════════════════
try:
    from Fetching_Trading_Data_File import Fetching_Trading_Data_1, Fetching_Trading_Data_2
except ImportError:
    _log("❌ تعذّر استيراد Fetching_Trading_Data_File.py")
    sys.exit(1)

try:
    from Indicator_Calculation_File import Indicator_Calculation
except ImportError:
    _log("❌ تعذّر استيراد Indicator_Calculation_File.py")
    sys.exit(1)

try:
    from Entry_Decision_File import Entry_Decision
except ImportError:
    _log("❌ تعذّر استيراد Entry_Decision_File.py")
    sys.exit(1)

try:
    from Exit_Decision_File import Exit_Decision, Calc_TP_Price
except ImportError:
    _log("❌ تعذّر استيراد Exit_Decision_File.py")
    sys.exit(1)

try:
    from Decision_Execution_File import (
        Decision_Execution,
        Place_TP_Limit_Order,
        Cancel_Order,
        Get_Order_Status,
        Execute_Emergency_Sell,
    )
except ImportError:
    _log("❌ تعذّر استيراد Decision_Execution_File.py")
    sys.exit(1)


# ══════════════════════════════════════════════
#   ثوابت
# ══════════════════════════════════════════════
MEXC_BASE_URL   = "https://api.mexc.com"
KLINES_ENDPOINT = "/api/v3/klines"
CYCLE_SECONDS   = 60
MIN_USDT        = 2.0     # الحد الأدنى لقيمة الصفقة بالـ USDT
TP_QTY_SAFETY_MARGIN = 0.998   # هامش أمان بسيط (0.2%) عند حجز كمية أمر
                                 # TP الحدّي، لتفادي رفض الأمر بسبب خصم
                                 # عمولة التداول من العملة الأساسية نفسها


# ══════════════════════════════════════════════
#   حالة البوت (State)
# ══════════════════════════════════════════════
bot_state = {
    "in_position" : False,
    "position"    : None,   # {"entry_price", "entry_atr", "tp_price",
                             #  "tp_order_id", "tp_quantity"} بعد الدخول
}


# ══════════════════════════════════════════════
#   دالة جلب timestamp الشمعة الحالية
# ══════════════════════════════════════════════
def _get_current_candle_open_time(symbol: str) -> int:
    try:
        response = requests.get(
            MEXC_BASE_URL + KLINES_ENDPOINT,
            params={"symbol": symbol, "interval": "1m", "limit": 1},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        if not data or not isinstance(data, list) or len(data) == 0:
            raise ValueError("❌ استجابة فارغة من MEXC عند جلب الشمعة الحالية")

        return int(data[0][0])

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"❌ خطأ في الاتصال بـ MEXC: {e}")


# ══════════════════════════════════════════════
#   دالة مساعدة: ضبط توقيت الدورة
# ══════════════════════════════════════════════
def _sleep_until_next_cycle(cycle_start: float, cycle_seconds: int):
    elapsed   = time.time() - cycle_start
    remaining = cycle_seconds - elapsed

    if remaining > 0:
        _log(f"[Manager] ⏳ انتظار {remaining:.1f} ثانية للدورة القادمة ...")
        time.sleep(remaining)
    else:
        _log(f"[Manager] ⚠️  الدورة استغرقت {elapsed:.1f}ث (تجاوزت {cycle_seconds}ث) — بدء فوري.")


# ══════════════════════════════════════════════
#   الدالة الرئيسية
# ══════════════════════════════════════════════
def main():

    # ─────────────────────────────────────────
    # تحميل الإعدادات من Settings.py
    # ─────────────────────────────────────────
    Symbol     = Settings.Symbol
    Secret_Key = Settings.Secret_Key
    Access_Key = Settings.Access_Key
    Buy_Volume = Settings.Buy_Volume
    # ملاحظة: TP لم يعد يُقرأ من Settings.py — أصبح ديناميكياً بناءً على
    # ATR وقت الدخول (انظر TP_ATR_MULTIPLIER في Exit_Decision_File.py)

    _log("=" * 60)
    _log("        Super Trader — بدء التشغيل")
    _log("=" * 60)
    _log(f"   الزوج     : {Symbol}")
    _log(f"   Buy_Volume: {Buy_Volume}")
    _log(f"   TP        : ديناميكي (مبني على ATR وقت الدخول)")
    _log("=" * 60)

    # ─────────────────────────────────────────
    # الخطوة 1: Exchange Information + 150 شمعة أولية
    # ─────────────────────────────────────────
    _log("\n[Manager] ▶ تنفيذ Fetching_Trading_Data_1 ...")
    try:
        Exchange_Information = Fetching_Trading_Data_1(
            Symbol     = Symbol,
            Access_Key = Access_Key,
            Secret_Key = Secret_Key
        )
    except Exception as e:
        _log(f"[Manager] ❌ فشل Fetching_Trading_Data_1: {e}")
        sys.exit(1)

    _log("[Manager] ✅ Exchange_Information جاهز.")

    # ─────────────────────────────────────────
    # الخطوة 2: مزامنة بداية الدورة مع الشمعة
    # ─────────────────────────────────────────
    _log("\n[Manager] ▶ جلب وقت افتتاح الشمعة الحالية ...")
    try:
        TIMESTAMP = _get_current_candle_open_time(Symbol)
    except Exception as e:
        _log(f"[Manager] ❌ فشل جلب timestamp الشمعة: {e}")
        sys.exit(1)

    next_cycle_time = (TIMESTAMP / 1000.0) + CYCLE_SECONDS
    wait_seconds    = next_cycle_time - time.time()

    if wait_seconds > 0:
        _log(f"[Manager] ⏳ الانتظار {wait_seconds:.1f} ثانية لبدء الدورة ...")
        time.sleep(wait_seconds)
    else:
        _log("[Manager] ⚡ الشمعة اكتملت بالفعل — بدء الدورة فوراً.")

    # ─────────────────────────────────────────
    # دالة مساعدة: خروج طارئ (SL أو خروج طارئ رابح)
    # تُلغي أمر TP الحدّي المعلَّق أولاً (بمعرّفه فقط) ثم تبيع فوراً
    # بأمر سوق لنفس الكمية المحجوزة أصلاً في ذلك الأمر
    # ─────────────────────────────────────────
    def _execute_emergency_exit(reason_label: str):
        position = bot_state["position"]
        entry_price = position["entry_price"]

        _log(
            f"[Manager] 🚨 خروج طارئ ({reason_label}) | "
            f"سعر الدخول={entry_price:.5f} | إلغاء أمر TP (orderId="
            f"{position['tp_order_id']}) أولاً ..."
        )

        # ── الخطوة 1: إلغاء أمر TP الحدّي المحدد فقط ─────
        if position.get("tp_order_id"):
            cancel_result = Cancel_Order(
                Symbol     = Symbol,
                order_id   = position["tp_order_id"],
                Access_Key = Access_Key,
                Secret_Key = Secret_Key
            )
            if not cancel_result["success"]:
                _log(
                    "[Manager] ⚠️ فشل إلغاء أمر TP — سنحاول البيع رغم ذلك "
                    "(قد يفشل البيع لو الكمية لا تزال محجوزة فعلياً)."
                )
        else:
            _log("[Manager] ⚠️ لا يوجد tp_order_id مسجَّل — تخطي خطوة الإلغاء.")

        # ── الخطوة 2: بيع فوري بأمر سوق ─────
        try:
            if position.get("tp_quantity") is not None:
                Execution_Result = Execute_Emergency_Sell(
                    Symbol               = Symbol,
                    quantity             = position["tp_quantity"],
                    Exchange_Information = Exchange_Information,
                    Access_Key           = Access_Key,
                    Secret_Key           = Secret_Key
                )
            else:
                # حالة نادرة: لم تتوفر كمية دقيقة عند الدخول (فشل كامل
                # باستخراج تفاصيل تنفيذ الشراء) — fallback: جلب رصيد
                # فعلي حالي وبيع كل المتاح كحل أخير
                _log(
                    "[Manager] ⚠️ لا توجد كمية TP محفوظة — جلب رصيد فعلي "
                    "وبيع الكل كحل أخير."
                )
                _, _, fresh_balance = Fetching_Trading_Data_2(
                    Symbol     = Symbol,
                    Access_Key = Access_Key,
                    Secret_Key = Secret_Key
                )
                Execution_Result = Decision_Execution(
                    Decision             = "SELL",
                    Buy_Volume           = Buy_Volume,
                    My_balance           = fresh_balance,
                    Exchange_Information = Exchange_Information,
                    Symbol               = Symbol,
                    Access_Key           = Access_Key,
                    Secret_Key           = Secret_Key
                )

            real_exit_price = Execution_Result.get("avg_price")

            if real_exit_price is not None:
                real_pl = real_exit_price - entry_price
                real_pl_pct = (real_pl / entry_price) * 100
                _log(
                    f"[Manager] 💰 النتيجة الفعلية | "
                    f"دخول={entry_price:.5f} | خروج فعلي={real_exit_price:.5f} | "
                    f"ربح/خسارة={real_pl:.5f} ({real_pl_pct:+.2f}%)"
                )
            else:
                _log(
                    "[Manager] ⚠️ تعذّر الحصول على سعر التنفيذ الفعلي من المنصة — "
                    "لا يمكن تأكيد الربح/الخسارة الحقيقية لهذه الصفقة."
                )

            bot_state["in_position"] = False
            bot_state["position"]    = None
            _log("[Manager] ✅ تم إغلاق الصفقة (خروج طارئ).")

        except Exception as e:
            _log(f"[Manager] ❌ فشل تنفيذ البيع الطارئ: {e}")

    # ─────────────────────────────────────────
    # الخطوة 3: حلقة التداول اللانهائية
    # ─────────────────────────────────────────
    _log("\n[Manager] 🔄 بدء حلقة التداول ...\n")

    cycle_number  = 0
    Decision_prev = "ANYTHING"   # القرار السابق — القيمة الافتراضية عند البدء

    while True:
        cycle_number += 1
        cycle_start  = time.time()

        _log("-" * 60)
        _log(f"[Manager] 🕐 دورة رقم {cycle_number}")
        if bot_state["in_position"]:
            _log(
                f"[Manager] 📌 داخل صفقة | "
                f"سعر الدخول={bot_state['position']['entry_price']:.4f} | "
                f"TP موضوع عند={bot_state['position']['tp_price']:.4f} | "
                f"orderId={bot_state['position']['tp_order_id']}"
            )
        _log("-" * 60)

        # ── جلب البيانات ───────────────────────────────
        try:
            Raw_Data, Raw_Data_HTF, My_balance = Fetching_Trading_Data_2(
                Symbol     = Symbol,
                Access_Key = Access_Key,
                Secret_Key = Secret_Key
            )
        except Exception as e:
            _log(f"[Manager] ❌ فشل Fetching_Trading_Data_2: {e} — تخطي الدورة.")
            _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
            continue

        # ── حساب المؤشرات ──────────────────────────────
        try:
            Final_Data = Indicator_Calculation(Raw_Data)
        except Exception as e:
            _log(f"[Manager] ❌ فشل Indicator_Calculation: {e} — تخطي الدورة.")
            _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
            continue

        current_price = Final_Data["price"]

        # ══════════════════════════════════════════════
        # منطق الخروج — يعمل فقط إذا كنا داخل صفقة
        # 1) هل أمر TP الحدّي تحقق فعلياً على المنصة؟ (فحص حالة الأمر)
        # 2) لو لا → فحص SL/الخروج الطارئ الرابح عبر Exit_Decision
        # (TP لم يعد يُفحص محلياً — منفَّذ كأمر LIMIT مستقل على المنصة)
        # ══════════════════════════════════════════════
        if bot_state["in_position"]:
            position = bot_state["position"]

            # ── الخطوة 1: هل أمر TP الحدّي تحقق (FILLED)؟ ─────
            if position.get("tp_order_id"):
                try:
                    order_status = Get_Order_Status(
                        Symbol     = Symbol,
                        order_id   = position["tp_order_id"],
                        Access_Key = Access_Key,
                        Secret_Key = Secret_Key
                    )
                except Exception as e:
                    _log(f"[Manager] ❌ فشل الاستعلام عن حالة أمر TP: {e} — تخطي الدورة.")
                    _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                    continue

                if order_status["status"] == "FILLED":
                    real_exit_price = order_status.get("avg_price")
                    entry_price     = position["entry_price"]

                    if real_exit_price is not None:
                        real_pl = real_exit_price - entry_price
                        real_pl_pct = (real_pl / entry_price) * 100
                        _log(
                            f"[Manager] 🎯 TP تحقق فعلياً على المنصة | "
                            f"دخول={entry_price:.5f} | خروج={real_exit_price:.5f} | "
                            f"ربح/خسارة={real_pl:.5f} ({real_pl_pct:+.2f}%)"
                        )
                    else:
                        _log("[Manager] 🎯 TP تحقق (FILLED) — تعذّر استخراج السعر الدقيق.")

                    bot_state["in_position"] = False
                    bot_state["position"]    = None
                    _log("[Manager] ✅ تم إغلاق الصفقة (TP).")

                    _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                    continue

                elif order_status["status"] is None:
                    _log("[Manager] ⚠️ تعذّر التأكد من حالة أمر TP هذه الدورة — إعادة المحاولة لاحقاً.")

            # ── الخطوة 2: TP لم يتحقق بعد → فحص SL/الخروج الطارئ ─────
            try:
                Exit_Decision_Result = Exit_Decision(
                    Final_Data = Final_Data,
                    Position   = position
                )
            except Exception as e:
                _log(f"[Manager] ❌ فشل Exit_Decision: {e} — تخطي الدورة.")
                _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                continue

            _log(
                f"[Manager] 📊 قرار الخروج (Exit_Decision) هذه الدورة: "
                f"{Exit_Decision_Result} | سعر الدخول={position['entry_price']:.5f} | "
                f"السعر الحالي={current_price:.5f} | "
                f"TP المعلَّق عند={position['tp_price']:.5f}"
            )

            if Exit_Decision_Result == "SELL":
                _log("[Manager] 📉 تحقق شرط SL/الخروج الطارئ الرابح — سيتم تنفيذ خروج طارئ فوراً.")
                _execute_emergency_exit("SL/خروج طارئ رابح")
            else:
                _log("[Manager] ➡️ لا يوجد شرط خروج متحقق هذه الدورة — البقاء في الصفقة.")

            _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
            continue

        # ══════════════════════════════════════════════
        # منطق الدخول — يعمل فقط إذا كنا خارج صفقة
        # ══════════════════════════════════════════════

        # ── اتخاذ القرار (مع تمرير Decision_prev) ─────
        try:
            Decision = Entry_Decision(
                Final_Data    = Final_Data,
                Decision_prev = Decision_prev,
                Raw_Data      = Raw_Data,
                Raw_Data_HTF  = Raw_Data_HTF
            )
        except Exception as e:
            _log(f"[Manager] ❌ فشل Entry_Decision: {e} — تخطي الدورة.")
            _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
            continue

        _log(
            f"[Manager] 🧭 قرار الدخول (Entry_Decision) هذه الدورة: {Decision} | "
            f"السعر الحالي={current_price:.5f} | Decision_prev السابق={Decision_prev}"
        )

        # ── تحديث Decision_prev
        #    يُحدَّث فقط عند BUY — لا عند ANYTHING
        #    حتى يحتفظ بآخر قرار حقيقي صدر
        if Decision == "BUY":
            Decision_prev = Decision

        # ── تنفيذ قرار الشراء ─────────────────────────
        if Decision == "BUY":

            usdt_available = float(My_balance["quote"]["free"])
            buy_usdt       = round(usdt_available * Buy_Volume, 2)

            if buy_usdt < MIN_USDT:
                _log(
                    f"[Manager] ⚠️  رصيد غير كافٍ للشراء "
                    f"({buy_usdt}$ < الحد الأدنى {MIN_USDT}$) — تخطي الدورة."
                )
                _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                continue

            try:
                Execution_Result = Decision_Execution(
                    Decision             = "BUY",
                    Buy_Volume           = Buy_Volume,
                    My_balance           = My_balance,
                    Exchange_Information = Exchange_Information,
                    Symbol               = Symbol,
                    Access_Key           = Access_Key,
                    Secret_Key           = Secret_Key
                )

                real_entry_price = Execution_Result.get("avg_price")
                real_executed_qty = Execution_Result.get("executed_qty")

                if real_entry_price is not None:
                    entry_price = real_entry_price
                else:
                    # Fallback: لا يوجد سعر تنفيذ فعلي موثوق من المنصة —
                    # نستخدم سعر الشمعة كحل أخير مع تحذير واضح، لأن
                    # هذا قد يسبب انحراف بين TP/SL المحسوبين والواقع الفعلي
                    entry_price = current_price
                    _log(
                        "[Manager] ⚠️ تعذّر الحصول على سعر التنفيذ الفعلي — "
                        "استُخدم سعر الشمعة كتقريب. راقب هذه الصفقة بعناية."
                    )

                entry_atr = Final_Data["atr"]
                tp_price  = Calc_TP_Price(entry_price, entry_atr)

                # ── وضع أمر TP الحدّي مباشرة بعد الدخول ─────
                if real_executed_qty is not None and real_executed_qty > 0:
                    # هامش أمان بسيط (0.2%) لتفادي رفض الأمر بسبب خصم
                    # عمولة التداول من العملة الأساسية نفسها
                    tp_quantity = real_executed_qty * TP_QTY_SAFETY_MARGIN

                    tp_result = Place_TP_Limit_Order(
                        Symbol               = Symbol,
                        quantity             = tp_quantity,
                        tp_price             = tp_price,
                        Exchange_Information = Exchange_Information,
                        Access_Key           = Access_Key,
                        Secret_Key           = Secret_Key
                    )

                    tp_order_id  = tp_result["order_id"] if tp_result["success"] else None
                    tp_quantity_final = tp_result["quantity"]

                    if not tp_result["success"]:
                        _log(
                            "[Manager] ⚠️ فشل وضع أمر TP الحدّي — الصفقة ستبقى "
                            "بدون هدف ربح آلي! تُدار فقط عبر SL/الخروج الطارئ "
                            "الرابح حتى يُعاد وضع الأمر يدوياً أو بدورة قادمة."
                        )
                else:
                    _log(
                        "[Manager] ⚠️ لا توجد كمية منفَّذة موثوقة — تعذّر وضع "
                        "أمر TP الحدّي. الصفقة بدون هدف ربح آلي."
                    )
                    tp_order_id       = None
                    tp_quantity_final = None

                bot_state["in_position"] = True
                bot_state["position"] = {
                    "entry_price": entry_price,
                    "entry_atr"  : entry_atr,
                    "tp_price"   : tp_price,
                    "tp_order_id": tp_order_id,
                    "tp_quantity": tp_quantity_final,
                }

                _log(
                    f"[Manager] ✅ تم فتح الصفقة | "
                    f"سعر الدخول الفعلي={entry_price:.5f} | "
                    f"(سعر الشمعة وقت القرار={current_price:.5f}) | "
                    f"ATR وقت الدخول={entry_atr:.4f} | "
                    f"TP موضوع عند={tp_price:.5f} | orderId={tp_order_id}"
                )

            except Exception as e:
                _log(f"[Manager] ❌ فشل تنفيذ الشراء: {e}")

        elif Decision == "ANYTHING":
            pass  # لا إجراء

        _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)


# ══════════════════════════════════════════════
#   نقطة الدخول
# ══════════════════════════════════════════════
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("\n[Manager] 🛑 تم إيقاف البوت يدوياً.")
        sys.exit(0)
