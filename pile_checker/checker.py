import re
from datetime import datetime
from typing import List, Dict, Tuple
from dataclasses import dataclass, field

from .config import CheckConfig
from .reader import PileRecord


ISSUE_TYPES = {
    "pile_duplicate": "桩号重复",
    "pile_missing": "桩号缺失",
    "hole_depth_short": "实际孔深不足",
    "volume_exceed": "混凝土方量差异超限",
    "pouring_timeout": "成孔到灌注间隔过长",
    "field_missing": "关键字段缺失",
}


@dataclass
class Issue:
    issue_type: str
    file_name: str
    pile_no: str
    reason: str
    suggestion: str
    detail: str = ""
    row_index: int = 0

    @property
    def type_label(self) -> str:
        return ISSUE_TYPES.get(self.issue_type, self.issue_type)


def _extract_pile_number(pile_no: str, prefix: str = "") -> Tuple[str, int]:
    base = pile_no
    if prefix and base.startswith(prefix):
        base = base[len(prefix):]
    match = re.search(r"(\d+)", base)
    if match:
        num_str = match.group(1)
        prefix_part = base[:match.start()]
        return prefix_part, int(num_str)
    return base, 0


def check_pile_duplicates(records: List[PileRecord]) -> List[Issue]:
    issues = []
    pile_map: Dict[str, List[PileRecord]] = {}
    for rec in records:
        if rec.pile_no:
            pile_map.setdefault(rec.pile_no, []).append(rec)
    for pile_no, recs in pile_map.items():
        if len(recs) > 1:
            files = [r.source_file for r in recs]
            for rec in recs:
                issues.append(Issue(
                    issue_type="pile_duplicate",
                    file_name=rec.source_file,
                    pile_no=pile_no,
                    reason=f"桩号在 {len(recs)} 份记录中重复出现: {', '.join(files)}",
                    suggestion="核对施工记录，确认是否同一根桩重复填报或不同桩号混淆",
                    detail=f"第 {rec.row_index} 行",
                    row_index=rec.row_index,
                ))
    return issues


def check_pile_missing(records: List[PileRecord], config: CheckConfig) -> List[Issue]:
    issues = []
    if not config.expected_pile_count:
        return issues
    actual_count = len(set(r.pile_no for r in records if r.pile_no))
    if actual_count < config.expected_pile_count:
        issues.append(Issue(
            issue_type="pile_missing",
            file_name="(汇总)",
            pile_no="(批量)",
            reason=f"应有 {config.expected_pile_count} 根桩，实际记录 {actual_count} 根，缺少 {config.expected_pile_count - actual_count} 根",
            suggestion="对照桩位布置图检查是否漏报，或与现场施工日志核对",
            detail=f"差 {config.expected_pile_count - actual_count} 根",
        ))
    if config.pile_prefix:
        pile_nums = set()
        for rec in records:
            _, num = _extract_pile_number(rec.pile_no, config.pile_prefix)
            if num > 0:
                pile_nums.add(num)
        if pile_nums:
            min_num = min(pile_nums)
            max_num = max(pile_nums)
            expected_full = set(range(min_num, max_num + 1))
            missing = expected_full - pile_nums
            if missing:
                missing_list = sorted(missing)
                missing_str = ", ".join(f"{config.pile_prefix}{n}" for n in missing_list[:10])
                if len(missing_list) > 10:
                    missing_str += f" 等共 {len(missing_list)} 根"
                issues.append(Issue(
                    issue_type="pile_missing",
                    file_name="(汇总)",
                    pile_no="(连号检查)",
                    reason=f"桩号范围 {config.pile_prefix}{min_num}~{config.pile_prefix}{max_num} 之间存在断号: {missing_str}",
                    suggestion="检查断号桩是否漏报或设计变更取消",
                    detail=f"缺失 {len(missing)} 根",
                ))
    return issues


def check_hole_depth(records: List[PileRecord], config: CheckConfig) -> List[Issue]:
    issues = []
    for rec in records:
        if rec.design_length is None or rec.actual_hole_depth is None:
            continue
        diff = rec.actual_hole_depth - rec.design_length
        if diff < config.min_hole_depth_margin:
            shortage = config.min_hole_depth_margin - diff
            issues.append(Issue(
                issue_type="hole_depth_short",
                file_name=rec.source_file,
                pile_no=rec.pile_no,
                reason=f"实际孔深 {rec.actual_hole_depth:.2f}m 低于设计桩长 {rec.design_length:.2f}m，短少 {shortage:.2f}m",
                suggestion="复核孔深测量记录，确认是否存在测绳误差或孔底沉渣过厚",
                detail=f"第 {rec.row_index} 行，差值 {diff:.2f}m",
                row_index=rec.row_index,
            ))
    return issues


