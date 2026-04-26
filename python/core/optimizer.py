"""
套料优化系统优化器

优化目标：最大化占用率（最小化原材料使用）

约束条件：
1. 单根原材料零件号上限：硬约束（最多3个不同零件号）
2. 单零件号套料方案上限：软约束（尽量不超过5，最多不超过7）

只要零部件对应的规格型号套料存在，就一定可以套，不存在套不上的情况。

求解策略：
- 小规模问题（零件数 ≤ 阈值）：尝试 MIP 精确求解
- 大规模问题或 MIP 超时：使用贪心算法
"""

from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import copy
import time

from core.models import Part, RawMaterial, CuttingPlan, NestingResult, NestingConfig
from core.loss_calculator import LossCalculator
from core.utils import normalize_spec, get_spec_key

# 尝试导入 MIP 求解器
try:
    from core.mip_solver import MIPSolver
    HAS_MIP = True
except ImportError:
    HAS_MIP = False


class MIPOptimizer:
    """混合优化器：MIP + 贪心"""

    def __init__(
        self,
        loss_calculator: LossCalculator,
        config: NestingConfig
    ):
        """
        初始化优化器

        Args:
            loss_calculator: 损耗计算器
            config: 配置参数
        """
        self.loss_calculator = loss_calculator
        self.config = config

        # 创建 MIP 求解器（如果可用）
        self.mip_solver = None
        if HAS_MIP:
            try:
                self.mip_solver = MIPSolver(loss_calculator, config)
            except Exception:
                pass

    def solve(
        self,
        parts: List[Part],
        materials: List[RawMaterial]
    ) -> NestingResult:
        """
        执行优化求解

        策略：
        1. 尝试 MIP 精确求解（如果适合）
        2. MIP 失败/超时/不适合时，回退贪心算法

        Args:
            parts: 零件列表
            materials: 原材料列表

        Returns:
            套料结果
        """
        start_time = time.time()

        # 尝试 MIP 求解
        if self.mip_solver and self.mip_solver.can_solve(len(parts), len(materials)):
            print(f"  尝试 MIP 求解（零件数={len(parts)}）...")
            result, status = self.mip_solver.solve(parts, materials, time_limit=60)

            if result and status in ['optimal', 'feasible']:
                elapsed = time.time() - start_time
                print(f"  MIP 求解成功，耗时 {elapsed:.1f}s，利用率 {result.total_utilization:.2%}")
                return result

            print(f"  MIP 求解失败（{status}），回退贪心算法...")

        # 使用贪心算法
        return self._solve_greedy(parts, materials)

    def _solve_greedy(
        self,
        parts: List[Part],
        materials: List[RawMaterial]
    ) -> NestingResult:
        # 复制零件和原材料，避免修改原始数据
        remaining_parts = {p.part_no: copy.deepcopy(p) for p in parts}
        materials_copy = [copy.deepcopy(m) for m in materials]

        # 按材质+规格分组零件
        part_groups = self._group_parts(list(remaining_parts.values()))

        # 按规格分组原材料
        material_groups = self._group_materials(materials_copy)

        # 存储所有切割方案
        all_cutting_plans: List[CuttingPlan] = []
        unassigned_parts: List[Part] = []

        # 每个零件号的套料方案组合（存储不同的数量）
        part_plan_combinations: Dict[str, set] = defaultdict(set)

        # 对每个零件组进行处理
        for (material_type, spec), group_parts in part_groups.items():
            spec_normalized = normalize_spec(spec)
            available_materials = material_groups.get(spec_normalized, [])

            # 过滤出材质兼容的原材料
            compatible_materials = self._filter_compatible_materials(
                material_type, available_materials
            )

            if not compatible_materials:
                # 没有可用原材料，将零件标记为未分配
                for p in group_parts:
                    if remaining_parts.get(p.part_no) and remaining_parts[p.part_no].quantity > 0:
                        unassigned_parts.append(remaining_parts[p.part_no])
                continue

            # 使用贪心算法求解
            group_part_nos = set(p.part_no for p in group_parts)
            group_plans, group_unassigned = self._solve_group_greedy(
                remaining_parts, compatible_materials, part_plan_combinations, spec, material_type, group_part_nos
            )

            all_cutting_plans.extend(group_plans)
            unassigned_parts.extend(group_unassigned)

        # 计算汇总
        material_summary = self._calculate_material_summary(all_cutting_plans)
        total_utilization, total_loss_ratio = self._calculate_overall_metrics(all_cutting_plans)

        # 计算每个零件号的套料方案次数（组合数）
        part_plan_count = {part_no: len(combos) for part_no, combos in part_plan_combinations.items()}

        return NestingResult(
            original_parts=parts,
            cutting_plans=all_cutting_plans,
            material_summary=material_summary,
            unassigned_parts=unassigned_parts,
            total_utilization=total_utilization,
            total_loss_ratio=total_loss_ratio,
            part_plan_count=dict(part_plan_count)
        )

    def _group_parts(self, parts: List[Part]) -> Dict[Tuple[str, str], List[Part]]:
        """按材质+规格分组零件"""
        groups = defaultdict(list)
        for part in parts:
            key = get_spec_key(part.material, part.spec)
            groups[key].append(part)
        return groups

    def _group_materials(self, materials: List[RawMaterial]) -> Dict[str, List[RawMaterial]]:
        """按规格分组原材料"""
        groups = defaultdict(list)
        for material in materials:
            spec_normalized = normalize_spec(material.spec)
            groups[spec_normalized].append(material)
        return groups

    def _filter_compatible_materials(
        self,
        target_material: str,
        materials: List[RawMaterial]
    ) -> List[RawMaterial]:
        """
        过滤出材质兼容的原材料

        策略：
        1. 优先匹配相同材质
        2. 其次匹配前缀相似的材质（如 Q235B 匹配 Q235）
        3. 如果都不匹配，返回所有同规格原材料（材质不匹配时使用同规格其他材质）
        """
        target_upper = target_material.upper()

        exact_match = []
        prefix_match = []

        for material in materials:
            material_upper = material.material_type.upper()

            if material_upper == target_upper:
                exact_match.append(material)
                continue

            if material_upper.startswith(target_upper[:4]) or target_upper.startswith(material_upper[:4]):
                prefix_match.append(material)

        # 优先返回精确匹配
        if exact_match:
            return exact_match

        # 其次返回前缀匹配
        if prefix_match:
            return prefix_match

        # 如果都不匹配，返回所有同规格原材料（确保能套上）
        return materials

    def _solve_group_greedy(
        self,
        remaining_parts: Dict[str, Part],
        materials: List[RawMaterial],
        part_plan_combinations: Dict[str, set],
        spec: str,
        material: str,
        group_part_nos: set
    ) -> Tuple[List[CuttingPlan], List[Part]]:
        """
        使用贪心算法求解

        优化目标：最大化利用率（最小化原材料使用）

        Args:
            remaining_parts: 剩余零件需求 {零件号: Part}
            materials: 可用原材料列表
            part_plan_combinations: 零件号套料方案组合 {零件号: set(数量1, 数量2, ...)}
            spec: 规格字符串
            material: 材质
            group_part_nos: 当前分组的零件号集合

        Returns:
            (切割方案列表, 未分配零件列表)
        """
        cutting_plans = []
        unassigned_parts = []

        # 按长度降序排序原材料
        sorted_materials = sorted(materials, key=lambda m: m.length, reverse=True)

        # 循环直到所有零件都处理完或没有可用原材料
        max_iterations = 100000
        iteration = 0

        # 计算当前组合数（用于约束判断）
        def get_plan_count(part_no: str) -> int:
            return len(part_plan_combinations.get(part_no, set()))

        while iteration < max_iterations:
            iteration += 1

            # 检查当前分组是否还有剩余需求
            has_demand = any(
                remaining_parts[part_no].quantity > 0
                for part_no in group_part_nos
            )

            if not has_demand:
                break

            # 找到最佳的原材料和零件组合（最大化利用率）
            best_plan = None
            best_utilization = -1
            best_material = None

            for raw_material in sorted_materials:
                if raw_material.stock <= 0:
                    continue

                plan = self._try_fit_material(
                    raw_material,
                    remaining_parts,
                    part_plan_combinations,
                    spec,
                    material,
                    group_part_nos
                )

                if plan and plan.utilization > best_utilization:
                    best_utilization = plan.utilization
                    best_plan = plan
                    best_material = raw_material

            if best_plan:
                cutting_plans.append(best_plan)
                best_material.stock -= 1

                # 更新剩余需求和套料方案组合
                for part_no, length, qty in best_plan.parts:
                    remaining_parts[part_no].quantity -= qty
                    part_plan_combinations[part_no].add(qty)
            else:
                # 无法找到合适的方案，尝试放宽约束
                plan = self._try_fit_material_relaxed(
                    sorted_materials,
                    remaining_parts,
                    part_plan_combinations,
                    spec,
                    material,
                    group_part_nos
                )

                if plan:
                    cutting_plans.append(plan)
                    plan.raw_material.stock -= 1

                    for part_no, length, qty in plan.parts:
                        remaining_parts[part_no].quantity -= qty
                        part_plan_combinations[part_no].add(qty)
                else:
                    # 真的无法套料了（理论上不应该发生）
                    break

        # 收集当前分组未分配的零件
        for part_no in group_part_nos:
            if remaining_parts[part_no].quantity > 0:
                unassigned_parts.append(copy.deepcopy(remaining_parts[part_no]))

        return cutting_plans, unassigned_parts

    def _try_fit_material(
        self,
        raw_material: RawMaterial,
        remaining_parts: Dict[str, Part],
        part_plan_combinations: Dict[str, set],
        spec: str,
        material: str,
        group_part_nos: set,
        allow_exceed_hard: bool = False
    ) -> Optional[CuttingPlan]:
        """
        尝试在原材料上套料

        贪心策略：优先选择长零件，最大化利用率

        软约束策略（两级优先级）：
        - 优先级0：套料方案组合数 < 软约束上限（5次）
        - 优先级1：软约束上限 <= 套料方案组合数 < 硬约束上限（7次）
        - 超过硬约束上限的零件：默认不允许，allow_exceed_hard=True 时允许

        Args:
            raw_material: 原材料
            remaining_parts: 剩余零件需求
            part_plan_combinations: 零件号套料方案组合 {零件号: set(数量1, 数量2, ...)}
            spec: 规格字符串
            material: 材质
            group_part_nos: 当前分组的零件号集合
            allow_exceed_hard: 是否允许超过硬约束上限（兜底时使用）

        Returns:
            切割方案，如果无法套料则返回 None
        """
        # 获取有剩余需求的零件
        available_parts = []
        for part_no in group_part_nos:
            part = remaining_parts[part_no]
            if part.quantity > 0:
                # 计算当前组合数
                count = len(part_plan_combinations.get(part_no, set()))
                # 两级优先级
                if count < self.config.max_materials_per_part:
                    available_parts.append((part_no, part.length, part.quantity, 0))  # 最高优先级
                elif count < self.config.max_materials_per_part_hard:
                    available_parts.append((part_no, part.length, part.quantity, 1))  # 次优先级
                elif allow_exceed_hard:
                    # 兜底：允许超过硬约束
                    available_parts.append((part_no, part.length, part.quantity, 2))  # 最低优先级
                # else: 超过硬约束且不允许超过，跳过该零件

        if not available_parts:
            return None

        # 按优先级和长度排序：优先级低的在前（0最高），长度长的在前
        available_parts.sort(key=lambda x: (x[3], -x[1]))

        # 获取损耗信息
        single_cut_loss, head_tail_loss = self.loss_calculator.get_loss(spec, material)

        # 贪心选择零件
        combination = []
        used_length = 0
        part_types = 0

        for part_no, part_length, part_qty, priority in available_parts:
            if part_types >= self.config.max_parts_per_material:
                break

            # 计算当前已选零件的总刀数
            current_total_cuts = sum(c[2] for c in combination)

            # 计算添加这个零件后的总损耗
            new_cut_count = current_total_cuts + 1
            new_total_loss = single_cut_loss * new_cut_count + head_tail_loss

            # 计算剩余可用空间
            remaining_space = raw_material.length - used_length - new_total_loss

            if part_length <= remaining_space:
                # 计算能放多少个
                max_fit = remaining_space // part_length
                max_fit = min(max_fit, part_qty)

                if max_fit > 0:
                    combination.append((part_no, part_length, max_fit))
                    used_length += part_length * max_fit
                    part_types += 1

        if not combination:
            return None

        # 计算切割刀数
        cut_count = sum(c[2] for c in combination)

        # 计算总损耗
        total_loss = single_cut_loss * cut_count + head_tail_loss

        # 计算剩余长度
        remaining_length = raw_material.length - used_length - total_loss

        # 计算利用率
        utilization = used_length / raw_material.length

        plan = CuttingPlan(
            raw_material=raw_material,
            parts=combination,
            cut_count=len(combination),
            single_cut_loss=single_cut_loss,
            head_tail_loss=head_tail_loss,
            used_length=used_length,
            total_loss=total_loss,
            remaining_length=remaining_length,
            utilization=utilization
        )

        return plan

    def _try_fit_material_relaxed(
        self,
        sorted_materials: List[RawMaterial],
        remaining_parts: Dict[str, Part],
        part_plan_combinations: Dict[str, set],
        spec: str,
        material: str,
        group_part_nos: set
    ) -> Optional[CuttingPlan]:
        """
        放宽约束尝试套料（兜底逻辑）

        当所有零件都达到硬约束上限时，允许超过硬约束继续套料
        确保所有零件都能套上（只要规格匹配）

        Args:
            sorted_materials: 排序后的原材料列表
            remaining_parts: 剩余零件需求
            part_plan_combinations: 零件号套料方案组合 {零件号: set(数量1, 数量2, ...)}
            spec: 规格字符串
            material: 材质
            group_part_nos: 当前分组的零件号集合

        Returns:
            切割方案，如果无法套料则返回 None
        """
        # 检查是否所有有剩余需求的零件都达到了硬约束上限
        all_at_hard_limit = True
        for part_no in group_part_nos:
            if remaining_parts[part_no].quantity > 0:
                count = len(part_plan_combinations.get(part_no, set()))
                if count < self.config.max_materials_per_part_hard:
                    all_at_hard_limit = False
                    break

        # 只有当所有零件都达到硬约束上限时，才允许超过硬约束
        allow_exceed_hard = all_at_hard_limit

        # 找到最佳方案
        best_plan = None
        best_utilization = -1

        for raw_material in sorted_materials:
            if raw_material.stock <= 0:
                continue

            plan = self._try_fit_material(
                raw_material,
                remaining_parts,
                part_plan_combinations,
                spec,
                material,
                group_part_nos,
                allow_exceed_hard=allow_exceed_hard
            )

            if plan and plan.utilization > best_utilization:
                best_utilization = plan.utilization
                best_plan = plan

        return best_plan

    def _calculate_material_summary(
        self,
        cutting_plans: List[CuttingPlan]
    ) -> Dict[Tuple[str, str], Dict]:
        """计算原材料汇总"""
        summary = defaultdict(lambda: {
            'count': 0,
            'total_used_length': 0,
            'total_length': 0,
            'total_loss': 0
        })

        for plan in cutting_plans:
            key = (plan.raw_material.material_type, normalize_spec(plan.raw_material.spec))
            summary[key]['count'] += 1
            summary[key]['total_used_length'] += plan.used_length
            summary[key]['total_length'] += plan.raw_material.length
            summary[key]['total_loss'] += plan.total_loss

        for key, data in summary.items():
            data['utilization'] = data['total_used_length'] / data['total_length'] if data['total_length'] > 0 else 0
            data['loss_ratio'] = data['total_loss'] / data['total_length'] if data['total_length'] > 0 else 0

        return dict(summary)

    def _calculate_overall_metrics(
        self,
        cutting_plans: List[CuttingPlan]
    ) -> Tuple[float, float]:
        """计算总利用率和总损耗比"""
        if not cutting_plans:
            return 0.0, 0.0

        total_used = sum(p.used_length for p in cutting_plans)
        total_length = sum(p.raw_material.length for p in cutting_plans)
        total_loss = sum(p.total_loss for p in cutting_plans)

        utilization = total_used / total_length if total_length > 0 else 0
        loss_ratio = total_loss / total_length if total_length > 0 else 0

        return utilization, loss_ratio