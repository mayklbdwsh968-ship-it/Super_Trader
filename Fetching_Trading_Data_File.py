"""
ملف: Fetching_Trading_Data_File.py
تم تعديله للانتقال من MEXC إلى Bitunix Pro (Spot API)

ملاحظات مهمة حول الانتقال:
- Bitunix تستخدم توقيعاً مختلفاً كلياً عن MEXC: SHA256 مزدوج
  (وليس HMAC)، مع حقول Header إضافية (api-key, nonce, timestamp, sign)
  بدل تمرير المفتاح والتوقيع كـ query params كما في MEXC.
- الدومين الأساسي: https://openapi.bitunix.com
- الفوليوم (Volume): توثيق Bitunix الرسمي لنقطة الشموع لا يذكر
  اسم حقل الفوليوم بشكل قاطع (نقص معروف في توثيقهم). بناءً على أمثلة
  استجابة فعلية من نقاط مشابهة في نفس الـ API (baseVol/quoteVol)،
  أُضيفت دالة تحليل "دفاعية" (_extract_volume) تجرّب عدة أسماء محتملة
  للحقل بالترتيب، وتطبع تحذيراً واضحاً في السجل مرة واحدة فقط إن لم
  تجد أياً منها، حتى يمكن ملاحظة ذلك فوراً من Log.txt وتصحيحه بسطر
  واحد دون كسر بقية المشروع.
"""

import time
import json
import uuid
import hashlib
import requests
from datetime import datetime, timezone


# ============================================================
# المتغيرات العامة (بدون تغيير عن النسخة السابقة)
# ============================================================
All_Raw_Data = []
All_Raw_Data_HTF = []

# ============================================================
# ثوابت Bitunix API
# ============================================================
BITUNIX_BASE_URL = "https://openapi.bitunix.com"

COIN_PAIR_LIST_ENDPOINT = "/api/spot/v1/common/coin_pair/list"
KLINE_HISTORY_ENDPOINT  = "/api/spot/v1/market/kline/history"
ACCOUNT_ENDPOINT        = "/api/spot/v1/user/account"

KLINES_LIMIT   = 151   # نطلب 151 لأنه سيُحذف آخر شمعة قد تكون غير مكتملة → يبقى 150
CANDLES_COUNT  = 150
TIMEFRAME      = "1"   # فريم العمل الأساسي عند Bitunix: "1" يعني 1 دقيقة
                        # (قيم Bitunix المتاحة: 1,3,5,15,30,60,120,240,360,720,D,M,W)

# ── إعدادات فريم الدعم الأعلى (HTF) ─────
HTF_TIMEFRAME     = "60"   # 60 دقيقة (ساعة) — عند Bitunix تُكتب "60" وليس "60m"
HTF_KLINES_LIMIT  = 101
HTF_CANDLES_COUNT = 100

# ── علم داخلي: هل طُبعت رسالة تحذير الفوليوم من قبل؟ (لتفادي تكرارها كل دورة) ──
_volume_warning_printed = False


# ============================================================
# دوال التوقيع الخاصة بـ Bitunix
# ============================================================
def _get_timestamp_ms():
    """الوقت الحالي بالمللي ثانية (نص، كما تتطلبه Bitunix في الـ Header)"""
    return str(int(time.time() * 1000))


def _gen_nonce():
    """سلسلة عشوائية 32 حرفاً كما يتطلب Bitunix"""
    return uuid.uuid4().hex


def _sign(nonce, timestamp, api_key, secret_key, query_params=None, body_obj=None):
    """
    توقيع Bitunix (مزدوج SHA256):
        queryParams: كل معاملات الـ query مرتّبة تصاعدياً حسب المفتاح (ASCII)
                     ومُلصقة كـ key+value بدون فواصل أو علامات '='
        body       : كائن الـ JSON مضغوطاً كنص (بدون مسافات) إن وُجد، وإلا نص فارغ
        digest = SHA256(nonce + timestamp + api-key + queryParams + body)
        sign   = SHA256(digest + secretKey)
    """
    if query_params:
        query_str = "".join(
            f"{k}{v}" for k, v in sorted(query_params.items(), key=lambda kv: kv[0])
        )
    else:
        query_str = ""

    if body_obj:
        body_str = json.dumps(body_obj, separators=(',', ':'), ensure_ascii=False)
    else:
        body_str = ""

    digest_input = f"{nonce}{timestamp}{api_key}{query_str}{body_str}"
    digest = hashlib.sha256(digest_input.encode('utf-8')).hexdigest()
    sign_input = f"{digest}{secret_key}"
    return hashlib.sha256(sign_input.encode('utf-8')).hexdigest()


