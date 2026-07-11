"""
ملف: Exit_Decision_File.py
الوظيفة: إدارة كاملة لخروج الصفقة بعد فتحها — متوافق مع نظام الأوامر الحدّية المسبقة
         (60% عند TP1 و 40% عند TP2) على المنصة، مع مراقبة السعر وحالة الأوامر
         كل دورة لتنفيذ الخروج الطارئ (SL، وقف زمني، خروج طارئ رابح).
المسار: Super_Trader/Exit_Decision_File.py
"""

# ══════════════════════════════════════════════
#   إعدادات إدارة المخاطر والأهداف
# ══════════════════════════════════════════════
SL_STRUCTURE_ATR_BUFFER = 0.3
SL_ATR_MULTIPLIER = 1.5
SL_MIN_RISK_ATR_MULTIPLIER = 0.8
SL_MAX_RISK_PCT = 0.08 

TP_RESISTANCE_BUFFER_PCT = 0.0015 
MIN_TP1_RR = 1.1

# النسب الجديدة المعتمدة من المستخدم للـ Limit Orders
TP1_SELL_FRACTION = 0.60
TP2_SELL_FRACTION = 0.40

RR_STRONG_MARKET = 3.0
RR_MEDIUM_MARKET = 2.0
RR_WEAK_MARKET   = 1.3

TIME_STOP_CYCLES = 25
TIME_STOP_MIN_PROGRESS_ATR = 0.4

RESISTANCE_LOOKBACK_CANDLES        = 100
RESISTANCE_CLUSTER_TOLERANCE_PCT   = 0.3
RESISTANCE_MIN_TOUCHES             = 2

MIN_PROFIT_ATR_MULTIPLIER = 0.5


def _find_strong_resistance_zones(candles):
    if not candles or len(candles) < 5:
        return []
    recent = candles[-RESISTANCE_LOOKBACK_CANDLES:] if len(candles) > RESISTANCE_LOOKBACK_CANDLES else candles
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
    return [sum(zone) / len(zone) for zone in zones if len(zone) >= RESISTANCE_MIN_TOUCHES]


def _assess_market_strength(Final_Data):
    price = Final_Data["price"]
    ema9  = Final_Data["ema9"]
    ema21 = Final_Data["ema21"]
    ema50 = Final_Data["ema50"]
    volume_ratio = Final_Data["volume_ratio"]
    hist_now  = Final_Data["hist_now"]
    hist_prev = Final_Data["hist_prev"]

    score = 0
    if price > ema9 > ema21 > ema50: score += 2
    elif price > ema21: score += 1
    if volume_ratio > 1.5: score += 1
    if hist_now > hist_prev > 0: score += 1

    if score >= 3: return "strong", RR_STRONG_MARKET
    elif score >= 1: return "medium", RR_MEDIUM_MARKET
    else: return "weak", RR_WEAK_MARKET


def Calc_SL_Price(entry_price: float, entry_atr: float, swing_low: float) -> float:
    structural_sl = swing_low - (entry_atr * SL_STRUCTURE_ATR_BUFFER)
    atr_sl        = entry_price - (entry_atr * SL_ATR_MULTIPLIER)

    if swing_low <= 0 or structural_sl >= entry_price:
        return atr_sl

    structural_risk = entry_price - structural_sl
    min_risk = entry_atr * SL_MIN_RISK_ATR_MULTIPLIER
    max_risk = entry_price * SL_MAX_RISK_PCT

    if structural_risk < min_risk: return entry_price - min_risk
    if structural_risk > max_risk: return atr_sl
    return structural_sl


def Calc_TP_Targets(entry_price: float, sl_price: float, resistance_zones: list, rr_target: float):
    risk = entry_price - sl_price
    if risk <= 0: risk = entry_price * 0.02

    resistances_above = sorted(r for r in resistance_zones if r > entry_price)

    if resistances_above:
        tp1 = resistances_above[0] * (1 - TP_RESISTANCE_BUFFER_PCT)
        if (tp1 - entry_price) < (risk * MIN_TP1_RR):
            tp1 = entry_price + (risk * MIN_TP1_RR)
    else:
        tp1 = entry_price + (risk * MIN_TP1_RR)

    further_resistances = [r for r in resistances_above if r > tp1]
    if further_resistances:
        tp2 = further_resistances[0] * (1 - TP_RESISTANCE_BUFFER_PCT)
        if (tp2 - entry_price) < (risk * rr_target):
            tp2 = entry_price + (risk * rr_target)
    else:
        tp2 = entry_price + (risk * rr_target)

    if tp2 <= tp1:
        tp2 = tp1 + (risk * 0.5)

    return tp1, tp2


