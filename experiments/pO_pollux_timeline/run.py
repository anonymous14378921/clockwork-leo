"""Export full-cycle schedules for a fixed, illustrative two-hour timeline."""
import json
import math
import shutil
import pandas as pd
from lab import calendar as cal
from lab.cycle import grid, cycle_s
from lab.harness import Run
from lab.provider import build_provider
from lab.provision_milp import load_chain, load_io, load_profiles


def main():
    run = Run.start('pO_pollux_timeline')
    cfg = run.config
    # Preserve inputs as well as the harness provenance, including dirty trees.
    for directory in ('src', 'configs', 'constants', 'workflows', 'data'):
        shutil.copytree(run.root / directory, run.dir / 'inputs' / directory,
                        ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(__file__, run.dir / 'run.py')
    times = grid(cfg['n_steps'])
    step_h = cycle_s() / len(times) / 3600
    build = lambda t: build_provider(cfg['provider'],
        (cfg['aoi']['lat'], cfg['aoi']['lon']), t=t, seed=cfg['seed'])
    log = lambda msg: print(msg, flush=True)
    states = cal.collect_candidates(build, times, cfg['slo_ms'], cfg['cost_slack'], log)
    comps, edges = load_chain()
    table, rates = cal.latency_table(build, times, states, comps, edges,
                                   load_profiles(), load_io(), log)
    feasible = [[i for i in range(len(states)) if cal.feasible(table, k, i, cfg['slo_ms'])]
                for k in range(len(times))]
    optimum = [min(ids, key=lambda i: rates[i]) if ids else -1 for ids in feasible]
    schedules = {'Pollux': cal.plan_calendar(states, table, rates, step_h,
                                             cfg['switch_cost'], cfg['slo_ms'])}
    for name, policy in [('Reactive', 'event'), ('Per-Snapshot Minimum', 'fresh')]:
        schedules[name] = cal.simulate_reactive(states, table, rates, optimum,
            step_h, cfg['slo_ms'], policy, 0, cfg['switch_cost'])
    for minutes in cfg.get('horizons_min', []):
        log(f'Rolling Horizon {minutes} minutes')
        steps = max(1, int(round(minutes*60/(step_h*3600))))
        schedules[f'RH{minutes}'] = cal.simulate_rolling(states, table, rates,
            step_h, cfg['switch_cost'], cfg['slo_ms'], steps)
    rows, summary = [], {}
    for name, schedule in schedules.items():
        total = 0.0
        events = 0
        for k, t in enumerate(times):
            i, old = schedule.assignment[k], schedule.assignment[k-1]
            state = states[i] if i >= 0 else cal.NONE
            previous = states[old] if old >= 0 else cal.NONE
            changed = cal.is_reprovision(previous, state)
            rate = rates[i] if i >= 0 else 0.0
            before = total
            total += cfg['switch_cost'] * changed + rate * step_h
            events += changed
            assert not feasible[k] or i in feasible[k]
            rows.append(dict(method=name, snapshot=k, time_s=t,
                end_s=t + step_h*3600, state=i, rate=rate,
                reprovision=int(changed), pool_serviceable=bool(feasible[k]),
                cumulative_before=before, cumulative_after=total,
                latency_ms=table[k][i][1] if i >= 0 and table[k][i] else None))
        assert math.isclose(total, schedule.objective, rel_tol=1e-9)
        assert events == schedule.switches
        summary[name] = dict(cost=total, reprovisions=events, served=schedule.served)
    run.save_dataframe('timeline.csv', pd.DataFrame(rows))
    run.save_json('summary.json', summary)
    run.save_json('states.json', [dict(id=i, compute=s.compute, planes=sorted(s.planes),
                                     rate=rates[i]) for i, s in enumerate(states)])
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
