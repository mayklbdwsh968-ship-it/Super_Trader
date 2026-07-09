"""
ملف: Exit_Decision_File.py
الوظيفة: إدارة كاملة لخروج الصفقة بعد فتحها — SL هيكلي ثابت، TP متعدد
         المستويات مع خروج جزئي، وTrailing Stop للجزء المتبقي.
         يعمل فقط بعد فتح مركز — Manager.py يمرر له البيانات في هذه
         الحالة فقط، مع معلومات المركز المفتوح (Position).
المسار: Super_Trader/Exit_Decision_File.py

═══════════════════════════════════════════════════════
   المبدأ الجديد: "الأفضلية الإحصائية" (Statistical Edge)
═══════════════════════════════════════════════════════
في سوق Spot لا يوجد خطر تصفية كما في Futures، لذا الهدف من الخروج
ليس حماية هامش، بل حماية رأس المال والحفاظ على أفضلية إحصائية طويلة
المدى. هذا يعني اتباع قاعدتين ذهبيتين غيّرتا تصميم هذا الملف بالكامل:

  1) "ضع SL في المكان الذي تصبح فيه فكرة الدخول خاطئة، وليس في المكان
     الذي تتحمل فيه الخسارة." → SL أصبح سعراً هيكلياً ثابتاً يُحسب مرة
     واحدة فقط عند الدخول (خلف الدعم/القاع الهيكلي أو ATR×2 كبديل)،
     وليس نظام نقاط تفاعلي متغيّر كل دورة كما كان سابقاً.

  2) "TP عند مناطق العرض والسيولة، وليس نسبة ثابتة، مع خروج جزئي
     وTrailing Stop للباقي." → أصبحت هناك TP1 (أول مقاومة قوية) وTP2
     (مقاومة أبعد)، مع بيع جزئي عند كل منهما وترك جزء يُدار بـ Trailing
     Stop يتحرك مع الاتجاه، بدل بيع الكمية كاملة عند رقم واحد.

═══════════════════════════════════════════════════════
   ⚠️ تغيير جوهري في العقد (Contract) مع Manager.py
═══════════════════════════════════════════════════════
1) Exit_Decision() لم تعد تُعيد str بسيط ("SELL"/"HOLD")، بل تُعيد dict:
   {
       "action"          : str,   # انظر القيم الممكنة أدناه
       "sell_fraction"   : float, # نسبة من الكمية الأصلية للمركز (0..1)
       "updated_position": dict,  # يجب استبدال Position الحالي بهذا بالكامل
       "log"             : str,   # رسالة جاهزة للطباعة/التسجيل
   }

   القيم الممكنة لـ "action":
   - "HOLD"              : لا تفعل شيئاً، فقط احفظ updated_position
   - "SELL_SL"            : بيع كل الكمية المتبقية فوراً (وقف خسارة)
   - "SELL_TIME_STOP"     : بيع كل الكمية المتبقية (خرجت الصفقة زمنياً بلا تقدّم)
   - "SELL_TP1_PARTIAL"   : بيع sell_fraction من الكمية الأصلية (هدف أول)
   - "SELL_TP2_PARTIAL"   : بيع sell_fraction من الكمية الأصلية (هدف ثانٍ)
   - "SELL_TRAIL"         : بيع كل الكمية المتبقية (تريلينغ ستوب انكسر)

2) عند فتح صفقة جديدة، Manager.py يجب أن يستدعي الدالة الجديدة
   Init_Position_Risk_Management() بدل Calc_TP_Price() القديمة، لبناء
   كائن Position الكامل بكل حقول إدارة المخاطرة اللازمة (انظر تعريف
   Position بالأسفل). هذا يتطلب تمرير Raw_Data/Raw_Data_HTF (لتحديد
   مناطق المقاومة) إضافة لـ Final_Data وسعر/ATR الدخول.

3) بما أن TP لم يعد رقماً واحداً يُوضع كأمر LIMIT معلَّق على المنصة،
   بل مستويات متعددة مُدارة بفحص نشط كل دورة، فإن Manager.py يحتاج
   على الأرجح إعادة النظر في طريقة وضع أوامر TP (تنفيذ سوقي عند تحقق
   الشرط بدل أمر حدّي معلَّق دائم) — هذا تغيير معماري خارج نطاق هذا
   الملف، وقد أوضحته بالتفصيل في ردّي، ويسعدني تطبيقه في Manager.py
   إن رغبت.

═══════════════════════════════════════════════════════
   تعريف Position الجديد (يُبنى بالكامل عبر Init_Position_Risk_Management)
═══════════════════════════════════════════════════════
Position = {
    "entry_price"     : float,  # سعر الدخول الفعلي
    "entry_atr"       : float,  # ATR وقت الدخول بالضبط (ثابت طوال الصفقة)
    "sl_price"        : float,  # وقف الخسارة الهيكلي — ثابت منذ الدخول
    "tp1_price"       : float,  # الهدف الأول (أول مقاومة قوية أو RR ثابت)
    "tp2_price"       : float,  # الهدف الثاني (مقاومة أبعد أو RR أعلى)
    "tp1_done"        : bool,   # هل نُفِّذ الخروج الجزئي الأول
    "tp2_done"        : bool,   # هل نُفِّذ الخروج الجزئي الثاني
    "remaining_pct"   : float,  # النسبة المتبقية من الكمية الأصلية (تبدأ 1.0)
    "trailing_active" : bool,   # هل تفعّل التتبع (يتفعّل تلقائياً بعد TP1)
    "trailing_stop"   : float | None,  # سعر التريلينغ الحالي
    "highest_price"   : float,  # أعلى سعر وصلت إليه الصفقة منذ الدخول
    "cycles_held"      : int,   # عدد الدورات منذ الدخول (للوقف الزمني)
    "market_strength" : str,    # "strong" | "medium" | "weak" وقت الدخول
    "rr_target"       : float,  # نسبة RR المستهدفة لـ TP2 (ديناميكية)
}
"""


