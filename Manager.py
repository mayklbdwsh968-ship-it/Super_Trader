"""
ملف: Manager_Cloud.py
الوظيفة: نسخة "الخادم السحابي / Google Colab" من Manager.py — مطابقة
         تماماً لملف Manager.py (نسخة Termux) من حيث منطق التداول
         والتوافق مع العقد الجديد لـ Entry_Decision_File.py و
         Exit_Decision_File.py، والفرق الوحيد بينهما هو تفعيل نظام
         التسجيل المركزي (Loger.py / Loger_Colab.py) في أعلى الملف —
         نظام التسجيل مفصول بالكامل عن نظام التداول، فلا يوجد أي دالة
         _log() داخل هذا الملف؛ فقط print() عادية في كل مكان، يعترضها
         Loger تلقائياً بمجرد استيراده.
المسار: Super_Trader/Manager_Cloud.py

اختيار تلقائي لنسخة المُسجِّل المناسبة:
    - إن كانت البيئة Google Colab (يُكتشف عبر وجود مكتبة google.colab)
      يُستخدم Loger_Colab.py (يضيف نسخاً احتياطياً دورياً + عند نهاية
      الجلسة إلى Google Drive، فوق التسجيل المحلي العادي في Log.txt).
    - غير ذلك (خادم سحابي عادي مثل Koyeb/GitHub Actions) يُستخدم
      Loger.py العادي (تسجيل محلي في Log.txt فقط — لا حاجة لنسخ Drive).

    ⚠️ ملاحظة مهمة: إن كان مجلد المشروع نفسه (حيث يعمل هذا الملف) واقعاً
    فعلياً داخل Google Drive المربوط (مثال:
    '/content/drive/MyDrive/Super_Trader/')، فـ Log.txt يُكتب أصلاً
    داخل Drive لحظياً مع كل سطر — عندها يمكنك تجاهل هذا الاكتشاف
    التلقائي واستخدام "import Loger" مباشرة بدل الاعتماد على
    Loger_Colab، لأن النسخ الاحتياطي الإضافي يصبح غير ضروري.
"""

# ══════════════════════════════════════════════
#   تفعيل نظام التسجيل المركزي — أول شيء يحدث في الملف بأكمله، قبل
#   أي استيراد آخر، حتى تُسجَّل رسائل نجاح/فشل استيراد باقي الملفات
#   هي نفسها في Log.txt أيضاً
# ══════════════════════════════════════════════
try:
    import google.colab  # noqa: F401  — موجودة فقط داخل بيئة Google Colab
    import Loger_Colab as Loger  # noqa: F401
except ImportError:
    import Loger  # noqa: F401

import time
import sys
import requests

# ══════════════════════════════════════════════
#   استيراد الإعدادات
# ══════════════════════════════════════════════
try:
    import Settings
except ImportError:
    print("❌ تعذّر استيراد Settings.py — تأكد من وجوده في نفس المجلد.")
    sys.exit(1)

# ══════════════════════════════════════════════
#   استيراد ملفات المشروع
# ══════════════════════════════════════════════
try:
    from Fetching_Trading_Data_File import Fetching_Trading_Data_1, Fetching_Trading_Data_2
except ImportError:
    print("❌ تعذّر استيراد Fetching_Trading_Data_File.py")
    sys.exit(1)

try:
    from Indicator_Calculation_File import Indicator_Calculation
except ImportError:
    print("❌ تعذّر استيراد Indicator_Calculation_File.py")
    sys.exit(1)

try:
    from Entry_Decision_File import Entry_Decision
except ImportError:
    print("❌ تعذّر استيراد Entry_Decision_File.py")
    sys.exit(1)

try:
    from Exit_Decision_File import Exit_Decision, Init_Position_Risk_Management
except ImportError:
    print("❌ تعذّر استيراد Exit_Decision_File.py (تأكد من وجود "
          "Init_Position_Risk_Management فيه — العقد الجديد)")
    sys.exit(1)

try:
    from Decision_Execution_File import Decision_Execution, Execute_Emergency_Sell
except ImportError:
    print("❌ تعذّر استيراد Decision_Execution_File.py")
    sys.exit(1)


