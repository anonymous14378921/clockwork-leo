"""Pollux: cyclic schedule construction over one orbital cycle.

The plan object is a CALENDAR: a sequence of segments over one cycle (a
sidereal day), each holding a provisioning STATE, and repeating every
cycle. A state is a compute placement (component -> satellite, hardware
implied) plus the reserved plane set. Inside a segment the ingress
satellite is the best AoI-visible member of the reserved planes at each
instant (free handover); a segment boundary is a REPROVISION, which
changes the compute placement or grows the plane set (shrinking is free).

Objective: integrated reservation cost plus a switching cost per
reprovision, subject to per-request SLO feasibility at every instant.
Solved exactly over a candidate state pool by a time-axis dynamic program
(states x instants), with the running-minimum trick for switches, run
around the cycle twice so the calendar wraps. Candidates come from
Castor's per-instant label search (every nondominated final plan within
a cost slack of the instant's optimum), so a slightly dearer plan that
lasts longer is available to the DP.

Unserviceable intervals (no state can serve) allow a state to be held
(paid, unserved) or released (free); re-entry is a reprovision.

Approximations: (1) time is discretized to N instants; (2) the state
pool is finite, controlled by the cost slack; (3) the cyclic wrap is
handled by two passes, provably within two switching costs of the cyclic
optimum, with the linear optimum as a lower bound (exact_cycle=True
solves the wrap exactly for small pools).
"""

from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

from lab.provider import INF_MS, PlaneId, ProviderInstance, SatId
from lab.castor import solve_label
from lab.service import AOI, EGRESS, ProvisionPlan, evaluate, load_io

Build = Callable[[float], ProviderInstance]     # t -> instance


@dataclass(frozen=True)
class State:
    compute: Tuple[Tuple[str, SatId, str], ...]   # (component, sat, hw)
    planes: FrozenSet[PlaneId]

    @property
    def compute_key(self):
        return tuple((v, s) for v, s, _ in self.compute)

    def placement(self, ingress: SatId, egress: SatId
                  ) -> Dict[str, Tuple[SatId, Optional[str]]]:
        p: Dict[str, Tuple[SatId, Optional[str]]] = {AOI: (ingress, None),
                                                    EGRESS: (egress, None)}
        for v, s, h in self.compute:
            p[v] = (s, h)
        return p


NONE = State(compute=tuple(), planes=frozenset())


def state_of(plan: ProvisionPlan) -> State:
    comp = tuple(sorted((a.component, a.sat, a.hardware)
                        for a in plan.assignments
                        if a.component not in (AOI, EGRESS)))
    return State(comp, frozenset(plan.activated))


def rate_of(inst: ProviderInstance, state: State) -> float:
    """Reservation rate of a state in cost units per hour (its plan cost:
    activated planes plus every used satellite billed once)."""
    if state is NONE:
        return 0.0
    sats = {s for _, s, _ in state.compute}
    return (len(state.planes) * inst.plane_cost
            + sum(inst.hw_cost[inst.sat_hw[s]] for s in sats))


def serve(inst: ProviderInstance, state: State, comps, edges, profiles, io
          ) -> Optional[Tuple[SatId, float]]:
    """Best ingress and egress within the state's reserved planes at this
    instant: ((ingress, egress), minimum end-to-end latency), or None when
    no reserved plane has a visible member or no route exists. Ingress and
    egress are symmetric: both are visible satellites of reserved planes
    and both may hand over freely. Callers threshold the latency against
    their SLO (minus any margin), so one table serves every margin."""
    vis = inst.visible_in(state.planes)
    if not vis:
        return None
    best = None
    for s_in in vis:
        for s_out in vis:
            _, lat, _, _, _ = evaluate(inst, comps, edges, profiles,
                                       state.placement(s_in, s_out), io)
            if lat < INF_MS and (best is None or lat < best[1]):
                best = ((s_in, s_out), lat)
    return best


def is_reprovision(old: State, new: State) -> bool:
    """A reprovision changes the compute placement or grows the plane set.
    Releasing everything (to NONE) is free; provisioning from NONE is a
    reprovision."""
    if new is NONE:
        return False
    if old is NONE:
        return True
    return old.compute_key != new.compute_key or not new.planes <= old.planes


