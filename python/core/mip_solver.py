"""
套料优化系统 MIP 求解器

使用混合整数规划（MIP）求解套料问题，目标是最小化总材料使用量。

建模方式：直接建模
- 决策变量 y[m]: 原材料 m 是否使用（二进制）
- 决策变量 x[p,m]: 零件 p 在原材料 m 上的数量（整数）
- 辅助变量 z[p,m]: 零件 p 是否在原材料 m 上（二进制）

目标函数：min sum(material_length[m] * y[m])

约束条件：
1. 需求满足：sum(x[p,m] for m) >= demand[p]
2. 长度约束：sum(part_length[p] * x[p,m]) + loss <= material_length[m] * y[m]
3. 零件号上限：sum(z[p,m] for p) <= 3 * y[m]
4. 关联约束：x[p,m] <= M * z[p,m]（大M约束）
"""

from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import copy
import time

try:
    import pulp
    HAS_PULP = True
except ImportError:
    HAS_PULP = False

from core.models import Part, RawMaterial, CuttingPlan, NestingResult, NestingConfig
from core.loss_calculator import LossCalculator
from core.utils import normalize_spec, get_spec_key


class MIPSolver:
    """MIP 求解器 - 直接建模方式"""

    def __init__(
        self,
        loss_calculator: LossCalculator,
        config: NestingConfig
    ):
        if not HAS_PULP:
            raise ImportError("PuLP 库未安装，请运行: pip install pulp")

        self.loss_calculator = loss_calculator
        self.config = config

    def can_solve(self, num_parts: int, num_materials: int) -> bool:
        """
        判断是否适合用 MIP 求解

        规则：
        - 零件数 <= 阈值（默认30）
        - 原材料种类数 <= 50（避免变量过多）
        """
        if num_parts > self.config.mip_threshold:
            return False
        if num_materials > 50:
            return False
        return True

    def solve(
        self,
        parts: List[Part],
        materials: List[RawMaterial],
        time_limit: Optional[int] = None
    ) -> Tuple[Optional[NestingResult], str]:
        """
        执行 MIP 求解

        Args:
            parts: 零件列表
            materials: 原材料列表
            time_limit: 时间限制（秒）

        Returns:
            (套料结果, 求解状态)
        """
        if time_limit is None:
            time_limit = min(self.config.time_limit, 300)  # MIP 最多 5 分钟

        # 按材质+规格分组
        part_groups = self._group_parts(parts)
        material_groups = self._group_materials(materials)

        all_cutting_plans: List[CuttingPlan] = []
        unassigned_parts: List[Part] = []
        part_plan_count: Dict[str, int] = defaultdict(int)

        # 对每个分组独立求解
        for (material_type, spec), group_parts in part_groups.items():
            spec_normalized = normalize_spec(spec)
            available_materials = material_groups.get(spec_normalized, [])

            compatible_materials = self._filter_compatible_materials(
                material_type, available_materials
            )

            if not compatible_materials:
                unassigned_parts.extend(group_parts)
                continue

            # 合并相同长度的原材料（减少变量）
            merged_materials = self._merge_materials(compatible_materials)

            # 检查是否适合 MIP
            if not self.can_solve(len(group_parts), len(merged_materials)):
                # 不适合 MIP，返回 None 让调用者使用贪心
                return None, 'too_large'

            # MIP 求解
            group_plans, group_unassigned, status = self._solve_group_mip(
                group_parts,
                merged_materials,
                material_type,
                spec,
                time_limit // max(1, len(part_groups))
            )

            all_cutting_plans.extend(group_plans)
            unassigned_parts.extend(group_unassigned)

            for plan in group_plans:
                for part_no, _, _ in plan.parts:
                    part_plan_count[part_no] += 1

        if not all_cutting_plans:
            return None, 'infeasible'

        material_summary = self._calculate_material_summary(all_cutting_plans)
        total_utilization, total_loss_ratio = self._calculate_overall_metrics(all_cutting_plans)

        result = NestingResult(
            original_parts=parts,
            cutting_plans=all_cutting_plans,
            material_summary=material_summary,
            unassigned_parts=unassigned_parts,
            total_utilization=total_utilization,
            total_loss_ratio=total_loss_ratio,
            part_plan_count=dict(part_plan_count)
        )

        return result, 'optimal'

    def _solve_group_mip(
        self,
        parts: List[Part],
        materials: List[RawMaterial],
        material_type: str,
        spec: str,
        time_limit: int
    ) -> Tuple[List[CuttingPlan], List[Part], str]:
        """对单个分组使用 MIP 求解"""
        single_cut_loss, head_tail_loss = self.loss_calculator.get_loss(spec, material_type)

        # 创建模型
        prob = pulp.LpProblem("Nesting", pulp.LpMinimize)

        # 索引
        part_indices = list(range(len(parts)))
        material_indices = list(range(len(materials)))

        # 决策变量
        # y[j]: 原材料 j 使用的数量
        y = {}
        for j in material_indices:
            y[j] = pulp.LpVariable(f"y_{j}", lowBound=0, cat=pulp.LpInteger)

        # x[i,j]: 零件 i 在原材料 j 上的数量
        x = {}
        for i in part_indices:
            for j in material_indices:
                x[i, j] = pulp.LpVariable(f"x_{i}_{j}", lowBound=0, cat=pulp.LpInteger)

        # z[i,j]: 零件 i 是否在原材料 j 上（用于零件号上限约束）
        z = {}
        for i in part_indices:
            for j in material_indices:
                z[i, j] = pulp.LpVariable(f"z_{i}_{j}", cat=pulp.LpBinary)

        # 目标函数：最小化总材料长度
        prob += pulp.lpSum(
            materials[j].length * y[j]
            for j in material_indices
        )

        # 约束 1：需求满足
        for i in part_indices:
            prob += pulp.lpSum(
                x[i, j] for j in material_indices
            ) >= parts[i].quantity

        # 约束 2：长度约束（考虑损耗）
        M = 10000  # 大 M
        for j in material_indices:
            # 每种原材料使用的数量不能超过库存
            prob += y[j] <= materials[j].stock

            # 长度约束：零件总长度 + 损耗 <= 材料长度 * 使用数量
            # 简化：假设每次使用一根材料
            # 实际应该更复杂，这里用近似
            prob += pulp.lpSum(
                parts[i].length * x[i, j]
                for i in part_indices
            ) + single_cut_loss * pulp.lpSum(z[i, j] for i in part_indices) + head_tail_loss * y[j] \
                <= materials[j].length * y[j] + M * (1 - pulp.lpSum(z[i, j] for i in part_indices) / max(1, len(parts)))

        # 约束 3：零件号上限（每根材料最多 3 种零件）
        for j in material_indices:
            prob += pulp.lpSum(z[i, j] for i in part_indices) <= self.config.max_parts_per_material * y[j]

        # 约束 4：关联约束
        for i in part_indices:
            for j in material_indices:
                prob += x[i, j] <= M * z[i, j]
                prob += z[i, j] <= y[j]

        # 求解
        solver = pulp.PULP_CBC_CMD(timeLimit=time_limit, msg=0)

        try:
            status = prob.solve(solver)
        except Exception as e:
            return [], parts, 'error'

        # 检查状态
        if pulp.LpStatus[status] not in ['Optimal', 'Not Solved']:
            if pulp.LpStatus[status] == 'Infeasible':
                return [], parts, 'infeasible'

        # 提取结果
        cutting_plans = []
        for j in material_indices:
            count = int(pulp.value(y[j]) or 0)
            if count > 0:
                # 获取该原材料上的零件分配
                assigned_parts = []
                for i in part_indices:
                    qty = int(pulp.value(x[i, j]) or 0)
                    if qty > 0:
                        assigned_parts.append((parts[i].part_no, parts[i].length, qty))

                if assigned_parts:
                    # 创建切割方案
                    used_length = sum(p[1] * p[2] for p in assigned_parts)
                    cut_count = len(assigned_parts)
                    total_loss = single_cut_loss * cut_count + head_tail_loss

                    for _ in range(count):
                        plan = CuttingPlan(
                            raw_material=materials[j],
                            parts=assigned_parts,
                            cut_count=cut_count,
                            single_cut_loss=single_cut_loss,
                            head_tail_loss=head_tail_loss,
                            used_length=used_length,
                            total_loss=total_loss,
                            remaining_length=materials[j].length - used_length - total_loss,
                            utilization=used_length / materials[j].length
                        )
                        cutting_plans.append(plan)

        return cutting_plans, [], 'optimal'

    def _merge_materials(self, materials: List[RawMaterial]) -> List[RawMaterial]:
        """合并相同规格、相同长度的原材料"""
        merged = {}
        for m in materials:
            key = (m.material_type, m.spec, m.length)
            if key not in merged:
                merged[key] = m
            else:
                merged[key].stock += m.stock
        return list(merged.values())

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
        """过滤出材质兼容的原材料"""
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

        if exact_match:
            return exact_match
        if prefix_match:
            return prefix_match
        return materials

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
