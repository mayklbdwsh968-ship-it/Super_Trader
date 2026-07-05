"""
ملف: Entry_Decision_File.py
الوظيفة: اتخاذ قرار الدخول فقط (BUY / ANYTHING)
         يعمل فقط عندما لا يوجد مركز مفتوح — Manager.py يمرر له البيانات
         في هذه الحالة فقط.
         بعد فتح المركز، تنتقل الإدارة إلى Exit_Decision_File.py
المسار: Super_Trader/Entry_Decision_File.py

المبدأ: OR بين عدة مسارات دخول مستقلة — كل مسار قوي ودقيق بذاته،
        لكن وجود عدة مسارات يزيد فرص الدخول لأنه يغطي حالات مختلفة
        من الاتجاه الصاعد بدل حالة واحدة فقط (لحظة تقاطع MACD).

تحديث مهم:
    - أُزيلت بوّابة الحجم العامة التي كانت تُطبَّق قبل كل المسارات
      (MIN_VOLUME_FLOOR) بشكل كامل. بدلاً منها، كل مسار لا يملك شرط
      حجم خاص به أصبح يملك الآن حد حجم أدنى مستقل يناسب طبيعته —
      هذا أدق من بوّابة عامة واحدة تُسقط كل المسارات معاً حتى لو
      كان أحدها قوياً بما يكفي بحجم أقل.
    - أُضيف مسار خامس جديد: الارتداد من دعم قوي (Support Reversal)
      يعتمد على تحديد مناطق دعم قوية من بيانات الشموع الخام الداخلة
      إلى هذا الملف مباشرة (وليس من مؤشرات جاهزة)، ثم يشترط وصول
      السعر إلى إحدى هذه المناطق + ظهور إشارة انعكاس (شمعة ابتلاعية
      صعودية أو RSI متشبع بيعياً).
"""


# ══════════════════════════════════════════════
#   فلتر قوة تقاطع MACD (بديل عن إبطاء المؤشر لتفادي الضجيج)
# ══════════════════════════════════════════════
# فارق الهيستوغرام (macd_line - signal_line) يجب أن يكون ذا معنى نسبةً
# لتقلب السوق الحالي (ATR)، مو مجرد فارق موجب ضئيل جداً قريب من الصفر.
# هذا يفلتر "التقاطعات الوهمية" مباشرة بدل الاعتماد فقط على إبطاء
# MACD — يحافظ على سرعة استجابة المؤشر مع رفض الإشارات الهامشية فقط.
MIN_MACD_STRENGTH_ATR_RATIO = 0.05

# ══════════════════════════════════════════════
#   حدود الحجم المستقلة لكل مسار
#   (بديل بوّابة الحجم العامة التي أُزيلت بالكامل)
# ══════════════════════════════════════════════
# مسار 1 (تقاطع الزخم الأصلي): لحظة دخول حقيقية يجب أن تكون مدعومة
# بحجم قريب من المتوسط على الأقل — تقاطع بحجم ضعيف جداً مشكوك بصدقه
MIN_VOLUME_PATH1 = 0.8

# مسار 2 (استمرار الزخم): الاتجاه مستمر أصلاً وليس لحظة دخول جديدة،
# لذلك سقف أدنى أخف يكفي لتأكيد أن الزخم لا يزال حياً
MIN_VOLUME_PATH2 = 0.7

# مسار 3 (ارتداد من الدعم): أثناء الارتداد يكون الحجم غالباً أقل من
# المتوسط طبيعياً (تصحيح هادئ)، لذلك سقف أدنى منخفض فقط لاستبعاد
# حالات السيولة شبه المعدومة، مع بقاء OBV هو المؤكد الأساسي للحجم
MIN_VOLUME_PATH3 = 0.5

# مسار 5 (ارتداد من دعم قوي + إشارة انعكاس): دخول عند الدعم يجب أن
# يكون مدعوماً بحجم لا بأس به حتى لا يكون ارتداداً وهمياً بسيولة ضعيفة
MIN_VOLUME_PATH5 = 0.7

