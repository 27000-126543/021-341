import os
import json
import re
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


ISSUE_SEVERITY = {
    "pile_duplicate": "严重",
    "pile_missing": "严重",
    "hole_depth_short": "严重",
    "volume_exceed": "警告",
    "pouring_timeout": "警告",
    "field_missing": "提示",
    "pile_no_empty": "严重",
    "volume_calc_missing": "提示",
}

SEVERITY_ORDER = {"严重": 0, "警告": 1, "提示": 2}


@dataclass
class CheckConfig:
    concrete_volume_tolerance: float = 0.05
    max_pouring_interval_hours: float = 24.0
    min_hole_depth_margin: float = 0.0
    expected_pile_count: int = 0
    pile_prefix: str = ""
    default_pile_diameter: Optional[float] = None
    pile_number_start: Optional[int] = None
    pile_number_end: Optional[int] = None

    field_mapping: dict = field(default_factory=lambda: {
        "pile_no": ["桩号", "桩编号", "桩号编号", "pile_no", "pile_number"],
        "design_length": ["设计桩长", "设计桩长(m)", "设计长度", "design_length"],
        "actual_hole_depth": ["实际孔深", "实际孔深(m)", "孔深", "hole_depth"],
        "concrete_volume": ["混凝土方量", "砼方量", "混凝土用量", "concrete_volume"],
        "theoretical_volume": ["理论方量", "设计方量", "theoretical_volume"],
        "hole_finish_time": ["成孔时间", "成孔完成时间", "钻孔完成时间", "hole_finish_time"],
        "pouring_start_time": ["灌注开始时间", "开盘时间", "灌注时间", "pouring_time"],
        "pile_diameter": ["桩径", "设计桩径", "桩径(mm)", "diameter"],
    })

    def get_field_names(self, key: str) -> list:
        return self.field_mapping.get(key, [])

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("field_mapping", None)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckConfig":
        cfg = cls()
        for k, v in data.items():
            if hasattr(cfg, k) and k != "field_mapping":
                setattr(cfg, k, v)
        if "field_mapping" in data and isinstance(data["field_mapping"], dict):
            cfg.field_mapping.update(data["field_mapping"])
        return cfg


@dataclass
class DateFilter:
    enabled: bool = False
    target_date: Optional[str] = None
    match_from_filename: bool = True
    match_from_record: bool = True

    def parse_target(self) -> Optional[datetime]:
        if not self.target_date:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(self.target_date, fmt)
            except ValueError:
                continue
        return None


@dataclass
class AppConfig:
    input_dir: str = "./records"
    output_dir: str = "./reports"
    check: CheckConfig = field(default_factory=CheckConfig)
    date_filter: DateFilter = field(default_factory=DateFilter)
    project_name: str = ""

    def ensure_dirs(self):
        os.makedirs(self.input_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "input_dir": self.input_dir,
            "output_dir": self.output_dir,
            "date_filter": asdict(self.date_filter),
            "check": self.check.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        cfg = cls()
        cfg.project_name = data.get("project_name", "")
        cfg.input_dir = data.get("input_dir", cfg.input_dir)
        cfg.output_dir = data.get("output_dir", cfg.output_dir)
        if "check" in data and isinstance(data["check"], dict):
            cfg.check = CheckConfig.from_dict(data["check"])
        if "date_filter" in data and isinstance(data["date_filter"], dict):
            df = data["date_filter"]
            cfg.date_filter = DateFilter(
                enabled=df.get("enabled", False),
                target_date=df.get("target_date"),
                match_from_filename=df.get("match_from_filename", True),
                match_from_record=df.get("match_from_record", True),
            )
        return cfg


def load_project_config(config_path: str) -> AppConfig:
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return AppConfig.from_dict(data)


def save_project_config(config_path: str, app_config: AppConfig):
    os.makedirs(os.path.dirname(os.path.abspath(config_path)) or ".", exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(app_config.to_dict(), f, ensure_ascii=False, indent=2)


def extract_date_from_filename(filename: str) -> Optional[datetime]:
    patterns = [
        r"(\d{4})[-_/年](\d{1,2})[-_/月](\d{1,2})",
        r"(\d{4})(\d{2})(\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, filename)
        if m:
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return datetime(y, mo, d)
            except ValueError:
                continue
    return None
