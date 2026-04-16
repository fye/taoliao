# 电力行业角钢套料优化系统

基于混合整数规划（MIP）+ 贪心算法的角钢套料优化系统，用于电力行业中角钢材料的下料优化，最大化材料利用率。

## 功能特性

- **MIP精确求解**：使用 OR-Tools CBC 求解器，保证最优解
- **贪心算法回退**：MIP无法求解时自动回退，保证总能得到可行解
- **灵活的约束配置**：支持自定义零件号限制、余料限制等参数
- **损耗规则配置**：支持不同规格、材质的损耗规则
- **Excel输入输出**：支持Excel格式的需求清单和结果输出

## 环境依赖

- **Python**: 3.8+
- **操作系统**: macOS / Linux / Windows

## 安装步骤

### 1. 克隆仓库

```bash
git clone git@github.com:fye/taoliao.git
cd taoliao
```

### 2. 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# 或
.\venv\Scripts\activate   # Windows
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

依赖包列表：
- `ortools` - Google OR-Tools 优化求解器
- `pandas` - 数据处理
- `openpyxl` - Excel文件读写

## 执行命令

### 基本用法

使用默认配置运行：

```bash
source venv/bin/activate
python main.py
```

### 完整参数

```bash
python main.py --demand docs/需求清单.xlsx \
               --market docs/角钢市场清单.xlsx \
               --loss docs/损耗规则.xlsx \
               --output output/套料结果.xlsx \
               --max-parts 3 \
               --max-materials 3 \
               --max-remainder 1000 \
               --time-limit 60
```

### 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|-----|------|-------|------|
| `--demand` | `-d` | docs/需求清单.xlsx | 需求清单文件路径 |
| `--market` | `-m` | docs/角钢市场清单.xlsx | 市场清单文件路径 |
| `--loss` | `-l` | docs/损耗规则.xlsx | 损耗规则文件路径 |
| `--output` | `-o` | output/套料结果.xlsx | 输出文件路径 |
| `--max-parts` | | 3 | 单根原材料最多零件号数 |
| `--max-materials` | | 3 | 单零件号最多原材料数 |
| `--max-remainder` | | 1000 | 余料上限(mm) |
| `--time-limit` | | 3600 | 每分组求解时间限制(秒) |

## 输入文件格式

### 需求清单 (demand)

| 字段名 | 类型 | 说明 |
|-------|------|------|
| 部件号 | 字符串 | 零件唯一标识 |
| 材质 | 字符串 | 如 Q235B, Q355B |
| 规格 | 字符串 | 如 L90X7 |
| 长度(mm) | 整数 | 零件长度 |
| 单基数量(件) | 整数 | 需求数量 |

### 市场清单 (market)

| 字段名 | 类型 | 说明 |
|-------|------|------|
| 材质 | 字符串 | 如 Q235B |
| 规格全称 | 字符串 | 如 L100X10 |
| 长度 | 整数 | 原材料长度(mm) |
| A市场货存量 | 整数 | 库存数量 |

### 损耗规则 (loss)

| 字段名 | 类型 | 说明 |
|-------|------|------|
| 肢宽范围 | 字符串 | 如 L40-L56 |
| 厚度范围 | 字符串 | 如 小于等于12 |
| 材质 | 字符串 | 如 Q235,Q355,Q420 |
| 单刀损耗 | 整数 | 每次切割损耗(mm) |
| 头尾损耗 | 整数 | 固定损耗(mm) |

## 输出文件格式

输出为Excel文件，包含3个Sheet：

### Sheet 1: 原始需求清单
复制输入的需求清单

### Sheet 2: 套料结果

| 字段名 | 说明 |
|-------|------|
| 序号 | 切割方案编号 |
| 原材料材质 | 使用的原材料材质 |
| 规格 | 原材料规格 |
| 原材料长度 | 原材料长度(mm) |
| 切割的部件号 | 如 915/1049*1 + 411/996*4 |
| 切割刀数 | 切割次数 |
| 单刀损 | 单刀损耗(mm) |
| 两头损耗 | 头尾损耗(mm) |
| 使用长度 | 零件总长度(mm) |
| 剩余长度 | 余料(mm) |
| 利用率 | 零件长度/原材料长度 |
| 损耗比 | 损耗/原材料长度 |

### Sheet 3: 原材料汇总

| 字段名 | 说明 |
|-------|------|
| 材质 | 原材料材质 |
| 规格 | 原材料规格 |
| 母材数量 | 使用数量(根) |
| 总长度 | 总长度(mm) |
| 使用长度 | 零件总长度(mm) |
| 损耗长度 | 总损耗(mm) |
| 利用率 | 平均利用率 |
| 损耗比 | 平均损耗比 |

## Python API 使用

```python
from taoliao.core import NestingOptimizer, NestingConfig
from taoliao.data import DataLoader, ResultExporter

# 加载数据
loader = DataLoader()
parts = loader.load_parts('docs/需求清单.xlsx')
materials = loader.load_materials('docs/角钢市场清单.xlsx')

# 配置参数
config = NestingConfig(
    max_parts_per_material=3,    # 单根材料最多3种零件
    max_materials_per_part=3,    # 单零件最多3根材料
    max_remainder=1000,          # 余料上限1000mm
    time_limit=60                # 每分组60秒
)

# 执行优化
optimizer = NestingOptimizer(config)
result = optimizer.optimize(parts, materials)

# 导出结果
exporter = ResultExporter(result)
exporter.export('output/result.xlsx', loader.get_raw_parts_df())

# 打印摘要
exporter.print_summary()
```

## 运行示例

```
============================================================
套料结果摘要
============================================================

总切割方案数: 290
总利用率: 90.10%
总损耗比: 0.55%

原材料使用情况:
------------------------------------------------------------
  Q355B L90X7:
    数量: 19 根
    利用率: 97.95%
    损耗比: 0.76%
  Q235B L45X4:
    数量: 34 根
    利用率: 90.37%
    损耗比: 0.79%
  ...
```

## 项目结构

```
taoliao/
├── taoliao/
│   ├── core/                    # 核心算法
│   │   ├── models.py           # 数据模型
│   │   ├── optimizer.py        # MIP优化器
│   │   ├── greedy_solver.py    # 贪心算法
│   │   ├── loss_calculator.py  # 损耗计算
│   │   └── utils.py            # 辅助函数
│   ├── data/                    # 数据处理
│   │   ├── loader.py           # 数据加载
│   │   └── exporter.py         # 结果导出
│   └── config/                  # 配置
│       └── settings.py
├── docs/                        # 文档和示例数据
│   ├── 设计文档.md
│   ├── 算法设计.md
│   ├── 套料规则.md
│   ├── 需求清单.xlsx
│   ├── 角钢市场清单.xlsx
│   └── 损耗规则.xlsx
├── output/                      # 输出目录
├── main.py                      # CLI入口
├── requirements.txt             # 依赖列表
└── README.md                    # 本文件
```

## 算法说明

系统采用**MIP + 贪心**混合策略：

1. **MIP精确求解**：对每个规格分组，构建混合整数规划模型，使用OR-Tools CBC求解器求解
2. **贪心回退**：当MIP超时或无解时，自动回退到贪心算法，保证总能得到可行解

详细算法设计请参考 [算法设计文档](docs/算法设计.md)。

## 许可证

MIT License
