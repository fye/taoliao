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
            # 改进策略：综合考虑利用率、余料和材料长度
            # 优先选择：利用率高 且 余料小 且 材料短 的方案
            best_plan = None
            best_score = float('-inf')

            for length in available_lengths:
                raw_mat = length_to_material.get(length)
                if not raw_mat:
                    continue

                plan = self._fill_material(
                    raw_mat, active_parts, loss_rule
                )

                if plan:
                    # 评分 = 利用率 * 1000 - 余料惩罚 - 材料长度惩罚
                    # 优先选择利用率高、余料小、材料短的方案
                    # 余料惩罚：余料越大，惩罚越大
                    remainder_penalty = plan.remaining_length / 1000.0
                    # 材料长度惩罚：鼓励使用更短的材料
                    length_penalty = length / 50000.0
                    # 利用率奖励
                    utilization_bonus = plan.utilization * 100

                    score = utilization_bonus - remainder_penalty - length_penalty

                    if score > best_score:
                        best_score = score
                        best_plan = plan

            if best_plan is None:
                # 无法填充，使用最短能放下的原材料
                active_parts_sorted = sorted(active_parts, key=lambda x: x[1], reverse=True)
                part_no, part_length, _ = active_parts_sorted[0]

                # 找到最短能放下的材料
                for length in available_lengths:
                    if length >= part_length + loss_rule.head_tail_loss + loss_rule.single_cut_loss:
                        raw_mat = length_to_material[length]
                        break
                else:
                    raw_mat = length_to_material[available_lengths[-1]]
                    length = available_lengths[-1]

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

            # 更新剩余零件数量
            for part_no, part_length, qty in best_plan.parts:
                for i, (p_no, p_len, p_qty) in enumerate(remaining_parts):
                    if p_no == part_no and p_len == part_length:
                        remaining_parts[i] = (p_no, p_len, p_qty - qty)
                        break

            cutting_plans.append(best_plan)

        # 新增：材料替换优化 - 尝试用更短的材料替换长的材料
        cutting_plans = self._material_substitution_optimize(cutting_plans, materials, loss_rule)

        # 后处理优化：重新优化低利用率的方案
        cutting_plans = self._post_optimize(cutting_plans, materials, loss_rule)

        return cutting_plans

    def _material_substitution_optimize(
        self,
        cutting_plans: List[CuttingPlan],
        materials: List[RawMaterial],
        loss_rule: LossRule
    ) -> List[CuttingPlan]:
        """
        材料替换优化：尝试用更短的材料替换长的材料，减少总材料使用量

        策略：对于每根长材料，尝试用多根短材料替换

        Args:
            cutting_plans: 切割方案列表
            materials: 可用原材料列表
            loss_rule: 损耗规则

        Returns:
            优化后的切割方案列表
        """
        if len(cutting_plans) <= 1:
            return cutting_plans

        # 获取可用原材料长度（升序）
        available_lengths = sorted(set(m.length for m in materials))
        length_to_material = {m.length: m for m in materials}

        if len(available_lengths) <= 1:
            return cutting_plans

        # 找出使用长材料的方案
        long_material_threshold = available_lengths[-2] if len(available_lengths) >= 2 else available_lengths[-1]

        improved = True
        while improved:
            improved = False

            for i in range(len(cutting_plans)):
                plan = cutting_plans[i]
                if plan.raw_material.length <= long_material_threshold:
                    continue

                # 收集这根长材料上的所有零件
                parts = plan.parts
                parts_total_length = sum(p[1] * p[2] for p in parts)

                # 尝试用更短的材料重新分配这些零件
                shorter_lengths = [l for l in available_lengths if l < plan.raw_material.length]
                if not shorter_lengths:
                    continue

                # 尝试用最短能放下的材料
                best_new_plans = None
                best_new_total = float('inf')

                for test_length in shorter_lengths:
                    # 检查是否可能用更少的总材料量
                    test_mat = length_to_material[test_length]

                    # 估算需要的材料数量
                    est_count = (parts_total_length + loss_rule.head_tail_loss) // (test_length - loss_rule.head_tail_loss - loss_rule.single_cut_loss * 3) + 1

                    if test_length * est_count >= plan.raw_material.length:
                        # 总材料量不会减少，跳过
                        continue

                    # 尝试实际分配
                    remaining_parts = [(p[0], p[1], p[2]) for p in parts]
                    new_plans = []

                    while any(p[2] > 0 for p in remaining_parts):
                        active = [p for p in remaining_parts if p[2] > 0]
                        if not active:
                            break

                        # 使用贪心填充
                        filled_plan = self._fill_material(test_mat, active, loss_rule)

                        if filled_plan is None:
                            # 无法填充，需要用更长的材料
                            for fallback_length in [l for l in available_lengths if l > test_length]:
                                fallback_mat = length_to_material[fallback_length]
                                filled_plan = self._fill_material(fallback_mat, active, loss_rule)
                                if filled_plan:
                                    break

                            if filled_plan is None:
                                break

                        new_plans.append(filled_plan)

                        for part_no, part_length, qty in filled_plan.parts:
                            for j, (p_no, p_len, p_qty) in enumerate(remaining_parts):
                                if p_no == part_no and p_len == part_length:
                                    remaining_parts[j] = (p_no, p_len, p_qty - qty)
                                    break

                    # 检查是否所有零件都分配了
                    if all(p[2] <= 0 for p in remaining_parts):
                        new_total = sum(p.raw_material.length for p in new_plans)
                        if new_total < best_new_total and new_total < plan.raw_material.length:
                            best_new_total = new_total
                            best_new_plans = new_plans

                if best_new_plans:
                    # 执行替换
                    cutting_plans = cutting_plans[:i] + best_new_plans + cutting_plans[i+1:]
                    improved = True
                    break

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

                    new_cut_count = sum(p[2] for p in new_parts)
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
                        new_low_cut_count = sum(p[2] for p in new_low_parts)
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

                # 计算添加后的新切割刀数（所有零件数量之和）
                updated_parts = list(new_plan.parts)
                found = False
                for pi, (pn, pl, pq) in enumerate(updated_parts):
                    if pn == part_no and pl == length:
                        updated_parts[pi] = (pn, pl, pq + max_fit)
                        found = True
                        break
                if not found:
                    updated_parts.append((part_no, length, max_fit))

                new_cut_count = sum(p[2] for p in updated_parts)
                new_total_loss = loss_rule.head_tail_loss + loss_rule.single_cut_loss * new_cut_count
                max_fit = min(max_fit, (new_plan.raw_material.length - new_plan.used_length - new_total_loss) // length)
                if max_fit <= 0:
                    continue

                added_length = length * max_fit
                new_remaining = new_plan.raw_material.length - (new_plan.used_length + added_length) - new_total_loss

                if new_remaining >= 0:
                    new_used = new_plan.used_length + added_length
                    new_utilization = new_used / new_plan.raw_material.length

                    new_plans[new_plan_idx] = CuttingPlan(
                        raw_material=new_plan.raw_material,
                        parts=updated_parts,
                        cut_count=new_cut_count,
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

            # 计算当前已选零件的总长度和总数量
            current_length = sum(p[1] * p[2] for p in selected_parts)
            current_cut_count = sum(p[2] for p in selected_parts)

            # 尝试加入尽可能多的该零件
            # 每个零件都会增加 single_cut_loss 的损耗
            # 所以: current_length + part_length * qty + head_tail_loss + single_cut_loss * (current_cut_count + qty) <= raw_material.length
            # 即: part_length * qty + single_cut_loss * qty <= available_length - current_length - single_cut_loss * current_cut_count
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

        # 切割刀数 = 所有零件数量之和（每种零件切几刀）
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