# ══════════════════════════════════════════════
#   إعدادات وقف الخسارة الهيكلي (SL)
# ══════════════════════════════════════════════
# هامش الأمان خلف الدعم الهيكلي (القاعدة الذهبية: الوقف خلف المنطقة
# وليس داخلها) — يُضرب في ATR ليتكيّف مع تقلب السوق تلقائياً
SL_STRUCTURE_ATR_BUFFER = 0.3

# مضاعِف ATR البديل عندما لا يكون الدعم الهيكلي منطقياً (بعيد جداً/
# قريب جداً/غير موجود) — طريقة ATR ممتازة للبوتات لأنها تتكيف تلقائياً
# (خُفِّض من 2.0 إلى 1.5 — يطابق GATE_SL_ATR_MULTIPLIER في
#  Entry_Decision_File.py، ويقلّل مسافة الوقف غير الضرورية في السكالبينج)
SL_ATR_MULTIPLIER = 1.5

# الحد الأدنى المطلق لمسافة الوقف (نسبةً لـ ATR) — وقف أضيق من هذا
# عرضة لضجيج السعر الطبيعي ويُفعَّل بلا سبب حقيقي (whipsaw)
SL_MIN_RISK_ATR_MULTIPLIER = 0.8

# الحد الأقصى المطلق لمسافة الوقف كنسبة من سعر الدخول — حماية من دعم
# هيكلي بعيد جداً يجعل المخاطرة غير منطقية مهما بدا "صحيحاً" تحليلياً
SL_MAX_RISK_PCT = 0.08   # 8%

# ══════════════════════════════════════════════
#   إعدادات جني الأرباح متعدد المستويات (TP1 / TP2)
# ══════════════════════════════════════════════
# نسبة الابتعاد عن رقم المقاومة "الدائري" بالضبط — كثير من المتداولين
# يضعون أوامرهم عند الأرقام الواضحة، فالمنافسة هناك أعلى والتنفيذ أصعب
TP_RESISTANCE_BUFFER_PCT = 0.0015   # 0.15%

# أقل RR مقبول لـ TP1 حتى لو وُجدت مقاومة أقرب من ذلك (لا فائدة من
# هدف أول قريب جداً لا يغطي حتى المخاطرة نفسها)
# (خُفِّض من 1.3 إلى 1.1 ليطابق MIN_ACCEPTABLE_ENTRY_RR في
#  Entry_Decision_File.py — نفس فلسفة "الأفضلية" في الطرفين)
MIN_TP1_RR = 1.1

# نسبة الكمية الأصلية التي تُباع عند كل هدف — الباقي (هنا 25%) يُدار
# بالكامل عبر Trailing Stop لالتقاط الحركة الكبيرة المحتملة
TP1_SELL_FRACTION = 0.45
TP2_SELL_FRACTION = 0.30
# الباقي بعد الهدفين = 1 - 0.45 - 0.30 = 0.25 (تريلينغ فقط)

