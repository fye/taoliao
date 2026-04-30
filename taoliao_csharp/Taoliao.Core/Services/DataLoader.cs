using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using OfficeOpenXml;
using Taoliao.Core.Models;

namespace Taoliao.Core.Services
{
    /// <summary>
    /// 数据加载器
    /// </summary>
    public class DataLoader
    {
        /// <summary>
        /// 加载零件需求清单
        /// </summary>
        public List<Part> LoadParts(string filePath)
        {
            var parts = new List<Part>();

            using (var package = new ExcelPackage(new FileInfo(filePath)))
            {
                var worksheet = package.Workbook.Worksheets[0];
                var colIndex = GetColumnIndices(worksheet);

                int rowCount = worksheet.Dimension.Rows;
                for (int row = 2; row <= rowCount; row++)
                {
                    var part = new Part
                    {
                        PartNo = GetCellValue(worksheet, row, colIndex, "部件号") ?? "",
                        Material = GetCellValue(worksheet, row, colIndex, "材质") ?? "",
                        Spec = NormalizeSpec(GetCellValue(worksheet, row, colIndex, "规格") ?? ""),
                        Length = GetIntValue(worksheet, row, colIndex, "长度(mm)"),
                        Quantity = GetIntValue(worksheet, row, colIndex, "单基数量(件)", 1),
                        Width = GetNullableIntValue(worksheet, row, colIndex, "宽度(mm)"),
                        Weight = GetNullableDoubleValue(worksheet, row, colIndex, "单件重量(kg)"),
                        Holes = GetNullableIntValue(worksheet, row, colIndex, "单件孔数"),
                        Remark = GetCellValue(worksheet, row, colIndex, "备注"),
                        SegmentNo = GetCellValue(worksheet, row, colIndex, "段号(只读)")
                    };

                    if (!string.IsNullOrEmpty(part.PartNo) && part.Length > 0)
                    {
                        parts.Add(part);
                    }
                }
            }

            return parts;
        }

        /// <summary>
        /// 加载原材料市场清单
        /// </summary>
        public List<RawMaterial> LoadMaterials(string filePath)
        {
            var materials = new List<RawMaterial>();

            using (var package = new ExcelPackage(new FileInfo(filePath)))
            {
                var worksheet = package.Workbook.Worksheets[0];
                var colIndex = GetColumnIndices(worksheet);

                int rowCount = worksheet.Dimension.Rows;
                for (int row = 2; row <= rowCount; row++)
                {
                    var material = new RawMaterial
                    {
                        MaterialType = GetCellValue(worksheet, row, colIndex, "材质") ?? "",
                        Spec = NormalizeSpec(GetCellValue(worksheet, row, colIndex, "规格全称") ?? ""),
                        Length = GetIntValue(worksheet, row, colIndex, "长度"),
                        Stock = GetIntValue(worksheet, row, colIndex, "A市场货存量", 0)
                    };

                    if (!string.IsNullOrEmpty(material.Spec) && material.Length > 0)
                    {
                        materials.Add(material);
                    }
                }
            }

            return materials;
        }

        /// <summary>
        /// 加载损耗规则
        /// </summary>
        public List<LossRule> LoadLossRules(string filePath)
        {
            var rules = new List<LossRule>();

            using (var package = new ExcelPackage(new FileInfo(filePath)))
            {
                var worksheet = package.Workbook.Worksheets[0];

                // 从第3行开始读取数据（跳过标题行）
                int rowCount = worksheet.Dimension.Rows;
                for (int row = 3; row <= rowCount; row++)
                {
                    var limbWidthStr = GetCellValue(worksheet, row, 0) ?? "";
                    var thicknessStr = GetCellValue(worksheet, row, 1) ?? "";
                    var materialStr = GetCellValue(worksheet, row, 2) ?? "";
                    var singleCutLoss = GetIntValue(worksheet, row, 3, 0);
                    var headTailLoss = GetIntValue(worksheet, row, 4, 0);

                    var rule = new LossRule
                    {
                        LimbWidthRange = ParseRange(limbWidthStr, "L"),
                        ThicknessRange = ParseRange(thicknessStr, ""),
                        Materials = ParseMaterials(materialStr),
                        SingleCutLoss = singleCutLoss,
                        HeadTailLoss = headTailLoss
                    };

                    rules.Add(rule);
                }
            }

            return rules;
        }

