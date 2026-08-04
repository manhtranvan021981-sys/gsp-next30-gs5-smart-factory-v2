#!/usr/bin/env python3
"""Fail the deployment if a generated GS5 data package is incomplete."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path


EXPECTED_COLS = [
    "date",
    "month",
    "week",
    "af_raw_code",
    "af_code",
    "af_status",
    "af_quality_flag",
    "af_conflict_codes",
    "segment_code",
    "segment_label",
    "segment",
    "af_conflict_ltt",
    "af_conflict_stat",
    "machine",
    "operator",
    "ltt",
    "stat",
    "mat_code",
    "mat_name",
    "process",
    "process_code",
    "line",
    "line_name",
    "unit",
    "shift",
    "qty",
    "ok",
    "ng",
    "ng_rate",
    "allow_qty",
    "allow_rate",
    "over_qty",
    "over_pos",
    "over_rate",
    "downtime",
    "prep_h",
    "nvl_h",
    "machine_h",
    "file_h",
    "reason",
    "capacity",
    "oee",
    "A",
    "P",
    "Q",
    "actual_prod",
    "achv_tech",
    "confidence",
    "flag_count",
    "flags",
    "rag",
    "ltt_req_qty",
    "ltt_allow_ng_qty",
    "converted_qty",
    "setup_std_h",
    "run_std_h",
    "total_std_h",
    "k_lot",
    "job_size_class",
    "oee_weight",
    "oee_lot_adjusted",
    "oee_weight_valid",
    "capa_time_std",
    "capa_actual",
    "capa_rate_std",
    "capa_rate_tech",
]

EXPECTED_SCHEMA = "gs5-static-shards-v4-af-quality-independent"
AF_ALIASES = {
    "SOB": "PHOI",
    "SOE": "PHOI",
    "SOA": "PHOI",
    "SBA": "PHOI",
    "SBC": "PHOI",
    "SBE": "PHOI",
    "SOC": "PHOI",
    "SOG": "PHOI",
    "SEE": "PHOI",
    "SEC": "PHOI",
    "DUP": "HBL",
}
MASTER_SEGMENTS = {
    "HOC": ("01_HOC", "01_Nhóm hàng Hộp cứng"),
    "HOT": ("02_HOT", "02_Nhóm hàng Hộp thường (hộp mềm)"),
    "HBD": ("03_HBD", "03_Nhóm hàng Hộp bồi duplex"),
    "HBL": ("04_HBL", "04_Nhóm hàng Hộp bồi label"),
    "FLC": ("05_FLC", "05_Nhóm hàng Hộp Flexo carton"),
    "FLP": ("06_FLP", "06_Nhóm hàng Hộp Flexo process"),
    "FPK": ("07_FPK", "07_Nhóm hàng PK phôi carton"),
    "SHD": ("08_SHD", "08_Nhóm hàng Sách hướng dẫn"),
    "PLL": ("09_PLL", "09_Nhóm hàng Pallet"),
    "PHOI": ("10_PHOI", "10_Nhóm hàng Phôi sóng"),
    "GCI": ("11_GCI", "11_Nhóm hàng Gia công in"),
    "KHA": ("12_KHA", "12_Nhóm hàng Khay giấy"),
    "TUI": ("13_TUI", "13_Nhóm hàng Túi giấy"),
    "NVLC": ("14_NVLC", "14_Nhóm Nguyên vật liệu chính"),
    "NVLP": ("15_NVLP", "15_Nhóm Nguyên vật liệu phụ"),
    "PTRO": ("16_PTRO", "16_Nhóm CCDC, VTB, VIT, VPP"),
    "KHC": ("17_KHC", "17_Nhóm hàng khác"),
    "LE": ("18_LE", "18_Nhóm Lề, phế"),
    "TCKT": ("19_TCKT", "19_Nhóm hàng thương mại"),
}
CONTROL_SEGMENTS = {
    "00": "00_Chưa khai báo dòng hàng mẹ",
    "98": "98_Xung đột AF theo LTT/phiếu",
    "99": "99_AF chưa ánh xạ",
}


def read_gzip_json(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("site/data"))
    parser.add_argument("--plant", default="GS5")
    args = parser.parse_args()
    manifest_path = args.data / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == EXPECTED_SCHEMA
    assert manifest["schema_version"] == 4
    assert manifest["plant"] == args.plant, (
        f"Sai nhà máy: manifest={manifest['plant']}, yêu cầu={args.plant}."
    )
    assert manifest["global"]["accepted_rows"] > 0
    assert manifest["scanned_rows"] == manifest["global"]["scanned_rows"]
    assert manifest["accepted_rows"] == manifest["global"]["accepted_rows"]
    assert manifest["scanned_rows"] >= manifest["accepted_rows"]
    assert manifest["source_size"] > 0
    assert len(manifest["source_sha256"]) == 64
    assert manifest["source"]["sha256"] == manifest["source_sha256"]
    assert manifest["af_aliases"] == AF_ALIASES
    assert manifest["periods"], "Không có phân vùng tháng."
    dated = [item["value"] for item in manifest["periods"] if item["value"] != "Không tháng"]
    expected_latest = dated[-1] if dated else "Không tháng"
    assert manifest["latest_detected_period"] == expected_latest
    assert manifest["latest_period"] == expected_latest
    assert len(manifest["af_master"]) == 19
    assert [item["code"] for item in manifest["af_master"]] == list(MASTER_SEGMENTS)
    assert [item["segment_code"] for item in manifest["af_control_groups"]] == [
        "00",
        "98",
        "99",
    ]
    total = 0
    observed_counts: dict[str, int] = {}
    for period in manifest["periods"]:
        payload = read_gzip_json(args.data / period["file"])
        assert payload["cols"] == EXPECTED_COLS
        assert len(payload["rows"]) == period["rows"]
        assert payload["meta"]["rows"] == period["rows"]
        assert period["rows"] <= 100_000, (
            f"Phân vùng {period['value']} có {period['rows']} dòng; "
            "quá ngưỡng an toàn trình duyệt."
        )
        assert all(len(row) == len(EXPECTED_COLS) for row in payload["rows"])
        for raw in payload["rows"]:
            row = dict(zip(EXPECTED_COLS, raw))
            af_code = str(row["af_code"] or "")
            af_raw_code = str(row["af_raw_code"] or "")
            segment_code = str(row["segment_code"] or "")
            segment_label = str(row["segment_label"] or "")
            assert row["segment"] == segment_label
            observed_counts[segment_code] = observed_counts.get(segment_code, 0) + 1
            if segment_code in CONTROL_SEGMENTS:
                assert segment_label == CONTROL_SEGMENTS[segment_code]
                if segment_code == "00":
                    assert af_code == ""
                    assert af_raw_code == ""
                    assert row["af_status"] == "AF trống"
                elif segment_code == "98":
                    raise AssertionError(
                        "98 chỉ được dùng làm bộ lọc chất lượng, không được ghi đè mảng KPI."
                    )
                else:
                    assert af_code and af_code not in MASTER_SEGMENTS
                    assert af_raw_code not in AF_ALIASES
                    assert row["af_status"] == "AF ngoài danh mục"
            else:
                assert af_code in MASTER_SEGMENTS
                assert AF_ALIASES.get(af_raw_code, af_raw_code) == af_code
                expected_code, expected_label = MASTER_SEGMENTS[af_code]
                assert segment_code == expected_code
                assert segment_label == expected_label
                expected_status = (
                    "Hợp lệ qua ánh xạ" if af_raw_code in AF_ALIASES else "Hợp lệ"
                )
                assert row["af_status"] == expected_status
                if row["af_conflict_ltt"] or row["af_conflict_stat"]:
                    codes = {
                        item.strip()
                        for item in str(row["af_conflict_codes"]).split("|")
                        if item.strip()
                    }
                    assert len(codes) >= 2
                    assert codes <= set(MASTER_SEGMENTS)
                    assert str(row["af_quality_flag"]).startswith("Xung đột thật")
                else:
                    assert row["af_conflict_codes"] == ""
        total += period["rows"]
    assert total == manifest["global"]["accepted_rows"]
    assert observed_counts == manifest["global"]["af_quality"]["segment_counts"]
    assert sum(observed_counts.values()) == total
    assert "GS5 khác" not in {
        item["label"] for item in manifest["af_master"] + manifest["af_control_groups"]
    }
    schedule = read_gzip_json(args.data / manifest["schedule"]["file"])
    assert schedule["meta"]["plant"] == args.plant
    assert len(schedule["rows"]) == manifest["schedule"]["rows"]
    for row in schedule["rows"]:
        assert row["seg"] == row["segment_label"]
        assert row["segment_code"] in {
            *CONTROL_SEGMENTS,
            *(value[0] for value in MASTER_SEGMENTS.values()),
        }
        assert row["segment_code"] != "98"
    print(
        f"VERIFY OK: {total:,} dòng, {len(manifest['periods'])} phân vùng, "
        f"{len(schedule['rows']):,} dòng lịch hiện hành."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
