"""Toy experiment entry point.

The whole loop in one file: start a run (provenance captured automatically),
run the system under test, write raw data into the run dir. Run it with
`just run toy` — never `python experiments/toy/run.py` directly (see CLAUDE.md).
"""

import pandas as pd

from lab.harness import Run
from lab.toy import run_toy


def main() -> None:
    run = Run.start("toy")

    curves = run_toy(run.config)

    # Tidy long-form data: one row per (step, series). Raw data lands in results/.
    rows = []
    for series, values in curves.items():
        for step, value in enumerate(values):
            rows.append({"step": step, "value": value, "method": series})
    df = pd.DataFrame(rows)

    out = run.save_dataframe("metrics.csv", df)
    print(f"[toy] wrote {len(df)} rows -> {out}")


if __name__ == "__main__":
    main()