# ══════════════════════════════════════════════
#   إعدادات Trailing Stop (للجزء المتبقي بعد TP1)
# ══════════════════════════════════════════════
# يبدأ التتبع بعد تحقق TP1 فقط — يتحرك مع أعلى سعر مسجَّل، بمسافة
# تساوي ATR الحالي × هذا المضاعِف (وليس ATR الدخول، ليتكيف مع التقلب
# الفعلي أثناء الصفقة لا وقت الدخول فقط)
TRAIL_ATR_MULTIPLIER = 1.5

# ══════════════════════════════════════════════
#   إعدادات تقييم قوة السوق (تُحدِّد RR المستهدف لـ TP2)
# ══════════════════════════════════════════════
RR_STRONG_MARKET = 3.0
RR_MEDIUM_MARKET = 2.0
RR_WEAK_MARKET   = 1.3

# ══════════════════════════════════════════════
#   إعدادات الوقف الزمني (Time Stop)
# ══════════════════════════════════════════════
# عدد الدورات (≈ دقائق على فريم 1m) قبل اعتبار الصفقة "بلا تقدّم"
TIME_STOP_CYCLES = 25

# الحد الأدنى من التقدّم المطلوب (نسبةً لـ ATR الدخول) خلال تلك المدة
# حتى لا تُعتبر الصفقة "راكدة" — تقدّم أقل من هذا مع ضعف الزخم = خروج
TIME_STOP_MIN_PROGRESS_ATR = 0.4

# ══════════════════════════════════════════════
#   إعدادات تحديد مناطق المقاومة من الشموع الخام (مرآة لمناطق الدعم)
# ══════════════════════════════════════════════
RESISTANCE_LOOKBACK_CANDLES        = 100
RESISTANCE_CLUSTER_TOLERANCE_PCT   = 0.3
RESISTANCE_MIN_TOUCHES             = 2

# ══════════════════════════════════════════════
#   إعدادات كشف الاتجاه العام لتعديل SL/TP الديناميكي بحسب قوة/اتجاه
#   التذبذب (بناءً على نفس شموع تحديد الدعم/المقاومة)
# ══════════════════════════════════════════════
TREND_GAP_PCT_CAP = 5.0

# ══════════════════════════════════════════════
#   إعدادات الخروج الربحي المبكر (فقط قبل تحقق TP1 — خروج عند ضعف
#   زخم مفاجئ رغم وجود ربح كافٍ). نظام "الإنذار المبكر" القديم القائم
#   على النقاط (SL بديل قبل الوصول للـ SL الحقيقي) أُلغي بالكامل لأنه
#   كان يتسبب في خروج خاسر مبكر قبل وصول السعر لوقف الخسارة الفعلي —
#   الآن SL الوحيد المعتمد هو السعر الهيكلي الثابت (الطبقة 0 أعلاه).
# ══════════════════════════════════════════════
MIN_PROFIT_ATR_MULTIPLIER = 0.5


# ══════════════════════════════════════════════
#   دالة مساعدة: تحديد مناطق المقاومة القوية (مرآة لمناطق الدعم)
# ══════════════════════════════════════════════
def _find_strong_resistance_zones(candles):
    """
    نفس منطق تحديد مناطق الدعم تماماً لكن معكوساً: تبحث عن القمم
    المتأرجحة (swing highs) المتقاربة والمتكررة عدة مرات لتشكّل مناطق
    مقاومة "قوية" — أي مُختبَرة أكثر من مرة، وليست أي قمة عابرة.
    """
    if not candles or len(candles) < 5:
        return []

    recent = candles[-RESISTANCE_LOOKBACK_CANDLES:] \
        if len(candles) > RESISTANCE_LOOKBACK_CANDLES else candles

    highs = [c[2] for c in recent]  # index 2 = high

    swing_highs = []
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            swing_highs.append(highs[i])

    if not swing_highs:
        return []

    swing_highs.sort()

    zones = []
    current_zone = [swing_highs[0]]
    for lvl in swing_highs[1:]:
        zone_avg = sum(current_zone) / len(current_zone)
        diff_pct = abs(lvl - zone_avg) / zone_avg * 100
        if diff_pct <= RESISTANCE_CLUSTER_TOLERANCE_PCT:
            current_zone.append(lvl)
        else:
            zones.append(current_zone)
            current_zone = [lvl]
    zones.append(current_zone)

    strong_zones = [
        sum(zone) / len(zone)
        for zone in zones
        if len(zone) >= RESISTANCE_MIN_TOUCHES
    ]

    return strong_zones


