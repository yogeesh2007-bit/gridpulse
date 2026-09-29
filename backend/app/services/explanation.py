"""Human-readable explanations of a recommendation.

The deterministic rule-based text is always produced first and is the source of truth. OpenRouter is an
optional layer that only *rephrases* those facts; its output is discarded (and the rule-based text kept)
if the key is missing, the call fails, or the text contains numbers that are not in the facts.
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

import httpx

from ..config import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _m(minutes: float) -> str:
    minutes = round(minutes)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def rule_based_explanation(rec: dict) -> str:
    chosen = rec.get("chosen")
    drv = rec["driver"]
    if not chosen:
        reasons = "; ".join(f"{c['name']}: {c['rejection_reason']}" for c in rec["candidates"]
                            if c.get("rejection_reason"))
        return f"No station is safely usable right now. {reasons}".strip()

    parts = [
        f"Go to {chosen['name']} ({chosen['distance_km']:.1f} km, {_m(chosen['travel_min'])} drive). "
        f"You would arrive at about {chosen['soc_arrival']:.0f}% and charge to {drv['soc_target']:.0f}% "
        f"at {chosen['charge_kw']:.0f} kW in {_m(chosen['charge_min'])}"
    ]
    if chosen["wait_min"] >= 1:
        ahead = chosen["queue_ahead"]
        why = f" ({ahead} in the queue ahead of you)" if ahead else " (all ports busy)"
        parts[0] += f", after a {_m(chosen['wait_min'])} wait{why}."
    else:
        parts[0] += ", with no wait."
    parts.append(f"Total time to a finished charge is about {_m(chosen['total_min'])}.")

    if chosen["deadline_ok"]:
        margin = drv["deadline_minutes"] - (chosen["start_min"] + chosen["charge_min"])
        parts.append(f"That is {_m(margin)} before your deadline.")
    else:
        parts.append(f"That misses your deadline by {_m(chosen['deadline_miss_min'])}.")

    if chosen["power_limited"]:
        parts.append(
            f"Site power is limited right now, so charging is capped at {chosen['charge_kw']:.0f} kW."
        )
    if chosen["displaces"]:
        parts.append(
            f"Because your battery need is {drv['priority_class']}, you are placed ahead of "
            f"{chosen['displaces']} lower-priority queued driver(s)."
        )

    cmp_ = rec.get("comparison_with_nearest")
    if cmp_:
        if cmp_["nearest_feasible"]:
            parts.append(
                f"{cmp_['nearest_station_name']} is closer ({_m(cmp_['nearest_travel_min'])} away) but would "
                f"finish {_m(abs(cmp_['minutes_saved']))} "
                f"{'later' if cmp_['minutes_saved'] >= 0 else 'earlier'}"
                + (f" because of a {_m(cmp_['nearest_wait_min'])} wait." if cmp_["nearest_wait_min"] >= 1 else ".")
            )
        else:
            parts.append(
                f"{cmp_['nearest_station_name']} is closer but unusable: {cmp_['nearest_rejection_reason']}."
            )
    else:
        others = [c for c in rec["candidates"] if c["station_id"] != chosen["station_id"] and c["feasible"]]
        if others:
            o = others[0]
            parts.append(f"{o['name']} would take about {_m(o['total_min'])} in total.")

    routing = rec.get("routing") or {}
    if routing.get("estimated"):
        parts.append("Note: travel times are straight-line estimates, so treat them as approximate.")

    b = chosen["score_breakdown"]
    if b["urgency_bonus"] > 0:
        parts.append(
            f"Your request is {drv['priority_class']} (urgency {drv['urgency']:.2f}), so this station earned a "
            f"{b['urgency_bonus']:.0f}-minute urgency bonus for being able to start you soon."
        )
    if b["load_penalty"] > 0:
        parts.append(f"Once you are charging it would be at {b['projected_load_pct']:.0f}% of its site power limit, "
                     f"which adds a {b['load_penalty']:.0f}-minute load penalty.")
    parts.append(
        f"Score: {b['travel_time']:.0f} travel + {b['predicted_wait']:.0f} wait + {b['charging_time']:.0f} charge"
        f" + {b['load_penalty']:.0f} load penalty - {b['urgency_bonus']:.0f} urgency bonus"
        f" = {b['final_score']:.0f} (lower is better)."
    )
    return " ".join(parts)


# ---- optional LLM phrasing -------------------------------------------------------------------------
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    return [float(x) for x in _NUM.findall(text)]


def numbers_grounded(llm_text: str, facts_text: str) -> bool:
    """True if every number the LLM wrote (within rounding) also appears in the facts."""
    facts = _numbers(facts_text)
    return all(any(abs(n - f) <= 0.51 for f in facts) for n in _numbers(llm_text))


def _facts(rec: dict) -> dict:
    def slim(c: dict) -> dict:
        keys = ("name", "distance_km", "travel_min", "wait_min", "charge_min", "total_min", "charge_kw",
                "queue_ahead", "soc_arrival", "deadline_ok", "deadline_miss_min", "feasible",
                "rejection_reason", "final_score", "score_breakdown")
        return {k: c[k] for k in keys}

    return {
        "driver": rec["driver"],
        "chosen": slim(rec["chosen"]) if rec["chosen"] else None,
        "alternatives": [slim(c) for c in rec["candidates"] if not rec["chosen"]
                         or c["station_id"] != rec["chosen"]["station_id"]],
        "comparison_with_nearest": rec.get("comparison_with_nearest"),
        "warnings": rec.get("warnings", []),
        "routing_confidence": (rec.get("routing") or {}).get("confidence"),
    }


MAX_ATTEMPTS = 3
_SPACES = {0x202F: " ", 0x00A0: " "}  # narrow / non-breaking spaces some models emit


def _station_key(rec: dict) -> Optional[str]:
    """Short identifier of the chosen station that a valid explanation must mention, e.g. 'Station B'."""
    if not rec.get("chosen"):
        return None
    return rec["chosen"]["name"].split(" (")[0]


def _text_problem(text: str, station_key: Optional[str], facts_text: str) -> Optional[str]:
    """Why LLM text is unusable, or None if it passes. Guards against empty/junk/ungrounded output."""
    if not text:
        return "OpenRouter returned empty text"
    if len(text) < 60:
        return "LLM text too short to be an explanation"
    if station_key and station_key.lower() not in text.lower():
        return "LLM text does not mention the chosen station"
    if not numbers_grounded(text, facts_text):
        return "LLM text contained numbers not present in the facts"
    return None


def llm_explanation(rec: dict) -> tuple[Optional[str], Optional[str], int]:
    """Returns (text, fallback_reason, latency_ms). text is None when the caller should use rules."""
    if not settings.openrouter_api_key:
        return None, "OPENROUTER_API_KEY not set", 0
    facts = json.dumps(_facts(rec), ensure_ascii=False)
    baseline = rule_based_explanation(rec)
    payload = {
        "model": settings.openrouter_model,
        "temperature": 0.2,
        # Free routed models are often "reasoning" models that burn the whole budget thinking and return
        # empty content. Disable reasoning (ignored by models that do not support the flag).
        "max_tokens": 800,
        "reasoning": {"enabled": False},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You explain EV charging station recommendations to a driver in 2-4 short, friendly "
                    "sentences. Use ONLY the facts provided. Never invent or change numbers, never "
                    "recommend a different station than the chosen one, and do not mention JSON or scores."
                ),
            },
            {"role": "user", "content": f"Facts:\n{facts}\n\nDraft explanation to rephrase:\n{baseline}"},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "GridPulse",
    }
    station_key = _station_key(rec)
    t0 = time.monotonic()
    reason = "no attempt made"
    # The free router may hand back a different (sometimes unsuitable) model each call, so retry a few times.
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = httpx.post(OPENROUTER_URL, json=payload, headers=headers,
                              timeout=min(settings.openrouter_timeout_s, 15.0))
            resp.raise_for_status()
            text = (resp.json()["choices"][0]["message"]["content"] or "").translate(_SPACES).strip()
        except Exception as exc:  # network, HTTP status, JSON shape
            reason = f"OpenRouter call failed: {type(exc).__name__}: {str(exc)[:120]}"
            continue
        problem = _text_problem(text, station_key, facts + " " + baseline)
        if problem is None:
            return text, None, int((time.monotonic() - t0) * 1000)
        reason = f"{problem} (attempt {attempt}/{MAX_ATTEMPTS})"
    return None, reason, int((time.monotonic() - t0) * 1000)
