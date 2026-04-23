# 电力行业角钢套料优化系统 (C#版)

基于混合整数规划（MIP）+ 贪心算法的角钢套料优化系统，用于电力行业中角钢材料的下料优化，最大化材料利用率。

## 环境依赖

- **.NET SDK**: 8.0+
- **操作系统**: macOS / Linux / Windows

## 依赖包

- `Google.OrTools` (9.8.3296) - Google OR-Tools 优化求解器
- `NPOI` (2.7.2) - Excel文件读写

## 安装步骤

### 1. 安装 .NET SDK

**macOS:**
```bash
brew install --cask dotnet-sdk
```

**Linux (Ubuntu):**
```bash
sudo apt-get update
sudo apt-get install -y dotnet-sdk-8.0
```

**Windows:**
从 https://dotnet.microsoft.com/download 下载安装

### 2. 克隆仓库

```bash
git clone git@github.com:fye/taoliao.git
cd taoliao/taoliao_csharp
```

### 3. 还原依赖

```bash
dotnet restore
```

### 4. 编译项目

```bash
dotnet build
```

## 执行命令

### 基本用法

```bash
dotnet run --project Taoliao.CLI
```

### 指定需求文件

```bash
dotnet run --project Taoliao.CLI -- -d ../docs/EB21S-DJ原始表.xlsx
```

### 完整参数

```bash
dotnet run --project Taoliao.CLI -- \
    -d ../docs/需求清单.xlsx \
    -m ../docs/角钢市场清单.xlsx \
    -l ../docs/损耗规则.xlsx \
    --max-parts 3 \
    --max-materials 3 \
    --max-remainder 1000 \
    --time-limit 120
```

### 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|-----|------|-------|------|
| `--demand` | `-d` | ../docs/需求清单.xlsx | 需求清单文件路径 |
| `--market` | `-m` | ../docs/角钢市场清单.xlsx | 市场清单文件路径 |
| `--loss` | `-l` | ../docs/损耗规则.xlsx | 损耗规则文件路径 |
| `--output` | `-o` | ../output/套料结果.xlsx | 输出文件路径 |
| `--max-parts` | | 3 | 单根原材料最多零件号数 |
| `--max-materials` | | 3 | 单零件号最多套料方案数（按不同方案计数） |
| `--max-remainder` | | 1000 | 余料上限(mm) |
| `--time-limit` | | 120 | 每分组MIP求解时间限制(秒) |

**注意**：零件数 > 50 的分组使用贪心算法，≤ 50 使用 MIP 精确求解

## 输出结果

输出Excel文件包含以下Sheet页：

| Sheet名称 | 说明 |
|----------|------|
| 原始需求清单 | 输入的零件需求列表 |
| 套料结果 | 每根原材料的切割方案 |
| 原材料汇总 | 各材质规格的使用统计 |
| 未套料零部件 | 无法匹配原材料的零件（如有） |

## 项目结构

```
taoliao_csharp/
├── Taoliao.sln                    # 解决方案文件
├── Taoliao.Core/                  # 核心库
│   ├── Taoliao.Core.csproj
│   ├── Models/
│   │   └── Models.cs             # 数据模型
│   ├── Services/
│   │   ├── DataLoader.cs         # 数据加载
│   │   ├── ResultExporter.cs     # 结果导出
│   │   └── LossCalculator.cs     # 损耗计算
│   ├── Algorithms/
│   │   ├── MipNestingOptimizer.cs # MIP优化器
│   │   └── GreedyNestingSolver.cs # 贪心算法
│   └── NestingOptimizer.cs       # 主优化器
└── Taoliao.CLI/                   # 命令行工具
    ├── Taoliao.CLI.csproj
    └── Program.cs
```

## 与Python版本对比

| 特性 | Python版 | C#版 |
|-----|---------|------|
| 求解器 | OR-Tools (Python) | OR-Tools (C#) |
| Excel处理 | pandas + openpyxl | NPOI |
| 性能 | 较慢 | 更快 |
| 部署 | 需Python环境 | 单文件可执行 |

## 发布可执行文件

```bash
# 发布为单文件
dotnet publish Taoliao.CLI -c Release -r osx-arm64 --self-contained -p:PublishSingleFile=true

# 输出位置
# Taoliao.CLI/bin/Release/net8.0/osx-arm64/publish/Taoliao.CLI
```

支持的运行时：
- `osx-arm64` - macOS Apple Silicon
- `osx-x64` - macOS Intel
- `linux-x64` - Linux x64
- `win-x64` - Windows x64