def _auth_headers(Access_Key, Secret_Key, query_params=None, body_obj=None):
    nonce     = _gen_nonce()
    timestamp = _get_timestamp_ms()
    sign      = _sign(nonce, timestamp, Access_Key, Secret_Key, query_params, body_obj)
    return {
        "api-key":     Access_Key,
        "nonce":       nonce,
        "timestamp":   timestamp,
        "sign":        sign,
        "Content-Type": "application/json",
    }


def _is_success(result: dict) -> bool:
    """نجاح الطلب عند Bitunix: code == 0 أو "0" (قد تُعاد كنص أو رقم)"""
    return str(result.get("code")) == "0"


# ============================================================
# دوال الطلبات (عامة / موقّعة) مع إعادة محاولة تلقائية
# ============================================================
def _public_get(endpoint, params=None, retries=5, timeout=30):
    if params is None:
        params = {}
    url = f"{BITUNIX_BASE_URL}{endpoint}"

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            result = response.json()
            if not _is_success(result):
                raise RuntimeError(f"❌ رد خطأ من Bitunix عند {endpoint}: {result}")
            return result.get("data")
        except requests.exceptions.HTTPError as e:
            body = e.response.text if e.response is not None else "(لا يوجد رد)"
            print(f"❌ خطأ HTTP من Bitunix عند {endpoint}: {e} | تفاصيل الرد: {body}")
            raise RuntimeError(f"❌ فشل الطلب العام ({endpoint}): {body}")
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            if attempt < retries:
                wait = attempt * 3
                print(f"⚠️  طلب عام فشل (محاولة {attempt}/{retries}) — إعادة بعد {wait}ث: {e}")
                time.sleep(wait)
            else:
                raise RuntimeError(f"❌ فشل الطلب العام بعد {retries} محاولات: {e}")


def _signed_get(endpoint, Access_Key, Secret_Key, params=None, retries=5, timeout=30):
    if params is None:
        params = {}
    url = f"{BITUNIX_BASE_URL}{endpoint}"

    for attempt in range(1, retries + 1):
        try:
            headers = _auth_headers(Access_Key, Secret_Key, query_params=params, body_obj=None)
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            result = response.json()
            if not _is_success(result):
                raise RuntimeError(f"❌ رد خطأ من Bitunix عند {endpoint}: {result}")
            return result.get("data")
        except requests.exceptions.HTTPError as e:
            body = e.response.text if e.response is not None else "(لا يوجد رد)"
            print(f"❌ خطأ HTTP موقّع من Bitunix عند {endpoint}: {e} | تفاصيل الرد: {body}")
            raise RuntimeError(f"❌ فشل الطلب الموقّع ({endpoint}): {body}")
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            if attempt < retries:
                wait = attempt * 3
                print(f"⚠️  طلب موقّع فشل (محاولة {attempt}/{retries}) — إعادة بعد {wait}ث: {e}")
                time.sleep(wait)
            else:
                raise RuntimeError(f"❌ فشل الطلب الموقّع بعد {retries} محاولات: {e}")


