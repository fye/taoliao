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

        // 后处理优化：重新优化低利用率的方案
        cuttingPlans = PostOptimize(cuttingPlans, materials, lossRule);

        return cuttingPlans;
    }

    /// <summary>
    /// 后处理优化：收集低利用率方案的零件，重新贪心分配
    /// </summary>
    private List<CuttingPlan> PostOptimize(
        List<CuttingPlan> cuttingPlans,
        List<RawMaterial> materials,
        LossRule lossRule)
    {
        if (cuttingPlans.Count <= 1)
            return cuttingPlans;

        // 找出低利用率的方案（<70%）
        const double lowUtilThreshold = 0.70;
        var lowUtilIndices = new List<int>();
        for (int i = 0; i < cuttingPlans.Count; i++)
        {
            if (cuttingPlans[i].Utilization < lowUtilThreshold)
                lowUtilIndices.Add(i);
        }

        if (!lowUtilIndices.Any())
            return cuttingPlans;

        // 收集低利用率方案中的所有零件
        var lowUtilParts = new Dictionary<(string, int), int>();  // (partNo, length) -> totalQty
        foreach (var i in lowUtilIndices)
        {
            var plan = cuttingPlans[i];
            foreach (var (partNo, length, qty) in plan.Parts)
            {
                var key = (partNo, length);
                if (!lowUtilParts.ContainsKey(key))
                    lowUtilParts[key] = 0;
                lowUtilParts[key] += qty;
            }
        }

        if (!lowUtilParts.Any())
            return cuttingPlans;

        // 收集高利用率方案中的零件（用于尝试重新组合）
        var highUtilParts = new Dictionary<(string, int), int>();
        for (int i = 0; i < cuttingPlans.Count; i++)
        {
            if (lowUtilIndices.Contains(i))
                continue;
            if (cuttingPlans[i].Utilization < lowUtilThreshold)
                continue;
            foreach (var (partNo, length, qty) in cuttingPlans[i].Parts)
            {
                var key = (partNo, length);
                if (!highUtilParts.ContainsKey(key))
                    highUtilParts[key] = 0;
                highUtilParts[key] += qty;
            }
        }

        // 收集所有可用原材料长度
        var availableLengths = materials.Select(m => m.Length).Distinct().OrderBy(l => l).ToList();
        var lengthToMaterial = materials.GroupBy(m => m.Length).ToDictionary(g => g.Key, g => g.First());

        // 将低利用率方案的零件重新打包
        var partList = lowUtilParts.Select(kv => (kv.Key.Item1, kv.Key.Item2, kv.Value)).ToList();
        partList.Sort((a, b) => b.Item2.CompareTo(a.Item2));  // 按长度降序

        var newPlans = new List<CuttingPlan>();
        var remaining = partList.ToList();

        while (remaining.Any(p => p.Quantity > 0))
        {
            var active = remaining.Where(p => p.Quantity > 0).ToList();
            if (!active.Any())
                break;

            CuttingPlan? bestPlan = null;
            double bestScore = -1;

            foreach (var length in availableLengths)
            {
                if (!lengthToMaterial.TryGetValue(length, out var rawMat))
                    continue;

                var plan = FillMaterial(rawMat, active, lossRule);
                if (plan != null)
                {
                    var score = plan.Utilization * 10000 - length / 1000.0;
                    if (score > bestScore)
                    {
                        bestScore = score;
                        bestPlan = plan;
                    }
                }
            }

            if (bestPlan == null)
            {
                // 无法填充，使用最长的原材料
                var rawMat = lengthToMaterial[availableLengths.Last()];
                var activeSorted = active.OrderByDescending(p => p.Length).ToList();
                var (partNo, partLength, _) = activeSorted.First();

                var cutCount = 1;
                var usedLength = partLength;
                var totalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * cutCount;

                bestPlan = new CuttingPlan
                {
                    RawMaterial = rawMat,
                    Parts = new List<(string, int, int)> { (partNo, partLength, 1) },
                    CutCount = cutCount,
                    SingleCutLoss = lossRule.SingleCutLoss,
                    HeadTailLoss = lossRule.HeadTailLoss,
                    UsedLength = usedLength,
                    TotalLoss = totalLoss,
                    RemainingLength = rawMat.Length - usedLength - totalLoss,
                    Utilization = (double)usedLength / rawMat.Length
                };
            }

            // 更新剩余零件
            foreach (var (partNo, partLength, qty) in bestPlan.Parts)
            {
                for (int i = 0; i < remaining.Count; i++)
                {
                    if (remaining[i].PartNo == partNo && remaining[i].Length == partLength)
                    {
                        remaining[i] = (partNo, partLength, remaining[i].Quantity - qty);
                        break;
                    }
                }
            }

            newPlans.Add(bestPlan);
        }

        // 第二轮：尝试将新方案与高利用率方案中的剩余零件合并
        for (int newPlanIdx = 0; newPlanIdx < newPlans.Count; newPlanIdx++)
        {
            var newPlan = newPlans[newPlanIdx];
            if (newPlan.Utilization >= lowUtilThreshold)
                continue;

            var availableSpace = newPlan.RemainingLength - lossRule.SingleCutLoss;
            if (availableSpace <= 0)
                continue;

            // 查找可以从高利用率方案中"借出"的零件
            foreach (var kv in highUtilParts.ToList())
            {
                var (partNo, length) = kv.Key;
                var qty = kv.Value;

                if (qty <= 0)
                    continue;
                if (length > availableSpace)
                    continue;
                if (newPlan.Parts.Count >= _config.MaxPartsPerMaterial)
                {
                    if (!newPlan.Parts.Any(p => p.PartNo == partNo))
                        continue;
                }

                // 计算可以放多少
                var maxFit = Math.Min(qty, availableSpace / length);
                if (maxFit <= 0)
                    continue;

                var newCutCount = newPlan.CutCount + (newPlan.Parts.Any(p => p.PartNo == partNo) ? 0 : 1);
                var newTotalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * newCutCount;
                maxFit = Math.Min(maxFit, (newPlan.RawMaterial.Length - newPlan.UsedLength - newTotalLoss) / length);
                if (maxFit <= 0)
                    continue;

                var addedLength = length * maxFit;
                var newRemaining = newPlan.RawMaterial.Length - (newPlan.UsedLength + addedLength) - newTotalLoss;

                if (newRemaining >= 0)
                {
                    var updatedParts = newPlan.Parts.ToList();
                    var found = false;
                    for (int pi = 0; pi < updatedParts.Count; pi++)
                    {
                        if (updatedParts[pi].PartNo == partNo && updatedParts[pi].Length == length)
                        {
                            updatedParts[pi] = (partNo, length, updatedParts[pi].Quantity + maxFit);
                            found = true;
                            break;
                        }
                    }
                    if (!found)
                    {
                        updatedParts.Add((partNo, length, maxFit));
                        newCutCount = updatedParts.Count;
                    }

                    var newUsed = newPlan.UsedLength + addedLength;
                    newTotalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * updatedParts.Count;
                    newRemaining = newPlan.RawMaterial.Length - newUsed - newTotalLoss;
                    var newUtilization = (double)newUsed / newPlan.RawMaterial.Length;

                    newPlans[newPlanIdx] = new CuttingPlan
                    {
                        RawMaterial = newPlan.RawMaterial,
                        Parts = updatedParts,
                        CutCount = updatedParts.Count,
                        SingleCutLoss = lossRule.SingleCutLoss,
                        HeadTailLoss = lossRule.HeadTailLoss,
                        UsedLength = newUsed,
                        TotalLoss = newTotalLoss,
                        RemainingLength = newRemaining,
                        Utilization = newUtilization
                    };

                    highUtilParts[(partNo, length)] -= maxFit;
                    availableSpace = newRemaining - lossRule.SingleCutLoss;
                }
            }
        }

        // 构建最终结果
        var result = new List<CuttingPlan>();
        for (int i = 0; i < cuttingPlans.Count; i++)
        {
            if (!lowUtilIndices.Contains(i))
                result.Add(cuttingPlans[i]);
        }

        result.AddRange(newPlans);

        return result;
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
