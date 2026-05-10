using System;
using System.Collections.Generic;
using Taoliao.Core;
using Taoliao.Core.Models;
using Taoliao.Core.Services;

namespace Taoliao.CLI
{
    class Program
    {
        static int Main(string[] args)
        {
            // 默认参数 (相对于taoliao_csharp目录)
            string demandFile = "../docs/需求清单.xlsx";
            string marketFile = "../docs/角钢市场清单.xlsx";
            string lossFile = "../docs/损耗规则.xlsx";
            string outputFile = "../output/套料结果.xlsx";
            int maxPartsPerMaterial = 3;
            int maxMaterialsPerPart = 5;
            int maxRemainder = 1000;
            int timeLimit = 120;

            // 解析命令行参数
            for (int i = 0; i < args.Length; i++)
            {
                switch (args[i])
                {
                    case "-d":
                    case "--demand":
                        if (i + 1 < args.Length) demandFile = args[++i];
                        break;
                    case "-m":
                    case "--market":
                        if (i + 1 < args.Length) marketFile = args[++i];
                        break;
                    case "-l":
                    case "--loss":
                        if (i + 1 < args.Length) lossFile = args[++i];
                        break;
                    case "-o":
                    case "--output":
                        if (i + 1 < args.Length) outputFile = args[++i];
                        break;
                    case "--max-parts":
                        if (i + 1 < args.Length) maxPartsPerMaterial = int.Parse(args[++i]);
                        break;
                    case "--max-materials":
                        if (i + 1 < args.Length) maxMaterialsPerPart = int.Parse(args[++i]);
                        break;
                    case "--max-remainder":
                        if (i + 1 < args.Length) maxRemainder = int.Parse(args[++i]);
                        break;
                    case "--time-limit":
                        if (i + 1 < args.Length) timeLimit = int.Parse(args[++i]);
                        break;
                    case "-h":
                    case "--help":
                        PrintHelp();
                        return 0;
                }
            }

            // 检查输入文件
            if (!System.IO.File.Exists(demandFile))
            {
                Console.WriteLine(string.Format("错误: 需求清单文件不存在: {0}", demandFile));
                return 1;
            }
            if (!System.IO.File.Exists(marketFile))
            {
                Console.WriteLine(string.Format("错误: 市场清单文件不存在: {0}", marketFile));
                return 1;
            }

            // 创建配置
            var config = new NestingConfig
            {
                MaxPartsPerMaterial = maxPartsPerMaterial,
                MaxMaterialsPerPart = maxMaterialsPerPart,
                MaxRemainder = maxRemainder,
                TimeLimit = timeLimit
            };

            Console.WriteLine("============================================================");
            Console.WriteLine("电力行业角钢套料优化系统 (C#版)");
            Console.WriteLine("============================================================");
            Console.WriteLine("\n配置参数:");
            Console.WriteLine(string.Format("  单根材料最多零件号: {0}", config.MaxPartsPerMaterial));
            Console.WriteLine(string.Format("  单零件号最多原材料: {0}", config.MaxMaterialsPerPart));
            Console.WriteLine(string.Format("  余料上限: {0}mm", config.MaxRemainder));
            Console.WriteLine(string.Format("  求解时间限制: {0}秒", config.TimeLimit));

            // 加载数据
            Console.WriteLine("\n加载数据...");
            var loader = new DataLoader();

            Console.WriteLine(string.Format("  需求清单: {0}", demandFile));
            var parts = loader.LoadParts(demandFile);
            Console.WriteLine(string.Format("  加载零件数: {0}", parts.Count));

            Console.WriteLine(string.Format("  市场清单: {0}", marketFile));
            var materials = loader.LoadMaterials(marketFile);
            Console.WriteLine(string.Format("  加载原材料数: {0}", materials.Count));

            // 加载损耗规则
            List<LossRule> lossRules = null;
            if (System.IO.File.Exists(lossFile))
            {
                Console.WriteLine(string.Format("  损耗规则: {0}", lossFile));
                lossRules = loader.LoadLossRules(lossFile);
                Console.WriteLine(string.Format("  加载损耗规则数: {0}", lossRules.Count));
            }

            // 执行优化
            Console.WriteLine("\n开始优化...");
            var optimizer = new NestingOptimizer(config, lossRules);
            var result = optimizer.Optimize(parts, materials);

            // 校验套料结果
            Console.WriteLine("\n校验套料结果...");
            var validationResult = ValidateResult(result, parts);
            if (validationResult.IsValid)
            {
                Console.WriteLine("  校验通过: 零部件数量一致");
            }
            else
            {
                Console.WriteLine(string.Format("  校验失败: {0}", validationResult.Message));
                foreach (var detail in validationResult.Details)
                {
                    Console.WriteLine(string.Format("    {0}", detail));
                }
            }

            // 检查溢出方案
            var overflowPlans = result.CuttingPlans.Where(p => p.Overflow).ToList();
            if (overflowPlans.Count > 0)
            {
                Console.WriteLine(string.Format("  注意: {0} 个零件超出原材料长度（溢出）", overflowPlans.Count));
                foreach (var p in overflowPlans)
                {
                    Console.WriteLine(string.Format("    {0} -> 原材料长度 {1}mm, 剩余 {2}mm",
                        p.PartsDescription, p.RawMaterial.Length, p.RemainingLength));
                }
            }

            // 导出结果
            Console.WriteLine(string.Format("\n导出结果: {0}", outputFile));
            var exporter = new ResultExporter(result);
            exporter.Export(outputFile, parts);
            exporter.PrintSummary();

            Console.WriteLine(string.Format("\n完成! 结果已保存到: {0}", outputFile));

            return 0;
        }

