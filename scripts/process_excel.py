#!/usr/bin/env python3
"""Build browser-safe GS5 dashboard shards from the large ERP XLSX file.

The workbook is read in streaming mode. Processed rows are written to monthly
JSONL files first, then packed as deterministic gzip JSON payloads. This keeps
both the GitHub Actions runner and the browser away from a 1 GB uncompressed XML
document and a 280k-row in-memory JavaScript array.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

FILE_ID = "1ZCe-HgzUxoWV91JdsjSEF16rN5cn0W0e"
FILE_NAME = "P3_Tong_Hop_LTT_2507.xlsx"
SHEET_NAME = "P3.Tổng hợp lệnh thao tác"
SOURCE_RANGE = "A9:CT"
PLANT_CODE = "GS5"
SOURCE_URL = (
    "https://drive.usercontent.google.com/download"
    f"?id={FILE_ID}&export=download&confirm=t"
)
SCHEMA_VERSION = "gs5-static-shards-v3-af-alias-sha256"
MAX_COLUMNS = 98  # A:CT, zero-based indices 0..97.

AF_MASTER: tuple[tuple[str, str, str], ...] = (
    ("01", "HOC", "01_Nhóm hàng Hộp cứng"),
    ("02", "HOT", "02_Nhóm hàng Hộp thường (hộp mềm)"),
    ("03", "HBD", "03_Nhóm hàng Hộp bồi duplex"),
    ("04", "HBL", "04_Nhóm hàng Hộp bồi label"),
    ("05", "FLC", "05_Nhóm hàng Hộp Flexo carton"),
    ("06", "FLP", "06_Nhóm hàng Hộp Flexo process"),
    ("07", "FPK", "07_Nhóm hàng PK phôi carton"),
    ("08", "SHD", "08_Nhóm hàng Sách hướng dẫn"),
    ("09", "PLL", "09_Nhóm hàng Pallet"),
    ("10", "PHOI", "10_Nhóm hàng Phôi sóng"),
    ("11", "GCI", "11_Nhóm hàng Gia công in"),
    ("12", "KHA", "12_Nhóm hàng Khay giấy"),
    ("13", "TUI", "13_Nhóm hàng Túi giấy"),
    ("14", "NVLC", "14_Nhóm Nguyên vật liệu chính"),
    ("15", "NVLP", "15_Nhóm Nguyên vật liệu phụ"),
    ("16", "PTRO", "16_Nhóm CCDC, VTB, VIT, VPP"),
    ("17", "KHC", "17_Nhóm hàng khác"),
    ("18", "LE", "18_Nhóm Lề, phế"),
    ("19", "TCKT", "19_Nhóm hàng thương mại"),
)
AF_BY_CODE = {
    code: {"sort": sort, "code": code, "segment_code": f"{sort}_{code}", "label": label}
    for sort, code, label in AF_MASTER
}
AF_ALIASES: dict[str, str] = {
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
AF_CONTROL_GROUPS: tuple[dict[str, str], ...] = (
    {
        "sort": "00",
        "code": "00",
        "segment_code": "00",
        "label": "00_Chưa khai báo dòng hàng mẹ",
    },
    {
        "sort": "98",
        "code": "98",
        "segment_code": "98",
        "label": "98_Xung đột AF theo LTT/phiếu",
    },
    {
        "sort": "99",
        "code": "99",
        "segment_code": "99",
        "label": "99_AF chưa ánh xạ",
    },
)
AF_CONTROL_BY_CODE = {item["code"]: item for item in AF_CONTROL_GROUPS}

PROCESSED_COLS = [
    "date",
    "month",
    "week",
    "af_raw_code",
    "af_code",
    "af_status",
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


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def finite(value: float) -> float:
    return value if math.isfinite(value) else 0.0


def to_num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return finite(float(value))
    text = str(value).strip()
    if not text:
        return 0.0
    is_percent = "%" in text
    text = text.replace("%", "").replace(" ", "").replace("\u00a0", "")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    has_comma = "," in text
    has_dot = "." in text
    if has_comma and has_dot:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        parts = text.split(",")
        if len(parts) > 2:
            text = text.replace(",", "")
        elif len(parts) == 2 and len(parts[1]) == 3 and parts[0] != "0":
            text = "".join(parts)
        else:
            text = text.replace(",", ".")
    elif has_dot:
        parts = text.split(".")
        if len(parts) > 2:
            text = text.replace(".", "")
        elif len(parts) == 2 and len(parts[1]) == 3 and parts[0] != "0":
            text = "".join(parts)
    text = re.sub(r"[^0-9.\-]", "", text)
    try:
        result = float(text)
    except (TypeError, ValueError):
        return 0.0
    if negative:
        result = -result
    if is_percent:
        result /= 100.0
    return finite(result)


def excel_serial_datetime(value: float) -> datetime | None:
    if not math.isfinite(value) or value <= 0:
        return None
    try:
        return datetime(1899, 12, 30, tzinfo=timezone.utc) + timedelta(days=value)
    except (OverflowError, ValueError):
        return None


def parse_datetime_value(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        number = float(value)
        if 20000 < number < 80000:
            return excel_serial_datetime(number)
    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        number = float(text)
        if 20000 < number < 80000:
            return excel_serial_datetime(number)
    match = re.search(
        r"(?:new\s+)?Date\s*\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})"
        r"(?:\s*,\s*(\d{1,2}))?(?:\s*,\s*(\d{1,2}))?(?:\s*,\s*(\d{1,2}))?",
        text,
        re.I,
    )
    if match:
        year, month0, day, hour, minute, second = [
            int(item or 0) for item in match.groups()
        ]
        try:
            return datetime(
                year, month0 + 1, day, hour, minute, second, tzinfo=timezone.utc
            )
        except ValueError:
            return None
    candidates = (
        ("%Y-%m-%dT%H:%M:%S", text[:19]),
        ("%Y-%m-%d %H:%M:%S", text[:19]),
        ("%Y-%m-%d", text[:10]),
        ("%d/%m/%Y %H:%M:%S", text[:19]),
        ("%d/%m/%Y", text[:10]),
        ("%d-%m-%Y", text[:10]),
    )
    for fmt, candidate in candidates:
        try:
            return datetime.strptime(candidate, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def iso_date(value: datetime | None) -> str:
    return value.date().isoformat() if value else ""


def month_key(value: datetime | None) -> str:
    return value.strftime("%Y-%m") if value else "Không tháng"


def week_key(value: datetime | None) -> str:
    if not value:
        return "Không tuần"
    iso = value.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def raw_at(raw: list[Any], index: int) -> Any:
    return raw[index] if index < len(raw) else ""


def normalize_af(value: Any) -> str:
    return clean_text(value).upper()


def canonical_af(value: Any) -> str:
    normalized = normalize_af(value)
    return AF_ALIASES.get(normalized, normalized)


def classify_af(
    raw: list[Any],
    ltt_conflicts: set[str] | None = None,
    stat_conflicts: set[str] | None = None,
) -> dict[str, Any]:
    ltt = clean_text(raw_at(raw, 2))
    stat = clean_text(raw_at(raw, 45))
    af_raw_code = normalize_af(raw_at(raw, 31))
    af_code = canonical_af(af_raw_code)
    conflict_ltt = bool(ltt and ltt_conflicts and ltt in ltt_conflicts)
    conflict_stat = bool(stat and stat_conflicts and stat in stat_conflicts)

    if conflict_ltt or conflict_stat:
        item = AF_CONTROL_BY_CODE["98"]
        if conflict_ltt and conflict_stat:
            status = "Xung đột LTT và phiếu"
        elif conflict_ltt:
            status = "Xung đột LTT"
        else:
            status = "Xung đột phiếu"
    elif not af_code:
        item = AF_CONTROL_BY_CODE["00"]
        status = "AF trống"
    elif af_code not in AF_BY_CODE:
        item = AF_CONTROL_BY_CODE["99"]
        status = "AF ngoài danh mục"
    else:
        item = AF_BY_CODE[af_code]
        status = "Hợp lệ qua ánh xạ" if af_raw_code in AF_ALIASES else "Hợp lệ"

    return {
        "af_raw_code": af_raw_code,
        "af_code": af_code,
        "af_status": status,
        "segment_code": item["segment_code"],
        "segment_label": item["label"],
        "segment": item["label"],
        "af_conflict_ltt": conflict_ltt,
        "af_conflict_stat": conflict_stat,
    }


def rag_for(obj: dict[str, Any]) -> str:
    threshold = max(0.08, to_num(obj["allow_rate"]) * 2 + 0.02)
    if (
        to_num(obj["over_pos"]) > 1000
        or to_num(obj["downtime"]) > 4
        or to_num(obj["ng_rate"]) > threshold
        or obj["confidence"] == "Đỏ"
    ):
        return "Đỏ"
    if (
        to_num(obj["over_pos"]) > 0
        or to_num(obj["downtime"]) > 0
        or obj["confidence"] == "Vàng"
    ):
        return "Vàng"
    return "Xanh"


def process_raw_row(raw: list[Any], af_contract: dict[str, Any]) -> list[Any]:
    while len(raw) < 100:
        raw.append("")
    stat_date = parse_datetime_value(raw[43])  # AR
    ltt_req_qty = to_num(raw[18])  # S
    ltt_allow_ng_qty = to_num(raw[20])  # U
    ltt_plan_h = to_num(raw[25])  # Z
    qty = to_num(raw[58])  # BG
    ok_qty = to_num(raw[59])  # BH
    ng_raw = to_num(raw[60])  # BI
    ng_qty = ng_raw if ng_raw != 0 else max(qty - ok_qty, 0)
    ng_rate_raw = to_num(raw[61])
    ng_rate = ng_rate_raw if ng_rate_raw != 0 else (ng_qty / qty if qty else 0)
    allow_qty = to_num(raw[85])  # CH
    allow_rate_raw = to_num(raw[86])  # CI
    allow_rate = (
        allow_rate_raw if allow_rate_raw != 0 else (allow_qty / qty if qty else 0)
    )
    over_raw = to_num(raw[93])  # CP
    over_qty = ng_qty - allow_qty if raw[93] in (None, "") else over_raw
    over_pos = max(over_qty, 0)
    over_rate_raw = to_num(raw[92])  # CO
    over_rate = (
        over_rate_raw if over_rate_raw != 0 else (over_qty / qty if qty else 0)
    )
    prep_h = to_num(raw[73]) / 60
    nvl_h = to_num(raw[74]) / 60
    machine_h = to_num(raw[75]) / 60
    file_h = to_num(raw[76]) / 60
    downtime_raw = to_num(raw[77])
    downtime = (
        downtime_raw
        if downtime_raw != 0
        else prep_h + nvl_h + machine_h + file_h
    )
    capacity = to_num(raw[79])  # CB
    converted_qty = to_num(raw[81])  # CD
    setup_std_h = (to_num(raw[82]) + to_num(raw[83])) / 60
    run_std_h = converted_qty / capacity if capacity > 0 and converted_qty > 0 else 0
    total_std_source = to_num(raw[87])  # CJ
    total_std_h = total_std_source if total_std_source > 0 else setup_std_h + run_std_h
    k_lot_raw = run_std_h / total_std_h if total_std_h > 0 and run_std_h > 0 else 0
    k_lot = max(0, min(1, k_lot_raw))
    if k_lot >= 0.75:
        job_size_class = "Job dài"
    elif k_lot >= 0.45:
        job_size_class = "Job trung bình"
    elif k_lot > 0:
        job_size_class = "Job ngắn"
    else:
        job_size_class = "Thiếu dữ liệu"
    availability = to_num(raw[88])
    performance = to_num(raw[89])
    quality = to_num(raw[90])
    oee_raw = to_num(raw[91])
    oee = (
        oee_raw
        if oee_raw != 0
        else (
            availability * performance * quality
            if availability and performance and quality
            else 0
        )
    )
    oee_weight_valid = 0 < oee <= 1.2 and total_std_h > 0
    oee_weight = oee * total_std_h if oee_weight_valid else 0
    oee_lot_adjusted = min(oee / k_lot, 1) if oee > 0 and k_lot > 0 else 0
    capa_time_source = to_num(raw[94])  # CQ
    if capa_time_source != 0:
        capa_time_std = capa_time_source
    elif ltt_req_qty > 0 and ltt_plan_h > 0:
        capa_time_std = ltt_req_qty / ltt_plan_h
    else:
        capa_time_std = capacity
    capa_actual = to_num(raw[95])  # CR
    capa_rate_source = to_num(raw[96])  # CS
    if capa_rate_source != 0:
        capa_rate_std = capa_rate_source
    elif capa_actual > 0 and capa_time_std > 0:
        capa_rate_std = capa_actual / capa_time_std
    elif capa_actual > 0 and capacity > 0:
        capa_rate_std = capa_actual / capacity
    else:
        capa_rate_std = 0
    capa_rate_tech = to_num(raw[97])  # CT

    start = parse_datetime_value(raw[55])
    finish = parse_datetime_value(raw[56])
    flags: list[str] = []
    if downtime > 0 and not clean_text(raw[78]):
        flags.append("Downtime thiếu nguyên nhân")
    if start and finish and finish < start:
        flags.append("Thiếu/sai thời gian thống kê")
    if start and not 2025 <= start.year <= 2027:
        flags.append("TG bắt đầu TK năm bất thường")
    if finish and not 2025 <= finish.year <= 2027:
        flags.append("TG kết thúc TK năm bất thường")
    if (
        availability < 0
        or performance < 0
        or quality < 0
        or oee < 0
        or availability > 1.2
        or performance > 1.2
        or quality > 1.05
        or oee > 1.2
        or (0 < oee < 0.05)
    ):
        flags.append("OEE/A/P/Q bất thường")
    if af_contract["af_conflict_ltt"] or af_contract["af_conflict_stat"]:
        flags.append("AF xung đột theo LTT/phiếu")
    elif af_contract["segment_code"] == "00":
        flags.append("AF trống")
    elif af_contract["segment_code"] == "99":
        flags.append("AF chưa ánh xạ")
    confidence = "Xanh"
    if (
        af_contract["af_conflict_ltt"]
        or af_contract["af_conflict_stat"]
        or any("Downtime thiếu" in item or "năm bất thường" in item for item in flags)
    ):
        confidence = "Đỏ"
    elif flags:
        confidence = "Vàng"

    obj: dict[str, Any] = {
        "date": iso_date(stat_date),
        "month": month_key(stat_date),
        "week": week_key(stat_date),
        **af_contract,
        "machine": clean_text(raw[47] or raw[27]) or "Chưa có",
        "operator": clean_text(raw[49]) or "Chưa có",
        "ltt": clean_text(raw[2]),
        "stat": clean_text(raw[45]),
        "mat_code": clean_text(raw[5]),
        "mat_name": clean_text(raw[6]),
        "process": clean_text(raw[29]),
        "process_code": clean_text(raw[28]),
        "line": clean_text(raw[32]),
        "line_name": clean_text(raw[33]),
        "unit": clean_text(raw[62] or raw[7]),
        "shift": clean_text(raw[54] or raw[22]),
        "qty": qty,
        "ok": ok_qty,
        "ng": ng_qty,
        "ng_rate": ng_rate,
        "allow_qty": allow_qty,
        "allow_rate": allow_rate,
        "over_qty": over_qty,
        "over_pos": over_pos,
        "over_rate": over_rate,
        "downtime": downtime,
        "prep_h": prep_h,
        "nvl_h": nvl_h,
        "machine_h": machine_h,
        "file_h": file_h,
        "reason": clean_text(raw[78]) or "Chưa có",
        "capacity": capacity,
        "oee": oee,
        "A": availability,
        "P": performance,
        "Q": quality,
        "actual_prod": capa_actual,
        "achv_tech": capa_rate_tech,
        "confidence": confidence,
        "flag_count": len(flags),
        "flags": "; ".join(flags),
        "ltt_req_qty": ltt_req_qty,
        "ltt_allow_ng_qty": ltt_allow_ng_qty,
        "converted_qty": converted_qty,
        "setup_std_h": setup_std_h,
        "run_std_h": run_std_h,
        "total_std_h": total_std_h,
        "k_lot": k_lot,
        "job_size_class": job_size_class,
        "oee_weight": oee_weight,
        "oee_lot_adjusted": oee_lot_adjusted,
        "oee_weight_valid": oee_weight_valid,
        "capa_time_std": capa_time_std,
        "capa_actual": capa_actual,
        "capa_rate_std": capa_rate_std,
        "capa_rate_tech": capa_rate_tech,
    }
    obj["rag"] = rag_for(obj)
    return [obj[column] for column in PROCESSED_COLS]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def column_index(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference or "")
    if not match:
        return -1
    result = 0
    for char in match.group(1):
        result = result * 26 + ord(char) - 64
    return result - 1


def shared_text(element: ET.Element) -> str:
    return "".join(
        child.text or "" for child in element.iter() if local_name(child.tag) == "t"
    )


def read_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in workbook.namelist():
        return []
    strings: list[str] = []
    with workbook.open(path) as stream:
        for event, element in ET.iterparse(stream, events=("end",)):
            if local_name(element.tag) == "si":
                strings.append(shared_text(element))
                element.clear()
    return strings


def resolve_sheet_path(workbook: zipfile.ZipFile, wanted_name: str) -> str:
    namespaces = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    workbook_xml = ET.fromstring(workbook.read("xl/workbook.xml"))
    relation_id = ""
    for sheet in workbook_xml.findall(".//main:sheet", namespaces):
        if sheet.attrib.get("name") == wanted_name:
            relation_id = sheet.attrib.get(f"{{{namespaces['rel']}}}id", "")
            break
    if not relation_id:
        available = [
            sheet.attrib.get("name", "")
            for sheet in workbook_xml.findall(".//main:sheet", namespaces)
        ]
        raise RuntimeError(
            f"Không tìm thấy sheet {wanted_name!r}. Có các sheet: {available}"
        )
    rels_xml = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    for relation in rels_xml.findall("pkg:Relationship", namespaces):
        if relation.attrib.get("Id") == relation_id:
            target = relation.attrib.get("Target", "")
            if target.startswith("/"):
                return target.lstrip("/")
            return str(Path("xl") / target).replace("\\", "/")
    raise RuntimeError(f"Không tìm thấy quan hệ XML cho sheet {wanted_name!r}.")


def cell_value(cell: ET.Element, shared_strings: list[str]) -> Any:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return shared_text(cell)
    value: str | None = None
    for child in cell:
        if local_name(child.tag) == "v":
            value = child.text or ""
            break
    if value is None:
        return ""
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        return value == "1"
    if cell_type in ("", "n"):
        try:
            number = float(value)
            return int(number) if number.is_integer() else number
        except ValueError:
            return value
    return value


def iter_sheet_rows(
    workbook: zipfile.ZipFile,
    sheet_path: str,
    shared_strings: list[str],
    max_columns: int,
) -> Iterable[tuple[int, list[Any]]]:
    with workbook.open(sheet_path) as stream:
        for event, element in ET.iterparse(stream, events=("end",)):
            if local_name(element.tag) != "row":
                continue
            row_number = int(element.attrib.get("r", "0") or 0)
            row: list[Any] = [""] * max_columns
            for cell in element:
                if local_name(cell.tag) != "c":
                    continue
                index = column_index(cell.attrib.get("r", ""))
                if 0 <= index < max_columns:
                    row[index] = cell_value(cell, shared_strings)
            yield row_number, row
            element.clear()


def analyze_af_conflicts(
    workbook: zipfile.ZipFile,
    sheet_path: str,
    shared_strings: list[str],
    plant_code: str,
) -> tuple[set[str], set[str]]:
    ltt_af: dict[str, set[str]] = defaultdict(set)
    stat_af: dict[str, set[str]] = defaultdict(set)
    inspected = 0
    for row_number, raw in iter_sheet_rows(
        workbook, sheet_path, shared_strings, MAX_COLUMNS
    ):
        if row_number <= 9:
            continue
        if clean_text(raw_at(raw, 4)) != plant_code:
            continue
        if not (
            clean_text(raw_at(raw, 2))
            or clean_text(raw_at(raw, 45))
            or clean_text(raw_at(raw, 5))
        ):
            continue
        inspected += 1
        af_code = canonical_af(raw_at(raw, 31)) or "__MISSING__"
        ltt = clean_text(raw_at(raw, 2))
        stat = clean_text(raw_at(raw, 45))
        if ltt:
            ltt_af[ltt].add(af_code)
        if stat:
            stat_af[stat].add(af_code)
    ltt_conflicts = {key for key, values in ltt_af.items() if len(values) > 1}
    stat_conflicts = {key for key, values in stat_af.items() if len(values) > 1}
    print(
        f"Kiểm tra AF: {inspected:,} dòng {plant_code}, "
        f"{len(ltt_conflicts):,} LTT xung đột, "
        f"{len(stat_conflicts):,} phiếu xung đột.",
        flush=True,
    )
    return ltt_conflicts, stat_conflicts


@dataclass
class ShardStats:
    key: str
    file_name: str
    rows: int = 0
    ltts: set[str] = field(default_factory=set)
    stats: set[str] = field(default_factory=set)
    machines: set[str] = field(default_factory=set)
    operators: set[str] = field(default_factory=set)
    date_min: str = ""
    date_max: str = ""
    ltt_required_qty: float = 0
    ltt_allow_ng_qty: float = 0
    actual_qty: float = 0
    ng: float = 0
    allow_qty: float = 0
    over_pos: float = 0
    downtime: float = 0
    oee_sum: float = 0
    oee_count: int = 0
    red: int = 0
    yellow: int = 0
    segment_counts: dict[str, int] = field(default_factory=dict)
    af_status_counts: dict[str, int] = field(default_factory=dict)

    def add(self, processed: list[Any]) -> None:
        row = dict(zip(PROCESSED_COLS, processed))
        self.rows += 1
        segment_code = str(row["segment_code"] or "")
        af_status = str(row["af_status"] or "")
        self.segment_counts[segment_code] = self.segment_counts.get(segment_code, 0) + 1
        self.af_status_counts[af_status] = self.af_status_counts.get(af_status, 0) + 1
        ltt = str(row["ltt"] or "")
        stat = str(row["stat"] or "")
        if ltt and ltt not in self.ltts:
            self.ltts.add(ltt)
            self.ltt_required_qty += to_num(row["ltt_req_qty"])
            self.ltt_allow_ng_qty += to_num(row["ltt_allow_ng_qty"])
        if stat and stat not in self.stats:
            self.stats.add(stat)
            self.actual_qty += to_num(row["qty"])
            self.ng += to_num(row["ng"])
            self.allow_qty += to_num(row["allow_qty"])
            self.over_pos += max(to_num(row["ng"]) - to_num(row["allow_qty"]), 0)
        if row["machine"]:
            self.machines.add(str(row["machine"]))
        if row["operator"]:
            self.operators.add(str(row["operator"]))
        self.downtime += to_num(row["downtime"])
        self.oee_sum += to_num(row["oee"])
        self.oee_count += 1
        if row["confidence"] == "Đỏ":
            self.red += 1
        if row["confidence"] == "Vàng":
            self.yellow += 1
        day = str(row["date"] or "")
        if day:
            if not self.date_min or day < self.date_min:
                self.date_min = day
            if not self.date_max or day > self.date_max:
                self.date_max = day

    def meta(self, source_label: str, generated: str) -> dict[str, Any]:
        return {
            "source": source_label,
            "generated": generated,
            "period": self.key,
            "rows": self.rows,
            "ltt": len(self.ltts),
            "stats": len(self.stats),
            "machines": len(self.machines),
            "operators": len(self.operators),
            "date_min": self.date_min,
            "date_max": self.date_max,
            "af_quality": {
                "segment_counts": dict(sorted(self.segment_counts.items())),
                "status_counts": dict(sorted(self.af_status_counts.items())),
            },
        }

    def exec_summary(self) -> dict[str, Any]:
        defect_rate = self.ng / self.actual_qty if self.actual_qty else 0
        allow_rate = (
            self.ltt_allow_ng_qty / self.ltt_required_qty
            if self.ltt_required_qty
            else 0
        )
        completion_rate = (
            self.actual_qty / self.ltt_required_qty if self.ltt_required_qty else 0
        )
        return {
            "month": self.key,
            "rows": self.rows,
            "ltt": len(self.ltts),
            "stats": len(self.stats),
            "machines": len(self.machines),
            "ops": len(self.operators),
            "ltt_required_qty": self.ltt_required_qty,
            "ltt_allow_ng_qty": self.ltt_allow_ng_qty,
            "actual_qty": self.actual_qty,
            "ng": self.ng,
            "allow_qty": self.allow_qty,
            "over_pos": self.over_pos,
            "dt": self.downtime,
            "oee": self.oee_sum / self.oee_count if self.oee_count else 0,
            "defect_rate": defect_rate,
            "allow_rate": allow_rate,
            "completion_rate": completion_rate,
            "red": self.red,
            "yellow": self.yellow,
        }


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def write_gzip_json(
    output_path: Path, prefix: str, jsonl_path: Path | None, suffix: str
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as zipped:
            zipped.write(prefix.encode("utf-8"))
            if jsonl_path and jsonl_path.exists():
                first = True
                with jsonl_path.open("rb") as source:
                    for line in source:
                        line = line.strip()
                        if not line:
                            continue
                        if not first:
                            zipped.write(b",")
                        zipped.write(line)
                        first = False
            zipped.write(suffix.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def source_signature(file_id: str, content_sha256: str) -> str:
    payload = f"{SCHEMA_VERSION}|{file_id}|{content_sha256}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def cache_busted_url(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}gs5_source_check={time.time_ns()}"


def probe_source(url: str, file_id: str, target: Path) -> dict[str, Any]:
    download_meta = download_source(cache_busted_url(url), target)
    digest = sha256_file(target)
    return {
        "signature": source_signature(file_id, digest),
        "source_sha256": digest,
        "size": target.stat().st_size,
        "modified": download_meta.get("modified", ""),
        "etag": download_meta.get("etag", ""),
        "resolved_url": download_meta.get("resolved_url", ""),
        "download_path": str(target),
    }


def download_source(
    url: str, target: Path, expected_size: int = 0
) -> dict[str, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "GS5-Dashboard/1.0"})
    with urlopen(request, timeout=300) as response:
        response_headers = {
            key.lower(): value for key, value in response.headers.items()
        }
        resolved_url = response.geturl()
        content_type = response.headers.get("content-type", "")
        with target.open("wb") as output:
            downloaded = 0
            last_report = 0
            while chunk := response.read(4 * 1024 * 1024):
                if not chunk:
                    continue
                output.write(chunk)
                downloaded += len(chunk)
                if downloaded - last_report >= 32 * 1024 * 1024:
                    print(
                        f"Đã tải {downloaded / 1024 / 1024:.1f} MB...",
                        flush=True,
                    )
                    last_report = downloaded
    if expected_size and target.stat().st_size != expected_size:
        raise RuntimeError(
            f"Dung lượng tải về {target.stat().st_size} khác metadata {expected_size}."
        )
    if target.read_bytes()[:2] != b"PK":
        raise RuntimeError(
            f"Nguồn tải về không phải XLSX/ZIP. Content-Type: {content_type}"
        )
    return {
        "modified": response_headers.get("last-modified", ""),
        "etag": response_headers.get("etag", ""),
        "resolved_url": resolved_url,
    }


def schedule_window() -> tuple[datetime, datetime]:
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    monday = today - timedelta(days=today.isoweekday() - 1)
    return monday, monday + timedelta(days=14)


def schedule_variant_overlaps(raw: list[Any], start: datetime, end: datetime) -> bool:
    begin = parse_datetime_value(raw_at(raw, 23))
    finish = parse_datetime_value(raw_at(raw, 24))
    return bool(begin and finish and finish >= begin and finish >= start and begin < end)


def safe_shard_name(key: str) -> str:
    return "period_undated.json.gz" if key == "Không tháng" else f"period_{key.replace('-', '_')}.json.gz"


def month_label(key: str) -> str:
    if key == "Không tháng":
        return "Thiếu ngày thống kê"
    year, month = key.split("-")
    return f"Tháng {month}/{year}"


def build_data(
    workbook_path: Path,
    out_dir: Path,
    plant_code: str,
    source_meta: dict[str, Any],
    sheet_name: str,
    file_name: str,
    file_id: str,
) -> dict[str, Any]:
    started = time.monotonic()
    generated_dt = datetime.now(ZoneInfo("Asia/Bangkok"))
    generated = generated_dt.strftime("%H:%M:%S %d/%m/%Y")
    generated_iso = generated_dt.isoformat(timespec="seconds")
    source_label = f"Excel Drive near-live · {file_name} · {plant_code}"

    if out_dir.exists():
        for pattern in ("*.json.gz", "manifest.json"):
            for path in out_dir.glob(pattern):
                path.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    temp_root = Path(tempfile.mkdtemp(prefix="gs5-xlsx-jsonl-"))
    handles: dict[str, Any] = {}
    shard_stats: dict[str, ShardStats] = {}
    scanned = 0
    accepted = 0
    plant_counts: dict[str, int] = defaultdict(int)
    global_ltts: set[str] = set()
    global_stats: set[str] = set()
    global_machines: set[str] = set()
    global_operators: set[str] = set()
    global_date_min = ""
    global_date_max = ""
    global_segment_counts: dict[str, int] = defaultdict(int)
    global_af_counts: dict[str, int] = defaultdict(int)
    global_af_raw_counts: dict[str, int] = defaultdict(int)
    global_af_status_counts: dict[str, int] = defaultdict(int)
    global_af_conflict_rows = 0

    actual_by_ltt: dict[str, float] = defaultdict(float)
    plan_by_ltt: dict[str, float] = {}
    plan_conflict: set[str] = set()
    schedule_candidates: dict[str, dict[str, Any]] = {}
    schedule_start, schedule_end = schedule_window()

    try:
        with zipfile.ZipFile(workbook_path) as workbook:
            shared_strings = read_shared_strings(workbook)
            print(f"Shared strings: {len(shared_strings):,}", flush=True)
            sheet_path = resolve_sheet_path(workbook, sheet_name)
            print(f"Sheet XML: {sheet_path}", flush=True)
            ltt_af_conflicts, stat_af_conflicts = analyze_af_conflicts(
                workbook, sheet_path, shared_strings, plant_code
            )
            header_ok = False
            for row_number, raw in iter_sheet_rows(
                workbook, sheet_path, shared_strings, MAX_COLUMNS
            ):
                if row_number < 9:
                    continue
                if row_number == 9:
                    header = " | ".join(clean_text(item) for item in raw)
                    header_ok = (
                        "Lệnh công đoạn" in header and "Số thống kê" in header
                    )
                    if not header_ok:
                        raise RuntimeError(
                            "Không nhận diện được header dòng 9: thiếu "
                            "'Lệnh công đoạn' hoặc 'Số thống kê'."
                        )
                    continue
                scanned += 1
                plant = clean_text(raw_at(raw, 4)) or "(trống)"
                plant_counts[plant] += 1
                if plant != plant_code:
                    continue
                if not (
                    clean_text(raw_at(raw, 2))
                    or clean_text(raw_at(raw, 45))
                    or clean_text(raw_at(raw, 5))
                ):
                    continue

                accepted += 1
                af_contract = classify_af(raw, ltt_af_conflicts, stat_af_conflicts)
                processed = process_raw_row(raw, af_contract)
                processed_obj = dict(zip(PROCESSED_COLS, processed))
                global_segment_counts[str(processed_obj["segment_code"])] += 1
                global_af_counts[str(processed_obj["af_code"] or "(trống)")] += 1
                global_af_raw_counts[
                    str(processed_obj["af_raw_code"] or "(trống)")
                ] += 1
                global_af_status_counts[str(processed_obj["af_status"])] += 1
                if (
                    processed_obj["af_conflict_ltt"]
                    or processed_obj["af_conflict_stat"]
                ):
                    global_af_conflict_rows += 1
                key = str(processed_obj["month"])
                if key not in handles:
                    jsonl_path = temp_root / f"{len(handles):02d}.jsonl"
                    handles[key] = jsonl_path.open("wb")
                    shard_stats[key] = ShardStats(
                        key=key, file_name=safe_shard_name(key)
                    )
                handles[key].write(compact_json(processed).encode("utf-8") + b"\n")
                shard_stats[key].add(processed)

                ltt = str(processed_obj["ltt"] or "")
                stat = str(processed_obj["stat"] or "")
                machine = str(processed_obj["machine"] or "")
                operator = str(processed_obj["operator"] or "")
                day = str(processed_obj["date"] or "")
                if ltt:
                    global_ltts.add(ltt)
                    actual_by_ltt[ltt] += to_num(raw_at(raw, 58))
                    plan = to_num(raw_at(raw, 18))
                    if plan > 0:
                        if ltt in plan_by_ltt and plan_by_ltt[ltt] != plan:
                            plan_conflict.add(ltt)
                        else:
                            plan_by_ltt.setdefault(ltt, plan)
                if stat:
                    global_stats.add(stat)
                if machine:
                    global_machines.add(machine)
                if operator:
                    global_operators.add(operator)
                if day:
                    if not global_date_min or day < global_date_min:
                        global_date_min = day
                    if not global_date_max or day > global_date_max:
                        global_date_max = day

                if ltt and schedule_variant_overlaps(raw, schedule_start, schedule_end):
                    group = schedule_candidates.setdefault(
                        ltt,
                        {
                            "l": ltt,
                            "f": clean_text(raw_at(raw, 5)),
                            "g": clean_text(raw_at(raw, 6)),
                            "k": clean_text(raw_at(raw, 10)),
                            "af": processed_obj["af_code"],
                            "af_status": processed_obj["af_status"],
                            "segment_code": processed_obj["segment_code"],
                            "segment_label": processed_obj["segment_label"],
                            "af_conflict_ltt": processed_obj["af_conflict_ltt"],
                            "af_conflict_stat": processed_obj["af_conflict_stat"],
                            "variants": {},
                            "filters": set(),
                        },
                    )
                    if processed_obj["segment_code"] == "98":
                        group["af_status"] = processed_obj["af_status"]
                        group["segment_code"] = "98"
                        group["segment_label"] = AF_CONTROL_BY_CODE["98"]["label"]
                    group["af_conflict_ltt"] = bool(
                        group["af_conflict_ltt"]
                        or processed_obj["af_conflict_ltt"]
                    )
                    group["af_conflict_stat"] = bool(
                        group["af_conflict_stat"]
                        or processed_obj["af_conflict_stat"]
                    )
                    ab = clean_text(raw_at(raw, 27))
                    machine_filter = clean_text(raw_at(raw, 47) or raw_at(raw, 27))
                    if ab:
                        group["filters"].add(ab)
                    if machine_filter:
                        group["filters"].add(machine_filter)
                    variant_key = (
                        ab,
                        str(raw_at(raw, 23)),
                        str(raw_at(raw, 24)),
                    )
                    group["variants"].setdefault(
                        variant_key,
                        {
                            "ab": ab,
                            "x": raw_at(raw, 23),
                            "y": raw_at(raw, 24),
                        },
                    )

                if accepted % 25_000 == 0:
                    print(
                        f"Đã xử lý {accepted:,} dòng {plant_code} "
                        f"(đã quét {scanned:,})...",
                        flush=True,
                    )
            if not header_ok:
                raise RuntimeError("Không đọc được dòng header 9.")
    finally:
        for handle in handles.values():
            handle.close()

    if not accepted:
        raise RuntimeError(f"Không tìm thấy dữ liệu nhà máy {plant_code}.")

    periods: list[dict[str, Any]] = []
    sorted_keys = sorted(
        shard_stats,
        key=lambda item: ("9999-99" if item == "Không tháng" else item),
    )
    for key in sorted_keys:
        stats = shard_stats[key]
        payload_meta = stats.meta(source_label, generated)
        prefix = (
            '{"meta":'
            + compact_json(payload_meta)
            + ',"cols":'
            + compact_json(PROCESSED_COLS)
            + ',"rows":['
        )
        output_path = out_dir / stats.file_name
        jsonl_path = temp_root / f"{list(handles).index(key):02d}.jsonl"
        write_gzip_json(output_path, prefix, jsonl_path, "]}")
        periods.append(
            {
                "value": key,
                "label": month_label(key),
                "file": stats.file_name,
                "rows": stats.rows,
                "ltt": len(stats.ltts),
                "stats": len(stats.stats),
                "machines": len(stats.machines),
                "operators": len(stats.operators),
                "date_min": stats.date_min,
                "date_max": stats.date_max,
                "af_quality": {
                    "segment_counts": dict(sorted(stats.segment_counts.items())),
                    "status_counts": dict(sorted(stats.af_status_counts.items())),
                },
                "exec_summary": stats.exec_summary(),
                "bytes_gzip": output_path.stat().st_size,
            }
        )

    schedule_rows: list[dict[str, Any]] = []
    for ltt, group in schedule_candidates.items():
        variants = list(group["variants"].values())
        conflict = len(variants) > 1 or ltt in plan_conflict
        for variant in variants:
            schedule_rows.append(
                {
                    "l": ltt,
                    "f": group["f"],
                    "g": group["g"],
                    "k": group["k"],
                    "af": group["af"],
                    "af_code": group["af"],
                    "af_status": group["af_status"],
                    "segment_code": group["segment_code"],
                    "segment_label": group["segment_label"],
                    "af_conflict_ltt": group["af_conflict_ltt"],
                    "af_conflict_stat": group["af_conflict_stat"],
                    "s": plan_by_ltt.get(ltt, 0),
                    "bg": actual_by_ltt.get(ltt, 0),
                    "ab": variant["ab"],
                    "x": variant["x"],
                    "y": variant["y"],
                    "seg": group["segment_label"],
                    "mf": sorted(group["filters"]),
                    "t": 1,
                    "sourceConflict": bool(
                        conflict
                        or group["af_conflict_ltt"]
                        or group["af_conflict_stat"]
                    ),
                }
            )
    schedule_rows.sort(
        key=lambda row: (
            clean_text(row["af"]),
            clean_text(row["ab"]),
            str(row["x"]),
            clean_text(row["l"]),
        )
    )
    schedule_meta = {
        "source": source_label,
        "generated": generated,
        "plant": plant_code,
        "window_start": schedule_start.isoformat(),
        "window_end": schedule_end.isoformat(),
        "rows": len(schedule_rows),
        "ltt": len({row["l"] for row in schedule_rows}),
    }
    schedule_payload = {
        "meta": schedule_meta,
        "rows": schedule_rows,
    }
    schedule_path = out_dir / "schedule_current.json.gz"
    write_gzip_json(
        schedule_path,
        compact_json(schedule_payload),
        None,
        "",
    )

    dated_periods = [item["value"] for item in periods if item["value"] != "Không tháng"]
    manifest = {
        "schema": SCHEMA_VERSION,
        "schema_version": 3,
        "plant": plant_code,
        "generated_at": generated_iso,
        "generated_display": generated,
        "latest_period": dated_periods[-1] if dated_periods else "Không tháng",
        "latest_detected_period": dated_periods[-1] if dated_periods else "Không tháng",
        "source_sha256": source_meta.get("source_sha256", ""),
        "source_size": source_meta.get("size", workbook_path.stat().st_size),
        "scanned_rows": scanned,
        "accepted_rows": accepted,
        "date_min": global_date_min,
        "date_max": global_date_max,
        "load_mode": "single-period",
        "load_mode_note": (
            "Dashboard chỉ nạp một tháng mỗi lần để tránh giữ hàng trăm nghìn dòng "
            "trong RAM trình duyệt."
        ),
        "af_master": [
            {
                **AF_BY_CODE[code],
                "rows": global_segment_counts.get(AF_BY_CODE[code]["segment_code"], 0),
            }
            for _, code, _ in AF_MASTER
        ],
        "af_aliases": dict(AF_ALIASES),
        "af_control_groups": [
            {
                **item,
                "rows": global_segment_counts.get(item["segment_code"], 0),
            }
            for item in AF_CONTROL_GROUPS
        ],
        "source": {
            "file_id": file_id,
            "file_name": file_name,
            "sheet_name": sheet_name,
            "range": SOURCE_RANGE,
            "size": source_meta.get("size", workbook_path.stat().st_size),
            "modified": source_meta.get("modified", ""),
            "etag": source_meta.get("etag", ""),
            "signature": source_meta["signature"],
            "sha256": source_meta.get("source_sha256", ""),
        },
        "global": {
            "scanned_rows": scanned,
            "accepted_rows": accepted,
            "plant_counts": dict(
                sorted(plant_counts.items(), key=lambda item: item[1], reverse=True)
            ),
            "ltt": len(global_ltts),
            "stats": len(global_stats),
            "machines": len(global_machines),
            "operators": len(global_operators),
            "date_min": global_date_min,
            "date_max": global_date_max,
            "undated_rows": shard_stats.get(
                "Không tháng", ShardStats("", "")
            ).rows,
            "af_quality": {
                "blank_rows": global_segment_counts.get("00", 0),
                "conflict_rows": global_af_conflict_rows,
                "unmapped_rows": global_segment_counts.get("99", 0),
                "ltt_conflicts": len(ltt_af_conflicts),
                "stat_conflicts": len(stat_af_conflicts),
                "segment_counts": dict(sorted(global_segment_counts.items())),
                "af_counts": dict(
                    sorted(global_af_counts.items(), key=lambda item: (-item[1], item[0]))
                ),
                "raw_af_counts": dict(
                    sorted(
                        global_af_raw_counts.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ),
                "alias_rows": {
                    alias: global_af_raw_counts.get(alias, 0)
                    for alias in AF_ALIASES
                    if global_af_raw_counts.get(alias, 0)
                },
                "status_counts": dict(sorted(global_af_status_counts.items())),
            },
        },
        "periods": periods,
        "schedule": {
            "file": schedule_path.name,
            **schedule_meta,
            "bytes_gzip": schedule_path.stat().st_size,
        },
        "processing_seconds": round(time.monotonic() - started, 1),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    shutil.rmtree(temp_root, ignore_errors=True)
    return manifest


def local_source_meta(path: Path, file_id: str = "local") -> dict[str, Any]:
    stat = path.stat()
    digest = sha256_file(path)
    return {
        "signature": source_signature(file_id, digest),
        "source_sha256": digest,
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "etag": digest,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--out", type=Path, default=Path("site/data"))
    parser.add_argument("--plant", default=PLANT_CODE)
    parser.add_argument("--file-id", default=FILE_ID)
    parser.add_argument("--file-name", default=FILE_NAME)
    parser.add_argument("--sheet-name", default=SHEET_NAME)
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--download-to", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    probe_download: Path | None = None
    if args.input:
        source_meta = local_source_meta(args.input, args.file_id)
    else:
        if args.download_to:
            probe_download = args.download_to
        else:
            probe_dir = Path(tempfile.mkdtemp(prefix="gs5-probe-"))
            probe_download = probe_dir / args.file_name
        source_meta = probe_source(args.source_url, args.file_id, probe_download)
    if args.probe:
        output = {
            "signature": source_meta["signature"],
            "size": source_meta["size"],
            "modified": source_meta.get("modified", ""),
            "source_sha256": source_meta.get("source_sha256", ""),
        }
        print(compact_json(output))
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as stream:
                for key, value in output.items():
                    stream.write(f"{key}={value}\n")
        if not args.download_to and probe_download:
            shutil.rmtree(probe_download.parent, ignore_errors=True)
        return 0

    temporary_download: Path | None = None
    workbook_path = args.input
    if not workbook_path and probe_download and probe_download.exists():
        workbook_path = probe_download
        if not args.download_to:
            temporary_download = probe_download
    elif not workbook_path:
        temp_dir = Path(tempfile.mkdtemp(prefix="gs5-source-"))
        temporary_download = temp_dir / args.file_name
        print(
            f"Tải Excel {source_meta['size'] / 1024 / 1024:.1f} MB từ Drive...",
            flush=True,
        )
        download_source(args.source_url, temporary_download, int(source_meta["size"]))
        workbook_path = temporary_download
    assert workbook_path is not None
    try:
        manifest = build_data(
            workbook_path=workbook_path,
            out_dir=args.out,
            plant_code=args.plant,
            source_meta=source_meta,
            sheet_name=args.sheet_name,
            file_name=args.file_name,
            file_id=args.file_id,
        )
    finally:
        if temporary_download:
            shutil.rmtree(temporary_download.parent, ignore_errors=True)
    print(
        "Hoàn tất: "
        f"{manifest['global']['accepted_rows']:,} dòng, "
        f"{len(manifest['periods'])} phân vùng, "
        f"{manifest['processing_seconds']} giây.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"LỖI: {exc}", file=sys.stderr)
        raise
