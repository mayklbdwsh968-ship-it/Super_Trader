"""
ملف: Decision_Execution_File.py
الوظيفة: تنفيذ قرار التداول (شراء / بيع / لا شيء) عبر منصة Bitunix Pro (Spot)
تم تعديله للانتقال من MEXC إلى Bitunix.

فروقات جوهرية عن نسخة MEXC:
- التوقيع: SHA256 مزدوج عبر Headers (api-key/nonce/timestamp/sign)
  بدل HMAC-SHA256 عبر query params.
- عند BUY + MARKET: حقل "volume" يُمرَّر كمبلغ USDT مباشرة (نفس سلوك
  quoteOrderQty في MEXC) — هذا مؤكَّد من توثيق/أمثلة Bitunix الفعلية.
- عند SELL (أي نوع) وعند أي أمر LIMIT: حقل "volume" يُمرَّر ككمية
  بالعملة الأساسية (Base token).
- استجابة place_order في Bitunix لا تتضمن سعر/كمية التنفيذ الفعليين
  (لا يوجد "fills" مباشرة كما في MEXC) — لذلك تُستكمل العملية دوماً
  باستعلام عن التعبئات الفعلية عبر /order/deal/list بعد إرسال الأمر.
"""

import time
import json
import math
import uuid
import hashlib
import requests

# ──────────────────────────────────────────────
# ثوابت
# ──────────────────────────────────────────────
BITUNIX_BASE_URL = "https://openapi.bitunix.com"

PLACE_ORDER_ENDPOINT = "/api/spot/v1/order/place_order"
CANCEL_ORDER_ENDPOINT = "/api/spot/v1/order/cancel"
DEAL_LIST_ENDPOINT    = "/api/spot/v1/order/deal/list"
PENDING_LIST_ENDPOINT = "/api/spot/v1/order/pending/list"

# انتظار بعد إرسال أمر السوق قبل الاستعلام عن التعبئات (تسوية الأمر لدى المنصة)
FILL_QUERY_INITIAL_WAIT   = 1.0
FILL_QUERY_RETRY_WAIT     = 1.5
FILL_QUERY_MAX_RETRIES    = 4


# ══════════════════════════════════════════════
#   دوال التوقيع (مطابقة لِـ Fetching_Trading_Data_File.py)
# ══════════════════════════════════════════════

def _round_down(value: float, decimals: int) -> float:
    """تقريب للأسفل بعدد محدد من الخانات العشرية."""
    if decimals < 0:
        decimals = 0
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def _get_timestamp_ms() -> str:
    return str(int(time.time() * 1000))


def _gen_nonce() -> str:
    return uuid.uuid4().hex


def _sign(nonce, timestamp, api_key, secret_key, query_params=None, body_obj=None) -> str:
    if query_params:
        query_str = "".join(
            f"{k}{v}" for k, v in sorted(query_params.items(), key=lambda kv: kv[0])
        )
    else:
        query_str = ""

    body_str = json.dumps(body_obj, separators=(',', ':'), ensure_ascii=False) if body_obj else ""

    digest_input = f"{nonce}{timestamp}{api_key}{query_str}{body_str}"
    digest = hashlib.sha256(digest_input.encode('utf-8')).hexdigest()
    sign_input = f"{digest}{secret_key}"
    return hashlib.sha256(sign_input.encode('utf-8')).hexdigest()


def _auth_headers(Access_Key, Secret_Key, query_params=None, body_obj=None) -> dict:
    nonce     = _gen_nonce()
    timestamp = _get_timestamp_ms()
    sign      = _sign(nonce, timestamp, Access_Key, Secret_Key, query_params, body_obj)
    return {
        "api-key":      Access_Key,
        "nonce":        nonce,
        "timestamp":    timestamp,
        "sign":         sign,
        "Content-Type": "application/json",
    }


def _is_success(result: dict) -> bool:
    return str(result.get("code")) == "0"


# ══════════════════════════════════════════════
#   دوال الطلبات الموقّعة (POST / GET)
# ══════════════════════════════════════════════