# ══════════════════════════════════════════════
#   دالة مساعدة: كشف الاتجاه العام + متوسط نسبة التذبذب
#   (تُستخدم لتعديل SL/TP بحسب الاتجاه — طلب تدقيق يدوي)
# ══════════════════════════════════════════════
def _detect_trend_and_gap_pct(candles, use_highs):
    """
    يحدد الاتجاه العام (up/down/neutral) بمقارنة آخر قمتين (أو قاعين)
    متأرجحتين ضمن نفس شموع الدعم/المقاومة، ويحسب متوسط النسبة المئوية
    للمسافة بين القمم (أو القيعان) المتتالية كمقياس لقوة التذبذب في
    هذا الاتجاه.

    use_highs=True  → يفحص القمم (يُستخدم لتعديل TP)
    use_highs=False → يفحص القيعان (يُستخدم لتعديل SL)
    """
    if not candles or len(candles) < 5:
        return "neutral", 0.0

    recent = candles[-RESISTANCE_LOOKBACK_CANDLES:] \
        if len(candles) > RESISTANCE_LOOKBACK_CANDLES else candles

    idx = 2 if use_highs else 3  # 2=high, 3=low
    values = [c[idx] for c in recent]

    swings = []
    for i in range(1, len(values) - 1):
        if use_highs:
            if values[i] > values[i - 1] and values[i] > values[i + 1]:
                swings.append(values[i])
        else:
            if values[i] < values[i - 1] and values[i] < values[i + 1]:
                swings.append(values[i])

    if len(swings) < 2:
        return "neutral", 0.0

    if swings[-1] > swings[-2]:
        trend = "up"
    elif swings[-1] < swings[-2]:
        trend = "down"
    else:
        trend = "neutral"

    gaps_pct = []
    for i in range(1, len(swings)):
        prev = swings[i - 1]
        if prev > 0:
            gaps_pct.append(abs(swings[i] - prev) / prev * 100)

    avg_gap_pct = min(sum(gaps_pct) / len(gaps_pct), TREND_GAP_PCT_CAP) if gaps_pct else 0.0
    return trend, avg_gap_pct


# ══════════════════════════════════════════════
#   دالة مساعدة: تقييم قوة السوق وقت الدخول → RR مستهدف
# ══════════════════════════════════════════════
def _assess_market_strength(Final_Data):
    """
    تقييم بسيط وذاتي الاكتفاء (لا يحتاج بيانات إضافية) لقوة الاتجاه
    وقت الدخول، بالاعتماد على: تراصف المتوسطات، قوة الحجم، واتجاه
    الهيستوغرام. كلما كان السوق أقوى، كلما استحق RR أعلى (اتجاه قوي
    يستحق ترك الأرباح تركض لهدف أبعد)، والعكس (سوق ضعيف → أهداف أقرب
    وأكثر واقعية، تحقيقاً لمبدأ الأفضلية بدل الطمع في اتجاه هش).

    المخرج: (market_strength: str, rr_target: float)
    """
    price = Final_Data["price"]
    ema9  = Final_Data["ema9"]
    ema21 = Final_Data["ema21"]
    ema50 = Final_Data["ema50"]
    volume_ratio = Final_Data["volume_ratio"]
    hist_now  = Final_Data["hist_now"]
    hist_prev = Final_Data["hist_prev"]

    score = 0
    if price > ema9 > ema21 > ema50:
        score += 2
    elif price > ema21:
        score += 1

    if volume_ratio > 1.5:
        score += 1

    if hist_now > hist_prev > 0:
        score += 1

    if score >= 3:
        return "strong", RR_STRONG_MARKET
    elif score >= 1:
        return "medium", RR_MEDIUM_MARKET
    else:
        return "weak", RR_WEAK_MARKET


