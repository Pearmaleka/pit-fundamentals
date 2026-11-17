"""Build <root>/pit/facts/<quarter>.parquet from <root>/parquet/{sub,num}.

python scripts/build_store.py <quant-lab root> [seconds]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pitfund import store  # noqa: E402

if __name__ == "__main__":
    root = Path(sys.argv[1])
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else float("inf")
    con = store.connect(temp_dir=str(root / "tmp_duckdb"))
    done = store.build_facts(root / "parquet", root / "pit", con, budget_s=budget)
    print(f"built {len(done)} quarters", done[:1], done[-1:])