# ============================================================
# دوال مساعدة لتحليل الشموع (دفاعية بخصوص أسماء الحقول)
# ============================================================
def _extract_ts_ms(candle: dict) -> int:
    """
    يحاول استخراج التوقيت من عدة أسماء محتملة للحقل (ts / time)،
    ويتعامل مع كلا الشكلين: رقم (ثواني أو مللي ثانية) أو نص ISO8601.
    """
    raw = candle.get("ts", candle.get("time"))

    if isinstance(raw, (int, float)):
        val = int(raw)
        # إن كانت القيمة تبدو بالثواني (أقل من 10^12) نحوّلها لمللي ثانية
        if val < 10**12:
            val *= 1000
        return val

    if isinstance(raw, str):
        # قد تكون رقماً بصيغة نصية
        try:
            val = int(raw)
            if val < 10**12:
                val *= 1000
            return val
        except ValueError:
            pass
        # أو صيغة ISO8601
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except ValueError:
            pass

    # فشل كل المحاولات — نستخدم الوقت الحالي كحل أخير (لن يحدث عادة)
    print(f"⚠️ تعذّر تحليل توقيت الشمعة: {candle} — استُخدم الوقت الحالي.")
    return int(time.time() * 1000)


def _extract_volume(candle: dict) -> float:
    """
    دالة دفاعية: تجرّب عدة أسماء محتملة لحقل الفوليوم بالترتيب.
    إن لم يُعثر على أي منها، تطبع تحذيراً واضحاً (مرة واحدة فقط طوال
    عمر التشغيل) وتُعيد 0.0 كحل مؤقت غير مُعطِّل للمشروع.
    """
    global _volume_warning_printed

    for key in ("baseVol", "vol", "volume", "amount", "quoteVol"):
        if key in candle and candle[key] is not None:
            try:
                return float(candle[key])
            except (ValueError, TypeError):
                continue

    if not _volume_warning_printed:
        print(
            "⚠️⚠️⚠️ [تحذير هام] لم يُعثر على أي حقل فوليوم معروف "
            f"(baseVol/vol/volume/amount/quoteVol) داخل بيانات الشمعة القادمة "
            f"من Bitunix. شكل الشمعة الفعلي: {candle} — "
            "الفوليوم سيُسجَّل كـ 0.0 مؤقتاً. الرجاء نسخ شكل الشمعة أعلاه "
            "من Log.txt وإرساله لتصحيح اسم الحقل."
        )
        _volume_warning_printed = True

    return 0.0


def _parse_klines(klines_data):
    """
    تُحوّل استجابة klines من Bitunix (قائمة كائنات) إلى قائمة شموع
    منسّقة [timestamp, open, high, low, close, volume] مرتّبة من
    الأقدم إلى الأحدث — لتبقى بنية البيانات مطابقة تماماً لما كانت
    عليه مع MEXC، دون أي حاجة لتعديل باقي ملفات المشروع.
    """
    candles = []
    if not klines_data or not isinstance(klines_data, list):
        return candles

    for candle in klines_data:
        try:
            timestamp = _extract_ts_ms(candle)
            open_p    = float(candle["open"])
            high_p    = float(candle["high"])
            low_p     = float(candle["low"])
            close_p   = float(candle["close"])
            volume_p  = _extract_volume(candle)
            candles.append([timestamp, open_p, high_p, low_p, close_p, volume_p])
        except (KeyError, ValueError, TypeError) as e:
            print(f"⚠️ تخطي شمعة غير صالحة: {candle} — الخطأ: {e}")
            continue

    candles.sort(key=lambda x: x[0])
    return candles


