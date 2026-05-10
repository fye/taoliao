using System;
using System.Collections.Generic;
using System.Linq;
using Taoliao.Core.Models;
using Taoliao.Core.Services;

namespace Taoliao.Core.Algorithms
{
    /// <summary>
    /// 贪心套料求解器 - 核心目标：最小化总材料长度
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
        /// 核心目标：在满足所有零件需求的前提下，最小化总材料长度
        /// 策略：尝试多种贪心策略，选择总材料长度最小的方案
        /// </summary>
        public List<CuttingPlan> Solve(
            List<Part> parts,
            List<RawMaterial> materials,
            string spec,
            string materialType)
        {
            var lossRule = _lossCalculator.GetLossRule(spec, materialType);

            // 获取可用原材料长度（升序）
            var availableLengths = materials.Select(m => m.Length).Distinct().OrderBy(l => l).ToList();
            var lengthToMaterial = materials.GroupBy(m => m.Length).ToDictionary(g => g.Key, g => g.First());

            // 零件列表
            var partList = parts.Select(p => new PartAllocation(p.PartNo, p.Length, p.Quantity)).ToList();

            // 尝试多种策略，选择总材料长度最小的方案
            List<CuttingPlan> bestPlans = null;
            long bestTotalLength = long.MaxValue;

            // 策略1：选择利用率最高的材料（核心策略）
            var plans1 = SolveBestUtilization(partList, availableLengths, lengthToMaterial, lossRule);
            if (plans1 != null && plans1.Count > 0)
            {
                long total1 = plans1.Sum(p => (long)p.RawMaterial.Length);
                if (total1 < bestTotalLength)
                {
                    bestTotalLength = total1;
                    bestPlans = plans1;
                }
            }

            // 策略2：固定使用最长材料
            var plans2 = SolveWithFixedLength(partList, availableLengths, lengthToMaterial, lossRule);
            if (plans2 != null && plans2.Count > 0)
            {
                long total2 = plans2.Sum(p => (long)p.RawMaterial.Length);
                if (total2 < bestTotalLength)
                {
                    bestTotalLength = total2;
                    bestPlans = plans2;
                }
            }

            // 策略3：优先使用短材料（某些场景更优）
            var plans3 = SolvePreferShort(partList, availableLengths, lengthToMaterial, lossRule);
            if (plans3 != null && plans3.Count > 0)
            {
                long total3 = plans3.Sum(p => (long)p.RawMaterial.Length);
                if (total3 < bestTotalLength)
                {
                    bestTotalLength = total3;
                    bestPlans = plans3;
                }
            }

            return bestPlans ?? new List<CuttingPlan>();
        }

        /// <summary>
        /// 策略：每次选择利用率最高的材料
        /// </summary>
        private List<CuttingPlan> SolveBestUtilization(
            List<PartAllocation> partList,
            List<int> availableLengths,
            Dictionary<int, RawMaterial> lengthToMaterial,
            LossRule lossRule)
        {
            var remainingParts = partList.Select(p => new PartAllocation(p.PartNo, p.Length, p.Quantity)).ToList();
            var cuttingPlans = new List<CuttingPlan>();

            // 按材料长度降序排列（优先尝试长材料）
            var sortedLengths = availableLengths.OrderByDescending(l => l).ToList();

            while (HasRemainingParts(remainingParts))
            {
                var activeParts = remainingParts.Where(p => p.Quantity > 0).ToList();
                if (activeParts.Count == 0) break;

                CuttingPlan bestPlan = null;
                double bestUtilization = -1;

                // 尝试所有材料，选择利用率最高的
                foreach (var length in sortedLengths)
                {
                    var rawMat = lengthToMaterial[length];
                    var plan = FillMaterial(rawMat, activeParts, lossRule);

                    if (plan == null) continue;

                    // 选择利用率最高的方案
                    if (plan.Utilization > bestUtilization)
                    {
                        bestUtilization = plan.Utilization;
                        bestPlan = plan;
                    }
                }

                if (bestPlan == null)
                {
                    // 没有材料能放下任何零件（溢出标记）
                    var activeSorted = activeParts.OrderByDescending(p => p.Length).ToList();
                    var part = activeSorted[0];

                    int maxAvailableLength = availableLengths.Max();
                    var rawMat = lengthToMaterial[maxAvailableLength];

                    int cutCount = 1;
                    int usedLength = part.Length;
                    int totalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * cutCount;
                    int remaining = rawMat.Length - usedLength - totalLoss;

                    bestPlan = new CuttingPlan
                    {
                        RawMaterial = rawMat,
                        Parts = new List<PartAllocation> { new PartAllocation(part.PartNo, part.Length, 1) },
                        CutCount = cutCount,
                        SingleCutLoss = lossRule.SingleCutLoss,
                        HeadTailLoss = lossRule.HeadTailLoss,
                        UsedLength = usedLength,
                        TotalLoss = totalLoss,
                        RemainingLength = remaining,
                        Utilization = rawMat.Length > 0 ? (double)usedLength / rawMat.Length : 0,
                        Overflow = remaining < 0
                    };
                }

                // 更新剩余零件
                UpdateRemainingParts(remainingParts, bestPlan.Parts);
                cuttingPlans.Add(bestPlan);
            }

            return cuttingPlans;
        }

