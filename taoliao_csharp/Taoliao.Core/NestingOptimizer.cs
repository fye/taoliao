using Taoliao.Core.Algorithms;
using Taoliao.Core.Models;
using Taoliao.Core.Services;

namespace Taoliao.Core;

/// <summary>
/// 套料优化器
/// </summary>
public class NestingOptimizer
{
    private readonly NestingConfig _config;
    private readonly LossCalculator _lossCalculator;

    public NestingOptimizer(NestingConfig? config = null, List<LossRule>? lossRules = null)
    {
        _config = config ?? new NestingConfig();
        _lossCalculator = new LossCalculator(lossRules);
    }

    /// <summary>
    /// 执行套料优化
    /// </summary>
    public NestingResult Optimize(List<Part> parts, List<RawMaterial> materials)
    {
        // 按材质+规格分组
        var partGroups = parts
            .GroupBy(p => (p.Material, p.Spec))
            .ToDictionary(g => g.Key, g => g.ToList());

        var allCuttingPlans = new List<CuttingPlan>();
        var materialSummary = new Dictionary<(string, string), MaterialSummary>();

        // 对每个分组独立求解
        foreach (var ((materialType, spec), groupParts) in partGroups)
        {
            Console.WriteLine($"\n处理规格: {spec}, 材质: {materialType}, 零件数: {groupParts.Count}");

            // 筛选可用的原材料
            var availableMaterials = materials
                .Where(m => m.Spec == spec && m.MaterialType == materialType)
                .ToList();

            // 如果没有完全匹配材质的材料，尝试使用同规格的其他材质
            if (!availableMaterials.Any())
            {
                availableMaterials = materials.Where(m => m.Spec == spec).ToList();
                Console.WriteLine($"  警告: 材质 {materialType} 无匹配原材料，使用同规格其他材质");
            }

            if (!availableMaterials.Any())
            {
                Console.WriteLine($"  错误: 规格 {spec} 无可用原材料，跳过");
                continue;
            }

            // 求解该分组
            var cuttingPlans = SolveGroup(groupParts, availableMaterials, spec, materialType);

            // 汇总结果
            foreach (var plan in cuttingPlans)
            {
                allCuttingPlans.Add(plan);

                var key = (plan.RawMaterial.MaterialType, plan.RawMaterial.Spec);
                if (!materialSummary.ContainsKey(key))
                {
                    materialSummary[key] = new MaterialSummary();
                }

                materialSummary[key].Count++;
                materialSummary[key].TotalLength += plan.RawMaterial.Length;
                materialSummary[key].TotalUsed += plan.UsedLength;
                materialSummary[key].TotalLoss += plan.TotalLoss;
            }
        }

        // 计算汇总统计
        foreach (var summary in materialSummary.Values)
        {
            if (summary.TotalLength > 0)
            {
                summary.Utilization = (double)summary.TotalUsed / summary.TotalLength;
                summary.LossRatio = (double)summary.TotalLoss / summary.TotalLength;
            }
        }

        return new NestingResult
        {
            OriginalParts = parts,
            CuttingPlans = allCuttingPlans,
            MaterialSummary = materialSummary
        };
    }

    private List<CuttingPlan> SolveGroup(
        List<Part> parts,
        List<RawMaterial> materials,
        string spec,
        string materialType)
    {
        // 尝试MIP求解
        var mipOptimizer = new MipNestingOptimizer(_config, _lossCalculator);
        var cuttingPlans = mipOptimizer.Solve(parts, materials, spec, materialType);

        // 如果MIP求解失败，回退到贪心算法
        if (!cuttingPlans.Any())
        {
            Console.WriteLine($"  回退到贪心算法");
            var greedySolver = new GreedyNestingSolver(_config, _lossCalculator);
            cuttingPlans = greedySolver.Solve(parts, materials, spec, materialType);
        }

        return cuttingPlans;
    }
}
