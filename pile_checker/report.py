import os
from datetime import datetime
from typing import List, Dict

from .checker import Issue, ISSUE_TYPES


def generate_text_report(project_name: str, check_date: str, issues: List[Issue],
                         total_records: int, total_files: int, errors: List[str]) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append("  桩基施工记录批量校核报告")
    lines.append("=" * 72)
    lines.append(f"  项目名称: {project_name}")
    lines.append(f"  检查日期: {check_date}")
    lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  检查文件: {total_files} 份")
    lines.append(f"  记录总数: {total_records} 条")
    lines.append(f"  问题数量: {len(issues)} 条")
    lines.append("-" * 72)

    if errors:
        lines.append("")
        lines.append("【读取错误】")
        lines.append("-" * 72)
        for i, err in enumerate(errors, 1):
            lines.append(f"  {i}. {err}")

    if not issues:
        lines.append("")
        lines.append("【检查结果】全部通过，未发现明显问题。")
        lines.append("  （注：本工具仅作批量初筛，正式资料仍需人工复核。）")
        lines.append("")
        return "\n".join(lines)

    type_counts: Dict[str, int] = {}
    for issue in issues:
        type_counts[issue.issue_type] = type_counts.get(issue.issue_type, 0) + 1

    lines.append("")
    lines.append("【问题分类统计】")
    lines.append("-" * 72)
    for itype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        label = ISSUE_TYPES.get(itype, itype)
        lines.append(f"  {label}: {count} 条")

    lines.append("")
    lines.append("【问题清单】")
    lines.append("-" * 72)

    current_file = None
    idx = 1
    for issue in issues:
        if issue.file_name != current_file:
            current_file = issue.file_name
            lines.append("")
            lines.append(f"  ▶ 文件: {current_file}")
        lines.append(f"  [{idx}] {issue.type_label}")
        lines.append(f"      桩号: {issue.pile_no}")
        lines.append(f"      疑似原因: {issue.reason}")
        lines.append(f"      建议复核项: {issue.suggestion}")
        if issue.detail:
            lines.append(f"      详细信息: {issue.detail}")
        idx += 1

    lines.append("")
    lines.append("=" * 72)
    lines.append("  报告结束  请内业工程师逐条核实后反馈施工员整改")
    lines.append("=" * 72)
    lines.append("")
    return "\n".join(lines)


def generate_csv_report(issues: List[Issue]) -> str:
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["序号", "问题类型", "文件名", "桩号", "行号", "疑似原因", "建议复核项", "详细信息"])
    for i, issue in enumerate(issues, 1):
        writer.writerow([
            i,
            issue.type_label,
            issue.file_name,
            issue.pile_no,
            issue.row_index if issue.row_index else "",
            issue.reason,
            issue.suggestion,
            issue.detail,
        ])
    return output.getvalue()


def save_reports(project_name: str, check_date: str, output_dir: str,
                 issues: List[Issue], total_records: int, total_files: int,
                 errors: List[str]) -> Dict[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    safe_date = check_date.replace("/", "-").replace(":", "-")
    base_name = f"{project_name}_{safe_date}_桩基校核报告"

    results = {}

    text_content = generate_text_report(project_name, check_date, issues,
                                        total_records, total_files, errors)
    txt_path = os.path.join(output_dir, f"{base_name}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text_content)
    results["txt"] = txt_path

    if issues:
        csv_content = generate_csv_report(issues)
        csv_path = os.path.join(output_dir, f"{base_name}.csv")
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(csv_content)
        results["csv"] = csv_path

    return results


def print_console_summary(issues: List[Issue], total_records: int,
                          total_files: int, errors: List[str]):
    print()
    print("━" * 60)
    print(f"  共检查 {total_files} 份文件，{total_records} 条记录")
    if errors:
        print(f"  读取错误 {len(errors)} 项")
    print(f"  发现问题 {len(issues)} 条")
    print("━" * 60)
    if not issues and not errors:
        print("  ✓ 全部通过，未发现明显问题。")
        print("    （建议仍需人工抽核关键记录）")
    else:
        type_counts: Dict[str, int] = {}
        for issue in issues:
            type_counts[issue.issue_type] = type_counts.get(issue.issue_type, 0) + 1
        for itype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            label = ISSUE_TYPES.get(itype, itype)
            print(f"    • {label}: {count} 条")
    print()
