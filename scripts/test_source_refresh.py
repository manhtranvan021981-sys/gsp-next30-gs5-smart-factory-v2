#!/usr/bin/env python3
"""Contract tests for content-hash refresh and workflow rebuild behavior."""

from __future__ import annotations

import tempfile
from pathlib import Path

from process_excel import local_source_meta


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="gs5-source-contract-") as folder:
        first = Path(folder) / "first.xlsx"
        second = Path(folder) / "second.xlsx"
        first.write_bytes(b"PK\x03\x04same-size-A")
        second.write_bytes(b"PK\x03\x04same-size-B")
        meta_a = local_source_meta(first, "GS5-FILE-ID")
        meta_b = local_source_meta(second, "GS5-FILE-ID")
        assert meta_a["size"] == meta_b["size"]
        assert meta_a["source_sha256"] != meta_b["source_sha256"]
        assert meta_a["signature"] != meta_b["signature"]
        assert len(meta_a["source_sha256"]) == 64

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "update-dashboard.yml"
    ).read_text(encoding="utf-8")
    required = (
        "push:",
        "--download-to .source/P3_Tong_Hop_LTT_GS5.xlsx",
        "gs5-v3-content-sha256-",
        "github.event_name == 'workflow_dispatch'",
        "--input .source/P3_Tong_Hop_LTT_GS5.xlsx",
    )
    for marker in required:
        assert marker in workflow, f"Workflow thiếu điều kiện: {marker}"

    print("SOURCE REFRESH CONTRACT OK: content SHA-256 và rebuild thủ công đều đạt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
