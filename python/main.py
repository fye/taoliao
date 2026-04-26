#!/usr/bin/env python3
"""
套料优化系统 CLI 入口

在符合规则的前提下，尽可能提高占用率（利用率）

用法:
    python main.py
    python main.py --demand ../docs/需求清单.xlsx --market ../docs/角钢市场清单.xlsx
    python main.py --help
"""

import argparse
import sys
import os
from datetime import datetime

# 添加当前目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.models import NestingConfig
from core.loss_calculator import LossCalculator
from core.optimizer import MIPOptimizer
from data.loader import DataLoader
from data.exporter import ResultExporter, create_output_path
from config.settings import create_custom_settings


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='套料优化系统 - 电力行业角钢下料优化求解',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 使用默认路径
    python main.py

    # 指定输入文件
    python main.py --demand ../docs/需求清单.xlsx --market ../docs/角钢市场清单.xlsx

    # 指定输出路径
    python main.py --output ../output/result.xlsx

    # 自定义约束参数
    python main.py --max-parts 3 --max-materials 5 --max-remainder 1000
        """
    )

    # 输入文件参数
    parser.add_argument(
        '--demand', '-d',
        default='../docs/需求清单.xlsx',
        help='需求清单 Excel 文件路径 (默认: ../docs/需求清单.xlsx)'
    )
    parser.add_argument(
        '--market', '-m',
        default='../docs/角钢市场清单.xlsx',
        help='市场清单 Excel 文件路径 (默认: ../docs/角钢市场清单.xlsx)'
    )
    parser.add_argument(
        '--loss-rules', '-l',
        default='../docs/损耗规则.xlsx',
        help='损耗规则 Excel 文件路径 (默认: ../docs/损耗规则.xlsx)'
    )

    # 输出文件参数
    parser.add_argument(
        '--output', '-o',
        default=None,
        help='输出 Excel 文件路径 (默认: ../output/{timestamp}_result.xlsx)'
    )

    # 约束参数
    parser.add_argument(
        '--max-parts',
        type=int,
        default=3,
        help='单根原材料零件号上限（硬约束）(默认: 3)'
    )
    parser.add_argument(
        '--max-materials',
        type=int,
        default=5,
        help='单零件号原材料上限（软约束，可超过）(默认: 5)'
    )

    # 求解参数
    parser.add_argument(
        '--time-limit',
        type=int,
        default=3600,
        help='MIP 求解时间限制(秒) (默认: 3600)'
    )
    parser.add_argument(
        '--mip-threshold',
        type=int,
        default=30,
        help='使用 MIP 求解的零件数阈值 (默认: 30)'
    )

    # 其他参数
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='显示详细输出'
    )

    return parser.parse_args()


def resolve_path(path: str) -> str:
    """解析文件路径（支持相对路径）"""
    if not os.path.isabs(path):
        # 相对于脚本所在目录
        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, path)
    return os.path.normpath(path)


def main():
    """主函数"""
    args = parse_args()

    # 解析文件路径
    demand_path = resolve_path(args.demand)
    market_path = resolve_path(args.market)
    loss_rules_path = resolve_path(args.loss_rules)

    # 设置输出路径
    if args.output:
        output_path = resolve_path(args.output)
    else:
        output_dir = resolve_path('../output')
        output_path = create_output_path(output_dir, 'result')

    # 打印配置信息
    print("\n" + "=" * 60)
    print("套料优化系统")
    print("=" * 60)
    print(f"需求清单: {demand_path}")
    print(f"市场清单: {market_path}")
    print(f"损耗规则: {loss_rules_path}")
    print(f"输出路径: {output_path}")
    print(f"\n约束参数:")
    print(f"  单根原材料零件号上限: {args.max_parts}（硬约束）")
    print(f"  单零件号原材料上限: {args.max_materials}（软约束，可超过）")
    print("=" * 60 + "\n")

    # 检查输入文件是否存在
    for path, name in [(demand_path, '需求清单'), (market_path, '市场清单'), (loss_rules_path, '损耗规则')]:
        if not os.path.exists(path):
            print(f"错误: {name}文件不存在: {path}")
            sys.exit(1)

    try:
        # 1. 加载数据
        print("正在加载数据...")
        loader = DataLoader()
        parts = loader.load_parts(demand_path)
        materials = loader.load_materials(market_path)
        loss_rules = loader.load_loss_rules(loss_rules_path)

        print(f"  零件数: {len(parts)}")
        print(f"  原材料数: {len(materials)}")
        print(f"  损耗规则数: {len(loss_rules)}")

        # 2. 创建配置
        config = NestingConfig(
            max_parts_per_material=args.max_parts,
            max_materials_per_part=args.max_materials,
            time_limit=args.time_limit,
            mip_threshold=args.mip_threshold
        )

        # 3. 创建损耗计算器
        loss_calculator = LossCalculator(loss_rules)

        # 4. 创建优化器并求解
        print("\n正在优化求解...")
        optimizer = MIPOptimizer(loss_calculator, config)
        result = optimizer.solve(parts, materials)

        # 5. 导出结果
        print("\n正在导出结果...")
        exporter = ResultExporter(result)
        exporter.export(output_path, loader.get_raw_parts_df())

        # 6. 打印摘要
        exporter.print_summary()

        print(f"结果已保存到: {output_path}")

    except Exception as e:
        print(f"\n错误: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()