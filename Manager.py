"""
ملف: Manager.py
الوظيفة: مدير التداول المركزي المتوافق مع البيئات السحابية والمحلية كافة.
         يقوم بوضع أوامر بيع حدية فور الدخول ومراقبتها بشكل دوري متناسق.
المسار: Super_Trader/Manager_Cloud.py
"""

try:
    import google.colab  # noqa: F401
    import Loger_Colab as Loger  # noqa: F401
except ImportError:
    try:
        import Loger  # noqa: F401
    except ImportError:
        pass

import time
import sys
import requests

try:
    import Settings
except ImportError:
    print("❌ تعذّر استيراد Settings.py — تأكد من وجوده في نفس المجلد.")
    sys.exit(1)

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
    print("❌ تعذّر استيراد Exit_Decision_File.py")
    sys.exit(1)

try:
    from Decision_Execution_File import Decision_Execution, Execute_Emergency_Sell, Place_TP_Limit_Order, Cancel_Order, Get_Order_Status
except ImportError:
    print("❌ تعذّر استيراد Decision_Execution_File.py")
    sys.exit(1)


BITUNIX_BASE_URL       = "https://openapi.bitunix.com"
KLINE_HISTORY_ENDPOINT = "/api/spot/v1/market/kline/history"
CYCLE_SECONDS   = 60
MIN_USDT        = 2.0     
QTY_SAFETY_MARGIN = 0.998   

bot_state = {
    "in_position" : False,
    "position"    : None,   
}

def _get_current_candle_open_time(symbol: str) -> int:
    try:
        response = requests.get(
            BITUNIX_BASE_URL + KLINE_HISTORY_ENDPOINT,
            params={"symbol": symbol, "interval": "1", "limit": 1},
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        if str(result.get("code")) != "0":
            raise ValueError(f"❌ رد خطأ من Bitunix: {result}")
        data = result.get("data")
        if not data:
            raise ValueError("❌ استجابة فارغة من Bitunix")
        candle = data[0]
        raw_ts = candle.get("ts", candle.get("time"))
        if isinstance(raw_ts, str):
            try: raw_ts = int(raw_ts)
            except ValueError:
                from datetime import datetime
                dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000)
        raw_ts = int(raw_ts)
        if raw_ts < 10**12: raw_ts *= 1000
        return raw_ts
    except Exception as e:
        raise RuntimeError(f"❌ خطأ في الاتصال بـ Bitunix: {e}")

def _sleep_until_next_cycle(cycle_start: float, cycle_seconds: int):
    elapsed   = time.time() - cycle_start
    remaining = cycle_seconds - elapsed
    if remaining > 0:
        print(f"[Manager] ⏳ انتظار {remaining:.1f} ثانية للدورة القادمة ...")
        time.sleep(remaining)
    else:
        print(f"[Manager] ⚠️ بدء فوري للدورة القادمة.")