        /// <summary>
        /// 获取默认损耗规则
        /// </summary>
        public static List<LossRule> GetDefaultLossRules()
        {
            return new List<LossRule>
            {
                // L40-L56, 不限厚度, 不限材质
                new LossRule
                {
                    LimbWidthRange = new IntRange(40, 56),
                    ThicknessRange = IntRange.Unlimited,
                    Materials = new List<string>(),
                    SingleCutLoss = 10,
                    HeadTailLoss = 30
                },
                // L63-L75, 不限厚度, 不限材质
                new LossRule
                {
                    LimbWidthRange = new IntRange(63, 75),
                    ThicknessRange = IntRange.Unlimited,
                    Materials = new List<string>(),
                    SingleCutLoss = 0,
                    HeadTailLoss = 10
                },
                // L80-L90, 不限厚度, 不限材质
                new LossRule
                {
                    LimbWidthRange = new IntRange(80, 90),
                    ThicknessRange = IntRange.Unlimited,
                    Materials = new List<string>(),
                    SingleCutLoss = 15,
                    HeadTailLoss = 35
                },
                // L100-L180, 厚度<=12, Q235/Q355/Q420
                new LossRule
                {
                    LimbWidthRange = new IntRange(100, 180),
                    ThicknessRange = new IntRange(0, 12),
                    Materials = new List<string> { "Q235", "Q235B", "Q355", "Q355B", "Q420", "Q420B" },
                    SingleCutLoss = 20,
                    HeadTailLoss = 55
                },
                // L140及以上, 厚度>=14, Q235/Q355/Q420
                new LossRule
                {
                    LimbWidthRange = new IntRange(140, 999),
                    ThicknessRange = new IntRange(14, 999),
                    Materials = new List<string> { "Q235", "Q235B", "Q355", "Q355B", "Q420", "Q420B" },
                    SingleCutLoss = 2,
                    HeadTailLoss = 8
                },
                // 不限规格, Q460材质
                new LossRule
                {
                    LimbWidthRange = IntRange.Unlimited,
                    ThicknessRange = IntRange.Unlimited,
                    Materials = new List<string> { "Q460", "Q460B" },
                    SingleCutLoss = 2,
                    HeadTailLoss = 8
                }
            };
        }

        private Dictionary<string, int> GetColumnIndices(ExcelWorksheet worksheet)
        {
            var indices = new Dictionary<string, int>();
            int colCount = worksheet.Dimension.Columns;

            for (int col = 1; col <= colCount; col++)
            {
                var value = worksheet.Cells[1, col].Text?.Trim();
                if (!string.IsNullOrEmpty(value))
                {
                    indices[value] = col - 1; // 0-based index
                }
            }
            return indices;
        }

        private string GetCellValue(ExcelWorksheet worksheet, int row, int col)
        {
            return worksheet.Cells[row, col + 1].Text?.Trim();
        }

        private string GetCellValue(ExcelWorksheet worksheet, int row, Dictionary<string, int> colIndex, string colName)
        {
            if (!colIndex.ContainsKey(colName)) return null;
            return worksheet.Cells[row, colIndex[colName] + 1].Text?.Trim();
        }

        private int GetIntValue(ExcelWorksheet worksheet, int row, int col, int defaultValue = 0)
        {
            var text = worksheet.Cells[row, col + 1].Text?.Trim();
            if (string.IsNullOrEmpty(text)) return defaultValue;
            int result;
            return int.TryParse(text, out result) ? result : defaultValue;
        }

        private int GetIntValue(ExcelWorksheet worksheet, int row, Dictionary<string, int> colIndex, string colName, int defaultValue = 0)
        {
            if (!colIndex.ContainsKey(colName)) return defaultValue;
            return GetIntValue(worksheet, row, colIndex[colName], defaultValue);
        }

