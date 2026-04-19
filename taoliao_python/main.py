#!/usr/bin/env python3
"""
套料优化系统主入口
"""

import argparse
import sys
from pathlib import Path

# 禁用输出缓冲
import os
os.environ['PYTHONUNBUFFERED'] = '1'

from taoliao.core import NestingOptimizer, NestingConfig
from taoliao.data import DataLoader, ResultExporter
from taoliao.config import Settings
from collections import defaultdict


def validate_result(result, original_parts):
    """
    校验套料结果是否与原始需求一致

    Args:
        result: 套料结果
        original_parts: 原始零件列表

    Returns:
        校验结果字典
    """
    # 统计原始需求中的零件数量
    original_counts = defaultdict(int)
    for part in original_parts:
        key = (part.part_no, part.length)
        original_counts[key] += part.quantity

    # 统计套料结果中的零件数量
    result_counts = defaultdict(int)
    for plan in result.cutting_plans:
        for part_no, length, qty in plan.parts:
            key = (part_no, length)
            result_counts[key] += qty

    # 比较
    details = []
    all_keys = set(original_counts.keys()) | set(result_counts.keys())

    for key in sorted(all_keys):
        part_no, length = key
        orig_qty = original_counts.get(key, 0)
        result_qty = result_counts.get(key, 0)

        if orig_qty != result_qty:
            diff = result_qty - orig_qty
            sign = '+' if diff > 0 else ''
            details.append(f"部件号 {part_no} (长度{length}mm): 需求{orig_qty}个, 套料{result_qty}个 ({sign}{diff})")

    if details:
        return {
            'valid': False,
            'message': '零部件数量不一致',
            'details': details
        }

    return {'valid': True}


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='电力行业角钢套料优化系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py
  python main.py --demand docs/需求清单.xlsx --output output/result.xlsx
  python main.py --max-parts 3 --max-materials 5 --max-remainder 1000
        """
    )

    parser.add_argument(
        '--demand', '-d',
        type=str,
        default=Settings.default_demand_file,
        help=f'需求清单文件路径 (默认: {Settings.default_demand_file})'
    )

    parser.add_argument(
        '--market', '-m',
        type=str,
        default=Settings.default_market_file,
        help=f'市场清单文件路径 (默认: {Settings.default_market_file})'
    )

    parser.add_argument(
        '--loss', '-l',
        type=str,
        default=Settings.default_loss_file,
        help=f'损耗规则文件路径 (默认: {Settings.default_loss_file})'
    )

    parser.add_argument(
        '--output', '-o',
        type=str,
        default=Settings.default_output_file,
        help=f'输出文件路径 (默认: {Settings.default_output_file})'
    )

    parser.add_argument(
        '--max-parts',
        type=int,
        default=Settings.max_parts_per_material,
        help=f'单根原材料最多零件号数 (默认: {Settings.max_parts_per_material})'
    )

    parser.add_argument(
        '--max-materials',
        type=int,
        default=Settings.max_materials_per_part,
        help=f'单零件号最多原材料数 (默认: {Settings.max_materials_per_part})'
    )

    parser.add_argument(
        '--max-remainder',
        type=int,
        default=Settings.max_remainder,
        help=f'余料上限(mm) (默认: {Settings.max_remainder})'
    )

    parser.add_argument(
        '--time-limit',
        type=int,
        default=Settings.solver_time_limit,
        help=f'求解时间限制(秒) (默认: {Settings.solver_time_limit})'
    )

    args = parser.parse_args()

    # 检查输入文件
    for file_path, name in [(args.demand, '需求清单'), (args.market, '市场清单')]:
        if not Path(file_path).exists():
            print(f"错误: {name}文件不存在: {file_path}")
            sys.exit(1)

    # 创建配置
    config = NestingConfig(
        max_parts_per_material=args.max_parts,
        max_materials_per_part=args.max_materials,
        max_remainder=args.max_remainder,
        time_limit=args.time_limit
    )

    print("=" * 60)
    print("电力行业角钢套料优化系统")
    print("=" * 60)
    print(f"\n配置参数:")
    print(f"  单根材料最多零件号: {config.max_parts_per_material}")
    print(f"  单零件号最多原材料: {config.max_materials_per_part}")
    print(f"  余料上限: {config.max_remainder}mm")
    print(f"  求解时间限制: {config.time_limit}秒")

    # 加载数据
    print(f"\n加载数据...")
    loader = DataLoader()

    print(f"  需求清单: {args.demand}")
    parts = loader.load_parts(args.demand)
    print(f"  加载零件数: {len(parts)}")

    print(f"  市场清单: {args.market}")
    materials = loader.load_materials(args.market)
    print(f"  加载原材料数: {len(materials)}")

    # 加载损耗规则
    loss_rules = None
    if Path(args.loss).exists():
        print(f"  损耗规则: {args.loss}")
        loss_rules = loader.load_loss_rules(args.loss)
        print(f"  加载损耗规则数: {len(loss_rules)}")

    # 执行优化
    print(f"\n开始优化...")
    optimizer = NestingOptimizer(config)
    result = optimizer.optimize(parts, materials, loss_rules)

    # 校验套料结果
    print(f"\n校验套料结果...")
    validation_result = validate_result(result, parts)
    if validation_result['valid']:
        print(f"  校验通过: 零部件数量一致")
    else:
        print(f"  校验失败: {validation_result['message']}")
        for detail in validation_result.get('details', []):
            print(f"    {detail}")

    # 获取求解器统计
    stats = optimizer.get_solver_stats()
    if stats:
        print(f"\n求解器统计:")
        print(f"  状态: {stats.status}")
        print(f"  目标值: {stats.objective_value:.0f}mm")
        print(f"  求解时间: {stats.solve_time:.2f}秒")
        print(f"  变量数: {stats.num_variables}")
        print(f"  约束数: {stats.num_constraints}")

    # 导出结果
    print(f"\n导出结果: {args.output}")
    exporter = ResultExporter(result)
    exporter.export(args.output, loader.get_raw_parts_df())
    exporter.print_summary()

    print(f"\n完成! 结果已保存到: {args.output}")


if __name__ == '__main__':
    main()
