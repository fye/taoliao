using Taoliao.Core.Models;
using Taoliao.Core.Services;

namespace Taoliao.Core.Algorithms;

/// <summary>
/// 贪心套料求解器
/// </summary>
public class GreedyNestingSolver
{
    private readonly NestingConfig _config;
    private readonly LossCalculator _lossCalculator;

    public GreedyNestingSolver(NestingConfig config, LossCalculator lossCalculator)
    {
        _config = config;
        _lossCalculator = lossCalculator;
    }

    /// <summary>
    /// 使用贪心算法求解
    /// </summary>
    public List<CuttingPlan> Solve(
        List<Part> parts,
        List<RawMaterial> materials,
        string spec,
        string materialType)
    {
        var lossRule = _lossCalculator.GetLossRule(spec, materialType);

        // 复制零件列表（带剩余数量）
        var remainingParts = parts.Select(p => (p.PartNo, p.Length, p.Quantity)).ToList();

        // 获取可用原材料长度（按升序排列）
        var availableLengths = materials.Select(m => m.Length).Distinct().OrderBy(l => l).ToList();
        var lengthToMaterial = materials.GroupBy(m => m.Length).ToDictionary(g => g.Key, g => g.First());

        var cuttingPlans = new List<CuttingPlan>();

        while (remainingParts.Any(p => p.Quantity > 0))
        {
            // 过滤出还有需求的零件
            var activeParts = remainingParts.Where(p => p.Quantity > 0).ToList();
            if (!activeParts.Any())
                break;

            // 选择最优的原材料长度和填充方案
            CuttingPlan? bestPlan = null;
            double bestUtilization = -1;

            foreach (var length in availableLengths)
            {
                if (!lengthToMaterial.TryGetValue(length, out var rawMat))
                    continue;

                var plan = FillMaterial(rawMat, activeParts, lossRule);

                if (plan != null && plan.Utilization > bestUtilization)
                {
                    bestUtilization = plan.Utilization;
                    bestPlan = plan;
                }
            }

            if (bestPlan == null)
            {
                // 无法填充，使用最长的原材料
                var length = availableLengths.Last();
                var rawMat = lengthToMaterial[length];

                // 只放一个最大的零件
                var sortedParts = activeParts.OrderByDescending(p => p.Length).ToList();
                var (partNo, partLength, _) = sortedParts.First();

                var cutCount = 1;
                var usedLength = partLength;
                var totalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * cutCount;
                var remaining = length - usedLength - totalLoss;

                bestPlan = new CuttingPlan
                {
                    RawMaterial = rawMat,
                    Parts = new List<(string, int, int)> { (partNo, partLength, 1) },
                    CutCount = cutCount,
                    SingleCutLoss = lossRule.SingleCutLoss,
                    HeadTailLoss = lossRule.HeadTailLoss,
                    UsedLength = usedLength,
                    TotalLoss = totalLoss,
                    RemainingLength = remaining,
                    Utilization = (double)usedLength / length
                };
            }

            // 更新剩余零件数量
            foreach (var (partNo, partLength, qty) in bestPlan.Parts)
            {
                for (int i = 0; i < remainingParts.Count; i++)
                {
                    if (remainingParts[i].PartNo == partNo && remainingParts[i].Length == partLength)
                    {
                        remainingParts[i] = (partNo, partLength, remainingParts[i].Quantity - qty);
                        break;
                    }
                }
            }

            cuttingPlans.Add(bestPlan);
        }

        return cuttingPlans;
    }

    private CuttingPlan? FillMaterial(
        RawMaterial rawMaterial,
        List<(string PartNo, int Length, int Quantity)> parts,
        LossRule lossRule)
    {
        var availableLength = rawMaterial.Length - lossRule.HeadTailLoss;

        // 按长度降序排列零件
        var sortedParts = parts.OrderByDescending(p => p.Length).ToList();

        var selectedParts = new List<(string PartNo, int Length, int Quantity)>();
        var partNoSet = new HashSet<string>();

        foreach (var (partNo, partLength, remainingQty) in sortedParts)
        {
            if (remainingQty <= 0)
                continue;

            // 检查零件号限制
            if (partNoSet.Count >= _config.MaxPartsPerMaterial && !partNoSet.Contains(partNo))
                continue;

            // 计算可加入数量
            var currentLength = selectedParts.Sum(p => p.Length * p.Quantity);
            var maxQty = Math.Min(
                remainingQty,
                (int)((availableLength - currentLength) / partLength)
            );

            if (maxQty > 0)
            {
                selectedParts.Add((partNo, partLength, maxQty));
                partNoSet.Add(partNo);
            }
        }

        if (!selectedParts.Any())
            return null;

        var cutCount = selectedParts.Count;
        var usedLength = selectedParts.Sum(p => p.Length * p.Quantity);
        var totalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * cutCount;
        var remaining = rawMaterial.Length - usedLength - totalLoss;

        return new CuttingPlan
        {
            RawMaterial = rawMaterial,
            Parts = selectedParts,
            CutCount = cutCount,
            SingleCutLoss = lossRule.SingleCutLoss,
            HeadTailLoss = lossRule.HeadTailLoss,
            UsedLength = usedLength,
            TotalLoss = totalLoss,
            RemainingLength = remaining,
            Utilization = (double)usedLength / rawMaterial.Length
        };
    }
}