def check_concrete_volume(records: List[PileRecord], config: CheckConfig) -> List[Issue]:
    issues = []
    for rec in records:
        if rec.concrete_volume is None:
            continue
        theoretical = rec.calc_theoretical_volume()
        if theoretical is None or theoretical <= 0:
            continue
        diff = rec.concrete_volume - theoretical
        diff_ratio = diff / theoretical
        if abs(diff_ratio) > config.concrete_volume_tolerance:
            direction = "超" if diff_ratio > 0 else "少"
            issues.append(Issue(
                issue_type="volume_exceed",
                file_name=rec.source_file,
                pile_no=rec.pile_no,
                reason=f"混凝土记录方量 {rec.concrete_volume:.2f}m³，理论方量 {theoretical:.2f}m³，{direction}灌 {abs(diff_ratio)*100:.1f}%",
                suggestion="复核砼小票累计方量，检查是否存在扩孔、坍孔或记录偏差",
                detail=f"第 {rec.row_index} 行，偏差 {diff_ratio*100:+.1f}%，阈值 ±{config.concrete_volume_tolerance*100:.0f}%",
                row_index=rec.row_index,
            ))
    return issues


def check_pouring_interval(records: List[PileRecord], config: CheckConfig) -> List[Issue]:
    issues = []
    for rec in records:
        if rec.hole_finish_time is None or rec.pouring_start_time is None:
            continue
        interval = rec.pouring_start_time - rec.hole_finish_time
        hours = interval.total_seconds() / 3600.0
        if hours < 0:
            issues.append(Issue(
                issue_type="pouring_timeout",
                file_name=rec.source_file,
                pile_no=rec.pile_no,
                reason=f"灌注时间 {rec.pouring_start_time.strftime('%Y-%m-%d %H:%M')} 早于成孔时间 {rec.hole_finish_time.strftime('%Y-%m-%d %H:%M')}，时间逻辑矛盾",
                suggestion="检查成孔时间和灌注时间填报是否颠倒或格式错误",
                detail=f"第 {rec.row_index} 行",
                row_index=rec.row_index,
            ))
        elif hours > config.max_pouring_interval_hours:
            issues.append(Issue(
                issue_type="pouring_timeout",
                file_name=rec.source_file,
                pile_no=rec.pile_no,
                reason=f"成孔到灌注间隔 {hours:.1f} 小时，超过阈值 {config.max_pouring_interval_hours:.0f} 小时",
                suggestion="核对施工日志，确认是否存在待料或设备故障，必要时评估沉渣厚度",
                detail=f"第 {rec.row_index} 行，间隔 {hours:.1f}h",
                row_index=rec.row_index,
            ))
    return issues


def check_field_missing(records: List[PileRecord]) -> List[Issue]:
    issues = []
    key_fields = [
        ("design_length", "设计桩长"),
        ("actual_hole_depth", "实际孔深"),
        ("concrete_volume", "混凝土方量"),
    ]
    for rec in records:
        missing_fields = []
        for attr, label in key_fields:
            if getattr(rec, attr) is None:
                missing_fields.append(label)
        if missing_fields:
            issues.append(Issue(
                issue_type="field_missing",
                file_name=rec.source_file,
                pile_no=rec.pile_no,
                reason=f"关键字段缺失: {', '.join(missing_fields)}",
                suggestion="补充缺失数据后再审",
                detail=f"第 {rec.row_index} 行",
                row_index=rec.row_index,
            ))
    return issues


def run_all_checks(records: List[PileRecord], config: CheckConfig) -> List[Issue]:
    issues = []
    issues.extend(check_pile_duplicates(records))
    issues.extend(check_pile_missing(records, config))
    issues.extend(check_hole_depth(records, config))
    issues.extend(check_concrete_volume(records, config))
    issues.extend(check_pouring_interval(records, config))
    issues.extend(check_field_missing(records))
    issues.sort(key=lambda x: (x.file_name, x.row_index, x.issue_type))
    return issues
