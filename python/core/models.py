"""
套料优化系统数据模型定义

在符合规则的前提下，尽可能提高占用率（利用率）
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


@dataclass
class Part:
    """零件信息"""
    part_no: str           # 部件号
    material: str          # 材质 (如 Q235B, Q355B, Q345B)
    spec: str              # 规格 (如 L90X7 或 L90*7)
    length: int            # 长度(mm)
    quantity: int          # 需求数量
    width: Optional[int] = None       # 宽度(mm)
    weight: Optional[float] = None    # 单件重量(kg)
    holes: Optional[int] = None       # 单件孔数
    remark: Optional[str] = None      # 备注
    segment_no: Optional[str] = None  # 段号

    # 解析后的规格信息（运行时填充）
    limb_width: Optional[int] = None   # 肢宽(mm)
    thickness: Optional[int] = None    # 厚度(mm)


@dataclass
class RawMaterial:
    """原材料信息"""
    material_type: str     # 材质
    spec: str              # 规格 (如 L100X10)
    length: int            # 长度(mm)
    stock: int             # 市场货存量

    # 解析后的规格信息（运行时填充）
    limb_width: Optional[int] = None   # 肢宽(mm)
    thickness: Optional[int] = None    # 厚度(mm)


@dataclass
class LossRule:
    """损耗规则"""
    limb_width_min: int              # 肢宽最小值
    limb_width_max: int              # 肢宽最大值
    thickness_min: Optional[int]     # 厚度最小值 (None表示不限)
    thickness_max: Optional[int]     # 厚度最大值 (None表示不限)
    materials: List[str]             # 适用材质列表 (空列表表示不限)
    single_cut_loss: int             # 单刀损耗(mm)
    head_tail_loss: int              # 头尾损耗(mm)

    def matches(self, limb_width: int, thickness: int, material: str) -> bool:
        """检查是否匹配当前规格和材质"""
        # 检查肢宽范围
        if not (self.limb_width_min <= limb_width <= self.limb_width_max):
            return False

        # 检查厚度范围
        if self.thickness_min is not None and thickness < self.thickness_min:
            return False
        if self.thickness_max is not None and thickness > self.thickness_max:
            return False

        # 检查材质
        if self.materials and material not in self.materials:
            return False

        return True


@dataclass
class CuttingPlan:
    """单根原材料的切割方案"""
    raw_material: RawMaterial
    parts: List[Tuple[str, int, int]]  # [(部件号, 长度, 数量), ...]
    cut_count: int                      # 切割刀数
    single_cut_loss: int                # 单刀损耗
    head_tail_loss: int                 # 头尾损耗
    used_length: int                    # 使用长度（零件总长度）
    total_loss: int                     # 总损耗
    remaining_length: int               # 剩余长度（余料）
    utilization: float                  # 利用率

    def get_parts_description(self) -> str:
        """生成切割部件描述字符串，如：915/1049*1 + 411/996*4"""
        parts_str = []
        for part_no, length, qty in self.parts:
            parts_str.append(f"{part_no}/{length}*{qty}")
        return " + ".join(parts_str)


@dataclass
class NestingResult:
    """套料结果"""
    original_parts: List[Part]                    # 原始零件列表
    cutting_plans: List[CuttingPlan]              # 切割方案列表
    material_summary: Dict[Tuple[str, str], Dict] # 原材料汇总 {(材质, 规格): {数量, 利用率, 损耗比}}
    unassigned_parts: List[Part]                  # 未套料零件列表
    total_utilization: float                      # 总利用率
    total_loss_ratio: float                       # 总损耗比

    # 每个零件号的套料方案次数统计（按不同组合计数）
    # key: 零件号, value: 不同 (数量) 组合的集合
    part_plan_combinations: Dict[str, set] = field(default_factory=dict)

    # 每个零件号的套料方案次数（组合数）
    part_plan_count: Dict[str, int] = field(default_factory=dict)


@dataclass
class NestingConfig:
    """套料配置参数"""
    max_parts_per_material: int = 3      # 单根原材料零件号上限（硬约束）
    max_materials_per_part: int = 5      # 单零件号原材料上限（软约束）
    max_materials_per_part_hard: int = 7 # 单零件号原材料上限（硬约束上限，=软约束+2）
    time_limit: int = 3600               # 求解时间限制(秒)
    mip_threshold: int = 30              # 使用MIP求解的零件数阈值

    def __post_init__(self):
        """验证配置参数"""
        if self.max_parts_per_material < 1:
            raise ValueError("单根原材料零件号上限必须 >= 1")
        if self.max_materials_per_part < 1:
            raise ValueError("单零件号原材料上限必须 >= 1")
        # 确保硬约束 >= 软约束
        if self.max_materials_per_part_hard < self.max_materials_per_part:
            self.max_materials_per_part_hard = self.max_materials_per_part + 2