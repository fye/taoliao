namespace Taoliao.Core.Models;

/// <summary>
/// 零件信息
/// </summary>
public class Part
{
    /// <summary>
    /// 部件号
    /// </summary>
    public string PartNo { get; set; } = string.Empty;

    /// <summary>
    /// 材质 (如 Q235B, Q355B)
    /// </summary>
    public string Material { get; set; } = string.Empty;

    /// <summary>
    /// 规格 (如 L90X7)
    /// </summary>
    public string Spec { get; set; } = string.Empty;

    /// <summary>
    /// 长度(mm)
    /// </summary>
    public int Length { get; set; }

    /// <summary>
    /// 需求数量
    /// </summary>
    public int Quantity { get; set; }

    /// <summary>
    /// 宽度(mm)
    /// </summary>
    public int? Width { get; set; }

    /// <summary>
    /// 单件重量(kg)
    /// </summary>
    public double? Weight { get; set; }

    /// <summary>
    /// 单件孔数
    /// </summary>
    public int? Holes { get; set; }

    /// <summary>
    /// 备注
    /// </summary>
    public string? Remark { get; set; }

    /// <summary>
    /// 段号
    /// </summary>
    public string? SegmentNo { get; set; }
}

/// <summary>
/// 原材料信息
/// </summary>
public class RawMaterial
{
    /// <summary>
    /// 材质
    /// </summary>
    public string MaterialType { get; set; } = string.Empty;

    /// <summary>
    /// 规格 (如 L100X10)
    /// </summary>
    public string Spec { get; set; } = string.Empty;

    /// <summary>
    /// 长度(mm)
    /// </summary>
    public int Length { get; set; }

    /// <summary>
    /// 市场货存量
    /// </summary>
    public int Stock { get; set; }
}

/// <summary>
/// 损耗规则
/// </summary>
public class LossRule
{
    /// <summary>
    /// 肢宽范围 (min, max)
    /// </summary>
    public (int Min, int Max) LimbWidthRange { get; set; }

    /// <summary>
    /// 厚度范围 (min, max), (0, 999)表示不限
    /// </summary>
    public (int Min, int Max) ThicknessRange { get; set; }

    /// <summary>
    /// 适用材质，空列表表示不限
    /// </summary>
    public List<string> Materials { get; set; } = new();

    /// <summary>
    /// 单刀损耗(mm)
    /// </summary>
    public int SingleCutLoss { get; set; }

    /// <summary>
    /// 头尾损耗(mm)
    /// </summary>
    public int HeadTailLoss { get; set; }

    /// <summary>
    /// 检查规则是否匹配给定的规格和材质
    /// </summary>
    public bool Matches(string spec, string material)
    {
        var (limbWidth, thickness) = ParseSpec(spec);
        if (limbWidth == null) return false;

        // 检查肢宽范围
        if (LimbWidthRange.Min > limbWidth || limbWidth > LimbWidthRange.Max)
            return false;

        // 检查厚度范围
        if (ThicknessRange != (0, 999))
        {
            if (ThicknessRange.Min > thickness || thickness > ThicknessRange.Max)
                return false;
        }

        // 检查材质
        if (Materials.Count > 0 && !Materials.Contains(material))
            return false;

        return true;
    }

    /// <summary>
    /// 解析规格字符串，返回(肢宽, 厚度)
    /// </summary>
    private static (int?, int?) ParseSpec(string spec)
    {
        try
        {
            var upperSpec = spec.ToUpper().Replace('X', 'X');
            if (!upperSpec.StartsWith('L'))
                return (null, null);

            var parts = upperSpec[1..].Split('X');
            if (parts.Length != 2)
                return (null, null);

            return (int.Parse(parts[0]), int.Parse(parts[1]));
        }
        catch
        {
            return (null, null);
        }
    }
}

/// <summary>
/// 单根原材料的切割方案
/// </summary>
public class CuttingPlan
{
    /// <summary>
    /// 使用的原材料
    /// </summary>
    public RawMaterial RawMaterial { get; set; } = null!;

    /// <summary>
    /// 切割的零件列表 [(部件号, 长度, 数量), ...]
    /// </summary>
    public List<(string PartNo, int Length, int Quantity)> Parts { get; set; } = new();

    /// <summary>
    /// 切割刀数
    /// </summary>
    public int CutCount { get; set; }

    /// <summary>
    /// 单刀损耗
    /// </summary>
    public int SingleCutLoss { get; set; }

    /// <summary>
    /// 头尾损耗
    /// </summary>
    public int HeadTailLoss { get; set; }

    /// <summary>
    /// 零件使用长度
    /// </summary>
    public int UsedLength { get; set; }

    /// <summary>
    /// 总损耗
    /// </summary>
    public int TotalLoss { get; set; }

    /// <summary>
    /// 剩余长度
    /// </summary>
    public int RemainingLength { get; set; }

    /// <summary>
    /// 利用率
    /// </summary>
    public double Utilization { get; set; }

    /// <summary>
    /// 生成切割部件号描述
    /// </summary>
    public string PartsDescription =>
        string.Join(" + ", Parts.Select(p => $"{p.PartNo}/{p.Length}*{p.Quantity}"));

    /// <summary>
    /// 损耗比
    /// </summary>
    public double LossRatio => RawMaterial.Length > 0
        ? (double)TotalLoss / RawMaterial.Length
        : 0;
}

/// <summary>
/// 套料结果
/// </summary>
public class NestingResult
{
    /// <summary>
    /// 原始需求清单
    /// </summary>
    public List<Part> OriginalParts { get; set; } = new();

    /// <summary>
    /// 切割方案列表
    /// </summary>
    public List<CuttingPlan> CuttingPlans { get; set; } = new();

    /// <summary>
    /// 原材料汇总
    /// </summary>
    public Dictionary<(string Material, string Spec), MaterialSummary> MaterialSummary { get; set; } = new();

    /// <summary>
    /// 总利用率
    /// </summary>
    public double TotalUtilization
    {
        get
        {
            var totalPartLength = CuttingPlans.Sum(p => p.UsedLength);
            var totalMaterialLength = CuttingPlans.Sum(p => p.RawMaterial.Length);
            return totalMaterialLength > 0 ? (double)totalPartLength / totalMaterialLength : 0;
        }
    }

    /// <summary>
    /// 总损耗比
    /// </summary>
    public double TotalLossRatio
    {
        get
        {
            var totalLoss = CuttingPlans.Sum(p => p.TotalLoss);
            var totalMaterialLength = CuttingPlans.Sum(p => p.RawMaterial.Length);
            return totalMaterialLength > 0 ? (double)totalLoss / totalMaterialLength : 0;
        }
    }
}

/// <summary>
/// 原材料汇总信息
/// </summary>
public class MaterialSummary
{
    public int Count { get; set; }
    public int TotalLength { get; set; }
    public int TotalUsed { get; set; }
    public int TotalLoss { get; set; }
    public double Utilization { get; set; }
    public double LossRatio { get; set; }
}

/// <summary>
/// 套料配置参数
/// </summary>
public class NestingConfig
{
    /// <summary>
    /// 单根原材料零件号上限
    /// </summary>
    public int MaxPartsPerMaterial { get; set; } = 3;

    /// <summary>
    /// 单零件号原材料上限
    /// </summary>
    public int MaxMaterialsPerPart { get; set; } = 5;

    /// <summary>
    /// 余料上限(mm)
    /// </summary>
    public int MaxRemainder { get; set; } = 1000;

    /// <summary>
    /// 求解时间限制(秒)
    /// </summary>
    public int TimeLimit { get; set; } = 3600;
}
