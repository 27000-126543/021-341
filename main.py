#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桩基施工记录批量校核工具 v3.0
用法:
  python main.py check <项目名称> <检查日期> [选项]
  python main.py feedback <项目名称> <检查日期> --feedback <反馈文件> [选项]
"""

import sys
import os
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pile_checker.config import (
    AppConfig, CheckConfig, DateFilter,
    load_project_config, save_project_config,
)
from pile_checker.reader import read_all_records
from pile_checker.checker import run_all_checks
from pile_checker.report import save_reports, print_console_summary
from pile_checker.feedback import (
    read_feedback, merge_feedback, status_summary,
    save_feedback_reports,
)


def _looks_like_date(s: str) -> bool:
    if not s:
        return False
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            datetime.strptime(s, fmt)
            return True
        except ValueError:
            continue
    return False


def _add_common_args(parser):
    parser.add_argument("project_name", nargs="?", default=None,
                        help="项目名称（使用 -c 时可省略）")
    parser.add_argument("check_date", nargs="?", default=None,
                        help="检查日期，格式 YYYY-MM-DD，默认为今天")

    parser.add_argument("-c", "--config", dest="config_file", default=None,
                        help="项目配置文件路径（JSON）")

    parser.add_argument("-i", "--input-dir", default=None,
                        help="桩基记录文件所在目录，默认 ./records")
    parser.add_argument("-o", "--output-dir", default=None,
                        help="报告输出目录，默认 ./reports")


def _add_check_args(parser):
    parser.add_argument("--filter-date", action="store_true",
                        help="启用日期筛选，仅保留当天记录行（按记录内成孔/灌注日期逐行筛选）")
    parser.add_argument("--no-filter", action="store_true",
                        help="禁用日期筛选，检查整个文件夹（默认行为）")

    check = parser.add_argument_group("校核参数")
    check.add_argument("--volume-tol", type=float, default=None,
                       help="混凝土方量差异容许比例，默认 0.05 (即 ±5%%)")
    check.add_argument("--max-interval", type=float, default=None,
                       help="成孔到灌注最大容许间隔（小时），默认 24")
    check.add_argument("--depth-margin", type=float, default=None,
                       help="孔深容许负偏差（米），默认 0")
    check.add_argument("--default-diameter", type=float, default=None,
                       help="项目统一桩径(mm)")
    check.add_argument("--pile-count", type=int, default=None,
                       help="预期桩数")
    check.add_argument("--pile-prefix", type=str, default=None,
                       help="桩号前缀，如 ZK、ZH")
    check.add_argument("--pile-start", type=int, default=None,
                       help="桩号起始编号")
    check.add_argument("--pile-end", type=int, default=None,
                       help="桩号结束编号")

    parser.add_argument("--save-config", dest="save_config", default=None,
                        help="保存当前参数为项目配置文件")
    parser.add_argument("--no-xlsx", action="store_true",
                        help="不生成 Excel 格式报告")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="安静模式")


def _add_feedback_args(parser):
    parser.add_argument("--feedback", required=True,
                        help="施工员反馈表文件路径（CSV 或 Excel）")
    parser.add_argument("--no-xlsx", action="store_true",
                        help="不生成 Excel 格式整改报告")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="安静模式")


def build_parser():
    parser = argparse.ArgumentParser(
        description="桩基施工记录批量校核工具 v3.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    p_check = sub.add_parser("check", help="批量校核桩基记录",
                             formatter_class=argparse.RawDescriptionHelpFormatter,
                             epilog="""
示例:
  python main.py check 滨江一号项目 2026-06-21
  python main.py check 滨江一号 2026-06-21 --filter-date
  python main.py check -c projects/滨江一号.json 2026-06-21 --filter-date
  python main.py check 科技园 2026-06-21 --volume-tol 0.08 --pile-prefix ZK
  python main.py check 滨江一号 --save-config projects/滨江一号.json --pile-prefix ZK --pile-count 120
                             """)
    _add_common_args(p_check)
    _add_check_args(p_check)

    p_feedback = sub.add_parser("feedback", help="导入反馈表生成整改跟踪汇总",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="""
