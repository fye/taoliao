using Google.OrTools.LinearSolver;
using Taoliao.Core.Models;
using Taoliao.Core.Services;

namespace Taoliao.Core.Algorithms;

/// <summary>
/// MIP套料优化器
/// </summary>
public class MipNestingOptimizer
{
    private readonly NestingConfig _config;
    private readonly LossCalculator _lossCalculator;

    public MipNestingOptimizer(NestingConfig config, LossCalculator lossCalculator)
    {
        _config = config;
        _lossCalculator = lossCalculator;
    }

    /// <summary>
    /// 求解器统计信息
    /// </summary>
    public SolverStats? Stats { get; private set; }

    /// <summary>
    /// 求解单个分组的套料问题
    /// </summary>
    public List<CuttingPlan> Solve(
        List<Part> parts,
        List<RawMaterial> materials,
        string spec,
        string materialType)
    {
        var lossRule = _lossCalculator.GetLossRule(spec, materialType);

        // 合并相同零件
        var mergedParts = MergeParts(parts);

        // 获取唯一长度
        var uniqueLengths = materials.Select(m => m.Length).Distinct().OrderBy(l => l).ToList();

        Console.WriteLine($"  可用原材料长度: [{string.Join(", ", uniqueLengths)}]");

        // 创建求解器
        var solver = Solver.CreateSolver("CBC");
        if (solver == null)
        {
            Console.WriteLine("  无法创建CBC求解器");
            return new List<CuttingPlan>();
        }

        solver.SetTimeLimit(_config.TimeLimit * 1000);

        // 估计需要的原材料数量上界
        int maxMaterialsNeeded = EstimateMaxMaterials(mergedParts, materials, lossRule);

        // 创建变量
        var x = new Dictionary<(int, int, int), Variable>();  // (length, i, j) -> 切割数量
        var y = new Dictionary<(int, int), Variable>();       // (length, i) -> 是否使用
        var z = new Dictionary<(int, int, int), Variable>();  // (length, i, j) -> 是否切割
        var r = new Dictionary<(int, int), Variable>();       // (length, i) -> 余料

        foreach (var length in uniqueLengths)
        {
            for (int i = 0; i < maxMaterialsNeeded; i++)
            {
                y[(length, i)] = solver.MakeIntVar(0, 1, $"y_{length}_{i}");
                r[(length, i)] = solver.MakeNumVar(0, length, $"r_{length}_{i}");

                for (int j = 0; j < mergedParts.Count; j++)
                {
                    x[(length, i, j)] = solver.MakeIntVar(0, mergedParts[j].Quantity, $"x_{length}_{i}_{j}");
                    z[(length, i, j)] = solver.MakeIntVar(0, 1, $"z_{length}_{i}_{j}");
                }
            }
        }

        // 约束1: 需求满足
        for (int j = 0; j < mergedParts.Count; j++)
        {
            var ct = solver.MakeConstraint(mergedParts[j].Quantity, mergedParts[j].Quantity, $"demand_{j}");
            foreach (var length in uniqueLengths)
            {
                for (int i = 0; i < maxMaterialsNeeded; i++)
                {
                    ct.SetCoefficient(x[(length, i, j)], 1);
                }
            }
        }

        // 约束2: 容量约束
        foreach (var length in uniqueLengths)
        {
            for (int i = 0; i < maxMaterialsNeeded; i++)
            {
                var ct = solver.MakeConstraint(double.NegativeInfinity, length, $"capacity_{length}_{i}");

                foreach (var part in mergedParts)
                {
                    int j = mergedParts.IndexOf(part);
                    ct.SetCoefficient(x[(length, i, j)], part.Length);
                }

                for (int j = 0; j < mergedParts.Count; j++)
                {
                    ct.SetCoefficient(z[(length, i, j)], lossRule.SingleCutLoss);
                }

                ct.SetCoefficient(y[(length, i)], -length + lossRule.HeadTailLoss);
            }
        }

        // 约束3: 零件号约束（材料侧）
        foreach (var length in uniqueLengths)
        {
            for (int i = 0; i < maxMaterialsNeeded; i++)
            {
                var ct = solver.MakeConstraint(0, _config.MaxPartsPerMaterial, $"parts_per_mat_{length}_{i}");
                for (int j = 0; j < mergedParts.Count; j++)
                {
                    ct.SetCoefficient(z[(length, i, j)], 1);
                }
            }
        }

        // 约束4: 零件号约束（零件侧）
        for (int j = 0; j < mergedParts.Count; j++)
        {
            var ct = solver.MakeConstraint(0, _config.MaxMaterialsPerPart, $"mats_per_part_{j}");
            foreach (var length in uniqueLengths)
            {
                for (int i = 0; i < maxMaterialsNeeded; i++)
                {
                    ct.SetCoefficient(z[(length, i, j)], 1);
                }
            }
        }

        // 约束5: 关联约束
        foreach (var length in uniqueLengths)
        {
            for (int i = 0; i < maxMaterialsNeeded; i++)
            {
                for (int j = 0; j < mergedParts.Count; j++)
                {
                    // x > 0 => z = 1
                    var ct1 = solver.MakeConstraint(double.NegativeInfinity, 0, $"link1_{length}_{i}_{j}");
                    ct1.SetCoefficient(x[(length, i, j)], 1);
                    ct1.SetCoefficient(z[(length, i, j)], -mergedParts[j].Quantity);

                    // z = 1 => y = 1
                    var ct2 = solver.MakeConstraint(double.NegativeInfinity, 0, $"link2_{length}_{i}_{j}");
                    ct2.SetCoefficient(z[(length, i, j)], 1);
                    ct2.SetCoefficient(y[(length, i)], -1);
                }
            }
        }

        // 余料定义约束
        foreach (var length in uniqueLengths)
        {
            for (int i = 0; i < maxMaterialsNeeded; i++)
            {
                var ct = solver.MakeConstraint(0, 0, $"remainder_eq_{length}_{i}");
                ct.SetCoefficient(r[(length, i)], 1);
                ct.SetCoefficient(y[(length, i)], -length + lossRule.HeadTailLoss);

                for (int j = 0; j < mergedParts.Count; j++)
                {
                    ct.SetCoefficient(x[(length, i, j)], mergedParts[j].Length);
                }

                for (int j = 0; j < mergedParts.Count; j++)
                {
                    ct.SetCoefficient(z[(length, i, j)], lossRule.SingleCutLoss);
                }
            }
        }

        // 对称性破除
        foreach (var length in uniqueLengths)
        {
            for (int i = 0; i < maxMaterialsNeeded - 1; i++)
            {
                var ct = solver.MakeConstraint(double.NegativeInfinity, 0, $"symmetry_{length}_{i}");
                ct.SetCoefficient(y[(length, i)], 1);
                ct.SetCoefficient(y[(length, i + 1)], -1);
            }
        }

        // 目标函数
        var objective = solver.Objective();
        const double penaltyWeight = 0.1;

        foreach (var length in uniqueLengths)
        {
            for (int i = 0; i < maxMaterialsNeeded; i++)
            {
                objective.SetCoefficient(y[(length, i)], length);
                objective.SetCoefficient(r[(length, i)], penaltyWeight);
            }
        }
        objective.SetMinimization();

        // 求解
        Console.WriteLine($"  开始求解 (变量数: {solver.NumVariables()}, 约束数: {solver.NumConstraints()})");
        var status = solver.Solve();

        // 记录统计信息
        Stats = new SolverStats
        {
            Status = StatusToString(status),
            ObjectiveValue = status == Solver.ResultStatus.Optimal || status == Solver.ResultStatus.Feasible
                ? objective.Value()
                : 0,
            SolveTime = solver.WallTime() / 1000,
            NumVariables = solver.NumVariables(),
            NumConstraints = solver.NumConstraints()
        };

        if (status == Solver.ResultStatus.Optimal)
        {
            Console.WriteLine($"  找到最优解! 目标值: {objective.Value():F0}mm, 耗时: {solver.WallTime() / 1000:F2}s");
        }
        else if (status == Solver.ResultStatus.Feasible)
        {
            Console.WriteLine($"  找到可行解 (可能非最优). 目标值: {objective.Value():F0}mm, 耗时: {solver.WallTime() / 1000:F2}s");
        }
        else
        {
            Console.WriteLine($"  MIP求解失败: {StatusToString(status)}");
            return new List<CuttingPlan>();
        }

        // 提取解
        var cuttingPlans = ExtractSolution(solver, x, y, z, uniqueLengths, maxMaterialsNeeded, mergedParts, materials, lossRule);

        // 后处理：尝试优化低利用率的方案
        cuttingPlans = PostOptimize(cuttingPlans, mergedParts, materials, lossRule);

        return cuttingPlans;
    }

