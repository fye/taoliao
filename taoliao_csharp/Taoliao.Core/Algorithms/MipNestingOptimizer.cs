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
        return ExtractSolution(solver, x, y, z, uniqueLengths, maxMaterialsNeeded, mergedParts, materials, lossRule);
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