def Init_Position_Risk_Management(entry_price: float, entry_atr: float,
                                   Final_Data: dict, Raw_Data: list = None,
                                   Raw_Data_HTF: list = None) -> dict:
    swing_low = Final_Data["swing_low"]
    resistance_source = Raw_Data_HTF if Raw_Data_HTF else Raw_Data
    resistance_zones = _find_strong_resistance_zones(resistance_source) if resistance_source else []

    market_strength, rr_target = _assess_market_strength(Final_Data)
    sl_price = Calc_SL_Price(entry_price, entry_atr, swing_low)
    tp1_price, tp2_price = Calc_TP_Targets(entry_price, sl_price, resistance_zones, rr_target)

    return {
        "entry_price"     : entry_price,
        "entry_atr"       : entry_atr,
        "sl_price"        : sl_price,
        "tp1_price"       : tp1_price,
        "tp2_price"       : tp2_price,
        "tp1_order_id"    : None,   # سيتم تخزينه بواسطة Manager بعد وضع الأمر الحدّي
        "tp2_order_id"    : None,   # سيتم تخزينه بواسطة Manager بعد وضع الأمر الحدّي
        "tp1_done"        : False,
        "tp2_done"        : False,
        "cycles_held"     : 0,
        "market_strength" : market_strength,
        "rr_target"       : rr_target,
    }


def Exit_Decision(Final_Data: dict, Position: dict) -> dict:
    """
    تتخذ القرار بناءً على حركة السعر وحالة أوامر المنصة الممررة في كائن Position.
    """
    price        = Final_Data["price"]
    volume_ratio = Final_Data["volume_ratio"]
    rsi_now      = Final_Data["rsi_now"]
    rsi_prev     = Final_Data["rsi_prev"]
    hist_now     = Final_Data["hist_now"]
    hist_prev    = Final_Data["hist_prev"]

    entry_price = Position["entry_price"]
    entry_atr   = Position["entry_atr"]
    sl_price    = Position["sl_price"]
    tp1_done    = Position.get("tp1_done", False)
    tp2_done    = Position.get("tp2_done", False)
    cycles_held = Position.get("cycles_held", 0) + 1

    profit = price - entry_price

    updated_position = dict(Position)
    updated_position["cycles_held"] = cycles_held

    # 1. تحقق الـ SL الهيكلي (أولوية قصوى) -> إلغاء الأوامر والبيع فوراً بالسوق
    if price <= sl_price:
        log = f"[Exit_Decision] 🚨 كسر وقف الخسارة الهيكلي! السعر={price:.5f} | SL={sl_price:.5f}"
        return {
            "action": "EMERGENCY_MARKET_SELL",
            "reason": "SL_BREACH",
            "updated_position": updated_position,
            "log": log
        }

    # 2. تحقق الـ الوقف الزمني (Time Stop) إذا لم يتحقق TP1 بعد -> إلغاء والبيع بالسوق
    if cycles_held >= TIME_STOP_CYCLES and not tp1_done:
        min_progress = entry_atr * TIME_STOP_MIN_PROGRESS_ATR
        momentum_dead = hist_now <= hist_prev and volume_ratio < 1.0
        if profit < min_progress and momentum_dead:
            log = f"[Exit_Decision] ⏳ تحقق الوقف الزمني (الصفقة راكدة) دورة={cycles_held}"
            return {
                "action": "EMERGENCY_MARKET_SELL",
                "reason": "TIME_STOP",
                "updated_position": updated_position,
                "log": log
            }

    # 3. تحقق الخروج الطارئ الرابح المبكر (قبل تحقق TP1) -> إلغاء والبيع بالسوق
    if not tp1_done:
        min_profit_required = entry_atr * MIN_PROFIT_ATR_MULTIPLIER
        has_enough_profit = profit >= min_profit_required
        momentum_weakening = (hist_prev >= 0 > hist_now) or (rsi_prev >= 50 > rsi_now)

        if has_enough_profit and momentum_weakening:
            log = f"[Exit_Decision] ⚠️ خروج طارئ رابح مبكر لضعف الزخم المفاجئ | السعر={price:.5f}"
            return {
                "action": "EMERGENCY_MARKET_SELL",
                "reason": "EARLY_PROFIT_EXIT",
                "updated_position": updated_position,
                "log": log
            }

    # 4. إذا لم تتحقق أي حالة خروج طارئة، يستمر الوضع الحالي (HOLD) في انتظار تنفيذ أوامر المنصة الحدية
    log = f"[Exit_Decision] 🟢 HOLD | السعر الحالي={price:.5f} | SL={sl_price:.5f} | دورة={cycles_held}"
    return {
        "action": "HOLD",
        "reason": "WAITING_FOR_LIMIT_ORDERS",
        "updated_position": updated_position,
        "log": log
    }