def main():
    Symbol     = Settings.Symbol
    Secret_Key = Settings.Secret_Key
    Access_Key = Settings.Access_Key
    Buy_Volume = Settings.Buy_Volume

    print("=" * 60)
    print("        Super Trader — نظام الأوامر الحدّية المحدث")
    print("=" * 60)

    print("\n[Manager] ▶ تنفيذ Fetching_Trading_Data_1 ...")
    try:
        Exchange_Information = Fetching_Trading_Data_1(Symbol=Symbol, Access_Key=Access_Key, Secret_Key=Secret_Key)
    except Exception as e:
        print(f"[Manager] ❌ فشل جلب معلومات المنصة الأساسية: {e}")
        sys.exit(1)

    print("\n[Manager] ▶ جلب وقت افتتاح الشمعة الحالية للضبط التلقائي ...")
    try:
        TIMESTAMP = _get_current_candle_open_time(Symbol)
    except Exception as e:
        print(f"[Manager] ❌ فشل جلب توقيت الشمعة: {e}")
        sys.exit(1)

    next_cycle_time = (TIMESTAMP / 1000.0) + CYCLE_SECONDS
    wait_seconds    = next_cycle_time - time.time()
    if wait_seconds > 0:
        print(f"[Manager] ⏳ الانتظار {wait_seconds:.1f} ثانية لبدء الدورة الحقيقية الأولى ...")
        time.sleep(wait_seconds)

    print("\n[Manager] 🔄 بدء حلقة التداول اللانهائية بنجاح ...\n")
    cycle_number  = 0
    Decision_prev = "ANYTHING"

    while True:
        cycle_number += 1
        cycle_start  = time.time()

        print("-" * 60)
        print(f"[Manager] 🕐 دورة رقم {cycle_number}")
        
        # ── الاستعلام الفوري وتحديث حالة الأوامر الحدية أول كل دورة إن كنا بالداخل ──
        if bot_state["in_position"]:
            pos = bot_state["position"]
            
            # فحص حالة أمر TP1 المعلق
            if not pos["tp1_done"] and pos["tp1_order_id"]:
                status_res = Get_Order_Status(Symbol, pos["tp1_order_id"], Access_Key, Secret_Key)
                if status_res["status"] == "FILLED":
                    pos["tp1_done"] = True
                    print(f"[Manager] 🎉 رائع! تم تنفيذ أمر TP1 الحدّي بالكامل على المنصة بسعر فني={status_res['avg_price']}")
            
            # فحص حالة أمر TP2 المعلق
            if not pos["tp2_done"] and pos["tp2_order_id"]:
                status_res = Get_Order_Status(Symbol, pos["tp2_order_id"], Access_Key, Secret_Key)
                if status_res["status"] == "FILLED":
                    pos["tp2_done"] = True
                    print(f"[Manager] 🎉 رائع! تم تنفيذ أمر TP2 الحدّي بالكامل على المنصة بسعر فني={status_res['avg_price']}")
            
            # إذا تم تنفيذ كلا الأمرين بنجاح كامل، نغلق حالة الصفقة بأمان ونظافة
            if pos["tp1_done"] and pos["tp2_done"]:
                print("[Manager] ✅ تم تنفيذ جني الأرباح لكلا الأمرين بالكامل بنجاح ساحق. إغلاق المركز بسلام.")
                bot_state["in_position"] = False
                bot_state["position"] = None
                Decision_prev = "ANYTHING"
                _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                continue

            print(
                f"[Manager] 📌 داخل صفقة | دخول={pos['entry_price']:.4f} | SL={pos['sl_price']:.4f} |\n"
                f"   أمر TP1 الحدّي ({pos['tp1_price']:.4f}) -> {'✅ منفذ' if pos['tp1_done'] else '⏳ معلق بالمنصة'} |\n"
                f"   أمر TP2 الحدّي ({pos['tp2_price']:.4f}) -> {'✅ منفذ' if pos['tp2_done'] else '⏳ معلق بالمنصة'}"
            )

        # ── جلب وتجهيز البيانات الدورية ──
        try:
            Raw_Data, Raw_Data_HTF, My_balance = Fetching_Trading_Data_2(Symbol=Symbol, Access_Key=Access_Key, Secret_Key=Secret_Key)
            Final_Data = Indicator_Calculation(Raw_Data)
        except Exception as e:
            print(f"[Manager] ❌ خطأ أثناء تحديث بيانات السوق: {e} — تخطي الدورة.")
            _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
            continue

        current_price = Final_Data["price"]

        # ══════════════════════════════════════════════
        #   منطق إدارة الخروج والتدخل الفوري عند الطوارئ
        # ══════════════════════════════════════════════
        if bot_state["in_position"]:
            pos = bot_state["position"]
            
            exit_res = Exit_Decision(Final_Data, pos)
            bot_state["position"] = exit_res["updated_position"]

            if exit_res["action"] == "EMERGENCY_MARKET_SELL":
                print(f"[Manager] 🚨 {exit_res['log']} -> بدء معالجة الخروج الطارئ فوراً وبلا تردد.")
                
                # أولاً: إلغاء كافة الأوامر الحدية المتبقية فوراً على المنصة لمنع أي تنفيذ مزدوج
                if not pos["tp1_done"] and pos["tp1_order_id"]:
                    Cancel_Order(Symbol, pos["tp1_order_id"], Access_Key, Secret_Key)
                if not pos["tp2_done"] and pos["tp2_order_id"]:
                    Cancel_Order(Symbol, pos["tp2_order_id"], Access_Key, Secret_Key)
                
                # ثانياً: جني وتحديث الرصيد الفوري المتبقي لبيعه عبر السوق بالكامل
                try:
                    _, _, fresh_balance = Fetching_Trading_Data_2(Symbol=Symbol, Access_Key=Access_Key, Secret_Key=Secret_Key)
                    available_base_qty = float(fresh_balance["base"]["free"])
                    
                    if available_base_qty > 0:
                        sell_res = Execute_Emergency_Sell(Symbol, available_base_qty, Exchange_Information, Access_Key, Secret_Key)
                        if sell_res.get("executed"):
                            print(f"[Manager] ✅ تم تصفية الرصيد الطارئ المتبقي بنجاح عبر أمر السوق بسعر متوسط={sell_res.get('avg_price')}")
                except Exception as ex_sell:
                    print(f"[Manager] ❌ فشل حرج أثناء محاولة البيع الفوري للسوق: {ex_sell}")
                
                # تصفير حالة البوت بالكامل للعودة لوضع الاستعداد
                bot_state["in_position"] = False
                bot_state["position"] = None
                Decision_prev = "ANYTHING"
                
                _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                continue
            
            else:
                # الحالة HOLD، ننتظر الدورة التالية
                _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                continue

        # ══════════════════════════════════════════════
        #   منطق الدخول المحدث (BUY)
        # ══════════════════════════════════════════════
        try:
            Decision = Entry_Decision(Final_Data=Final_Data, Decision_prev=Decision_prev, Raw_Data=Raw_Data, Raw_Data_HTF=Raw_Data_HTF)
        except Exception as e:
            print(f"[Manager] ❌ فشل فحص إشارة الدخول: {e}")
            _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
            continue

        if Decision == "BUY":
            usdt_available = float(My_balance["quote"]["free"])
            buy_usdt       = round(usdt_available * Buy_Volume, 2)

            if buy_usdt < MIN_USDT:
                print(f"[Manager] ⚠️ رصيد USDT غير كافٍ ({buy_usdt}$ < {MIN_USDT}$) — تخطي.")
                _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                continue

            try:
                # 1. تنفيذ الشراء الفوري عبر السوق لشحن العملة
                exec_res = Decision_Execution("BUY", Buy_Volume, My_balance, Exchange_Information, Symbol, Access_Key, Secret_Key)
                real_entry_price  = exec_res.get("avg_price") or current_price
                real_executed_qty = exec_res.get("executed_qty")

                if not real_executed_qty or real_executed_qty <= 0:
                    # محاولة استنتاج الكمية من رصيد المنصة الفعلي الاحتياطي
                    _, _, b_after = Fetching_Trading_Data_2(Symbol=Symbol, Access_Key=Access_Key, Secret_Key=Secret_Key)
                    real_executed_qty = float(b_after["base"]["free"])

                if real_executed_qty <= 0:
                    print("[Manager] ❌ فشل تحديد الكمية المشتراة. إلغاء معالجة المركز.")
                    _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)
                    continue

                # تطبيق هامش الأمان الصارم للكمية قبل التوزيع لمنع الرفض
                safe_qty = real_executed_qty * QTY_SAFETY_MARGIN
                
                # 2. بناء هيكل تتبع المخاطرة والأهداف الفنية الديناميكية
                pos_risk = Init_Position_Risk_Management(real_entry_price, Final_Data["atr"], Final_Data, Raw_Data, Raw_Data_HTF)
                
                # 3. إرسال الأوامر الحدية (Limit Orders) للمنصة فوراً (60% لـ TP1 و 40% لـ TP2)
                qty_tp1 = safe_qty * 0.60
                qty_tp2 = safe_qty * 0.40

                print(f"[Manager] 📤 إرسال الأوامر الحدّية للمنصة فوراً: TP1={pos_risk['tp1_price']:.4f} (60%) | TP2={pos_risk['tp2_price']:.4f} (40%)")
                
                order_tp1_res = Place_TP_Limit_Order(Symbol, qty_tp1, pos_risk["tp1_price"], Exchange_Information, Access_Key, Secret_Key)
                order_tp2_res = Place_TP_Limit_Order(Symbol, qty_tp2, pos_risk["tp2_price"], Exchange_Information, Access_Key, Secret_Key)

                pos_risk["tp1_order_id"] = order_tp1_res.get("order_id") if order_tp1_res.get("success") else None
                pos_risk["tp2_order_id"] = order_tp2_res.get("order_id") if order_tp2_res.get("success") else None

                # تثبيت المركز داخل البوت
                bot_state["in_position"] = True
                bot_state["position"]    = pos_risk
                Decision_prev = "BUY"

                print(f"[Manager] 🎉 تم فتح الصفقة ووضع الأوامر بنجاح 100%! دخول={real_entry_price:.5f} | SL الهيكلي الفعلي={pos_risk['sl_price']:.5f}")

            except Exception as e:
                print(f"[Manager] ❌ خطأ حرج أثناء محاولة تنفيذ الشراء وتوزيع الأهداف: {e}")

        _sleep_until_next_cycle(cycle_start, CYCLE_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Manager] 🛑 تم إيقاف البوت يدوياً بطلب من المستخدم.")
        sys.exit(0)