def collect_candidates(build: Build, times: List[float], slo_ms: float,
                       cost_slack: float, log=None) -> List[State]:
    """Union over instants of every nondominated final plan within
    cost_slack of that instant's optimum, plus each plan's release variant
    (the compute planes alone) when it differs."""
    seen: Dict[State, None] = {}
    for k, t in enumerate(times):
        inst = build(t)
        plans = solve_label(inst, slo_ms, keep_all=True, cost_slack=cost_slack)
        for plan in plans or []:
            st = state_of(plan)
            seen.setdefault(st, None)
            core = frozenset((s[0], s[1]) for _, s, _ in st.compute)
            if core != st.planes:
                seen.setdefault(State(st.compute, core), None)
        if log and k % max(1, len(times) // 4) == 0:
            log(f"[calendar] candidates at instant {k}: {len(seen)}")
    return list(seen)


def latency_table(build: Build, times: List[float], states: List[State],
                  comps, edges, profiles, io, log=None
                  ) -> Tuple[List[List[Optional[Tuple[SatId, float]]]],
                             List[float]]:
    """serve() of every state at every instant, and each state's rate."""
    table: List[List[Optional[Tuple[SatId, float]]]] = []
    rates: List[float] = []
    for k, t in enumerate(times):
        inst = build(t)
        if not rates:
            rates = [rate_of(inst, st) for st in states]
        table.append([serve(inst, st, comps, edges, profiles, io)
                      for st in states])
        if log and k % max(1, len(times) // 4) == 0:
            log(f"[calendar] latency table instant {k}/{len(times)}")
    return table, rates


def feasible(table, k: int, i: int, slo_ms: float) -> bool:
    cell = table[k][i]
    return cell is not None and cell[1] <= slo_ms


@dataclass
class Calendar:
    states: List[State]
    assignment: List[int]            # per instant: state index, -1 = NONE
    ingress: List[Optional[Tuple[SatId, SatId]]]   # scheduled (in, out)
    switches: int                    # reprovisions per cycle (wrap included)
    unit_hours: float                # reserved cost units x hours per cycle
    served: float                    # fraction of instants served
    objective: float
    lower_bound: float = float("nan")   # linear (no-wrap) optimum over X

    def segments(self) -> List[Tuple[int, int, int]]:
        """(start instant, end instant exclusive, state index) runs."""
        out = []
        start = 0
        for k in range(1, len(self.assignment) + 1):
            if k == len(self.assignment) or \
                    self.assignment[k] != self.assignment[start]:
                out.append((start, k, self.assignment[start]))
                start = k
        return out


def _free_pred(states) -> List[List[int]]:
    """Free predecessors per state: same compute placement and a superset
    of planes (stay, or release planes)."""
    groups: Dict[Tuple, List[int]] = {}
    for i, st in enumerate(states):
        groups.setdefault(st.compute_key, []).append(i)
    return [[j for j in groups[st.compute_key]
             if states[j].planes >= st.planes] for st in states]


def _dp_core(states, table, rates, step_h, switch_cost, slo_ms,
             instants: List[int], start: Optional[int] = None,
             init: Optional[List[float]] = None, free_pred=None):
    """Time-axis DP over the given table instants (indices into the
    table, so a window may wrap around the cycle). Index m = NONE.
    `start` pins the first instant to that state; `init` is the value
    row of a virtual predecessor instant (the incumbent before the
    window) from which the first instant is entered with the usual
    switch economy. Returns the value and parent tables."""
    n = len(table)
    m = len(states)
    if free_pred is None:
        free_pred = _free_pred(states)
    INF = float("inf")
    horizon = len(instants)
    dp = [[INF] * (m + 1) for _ in range(horizon)]
    parent = [[-1] * (m + 1) for _ in range(horizon)]
    for h, k in enumerate(instants):
        feas = [i for i in range(m) if feasible(table, k, i, slo_ms)]
        # Coverage gap (no state can serve): every state may be HELD,
        # reserved and paid but serving nothing, or released to NONE
        # (free); re-entry from NONE is a reprovision. Holding is what a
        # reactive controller does, so both sides see the same economy.
        gap = not feas
        allowed = list(range(m)) if gap else feas
        if h == 0 and init is None:
            if start is not None:
                if start == m:
                    dp[0][m] = 0.0
                elif start in allowed:
                    dp[0][start] = rates[start] * step_h
                continue
            for i in allowed:
                dp[0][i] = rates[i] * step_h
            dp[0][m] = 0.0 if gap else INF
            continue
        prev = init if h == 0 else dp[h - 1]
        gmin = min(range(m + 1), key=lambda j: prev[j])
        if prev[gmin] == INF:
            continue                        # pinned start infeasible
        for i in allowed:
            best_val, best_j = INF, -1
            for j in free_pred[i]:
                if prev[j] < best_val:
                    best_val, best_j = prev[j], j
            if prev[gmin] + switch_cost < best_val:
                best_val, best_j = prev[gmin] + switch_cost, gmin
            dp[h][i] = best_val + rates[i] * step_h
            parent[h][i] = best_j
        if gap:                             # releasing is free
            dp[h][m] = prev[gmin]
            parent[h][m] = gmin
    return dp, parent


def _dp_pass(states, table, rates, step_h, switch_cost, slo_ms, passes: int,
             start: Optional[int] = None):
    """Time-axis DP over `passes` consecutive cycles. Returns the state
    index path (index m = NONE) and the final-instant values. With
    `start`, the first instant is pinned to that state."""
    n = len(table)
    return _dp_core(states, table, rates, step_h, switch_cost, slo_ms,
                    [h % n for h in range(passes * n)], start=start)


def _backtrack(parent, dp, horizon: int, end: int) -> List[int]:
    path = [0] * horizon
    cur = end
    for h in range(horizon - 1, -1, -1):
        path[h] = cur
        cur = parent[h][cur]
    return path


def _finish(states, table, rates, step_h, switch_cost, seq: List[int],
            slo_ms: float) -> Calendar:
    """Assemble a Calendar from a state-index sequence. A reserved state
    at an instant it cannot serve is HELD (paid, unserved)."""
    n = len(table)
    m = len(states)
    assignment = [i if i < m else -1 for i in seq]
    state_seq = [states[i] if i >= 0 else NONE for i in assignment]
    switches = sum(is_reprovision(state_seq[k - 1], state_seq[k])
                   for k in range(1, n))
    switches += is_reprovision(state_seq[-1], state_seq[0])   # wrap
    unit_hours = sum(rates[i] * step_h for i in assignment if i >= 0)
    ingress = [table[k][i][0] if i >= 0 and feasible(table, k, i, slo_ms)
               else None for k, i in enumerate(assignment)]
    served = sum(x is not None for x in ingress) / n
    return Calendar(states, assignment, ingress, switches, unit_hours,
                    served, unit_hours + switch_cost * switches)


def plan_calendar(states: List[State], table, rates: List[float],
                  step_h: float, switch_cost: float, slo_ms: float,
                  exact_cycle: bool = False) -> Calendar:
    """DP over the candidate pool. Objective: sum of rate x step over
    reserved instants plus switch_cost per reprovision, the wrap-around
    reprovision included. Default: two passes around the cycle, the
    second returned (provably within two switch costs of the cyclic optimum, with
    the linear optimum returned as a lower bound). exact_cycle=True pins every
    possible start state in turn and charges the wrap exactly (tiny
    horizons, the test oracle's counterpart)."""
    n = len(table)
    m = len(states)
    if not exact_cycle:
        dp, parent = _dp_pass(states, table, rates, step_h, switch_cost,
                              slo_ms, passes=2)
        end = min(range(m + 1), key=lambda j: dp[2 * n - 1][j])
        cal = _finish(states, table, rates, step_h, switch_cost,
                      _backtrack(parent, dp, 2 * n, end)[n:], slo_ms)
        # The linear (no-wrap) optimum lower-bounds the cyclic optimum; the
        # two-pass calendar is provably within 2 x switch_cost of it and
        # the measured gap is reported next to every result.
        cal.lower_bound = min(dp[n - 1])
        return cal
    best = None
    starts = [i for i in range(m) if feasible(table, 0, i, slo_ms)]
    if not starts:
        starts = list(range(m + 1))         # gap at instant 0: hold or NONE
    for s0 in starts:
        dp, parent = _dp_pass(states, table, rates, step_h, switch_cost,
                              slo_ms, passes=1, start=s0)
        for end in range(m + 1):
            if dp[n - 1][end] == float("inf"):
                continue
            wrap = is_reprovision(states[end] if end < m else NONE,
                                  states[s0] if s0 < m else NONE)
            total = dp[n - 1][end] + switch_cost * wrap
            if best is None or total < best[0]:
                best = (total, _backtrack(parent, dp, n, end))
    return _finish(states, table, rates, step_h, switch_cost, best[1],
                   slo_ms)


def plan_day(states: List[State], table, rates: List[float],
             step_h: float, switch_cost: float, slo_ms: float,
             start: Optional[int] = None) -> Calendar:
    """One horizon planned linearly (no wrap): the daily planner for a
    constellation whose AoI geometry does not repeat. `start` is the
    index of the state held when the horizon begins (yesterday's last
    state; None = nothing held); entering the first instant from it
    follows the usual switch economy, so a reprovision at the boundary
    is charged like any other. Exact for the horizon it is given."""
    n = len(table)
    m = len(states)
    INF = float("inf")
    init = None
    if start is not None:
        init = [INF] * (m + 1)
        init[start] = 0.0
    dp, parent = _dp_core(states, table, rates, step_h, switch_cost,
                          slo_ms, list(range(n)), init=init)
    end = min(range(m + 1), key=lambda j: dp[n - 1][j])
    seq = _backtrack(parent, dp, n, end)
    cal = _finish(states, table, rates, step_h, switch_cost, seq, slo_ms)
    state_seq = [states[i] if i < m else NONE for i in seq]
    first = states[start] if start is not None and start < m else NONE
    cal.switches = is_reprovision(first, state_seq[0]) + sum(
        is_reprovision(state_seq[k - 1], state_seq[k]) for k in range(1, n))
    cal.objective = cal.unit_hours + switch_cost * cal.switches
    cal.lower_bound = cal.objective          # exact on its horizon
    return cal


def replay(table_other, cal: Calendar, slo_ms: float) -> List[bool]:
    """Execute a calendar open-loop against another latency table (another
    substrate, such as the near-repeat altitudes, or the same one without
    the planning margin): per instant, is the scheduled state still
    SLO-feasible with free handover inside its reserved planes?"""
    return [i >= 0 and feasible(table_other, k, i, slo_ms)
            for k, i in enumerate(cal.assignment)]


def _second_cycle(states, table, rates, step_h, switch_cost, seq2,
                  served2, slo_ms) -> Calendar:
    """Report the second of two simulated cycles: assignment and service
    from instants n..2n-1, reprovisions counted on the transitions INTO
    those instants (the one from instant n-1 to n is the cycle boundary,
    the counterpart of the calendar's wrap)."""
    n = len(table)
    m = len(states)
    cal = _finish(states, table, rates, step_h, switch_cost, seq2[n:],
                  slo_ms)
    state_seq = [states[i] if i < m else NONE for i in seq2]
    cal.switches = sum(is_reprovision(state_seq[k - 1], state_seq[k])
                       for k in range(n, 2 * n))
    cal.objective = cal.unit_hours + switch_cost * cal.switches
    if served2 is not None:
        cal.served = sum(served2[n:]) / n
    return cal


def simulate_reactive(states: List[State], table, rates: List[float],
                      optimum: List[int], step_h: float, slo_ms: float,
                      policy: str, staging_steps: int = 0,
                      switch_cost: float = 0.0) -> Calendar:
    """Reactive baselines on the same instants and candidate states,
    simulated over TWO cycles from nothing, the second cycle reported.
    `optimum[k]` is the index of the instant's min-cost state (-1 if none).
    event: keep the incumbent while feasible, else adopt the optimum.
    fresh: adopt the optimum whenever that is a reprovision. During an
    UNSERVICEABLE interval (no state can serve) both release their
    reservation for free, exactly as the calendar DP may; re-entry counts
    as a reprovision on both sides, so that at switch cost zero the
    calendar and always-fresh coincide (tested). A switch takes
    staging_steps instants to come up (model staging), during which the
    request is not served; with staging_steps=0 the policy is pre-staged
    (the overlap is priced separately by overlap_unit_hours)."""
    n = len(table)
    m = len(states)
    inc = -1
    seq, served = [], []
    down_until = -1
    for h in range(2 * n):
        k = h % n
        if optimum[k] < 0:                  # unserviceable: release
            inc = -1
            seq.append(m)
            served.append(False)
            continue
        alive = inc >= 0 and feasible(table, k, inc, slo_ms)
        if policy == "event":
            adopt = not alive
        elif policy == "fresh":
            # adopt the instant's optimum whenever it differs (a cheaper
            # release variant included); only a reprovision counts a switch
            adopt = not alive or optimum[k] != inc
        else:
            raise ValueError(policy)
        switched = False
        if adopt:
            switched = inc < 0 or is_reprovision(states[inc],
                                                 states[optimum[k]])
            inc = optimum[k]
            alive = True
        if switched and staging_steps > 0:
            down_until = h + staging_steps
        seq.append(inc if inc >= 0 else m)
        served.append(alive and h >= down_until)
    return _second_cycle(states, table, rates, step_h, switch_cost, seq,
                         served, slo_ms)


def simulate_rolling(states: List[State], table, rates: List[float],
                     step_h: float, switch_cost: float, slo_ms: float,
                     horizon_steps: int) -> Calendar:
    """Rolling-horizon baseline: at every instant, run the calendar DP
    over the next `horizon_steps` instants (wrapping around the cycle)
    from the incumbent state, apply only the first decision, advance.
    Two cycles from nothing, the second reported. Same states, table,
    rates and switch economy as the calendar; it only sees less future."""
    n = len(table)
    m = len(states)
    H = max(1, min(horizon_steps, n))
    fp = _free_pred(states)
    INF = float("inf")
    inc = m
    seq = []
    for h in range(2 * n):
        k = h % n
        init = [INF] * (m + 1)
        init[inc] = 0.0
        window = [(k + j) % n for j in range(H)]
        dp, parent = _dp_core(states, table, rates, step_h, switch_cost,
                              slo_ms, window, init=init, free_pred=fp)
        end = min(range(m + 1), key=lambda j: dp[H - 1][j])
        if dp[H - 1][end] == INF:           # nothing reachable: release
            inc = m
        else:
            inc = _backtrack(parent, dp, H, end)[0]
        seq.append(inc)
    return _second_cycle(states, table, rates, step_h, switch_cost, seq,
                         None, slo_ms)


def overlap_unit_hours(cal: Calendar, rates: List[float],
                       staging_s: float) -> float:
    """Price of pre-provisioning: the calendar reserves each incoming
    state staging_s before its boundary, so both states are paid during
    the overlap. Returns the extra unit-hours per cycle."""
    n = len(cal.assignment)
    extra = 0.0
    for k in range(n):
        i, j = cal.assignment[k - 1], cal.assignment[k]
        if j >= 0 and i != j:
            extra += rates[j] * staging_s / 3600.0
    return extra


def brute_calendar(states: List[State], table, rates: List[float],
                   step_h: float, switch_cost: float, slo_ms: float
                   ) -> float:
    """Exhaustive objective over all state sequences (tiny horizons only;
    the wrap is included exactly like the DP counts it). Test oracle."""
    import itertools
    n = len(table)
    m = len(states)
    # at a gap instant any state may be held (paid) or nothing (NONE)
    options = [[i for i in range(m) if feasible(table, k, i, slo_ms)]
               or list(range(m)) + [-1] for k in range(n)]
    best = float("inf")
    for seq in itertools.product(*options):
        st = [states[i] if i >= 0 else NONE for i in seq]
        cost = sum(rates[i] * step_h for i in seq if i >= 0)
        sw = sum(is_reprovision(st[k - 1], st[k]) for k in range(1, n))
        sw += is_reprovision(st[-1], st[0])
        best = min(best, cost + switch_cost * sw)
    return best
