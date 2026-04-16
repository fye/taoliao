"""
数据加载器
"""

import pandas as pd
from pathlib import Path
from typing import List, Optional, Dict, Tuple
import re

from ..core.models import Part, RawMaterial, LossRule


class DataLoader:
    """数据加载器"""

    def __init__(self):
        self._raw_parts_df: Optional[pd.DataFrame] = None
        self._raw_materials_df: Optional[pd.DataFrame] = None

    def load_parts(self, file_path: str) -> List[Part]:
        """
        加载零件需求清单

        Args:
            file_path: Excel文件路径

        Returns:
            零件列表
        """
        df = pd.read_excel(file_path)
        self._raw_parts_df = df.copy()

        parts = []
        for _, row in df.iterrows():
            part = Part(
                part_no=str(row.get('部件号', '')),
                material=str(row.get('材质', '')),
                spec=str(row.get('规格', '')),
                length=int(row.get('长度(mm)', 0)),
                quantity=int(row.get('单基数量(件)', 1)),
                width=self._safe_int(row.get('宽度(mm)')),
                weight=self._safe_float(row.get('单件重量(kg)')),
                holes=self._safe_int(row.get('单件孔数')),
                remark=str(row.get('备注', '')) if pd.notna(row.get('备注')) else None,
                segment_no=str(row.get('段号(只读)', '')) if pd.notna(row.get('段号(只读)')) else None
            )
            if part.part_no and part.length > 0:
                parts.append(part)

        return parts

    def load_materials(self, file_path: str) -> List[RawMaterial]:
        """
        加载原材料市场清单

        Args:
            file_path: Excel文件路径

        Returns:
            原材料列表
        """
        df = pd.read_excel(file_path)
        self._raw_materials_df = df.copy()

        materials = []
        for _, row in df.iterrows():
            material = RawMaterial(
                material_type=str(row.get('材质', '')),
                spec=str(row.get('规格全称', '')),
                length=int(row.get('长度', 0)),
                stock=self._safe_int(row.get('A市场货存量', 0))
            )
            if material.spec and material.length > 0:
                materials.append(material)

        return materials

    def load_loss_rules(self, file_path: str) -> List[LossRule]:
        """
        加载损耗规则

        Args:
            file_path: Excel文件路径

        Returns:
            损耗规则列表
        """
        df = pd.read_excel(file_path, header=None)

        # 跳过标题行，从第2行开始是数据
        rules = []
        for i in range(2, len(df)):
            row = df.iloc[i]

            limb_width_str = str(row[0]) if pd.notna(row[0]) else ''
            thickness_str = str(row[1]) if pd.notna(row[1]) else ''
            material_str = str(row[2]) if pd.notna(row[2]) else ''
            single_cut_loss = self._safe_int(row[3]) or 0
            head_tail_loss = self._safe_int(row[4]) or 0

            limb_width_range = self._parse_range(limb_width_str, 'L')
            thickness_range = self._parse_range(thickness_str, '')
            materials = self._parse_materials(material_str)

            rule = LossRule(
                limb_width_range=limb_width_range,
                thickness_range=thickness_range,
                materials=materials,
                single_cut_loss=single_cut_loss,
                head_tail_loss=head_tail_loss
            )
            rules.append(rule)

        return rules

    def get_raw_parts_df(self) -> Optional[pd.DataFrame]:
        """获取原始零件数据DataFrame"""
        return self._raw_parts_df

    def get_raw_materials_df(self) -> Optional[pd.DataFrame]:
        """获取原始原材料数据DataFrame"""
        return self._raw_materials_df

    @staticmethod
    def _safe_int(value) -> Optional[int]:
        """安全转换为整数"""
        if pd.isna(value):
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """安全转换为浮点数"""
        if pd.isna(value):
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_range(range_str: str, prefix: str) -> Tuple[int, int]:
        """
        解析范围字符串

        Args:
            range_str: 范围字符串，如 "L40-L56", "小于等于12", "不限"
            prefix: 前缀，如 'L'

        Returns:
            (min, max) 元组
        """
        range_str = range_str.strip()

        # 不限
        if '不限' in range_str or range_str == '':
            return (0, 999)

        # 移除前缀
        if prefix and range_str.startswith(prefix):
            range_str = range_str[len(prefix):]

        # L40-L56 格式
        if '-' in range_str:
            parts = range_str.split('-')
            if len(parts) == 2:
                try:
                    min_val = int(parts[0].strip())
                    max_val = int(parts[1].strip())
                    return (min_val, max_val)
                except ValueError:
                    pass

        # 小于等于12 格式
        if '小于等于' in range_str:
            match = re.search(r'(\d+)', range_str)
            if match:
                max_val = int(match.group(1))
                return (0, max_val)

        # 大于等于14 格式
        if '大于等于' in range_str:
            match = re.search(r'(\d+)', range_str)
            if match:
                min_val = int(match.group(1))
                return (min_val, 999)

        # L140及以上 格式
        if '及以上' in range_str:
            match = re.search(r'(\d+)', range_str)
            if match:
                min_val = int(match.group(1))
                return (min_val, 999)

        return (0, 999)

    @staticmethod
    def _parse_materials(material_str: str) -> List[str]:
        """
        解析材质字符串

        Args:
            material_str: 材质字符串，如 "Q235,Q355,Q420"

        Returns:
            材质列表
        """
        if '不限' in material_str or material_str == '':
            return []

        materials = []
        for m in material_str.split(','):
            m = m.strip()
            if m:
                materials.append(m)
                # 同时添加带B后缀的版本
                if not m.endswith('B'):
                    materials.append(m + 'B')

        return materials
