import os
import csv
import io
import json
import shutil
import zipfile
from datetime import datetime
from typing import Dict, List, Optional

from .config import AppConfig, save_project_config
from .reader import FileMeta
from .feedback import generate_feedback_template_csv


def generate_file_manifest(file_metas: List[FileMeta]) -> str:
    lines = []
    lines.append("桩基校核交接包 - 文件清单")
    lines.append("=" * 60)
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"文件总数: {len(file_metas)}")
    lines.append("")

    included = [m for m in file_metas if m.included]
    excluded = [m for m in file_metas if not m.included]

    if included:
        lines.append("【纳入检查的记录文件】")
        lines.append("-" * 60)
        for m in included:
            date_str = m.date_from_name.strftime("%Y-%m-%d") if m.date_from_name else "未识别"
            filter_note = f" (筛除非当天 {m.rows_filtered_by_date} 条)" if m.rows_filtered_by_date > 0 else ""
            size = ""
            try:
                size = f", {os.path.getsize(m.path)/1024:.1f} KB"
            except Exception:
                pass
            lines.append(f"  ✓ {m.name}  [{date_str}]  {m.record_count} 条记录{filter_note}{size}")
        lines.append("")

    if excluded:
        lines.append("【已排除的文件】")
        lines.append("-" * 60)
        for m in excluded:
            lines.append(f"  ✗ {m.name}  → {m.exclude_reason}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines) + "\n"


def build_handover_package(
    project_name: str,
    check_date: str,
    output_dir: str,
    app_config: AppConfig,
    report_files: Dict[str, str],
    feedback_report_files: Optional[Dict[str, str]] = None,
    file_metas: Optional[List[FileMeta]] = None,
    include_zip: bool = True,
) -> Dict[str, str]:
    safe_date = check_date.replace("/", "-").replace(":", "-")
    safe_project = project_name.replace(" ", "_")
    package_dir = os.path.join(output_dir, f"{safe_project}_{safe_date}_交接包")
    os.makedirs(package_dir, exist_ok=True)

    results: Dict[str, str] = {}

    for desc, src_path in report_files.items():
        if not os.path.isfile(src_path):
            continue
        dst = os.path.join(package_dir, os.path.basename(src_path))
        shutil.copy2(src_path, dst)
        results[f"report_{desc}"] = dst

    if feedback_report_files:
        fb_dir = os.path.join(package_dir, "整改反馈")
        os.makedirs(fb_dir, exist_ok=True)
        for desc, src_path in feedback_report_files.items():
            if not os.path.isfile(src_path):
                continue
            dst = os.path.join(fb_dir, os.path.basename(src_path))
            shutil.copy2(src_path, dst)
            results[f"feedback_{desc}"] = dst

    tpl_path = os.path.join(package_dir, "整改反馈表_模板.csv")
    with open(tpl_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(generate_feedback_template_csv(project_name, check_date))
    results["feedback_template"] = tpl_path

    cfg_path = os.path.join(package_dir, "项目配置快照.json")
    save_project_config(cfg_path, app_config)
    results["config_snapshot"] = cfg_path

    readme_path = os.path.join(package_dir, "交接说明.txt")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(_generate_readme(project_name, check_date))
    results["readme"] = readme_path

    if file_metas:
        manifest_path = os.path.join(package_dir, "文件清单.txt")
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(generate_file_manifest(file_metas))
        results["file_manifest"] = manifest_path

    if include_zip:
        zip_path = os.path.join(output_dir, f"{safe_project}_{safe_date}_交接包.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(package_dir):
                for name in files:
                    full = os.path.join(root, name)
                    arc = os.path.relpath(full, package_dir)
                    zf.write(full, arc)
        results["zip"] = zip_path

    return results


def _generate_readme(project_name: str, check_date: str) -> str:
    lines = []
    lines.append("桩基施工记录校核 - 交接说明")
    lines.append("=" * 60)
    lines.append(f"项目名称: {project_name}")
    lines.append(f"检查日期: {check_date}")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("本交接包包含:")
    lines.append("  1. 桩基校核报告（TXT/CSV/Excel）")
    lines.append("     - 按严重程度分组，每条问题带唯一编号")
    lines.append("  2. 整改跟踪报告（如已导入反馈）")
    lines.append("  3. 整改反馈表模板.csv")
    lines.append("     - 施工员按编号逐条填写状态和说明")
    lines.append("     - 可选: 复核日期、处理责任人、附件路径")
    lines.append("  4. 项目配置快照.json")
    lines.append("     - 记录本次使用的桩号前缀、阈值、字段映射等参数")
    lines.append("  5. 文件清单.txt")
    lines.append("     - 本次纳入/排除的原始记录文件明细")
    lines.append("")
    lines.append("整改反馈流程:")
    lines.append("  1) 施工员打开【整改反馈表模板.csv】")
    lines.append("  2) 按问题编号对应报告逐条填写整改状态")
    lines.append("  3) 资料员运行: python main.py feedback 项目名 日期 --feedback 反馈表")
    lines.append("  4) 查看闭环汇总，追踪仍异常和待复核项")
    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines) + "\n"