# ============================================================
# الدالة الأولى: Fetching_Trading_Data_1
# ============================================================
def Fetching_Trading_Data_1(Symbol, Access_Key, Secret_Key):
    """
    تجلب:
    1. معلومات الزوج (Exchange Information) من Bitunix
    2. آخر 150 شمعة على فريم 1 دقيقة وتحفظها في All_Raw_Data
    3. آخر 100 شمعة HTF (60 دقيقة) وتحفظها في All_Raw_Data_HTF
    مخرجات: Exchange_Information
    """
    global All_Raw_Data
    global All_Raw_Data_HTF

    # ============================================================
    # الجزء 1: جلب قائمة أزواج التداول واستخراج الزوج المطلوب
    # ============================================================
    print("⏳ جلب بيانات أزواج التداول من Bitunix...")

    pairs_data = _public_get(COIN_PAIR_LIST_ENDPOINT, params={})

    if not pairs_data or not isinstance(pairs_data, list):
        raise ValueError("❌ استجابة غير صالحة من Bitunix عند جلب قائمة الأزواج")

    pair_info = None
    for p in pairs_data:
        combined = f"{p.get('base', '')}{p.get('quote', '')}"
        if combined == Symbol:
            pair_info = p
            break

    if pair_info is None:
        raise ValueError(f"❌ الزوج '{Symbol}' غير موجود في قائمة أزواج Bitunix")

    try:
        price_scale    = int(pair_info.get("quotePrecision", 8) or 8)
        quantity_scale = int(pair_info.get("basePrecision", 8) or 8)
        # ── ملاحظة مهمة: تأكيد من مثال استجابة رسمي فعلي لـ Bitunix ──
        # minPrice  = الحد الأدنى لقيمة الصفقة (بعملة التسعير/quote) → يقابل minNotional في MEXC
        # minVolume = الحد الأدنى للكمية (بالعملة الأساسية/base)     → يقابل minQty في MEXC
        min_notional = float(pair_info.get("minPrice", 0) or 0)
        min_qty      = float(pair_info.get("minVolume", 0) or 0)
    except (ValueError, TypeError) as e:
        raise ValueError(f"❌ خطأ في تحليل بيانات الزوج من Bitunix: {e}")

    Exchange_Information = {
        "priceScale"   : price_scale,
        "quantityScale": quantity_scale,
        "minPrice"     : None,   # Bitunix لا توفر حداً أدنى/أقصى للسعر في هذه النقطة
        "maxPrice"     : None,
        "minQty"       : min_qty,
        "maxQty"       : None,   # Bitunix لا توفر حداً أقصى للكمية في هذه النقطة
        "minNotional"  : min_notional
    }

    print(f"✅ Exchange Information للزوج {Symbol}:")
    for k, v in Exchange_Information.items():
        print(f"   {k}: {v}")

    # ============================================================
    # الجزء 2: جلب آخر 150 شمعة (فريم 1 دقيقة)
    # ============================================================
    print(f"\n⏳ جلب آخر {KLINES_LIMIT} شمعة للزوج {Symbol}...")

    klines_data = _public_get(
        KLINE_HISTORY_ENDPOINT,
        params={
            "symbol"  : Symbol,
            "interval": TIMEFRAME,
            "limit"   : KLINES_LIMIT
        }
    )

    raw_candles = _parse_klines(klines_data)

    # حذف آخر شمعة لأنها قد تكون مفتوحة (غير مكتملة) — نفس احتياط MEXC
    if len(raw_candles) > 0:
        raw_candles = raw_candles[:-1]

    if len(raw_candles) < CANDLES_COUNT:
        raise ValueError(
            f"❌ عدد الشموع غير كافٍ: {len(raw_candles)} (المطلوب {CANDLES_COUNT})"
        )

    raw_candles = raw_candles[-CANDLES_COUNT:]
    All_Raw_Data = raw_candles

    print(f"✅ تم تحديث All_Raw_Data — عدد الشموع: {len(All_Raw_Data)}")

    # ============================================================
    # الجزء 3: جلب شموع فريم أعلى (HTF)
    # ============================================================
    print(f"\n⏳ جلب آخر {HTF_KLINES_LIMIT} شمعة ({HTF_TIMEFRAME} دقيقة) "
          f"للزوج {Symbol} (لتحديد مناطق الدعم)...")

    htf_klines_data = _public_get(
        KLINE_HISTORY_ENDPOINT,
        params={
            "symbol"  : Symbol,
            "interval": HTF_TIMEFRAME,
            "limit"   : HTF_KLINES_LIMIT
        }
    )

    htf_candles = _parse_klines(htf_klines_data)

    if len(htf_candles) > 0:
        htf_candles = htf_candles[:-1]

    if len(htf_candles) < HTF_CANDLES_COUNT:
        raise ValueError(
            f"❌ عدد شموع HTF غير كافٍ: {len(htf_candles)} "
            f"(المطلوب {HTF_CANDLES_COUNT})"
        )

    htf_candles = htf_candles[-HTF_CANDLES_COUNT:]
    All_Raw_Data_HTF = htf_candles

    print(f"✅ تم تحديث All_Raw_Data_HTF — عدد شموع {HTF_TIMEFRAME}m: "
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

    if len(All_Raw_Data) == 0:
        raise RuntimeError(
            "❌ All_Raw_Data فارغ — يجب تشغيل Fetching_Trading_Data_1 أولاً"
        )
    if len(All_Raw_Data_HTF) == 0:
        raise RuntimeError(
            "❌ All_Raw_Data_HTF فارغ — يجب تشغيل Fetching_Trading_Data_1 أولاً"
        )

    # ============================================================
    # الجزء 1: جلب آخر شمعة مكتملة (فريم العمل الأساسي)
    # ============================================================
    print("⏳ جلب آخر شمعة مكتملة...")

    klines_data = _public_get(
        KLINE_HISTORY_ENDPOINT,
        params={"symbol": Symbol, "interval": TIMEFRAME, "limit": 2}
    )

    candles = _parse_klines(klines_data)
    if len(candles) < 2:
        raise ValueError("❌ استجابة غير صالحة من Bitunix عند جلب آخر شمعة")

    # نأخذ الشمعة الأولى (قبل الأخيرة) لأنها مكتملة بالتأكيد
    new_candle = candles[0]
    timestamp  = new_candle[0]

    if All_Raw_Data[-1][0] != timestamp:
        All_Raw_Data.append(new_candle)
        while len(All_Raw_Data) > CANDLES_COUNT:
            All_Raw_Data.pop(0)
        print(f"✅ تم تحديث All_Raw_Data — عدد الشموع: {len(All_Raw_Data)}")
    else:
        print(f"⚠️ الشمعة موجودة مسبقاً (timestamp: {timestamp}) — لم يتم التحديث")

    Raw_Data = All_Raw_Data.copy()

    # ============================================================
    # الجزء 2: جلب آخر شمعة HTF مكتملة
    # ============================================================
    print(f"⏳ جلب آخر شمعة HTF ({HTF_TIMEFRAME} دقيقة) مكتملة...")

    htf_klines_data = _public_get(
        KLINE_HISTORY_ENDPOINT,
        params={"symbol": Symbol, "interval": HTF_TIMEFRAME, "limit": 2}
    )

    htf_candles_parsed = _parse_klines(htf_klines_data)
    if len(htf_candles_parsed) < 2:
        raise ValueError("❌ استجابة غير صالحة من Bitunix عند جلب آخر شمعة HTF")

    new_htf_candle = htf_candles_parsed[0]
    htf_timestamp   = new_htf_candle[0]

    if All_Raw_Data_HTF[-1][0] != htf_timestamp:
        All_Raw_Data_HTF.append(new_htf_candle)
        while len(All_Raw_Data_HTF) > HTF_CANDLES_COUNT:
            All_Raw_Data_HTF.pop(0)
        print(f"✅ تم تحديث All_Raw_Data_HTF — عدد شموع {HTF_TIMEFRAME}m: "
              f"{len(All_Raw_Data_HTF)}")
    else:
        print(f"⚠️ شمعة HTF موجودة مسبقاً (timestamp: {htf_timestamp}) "
              f"— لم يتم التحديث")

    Raw_Data_HTF = All_Raw_Data_HTF.copy()

    # ============================================================
    # الجزء 3: جلب رصيد العملتين
    # ============================================================
    print("\n⏳ جلب رصيد الحساب...")

    quote_currency = "USDT"
    base_currency  = Symbol.replace(quote_currency, "")

    balance_data = _signed_get(ACCOUNT_ENDPOINT, Access_Key, Secret_Key, params={})

    quote_free = 0.0
    base_free  = 0.0

    if balance_data and isinstance(balance_data, list):
        for asset in balance_data:
            try:
                name    = asset.get("coin", "")
                total   = float(asset.get("balance", 0))
                locked  = float(asset.get("balanceLocked", 0))
                # ── ملاحظة: "balance" في Bitunix هو الرصيد الكلي، و
                # "balanceLocked" هو الجزء المحجوز (داخل أوامر مفتوحة).
                # "free" (المتاح فعلياً) = الكلي - المحجوز، بنفس معنى
                # حقل "free" في MEXC الذي اعتمد عليه باقي المشروع.
                free = total - locked
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
