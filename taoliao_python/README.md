# 电力行业角钢套料优化系统 (Python版)

基于混合整数规划（MIP）+ 贪心算法的角钢套料优化系统，用于电力行业中角钢材料的下料优化，最大化材料利用率。

## 环境依赖

- **Python**: 3.8+
- **操作系统**: macOS / Linux / Windows

## 安装步骤

### 1. 进入Python项目目录

```bash
cd taoliao_python
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

```bash
source venv/bin/activate
python main.py
```

### 完整参数

```bash
python main.py --demand ../docs/需求清单.xlsx \
               --market ../docs/角钢市场清单.xlsx \
               --loss ../docs/损耗规则.xlsx \
               --output ../output/套料结果.xlsx \
               --max-parts 3 \
               --max-materials 3 \
               --max-remainder 1000 \
               --time-limit 60
```

### 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|-----|------|-------|------|
| `--demand` | `-d` | ../docs/需求清单.xlsx | 需求清单文件路径 |
| `--market` | `-m` | ../docs/角钢市场清单.xlsx | 市场清单文件路径 |
| `--loss` | `-l` | ../docs/损耗规则.xlsx | 损耗规则文件路径 |
| `--output` | `-o` | ../output/套料结果.xlsx | 输出文件路径 |
| `--max-parts` | | 3 | 单根原材料最多零件号数 |
| `--max-materials` | | 3 | 单零件号最多原材料数 |
| `--max-remainder` | | 1000 | 余料上限(mm) |
| `--time-limit` | | 3600 | 每分组求解时间限制(秒) |

## 项目结构

```
taoliao_python/
├── main.py                      # CLI入口
├── requirements.txt             # 依赖列表
└── taoliao/                     # 核心包
    ├── __init__.py
    ├── core/                    # 核心算法
    │   ├── __init__.py
    │   ├── models.py           # 数据模型
    │   ├── optimizer.py        # MIP优化器
    │   ├── greedy_solver.py    # 贪心算法
    │   ├── loss_calculator.py  # 损耗计算
    │   └── utils.py            # 辅助函数
    ├── data/                    # 数据处理
    │   ├── __init__.py
    │   ├── loader.py           # 数据加载
    │   └── exporter.py         # 结果导出
    └── config/                  # 配置
        ├── __init__.py
        └── settings.py
```

## Python API 使用

```python
from taoliao.core import NestingOptimizer, NestingConfig
from taoliao.data import DataLoader, ResultExporter

# 加载数据
loader = DataLoader()
parts = loader.load_parts('../docs/需求清单.xlsx')
materials = loader.load_materials('../docs/角钢市场清单.xlsx')

# 配置参数
config = NestingConfig(
    max_parts_per_material=3,
    max_materials_per_part=3,
    max_remainder=1000,
    time_limit=60
)

# 执行优化
optimizer = NestingOptimizer(config)
result = optimizer.optimize(parts, materials)

# 导出结果
exporter = ResultExporter(result)
exporter.export('../output/result.xlsx', loader.get_raw_parts_df())
exporter.print_summary()
```
