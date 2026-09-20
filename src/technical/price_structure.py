# Provider-neutral deterministic price-structure calculations.
import math

PRICE_STRUCTURE_SCHEMA_VERSION = 1

def clean_json_value(value):
    """Convert NaN/Inf values to None so MCP output is strict JSON-safe."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None

    if isinstance(value, dict):
        return {
            key: clean_json_value(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            clean_json_value(item)
            for item in value
        ]

    return value


def _dedupe_bars_by_time(rows, fields=("close",)):
    """Deterministic dedupe of bars by time_key (shared duplicate policy).

    Identical duplicates (same field values at the same time_key) collapse
    deterministically. Conflicting duplicates (different values at the same
    time_key) flag the series: the caller must not pick first/last, it must
    mark the timeframe INDETERMINATE. Invalid rows (missing time_key or
    non-finite field values) are skipped. Returns (mapping, conflicting).
    Single-field callers receive scalar values; multi-field callers receive
    tuples.
    """
    mapping = {}
    conflicting = False
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        time_key = row.get("time_key")
        if time_key is None:
            continue
        key = str(time_key)
        values = []
        valid = True
        for field in fields:
            try:
                value = float(row.get(field))
            except (TypeError, ValueError, OverflowError):
                valid = False
                break
            if not math.isfinite(value):
                valid = False
                break
            values.append(value)
        if not valid:
            continue
        stored = tuple(values) if len(fields) > 1 else values[0]
        if key in mapping and mapping[key] != stored:
            conflicting = True
        else:
            mapping[key] = stored
    return mapping, conflicting


def _structure_swings(bars, n=2):
    """Confirmed symmetric pivots with explicit lookahead protection.

    A pivot at index t is confirmed only when at least n completed bars exist
    on both sides (t-n ... t-1 and t+1 ... t+n), so a bar is never classified
    as a pivot before the right-side confirmation bars have arrived. Strict
    comparison avoids flat-top / flat-bottom ambiguity.
    """
    swings = []
    for i in range(n, len(bars) - n):
        high = bars[i]["high"]
        low = bars[i]["low"]
        if (high > max(bar["high"] for bar in bars[i - n:i])
                and high > max(bar["high"] for bar in bars[i + 1:i + n + 1])):
            swings.append({"index": i, "price": high, "type": "HIGH"})
        if (low < min(bar["low"] for bar in bars[i - n:i])
                and low < min(bar["low"] for bar in bars[i + 1:i + n + 1])):
            swings.append({"index": i, "price": low, "type": "LOW"})
    swings.sort(key=lambda swing: swing["index"])
    return swings


def _cluster_levels(prices, tolerance_pct=0.75):
    """Cluster sorted prices into deterministic zones.

    A price joins an existing zone when its distance from the zone midpoint
    is <= tolerance_pct; otherwise it starts a new zone. Returns a list of
    {"lower", "upper", "touch_count", "members", "latest_index"}.
    """
    if not prices:
        return []
    zones = []
    for price, index in sorted((value, idx) for value, idx in prices):
        merged = False
        for zone in zones:
            midpoint = (zone["lower"] + zone["upper"]) / 2.0
            if abs(price - midpoint) / midpoint * 100.0 <= tolerance_pct:
                zone["lower"] = min(zone["lower"], price)
                zone["upper"] = max(zone["upper"], price)
                zone["touch_count"] += 1
                zone["members"].append(price)
                zone["latest_index"] = max(zone["latest_index"], index)
                merged = True
                break
        if not merged:
            zones.append({
                "lower": price,
                "upper": price,
                "touch_count": 1,
                "members": [price],
                "latest_index": index,
            })
    return zones


def _zone_strength(zone, timeframe, bar_count, reaction_touches):
    """Transparent zone strength scoring.

    points = touch_count tier (+2 for >=3, +1 for ==2)
           + timeframe importance (+1 for daily)
           + recency (+1 when the latest member is within the last 30 bars)
    STRONG >= 3, MEDIUM == 2, WEAK otherwise. reaction_touches is reported as
    evidence but does not change the strength tier (kept transparent).
    """
    points = 0
    if zone["touch_count"] >= 3:
        points += 2
    elif zone["touch_count"] == 2:
        points += 1
    if timeframe == "daily":
        points += 1
    if bar_count - zone["latest_index"] <= 30:
        points += 1
    strength = "STRONG" if points >= 3 else "MEDIUM" if points == 2 else "WEAK"
    return strength, {
        "touch_count": zone["touch_count"],
        "reaction_touches": reaction_touches,
        "timeframe": timeframe,
        "recency_bars": bar_count - zone["latest_index"],
        "points": points,
    }


def _nearest_zone(zones, close, above):
    """Nearest zone above (above=True) or below (above=False) the close.

    Prefers zones on the requested side; when none exist on that side (for
    example the price has broken above every resistance), falls back to the
    nearest zone on the opposite side so breakout / breakdown states and
    location classification remain deterministic. A negative distance then
    expresses that the price is beyond the level.
    """
    if not zones:
        return None
    best_zone = None
    best_distance = None
    for zone in zones:
        midpoint = (zone["lower"] + zone["upper"]) / 2.0
        if above and midpoint >= close:
            distance = midpoint - close
        elif not above and midpoint <= close:
            distance = close - midpoint
        else:
            distance = abs(midpoint - close) + 1000000.0
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_zone = zone
    return best_zone


def _structure_timeframe(bars, health, timeframe_name, n=2, window=120,
                         minimum_bars=30, cluster_tolerance=0.75,
                         penetration_pct=0.5, retest_window=10):
    """One timeframe of deterministic price structure.

    Pipeline (every rule transparent, no lookahead):
      1. Unified Data Health gate -> INDETERMINATE on abnormal.
      2. Duplicate timestamp policy -> INDETERMINATE on conflicting dupes.
      3. Minimum bars -> INDETERMINATE with INSUFFICIENT_SWINGS.
      4. Confirmed pivots (right-side n bars completed) -> swings.
      5. Trend: latest two confirmed highs / lows -> HH+HL / LH+LL / RANGE.
      6. STRUCTURE_DAMAGED: the most recent confirmed uptrend anchor's
         higher low is effectively broken by a later close, without a full
         LH+LL downtrend (mirror rule for downtrend anchors).
      7. Breakout / Breakdown: close penetrates a clustered zone bound by
         more than penetration_pct (wick-only never counts).
      8. Retest: after a prior penetration in the last retest_window bars,
         price returns into the zone without closing back through it.
      9. Pullback: within an intact trend, price pulls back from the latest
         swing extreme but the latest swing low/high still holds.
    """
    empty = {
        "state": "INDETERMINATE",
        "swing_count": 0,
        "bar_count": len(bars) if isinstance(bars, list) else 0,
        "support": [],
        "resistance": [],
        "reason_codes": [],
    }
    if not isinstance(bars, list):
        return empty

    result = dict(empty)

    if health != "OK":
        result["reason_codes"].append("DATA_HEALTH_LIMITED")
        return result

    mapping, conflict = _dedupe_bars_by_time(
        bars, fields=("open", "high", "low", "close"))
    if conflict:
        result["reason_codes"].append("CONFLICTING_DUPLICATE_TIMESTAMP")
        return result

    ordered = sorted(mapping)
    if not ordered:
        result["reason_codes"].append("INSUFFICIENT_SWINGS")
        return result

    rows = []
    for key in ordered:
        open_p, high_p, low_p, close_p = mapping[key]
        rows.append({"time_key": key, "open": open_p, "high": high_p,
                     "low": low_p, "close": close_p})
    result["bar_count"] = len(rows)
    if len(rows) < minimum_bars:
        result["reason_codes"].append("INSUFFICIENT_SWINGS")
        return result

    swings = _structure_swings(rows, n=n)
    recent_swings = [swing for swing in swings
                     if swing["index"] >= len(rows) - window]
    result["swing_count"] = len(recent_swings)

    if len(recent_swings) < 4:
        result["bar_count"] = len(rows)
        result["reason_codes"].append("INSUFFICIENT_SWINGS")
        return result

    highs = [swing for swing in recent_swings if swing["type"] == "HIGH"]
    lows = [swing for swing in recent_swings if swing["type"] == "LOW"]
    if len(highs) < 2 or len(lows) < 2:
        result["bar_count"] = len(rows)
        result["reason_codes"].append("INSUFFICIENT_SWINGS")
        return result

    # ---- clustering into support / resistance zones ----
    support_zones = _cluster_levels(
        [(swing["price"], swing["index"]) for swing in lows],
        tolerance_pct=cluster_tolerance)
    resistance_zones = _cluster_levels(
        [(swing["price"], swing["index"]) for swing in highs],
        tolerance_pct=cluster_tolerance)

    def reaction_touches(lower, upper):
        count = 0
        for row in rows:
            if lower <= row["close"] <= upper:
                count += 1
        return count

    def finalize_zone(zone, kind):
        touches = reaction_touches(zone["lower"], zone["upper"])
        strength, strength_evidence = _zone_strength(
            zone, timeframe_name, len(rows), touches)
        return {
            "type": kind,
            "lower": round(zone["lower"], 2),
            "upper": round(zone["upper"], 2),
            "source": ("SWING_LOW_CLUSTER" if kind == "SUPPORT"
                       else "SWING_HIGH_CLUSTER"),
            "strength": strength,
            "touch_count": zone["touch_count"],
            "timeframe": timeframe_name,
            "strength_evidence": strength_evidence,
        }

    support = [finalize_zone(zone, "SUPPORT") for zone in support_zones]
    resistance = [finalize_zone(zone, "RESISTANCE") for zone in resistance_zones]
    result["support"] = support
    result["resistance"] = resistance

    closes = [row["close"] for row in rows]
    close = closes[-1]

    # ---- trend structure ----
    h1, h2 = highs[-2]["price"], highs[-1]["price"]
    l1, l2 = lows[-2]["price"], lows[-1]["price"]
    hh = h2 > h1
    lh = h2 < h1
    hl = l2 > l1
    ll = l2 < l1

    if hh and hl:
        trend = "UPTREND"
        result["reason_codes"].extend(
            ["HIGHER_HIGH_CONFIRMED", "HIGHER_LOW_CONFIRMED"])
    elif lh and ll:
        trend = "DOWNTREND"
        result["reason_codes"].extend(
            ["LOWER_HIGH_CONFIRMED", "LOWER_LOW_CONFIRMED"])
    else:
        trend = "RANGE"
        result["reason_codes"].append("RANGE_BOUNDARIES_CONFIRMED")

    # ---- structure damage (anchor broken, not yet full reversal) ----
    def damage_check():
        # scan alternating quads newest-first for a confirmed trend anchor
        # whose protective level is then broken by a later close
        for start in range(len(recent_swings) - 3, -1, -1):
            quad = recent_swings[start:start + 4]
            types = [swing["type"] for swing in quad]
            if types not in (["HIGH", "LOW", "HIGH", "LOW"],
                             ["LOW", "HIGH", "LOW", "HIGH"]):
                continue
            q_highs = [quad[0], quad[2]] if types[0] == "HIGH" else [quad[1], quad[3]]
            q_lows = [quad[1], quad[3]] if types[0] == "HIGH" else [quad[0], quad[2]]
            anchor_hh = q_highs[1]["price"] > q_highs[0]["price"]
            anchor_hl = q_lows[1]["price"] > q_lows[0]["price"]
            anchor_lh = q_highs[1]["price"] < q_highs[0]["price"]
            anchor_ll = q_lows[1]["price"] < q_lows[0]["price"]
            if anchor_hh and anchor_hl:
                level = q_lows[1]["price"]
                broken = any(
                    row["close"] < level * (1.0 - penetration_pct / 100.0)
                    for row in rows[q_lows[1]["index"] + 1:])
                if broken:
                    return "HIGHER_LOW_BROKEN"
                # anchor intact here: keep scanning older quads
                continue
            if anchor_lh and anchor_ll:
                level = q_highs[1]["price"]
                broken = any(
                    row["close"] > level * (1.0 + penetration_pct / 100.0)
                    for row in rows[q_highs[1]["index"] + 1:])
                if broken:
                    return "LOWER_HIGH_BROKEN"
                # anchor intact here: keep scanning older quads
                continue
        return None

    damaged_code = damage_check()
    if damaged_code is not None and trend not in ("DOWNTREND" if damaged_code
                                                  == "HIGHER_LOW_BROKEN" else "UPTREND"):
        # The anchor break is meaningful when the full opposite trend is not
        # yet confirmed (otherwise the trend state itself takes precedence).
        opposite_confirmed = (
            (damaged_code == "HIGHER_LOW_BROKEN" and lh and ll)
            or (damaged_code == "LOWER_HIGH_BROKEN" and hh and hl))
        if not opposite_confirmed:
            trend = "STRUCTURE_DAMAGED"
            result["reason_codes"].append(damaged_code)

    # ---- breakout / breakdown (close-based, no wick-only) ----
    # The reference is the last CONFIRMED swing extreme (spec: confirmed
    # prior resistance / support). A close beyond that level by more than
    # penetration_pct is a break; wick-only never counts. Location keeps
    # its own nearest-zone classification below.
    nearest_res = _nearest_zone(resistance, close, above=True)
    nearest_sup = _nearest_zone(support, close, above=False)
    prior_high = highs[-1]["price"]
    prior_low = lows[-1]["price"]
    # Retest references the PREVIOUS confirmed swing extreme (the level that
    # was actually crossed); the latest pivot cannot self-reference its own
    # breakout close.
    prev_high = highs[-2]["price"]
    prev_low = lows[-2]["price"]
    pen = penetration_pct / 100.0

    # ---- fresh crossing rule (Blocker B) ----
    # BREAKOUT/BREAKDOWN only fire on the FIRST bar that crosses the
    # confirmed prior level (previous close still at/inside the level,
    # current close beyond it). Bars that merely stay on the same side do
    # NOT repeat the event state; they fall through to retest / pullback /
    # the base trend. No event memory, no runtime state: recomputable from
    # bars history alone.
    breakout_threshold = prior_high * (1.0 + pen)
    breakdown_threshold = prior_low * (1.0 - pen)
    prev_close = closes[-2] if len(closes) >= 2 else None
    fresh_breakout = (prev_close is not None
                      and prev_close <= breakout_threshold
                      and close > breakout_threshold)
    fresh_breakdown = (prev_close is not None
                       and prev_close >= breakdown_threshold
                       and close < breakdown_threshold)

    # ---- priority: STRUCTURE_DAMAGED > same-bar breakout/breakdown ----
    # (Blocker A) A confirmed anchor break keeps the damaged state; a
    # same-bar crossing is recorded as evidence only and never overrides.
    state = trend
    if fresh_breakout:
        result["reason_codes"].append("BREAKOUT_ABOVE_RESISTANCE")
        if state != "STRUCTURE_DAMAGED":
            state = "BREAKOUT"
    elif fresh_breakdown:
        result["reason_codes"].append("BREAKDOWN_BELOW_SUPPORT")
        if state != "STRUCTURE_DAMAGED":
            state = "BREAKDOWN"
    elif (any(row["close"] > prev_high * (1.0 + pen)
              for row in rows[-retest_window:])
          and prev_high * (1.0 - pen) <= close <= prev_high * (1.0 + pen)):
        # price came back to the broken level without closing back through it
        state = "RETEST"
        result["reason_codes"].append("RETESTING_BREAKOUT_LEVEL")
    elif (any(row["close"] < prev_low * (1.0 - pen)
              for row in rows[-retest_window:])
          and prev_low * (1.0 - pen) <= close <= prev_low * (1.0 + pen)):
        state = "RETEST"
        result["reason_codes"].append("RETESTING_BREAKDOWN_LEVEL")
    elif (trend == "UPTREND"
          and close < prior_high * (1.0 - pen)
          and close > lows[-1]["price"]):
        state = "PULLBACK"
        result["reason_codes"].append("PULLBACK_WITHIN_UPTREND")
    elif (trend == "DOWNTREND"
          and close > prior_low * (1.0 + pen)
          and close < highs[-1]["price"]):
        # mirror pullback inside a downtrend (against-trend rally)
        state = "PULLBACK"
        result["reason_codes"].append("PULLBACK_WITHIN_DOWNTREND")

    result["state"] = state
    result["latest_close"] = close
    result["swing_highs"] = [round(swing["price"], 2) for swing in highs]
    result["swing_lows"] = [round(swing["price"], 2) for swing in lows]
    return result


def build_price_structure_state(structure_input):
    """Deterministic Price Structure + Support/Resistance state.

    Pure function. Daily is the primary anchor; 1H confirms and 15m describes
    short-term execution structure. Short timeframes may express pullback,
    retest, deterioration or short-term breaks but never silently override
    the daily anchor into the opposite primary structure. Market Regime and
    Relative Strength are deliberately not inputs (orthogonal modules).
    No positions, no AI, no runtime state, no trading semantics.
    """
    def result(primary_structure="INDETERMINATE", current_phase="INDETERMINATE",
               structure_integrity="UNKNOWN", location_state="NO_CLEAR_LEVEL",
               nearest_support=None, nearest_resistance=None,
               distance_to_support_pct=None, distance_to_resistance_pct=None,
               timeframes=None, levels=None, data_health=None,
               confidence="LOW", reason_codes=None):
        return clean_json_value({
            "schema_version": PRICE_STRUCTURE_SCHEMA_VERSION,
            "generated_at": generated_at,
            "symbol": symbol,
            "primary_structure": primary_structure,
            "current_phase": current_phase,
            "structure_integrity": structure_integrity,
            "location_state": location_state,
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
            "distance_to_support_pct": distance_to_support_pct,
            "distance_to_resistance_pct": distance_to_resistance_pct,
            "timeframes": timeframes if timeframes is not None else {},
            "levels": levels if levels is not None else {
                "support": [], "resistance": []},
            "data_health": data_health if data_health is not None else {},
            "confidence": confidence,
            "reason_codes": sorted(set(reason_codes or [])),
        })

    if not isinstance(structure_input, dict):
        symbol = None
        generated_at = None
        return result(reason_codes=["INVALID_STRUCTURE_INPUT"])
    symbol = structure_input.get("symbol")
    generated_at = structure_input.get("generated_at")
    if (not isinstance(symbol, str) or not symbol
            or not isinstance(generated_at, str) or not generated_at):
        return result(reason_codes=["INVALID_STRUCTURE_INPUT"])
    bars = structure_input.get("bars")
    data_health = structure_input.get("data_health")
    if not isinstance(bars, dict) or not isinstance(data_health, dict):
        return result(reason_codes=["INVALID_STRUCTURE_INPUT"])

    timeframes = {}
    reasons = []
    for name in ("daily", "hourly", "15m"):
        timeframes[name] = _structure_timeframe(
            bars.get(name) if isinstance(bars.get(name), list) else [],
            data_health.get(name),
            timeframe_name=name,
        )
        reasons.extend(timeframes[name]["reason_codes"])

    daily = timeframes["daily"]
    hourly = timeframes["hourly"]
    short_term = timeframes["15m"]

    if daily["state"] == "INDETERMINATE":
        if "DATA_HEALTH_LIMITED" in daily["reason_codes"]:
            reasons.append("DATA_HEALTH_LIMITED")
        elif "CONFLICTING_DUPLICATE_TIMESTAMP" in daily["reason_codes"]:
            reasons.append("CONFLICTING_DUPLICATE_TIMESTAMP")
        else:
            reasons.append("INSUFFICIENT_SWINGS")
        return result(
            timeframes=timeframes,
            data_health=data_health,
            confidence="LOW",
            reason_codes=reasons,
        )

    primary_structure = daily["state"]
    primary_is_directional = primary_structure in ("UPTREND", "DOWNTREND")

    # ---- current phase from short timeframes (daily anchor untouched) ----
    phase_candidates = []
    if daily["state"] in ("PULLBACK", "RETEST", "BREAKOUT", "BREAKDOWN",
                          "STRUCTURE_DAMAGED"):
        phase_candidates.append(daily["state"])
    for frame in (hourly, short_term):
        if frame["state"] in ("PULLBACK", "RETEST", "BREAKOUT", "BREAKDOWN",
                              "STRUCTURE_DAMAGED"):
            phase_candidates.append(frame["state"])
    current_phase = phase_candidates[0] if phase_candidates else primary_structure

    # ---- structure integrity ----
    opposing = {
        "UPTREND": "DOWNTREND",
        "DOWNTREND": "UPTREND",
    }
    short_term_states = [hourly["state"], short_term["state"]]
    if daily["state"] == "STRUCTURE_DAMAGED":
        integrity = "BROKEN"
    elif primary_is_directional and any(
            frame_state == opposing[primary_structure]
            for frame_state in short_term_states):
        integrity = "WEAKENING"
    elif "STRUCTURE_DAMAGED" in short_term_states:
        integrity = "WEAKENING"
    else:
        integrity = "INTACT"
    # defensive integrity (Blocker A): broken-anchor evidence can never read
    # INTACT. Daily broken anchor -> at least BROKEN; intraday-only broken
    # anchor -> at least WEAKENING.
    if ("HIGHER_LOW_BROKEN" in daily["reason_codes"]
            or "LOWER_HIGH_BROKEN" in daily["reason_codes"]):
        integrity = "BROKEN"
    elif ("HIGHER_LOW_BROKEN" in hourly["reason_codes"]
          or "LOWER_HIGH_BROKEN" in hourly["reason_codes"]
          or "HIGHER_LOW_BROKEN" in short_term["reason_codes"]
          or "LOWER_HIGH_BROKEN" in short_term["reason_codes"]):
        if integrity == "INTACT":
            integrity = "WEAKENING"
    reasons.append(f"PRIMARY_STRUCTURE_{integrity}")

    # ---- nearest zones from daily + location state ----
    daily_close = daily.get("latest_close")
    all_support = [zone for frame in timeframes.values()
                   for zone in frame["support"]]
    all_resistance = [zone for frame in timeframes.values()
                      for zone in frame["resistance"]]
    nearest_support = None
    nearest_resistance = None
    if daily_close is not None:
        nearest_support = _nearest_zone(daily["support"], daily_close,
                                        above=False)
        nearest_resistance = _nearest_zone(daily["resistance"], daily_close,
                                           above=True)
        support_mid = ((nearest_support["lower"] + nearest_support["upper"]) / 2.0
                       if nearest_support else None)
        resistance_mid = ((nearest_resistance["lower"] + nearest_resistance["upper"]) / 2.0
                          if nearest_resistance else None)
        distance_to_support_pct = (
            round((daily_close - support_mid) / daily_close * 100.0, 4)
            if support_mid else None)
        distance_to_resistance_pct = (
            round((resistance_mid - daily_close) / daily_close * 100.0, 4)
            if resistance_mid else None)

        at_pct, near_pct = 0.5, 1.5
        location_state = "MID_RANGE"
        if nearest_resistance and daily_close > nearest_resistance["upper"] * 1.005:
            location_state = "ABOVE_RESISTANCE"
        elif nearest_support and daily_close < nearest_support["lower"] * 0.995:
            location_state = "BELOW_SUPPORT"
        elif nearest_resistance and abs(distance_to_resistance_pct) <= at_pct:
            location_state = "AT_RESISTANCE"
        elif nearest_resistance and abs(distance_to_resistance_pct) <= near_pct:
            location_state = "NEAR_RESISTANCE"
        elif nearest_support and abs(distance_to_support_pct) <= at_pct:
            location_state = "AT_SUPPORT"
        elif nearest_support and abs(distance_to_support_pct) <= near_pct:
            location_state = "NEAR_SUPPORT"
        if location_state in ("NEAR_SUPPORT", "AT_SUPPORT", "BELOW_SUPPORT"):
            reasons.append("NEAR_MAJOR_SUPPORT")
        if location_state in ("NEAR_RESISTANCE", "AT_RESISTANCE",
                              "ABOVE_RESISTANCE"):
            reasons.append("NEAR_MAJOR_RESISTANCE")
    else:
        distance_to_support_pct = None
        distance_to_resistance_pct = None
        location_state = "NO_CLEAR_LEVEL"

    # ---- coverage-aware confidence ----
    daily_swings = daily["swing_count"]
    available_timeframes = sum(
        1 for frame in timeframes.values()
        if frame["state"] != "INDETERMINATE")
    if daily_swings >= 4 and daily["bar_count"] >= 60 and available_timeframes == 3:
        confidence = "HIGH"
    elif daily_swings >= 3 and daily["bar_count"] >= 30 and available_timeframes >= 2:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    if integrity == "WEAKENING" and confidence == "HIGH":
        confidence = "MEDIUM"
    elif integrity == "WEAKENING" and confidence == "MEDIUM":
        confidence = "LOW"

    return result(
        primary_structure=primary_structure,
        current_phase=current_phase,
        structure_integrity=integrity,
        location_state=location_state,
        nearest_support=nearest_support,
        nearest_resistance=nearest_resistance,
        distance_to_support_pct=distance_to_support_pct,
        distance_to_resistance_pct=distance_to_resistance_pct,
        timeframes=timeframes,
        levels={
            "support": sorted(
                all_support,
                key=lambda zone: (zone["lower"] + zone["upper"]) / 2.0),
            "resistance": sorted(
                all_resistance,
                key=lambda zone: (zone["lower"] + zone["upper"]) / 2.0),
        },
        data_health=data_health,
        confidence=confidence,
        reason_codes=reasons,
    )

