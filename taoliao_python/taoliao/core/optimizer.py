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
        for l in unique_lengths:
            for i in range(max_materials_needed):
                # Σ(x * length) + head_tail_loss + single_cut * Σz <= L * y
                constraint = solver.Constraint(
                    -solver.infinity(),
                    l * 1.0,  # 上界会在下面设置
                    f'capacity_{l}_{i}'
                )

                # 零件长度项
                for j, part in enumerate(merged_parts):
                    constraint.SetCoefficient(x[l, i, j], part.length)

                # 刀损耗项
                for j in range(len(merged_parts)):
                    constraint.SetCoefficient(z[l, i, j], loss_rule.single_cut_loss)

                # y变量（用于上界）
                constraint.SetCoefficient(y[l, i], -l + loss_rule.head_tail_loss)

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

                # 余料 = L*y - Σ(x*length) - head_tail*y - single_cut*Σz
                constraint = solver.Constraint(0, 0, f'remainder_eq_{l}_{i}')
                constraint.SetCoefficient(r[l, i], 1)
                constraint.SetCoefficient(y[l, i], -l + loss_rule.head_tail_loss)
                for j, part in enumerate(merged_parts):
                    constraint.SetCoefficient(x[l, i, j], part.length)
                for j in range(len(merged_parts)):
                    constraint.SetCoefficient(z[l, i, j], loss_rule.single_cut_loss)

        # 对称性破除：相同长度的材料按顺序使用
        for l in unique_lengths:
            for i in range(max_materials_needed - 1):
                constraint = solver.Constraint(
                    -solver.infinity(), 0, f'symmetry_{l}_{i}'
                )
                constraint.SetCoefficient(y[l, i], 1)
                constraint.SetCoefficient(y[l, i + 1], -1)

        # 目标函数：最小化原材料总长度 + 余料惩罚
        # 惩罚权重：余料超过max_remainder时惩罚
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
                        cut_count = len(parts_on_material)
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