# ══════════════════════════════════════════════
#   حساب وقف الخسارة الهيكلي — يُستدعى مرة واحدة فقط عند الدخول
# ══════════════════════════════════════════════
def Calc_SL_Price(entry_price: float, entry_atr: float, swing_low: float,
                   trend: str = "up", gap_pct: float = 0.0) -> float:
    """
    القاعدة الذهبية: SL في المكان الذي يثبت فيه فشل فكرة الدخول، وليس
    في المكان الذي تتحمل فيه الخسارة فقط. الأولوية للدعم الهيكلي
    (خلف آخر قاع حقيقي)، مع هامش أمان بسيط (ATR × 0.3) وحدود دنيا/
    قصوى منطقية تمنع وقفاً ضيقاً جداً (ضجيج) أو بعيداً جداً (مخاطرة
    غير مقبولة)، وعندها يُستبدل تلقائياً بطريقة ATR × 2 (ممتازة للبوت).

    تعديل حسب الاتجاه العام (طلب تدقيق يدوي): إذا كان الاتجاه العام
    هابطاً (trend="down")، يُبعَّد SL أكثر تحت الدعم/القاع الهيكلي
    بنسبة gap_pct إضافية (متوسط نسبة تباعد القيعان عن بعضها في هذا
    الاتجاه) — لأن احتمال كسر الدعم فعلياً أعلى في اتجاه هابط. في
    الاتجاه الصاعد (trend="up") لا يتغيّر شيء، ويبقى SL كما كان.
    """
    structural_sl = swing_low - (entry_atr * SL_STRUCTURE_ATR_BUFFER)
    if trend == "down" and gap_pct > 0 and swing_low > 0:
        structural_sl -= swing_low * (gap_pct / 100)
    atr_sl        = entry_price - (entry_atr * SL_ATR_MULTIPLIER)

    # الدعم غير منطقي (فوق سعر الدخول أو قيمة غير صالحة) → ATR مباشرة
    if swing_low <= 0 or structural_sl >= entry_price:
        return atr_sl

    structural_risk = entry_price - structural_sl
    min_risk = entry_atr * SL_MIN_RISK_ATR_MULTIPLIER
    max_risk = entry_price * SL_MAX_RISK_PCT

    if structural_risk < min_risk:
        # الدعم قريب جداً من الدخول — وقف بهذه الضيقة عرضة للضجيج
        return entry_price - min_risk
    if structural_risk > max_risk:
        # الدعم بعيد جداً — مخاطرة غير منطقية، استخدم ATR بدلاً منه
        return atr_sl

    return structural_sl


# ══════════════════════════════════════════════
#   حساب أهداف الربح (TP1 / TP2) — تُستدعى مرة واحدة عند الدخول
# ══════════════════════════════════════════════
def Calc_TP_Targets(entry_price: float, sl_price: float,
                     resistance_zones: list, rr_target: float,
                     trend: str = "neutral", gap_pct: float = 0.0):
    """
    TP1: أقرب مقاومة قوية أعلى الدخول (مع هامش ابتعاد عن الرقم
    الدائري بالضبط)، بشرط أن تحقق RR معقولاً (≥ MIN_TP1_RR) وإلا
    استُبدلت بهدف RR ثابت. TP2: المقاومة التالية، أو RR الديناميكي
    المبني على قوة السوق (rr_target) إن لم توجد مقاومة أبعد معروفة.

    تعديل حسب الاتجاه العام (طلب تدقيق يدوي): بدل استخدام مستوى
    المقاومة كما هو دائماً، يُعدَّل حسب الاتجاه العام (trend) ونسبة
    التذبذب (gap_pct، متوسط تباعد القمم عن بعضها في هذا الاتجاه):
    - اتجاه هابط: TP يُقرَّب من القمة نحو سعر الدخول بنسبة gap_pct —
      جني ربح أبكر قبل أن ينعكس السعر فعلياً، بدل انتظار وصول السعر
      للقمة كاملة وهو أمر أقل احتمالاً في اتجاه ضعيف/هابط.
    - اتجاه صاعد: TP يُبعَّد عن القمة بنسبة gap_pct — يترك مجالاً
      أكبر لاستمرار الاتجاه القوي بدل الخروج المبكر رغم استمرار الصعود.
    - اتجاه محايد (neutral) أو gap_pct=0: لا تغيير عن المنطق الأصلي.
    """
    risk = entry_price - sl_price
    if risk <= 0:
        risk = entry_price * 0.02   # حماية من قيمة غير منطقية

    resistances_above = sorted(r for r in resistance_zones if r > entry_price)

    def _adjust_level_for_trend(raw_level: float) -> float:
        if trend == "down" and gap_pct > 0:
            shrunk = raw_level - (raw_level * (gap_pct / 100))
            return max(shrunk, entry_price)
        if trend == "up" and gap_pct > 0:
            return raw_level * (1 + (gap_pct / 100))
        return raw_level

    # ── TP1 ─────
    if resistances_above:
        raw_tp1 = _adjust_level_for_trend(resistances_above[0])
        tp1 = raw_tp1 * (1 - TP_RESISTANCE_BUFFER_PCT)
        if (tp1 - entry_price) < (risk * MIN_TP1_RR):
            tp1 = entry_price + (risk * MIN_TP1_RR)
    else:
        tp1 = entry_price + (risk * MIN_TP1_RR)

    # ── TP2 ─────
    further_resistances = [r for r in resistances_above if r > tp1]
    if further_resistances:
        raw_tp2 = _adjust_level_for_trend(further_resistances[0])
        tp2 = raw_tp2 * (1 - TP_RESISTANCE_BUFFER_PCT)
        if (tp2 - entry_price) < (risk * rr_target):
            tp2 = entry_price + (risk * rr_target)
    else:
        tp2 = entry_price + (risk * rr_target)

    if tp2 <= tp1:
        tp2 = tp1 + (risk * 0.5)

    return tp1, tp2


