"""
套料优化系统结果导出器

在符合规则的前提下，尽可能提高占用率（利用率）

输出格式：
- Sheet 1: 原始需求清单 + 套料方案次数
- Sheet 2: 套料结果详情
- Sheet 3: 原材料汇总
- Sheet 4: 未套料清单
"""

import pandas as pd
from typing import Optional
import os
from datetime import datetime

from core.models import NestingResult, CuttingPlan
from core.utils import normalize_spec


class ResultExporter:
    """结果导出器"""

    def __init__(self, result: NestingResult):
        """
        初始化导出器

        Args:
            result: 套料结果
        """
        self.result = result

    def export(
        self,
        output_path: str,
        original_df: Optional[pd.DataFrame] = None
    ) -> str:
        """
        导出结果到 Excel 文件

        Args:
            output_path: 输出文件路径
            original_df: 原始需求清单 DataFrame（可选）

        Returns:
            实际输出的文件路径
        """
        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 创建 Excel writer
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Sheet 1: 原始需求清单 + 套料方案次数
            self._export_original_demand(writer, original_df)

            # Sheet 2: 套料结果详情
            self._export_cutting_plans(writer)

            # Sheet 3: 原材料汇总
            self._export_material_summary(writer)

            # Sheet 4: 未套料清单
            self._export_unassigned_parts(writer)

        return output_path

    def _export_original_demand(
        self,
        writer: pd.ExcelWriter,
        original_df: Optional[pd.DataFrame]
    ):
        """导出原始需求清单"""
        if original_df is not None:
            df = original_df.copy()
            # 添加套料方案次数列
            df['套料方案次数'] = df['部件号'].map(
                lambda x: self.result.part_plan_count.get(str(x), 0)
            )
        else:
            # 从结果中构建
            data = []
            for part in self.result.original_parts:
                data.append({
                    '部件号': part.part_no,
                    '材质': part.material,
                    '规格': part.spec,
                    '长度(mm)': part.length,
                    '单基数量(件)': part.quantity,
                    '套料方案次数': self.result.part_plan_count.get(part.part_no, 0)
                })
            df = pd.DataFrame(data)

        df.to_excel(writer, sheet_name='原始需求清单', index=False)

    def _export_cutting_plans(self, writer: pd.ExcelWriter):
        """导出套料结果详情"""
        data = []

        for i, plan in enumerate(self.result.cutting_plans, 1):
            row = {
                '序号': i,
                '原材料材质': plan.raw_material.material_type,
                '规格': normalize_spec(plan.raw_material.spec),
                '原材料长度': plan.raw_material.length,
                '切割的部件号': plan.get_parts_description(),
                '切割刀数': plan.cut_count,
                '单刀损': plan.single_cut_loss,
                '两头损耗': plan.head_tail_loss,
                '使用长度': plan.used_length,
                '剩余长度': plan.remaining_length,
                '利用率': f"{plan.utilization:.2%}",
                '损耗比': f"{plan.total_loss / plan.raw_material.length:.2%}" if plan.raw_material.length > 0 else "0.00%",
                '备注': ''
            }
            data.append(row)

        df = pd.DataFrame(data)
        df.to_excel(writer, sheet_name='套料结果', index=False)

    def _export_material_summary(self, writer: pd.ExcelWriter):
        """导出原材料汇总"""
        # 按材质+规格分组，统计每种长度的使用数量
        from collections import defaultdict

        # {(材质, 规格): {长度: 数量}}
        length_counts = defaultdict(lambda: defaultdict(int))
        # {(材质, 规格): {'total_length': 总长度, 'used_length': 使用长度, 'total_loss': 损耗长度}}
        summary_data = defaultdict(lambda: {
            'total_length': 0,
            'used_length': 0,
            'total_loss': 0,
            'count': 0
        })

        for plan in self.result.cutting_plans:
            key = (plan.raw_material.material_type, normalize_spec(plan.raw_material.spec))
            length = plan.raw_material.length

            # 统计每种长度的数量
            length_counts[key][length] += 1

            # 统计汇总数据
            summary_data[key]['total_length'] += length
            summary_data[key]['used_length'] += plan.used_length
            summary_data[key]['total_loss'] += plan.total_loss
            summary_data[key]['count'] += 1

        # 构建输出数据
        data = []
        for (material, spec), length_dict in length_counts.items():
            # 生成套料明细：长度1*根数1 + 长度2*根数2 + ...
            detail_parts = [f"{length}*{count}" for length, count in sorted(length_dict.items())]
            nesting_detail = " + ".join(detail_parts)

            summary = summary_data[(material, spec)]
            total_length = summary['total_length']
            used_length = summary['used_length']
            total_loss = summary['total_loss']
            count = summary['count']

            utilization = used_length / total_length if total_length > 0 else 0
            loss_ratio = total_loss / total_length if total_length > 0 else 0

            row = {
                '材质': material,
                '规格': spec,
                '套料明细': nesting_detail,
                '母材数量': count,
                '总长度': total_length,
                '使用长度': used_length,
                '损耗长度': total_loss,
                '利用率': f"{utilization:.2%}",
                '损耗比': f"{loss_ratio:.2%}"
            }
            data.append(row)

        # 按材质、规格排序
        data.sort(key=lambda x: (x['材质'], x['规格']))

        df = pd.DataFrame(data)
        df.to_excel(writer, sheet_name='原材料汇总', index=False)

    def _export_unassigned_parts(self, writer: pd.ExcelWriter):
        """导出未套料清单"""
        data = []

        for part in self.result.unassigned_parts:
            row = {
                '部件号': part.part_no,
                '材质': part.material,
                '规格': part.spec,
                '长度(mm)': part.length,
                '需求数量': part.quantity,
                '未套料数量': part.quantity,
                '备注': '未找到合适的原材料'
            }
            data.append(row)

        df = pd.DataFrame(data)
        df.to_excel(writer, sheet_name='未套料清单', index=False)

    def print_summary(self):
        """打印结果摘要"""
        print("\n" + "=" * 60)
        print("套料优化结果摘要")
        print("=" * 60)
        print(f"总切割方案数: {len(self.result.cutting_plans)}")
        print(f"总利用率: {self.result.total_utilization:.2%}")
        print(f"总损耗比: {self.result.total_loss_ratio:.2%}")
        print(f"未套料零件数: {len(self.result.unassigned_parts)}")

        if self.result.unassigned_parts:
            print("\n未套料零件:")
            for part in self.result.unassigned_parts[:10]:  # 只显示前10个
                print(f"  - {part.part_no}: {part.spec}, 长度={part.length}mm, 数量={part.quantity}")
            if len(self.result.unassigned_parts) > 10:
                print(f"  ... 还有 {len(self.result.unassigned_parts) - 10} 个未套料零件")

        print("=" * 60 + "\n")


def create_output_path(base_dir: str, prefix: str = "result") -> str:
    """
    创建输出文件路径

    格式: {base_dir}/{timestamp}_{prefix}.xlsx

    Args:
        base_dir: 基础目录
        prefix: 文件名前缀

    Returns:
        输出文件路径
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{prefix}.xlsx"
    return os.path.join(base_dir, filename)