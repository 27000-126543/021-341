import os
from dataclasses import dataclass, field


@dataclass
class CheckConfig:
    concrete_volume_tolerance: float = 0.05
    max_pouring_interval_hours: float = 24.0
    min_hole_depth_margin: float = 0.0
    expected_pile_count: int = 0
    pile_prefix: str = ""

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


@dataclass
class AppConfig:
    input_dir: str = "./records"
    output_dir: str = "./reports"
    check: CheckConfig = field(default_factory=CheckConfig)

    def ensure_dirs(self):
        os.makedirs(self.input_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