# ══════════════════════════════════════════════
#   بناء إدارة المخاطرة الكاملة لمركز جديد — تُستدعى مرة واحدة فقط
#   فور تأكيد نجاح الشراء (تحل محل Calc_TP_Price القديمة)
# ══════════════════════════════════════════════
def Init_Position_Risk_Management(entry_price: float, entry_atr: float,
                                   Final_Data: dict, Raw_Data: list = None,
                                   Raw_Data_HTF: list = None) -> dict:
    """
    يبني كائن Position الكامل بكل حقول إدارة المخاطرة: SL هيكلي، TP1/
    TP2 ديناميكيان مبنيان على مناطق مقاومة حقيقية، وتقييم قوة السوق
    الذي يحدد RR المستهدف. يُستدعى من Manager.py مرة واحدة فقط فور
    تأكيد نجاح الشراء، بدل الدالة القديمة Calc_TP_Price.
    """
    swing_low = Final_Data["swing_low"]
    resistance_source = Raw_Data_HTF if Raw_Data_HTF else Raw_Data
    resistance_zones = (
        _find_strong_resistance_zones(resistance_source)
        if resistance_source else []
    )

    # ── كشف الاتجاه العام لتعديل SL/TP (طلب تدقيق يدوي) ─────
    trend_for_tp, gap_pct_for_tp = (
        _detect_trend_and_gap_pct(resistance_source, use_highs=True)
        if resistance_source else ("neutral", 0.0)
    )
    trend_for_sl, gap_pct_for_sl = (
        _detect_trend_and_gap_pct(resistance_source, use_highs=False)
        if resistance_source else ("up", 0.0)
    )

    market_strength, rr_target = _assess_market_strength(Final_Data)
    sl_price = Calc_SL_Price(
        entry_price, entry_atr, swing_low,
        trend=trend_for_sl, gap_pct=gap_pct_for_sl
    )
    tp1_price, tp2_price = Calc_TP_Targets(
        entry_price, sl_price, resistance_zones, rr_target,
        trend=trend_for_tp, gap_pct=gap_pct_for_tp
    )

    print(
        f"[Exit_Decision] 🎯 إدارة مخاطرة جديدة | دخول={entry_price:.5f} | "
        f"SL={sl_price:.5f} | TP1={tp1_price:.5f} | TP2={tp2_price:.5f} | "
        f"قوة السوق={market_strength} (RR={rr_target}) | "
        f"مقاومات مكتشفة={len(resistance_zones)} | "
        f"اتجاه TP={trend_for_tp}({gap_pct_for_tp:.2f}%) | "
        f"اتجاه SL={trend_for_sl}({gap_pct_for_sl:.2f}%)"
    )

    return {
        "entry_price"     : entry_price,
        "entry_atr"       : entry_atr,
        "sl_price"        : sl_price,
        "tp1_price"       : tp1_price,
        "tp2_price"       : tp2_price,
        "tp1_done"        : False,
        "tp2_done"        : False,
        "remaining_pct"   : 1.0,
        "trailing_active" : False,
        "trailing_stop"   : None,
        "highest_price"   : entry_price,
        "cycles_held"     : 0,
        "market_strength" : market_strength,
        "rr_target"       : rr_target,
    }


