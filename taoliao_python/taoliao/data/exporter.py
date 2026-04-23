"""
结果导出器
"""

import pandas as pd
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime

from ..core.models import NestingResult, CuttingPlan, Part


class ResultExporter:
    """结果导出器"""

    def __init__(self, result: NestingResult):
        """
        初始化导出器

        Args:
            result: 套料结果
        """
        self.result = result

    def export(self, output_path: str, original_parts_df: Optional[pd.DataFrame] = None) -> str:
        """
        导出结果到Excel文件

        Args:
            output_path: 输出文件路径
            original_parts_df: 原始零件数据DataFrame（可选）

        Returns:
            实际输出文件路径
        """
        # 确保输出目录存在
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 创建Excel写入器
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Sheet 1: 原始需求清单
            self._write_original_parts(writer, original_parts_df)

            # Sheet 2: 套料结果
            self._write_cutting_plans(writer)

            # Sheet 3: 原材料汇总
            self._write_material_summary(writer)

            # Sheet 4: 未套料零部件
            self._write_unmatched_parts(writer)

        return str(output_path)

    def _write_original_parts(self, writer: pd.ExcelWriter, original_parts_df: Optional[pd.DataFrame]):
        """写入原始需求清单"""
        if original_parts_df is not None:
            original_parts_df.to_excel(writer, sheet_name='原始需求清单', index=False)
        else:
            # 从结果中构建
            data = []
            for part in self.result.original_parts:
                data.append({
                    '段号(只读)': part.segment_no,
                    '部件号': part.part_no,
                    '材质': part.material,
                    '规格': part.spec,
                    '长度(mm)': part.length,
                    '宽度(mm)': part.width,
                    '单基数量(件)': part.quantity,
                    '单件重量(kg)': part.weight,
                    '单件孔数': part.holes,
                    '备注': part.remark
                })
            df = pd.DataFrame(data)
            df.to_excel(writer, sheet_name='原始需求清单', index=False)

    def _write_cutting_plans(self, writer: pd.ExcelWriter):
        """写入套料结果"""
        data = []
        for i, plan in enumerate(self.result.cutting_plans, 1):
            data.append({
                '序号': i,
                '原材料材质': plan.raw_material.material_type,
                '规格': plan.raw_material.spec,
                '原材料长度': plan.raw_material.length,
                '切割的部件号': plan.parts_description,
                '切割刀数': plan.cut_count,
                '单刀损': plan.single_cut_loss,
                '两头损耗': plan.head_tail_loss,
                '使用长度': plan.used_length,
                '剩余长度': plan.remaining_length,
                '利用率': f'{plan.utilization * 100:.2f}%',
                '损耗比': f'{plan.loss_ratio * 100:.2f}%',
                '备注': ''
            })

        df = pd.DataFrame(data)
        df.to_excel(writer, sheet_name='套料结果', index=False)

    def _write_material_summary(self, writer: pd.ExcelWriter):
        """写入原材料汇总"""
        # 先统计每种材质规格下，不同长度的使用数量
        length_distribution: Dict[Tuple[str, str], Dict[int, int]] = {}
        for plan in self.result.cutting_plans:
            key = (plan.raw_material.material_type, plan.raw_material.spec)
            length = plan.raw_material.length
            if key not in length_distribution:
                length_distribution[key] = {}
            length_distribution[key][length] = length_distribution[key].get(length, 0) + 1

        data = []
        for (material_type, spec), stats in self.result.material_summary.items():
            # 格式化长度分布：套料长度 * 个数，多个用 + 拼接
            length_stats = length_distribution.get((material_type, spec), {})
            # 按长度降序排列
            sorted_lengths = sorted(length_stats.items(), key=lambda x: x[0], reverse=True)
            length_detail = ' + '.join(f'{length} * {count}' for length, count in sorted_lengths)

            data.append({
                '材质': material_type,
                '规格': spec,
                '套料明细': length_detail,
                '母材数量': stats['count'],
                '总长度': stats['total_length'],
                '使用长度': stats['total_used'],
                '损耗长度': stats['total_loss'],
                '利用率': f'{stats["utilization"] * 100:.2f}%',
                '损耗比': f'{stats["loss_ratio"] * 100:.2f}%'
            })

        df = pd.DataFrame(data)

        # 按材质和规格排序
        if not df.empty:
            df = df.sort_values(['材质', '规格'])

        df.to_excel(writer, sheet_name='原材料汇总', index=False)

    def _write_unmatched_parts(self, writer: pd.ExcelWriter):
        """写入未套料零部件"""
        data = []
        for part in self.result.unmatched_parts:
            data.append({
                '段号(只读)': part.segment_no,
                '部件号': part.part_no,
                '材质': part.material,
                '规格': part.spec,
                '长度(mm)': part.length,
                '宽度(mm)': part.width,
                '未套料数量(件)': part.quantity,
                '单件重量(kg)': part.weight,
                '单件孔数': part.holes,
                '备注': part.remark
            })

        df = pd.DataFrame(data)
        if not df.empty:
            df.to_excel(writer, sheet_name='未套料零部件', index=False)
        else:
            # 即使没有未套料零部件，也创建一个空的sheet
            pd.DataFrame({'说明': ['无未套料零部件']}).to_excel(
                writer, sheet_name='未套料零部件', index=False
            )

    def print_summary(self):
        """打印结果摘要"""
        print("\n" + "=" * 60)
        print("套料结果摘要")
        print("=" * 60)

        print(f"\n总切割方案数: {len(self.result.cutting_plans)}")
        print(f"总利用率: {self.result.total_utilization * 100:.2f}%")
        print(f"总损耗比: {self.result.total_loss_ratio * 100:.2f}%")

        print("\n原材料使用情况:")
        print("-" * 60)
        for (material_type, spec), stats in self.result.material_summary.items():
            print(f"  {material_type} {spec}:")
            print(f"    数量: {stats['count']} 根")
            print(f"    利用率: {stats['utilization'] * 100:.2f}%")
            print(f"    损耗比: {stats['loss_ratio'] * 100:.2f}%")

        print("\n" + "=" * 60)
