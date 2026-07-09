import time
import hmac
import hashlib
import requests


# ============================================================
# المتغير العام — يُحفظ في الذاكرة طوال فترة تشغيل البرنامج
# يُستبدل عند كل تنفيذ لـ Fetching_Trading_Data_1
# ============================================================
All_Raw_Data = []

# ============================================================
# متغير عام إضافي — شموع فريم أعلى (HTF) لتحديد مناطق الدعم بدقة
# أكبر مما يسمح به فريم العمل الأساسي (1m). يُدار بنفس منطق
# All_Raw_Data تماماً (تحديث أوّلي كامل ثم تحديث تراكمي كل دورة).
# ============================================================
All_Raw_Data_HTF = []


# ============================================================
# ثوابت MEXC API
# ============================================================
MEXC_BASE_URL  = "https://api.mexc.com"
KLINES_LIMIT   = 151   # نطلب 151 لأنه سيُحذف آخر شمعة غير مكتملة → يبقى 150
CANDLES_COUNT  = 150   # عدد الشموع المحفوظة في All_Raw_Data
TIMEFRAME      = "1m"

# ── إعدادات فريم الدعم الأعلى (HTF) ─────
# يُستخدم فقط لتحديد مناطق الدعم بدقة أكبر من فريم 1m (أقل ضجيجاً).
# ملاحظة مهمة: MEXC لا تقبل القيمة "1h" في هذا المسار من الـ API —
# القيمة الصحيحة لفريم الساعة في MEXC هي "60m" حرفياً (وليس "1h"
# كما في منصات أخرى). القيم المتاحة: 1m, 5m, 15m, 30m, 60m, 4h, 1d,
# 1W, 1M. يمكن تغييرها إلى "15m" حسب الحاجة دون تعديل أي منطق آخر.
HTF_TIMEFRAME     = "60m"
HTF_KLINES_LIMIT  = 101   # نطلب 101 لحذف آخر شمعة غير مكتملة → يبقى 100
HTF_CANDLES_COUNT = 100   # عدد شموع HTF المحفوظة في All_Raw_Data_HTF


# ============================================================
# دوال مساعدة
# ============================================================
def _get_timestamp():
    """يُعيد الوقت الحالي بالمللي ثانية"""
    return int(time.time() * 1000)


