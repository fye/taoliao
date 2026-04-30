using System;
using System.Collections.Generic;
using System.Linq;

namespace Taoliao.Core.Models
{
    /// <summary>
    /// 零件信息
    /// </summary>
    public class Part
    {
        /// <summary>
        /// 部件号
        /// </summary>
        public string PartNo { get; set; }

        /// <summary>
        /// 材质 (如 Q235B, Q355B)
        /// </summary>
        public string Material { get; set; }

        /// <summary>
        /// 规格 (如 L90X7)
        /// </summary>
        public string Spec { get; set; }

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
        public string Remark { get; set; }

        /// <summary>
        /// 段号
        /// </summary>
        public string SegmentNo { get; set; }

        public Part()
        {
            PartNo = "";
            Material = "";
            Spec = "";
        }
    }

    /// <summary>
    /// 原材料信息
    /// </summary>
    public class RawMaterial
    {
        /// <summary>
        /// 材质
        /// </summary>
        public string MaterialType { get; set; }

        /// <summary>
        /// 规格 (如 L100X10)
        /// </summary>
        public string Spec { get; set; }

        /// <summary>
        /// 长度(mm)
        /// </summary>
        public int Length { get; set; }

        /// <summary>
        /// 市场货存量
        /// </summary>
        public int Stock { get; set; }

        public RawMaterial()
        {
            MaterialType = "";
            Spec = "";
        }
    }

    /// <summary>
    /// 范围
    /// </summary>
    public class IntRange
    {
        public int Min { get; set; }
        public int Max { get; set; }

        public IntRange(int min, int max)
        {
            Min = min;
            Max = max;
        }

        public static IntRange Unlimited
        {
            get { return new IntRange(0, 999); }
        }
    }

    /// <summary>
    /// 损耗规则
    /// </summary>
    public class LossRule
    {
        /// <summary>
        /// 肢宽范围 (min, max)
        /// </summary>
        public IntRange LimbWidthRange { get; set; }

        /// <summary>
        /// 厚度范围 (min, max), (0, 999)表示不限
        /// </summary>
        public IntRange ThicknessRange { get; set; }

        /// <summary>
        /// 适用材质，空列表表示不限
        /// </summary>
        public List<string> Materials { get; set; }

        /// <summary>
        /// 单刀损耗(mm)
        /// </summary>
        public int SingleCutLoss { get; set; }

        /// <summary>
        /// 头尾损耗(mm)
        /// </summary>
        public int HeadTailLoss { get; set; }

        public LossRule()
        {
            Materials = new List<string>();
            LimbWidthRange = IntRange.Unlimited;
            ThicknessRange = IntRange.Unlimited;
        }

        /// <summary>
        /// 检查规则是否匹配给定的规格和材质
        /// </summary>
        public bool Matches(string spec, string material)
        {
            var result = ParseSpec(spec);
            int? limbWidth = result.Item1;
            int? thickness = result.Item2;

            if (limbWidth == null) return false;

            // 检查肢宽范围
            if (limbWidth < LimbWidthRange.Min || limbWidth > LimbWidthRange.Max)
                return false;

            // 检查厚度范围
            if (ThicknessRange.Min != 0 || ThicknessRange.Max != 999)
            {
                if (thickness < ThicknessRange.Min || thickness > ThicknessRange.Max)
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
        public static Tuple<int?, int?> ParseSpec(string spec)
        {
            try
            {
                var upperSpec = spec.ToUpper().Replace('X', 'X');
                if (!upperSpec.StartsWith("L"))
                    return Tuple.Create<int?, int?>(null, null);

                var parts = upperSpec.Substring(1).Split('X');
                if (parts.Length != 2)
                    return Tuple.Create<int?, int?>(null, null);

                return Tuple.Create<int?, int?>(int.Parse(parts[0]), int.Parse(parts[1]));
            }
            catch
            {
                return Tuple.Create<int?, int?>(null, null);
            }
        }
    }

    /// <summary>
    /// 零件分配信息
    /// </summary>
    public class PartAllocation
    {
        public string PartNo { get; set; }
        public int Length { get; set; }
        public int Quantity { get; set; }

        public PartAllocation(string partNo, int length, int quantity)
        {
            PartNo = partNo;
            Length = length;
            Quantity = quantity;
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
        public RawMaterial RawMaterial { get; set; }

        /// <summary>
        /// 切割的零件列表
        /// </summary>
        public List<PartAllocation> Parts { get; set; }

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

        public CuttingPlan()
        {
            Parts = new List<PartAllocation>();
        }

        /// <summary>
        /// 生成切割部件号描述
        /// </summary>
        public string PartsDescription
        {
            get
            {
                return string.Join(" + ", Parts.Select(p => string.Format("{0}/{1}*{2}", p.PartNo, p.Length, p.Quantity)));
            }
        }

        /// <summary>
        /// 损耗比
        /// </summary>
        public double LossRatio
        {
            get
            {
                return RawMaterial != null && RawMaterial.Length > 0
                    ? (double)TotalLoss / RawMaterial.Length
                    : 0;
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
        public Dictionary<int, int> LengthDistribution { get; set; }

        public MaterialSummary()
        {
            LengthDistribution = new Dictionary<int, int>();
        }
    }

    /// <summary>
    /// 套料结果
    /// </summary>
    public class NestingResult
    {
        /// <summary>
        /// 原始需求清单
        /// </summary>
        public List<Part> OriginalParts { get; set; }

        /// <summary>
        /// 切割方案列表
        /// </summary>
        public List<CuttingPlan> CuttingPlans { get; set; }

        /// <summary>
        /// 原材料汇总
        /// </summary>
        public Dictionary<string, MaterialSummary> MaterialSummary { get; set; }

        public NestingResult()
        {
            OriginalParts = new List<Part>();
            CuttingPlans = new List<CuttingPlan>();
            MaterialSummary = new Dictionary<string, MaterialSummary>();
        }

        /// <summary>
        /// 总利用率
        /// </summary>
        public double TotalUtilization
        {
            get
            {
                long totalPartLength = 0;
                long totalMaterialLength = 0;
                foreach (var p in CuttingPlans)
                {
                    totalPartLength += p.UsedLength;
                    totalMaterialLength += p.RawMaterial.Length;
                }
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
                long totalLoss = 0;
                long totalMaterialLength = 0;
                foreach (var p in CuttingPlans)
                {
                    totalLoss += p.TotalLoss;
                    totalMaterialLength += p.RawMaterial.Length;
                }
                return totalMaterialLength > 0 ? (double)totalLoss / totalMaterialLength : 0;
            }
        }
    }

    /// <summary>
    /// 套料配置参数
    /// </summary>
    public class NestingConfig
    {
        /// <summary>
        /// 单根原材料零件号上限
        /// </summary>
        public int MaxPartsPerMaterial { get; set; }

        /// <summary>
        /// 单零件号原材料上限
        /// </summary>
        public int MaxMaterialsPerPart { get; set; }

        /// <summary>
        /// 余料上限(mm)
        /// </summary>
        public int MaxRemainder { get; set; }

        /// <summary>
        /// 求解时间限制(秒)
        /// </summary>
        public int TimeLimit { get; set; }

        public NestingConfig()
        {
            MaxPartsPerMaterial = 3;
            MaxMaterialsPerPart = 5;
            MaxRemainder = 1000;
            TimeLimit = 120;
        }
    }
}
