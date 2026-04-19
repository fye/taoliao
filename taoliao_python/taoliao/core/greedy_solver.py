"""
贪心套料算法 - 以最小化总材料长度为核心目标
"""

from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import copy

from .models import Part, RawMaterial, LossRule, CuttingPlan, NestingConfig
from .loss_calculator import LossCalculator
from .utils import filter_materials_by_spec, get_unique_material_lengths


class GreedyNestingSolver:
    """贪心套料求解器 - 核心目标：最小化总材料长度"""

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

        核心目标：在满足所有零件需求的前提下，最小化总材料长度

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

        # 获取可用原材料长度（升序）
        available_lengths = sorted(set(m.length for m in materials))
        length_to_material = {m.length: m for m in materials}

        # 零件列表
        part_list = [(p.part_no, p.length, p.quantity) for p in parts]

        # 策略：优先使用长材料填充（这是最简单且通常最有效的策略）
        cutting_plans = self._solve_long_first(
            part_list, available_lengths, length_to_material, loss_rule
        )

        return cutting_plans if cutting_plans else []

    def _solve_long_first(
        self,
        part_list: List[Tuple[str, int, int]],
        available_lengths: List[int],
        length_to_material: Dict[int, RawMaterial],
        loss_rule: LossRule
    ) -> Optional[List[CuttingPlan]]:
        """
        策略：优先使用长材料，尽可能填满每一根

        这种策略通常能最小化总材料长度
        """
        remaining_parts = list(part_list)
        cutting_plans = []

        # 按材料长度降序排列
        sorted_lengths = sorted(available_lengths, reverse=True)

        while any(p[2] > 0 for p in remaining_parts):
            active_parts = [p for p in remaining_parts if p[2] > 0]
            if not active_parts:
                break

            best_plan = None
            best_utilization = -1

            # 尝试所有材料，选择利用率最高的
            for length in sorted_lengths:
                raw_mat = length_to_material[length]
                plan = self._fill_material(raw_mat, active_parts, loss_rule)

                if plan is None:
                    continue

                # 选择利用率最高的方案（这通常意味着最少的剩余空间）
                if plan.utilization > best_utilization:
                    best_utilization = plan.utilization
                    best_plan = plan

            if best_plan is None:
                # 没有材料能放下任何零件，使用最长的材料放一个零件
                active_sorted = sorted(active_parts, key=lambda x: x[1], reverse=True)
                part_no, part_length, _ = active_sorted[0]

                for length in sorted_lengths:
                    if length >= part_length + loss_rule.head_tail_loss + loss_rule.single_cut_loss:
                        raw_mat = length_to_material[length]
                        break
                else:
                    raw_mat = length_to_material[sorted_lengths[-1]]

                cut_count = 1
                used_length = part_length
                total_loss = loss_rule.head_tail_loss + loss_rule.single_cut_loss * cut_count
                remaining = raw_mat.length - used_length - total_loss

                best_plan = CuttingPlan(
                    raw_material=raw_mat,
                    parts=[(part_no, part_length, 1)],
                    cut_count=cut_count,
                    single_cut_loss=loss_rule.single_cut_loss,
                    head_tail_loss=loss_rule.head_tail_loss,
                    used_length=used_length,
                    total_loss=total_loss,
                    remaining_length=remaining,
                    utilization=used_length / raw_mat.length
                )

            # 更新剩余零件
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

            # 计算当前已选零件的总长度和总数量
            current_length = sum(p[1] * p[2] for p in selected_parts)
            current_cut_count = sum(p[2] for p in selected_parts)

            # 尝试加入尽可能多的该零件
            max_space = available_length - current_length - loss_rule.single_cut_loss * current_cut_count
            max_qty = min(
                remaining_qty,
                max_space // (part_length + loss_rule.single_cut_loss)
            )

            if max_qty > 0:
                selected_parts.append((part_no, part_length, int(max_qty)))
                part_no_set.add(part_no)

        if not selected_parts:
            return None

        # 切割刀数 = 所有零件数量之和
        cut_count = sum(p[2] for p in selected_parts)
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