def _signed_post(endpoint: str, body_obj: dict, access_key: str, secret_key: str, timeout=10) -> dict:
    headers = _auth_headers(access_key, secret_key, query_params=None, body_obj=body_obj)
    url = f"{BITUNIX_BASE_URL}{endpoint}"
    response = requests.post(
        url,
        data=json.dumps(body_obj, separators=(',', ':'), ensure_ascii=False),
        headers=headers,
        timeout=timeout
    )
    response.raise_for_status()
    result = response.json()
    if not _is_success(result):
        raise RuntimeError(f"❌ رد خطأ من Bitunix عند {endpoint}: {result}")
    return result.get("data")


def _signed_get(endpoint: str, params: dict, access_key: str, secret_key: str, timeout=10) -> dict:
    headers = _auth_headers(access_key, secret_key, query_params=params, body_obj=None)
    url = f"{BITUNIX_BASE_URL}{endpoint}"
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    result = response.json()
    if not _is_success(result):
        raise RuntimeError(f"❌ رد خطأ من Bitunix عند {endpoint}: {result}")
    return result.get("data")


# ══════════════════════════════════════════════
#   دوال مساعدة أساسية
# ══════════════════════════════════════════════

def _place_order(
    symbol: str,
    side: int,          # 1 = Sell, 2 = Buy
    order_type: int,    # 1 = Limit, 2 = Market
    volume: float,
    price: float = 0,
    access_key: str = "",
    secret_key: str = ""
) -> dict:
    """
    يرسل طلب أمر جديد إلى Bitunix.

    - عند BUY+MARKET: volume = مبلغ بعملة التسعير (USDT) مباشرة.
    - عند SELL (أي نوع) أو أي أمر LIMIT: volume = كمية بالعملة الأساسية.
    - price تُرسَل دائماً؛ عند أوامر السوق تُرسَل "0" (تُتجاهل من المنصة).

    المخرج: استجابة Bitunix الخام لِـ data (تحتوي orderId على الأقل).
    """
    body = {
        "symbol": symbol,
        "side":   side,
        "type":   order_type,
        "volume": str(volume),
        "price":  str(price) if price else "0",
    }

    try:
        result = _signed_post(PLACE_ORDER_ENDPOINT, body, access_key, secret_key)
        print(f"[Decision_Execution] تم إرسال الأمر بنجاح: {result}")
        return result or {}
    except requests.exceptions.HTTPError as e:
        body_text = e.response.text if e.response is not None else "(لا يوجد رد)"
        print(f"[Decision_Execution] خطأ HTTP: {e} | الاستجابة: {body_text}")
        raise
    except Exception as e:
        print(f"[Decision_Execution] خطأ غير متوقع أثناء إرسال الأمر: {e}")
        raise


def _query_fills(symbol: str, order_id: str, access_key: str, secret_key: str) -> list:
    """
    يستعلم عن التعبئات الفعلية (fills) لأمر مُنفَّذ عبر /order/deal/list —
    هذه هي النقطة الوحيدة التي توفرها Bitunix لمعرفة سعر التنفيذ الفعلي
    وكمية التنفيذ، لأن رد place_order لا يتضمنها.
    """
    try:
        data = _signed_get(
            DEAL_LIST_ENDPOINT,
            {"orderId": order_id, "symbol": symbol},
            access_key, secret_key
        )
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[Decision_Execution] ⚠️ فشل الاستعلام عن تعبئات الأمر {order_id}: {e}")
        return []


def _extract_execution_details(fills: list) -> dict:
    """
    يستخرج سعر التنفيذ الفعلي المرجّح (weighted average) والكمية المنفَّذة
    من قائمة التعبئات (fills) العائدة من /order/deal/list.

    يُعيد: {"avg_price": float|None, "executed_qty": float|None}
    """
    if not fills:
        return {"avg_price": None, "executed_qty": None}

    try:
        total_qty   = sum(float(f["volume"]) for f in fills)
        total_quote = sum(float(f["volume"]) * float(f["price"]) for f in fills)
    except (KeyError, ValueError, TypeError):
        return {"avg_price": None, "executed_qty": None}

    if total_qty > 0:
        return {"avg_price": total_quote / total_qty, "executed_qty": total_qty}

    return {"avg_price": None, "executed_qty": None}


