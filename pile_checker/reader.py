import os
import math
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from .config import CheckConfig


@dataclass
class PileRecord:
    pile_no: str
    design_length: Optional[float] = None
    actual_hole_depth: Optional[float] = None
    concrete_volume: Optional[float] = None
    theoretical_volume: Optional[float] = None
    hole_finish_time: Optional[datetime] = None
    pouring_start_time: Optional[datetime] = None
    pile_diameter: Optional[float] = None
    source_file: str = ""
    row_index: int = 0

    def calc_theoretical_volume(self) -> Optional[float]:
        if self.theoretical_volume is not None:
            return self.theoretical_volume
        if self.pile_diameter and self.design_length:
            radius = self.pile_diameter / 2 / 1000.0
            area = math.pi * radius * radius
            return area * self.design_length
        return None


def _find_column(columns: List[str], candidates: List[str]) -> Optional[str]:
    col_lower = {c.strip().lower(): c for c in columns}
    for cand in candidates:
        cand_lower = cand.strip().lower()
        if cand_lower in col_lower:
            return col_lower[cand_lower]
    return None


def _parse_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_datetime(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    fmts = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y %H:%M",
        "%m-%d-%Y %H:%M",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        import pandas as pd
        ts = pd.to_datetime(s)
        if pd.notna(ts):
            return ts.to_pydatetime()
    except Exception:
        pass
    return None


def read_csv_file(file_path: str, config: CheckConfig) -> List[PileRecord]:
    import csv
    records = []
    filename = os.path.basename(file_path)
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return records
        columns = list(reader.fieldnames)
        col_map = {}
        for key in config.field_mapping.keys():
            col = _find_column(columns, config.get_field_names(key))
            if col:
                col_map[key] = col
        for i, row in enumerate(reader, start=2):
            rec = PileRecord(
                pile_no=str(row.get(col_map.get("pile_no", ""), "")).strip(),
                source_file=filename,
                row_index=i,
            )
            if not rec.pile_no:
                continue
            if "design_length" in col_map:
                rec.design_length = _parse_float(row.get(col_map["design_length"]))
            if "actual_hole_depth" in col_map:
                rec.actual_hole_depth = _parse_float(row.get(col_map["actual_hole_depth"]))
            if "concrete_volume" in col_map:
                rec.concrete_volume = _parse_float(row.get(col_map["concrete_volume"]))
            if "theoretical_volume" in col_map:
                rec.theoretical_volume = _parse_float(row.get(col_map["theoretical_volume"]))
            if "pile_diameter" in col_map:
                rec.pile_diameter = _parse_float(row.get(col_map["pile_diameter"]))
            if "hole_finish_time" in col_map:
                rec.hole_finish_time = _parse_datetime(row.get(col_map["hole_finish_time"]))
            if "pouring_start_time" in col_map:
                rec.pouring_start_time = _parse_datetime(row.get(col_map["pouring_start_time"]))
            records.append(rec)
    return records


def read_excel_file(file_path: str, config: CheckConfig) -> List[PileRecord]:
    import openpyxl
    records = []
    filename = os.path.basename(file_path)
    wb = openpyxl.load_workbook(file_path, data_only=True)
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        if ws.max_row < 2:
            continue
        header_row = []
        for cell in ws[1]:
            header_row.append(str(cell.value).strip() if cell.value is not None else "")
        col_map = {}
        for key in config.field_mapping.keys():
            col = _find_column(header_row, config.get_field_names(key))
            if col:
                col_idx = header_row.index(col)
                col_map[key] = col_idx
        if "pile_no" not in col_map:
            continue
        for row_idx in range(2, ws.max_row + 1):
            row_data = []
            for col_idx in range(ws.max_column):
                cell = ws.cell(row=row_idx, column=col_idx + 1)
                row_data.append(cell.value)
            pile_no_val = row_data[col_map["pile_no"]] if col_map["pile_no"] < len(row_data) else ""
            pile_no = str(pile_no_val).strip() if pile_no_val is not None else ""
            if not pile_no:
                continue
            rec = PileRecord(
                pile_no=pile_no,
                source_file=filename,
                row_index=row_idx,
            )
            if "design_length" in col_map and col_map["design_length"] < len(row_data):
                rec.design_length = _parse_float(row_data[col_map["design_length"]])
            if "actual_hole_depth" in col_map and col_map["actual_hole_depth"] < len(row_data):
                rec.actual_hole_depth = _parse_float(row_data[col_map["actual_hole_depth"]])
            if "concrete_volume" in col_map and col_map["concrete_volume"] < len(row_data):
                rec.concrete_volume = _parse_float(row_data[col_map["concrete_volume"]])
            if "theoretical_volume" in col_map and col_map["theoretical_volume"] < len(row_data):
                rec.theoretical_volume = _parse_float(row_data[col_map["theoretical_volume"]])
            if "pile_diameter" in col_map and col_map["pile_diameter"] < len(row_data):
                rec.pile_diameter = _parse_float(row_data[col_map["pile_diameter"]])
            if "hole_finish_time" in col_map and col_map["hole_finish_time"] < len(row_data):
                rec.hole_finish_time = _parse_datetime(row_data[col_map["hole_finish_time"]])
            if "pouring_start_time" in col_map and col_map["pouring_start_time"] < len(row_data):
                rec.pouring_start_time = _parse_datetime(row_data[col_map["pouring_start_time"]])
            records.append(rec)
    wb.close()
    return records


def read_all_records(input_dir: str, config: CheckConfig) -> Tuple[List[PileRecord], List[str]]:
    all_records = []
    errors = []
    if not os.path.isdir(input_dir):
        errors.append(f"输入目录不存在: {input_dir}")
        return all_records, errors
    supported_ext = (".xlsx", ".xls", ".csv")
    files = []
    for fname in os.listdir(input_dir):
        fpath = os.path.join(input_dir, fname)
        if os.path.isfile(fpath) and fname.lower().endswith(supported_ext):
            if not fname.startswith("~$"):
                files.append(fpath)
    if not files:
        errors.append(f"目录 {input_dir} 中未找到 Excel 或 CSV 文件")
        return all_records, errors
    for fpath in sorted(files):
        try:
            if fpath.lower().endswith(".csv"):
                recs = read_csv_file(fpath, config)
            else:
                recs = read_excel_file(fpath, config)
            all_records.extend(recs)
        except Exception as e:
            errors.append(f"读取文件 {os.path.basename(fpath)} 失败: {str(e)}")
    return all_records, errors