        private int? GetNullableIntValue(ExcelWorksheet worksheet, int row, Dictionary<string, int> colIndex, string colName)
        {
            if (!colIndex.ContainsKey(colName)) return null;
            var text = worksheet.Cells[row, colIndex[colName] + 1].Text?.Trim();
            if (string.IsNullOrEmpty(text)) return null;
            int result;
            return int.TryParse(text, out result) ? result : null;
        }

        private double? GetNullableDoubleValue(ExcelWorksheet worksheet, int row, Dictionary<string, int> colIndex, string colName)
        {
            if (!colIndex.ContainsKey(colName)) return null;
            var text = worksheet.Cells[row, colIndex[colName] + 1].Text?.Trim();
            if (string.IsNullOrEmpty(text)) return null;
            double result;
            return double.TryParse(text, out result) ? result : null;
        }

        private string NormalizeSpec(string spec)
        {
            if (string.IsNullOrEmpty(spec)) return spec;
            // 统一规格格式：将 * 替换为 X
            return spec.Replace('*', 'X').ToUpper();
        }

        private IntRange ParseRange(string rangeStr, string prefix)
        {
            rangeStr = rangeStr.Trim();

            // 不限
            if (rangeStr.Contains("不限") || string.IsNullOrEmpty(rangeStr))
                return IntRange.Unlimited;

            // 移除前缀
            if (!string.IsNullOrEmpty(prefix) && rangeStr.StartsWith(prefix))
                rangeStr = rangeStr.Substring(prefix.Length);

            // L40-L56 格式
            if (rangeStr.Contains('-'))
            {
                var parts = rangeStr.Split('-');
                if (parts.Length == 2)
                {
                    // 移除可能的前缀
                    string minStr = parts[0].Trim();
                    string maxStr = parts[1].Trim();
                    if (!string.IsNullOrEmpty(prefix) && minStr.StartsWith(prefix))
                        minStr = minStr.Substring(prefix.Length);
                    if (!string.IsNullOrEmpty(prefix) && maxStr.StartsWith(prefix))
                        maxStr = maxStr.Substring(prefix.Length);

                    int min, max;
                    if (int.TryParse(minStr, out min) && int.TryParse(maxStr, out max))
                        return new IntRange(min, max);
                }
            }

            // 小于等于12 格式
            if (rangeStr.Contains("小于等于"))
            {
                var match = Regex.Match(rangeStr, @"\d+");
                if (match.Success)
                {
                    int max;
                    if (int.TryParse(match.Value, out max))
                        return new IntRange(0, max);
                }
            }

            // 大于等于14 格式
            if (rangeStr.Contains("大于等于"))
            {
                var match = Regex.Match(rangeStr, @"\d+");
                if (match.Success)
                {
                    int min;
                    if (int.TryParse(match.Value, out min))
                        return new IntRange(min, 999);
                }
            }

            // L140及以上 格式
            if (rangeStr.Contains("及以上"))
            {
                var match = Regex.Match(rangeStr, @"\d+");
                if (match.Success)
                {
                    int min;
                    if (int.TryParse(match.Value, out min))
                        return new IntRange(min, 999);
                }
            }

            return IntRange.Unlimited;
        }

        private List<string> ParseMaterials(string materialStr)
        {
            if (materialStr.Contains("不限") || string.IsNullOrEmpty(materialStr))
                return new List<string>();

            var materials = new List<string>();
            foreach (var m in materialStr.Split(','))
            {
                var trimmed = m.Trim();
                if (!string.IsNullOrEmpty(trimmed))
                {
                    materials.Add(trimmed);
                    // 同时添加带B后缀的版本
                    if (!trimmed.EndsWith("B"))
                        materials.Add(trimmed + "B");
                    // Q355和Q345是新旧标准的关系，需要同时支持
                    if (trimmed == "Q355")
                    {
                        materials.Add("Q345");
                        materials.Add("Q345B");
                    }
                    else if (trimmed == "Q355B")
                    {
                        materials.Add("Q345");
                        materials.Add("Q345B");
                    }
                }
            }
            return materials;
        }
    }
}