def _sign(secret_key, params_str):
    """يحسب توقيع HMAC-SHA256"""
    return hmac.new(
        secret_key.encode('utf-8'),
        params_str.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def _signed_request(method, endpoint, Access_Key, Secret_Key, params=None,
                    retries=5, timeout=30):
    """
    يُرسل طلباً موقّعاً إلى MEXC API
    يُعيد المحاولة تلقائياً عند timeout أو خطأ شبكة
    ملاحظة: يُعاد بناء التوقيع في كل محاولة لأن timestamp يتغير

    recvWindow=10000: هامش أمان أكبر من الافتراضي (5000) يتحمّل فرق
    توقيت بسيط بين الجهاز وخادم MEXC (شائع على Termux/Android).
    هذا لا يُغني عن ضبط توقيت الجهاز، فقط يقلل حساسية الطلب له.
    (رُفع لاحقاً إلى 20000 بسبب تكرار خطأ 700003 مع اتصال غير مستقر)
    """
    if params is None:
        params = {}

    url     = f"{MEXC_BASE_URL}{endpoint}"
    headers = {"X-MEXC-APIKEY": Access_Key}

    for attempt in range(1, retries + 1):
        try:
            attempt_params = dict(params)
            attempt_params['timestamp']  = _get_timestamp()
            attempt_params.setdefault('recvWindow', 20000)

            query_str = '&'.join(
                f"{k}={v}" for k, v in sorted(attempt_params.items())
            )
            signature = _sign(Secret_Key, query_str)
            full_url  = f"{url}?{query_str}&signature={signature}"

            if method.upper() == "GET":
                response = requests.get(full_url, headers=headers, timeout=timeout)
            else:
                response = requests.post(full_url, headers=headers, timeout=timeout)

            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            # نطبع محتوى الرد الفعلي من MEXC (يحتوي code/msg الحقيقي) —
            # بدونه لا نعرف السبب الدقيق (توقيع/صلاحيات/توقيت/...)
            body = e.response.text if e.response is not None else "(لا يوجد رد)"

            # ── حالة خاصة: خطأ التوقيت (700003) ─────
            # "Timestamp for this request is outside of the recvWindow"
            # هذا الخطأ غالباً عابر (تأخر شبكة بسيط بين إنشاء الطلب
            # ووصوله لخادم MEXC، شائع على اتصالات ضعيفة/غير مستقرة)
            # وليس خطأ دائماً كالتوقيع الخاطئ أو رصيد غير كافٍ. لذلك
            # يستحق إعادة محاولة بتوقيت جديد بدل الاستسلام الفوري —
            # فرق عن باقي أخطاء HTTP التي لا تُصلحها إعادة المحاولة.
            if "700003" in body and attempt < retries:
                wait = attempt * 3
                print(
                    f"⚠️  خطأ توقيت (700003) من MEXC عند {endpoint} "
                    f"(محاولة {attempt}/{retries}) — إعادة بتوقيت جديد بعد {wait}ث"
                )
                time.sleep(wait)
                continue

            print(f"❌ خطأ HTTP من MEXC عند {endpoint}: {e} | تفاصيل الرد: {body}")
            raise RuntimeError(f"❌ فشل الطلب الموقّع ({endpoint}): {body}")

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            if attempt < retries:
                wait = attempt * 3
                print(f"⚠️  طلب موقّع فشل (محاولة {attempt}/{retries}) — إعادة بعد {wait}ث: {e}")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"❌ فشل الطلب الموقّع بعد {retries} محاولات: {e}"
                )


def _public_request(endpoint, params=None, retries=5, timeout=30):
    """
    يُرسل طلباً عاماً (بدون توقيع) إلى MEXC API
    يُعيد المحاولة تلقائياً عند timeout أو خطأ شبكة
    """
    if params is None:
        params = {}

    url = f"{MEXC_BASE_URL}{endpoint}"

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            if attempt < retries:
                wait = attempt * 3
                print(f"⚠️  طلب عام فشل (محاولة {attempt}/{retries}) — إعادة بعد {wait}ث: {e}")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"❌ فشل الطلب العام بعد {retries} محاولات: {e}"
                )


def _parse_klines(klines_response):
    """
    تُحوّل استجابة klines الخام من MEXC إلى قائمة شموع منسّقة
    [timestamp, open, high, low, close, volume] مرتّبة من الأقدم
    إلى الأحدث. تُستخدم لكل من فريم العمل الأساسي وفريم HTF.
    """
    candles = []
    for candle in klines_response:
        try:
            timestamp = int(candle[0])
            open_p    = float(candle[1])
            high_p    = float(candle[2])
            low_p     = float(candle[3])
            close_p   = float(candle[4])
            volume_p  = float(candle[5])
            candles.append([timestamp, open_p, high_p,
                             low_p, close_p, volume_p])
        except (IndexError, ValueError, TypeError):
            continue

    candles.sort(key=lambda x: x[0])
    return candles


