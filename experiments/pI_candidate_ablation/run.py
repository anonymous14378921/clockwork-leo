"""Experiment I: is the candidate restriction lossless? (verification)

For each instance, solve with the restricted candidate set and with the
full satellite set; compare optimal costs and runtimes. Run via
`just run pI_candidate_ablation`.
"""

import time

import pandas as pd

from lab import constants as C
from lab.cycle import epochs
from lab.harness import Run
from lab.provider import build_provider
from lab.provision_label import solve_label


def main() -> None:
    run = Run.start("pI_candidate_ablation")
    cfg = run.config
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))

    rows = []
    for t0 in epochs(cfg):
        for seed in cfg["fleet_seeds"]:
            inst = build_provider(cfg["provider"], aoi, t=float(t0),
                                  seed=int(seed))
            if not any(pv.visible for pv in inst.planes.values()):
                continue
            for slo in cfg["slos_ms"]:
                slo_ms = C.to_float(slo)
                t_s = time.perf_counter()
                restricted = solve_label(inst, slo_ms)
                t_res = time.perf_counter() - t_s
                t_s = time.perf_counter()
                full = solve_label(inst, slo_ms, full_candidates=True)
                t_full = time.perf_counter() - t_s
                match = ((restricted is None) == (full is None)
                         and (restricted is None
                              or abs(restricted.cost - full.cost) < 1e-6))
                rows.append({
                    "epoch_s": float(t0), "seed": int(seed), "slo_ms": slo_ms,
                    "cost_restricted": restricted.cost if restricted else None,
                    "cost_full": full.cost if full else None,
                    "time_restricted_s": t_res, "time_full_s": t_full,
                    "match": match,
                })
        print(f"[pI] epoch {t0} done", flush=True)
    df = pd.DataFrame(rows)
    run.save_dataframe("candidates.csv", df)
    mism = int((~df["match"]).sum())
    print(f"[pI] instances: {len(df)} | cost mismatches: {mism} | "
          f"median runtime restricted {df.time_restricted_s.median()*1e3:.1f}"
          f" ms vs full {df.time_full_s.median()*1e3:.1f} ms")
    if mism:
        print(df[~df["match"]].to_string())


if __name__ == "__main__":
    main()