def _wait_for_fills(symbol: str, order_id: str, access_key: str, secret_key: str) -> dict:
    """
    ينتظر ويعيد المحاولة عدة مرات حتى تظهر التعبئات الفعلية للأمر
    (أوامر السوق تُنفَّذ فوراً عادةً، لكن قد يتأخر ظهورها في deal/list
    بضع ثوانٍ بسبب تسوية النظام لدى المنصة).
    """
    time.sleep(FILL_QUERY_INITIAL_WAIT)

    for attempt in range(1, FILL_QUERY_MAX_RETRIES + 1):
        fills = _query_fills(symbol, order_id, access_key, secret_key)
        details = _extract_execution_details(fills)
        if details["avg_price"] is not None:
            return details

        if attempt < FILL_QUERY_MAX_RETRIES:
            print(
                f"[Decision_Execution] ⚠️ لا توجد تعبئات بعد للأمر {order_id} "
                f"(محاولة {attempt}/{FILL_QUERY_MAX_RETRIES}) — إعادة محاولة..."
            )
            time.sleep(FILL_QUERY_RETRY_WAIT)

    print(
        f"[Decision_Execution] ⚠️ لم تظهر تعبئات موثوقة للأمر {order_id} "
        f"بعد {FILL_QUERY_MAX_RETRIES} محاولات."
    )
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
    يضع أمر بيع حدّي (LIMIT SELL) عند سعر TP مباشرة بعد الدخول.
    المخرج: {"success": bool, "order_id": str|None, "price": float, "quantity": float}
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
            symbol     = Symbol,
            side       = 1,   # Sell
            order_type = 1,   # Limit
            volume     = rounded_qty,
            price      = rounded_price,
            access_key = Access_Key,
            secret_key = Secret_Key
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
    """يُلغي أمراً محدداً بالضبط بواسطة orderId."""
    body = {"orderIdList": [{"orderId": order_id, "symbol": Symbol}]}

    try:
        result = _signed_post(CANCEL_ORDER_ENDPOINT, body, Access_Key, Secret_Key)
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
    يستعلم عن حالة أمر محدد. بما أن Bitunix لا توفر نقطة "تفاصيل أمر
    واحد" موثّقة رسمياً، تُستنتج الحالة كالتالي:
      1) إن وُجدت تعبئات (fills) عبر /order/deal/list → الأمر FILLED
         (كلياً أو جزئياً) وتُستخرج منها avg_price/executed_qty.
      2) إن لم توجد تعبئات لكن الأمر لا يزال ضمن /order/pending/list
         → الأمر لا يزال NEW (لم يتحقق TP بعد).
      3) إن لم توجد تعبئات ولم يظهر ضمن القائمة المعلّقة → على الأرجح
         أُلغي أو انتهت صلاحيته.

    المخرج:
        {"status": str|None, "avg_price": float|None, "executed_qty": float|None}
        status من قيم: "FILLED" | "NEW" | "UNKNOWN"
    """
    fills = _query_fills(Symbol, order_id, Access_Key, Secret_Key)
    details = _extract_execution_details(fills)

    if details["avg_price"] is not None:
        return {"status": "FILLED", "avg_price": details["avg_price"], "executed_qty": details["executed_qty"]}

    try:
        pending_data = _signed_get(
            PENDING_LIST_ENDPOINT, {"symbol": Symbol}, Access_Key, Secret_Key
        )
        pending_orders = pending_data if isinstance(pending_data, list) else []
        for order in pending_orders:
            if str(order.get("orderId")) == str(order_id):
                return {"status": "NEW", "avg_price": None, "executed_qty": None}
    except Exception as e:
        print(f"[Decision_Execution] ⚠️ فشل الاستعلام عن الأوامر المعلّقة: {e}")
        return {"status": "UNKNOWN", "avg_price": None, "executed_qty": None}

    return {"status": "UNKNOWN", "avg_price": None, "executed_qty": None}


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
            side       = 1,   # Sell
            order_type = 2,   # Market
            volume     = sell_qty,
            price      = 0,
            access_key = Access_Key,
            secret_key = Secret_Key
        )
        order_id = result.get("orderId")
        if not order_id:
            print("[Decision_Execution] ❌ لم يُعَد orderId من أمر البيع الطارئ.")
            return {"executed": False, "avg_price": None, "executed_qty": None}

        details = _wait_for_fills(Symbol, order_id, Access_Key, Secret_Key)
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

    المدخلات: (بدون تغيير عن التوقيع السابق)
        Decision            : str   — "ANYTHING" | "BUY" | "SELL"
        Buy_Volume          : float — نسبة USDT المستخدمة عند الشراء (0.0 → 1.0)
        My_balance          : dict  — {"quote": {...}, "base": {...}}
        Exchange_Information: dict  — قيود المنصة
        Symbol              : str   — مثال: "SOLUSDT"
        Access_Key          : str   — api-key الخاص بـ Bitunix
        Secret_Key          : str   — المفتاح السري لإنشاء التوقيع
    """

    if Decision == "ANYTHING":
        print("[Decision_Execution] القرار: ANYTHING — لا إجراء.")
        return {"executed": False, "avg_price": None, "executed_qty": None}

    quantity_scale = int(Exchange_Information.get("quantityScale", 2) or 2)
    min_qty        = float(Exchange_Information.get("minQty",       0) or 0)
    min_notional   = float(Exchange_Information.get("minNotional",  0) or 0)

    # ══════════════════════════════
    # قرار البيع — volume = كمية بالعملة الأساسية
    # ══════════════════════════════
    if Decision == "SELL":
        base_currency  = My_balance["base"]["currency"]
        base_available = float(My_balance["base"]["free"])

        if base_available <= 0:
            print(f"[Decision_Execution] لا يوجد رصيد متاح للعملة {base_currency}. تم تخطي البيع.")
            return {"executed": False, "avg_price": None, "executed_qty": None}

        sell_qty = _round_down(base_available, quantity_scale)

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
            side       = 1,   # Sell
            order_type = 2,   # Market
            volume     = sell_qty,
            price      = 0,
            access_key = Access_Key,
            secret_key = Secret_Key
        )
        order_id = result.get("orderId")
        if not order_id:
            print("[Decision_Execution] ❌ لم يُعَد orderId من أمر البيع.")
            return {"executed": False, "avg_price": None, "executed_qty": None}

        details = _wait_for_fills(Symbol, order_id, Access_Key, Secret_Key)
        return {
            "executed":     True,
            "avg_price":    details["avg_price"],
            "executed_qty": details["executed_qty"],
        }

    # ══════════════════════════════
    # قرار الشراء — volume = مبلغ بعملة التسعير (USDT) مباشرة
    # (مؤكَّد من أمثلة Bitunix الفعلية لأوامر BUY+MARKET، مطابق تماماً
    # لسلوك quoteOrderQty في MEXC — لا حاجة لتحويل المبلغ لكمية)
    # ══════════════════════════════
    elif Decision == "BUY":
        usdt_available = float(My_balance["quote"]["free"])

        if usdt_available <= 0:
            print("[Decision_Execution] لا يوجد رصيد USDT متاح. تم تخطي الشراء.")
            return {"executed": False, "avg_price": None, "executed_qty": None}

        raw_buy_usdt = usdt_available * Buy_Volume
        buy_usdt     = _round_down(raw_buy_usdt, 2)   # USDT دائماً بخانتين عشريتين

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
            symbol     = Symbol,
            side       = 2,   # Buy
            order_type = 2,   # Market
            volume     = buy_usdt,   # مبلغ USDT مباشرة عند BUY+MARKET
            price      = 0,
            access_key = Access_Key,
            secret_key = Secret_Key
        )
        order_id = result.get("orderId")
        if not order_id:
            print("[Decision_Execution] ❌ لم يُعَد orderId من أمر الشراء.")
            return {"executed": False, "avg_price": None, "executed_qty": None}

        details = _wait_for_fills(Symbol, order_id, Access_Key, Secret_Key)
        return {
            "executed":     True,
            "avg_price":    details["avg_price"],
            "executed_qty": details["executed_qty"],
        }

    else:
        print(f"[Decision_Execution] قيمة Decision غير معروفة: '{Decision}' — لا إجراء.")
        return {"executed": False, "avg_price": None, "executed_qty": None}
