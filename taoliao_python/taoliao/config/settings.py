"""配置模块"""

from dataclasses import dataclass


@dataclass
class Settings:
    """系统配置"""
    # 默认配置文件路径 (相对于taoliao_python目录)
    default_demand_file: str = "../docs/需求清单.xlsx"
    default_market_file: str = "../docs/角钢市场清单.xlsx"
    default_loss_file: str = "../docs/损耗规则.xlsx"
    default_output_file: str = "../output/套料结果.xlsx"

    # 求解器配置
    solver_time_limit: int = 120  # 秒
    max_parts_per_material: int = 3
    max_materials_per_part: int = 5
    max_remainder: int = 1000  # mm
