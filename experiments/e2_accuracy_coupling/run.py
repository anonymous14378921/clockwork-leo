"""E2 accuracy coupling: EQ1 spread + mechanisms, EQ2 cost frontier.

For every instance (constellation x AoI x capable fraction x fleet seed) the
restricted (configuration, placement) space is enumerated ONCE; the best and the
best-packed (zero-detour) plans are then derived per SLO by filtering, and the
budget frontier by filtering the designated instance. Spread = best - packed at
equal SLO. The chosen configuration per instance is the config-shift signal.

Run via `just run e2_accuracy_coupling`.
"""

import pandas as pd

from lab import constants as C
from lab.enumeration import enumerate_records, best_feasible
from lab.harness import Run
from lab.instances import build_instance
from lab.workflow import load_workflow


def _row(base: dict, tag: str, rec) -> dict:
    out = dict(base)
    if rec is None:
        out.update({f"{tag}_accuracy": None})
        return out
    out.update({
        f"{tag}_accuracy": rec["accuracy"],
        f"{tag}_detector": rec["detector"], f"{tag}_verifier": rec["verifier"],
        f"{tag}_threshold": rec["threshold"], f"{tag}_phi": rec["phi"],
        f"{tag}_cost": rec["cost"], f"{tag}_tight_ms": rec["tight_ms"],
        f"{tag}_detect_detour_ms": rec["detect_detour_ms"],
        f"{tag}_verify_detour_ms": rec["verify_detour_ms"],
        f"{tag}_detect_device": rec["detect_device"],
        f"{tag}_verify_device": rec["verify_device"],
        "acc_source": rec["acc_source"],
    })
    return out


def main() -> None:
    run = Run.start("e2_accuracy_coupling")
    cfg = run.config
    wf = load_workflow(cfg["workflow"])
    slack = wf.slo_slack_factor
    k = int(cfg["candidates_k"])

    rows = []
    for con in cfg["constellations"]:
        for seed in cfg["fleet_seeds"]:
            for p in cfg["capable_fractions"]:
                for aoi in cfg["aois"]:
                    inst = build_instance(con, aoi, C.to_float(p), int(seed))
                    base = {"constellation": con, "topology": inst.topology,
                            "aoi": aoi, "p": C.to_float(p), "seed": int(seed),
                            "covered": inst.covered}
                    if not inst.covered:
                        rows.append(dict(base, slo_s=None))
                        continue
                    records = enumerate_records(wf, inst, k)
                    for slo_s in cfg["slos_s"]:
                        slo_ms = C.to_float(slo_s) * 1e3
                        best = best_feasible(records, slo_ms, slack)
                        packed = best_feasible(records, slo_ms, slack,
                                               packed_only=True)
                        r = _row(dict(base, slo_s=C.to_float(slo_s)), "best", best)
                        r = _row(r, "packed", packed)
                        if best and packed:
                            r["spread"] = best["accuracy"] - packed["accuracy"]
                        rows.append(r)
                    print(f"[e2] {con} {aoi} p={p} seed={seed}: "
                          f"{len(records)} plans enumerated")
    df = pd.DataFrame(rows)
    run.save_dataframe("spread.csv", df)

    fr = cfg["frontier"]
    frows = []
    for seed in cfg["fleet_seeds"]:
        inst = build_instance(fr["constellation"], fr["aoi"],
                              C.to_float(fr["p"]) if "p" in fr else None,
                              int(seed), mix=fr.get("mix", "sparse-strong"))
        records = enumerate_records(wf, inst, k)
        for slo_s in fr["slos_s"]:
            for b in fr["budgets"]:
                budget = C.to_float(b)
                best = best_feasible(records, C.to_float(slo_s) * 1e3,
                                     slack, budget=budget)
                frows.append(_row({"budget": budget, "seed": int(seed),
                                   "slo_s": C.to_float(slo_s)}, "best", best))
    fdf = pd.DataFrame(frows)
    run.save_dataframe("frontier.csv", fdf)

    src = set(df.get("acc_source", pd.Series(dtype=str)).dropna().unique())
    print(f"[e2] accuracy sources in results: {src or '{none}'}")
    if src != {"measured-grid"}:
        print("[e2] WARNING: placeholder accuracy grid in use; results validate "
              "machinery and mechanism structure ONLY, not paper numbers.")
    n_cov = int(df["covered"].sum())
    print(f"[e2] rows: {len(df)} spread ({n_cov} covered), {len(fdf)} frontier")


if __name__ == "__main__":
    main()