示例:
  python main.py feedback 滨江一号 2026-06-21 --feedback feedback/施工员反馈.xlsx
  python main.py feedback -c projects/滨江一号.json 2026-06-21 --feedback feedback/反馈.csv
                                """)
    _add_common_args(p_feedback)
    _add_feedback_args(p_feedback)

    p_legacy = sub.add_parser("run", help="[兼容] 等同于 check",
                              formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_common_args(p_legacy)
    _add_check_args(p_legacy)

    return parser


def _apply_cli_overrides(app_cfg: AppConfig, args):
    if hasattr(args, "input_dir") and args.input_dir:
        app_cfg.input_dir = args.input_dir
    if hasattr(args, "output_dir") and args.output_dir:
        app_cfg.output_dir = args.output_dir
    if args.project_name:
        app_cfg.project_name = args.project_name

    chk = app_cfg.check
    for attr, arg_name in [
        ("concrete_volume_tolerance", "volume_tol"),
        ("max_pouring_interval_hours", "max_interval"),
        ("min_hole_depth_margin", "depth_margin"),
        ("default_pile_diameter", "default_diameter"),
        ("expected_pile_count", "pile_count"),
    ]:
        val = getattr(args, arg_name, None)
        if val is not None:
            setattr(chk, attr, val)

    for attr, arg_name in [
        ("pile_prefix", "pile_prefix"),
        ("pile_number_start", "pile_start"),
        ("pile_number_end", "pile_end"),
    ]:
        val = getattr(args, arg_name, None)
        if val is not None:
            setattr(chk, attr, val)

    df = app_cfg.date_filter
    if getattr(args, "filter_date", False):
        df.enabled = True
        df.match_from_filename = False
        df.match_from_record = True
    if getattr(args, "no_filter", False):
        df.enabled = False


def _load_config(args):
    if getattr(args, "config_file", None):
        try:
            app_config = load_project_config(args.config_file)
        except FileNotFoundError as e:
            print(f"  ✗ {e}")
            sys.exit(2)
        except Exception as e:
            print(f"  ✗ 读取配置文件失败: {e}")
            sys.exit(2)
    else:
        app_config = AppConfig()

    if (
        getattr(args, "config_file", None)
        and app_config.project_name
        and args.project_name
        and not args.check_date
        and _looks_like_date(args.project_name)
    ):
        args.check_date = args.project_name
        args.project_name = None

    _apply_cli_overrides(app_config, args)

    check_date = args.check_date or datetime.now().strftime("%Y-%m-%d")
    app_config.date_filter.target_date = check_date

    if not app_config.project_name:
        print("  ✗ 项目名称缺失。请指定 project_name 或使用 -c 配置文件。")
        sys.exit(2)

    return app_config, check_date


def cmd_check(args):
    app_config, check_date = _load_config(args)

    if getattr(args, "save_config", None):
        try:
            save_project_config(args.save_config, app_config)
            print(f"  ✓ 项目配置已保存到: {os.path.abspath(args.save_config)}")
            print(f"    下次直接运行: python main.py check -c {args.save_config} {check_date}")
        except Exception as e:
            print(f"  ✗ 保存配置失败: {e}")
            sys.exit(2)
        sys.exit(0)

    app_config.ensure_dirs()

    if not args.quiet:
        print()
        print("╔══════════════════════════════════════════════════════════╗")
        print("║       桩基施工记录批量校核工具  v3.0                    ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print()
        print(f"  项目名称: {app_config.project_name}")
        print(f"  检查日期: {check_date}")
        print(f"  记录目录: {os.path.abspath(app_config.input_dir)}")
        print(f"  报告目录: {os.path.abspath(app_config.output_dir)}")
        if app_config.date_filter.enabled:
            print(f"  日期筛选: 已启用（按记录行内成孔/灌注日期逐行筛选 {check_date}）")
        else:
            print(f"  日期筛选: 已关闭（检查全部文件）")
        print()
        print("  校核参数:")
        chk = app_config.check
        print(f"    混凝土方量容许偏差: ±{chk.concrete_volume_tolerance*100:.0f}%")
        print(f"    成孔到灌注最大间隔: {chk.max_pouring_interval_hours:.0f} 小时")
        print(f"    孔深容许负偏差: {chk.min_hole_depth_margin:.2f} m")
        if chk.default_pile_diameter:
            print(f"    默认桩径: {chk.default_pile_diameter:.0f} mm")
        if chk.expected_pile_count:
            print(f"    预期桩数: {chk.expected_pile_count} 根")
        if chk.pile_prefix:
            rng = ""
            if chk.pile_number_start and chk.pile_number_end:
                rng = f" {chk.pile_number_start}~{chk.pile_number_end}"
            print(f"    桩号前缀: {chk.pile_prefix}{rng}（连号检查）")
        print()
        print("  正在读取记录文件...")

    records, errors, file_metas = read_all_records(
        os.path.abspath(app_config.input_dir),
        app_config.check,
        app_config.date_filter if app_config.date_filter.enabled else None,
    )

    included_files = [m for m in file_metas if m.included]
    total_files = len(included_files)
    total_records = len(records)

    if not args.quiet:
        scanned = len(file_metas)
        excluded = scanned - total_files
        print(f"  ✓ 扫描 {scanned} 份文件，纳入 {total_files} 份，排除 {excluded} 份，共 {total_records} 条有效记录")
        if errors:
            print(f"  ⚠ 读取过程中有 {len(errors)} 个错误")
        print()
        print("  正在执行校核...")

    issues = run_all_checks(records, app_config.check)

    if not args.quiet:
        print(f"  ✓ 校核完成，发现 {len(issues)} 条问题")

    report_files = save_reports(
        app_config.project_name, check_date,
        os.path.abspath(app_config.output_dir),
        issues, total_records, total_files,
        errors, file_metas,
        no_xlsx=args.no_xlsx,
    )

    print_console_summary(issues, total_records, total_files, errors, file_metas)

    if report_files:
        print("  报告文件:")
        for fmt, fpath in report_files.items():
            label = {"txt": "TXT 文本报告", "csv": "CSV 明细表", "xlsx": "Excel 工作簿"}.get(fmt, fmt.upper())
            print(f"    [{fmt.upper()}] {label} → {fpath}")
    print()

    if issues:
        print("  💡 如需跟踪整改，可使用 feedback 子命令:")
        print(f"     python main.py feedback {app_config.project_name} {check_date} --feedback <反馈表文件>")
        print()

    if issues:
        sys.exit(1)
    else:
        sys.exit(0)


def cmd_feedback(args):
    app_config, check_date = _load_config(args)
    app_config.ensure_dirs()

    if not args.quiet:
        print()
        print("╔══════════════════════════════════════════════════════════╗")
        print("║       桩基施工记录校核 — 整改跟踪  v3.0               ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print()
        print(f"  项目名称: {app_config.project_name}")
        print(f"  检查日期: {check_date}")
        print(f"  反馈文件: {args.feedback}")
        print()
        print("  正在读取校核报告...")

    report_dir = os.path.abspath(app_config.output_dir)
    safe_date = check_date.replace("/", "-").replace(":", "-")
    base_name = f"{app_config.project_name}_{safe_date}_桩基校核报告"

    csv_path = os.path.join(report_dir, f"{base_name}.csv")
    if not os.path.isfile(csv_path):
        print(f"  ✗ 未找到校核报告 CSV: {csv_path}")
        print("    请先运行 check 命令生成校核报告")
        sys.exit(2)

    if not args.quiet:
        print(f"  ✓ 找到校核报告: {csv_path}")
        print("  正在读取反馈表...")

    feedback_entries, fb_errors = read_feedback(args.feedback)
    if fb_errors:
        for e in fb_errors:
            print(f"  ⚠ {e}")
    if not feedback_entries:
        print("  ✗ 反馈表为空或无法读取")
        sys.exit(2)

    if not args.quiet:
        print(f"  ✓ 读取到 {len(feedback_entries)} 条反馈")

    import csv as csv_mod
    from pile_checker.checker import Issue
    issues = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv_mod.DictReader(f)
        for row in reader:
            issues.append(Issue(
                issue_type="",
                file_name=row.get("文件名", ""),
                pile_no=row.get("桩号", ""),
                reason=row.get("疑似原因", ""),
                suggestion=row.get("建议复核项", ""),
                detail=row.get("详细信息", ""),
                row_index=int(row.get("行号", 0) or 0),
                issue_id=row.get("问题编号", ""),
            ))

    if not issues:
        print("  ✗ 校核报告中无问题记录")
        sys.exit(2)

    merged = merge_feedback(issues, feedback_entries)
    summary = status_summary(merged)

    if not args.quiet:
        print()
        print("  整改状态汇总:")
        for status, count in summary.items():
            icon = {"已整改": "✅", "待复核": "🔄", "仍异常": "❌", "未反馈": "⬜"}.get(status, "❓")
            print(f"    {icon} {status}: {count} 条")
        print()

    fb_report_files = save_feedback_reports(
        app_config.project_name, check_date,
        report_dir, merged,
        no_xlsx=args.no_xlsx,
    )

    print("  整改跟踪报告:")
    for fmt, fpath in fb_report_files.items():
        label = {"txt": "TXT 文本报告", "xlsx": "Excel 工作簿"}.get(fmt, fmt.upper())
        print(f"    [{fmt.upper()}] {label} → {fpath}")
    print()


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "check" or args.command == "run":
        cmd_check(args)
    elif args.command == "feedback":
        cmd_feedback(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