    private List<Part> MergeParts(List<Part> parts)
    {
        var merged = new Dictionary<(string, int), Part>();

        foreach (var part in parts)
        {
            var key = (part.PartNo, part.Length);
            if (!merged.ContainsKey(key))
            {
                merged[key] = new Part
                {
                    PartNo = part.PartNo,
                    Material = part.Material,
                    Spec = part.Spec,
                    Length = part.Length,
                    Quantity = 0
                };
            }
            merged[key].Quantity += part.Quantity;
        }

        return merged.Values.ToList();
    }

    private int EstimateMaxMaterials(List<Part> parts, List<RawMaterial> materials, LossRule lossRule)
    {
        var totalPartLength = parts.Sum(p => p.Length * p.Quantity);
        var minMaterialLength = materials.Min(m => m.Length);
        var estimated = totalPartLength / (minMaterialLength * 0.8);
        return Math.Max((int)(estimated * 1.5), Math.Max(parts.Count * 2, 10));
    }

    private List<CuttingPlan> ExtractSolution(
        Solver solver,
        Dictionary<(int, int, int), Variable> x,
        Dictionary<(int, int), Variable> y,
        Dictionary<(int, int, int), Variable> z,
        List<int> uniqueLengths,
        int maxMaterials,
        List<Part> parts,
        List<RawMaterial> materials,
        LossRule lossRule)
    {
        var cuttingPlans = new List<CuttingPlan>();
        var lengthToMaterial = materials.GroupBy(m => m.Length).ToDictionary(g => g.Key, g => g.First());

        foreach (var length in uniqueLengths)
        {
            if (!lengthToMaterial.TryGetValue(length, out var rawMat))
                continue;

            for (int i = 0; i < maxMaterials; i++)
            {
                if (y[(length, i)].SolutionValue() > 0.5)
                {
                    var partsOnMaterial = new List<(string, int, int)>();

                    for (int j = 0; j < parts.Count; j++)
                    {
                        var qty = (int)Math.Round(x[(length, i, j)].SolutionValue());
                        if (qty > 0)
                        {
                            partsOnMaterial.Add((parts[j].PartNo, parts[j].Length, qty));
                        }
                    }

                    if (partsOnMaterial.Count > 0)
                    {
                        var cutCount = partsOnMaterial.Count;
                        var usedLength = partsOnMaterial.Sum(p => p.Length * p.Quantity);
                        var totalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * cutCount;
                        var remaining = length - usedLength - totalLoss;

                        cuttingPlans.Add(new CuttingPlan
                        {
                            RawMaterial = rawMat,
                            Parts = partsOnMaterial,
                            CutCount = cutCount,
                            SingleCutLoss = lossRule.SingleCutLoss,
                            HeadTailLoss = lossRule.HeadTailLoss,
                            UsedLength = usedLength,
                            TotalLoss = totalLoss,
                            RemainingLength = remaining,
                            Utilization = (double)usedLength / length
                        });
                    }
                }
            }
        }

        return cuttingPlans;
    }

