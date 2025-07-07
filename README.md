# iFixit爬虫

该爬虫用于爬取[iFixit英文网站](https://www.ifixit.com/)上的设备信息、维修指南和故障排除内容。

**🎉 v3.0重大更新**：新增整合爬虫工具，结合树形结构和详细内容提取，提供最完整的数据爬取解决方案。同时修复了字段排序问题，确保数据结构的一致性和可读性。

## 项目概述

本项目是一个功能完整的iFixit网站爬虫工具集，支持多种爬取模式和数据格式。从简单的产品信息提取到完整的维修指南和故障排除内容爬取，满足不同层次的数据需求。

## 核心特性

### 🚀 多模式爬取支持
- **🌟 整合爬虫** (`combined_crawler.py`) - **最新推荐**：结合树形结构和详细内容，提供最完整的数据
- **增强版爬虫** (`enhanced_crawler.py`) - 完整内容爬取，包括维修指南详细步骤和故障排除内容
- **交互式爬虫** (`easy_crawler.py`) - 新手友好，支持引导式类别选择
- **批量爬虫** (`batch_crawler.py`) - 自动遍历指定类别下的所有产品
- **树形爬虫** (`tree_crawler.py`) - 构建完整的多层级设备分类树结构
- **完整站点爬虫** (`crawler.py`) - 从根目录开始的全站递归爬取

### 🎯 智能内容提取
- **精准数据提取**：从产品页面智能提取产品名称、URL和说明书链接，支持PDF文档和视频指南
- **智能内容验证**：只提取页面上真实存在的内容，杜绝虚假字段，确保数据质量
- **动态字段识别**：根据页面实际结构动态提取字段，适应不同页面布局
- **多媒体资源提取**：支持图片、视频、文档等多种媒体资源的URL提取
- **内容质量控制**：自动排除Related Pages、评论区、商业推广等无关内容

### 🔧 高级功能
- **路径智能识别**：从React组件提取面包屑导航，支持中英文混合路径，精确构建设备分类层次
- **智能分层爬取**：递归爬取设备分类树，构建完整的多层级产品结构，自动区分分类和产品
- **规范的数据结构**：产品节点与分类节点严格区分，支持多种输出格式
- **详细输出控制**：支持静默模式和详细模式，可通过命令行参数控制调试信息的显示
- **智能URL处理**：自动添加语言参数，支持多种URL格式输入，智能检测页面存在性
- **Robots.txt遵守**：完全遵守网站爬取规则，添加合理延迟避免对服务器造成压力

## 数据格式说明

### 📋 基础爬虫格式（easy_crawler.py、batch_crawler.py）

#### 单个产品对象格式
```json
{
  "product_name": "iPad Pro 12.9英寸 Repair",
  "product_url": "https://www.ifixit.com/Device/iPad_Pro_12.9%22",
  "instruction_url": "https://www.ifixit.com/Document/.../manual.pdf"
}
```

#### 批量产品数组格式
```json
[
  {
    "product_name": "iPad Pro 12.9英寸 Repair",
    "product_url": "https://www.ifixit.com/Device/iPad_Pro_12.9%22",
    "instruction_url": "https://www.ifixit.com/Document/.../manual.pdf"
  },
  {
    "product_name": "iPad Air 2 Repair",
    "product_url": "https://www.ifixit.com/Device/iPad_Air_2",
    "instruction_url": ""
  }
]
```

### 🌟 整合爬虫格式（combined_crawler.py）- 最新推荐

#### 完整树形结构 + 详细内容
```json
{
  "name": "Device",
  "url": "https://www.ifixit.com/Device",
  "children": [
    {
      "name": "Mac",
      "url": "https://www.ifixit.com/Device/Mac",
      "title": "Mac Repair",
      "view_statistics": {
        "past_24_hours": "1,366",
        "past_7_days": "10,431",
        "past_30_days": "45,581",
        "all_time": "18,173,453"
      },
      "children": [
        {
          "name": "MacBook_Pro_17\"_Unibody",
          "url": "https://www.ifixit.com/Device/MacBook_Pro_17%22_Unibody",
          "title": "MacBook Pro 17\" Unibody Repair",
          "instruction_url": "",
          "view_statistics": {
            "past_24_hours": "31",
            "past_7_days": "237",
            "past_30_days": "806",
            "all_time": "683,126"
          },
          "guides": [
            {
              "url": "https://www.ifixit.com/Guide/MacBook+Pro+17-Inch+Unibody+AirPort+Antenna+Replacement/9588",
              "title": "MacBook Pro 17\" Unibody AirPort Antenna Replacement",
              "time_required": "No estimate",
              "difficulty": "Moderate",
              "introduction": "Replace the AirPort Antenna in your MacBook Pro...",
              "what_you_need": {
                "Tools": ["Phillips #00 Screwdriver", "Spudger", "T6 Torx Screwdriver"]
              },
              "view_statistics": {
                "past_24_hours": "13",
                "past_7_days": "77",
                "past_30_days": "128",
                "all_time": "17,050"
              },
              "completed": "9",
              "favorites": "14",
              "videos": [],
              "steps": [
                {
                  "title": "Step 1 Lower Case",
                  "content": "Remove the following ten screws...",
                  "images": ["https://guide-images.cdn.ifixit.com/igi/syE2ybccRrcFeJJi.medium"],
                  "videos": []
                }
              ]
            }
          ],
          "troubleshooting": [
            {
              "url": "https://www.ifixit.com/Troubleshooting/Mac_Laptop/MacBook+Fan+Loud/506012",
              "title": "MacBook Fan Loud",
              "view_statistics": {
                "past_24_hours": "300",
                "past_7_days": "2,342",
                "past_30_days": "8,618",
                "all_time": "56,374"
              },
              "first_steps": "Before undertaking any of the more time consuming solutions...",
              "causes": [
                {
                  "number": "1",
                  "title": "Overheating",
                  "content": "The harder your MacBook is working, the more heat it is generating...",
                  "images": [
                    {
                      "url": "https://guide-images.cdn.ifixit.com/igi/abc.medium.jpg",
                      "description": "CPU temperature monitoring"
                    }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

**数据结构特点**：
- ✅ **完整层级结构**：从根目录到目标设备的完整路径
- ✅ **正确字段顺序**：name → url → title → 详细内容 → children
- ✅ **智能内容验证**：只包含页面真实存在的字段
- ✅ **多媒体资源**：图片、视频、文档URL完整提取
- ✅ **统计数据**：浏览量、完成数、收藏数等真实数据
- ✅ **完整内容爬取**：支持爬取所有指南和故障排除，无数量限制

**实际爬取示例**（MacBook Pro 17" Unibody）：
- **指南数量**：35个完整维修指南
- **故障排除**：7个详细故障排除页面
- **文件大小**：644KB (7,930 行)
- **数据完整性**：包含完整的步骤说明、工具清单、统计数据

### 🔧 增强版爬虫格式（enhanced_crawler.py）

#### 完整设备信息对象
```json
{
  "product_name": "MacBook Pro 17英寸 Unibody Repair",
  "product_url": "https://www.ifixit.com/Device/MacBook_Pro_17%22_Unibody",
  "instruction_url": "",
  "guides": [
    {
      "url": "https://www.ifixit.com/Guide/MacBook+Pro+17-Inch+Unibody+AirPort+Antenna+Replacement/9588",
      "title": "MacBook Pro 17\" Unibody AirPort Antenna Replacement",
      "time_required": "No estimate",
      "difficulty": "Moderate",
      "introduction": "Replace the AirPort Antenna in your MacBook Pro to get a clear signal...",
      "what_you_need": {
        "Tools": ["Phillips #00 Screwdriver", "Spudger", "T6 Torx Screwdriver"]
      },
      "view_statistics": {
        "past_24_hours": "20",
        "past_7_days": "61",
        "past_30_days": "110",
        "all_time": "17,031"
      },
      "completed": "9",
      "favorites": "14",
      "videos": [],
      "steps": [
        {
          "title": "Step 1 Lower Case",
          "content": "Remove the following ten screws securing the lower case...",
          "images": ["https://guide-images.cdn.ifixit.com/igi/syE2ybccRrcFeJJi.medium"],
          "videos": []
        }
      ]
    }
  ],
  "troubleshooting": [
    {
      "url": "https://www.ifixit.com/Troubleshooting/Mac_Laptop/MacBook+Won't+Turn+On/483799",
      "title": "MacBook Won't Turn On",
      "view_statistics": {
        "past_24_hours": "188",
        "past_7_days": "1,174",
        "past_30_days": "5,428",
        "all_time": "116,958"
      },
      "introduction": "There are few electronics problems more disheartening...",
      "the_basics": "Before undertaking any of the more time-consuming solutions...",
      "causes": [
        {
          "number": "1",
          "title": "Faulty Power Source",
          "content": "Your computer itself could be perfectly fine...",
          "images": [
            {
              "url": "https://guide-images.cdn.ifixit.com/igi/abc.medium.jpg",
              "alt": "Power adapter connection"
            }
          ],
          "videos": []
        }
      ]
    }
  ],
  "crawl_timestamp": "2024-07-04 15:30:45"
}
```

### 🌳 树形结构格式（tree_crawler.py）

#### 多层级设备分类树
```json
{
  "name": "设备",
  "url": "https://www.ifixit.com/Device",
  "children": [
    {
      "name": "Mac",
      "url": "https://www.ifixit.com/Device/Mac",
      "children": [
        {
          "name": "笔记本",
          "url": "https://www.ifixit.com/Device/Mac/笔记本",
          "children": [
            {
              "name": "MacBook",
              "url": "https://www.ifixit.com/Device/Mac/笔记本/MacBook",
              "children": [
                {
                  "name": "MacBook Core Duo Repair",
                  "url": "https://www.ifixit.com/Device/MacBook_Core_Duo",
                  "instruction_url": "",
                  "children": []
                },
                {
                  "name": "MacBook Unibody A1342 Repair",
                  "url": "https://www.ifixit.com/Device/MacBook_Unibody_Model_A1342",
                  "instruction_url": "https://www.ifixit.com/Document/.../manual.pdf",
                  "children": []
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

**节点类型说明**：
- **分类节点**：包含 `name`、`url`、`children` 字段，不包含 `instruction_url`
- **产品节点**：包含 `name`、`url`、`instruction_url`、`children` 字段，其中 `children` 为空数组

## 快速开始

### 📦 安装依赖

```bash
pip install -r requirements.txt
```

### 🚀 推荐使用方式

#### 1. 🌟 整合爬虫（最新推荐）- 树形结构 + 详细内容

获取设备的完整层级结构和详细内容，包括维修指南和故障排除：

```bash
# 基本用法（静默模式）
python combined_crawler.py MacBook_Pro_17%22_Unibody

# 启用详细输出模式
python combined_crawler.py MacBook_Pro_17%22_Unibody verbose

# 交互式输入
python combined_crawler.py

# 显示帮助信息
python combined_crawler.py --help
```

**支持的输入格式**：
```bash
# 完整URL
python combined_crawler.py https://www.ifixit.com/Device/MacBook_Pro_17%22_Unibody

# 产品名（推荐）
python combined_crawler.py MacBook_Pro_17%22_Unibody

# 类别名称
python combined_crawler.py Television
python combined_crawler.py LG_Television
```

**Python API 使用**：
```python
from combined_crawler import CombinedIFixitCrawler

# 创建整合爬虫实例
crawler = CombinedIFixitCrawler(verbose=True)

# 爬取完整树形结构和详细内容
device_url = "https://www.ifixit.com/Device/MacBook_Pro_17%22_Unibody"
result = crawler.crawl_combined_tree(device_url, "MacBook_Pro_17%22_Unibody")

# 保存结果
crawler.save_combined_result(result)
```

**输出特点**：
- ✅ 完整的层级树形结构（从根目录到目标设备）
- ✅ 每个节点的详细内容（维修指南、故障排除、统计数据）
- ✅ 智能内容验证，确保数据真实性
- ✅ 多媒体资源URL提取（图片、视频、文档）
- ✅ 正确的字段排序：name → url → title → 详细内容 → children
- ✅ 文件命名：`combined_[设备名].json`

#### 2. 增强版爬虫 - 完整内容爬取

获取设备的完整信息，包括维修指南和故障排除内容：

```bash
# 基本用法（静默模式）
python3 enhanced_crawler.py MacBook_Pro_17%22_Unibody

# 启用详细输出模式
python3 enhanced_crawler.py --verbose iPhone_12
python3 enhanced_crawler.py -v iPad_Air_2

# 显示帮助信息
python3 enhanced_crawler.py --help
```

**输出特点**：
- ✅ 设备基本信息、维修指南详细步骤、故障排除内容
- ✅ 智能内容验证，确保数据真实性
- ✅ 多媒体资源URL提取（图片、视频、文档）
- ✅ 静默/详细输出模式控制
- ✅ 文件命名：`enhanced_[设备名].json`

#### 3. 交互式爬虫（新手友好）

支持引导式类别选择，适合初学者使用：

```bash
# 基本用法
python3 easy_crawler.py iPad_3G

# 完整URL
python3 easy_crawler.py https://www.ifixit.com/Device/iPad_3G

# 交互式输入
python3 easy_crawler.py

# 显示帮助
python3 easy_crawler.py -h
```

**特点**：
- 🎯 自动检测页面类型（产品页面 vs 类别页面）
- 🔍 类别页面时显示子类别供用户选择
- 💬 支持交互式输入和引导
- 📝 自动开启调试模式显示详细信息
- 📁 文件命名：`[设备名].json`

#### 4. 批量爬虫（大量数据收集）

自动遍历指定类别下的所有产品，适合批量数据收集：

```bash
# 基本用法
python3 batch_crawler.py iPad

# 启用调试模式
python3 batch_crawler.py --debug LG_Television

# 测试预定义URL
python3 batch_crawler.py test

# 显示帮助
python3 batch_crawler.py -h
```

**特点**：
- 🔍 智能搜索：直接访问失败时自动搜索
- 🚫 自动去重，避免重复爬取
- ⏱️ 合理延迟，避免请求过于频繁
- 🐛 调试模式显示详细过程
- 📁 文件命名：`batch_[设备名].json`

#### 5. 树形爬虫（结构分析）

构建完整的多层级设备分类树，适合分析网站结构：

```bash
# 基本用法
python3 tree_crawler.py MacBook

# 启用调试模式
python3 tree_crawler.py --debug Television

# 完整URL
python3 tree_crawler.py https://www.ifixit.com/Device/LG_Television

# 显示帮助
python3 tree_crawler.py -h
```

**使用示例**：
```bash
# 不同产品类别
python3 tree_crawler.py Television          # 电视类别树
python3 tree_crawler.py LG_Television       # LG电视子类别
python3 tree_crawler.py Apple_Headphone     # 苹果耳机类别
python3 tree_crawler.py MacBook             # MacBook类别树
```

**特点**：
- 🌳 多层级路径发现，从React组件提取面包屑导航
- 🎯 精确构建设备分类层次结构
- 🔍 智能区分分类节点和产品节点
- 🌐 支持中英文混合路径处理
- 📁 文件命名：`tree_[目标名称].json`

#### 6. 完整站点爬虫（全站数据）

从设备首页开始递归爬取整个网站：

```bash
# 基本用法
python3 crawler.py

# 启用调试模式
python3 crawler.py --debug
```

**特点**：
- 🌐 从设备首页开始递归爬取所有类别和产品
- 🎯 自动识别最终产品页面和类别页面
- ⏱️ 添加随机延迟避免对服务器造成压力
- 🚫 自动跳过无关页面（创建指南、编辑页面等）
- 🐛 支持调试模式显示详细爬取过程

## 🔧 高级功能

### 树形爬虫高级特性

**多层次路径发现机制**：
1. **React组件数据提取**（最准确）- 从页面JavaScript数据中提取面包屑
2. **Schema.org元数据提取** - 从结构化数据中提取标准化面包屑
3. **DOM面包屑容器提取** - 从HTML面包屑元素中提取
4. **页面导航链接提取** - 从头部导航中提取路径信息
5. **URL结构推断** - 从URL路径推断基本分类结构

**路径示例**：
- 电视类别: `设备 > 电子产品 > 电视 > TCL Television`
- 耳机类别: `设备 > 电子产品 > 耳机 > Apple Headphone`
- 笔记本类别: `设备 > Mac > 笔记本 > MacBook`

**节点规范**：
- **分类节点**：`name` + `url` + `children`（不含instruction_url）
- **产品节点**：`name` + `url` + `instruction_url` + `children`（空数组）

## 📁 输出结果

所有爬取结果保存在 `results/` 目录下的JSON文件中：

### 文件命名规则

| 爬虫类型 | 文件命名格式 | 示例 |
|---------|-------------|------|
| **🌟 整合爬虫** | `combined_[设备名].json` | `combined_MacBook_Pro_17%22_Unibody.json` |
| 增强版爬虫 | `enhanced_[设备名].json` | `enhanced_MacBook_Pro_17%22_Unibody.json` |
| 交互式爬虫 | `[设备名].json` | `iPad_3G.json` |
| 批量爬虫 | `batch_[设备名].json` | `batch_LG_Television.json` |
| 树形爬虫 | `tree_[目标名称].json` | `tree_MacBook.json` |
| 完整爬虫 | `ifixit_products.json` | `ifixit_products.json` |

### 数据内容对比

| 爬虫类型 | 基本信息 | 维修指南 | 故障排除 | 树形结构 | 统计数据 | 字段排序 |
|---------|---------|---------|---------|---------|---------|---------|
| **🌟 整合爬虫** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 增强版爬虫 | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| 交互式爬虫 | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| 批量爬虫 | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| 树形爬虫 | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ |
| 完整爬虫 | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |

## ⚠️ 重要注意事项

### 🌐 网站访问规范
- **目标站点**：仅使用英文站点 `https://www.ifixit.com/`
- **Robots.txt遵守**：严格遵守网站爬取规则，跳过被禁止的URL
- **访问频率控制**：添加随机延迟（1-2秒），避免对服务器造成压力
- **URL结构理解**：iFixit使用路径替换而非追加，如 `/Device/Tablet` → `/Device/iPad`

### 🔍 内容质量保证（v2.1核心特性）
- **真实性验证**：只提取页面上真实存在的内容，绝不添加虚假字段
- **字段严格验证**：每个字段都经过验证，确保对应标题在页面上真实存在
- **内容纯净化**：自动排除作者信息、元数据、商业推广等非主要内容
- **边界精确检测**：识别不同内容区域边界，防止内容混合和污染
- **智能过滤**：自动跳过"创建指南"、"翻译"、"贡献者"等非产品页面

### 🎛️ 输出控制选项
- **增强版爬虫**：默认静默模式，使用 `--verbose` 或 `-v` 启用详细输出
- **其他爬虫**：使用 `--debug` 启用调试模式
- **帮助信息**：所有爬虫都支持 `--help` 或 `-h` 显示使用说明

## 📋 命令行选项总览

| 爬虫文件 | 基本用法 | 调试选项 | 帮助选项 | 特殊功能 |
|---------|---------|---------|---------|---------|
| **🌟 `combined_crawler.py`** | `python combined_crawler.py [URL/产品名]` | `verbose` | `--help`, `-h` | 交互式输入 |
| `enhanced_crawler.py` | `python3 enhanced_crawler.py [URL/产品名]` | `--verbose`, `-v` | `--help`, `-h` | `test` |
| `easy_crawler.py` | `python3 easy_crawler.py [URL/产品名]` | 默认开启 | `-h` | 交互式输入 |
| `batch_crawler.py` | `python3 batch_crawler.py [URL/产品名]` | `--debug` | `-h` | `test` |
| `tree_crawler.py` | `python3 tree_crawler.py [URL/设备名]` | `--debug` | `-h` | - |
| `crawler.py` | `python3 crawler.py` | `--debug` | - | - |

## 🔧 技术特性详解

### 增强版爬虫核心技术（v2.1）

**智能内容验证机制**：
- ✅ **真实性验证**：只提取页面真实存在的内容，不添加虚假字段
- ✅ **精确字段提取**：只有在页面存在对应标题时才提取相应字段
- ✅ **作者信息过滤**：自动识别并排除作者信息、元数据等非主要内容
- ✅ **内容边界检测**：精确识别不同section边界，防止内容混合
- ✅ **动态字段识别**：根据页面实际结构动态提取字段（introduction、first_steps、the_basics、triage等）

**高级去重算法**：
- 🔄 **多层次去重**：哈希、文本相似度、句子级别等多种去重算法
- 🔄 **内容重叠检测**：防止不同section之间的内容重复
- 🔄 **智能文本清理**：保留段落结构同时去除多余空白和重复内容

**多媒体资源提取**：
- 🖼️ **图片**：优先提取medium格式，过滤图标和缩略图
- 🎥 **视频**：支持YouTube、Vimeo等平台的嵌入视频和链接
- 📄 **文档**：支持PDF、Word文档以及iFixit指南链接
- 🔗 **媒体关联**：将图片和视频与对应的故障原因关联

**智能数据提取**：
- 📊 从API获取准确的时间和难度信息
- 📈 提取真实的浏览量、完成数、收藏数等统计数据
- 🎯 动态提取页面字段，适应不同页面结构
- 🔧 支持各种HTML结构的内容提取

### 基础爬虫特性

**产品识别与处理**：
- 🎯 **页面类型识别**：只收集最终产品页面，跳过中间类别页面
- 📝 **文本处理**：自动将英寸符号(")转换为"英寸"文本，优化JSON输出
- 📄 **说明书链接**：PDF文档优先，无PDF时提取视频指南链接

### 树形爬虫特性

**路径发现机制**：
- 🌐 **React组件提取**：从网页JavaScript数据中提取最精准的面包屑
- 📊 **多数据源融合**：Schema.org元数据、DOM面包屑、导航链接等
- 🔗 **智能路径修复**：确保所有路径符合网站真实结构
- 🌍 **中英文混合处理**：智能映射中文分类名称到英文URL

**支持的路径类型**：
- 📺 电视：`设备 > 电子产品 > 电视 > [品牌] Television`
- 🎧 耳机：`设备 > 电子产品 > 耳机 > [品牌] Headphone`
- 💻 笔记本：`设备 > Mac > 笔记本 > [品牌/型号]`

## 📁 项目文件说明

### 🚀 核心爬虫文件

| 文件名 | 功能描述 | 推荐场景 | 主要特性 |
|--------|---------|---------|---------|
| **🌟 `combined_crawler.py`** | **整合爬虫**（最新推荐） | 最完整数据需求 | 树形结构+详细内容、字段排序优化、完整层级路径 |
| `enhanced_crawler.py` | 增强版爬虫 | 详细内容需求 | 智能内容验证、多媒体提取、API数据获取 |
| `easy_crawler.py` | 交互式爬虫 | 新手学习、单个产品 | 引导式操作、页面类型检测 |
| `batch_crawler.py` | 批量爬虫 | 大量数据收集 | 自动搜索、去重处理、延迟控制 |
| `tree_crawler.py` | 树形结构爬虫 | 结构分析、分类研究 | 多层路径发现、面包屑提取 |
| `crawler.py` | 完整站点爬虫 | 全站数据、研究用途 | 递归爬取、页面识别 |

### 📋 配置文件

- `requirements.txt` - Python依赖包列表
- `robots.txt` - 网站爬取规则参考
- `need.txt` - 项目需求说明

### 📊 输出目录

- `results/` - 所有爬取结果的JSON文件存储目录

## 🎯 使用场景推荐

### 根据需求选择合适的爬虫

| 使用场景 | 推荐爬虫 | 命令示例 | 优势 |
|---------|---------|---------|------|
| **🌟 最完整数据研究** | `combined_crawler.py` | `python combined_crawler.py MacBook_Pro_17%22_Unibody` | 树形结构+详细内容，数据最全面 |
| **完整内容爬取** | `enhanced_crawler.py` | `python3 enhanced_crawler.py MacBook_Pro_17%22_Unibody` | 详细内容，质量最高 |
| **新手学习** | `easy_crawler.py` | `python3 easy_crawler.py iPad_3G` | 交互友好，操作简单 |
| **批量数据收集** | `batch_crawler.py` | `python3 batch_crawler.py LG_Television` | 自动化程度高，效率高 |
| **网站结构分析** | `tree_crawler.py` | `python3 tree_crawler.py MacBook` | 层级关系清晰 |
| **全站数据挖掘** | `crawler.py` | `python3 crawler.py` | 覆盖范围最广 |

### 典型工作流程

**1. 探索阶段**（推荐新手）：
```bash
# 先用交互式爬虫了解网站结构
python3 easy_crawler.py MacBook

# 再用树形爬虫分析分类层次
python3 tree_crawler.py MacBook
```

**2. 数据收集阶段**：
```bash
# 🌟 推荐：使用整合爬虫获取最完整数据（树形结构+详细内容）
python combined_crawler.py MacBook_Pro_17%22_Unibody verbose

# 或使用增强版爬虫获取详细内容
python3 enhanced_crawler.py --verbose MacBook_Pro_17%22_Unibody

# 或使用批量爬虫收集大量数据
python3 batch_crawler.py --debug MacBook
```

**3. 大规模研究**：
```bash
# 使用完整站点爬虫进行全站数据收集
python3 crawler.py --debug
```

## 🎛️ 输出控制详解

### 增强版爬虫输出模式

| 模式 | 命令 | 显示内容 | 适用场景 |
|------|------|---------|---------|
| **静默模式** | `python3 enhanced_crawler.py MacBook` | 仅基本进度 | 日常使用、自动化脚本 |
| **详细模式** | `python3 enhanced_crawler.py -v MacBook` | 完整调试信息 | 开发调试、问题排查 |

**详细模式包含信息**：
- 🔗 API调用详情和响应状态
- 📄 内容提取过程和字段验证
- 📊 图片和视频提取统计
- ✅ 完成统计和保存信息

### 其他爬虫调试选项

```bash
# 批量爬虫调试 - 显示每个产品的详细爬取过程
python3 batch_crawler.py --debug LG_Television

# 树形爬虫调试 - 显示路径发现和树结构构建过程
python3 tree_crawler.py --debug MacBook

# 完整爬虫调试 - 显示递归爬取的详细过程
python3 crawler.py --debug
```

### 输出信息对比表

| 信息类型 | 静默模式 | 详细/调试模式 | 说明 |
|---------|---------|-------------|------|
| 基本进度 | ✅ | ✅ | 爬取进度和状态 |
| API调用详情 | ❌ | ✅ | 请求URL、响应状态等 |
| 内容提取过程 | ❌ | ✅ | 字段提取、验证过程 |
| 统计信息 | ❌ | ✅ | 数据量、成功率等 |
| 错误详情 | 基本 | 详细 | 错误原因和堆栈信息 |

## 📈 版本更新历史

### 🎉 v3.0 - 整合爬虫与字段排序优化重大升级（当前版本）

**核心新功能**：
- 🌟 **整合爬虫工具**：新增 `combined_crawler.py`，结合树形结构和详细内容提取
- ✅ **完整层级路径**：从根目录到目标设备的完整树形结构
- ✅ **字段排序优化**：修复字段顺序问题，确保 name → url → title → 详细内容 → children
- ✅ **数据结构一致性**：统一所有爬虫的字段排序和数据格式
- ✅ **智能内容整合**：将树形结构与详细内容完美结合
- ✅ **无重复数据**：解决title字段重复出现的问题
- ✅ **完整数据爬取**：支持爬取所有指南和故障排除，无数量限制

### 🎉 v2.1 - 内容验证与质量控制重大升级

**核心改进**：
- ✅ **智能内容验证**：只提取页面真实存在的内容，杜绝虚假字段
- ✅ **精确字段提取**：修复Introduction等内容提取逻辑，支持各种HTML结构
- ✅ **作者信息过滤**：自动识别并排除作者信息、元数据等非主要内容
- ✅ **动态字段识别**：根据页面实际结构动态提取字段
- ✅ **高级去重机制**：多层次去重算法，防止内容重复和混合
- ✅ **内容边界检测**：精确识别不同section边界，确保数据纯净
- ✅ **媒体内容关联**：将图片和视频与对应的故障原因关联

### 🚀 v2.0 - 输出控制优化

**主要特性**：
- 🎛️ **输出模式控制**：增强版爬虫新增静默模式和详细输出模式
- 📋 **命令行统一**：统一所有爬虫的命令行参数格式
- 🌐 **智能URL处理**：自动添加语言参数，智能检测页面存在性
- 📊 **API数据提取**：从iFixit API获取准确的时间、难度和统计信息
- 🔧 **内容质量提升**：更好的商业内容过滤和重复内容去除

### 🔧 v1.5 - 功能完善

**功能增强**：
- 🎯 **故障排除优化**：精确的边界检测，避免提取无关内容
- 🎥 **多媒体资源**：完善的图片、视频、文档URL提取
- 📋 **数据结构规范**：统一的JSON输出格式和字段顺序
- 🌳 **路径发现增强**：多层次面包屑导航提取机制

### 🏗️ v1.0 - 基础功能

**基础架构**：
- 🔄 **多模式爬取**：支持单个、批量、树形、增强版等多种爬取模式
- 🎯 **智能分层**：自动区分产品页面和类别页面
- 🚫 **内容过滤**：排除无关页面和内容
- 📄 **数据提取**：基础的产品信息和说明书链接提取

## 🛠️ 技术规格

### 开发环境
- **编程语言**：Python 3.x
- **核心依赖**：
  - `requests` >= 2.25.1 - HTTP请求处理
  - `beautifulsoup4` >= 4.9.3 - HTML解析
  - `urllib3` - URL处理和网络请求
- **数据格式**：JSON (UTF-8编码)
- **目标网站**：iFixit英文站点 (www.ifixit.com)
- **合规性**：完全遵守robots.txt规则

### 系统要求
- Python 3.6+
- 网络连接
- 约50MB磁盘空间（用于依赖包）

### 性能特点
- **并发控制**：单线程顺序爬取，避免对服务器造成压力
- **延迟控制**：1-2秒随机延迟，符合网站访问规范
- **内存优化**：流式处理大型页面，避免内存溢出
- **错误恢复**：自动重试机制，提高爬取成功率

## 🤝 贡献指南

欢迎参与项目改进！我们接受以下类型的贡献：

### 🐛 Bug报告
- 详细描述问题现象和复现步骤
- 提供错误日志和环境信息
- 建议修复方案（如果有）

### 💡 功能建议
- 说明新功能的用途和应用场景
- 提供实现思路和技术方案
- 考虑对现有功能的影响

### 💻 代码贡献
- 遵循现有的代码风格和注释规范
- 添加必要的测试用例
- 更新相关文档

### 📚 文档改进
- 完善README和代码注释
- 添加使用示例和最佳实践
- 翻译文档到其他语言

## 📄 许可证与免责声明

**使用许可**：本项目仅供学习和研究使用

**重要提醒**：
- 请遵守iFixit网站的使用条款和robots.txt规则
- 不得用于商业用途或大规模数据挖掘
- 使用时请保持合理的访问频率
- 尊重网站版权和知识产权

**免责声明**：使用本工具产生的任何后果由使用者自行承担
 