        static ValidationResult ValidateResult(NestingResult result, List<Part> originalParts)
        {
            // 统计原始需求中的零件数量
            var originalCounts = new Dictionary<string, int>();
            foreach (var part in originalParts)
            {
                var key = string.Format("{0}_{1}", part.PartNo, part.Length);
                if (!originalCounts.ContainsKey(key))
                    originalCounts[key] = 0;
                originalCounts[key] += part.Quantity;
            }

            // 统计套料结果中的零件数量
            var resultCounts = new Dictionary<string, int>();
            foreach (var plan in result.CuttingPlans)
            {
                foreach (var part in plan.Parts)
                {
                    var key = string.Format("{0}_{1}", part.PartNo, part.Length);
                    if (!resultCounts.ContainsKey(key))
                        resultCounts[key] = 0;
                    resultCounts[key] += part.Quantity;
                }
            }

            // 比较
            var details = new List<string>();
            var allKeys = new HashSet<string>(originalCounts.Keys);
            foreach (var key in resultCounts.Keys)
                allKeys.Add(key);

            foreach (var key in allKeys.OrderBy(k => k))
            {
                int origQty = originalCounts.ContainsKey(key) ? originalCounts[key] : 0;
                int resultQty = resultCounts.ContainsKey(key) ? resultCounts[key] : 0;

                if (origQty != resultQty)
                {
                    int diff = resultQty - origQty;
                    string sign = diff > 0 ? "+" : "";
                    var keyParts = key.Split('_');
                    details.Add(string.Format("部件号 {0} (长度{1}mm): 需求{2}个, 套料{3}个 ({4}{5})",
                        keyParts[0], keyParts[1], origQty, resultQty, sign, diff));
                }
            }

            if (details.Count > 0)
            {
                return new ValidationResult { IsValid = false, Message = "零部件数量不一致", Details = details };
            }

            return new ValidationResult { IsValid = true, Details = new List<string>() };
        }

        static void PrintHelp()
        {
            Console.WriteLine("电力行业角钢套料优化系统 (C#版)");
            Console.WriteLine();
            Console.WriteLine("用法: Taoliao.CLI [选项]");
            Console.WriteLine();
            Console.WriteLine("选项:");
            Console.WriteLine("  -d, --demand <文件>       需求清单文件路径 (默认: ../docs/需求清单.xlsx)");
            Console.WriteLine("  -m, --market <文件>       市场清单文件路径 (默认: ../docs/角钢市场清单.xlsx)");
            Console.WriteLine("  -l, --loss <文件>         损耗规则文件路径 (默认: ../docs/损耗规则.xlsx)");
            Console.WriteLine("  -o, --output <文件>       输出文件路径 (默认: ../output/套料结果.xlsx)");
            Console.WriteLine("  --max-parts <数量>        单根材料最多零件号数 (默认: 3)");
            Console.WriteLine("  --max-materials <数量>    单零件号最多原材料数 (默认: 5)");
            Console.WriteLine("  --max-remainder <毫米>    余料上限(mm) (默认: 1000)");
            Console.WriteLine("  --time-limit <秒>         求解时间限制(秒) (默认: 120)");
            Console.WriteLine("  -h, --help                显示帮助信息");
            Console.WriteLine();
            Console.WriteLine("示例:");
            Console.WriteLine("  Taoliao.CLI");
            Console.WriteLine("  Taoliao.CLI -d docs/需求清单.xlsx -o output/result.xlsx");
            Console.WriteLine("  Taoliao.CLI --max-parts 3 --time-limit 120");
        }
    }

    class ValidationResult
    {
        public bool IsValid { get; set; }
        public string Message { get; set; }
        public List<string> Details { get; set; }
    }
}