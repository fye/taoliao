"""
套料优化核心数据模型
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from enum import Enum


@dataclass
class Part:
    """零件信息"""
    part_no: str                    # 部件号
    material: str                   # 材质 (如 Q235B, Q355B)
    spec: str                       # 规格 (如 L90X7)
    length: int                     # 长度(mm)
    quantity: int                   # 需求数量
    width: Optional[int] = None     # 宽度(mm)
    weight: Optional[float] = None  # 单件重量(kg)
    holes: Optional[int] = None     # 单件孔数
    remark: Optional[str] = None    # 备注
    segment_no: Optional[str] = None  # 段号

    def __hash__(self):
        return hash((self.part_no, self.material, self.spec, self.length))

    def __eq__(self, other):
        if not isinstance(other, Part):
            return False
        return (self.part_no == other.part_no and
                self.material == other.material and
                self.spec == other.spec and
                self.length == other.length)


@dataclass
class RawMaterial:
    """原材料信息"""
    material_type: str              # 材质
    spec: str                       # 规格 (如 L100X10)
    length: int                     # 长度(mm)
    stock: int = 0                  # 市场货存量

    def __hash__(self):
        return hash((self.material_type, self.spec, self.length))

    def __eq__(self, other):
        if not isinstance(other, RawMaterial):
            return False
        return (self.material_type == other.material_type and
                self.spec == other.spec and
                self.length == other.length)

    @property
    def spec_key(self) -> str:
        """规格标识（用于匹配零件）"""
        return self.spec


@dataclass
class LossRule:
    """损耗规则"""
    limb_width_range: Tuple[int, int]   # 肢宽范围 (min, max)
    thickness_range: Tuple[int, int]    # 厚度范围 (min, max), (0, 999)表示不限
    materials: List[str]                # 适用材质，空列表表示不限
    single_cut_loss: int                # 单刀损耗(mm)
    head_tail_loss: int                 # 头尾损耗(mm)

    def matches(self, spec: str, material: str) -> bool:
        """检查规则是否匹配给定的规格和材质"""
        # 解析规格 LAAAXBB，如 L90X7 -> 肢宽90，厚度7
        limb_width, thickness = self._parse_spec(spec)
        if limb_width is None:
            return False

        # 检查肢宽范围
        if not (self.limb_width_range[0] <= limb_width <= self.limb_width_range[1]):
            return False

        # 检查厚度范围
        if self.thickness_range != (0, 999):  # 不是"不限"
            if not (self.thickness_range[0] <= thickness <= self.thickness_range[1]):
                return False

        # 检查材质
        if self.materials and material not in self.materials:
            return False

        return True

    @staticmethod
    def _parse_spec(spec: str) -> Tuple[Optional[int], Optional[int]]:
        """解析规格字符串，返回(肢宽, 厚度)"""
        try:
            # 格式: LAAAXBB 或 LAAAxBB
            spec = spec.upper().replace('X', 'X')
            if not spec.startswith('L'):
                return None, None

            parts = spec[1:].split('X')
            if len(parts) != 2:
                return None, None

            limb_width = int(parts[0])
            thickness = int(parts[1])
            return limb_width, thickness
        except (ValueError, IndexError):
            return None, None


@dataclass
class CuttingPlan:
    """单根原材料的切割方案"""
    raw_material: RawMaterial                    # 使用的原材料
    parts: List[Tuple[str, int, int]]            # [(部件号, 长度, 数量), ...]
    cut_count: int                               # 切割刀数
    single_cut_loss: int                         # 单刀损耗
    head_tail_loss: int                          # 头尾损耗
    used_length: int                             # 零件使用长度
    total_loss: int                              # 总损耗
    remaining_length: int                        # 剩余长度
    utilization: float                           # 利用率

    @property
    def parts_description(self) -> str:
        """生成切割部件号描述，如：915/1049*1 + 411/996*4"""
        return ' + '.join(f"{part_no}/{length}*{qty}"
                         for part_no, length, qty in self.parts)

    @property
    def loss_ratio(self) -> float:
        """损耗比"""
        if self.raw_material.length == 0:
            return 0.0
        return self.total_loss / self.raw_material.length


@dataclass
class NestingResult:
    """套料结果"""
    original_parts: List[Part]                   # 原始需求清单
    cutting_plans: List[CuttingPlan]             # 切割方案列表
    material_summary: Dict[Tuple[str, str], Dict]  # 原材料汇总 {(材质, 规格): {数量, 利用率, ...}}

    @property
    def total_utilization(self) -> float:
        """总利用率"""
        total_part_length = sum(
            sum(p[1] * p[2] for p in plan.parts)
            for plan in self.cutting_plans
        )
        total_material_length = sum(
            plan.raw_material.length
            for plan in self.cutting_plans
        )
        if total_material_length == 0:
            return 0.0
        return total_part_length / total_material_length

    @property
    def total_loss_ratio(self) -> float:
        """总损耗比"""
        total_loss = sum(plan.total_loss for plan in self.cutting_plans)
        total_material_length = sum(
            plan.raw_material.length
            for plan in self.cutting_plans
        )
        if total_material_length == 0:
            return 0.0
        return total_loss / total_material_length


@dataclass
class NestingConfig:
    """套料配置参数"""
    max_parts_per_material: int = 3      # 单根原材料零件号上限
    max_materials_per_part: int = 3      # 单零件号原材料上限
    max_remainder: int = 1000            # 余料上限(mm)
    time_limit: int = 3600               # 求解时间限制(秒)
    allow_material_substitution: bool = True  # 是否允许材质替代


# 默认损耗规则
DEFAULT_LOSS_RULES: List[LossRule] = [
    # L40-L56, 不限厚度, 不限材质
    LossRule(
        limb_width_range=(40, 56),
        thickness_range=(0, 999),
        materials=[],
        single_cut_loss=10,
        head_tail_loss=30
    ),
    # L63-L75, 不限厚度, 不限材质
    LossRule(
        limb_width_range=(63, 75),
        thickness_range=(0, 999),
        materials=[],
        single_cut_loss=0,
        head_tail_loss=10
    ),
    # L80-L90, 不限厚度, 不限材质
    LossRule(
        limb_width_range=(80, 90),
        thickness_range=(0, 999),
        materials=[],
        single_cut_loss=15,
        head_tail_loss=35
    ),
    # L100-L180, 厚度<=12, Q235/Q355/Q420
    LossRule(
        limb_width_range=(100, 180),
        thickness_range=(0, 12),
        materials=['Q235', 'Q235B', 'Q355', 'Q355B', 'Q420', 'Q420B'],
        single_cut_loss=20,
        head_tail_loss=55
    ),
    # L140及以上, 厚度>=14, Q235/Q355/Q420
    LossRule(
        limb_width_range=(140, 999),
        thickness_range=(14, 999),
        materials=['Q235', 'Q235B', 'Q355', 'Q355B', 'Q420', 'Q420B'],
        single_cut_loss=2,
        head_tail_loss=8
    ),
    # 不限规格, Q460材质
    LossRule(
        limb_width_range=(0, 999),
        thickness_range=(0, 999),
        materials=['Q460', 'Q460B'],
        single_cut_loss=2,
        head_tail_loss=8
    ),
]
