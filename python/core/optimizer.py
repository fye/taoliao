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
                remaining_parts, compatible_materials, spec, material_type, group_part_nos
            )

            all_cutting_plans.extend(group_plans)
            unassigned_parts.extend(group_unassigned)

        # 计算汇总
        material_summary = self._calculate_material_summary(all_cutting_plans)
        total_utilization, total_loss_ratio = self._calculate_overall_metrics(all_cutting_plans)

        # 计算每个零件号的套料方案次数（基于不同的组合签名）
        part_plan_count = self._calculate_part_plan_count(all_cutting_plans)

        return NestingResult(
            original_parts=parts,
            cutting_plans=all_cutting_plans,
            material_summary=material_summary,
            unassigned_parts=unassigned_parts,
            total_utilization=total_utilization,
            total_loss_ratio=total_loss_ratio,
            part_plan_count=dict(part_plan_count)
        )

    def _calculate_part_plan_count(
        self,
        cutting_plans: List[CuttingPlan]
    ) -> Dict[str, int]:
        """
        计算每个零件号的套料方案次数

        根据设计文档定义：
        "一套方案的信息包括：零部件号+数量的组合"

        例如：
        - 方案1: 703/2752*1 + 901A/3433*2
        - 方案2: 703/2752*1 + 902/3433*1 + 1116/2306*2
        零件 703 在两个方案中数量都是 1，但组合不同，算 2 次分配

        实现方式：
        1. 对于每个切割方案，生成一个"组合签名"（所有零件号+数量的集合）
        2. 对于每个零件号，统计它出现在多少个不同的组合签名中
        """
        # 对于每个零件号，记录它出现的所有组合签名
        part_combinations: Dict[str, set] = defaultdict(set)

        for plan in cutting_plans:
            # 生成组合签名：frozenset of (part_no, qty) tuples
            combination_signature = frozenset((part_no, qty) for part_no, _, qty in plan.parts)

            # 对于方案中的每个零件，记录这个组合签名
            for part_no, _, qty in plan.parts:
                part_combinations[part_no].add(combination_signature)

        # 计算每个零件的套料方案次数
        return {part_no: len(combos) for part_no, combos in part_combinations.items()}

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
        spec: str,
        material: str,
        group_part_nos: set
    ) -> Tuple[List[CuttingPlan], List[Part]]:
        """
        使用贪心算法求解

        优化目标：最大化利用率（最小化原材料使用）

        铁塔套料优化策略（两阶段优化）：
        1. 第一阶段：长零件套料，预留空间给短零件
        2. 第二阶段：短零件填充预留空间
        3. 后处理优化：合并低利用率方案

        Args:
            remaining_parts: 剩余零件需求 {零件号: Part}
            materials: 可用原材料列表
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

        # 铁塔套料优化：将零件分为短零件和长零件
        SHORT_PART_THRESHOLD = 1000  # 短零件阈值（mm）

        short_part_nos = set()
        long_part_nos = set()
        for part_no in group_part_nos:
            if remaining_parts[part_no].length < SHORT_PART_THRESHOLD:
                short_part_nos.add(part_no)
            else:
                long_part_nos.add(part_no)

        # 循环直到所有零件都处理完或没有可用原材料
        max_iterations = 100000
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # 检查当前分组是否还有剩余需求
            has_demand = any(
                remaining_parts[part_no].quantity > 0
                for part_no in group_part_nos
            )

            if not has_demand:
                break

            # 铁塔套料优化：优先处理短零件
            has_short_demand = any(
                remaining_parts[part_no].quantity > 0
                for part_no in short_part_nos
            )

            # 计算当前每个零件的组合数（基于已有的切割方案）
            part_plan_count = self._calculate_part_plan_count(cutting_plans)

            # 找到最佳的原材料和零件组合（最大化利用率）
            best_plan = None
            best_utilization = -1
            best_material = None

            # 铁塔套料优化：记录所有可行方案，选择最优
            all_plans = []

            for raw_material in sorted_materials:
                if raw_material.stock <= 0:
                    continue

                # 铁塔套料优化：如果还有短零件需求，优先选择能容纳短零件的方案
                plan = self._try_fit_material(
                    raw_material,
                    remaining_parts,
                    part_plan_count,
                    spec,
                    material,
                    group_part_nos,
                    prefer_short_parts=has_short_demand
                )

                if plan:
                    # 检查该方案是否能完整满足当前分组所有剩余零件需求
                    remaining_after = {part_no: copy.deepcopy(part) for part_no, part in remaining_parts.items() if part_no in group_part_nos}
                    for part_no, length, qty in plan.parts:
                        if part_no in remaining_after:
                            remaining_after[part_no].quantity -= qty
                    # 只检查当前分组的零件是否都满足
                    all_satisfied = all(part.quantity <= 0 for part_no, part in remaining_after.items() if part_no in group_part_nos)
                    all_plans.append((plan, raw_material, all_satisfied))

            # 优先选择能完整满足所有需求的方案
            # 关键：完整满足时，选择材料长度最短的（总材料使用量最少）
            # 而不是利用率最高的（避免选择过长材料导致浪费）
            complete_plans = [(p, m) for p, m, s in all_plans if s]
            incomplete_plans = [(p, m) for p, m, s in all_plans if not s]

            # 如果有能完整满足的方案，选择材料长度最短的（总材料使用量最少）
            if complete_plans:
                complete_plans.sort(key=lambda x: x[1].length)  # 按材料长度升序
                best_plan, best_material = complete_plans[0]
            else:
                # 没有能完整满足的方案，按利用率排序选择
                incomplete_plans.sort(key=lambda x: x[0].utilization, reverse=True)
                best_plan = None
                best_material = None

                for plan, raw_material in incomplete_plans:
                    if plan.utilization < 0.6:
                        continue
                    best_plan = plan
                    best_material = raw_material
                    break

                if not best_plan and incomplete_plans:
                    best_plan, best_material = incomplete_plans[0]

            if best_plan:
                cutting_plans.append(best_plan)
                best_material.stock -= 1

                # 更新剩余需求
                for part_no, length, qty in best_plan.parts:
                    remaining_parts[part_no].quantity -= qty
            else:
                # 无法找到合适的方案，尝试放宽约束
                plan = self._try_fit_material_relaxed(
                    sorted_materials,
                    remaining_parts,
                    part_plan_count,
                    spec,
                    material,
                    group_part_nos
                )

                if plan:
                    cutting_plans.append(plan)
                    plan.raw_material.stock -= 1

                    for part_no, length, qty in plan.parts:
                        remaining_parts[part_no].quantity -= qty
                else:
                    # 真的无法套料了（理论上不应该发生）
                    break

        # 收集当前分组未分配的零件
        for part_no in group_part_nos:
            if remaining_parts[part_no].quantity > 0:
                unassigned_parts.append(copy.deepcopy(remaining_parts[part_no]))

        # 后处理优化：尝试合并低利用率方案
        # 注意：后处理优化会修改切割方案，需要检查是否所有零件都被保留
        original_parts_count = defaultdict(int)
        for plan in cutting_plans:
            for part_no, length, qty in plan.parts:
                original_parts_count[part_no] += qty

        # 暂时禁用后处理优化，因为会导致零件丢失
        # cutting_plans = self._post_optimize(cutting_plans, spec, material)
        # cutting_plans = self._post_optimize_aggressive(cutting_plans, spec, material)

        # 检查后处理优化后是否所有零件都被保留
        final_parts_count = defaultdict(int)
        for plan in cutting_plans:
            for part_no, length, qty in plan.parts:
                final_parts_count[part_no] += qty

        # 检查是否有零件丢失
        for part_no, count in original_parts_count.items():
            if final_parts_count[part_no] < count:
                # 有零件丢失，需要重新添加
                missing_qty = count - final_parts_count[part_no]
                # 这不应该发生，打印警告
                print(f"警告: 零件 {part_no} 在后处理优化中丢失了 {missing_qty} 个")

        return cutting_plans, unassigned_parts

    def _post_optimize(
        self,
        cutting_plans: List[CuttingPlan],
        spec: str,
        material: str
    ) -> List[CuttingPlan]:
        """
        后处理优化：尝试合并低利用率方案

        针对铁塔套料特点：
        1. 找出低利用率方案（< 60%）
        2. 尝试将其零件合并到其他方案
        3. 重复多次直到无法继续优化
        """
        if len(cutting_plans) < 2:
            return cutting_plans

        single_cut_loss, head_tail_loss = self.loss_calculator.get_loss(spec, material)

        # 多轮优化
        max_rounds = 10
        for round_num in range(max_rounds):
            # 找出低利用率方案
            low_util_indices = [i for i, p in enumerate(cutting_plans) if p.utilization < 0.6]

            if not low_util_indices:
                break  # 没有低利用率方案，结束优化

            improved = False

            for low_idx in low_util_indices:
                low_plan = cutting_plans[low_idx]

                # 尝试将低利用率方案的零件合并到其他方案
                # 按利用率降序排序其他方案
                other_indices = [i for i in range(len(cutting_plans)) if i != low_idx]
                other_indices.sort(key=lambda i: cutting_plans[i].utilization, reverse=True)

                for high_idx in other_indices:
                    high_plan = cutting_plans[high_idx]

                    # 检查是否可以合并
                    merged_parts = list(high_plan.parts)
                    merged_used = high_plan.used_length

                    for part_no, part_length, part_qty in low_plan.parts:
                        # 检查零件号上限
                        existing_part_nos = set(p[0] for p in merged_parts)
                        if part_no not in existing_part_nos and len(merged_parts) >= self.config.max_parts_per_material:
                            continue  # 零件号上限，跳过

                        # 计算添加后的空间
                        new_used = merged_used + part_length * part_qty
                        new_cut_count = len(merged_parts) + (1 if part_no not in existing_part_nos else 0)
                        new_loss = single_cut_loss * new_cut_count + head_tail_loss
                        new_remaining = high_plan.raw_material.length - new_used - new_loss

                        if new_remaining >= 0:
                            # 可以添加
                            merged_parts.append((part_no, part_length, part_qty))
                            merged_used = new_used

                    # 检查合并后是否改善
                    if len(merged_parts) > len(high_plan.parts):
                        new_util = merged_used / high_plan.raw_material.length

                        # 更新方案
                        new_loss = single_cut_loss * len(merged_parts) + head_tail_loss
                        cutting_plans[high_idx] = CuttingPlan(
                            raw_material=high_plan.raw_material,
                            parts=merged_parts,
                            cut_count=len(merged_parts),
                            single_cut_loss=single_cut_loss,
                            head_tail_loss=head_tail_loss,
                            used_length=merged_used,
                            total_loss=new_loss,
                            remaining_length=high_plan.raw_material.length - merged_used - new_loss,
                            utilization=new_util
                        )

                        # 移除低利用率方案
                        cutting_plans.pop(low_idx)
                        improved = True
                        break

                if improved:
                    break  # 重新开始下一轮

            if not improved:
                break  # 无法继续优化，结束

        return cutting_plans

    def _post_optimize_aggressive(
        self,
        cutting_plans: List[CuttingPlan],
        spec: str,
        material: str
    ) -> List[CuttingPlan]:
        """
        更激进的后处理优化：尝试合并低利用率方案

        策略：
        1. 找出单零件号的低利用率方案（< 60%）
        2. 尝试将其零件合并到其他方案
        3. 即使合并后利用率不是很高，只要能提高整体利用率就执行
        """
        if len(cutting_plans) < 2:
            return cutting_plans

        single_cut_loss, head_tail_loss = self.loss_calculator.get_loss(spec, material)

        # 找出单零件号的低利用率方案
        single_part_low_util = [
            (i, p) for i, p in enumerate(cutting_plans)
            if p.utilization < 0.6 and len(p.parts) == 1
        ]

        if not single_part_low_util:
            return cutting_plans

        removed_indices = set()

        for low_idx, low_plan in single_part_low_util:
            if low_idx in removed_indices:
                continue

            # 获取该零件的信息
            part_no, part_length, part_qty = low_plan.parts[0]

            # 尝试找到可以容纳该零件的其他方案
            best_target_idx = None
            best_new_util = 0

            for i, plan in enumerate(cutting_plans):
                if i == low_idx or i in removed_indices:
                    continue

                # 检查零件号上限
                existing_part_nos = set(p[0] for p in plan.parts)
                if part_no not in existing_part_nos and len(plan.parts) >= self.config.max_parts_per_material:
                    continue  # 零件号上限，跳过

                # 计算添加后的空间
                new_used = plan.used_length + part_length * part_qty
                new_cut_count = plan.cut_count + (1 if part_no not in existing_part_nos else 0)
                new_loss = single_cut_loss * new_cut_count + head_tail_loss
                new_remaining = plan.raw_material.length - new_used - new_loss

                if new_remaining >= 0:
                    new_util = new_used / plan.raw_material.length
                    # 选择利用率提升最大的方案
                    if new_util > best_new_util:
                        best_new_util = new_util
                        best_target_idx = i

            # 如果找到合适的方案，执行合并
            if best_target_idx is not None and best_new_util > low_plan.utilization:
                target_plan = cutting_plans[best_target_idx]
                existing_part_nos = set(p[0] for p in target_plan.parts)

                # 更新目标方案
                new_parts = list(target_plan.parts)
                if part_no in existing_part_nos:
                    # 增加数量
                    for j, (pn, pl, pq) in enumerate(new_parts):
                        if pn == part_no:
                            new_parts[j] = (pn, pl, pq + part_qty)
                            break
                else:
                    new_parts.append((part_no, part_length, part_qty))

                new_used = sum(p[1] * p[2] for p in new_parts)
                new_loss = single_cut_loss * len(new_parts) + head_tail_loss

                cutting_plans[best_target_idx] = CuttingPlan(
                    raw_material=target_plan.raw_material,
                    parts=new_parts,
                    cut_count=len(new_parts),
                    single_cut_loss=single_cut_loss,
                    head_tail_loss=head_tail_loss,
                    used_length=new_used,
                    total_loss=new_loss,
                    remaining_length=target_plan.raw_material.length - new_used - new_loss,
                    utilization=new_used / target_plan.raw_material.length
                )

                # 标记移除低利用率方案
                removed_indices.add(low_idx)

        # 移除已合并的方案
        if removed_indices:
            cutting_plans = [p for i, p in enumerate(cutting_plans) if i not in removed_indices]

        return cutting_plans

    def _evaluate_plan(
        self,
        plan: CuttingPlan,
        remaining_parts: Dict[str, Part],
        sorted_materials: List[RawMaterial],
        spec: str,
        material: str
    ) -> float:
        """
        评估方案的综合得分

        核心目标：最小化总材料使用量

        评估逻辑：
        1. 如果当前方案能完整满足所有零件需求（没有剩余），得分最高
        2. 否则，按"总材料效率"评分：当前方案零件长度 / (当前材料长度 + 预估剩余材料长度)

        这样可以避免"当前利用率高但总材料使用量多"的问题。
        例如：7000mm利用率90%但需要2根(14000mm) vs 8000mm利用率86%只需1根(8000mm)
        后者总材料更少，得分更高。

        Args:
            plan: 当前切割方案
            remaining_parts: 剩余零件需求
            sorted_materials: 可用原材料列表
            spec: 规格字符串
            material: 材质

        Returns:
            综合得分（越高越好）
        """
        # 计算剩余零件需求
        remaining_after = {}
        for part_no, part in remaining_parts.items():
            remaining_after[part_no] = copy.deepcopy(part)

        for part_no, length, qty in plan.parts:
            if part_no in remaining_after:
                remaining_after[part_no].quantity -= qty

        # 检查是否所有零件都完整满足
        all_satisfied = all(part.quantity <= 0 for part in remaining_after.values())

        if all_satisfied:
            # 所有零件都完整满足，得分 = 当前利用率（最高优先级）
            # 但仍然按利用率排序，避免选择过长的材料
            return plan.utilization + 1.0  # 加1确保比不完整的方案优先

        # 有剩余零件，估算剩余需要的材料长度
        estimated_remaining_material = self._estimate_remaining_material(
            remaining_after, sorted_materials, spec, material
        )

        # 总材料长度 = 当前 + 预估剩余
        total_material = plan.raw_material.length + estimated_remaining_material

        # 总零件长度（当前方案 + 剩余）
        current_used = plan.used_length
        remaining_used = sum(
            part.length * part.quantity
            for part in remaining_after.values()
            if part.quantity > 0
        )
        total_used = current_used + remaining_used

        # 综合得分：总零件长度 / 总材料长度
        if total_material > 0:
            score = total_used / total_material
        else:
            score = 0

        return score

    def _estimate_remaining_material(
        self,
        remaining_parts: Dict[str, Part],
        sorted_materials: List[RawMaterial],
        spec: str,
        material: str
    ) -> float:
        """
        估算剩余零件需要的材料总长度

        策略：用贪心方法，尝试在可用材料上套料，返回需要的材料总长度

        Args:
            remaining_parts: 剩余零件需求
            sorted_materials: 可用原材料列表
            spec: 规格字符串
            material: 材质

        Returns:
            预估需要的材料总长度
        """
        # 检查是否有剩余需求
        has_demand = any(part.quantity > 0 for part in remaining_parts.values())
        if not has_demand:
            return 0

        # 收集剩余零件
        remaining_list = [
            (part_no, part.length, part.quantity)
            for part_no, part in remaining_parts.items()
            if part.quantity > 0
        ]

        if not remaining_list:
            return 0

        # 按长度降序排序
        remaining_list.sort(key=lambda x: -x[1])

        # 贪心估算：尝试在每种材料上放尽可能多的零件
        single_cut_loss, head_tail_loss = self.loss_calculator.get_loss(spec, material)

        total_material = 0
        remaining_copy = {part_no: qty for part_no, _, qty in remaining_list}

        # 最多估算10根材料
        max_estimates = 10
        for _ in range(max_estimates):
            if all(qty <= 0 for qty in remaining_copy.values()):
                break

            # 找最合适的材料
            best_material_length = 0
            best_used = 0
            best_remaining = {}

            for raw_material in sorted_materials:
                if raw_material.stock <= 0:
                    continue

                # 尝试在该材料上放零件
                used = 0
                cuts = 0
                temp_remaining = dict(remaining_copy)
                part_types = 0

                for part_no, part_length, _ in remaining_list:
                    if part_types >= self.config.max_parts_per_material:
                        break

                    available_qty = temp_remaining.get(part_no, 0)
                    if available_qty <= 0:
                        continue

                    # 计算能放多少个
                    max_fit = 0
                    for try_qty in range(available_qty, 0, -1):
                        total_cuts = cuts + try_qty
                        total_loss = single_cut_loss * total_cuts + head_tail_loss
                        total_used = used + part_length * try_qty

                        if total_used + total_loss <= raw_material.length:
                            max_fit = try_qty
                            break

                    if max_fit > 0:
                        used += part_length * max_fit
                        cuts += max_fit
                        temp_remaining[part_no] = temp_remaining.get(part_no, 0) - max_fit
                        part_types += 1

                # 选择利用率最高的材料
                if used > 0:
                    util = used / raw_material.length
                    if best_used == 0 or util > best_used / best_material_length:
                        best_material_length = raw_material.length
                        best_used = used
                        best_remaining = dict(temp_remaining)

            if best_material_length > 0:
                total_material += best_material_length
                remaining_copy = best_remaining
            else:
                # 无法找到合适的材料，用最短的材料估算
                for raw_material in sorted_materials:
                    if raw_material.stock > 0:
                        total_material += raw_material.length
                        break
                break

        return total_material

    def _try_fit_material(
        self,
        raw_material: RawMaterial,
        remaining_parts: Dict[str, Part],
        part_plan_count: Dict[str, int],
        spec: str,
        material: str,
        group_part_nos: set,
        allow_exceed_hard: bool = False,
        prefer_short_parts: bool = False
    ) -> Optional[CuttingPlan]:
        """
        尝试在原材料上套料

        贪心策略：优先选择长零件，最大化利用率

        铁塔套料优化：
        - 如果 prefer_short_parts=True，优先选择短零件，强制与长零件组合

        软约束策略（两级优先级）：
        - 优先级0：套料方案组合数 < 软约束上限（5次）
        - 优先级1：软约束上限 <= 套料方案组合数 < 硬约束上限（7次）
        - 超过硬约束上限的零件：默认不允许，allow_exceed_hard=True 时允许

        Args:
            raw_material: 原材料
            remaining_parts: 剩余零件需求
            part_plan_count: 零件号套料方案次数 {零件号: 次数}
            spec: 规格字符串
            material: 材质
            group_part_nos: 当前分组的零件号集合
            allow_exceed_hard: 是否允许超过硬约束上限（兜底时使用）
            prefer_short_parts: 是否优先选择短零件（铁塔套料优化）

        Returns:
            切割方案，如果无法套料则返回 None
        """
        # 获取有剩余需求的零件
        available_parts = []
        for part_no in group_part_nos:
            part = remaining_parts[part_no]
            if part.quantity > 0:
                # 获取当前组合数
                count = part_plan_count.get(part_no, 0)
                # 三级优先级
                if count < self.config.max_materials_per_part:
                    available_parts.append((part_no, part.length, part.quantity, 0))  # 最高优先级
                elif count < self.config.max_materials_per_part_hard:
                    available_parts.append((part_no, part.length, part.quantity, 1))  # 次优先级
                elif allow_exceed_hard:
                    # 兜底：允许超过硬约束，确保所有零件都能套上
                    # 使用 count 作为优先级，这样可以让超过次数少的零件优先被选择
                    # 从而分散"超过"的情况，避免某些零件被过度选择
                    available_parts.append((part_no, part.length, part.quantity, count))
                # else: 超过硬约束且不允许超过，跳过该零件

        if not available_parts:
            return None

        # 铁塔套料优化：排序策略
        if prefer_short_parts:
            # 优先选择短零件（< 1000mm），然后是长零件
            # 短零件按长度升序（最短的优先），长零件按长度降序
            SHORT_THRESHOLD = 1000
            available_parts.sort(key=lambda x: (
                x[3],  # 优先级
                0 if x[1] < SHORT_THRESHOLD else 1,  # 短零件优先
                x[1] if x[1] < SHORT_THRESHOLD else -x[1]  # 短零件升序，长零件降序
            ))
        else:
            # 默认：按优先级和长度排序：优先级低的在前（0最高），长度长的在前
            available_parts.sort(key=lambda x: (x[3], -x[1]))

        # 获取损耗信息
        single_cut_loss, head_tail_loss = self.loss_calculator.get_loss(spec, material)

        # 贪心选择零件
        combination = []
        used_length = 0
        part_types = 0

        # 如果允许超过硬约束（兜底模式），使用简单的贪心策略
        if allow_exceed_hard:
            for part_no, part_length, part_qty, priority in available_parts:
                if part_types >= self.config.max_parts_per_material:
                    break

                current_total_cuts = sum(c[2] for c in combination)
                initial_remaining = raw_material.length - used_length - single_cut_loss * (current_total_cuts + 1) - head_tail_loss

                if part_length <= initial_remaining:
                    max_fit = 0
                    test_remaining = initial_remaining
                    while max_fit < part_qty:
                        if part_length <= test_remaining:
                            max_fit += 1
                            test_remaining -= part_length
                            test_remaining -= single_cut_loss
                        else:
                            break

                    if max_fit > 0:
                        combination.append((part_no, part_length, max_fit))
                        used_length += part_length * max_fit
                        part_types += 1
        else:
            # 正常模式：简单贪心策略
            for part_no, part_length, part_qty, priority in available_parts:
                if part_types >= self.config.max_parts_per_material:
                    break

                current_total_cuts = sum(c[2] for c in combination)
                initial_remaining = raw_material.length - used_length - single_cut_loss * (current_total_cuts + 1) - head_tail_loss

                if part_length <= initial_remaining:
                    max_fit = 0
                    test_remaining = initial_remaining
                    while max_fit < part_qty:
                        if part_length <= test_remaining:
                            max_fit += 1
                            test_remaining -= part_length
                            test_remaining -= single_cut_loss
                        else:
                            break

                    if max_fit > 0:
                        combination.append((part_no, part_length, max_fit))
                        used_length += part_length * max_fit
                        part_types += 1

        if not combination:
            return None

        # 计算切割刀数（所有零件数量之和）
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
            cut_count=cut_count,  # 使用正确的切割刀数
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
        part_plan_count: Dict[str, int],
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
            part_plan_count: 零件号套料方案次数 {零件号: 次数}
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
                count = part_plan_count.get(part_no, 0)
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
                part_plan_count,
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