# ============================================================
# الدالة الأولى: Fetching_Trading_Data_1
# ============================================================
def Fetching_Trading_Data_1(Symbol, Access_Key, Secret_Key):
    """
    تجلب:
    1. Exchange Information للزوج Symbol
    2. آخر 150 شمعة على الفريم 1m وتحفظها في All_Raw_Data
    مخرجات: Exchange_Information
    """
    global All_Raw_Data
    global All_Raw_Data_HTF

    # ============================================================
    # الجزء 1: جلب Exchange Information
    # ============================================================
    print("⏳ جلب Exchange Information...")

    ei_response = _public_request(
        "/api/v3/exchangeInfo",
        params={"symbol": Symbol}
    )

    # استخراج بيانات الزوج المطلوب
    symbol_info = None
    for s in ei_response.get("symbols", []):
        if s.get("symbol") == Symbol:
            symbol_info = s
            break

    if symbol_info is None:
        raise ValueError(f"❌ الزوج '{Symbol}' غير موجود في Exchange Information")

    # استخراج القيم المطلوبة من filters
    price_scale    = symbol_info.get("quotePrecision",     8)
    quantity_scale = symbol_info.get("baseAssetPrecision", 8)
    min_price      = None
    max_price      = None
    min_qty        = None
    max_qty        = None
    min_notional   = None

    for f in symbol_info.get("filters", []):
        filter_type = f.get("filterType", "")

        if filter_type == "PRICE_FILTER":
            min_price = float(f.get("minPrice", 0))
            max_price = float(f.get("maxPrice", 0))

        elif filter_type == "LOT_SIZE":
            min_qty = float(f.get("minQty", 0))
            max_qty = float(f.get("maxQty", 0))

        elif filter_type == "MIN_NOTIONAL":
            min_notional = float(f.get("minNotional", 0))

    Exchange_Information = {
        "priceScale"   : price_scale,
        "quantityScale": quantity_scale,
        "minPrice"     : min_price,
        "maxPrice"     : max_price,
        "minQty"       : min_qty,
        "maxQty"       : max_qty,
        "minNotional"  : min_notional
    }

    print(f"✅ Exchange Information للزوج {Symbol}:")
    for k, v in Exchange_Information.items():
        print(f"   {k}: {v}")

    # ============================================================
    # الجزء 2: جلب آخر 150 شمعة
    # ============================================================
    print(f"\n⏳ جلب آخر {KLINES_LIMIT} شمعة للزوج {Symbol}...")

    klines_response = _public_request(
        "/api/v3/klines",
        params={
            "symbol"  : Symbol,
            "interval": TIMEFRAME,
            "limit"   : KLINES_LIMIT
        }
    )

    if not klines_response or not isinstance(klines_response, list):
        raise ValueError("❌ استجابة غير صالحة من MEXC عند جلب الشموع")

    # بناء All_Raw_Data
    # استجابة klines من MEXC:
    # [0]=openTime [1]=open [2]=high [3]=low [4]=close [5]=volume ...
    raw_candles = _parse_klines(klines_response)

    # حذف آخر شمعة لأنها قد تكون مفتوحة (غير مكتملة)
    if len(raw_candles) > 0:
        raw_candles = raw_candles[:-1]

    # التأكد من وجود 150 شمعة على الأقل
    if len(raw_candles) < CANDLES_COUNT:
        raise ValueError(
            f"❌ عدد الشموع غير كافٍ: {len(raw_candles)} (المطلوب {CANDLES_COUNT})"
        )

    # الاحتفاظ بآخر CANDLES_COUNT شمعة فقط
    raw_candles = raw_candles[-CANDLES_COUNT:]

    # تحديث المتغير العام
    All_Raw_Data = raw_candles

    print(f"✅ تم تحديث All_Raw_Data — عدد الشموع: {len(All_Raw_Data)}")

    # ============================================================
    # الجزء 3: جلب شموع فريم أعلى (HTF) لتحديد مناطق الدعم بدقة أكبر
    # (نفس منطق الجزء 2 تماماً، لكن بفريم/عدد مختلفين)
    # ============================================================
    print(f"\n⏳ جلب آخر {HTF_KLINES_LIMIT} شمعة ({HTF_TIMEFRAME}) "
          f"للزوج {Symbol} (لتحديد مناطق الدعم)...")

    htf_klines_response = _public_request(
        "/api/v3/klines",
        params={
            "symbol"  : Symbol,
            "interval": HTF_TIMEFRAME,
            "limit"   : HTF_KLINES_LIMIT
        }
    )

    if not htf_klines_response or not isinstance(htf_klines_response, list):
        raise ValueError("❌ استجابة غير صالحة من MEXC عند جلب شموع HTF")

    htf_candles = _parse_klines(htf_klines_response)

    if len(htf_candles) > 0:
        htf_candles = htf_candles[:-1]

    if len(htf_candles) < HTF_CANDLES_COUNT:
        raise ValueError(
            f"❌ عدد شموع HTF غير كافٍ: {len(htf_candles)} "
            f"(المطلوب {HTF_CANDLES_COUNT})"
        )

    htf_candles = htf_candles[-HTF_CANDLES_COUNT:]

    All_Raw_Data_HTF = htf_candles

    print(f"✅ تم تحديث All_Raw_Data_HTF — عدد شموع {HTF_TIMEFRAME}: "
          f"{len(All_Raw_Data_HTF)}")

    return Exchange_Information


