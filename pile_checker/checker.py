import re
import hashlib
from datetime import datetime
from typing import List, Dict, Tuple
from dataclasses import dataclass

from .config import CheckConfig, ISSUE_SEVERITY, SEVERITY_ORDER
from .reader import PileRecord


ISSUE_TYPES = {
    "pile_duplicate": "桩号重复",
    "pile_missing": "桩号缺失",
    "hole_depth_short": "实际孔深不足",
    "volume_exceed": "混凝土方量差异超限",
    "pouring_timeout": "成孔到灌注间隔过长",
    "field_missing": "关键字段缺失",
    "pile_no_empty": "桩号为空",
    "volume_calc_missing": "理论方量无法计算",
}


def _make_issue_id(issue_type: str, file_name: str, row_index: int,
                   pile_no: str, detail: str = "") -> str:
    raw = f"{issue_type}|{file_name}|{row_index}|{pile_no}|{detail}"
    h = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8].upper()
    short_type = issue_type[:3].upper()
    return f"{short_type}-{h}"


@dataclass
class Issue:
    issue_type: str
    file_name: str
    pile_no: str
    reason: str
    suggestion: str
    detail: str = ""
    row_index: int = 0
    issue_id: str = ""

    def __post_init__(self):
        if not self.issue_id:
            self.issue_id = _make_issue_id(
                self.issue_type, self.file_name, self.row_index,
                self.pile_no, self.detail,
            )

    @property
    def type_label(self) -> str:
        return ISSUE_TYPES.get(self.issue_type, self.issue_type)

    @property
    def severity(self) -> str:
        return ISSUE_SEVERITY.get(self.issue_type, "提示")

    @property
    def severity_order(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 99)


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


def _format_field_hints(rec: PileRecord) -> str:
    hints = []
    if rec.design_length is not None:
        hints.append(f"设计桩长={rec.design_length}")
    if rec.actual_hole_depth is not None:
        hints.append(f"实际孔深={rec.actual_hole_depth}")
    if rec.concrete_volume is not None:
        hints.append(f"方量={rec.concrete_volume}")
    if rec.theoretical_volume is not None:
        hints.append(f"理论方量={rec.theoretical_volume}")
    if rec.pile_diameter is not None:
        hints.append(f"桩径={rec.pile_diameter}")
    if rec.hole_finish_time is not None:
        hints.append(f"成孔={rec.hole_finish_time.strftime('%m-%d %H:%M')}")
    if rec.pouring_start_time is not None:
        hints.append(f"灌注={rec.pouring_start_time.strftime('%m-%d %H:%M')}")
    return f"（{', '.join(hints)}）" if hints else ""


def check_pile_no_empty(records: List[PileRecord]) -> List[Issue]:
    issues = []
    for rec in records:
        if not rec.pile_no and rec.has_any_data():
            hint = _format_field_hints(rec)
            issues.append(Issue(
                issue_type="pile_no_empty",
                file_name=rec.source_file,
                pile_no="(空)",
                reason=f"该行桩号为空{hint}，已有数据填写但漏了桩号",
                suggestion="补填桩号后再审；如为汇总/空行请删除整行",
                detail=f"第 {rec.row_index} 行",
                row_index=rec.row_index,
            ))
    return issues


def check_pile_duplicates(records: List[PileRecord]) -> List[Issue]:
    issues = []
    pile_map: Dict[str, List[PileRecord]] = {}
    for rec in records:
        if rec.pile_no:
            pile_map.setdefault(rec.pile_no, []).append(rec)
    for pile_no, recs in pile_map.items():
        if len(recs) > 1:
            files = [f"{r.source_file}(第{r.row_index}行)" for r in recs]
            for rec in recs:
                issues.append(Issue(
                    issue_type="pile_duplicate",
                    file_name=rec.source_file,
                    pile_no=pile_no,
                    reason=f"桩号在 {len(recs)} 处重复出现: {', '.join(files)}",
                    suggestion="核对施工记录，确认是否同一根桩重复填报或不同桩号混淆",
                    detail=f"第 {rec.row_index} 行",
                    row_index=rec.row_index,
                ))
    return issues


