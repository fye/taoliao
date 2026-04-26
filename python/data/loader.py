"""
套料优化系统数据加载器

在符合规则的前提下，尽可能提高占用率（利用率）
"""

import pandas as pd
from typing import List, Optional
import os

from core.models import Part, RawMaterial, LossRule
from core.utils import parse_spec, normalize_spec


class DataLoader:
    """数据加载器"""

    def __init__(self):
        self.raw_parts_df: Optional[pd.DataFrame] = None
        self.raw_materials_df: Optional[pd.DataFrame] = None
        self.raw_loss_rules_df: Optional[pd.DataFrame] = None

    def load_parts(self, file_path: str) -> List[Part]:
        """
        加载需求清单

        支持的列名：
        - 段号(只读) 或 段号
        - 部件号
        - 材质
        - 规格
        - 长度(mm)
        - 宽度(mm)
        - 单基数量(件)
        - 单件重量(kg)
        - 单件孔数
        - 备注

        Args:
            file_path: Excel 文件路径

        Returns:
            零件列表
        """
        df = pd.read_excel(file_path)
        self.raw_parts_df = df.copy()

        parts = []
        for _, row in df.iterrows():
            # 获取段号（兼容两种列名）
            segment_no = row.get('段号(只读)', row.get('段号', None))

            # 处理 NaN 值
            def get_value(val, default=None):
                if pd.isna(val):
                    return default
                return val

            part = Part(
                part_no=str(get_value(row['部件号'], '')),
                material=str(get_value(row['材质'], '')),
                spec=str(get_value(row['规格'], '')),
                length=int(get_value(row['长度(mm)'], 0)),
                quantity=int(get_value(row['单基数量(件)'], 0)),
                width=get_value(row.get('宽度(mm)'), None),
                weight=get_value(row.get('单件重量(kg)'), None),
                holes=get_value(row.get('单件孔数'), None),
                remark=get_value(row.get('备注'), None),
                segment_no=str(get_value(segment_no, ''))
            )

            # 解析规格
            try:
                limb_width, thickness = parse_spec(part.spec)
                part.limb_width = limb_width
                part.thickness = thickness
            except ValueError:
                # 规格解析失败，保留 None
                pass

            parts.append(part)

        return parts

    def load_materials(self, file_path: str) -> List[RawMaterial]:
        """
        加载市场清单

        支持的列名：
        - 材质
        - 规格全称
        - 长度
        - A市场货存量

        Args:
            file_path: Excel 文件路径

        Returns:
            原材料列表
        """
        df = pd.read_excel(file_path)
        self.raw_materials_df = df.copy()

        materials = []
        for _, row in df.iterrows():
            # 处理 NaN 值
            def get_value(val, default=None):
                if pd.isna(val):
                    return default
                return val

            material = RawMaterial(
                material_type=str(get_value(row['材质'], '')),
                spec=str(get_value(row['规格全称'], '')),
                length=int(get_value(row['长度'], 0)),
                stock=int(get_value(row['A市场货存量'], 0))
            )

            # 解析规格
            try:
                limb_width, thickness = parse_spec(material.spec)
                material.limb_width = limb_width
                material.thickness = thickness
            except ValueError:
                pass

            materials.append(material)

        return materials

    def load_loss_rules(self, file_path: str) -> List[LossRule]:
        """
        加载损耗规则

        Excel 格式：
        - 第一行是标题
        - 第二行是列名：肢宽范围、厚度范围、材质、单刀损耗、头尾损耗
        - 后续行是规则数据

        Args:
            file_path: Excel 文件路径

        Returns:
            损耗规则列表
        """
        df = pd.read_excel(file_path)
        self.raw_loss_rules_df = df.copy()

        # 跳过第一行（标题行），从第二行开始读取
        # 第一列是标题，第二列开始是实际数据
        rules = []

        # 遍历数据行（跳过标题行）
        for i in range(1, len(df)):
            row = df.iloc[i]

            limb_width_range = str(row.iloc[0])  # 肢宽范围
            thickness_range = str(row.iloc[1])   # 厚度范围
            materials_str = str(row.iloc[2])     # 材质
            single_cut_loss = int(row.iloc[3])   # 单刀损耗
            head_tail_loss = int(row.iloc[4])    # 头尾损耗

            # 解析肢宽范围
            limb_width_min, limb_width_max = self._parse_range(limb_width_range, 'limb_width')

            # 解析厚度范围
            thickness_min, thickness_max = self._parse_range(thickness_range, 'thickness')

            # 解析材质列表
            materials = self._parse_materials(materials_str)

            rule = LossRule(
                limb_width_min=limb_width_min,
                limb_width_max=limb_width_max,
                thickness_min=thickness_min,
                thickness_max=thickness_max,
                materials=materials,
                single_cut_loss=single_cut_loss,
                head_tail_loss=head_tail_loss
            )
            rules.append(rule)

        return rules

    def _parse_range(self, range_str: str, range_type: str) -> tuple:
        """
        解析范围字符串

        支持格式：
        - "L40-L56" -> (40, 56)
        - "L140及以上" -> (140, 999)
        - "小于等于12" -> (None, 12)
        - "大于等于14" -> (14, None)
        - "不限" -> (None, None) 或 (0, 999)

        Args:
            range_str: 范围字符串
            range_type: 'limb_width' 或 'thickness'

        Returns:
            (min, max) 元组
        """
        range_str = str(range_str).strip()

        if range_type == 'limb_width':
            # 肢宽范围解析
            if '不限' in range_str:
                return (0, 999)

            match = re.match(r'L(\d+)-L(\d+)', range_str)
            if match:
                return (int(match.group(1)), int(match.group(2)))

            match = re.match(r'L(\d+)及以上', range_str)
            if match:
                return (int(match.group(1)), 999)

            return (0, 999)
        else:
            # 厚度范围解析
            if '不限' in range_str:
                return (None, None)

            if '小于等于' in range_str or '≤' in range_str:
                match = re.search(r'(\d+)', range_str)
                if match:
                    return (None, int(match.group(1)))

            if '大于等于' in range_str or '≥' in range_str:
                match = re.search(r'(\d+)', range_str)
                if match:
                    return (int(match.group(1)), None)

            return (None, None)

    def _parse_materials(self, materials_str: str) -> List[str]:
        """
        解析材质字符串

        支持格式：
        - "Q235,Q355,Q420" -> ["Q235", "Q355", "Q420"]
        - "不限" -> []
        - "Q460" -> ["Q460"]

        Args:
            materials_str: 材质字符串

        Returns:
            材质列表
        """
        materials_str = str(materials_str).strip()

        if '不限' in materials_str or not materials_str:
            return []

        # 按逗号分割
        materials = [m.strip() for m in materials_str.replace('，', ',').split(',') if m.strip()]
        return materials

    def get_raw_parts_df(self) -> Optional[pd.DataFrame]:
        """获取原始零件数据 DataFrame"""
        return self.raw_parts_df

    def get_raw_materials_df(self) -> Optional[pd.DataFrame]:
        """获取原始原材料数据 DataFrame"""
        return self.raw_materials_df

    def get_raw_loss_rules_df(self) -> Optional[pd.DataFrame]:
        """获取原始损耗规则数据 DataFrame"""
        return self.raw_loss_rules_df


# 导入 re 模块
import re