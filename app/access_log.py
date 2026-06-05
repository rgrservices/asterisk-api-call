from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger("call_api.access")


def setup_access_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.handlers.clear()
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def write_access_record(**fields: Any) -> None:
    row = {"ts": datetime.now(UTC).isoformat(), **fields}
    _logger.info(json.dumps(row, ensure_ascii=False))
