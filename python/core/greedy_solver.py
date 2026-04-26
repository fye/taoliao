"""
套料优化系统贪心求解器

在符合规则的前提下，尽可能提高占用率（利用率）

贪心策略：
1. 按材质+规格分组零件
2. 对每组零件按长度降序排序
3. 优先选择利用率最高的原材料
4. 满足约束：单根原材料最多3个零件号，余料不超过1000mm（软约束）
"""

from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import copy

from core.models import Part, RawMaterial, CuttingPlan, NestingResult, NestingConfig
from core.loss_calculator import LossCalculator
from core.utils import normalize_spec, get_spec_key


class GreedySolver:
    """贪心求解器"""

    def __init__(
        self,
        loss_calculator: LossCalculator,
        config: NestingConfig
    ):
        """
        初始化贪心求解器

        Args:
            loss_calculator: 损耗计算器
            config: 配置参数
        """
        self.loss_calculator = loss_calculator
        self.config = config

    def solve(
        self,
        parts: List[Part],
        materials: List[RawMaterial]
    ) -> NestingResult:
        """
        执行贪心求解

        Args:
            parts: 零件列表
            materials: 原材料列表

        Returns:
            套料结果
        """
        # 复制零件和原材料，避免修改原始数据
        remaining_parts = {p.part_no: copy.deepcopy(p) for p in parts}
        materials_copy = [copy.deepcopy(m) for m in materials]

        # 按材质+规格分组零件
        part_groups = self._group_parts(list(remaining_parts.values()))

        # 按规格分组原材料
        material_groups = self._group_materials(materials_copy)

        # 存储所有切割方案
        all_cutting_plans: List[CuttingPlan] = []

        # 存储未分配的零件
        unassigned_parts: List[Part] = []

        # 统计每个零件号的套料方案次数
        part_plan_count: Dict[str, int] = defaultdict(int)

        # 对每个零件组进行处理
        for (material_type, spec), group_parts in part_groups.items():
            # 获取该规格的可用原材料
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

            # 对该组零件进行贪心套料
            group_plans, group_unassigned = self._solve_group(
                remaining_parts, compatible_materials, part_plan_count
            )

            all_cutting_plans.extend(group_plans)
            unassigned_parts.extend(group_unassigned)

        # 计算原材料汇总
        material_summary = self._calculate_material_summary(all_cutting_plans)

        # 计算总利用率和总损耗比
        total_utilization, total_loss_ratio = self._calculate_overall_metrics(all_cutting_plans)

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
        """过滤出材质兼容的原材料"""
        target_upper = target_material.upper()

        compatible = []
        for material in materials:
            material_upper = material.material_type.upper()

            # 完全匹配
            if material_upper == target_upper:
                compatible.append(material)
                continue

            # 同系列匹配（如 Q235B 和 Q235A）
            if material_upper.startswith(target_upper[:4]) or target_upper.startswith(material_upper[:4]):
                compatible.append(material)

        return compatible

    def _solve_group(
        self,
        remaining_parts: Dict[str, Part],
        materials: List[RawMaterial],
        part_plan_count: Dict[str, int]
    ) -> Tuple[List[CuttingPlan], List[Part]]:
        """
        对一组零件进行贪心套料

        Args:
            remaining_parts: 剩余零件需求 {零件号: Part}
            materials: 可用原材料列表
            part_plan_count: 零件号套料方案次数统计

        Returns:
            (切割方案列表, 未分配零件列表)
        """
        cutting_plans = []
        unassigned_parts = []

        # 获取该组零件的规格和材质（用于损耗计算）
        sample_part = next(iter(remaining_parts.values()))
        spec = sample_part.spec
        material = sample_part.material

        # 按长度降序排序原材料
        sorted_materials = sorted(materials, key=lambda m: m.length, reverse=True)

        # 循环直到所有零件都处理完或没有可用原材料
        max_iterations = 10000  # 防止无限循环
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # 检查是否还有剩余需求
            has_demand = False
            for part_no, part in remaining_parts.items():
                if part.quantity > 0:
                    has_demand = True
                    break

            if not has_demand:
                break

            # 找到最佳的原材料和零件组合
            best_plan = None
            best_utilization = -1
            best_material = None

            for raw_material in sorted_materials:
                if raw_material.stock <= 0:
                    continue

                # 尝试在该原材料上套料
                plan = self._try_fit_material(
                    raw_material,
                    remaining_parts,
                    part_plan_count,
                    spec,
                    material
                )

                if plan and plan.utilization > best_utilization:
                    best_utilization = plan.utilization
                    best_plan = plan
                    best_material = raw_material

            if best_plan:
                cutting_plans.append(best_plan)
                best_material.stock -= 1

                # 更新剩余需求
                for part_no, length, qty in best_plan.parts:
                    remaining_parts[part_no].quantity -= qty
                    part_plan_count[part_no] += 1
            else:
                # 无法找到合适的方案，退出循环
                break

        # 收集未分配的零件
        for part_no, part in remaining_parts.items():
            if part.quantity > 0:
                unassigned_parts.append(copy.deepcopy(part))

        return cutting_plans, unassigned_parts

    def _try_fit_material(
        self,
        raw_material: RawMaterial,
        remaining_parts: Dict[str, Part],
        part_plan_count: Dict[str, int],
        spec: str,
        material: str
    ) -> Optional[CuttingPlan]:
        """
        尝试在原材料上套料

        贪心策略：优先选择长零件，最大化利用率

        Args:
            raw_material: 原材料
            remaining_parts: 剩余零件需求
            part_plan_count: 零件号套料方案次数统计
            spec: 规格字符串
            material: 材质

        Returns:
            切割方案，如果无法套料则返回 None
        """
        # 获取有剩余需求且未超过套料方案上限的零件
        available_parts = []
        for part_no, part in remaining_parts.items():
            if part.quantity > 0 and part_plan_count.get(part_no, 0) < self.config.max_materials_per_part:
                available_parts.append((part_no, part.length, part.quantity))

        if not available_parts:
            return None

        # 按长度降序排序
        available_parts.sort(key=lambda x: x[1], reverse=True)

        # 获取损耗信息
        single_cut_loss, head_tail_loss = self.loss_calculator.get_loss(spec, material)

        # 贪心选择零件
        combination = []  # [(零件号, 长度, 数量), ...]
        used_length = 0
        part_types = 0  # 已选零件种类数

        for part_no, part_length, part_qty in available_parts:
            if part_types >= self.config.max_parts_per_material:
                break

            # 计算当前刀数
            current_cut_count = sum(c[2] for c in combination) + len(combination)

            # 计算剩余可用空间
            # 总损耗 = 单刀损耗 × (当前刀数 + 新零件数量) + 头尾损耗
            # 剩余空间 = 原材料长度 - 已用长度 - 新损耗
            remaining_space = raw_material.length - used_length - head_tail_loss

            # 检查是否能放至少一个该零件
            if part_length + single_cut_loss <= remaining_space:
                # 计算能放多少个
                max_fit = (remaining_space - single_cut_loss) // (part_length + single_cut_loss)
                max_fit = min(max_fit, part_qty)

                if max_fit > 0:
                    combination.append((part_no, part_length, max_fit))
                    used_length += part_length * max_fit
                    part_types += 1

        if not combination:
            return None

        # 计算切割刀数（每种零件切一刀，但每刀可能切多个）
        cut_count = len(combination)

        # 计算总损耗
        total_loss = single_cut_loss * cut_count + head_tail_loss

        # 计算剩余长度
        remaining_length = raw_material.length - used_length - total_loss

        # 计算利用率
        utilization = used_length / raw_material.length

        # 检查余料约束（软约束）
        if remaining_length > self.config.max_remainder:
            # 余料过大，但仍然返回方案（软约束）
            pass

        plan = CuttingPlan(
            raw_material=raw_material,
            parts=combination,
            cut_count=cut_count,
            single_cut_loss=single_cut_loss,
            head_tail_loss=head_tail_loss,
            used_length=used_length,
            total_loss=total_loss,
            remaining_length=remaining_length,
            utilization=utilization
        )

        return plan

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

        # 计算利用率和损耗比
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