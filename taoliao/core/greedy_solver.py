"""
贪心套料算法 - 作为MIP的回退方案
"""

from typing import List, Dict, Tuple, Optional
from collections import defaultdict

from .models import Part, RawMaterial, LossRule, CuttingPlan, NestingConfig
from .loss_calculator import LossCalculator
from .utils import filter_materials_by_spec, get_unique_material_lengths


class GreedyNestingSolver:
    """贪心套料求解器"""

    def __init__(self, config: NestingConfig, loss_calculator: LossCalculator):
        self.config = config
        self.loss_calculator = loss_calculator

    def solve(
        self,
        parts: List[Part],
        materials: List[RawMaterial],
        spec: str,
        material_type: str
    ) -> List[CuttingPlan]:
        """
        使用贪心算法求解

        Args:
            parts: 零件列表
            materials: 可用原材料列表
            spec: 规格
            material_type: 材质

        Returns:
            切割方案列表
        """
        # 获取损耗规则
        loss_rule = self.loss_calculator.get_loss_rule(spec, material_type)

        # 复制零件列表（带剩余数量）
        remaining_parts = [(p.part_no, p.length, p.quantity) for p in parts]

        # 获取可用原材料长度（按升序排列）
        available_lengths = get_unique_material_lengths(materials)

        # 创建长度到材料的映射
        length_to_material = {m.length: m for m in materials}

        cutting_plans = []

        while any(p[2] > 0 for p in remaining_parts):
            # 过滤出还有需求的零件
            active_parts = [p for p in remaining_parts if p[2] > 0]
            if not active_parts:
                break

            # 选择最优的原材料长度和填充方案
            best_plan = None
            best_utilization = -1

            for length in available_lengths:
                raw_mat = length_to_material.get(length)
                if not raw_mat:
                    continue

                plan = self._fill_material(
                    raw_mat, active_parts, loss_rule
                )

                if plan and plan.utilization > best_utilization:
                    best_utilization = plan.utilization
                    best_plan = plan

            if best_plan is None:
                # 无法填充，使用最长的原材料
                length = available_lengths[-1]
                raw_mat = length_to_material[length]
                # 只放一个最大的零件
                active_parts_sorted = sorted(active_parts, key=lambda x: x[1], reverse=True)
                part_no, part_length, _ = active_parts_sorted[0]

                cut_count = 1
                used_length = part_length
                total_loss = loss_rule.head_tail_loss + loss_rule.single_cut_loss * cut_count
                remaining = length - used_length - total_loss

                best_plan = CuttingPlan(
                    raw_material=raw_mat,
                    parts=[(part_no, part_length, 1)],
                    cut_count=cut_count,
                    single_cut_loss=loss_rule.single_cut_loss,
                    head_tail_loss=loss_rule.head_tail_loss,
                    used_length=used_length,
                    total_loss=total_loss,
                    remaining_length=remaining,
                    utilization=used_length / length
                )

            # 更新剩余零件数量
            for part_no, part_length, qty in best_plan.parts:
                for i, (p_no, p_len, p_qty) in enumerate(remaining_parts):
                    if p_no == part_no and p_len == part_length:
                        remaining_parts[i] = (p_no, p_len, p_qty - qty)
                        break

            cutting_plans.append(best_plan)

        return cutting_plans

    def _fill_material(
        self,
        raw_material: RawMaterial,
        parts: List[Tuple[str, int, int]],
        loss_rule: LossRule
    ) -> Optional[CuttingPlan]:
        """
        贪心填充单根原材料

        Args:
            raw_material: 原材料
            parts: 零件列表 [(部件号, 长度, 剩余数量), ...]
            loss_rule: 损耗规则

        Returns:
            切割方案，如果无法填充则返回None
        """
        available_length = raw_material.length - loss_rule.head_tail_loss

        # 按长度降序排列零件
        sorted_parts = sorted(parts, key=lambda x: x[1], reverse=True)

        selected_parts = []
        part_no_set = set()

        for part_no, part_length, remaining_qty in sorted_parts:
            if remaining_qty <= 0:
                continue

            # 检查零件号限制
            if len(part_no_set) >= self.config.max_parts_per_material:
                if part_no not in part_no_set:
                    continue

            # 计算加入该零件后的长度
            cut_loss = loss_rule.single_cut_loss * (len(selected_parts) + 1) if selected_parts else loss_rule.single_cut_loss
            current_length = sum(p[1] * p[2] for p in selected_parts)

            # 尝试加入尽可能多的该零件
            max_qty = min(
                remaining_qty,
                (available_length - current_length - cut_loss) // part_length
            )

            if max_qty > 0:
                selected_parts.append((part_no, part_length, int(max_qty)))
                part_no_set.add(part_no)

        if not selected_parts:
            return None

        cut_count = len(selected_parts)
        used_length = sum(p[1] * p[2] for p in selected_parts)
        total_loss = loss_rule.head_tail_loss + loss_rule.single_cut_loss * cut_count
        remaining = raw_material.length - used_length - total_loss

        return CuttingPlan(
            raw_material=raw_material,
            parts=selected_parts,
            cut_count=cut_count,
            single_cut_loss=loss_rule.single_cut_loss,
            head_tail_loss=loss_rule.head_tail_loss,
            used_length=used_length,
            total_loss=total_loss,
            remaining_length=remaining,
            utilization=used_length / raw_material.length
        )