    /// <summary>
    /// 后处理优化：重新优化低利用率的切割方案
    /// </summary>
    private List<CuttingPlan> PostOptimize(
        List<CuttingPlan> cuttingPlans,
        List<Part> parts,
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

        Console.WriteLine($"  后处理优化: 发现 {lowUtilIndices.Count} 个低利用率方案（<{lowUtilThreshold:P0}），尝试重新优化...");

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

                var plan = GreedyFill(rawMat, active, lossRule);
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

        // 统计改善
        var oldTotal = lowUtilIndices.Sum(i => cuttingPlans[i].RawMaterial.Length);
        var newTotal = newPlans.Sum(p => p.RawMaterial.Length);
        var saved = oldTotal - newTotal;

        if (saved > 0)
        {
            Console.WriteLine($"    重新优化完成: 低利用率方案从 {lowUtilIndices.Count} 个减少到 {newPlans.Count} 个，节省 {saved}mm 材料");
        }
        else
        {
            Console.WriteLine($"    重新优化完成: 方案数从 {lowUtilIndices.Count} 个变为 {newPlans.Count} 个");
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

    /// <summary>
    /// 贪心填充单根原材料
    /// </summary>
    private CuttingPlan? GreedyFill(
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

    private static string StatusToString(Solver.ResultStatus status)
    {
        return status switch
        {
            Solver.ResultStatus.Optimal => "OPTIMAL",
            Solver.ResultStatus.Feasible => "FEASIBLE",
            Solver.ResultStatus.Infeasible => "INFEASIBLE",
            Solver.ResultStatus.Unbounded => "UNBOUNDED",
            Solver.ResultStatus.Abnormal => "ABNORMAL",
            Solver.ResultStatus.NotSolved => "NOT_SOLVED",
            _ => $"UNKNOWN({status})"
        };
    }
}

/// <summary>
/// 求解器统计信息
/// </summary>
public class SolverStats
{
    public string Status { get; set; } = "";
    public double ObjectiveValue { get; set; }
    public double SolveTime { get; set; }
    public int NumVariables { get; set; }
    public int NumConstraints { get; set; }
}
