"""
ملف: Decision_Execution_File.py
الوظيفة: تنفيذ قرار التداول (شراء / بيع / لا شيء)
المسار: /content/Trading_System/Decision_Execution_File.py  (على Google Colab)
"""

import math
import time
import hmac
import hashlib
import requests

# ──────────────────────────────────────────────
# ثوابت
# ──────────────────────────────────────────────
MEXC_BASE_URL   = "https://api.mexc.com"
ORDER_ENDPOINT  = "/api/v3/order"


# ══════════════════════════════════════════════
#   دوال مساعدة
# ══════════════════════════════════════════════

def _round_down(value: float, decimals: int) -> float:
    """تقريب للأسفل بعدد محدد من الخانات العشرية."""
    if decimals < 0:
        decimals = 0
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def _sign_request(params: dict, secret_key: str) -> str:
    """
    ينشئ توقيع HMAC-SHA256 لمعاملات الطلب.
    يُرتّب المعاملات كـ query string ثم يوقّعها.
    """
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    signature = hmac.new(
        secret_key.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature


def _get_timestamp() -> int:
    """يعيد الوقت الحالي بالمللي‑ثانية."""
    return int(time.time() * 1000)


def _place_order(
    symbol: str,
    side: str,
    order_type: str,
    quantity: float = None,
    quote_order_qty: float = None,
    price: float = None,
    time_in_force: str = None,
    access_key: str = "",
    secret_key: str = ""
) -> dict:
    """
    يرسل طلب أمر جديد إلى MEXC.

    - للبيع بأمر سوق  (SELL/MARKET): يُمرَّر quantity
    - للشراء بأمر سوق (BUY/MARKET) : يُمرَّر quote_order_qty
    - لأمر حدّي (LIMIT)            : يُمرَّر quantity + price + time_in_force

    newOrderRespType=FULL: نطلب صراحة تفاصيل التنفيذ الكاملة (fills)
    لأن الرد الافتراضي من MEXC لا يتضمنها، وبدونها لا نعرف
    سعر التنفيذ الفعلي — فقط سعر تقريبي غير موثوق.
    """
    params = {
        "symbol":          symbol,
        "side":            side,
        "type":            order_type,
        "newOrderRespType": "FULL",
        "timestamp":       _get_timestamp(),
    }

    if quantity is not None:
        params["quantity"] = quantity

    if quote_order_qty is not None:
        params["quoteOrderQty"] = quote_order_qty

    if price is not None:
        params["price"] = price

    if time_in_force is not None:
        params["timeInForce"] = time_in_force

    # إنشاء التوقيع وإضافته
    params["signature"] = _sign_request(params, secret_key)

    headers = {
        "X-MEXC-APIKEY": access_key,
        "Content-Type":  "application/json",
    }

    try:
        response = requests.post(
            MEXC_BASE_URL + ORDER_ENDPOINT,
            params=params,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        print(f"[Decision_Execution] تم تنفيذ الأمر بنجاح: {result}")

        # ── محاولة استخراج سعر التنفيذ الفعلي من الرد المباشر ──
        details = _extract_execution_details(result)

        # ── Fallback: لو الرد المباشر ما تضمّن بيانات كافية،
        #    نستعلم عن الأمر بشكل منفصل ──
        if details["avg_price"] is None and result.get("orderId"):
            print("[Decision_Execution] ⚠️ الرد لا يحتوي بيانات تنفيذ كافية — استعلام إضافي ...")
            time.sleep(1)  # مهلة قصيرة لضمان تسوية الأمر في نظام المنصة
            queried = _query_order(
                symbol     = symbol,
                order_id   = result["orderId"],
                access_key = access_key,
                secret_key = secret_key
            )
            details = _extract_execution_details(queried)

        result["_execution_details"] = details
        return result

    except requests.exceptions.HTTPError as e:
        print(f"[Decision_Execution] خطأ HTTP: {e} | الاستجابة: {e.response.text}")
        raise
    except Exception as e:
        print(f"[Decision_Execution] خطأ غير متوقع أثناء إرسال الأمر: {e}")
        raise


def _query_order(
    symbol: str,
    order_id: str,
    access_key: str,
    secret_key: str
) -> dict:
    """
    يستعلم عن تفاصيل أمر مُنفَّذ مسبقاً (fallback) — يُستخدم فقط إذا
    رد _place_order لم يتضمن fills/executedQty/cummulativeQuoteQty
    رغم newOrderRespType=FULL (بعض المنصات لا تلتزم بالضبط).
    """
    params = {
        "symbol":    symbol,
        "orderId":   order_id,
        "timestamp": _get_timestamp(),
    }
    params["signature"] = _sign_request(params, secret_key)

    headers = {"X-MEXC-APIKEY": access_key}

    try:
        response = requests.get(
            MEXC_BASE_URL + ORDER_ENDPOINT,
            params=params,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[Decision_Execution] ⚠️ فشل الاستعلام عن الأمر {order_id}: {e}")
        return {}


def _extract_execution_details(order_result: dict) -> dict:
    """
    يستخرج سعر التنفيذ الفعلي المرجّح (weighted average) والكمية المنفَّذة
    من رد المنصة، بترتيب أولوية:
        1) fills[]                              (الأدق — كل تعبئة على حدة)
        2) cummulativeQuoteQty / executedQty     (المتوسط المرجح الكلي)
        3) لا يوجد بيانات موثوقة → avg_price = None

    يُعيد: {"avg_price": float|None, "executed_qty": float|None}
    """
    fills = order_result.get("fills") or []
    if fills:
        total_qty  = sum(float(f["qty"]) for f in fills)
        total_quote = sum(float(f["qty"]) * float(f["price"]) for f in fills)
        if total_qty > 0:
            return {
                "avg_price":    total_quote / total_qty,
                "executed_qty": total_qty,
            }

    executed_qty     = order_result.get("executedQty")
    cummulative_quote = order_result.get("cummulativeQuoteQty")
    if executed_qty is not None and cummulative_quote is not None:
        try:
            executed_qty_f = float(executed_qty)
            if executed_qty_f > 0:
                return {
                    "avg_price":    float(cummulative_quote) / executed_qty_f,
                    "executed_qty": executed_qty_f,
                }
        except (ValueError, TypeError):
            pass

    return {"avg_price": None, "executed_qty": None}


# ══════════════════════════════════════════════
#   إدارة أمر TP الحدي (Resting Limit Order)
# ══════════════════════════════════════════════

def Place_TP_Limit_Order(
    Symbol: str,
    quantity: float,
    tp_price: float,
    Exchange_Information: dict,
    Access_Key: str,
    Secret_Key: str
) -> dict:
    """
    يضع أمر بيع حدّي (LIMIT SELL) عند سعر TP مباشرة بعد الدخول —
    المنصة نفسها تنفّذه تلقائياً فور وصول السعر للهدف، بدل انتظار
    البوت ومراقبة السعر يدوياً ثم إرسال أمر سوق.

    المدخلات:
        quantity : float — الكمية المُراد بيعها عند TP (عادة نفس
                   الكمية المشتراة تماماً — executed_qty من أمر الشراء)
        tp_price : float — السعر المستهدف (بعد تطبيق فحص الحد الأدنى
                   0.5% في Exit_Decision_File._calc_tp_price)

    المخرج:
        {"success": bool, "order_id": str|None, "price": float, "quantity": float}
    """
    price_scale    = int(Exchange_Information.get("priceScale",    8) or 8)
    quantity_scale = int(Exchange_Information.get("quantityScale", 8) or 8)
    min_qty        = float(Exchange_Information.get("minQty",       0) or 0)

    rounded_qty   = _round_down(quantity, quantity_scale)
    rounded_price = round(tp_price, price_scale)

    if rounded_qty <= 0 or rounded_qty < min_qty:
        print(
            f"[Decision_Execution] ⚠️ الكمية ({rounded_qty}) غير كافية "
            f"لوضع أمر TP الحدي — تم التخطي."
        )
        return {"success": False, "order_id": None, "price": rounded_price, "quantity": rounded_qty}

    try:
        result = _place_order(
            symbol        = Symbol,
            side          = "SELL",
            order_type    = "LIMIT",
            quantity      = rounded_qty,
            price         = rounded_price,
            time_in_force = "GTC",
            access_key    = Access_Key,
            secret_key    = Secret_Key
        )
        order_id = result.get("orderId")
        print(
            f"[Decision_Execution] ✅ أمر TP الحدي موضوع | "
            f"السعر={rounded_price} | الكمية={rounded_qty} | orderId={order_id}"
        )
        return {"success": True, "order_id": order_id, "price": rounded_price, "quantity": rounded_qty}

    except Exception as e:
        print(f"[Decision_Execution] ❌ فشل وضع أمر TP الحدي: {e}")
        return {"success": False, "order_id": None, "price": rounded_price, "quantity": rounded_qty}


def Cancel_Order(
    Symbol: str,
    order_id: str,
    Access_Key: str,
    Secret_Key: str
) -> dict:
    """
    يُلغي أمراً محدداً بالضبط بواسطة orderId — وليس كل الأوامر المفتوحة.
    يُستخدم لإلغاء أمر TP الحدي تحديداً عند تحقق SL أو الخروج الطارئ
    الرابح، قبل تنفيذ البيع الفوري بأمر سوق.
    """
    params = {
        "symbol":    Symbol,
        "orderId":   order_id,
        "timestamp": _get_timestamp(),
    }
    params["signature"] = _sign_request(params, Secret_Key)

    headers = {"X-MEXC-APIKEY": Access_Key}

    try:
        response = requests.delete(
            MEXC_BASE_URL + ORDER_ENDPOINT,
            params=params,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        print(f"[Decision_Execution] ✅ تم إلغاء أمر TP الحدي ({order_id}): {result}")
        return {"success": True, "raw": result}

    except Exception as e:
        print(f"[Decision_Execution] ❌ فشل إلغاء أمر TP الحدي ({order_id}): {e}")
        return {"success": False, "raw": None}


def Get_Order_Status(
    Symbol: str,
    order_id: str,
    Access_Key: str,
    Secret_Key: str
) -> dict:
    """
    يستعلم عن حالة أمر محدد — يُستخدم كل دورة للتحقق هل أمر TP الحدي
    تحقق (FILLED) على المنصة فعلياً، بدل مراقبة السعر يدوياً.

    المخرج:
        {"status": str|None, "avg_price": float|None, "executed_qty": float|None}
        status من قيم المنصة: "NEW" | "PARTIALLY_FILLED" | "FILLED" |
                               "CANCELED" | "REJECTED" | "EXPIRED" | None (فشل الاستعلام)
    """
    raw = _query_order(Symbol, order_id, Access_Key, Secret_Key)
    details = _extract_execution_details(raw)
    return {
        "status":       raw.get("status"),
        "avg_price":    details["avg_price"],
        "executed_qty": details["executed_qty"],
    }


def Execute_Emergency_Sell(
    Symbol: str,
    quantity: float,
    Exchange_Information: dict,
    Access_Key: str,
    Secret_Key: str
) -> dict:
    """
    ينفذ بيع فوري بأمر سوق (MARKET) لكمية محددة بالضبط — يُستخدم بعد
    إلغاء أمر TP الحدي عند تحقق SL أو الخروج الطارئ الرابح.

    نستخدم نفس الكمية المعروفة أصلاً (كمية أمر TP الذي أُلغي للتو)
    بدل إعادة جلب الرصيد، لأن رصيد "Free" وقت بداية الدورة لا يشمل
    الكمية المحجوزة داخل أمر TP المفتوح (تظهر Locked) — واستخدام
    الكمية المعروفة أدق وأسرع من انتظار تحرّرها في الرصيد ثم إعادة جلبه.
    """
    quantity_scale = int(Exchange_Information.get("quantityScale", 8) or 8)
    min_qty        = float(Exchange_Information.get("minQty",       0) or 0)

    sell_qty = _round_down(quantity, quantity_scale)

    if sell_qty <= 0 or sell_qty < min_qty:
        print(
            f"[Decision_Execution] ⚠️ كمية الخروج الطارئ ({sell_qty}) "
            f"أقل من الحد الأدنى — تم التخطي."
        )
        return {"executed": False, "avg_price": None, "executed_qty": None}

    print(f"[Decision_Execution] 🚨 بيع طارئ فوري | الكمية: {sell_qty} | الزوج: {Symbol}")

    try:
        result = _place_order(
            symbol     = Symbol,
            side       = "SELL",
            order_type = "MARKET",
            quantity   = sell_qty,
            access_key = Access_Key,
            secret_key = Secret_Key
        )
        details = result["_execution_details"]
        return {
            "executed":     True,
            "avg_price":    details["avg_price"],
            "executed_qty": details["executed_qty"],
        }
    except Exception as e:
        print(f"[Decision_Execution] ❌ فشل تنفيذ البيع الطارئ: {e}")
        return {"executed": False, "avg_price": None, "executed_qty": None}


# ══════════════════════════════════════════════
#   الدالة الرئيسية
# ══════════════════════════════════════════════

def Decision_Execution(
    Decision,
    Buy_Volume,
    My_balance,
    Exchange_Information,
    Symbol,
    Access_Key,
    Secret_Key
):
    """
    تنفّذ قرار التداول بناءً على قيمة Decision.

    المدخلات:
        Decision            : str   — "ANYTHING" | "BUY" | "SELL"
        Buy_Volume          : float — نسبة USDT المستخدمة عند الشراء (0.0 → 1.0)
                                      (تُستخدم فقط عند Decision == "BUY")
        My_balance          : dict  — {
                                          "quote": {"currency": "USDT", "free": float},
                                          "base" : {"currency": "SOL",  "free": float}
                                      }
        Exchange_Information: dict  — قيود المنصة (priceScale, quantityScale, minQty, ...)
        Symbol              : str   — مثال: "SOLUSDT"
        Access_Key          : str   — مفتاح API للوصول
        Secret_Key          : str   — المفتاح السري لإنشاء التوقيع
    """

    # ─────────────────────────────
    # لا إجراء إذا كان القرار ANYTHING
    # ─────────────────────────────
    if Decision == "ANYTHING":
        print("[Decision_Execution] القرار: ANYTHING — لا إجراء.")
        return {"executed": False, "avg_price": None, "executed_qty": None}

    # ─────────────────────────────
    # استخراج قيود المنصة
    # ─────────────────────────────
    quantity_scale  = int(Exchange_Information.get("quantityScale",  2) or 2)
    min_qty         = float(Exchange_Information.get("minQty",        0) or 0)
    min_notional    = float(Exchange_Information.get("minNotional",   0) or 0)

    # ══════════════════════════════
    # قرار البيع
    # ══════════════════════════════
    if Decision == "SELL":
        # استخراج الكمية المتاحة من العملة الأساسية
        base_currency  = My_balance["base"]["currency"]
        base_available = float(My_balance["base"]["free"])

        if base_available <= 0:
            print(f"[Decision_Execution] لا يوجد رصيد متاح للعملة {base_currency}. تم تخطي البيع.")
            return {"executed": False, "avg_price": None, "executed_qty": None}

        # كمية البيع = كل الكمية المتاحة من العملة الأساسية
        sell_qty = _round_down(base_available, quantity_scale)

        # التحقق من الحد الأدنى للكمية
        if sell_qty < min_qty:
            print(
                f"[Decision_Execution] كمية البيع المحسوبة ({sell_qty}) "
                f"أقل من الحد الأدنى ({min_qty}). تم تخطي البيع."
            )
            return {"executed": False, "avg_price": None, "executed_qty": None}

        print(
            f"[Decision_Execution] بيع | العملة: {base_currency} | "
            f"الكمية: {sell_qty} | الزوج: {Symbol}"
        )

        result = _place_order(
            symbol     = Symbol,
            side       = "SELL",
            order_type = "MARKET",
            quantity   = sell_qty,
            access_key = Access_Key,
            secret_key = Secret_Key
        )
        details = result["_execution_details"]
        return {
            "executed":     True,
            "avg_price":    details["avg_price"],
            "executed_qty": details["executed_qty"],
        }

    # ══════════════════════════════
    # قرار الشراء
    # ══════════════════════════════
    elif Decision == "BUY":
        # استخراج رصيد USDT المتاح
        usdt_available = float(My_balance["quote"]["free"])

        if usdt_available <= 0:
            print("[Decision_Execution] لا يوجد رصيد USDT متاح. تم تخطي الشراء.")
            return {"executed": False, "avg_price": None, "executed_qty": None}

        # كمية USDT للشراء = الرصيد المتاح × Buy_Volume
        raw_buy_usdt = usdt_available * Buy_Volume
        buy_usdt     = _round_down(raw_buy_usdt, 2)   # USDT دائماً بخانتين عشريتين

        # التحقق من الحد الأدنى للصفقة (minNotional)
        if min_notional > 0 and buy_usdt < min_notional:
            print(
                f"[Decision_Execution] كمية USDT المحسوبة ({buy_usdt}) "
                f"أقل من الحد الأدنى للصفقة ({min_notional}). تم تخطي الشراء."
            )
            return {"executed": False, "avg_price": None, "executed_qty": None}

        print(
            f"[Decision_Execution] شراء | كمية USDT: {buy_usdt} | الزوج: {Symbol}"
        )

        result = _place_order(
            symbol          = Symbol,
            side            = "BUY",
            order_type      = "MARKET",
            quote_order_qty = buy_usdt,
            access_key      = Access_Key,
            secret_key      = Secret_Key
        )
        details = result["_execution_details"]
        return {
            "executed":     True,
            "avg_price":    details["avg_price"],
            "executed_qty": details["executed_qty"],
        }

    else:
        print(f"[Decision_Execution] قيمة Decision غير معروفة: '{Decision}' — لا إجراء.")
        return {"executed": False, "avg_price": None, "executed_qty": None}
