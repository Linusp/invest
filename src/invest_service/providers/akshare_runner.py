"""Run AkShare network calls out of process so they can be timed out safely."""

import contextlib
import json
import sys
from typing import Any

ALLOWED_FUNCTIONS = {
    "fund_etf_category_sina",
    "fund_etf_hist_sina",
    "fund_etf_spot_em",
    "stock_zh_index_daily",
    "stock_zh_index_daily_tx",
    "stock_zh_a_daily",
    "stock_zh_a_hist_tx",
}


def main() -> None:
    request: dict[str, Any] = json.load(sys.stdin)
    function_name = request.get("function")
    kwargs = request.get("kwargs")
    if function_name not in ALLOWED_FUNCTIONS or not isinstance(kwargs, dict):
        raise ValueError("unsupported AkShare call")

    import akshare

    function = getattr(akshare, function_name)
    with contextlib.redirect_stdout(sys.stderr):
        frame = function(**kwargs)
    sys.stdout.write(frame.to_json(orient="records", date_format="iso", force_ascii=False))


if __name__ == "__main__":
    main()
