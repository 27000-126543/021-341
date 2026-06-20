#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桩基施工记录批量校核工具 v4.0
子命令:
  check    - 批量校核桩基记录
  feedback - 导入施工员反馈表，生成整改跟踪闭环汇总
  export   - 一键打包交接资料（报告 + 配置快照 + 反馈模板 + 文件清单）
  history  - 多日复查视图：查看问题新增/持续/消失，生成日报汇总
  archive  - 归档台账视图：查看各项目各日期资料齐全度，导出台账表
"""

import sys
import os
import argparse
import csv as csv_mod
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pile_checker.config import (
    AppConfig, CheckConfig, DateFilter,
    load_project_config, save_project_config,
)
from pile_checker.reader import read_all_records
from pile_checker.checker import run_all_checks, Issue, ISSUE_TYPES
from pile_checker.config import ISSUE_SEVERITY
from pile_checker.report import save_reports, print_console_summary
from pile_checker.feedback import (
    read_feedback, merge_feedback, status_summary,
    save_feedback_reports,
)
from pile_checker.export import build_handover_package, load_run_params
from pile_checker.history import (
    build_history, find_persistent_issues, save_history_reports,
)
from pile_checker.archive import scan_archive, save_archive_reports


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
    parser.add_argument("--no-export", action="store_true",
                        help="不自动打包交接资料（默认 check 完成后自动打包）")
    parser.add_argument("--no-zip", action="store_true",
                        help="交接包不生成 ZIP 压缩包")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="安静模式")


def _add_feedback_args(parser):
    parser.add_argument("--feedback", required=True,
                        help="施工员反馈表文件路径（CSV 或 Excel）")
    parser.add_argument("--no-xlsx", action="store_true",
                        help="不生成 Excel 格式整改报告")
    parser.add_argument("--no-export", action="store_true",
                        help="不自动打包交接资料")
    parser.add_argument("--no-zip", action="store_true",
                        help="交接包不生成 ZIP 压缩包")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="安静模式")


def _add_history_args(parser):
    parser.add_argument("--from", dest="from_date", default=None,
                        help="起始日期 YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", default=None,
                        help="结束日期 YYYY-MM-DD")
    parser.add_argument("--persistent-days", type=int, default=2,
                        help="连续多少天未关闭算为持续问题，默认 2 天")
    parser.add_argument("--no-xlsx", action="store_true",
                        help="不生成 Excel 格式报告")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="安静模式")


def _add_export_args(parser):
    parser.add_argument("--no-zip", action="store_true",
                        help="不生成 ZIP 压缩包")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="安静模式")


def _add_archive_args(parser):
    parser.add_argument("--no-xlsx", action="store_true",
                        help="不生成 Excel 格式台账")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="安静模式")


def build_parser():
    parser = argparse.ArgumentParser(
        description="桩基施工记录批量校核工具 v4.0",
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
  python main.py check 滨江一号 --save-config projects/滨江一号.json --pile-prefix ZK
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

    p_history = sub.add_parser("history", help="多日复查视图",
                               formatter_class=argparse.RawDescriptionHelpFormatter,
                               epilog="""
示例:
  python main.py history 滨江一号 --from 2026-06-15 --to 2026-06-21
  python main.py history -c projects/滨江一号.json --from 2026-06-01 --persistent-days 3
                               """)
    _add_common_args(p_history)
    _add_history_args(p_history)

    p_export = sub.add_parser("export", help="一键打包交接资料",
                             formatter_class=argparse.RawDescriptionHelpFormatter,
                             epilog="""
示例:
  python main.py export 滨江一号 2026-06-21
  python main.py export -c projects/滨江一号.json 2026-06-21
                             """)
    _add_common_args(p_export)
    _add_export_args(p_export)

    p_archive = sub.add_parser("archive", help="归档台账视图，查看各日期资料齐全度",
                               formatter_class=argparse.RawDescriptionHelpFormatter,
                               epilog="""
