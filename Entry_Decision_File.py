# -*- coding: utf-8 -*-
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
"""

# ══════════════════════════════════════════════
#   فلتر قوة تقاطع MACD
# ══════════════════════════════════════════════
MIN_MACD_STRENGTH_ATR_RATIO = 0.05

# ══════════════════════════════════════════════
#   حدود الحجم المستقلة لكل مسار
# ══════════════════════════════════════════════
MIN_VOLUME_PATH1 = 0.8   # تقاطع الزخم الأصلي
MIN_VOLUME_PATH2 = 0.7   # استمرار الزخم
MIN_VOLUME_PATH3 = 0.5   # ارتداد الدعم
MIN_VOLUME_PATH5 = 0.7   # ارتداد دعم قوي + انعكاس
MIN_VOLUME_PATH6 = 0.6   # كسر هيكل مبكر
MIN_VOLUME_PATH7 = 0.35  # انحراف صعودي (يحدث عادة بحجم هادئ وقت التجميع)

# سقف أعلى للحجم في مسار 1 و2 فقط — حجم انفجاري متطرف (> هذا الرقم)
# في هذا الزوج أثبت أنه غالباً "قمة شرائية/تصريف" (Buying Climax) تليها
# ردّة فعل هابطة فورية، وليس استمراراً حقيقياً للزخم (شوهد ذلك في صفقة
# دخلت بحجم 2.08x ثم هبطت فوراً حتى SL). المسارات الأخرى (3/5/6/7) لا
# تتأثر لأنها ترتبط بارتدادات/انعكاسات لا زخم استمراري صرف.
MAX_VOLUME_CLIMAX_RATIO = 2.0

# ══════════════════════════════════════════════
#   إعدادات تحديد مناطق الدعم (مسار 5 + بوّابة الأفضلية)
# ══════════════════════════════════════════════
SUPPORT_LOOKBACK_CANDLES       = 100
SUPPORT_CLUSTER_TOLERANCE_PCT  = 0.3
SUPPORT_MIN_TOUCHES            = 2
NEAR_SUPPORT_ATR_MULTIPLIER    = 0.5
RSI_OVERSOLD_THRESHOLD         = 32

# ══════════════════════════════════════════════
#   إعدادات تحديد مناطق المقاومة (بوّابة الأفضلية — مرآة للدعم)
# ══════════════════════════════════════════════
RESISTANCE_LOOKBACK_CANDLES      = 100
RESISTANCE_CLUSTER_TOLERANCE_PCT = 0.3
RESISTANCE_MIN_TOUCHES           = 2
TP_RESISTANCE_BUFFER_PCT         = 0.0015   # نفس منطق Exit_Decision تماماً

# ══════════════════════════════════════════════
#   إعدادات فلتر "الهبوط بعد قمة" (Post-Spike Exhaustion Filter)
# ══════════════════════════════════════════════
EXHAUSTION_LOOKBACK_CANDLES        = 15
EXHAUSTION_PULLBACK_ATR_MULTIPLIER = 1.2

# ══════════════════════════════════════════════
#   إعدادات مسار 6 — كسر هيكل مبكر
# ══════════════════════════════════════════════
STRUCTURE_LOOKBACK_CANDLES = 40

# ══════════════════════════════════════════════
#   إعدادات مسار 7 — انحراف صعودي RSI
# ══════════════════════════════════════════════
DIVERGENCE_RSI_CEILING = 45

# ══════════════════════════════════════════════
#   إعدادات SL الافتراضي المستخدم في بوّابة الأفضلية فقط
# ══════════════════════════════════════════════
GATE_SL_STRUCTURE_ATR_BUFFER   = 0.3
GATE_SL_ATR_MULTIPLIER         = 1.5
GATE_SL_MIN_RISK_ATR_MULTIPLIER = 0.8
GATE_SL_MAX_RISK_PCT           = 0.08

# أقل RR مقبول لدخول الصفقة أصلاً
MIN_ACCEPTABLE_ENTRY_RR = 1.1

# ══════════════════════════════════════════════
#   إعدادات كشف الاتجاه العام لتعديل SL/TP الديناميكي في بوّابة
#   الأفضلية (مرآة تماماً لنفس المنطق في Exit_Decision_File.py، حتى
#   يتطابق تقدير RR وقت الدخول مع إدارة المخاطرة الفعلية بعد الدخول)
# ══════════════════════════════════════════════
TREND_GAP_PCT_CAP = 5.0


# ══════════════════════════════════════════════
#   دالة مساعدة: تحديد مناطق الدعم القوية من الشموع الخام
# ══════════════════════════════════════════════
def _find_strong_support_zones(candles):
    if not candles or len(candles) < 5:
        return []

    recent = candles[-SUPPORT_LOOKBACK_CANDLES:] \
        if len(candles) > SUPPORT_LOOKBACK_CANDLES else candles

    lows = [c[3] for c in recent]

    swing_lows = []
    for i in range(1, len(lows) - 1):
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swing_lows.append(lows[i])

    if not swing_lows:
        return []

    swing_lows.sort()

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

    return [
        sum(zone) / len(zone)
        for zone in zones
        if len(zone) >= SUPPORT_MIN_TOUCHES
    ]


# ══════════════════════════════════════════════
#   دالة مساعدة: تحديد مناطق المقاومة القوية (مرآة للدعم)
# ══════════════════════════════════════════════
def _find_strong_resistance_zones(candles):
    if not candles or len(candles) < 5:
        return []

    recent = candles[-RESISTANCE_LOOKBACK_CANDLES:] \
        if len(candles) > RESISTANCE_LOOKBACK_CANDLES else candles

    highs = [c[2] for c in recent]

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

    return [
        sum(zone) / len(zone)
        for zone in zones
        if len(zone) >= RESISTANCE_MIN_TOUCHES
    ]


# ══════════════════════════════════════════════
#   دالة مساعدة: كشف الاتجاه العام + متوسط نسبة التذبذب
#   (يُستخدم لتعديل تقدير SL/TP في بوّابة الأفضلية بحسب الاتجاه)
# ══════════════════════════════════════════════
def _detect_trend_and_gap_pct(candles, use_highs):
    """
    يحدد الاتجاه العام (up/down/neutral) بمقارنة آخر قمتين (أو قاعين)
    متأرجحتين ضمن نفس شموع الدعم/المقاومة، ويحسب متوسط النسبة المئوية
    للمسافة بين القمم (أو القيعان) المتتالية كمقياس لقوة التذبذب في
    هذا الاتجاه — نفس منطق Exit_Decision_File.py تماماً.
    """
    if not candles or len(candles) < 5:
        return "neutral", 0.0

    recent = candles[-RESISTANCE_LOOKBACK_CANDLES:] \
        if len(candles) > RESISTANCE_LOOKBACK_CANDLES else candles

    idx = 2 if use_highs else 3
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
#   دالة مساعدة: كشف "الهبوط بعد قمة" (Post-Spike Pullback)
# ══════════════════════════════════════════════
def _is_post_spike_pullback(candles, atr):
    if not candles or len(candles) < 3 or atr <= 0:
        return False

    recent = candles[-EXHAUSTION_LOOKBACK_CANDLES:] \
        if len(candles) > EXHAUSTION_LOOKBACK_CANDLES else candles

    recent_high   = max(c[2] for c in recent)
    current_close = recent[-1][4]

    pullback_amount = recent_high - current_close
    return pullback_amount >= (atr * EXHAUSTION_PULLBACK_ATR_MULTIPLIER)


# ══════════════════════════════════════════════
#   دالة مساعدة: كشف شمعة ابتلاعية صعودية
# ══════════════════════════════════════════════
def _is_bullish_engulfing(candles):
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


# ══════════════════════════════════════════════
#   دالة مساعدة: كسر هيكل مبكر (Higher Low + كسر مقاومة صغيرة بينهما)
# ══════════════════════════════════════════════
def _detect_early_structure_break(candles):
    if not candles or len(candles) < 6:
        return False, None

    recent = candles[-STRUCTURE_LOOKBACK_CANDLES:] \
        if len(candles) > STRUCTURE_LOOKBACK_CANDLES else candles

    swing_lows = []
    for i in range(1, len(recent) - 1):
        if recent[i][3] < recent[i - 1][3] and recent[i][3] < recent[i + 1][3]:
            swing_lows.append((i, recent[i][3]))

    if len(swing_lows) < 2:
        return False, None

    idx_prev, low_prev = swing_lows[-2]
    idx_last, low_last = swing_lows[-1]

    if low_last <= low_prev:
        return False, None

    between = recent[idx_prev:idx_last + 1]
    minor_resistance = max(c[2] for c in between)

    return True, minor_resistance


# ══════════════════════════════════════════════
#   بوّابة الأفضلية (RR Gate) — محسنة ديناميكياً للسكالبينج
# ══════════════════════════════════════════════
def _passes_edge_gate(price, atr, swing_low, resistance_zones, candles=None,
                       trend_sl="up", gap_pct_sl=0.0,
                       trend_tp="neutral", gap_pct_tp=0.0):
    """
    تحسب SL وTP1 افتراضيين بدقة عالية بناء على القيعان والمقاومات الهيكلية.
    تم تطويرها لتأخذ بالاعتبار القيعان القريبة الحالية لحماية الصفقات الفورية.

    تُعدَّل SL/TP1 حسب الاتجاه العام (نفس منطق Exit_Decision_File.py):
    - اتجاه هابط: SL يُبعَّد أكثر تحت الدعم (مخاطرة أعلى محتملة لكسر
      الدعم)، وTP1 يُقرَّب من القمة نحو السعر الحالي (جني ربح أبكر
      قبل الانعكاس المحتمل بدل انتظار القمة كاملة).
    - اتجاه صاعد: SL كما هو (بدون تعديل)، وTP1 يُبعَّد عن القمة
      (مساحة أكبر لاستمرار اتجاه قوي).
    """
    local_low = swing_low
    if candles and len(candles) >= 5:
        local_low = min(c[3] for c in candles[-5:])

    target_low = local_low if (0 < local_low < price) else swing_low

    structural_sl = target_low - (atr * GATE_SL_STRUCTURE_ATR_BUFFER)
    if trend_sl == "down" and gap_pct_sl > 0 and target_low > 0:
        structural_sl -= target_low * (gap_pct_sl / 100)
    atr_sl        = price - (atr * GATE_SL_ATR_MULTIPLIER)

    if target_low <= 0 or structural_sl >= price:
        sl_estimate = atr_sl
    else:
        structural_risk = price - structural_sl
        min_risk = atr * GATE_SL_MIN_RISK_ATR_MULTIPLIER
        max_risk = price * GATE_SL_MAX_RISK_PCT
        if structural_risk < min_risk:
            sl_estimate = price - min_risk
        elif structural_risk > max_risk:
            sl_estimate = atr_sl
        else:
            sl_estimate = structural_sl

    risk = price - sl_estimate
    if risk <= 0:
        return False, 0.0, sl_estimate, price

    resistances_above = sorted(r for r in resistance_zones if r > price)
    if resistances_above:
        raw_tp1 = resistances_above[0]
        if trend_tp == "down" and gap_pct_tp > 0:
            raw_tp1 = max(raw_tp1 - raw_tp1 * (gap_pct_tp / 100), price)
        elif trend_tp == "up" and gap_pct_tp > 0:
            raw_tp1 = raw_tp1 * (1 + gap_pct_tp / 100)
        tp1_estimate = raw_tp1 * (1 - TP_RESISTANCE_BUFFER_PCT)
    else:
        tp1_estimate = price + (risk * MIN_ACCEPTABLE_ENTRY_RR)

    reward = tp1_estimate - price
    if reward <= 0:
        return False, 0.0, sl_estimate, tp1_estimate

    rr = reward / risk
    return (rr >= MIN_ACCEPTABLE_ENTRY_RR), rr, sl_estimate, tp1_estimate


def _chk(passed: bool) -> str:
    return "✅" if passed else "❌"


def _print_full_cycle_diagnostics(price, ema9, ema21, ema50, rsi_now, rsi_prev,
                                   macd_line, signal_line, hist_now, hist_prev,
                                   volume_ratio, obv_now, obv_prev, swing_low,
                                   swing_high, low_now, atr, macd_strength_ok,
                                   post_spike_pullback, path_conditions,
                                   support_zones, near_strong_support,
                                   bullish_engulfing, rsi_oversold,
                                   resistance_zones, any_path_triggered,
                                   gate_passed, rr, sl_est, tp1_est,
                                   triggered_paths, Decision, Decision_prev):
    print("╔" + "═" * 58 + "╗")
    print("║  [Entry_Decision] تشخيص كامل للدورة (نسخة محسنة)        ║")
    print("╚" + "═" * 58 + "╝")
    print(f"[Entry_Decision] 📊 السعر={price:.5f} | ATR={atr:.5f} | low_now={low_now:.5f}")
    print(f"[Entry_Decision] 📊 EMA9={ema9:.5f} | EMA21={ema21:.5f} | EMA50={ema50:.5f}")
    print(f"[Entry_Decision] 📊 RSI الآن={rsi_now:.2f} | حجم(نسبة)={volume_ratio:.2f}x")
    print(f"[Entry_Decision] 📊 MACD={macd_line:.6f} | Hist الآن={hist_now:.6f}")

    for path_name, conditions, achieved in path_conditions:
        status_line = " | ".join(f"{_chk(cond_ok)} {cond_label}" for cond_label, cond_ok, _ in conditions)
        overall = "✅ محقق" if achieved else "❌ غير محقق"
        print(f"[Entry_Decision] 🧩 {path_name} → {overall} | {status_line}")

    if any_path_triggered:
        print(f"[Entry_Decision] 🎯 بوّابة الأفضلية (RR Gate) → {_chk(gate_passed)} | RR≈{rr:.2f} | SL={sl_est:.5f} | TP1={tp1_est:.5f}")
    else:
        print("[Entry_Decision] 🎯 بوّابة الأفضلية (RR Gate) → لم تُفحص")
    print(f"[Entry_Decision] 🏁 الخلاصة: القرار={Decision} | المشغلات: {', '.join(triggered_paths) if triggered_paths else 'لا شيء'}")


def Entry_Decision(Final_Data: dict, Decision_prev: str,
                    Raw_Data: list, Raw_Data_HTF: list = None) -> str:
    """
    تحلّل Final_Data وتُعيد قرار الدخول الفوري المحسن والآمن من الانعكاسات الحادة.
    """
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

    macd_strength_ok = abs(hist_now) >= (atr * MIN_MACD_STRENGTH_ATR_RATIO)
    post_spike_pullback = _is_post_spike_pullback(Raw_Data, atr)

    # ══════════════════════════════════════════════
    #   مسار 1 — تقاطع الزخم الأصلي (Fresh Cross)
    # ══════════════════════════════════════════════
    p1_c1 = price > ema21
    p1_c2 = macd_line > signal_line
    p1_c3 = macd_strength_ok
    p1_c4 = 50 < rsi_now < 65
    p1_c5 = MIN_VOLUME_PATH1 < volume_ratio <= MAX_VOLUME_CLIMAX_RATIO
    p1_c6 = not post_spike_pullback
    path1 = p1_c1 and p1_c2 and p1_c3 and p1_c4 and p1_c5 and p1_c6
    path1_conditions = [
        ("price>EMA21", p1_c1, f"{price:.4f}>{ema21:.4f}"),
        ("MACD>Signal", p1_c2, f"{macd_line:.6f}>{signal_line:.6f}"),
        ("قوة MACD", p1_c3, f"|hist|={abs(hist_now):.6f}"),
        ("50<RSI<65", p1_c4, f"{rsi_now:.2f}"),
        (f"{MIN_VOLUME_PATH1}<حجم<={MAX_VOLUME_CLIMAX_RATIO}", p1_c5, f"{volume_ratio:.2f}x"),
        ("لا هبوط بعد قمة", p1_c6, str(not post_spike_pullback)),
    ]

    # ══════════════════════════════════════════════
    #   مسار 2 — استمرار الزخم (Momentum Continuation)
    # ══════════════════════════════════════════════
    p2_c1 = price > ema9 > ema21
    p2_c2 = hist_now > hist_prev > 0
    p2_c3 = macd_strength_ok
    p2_c4 = 45 < rsi_now < 65
    p2_c5 = MIN_VOLUME_PATH2 < volume_ratio <= MAX_VOLUME_CLIMAX_RATIO
    p2_c6 = not post_spike_pullback
    path2 = p2_c1 and p2_c2 and p2_c3 and p2_c4 and p2_c5 and p2_c6
    path2_conditions = [
        ("price>EMA9>EMA21", p2_c1, f"{price:.4f}>{ema9:.4f}>{ema21:.4f}"),
        ("Hist تصاعدي وموجب", p2_c2, f"{hist_now:.6f}>{hist_prev:.6f}>0"),
        ("قوة MACD", p2_c3, f"|hist|={abs(hist_now):.6f}"),
        ("45<RSI<65", p2_c4, f"{rsi_now:.2f}"),
        (f"{MIN_VOLUME_PATH2}<حجم<={MAX_VOLUME_CLIMAX_RATIO}", p2_c5, f"{volume_ratio:.2f}x"),
        ("لا هبوط بعد قمة", p2_c6, str(not post_spike_pullback)),
    ]

    # ══════════════════════════════════════════════
    #   مسار 3 — الارتداد من الدعم الحقيقي (Pullback Bounce)
    # ══════════════════════════════════════════════
    p3_c1 = price > ema50
    p3_c2 = low_now >= swing_low
    p3_c3 = rsi_prev < 50 <= rsi_now
    p3_c4 = obv_now > obv_prev
    p3_c5 = volume_ratio > MIN_VOLUME_PATH3
    p3_c6 = not post_spike_pullback
    path3 = p3_c1 and p3_c2 and p3_c3 and p3_c4 and p3_c5 and p3_c6
    path3_conditions = [
        ("price>EMA50", p3_c1, f"{price:.4f}>{ema50:.4f}"),
        ("low_now>=swing_low", p3_c2, f"{low_now:.4f}>={swing_low:.4f}"),
        ("RSI عبر 50 صعوداً", p3_c3, f"{rsi_prev:.2f}<50<={rsi_now:.2f}"),
        ("OBV تصاعدي", p3_c4, f"{obv_now:.2f}>{obv_prev:.2f}"),
        (f"حجم>{MIN_VOLUME_PATH3}", p3_c5, f"{volume_ratio:.2f}x"),
        ("لا هبوط بعد قمة", p3_c6, str(not post_spike_pullback)),
    ]

    # ══════════════════════════════════════════════
    #   مسار 4 — اختراق مقاومة حقيقية مدعوم بالحجم (Volume Breakout)
    # ══════════════════════════════════════════════
    p4_c1 = price > ema9 > ema21 > ema50
    p4_c2 = price > swing_high
    p4_c3 = volume_ratio > 1.3
    p4_c4 = rsi_now < 85
    path4 = p4_c1 and p4_c2 and p4_c3 and p4_c4
    path4_conditions = [
        ("تراصف EMA صاعد", p4_c1, f"{price:.4f}>{ema9:.4f}>{ema21:.4f}>{ema50:.4f}"),
        ("اختراق swing_high", p4_c2, f"{price:.4f}>{swing_high:.4f}"),
        ("حجم>1.3", p4_c3, f"{volume_ratio:.2f}x"),
        ("RSI<85", p4_c4, f"{rsi_now:.2f}"),
    ]

    # ══════════════════════════════════════════════
    #   مسار 5 — ارتداد من دعم قوي + إشارة انعكاس
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

    p5_c1 = near_strong_support
    p5_c2 = reversal_signal
    p5_c3 = volume_ratio > MIN_VOLUME_PATH5
    path5 = p5_c1 and p5_c2 and p5_c3
    path5_conditions = [
        ("قرب دعم قوي", p5_c1, f"عدد المناطق={len(support_zones)}"),
        ("إشارة انعكاس", p5_c2, f"ابتلاعية={bullish_engulfing}/RSI متشبع={rsi_oversold}"),
        (f"حجم>{MIN_VOLUME_PATH5}", p5_c3, f"{volume_ratio:.2f}x"),
    ]

    # ══════════════════════════════════════════════
    #   مسار 6 — كسر هيكل مبكر (Early Break of Structure)
    # ══════════════════════════════════════════════
    higher_low_formed, minor_resistance = _detect_early_structure_break(Raw_Data)

    p6_c1 = higher_low_formed
    p6_c2 = minor_resistance is not None
    p6_c3 = (minor_resistance is not None) and (price > minor_resistance)
    p6_c4 = volume_ratio > MIN_VOLUME_PATH6
    path6 = p6_c1 and p6_c2 and p6_c3 and p6_c4
    path6_conditions = [
        ("تشكّل Higher Low", p6_c1, str(higher_low_formed)),
        ("وجود مقاومة صغيرة", p6_c2, str(minor_resistance)),
        ("اختراق المقاومة الصغيرة", p6_c3, f"{price:.4f}>{minor_resistance:.4f}" if minor_resistance is not None else "—"),
        (f"حجم>{MIN_VOLUME_PATH6}", p6_c4, f"{volume_ratio:.2f}x"),
    ]

    # ══════════════════════════════════════════════
    #   مسار 7 — انحراف صعودي بين السعر وRSI (Bullish Divergence)
    # ══════════════════════════════════════════════
    p7_c1 = low_now < swing_low
    p7_c2 = rsi_now > rsi_prev
    p7_c3 = rsi_now < DIVERGENCE_RSI_CEILING
    bullish_divergence = p7_c1 and p7_c2 and p7_c3
    p7_c4 = volume_ratio > MIN_VOLUME_PATH7
    path7 = bullish_divergence and p7_c4
    path7_conditions = [
        ("قاع أدنى من swing_low", p7_c1, f"{low_now:.4f}<{swing_low:.4f}"),
        ("RSI يصعد رغم القاع الأدنى", p7_c2, f"{rsi_now:.2f}>{rsi_prev:.2f}"),
        (f"RSI<{DIVERGENCE_RSI_CEILING}", p7_c3, f"{rsi_now:.2f}"),
        (f"حجم>{MIN_VOLUME_PATH7}", p7_c4, f"{volume_ratio:.2f}x"),
    ]

    triggered_paths = []
    if path1: triggered_paths.append("1-تقاطع الزخم")
    if path2: triggered_paths.append("2-استمرار الزخم")
    if path3: triggered_paths.append("3-ارتداد الدعم")
    if path4: triggered_paths.append("4-اختراق بالحجم")
    if path5: triggered_paths.append(f"5-ارتداد دعم قوي ({'ابتلاعية' if bullish_engulfing else 'RSI متشبع'})")
    if path6: triggered_paths.append("6-كسر هيكل مبكر")
    if path7: triggered_paths.append("7-انحراف صعودي RSI")

    any_path_triggered = len(triggered_paths) > 0

    rr = 0.0
    gate_passed = False
    sl_est = None
    tp1_est = None
    resistance_zones = []
    if any_path_triggered:
        resistance_source = Raw_Data_HTF if Raw_Data_HTF else Raw_Data
        resistance_zones = _find_strong_resistance_zones(resistance_source)
        trend_tp, gap_pct_tp = _detect_trend_and_gap_pct(resistance_source, use_highs=True) \
            if resistance_source else ("neutral", 0.0)
        trend_sl, gap_pct_sl = _detect_trend_and_gap_pct(resistance_source, use_highs=False) \
            if resistance_source else ("up", 0.0)
        gate_passed, rr, sl_est, tp1_est = _passes_edge_gate(
            price, atr, swing_low, resistance_zones, Raw_Data,
            trend_sl=trend_sl, gap_pct_sl=gap_pct_sl,
            trend_tp=trend_tp, gap_pct_tp=gap_pct_tp,
        )

    buy_triggered = any_path_triggered and gate_passed
    Decision = "BUY" if buy_triggered else "ANYTHING"

    _print_full_cycle_diagnostics(
        price=price, ema9=ema9, ema21=ema21, ema50=ema50,
        rsi_now=rsi_now, rsi_prev=rsi_prev, macd_line=macd_line, signal_line=signal_line,
        hist_now=hist_now, hist_prev=hist_prev, volume_ratio=volume_ratio, obv_now=obv_now, obv_prev=obv_prev,
        swing_low=swing_low, swing_high=swing_high, low_now=low_now, atr=atr,
        macd_strength_ok=macd_strength_ok, post_spike_pullback=post_spike_pullback,
        path_conditions=[
            ("مسار 1", path1_conditions, path1),
            ("مسار 2", path2_conditions, path2),
            ("مسار 3", path3_conditions, path3),
            ("مسار 4", path4_conditions, path4),
            ("مسار 5", path5_conditions, path5),
            ("مسار 6", path6_conditions, path6),
            ("مسار 7", path7_conditions, path7),
        ],
        support_zones=support_zones, near_strong_support=near_strong_support,
        bullish_engulfing=bullish_engulfing, rsi_oversold=rsi_oversold,
        resistance_zones=resistance_zones, any_path_triggered=any_path_triggered,
        gate_passed=gate_passed, rr=rr, sl_est=sl_est, tp1_est=tp1_est,
        triggered_paths=triggered_paths, Decision=Decision, Decision_prev=Decision_prev,
    )

    if Decision == Decision_prev and Decision == "BUY":
        return "ANYTHING"

    return Decision
