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

        # 后处理优化：重新优化低利用率的方案
        cutting_plans = self._post_optimize(cutting_plans, materials, loss_rule)

        return cutting_plans

    def _post_optimize(
        self,
        cutting_plans: List[CuttingPlan],
        materials: List[RawMaterial],
        loss_rule: LossRule
    ) -> List[CuttingPlan]:
        """
        后处理优化：重新优化低利用率的切割方案

        Args:
            cutting_plans: 原始切割方案列表
            materials: 可用原材料列表
            loss_rule: 损耗规则

        Returns:
            优化后的切割方案列表
        """
        if len(cutting_plans) <= 1:
            return cutting_plans

        # 找出低利用率的方案（<70%）
        low_util_threshold = 0.70
        low_util_indices = set(
            i for i, plan in enumerate(cutting_plans)
            if plan.utilization < low_util_threshold
        )

        if not low_util_indices:
            return cutting_plans

        # 第一步：尝试将低利用率方案的零件填充到高利用率方案的剩余空间
        result_plans = list(cutting_plans)

        for low_idx in sorted(low_util_indices):
            low_plan = result_plans[low_idx]
            if low_plan is None:
                continue

            for part_no, part_length, part_qty in low_plan.parts:
                remaining_qty = part_qty

                for high_idx in range(len(result_plans)):
                    if high_idx in low_util_indices or high_idx == low_idx:
                        continue
                    if remaining_qty <= 0:
                        break

                    high_plan = result_plans[high_idx]
                    if high_plan is None:
                        continue

                    available_space = high_plan.remaining_length - loss_rule.single_cut_loss
                    if available_space < part_length:
                        continue

                    existing_part_nos = set(p[0] for p in high_plan.parts)
                    if len(existing_part_nos) >= self.config.max_parts_per_material:
                        if part_no not in existing_part_nos:
                            continue

                    max_fit = min(remaining_qty, available_space // part_length)
                    if max_fit <= 0:
                        continue

                    new_parts = list(high_plan.parts)
                    found = False
                    for pi, (pn, pl, pq) in enumerate(new_parts):
                        if pn == part_no and pl == part_length:
                            new_parts[pi] = (pn, pl, pq + max_fit)
                            found = True
                            break
                    if not found:
                        new_parts.append((part_no, part_length, max_fit))

                    new_cut_count = len(new_parts)
                    new_used = high_plan.used_length + part_length * max_fit
                    new_total_loss = loss_rule.head_tail_loss + loss_rule.single_cut_loss * new_cut_count
                    new_remaining = high_plan.raw_material.length - new_used - new_total_loss
                    new_utilization = new_used / high_plan.raw_material.length

                    result_plans[high_idx] = CuttingPlan(
                        raw_material=high_plan.raw_material,
                        parts=new_parts,
                        cut_count=new_cut_count,
                        single_cut_loss=loss_rule.single_cut_loss,
                        head_tail_loss=loss_rule.head_tail_loss,
                        used_length=new_used,
                        total_loss=new_total_loss,
                        remaining_length=new_remaining,
                        utilization=new_utilization
                    )

                    remaining_qty -= max_fit

                if remaining_qty < part_qty:
                    if remaining_qty > 0:
                        new_low_parts = [(pn, pl, pq) for pn, pl, pq in low_plan.parts
                                         if not (pn == part_no and pl == part_length)]
                        new_low_parts.append((part_no, part_length, remaining_qty))

                        new_low_used = sum(p[1] * p[2] for p in new_low_parts)
                        new_low_cut_count = len(new_low_parts)
                        new_low_total_loss = loss_rule.head_tail_loss + loss_rule.single_cut_loss * new_low_cut_count
                        new_low_remaining = low_plan.raw_material.length - new_low_used - new_low_total_loss
                        new_low_util = new_low_used / low_plan.raw_material.length if low_plan.raw_material.length > 0 else 0

                        result_plans[low_idx] = CuttingPlan(
                            raw_material=low_plan.raw_material,
                            parts=new_low_parts,
                            cut_count=new_low_cut_count,
                            single_cut_loss=loss_rule.single_cut_loss,
                            head_tail_loss=loss_rule.head_tail_loss,
                            used_length=new_low_used,
                            total_loss=new_low_total_loss,
                            remaining_length=new_low_remaining,
                            utilization=new_low_util
                        )
                    else:
                        result_plans[low_idx] = None

        final_plans = [p for p in result_plans if p is not None]

        new_low_util_indices = set(
            i for i, plan in enumerate(final_plans)
            if plan.utilization < low_util_threshold
        )

        if not new_low_util_indices:
            return final_plans

        # 第二步：收集剩余低利用率方案的零件，重新分配
        low_util_parts: Dict[Tuple[str, int], int] = {}
        for i in new_low_util_indices:
            plan = final_plans[i]
            for part_no, length, qty in plan.parts:
                key = (part_no, length)
                low_util_parts[key] = low_util_parts.get(key, 0) + qty

        if not low_util_parts:
            return final_plans

        high_util_parts: Dict[Tuple[str, int], int] = {}
        for i, plan in enumerate(final_plans):
            if i in new_low_util_indices:
                continue
            for part_no, length, qty in plan.parts:
                key = (part_no, length)
                high_util_parts[key] = high_util_parts.get(key, 0) + qty

        available_lengths = sorted(set(m.length for m in materials))
        length_to_material = {m.length: m for m in materials}

        part_list = [(part_no, length, qty) for (part_no, length), qty in low_util_parts.items()]
        part_list.sort(key=lambda x: x[1], reverse=True)

        new_plans = []
        remaining = list(part_list)

        while any(p[2] > 0 for p in remaining):
            active = [p for p in remaining if p[2] > 0]
            if not active:
                break

            best_plan = None
            best_score = -1

            for length in available_lengths:
                raw_mat = length_to_material[length]
                plan = self._fill_material(raw_mat, active, loss_rule)
                if plan:
                    score = plan.utilization * 10000 - length / 1000
                    if score > best_score:
                        best_score = score
                        best_plan = plan

            if best_plan is None:
                raw_mat = length_to_material[available_lengths[-1]]
                active_sorted = sorted(active, key=lambda x: x[1], reverse=True)
                part_no, part_length, _ = active_sorted[0]
                cut_count = 1
                used_length = part_length
                total_loss = loss_rule.head_tail_loss + loss_rule.single_cut_loss * cut_count

                best_plan = CuttingPlan(
                    raw_material=raw_mat,
                    parts=[(part_no, part_length, 1)],
                    cut_count=cut_count,
                    single_cut_loss=loss_rule.single_cut_loss,
                    head_tail_loss=loss_rule.head_tail_loss,
                    used_length=used_length,
                    total_loss=total_loss,
                    remaining_length=raw_mat.length - used_length - total_loss,
                    utilization=used_length / raw_mat.length
                )

            for part_no, part_length, qty in best_plan.parts:
                for i, (p_no, p_len, p_qty) in enumerate(remaining):
                    if p_no == part_no and p_len == part_length:
                        remaining[i] = (p_no, p_len, p_qty - qty)
                        break

            new_plans.append(best_plan)

        # 第三步：尝试将新方案与高利用率方案中的剩余零件合并
        for new_plan_idx, new_plan in enumerate(new_plans):
            if new_plan.utilization >= low_util_threshold:
                continue

            available_space = new_plan.remaining_length - loss_rule.single_cut_loss
            if available_space <= 0:
                continue

            for (part_no, length), qty in list(high_util_parts.items()):
                if qty <= 0:
                    continue
                if length > available_space:
                    continue
                if len(new_plan.parts) >= self.config.max_parts_per_material:
                    if part_no not in set(p[0] for p in new_plan.parts):
                        continue

                max_fit = min(qty, available_space // length)
                if max_fit <= 0:
                    continue

                new_cut_count = new_plan.cut_count + (1 if part_no not in set(p[0] for p in new_plan.parts) else 0)
                new_total_loss = loss_rule.head_tail_loss + loss_rule.single_cut_loss * new_cut_count
                max_fit = min(max_fit, (new_plan.raw_material.length - new_plan.used_length - new_total_loss) // length)
                if max_fit <= 0:
                    continue

                added_length = length * max_fit
                new_remaining = new_plan.raw_material.length - (new_plan.used_length + added_length) - new_total_loss

                if new_remaining >= 0:
                    updated_parts = list(new_plan.parts)
                    found = False
                    for pi, (pn, pl, pq) in enumerate(updated_parts):
                        if pn == part_no and pl == length:
                            updated_parts[pi] = (pn, pl, pq + max_fit)
                            found = True
                            break
                    if not found:
                        updated_parts.append((part_no, length, max_fit))

                    new_used = new_plan.used_length + added_length
                    new_total_loss = loss_rule.head_tail_loss + loss_rule.single_cut_loss * len(updated_parts)
                    new_remaining = new_plan.raw_material.length - new_used - new_total_loss
                    new_utilization = new_used / new_plan.raw_material.length

                    new_plans[new_plan_idx] = CuttingPlan(
                        raw_material=new_plan.raw_material,
                        parts=updated_parts,
                        cut_count=len(updated_parts),
                        single_cut_loss=loss_rule.single_cut_loss,
                        head_tail_loss=loss_rule.head_tail_loss,
                        used_length=new_used,
                        total_loss=new_total_loss,
                        remaining_length=new_remaining,
                        utilization=new_utilization
                    )
                    high_util_parts[(part_no, length)] -= max_fit
                    available_space = new_remaining - loss_rule.single_cut_loss

        # 构建最终结果
        result = []
        for i, plan in enumerate(final_plans):
            if i not in new_low_util_indices:
                result.append(plan)

        result.extend(new_plans)

        return result

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
