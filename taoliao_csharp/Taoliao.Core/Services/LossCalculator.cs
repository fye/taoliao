using Taoliao.Core.Models;

namespace Taoliao.Core.Services;

/// <summary>
/// 损耗计算器
/// </summary>
public class LossCalculator
{
    private readonly List<LossRule> _lossRules;

    public LossCalculator(List<LossRule>? lossRules = null)
    {
        _lossRules = lossRules ?? DataLoader.GetDefaultLossRules();
    }

    /// <summary>
    /// 获取适用于给定规格和材质的损耗规则
    /// </summary>
    public LossRule GetLossRule(string spec, string material)
    {
        foreach (var rule in _lossRules)
        {
            if (rule.Matches(spec, material))
                return rule;
        }

        // 如果没有匹配的规则，返回第一个规则作为默认
        return _lossRules.Count > 0 ? _lossRules[0] : new LossRule
        {
            LimbWidthRange = (0, 999),
            ThicknessRange = (0, 999),
            Materials = new List<string>(),
            SingleCutLoss = 10,
            HeadTailLoss = 30
        };
    }

    /// <summary>
    /// 计算总损耗
    /// </summary>
    public int CalculateLoss(string spec, string material, int cutCount)
    {
        var rule = GetLossRule(spec, material);
        return rule.HeadTailLoss + rule.SingleCutLoss * cutCount;
    }

    /// <summary>
    /// 计算剩余长度
    /// </summary>
    public int CalculateRemaining(int materialLength, int partsLength, string spec, string material, int cutCount)
    {
        var loss = CalculateLoss(spec, material, cutCount);
        return materialLength - partsLength - loss;
    }

    /// <summary>
    /// 计算利用率
    /// </summary>
    public double CalculateUtilization(int materialLength, int partsLength)
    {
        return materialLength > 0 ? (double)partsLength / materialLength : 0;
    }
}
