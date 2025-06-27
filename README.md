# iFixit爬虫

该爬虫用于爬取[iFixit中文网站](https://zh.ifixit.com/)上的产品信息，包括产品名称、产品URL和说明书链接。

## 功能特点

1. 从设备类别页面出发，递归爬取所有设备子类别
2. 只收集无子类别的最终产品页面信息
3. 自动处理URL结构（URL结构是替换而非追加）
4. 过滤非设备页面（如编辑、历史等页面）
5. 支持调试模式，便于观察爬取过程
6. 提取产品的完整URL地址
7. 准确获取最终产品页面的标题（如"iPad 3G Repair"）
8. 专门提取"文档"栏目下的PDF文档链接
9. 当没有PDF文档时，提取视频指南链接作为说明书链接
10. 支持交互式引导用户选择子类别
11. 支持批量爬取指定类别下的所有最终产品
12. 自动将产品名称中的英寸符号(")转换为"英寸"文本，避免JSON转义问题
13. 支持通过完整URL或产品名两种方式爬取数据
14. 文件命名规则：根据命令行参数自动生成，以"tree_"加参数名称命名
15. 支持以多层级树形结构方式爬取和保存设备信息
16. 精准提取网页React组件数据中的完整面包屑导航信息
17. 支持所有种类产品和类别的完整路径发现（如耳机、电视、笔记本等）
18. 智能URL路径修复，确保生成的路径匹配网站真实结构
19. 多层次路径发现机制，通过多种方式保证找到正确的层级关系
20. 支持中英文混合路径的正确处理（如"设备 > 电子产品 > 耳机 > Apple Headphone"）
21. 严格的字段规范：分类节点不包含instruction_url字段，只有产品节点（叶子节点）包含此字段
22. 标准化的字段顺序：产品节点遵循name-url-instruction_url-children顺序，分类节点遵循name-url-children顺序

## 爬取结果格式

### 使用easy_crawler.py的结果格式（单个对象）

```json
{
  "product_name": "iPad Pro 12.9英寸 Repair",                          // 产品名称（英寸符号已统一处理）
  "product_url": "https://zh.ifixit.com/Device/iPad_Pro_12.9%22",      // 产品完整URL
  "instruction_url": "https://zh.ifixit.com/Document/.../ipad_w_3g.pdf" // 说明书链接（PDF文档或视频链接）
}
```

### 使用batch_crawler.py的结果格式（数组包裹）

```json
[
  {
    "product_name": "iPad Pro 12.9英寸 Repair",                          // 产品名称（英寸符号已统一处理）
    "product_url": "https://zh.ifixit.com/Device/iPad_Pro_12.9%22",      // 产品完整URL
    "instruction_url": "https://zh.ifixit.com/Document/.../ipad_w_3g.pdf" // 说明书链接（PDF文档或视频链接）
  }
]
```

### 使用tree_crawler.py的结果格式（树形结构）

```json
{
  "name": "设备",                                    // 设备类别名称
  "url": "https://zh.ifixit.com/Device",            // 类别URL
  "children": [                                      // 子类别或产品列表
    {
      "name": "电子产品",                             // 子类别名称
      "url": "https://zh.ifixit.com/Device/Electronics", // 子类别URL
      "children": [                                  // 再下一级子类别或产品
        {
          "name": "电视",                             // 子类别名称
          "url": "https://zh.ifixit.com/Device/Television", // 子类别URL
          "children": [                              // 再下一级子类别或产品
            {
              "name": "LG Television",               // 子类别名称
              "url": "https://zh.ifixit.com/Device/LG_Television", // 子类别URL
              "children": [                          // 再下一级子类别或产品
                {
                  "name": "LG (70UK6570PUB) Repair", // 产品名称
                  "url": "https://zh.ifixit.com/Device/70UK6570PUB", // 产品URL
                  "instruction_url": "https://zh.ifixit.com/Document/.../manual.pdf", // 说明书链接
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

### 方法一：交互式爬取单个产品（推荐新手使用）

使用简易爬虫工具，支持引导用户选择子类别：

```bash
python easy_crawler.py [URL或产品名]
```

示例：
```bash
# 通过产品名爬取
python easy_crawler.py iPad_3G

# 通过完整URL爬取
python easy_crawler.py https://zh.ifixit.com/Device/iPad_3G
```

**输出文件命名规则**：使用URL路径最后一部分作为文件名，如`iPad_3G.json`

### 方法二：批量爬取指定类别下的所有最终产品

自动遍历指定类别下的所有子类别，只爬取最终产品页面：

```bash
python batch_crawler.py [URL或产品名]
```

示例：
```bash
# 通过产品名爬取
python batch_crawler.py iPad_3G

# 通过完整URL爬取
python batch_crawler.py https://zh.ifixit.com/Device/iPad_3G
```

或者使用test参数测试多个预定义URL：
```bash
python batch_crawler.py test
```

**输出文件命名规则**：文件名以`batch_`开头，后跟URL路径最后一部分，如`batch_iPad_3G.json`

### 方法三：以树形结构爬取设备分类

爬取并以层级树结构保存设备分类，适合需要展示层级关系的场景。该方法会自动从React组件数据中提取完整的面包屑导航，构建准确的多层级路径：

```bash
python tree_crawler.py [URL或设备名]
```

示例：
```bash
# 爬取电视产品类别树结构
python tree_crawler.py Television

# 爬取LG电视产品类别树结构（包含38个子类别）
python tree_crawler.py LG_Television

# 爬取苹果耳机产品类别树结构
python tree_crawler.py Apple_Headphone

# 爬取MacBook产品类别树结构
python tree_crawler.py MacBook

# 通过完整URL爬取
python tree_crawler.py https://zh.ifixit.com/Device/Television
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

### 方法四：运行完整爬虫

从设备首页开始爬取整个网站：

```bash
python crawler.py
```

## 输出结果

爬虫会将所有结果保存在`results/`目录下的JSON文件中，每条记录包含以下字段（按顺序）：
- product_name：产品名称（产品页面的标题）
- product_url：产品的完整URL地址
- instruction_url：说明书链接（如果有）

## 注意事项

1. URL结构：iFixit网站的URL结构是替换而非追加路径，例如从"平板电脑"到"iPad"的URL变化是从`/Device/Tablet`到`/Device/iPad`
2. 为避免对服务器造成压力，爬虫添加了随机延迟
3. 爬虫只收集最终产品页面（没有子类别的页面）的信息，中间类别页面（如iPad Pro）不会被收集
4. 爬虫会自动跳过"创建指南"等非产品页面，以及各种无关内容（如"翻译"、"贡献者"、"论坛问题"等）
5. 爬虫会自动将产品名称中的英寸符号(")转换为"英寸"文本，使JSON输出更加美观易读
6. 当产品页面没有PDF文档时，爬虫会尝试提取视频指南链接作为说明书链接
7. 输出结果中，字段顺序为：产品名称、产品URL、说明书链接
8. 文件命名规则：
   - easy_crawler.py生成的文件名：使用URL路径最后一部分，如`iPad_3G.json`
   - batch_crawler.py生成的文件名：以`batch_`开头，后跟URL路径最后一部分，如`batch_iPad_3G.json`
   - tree_crawler.py生成的文件名：以`tree_`开头，后跟命令行参数中指定的爬取目标名称，如`tree_Apple_Headphone.json`
9. 数据格式区别：
   - easy_crawler.py生成的JSON文件为单个对象
   - batch_crawler.py生成的JSON文件为数组包裹的对象，即使只有一个结果
   - tree_crawler.py生成的JSON文件为多层嵌套的树形结构，其中：
     - 分类节点（有子节点的节点）字段顺序为name、url、children，不包含instruction_url字段
     - 产品节点（叶子节点，无子分类）字段顺序为name、url、instruction_url、children，通过空的children数组表示这是产品节点
10. 面包屑导航提取：tree_crawler.py使用多层次的路径发现机制，优先从网页React组件中提取最精准的面包屑数据
11. 支持的目录路径类型：
    - 电视相关：设备 > 电子产品 > 电视 > [品牌] Television
    - 耳机相关：设备 > 电子产品 > 耳机 > [品牌] Headphone
    - 笔记本相关：设备 > Mac > 笔记本 > [品牌/型号]
    - 以及其他各种产品类别的多级路径

## 文件说明

- `crawler.py` - 主爬虫代码，支持完整站点爬取
- `easy_crawler.py` - 交互式爬虫工具（推荐新手使用）
- `batch_crawler.py` - 批量爬取工具，针对特定类别
- `tree_crawler.py` - 树形结构爬虫工具，具有增强的路径发现功能，将设备分类以完整的多层级树结构保存
 