"""
套料优化系统工具函数

在符合规则的前提下，尽可能提高占用率（利用率）
"""

import re
from typing import Tuple, Optional


def parse_spec(spec: str) -> Tuple[int, int]:
    """
    解析规格字符串，获取肢宽和厚度

    支持两种格式：
    - L70X5 (使用 X 分隔)
    - L70*5 (使用 * 分隔)

    Args:
        spec: 规格字符串，如 "L90X7" 或 "L90*7"

    Returns:
        (肢宽, 厚度) 元组，如 (90, 7)

    Raises:
        ValueError: 规格格式无效时抛出
    """
    if not spec:
        raise ValueError("规格不能为空")

    # 统一替换 * 为 X，并转大写
    spec_normalized = spec.upper().replace('*', 'X')

    # 匹配 L{肢宽}X{厚度} 格式
    match = re.match(r'^L(\d+)X(\d+)$', spec_normalized)
    if not match:
        raise ValueError(f"无效的规格格式: {spec}，期望格式如 L90X7 或 L90*7")

    limb_width = int(match.group(1))
    thickness = int(match.group(2))

    return limb_width, thickness


def normalize_spec(spec: str) -> str:
    """
    标准化规格字符串

    将 L70*5 转换为 L70X5 格式

    Args:
        spec: 原始规格字符串

    Returns:
        标准化后的规格字符串 (L70X5 格式)
    """
    if not spec:
        return spec
    return spec.upper().replace('*', 'X')


def format_spec(limb_width: int, thickness: int) -> str:
    """
    格式化规格字符串

    Args:
        limb_width: 肢宽
        thickness: 厚度

    Returns:
        格式化后的规格字符串，如 "L90X7"
    """
    return f"L{limb_width}X{thickness}"


def get_spec_key(material: str, spec: str) -> Tuple[str, str]:
    """
    获取材质+规格的唯一键

    Args:
        material: 材质
        spec: 规格

    Returns:
        (材质, 标准化规格) 元组
    """
    return (material.upper(), normalize_spec(spec))


def calculate_utilization(used_length: int, total_length: int) -> float:
    """
    计算利用率

    Args:
        used_length: 使用长度（零件总长度）
        total_length: 总长度（原材料长度）

    Returns:
        利用率 (0-1之间的小数)
    """
    if total_length <= 0:
        return 0.0
    return used_length / total_length


def calculate_loss_ratio(loss: int, total_length: int) -> float:
    """
    计算损耗比

    Args:
        loss: 损耗长度
        total_length: 总长度（原材料长度）

    Returns:
        损耗比 (0-1之间的小数)
    """
    if total_length <= 0:
        return 0.0
    return loss / total_length


def is_compatible_material(target_material: str, available_material: str, compatibility_map: dict) -> bool:
    """
    检查材质是否兼容

    Args:
        target_material: 目标材质
        available_material: 可用材质
        compatibility_map: 材质兼容映射

    Returns:
        是否兼容
    """
    # 完全匹配
    if target_material.upper() == available_material.upper():
        return True

    # 检查兼容映射
    target_upper = target_material.upper()
    available_upper = available_material.upper()

    # 提取基础材质名（去掉后缀 A/B/C 等）
    target_base = re.match(r'^(Q\d+)', target_upper)
    available_base = re.match(r'^(Q\d+)', available_upper)

    if target_base and available_base:
        target_base_name = target_base.group(1)
        available_base_name = available_base.group(1)

        # 检查是否在同一个兼容组
        if target_base_name in compatibility_map:
            compatible_list = compatibility_map[target_base_name]
            # 检查两个材质是否都在兼容列表中
            if target_upper in compatible_list and available_upper in compatible_list:
                return True

    return False


def group_parts_by_material_spec(parts: list) -> dict:
    """
    按材质+规格分组零件

    Args:
        parts: 零件列表

    Returns:
        {(材质, 规格): [零件列表]} 字典
    """
    groups = {}
    for part in parts:
        key = get_spec_key(part.material, part.spec)
        if key not in groups:
            groups[key] = []
        groups[key].append(part)
    return groups


def group_materials_by_spec(materials: list) -> dict:
    """
    按规格分组原材料

    Args:
        materials: 原材料列表

    Returns:
        {标准化规格: [原材料列表]} 字典
    """
    groups = {}
    for material in materials:
        spec_normalized = normalize_spec(material.spec)
        if spec_normalized not in groups:
            groups[spec_normalized] = []
        groups[spec_normalized].append(material)
    return groups