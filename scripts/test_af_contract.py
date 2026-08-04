#!/usr/bin/env python3
"""Contract tests for GS5 AF-only segmentation."""

from __future__ import annotations

from process_excel import (
    AF_ALIASES,
    AF_BY_CODE,
    AF_CONTROL_BY_CODE,
    AF_MASTER,
    PROCESSED_COLS,
    classify_af,
    canonical_af,
    normalize_af,
    process_raw_row,
)


def raw_row(
    *,
    af: str = "",
    ltt: str = "LTT-01",
    stat: str = "TK-01",
    machine: str = "MÁY-01",
    process: str = "",
) -> list[object]:
    raw: list[object] = [""] * 100
    raw[2] = ltt
    raw[4] = "GS5"
    raw[5] = "VT-01"
    raw[6] = "Vật tư kiểm thử"
    raw[27] = machine
    raw[28] = process
    raw[31] = af
    raw[43] = "2026-07-27"
    raw[45] = stat
    raw[58] = 100
    raw[59] = 99
    raw[60] = 1
    raw[85] = 1
    return raw


def main() -> int:
    assert len(AF_MASTER) == 19
    assert len(AF_BY_CODE) == 19
    assert normalize_af("  flc \n") == "FLC"
    assert canonical_af(" sob ") == "PHOI"
    assert canonical_af(" dup ") == "HBL"

    flc = raw_row(af=" flc ")
    result = classify_af(flc)
    assert result["af_code"] == "FLC"
    assert result["segment_code"] == "05_FLC"
    assert result["segment_label"] == "05_Nhóm hàng Hộp Flexo carton"
    assert result["af_status"] == "Hợp lệ"

    no_machine_inference = raw_row(
        af="HOC", machine="YRK FLEXO", process="INFLEXOCUON"
    )
    result = classify_af(no_machine_inference)
    assert result["segment_code"] == "01_HOC"
    assert result["segment_label"] == "01_Nhóm hàng Hộp cứng"

    phoi_alias = raw_row(af="SOB", process="KHAY")
    result = classify_af(phoi_alias)
    assert result["af_raw_code"] == "SOB"
    assert result["af_code"] == "PHOI"
    assert result["segment_code"] == "10_PHOI"
    assert result["af_status"] == "Hợp lệ qua ánh xạ"

    hbl_alias = raw_row(af="DUP")
    result = classify_af(hbl_alias)
    assert result["af_raw_code"] == "DUP"
    assert result["af_code"] == "HBL"
    assert result["segment_code"] == "04_HBL"

    for alias, canonical in AF_ALIASES.items():
        result = classify_af(raw_row(af=f" {alias.lower()} "))
        assert result["af_raw_code"] == alias
        assert result["af_code"] == canonical
        assert result["segment_code"] == AF_BY_CODE[canonical]["segment_code"]
    assert len({canonical_af("SOB"), canonical_af("SOE"), canonical_af("PHOI")}) == 1
    assert len({canonical_af("DUP"), canonical_af("HBL")}) == 1
    assert len({canonical_af("SOB"), canonical_af("DUP")}) == 2

    blank = raw_row(af="")
    result = classify_af(blank)
    assert result["segment_code"] == "00"
    assert result["af_status"] == "AF trống"

    ltt_conflict = raw_row(af="FLC", ltt="LTT-X")
    result = classify_af(ltt_conflict, {"LTT-X"}, set())
    assert result["segment_code"] == "98"
    assert result["af_conflict_ltt"] is True
    assert result["af_conflict_stat"] is False

    stat_conflict = raw_row(af="HOC", stat="TK-X")
    result = classify_af(stat_conflict, set(), {"TK-X"})
    assert result["segment_code"] == "98"
    assert result["af_status"] == "Xung đột phiếu"

    processed = process_raw_row(stat_conflict, result)
    obj = dict(zip(PROCESSED_COLS, processed))
    assert obj["segment"] == obj["segment_label"]
    assert obj["confidence"] == "Đỏ"
    assert "AF xung đột" in obj["flags"]

    valid = process_raw_row(flc, classify_af(flc))
    valid_obj = dict(zip(PROCESSED_COLS, valid))
    assert valid_obj["af_raw_code"] == "FLC"
    assert valid_obj["af_code"] == "FLC"
    assert valid_obj["af_status"] == "Hợp lệ"
    assert valid_obj["af_conflict_ltt"] is False
    assert valid_obj["af_conflict_stat"] is False

    print(
        "AF CONTRACT OK: 19 mã chuẩn, 11 alias, 00/98/99 "
        "và no-inference đều đạt."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
