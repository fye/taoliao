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

        策略：尝试多种贪心策略，选择总材料长度最小的方案

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

        # 尝试多种策略，选择总材料长度最小的方案
        best_plans = None
        best_total_length = float('inf')

        # 策略1：优先使用最长材料（贪心选择利用率最高的）
        plans1 = self._solve_with_strategy(
            part_list, available_lengths, length_to_material, loss_rule,
            strategy='prefer_long'
        )
        if plans1:
            total1 = sum(p.raw_material.length for p in plans1)
            if total1 < best_total_length:
                best_total_length = total1
                best_plans = plans1

        # 策略2：优先使用最短材料（能放下的前提下）
        plans2 = self._solve_with_strategy(
            part_list, available_lengths, length_to_material, loss_rule,
            strategy='prefer_short'
        )
        if plans2:
            total2 = sum(p.raw_material.length for p in plans2)
            if total2 < best_total_length:
                best_total_length = total2
                best_plans = plans2

        # 策略3：best-fit（选择剩余空间最小的材料）
        plans3 = self._solve_with_strategy(
            part_list, available_lengths, length_to_material, loss_rule,
            strategy='best_fit'
        )
        if plans3:
            total3 = sum(p.raw_material.length for p in plans3)
            if total3 < best_total_length:
                best_total_length = total3
                best_plans = plans3

        # 策略4：固定使用最长材料
        plans4 = self._solve_with_fixed_length(
            part_list, available_lengths, length_to_material, loss_rule
        )
        if plans4:
            total4 = sum(p.raw_material.length for p in plans4)
            if total4 < best_total_length:
                best_total_length = total4
                best_plans = plans4

        return best_plans if best_plans else []

    def _solve_with_strategy(
        self,
        part_list: List[Tuple[str, int, int]],
        available_lengths: List[int],
        length_to_material: Dict[int, RawMaterial],
        loss_rule: LossRule,
        strategy: str
    ) -> Optional[List[CuttingPlan]]:
        """
        使用指定策略求解

        Args:
            part_list: 零件列表 [(部件号, 长度, 数量), ...]
            available_lengths: 可用材料长度
            length_to_material: 长度到材料的映射
            loss_rule: 损耗规则
            strategy: 策略类型 ('prefer_long', 'prefer_short', 'best_fit')

        Returns:
            切割方案列表
        """
        remaining_parts = list(part_list)
        cutting_plans = []

        while any(p[2] > 0 for p in remaining_parts):
            active_parts = [p for p in remaining_parts if p[2] > 0]
            if not active_parts:
                break

            best_plan = None
            best_score = None

            for length in available_lengths:
                raw_mat = length_to_material[length]
                plan = self._fill_material(raw_mat, active_parts, loss_rule)

                if plan is None:
                    continue

                if strategy == 'best_fit':
                    # 选择剩余空间最小的
                    score = -plan.remaining_length  # 负数，越小越好
                elif strategy == 'prefer_long':
                    # 优先使用长材料，同时考虑利用率
                    # 评分 = 利用率 * 100 - 材料长度惩罚
                    score = plan.utilization * 100 - length / 1000
                else:  # prefer_short
                    # 优先使用短材料（能放下的前提下）
                    # 评分 = 利用率 * 100 + (最大长度 - 材料长度) / 1000
                    max_length = max(available_lengths)
                    score = plan.utilization * 100 + (max_length - length) / 1000

                if best_score is None or score > best_score:
                    best_score = score
                    best_plan = plan

            if best_plan is None:
                # 没有材料能放下任何零件，使用最长的材料放一个零件
                active_sorted = sorted(active_parts, key=lambda x: x[1], reverse=True)
                part_no, part_length, _ = active_sorted[0]

                for length in sorted(available_lengths, reverse=True):
                    if length >= part_length + loss_rule.head_tail_loss + loss_rule.single_cut_loss:
                        raw_mat = length_to_material[length]
                        break
                else:
                    raw_mat = length_to_material[available_lengths[-1]]

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

    def _solve_with_fixed_length(
        self,
        part_list: List[Tuple[str, int, int]],
        available_lengths: List[int],
        length_to_material: Dict[int, RawMaterial],
        loss_rule: LossRule
    ) -> Optional[List[CuttingPlan]]:
        """
        策略：固定使用最长材料，直到无法填充

        这种策略通常能最小化总材料长度，因为长材料能容纳更多零件
        """
        max_length = max(available_lengths)
        max_mat = length_to_material[max_length]

        remaining_parts = list(part_list)
        cutting_plans = []

        while any(p[2] > 0 for p in remaining_parts):
            active_parts = [p for p in remaining_parts if p[2] > 0]
            if not active_parts:
                break

            # 先尝试最长材料
            plan = self._fill_material(max_mat, active_parts, loss_rule)

            if plan is None:
                # 最长材料放不下，尝试其他材料
                for length in sorted(available_lengths, reverse=True):
                    if length < max_length:
                        raw_mat = length_to_material[length]
                        plan = self._fill_material(raw_mat, active_parts, loss_rule)
                        if plan:
                            break

            if plan is None:
                # 没有材料能放下任何零件，使用最长的材料放一个零件
                active_sorted = sorted(active_parts, key=lambda x: x[1], reverse=True)
                part_no, part_length, _ = active_sorted[0]

                cut_count = 1
                used_length = part_length
                total_loss = loss_rule.head_tail_loss + loss_rule.single_cut_loss * cut_count
                remaining = max_mat.length - used_length - total_loss

                plan = CuttingPlan(
                    raw_material=max_mat,
                    parts=[(part_no, part_length, 1)],
                    cut_count=cut_count,
                    single_cut_loss=loss_rule.single_cut_loss,
                    head_tail_loss=loss_rule.head_tail_loss,
                    used_length=used_length,
                    total_loss=total_loss,
                    remaining_length=remaining,
                    utilization=used_length / max_mat.length
                )

            # 更新剩余零件
            for part_no, part_length, qty in plan.parts:
                for i, (p_no, p_len, p_qty) in enumerate(remaining_parts):
                    if p_no == part_no and p_len == part_length:
                        remaining_parts[i] = (p_no, p_len, p_qty - qty)
                        break

            cutting_plans.append(plan)

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
