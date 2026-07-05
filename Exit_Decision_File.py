"""
ملف: Exit_Decision_File.py
الوظيفة: اتخاذ قرار الخروج (SELL / HOLD) للحالات الطارئة فقط
         (SL مؤكد أو خروج طارئ رابح). TP لم يعد يُفحص هنا — يُنفَّذ
         تلقائياً عبر أمر بيع حدّي (LIMIT) موضوع على المنصة مباشرة
         بعد الدخول (انظر Manager.py + Decision_Execution_File.py).
         يعمل فقط بعد فتح مركز — Manager.py يمرر له البيانات في هذه
         الحالة فقط، مع معلومات المركز المفتوح (Position).
المسار: Super_Trader/Exit_Decision_File.py

الترتيب (من الأخطر إلى الأقل خطورة — لا يجوز عكسه):
    1) SL مؤكَّد   — حماية رأس المال، أولوية قصوى، صعب التحقق عمداً
    2) خروج طارئ رابح — يعمل قبل وصول TP (الذي يُدار خارجياً الآن)

قبل تنفيذ أي SELL من هذا الملف، Manager.py يجب أن يُلغي أمر TP الحدّي
المعلَّق أولاً (Cancel_Order) — وإلا قد ينتج تعارض بين أمرين على نفس
الرصيد.

═══════════════════════════════════════════════════════
   متطلبات Position (يُبنى ويُحدَّث في Manager.py)
═══════════════════════════════════════════════════════
Position = {
    "entry_price" : float,     # سعر الدخول الفعلي
    "entry_atr"   : float,     # قيمة ATR وقت الدخول بالضبط
    "tp_price"    : float,     # سعر أمر TP الحدّي الموضوع فعلياً على
                                #   المنصة (بعد تأكيد الحد الأدنى 0.5%)
    "tp_order_id" : str|None,  # orderId الخاص بأمر TP الحدّي المعلَّق
}
"""


# ══════════════════════════════════════════════
#   الثوابت القابلة للضبط
# ══════════════════════════════════════════════

# TP = entry_price + (entry_atr × هذا الرقم) — يُحسب مرة واحدة عند
# الدخول عبر Calc_TP_Price() ويُستخدم لوضع أمر LIMIT فعلي على المنصة
TP_ATR_MULTIPLIER = 1.8

# الحد الأدنى المطلق لـ TP كنسبة من سعر الدخول — بغض النظر عن ATR،
# TP يجب ألا يقل عن هذي النسبة فوق سعر الدخول (تأكيد قبل وضع الأمر)
MIN_TP_PCT = 0.005   # 0.5%

# الحد الأدنى للربح المطلوب حتى يُسمح بالخروج الطارئ الرابح
# (كنسبة من ATR وقت الدخول)
MIN_PROFIT_ATR_MULTIPLIER = 0.5

# نظام نقاط تأكيد SL — يجب تحقق SL_SCORE_THRESHOLD من أصل 4 معايير
SL_SCORE_THRESHOLD   = 3
VOLUME_CONFIRM_LEVEL = 1.2   # حجم أعلى من المتوسط بهذه النسبة يؤكد الكسر
RSI_WEAKNESS_LEVEL   = 45    # RSI تحت هذا المستوى يؤكد ضعف الزخم


def Calc_TP_Price(entry_price: float, entry_atr: float) -> float:
    """
    يحسب سعر TP النهائي — يُستدعى مرة واحدة فقط فور تنفيذ الشراء، والنتيجة
    تُستخدم لوضع أمر LIMIT فعلي على المنصة (تبقى ثابتة طوال عمر الصفقة).

    مرحلة التأكيد: TP المحسوب من ATR يجب أن يكون على الأقل 0.5% أعلى من
    سعر الدخول. لو كان أقل (مثلاً بسبب تقلب منخفض جداً وقت الدخول)،
    يُرفع تلقائياً لهذا الحد الأدنى المطلق.
    """
    raw_tp = entry_price + (entry_atr * TP_ATR_MULTIPLIER)
    min_tp = entry_price * (1 + MIN_TP_PCT)

    if raw_tp < min_tp:
        print(
            f"[Exit_Decision] ⚠️ TP المحسوب من ATR ({raw_tp:.6f}) أقل من "
            f"الحد الأدنى {MIN_TP_PCT*100:.1f}% ({min_tp:.6f}) — تم رفعه."
        )
        return min_tp

    return raw_tp


