"""Pure, deterministic scheduling logic. No database, network or clock access in here.

All times are minutes relative to "now" (float). This is the core of GridPulse: queue simulation with
priority classes, site power headroom, charge-time estimation with taper, urgency, and the score used
to rank stations. Nothing in this module calls an LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

# ---- tunable constants -------------------------------------------------------------------------
MIN_KW = 3.0  # below this a session is not worth starting (power-blocked)
TAPER_SOC = 80.0  # above this SOC the vehicle accepts only TAPER_FACTOR of the power
TAPER_FACTOR = 0.5
RESERVE_SOC = 5.0  # arriving below this is considered stranded-risk => station infeasible
KWH_PER_KM = 0.18  # assumed consumption
NOMINAL_STATION_KW = 22.0  # used only for the request-time urgency estimate

# ---- scoring:  final_score = travel_time + predicted_wait + charging_time + load_penalty - urgency_bonus ----
FORMULA = "final_score = travel_time + predicted_wait + charging_time + load_penalty - urgency_bonus"
# load_penalty: above this projected site utilisation a station is penalised, so we steer drivers away from
# stations that would be running at their power limit...
LOAD_PENALTY_START_UTIL = 0.70
LOAD_PENALTY_PER_UNIT = 60.0  # ...by this many minutes per 1.00 (100 points) of utilisation above the start
# urgency_bonus: a station earns up to this many minutes off its score for an urgent driver, scaled by
#   urgency (0..1)  x  immediacy (1.0 with no wait, 0.5 at a 15 min wait, ...)  x  deadline factor (1.0 if the
#   deadline is met, fading to 0 when it is missed by DEADLINE_BONUS_GRACE_MIN or more).
# So urgency favours stations that can start the driver soon AND get them there in time.
URGENCY_BONUS_MAX_MIN = 30.0
URGENCY_WAIT_SCALE_MIN = 15.0
DEADLINE_BONUS_GRACE_MIN = 30.0
PRIORITY_RANK = {"urgent": 0, "normal": 1, "flexible": 2}
NEW_JOB = "__new__"
_PAST = -1e9


# ---- energy / time helpers -----------------------------------------------------------------------
def soc_after_drive(soc: float, distance_km: float, battery_kwh: float) -> float:
    return max(0.0, soc - distance_km * KWH_PER_KM / battery_kwh * 100.0)


def charge_minutes(soc_from: float, soc_to: float, battery_kwh: float, kw: float) -> float:
    """Minutes to charge from soc_from to soc_to at kw, with reduced power above TAPER_SOC."""
    if soc_to <= soc_from or kw <= 0:
        return 0.0
    fast_part = max(0.0, min(soc_to, TAPER_SOC) - soc_from) / 100.0 * battery_kwh
    slow_part = max(0.0, soc_to - max(soc_from, TAPER_SOC)) / 100.0 * battery_kwh
    return (fast_part / kw + slow_part / (kw * TAPER_FACTOR)) * 60.0


# ---- urgency -------------------------------------------------------------------------------------
def soc_urgency(soc: float) -> float:
    """1.0 at <=10% SOC, falling linearly to 0.0 at >=50%."""
    if soc <= 10:
        return 1.0
    if soc >= 50:
        return 0.0
    return (50.0 - soc) / 40.0


def deadline_urgency(slack_min: float) -> float:
    """1.0 with no slack, 0.0 with >=120 minutes of slack."""
    if slack_min <= 0:
        return 1.0
    if slack_min >= 120:
        return 0.0
    return 1.0 - slack_min / 120.0


def classify(urgency: float) -> str:
    if urgency >= 0.7:
        return "urgent"
    if urgency <= 0.3:
        return "flexible"
    return "normal"


def compute_urgency(
    soc_current: float, soc_target: float, deadline_min: float, battery_kwh: float, vehicle_kw: float
) -> tuple[float, str]:
    """Request-time urgency: worst of low-battery urgency and tight-deadline urgency."""
    need_min = charge_minutes(
        soc_current, soc_target, battery_kwh, min(vehicle_kw, NOMINAL_STATION_KW)
    )
    u = max(soc_urgency(soc_current), deadline_urgency(deadline_min - need_min))
    u = round(u, 3)
    return u, classify(u)


# ---- queue simulation ----------------------------------------------------------------------------
@dataclass(frozen=True)
class QueueJob:
    key: str
    arrival_min: float
    duration_min: float
    rank: int  # lower = higher priority
    kw: float


@dataclass(frozen=True)
class Slot:
    start_min: float
    end_min: float
    headroom_kw: float  # site headroom at the moment this job started (before it drew power)


def _overlap_kw(entries: Sequence[tuple[float, float, float]], t: float) -> float:
    return sum(kw for s, e, kw in entries if s <= t < e)


def simulate_queue(
    port_free_min: Sequence[float],
    jobs: Sequence[QueueJob],
    running: Sequence[tuple[float, float, float]] = (),
    site_avail_kw: Optional[float] = None,
) -> dict[str, Slot]:
    """Non-preemptive priority scheduling on N ports with a shared site power budget.

    - A port that frees up serves the highest-priority job that has already arrived (ties: earliest
      arrival). Active sessions are never preempted; higher-priority jobs only jump the *queue*.
    - Before a job starts, site headroom (site_avail_kw minus power of overlapping sessions) must be at
      least MIN_KW; otherwise the start slides to the next session end.
    - `running` = already-committed (start, end, kw) entries, i.e. active sessions.
    """
    free = [max(0.0, f) for f in port_free_min] or [0.0]
    pending = sorted(jobs, key=lambda j: (j.arrival_min, j.rank, j.key))
    committed: list[tuple[float, float, float]] = list(running)
    result: dict[str, Slot] = {}

    while pending:
        p = min(range(len(free)), key=lambda i: free[i])
        t = free[p]
        arrived = [j for j in pending if j.arrival_min <= t + 1e-9]
        if not arrived:
            t = min(j.arrival_min for j in pending)
            arrived = [j for j in pending if j.arrival_min <= t + 1e-9]
        job = min(arrived, key=lambda j: (j.rank, j.arrival_min, j.key))
        pending.remove(job)

        headroom = float("inf")
        if site_avail_kw is not None:
            while True:
                headroom = site_avail_kw - _overlap_kw(committed, t)
                if headroom >= MIN_KW:
                    break
                later_ends = [e for _, e, _ in committed if e > t]
                if not later_ends:
                    break
                t = min(later_ends)

        end = t + job.duration_min
        result[job.key] = Slot(t, end, headroom)
        committed.append((t, end, job.kw))
        free[p] = end
    return result


# ---- station evaluation -------------------------------------------------------------------------
@dataclass(frozen=True)
class ActiveLoad:
    end_min: float
    kw: float


@dataclass(frozen=True)
class QueuedLoad:
    key: str
    arrival_min: float
    duration_min: float
    rank: int
    kw: float


@dataclass(frozen=True)
class StationSnapshot:
    id: int
    code: str
    name: str
    kind: str
    lat: float
    lon: float
    ports: int
    max_kw_per_port: float
    site_limit_kw: float
    base_load_kw: float
    is_online: bool
    active: tuple[ActiveLoad, ...] = ()
    queued: tuple[QueuedLoad, ...] = ()

    @property
    def current_load_kw(self) -> float:
        return self.base_load_kw + sum(a.kw for a in self.active)


@dataclass(frozen=True)
class DriverNeed:
    soc_current: float
    soc_target: float
    deadline_min: float
    battery_kwh: float
    max_charge_kw: float
    urgency: float
    priority_class: str


@dataclass
class Candidate:
    station_id: int
    code: str
    name: str
    kind: str
    feasible: bool
    rejection_reason: Optional[str] = None
    distance_km: float = 0.0
    travel_min: float = 0.0
    route_source: str = ""
    soc_arrival: float = 0.0
    start_min: float = 0.0  # minutes from now until charging starts
    wait_min: float = 0.0
    charge_min: float = 0.0
    total_min: float = 0.0  # travel + wait + charge
    charge_kw: float = 0.0
    power_limited: bool = False
    queue_ahead: int = 0
    displaces: int = 0  # lower-priority queued drivers pushed back by this driver
    active_sessions: int = 0
    site_load_kw: float = 0.0
    site_limit_kw: float = 0.0
    headroom_kw: float = 0.0
    deadline_ok: bool = True
    deadline_miss_min: float = 0.0
    available_ports: int = 0  # ports with no active session right now
    queue_count: int = 0  # drivers currently queued
    projected_load_pct: float = 0.0  # site load (%) once this driver is charging
    route_estimated: bool = False  # route time is a straight-line estimate, not a real road route
    route_fallback: bool = False  # OSRM failed / rate-limited and we degraded to the estimate
    score: float = float("inf")
    score_breakdown: dict = field(default_factory=dict)


def _r(x: float, n: int = 1) -> float:
    return round(x, n)


def evaluate_station(need: DriverNeed, snap: StationSnapshot, distance_km: float,
                     travel_min: float, route_source: str = "") -> Candidate:
    cand = Candidate(
        station_id=snap.id, code=snap.code, name=snap.name, kind=snap.kind, feasible=False,
        distance_km=_r(distance_km, 2), travel_min=_r(travel_min), route_source=route_source,
        site_load_kw=_r(snap.current_load_kw), site_limit_kw=_r(snap.site_limit_kw),
        active_sessions=len(snap.active),
        available_ports=max(0, snap.ports - len(snap.active)), queue_count=len(snap.queued),
        route_estimated=bool(route_source) and route_source != "osrm",
        route_fallback="fallback" in route_source,
    )
    if not snap.is_online:
        cand.rejection_reason = "Station is offline"
        return cand

    soc_arr = soc_after_drive(need.soc_current, distance_km, need.battery_kwh)
    cand.soc_arrival = _r(soc_arr)
    if soc_arr < RESERVE_SOC:
        cand.rejection_reason = (
            f"Battery would drop to {soc_arr:.0f}% on arrival (below {RESERVE_SOC:.0f}% reserve)"
        )
        return cand
    if soc_arr >= need.soc_target:
        cand.rejection_reason = "Target SOC already met on arrival"
        return cand

    rank = PRIORITY_RANK[need.priority_class]
    site_avail = snap.site_limit_kw - snap.base_load_kw
    running = [(_PAST, a.end_min, a.kw) for a in snap.active]
    port_free = [a.end_min for a in snap.active][: snap.ports]
    port_free += [0.0] * (snap.ports - len(port_free))
    others = [QueueJob(q.key, q.arrival_min, q.duration_min, q.rank, q.kw) for q in snap.queued]

    baseline = simulate_queue(port_free, others, running, site_avail)

    kw_guess = min(snap.max_kw_per_port, need.max_charge_kw)
    guess_job = QueueJob(
        NEW_JOB, travel_min, charge_minutes(soc_arr, need.soc_target, need.battery_kwh, kw_guess),
        rank, kw_guess,
    )
    first = simulate_queue(port_free, others + [guess_job], running, site_avail)
    slot = first[NEW_JOB]
    if slot.headroom_kw < MIN_KW:
        cand.rejection_reason = "No spare site power available"
        return cand

    kw = min(kw_guess, slot.headroom_kw)
    charge = charge_minutes(soc_arr, need.soc_target, need.battery_kwh, kw)
    final_job = QueueJob(NEW_JOB, travel_min, charge, rank, kw)
    final = simulate_queue(port_free, others + [final_job], running, site_avail)
    start = final[NEW_JOB].start_min

    wait = max(0.0, start - travel_min)
    total = travel_min + wait + charge
    completion = start + charge
    miss = max(0.0, completion - need.deadline_min)
    load_before = snap.site_limit_kw - slot.headroom_kw  # base load + overlapping EV sessions at start
    projected_util = (load_before + kw) / snap.site_limit_kw if snap.site_limit_kw else 1.0
    # Components are rounded first and the final score is computed from the rounded values, so the
    # breakdown adds up exactly as displayed.
    travel_r, wait_r, charge_r = _r(travel_min), _r(wait), _r(charge)
    load_penalty = _r(LOAD_PENALTY_PER_UNIT * max(0.0, projected_util - LOAD_PENALTY_START_UTIL))
    immediacy = 1.0 / (1.0 + wait / URGENCY_WAIT_SCALE_MIN)
    deadline_factor = 1.0 if miss <= 0.0 else max(0.0, 1.0 - miss / DEADLINE_BONUS_GRACE_MIN)
    subtotal = travel_r + wait_r + charge_r + load_penalty
    urgency_bonus = _r(min(URGENCY_BONUS_MAX_MIN * need.urgency * immediacy * deadline_factor, subtotal))
    final_score = _r(subtotal - urgency_bonus)

    cand.feasible = True
    cand.start_min = _r(start, 2)
    cand.wait_min = _r(wait)
    cand.charge_min = _r(charge)
    cand.total_min = _r(total)
    cand.charge_kw = _r(kw)
    cand.power_limited = kw < kw_guess - 0.05
    cand.headroom_kw = _r(slot.headroom_kw)
    cand.queue_ahead = sum(1 for q in snap.queued if final[q.key].start_min < start)
    cand.displaces = sum(
        1 for q in snap.queued if final[q.key].start_min > baseline[q.key].start_min + 0.5
    )
    cand.deadline_ok = miss <= 0.0
    cand.deadline_miss_min = _r(miss)
    cand.projected_load_pct = _r(projected_util * 100.0)
    cand.score = final_score
    cand.score_breakdown = {
        "travel_time": travel_r,
        "predicted_wait": wait_r,
        "charging_time": charge_r,
        "load_penalty": load_penalty,
        "urgency_bonus": urgency_bonus,
        "final_score": final_score,
        # inputs behind the two adjustment terms, so the UI/LLM can explain them
        "urgency": _r(need.urgency, 2),
        "immediacy": _r(immediacy, 2),
        "deadline_factor": _r(deadline_factor, 2),
        "projected_load_pct": _r(projected_util * 100.0),
    }
    return cand