# ══════════════════════════════════════════════
#   إعدادات تحديد مناطق الدعم (مسار 5)
# ══════════════════════════════════════════════
# عدد الشموع (من الأحدث) التي تُفحص لاستخراج القيعان المتأرجحة
SUPPORT_LOOKBACK_CANDLES = 100

# نسبة التقارب المسموحة بين قاعين لاعتبارهما نفس منطقة الدعم (%)
SUPPORT_CLUSTER_TOLERANCE_PCT = 0.3

# الحد الأدنى لعدد مرات "اختبار" المنطقة لتُعتبر دعماً قوياً
# (قاع واحد فقط = صدفة، قاعان أو أكثر متقاربان = دعم حقيقي مُختبَر)
SUPPORT_MIN_TOUCHES = 2

# المسافة المسموحة بين السعر الحالي ومنطقة الدعم لاعتبار السعر
# "وصل إليها فعلياً" — مبنية على ATR بدل نسبة ثابتة لتتكيف مع تقلب
# السوق الحالي تلقائياً
NEAR_SUPPORT_ATR_MULTIPLIER = 0.5

# حد RSI الذي يُعتبر تحته السوق "متشبعاً بيعياً" (إشارة انعكاس محتملة)
RSI_OVERSOLD_THRESHOLD = 32


# ══════════════════════════════════════════════
#   دالة مساعدة: تحديد مناطق الدعم القوية من الشموع الخام
# ══════════════════════════════════════════════
def _find_strong_support_zones(candles):
    """
    تُحلّل قائمة شموع خام [timestamp, open, high, low, close, volume]
    (من الأقدم إلى الأحدث) وتُعيد قائمة بمستويات الدعم "القوية" فقط —
    أي القيعان المتأرجحة (swing lows) المتقاربة والمتكررة عدة مرات،
    وليس أي قاع عابر.

    المخرج: list[float] — مستويات الدعم (قد تكون فارغة إن لم توجد
    بيانات كافية أو لم يتكرر أي قاع).
    """
    if not candles or len(candles) < 5:
        return []

    recent = candles[-SUPPORT_LOOKBACK_CANDLES:] \
        if len(candles) > SUPPORT_LOOKBACK_CANDLES else candles

    lows = [c[3] for c in recent]  # index 3 = low

    # ── استخراج القيعان المتأرجحة (أقل من الجارتين) ─────
    swing_lows = []
    for i in range(1, len(lows) - 1):
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swing_lows.append(lows[i])

    if not swing_lows:
        return []

    swing_lows.sort()

    # ── تجميع القيعان المتقاربة في مناطق (clusters) ─────
    zones = []
    current_zone = [swing_lows[0]]

    for lvl in swing_lows[1:]:
        zone_avg = sum(current_zone) / len(current_zone)
        diff_pct = abs(lvl - zone_avg) / zone_avg * 100
        if diff_pct <= SUPPORT_CLUSTER_TOLERANCE_PCT:
            current_zone.append(lvl)
        else:
            zones.append(current_zone)
            current_zone = [lvl]
    zones.append(current_zone)

    # ── الاحتفاظ فقط بالمناطق "المُختبَرة" عدة مرات (دعم قوي) ─────
    strong_zones = [
        sum(zone) / len(zone)
        for zone in zones
        if len(zone) >= SUPPORT_MIN_TOUCHES
    ]

    return strong_zones


# ══════════════════════════════════════════════
#   دالة مساعدة: كشف شمعة ابتلاعية صعودية من آخر شمعتين خام
# ══════════════════════════════════════════════
def _is_bullish_engulfing(candles):
    """
    تتحقق من الشمعتين الأخيرتين في candles (من الأقدم إلى الأحدث):
    الشمعة السابقة هابطة، والشمعة الحالية صعودية وجسمها "يبتلع"
    جسم الشمعة السابقة بالكامل.
    """
    if not candles or len(candles) < 2:
        return False

    prev_candle = candles[-2]
    curr_candle = candles[-1]

    open_prev, close_prev = prev_candle[1], prev_candle[4]
    open_now,  close_now  = curr_candle[1],  curr_candle[4]

    prev_bearish = close_prev < open_prev
    curr_bullish = close_now > open_now
    engulfs = (open_now <= close_prev) and (close_now >= open_prev)

    return prev_bearish and curr_bullish and engulfs


