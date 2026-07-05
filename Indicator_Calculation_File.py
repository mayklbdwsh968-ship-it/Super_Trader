"""
ملف: Indicator_Calculation_File.py
الوظيفة: حساب المؤشرات الفنية على بيانات الشموع وإرجاع Final_Data
المسار: Super_Trader/Indicator_Calculation_File.py
"""


# ══════════════════════════════════════════════
#   دوال حساب المؤشرات (stdlib فقط — بدون pandas/ta-lib)
# ══════════════════════════════════════════════

def _calc_ema(values: list, period: int) -> list:
    """
    يحسب EMA على قائمة قيم.
    يُعيد قائمة بنفس الطول — القيم الأولى (قبل اكتمال الـ period) تكون None.
    """
    result = [None] * len(values)
    if len(values) < period:
        return result

    k = 2.0 / (period + 1)

    # أول قيمة EMA = المتوسط البسيط للـ period الأولى
    sma = sum(values[:period]) / period
    result[period - 1] = sma

    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)

    return result


def _calc_rsi(closes: list, period: int) -> list:
    """
    يحسب RSI على قائمة أسعار الإغلاق.
    يُعيد قائمة بنفس الطول — القيم الأولى تكون None.
    """
    result = [None] * len(closes)
    if len(closes) < period + 1:
        return result

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    # أول متوسط = SMA للـ period الأولى
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi_from_avg(ag, al):
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - (100.0 / (1 + rs))

    result[period] = _rsi_from_avg(avg_gain, avg_loss)

    for i in range(period + 1, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        result[i] = _rsi_from_avg(avg_gain, avg_loss)

    return result


def _calc_macd(closes: list, fast: int, slow: int, signal: int):
    """
    يحسب MACD Line و Signal Line و Histogram.
    يُعيد ثلاث قوائم: (macd_line, signal_line, histogram) بنفس طول closes.
    القيم غير المكتملة تكون None.
    """
    ema_fast   = _calc_ema(closes, fast)
    ema_slow   = _calc_ema(closes, slow)

    macd_line = []
    for f, s in zip(ema_fast, ema_slow):
        if f is None or s is None:
            macd_line.append(None)
        else:
            macd_line.append(f - s)

    # نحسب EMA للـ Signal فقط على القيم غير None
    # نبني قائمة مؤقتة نملأ None بـ 0 لحساب EMA ثم نُعيد None للمواضع الأصلية
    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if first_valid is None:
        n = len(closes)
        return [None]*n, [None]*n, [None]*n

    # EMA للـ signal تُحسب ابتداءً من أول قيمة MACD صالحة
    macd_valid = macd_line[first_valid:]
    signal_valid = _calc_ema(macd_valid, signal)

    signal_line = [None] * first_valid + signal_valid
    histogram   = []
    for m, s in zip(macd_line, signal_line):
        if m is None or s is None:
            histogram.append(None)
        else:
            histogram.append(m - s)

    return macd_line, signal_line, histogram


def _calc_volume_ma(volumes: list, period: int) -> list:
    """
    يحسب المتوسط المتحرك البسيط للـ Volume.
    يُعيد قائمة بنفس الطول — القيم الأولى تكون None.
    """
    result = [None] * len(volumes)
    for i in range(period - 1, len(volumes)):
        result[i] = sum(volumes[i - period + 1 : i + 1]) / period
    return result


def _calc_obv(closes: list, volumes: list) -> list:
    """
    يحسب On-Balance Volume (OBV).
    يُعيد قائمة بنفس الطول.
    """
    result = [0.0] * len(closes)
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            result[i] = result[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            result[i] = result[i - 1] - volumes[i]
        else:
            result[i] = result[i - 1]
    return result


def _calc_atr(highs: list, lows: list, closes: list, period: int) -> list:
    """
    يحسب ATR (Average True Range) — مقياس التقلب الحالي للسوق.
    يُستخدم لجعل شروط الدخول/الخروج ديناميكية حسب حالة السوق
    بدل نسب مئوية ثابتة.
    يُعيد قائمة بنفس الطول — القيم الأولى تكون None.
    """
    n = len(closes)
    result = [None] * n
    if n < period + 1:
        return result

    true_ranges = [None] * n
    for i in range(1, n):
        high_low   = highs[i] - lows[i]
        high_close = abs(highs[i] - closes[i - 1])
        low_close  = abs(lows[i] - closes[i - 1])
        true_ranges[i] = max(high_low, high_close, low_close)

    # أول ATR = متوسط بسيط لأول period من True Range
    first_atr = sum(true_ranges[1:period + 1]) / period
    result[period] = first_atr

    # بعدها: تمهيد Wilder (نفس أسلوب RSI)
    for i in range(period + 1, n):
        result[i] = (result[i - 1] * (period - 1) + true_ranges[i]) / period

    return result


def _calc_swing_low(lows: list, lookback: int) -> list:
    """
    يحسب أدنى سعر (Swing Low) خلال آخر lookback شمعة **قبل** الشمعة الحالية
    (لا تدخل الشمعة الحالية في الحساب) — يُستخدم كدعم حقيقي نقارن به
    الشمعة الحالية (هل كسرته أم ارتدت عنه)، بدل الاعتماد على EMA كتقريب.
    يُعيد قائمة بنفس الطول — القيم الأولى تكون None.
    """
    n = len(lows)
    result = [None] * n
    for i in range(lookback, n):
        result[i] = min(lows[i - lookback: i])
    return result


def _calc_swing_high(highs: list, lookback: int) -> list:
    """
    يحسب أعلى سعر (Swing High) خلال آخر lookback شمعة **قبل** الشمعة الحالية
    — يُستخدم كمقاومة حقيقية نقارن بها الشمعة الحالية (تأكيد اختراق حقيقي
    في مسار الدخول 4)، بدل الاعتماد على EMA كتقريب.
    يُعيد قائمة بنفس الطول — القيم الأولى تكون None.
    """
    n = len(highs)
    result = [None] * n
    for i in range(lookback, n):
        result[i] = max(highs[i - lookback: i])
    return result


# ══════════════════════════════════════════════
#   الدالة الرئيسية
# ══════════════════════════════════════════════

def Indicator_Calculation(Raw_Data: list) -> dict:
    """
    تحسب جميع المؤشرات الفنية على Raw_Data وتُعيد Final_Data.

    المدخل:
        Raw_Data : list[list] — 150 شمعة، كل شمعة:
                   [timestamp, open, high, low, close, volume]

    المخرج:
        Final_Data : dict — القيم الجاهزة للاستخدام في قرار التداول
    """

    if len(Raw_Data) < 50:
        raise ValueError(
            f"❌ عدد الشموع غير كافٍ: {len(Raw_Data)} (المطلوب 50 على الأقل)"
        )

    # ─────────────────────────────
    # استخراج الأعمدة
    # ─────────────────────────────
    highs   = [candle[2] for candle in Raw_Data]
    lows    = [candle[3] for candle in Raw_Data]
    closes  = [candle[4] for candle in Raw_Data]
    volumes = [candle[5] for candle in Raw_Data]

    # ─────────────────────────────
    # TREND: EMA 9 / 21 / 50
    # ─────────────────────────────
    ema9  = _calc_ema(closes, 9)
    ema21 = _calc_ema(closes, 21)
    ema50 = _calc_ema(closes, 50)

    # ─────────────────────────────
    # MOMENTUM: RSI 7
    # ─────────────────────────────
    rsi = _calc_rsi(closes, 7)

    # ─────────────────────────────
    # MACD: (8, 17, 9) — حل وسط بين السرعة والدقة
    # (أسرع من القياسي 12,26,9 بحوالي 35%، وأبطأ/أنعم بكثير من السريع
    # المفرط 5,13,3. الدقة ضد الضجيج تُضبط بفلتر قوة التقاطع في
    # Entry_Decision_File.py وليس بإبطاء المؤشر وحده)
    # ─────────────────────────────
    macd_line, signal_line, histogram = _calc_macd(closes, fast=8, slow=17, signal=9)

    # ─────────────────────────────
    # VOLUME: MA_20 + OBV
    # ─────────────────────────────
    volume_ma20 = _calc_volume_ma(volumes, 20)
    obv         = _calc_obv(closes, volumes)

    # ─────────────────────────────
    # VOLATILITY: ATR 14
    # ─────────────────────────────
    atr = _calc_atr(highs, lows, closes, 14)

    # ─────────────────────────────
    # SUPPORT / RESISTANCE: Swing Low/High (آخر 20 شمعة سابقة)
    # ─────────────────────────────
    SWING_LOOKBACK = 20
    swing_low  = _calc_swing_low(lows, SWING_LOOKBACK)
    swing_high = _calc_swing_high(highs, SWING_LOOKBACK)

    # ─────────────────────────────
    # التحقق من توفر القيم الضرورية
    # للشمعتين الأخيرتين [-1] و [-2]
    # ─────────────────────────────
    required = {
        "ema9[-1]"      : ema9[-1],
        "ema21[-1]"     : ema21[-1],
        "ema50[-1]"     : ema50[-1],
        "rsi[-1]"       : rsi[-1],
        "rsi[-2]"       : rsi[-2],
        "macd_line[-1]" : macd_line[-1],
        "signal_line[-1]": signal_line[-1],
        "histogram[-1]" : histogram[-1],
        "histogram[-2]" : histogram[-2],
        "volume_ma20[-1]": volume_ma20[-1],
        "obv[-1]"       : obv[-1],
        "obv[-2]"       : obv[-2],
        "atr[-1]"       : atr[-1],
        "swing_low[-1]" : swing_low[-1],
        "swing_high[-1]": swing_high[-1],
    }

    missing = [k for k, v in required.items() if v is None]
    if missing:
        raise ValueError(
            f"❌ قيم المؤشرات غير مكتملة — القيم الناقصة: {missing}\n"
            f"   تأكد من توفر 150 شمعة على الأقل."
        )

    # ─────────────────────────────
    # بناء Final_Data
    # ─────────────────────────────
    vol_ratio = volumes[-1] / volume_ma20[-1] if volume_ma20[-1] else 0.0

    Final_Data = {
        "price"         : closes[-1],

        "ema9"          : ema9[-1],
        "ema21"         : ema21[-1],
        "ema50"         : ema50[-1],

        "rsi_now"       : rsi[-1],
        "rsi_prev"      : rsi[-2],

        "macd_line"     : macd_line[-1],
        "signal_line"   : signal_line[-1],
        "hist_now"      : histogram[-1],
        "hist_prev"     : histogram[-2],

        "volume_ratio"  : vol_ratio,
        "obv_now"       : obv[-1],
        "obv_prev"      : obv[-2],

        "atr"           : atr[-1],
        "swing_low"     : swing_low[-1],
        "swing_high"    : swing_high[-1],

        "high_now"      : highs[-1],
        "low_now"       : lows[-1],
    }

    return Final_Data
