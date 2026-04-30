using System;
using System.Collections.Generic;
using System.Linq;
using Taoliao.Core.Algorithms;
using Taoliao.Core.Models;
using Taoliao.Core.Services;

namespace Taoliao.Core
{
    /// <summary>
    /// 套料优化器
    /// </summary>
    public class NestingOptimizer
    {
        private readonly NestingConfig _config;
        private readonly LossCalculator _lossCalculator;

        public NestingOptimizer(NestingConfig config = null, List<LossRule> lossRules = null)
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
            var partGroups = new Dictionary<string, List<Part>>();
            foreach (var part in parts)
            {
                var key = string.Format("{0}_{1}", part.Material, part.Spec);
                if (!partGroups.ContainsKey(key))
                    partGroups[key] = new List<Part>();
                partGroups[key].Add(part);
            }

            var allCuttingPlans = new List<CuttingPlan>();
            var materialSummary = new Dictionary<string, MaterialSummary>();

            // 对每个分组独立求解
            foreach (var kv in partGroups)
            {
                var keyParts = kv.Key.Split('_');
                var materialType = keyParts[0];
                var spec = keyParts[1];
                var groupParts = kv.Value;

                Console.WriteLine(string.Format("\n处理规格: {0}, 材质: {1}, 零件数: {2}", spec, materialType, groupParts.Count));

                // 筛选可用的原材料
                var availableMaterials = materials
                    .Where(m => m.Spec == spec && m.MaterialType == materialType)
                    .ToList();

                // 如果没有完全匹配材质的材料，尝试使用同规格的其他材质
                if (availableMaterials.Count == 0)
                {
                    availableMaterials = materials.Where(m => m.Spec == spec).ToList();
                    Console.WriteLine(string.Format("  警告: 材质 {0} 无匹配原材料，使用同规格其他材质", materialType));
                }

                if (availableMaterials.Count == 0)
                {
                    Console.WriteLine(string.Format("  错误: 规格 {0} 无可用原材料，跳过", spec));
                    continue;
                }

                // 求解该分组
                var cuttingPlans = SolveGroup(groupParts, availableMaterials, spec, materialType);

                // 汇总结果
                foreach (var plan in cuttingPlans)
                {
                    allCuttingPlans.Add(plan);

                    var summaryKey = string.Format("{0}_{1}", plan.RawMaterial.MaterialType, plan.RawMaterial.Spec);
                    if (!materialSummary.ContainsKey(summaryKey))
                    {
                        materialSummary[summaryKey] = new MaterialSummary();
                    }

                    materialSummary[summaryKey].Count++;
                    materialSummary[summaryKey].TotalLength += plan.RawMaterial.Length;
                    materialSummary[summaryKey].TotalUsed += plan.UsedLength;
                    materialSummary[summaryKey].TotalLoss += plan.TotalLoss;

                    // 记录长度分布
                    var length = plan.RawMaterial.Length;
                    if (!materialSummary[summaryKey].LengthDistribution.ContainsKey(length))
                        materialSummary[summaryKey].LengthDistribution[length] = 0;
                    materialSummary[summaryKey].LengthDistribution[length]++;
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
            var lossRule = _lossCalculator.GetLossRule(spec, materialType);

            // 预处理：合并相同零件
            var mergedParts = MergeParts(parts);

            // 获取唯一长度
            var uniqueLengths = materials.Select(m => m.Length).Distinct().OrderBy(l => l).ToList();
            Console.WriteLine(string.Format("  可用原材料长度: [{0}]", string.Join(", ", uniqueLengths)));

            // 计算总零件数量
            int totalPartCount = mergedParts.Sum(p => p.Quantity);

            // 对于大规模问题（超过50个零件），直接使用贪心算法
            if (totalPartCount > 50)
            {
                Console.WriteLine(string.Format("  零件数量: {0}个，使用贪心算法", totalPartCount));
                var greedySolver = new GreedyNestingSolver(_config, _lossCalculator);
                var plans = greedySolver.Solve(parts, materials, spec, materialType);

                // 全局优化
                plans = GlobalMaterialOptimize(plans, materials, lossRule);

                return plans;
            }

            // 对于小规模问题，使用贪心算法（因为 MIP 不支持 .NET 4.5.2）
            Console.WriteLine(string.Format("  零件数量: {0}个，使用贪心算法", totalPartCount));
            var greedySolver2 = new GreedyNestingSolver(_config, _lossCalculator);
            var cuttingPlans = greedySolver2.Solve(parts, materials, spec, materialType);

            // 后处理优化
            cuttingPlans = PostOptimize(cuttingPlans, mergedParts, materials, lossRule);

            // 全局优化
            cuttingPlans = GlobalMaterialOptimize(cuttingPlans, materials, lossRule);

            return cuttingPlans;
        }

        private List<Part> MergeParts(List<Part> parts)
        {
            var merged = new Dictionary<string, Part>();

            foreach (var part in parts)
            {
                var key = string.Format("{0}_{1}", part.PartNo, part.Length);
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
            var lowUtilIndices = new HashSet<int>();
            for (int i = 0; i < cuttingPlans.Count; i++)
            {
                if (cuttingPlans[i].Utilization < lowUtilThreshold)
                    lowUtilIndices.Add(i);
            }

            if (lowUtilIndices.Count == 0)
                return cuttingPlans;

            Console.WriteLine(string.Format("  后处理优化: 发现 {0} 个低利用率方案（<{1:P0}），尝试重新优化...",
                lowUtilIndices.Count, lowUtilThreshold));

            // 第一步：尝试将低利用率方案的零件填充到高利用率方案的剩余空间
            var resultPlans = new List<CuttingPlan>(cuttingPlans);
            int filledCount = 0;

            foreach (int lowIdx in lowUtilIndices.OrderBy(x => x))
            {
                var lowPlan = resultPlans[lowIdx];
                if (lowPlan == null) continue;

                // 尝试将这个低利用率方案的零件填充到其他方案
                foreach (var part in lowPlan.Parts.ToList())
                {
                    int remainingQty = part.Quantity;

                    // 遍历所有高利用率方案，尝试填充
                    for (int highIdx = 0; highIdx < resultPlans.Count; highIdx++)
                    {
                        if (lowUtilIndices.Contains(highIdx) || highIdx == lowIdx)
                            continue;
                        if (remainingQty <= 0) break;

                        var highPlan = resultPlans[highIdx];
                        if (highPlan == null) continue;

                        // 检查是否可以添加这个零件
                        int availableSpace = highPlan.RemainingLength - lossRule.SingleCutLoss;
                        if (availableSpace < part.Length) continue;

                        // 检查零件号限制
                        var existingPartNos = new HashSet<string>(highPlan.Parts.Select(p => p.PartNo));
                        if (existingPartNos.Count >= _config.MaxPartsPerMaterial && !existingPartNos.Contains(part.PartNo))
                            continue;

                        // 计算可以放多少
                        int maxFit = Math.Min(remainingQty, availableSpace / part.Length);
                        if (maxFit <= 0) continue;

                        // 更新高利用率方案
                        var newParts = new List<PartAllocation>(highPlan.Parts);
                        bool found = false;
                        for (int pi = 0; pi < newParts.Count; pi++)
                        {
                            if (newParts[pi].PartNo == part.PartNo && newParts[pi].Length == part.Length)
                            {
                                newParts[pi] = new PartAllocation(part.PartNo, part.Length, newParts[pi].Quantity + maxFit);
                                found = true;
                                break;
                            }
                        }
                        if (!found)
                        {
                            newParts.Add(new PartAllocation(part.PartNo, part.Length, maxFit));
                        }

                        int newCutCount = newParts.Sum(p => p.Quantity);
                        int newUsed = highPlan.UsedLength + part.Length * maxFit;
                        int newTotalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * newCutCount;
                        int newRemaining = highPlan.RawMaterial.Length - newUsed - newTotalLoss;
                        double newUtilization = (double)newUsed / highPlan.RawMaterial.Length;

                        resultPlans[highIdx] = new CuttingPlan
                        {
                            RawMaterial = highPlan.RawMaterial,
                            Parts = newParts,
                            CutCount = newCutCount,
                            SingleCutLoss = lossRule.SingleCutLoss,
                            HeadTailLoss = lossRule.HeadTailLoss,
                            UsedLength = newUsed,
                            TotalLoss = newTotalLoss,
                            RemainingLength = newRemaining,
                            Utilization = newUtilization
                        };

                        remainingQty -= maxFit;
                        filledCount += maxFit;
                    }

                    // 更新低利用率方案中的零件数量
                    if (remainingQty < part.Quantity)
                    {
                        if (remainingQty > 0)
                        {
                            var newLowParts = lowPlan.Parts.Where(p => !(p.PartNo == part.PartNo && p.Length == part.Length)).ToList();
                            newLowParts.Add(new PartAllocation(part.PartNo, part.Length, remainingQty));

                            int newLowUsed = newLowParts.Sum(p => p.Length * p.Quantity);
                            int newLowCutCount = newLowParts.Sum(p => p.Quantity);
                            int newLowTotalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * newLowCutCount;
                            int newLowRemaining = lowPlan.RawMaterial.Length - newLowUsed - newLowTotalLoss;
                            double newLowUtil = lowPlan.RawMaterial.Length > 0 ? (double)newLowUsed / lowPlan.RawMaterial.Length : 0;

                            resultPlans[lowIdx] = new CuttingPlan
                            {
                                RawMaterial = lowPlan.RawMaterial,
                                Parts = newLowParts,
                                CutCount = newLowCutCount,
                                SingleCutLoss = lossRule.SingleCutLoss,
                                HeadTailLoss = lossRule.HeadTailLoss,
                                UsedLength = newLowUsed,
                                TotalLoss = newLowTotalLoss,
                                RemainingLength = newLowRemaining,
                                Utilization = newLowUtil
                            };
                        }
                        else
                        {
                            // 完全填充，标记为删除
                            resultPlans[lowIdx] = null;
                        }
                    }
                }
            }

            // 移除被完全填充的方案
            var finalPlans = resultPlans.Where(p => p != null).ToList();

            if (filledCount > 0)
            {
                Console.WriteLine(string.Format("    第一步: 成功将 {0} 个零件填充到高利用率方案", filledCount));
            }

            // 检查是否还有低利用率方案
            var stillLowUtil = finalPlans.Where(p => p.Utilization < lowUtilThreshold).ToList();
            if (stillLowUtil.Count == 0)
            {
                Console.WriteLine("    优化完成: 所有低利用率方案已消除");
                return finalPlans;
            }

            return finalPlans;
        }

        /// <summary>
        /// 全局材料优化：穷举所有可能的材料长度分配方案，选择总长度最小的
        /// </summary>
        private List<CuttingPlan> GlobalMaterialOptimize(
            List<CuttingPlan> cuttingPlans,
            List<RawMaterial> materials,
            LossRule lossRule)
        {
            if (cuttingPlans.Count <= 1)
                return cuttingPlans;

            // 当前方案统计
            int currentPieceCount = cuttingPlans.Count;
            long currentTotalLength = cuttingPlans.Sum(p => (long)p.RawMaterial.Length);

            // 收集所有零件
            var allParts = new Dictionary<string, int>();
            foreach (var plan in cuttingPlans)
            {
                foreach (var part in plan.Parts)
                {
                    var key = string.Format("{0}_{1}", part.PartNo, part.Length);
                    if (!allParts.ContainsKey(key))
                        allParts[key] = 0;
                    allParts[key] += part.Quantity;
                }
            }

            if (allParts.Count == 0)
                return cuttingPlans;

            // 获取可用材料长度（升序）
            var availableLengths = materials.Select(m => m.Length).Distinct().OrderBy(l => l).ToList();
            var lengthToMaterial = materials.GroupBy(m => m.Length).ToDictionary(g => g.Key, g => g.First());

            if (availableLengths.Count <= 1)
                return cuttingPlans;

            var partList = allParts.Select(kv =>
            {
                var parts = kv.Key.Split('_');
                return new PartAllocation(parts[0], int.Parse(parts[1]), kv.Value);
            }).ToList();

            var bestPlans = cuttingPlans;
            long bestTotalLength = currentTotalLength;

            // 策略：贪心评分策略
            foreach (double alpha in new[] { 1.0, 5.0 })
            {
                var newPlans = TryScoredStrategy(partList, availableLengths, lengthToMaterial, lossRule, alpha);
                if (newPlans != null && newPlans.Count > 0)
                {
                    long newTotal = newPlans.Sum(p => (long)p.RawMaterial.Length);
                    if (newTotal < bestTotalLength)
                    {
                        bestTotalLength = newTotal;
                        bestPlans = newPlans;
                    }
                }
            }

            if (bestTotalLength < currentTotalLength)
            {
                long saved = currentTotalLength - bestTotalLength;
                Console.WriteLine(string.Format("  全局优化: 材料总长度从 {0:F1}m 优化到 {1:F1}m，节省 {2:F1}m",
                    currentTotalLength / 1000.0, bestTotalLength / 1000.0, saved / 1000.0));
            }

            return bestPlans;
        }

        /// <summary>
        /// 基于评分的策略：综合考虑利用率和材料长度
        /// </summary>
        private List<CuttingPlan> TryScoredStrategy(
            List<PartAllocation> partList,
            List<int> availableLengths,
            Dictionary<int, RawMaterial> lengthToMaterial,
            LossRule lossRule,
            double alpha)
        {
            var remaining = partList.Select(p => new PartAllocation(p.PartNo, p.Length, p.Quantity)).ToList();
            var newPlans = new List<CuttingPlan>();

            while (HasRemainingParts(remaining))
            {
                var active = remaining.Where(p => p.Quantity > 0).ToList();
                if (active.Count == 0) break;

                CuttingPlan bestPlan = null;
                double bestScore = double.NegativeInfinity;

                foreach (var length in availableLengths)
                {
                    var rawMat = lengthToMaterial[length];
                    var plan = GreedyFill(rawMat, active, lossRule);
                    if (plan == null) continue;

                    double score = plan.Utilization * 100 - alpha * length / 1000.0;
                    if (score > bestScore)
                    {
                        bestScore = score;
                        bestPlan = plan;
                    }
                }

                if (bestPlan == null)
                    return null;

                UpdateRemainingParts(remaining, bestPlan.Parts);
                newPlans.Add(bestPlan);
            }

            if (HasRemainingParts(remaining))
                return null;

            return newPlans;
        }

        /// <summary>
        /// 贪心填充单根原材料
        /// </summary>
        private CuttingPlan GreedyFill(
            RawMaterial rawMaterial,
            List<PartAllocation> parts,
            LossRule lossRule)
        {
            int availableLength = rawMaterial.Length - lossRule.HeadTailLoss;

            // 按长度降序排列零件
            var sortedParts = parts.OrderByDescending(p => p.Length).ToList();

            var selectedParts = new List<PartAllocation>();
            var partNoSet = new HashSet<string>();

            foreach (var part in sortedParts)
            {
                if (part.Quantity <= 0) continue;

                // 检查零件号限制
                if (partNoSet.Count >= _config.MaxPartsPerMaterial && !partNoSet.Contains(part.PartNo))
                    continue;

                // 计算当前已选零件的总长度和总数量
                int currentLength = 0;
                int currentCutCount = 0;
                foreach (var p in selectedParts)
                {
                    currentLength += p.Length * p.Quantity;
                    currentCutCount += p.Quantity;
                }

                // 每个零件都会增加 single_cut_loss 的损耗
                int maxSpace = availableLength - currentLength - lossRule.SingleCutLoss * currentCutCount;
                int maxQty = Math.Min(part.Quantity, maxSpace / (part.Length + lossRule.SingleCutLoss));

                if (maxQty > 0)
                {
                    selectedParts.Add(new PartAllocation(part.PartNo, part.Length, maxQty));
                    partNoSet.Add(part.PartNo);
                }
            }

            if (selectedParts.Count == 0)
                return null;

            // 切割刀数 = 所有零件数量之和
            int cutCount = selectedParts.Sum(p => p.Quantity);
            int usedLength = selectedParts.Sum(p => p.Length * p.Quantity);
            int totalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * cutCount;
            int remaining = rawMaterial.Length - usedLength - totalLoss;

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

        private bool HasRemainingParts(List<PartAllocation> parts)
        {
            return parts.Any(p => p.Quantity > 0);
        }

        private void UpdateRemainingParts(List<PartAllocation> remaining, List<PartAllocation> used)
        {
            foreach (var usedPart in used)
            {
                for (int i = 0; i < remaining.Count; i++)
                {
                    if (remaining[i].PartNo == usedPart.PartNo && remaining[i].Length == usedPart.Length)
                    {
                        remaining[i] = new PartAllocation(
                            remaining[i].PartNo,
                            remaining[i].Length,
                            remaining[i].Quantity - usedPart.Quantity);
                        break;
                    }
                }
            }
        }
    }
}