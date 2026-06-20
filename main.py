#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桩基施工记录批量校核工具 v2.0
用法: python main.py <项目名称> <检查日期> [选项]
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="桩基施工记录批量校核工具 v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本用法（检查所有文件）
  python main.py 滨江一号项目 2026-06-21

  # 仅检查当天记录（按日期筛选）
  python main.py 滨江一号项目 2026-06-21 --filter-date

  # 使用项目配置文件
  python main.py -c projects/binjiang.json 2026-06-21

  # 保存当前参数为项目配置
  python main.py 滨江一号项目 --save-config projects/binjiang.json \\
      --pile-prefix ZK --pile-count 120 --default-diameter 800

  # 自定义所有参数
  python main.py 科技园 2026-06-21 -i ./records -o ./reports \\
      --volume-tol 0.08 --max-interval 36 --depth-margin 0.05 \\
      --pile-prefix ZK --pile-count 120 --pile-start 1 --pile-end 120 \\
      --default-diameter 800
        """,
    )

    parser.add_argument("project_name", nargs="?", default=None,
                        help="项目名称（用于报告文件名；使用 -c 时可省略）")
    parser.add_argument("check_date", nargs="?", default=None,
                        help="检查日期，格式 YYYY-MM-DD，默认为今天")

    parser.add_argument("-c", "--config", dest="config_file", default=None,
                        help="项目配置文件路径（JSON），加载后命令行参数可覆盖配置值")
    parser.add_argument("--save-config", dest="save_config", default=None,
                        help="将当前参数保存为项目配置文件（JSON），保存后退出不执行检查")

    parser.add_argument("-i", "--input-dir", default=None,
                        help="桩基记录文件所在目录，默认 ./records")
    parser.add_argument("-o", "--output-dir", default=None,
                        help="报告输出目录，默认 ./reports")

    date_group = parser.add_argument_group("日期筛选")
    date_group.add_argument("--filter-date", action="store_true",
                            help="启用日期筛选，仅检查与 check_date 匹配的文件/记录")
    date_group.add_argument("--date-from-name", action="store_true", default=None,
                            help="按文件名中的日期匹配（默认同时匹配文件名和记录内日期）")
    date_group.add_argument("--date-from-record", action="store_true", default=None,
                            help="按记录内成孔/灌注日期匹配")
    date_group.add_argument("--no-filter", action="store_true",
                            help="禁用日期筛选，检查整个文件夹（默认行为）")

    check_group = parser.add_argument_group("校核参数")
    check_group.add_argument("--volume-tol", type=float, default=None,
                             help="混凝土方量差异容许比例，默认 0.05 (即 ±5%%)")
    check_group.add_argument("--max-interval", type=float, default=None,
                             help="成孔到灌注最大容许间隔（小时），默认 24")
    check_group.add_argument("--depth-margin", type=float, default=None,
                             help="孔深容许负偏差（米），默认 0")
    check_group.add_argument("--default-diameter", type=float, default=None,
                             help="项目统一桩径(mm)，记录中无桩径列时用此值推算理论方量")

    check_group.add_argument("--pile-count", type=int, default=None,
                             help="预期桩数，用于检查是否缺漏，0 表示不检查")
    check_group.add_argument("--pile-prefix", type=str, default=None,
                             help="桩号前缀，用于连号检查，如 ZK、ZH 等")
    check_group.add_argument("--pile-start", type=int, default=None,
                             help="桩号起始编号（连号检查用）")
    check_group.add_argument("--pile-end", type=int, default=None,
                             help="桩号结束编号（连号检查用）")

    out_group = parser.add_argument_group("报告输出")
    out_group.add_argument("--no-xlsx", action="store_true",
                           help="不生成 Excel 格式报告")
    out_group.add_argument("-q", "--quiet", action="store_true",
                           help="安静模式，仅输出结果摘要")

    return parser.parse_args()


def _apply_cli_overrides(app_cfg: AppConfig, args):
    if args.input_dir:
        app_cfg.input_dir = args.input_dir
    if args.output_dir:
        app_cfg.output_dir = args.output_dir

    if args.project_name:
        app_cfg.project_name = args.project_name

    chk = app_cfg.check
    if args.volume_tol is not None:
        chk.concrete_volume_tolerance = args.volume_tol
    if args.max_interval is not None:
        chk.max_pouring_interval_hours = args.max_interval
    if args.depth_margin is not None:
        chk.min_hole_depth_margin = args.depth_margin
    if args.default_diameter is not None:
        chk.default_pile_diameter = args.default_diameter
    if args.pile_count is not None:
        chk.expected_pile_count = args.pile_count
    if args.pile_prefix is not None:
        chk.pile_prefix = args.pile_prefix
    if args.pile_start is not None:
        chk.pile_number_start = args.pile_start
    if args.pile_end is not None:
        chk.pile_number_end = args.pile_end

    df = app_cfg.date_filter
    if args.filter_date:
        df.enabled = True
    if args.no_filter:
        df.enabled = False
    if args.date_from_name:
        df.match_from_filename = True
        df.match_from_record = False
    if args.date_from_record:
        df.match_from_filename = False
        df.match_from_record = True


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


def main():
    args = parse_args()

    if args.config_file:
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
        args.config_file
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
        print("  ✗ 项目名称缺失。请指定 project_name 参数或使用 -c 项目配置文件。")
        sys.exit(2)

    if args.save_config:
        try:
            save_project_config(args.save_config, app_config)
            print(f"  ✓ 项目配置已保存到: {os.path.abspath(args.save_config)}")
            print(f"    下次直接运行: python main.py -c {args.save_config} {check_date}")
        except Exception as e:
            print(f"  ✗ 保存配置失败: {e}")
            sys.exit(2)
        sys.exit(0)

    app_config.ensure_dirs()

    if not args.quiet:
        print()
        print("╔══════════════════════════════════════════════════════════╗")
        print("║       桩基施工记录批量校核工具  v2.0                    ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print()
        print(f"  项目名称: {app_config.project_name}")
        print(f"  检查日期: {check_date}")
        print(f"  记录目录: {os.path.abspath(app_config.input_dir)}")
        print(f"  报告目录: {os.path.abspath(app_config.output_dir)}")
        if app_config.date_filter.enabled:
            modes = []
            if app_config.date_filter.match_from_filename:
                modes.append("文件名")
            if app_config.date_filter.match_from_record:
                modes.append("记录内日期")
            print(f"  日期筛选: 已启用（按 {' + '.join(modes)} 匹配 {check_date}）")
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
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