def Entry_Decision(Final_Data: dict, Decision_prev: str,
                    Raw_Data: list, Raw_Data_HTF: list = None) -> str:
    """
    تحلّل Final_Data (والشموع الخام) وتُعيد قرار الدخول.

    المدخلات:
        Final_Data    : dict — القيم المحسوبة من Indicator_Calculation:
            {
                "price"        : float,
                "ema9"         : float,
                "ema21"        : float,
                "ema50"        : float,
                "rsi_now"      : float,
                "rsi_prev"     : float,
                "macd_line"    : float,
                "signal_line"  : float,
                "hist_now"     : float,
                "hist_prev"    : float,
                "volume_ratio" : float,
                "obv_now"      : float,
                "obv_prev"     : float,
                "atr"          : float,
                "swing_low"    : float,
                "swing_high"   : float,
                "high_now"     : float,
                "low_now"      : float,
            }
        Decision_prev : str  — القرار السابق ("BUY" | "ANYTHING")
        Raw_Data      : list — شموع خام على فريم العمل الأساسي (مثلاً 1m)
                        بصيغة [timestamp, open, high, low, close, volume]
                        من الأقدم إلى الأحدث. تُستخدم لكشف شمعة الانعكاس.
        Raw_Data_HTF  : list — شموع خام على فريم أعلى (15m/1H أو أكبر)
                        بنفس الصيغة، اختيارية. إن وُجدت تُستخدم أولاً
                        لتحديد مناطق الدعم (أدق من فريم صغير)، وإن لم
                        تتوفر يُستخدم Raw_Data نفسه كبديل.

    المخرج:
        Decision : str — "BUY" | "ANYTHING"
    """

    # ─────────────────────────────
    # استخراج القيم
    # ─────────────────────────────
    price        = Final_Data["price"]
    ema9         = Final_Data["ema9"]
    ema21        = Final_Data["ema21"]
    ema50        = Final_Data["ema50"]
    rsi_now      = Final_Data["rsi_now"]
    rsi_prev     = Final_Data["rsi_prev"]
    macd_line    = Final_Data["macd_line"]
    signal_line  = Final_Data["signal_line"]
    hist_now     = Final_Data["hist_now"]
    hist_prev    = Final_Data["hist_prev"]
    volume_ratio = Final_Data["volume_ratio"]
    obv_now      = Final_Data["obv_now"]
    obv_prev     = Final_Data["obv_prev"]
    swing_low    = Final_Data["swing_low"]
    swing_high   = Final_Data["swing_high"]
    low_now      = Final_Data["low_now"]
    atr          = Final_Data["atr"]

    # ══════════════════════════════════════════════
    #   فلتر قوة تقاطع MACD — تقاطع بفارق ضئيل جداً (قريب من الصفر)
    #   لا يُعتبر زخماً حقيقياً، حتى لو كانت الإشارة "موجبة" رياضياً
    # ══════════════════════════════════════════════
    macd_strength_ok = abs(hist_now) >= (atr * MIN_MACD_STRENGTH_ATR_RATIO)

    # ══════════════════════════════════════════════
    #   مسار 1 — تقاطع الزخم الأصلي (Fresh Cross)
    #   + شرط حجم مستقل بعد إزالة بوّابة الحجم العامة
    # ══════════════════════════════════════════════
    path1 = (
        price > ema21
        and macd_line > signal_line
        and macd_strength_ok
        and 50 < rsi_now < 65
        and volume_ratio > MIN_VOLUME_PATH1
    )

    # ══════════════════════════════════════════════
    #   مسار 2 — استمرار الزخم (Momentum Continuation)
    #   + شرط حجم مستقل (أخف من مسار 1 لأنه ليس لحظة دخول جديدة)
    # ══════════════════════════════════════════════
    path2 = (
        price > ema9 > ema21
        and hist_now > hist_prev > 0
        and macd_strength_ok
        and 45 < rsi_now < 65
        and volume_ratio > MIN_VOLUME_PATH2
    )

    # ══════════════════════════════════════════════
    #   مسار 3 — الارتداد من الدعم الحقيقي (Pullback Bounce)
    #   + شرط حجم مستقل خفيف (OBV يبقى المؤكد الأساسي هنا)
    # ══════════════════════════════════════════════
    path3 = (
        price > ema50
        and low_now >= swing_low
        and rsi_prev < 50 <= rsi_now
        and obv_now > obv_prev
        and volume_ratio > MIN_VOLUME_PATH3
    )

    # ══════════════════════════════════════════════
    #   مسار 4 — اختراق مقاومة حقيقية مدعوم بالحجم (Volume Breakout)
    #   (يملك أصلاً شرط حجم أقوى من البقية — لا تغيير هنا)
    # ══════════════════════════════════════════════
    path4 = (
        price > ema9 > ema21 > ema50
        and price > swing_high
        and volume_ratio > 1.3
        and rsi_now < 70
    )

    # ══════════════════════════════════════════════
    #   مسار 5 — ارتداد من دعم قوي + إشارة انعكاس (جديد)
    #   دعم قوي = مُستخرج من الشموع الخام نفسها (قيعان متكررة ومتقاربة)
    #   إشارة الانعكاس = شمعة ابتلاعية صعودية أو RSI متشبع بيعياً
    # ══════════════════════════════════════════════
    support_source = Raw_Data_HTF if Raw_Data_HTF else Raw_Data
    support_zones  = _find_strong_support_zones(support_source)

    near_strong_support = any(
        abs(price - level) <= (atr * NEAR_SUPPORT_ATR_MULTIPLIER)
        for level in support_zones
    )

    bullish_engulfing = _is_bullish_engulfing(Raw_Data)
    rsi_oversold      = rsi_now < RSI_OVERSOLD_THRESHOLD
    reversal_signal   = bullish_engulfing or rsi_oversold

    path5 = (
        near_strong_support
        and reversal_signal
        and volume_ratio > MIN_VOLUME_PATH5
    )

    # ══════════════════════════════════════════════
    #   القرار النهائي — BUY إذا تحقق أي مسار
    # ══════════════════════════════════════════════
    triggered_paths = []
    if path1:
        triggered_paths.append("1-تقاطع الزخم")
    if path2:
        triggered_paths.append("2-استمرار الزخم")
    if path3:
        triggered_paths.append("3-ارتداد الدعم")
    if path4:
        triggered_paths.append("4-اختراق بالحجم")
    if path5:
        reason = "ابتلاعية" if bullish_engulfing else "RSI متشبع"
        triggered_paths.append(f"5-ارتداد دعم قوي ({reason})")

    buy_triggered = len(triggered_paths) > 0
    Decision = "BUY" if buy_triggered else "ANYTHING"

    # ══════════════════════════════════════════════
    #   قاعدة Decision_prev
    #   إذا كان القرار الحالي مطابقاً للسابق → ANYTHING
    #   (يمنع تكرار إشارة BUY لنفس الحالة قبل أي تغيير)
    # ══════════════════════════════════════════════
    if Decision == Decision_prev and Decision == "BUY":
        print(
            f"[Entry_Decision] القرار: ANYTHING (تكرار BUY) | "
            f"السعر={price:.4f} | المسارات المتحققة: {', '.join(triggered_paths)}"
        )
        return "ANYTHING"

    # ══════════════════════════════════════════════
    #   إرجاع القرار النهائي
    # ══════════════════════════════════════════════
    if Decision == "BUY":
        print(
            f"[Entry_Decision] القرار: BUY | السعر={price:.4f} | "
            f"المسارات المتحققة: {', '.join(triggered_paths)} | "
            f"RSI={rsi_now:.2f} | حجم={volume_ratio:.2f}x | "
            f"مناطق دعم مكتشفة={len(support_zones)}"
        )
    else:
        print(
            f"[Entry_Decision] القرار: ANYTHING | السعر={price:.4f} | "
            f"لا يوجد مسار متحقق | RSI={rsi_now:.2f} | حجم={volume_ratio:.2f}x | "
            f"قرب دعم قوي={near_strong_support}"
        )

    return Decision