def Exit_Decision(Final_Data: dict, Position: dict) -> dict:
    """
    تُدار الصفقة عبر طبقات مرتّبة من الأخطر إلى الأقل خطورة:
      0) SL الهيكلي الثابت (فشل فرضية الدخول) — لا يجوز عكس أولويته
      1) الوقف الزمني (صفقة راكدة بلا تقدّم ولا زخم)
      2) TP1 / TP2 (خروج جزئي عند مناطق مقاومة حقيقية)
      3) Trailing Stop للجزء المتبقي بعد TP1
      4) خروج طارئ رابح مبكر (قبل الوصول لأي هدف، عند ضعف زخم مفاجئ)

    المخرج: dict — انظر توثيق العقد الجديد في رأس الملف.
    """
    price     = Final_Data["price"]
    atr       = Final_Data["atr"]
    swing_low = Final_Data["swing_low"]
    volume_ratio = Final_Data["volume_ratio"]
    rsi_now   = Final_Data["rsi_now"]
    rsi_prev  = Final_Data["rsi_prev"]
    hist_now  = Final_Data["hist_now"]
    hist_prev = Final_Data["hist_prev"]

    entry_price = Position["entry_price"]
    entry_atr   = Position["entry_atr"]
    sl_price    = Position["sl_price"]
    tp1_price   = Position["tp1_price"]
    tp2_price   = Position["tp2_price"]
    tp1_done    = Position.get("tp1_done", False)
    tp2_done    = Position.get("tp2_done", False)
    remaining_pct   = Position.get("remaining_pct", 1.0)
    trailing_active = Position.get("trailing_active", False)
    trailing_stop   = Position.get("trailing_stop")
    highest_price   = max(Position.get("highest_price", entry_price), price)
    cycles_held     = Position.get("cycles_held", 0) + 1

    profit = price - entry_price

    updated_position = dict(Position)
    updated_position["highest_price"] = highest_price
    updated_position["cycles_held"]   = cycles_held

    # ══════════════════════════════════════════════
    #   الطبقة 0 — SL الهيكلي الثابت (أولوية قصوى، لا يُتنازل عنها)
    # ══════════════════════════════════════════════
    if price <= sl_price:
        log = (
            f"[Exit_Decision] SELL (SL هيكلي) | السعر={price:.5f} | "
            f"SL={sl_price:.5f} | ربح/خسارة={profit:.5f}"
        )
        print(log)
        return {
            "action": "SELL_SL",
            "sell_fraction": remaining_pct,
            "updated_position": updated_position,
            "log": log,
        }

    # ══════════════════════════════════════════════
    #   الطبقة 1 — الوقف الزمني (صفقة راكدة بلا تقدّم ولا زخم)
    # ══════════════════════════════════════════════
    if cycles_held >= TIME_STOP_CYCLES and not tp1_done:
        min_progress = entry_atr * TIME_STOP_MIN_PROGRESS_ATR
        momentum_dead = hist_now <= hist_prev and volume_ratio < 1.0
        if profit < min_progress and momentum_dead:
            log = (
                f"[Exit_Decision] SELL (وقف زمني) | بعد {cycles_held} دورة "
                f"بلا تقدّم كافٍ | السعر={price:.5f} | ربح={profit:.5f}"
            )
            print(log)
            return {
                "action": "SELL_TIME_STOP",
                "sell_fraction": remaining_pct,
                "updated_position": updated_position,
                "log": log,
            }

    # ══════════════════════════════════════════════
    #   الطبقة 2 — TP1 (خروج جزئي أول + تفعيل Trailing Stop)
    # ══════════════════════════════════════════════
    if not tp1_done and price >= tp1_price:
        updated_position["tp1_done"]        = True
        updated_position["remaining_pct"]   = remaining_pct - TP1_SELL_FRACTION
        updated_position["trailing_active"] = True
        updated_position["trailing_stop"]   = price - (atr * TRAIL_ATR_MULTIPLIER)

        log = (
            f"[Exit_Decision] SELL_TP1_PARTIAL ({TP1_SELL_FRACTION*100:.0f}%) | "
            f"السعر={price:.5f} | TP1={tp1_price:.5f} | "
            f"تفعيل Trailing عند={updated_position['trailing_stop']:.5f}"
        )
        print(log)
        return {
            "action": "SELL_TP1_PARTIAL",
            "sell_fraction": TP1_SELL_FRACTION,
            "updated_position": updated_position,
            "log": log,
        }

    # ══════════════════════════════════════════════
    #   الطبقة 3 — TP2 (خروج جزئي ثانٍ)
    # ══════════════════════════════════════════════
    if tp1_done and not tp2_done and price >= tp2_price:
        updated_position["tp2_done"]      = True
        updated_position["remaining_pct"] = remaining_pct - TP2_SELL_FRACTION
        # تشديد التريلينغ قليلاً بعد TP2 لحماية أرباح الجزء الأخير
        new_trail = price - (atr * TRAIL_ATR_MULTIPLIER * 0.75)
        if trailing_stop is None or new_trail > trailing_stop:
            updated_position["trailing_stop"] = new_trail

        log = (
            f"[Exit_Decision] SELL_TP2_PARTIAL ({TP2_SELL_FRACTION*100:.0f}%) | "
            f"السعر={price:.5f} | TP2={tp2_price:.5f}"
        )
        print(log)
        return {
            "action": "SELL_TP2_PARTIAL",
            "sell_fraction": TP2_SELL_FRACTION,
            "updated_position": updated_position,
            "log": log,
        }

    # ══════════════════════════════════════════════
    #   الطبقة 4 — تحديث/تفعيل Trailing Stop (بعد TP1)
    # ══════════════════════════════════════════════
    if trailing_active:
        candidate_trail = price - (atr * TRAIL_ATR_MULTIPLIER)
        if trailing_stop is None or candidate_trail > trailing_stop:
            trailing_stop = candidate_trail
            updated_position["trailing_stop"] = trailing_stop

        if price <= trailing_stop:
            log = (
                f"[Exit_Decision] SELL_TRAIL | السعر={price:.5f} | "
                f"Trailing={trailing_stop:.5f} | ربح نهائي={profit:.5f}"
            )
            print(log)
            return {
                "action": "SELL_TRAIL",
                "sell_fraction": remaining_pct,
                "updated_position": updated_position,
                "log": log,
            }

    # ══════════════════════════════════════════════
    #   الطبقة 5 — خروج طارئ رابح مبكر (فقط قبل تحقق TP1 وقبل تفعيل
    #   Trailing، لتفادي التعارض مع الإدارة الجزئية بعد ذلك)
    #
    #   ⚠️ نظام "الإنذار المبكر" القديم (نقاط SL بديلة: كسر دعم/حجم/
    #   RSI/MACD ≥ 3 من 4 نقاط ← بيع فوري قبل الوصول لـ SL الحقيقي)
    #   أُلغي بالكامل هنا بناءً على تدقيق الـ Log: كان هذا النظام هو
    #   المسؤول عن كل الخسائر المسجَّلة (بيع طارئ عند سعر أعلى بكثير
    #   من SL الهيكلي الفعلي، رغم عدم وصول السعر له فعلياً). SL الوحيد
    #   المعتمد الآن للحالات الخاسرة هو السعر الهيكلي الثابت في
    #   الطبقة 0 أعلاه فقط — لا بديل نقطي آخر.
    # ══════════════════════════════════════════════
    if not tp1_done:
        min_profit_required = entry_atr * MIN_PROFIT_ATR_MULTIPLIER
        has_enough_profit = profit >= min_profit_required
        momentum_weakening = (
            (hist_prev >= 0 > hist_now)
            or (rsi_prev >= 50 > rsi_now)
        )

        if has_enough_profit and momentum_weakening:
            log = (
                f"[Exit_Decision] SELL (خروج طارئ رابح مبكر) | "
                f"السعر={price:.5f} | ربح={profit:.5f} | "
                f"سبب={'MACD' if hist_prev >= 0 > hist_now else 'RSI'}"
            )
            print(log)
            return {
                "action": "SELL_SL",   # يُعامَل كخروج كامل فوري
                "sell_fraction": remaining_pct,
                "updated_position": updated_position,
                "log": log,
            }

    # ══════════════════════════════════════════════
    #   لا يوجد سبب للخروج — استمرار الاحتفاظ بالمركز
    # ══════════════════════════════════════════════
    if not tp1_done:
        log = (
            f"[Exit_Decision] HOLD | السعر={price:.5f} | SL={sl_price:.5f} | "
            f"TP1={tp1_price:.5f} | ربح حالي={profit:.5f} | دورة={cycles_held}"
        )
    else:
        trail_txt = f"{trailing_stop:.5f}" if trailing_stop is not None else "—"
        tp2_txt = "✅" if tp2_done else f"{tp2_price:.5f}"
        log = (
            f"[Exit_Decision] HOLD | السعر={price:.5f} | SL={sl_price:.5f} | "
            f"TP1=✅ | TP2={tp2_txt} | Trailing={trail_txt} | "
            f"متبقٍّ={remaining_pct*100:.0f}% | ربح حالي={profit:.5f}"
        )
    print(log)
    return {
        "action": "HOLD",
        "sell_fraction": 0.0,
        "updated_position": updated_position,
        "log": log,
    }
