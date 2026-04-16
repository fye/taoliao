using Taoliao.Core;
using Taoliao.Core.Models;
using Taoliao.Core.Services;

namespace Taoliao.CLI;

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
        int maxMaterialsPerPart = 3;
        int maxRemainder = 1000;
        int timeLimit = 60;

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
        if (!File.Exists(demandFile))
        {
            Console.WriteLine($"错误: 需求清单文件不存在: {demandFile}");
            return 1;
        }
        if (!File.Exists(marketFile))
        {
            Console.WriteLine($"错误: 市场清单文件不存在: {marketFile}");
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
        Console.WriteLine($"\n配置参数:");
        Console.WriteLine($"  单根材料最多零件号: {config.MaxPartsPerMaterial}");
        Console.WriteLine($"  单零件号最多原材料: {config.MaxMaterialsPerPart}");
        Console.WriteLine($"  余料上限: {config.MaxRemainder}mm");
        Console.WriteLine($"  求解时间限制: {config.TimeLimit}秒");

        // 加载数据
        Console.WriteLine($"\n加载数据...");
        var loader = new DataLoader();

        Console.WriteLine($"  需求清单: {demandFile}");
        var parts = loader.LoadParts(demandFile);
        Console.WriteLine($"  加载零件数: {parts.Count}");

        Console.WriteLine($"  市场清单: {marketFile}");
        var materials = loader.LoadMaterials(marketFile);
        Console.WriteLine($"  加载原材料数: {materials.Count}");

        // 加载损耗规则
        List<Core.Models.LossRule>? lossRules = null;
        if (File.Exists(lossFile))
        {
            Console.WriteLine($"  损耗规则: {lossFile}");
            lossRules = loader.LoadLossRules(lossFile);
            Console.WriteLine($"  加载损耗规则数: {lossRules.Count}");
        }

        // 执行优化
        Console.WriteLine($"\n开始优化...");
        var optimizer = new NestingOptimizer(config, lossRules);
        var result = optimizer.Optimize(parts, materials);

        // 导出结果
        Console.WriteLine($"\n导出结果: {outputFile}");
        var exporter = new ResultExporter(result);
        exporter.Export(outputFile, parts);
        exporter.PrintSummary();

        Console.WriteLine($"\n完成! 结果已保存到: {outputFile}");

        return 0;
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
        Console.WriteLine("  --max-materials <数量>    单零件号最多原材料数 (默认: 3)");
        Console.WriteLine("  --max-remainder <毫米>    余料上限(mm) (默认: 1000)");
        Console.WriteLine("  --time-limit <秒>         求解时间限制(秒) (默认: 60)");
        Console.WriteLine("  -h, --help                显示帮助信息");
        Console.WriteLine();
        Console.WriteLine("示例:");
        Console.WriteLine("  Taoliao.CLI");
        Console.WriteLine("  Taoliao.CLI -d docs/需求清单.xlsx -o output/result.xlsx");
        Console.WriteLine("  Taoliao.CLI --max-parts 3 --time-limit 120");
    }
}