# ============================================================
# الدالة الثانية: Fetching_Trading_Data_2
# ============================================================
def Fetching_Trading_Data_2(Symbol, Access_Key, Secret_Key):
    """
    تجلب:
    1. آخر شمعة مكتملة (فريم العمل الأساسي) وتُضيفها إلى All_Raw_Data
    2. آخر شمعة HTF مكتملة (إن تغيّرت) وتُضيفها إلى All_Raw_Data_HTF
    3. رصيد العملتين (Base و Quote) للزوج المحدد
    مخرجات: Raw_Data, Raw_Data_HTF, My_balance

    My_balance = {
        "quote": {"currency": "USDT", "free": float},
        "base" : {"currency": "SOL",  "free": float}
    }
    """
    global All_Raw_Data
    global All_Raw_Data_HTF

    # ============================================================
    # التحقق المبدئي
    # ============================================================
    if len(All_Raw_Data) == 0:
        raise RuntimeError(
            "❌ All_Raw_Data فارغ — يجب تشغيل Fetching_Trading_Data_1 أولاً"
        )

    if len(All_Raw_Data_HTF) == 0:
        raise RuntimeError(
            "❌ All_Raw_Data_HTF فارغ — يجب تشغيل Fetching_Trading_Data_1 أولاً"
        )

    # ============================================================
    # الجزء 1: جلب آخر شمعة مكتملة
    # ============================================================
    print("⏳ جلب آخر شمعة مكتملة...")

    # نجلب آخر شمعتين لضمان أن الأولى مكتملة
    klines_response = _public_request(
        "/api/v3/klines",
        params={
            "symbol"  : Symbol,
            "interval": TIMEFRAME,
            "limit"   : 2
        }
    )

    if (not klines_response
            or not isinstance(klines_response, list)
            or len(klines_response) < 2):
        raise ValueError("❌ استجابة غير صالحة من MEXC عند جلب آخر شمعة")

    # نأخذ الشمعة الأولى (قبل الأخيرة) لأنها مكتملة بالتأكيد
    candle = klines_response[0]

    try:
        timestamp  = int(candle[0])
        open_p     = float(candle[1])
        high_p     = float(candle[2])
        low_p      = float(candle[3])
        close_p    = float(candle[4])
        volume_p   = float(candle[5])
        new_candle = [timestamp, open_p, high_p, low_p, close_p, volume_p]
    except (IndexError, ValueError, TypeError) as e:
        raise ValueError(f"❌ خطأ في تحليل بيانات الشمعة: {e}")

    # ============================================================
    # الجزء 2: تحديث All_Raw_Data
    # إضافة الشمعة الجديدة في النهاية
    # حذف أول شمعة للحفاظ على CANDLES_COUNT
    # ============================================================
    if All_Raw_Data[-1][0] != timestamp:
        All_Raw_Data.append(new_candle)
        # الحفاظ على CANDLES_COUNT شمعة بالضبط
        while len(All_Raw_Data) > CANDLES_COUNT:
            All_Raw_Data.pop(0)
        print(f"✅ تم تحديث All_Raw_Data — عدد الشموع: {len(All_Raw_Data)}")
    else:
        print(f"⚠️ الشمعة موجودة مسبقاً (timestamp: {timestamp}) — لم يتم التحديث")

    Raw_Data = All_Raw_Data.copy()

    # ============================================================
    # الجزء 2 (تابع): جلب آخر شمعة HTF مكتملة وتحديث All_Raw_Data_HTF
    # (نفس منطق تحديث All_Raw_Data تماماً، لكن على فريم HTF)
    # ============================================================
    print(f"⏳ جلب آخر شمعة HTF ({HTF_TIMEFRAME}) مكتملة...")

    htf_klines_response = _public_request(
        "/api/v3/klines",
        params={
            "symbol"  : Symbol,
            "interval": HTF_TIMEFRAME,
            "limit"   : 2
        }
    )

    if (not htf_klines_response
            or not isinstance(htf_klines_response, list)
            or len(htf_klines_response) < 2):
        raise ValueError("❌ استجابة غير صالحة من MEXC عند جلب آخر شمعة HTF")

    htf_candle = htf_klines_response[0]

    try:
        htf_timestamp  = int(htf_candle[0])
        htf_open_p     = float(htf_candle[1])
        htf_high_p     = float(htf_candle[2])
        htf_low_p      = float(htf_candle[3])
        htf_close_p    = float(htf_candle[4])
        htf_volume_p   = float(htf_candle[5])
        new_htf_candle = [htf_timestamp, htf_open_p, htf_high_p,
                           htf_low_p, htf_close_p, htf_volume_p]
    except (IndexError, ValueError, TypeError) as e:
        raise ValueError(f"❌ خطأ في تحليل بيانات شمعة HTF: {e}")

    if All_Raw_Data_HTF[-1][0] != htf_timestamp:
        All_Raw_Data_HTF.append(new_htf_candle)
        while len(All_Raw_Data_HTF) > HTF_CANDLES_COUNT:
            All_Raw_Data_HTF.pop(0)
        print(f"✅ تم تحديث All_Raw_Data_HTF — عدد شموع {HTF_TIMEFRAME}: "
              f"{len(All_Raw_Data_HTF)}")
    else:
        print(f"⚠️ شمعة HTF موجودة مسبقاً (timestamp: {htf_timestamp}) "
              f"— لم يتم التحديث")

    Raw_Data_HTF = All_Raw_Data_HTF.copy()

    # ============================================================
    # الجزء 3: جلب رصيد العملتين فقط
    # ============================================================
    print("\n⏳ جلب رصيد الحساب...")

    # استخراج العملتين من Symbol
    # مثال: SOLUSDT → base=SOL، quote=USDT
    quote_currency = "USDT"
    base_currency  = Symbol.replace(quote_currency, "")

    balance_response = _signed_request(
        method     = "GET",
        endpoint   = "/api/v3/account",
        Access_Key = Access_Key,
        Secret_Key = Secret_Key,
        params     = {}
    )

    quote_free = 0.0
    base_free  = 0.0

    for asset in balance_response.get("balances", []):
        try:
            name = asset.get("asset", "")
            free = float(asset.get("free", 0))
            if name == quote_currency:
                quote_free = free
            elif name == base_currency:
                base_free = free
        except (ValueError, TypeError):
            continue

    My_balance = {
        "quote": {"currency": quote_currency, "free": quote_free},
        "base" : {"currency": base_currency,  "free": base_free}
    }

    print(f"✅ الرصيد المتاح:")
    print(f"   {quote_currency}: {quote_free}")
    print(f"   {base_currency} : {base_free}")

    return Raw_Data, Raw_Data_HTF, My_balance
