using NPOI.SS.UserModel;
using NPOI.XSSF.UserModel;
using Taoliao.Core.Models;

namespace Taoliao.Core.Services;

/// <summary>
/// 结果导出器
/// </summary>
public class ResultExporter
{
    private readonly NestingResult _result;

    public ResultExporter(NestingResult result)
    {
        _result = result;
    }

    /// <summary>
    /// 导出结果到Excel文件
    /// </summary>
    public void Export(string outputPath, List<Part>? originalParts = null)
    {
        // 确保输出目录存在
        var dir = Path.GetDirectoryName(outputPath);
        if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
        {
            Directory.CreateDirectory(dir);
        }

        using var fs = new FileStream(outputPath, FileMode.Create, FileAccess.Write);
        var workbook = new XSSFWorkbook();

        // Sheet 1: 原始需求清单
        WriteOriginalParts(workbook, originalParts);

        // Sheet 2: 套料结果
        WriteCuttingPlans(workbook);

        // Sheet 3: 原材料汇总
        WriteMaterialSummary(workbook);

        workbook.Write(fs);
    }

    private void WriteOriginalParts(XSSFWorkbook workbook, List<Part>? originalParts)
    {
        var sheet = workbook.CreateSheet("原始需求清单");
        var headerRow = sheet.CreateRow(0);

        var headers = new[] { "段号(只读)", "部件号", "材质", "规格", "长度(mm)", "宽度(mm)",
            "单基数量(件)", "单件重量(kg)", "单件孔数", "备注" };

        for (int i = 0; i < headers.Length; i++)
        {
            headerRow.CreateCell(i).SetCellValue(headers[i]);
        }

        var parts = originalParts ?? _result.OriginalParts;
        for (int i = 0; i < parts.Count; i++)
        {
            var row = sheet.CreateRow(i + 1);
            var part = parts[i];

            row.CreateCell(0).SetCellValue(part.SegmentNo ?? "");
            row.CreateCell(1).SetCellValue(part.PartNo);
            row.CreateCell(2).SetCellValue(part.Material);
            row.CreateCell(3).SetCellValue(part.Spec);
            row.CreateCell(4).SetCellValue(part.Length);
            row.CreateCell(5).SetCellValue(part.Width?.ToString() ?? "");
            row.CreateCell(6).SetCellValue(part.Quantity);
            row.CreateCell(7).SetCellValue(part.Weight?.ToString() ?? "");
            row.CreateCell(8).SetCellValue(part.Holes?.ToString() ?? "");
            row.CreateCell(9).SetCellValue(part.Remark ?? "");
        }
    }

    private void WriteCuttingPlans(XSSFWorkbook workbook)
    {
        var sheet = workbook.CreateSheet("套料结果");
        var headerRow = sheet.CreateRow(0);

        var headers = new[] { "序号", "原材料材质", "规格", "原材料长度", "切割的部件号",
            "切割刀数", "单刀损", "两头损耗", "使用长度", "剩余长度", "利用率", "损耗比", "备注" };

        for (int i = 0; i < headers.Length; i++)
        {
            headerRow.CreateCell(i).SetCellValue(headers[i]);
        }

        for (int i = 0; i < _result.CuttingPlans.Count; i++)
        {
            var row = sheet.CreateRow(i + 1);
            var plan = _result.CuttingPlans[i];

            row.CreateCell(0).SetCellValue(i + 1);
            row.CreateCell(1).SetCellValue(plan.RawMaterial.MaterialType);
            row.CreateCell(2).SetCellValue(plan.RawMaterial.Spec);
            row.CreateCell(3).SetCellValue(plan.RawMaterial.Length);
            row.CreateCell(4).SetCellValue(plan.PartsDescription);
            row.CreateCell(5).SetCellValue(plan.CutCount);
            row.CreateCell(6).SetCellValue(plan.SingleCutLoss);
            row.CreateCell(7).SetCellValue(plan.HeadTailLoss);
            row.CreateCell(8).SetCellValue(plan.UsedLength);
            row.CreateCell(9).SetCellValue(plan.RemainingLength);
            row.CreateCell(10).SetCellValue($"{plan.Utilization * 100:F2}%");
            row.CreateCell(11).SetCellValue($"{plan.LossRatio * 100:F2}%");
            row.CreateCell(12).SetCellValue("");
        }
    }

    private void WriteMaterialSummary(XSSFWorkbook workbook)
    {
        var sheet = workbook.CreateSheet("原材料汇总");
        var headerRow = sheet.CreateRow(0);

        var headers = new[] { "材质", "规格", "母材数量", "总长度", "使用长度",
            "损耗长度", "利用率", "损耗比" };

        for (int i = 0; i < headers.Length; i++)
        {
            headerRow.CreateCell(i).SetCellValue(headers[i]);
        }

        int rowIndex = 1;
        foreach (var (key, summary) in _result.MaterialSummary.OrderBy(x => x.Key.Material).ThenBy(x => x.Key.Spec))
        {
            var row = sheet.CreateRow(rowIndex++);

            row.CreateCell(0).SetCellValue(key.Material);
            row.CreateCell(1).SetCellValue(key.Spec);
            row.CreateCell(2).SetCellValue(summary.Count);
            row.CreateCell(3).SetCellValue(summary.TotalLength);
            row.CreateCell(4).SetCellValue(summary.TotalUsed);
            row.CreateCell(5).SetCellValue(summary.TotalLoss);
            row.CreateCell(6).SetCellValue($"{summary.Utilization * 100:F2}%");
            row.CreateCell(7).SetCellValue($"{summary.LossRatio * 100:F2}%");
        }
    }

    /// <summary>
    /// 打印结果摘要
    /// </summary>
    public void PrintSummary()
    {
        Console.WriteLine();
        Console.WriteLine("============================================================");
        Console.WriteLine("套料结果摘要");
        Console.WriteLine("============================================================");

        Console.WriteLine($"\n总切割方案数: {_result.CuttingPlans.Count}");
        Console.WriteLine($"总利用率: {_result.TotalUtilization * 100:F2}%");
        Console.WriteLine($"总损耗比: {_result.TotalLossRatio * 100:F2}%");

        Console.WriteLine("\n原材料使用情况:");
        Console.WriteLine("------------------------------------------------------------");

        foreach (var (key, summary) in _result.MaterialSummary.OrderBy(x => x.Key.Material).ThenBy(x => x.Key.Spec))
        {
            Console.WriteLine($"  {key.Material} {key.Spec}:");
            Console.WriteLine($"    数量: {summary.Count} 根");
            Console.WriteLine($"    利用率: {summary.Utilization * 100:F2}%");
            Console.WriteLine($"    损耗比: {summary.LossRatio * 100:F2}%");
        }

        Console.WriteLine("\n============================================================");
    }
}
