#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桩基施工记录批量校核工具
用法: python main.py <项目名称> <检查日期> [选项]
"""

import sys
import os
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pile_checker.config import AppConfig, CheckConfig
from pile_checker.reader import read_all_records
from pile_checker.checker import run_all_checks
from pile_checker.report import save_reports, print_console_summary


def parse_args():
    parser = argparse.ArgumentParser(
        description="桩基施工记录批量校核工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py 滨江一号项目 2026-06-21
  python main.py 城南家园 2026-06-20 -i ./records -o ./reports
  python main.py 科技园 2026-06-21 --volume-tol 0.08 --max-interval 36
  python main.py 金融中心 2026-06-21 --pile-count 120 --pile-prefix ZK
        """,
    )
    parser.add_argument("project_name", help="项目名称（用于报告文件名）")
    parser.add_argument("check_date", nargs="?", default=None,
                        help="检查日期，格式 YYYY-MM-DD，默认为今天")

    parser.add_argument("-i", "--input-dir", default="./records",
                        help="桩基记录文件所在目录，默认 ./records")
    parser.add_argument("-o", "--output-dir", default="./reports",
                        help="报告输出目录，默认 ./reports")

    parser.add_argument("--volume-tol", type=float, default=0.05,
                        help="混凝土方量差异容许比例，默认 0.05 (即 ±5%%)")
    parser.add_argument("--max-interval", type=float, default=24.0,
                        help="成孔到灌注最大容许间隔（小时），默认 24")
    parser.add_argument("--depth-margin", type=float, default=0.0,
                        help="孔深容许负偏差（米），默认 0")

    parser.add_argument("--pile-count", type=int, default=0,
                        help="预期桩数，用于检查是否缺漏，0 表示不检查")
    parser.add_argument("--pile-prefix", type=str, default="",
                        help="桩号前缀，用于连号检查，如 ZK、ZH 等")

    parser.add_argument("--no-csv", action="store_true",
                        help="不输出 CSV 格式报告")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="安静模式，仅输出结果摘要")

    return parser.parse_args()


def main():
    args = parse_args()

    check_date = args.check_date or datetime.now().strftime("%Y-%m-%d")

    check_config = CheckConfig(
        concrete_volume_tolerance=args.volume_tol,
        max_pouring_interval_hours=args.max_interval,
        min_hole_depth_margin=args.depth_margin,
        expected_pile_count=args.pile_count,
        pile_prefix=args.pile_prefix,
    )

    app_config = AppConfig(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        check=check_config,
    )

    app_config.ensure_dirs()

    if not args.quiet:
        print()
        print("╔══════════════════════════════════════════════════╗")
        print("║          桩基施工记录批量校核工具  v1.0          ║")
        print("╚══════════════════════════════════════════════════╝")
        print()
        print(f"  项目名称: {args.project_name}")
        print(f"  检查日期: {check_date}")
        print(f"  记录目录: {os.path.abspath(app_config.input_dir)}")
        print(f"  报告目录: {os.path.abspath(app_config.output_dir)}")
        print()
        print("  校核参数:")
        print(f"    混凝土方量容许偏差: ±{check_config.concrete_volume_tolerance*100:.0f}%")
        print(f"    成孔到灌注最大间隔: {check_config.max_pouring_interval_hours:.0f} 小时")
        print(f"    孔深容许负偏差: {check_config.min_hole_depth_margin:.2f} m")
        if check_config.expected_pile_count:
            print(f"    预期桩数: {check_config.expected_pile_count} 根")
        if check_config.pile_prefix:
            print(f"    桩号前缀: {check_config.pile_prefix}（连号检查）")
        print()
        print("  正在读取记录文件...")

    input_dir = os.path.abspath(app_config.input_dir)
    records, errors = read_all_records(input_dir, check_config)

    file_set = set(r.source_file for r in records)
    total_files = len(file_set)
    total_records = len(records)

    if not args.quiet:
        print(f"  ✓ 已读取 {total_files} 份文件，{total_records} 条记录")
        if errors:
            print(f"  ⚠ 读取过程中有 {len(errors)} 个错误")
        print()
        print("  正在执行校核...")

    issues = run_all_checks(records, check_config)

    if not args.quiet:
        print(f"  ✓ 校核完成，发现 {len(issues)} 条问题")
        print()

    output_dir = os.path.abspath(app_config.output_dir)
    report_files = save_reports(
        args.project_name, check_date, output_dir,
        issues, total_records, total_files, errors,
    )

    print_console_summary(issues, total_records, total_files, errors)

    print("  报告文件:")
    for fmt, fpath in report_files.items():
        print(f"    [{fmt.upper()}] {fpath}")
    print()

    if issues:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
