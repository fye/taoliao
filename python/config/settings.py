"""
套料优化系统配置参数

在符合规则的前提下，尽可能提高占用率（利用率）
"""

from dataclasses import dataclass, field


# 材质兼容映射（当某材质缺失时，可使用替代材质）
DEFAULT_MATERIAL_COMPATIBILITY = {
    # Q系列材质兼容关系
    "Q235": ["Q235B", "Q235A"],
    "Q355": ["Q355B", "Q355A", "Q345B", "Q345A"],  # Q355是新标准，Q345是旧标准
    "Q345": ["Q345B", "Q345A", "Q355B", "Q355A"],
    "Q420": ["Q420B", "Q420A"],
    "Q460": ["Q460B", "Q460A"],
}


@dataclass
class Settings:
    """系统配置"""
    # 核心约束参数
    max_parts_per_material: int = 3      # 单根原材料零件号上限（硬约束）
    max_materials_per_part: int = 5      # 单零件号原材料上限（软约束，可超过）

    # 求解参数
    time_limit: int = 3600               # 求解时间限制(秒)
    mip_threshold: int = 30              # 使用MIP求解的零件数阈值

    # 材质兼容映射（当某材质缺失时，可使用替代材质）
    material_compatibility: dict = field(default_factory=lambda: DEFAULT_MATERIAL_COMPATIBILITY)


# 默认配置实例
DEFAULT_SETTINGS = Settings()


def get_settings() -> Settings:
    """获取默认配置"""
    return DEFAULT_SETTINGS


def create_custom_settings(
    max_parts_per_material: int = None,
    max_materials_per_part: int = None,
    time_limit: int = None,
    mip_threshold: int = None
) -> Settings:
    """创建自定义配置"""
    settings = Settings()
    if max_parts_per_material is not None:
        settings.max_parts_per_material = max_parts_per_material
    if max_materials_per_part is not None:
        settings.max_materials_per_part = max_materials_per_part
    if time_limit is not None:
        settings.time_limit = time_limit
    if mip_threshold is not None:
        settings.mip_threshold = mip_threshold
    return settings