# ══════════════════════════════════════════════
#   ثوابت
# ══════════════════════════════════════════════
MEXC_BASE_URL   = "https://api.mexc.com"
KLINES_ENDPOINT = "/api/v3/klines"
CYCLE_SECONDS   = 60
MIN_USDT        = 2.0     # الحد الأدنى لقيمة الصفقة بالـ USDT
QTY_SAFETY_MARGIN = 0.998   # هامش أمان بسيط (0.2%) عند حجز الكمية الأصلية
                             # original_qty، لتفادي رفض أوامر البيع لاحقاً
                             # بسبب خصم عمولة التداول من العملة الأساسية نفسها


# ══════════════════════════════════════════════
#   حالة البوت (State)
# ══════════════════════════════════════════════
bot_state = {
    "in_position" : False,
    "position"    : None,   # كائن Position الكامل من Init_Position_Risk_Management
                             # + مفتاح إضافي "original_qty" يضيفه Manager.py
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
        print(f"[Manager] ⏳ انتظار {remaining:.1f} ثانية للدورة القادمة ...")
        time.sleep(remaining)
    else:
        print(f"[Manager] ⚠️  الدورة استغرقت {elapsed:.1f}ث (تجاوزت {cycle_seconds}ث) — بدء فوري.")


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
    # ملاحظة: TP لم يعد رقماً ثابتاً يُقرأ من Settings.py — أصبح SL/TP1/TP2
    # ديناميكيين بالكامل، يُبنيان عند الدخول عبر Init_Position_Risk_Management
    # (انظر Exit_Decision_File.py)

    print("=" * 60)
    print("        Super Trader — بدء التشغيل")
    print("=" * 60)
    print(f"   الزوج     : {Symbol}")
    print(f"   Buy_Volume: {Buy_Volume}")
    print(f"   إدارة الخروج: SL هيكلي + TP1/TP2 جزئي + Trailing (ديناميكي بالكامل)")
    print("=" * 60)

    # ─────────────────────────────────────────
    # الخطوة 1: Exchange Information + 150 شمعة أولية
    # ─────────────────────────────────────────
    print("\n[Manager] ▶ تنفيذ Fetching_Trading_Data_1 ...")
    try:
        Exchange_Information = Fetching_Trading_Data_1(
            Symbol     = Symbol,
            Access_Key = Access_Key,
            Secret_Key = Secret_Key
        )
    except Exception as e:
        print(f"[Manager] ❌ فشل Fetching_Trading_Data_1: {e}")
        sys.exit(1)

    print("[Manager] ✅ Exchange_Information جاهز.")

    # ─────────────────────────────────────────
    # الخطوة 2: مزامنة بداية الدورة مع الشمعة
    # ─────────────────────────────────────────
    print("\n[Manager] ▶ جلب وقت افتتاح الشمعة الحالية ...")
    try:
        TIMESTAMP = _get_current_candle_open_time(Symbol)
    except Exception as e:
        print(f"[Manager] ❌ فشل جلب timestamp الشمعة: {e}")
        sys.exit(1)

    next_cycle_time = (TIMESTAMP / 1000.0) + CYCLE_SECONDS
    wait_seconds    = next_cycle_time - time.time()

    if wait_seconds > 0:
        print(f"[Manager] ⏳ الانتظار {wait_seconds:.1f} ثانية لبدء الدورة ...")
        time.sleep(wait_seconds)
    else:
        print("[Manager] ⚡ الشمعة اكتملت بالفعل — بدء الدورة فوراً.")

    # ─────────────────────────────────────────
    # دالة مساعدة: بيع سوق فوري لكمية محددة — تُستخدم من كل مستويات
    # الخروج الجديدة (TP1/TP2 الجزئي، وSL/الوقف الزمني/Trailing الكامل)
    # ─────────────────────────────────────────
    def _execute_market_sell(quantity: float, reason: str):
        try:
            Execution_Result = Execute_Emergency_Sell(
                Symbol               = Symbol,
                quantity             = quantity,
                Exchange_Information = Exchange_Information,
                Access_Key           = Access_Key,
                Secret_Key           = Secret_Key
            )
            return Execution_Result
        except Exception as e:
            print(f"[Manager] ❌ فشل تنفيذ بيع سوق ({reason}) لكمية {quantity}: {e}")
            return None

    # ─────────────────────────────────────────
    # دالة مساعدة: جلب رصيد فعلي وبيع الكل — fallback فقط عند غياب
    # original_qty موثوقة (فشل كامل باستخراج تفاصيل تنفيذ الشراء)
    # ─────────────────────────────────────────
    def _sell_all_available_fallback(My_balance_arg=None):
        try:
            if My_balance_arg is None:
                _, _, My_balance_arg = Fetching_Trading_Data_2(
                    Symbol     = Symbol,
                    Access_Key = Access_Key,
                    Secret_Key = Secret_Key
                )
            return Decision_Execution(
                Decision             = "SELL",
                Buy_Volume           = Buy_Volume,
                My_balance           = My_balance_arg,
                Exchange_Information = Exchange_Information,
                Symbol               = Symbol,
                Access_Key           = Access_Key,
                Secret_Key           = Secret_Key
            )
        except Exception as e:
            print(f"[Manager] ❌ فشل بيع الرصيد الكامل كحل بديل: {e}")
            return None

    # ─────────────────────────────────────────
    # الخطوة 3: حلقة التداول اللانهائية
    # ─────────────────────────────────────────
    print("\n[Manager] 🔄 بدء حلقة التداول ...\n")

    cycle_number  = 0
    Decision_prev = "ANYTHING"   # القرار السابق — القيمة الافتراضية عند البدء

    while True:
        cycle_number += 1
        cycle_start  = time.time()

        print("-" * 60)
        print(f"[Manager] 🕐 دورة رقم {cycle_number}")
        if bot_state["in_position"]:
            pos = bot_state["position"]
            print(
                f"[Manager] 📌 داخل صفقة | دخول={pos['entry_price']:.4f} | "
                f"SL={pos['sl_price']:.4f} | TP1={pos['tp1_price']:.4f}"
                f"{' ✅' if pos.get('tp1_done') else ''} | "
                f"TP2={pos['tp2_price']:.4f}{' ✅' if pos.get('tp2_done') else ''} | "
                f"متبقٍّ={pos.get('remaining_pct', 1.0)*100:.0f}%"
            )
        print("-" * 60)

        # ── جلب البيانات ───────────────────────────────
        try:
            Raw_Data, Raw_Data_HTF, My_balance = Fetching_Trading_Data_2(
                Symbol     = Symbol,
                Access_Key = Access_Key,
                Secret_Key = Secret_Key
            )
        except Exception as e:
            print(f"[Manager] ❌ فشل Fetching_Trading_Data_2: {e} — تخطي الدورة.")
            _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
            continue

        # ── حساب المؤشرات ──────────────────────────────
        try:
            Final_Data = Indicator_Calculation(Raw_Data)
        except Exception as e:
            print(f"[Manager] ❌ فشل Indicator_Calculation: {e} — تخطي الدورة.")
            _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
            continue

        current_price = Final_Data["price"]

        # ══════════════════════════════════════════════
        # منطق الخروج — يعمل فقط إذا كنا داخل صفقة
        # Exit_Decision الآن تُدير كل شيء داخلياً (SL/وقف زمني/TP1/TP2/
        # Trailing) وتُعيد إجراءً واحداً واضحاً كل دورة — لا حاجة لمراقبة
        # أي أمر معلَّق على المنصة، كل الخروج يُنفَّذ ببيع سوق فوري هنا
        # ══════════════════════════════════════════════
        if bot_state["in_position"]:
            position = bot_state["position"]
            original_qty = position.get("original_qty")
            entry_price  = position["entry_price"]

            try:
                Exit_Result = Exit_Decision(
                    Final_Data = Final_Data,
                    Position   = position
                )
            except Exception as e:
                print(f"[Manager] ❌ فشل Exit_Decision: {e} — تخطي الدورة.")
                _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                continue

            action        = Exit_Result["action"]
            sell_fraction = Exit_Result["sell_fraction"]
            updated_position = Exit_Result["updated_position"]
            # الحفاظ على original_qty عبر التحديثات (Exit_Decision لا يعرف
            # عنها شيئاً، فهي مفتاح خاص بـ Manager.py فقط)
            updated_position["original_qty"] = original_qty
            bot_state["position"] = updated_position

            if action == "HOLD":
                _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                continue

            # ── أي إجراء غير HOLD يتطلب بيع سوق فوري ─────
            is_full_exit = action in ("SELL_SL", "SELL_TIME_STOP", "SELL_TRAIL")
            action_labels = {
                "SELL_TP1_PARTIAL": "TP1 جزئي",
                "SELL_TP2_PARTIAL": "TP2 جزئي",
                "SELL_SL"         : "SL هيكلي",
                "SELL_TIME_STOP"  : "وقف زمني",
                "SELL_TRAIL"      : "Trailing Stop",
            }
            action_label = action_labels.get(action, action)

            if original_qty is not None and original_qty > 0:
                sell_qty = original_qty * sell_fraction
                Execution_Result = _execute_market_sell(sell_qty, action_label)
            else:
                # حالة نادرة: لم تتوفر original_qty موثوقة عند الدخول —
                # fallback فقط عند خروج كامل (لا معنى لبيع "جزئي" من
                # كمية مجهولة)؛ عند إجراء جزئي بلا original_qty نكتفي
                # بتسجيل تحذير والإبقاء على الصفقة كما هي هذه الدورة
                if is_full_exit:
                    print(
                        "[Manager] ⚠️ لا توجد original_qty محفوظة — جلب "
                        "رصيد فعلي وبيع الكل كحل أخير."
                    )
                    Execution_Result = _sell_all_available_fallback()
                else:
                    print(
                        f"[Manager] ⚠️ إجراء {action_label} مطلوب لكن لا توجد "
                        "original_qty موثوقة — تم تخطي التنفيذ هذه الدورة "
                        "(الصفقة لا تزال مفتوحة، سيُعاد التقييم بالدورة القادمة)."
                    )
                    Execution_Result = None

            if Execution_Result is not None:
                real_exit_price = Execution_Result.get("avg_price")
                if real_exit_price is not None:
                    real_pl = real_exit_price - entry_price
                    real_pl_pct = (real_pl / entry_price) * 100
                    print(
                        f"[Manager] 💰 تنفيذ {action_label} | دخول={entry_price:.5f} | "
                        f"خروج فعلي={real_exit_price:.5f} | "
                        f"ربح/خسارة (لهذا الجزء)={real_pl:.5f} ({real_pl_pct:+.2f}%)"
                    )
                else:
                    print(
                        f"[Manager] ⚠️ تم تنفيذ {action_label} لكن تعذّر الحصول "
                        "على سعر التنفيذ الفعلي من المنصة."
                    )
            else:
                print(f"[Manager] ⚠️ فشل تنفيذ بيع {action_label} — سيُعاد المحاولة الدورة القادمة.")
                if not is_full_exit:
                    _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                    continue

            if is_full_exit:
                bot_state["in_position"] = False
                bot_state["position"]    = None
                Decision_prev = "ANYTHING"
                print(f"[Manager] ✅ تم إغلاق الصفقة بالكامل ({action_label}).")
            else:
                print(
                    f"[Manager] ➡️ الصفقة لا تزال مفتوحة | "
                    f"متبقٍّ={bot_state['position'].get('remaining_pct', 1.0)*100:.0f}%"
                )

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
            print(f"[Manager] ❌ فشل Entry_Decision: {e} — تخطي الدورة.")
            _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
            continue

        # ── تحديث Decision_prev
        #    يُحدَّث فقط عند BUY — لا عند ANYTHING — حتى يحتفظ بآخر
        #    قرار حقيقي صدر. يُصفَّر إلى "ANYTHING" فور إغلاق أي صفقة
        #    (أعلاه)، ولا يُحدَّث هنا فوراً عند ظهور إشارة BUY، بل فقط
        #    بعد تأكد نجاح تنفيذ الشراء فعلياً (انظر أدناه) — لتفادي
        #    توقّف الدخول نهائياً بعد أي محاولة شراء فاشلة.

        # ── تنفيذ قرار الشراء ─────────────────────────
        if Decision == "BUY":

            usdt_available = float(My_balance["quote"]["free"])
            buy_usdt       = round(usdt_available * Buy_Volume, 2)

            if buy_usdt < MIN_USDT:
                print(
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

                real_entry_price  = Execution_Result.get("avg_price")
                real_executed_qty = Execution_Result.get("executed_qty")

                # ── fallback: استنتاج الكمية من فارق الرصيد الفعلي إن
                # لم تتوفر عبر استعلام تفاصيل التنفيذ ─────
                if real_executed_qty is None or real_executed_qty <= 0:
                    print(
                        "[Manager] ⚠️ لم يتوفر الكمية من استعلام تفاصيل "
                        "التنفيذ — محاولة استنتاجها من فارق الرصيد الفعلي ..."
                    )
                    try:
                        base_free_before = float(My_balance["base"]["free"])
                        _, _, fresh_balance_after_buy = Fetching_Trading_Data_2(
                            Symbol     = Symbol,
                            Access_Key = Access_Key,
                            Secret_Key = Secret_Key
                        )
                        base_free_after = float(
                            fresh_balance_after_buy["base"]["free"]
                        )
                        inferred_qty = base_free_after - base_free_before

                        if inferred_qty > 0:
                            real_executed_qty = inferred_qty
                            print(
                                f"[Manager] ✅ تم استنتاج الكمية المشتراة من "
                                f"فارق الرصيد: {inferred_qty}"
                            )
                        else:
                            print(
                                "[Manager] ⚠️ فارق الرصيد غير موجب — تعذّر "
                                "استنتاج كمية موثوقة أيضاً."
                            )
                    except Exception as balance_fallback_error:
                        print(
                            f"[Manager] ⚠️ فشل جلب الرصيد الفعلي كحل بديل: "
                            f"{balance_fallback_error}"
                        )

                if real_entry_price is not None:
                    entry_price = real_entry_price
                else:
                    # Fallback: لا يوجد سعر تنفيذ فعلي موثوق من المنصة —
                    # نستخدم سعر الشمعة كحل أخير مع تحذير واضح
                    entry_price = current_price
                    print(
                        "[Manager] ⚠️ تعذّر الحصول على سعر التنفيذ الفعلي — "
                        "استُخدم سعر الشمعة كتقريب. راقب هذه الصفقة بعناية."
                    )

                entry_atr = Final_Data["atr"]

                # ── بناء إدارة المخاطرة الكاملة (SL/TP1/TP2/Trailing) ─────
                position_risk = Init_Position_Risk_Management(
                    entry_price  = entry_price,
                    entry_atr    = entry_atr,
                    Final_Data   = Final_Data,
                    Raw_Data     = Raw_Data,
                    Raw_Data_HTF = Raw_Data_HTF
                )

                if real_executed_qty is not None and real_executed_qty > 0:
                    position_risk["original_qty"] = real_executed_qty * QTY_SAFETY_MARGIN
                else:
                    position_risk["original_qty"] = None
                    print(
                        "[Manager] ⚠️ لا توجد كمية منفَّذة موثوقة — الصفقة "
                        "مفتوحة لكن دون original_qty؛ سيُلجأ لبيع الرصيد "
                        "الكامل كحل أخير عند أي إشارة خروج كاملة."
                    )

                bot_state["in_position"] = True
                bot_state["position"]    = position_risk
                # يُحدَّث فقط الآن — بعد تأكد نجاح الشراء فعلياً على المنصة
                Decision_prev = "BUY"

                print(
                    f"[Manager] ✅ تم فتح الصفقة | سعر الدخول الفعلي={entry_price:.5f} | "
                    f"(سعر الشمعة وقت القرار={current_price:.5f}) | "
                    f"ATR وقت الدخول={entry_atr:.4f} | "
                    f"SL={position_risk['sl_price']:.5f} | "
                    f"TP1={position_risk['tp1_price']:.5f} | "
                    f"TP2={position_risk['tp2_price']:.5f} | "
                    f"قوة السوق={position_risk['market_strength']}"
                )

            except Exception as e:
                print(f"[Manager] ❌ فشل تنفيذ الشراء: {e}")

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
        print("\n[Manager] 🛑 تم إيقاف البوت يدوياً.")
        sys.exit(0)