def check_pile_missing(records: List[PileRecord], config: CheckConfig) -> List[Issue]:
    issues = []
    valid_records = [r for r in records if r.pile_no]
    actual_count = len(set(r.pile_no for r in valid_records))

    if config.expected_pile_count and actual_count < config.expected_pile_count:
        issues.append(Issue(
            issue_type="pile_missing",
            file_name="(汇总)",
            pile_no="(批量)",
            reason=f"应有 {config.expected_pile_count} 根桩，实际有效记录 {actual_count} 根，缺少 {config.expected_pile_count - actual_count} 根",
            suggestion="对照桩位布置图检查是否漏报，或与现场施工日志核对",
            detail=f"差 {config.expected_pile_count - actual_count} 根",
        ))

    start = config.pile_number_start
    end = config.pile_number_end
    if config.pile_prefix:
        pile_nums = set()
        for rec in valid_records:
            _, num = _extract_pile_number(rec.pile_no, config.pile_prefix)
            if num > 0:
                pile_nums.add(num)
        if pile_nums:
            if start is None:
                start = min(pile_nums)
            if end is None:
                end = max(pile_nums)
            expected_full = set(range(start, end + 1))
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
                    reason=f"桩号范围 {config.pile_prefix}{start}~{config.pile_prefix}{end} 之间存在断号: {missing_str}",
                    suggestion="检查断号桩是否漏报或设计变更取消",
                    detail=f"缺失 {len(missing)} 根",
                ))
    return issues


def check_hole_depth(records: List[PileRecord], config: CheckConfig) -> List[Issue]:
    issues = []
    for rec in records:
        if not rec.pile_no:
            continue
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


def check_volume_calc_missing(records: List[PileRecord], config: CheckConfig) -> List[Issue]:
    issues = []
    for rec in records:
        if not rec.pile_no:
            continue
        if rec.concrete_volume is None:
            continue
        theoretical = rec.calc_theoretical_volume(config.default_pile_diameter)
        if theoretical is None:
            missing = []
            if rec.theoretical_volume is None:
                missing.append("理论方量列")
            if rec.pile_diameter is None:
                missing.append("桩径列")
            if rec.design_length is None:
                missing.append("设计桩长列")
            issues.append(Issue(
                issue_type="volume_calc_missing",
                file_name=rec.source_file,
                pile_no=rec.pile_no,
                reason=f"有混凝土方量但无法计算理论值，缺少: {', '.join(missing)}",
                suggestion="补填理论方量或桩径+设计桩长，以便核对砼用量",
                detail=f"第 {rec.row_index} 行",
                row_index=rec.row_index,
            ))
    return issues


def check_concrete_volume(records: List[PileRecord], config: CheckConfig) -> List[Issue]:
    issues = []
    for rec in records:
        if not rec.pile_no:
            continue
        if rec.concrete_volume is None:
            continue
        theoretical = rec.calc_theoretical_volume(config.default_pile_diameter)
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
        if not rec.pile_no:
            continue
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
        if not rec.pile_no:
            continue
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


def sort_issues(issues: List[Issue]) -> List[Issue]:
    return sorted(
        issues,
        key=lambda x: (
            x.severity_order,
            x.issue_type,
            x.file_name,
            x.row_index,
        ),
    )


def run_all_checks(records: List[PileRecord], config: CheckConfig) -> List[Issue]:
    issues: List[Issue] = []
    issues.extend(check_pile_no_empty(records))
    issues.extend(check_pile_duplicates(records))
    issues.extend(check_pile_missing(records, config))
    issues.extend(check_hole_depth(records, config))
    issues.extend(check_volume_calc_missing(records, config))
    issues.extend(check_concrete_volume(records, config))
    issues.extend(check_pouring_interval(records, config))
    issues.extend(check_field_missing(records))
    return sort_issues(issues)
