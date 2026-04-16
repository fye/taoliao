"""
数据处理辅助函数
"""

from typing import List, Dict, Tuple, Optional
from .models import Part, RawMaterial


def group_parts_by_spec(parts: List[Part]) -> Dict[str, List[Part]]:
    """
    按规格分组零件

    Args:
        parts: 零件列表

    Returns:
        {规格: 零件列表} 字典
    """
    groups: Dict[str, List[Part]] = {}
    for part in parts:
        spec = part.spec
        if spec not in groups:
            groups[spec] = []
        groups[spec].append(part)
    return groups


def group_parts_by_material_spec(parts: List[Part]) -> Dict[Tuple[str, str], List[Part]]:
    """
    按材质和规格分组零件

    Args:
        parts: 零件列表

    Returns:
        {(材质, 规格): 零件列表} 字典
    """
    groups: Dict[Tuple[str, str], List[Part]] = {}
    for part in parts:
        key = (part.material, part.spec)
        if key not in groups:
            groups[key] = []
        groups[key].append(part)
    return groups


def filter_materials_by_spec(
    materials: List[RawMaterial],
    spec: str,
    material_type: Optional[str] = None
) -> List[RawMaterial]:
    """
    筛选指定规格的原材料

    Args:
        materials: 原材料列表
        spec: 规格
        material_type: 材质（可选）

    Returns:
        匹配的原材料列表
    """
    result = []
    for mat in materials:
        if mat.spec == spec:
            if material_type is None or mat.material_type == material_type:
                result.append(mat)
    return result


def get_unique_material_lengths(materials: List[RawMaterial]) -> List[int]:
    """
    获取唯一的原材料长度列表（按升序排列）

    Args:
        materials: 原材料列表

    Returns:
        长度列表
    """
    lengths = set(mat.length for mat in materials)
    return sorted(lengths)
