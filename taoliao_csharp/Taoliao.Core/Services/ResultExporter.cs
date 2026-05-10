using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using OfficeOpenXml;
using Taoliao.Core.Models;

namespace Taoliao.Core.Services
{
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
        public void Export(string outputPath, List<Part> originalParts = null)
        {
            // 确保输出目录存在
            var dir = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
            {
                Directory.CreateDirectory(dir);
            }

            using (var package = new ExcelPackage())
            {
                // Sheet 1: 原始需求清单
                WriteOriginalParts(package, originalParts);

                // Sheet 2: 套料结果
                WriteCuttingPlans(package);

                // Sheet 3: 原材料汇总
                WriteMaterialSummary(package);

                package.SaveAs(new FileInfo(outputPath));
            }
        }

        private void WriteOriginalParts(ExcelPackage package, List<Part> originalParts)
        {
            var worksheet = package.Workbook.Worksheets.Add("原始需求清单");

            var headers = new[] { "段号(只读)", "部件号", "材质", "规格", "长度(mm)", "宽度(mm)",
                "单基数量(件)", "单件重量(kg)", "单件孔数", "备注" };

            for (int i = 0; i < headers.Length; i++)
            {
                worksheet.Cells[1, i + 1].Value = headers[i];
            }

            var parts = originalParts ?? _result.OriginalParts;
            for (int i = 0; i < parts.Count; i++)
            {
                var row = i + 2;
                var part = parts[i];

                worksheet.Cells[row, 1].Value = part.SegmentNo ?? "";
                worksheet.Cells[row, 2].Value = part.PartNo;
                worksheet.Cells[row, 3].Value = part.Material;
                worksheet.Cells[row, 4].Value = part.Spec;
                worksheet.Cells[row, 5].Value = part.Length;
                worksheet.Cells[row, 6].Value = part.Width.HasValue ? part.Width.ToString() : "";
                worksheet.Cells[row, 7].Value = part.Quantity;
                worksheet.Cells[row, 8].Value = part.Weight.HasValue ? part.Weight.ToString() : "";
                worksheet.Cells[row, 9].Value = part.Holes.HasValue ? part.Holes.ToString() : "";
                worksheet.Cells[row, 10].Value = part.Remark ?? "";
            }
        }

        private void WriteCuttingPlans(ExcelPackage package)
        {
            var worksheet = package.Workbook.Worksheets.Add("套料结果");

            var headers = new[] { "序号", "原材料材质", "规格", "原材料长度", "切割的部件号",
                "切割刀数", "单刀损", "两头损耗", "使用长度", "剩余长度", "利用率", "损耗比", "备注" };

            for (int i = 0; i < headers.Length; i++)
            {
                worksheet.Cells[1, i + 1].Value = headers[i];
            }

            for (int i = 0; i < _result.CuttingPlans.Count; i++)
            {
                var row = i + 2;
                var plan = _result.CuttingPlans[i];

                worksheet.Cells[row, 1].Value = i + 1;
                worksheet.Cells[row, 2].Value = plan.RawMaterial.MaterialType;
                worksheet.Cells[row, 3].Value = plan.RawMaterial.Spec;
                worksheet.Cells[row, 4].Value = plan.RawMaterial.Length;
                worksheet.Cells[row, 5].Value = plan.PartsDescription;
                worksheet.Cells[row, 6].Value = plan.CutCount;
                worksheet.Cells[row, 7].Value = plan.SingleCutLoss;
                worksheet.Cells[row, 8].Value = plan.HeadTailLoss;
                worksheet.Cells[row, 9].Value = plan.UsedLength;
                worksheet.Cells[row, 10].Value = plan.RemainingLength;
                worksheet.Cells[row, 11].Value = string.Format("{0:F2}%", plan.Utilization * 100);
                worksheet.Cells[row, 12].Value = string.Format("{0:F2}%", plan.LossRatio * 100);
                worksheet.Cells[row, 13].Value = plan.Overflow ? "溢出" : "";
            }
        }

        private void WriteMaterialSummary(ExcelPackage package)
        {
            var worksheet = package.Workbook.Worksheets.Add("原材料汇总");

            var headers = new[] { "材质", "规格", "套料明细", "母材数量", "总长度", "使用长度",
                "损耗长度", "利用率", "损耗比" };

            for (int i = 0; i < headers.Length; i++)
            {
                worksheet.Cells[1, i + 1].Value = headers[i];
            }

            // 统计每种材质规格下，不同长度的使用数量
            var lengthDistribution = new Dictionary<string, Dictionary<int, int>>();
            foreach (var plan in _result.CuttingPlans)
            {
                var key = string.Format("{0}_{1}", plan.RawMaterial.MaterialType, plan.RawMaterial.Spec);
                var length = plan.RawMaterial.Length;
                if (!lengthDistribution.ContainsKey(key))
                    lengthDistribution[key] = new Dictionary<int, int>();
                if (!lengthDistribution[key].ContainsKey(length))
                    lengthDistribution[key][length] = 0;
                lengthDistribution[key][length]++;
            }

            int rowIndex = 2;
            var sortedKeys = _result.MaterialSummary.Keys.OrderBy(k => k).ToList();
            foreach (var key in sortedKeys)
            {
                var summary = _result.MaterialSummary[key];
                var row = rowIndex++;

                // 格式化长度分布
                string lengthDetail = "";
                if (lengthDistribution.ContainsKey(key))
                {
                    var sortedLengths = lengthDistribution[key].OrderByDescending(kv => kv.Key).ToList();
                    lengthDetail = string.Join(" + ", sortedLengths.Select(kv => string.Format("{0} * {1}", kv.Key, kv.Value)));
                }

                var parts = key.Split('_');
                worksheet.Cells[row, 1].Value = parts[0];
                worksheet.Cells[row, 2].Value = parts[1];
                worksheet.Cells[row, 3].Value = lengthDetail;
                worksheet.Cells[row, 4].Value = summary.Count;
                worksheet.Cells[row, 5].Value = summary.TotalLength;
                worksheet.Cells[row, 6].Value = summary.TotalUsed;
                worksheet.Cells[row, 7].Value = summary.TotalLoss;
                worksheet.Cells[row, 8].Value = string.Format("{0:F2}%", summary.Utilization * 100);
                worksheet.Cells[row, 9].Value = string.Format("{0:F2}%", summary.LossRatio * 100);
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

            Console.WriteLine(string.Format("\n总切割方案数: {0}", _result.CuttingPlans.Count));
            Console.WriteLine(string.Format("总利用率: {0:F2}%", _result.TotalUtilization * 100));
            Console.WriteLine(string.Format("总损耗比: {0:F2}%", _result.TotalLossRatio * 100));

            Console.WriteLine("\n原材料使用情况:");
            Console.WriteLine("------------------------------------------------------------");

            var sortedKeys = _result.MaterialSummary.Keys.OrderBy(k => k).ToList();
            foreach (var key in sortedKeys)
            {
                var summary = _result.MaterialSummary[key];
                var parts = key.Split('_');
                Console.WriteLine(string.Format("  {0} {1}:", parts[0], parts[1]));
                Console.WriteLine(string.Format("    数量: {0} 根", summary.Count));
                Console.WriteLine(string.Format("    利用率: {0:F2}%", summary.Utilization * 100));
                Console.WriteLine(string.Format("    损耗比: {0:F2}%", summary.LossRatio * 100));
            }

            Console.WriteLine("\n============================================================");
        }
    }
}