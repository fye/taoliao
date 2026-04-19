"""
套料优化器 - 基于MIP的精确求解算法
"""

from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass
from collections import defaultdict

from ortools.linear_solver import pywraplp

from .models import (
    Part, RawMaterial, LossRule, CuttingPlan,
    NestingResult, NestingConfig, DEFAULT_LOSS_RULES
)
from .loss_calculator import LossCalculator
from .utils import (
    group_parts_by_material_spec,
    filter_materials_by_spec,
    get_unique_material_lengths
)
from .greedy_solver import GreedyNestingSolver


@dataclass
class SolverStats:
    """求解器统计信息"""
    status: str
    objective_value: float
    solve_time: float
    num_variables: int
    num_constraints: int
    gap: float = 0.0


class NestingOptimizer:
    """套料优化器"""

    def __init__(self, config: Optional[NestingConfig] = None):
        """
        初始化优化器

        Args:
            config: 套料配置参数
        """
        self.config = config or NestingConfig()
        self.loss_calculator = LossCalculator()
        self._solver_stats: Optional[SolverStats] = None

    def optimize(
        self,
        parts: List[Part],
        materials: List[RawMaterial],
        loss_rules: Optional[List[LossRule]] = None
    ) -> NestingResult:
        """
        执行套料优化

        Args:
            parts: 零件需求列表
            materials: 原材料列表
            loss_rules: 损耗规则列表

        Returns:
            套料结果
        """
        # 设置损耗规则
        if loss_rules:
            self.loss_calculator = LossCalculator(loss_rules)

        # 按材质+规格分组
        part_groups = group_parts_by_material_spec(parts)

        all_cutting_plans: List[CuttingPlan] = []
        material_summary: Dict[Tuple[str, str], Dict] = defaultdict(
            lambda: {'count': 0, 'total_length': 0, 'total_used': 0, 'total_loss': 0}
        )

        # 对每个分组独立求解
        for (material_type, spec), group_parts in part_groups.items():
            print(f"\n处理规格: {spec}, 材质: {material_type}, 零件数: {len(group_parts)}")

            # 筛选可用的原材料
            available_materials = filter_materials_by_spec(materials, spec, material_type)

            # 如果没有完全匹配材质的材料，尝试使用同规格的其他材质
            if not available_materials:
                available_materials = filter_materials_by_spec(materials, spec)
                print(f"  警告: 材质 {material_type} 无匹配原材料，使用同规格其他材质")

            if not available_materials:
                print(f"  错误: 规格 {spec} 无可用原材料，跳过")
                continue

            # 求解该分组
            cutting_plans = self._solve_group(group_parts, available_materials, spec, material_type)

            # 汇总结果
            for plan in cutting_plans:
                all_cutting_plans.append(plan)
                key = (plan.raw_material.material_type, plan.raw_material.spec)
                material_summary[key]['count'] += 1
                material_summary[key]['total_length'] += plan.raw_material.length
                material_summary[key]['total_used'] += plan.used_length
                material_summary[key]['total_loss'] += plan.total_loss

        # 计算汇总统计
        for key, stats in material_summary.items():
            if stats['total_length'] > 0:
                stats['utilization'] = stats['total_used'] / stats['total_length']
                stats['loss_ratio'] = stats['total_loss'] / stats['total_length']
            else:
                stats['utilization'] = 0.0
                stats['loss_ratio'] = 0.0

        return NestingResult(
            original_parts=parts,
            cutting_plans=all_cutting_plans,
            material_summary=dict(material_summary)
        )

    def _solve_group(
        self,
        parts: List[Part],
        materials: List[RawMaterial],
        spec: str,
        material_type: str
    ) -> List[CuttingPlan]:
        """
        求解单个分组的套料问题

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

        # 预处理：合并相同零件
        merged_parts = self._merge_parts(parts)

        # 获取唯一长度
        unique_lengths = get_unique_material_lengths(materials)
        print(f"  可用原材料长度: {unique_lengths}")

        # 计算总零件数量
        total_part_count = sum(p.quantity for p in merged_parts)

        # 对于大规模问题（超过50个零件），直接使用贪心算法
        if total_part_count > 50:
            print(f"  零件数量较多 ({total_part_count}个)，直接使用贪心算法")
            greedy_solver = GreedyNestingSolver(self.config, self.loss_calculator)
            return greedy_solver.solve(parts, materials, spec, material_type)

        # 创建MIP模型
        solver = pywraplp.Solver.CreateSolver('CBC')
        if not solver:
            raise RuntimeError("无法创建CBC求解器")

        # 设置时间限制
        solver.SetTimeLimit(self.config.time_limit * 1000)

        # 创建决策变量
        # x[l][j] = 长度为l的原材料上切割零件j的数量
        # y[l][i] = 是否使用第i根长度为l的原材料
        # z[l][j] = 长度为l的原材料上是否切割零件j

        # 首先估计需要的原材料数量上界
        max_materials_needed = self._estimate_max_materials(merged_parts, materials, loss_rule)

        # 变量定义
        x = {}  # x[l, i, j] = 第i根长度l的材料上切割零件j的数量
        y = {}  # y[l, i] = 是否使用第i根长度l的材料
        z = {}  # z[l, i, j] = 第i根长度l的材料上是否切割零件j

        for l in unique_lengths:
            for i in range(max_materials_needed):
                # y变量
                y[l, i] = solver.IntVar(0, 1, f'y_{l}_{i}')

                for j, part in enumerate(merged_parts):
                    # x变量
                    x[l, i, j] = solver.IntVar(0, part.quantity, f'x_{l}_{i}_{j}')
                    # z变量
                    z[l, i, j] = solver.IntVar(0, 1, f'z_{l}_{i}_{j}')

        # 约束1: 需求满足
        for j, part in enumerate(merged_parts):
            constraint = solver.Constraint(part.quantity, part.quantity, f'demand_{j}')
            for l in unique_lengths:
                for i in range(max_materials_needed):
                    constraint.SetCoefficient(x[l, i, j], 1)

        # 约束2: 容量约束（含损耗）
        # 注意：单刀损耗应该乘以切割的零件总数（Σx），而不是零件种类数（Σz）
        # 约束形式: Σ(x * (length + single_cut)) <= (L - head_tail_loss) * y
        # 即: Σ(x * (length + single_cut)) - (L - head_tail_loss) * y <= 0
        for l in unique_lengths:
            for i in range(max_materials_needed):
                constraint = solver.Constraint(
                    -solver.infinity(),
                    0,
                    f'capacity_{l}_{i}'
                )

                # 零件长度项 + 刀损耗项
                for j, part in enumerate(merged_parts):
                    constraint.SetCoefficient(x[l, i, j], part.length + loss_rule.single_cut_loss)

                # y变量（用于上界）
                constraint.SetCoefficient(y[l, i], -(l - loss_rule.head_tail_loss))

        # 约束3: 零件号约束（材料侧）- 每根材料最多3种零件
        for l in unique_lengths:
            for i in range(max_materials_needed):
                constraint = solver.Constraint(
                    0, self.config.max_parts_per_material, f'parts_per_mat_{l}_{i}'
                )
                for j in range(len(merged_parts)):
                    constraint.SetCoefficient(z[l, i, j], 1)

        # 约束4: 零件号约束（零件侧）- 每个零件最多配到3根材料
        for j, part in enumerate(merged_parts):
            constraint = solver.Constraint(
                0, self.config.max_materials_per_part, f'mats_per_part_{j}'
            )
            for l in unique_lengths:
                for i in range(max_materials_needed):
                    constraint.SetCoefficient(z[l, i, j], 1)

        # 约束5: 关联约束
        for l in unique_lengths:
            for i in range(max_materials_needed):
                for j, part in enumerate(merged_parts):
                    # x > 0 => z = 1
                    constraint1 = solver.Constraint(
                        -solver.infinity(), 0, f'link1_{l}_{i}_{j}'
                    )
                    constraint1.SetCoefficient(x[l, i, j], 1)
                    constraint1.SetCoefficient(z[l, i, j], -part.quantity)

                    # z = 1 => y = 1
                    constraint2 = solver.Constraint(
                        -solver.infinity(), 0, f'link2_{l}_{i}_{j}'
                    )
                    constraint2.SetCoefficient(z[l, i, j], 1)
                    constraint2.SetCoefficient(y[l, i], -1)

        # 余料约束 - 作为软约束（惩罚项加入目标函数）
        # 引入余料变量 r[l, i]
        r = {}  # 余料变量
        for l in unique_lengths:
            for i in range(max_materials_needed):
                r[l, i] = solver.NumVar(0, l, f'r_{l}_{i}')

                # 余料 = L*y - Σ(x*length) - head_tail*y - single_cut*Σx
                constraint = solver.Constraint(0, 0, f'remainder_eq_{l}_{i}')
                constraint.SetCoefficient(r[l, i], 1)
                constraint.SetCoefficient(y[l, i], l - loss_rule.head_tail_loss)
                for j, part in enumerate(merged_parts):
                    constraint.SetCoefficient(x[l, i, j], -(part.length + loss_rule.single_cut_loss))

        # 对称性破除：相同长度的材料按顺序使用
        for l in unique_lengths:
            for i in range(max_materials_needed - 1):
                constraint = solver.Constraint(
                    -solver.infinity(), 0, f'symmetry_{l}_{i}'
                )
                constraint.SetCoefficient(y[l, i], 1)
                constraint.SetCoefficient(y[l, i + 1], -1)

        # 目标函数：最小化原材料总长度 + 余料惩罚
        PENALTY_WEIGHT = 0.1  # 惩罚权重
        objective = solver.Objective()
        for l in unique_lengths:
            for i in range(max_materials_needed):
                objective.SetCoefficient(y[l, i], l)
                objective.SetCoefficient(r[l, i], PENALTY_WEIGHT)
        objective.SetMinimization()

        # 求解
        print(f"  开始求解 (变量数: {solver.NumVariables()}, 约束数: {solver.NumConstraints()})")
        status = solver.Solve()

        # 记录统计信息
        self._solver_stats = SolverStats(
            status=self._status_to_string(status),
            objective_value=objective.Value() if status in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE] else 0,
            solve_time=solver.WallTime() / 1000,
            num_variables=solver.NumVariables(),
            num_constraints=solver.NumConstraints()
        )

        if status == pywraplp.Solver.OPTIMAL:
            print(f"  找到最优解! 目标值: {objective.Value():.0f}mm, 耗时: {solver.WallTime()/1000:.2f}s")
        elif status == pywraplp.Solver.FEASIBLE:
            print(f"  找到可行解 (可能非最优). 目标值: {objective.Value():.0f}mm, 耗时: {solver.WallTime()/1000:.2f}s")
        else:
            print(f"  MIP求解失败: {self._status_to_string(status)}, 回退到贪心算法")
            # 回退到贪心算法
            greedy_solver = GreedyNestingSolver(self.config, self.loss_calculator)
            return greedy_solver.solve(parts, materials, spec, material_type)

        # 提取解
        cutting_plans = self._extract_solution(
            solver, x, y, z, unique_lengths, max_materials_needed,
            merged_parts, materials, loss_rule
        )

        # 对于大规模问题，跳过后处理优化
        total_part_count = sum(p.quantity for p in merged_parts)
        if total_part_count <= 50:
            # 后处理：尝试优化低利用率的方案
            cutting_plans = self._post_optimize(cutting_plans, merged_parts, materials, loss_rule)

            # 全局优化：尝试用更短的材料组合替换当前方案
            cutting_plans = self._global_material_optimize(cutting_plans, materials, loss_rule)

        return cutting_plans

    def _merge_parts(self, parts: List[Part]) -> List[Part]:
        """
        合并相同的零件（相同部件号、长度）

        Args:
            parts: 零件列表

        Returns:
            合并后的零件列表
        """
        merged: Dict[Tuple[str, int], Part] = {}
        for part in parts:
            key = (part.part_no, part.length)
            if key not in merged:
                merged[key] = Part(
                    part_no=part.part_no,
                    material=part.material,
                    spec=part.spec,
                    length=part.length,
                    quantity=0
                )
            merged[key].quantity += part.quantity
        return list(merged.values())

    def _estimate_max_materials(
        self,
        parts: List[Part],
        materials: List[RawMaterial],
        loss_rule: LossRule
    ) -> int:
        """
        估计需要的最大原材料数量

        Args:
            parts: 零件列表
            materials: 原材料列表
            loss_rule: 损耗规则

        Returns:
            估计的最大原材料数量
        """
        # 计算零件总长度
        total_part_length = sum(p.length * p.quantity for p in parts)

        # 获取最小原材料长度
        min_material_length = min(m.length for m in materials)

        # 估计需要的材料数（假设80%利用率）
        estimated = total_part_length / (min_material_length * 0.8)

        # 加上安全边际
        return max(int(estimated * 1.5), len(parts) * 2, 10)

    def _extract_solution(
        self,
        solver,
        x: Dict,
        y: Dict,
        z: Dict,
        unique_lengths: List[int],
        max_materials: int,
        parts: List[Part],
        materials: List[RawMaterial],
        loss_rule: LossRule
    ) -> List[CuttingPlan]:
        """
        从求解结果中提取切割方案

        Args:
            solver: 求解器
            x, y, z: 决策变量
            unique_lengths: 唯一长度列表
            max_materials: 最大材料数
            parts: 零件列表
            materials: 原材料列表
            loss_rule: 损耗规则

        Returns:
            切割方案列表
        """
        cutting_plans = []

        # 创建长度到材料的映射
        length_to_material: Dict[int, RawMaterial] = {}
        for mat in materials:
            if mat.length not in length_to_material:
                length_to_material[mat.length] = mat

        for l in unique_lengths:
            raw_mat = length_to_material.get(l)
            if not raw_mat:
                continue

            for i in range(max_materials):
                if y[l, i].solution_value() > 0.5:
                    # 这根材料被使用了
                    parts_on_material = []
                    for j, part in enumerate(parts):
                        qty = int(round(x[l, i, j].solution_value()))
                        if qty > 0:
                            parts_on_material.append((part.part_no, part.length, qty))

                    if parts_on_material:
                        # 切割刀数 = 所有零件数量之和
                        cut_count = sum(p[2] for p in parts_on_material)
                        used_length = sum(p[1] * p[2] for p in parts_on_material)
                        total_loss = loss_rule.head_tail_loss + loss_rule.single_cut_loss * cut_count
                        remaining = l - used_length - total_loss
                        utilization = used_length / l if l > 0 else 0

                        plan = CuttingPlan(
                            raw_material=raw_mat,
                            parts=parts_on_material,
                            cut_count=cut_count,
                            single_cut_loss=loss_rule.single_cut_loss,
                            head_tail_loss=loss_rule.head_tail_loss,
                            used_length=used_length,
                            total_loss=total_loss,
                            remaining_length=remaining,
                            utilization=utilization
                        )
                        cutting_plans.append(plan)

        return cutting_plans

    @staticmethod
    def _status_to_string(status: int) -> str:
        """将求解器状态转换为字符串"""
        status_map = {
            pywraplp.Solver.OPTIMAL: 'OPTIMAL',
            pywraplp.Solver.FEASIBLE: 'FEASIBLE',
            pywraplp.Solver.INFEASIBLE: 'INFEASIBLE',
            pywraplp.Solver.UNBOUNDED: 'UNBOUNDED',
            pywraplp.Solver.ABNORMAL: 'ABNORMAL',
            pywraplp.Solver.MODEL_INVALID: 'MODEL_INVALID',
            pywraplp.Solver.NOT_SOLVED: 'NOT_SOLVED',
        }
        return status_map.get(status, f'UNKNOWN({status})')

    def get_solver_stats(self) -> Optional[SolverStats]:
        """获取求解器统计信息"""
        return self._solver_stats

    def _post_optimize(
        self,
        cutting_plans: List[CuttingPlan],
        parts: List[Part],
        materials: List[RawMaterial],
        loss_rule: LossRule
    ) -> List[CuttingPlan]:
        """
        后处理优化：重新优化低利用率的切割方案

        策略：
        1. 尝试将低利用率方案的零件填充到高利用率方案的剩余空间
        2. 收集剩余的低利用率方案零件，用贪心算法重新分配

        Args:
            cutting_plans: 原始切割方案列表
            parts: 零件列表
            materials: 原材料列表
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

        print(f"  后处理优化: 发现 {len(low_util_indices)} 个低利用率方案（<{low_util_threshold:.0%}），尝试重新优化...")

        # 第一步：尝试将低利用率方案的零件填充到高利用率方案的剩余空间
        result_plans = list(cutting_plans)
        filled_count = 0

        for low_idx in sorted(low_util_indices):
            low_plan = result_plans[low_idx]
            if low_plan is None:
                continue

            # 尝试将这个低利用率方案的零件填充到其他方案
            for part_no, part_length, part_qty in low_plan.parts:
                remaining_qty = part_qty

                # 遍历所有高利用率方案，尝试填充
                for high_idx in range(len(result_plans)):
                    if high_idx in low_util_indices or high_idx == low_idx:
                        continue
                    if remaining_qty <= 0:
                        break

                    high_plan = result_plans[high_idx]
                    if high_plan is None:
                        continue

                    # 检查是否可以添加这个零件
                    available_space = high_plan.remaining_length - loss_rule.single_cut_loss
                    if available_space < part_length:
                        continue

                    # 检查零件号限制
                    existing_part_nos = set(p[0] for p in high_plan.parts)
                    if len(existing_part_nos) >= self.config.max_parts_per_material:
                        if part_no not in existing_part_nos:
                            continue

                    # 计算可以放多少
                    max_fit = min(remaining_qty, available_space // part_length)
                    if max_fit <= 0:
                        continue

                    # 更新高利用率方案
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
                    filled_count += max_fit

                # 更新低利用率方案中的零件数量
                if remaining_qty < part_qty:
                    # 部分填充成功，更新低利用率方案
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
                        # 完全填充，标记为删除
                        result_plans[low_idx] = None

        # 移除被完全填充的方案
        final_plans = [p for p in result_plans if p is not None]

        # 更新低利用率索引
        new_low_util_indices = set(
            i for i, plan in enumerate(final_plans)
            if plan.utilization < low_util_threshold
        )

        if filled_count > 0:
            print(f"    第一步: 成功将 {filled_count} 个零件填充到高利用率方案")

        if not new_low_util_indices:
            print(f"    优化完成: 所有低利用率方案已消除")
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

        # 收集高利用率方案中的零件（用于尝试重新组合）
        high_util_parts: Dict[Tuple[str, int], int] = {}
        for i, plan in enumerate(final_plans):
            if i in new_low_util_indices:
                continue
            for part_no, length, qty in plan.parts:
                key = (part_no, length)
                high_util_parts[key] = high_util_parts.get(key, 0) + qty

        # 收集所有可用原材料长度
        available_lengths = sorted(set(m.length for m in materials))
        length_to_material = {m.length: m for m in materials}

        # 将低利用率方案的零件重新打包
        part_list = [(part_no, length, qty) for (part_no, length), qty in low_util_parts.items()]
        part_list.sort(key=lambda x: x[1], reverse=True)

        new_plans = []
        remaining = list(part_list)

        while any(p[2] > 0 for p in remaining):
            active = [p for p in remaining if p[2] > 0]
            if not active:
                break

            best_plan = None
            best_score = float('-inf')

            for length in available_lengths:
                raw_mat = length_to_material[length]
                plan = self._greedy_fill(raw_mat, active, loss_rule)
                if plan:
                    # 改进评分：综合考虑利用率、余料和材料长度
                    remainder_penalty = plan.remaining_length / 1000.0
                    length_penalty = length / 50000.0
                    utilization_bonus = plan.utilization * 100
                    score = utilization_bonus - remainder_penalty - length_penalty
                    if score > best_score:
                        best_score = score
                        best_plan = plan

            if best_plan is None:
                # 找到最短能放下的材料
                active_sorted = sorted(active, key=lambda x: x[1], reverse=True)
                part_no, part_length, _ = active_sorted[0]

                for length in available_lengths:
                    if length >= part_length + loss_rule.head_tail_loss + loss_rule.single_cut_loss:
                        raw_mat = length_to_material[length]
                        break
                else:
                    raw_mat = length_to_material[available_lengths[-1]]

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

            # 更新剩余零件
            for part_no, part_length, qty in best_plan.parts:
                for i, (p_no, p_len, p_qty) in enumerate(remaining):
                    if p_no == part_no and p_len == part_length:
                        remaining[i] = (p_no, p_len, p_qty - qty)
                        break

            new_plans.append(best_plan)

        # 构建最终结果
        result = []
        for i, plan in enumerate(final_plans):
            if i not in new_low_util_indices:
                result.append(plan)

        result.extend(new_plans)

        return result

    def _greedy_fill(
        self,
        raw_material: RawMaterial,
        parts: List[Tuple[str, int, int]],
        loss_rule: LossRule
    ) -> Optional[CuttingPlan]:
        """
        贪心填充单根原材料 - 改进版：尝试多种填充策略，选择利用率最高的

        Args:
            raw_material: 原材料
            parts: 零件列表 [(部件号, 长度, 剩余数量), ...]
            loss_rule: 损耗规则

        Returns:
            切割方案，如果无法填充则返回None
        """
        best_plan = None
        best_utilization = 0

        # 策略1：按长度降序填充（原策略）
        plan1 = self._greedy_fill_by_order(raw_material, parts, loss_rule, reverse=True)
        if plan1 and plan1.utilization > best_utilization:
            best_plan = plan1
            best_utilization = plan1.utilization

        # 策略2：按长度升序填充
        plan2 = self._greedy_fill_by_order(raw_material, parts, loss_rule, reverse=False)
        if plan2 and plan2.utilization > best_utilization:
            best_plan = plan2
            best_utilization = plan2.utilization

        # 策略3：按数量升序填充（优先填充数量少的零件）
        sorted_by_qty = sorted(parts, key=lambda x: x[2])
        plan3 = self._greedy_fill_by_order(raw_material, sorted_by_qty, loss_rule, reverse=True)
        if plan3 and plan3.utilization > best_utilization:
            best_plan = plan3
            best_utilization = plan3.utilization

        # 策略4：混合策略 - 优先填充能最大化利用率的零件
        plan4 = self._greedy_fill_best_fit(raw_material, parts, loss_rule)
        if plan4 and plan4.utilization > best_utilization:
            best_plan = plan4
            best_utilization = plan4.utilization

        return best_plan

    def _greedy_fill_by_order(
        self,
        raw_material: RawMaterial,
        parts: List[Tuple[str, int, int]],
        loss_rule: LossRule,
        reverse: bool = True
    ) -> Optional[CuttingPlan]:
        """
        按指定顺序贪心填充
        """
        available_length = raw_material.length - loss_rule.head_tail_loss

        sorted_parts = sorted(parts, key=lambda x: x[1], reverse=reverse)

        selected_parts = []
        part_no_set = set()

        for part_no, part_length, remaining_qty in sorted_parts:
            if remaining_qty <= 0:
                continue

            if len(part_no_set) >= self.config.max_parts_per_material:
                if part_no not in part_no_set:
                    continue

            # 计算当前已选零件的总长度和总数量
            current_length = sum(p[1] * p[2] for p in selected_parts)
            current_cut_count = sum(p[2] for p in selected_parts)

            # 每个零件都会增加 single_cut_loss 的损耗
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

    def _greedy_fill_best_fit(
        self,
        raw_material: RawMaterial,
        parts: List[Tuple[str, int, int]],
        loss_rule: LossRule
    ) -> Optional[CuttingPlan]:
        """
        最佳适应策略：每次选择能使剩余空间最小的零件
        """
        available_length = raw_material.length - loss_rule.head_tail_loss

        selected_parts = []
        part_no_set = set()
        remaining_parts = list(parts)

        while True:
            best_part = None
            best_remaining = float('inf')
            best_qty = 0

            current_length = sum(p[1] * p[2] for p in selected_parts)
            current_cut_count = sum(p[2] for p in selected_parts)

            for part_no, part_length, remaining_qty in remaining_parts:
                if remaining_qty <= 0:
                    continue

                if len(part_no_set) >= self.config.max_parts_per_material:
                    if part_no not in part_no_set:
                        continue

                # 每个零件都会增加 single_cut_loss 的损耗
                max_space = available_length - current_length - loss_rule.single_cut_loss * current_cut_count
                max_qty = min(
                    remaining_qty,
                    max_space // (part_length + loss_rule.single_cut_loss)
                )

                if max_qty > 0:
                    # 计算填充后的剩余空间
                    new_length = current_length + part_length * max_qty
                    new_cut_count = current_cut_count + max_qty
                    new_total_loss = loss_rule.single_cut_loss * new_cut_count
                    remaining = available_length - new_length - new_total_loss

                    if remaining < best_remaining:
                        best_remaining = remaining
                        best_part = (part_no, part_length, remaining_qty)
                        best_qty = max_qty

            if best_part is None:
                break

            selected_parts.append((best_part[0], best_part[1], int(best_qty)))
            part_no_set.add(best_part[0])

            # 更新剩余零件列表
            for i, (p_no, p_len, p_qty) in enumerate(remaining_parts):
                if p_no == best_part[0] and p_len == best_part[1]:
                    remaining_parts[i] = (p_no, p_len, p_qty - best_qty)
                    break

        if not selected_parts:
            return None

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

    def _global_material_optimize(
        self,
        cutting_plans: List[CuttingPlan],
        materials: List[RawMaterial],
        loss_rule: LossRule
    ) -> List[CuttingPlan]:
        """
        全局材料优化：穷举所有可能的材料长度分配方案，选择总长度最小的

        策略：
        1. 收集当前方案的所有零件
        2. 固定根数（与当前方案相同或更少）
        3. 穷举所有材料长度分配组合
        4. 对每种分配尝试贪心填充
        5. 选择总材料长度最小的可行方案

        Args:
            cutting_plans: 当前切割方案列表
            materials: 可用原材料列表
            loss_rule: 损耗规则

        Returns:
            优化后的切割方案列表
        """
        if len(cutting_plans) <= 1:
            return cutting_plans

        # 当前方案统计
        current_piece_count = len(cutting_plans)
        current_total_length = sum(p.raw_material.length for p in cutting_plans)

        # 收集所有零件
        all_parts: Dict[Tuple[str, int], int] = {}
        for plan in cutting_plans:
            for part_no, length, qty in plan.parts:
                key = (part_no, length)
                all_parts[key] = all_parts.get(key, 0) + qty

        if not all_parts:
            return cutting_plans

        # 获取可用材料长度（升序）
        available_lengths = sorted(set(m.length for m in materials))
        length_to_material = {m.length: m for m in materials}

        if len(available_lengths) <= 1:
            return cutting_plans

        part_list = [(part_no, length, qty) for (part_no, length), qty in all_parts.items()]

        best_plans = cutting_plans
        best_total_length = current_total_length
        best_piece_count = current_piece_count

        # 策略1：穷举材料长度分配，不固定根数
        # 估算需要的根数范围
        total_parts_length = sum(p[1] * p[2] for p in part_list)
        max_material_length = max(available_lengths)
        min_material_length = min(available_lengths)
        # 估算：假设平均利用率90%
        est_min_count = int(total_parts_length / (max_material_length * 0.9)) + 1
        est_max_count = int(total_parts_length / (min_material_length * 0.7)) + 3

        # 限制搜索范围
        min_count = max(1, est_min_count)
        max_count = min(est_max_count, current_piece_count + 10)

        for target_count in range(min_count, max_count + 1):
            new_plans = self._try_enumerate_distributions(
                part_list, available_lengths, length_to_material, loss_rule,
                target_count
            )
            if new_plans:
                new_pc = len(new_plans)
                new_tl = sum(p.raw_material.length for p in new_plans)
                # 优先选择总长度更短的方案
                if new_tl < best_total_length:
                    best_plans = new_plans
                    best_total_length = new_tl
                    best_piece_count = new_pc

        # 策略2：贪心评分策略（作为补充）
        for alpha in [1.0, 5.0]:
            new_plans = self._try_scored_strategy(
                part_list, available_lengths, length_to_material, loss_rule, alpha
            )
            if new_plans:
                new_pc = len(new_plans)
                new_tl = sum(p.raw_material.length for p in new_plans)
                if new_tl < best_total_length:
                    best_plans = new_plans
                    best_total_length = new_tl
                    best_piece_count = new_pc

        if best_total_length < current_total_length:
            saved = current_total_length - best_total_length
            print(f"  全局优化: 材料总长度从 {current_total_length/1000:.1f}m 优化到 {best_total_length/1000:.1f}m，节省 {saved/1000:.1f}m")

        return best_plans

    def _try_scored_strategy(
        self,
        part_list: List[Tuple[str, int, int]],
        available_lengths: List[int],
        length_to_material: Dict[int, RawMaterial],
        loss_rule: LossRule,
        alpha: float
    ) -> Optional[List[CuttingPlan]]:
        """
        基于评分的策略：综合考虑利用率和材料长度
        """
        remaining = list(part_list)
        new_plans = []

        while any(p[2] > 0 for p in remaining):
            active = [p for p in remaining if p[2] > 0]
            if not active:
                break

            best_plan = None
            best_score = float('-inf')

            for length in available_lengths:
                raw_mat = length_to_material[length]
                plan = self._greedy_fill(raw_mat, active, loss_rule)
                if plan is None:
                    continue

                score = plan.utilization * 100 - alpha * length / 1000
                if score > best_score:
                    best_score = score
                    best_plan = plan

            if best_plan is None:
                return None

            for part_no, part_length, qty in best_plan.parts:
                for i, (p_no, p_len, p_qty) in enumerate(remaining):
                    if p_no == part_no and p_len == part_length:
                        remaining[i] = (p_no, p_len, p_qty - qty)
                        break

            new_plans.append(best_plan)

        if any(p[2] > 0 for p in remaining):
            return None

        return new_plans

    def _try_enumerate_distributions(
        self,
        part_list: List[Tuple[str, int, int]],
        available_lengths: List[int],
        length_to_material: Dict[int, RawMaterial],
        loss_rule: LossRule,
        target_count: int
    ) -> Optional[List[CuttingPlan]]:
        """
        穷举材料长度分配策略：固定根数，穷举所有材料长度组合，选最优

        对每种分配（如：12M*10 + 11M*8 + 9M*6），尝试贪心填充，
        选择总材料长度最小的可行方案。

        Args:
            part_list: 零件列表
            available_lengths: 可用材料长度（升序）
            length_to_material: 长度到材料的映射
            loss_rule: 损耗规则
            target_count: 目标材料根数

        Returns:
            最优切割方案列表
        """
        num_lengths = len(available_lengths)

        # 限制穷举规模：如果组合数太大则只尝试部分
        # 估算组合数 C(target_count + num_lengths - 1, num_lengths - 1)
        import math
        combo_count = math.comb(target_count + num_lengths - 1, num_lengths - 1)

        # 如果组合数超过5000，限制搜索范围
        max_combos = 5000
        if combo_count > max_combos:
            # 使用启发式采样代替全穷举
            return self._sampled_enumerate(
                part_list, available_lengths, length_to_material,
                loss_rule, target_count, max_combos
            )

        # 全穷举
        best_plans = None
        best_total_length = float('inf')

        # 生成所有分配方案：n个材料分配到m个长度
        # 用递归生成所有 (c0, c1, ..., cm-1) 使得 sum(ci) = target_count
        def enumerate_distributions(n_materials, n_lengths, current=[]):
            if n_lengths == 1:
                yield current + [n_materials]
                return
            for i in range(n_materials + 1):
                yield from enumerate_distributions(
                    n_materials - i, n_lengths - 1, current + [i]
                )

        total_parts_length = sum(p[1] * p[2] for p in part_list)

        for dist in enumerate_distributions(target_count, num_lengths):
            # 计算该分配的总长度
            total_length = sum(dist[i] * available_lengths[i] for i in range(num_lengths))

            # 剪枝：如果总长度已经比当前最优差，跳过
            if total_length >= best_total_length:
                continue

            # 剪枝：如果总长度不足以容纳所有零件（考虑15%损耗和余料）
            if total_length < total_parts_length * 1.01:
                continue

            # 尝试用该分配贪心填充
            # 构建材料列表
            material_pool = []
            for i in range(num_lengths):
                material_pool.extend([available_lengths[i]] * dist[i])

            # 尝试多种填充顺序
            for order_type in ['asc', 'desc', 'random']:
                if order_type == 'asc':
                    ordered_pool = sorted(material_pool)
                elif order_type == 'desc':
                    ordered_pool = sorted(material_pool, reverse=True)
                else:
                    import random
                    ordered_pool = list(material_pool)
                    random.shuffle(ordered_pool)

                remaining = list(part_list)
                new_plans = []
                feasible = True

                for mat_length in ordered_pool:
                    active = [p for p in remaining if p[2] > 0]
                    if not active:
                        break

                    raw_mat = length_to_material[mat_length]
                    plan = self._greedy_fill(raw_mat, active, loss_rule)
                    if plan is None:
                        feasible = False
                        break

                    for part_no, part_length, qty in plan.parts:
                        for j, (p_no, p_len, p_qty) in enumerate(remaining):
                            if p_no == part_no and p_len == part_length:
                                remaining[j] = (p_no, p_len, p_qty - qty)
                                break

                    new_plans.append(plan)

                if feasible and not any(p[2] > 0 for p in remaining):
                    if total_length < best_total_length:
                        best_total_length = total_length
                        best_plans = new_plans
                    break  # 找到可行解，不需要尝试其他顺序

        return best_plans

    def _sampled_enumerate(
        self,
        part_list: List[Tuple[str, int, int]],
        available_lengths: List[int],
        length_to_material: Dict[int, RawMaterial],
        loss_rule: LossRule,
        target_count: int,
        max_samples: int
    ) -> Optional[List[CuttingPlan]]:
        """
        采样穷举：当组合数太大时，用启发式采样代替全穷举

        Args:
            part_list: 零件列表
            available_lengths: 可用材料长度（升序）
            length_to_material: 长度到材料的映射
            loss_rule: 损耗规则
            target_count: 目标材料根数
            max_samples: 最大采样数

        Returns:
            最优切割方案列表
        """
        import random
        num_lengths = len(available_lengths)
        total_parts_length = sum(p[1] * p[2] for p in part_list)

        best_plans = None
        best_total_length = float('inf')

        # 生成一些有代表性的分配
        distributions = []

        # 均匀分配
        base = target_count // num_lengths
        remainder = target_count % num_lengths
        uniform_dist = [base] * num_lengths
        for i in range(remainder):
            uniform_dist[i] += 1
        distributions.append(tuple(uniform_dist))

        # 随机采样
        for _ in range(min(max_samples, 1000)):
            # 生成随机分配
            dist = [0] * num_lengths
            for _ in range(target_count):
                dist[random.randint(0, num_lengths - 1)] += 1
            distributions.append(tuple(dist))

        for dist_tuple in distributions:
            dist = list(dist_tuple)
            total_length = sum(dist[i] * available_lengths[i] for i in range(num_lengths))

            if total_length >= best_total_length:
                continue
            if total_length < total_parts_length * 1.01:
                continue

            # 尝试升序和降序两种填充顺序
            for reverse in [False, True]:
                material_pool = []
                for i in range(num_lengths):
                    material_pool.extend([available_lengths[i]] * dist[i])

                if reverse:
                    material_pool = list(reversed(material_pool))

                remaining = list(part_list)
                new_plans = []
                feasible = True

                for mat_length in material_pool:
                    active = [p for p in remaining if p[2] > 0]
                    if not active:
                        break

                    raw_mat = length_to_material[mat_length]
                    plan = self._greedy_fill(raw_mat, active, loss_rule)
                    if plan is None:
                        feasible = False
                        break

                    for part_no, part_length, qty in plan.parts:
                        for j, (p_no, p_len, p_qty) in enumerate(remaining):
                            if p_no == part_no and p_len == part_length:
                                remaining[j] = (p_no, p_len, p_qty - qty)
                                break

                    new_plans.append(plan)

                if not feasible or any(p[2] > 0 for p in remaining):
                    continue

                if total_length < best_total_length:
                    best_total_length = total_length
                    best_plans = new_plans

        return best_plans
