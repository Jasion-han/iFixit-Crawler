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
14. 文件命名规则统一：使用URL路径最后一部分作为文件名

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

### 方法三：运行完整爬虫

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
4. 爬虫会自动跳过"创建指南"等非产品页面
5. 爬虫会自动将产品名称中的英寸符号(")转换为"英寸"文本，使JSON输出更加美观易读
6. 当产品页面没有PDF文档时，爬虫会尝试提取视频指南链接作为说明书链接，特别是对于如Golf Cart等有维护视频的产品
7. 输出结果中，字段顺序为：产品名称、产品URL、说明书链接
8. 文件命名规则：
   - easy_crawler.py生成的文件名：使用URL路径最后一部分，如`iPad_3G.json`
   - batch_crawler.py生成的文件名：以`batch_`开头，后跟URL路径最后一部分，如`batch_iPad_3G.json`
9. 数据格式区别：
   - easy_crawler.py生成的JSON文件为单个对象
   - batch_crawler.py生成的JSON文件为数组包裹的对象，即使只有一个结果

## 文件说明

- `crawler.py` - 主爬虫代码，支持完整站点爬取
- `easy_crawler.py` - 交互式爬虫工具（推荐新手使用）
- `batch_crawler.py` - 批量爬取工具，针对特定类别
 