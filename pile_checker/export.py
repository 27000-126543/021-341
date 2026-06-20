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


def generate_file_manifest(file_metas: List[Dict]) -> str:
    lines = []
    lines.append("桩基校核交接包 - 文件清单")
    lines.append("=" * 60)
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"文件总数: {len(file_metas)}")
    lines.append("")

    included = [m for m in file_metas if m.get("included", False)]
    excluded = [m for m in file_metas if not m.get("included", False)]

    if included:
        lines.append("【纳入检查的记录文件】")
        lines.append("-" * 60)
        for m in included:
            date_str = m.get("date_from_name", "") or "未识别"
            rows_filtered = m.get("rows_filtered_by_date", 0)
            filter_note = f" (筛除非当天 {rows_filtered} 条)" if rows_filtered > 0 else ""
            size = ""
            try:
                size = f", {m.get('size_kb', 0):.1f} KB" if m.get("size_kb") else ""
            except Exception:
                pass
            lines.append(f"  ✓ {m.get('name', '')}  [{date_str}]  {m.get('record_count', 0)} 条记录{filter_note}{size}")
        lines.append("")

    if excluded:
        lines.append("【已排除的文件】")
        lines.append("-" * 60)
        for m in excluded:
            lines.append(f"  ✗ {m.get('name', '')}  → {m.get('exclude_reason', '')}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines) + "\n"


def _filemeta_to_dict(meta) -> Dict:
    d = {
        "name": meta.name,
        "path": meta.path,
        "included": meta.included,
        "exclude_reason": meta.exclude_reason or "",
        "record_count": meta.record_count,
        "total_rows_read": getattr(meta, "total_rows_read", 0),
        "rows_filtered_by_date": getattr(meta, "rows_filtered_by_date", 0),
        "date_from_name": meta.date_from_name.strftime("%Y-%m-%d") if meta.date_from_name else "",
    }
    try:
        d["size_kb"] = os.path.getsize(meta.path) / 1024
    except Exception:
        d["size_kb"] = 0
    return d


def save_run_params(
    package_dir: str,
    project_name: str,
    check_date: str,
    app_config: AppConfig,
    file_metas: Optional[List[FileMeta]] = None,
    extra: Optional[Dict] = None,
) -> str:
    os.makedirs(package_dir, exist_ok=True)
    params = {
        "project_name": project_name,
        "check_date": check_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filter_date": getattr(app_config.date_filter, "enabled", False),
        "pile_prefix": getattr(app_config.check, "pile_prefix", ""),
        "volume_tolerance": getattr(app_config.check, "concrete_volume_tolerance", 0.05),
        "pouring_hours": getattr(app_config.check, "max_pouring_interval_hours", 24),
        "pile_diameter": getattr(app_config.check, "default_pile_diameter", 800) or 800,
        "check_config": app_config.to_dict(),
        "file_metas": [_filemeta_to_dict(m) for m in (file_metas or [])],
        "extra": extra or {},
    }
    path = os.path.join(package_dir, "run_params.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)
    return path


def load_run_params(package_dir: str) -> Optional[Dict]:
    path = os.path.join(package_dir, "run_params.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def build_handover_package(
    project_name: str,
    check_date: str,
    output_dir: str,
    app_config: AppConfig,
    report_files: Dict[str, str],
    feedback_report_files: Optional[Dict[str, str]] = None,
    file_metas: Optional[List[FileMeta]] = None,
    include_zip: bool = True,
    run_params: Optional[Dict] = None,
    readonly: bool = False,
) -> Dict[str, str]:
    safe_date = check_date.replace("/", "-").replace(":", "-")
    safe_project = project_name.replace(" ", "_")
    package_dir = os.path.join(output_dir, f"{safe_project}_{safe_date}_交接包")
    os.makedirs(package_dir, exist_ok=True)

    if run_params is None:
        run_params = load_run_params(package_dir)

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

    if run_params and run_params.get("check_config"):
        cfg_path = os.path.join(package_dir, "项目配置快照.json")
        if readonly:
            pass
        else:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(run_params["check_config"], f, ensure_ascii=False, indent=2)
        results["config_snapshot"] = cfg_path
    else:
        cfg_path = os.path.join(package_dir, "项目配置快照.json")
        if not readonly or not os.path.isfile(cfg_path):
            save_project_config(cfg_path, app_config)
        results["config_snapshot"] = cfg_path

    readme_path = os.path.join(package_dir, "交接说明.txt")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(_generate_readme(project_name, check_date))
    results["readme"] = readme_path

    manifest_metas = None
    if run_params and run_params.get("file_metas"):
        manifest_metas = run_params["file_metas"]
    elif file_metas:
        manifest_metas = [_filemeta_to_dict(m) for m in file_metas]

    if manifest_metas:
        manifest_path = os.path.join(package_dir, "文件清单.txt")
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(generate_file_manifest(manifest_metas))
        results["file_manifest"] = manifest_path

    if not readonly and not run_params:
        save_run_params(package_dir, project_name, check_date, app_config, file_metas)

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
