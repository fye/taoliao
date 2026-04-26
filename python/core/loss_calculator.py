"""
套料优化系统损耗计算器

在符合规则的前提下，尽可能提高占用率（利用率）
"""

from typing import List, Tuple, Optional

from core.models import LossRule
from core.utils import parse_spec


class LossCalculator:
    """损耗计算器"""

    def __init__(self, loss_rules: List[LossRule]):
        """
        初始化损耗计算器

        Args:
            loss_rules: 损耗规则列表
        """
        self.loss_rules = loss_rules

    def get_loss(self, spec: str, material: str) -> Tuple[int, int]:
        """
        获取指定规格和材质的损耗值

        匹配优先级：
        1. Q460 材质优先匹配
        2. L140及以上且厚度>=14
        3. L100-L180且厚度<=12
        4. L80-L90
        5. L63-L75
        6. L40-L56

        Args:
            spec: 规格字符串，如 "L90X7"
            material: 材质，如 "Q235B"

        Returns:
            (单刀损耗, 头尾损耗) 元组
        """
        # 解析规格
        try:
            limb_width, thickness = parse_spec(spec)
        except ValueError:
            # 解析失败，返回默认值
            return (10, 30)

        # 标准化材质
        material_upper = material.upper()

        # 按优先级匹配规则
        # 1. Q460 材质优先匹配
        if material_upper.startswith('Q460'):
            for rule in self.loss_rules:
                if rule.matches(limb_width, thickness, material_upper):
                    return (rule.single_cut_loss, rule.head_tail_loss)

        # 2-6. 其他规则按顺序匹配
        for rule in self.loss_rules:
            if rule.matches(limb_width, thickness, material_upper):
                return (rule.single_cut_loss, rule.head_tail_loss)

        # 未匹配到规则，返回默认值
        return (10, 30)

    def calculate_total_loss(
        self,
        spec: str,
        material: str,
        cut_count: int
    ) -> int:
        """
        计算总损耗

        公式：总损耗 = 单刀损耗 × 切割刀数 + 头尾损耗

        Args:
            spec: 规格字符串
            material: 材质
            cut_count: 切割刀数

        Returns:
            总损耗(mm)
        """
        single_cut_loss, head_tail_loss = self.get_loss(spec, material)
        return single_cut_loss * cut_count + head_tail_loss

    def calculate_remaining_length(
        self,
        raw_length: int,
        parts_length: int,
        spec: str,
        material: str,
        cut_count: int
    ) -> int:
        """
        计算剩余长度（余料）

        公式：余料 = 母料长度 - 零件总长度 - 总损耗

        Args:
            raw_length: 原材料长度
            parts_length: 零件总长度
            spec: 规格字符串
            material: 材质
            cut_count: 切割刀数

        Returns:
            剩余长度(mm)
        """
        total_loss = self.calculate_total_loss(spec, material, cut_count)
        return raw_length - parts_length - total_loss

    def calculate_utilization(
        self,
        raw_length: int,
        parts_length: int,
        spec: str,
        material: str,
        cut_count: int
    ) -> float:
        """
        计算利用率

        公式：利用率 = 零件总长度 / 原材料长度

        Args:
            raw_length: 原材料长度
            parts_length: 零件总长度
            spec: 规格字符串
            material: 材质
            cut_count: 切割刀数

        Returns:
            利用率 (0-1之间的小数)
        """
        if raw_length <= 0:
            return 0.0
        return parts_length / raw_length

    def can_fit(
        self,
        raw_length: int,
        parts_length: int,
        spec: str,
        material: str,
        cut_count: int,
        max_remainder: int = 1000
    ) -> bool:
        """
        检查零件是否能放入原材料

        Args:
            raw_length: 原材料长度
            parts_length: 零件总长度
            spec: 规格字符串
            material: 材质
            cut_count: 切割刀数
            max_remainder: 余料上限(mm)

        Returns:
            是否能放入
        """
        remaining = self.calculate_remaining_length(
            raw_length, parts_length, spec, material, cut_count
        )
        return remaining >= 0 and remaining <= max_remainder

    def get_max_fit_length(
        self,
        raw_length: int,
        spec: str,
        material: str,
        cut_count: int
    ) -> int:
        """
        获取原材料能容纳的最大零件长度

        Args:
            raw_length: 原材料长度
            spec: 规格字符串
            material: 材质
            cut_count: 切割刀数

        Returns:
            最大零件长度(mm)
        """
        total_loss = self.calculate_total_loss(spec, material, cut_count)
        return raw_length - total_loss