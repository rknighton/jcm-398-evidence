"""Run the expanded direct-read surface with hydration-path telemetry."""

from pathlib import Path

import bench_generation_safe_hybrid_expanded_surface as benchmark


HERE = Path(__file__).resolve().parent
benchmark.RAW_CSV = (
    HERE.parent / "source-runs" / "generation_safe_hybrid_hydration_trace_expanded_v2.csv"
)
benchmark.FAILURE = (
    HERE.parent / "logs" / "generation_safe_hybrid_hydration_trace_expanded_v2_failure.json"
)


if __name__ == "__main__":
    benchmark.main()
