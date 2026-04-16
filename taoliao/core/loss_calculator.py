"""
损耗计算器
"""

from typing import List, Optional
from .models import LossRule, Part, RawMaterial, DEFAULT_LOSS_RULES


class LossCalculator:
    """损耗计算器"""

    def __init__(self, loss_rules: Optional[List[LossRule]] = None):
        """
        初始化损耗计算器

        Args:
            loss_rules: 损耗规则列表，如果为None则使用默认规则
        """
        self.loss_rules = loss_rules or DEFAULT_LOSS_RULES

    def get_loss_rule(self, spec: str, material: str) -> LossRule:
        """
        获取适用于给定规格和材质的损耗规则

        Args:
            spec: 规格字符串，如 L90X7
            material: 材质，如 Q235B

        Returns:
            匹配的损耗规则，如果没有匹配则返回默认规则
        """
        for rule in self.loss_rules:
            if rule.matches(spec, material):
                return rule

        # 如果没有匹配的规则，返回一个默认规则
        # 使用第一个规则作为默认
        return self.loss_rules[0] if self.loss_rules else LossRule(
            limb_width_range=(0, 999),
            thickness_range=(0, 999),
            materials=[],
            single_cut_loss=10,
            head_tail_loss=30
        )

    def calculate_loss(
        self,
        spec: str,
        material: str,
        cut_count: int
    ) -> int:
        """
        计算总损耗

        Args:
            spec: 规格字符串
            material: 材质
            cut_count: 切割刀数（零件种类数）

        Returns:
            总损耗(mm)
        """
        rule = self.get_loss_rule(spec, material)
        return rule.head_tail_loss + rule.single_cut_loss * cut_count

    def calculate_remaining(
        self,
        material_length: int,
        parts_length: int,
        spec: str,
        material: str,
        cut_count: int
    ) -> int:
        """
        计算剩余长度

        Args:
            material_length: 原材料长度
            parts_length: 零件总长度
            spec: 规格字符串
            material: 材质
            cut_count: 切割刀数

        Returns:
            剩余长度(mm)
        """
        loss = self.calculate_loss(spec, material, cut_count)
        return material_length - parts_length - loss

    def calculate_utilization(
        self,
        material_length: int,
        parts_length: int
    ) -> float:
        """
        计算利用率

        Args:
            material_length: 原材料长度
            parts_length: 零件总长度

        Returns:
            利用率 (0.0 ~ 1.0)
        """
        if material_length == 0:
            return 0.0
        return parts_length / material_length
