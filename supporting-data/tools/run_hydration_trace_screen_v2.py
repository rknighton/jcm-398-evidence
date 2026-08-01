"""Run the established screen with per-call hydration-path telemetry."""

from pathlib import Path

import bench_generation_safe_hybrid_e2e as benchmark


HERE = Path(__file__).resolve().parent
benchmark.RAW_CSV = (
    HERE.parent / "source-runs" / "generation_safe_hybrid_hydration_trace_screen_v2.csv"
)
benchmark.PARITY_FAILURE = (
    HERE.parent / "logs" / "generation_safe_hybrid_hydration_trace_screen_v2_failure.json"
)


if __name__ == "__main__":
    benchmark.main()
