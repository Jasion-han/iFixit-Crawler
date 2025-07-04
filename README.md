# iFixit爬虫

该爬虫用于爬取[iFixit英文网站](https://www.ifixit.com/)上的设备信息、维修指南和故障排除内容。

**🎉 v2.1重大更新**：新增智能内容验证机制，确保只提取页面上真实存在的内容，杜绝虚假字段，大幅提升数据质量和可靠性。

## 功能特点

- **全面内容爬取**：支持设备基本信息、维修指南详细内容、故障排除页面的完整爬取
- **智能分层爬取**：递归爬取设备分类树，构建完整的多层级产品结构，自动区分分类和产品
- **精准数据提取**：从产品页面智能提取产品名称、URL和说明书链接，支持PDF文档和视频指南
- **故障排除专项爬取**：专门针对Troubleshooting内容进行优化，提取文本、图片、视频、文档URL
- **内容质量控制**：自动排除Related Pages、评论区等无关内容，确保数据纯净
- **多媒体资源提取**：支持图片、视频、文档等多种媒体资源的URL提取
- **路径智能识别**：从React组件提取面包屑导航，支持中英文混合路径，精确构建设备分类层次
- **规范的数据结构**：产品节点与分类节点严格区分，支持多种输出格式
- **多模式爬取**：支持单个产品交互爬取、批量爬取、树形结构爬取和增强版爬取，满足不同使用场景
- **详细输出控制**：支持静默模式和详细模式，可通过命令行参数控制调试信息的显示
- **智能URL处理**：自动添加语言参数，支持多种URL格式输入，智能检测页面存在性

## 爬取结果格式

### 基础爬虫结果格式（easy_crawler.py、batch_crawler.py）

#### 单个对象格式（easy_crawler.py）
```json
{
  "product_name": "iPad Pro 12.9英寸 Repair",                          // 产品名称（英寸符号已统一处理）
  "product_url": "https://www.ifixit.com/Device/iPad_Pro_12.9%22",      // 产品完整URL
  "instruction_url": "https://www.ifixit.com/Document/.../ipad_w_3g.pdf" // 说明书链接（PDF文档或视频链接）
}
```

#### 数组格式（batch_crawler.py）
```json
[
  {
    "product_name": "iPad Pro 12.9英寸 Repair",                          // 产品名称（英寸符号已统一处理）
    "product_url": "https://www.ifixit.com/Device/iPad_Pro_12.9%22",      // 产品完整URL
    "instruction_url": "https://www.ifixit.com/Document/.../ipad_w_3g.pdf" // 说明书链接（PDF文档或视频链接）
  }
]
```

### 增强版爬虫结果格式（enhanced_crawler.py）

#### 完整设备信息格式
```json
{
  "title": "iPad 3G",                                    // 设备标题
  "description": "First-generation Apple iPad with 3G capabilities...", // 设备描述
  "url": "https://www.ifixit.com/Device/iPad_3G",        // 设备页面URL
  "guides": [                                             // 维修指南列表
    {
      "title": "iPad 3G Battery Replacement",            // 指南标题
      "url": "https://www.ifixit.com/Guide/iPad+3G+Battery+Replacement/3186",
      "introduction": "Replace the battery in your iPad 3G...", // 指南介绍
      "difficulty": "Moderate",                          // 难度等级
      "time_required": "30-45 minutes",                  // 所需时间
      "tools": ["Phillips #00 Screwdriver", "Spudger"], // 所需工具
      "parts": ["iPad 3G Battery"],                      // 所需零件
      "steps": [                                          // 步骤详情
        {
          "title": "Remove the SIM card",
          "content": "Use the SIM eject tool to remove...",
          "images": [
            {
              "url": "https://guide-images.cdn.ifixit.com/igi/xyz.medium.jpg",
              "alt": "SIM card removal"
            }
          ],
          "videos": [],
          "documents": []
        }
      ],
      "videos": [],                                       // 指南相关视频
      "documents": []                                     // 指南相关文档
    }
  ],
  "troubleshooting": [                                    // 故障排除内容
    {
      "url": "https://www.ifixit.com/Troubleshooting/Mac_Laptop/MacBook+Won't+Turn+On/483799",
      "title": "MacBook Won't Turn On",                   // 故障排除标题
      "view_statistics": {                               // 浏览统计（如果有）
        "past_24_hours": "188",
        "past_7_days": "1,174",
        "past_30_days": "5,428",
        "all_time": "116,958"
      },
      "introduction": "There are few electronics problems more disheartening...", // 介绍内容（仅当页面真实存在时）
      "the_basics": "Before undertaking any of the more time-consuming solutions...", // 基础步骤（动态字段名）
      "triage": "Troubleshooting is a process that often resembles medical diagnosis...", // 诊断步骤（如果有）
      "causes": [                                         // 故障原因列表
        {
          "number": "1",
          "title": "Faulty Power Source",
          "content": "Your computer itself could be perfectly fine, but you've got a faulty charger...",
          "images": [                                     // 该原因相关的图片
            {
              "url": "https://guide-images.cdn.ifixit.com/igi/abc.medium.jpg",
              "alt": "Power adapter connection"
            }
          ],
          "videos": [                                     // 该原因相关的视频
            {
              "url": "https://www.youtube.com/watch?v=xyz",
              "title": "Testing power adapter"
            }
          ]
        }
      ]
    }
  ],
  "crawl_timestamp": "2024-07-02 15:30:45"              // 爬取时间戳
}
```

### 树形结构格式（tree_crawler.py）

```json
{
  "name": "设备",                                    // 设备类别名称
  "url": "https://www.ifixit.com/Device",            // 类别URL
  "children": [                                      // 子类别或产品列表
    {
      "name": "电子产品",                             // 子类别名称
      "url": "https://www.ifixit.com/Device/Electronics", // 子类别URL
      "children": [                                  // 再下一级子类别或产品
        {
          "name": "电视",                             // 子类别名称
          "url": "https://www.ifixit.com/Device/Television", // 子类别URL
          "children": [                              // 再下一级子类别或产品
            {
              "name": "LG Television",               // 子类别名称
              "url": "https://www.ifixit.com/Device/LG_Television", // 子类别URL
              "children": [                          // 再下一级子类别或产品
                {
                  "name": "LG (70UK6570PUB) Repair", // 产品名称
                  "url": "https://www.ifixit.com/Device/70UK6570PUB", // 产品URL
                  "instruction_url": "https://www.ifixit.com/Document/.../manual.pdf", // 说明书链接
                  "children": []                     // 空数组表示这是产品节点(叶子节点)
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

## 使用方法

### 安装依赖

```bash
pip install -r requirements.txt
```

### 方法一：增强版爬虫（推荐）- 完整内容爬取

使用增强版爬虫，支持设备信息、维修指南和故障排除内容的完整爬取：

```bash
# 基本用法（静默模式）
python3 enhanced_crawler.py [URL或产品名]

# 启用详细输出模式
python3 enhanced_crawler.py --verbose [URL或产品名]
python3 enhanced_crawler.py -v [URL或产品名]

# 显示帮助信息
python3 enhanced_crawler.py --help
```

**使用示例**：
```bash
# 使用完整URL
python3 enhanced_crawler.py https://www.ifixit.com/Device/MacBook_Pro_17%22_Unibody
python3 enhanced_crawler.py https://www.ifixit.com/Device/iPhone_12

# 使用产品名（推荐）
python3 enhanced_crawler.py MacBook_Pro_17%22_Unibody
python3 enhanced_crawler.py iPhone_12
python3 enhanced_crawler.py iPad_Air_2

# 启用详细输出
python3 enhanced_crawler.py --verbose MacBook_Pro_17%22_Unibody
python3 enhanced_crawler.py -v iPhone_12

# 使用部分URL
python3 enhanced_crawler.py /Device/MacBook_Pro_17%22_Unibody

# 运行测试
python3 enhanced_crawler.py test
```

或者在Python代码中使用：
```python
from enhanced_crawler import EnhancedIFixitCrawler

# 创建爬虫实例（默认静默模式）
crawler = EnhancedIFixitCrawler()

# 创建爬虫实例（启用详细输出）
crawler = EnhancedIFixitCrawler(verbose=True)

# 爬取完整设备信息（包括指南和故障排除）
device_url = "https://www.ifixit.com/Device/iPad_3G"
result = crawler.crawl_device_with_guides_and_troubleshooting(device_url)

# 保存结果
crawler.save_enhanced_results(result)
```

**特点**：
- 提取设备基本信息、维修指南详细步骤、故障排除内容
- 自动排除Related Pages和评论区内容
- 提取图片、视频、文档等多媒体资源URL
- 支持静默模式和详细输出模式
- 自动添加语言参数，智能检测页面存在性
- 输出文件命名：`enhanced_[设备名].json`

### 方法二：交互式爬取单个产品（推荐新手使用）

使用简易爬虫工具，支持引导用户选择子类别：

```bash
# 基本用法
python3 easy_crawler.py [URL或产品名]

# 显示帮助信息
python3 easy_crawler.py -h
```

**使用示例**：
```bash
# 通过产品名爬取
python3 easy_crawler.py iPad_3G

# 通过完整URL爬取
python3 easy_crawler.py https://www.ifixit.com/Device/iPad_3G

# 交互式输入（直接运行脚本）
python3 easy_crawler.py
```

**特点**：
- 自动检测是否为最终产品页面
- 如果是类别页面，会显示子类别供用户选择
- 支持交互式输入URL或产品名
- 自动开启调试模式显示详细信息
- **输出文件命名规则**：使用URL路径最后一部分作为文件名，如`iPad_3G.json`

### 方法三：批量爬取指定类别下的所有最终产品

自动遍历指定类别下的所有子类别，只爬取最终产品页面：

```bash
# 基本用法
python3 batch_crawler.py [URL或产品名]

# 启用调试模式
python3 batch_crawler.py --debug [URL或产品名]

# 显示帮助信息
python3 batch_crawler.py -h
```

**使用示例**：
```bash
# 通过产品名爬取
python3 batch_crawler.py iPad_3G

# 通过完整URL爬取
python3 batch_crawler.py https://www.ifixit.com/Device/iPad_3G

# 启用调试模式
python3 batch_crawler.py --debug iPad_3G

# 测试多个预定义URL
python3 batch_crawler.py test

# 启用调试模式测试
python3 batch_crawler.py test --debug
```

**特点**：
- 支持搜索功能：如果直接访问产品页面失败，会自动进行搜索
- 自动去重，避免重复爬取相同产品
- 支持调试模式显示详细信息
- 添加延迟避免请求过于频繁
- **输出文件命名规则**：文件名以`batch_`开头，后跟URL路径最后一部分，如`batch_iPad_3G.json`

### 方法四：以树形结构爬取设备分类

爬取并以层级树结构保存设备分类，适合需要展示层级关系的场景。该方法会自动从React组件数据中提取完整的面包屑导航，构建准确的多层级路径：

```bash
# 基本用法
python3 tree_crawler.py [URL或设备名]

# 启用调试模式
python3 tree_crawler.py --debug [URL或设备名]

# 显示帮助信息
python3 tree_crawler.py -h
```

**使用示例**：
```bash
# 爬取电视产品类别树结构
python3 tree_crawler.py Television

# 爬取LG电视产品类别树结构（包含38个子类别）
python3 tree_crawler.py LG_Television

# 爬取苹果耳机产品类别树结构
python3 tree_crawler.py Apple_Headphone

# 爬取MacBook产品类别树结构
python3 tree_crawler.py MacBook

# 通过完整URL爬取
python3 tree_crawler.py https://www.ifixit.com/Device/Television

# 启用调试模式
python3 tree_crawler.py --debug MacBook
```

**输出文件命名规则**：文件名以`tree_`开头，后跟命令行中指定的爬取目标名称，如`tree_Apple_Headphone.json`

**树形结构爬虫特点**：
1. 精准提取网页React组件数据中的完整面包屑导航信息
2. 多层次路径发现机制，包括:
   - 从React组件数据中提取面包屑（最准确）
   - 从Schema.org元数据中提取标准化面包屑
   - 从面包屑容器DOM元素中提取
   - 从页面头部导航链接中提取
   - 从URL结构推断基本路径
3. 支持所有种类产品和类别的完整路径发现，如:
   - 电视类别: "设备 > 电子产品 > 电视 > TCL Television"
   - 耳机类别: "设备 > 电子产品 > 耳机 > Apple Headphone"
   - 笔记本类别: "设备 > Mac > 笔记本 > MacBook"
4. 智能URL路径修复，确保所有路径符合网站真实结构
5. 中英文混合路径的处理，包括中文分类名称到英文URL的智能映射
6. 严格的节点规范控制：
   - 分类节点(有子节点): 不包含instruction_url字段，字段顺序为name-url-children
   - 产品节点(叶子节点): 必须包含instruction_url字段，字段顺序为name-url-instruction_url-children
7. 自动清理和优化结构：在保存前自动检查并修复所有节点结构，确保符合规范

### 方法五：运行完整爬虫

从设备首页开始爬取整个网站：

```bash
# 基本用法
python3 crawler.py

# 启用调试模式
python3 crawler.py --debug
```

**特点**：
- 从设备首页开始递归爬取所有类别和产品
- 自动识别最终产品页面和类别页面
- 支持调试模式显示详细爬取过程
- 添加随机延迟避免对服务器造成压力
- 自动跳过无关页面（如创建指南、编辑页面等）

## 输出结果

爬虫会将所有结果保存在`results/`目录下的JSON文件中。根据使用的爬虫类型，输出格式有所不同：

### 基础爬虫输出
每条记录包含以下字段（按顺序）：
- product_name：产品名称（产品页面的标题）
- product_url：产品的完整URL地址
- instruction_url：说明书链接（如果有）

### 增强版爬虫输出
包含完整的设备信息、维修指南和故障排除内容：
- 设备基本信息（标题、描述、URL）
- 维修指南详细内容（步骤、工具、零件、图片等）
- 故障排除内容（文本、图片、视频、文档URL）
- 爬取时间戳

## 注意事项

### 通用注意事项
1. **网站URL**：所有爬虫均使用英文站点 `https://www.ifixit.com/`，不再使用中文站点
2. **URL结构**：iFixit网站的URL结构是替换而非追加路径，例如从"平板电脑"到"iPad"的URL变化是从`/Device/Tablet`到`/Device/iPad`
3. **访问频率**：为避免对服务器造成压力，爬虫添加了随机延迟（1-2秒）
4. **Robots.txt遵守**：爬虫会检查并遵守robots.txt规则，跳过被禁止的URL
5. **内容过滤**：爬虫会自动跳过"创建指南"等非产品页面，以及各种无关内容（如"翻译"、"贡献者"、"论坛问题"等）
6. **内容验证**（v2.1重要更新）：
   - **真实性保证**：爬虫只提取页面上真实存在的内容，绝不添加虚假字段
   - **字段验证**：每个字段都经过严格验证，确保对应的标题在页面上真实存在
   - **内容纯净**：自动排除作者信息、元数据、商业推广等非主要内容
   - **边界检测**：精确识别不同内容区域的边界，防止内容混合和污染
7. **输出控制**：
   - **增强版爬虫**：默认静默模式，使用 `--verbose` 或 `-v` 启用详细输出
   - **其他爬虫**：使用 `--debug` 启用调试模式
   - 所有爬虫都支持 `--help` 或 `-h` 显示帮助信息

### 基础爬虫特点
6. **产品页面识别**：只收集最终产品页面（没有子类别的页面）的信息，中间类别页面（如iPad Pro）不会被收集
7. **文本处理**：自动将产品名称中的英寸符号(")转换为"英寸"文本，使JSON输出更加美观易读
8. **说明书链接**：当产品页面没有PDF文档时，会尝试提取视频指南链接作为说明书链接

### 增强版爬虫特点
9. **智能内容验证机制**（v2.1新增）：
   - **真实性验证**：只提取页面上真实存在的内容，不添加虚假字段
   - **Introduction精确提取**：只有在页面存在"Introduction"标题时才提取introduction字段
   - **作者信息过滤**：自动识别并排除作者信息、元数据等非主要内容
   - **内容边界检测**：精确识别不同section的边界，防止内容混合
   - **动态字段识别**：根据页面实际结构动态提取字段（如first_steps、the_basics、triage等）
   - **HTML结构适配**：支持各种HTML结构的内容提取，不局限于特定的DOM结构
10. **高级去重机制**：
    - **多层次去重**：使用哈希、文本相似度、句子级别等多种去重算法
    - **内容重叠检测**：防止不同section之间的内容重复
    - **智能文本清理**：保留段落结构的同时去除多余空白和重复内容
11. **内容质量控制**：
    - 自动排除Related Pages区域内容
    - 排除评论区和社交分享等无关内容
    - 只提取Troubleshooting标题之下的内容，不包含标题之前的内容
    - 自动排除商业推广内容和购买链接
    - 过滤导航菜单、页脚等非主要内容
12. **多媒体资源提取**：
    - 图片：优先提取medium格式，过滤图标和缩略图
    - 视频：支持YouTube、Vimeo等平台的嵌入视频和链接
    - 文档：支持PDF、Word文档以及iFixit指南链接
    - 媒体内容关联：将图片和视频与对应的故障原因关联
13. **数据结构规范**：
    - 故障排除内容使用统一的字段结构：动态字段 + `causes`数组
    - 每个cause包含独立的`images`和`videos`数组
    - 移除旧版本的`problems`、`solutions`、`related_guides`字段
14. **智能数据提取**：
    - 从API获取准确的时间和难度信息
    - 提取真实的浏览量、完成数、收藏数等统计数据
    - 动态提取页面字段，适应不同页面结构
    - 支持各种HTML结构的内容提取（不仅限于直接兄弟元素）
15. **输出控制**：
    - 默认静默模式，不显示详细调试信息
    - 使用 `--verbose` 或 `-v` 启用详细输出模式
    - 详细模式显示API调用、内容提取、统计信息等调试信息

### 文件命名规则
12. **输出文件命名**：
    - `enhanced_crawler.py`：`enhanced_[设备名].json`
    - `easy_crawler.py`：`[设备名].json`（使用URL路径最后一部分）
    - `batch_crawler.py`：`batch_[设备名].json`
    - `tree_crawler.py`：`tree_[目标名称].json`

### 数据格式区别
13. **输出格式**：
    - `enhanced_crawler.py`：完整的设备信息对象，包含guides和troubleshooting数组
    - `easy_crawler.py`：单个产品对象
    - `batch_crawler.py`：产品对象数组，即使只有一个结果
    - `tree_crawler.py`：多层嵌套的树形结构

### 树形爬虫特殊说明
14. **面包屑导航提取**：tree_crawler.py使用多层次的路径发现机制，优先从网页React组件中提取最精准的面包屑数据
15. **支持的目录路径类型**：
    - 电视相关：设备 > 电子产品 > 电视 > [品牌] Television
    - 耳机相关：设备 > 电子产品 > 耳机 > [品牌] Headphone
    - 笔记本相关：设备 > Mac > 笔记本 > [品牌/型号]
    - 以及其他各种产品类别的多级路径
16. **节点类型区分**：
    - 分类节点（有子节点）：字段顺序为name、url、children，不包含instruction_url字段
    - 产品节点（叶子节点）：字段顺序为name、url、instruction_url、children，通过空的children数组表示这是产品节点

## 文件说明

- `enhanced_crawler.py` - **增强版爬虫**（推荐），支持完整内容爬取，包括设备信息、维修指南和故障排除内容
  - **v2.1新增**：智能内容验证机制，确保数据真实性和纯净度
  - **v2.1新增**：动态字段识别，适应不同页面结构
  - **v2.1新增**：高级去重算法，防止内容重复和混合
  - 支持静默模式和详细输出模式
  - 智能数据提取和API调用
  - 自动排除商业内容和推广信息
- `crawler.py` - 主爬虫代码，支持完整站点爬取
  - 递归爬取所有设备类别和产品
  - 自动识别最终产品页面
- `easy_crawler.py` - 交互式爬虫工具（推荐新手使用）
  - 支持交互式选择子类别
  - 自动检测页面类型
- `batch_crawler.py` - 批量爬取工具，针对特定类别
  - 支持搜索功能
  - 自动去重处理
- `tree_crawler.py` - 树形结构爬虫工具，具有增强的路径发现功能，将设备分类以完整的多层级树结构保存
  - 多层次路径发现机制
  - 智能面包屑导航提取

## 推荐使用方式

1. **完整内容爬取**：使用 `enhanced_crawler.py` 获取设备的完整信息，包括维修指南和故障排除内容
   - **v2.1优势**：智能内容验证，确保提取的数据真实可靠，无虚假字段
   - 日常使用：`python3 enhanced_crawler.py MacBook_Pro_17%22_Unibody`
   - 调试模式：`python3 enhanced_crawler.py --verbose MacBook_Pro_17%22_Unibody`
2. **快速产品信息**：使用 `easy_crawler.py` 快速获取单个产品的基本信息
   - 适合新手和交互式使用
3. **批量处理**：使用 `batch_crawler.py` 批量处理特定类别下的所有产品
   - 适合大量数据收集
4. **结构分析**：使用 `tree_crawler.py` 分析和保存设备分类的层级结构
   - 适合分析网站结构和分类关系

## 命令行选项总览

| 爬虫文件 | 基本用法 | 调试选项 | 帮助选项 | 特殊功能 |
|---------|---------|---------|---------|---------|
| `enhanced_crawler.py` | `python3 enhanced_crawler.py [URL/产品名]` | `--verbose`, `-v` | `--help`, `-h` | `test` |
| `easy_crawler.py` | `python3 easy_crawler.py [URL/产品名]` | 默认开启 | `-h` | 交互式输入 |
| `batch_crawler.py` | `python3 batch_crawler.py [URL/产品名]` | `--debug` | `-h` | `test` |
| `tree_crawler.py` | `python3 tree_crawler.py [URL/设备名]` | `--debug` | `-h` | - |
| `crawler.py` | `python3 crawler.py` | `--debug` | - | - |

## 输出控制说明

### 增强版爬虫输出模式

**静默模式（默认）**：
```bash
python3 enhanced_crawler.py MacBook_Pro_17%22_Unibody
# 输出：只显示基本进度信息，无详细调试信息
```

**详细输出模式**：
```bash
python3 enhanced_crawler.py --verbose MacBook_Pro_17%22_Unibody
# 输出：显示完整的调试信息，包括：
# - API调用详情
# - 内容提取过程
# - 图片和视频提取统计
# - 完成统计信息
```

### 其他爬虫调试模式

**批量爬虫调试**：
```bash
python3 batch_crawler.py --debug iPad_3G
# 显示每个产品的详细爬取过程
```

**树形爬虫调试**：
```bash
python3 tree_crawler.py --debug MacBook
# 显示路径发现和树结构构建过程
```

### 输出信息对比

| 模式 | API调用信息 | 内容提取详情 | 统计信息 | 完成提示 |
|------|------------|-------------|---------|---------|
| 静默模式 | ❌ | ❌ | ❌ | ❌ |
| 详细模式 | ✅ | ✅ | ✅ | ✅ |
| 调试模式 | ✅ | ✅ | ✅ | ✅ |

## 最近更新

### v2.1 - 内容验证与质量控制重大升级
- **智能内容验证**：只提取页面上真实存在的内容，杜绝虚假字段
- **Introduction精确提取**：修复Introduction内容提取逻辑，支持各种HTML结构
- **作者信息过滤**：自动识别并排除作者信息、元数据等非主要内容
- **动态字段识别**：根据页面实际结构动态提取字段（introduction、first_steps、the_basics、triage等）
- **高级去重机制**：多层次去重算法，防止内容重复和混合
- **内容边界检测**：精确识别不同section边界，确保数据纯净
- **媒体内容关联**：将图片和视频与对应的故障原因关联

### v2.0 - 输出控制优化
- **增强版爬虫**：新增静默模式和详细输出模式控制
- **命令行选项**：统一所有爬虫的命令行参数格式
- **智能URL处理**：自动添加语言参数，智能检测页面存在性
- **API数据提取**：从iFixit API获取准确的时间、难度和统计信息
- **内容质量提升**：更好的商业内容过滤和重复内容去除

### v1.5 - 功能完善
- **故障排除优化**：精确的边界检测，避免提取无关内容
- **多媒体资源**：完善的图片、视频、文档URL提取
- **数据结构规范**：统一的JSON输出格式和字段顺序
- **路径发现增强**：多层次面包屑导航提取机制

### v1.0 - 基础功能
- **多模式爬取**：支持单个、批量、树形、增强版等多种爬取模式
- **智能分层**：自动区分产品页面和类别页面
- **内容过滤**：排除无关页面和内容
- **数据提取**：基础的产品信息和说明书链接提取

## 技术特点

- **语言**：Python 3.x
- **主要依赖**：requests, beautifulsoup4, urllib3
- **数据格式**：JSON
- **编码**：UTF-8
- **网站兼容**：iFixit英文站点 (www.ifixit.com)
- **Robots.txt**：完全遵守网站爬取规则

## 贡献指南

欢迎提交Issue和Pull Request来改进这个项目：

1. **Bug报告**：请详细描述问题和复现步骤
2. **功能建议**：请说明新功能的用途和实现思路
3. **代码贡献**：请遵循现有的代码风格和注释规范
4. **文档更新**：帮助完善README和代码注释

## 许可证

本项目仅供学习和研究使用，请遵守iFixit网站的使用条款和robots.txt规则。
 