示例:
  python main.py archive 滨江一号
  python main.py archive -c projects/滨江一号.json
  python main.py archive                    # 查看所有项目台账
                               """)
    _add_common_args(p_archive)
    _add_archive_args(p_archive)

    p_run = sub.add_parser("run", help="[兼容] 等同于 check",
                           formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_common_args(p_run)
    _add_check_args(p_run)

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


def _load_config(args, require_date: bool = True):
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

    check_date = None
    if require_date:
        check_date = args.check_date or datetime.now().strftime("%Y-%m-%d")
        app_config.date_filter.target_date = check_date

    if require_date and not app_config.project_name:
        print("  ✗ 项目名称缺失。请指定 project_name 或使用 -c 配置文件。")
        sys.exit(2)

    return app_config, check_date


def _load_issues_from_report_csv(csv_path: str) -> list:
    issues = []
    if not os.path.isfile(csv_path):
        return issues
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv_mod.DictReader(f)
        if not reader.fieldnames:
            return issues

        type_reverse = {v: k for k, v in ISSUE_TYPES.items()}
        for row in reader:
            itype_label = str(row.get("问题类型", "")).strip()
            itype_key = type_reverse.get(itype_label, itype_label) or "field_missing"
            issue = Issue(
                issue_type=itype_key,
                file_name=str(row.get("文件名", "")).strip(),
                pile_no=str(row.get("桩号", "")).strip(),
                reason=str(row.get("疑似原因", "")).strip(),
                suggestion=str(row.get("建议复核项", "")).strip(),
                detail=str(row.get("详细信息", "")).strip(),
                row_index=int(row.get("行号", 0) or 0),
                issue_id=str(row.get("问题编号", "")).strip(),
            )
            issues.append(issue)
    return issues


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
        print("║       桩基施工记录批量校核工具  v4.0                    ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print()
        print(f"  项目名称: {app_config.project_name}")
        print(f"  检查日期: {check_date}")
        print(f"  记录目录: {os.path.abspath(app_config.input_dir)}")
        print(f"  报告目录: {os.path.abspath(app_config.output_dir)}")
        if app_config.date_filter.enabled:
            print(f"  日期筛选: 已启用（成孔或灌注任一命中 {check_date} 即纳入）")
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
        total_filtered = sum(m.rows_filtered_by_date for m in file_metas)
        print(f"  ✓ 扫描 {scanned} 份文件，纳入 {total_files} 份，排除 {excluded} 份，共 {total_records} 条有效记录")
        if total_filtered > 0:
            print(f"  ※ 日期筛选共排除非当天记录 {total_filtered} 条")
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

    if not getattr(args, "no_export", False) and report_files:
        print("  正在打包交接资料...")
        try:
            handover = build_handover_package(
                project_name=app_config.project_name,
                check_date=check_date,
                output_dir=os.path.abspath(app_config.output_dir),
                app_config=app_config,
                report_files=report_files,
                file_metas=file_metas,
                include_zip=not getattr(args, "no_zip", False),
            )
            print("  交接资料:")
            for key, fpath in handover.items():
                if key == "zip":
                    print(f"    [ZIP] 压缩包 → {fpath}")
                elif key.startswith("report_"):
                    continue
                else:
                    label = {
                        "feedback_template": "反馈表模板",
                        "config_snapshot": "配置快照",
                        "readme": "交接说明",
                        "file_manifest": "文件清单",
                    }.get(key, key)
                    print(f"    [FILE] {label} → {fpath}")
            if os.path.isdir(handover.get("readme", "")):
                pass
            elif "readme" in handover:
                base_dir = os.path.dirname(handover["readme"])
                print(f"    [DIR] 交接包目录 → {base_dir}")
            print()
        except Exception as e:
            print(f"  ⚠ 打包交接资料失败: {e}")

    if issues:
        print("  💡 整改闭环:")
        print(f"     1) 将反馈模板发给施工员，按问题编号逐条填写")
        print(f"     2) 回收反馈表后运行:")
        print(f"        python main.py feedback {app_config.project_name} {check_date} --feedback <反馈表文件>")
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
        print("║       桩基施工记录校核 — 整改跟踪  v4.0               ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print()
        print(f"  项目名称: {app_config.project_name}")
        print(f"  检查日期: {check_date}")
        print(f"  反馈文件: {args.feedback}")
        print()

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

    issues = _load_issues_from_report_csv(csv_path)
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

    if not getattr(args, "no_export", False):
        report_files = {}
        for ext in ("txt", "csv", "xlsx"):
            fpath = os.path.join(report_dir, f"{base_name}.{ext}")
            if os.path.isfile(fpath):
                report_files[ext] = fpath
        if report_files:
            print("  正在打包交接资料（含整改跟踪）...")
            try:
                handover = build_handover_package(
                    project_name=app_config.project_name,
                    check_date=check_date,
                    output_dir=report_dir,
                    app_config=app_config,
                    report_files=report_files,
                    feedback_report_files=fb_report_files,
                    include_zip=not getattr(args, "no_zip", False),
                )
                print("  交接资料:")
                for key, fpath in handover.items():
                    if key == "zip":
                        print(f"    [ZIP] 压缩包 → {fpath}")
                    elif key.startswith("report_") or key.startswith("feedback_"):
                        continue
                    else:
                        label = {
                            "feedback_template": "反馈表模板",
                            "config_snapshot": "配置快照",
                            "readme": "交接说明",
                            "file_manifest": "文件清单",
                        }.get(key, key)
                        print(f"    [FILE] {label} → {fpath}")
                print()
            except Exception as e:
                print(f"  ⚠ 打包交接资料失败: {e}")


def cmd_history(args):
    app_config, check_date = _load_config(args)
    app_config.ensure_dirs()

    if not args.quiet:
        print()
        print("╔══════════════════════════════════════════════════════════╗")
        print("║       桩基施工记录校核 — 多日复查视图  v4.0           ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print()
        print(f"  项目名称: {app_config.project_name}")
        if args.from_date or args.to_date:
            print(f"  日期范围: {args.from_date or '最早'} ~ {args.to_date or '最新'}")
        print(f"  报告目录: {os.path.abspath(app_config.output_dir)}")
        print()
        print("  正在分析历史报告...")

    report_dir = os.path.abspath(app_config.output_dir)
    history = build_history(report_dir, app_config.project_name, args.from_date, args.to_date)

    if not history:
        print("  ✗ 未找到可用的历史校核报告（需要有 *_桩基校核报告.csv 文件）")
        print("    请先运行 check 命令生成至少 1 天的报告")
        sys.exit(2)

    persistent, details = find_persistent_issues(
        report_dir,
        project_name=app_config.project_name,
        min_days=args.persistent_days,
        start_date=args.from_date,
        end_date=args.to_date,
    )

    if not args.quiet:
        print(f"  ✓ 分析完成，覆盖 {len(history)} 天，持续问题 {len(persistent)} 条")
        print()

    dates = sorted(history.keys())
    print("  每日概览:")
    print(f"    {'日期':<12}  {'问题':>5}  {'新增':>5}  {'持续':>5}  {'已解决':>6}")
    for d in dates:
        s = history[d]
        print(
            f"    {d:<12}  {s.total_issues:>5}  {len(s.new_issues):>5}  "
            f"{len(s.persistent_issues):>5}  {len(s.resolved_issues):>6}"
        )
    if persistent:
        print()
        print(f"  连续 ≥{args.persistent_days} 天未关闭: {len(persistent)} 条")
        for issue_id, dates_list in sorted(persistent.items(), key=lambda x: -len(x[1]))[:5]:
            snap = details.get(issue_id)
            label = f"[{snap.severity}] {snap.issue_type}" if snap else ""
            print(f"    · {issue_id} {label}  连续{len(dates_list)}天")

    print()

    rep_files = save_history_reports(
        app_config.project_name, report_dir,
        history, persistent, details,
        args.from_date or "", args.to_date or "",
        no_xlsx=args.no_xlsx,
    )
    print("  历史报告:")
    for fmt, fpath in rep_files.items():
        label = {"txt": "TXT 文本报告", "xlsx": "Excel 工作簿"}.get(fmt, fmt.upper())
        print(f"    [{fmt.upper()}] {label} → {fpath}")
    print()


def cmd_export(args):
    app_config, check_date = _load_config(args)
    app_config.ensure_dirs()

    if not args.quiet:
        print()
        print("╔══════════════════════════════════════════════════════════╗")
        print("║       桩基施工记录校核 — 交接资料打包  v4.0           ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print()
        print(f"  项目名称: {app_config.project_name}")
        print(f"  检查日期: {check_date}")
        print()

    report_dir = os.path.abspath(app_config.output_dir)
    safe_date = check_date.replace("/", "-").replace(":", "-")

    package_dir = os.path.join(report_dir, f"{app_config.project_name}_{safe_date}_交接包")
    run_params = load_run_params(package_dir) if os.path.isdir(package_dir) else None

    if run_params:
        print(f"  ✓ 检测到历史运行参数（生成于 {run_params.get('generated_at', '')}）")
        print(f"    筛选口径: {'日期筛选' if run_params.get('filter_date') else '未筛选'}")
        print(f"    桩号前缀: {run_params.get('pile_prefix', '')}")
        if not args.quiet:
            print()
    else:
        print("  ⚠ 未检测到历史运行参数，将使用当前配置重新生成")
        print("    （建议先运行 check 命令后再打包，确保参数一致）")
        print()

    base_name = f"{app_config.project_name}_{safe_date}_桩基校核报告"

    report_files = {}
    for ext in ("txt", "csv", "xlsx"):
        fpath = os.path.join(report_dir, f"{base_name}.{ext}")
        if os.path.isfile(fpath):
            report_files[ext] = fpath

    fb_base = f"{app_config.project_name}_{safe_date}_整改跟踪报告"
    feedback_files = {}
    for ext in ("txt", "xlsx"):
        fpath = os.path.join(report_dir, f"{fb_base}.{ext}")
        if os.path.isfile(fpath):
            feedback_files[ext] = fpath

    if not report_files:
        print(f"  ✗ 未找到 {check_date} 的校核报告，请先运行 check 命令")
        sys.exit(2)

    file_metas = None
    if not run_params:
        records, errors, file_metas = read_all_records(
            os.path.abspath(app_config.input_dir),
            app_config.check,
            None,
        )

    print("  正在打包交接资料...")
    handover = build_handover_package(
        project_name=app_config.project_name,
        check_date=check_date,
        output_dir=report_dir,
        app_config=app_config,
        report_files=report_files,
        feedback_report_files=feedback_files if feedback_files else None,
        file_metas=file_metas,
        include_zip=not getattr(args, "no_zip", False),
        run_params=run_params,
        readonly=run_params is not None,
    )
    print("  交接资料:")
    for key, fpath in handover.items():
        if key == "zip":
            print(f"    [ZIP] 压缩包 → {fpath}")
        elif key.startswith("report_") or key.startswith("feedback_"):
            continue
        else:
            label = {
                "feedback_template": "反馈表模板",
                "config_snapshot": "配置快照",
                "readme": "交接说明",
                "file_manifest": "文件清单",
            }.get(key, key)
            print(f"    [FILE] {label} → {fpath}")
    if "readme" in handover:
        base_dir = os.path.dirname(handover["readme"])
        print(f"    [DIR] 交接包目录 → {base_dir}")
    print()


def cmd_archive(args):
    app_config, _ = _load_config(args, require_date=False)
    app_config.ensure_dirs()
    report_dir = os.path.abspath(app_config.output_dir)

    if not args.quiet:
        print()
        print("╔══════════════════════════════════════════════════════════╗")
        print("║       桩基施工记录校核 — 归档台账视图  v4.0           ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print()
        print(f"  报告目录: {report_dir}")
        if app_config.project_name and app_config.project_name != "项目":
            print(f"  项目过滤: {app_config.project_name}")
        print()
        print("  正在扫描归档资料...")

    archive_data = scan_archive(report_dir)
    proj_filter = app_config.project_name if app_config.project_name and app_config.project_name != "项目" else None

    if not archive_data:
        print("  ✗ 未找到任何归档资料，请先运行 check 命令生成报告")
        sys.exit(2)

    if proj_filter and proj_filter not in archive_data:
        print(f"  ✗ 未找到项目 [{proj_filter}] 的归档资料")
        print(f"    可用项目: {', '.join(archive_data.keys())}")
        sys.exit(2)

    rep_files = save_archive_reports(
        proj_filter,
        report_dir,
        archive_data,
        no_xlsx=args.no_xlsx,
    )

    if proj_filter and proj_filter in archive_data:
        dates = sorted(archive_data[proj_filter].keys())
        total = len(dates)
        complete = sum(1 for d in dates if archive_data[proj_filter][d].completeness >= 0.75)
        missing = [d for d in dates if archive_data[proj_filter][d].completeness < 0.75]
        print(f"  ✓ 扫描完成，项目 [{proj_filter}] 共 {total} 天资料")
        print(f"    完整度 ≥75%: {complete} 天")
        if missing:
            print(f"    需补资料: {', '.join(missing[:5])}")
            if len(missing) > 5:
                print(f"             等共 {len(missing)} 天")
        print()
    else:
        project_count = len(archive_data)
        total_days = sum(len(v) for v in archive_data.values())
        print(f"  ✓ 扫描完成，共 {project_count} 个项目，{total_days} 天资料")
        for proj in sorted(archive_data.keys())[:5]:
            dates = sorted(archive_data[proj].keys())
            print(f"    · {proj}: {len(dates)} 天")
        if project_count > 5:
            print(f"      等共 {project_count} 个项目")
        print()

    print("  归档台账:")
    for fmt, fpath in rep_files.items():
        label = {"txt": "TXT 文本台账", "xlsx": "Excel 工作簿"}.get(fmt, fmt.upper())
        print(f"    [{fmt.upper()}] {label} → {fpath}")
    print()


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command in ("check", "run"):
        cmd_check(args)
    elif args.command == "feedback":
        cmd_feedback(args)
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "archive":
        cmd_archive(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