def Exit_Decision(Final_Data: dict, Position: dict) -> str:
    """
    تحلّل Final_Data وحالة المركز المفتوح وتُعيد قرار الخروج.

    المدخلات:
        Final_Data : dict — نفس مخرجات Indicator_Calculation
        Position   : dict — {"entry_price": float, "entry_atr": float}

    المخرج:
        Decision : str — "SELL" | "HOLD"
    """

    price      = Final_Data["price"]
    swing_low  = Final_Data["swing_low"]
    volume_ratio = Final_Data["volume_ratio"]
    rsi_now    = Final_Data["rsi_now"]
    rsi_prev   = Final_Data["rsi_prev"]
    hist_now   = Final_Data["hist_now"]
    hist_prev  = Final_Data["hist_prev"]

    entry_price = Position["entry_price"]
    entry_atr   = Position["entry_atr"]

    profit = price - entry_price

    # ══════════════════════════════════════════════
    #   الطبقة 1 — SL مؤكَّد (أولوية قصوى)
    #   نظام نقاط: يجب تحقق 3 من 4 معايير معاً حتى يُفعَّل
    #   الهدف: تجنّب الخروج بسبب إشارة هبوط ضعيفة/كاذبة (whipsaw)
    # ══════════════════════════════════════════════
    sl_score = 0
    sl_reasons = []

    if price < swing_low:                      # إغلاق فعلي تحت الدعم الحقيقي
        sl_score += 1
        sl_reasons.append("كسر دعم")
    if volume_ratio > VOLUME_CONFIRM_LEVEL:     # حجم يؤكد قوة الكسر
        sl_score += 1
        sl_reasons.append("حجم مؤكِّد")
    if rsi_now < RSI_WEAKNESS_LEVEL:            # RSI يؤكد ضعف الزخم
        sl_score += 1
        sl_reasons.append("RSI ضعيف")
    if hist_now < hist_prev < 0:                # هيستوغرام MACD هابط وسالب
        sl_score += 1
        sl_reasons.append("MACD هابط")

    if sl_score >= SL_SCORE_THRESHOLD:
        print(
            f"[Exit_Decision] SELL (SL مؤكَّد) | نقاط={sl_score}/4 "
            f"({', '.join(sl_reasons)}) | السعر={price:.4f} | "
            f"ربح/خسارة={profit:.4f}"
        )
        return "SELL"

    # ══════════════════════════════════════════════
    #   الطبقة 2 — خروج طارئ رابح
    #   يعمل قبل وصول TP (الذي يُدار خارجياً عبر أمر حدّي على المنصة)
    #   شرطان معاً: (أ) ربح كافٍ  (ب) إشارة ضعف زخم مبكرة
    # ══════════════════════════════════════════════
    min_profit_required = entry_atr * MIN_PROFIT_ATR_MULTIPLIER
    has_enough_profit = profit >= min_profit_required

    momentum_weakening = (
        (hist_prev >= 0 > hist_now)          # هيستوغرام MACD يتحول سالب الآن
        or (rsi_prev >= 50 > rsi_now)        # RSI يكسر 50 هابطاً الآن
    )

    if has_enough_profit and momentum_weakening:
        print(
            f"[Exit_Decision] SELL (خروج طارئ رابح) | السعر={price:.4f} | "
            f"ربح={profit:.4f} (الحد الأدنى={min_profit_required:.4f}) | "
            f"سبب الضعف={'MACD' if hist_prev >= 0 > hist_now else 'RSI'}"
        )
        return "SELL"

    # ══════════════════════════════════════════════
    #   لا يوجد سبب للخروج — استمرار الاحتفاظ بالمركز
    #   (TP يبقى معلَّقاً كأمر حدّي على المنصة، يُفحص عبر Get_Order_Status
    #   في Manager.py وليس هنا)
    # ══════════════════════════════════════════════
    print(
        f"[Exit_Decision] HOLD | السعر={price:.4f} | هدف TP المعلَّق="
        f"{Position.get('tp_price', 0):.4f} | ربح حالي={profit:.4f} | "
        f"نقاط SL={sl_score}/4"
    )
    return "HOLD"
