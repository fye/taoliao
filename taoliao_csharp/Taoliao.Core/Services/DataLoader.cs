using System.Text.RegularExpressions;
using NPOI.SS.UserModel;
using NPOI.XSSF.UserModel;
using Taoliao.Core.Models;

namespace Taoliao.Core.Services;

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

        using var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read);
        var workbook = new XSSFWorkbook(fs);
        var sheet = workbook.GetSheetAt(0);

        // 获取列索引
        var headerRow = sheet.GetRow(0);
        var colIndex = GetColumnIndices(headerRow);

        for (int i = 1; i <= sheet.LastRowNum; i++)
        {
            var row = sheet.GetRow(i);
            if (row == null) continue;

            var part = new Part
            {
                PartNo = GetCellValue(row, colIndex.GetValueOrDefault("部件号", -1)) ?? "",
                Material = GetCellValue(row, colIndex.GetValueOrDefault("材质", -1)) ?? "",
                Spec = GetCellValue(row, colIndex.GetValueOrDefault("规格", -1)) ?? "",
                Length = GetIntValue(row, colIndex.GetValueOrDefault("长度(mm)", -1)),
                Quantity = GetIntValue(row, colIndex.GetValueOrDefault("单基数量(件)", -1), 1),
                Width = GetNullableIntValue(row, colIndex.GetValueOrDefault("宽度(mm)", -1)),
                Weight = GetNullableDoubleValue(row, colIndex.GetValueOrDefault("单件重量(kg)", -1)),
                Holes = GetNullableIntValue(row, colIndex.GetValueOrDefault("单件孔数", -1)),
                Remark = GetCellValue(row, colIndex.GetValueOrDefault("备注", -1)),
                SegmentNo = GetCellValue(row, colIndex.GetValueOrDefault("段号(只读)", -1))
            };

            if (!string.IsNullOrEmpty(part.PartNo) && part.Length > 0)
            {
                parts.Add(part);
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

        using var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read);
        var workbook = new XSSFWorkbook(fs);
        var sheet = workbook.GetSheetAt(0);

        var headerRow = sheet.GetRow(0);
        var colIndex = GetColumnIndices(headerRow);

        for (int i = 1; i <= sheet.LastRowNum; i++)
        {
            var row = sheet.GetRow(i);
            if (row == null) continue;

            var material = new RawMaterial
            {
                MaterialType = GetCellValue(row, colIndex.GetValueOrDefault("材质", -1)) ?? "",
                Spec = GetCellValue(row, colIndex.GetValueOrDefault("规格全称", -1)) ?? "",
                Length = GetIntValue(row, colIndex.GetValueOrDefault("长度", -1)),
                Stock = GetIntValue(row, colIndex.GetValueOrDefault("A市场货存量", -1), 0)
            };

            if (!string.IsNullOrEmpty(material.Spec) && material.Length > 0)
            {
                materials.Add(material);
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

        using var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read);
        var workbook = new XSSFWorkbook(fs);
        var sheet = workbook.GetSheetAt(0);

        // 从第3行开始读取数据（跳过标题行）
        for (int i = 2; i <= sheet.LastRowNum; i++)
        {
            var row = sheet.GetRow(i);
            if (row == null) continue;

            var limbWidthStr = GetCellValue(row, 0) ?? "";
            var thicknessStr = GetCellValue(row, 1) ?? "";
            var materialStr = GetCellValue(row, 2) ?? "";
            var singleCutLoss = GetIntValue(row, 3, 0);
            var headTailLoss = GetIntValue(row, 4, 0);

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
                LimbWidthRange = (40, 56),
                ThicknessRange = (0, 999),
                Materials = new List<string>(),
                SingleCutLoss = 10,
                HeadTailLoss = 30
            },
            // L63-L75, 不限厚度, 不限材质
            new LossRule
            {
                LimbWidthRange = (63, 75),
                ThicknessRange = (0, 999),
                Materials = new List<string>(),
                SingleCutLoss = 0,
                HeadTailLoss = 10
            },
            // L80-L90, 不限厚度, 不限材质
            new LossRule
            {
                LimbWidthRange = (80, 90),
                ThicknessRange = (0, 999),
                Materials = new List<string>(),
                SingleCutLoss = 15,
                HeadTailLoss = 35
            },
            // L100-L180, 厚度<=12, Q235/Q355/Q420
            new LossRule
            {
                LimbWidthRange = (100, 180),
                ThicknessRange = (0, 12),
                Materials = new List<string> { "Q235", "Q235B", "Q355", "Q355B", "Q420", "Q420B" },
                SingleCutLoss = 20,
                HeadTailLoss = 55
            },
            // L140及以上, 厚度>=14, Q235/Q355/Q420
            new LossRule
            {
                LimbWidthRange = (140, 999),
                ThicknessRange = (14, 999),
                Materials = new List<string> { "Q235", "Q235B", "Q355", "Q355B", "Q420", "Q420B" },
                SingleCutLoss = 2,
                HeadTailLoss = 8
            },
            // 不限规格, Q460材质
            new LossRule
            {
                LimbWidthRange = (0, 999),
                ThicknessRange = (0, 999),
                Materials = new List<string> { "Q460", "Q460B" },
                SingleCutLoss = 2,
                HeadTailLoss = 8
            }
        };
    }

    private Dictionary<string, int> GetColumnIndices(IRow? headerRow)
    {
        var indices = new Dictionary<string, int>();
        if (headerRow == null) return indices;

        for (int i = 0; i < headerRow.LastCellNum; i++)
        {
            var cell = headerRow.GetCell(i);
            if (cell != null)
            {
                var value = cell.ToString()?.Trim() ?? "";
                if (!string.IsNullOrEmpty(value))
                {
                    indices[value] = i;
                }
            }
        }
        return indices;
    }

    private string? GetCellValue(IRow row, int colIndex)
    {
        if (colIndex < 0) return null;
        var cell = row.GetCell(colIndex);
        return cell?.ToString()?.Trim();
    }

    private int GetIntValue(IRow row, int colIndex, int defaultValue = 0)
    {
        if (colIndex < 0) return defaultValue;
        var cell = row.GetCell(colIndex);
        if (cell == null) return defaultValue;

        return cell.CellType switch
        {
            CellType.Numeric => (int)cell.NumericCellValue,
            CellType.String when int.TryParse(cell.StringCellValue, out var val) => val,
            _ => defaultValue
        };
    }

    private int? GetNullableIntValue(IRow row, int colIndex)
    {
        if (colIndex < 0) return null;
        var cell = row.GetCell(colIndex);
        if (cell == null) return null;

        return cell.CellType switch
        {
            CellType.Numeric => (int?)cell.NumericCellValue,
            CellType.String when int.TryParse(cell.StringCellValue, out var val) => val,
            _ => null
        };
    }

    private double? GetNullableDoubleValue(IRow row, int colIndex)
    {
        if (colIndex < 0) return null;
        var cell = row.GetCell(colIndex);
        if (cell == null) return null;

        return cell.CellType switch
        {
            CellType.Numeric => cell.NumericCellValue,
            CellType.String when double.TryParse(cell.StringCellValue, out var val) => val,
            _ => null
        };
    }

    private (int, int) ParseRange(string rangeStr, string prefix)
    {
        rangeStr = rangeStr.Trim();

        // 不限
        if (rangeStr.Contains("不限") || string.IsNullOrEmpty(rangeStr))
            return (0, 999);

        // 移除前缀
        if (!string.IsNullOrEmpty(prefix) && rangeStr.StartsWith(prefix))
            rangeStr = rangeStr[prefix.Length..];

        // L40-L56 格式
        if (rangeStr.Contains('-'))
        {
            var parts = rangeStr.Split('-');
            if (parts.Length == 2)
            {
                if (int.TryParse(parts[0].Trim(), out var min) &&
                    int.TryParse(parts[1].Trim(), out var max))
                {
                    return (min, max);
                }
            }
        }

        // 小于等于12 格式
        if (rangeStr.Contains("小于等于"))
        {
            var match = Regex.Match(rangeStr, @"\d+");
            if (match.Success && int.TryParse(match.Value, out var max))
                return (0, max);
        }

        // 大于等于14 格式
        if (rangeStr.Contains("大于等于"))
        {
            var match = Regex.Match(rangeStr, @"\d+");
            if (match.Success && int.TryParse(match.Value, out var min))
                return (min, 999);
        }

        // L140及以上 格式
        if (rangeStr.Contains("及以上"))
        {
            var match = Regex.Match(rangeStr, @"\d+");
            if (match.Success && int.TryParse(match.Value, out var min))
                return (min, 999);
        }

        return (0, 999);
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
                if (!trimmed.EndsWith('B'))
                    materials.Add(trimmed + "B");
            }
        }
        return materials;
    }
}