        /// <summary>
        /// 策略：固定使用最长材料，直到无法填充
        /// </summary>
        private List<CuttingPlan> SolveWithFixedLength(
            List<PartAllocation> partList,
            List<int> availableLengths,
            Dictionary<int, RawMaterial> lengthToMaterial,
            LossRule lossRule)
        {
            int maxLength = availableLengths.Max();
            var maxMat = lengthToMaterial[maxLength];

            var remainingParts = partList.Select(p => new PartAllocation(p.PartNo, p.Length, p.Quantity)).ToList();
            var cuttingPlans = new List<CuttingPlan>();

            var sortedLengths = availableLengths.OrderByDescending(l => l).ToList();

            while (HasRemainingParts(remainingParts))
            {
                var activeParts = remainingParts.Where(p => p.Quantity > 0).ToList();
                if (activeParts.Count == 0) break;

                // 先尝试最长材料
                var plan = FillMaterial(maxMat, activeParts, lossRule);

                if (plan == null)
                {
                    // 最长材料放不下，尝试其他材料（按长度降序）
                    foreach (var length in sortedLengths)
                    {
                        if (length < maxLength)
                        {
                            var rawMat = lengthToMaterial[length];
                            plan = FillMaterial(rawMat, activeParts, lossRule);
                            if (plan != null) break;
                        }
                    }
                }

                if (plan == null)
                {
                    // 没有材料能放下任何零件（溢出标记）
                    var activeSorted = activeParts.OrderByDescending(p => p.Length).ToList();
                    var part = activeSorted[0];

                    int maxAvailableLength = availableLengths.Max();
                    var overflowMat = lengthToMaterial[maxAvailableLength];

                    int cutCount = 1;
                    int usedLength = part.Length;
                    int totalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * cutCount;
                    int remaining = overflowMat.Length - usedLength - totalLoss;

                    plan = new CuttingPlan
                    {
                        RawMaterial = overflowMat,
                        Parts = new List<PartAllocation> { new PartAllocation(part.PartNo, part.Length, 1) },
                        CutCount = cutCount,
                        SingleCutLoss = lossRule.SingleCutLoss,
                        HeadTailLoss = lossRule.HeadTailLoss,
                        UsedLength = usedLength,
                        TotalLoss = totalLoss,
                        RemainingLength = remaining,
                        Utilization = overflowMat.Length > 0 ? (double)usedLength / overflowMat.Length : 0,
                        Overflow = remaining < 0
                    };
                }

                // 更新剩余零件
                UpdateRemainingParts(remainingParts, plan.Parts);
                cuttingPlans.Add(plan);
            }

            return cuttingPlans;
        }

        /// <summary>
        /// 策略：优先使用短材料（在能放下的前提下）
        /// </summary>
        private List<CuttingPlan> SolvePreferShort(
            List<PartAllocation> partList,
            List<int> availableLengths,
            Dictionary<int, RawMaterial> lengthToMaterial,
            LossRule lossRule)
        {
            var remainingParts = partList.Select(p => new PartAllocation(p.PartNo, p.Length, p.Quantity)).ToList();
            var cuttingPlans = new List<CuttingPlan>();

            // 按材料长度升序排列
            var sortedLengths = availableLengths.OrderBy(l => l).ToList();

            while (HasRemainingParts(remainingParts))
            {
                var activeParts = remainingParts.Where(p => p.Quantity > 0).ToList();
                if (activeParts.Count == 0) break;

                CuttingPlan bestPlan = null;

                // 从短到长尝试，找到第一个能放下的
                foreach (var length in sortedLengths)
                {
                    var rawMat = lengthToMaterial[length];
                    var plan = FillMaterial(rawMat, activeParts, lossRule);

                    if (plan != null)
                    {
                        bestPlan = plan;
                        break;
                    }
                }

                if (bestPlan == null)
                {
                    // 没有材料能放下任何零件（溢出标记）
                    var activeSorted = activeParts.OrderByDescending(p => p.Length).ToList();
                    var part = activeSorted[0];

                    int maxAvailableLength = availableLengths.Max();
                    var rawMat = lengthToMaterial[maxAvailableLength];

                    int cutCount = 1;
                    int usedLength = part.Length;
                    int totalLoss = lossRule.HeadTailLoss + lossRule.SingleCutLoss * cutCount;
                    int remaining = rawMat.Length - usedLength - totalLoss;

                    bestPlan = new CuttingPlan
                    {
                        RawMaterial = rawMat,
                        Parts = new List<PartAllocation> { new PartAllocation(part.PartNo, part.Length, 1) },
                        CutCount = cutCount,
                        SingleCutLoss = lossRule.SingleCutLoss,
                        HeadTailLoss = lossRule.HeadTailLoss,
                        UsedLength = usedLength,
                        TotalLoss = totalLoss,
                        RemainingLength = remaining,
                        Utilization = rawMat.Length > 0 ? (double)usedLength / rawMat.Length : 0,
                        Overflow = remaining < 0
                    };
                }

                // 更新剩余零件
                UpdateRemainingParts(remainingParts, bestPlan.Parts);
                cuttingPlans.Add(bestPlan);
            }

            return cuttingPlans;
        }

        /// <summary>
        /// 贪心填充单根原材料
        /// </summary>
        private CuttingPlan FillMaterial(
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

            // 如果零件总长度+损耗超过原材料长度，方案无效
            if (remaining < 0)
                return null;

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