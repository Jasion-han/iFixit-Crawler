# iFixit 爬虫工具集

一个功能强大的 iFixit 网站爬虫工具集，支持多种爬取模式和企业级功能。

## 🚀 功能特性

- **多种爬取模式**：支持简单爬取、树形结构爬取、详细内容爬取和整合爬取
- **企业级功能**：代理池、MySQL存储、失败重试、异步处理
- **完整数据提取**：产品信息、维修指南、故障排除、统计数据等
- **智能路径识别**：基于页面面包屑导航构建真实路径结构
- **反爬虫策略**：请求间隔、浏览器模拟、User-Agent轮换

## 📁 项目结构

```
iFixit爬虫/
├── auto_crawler.py          # 企业级整合爬虫（推荐）
├── combined_crawler.py      # 基础整合爬虫
├── enhanced_crawler.py      # 详细内容爬虫
├── tree_crawler.py          # 树形结构爬虫
├── batch_crawler.py         # 批量爬取工具
├── easy_crawler.py          # 简易爬虫
├── crawler.py               # 基础爬虫类
├── requirements.txt         # 依赖包列表
├── robots.txt              # 爬虫规则
└── results/                # 爬取结果目录
```

## 🛠️ 安装依赖

```bash
pip install -r requirements.txt
```

### 主要依赖
- `requests` - HTTP请求
- `beautifulsoup4` - HTML解析
- `playwright` - 浏览器自动化
- `pymysql` - MySQL数据库连接
- `aiohttp` - 异步HTTP请求

## 📖 使用指南

### 1. 企业级整合爬虫（推荐）

**auto_crawler.py** - 功能最全面的爬虫，支持代理池和数据库存储

```bash
# 基本使用
python auto_crawler.py "iMac M Series"
python auto_crawler.py "https://www.ifixit.com/Device/Television"

# 交互式使用
python auto_crawler.py
```

**特性：**
- ✅ 树形结构 + 详细内容提取
- ✅ 代理池支持
- ✅ MySQL数据库存储
- ✅ 失败重试机制
- ✅ 异步处理
- ✅ 完整的指南和故障排除内容

### 2. 基础整合爬虫

**combined_crawler.py** - 结合树形结构和详细内容提取

```bash
python combined_crawler.py "MacBook Pro"
python combined_crawler.py "https://www.ifixit.com/Device/Mac"
```

**特性：**
- ✅ 树形结构展示
- ✅ 详细内容提取
- ✅ JSON文件输出
- ❌ 无代理池
- ❌ 无数据库存储

### 3. 详细内容爬虫

**enhanced_crawler.py** - 专注于提取详细的维修指南和故障排除内容

```bash
python enhanced_crawler.py "https://www.ifixit.com/Device/iPad"
```

**特性：**
- ✅ 完整指南内容（步骤、工具、配件）
- ✅ 故障排除页面
- ✅ 统计数据（浏览量、完成数等）
- ✅ 媒体文件链接（图片、视频）

### 4. 树形结构爬虫

**tree_crawler.py** - 构建设备分类的层级树形结构

```bash
python tree_crawler.py "Television"
python tree_crawler.py "https://www.ifixit.com/Device/Mac"
```

**特性：**
- ✅ 完整的分类层级结构
- ✅ 基于真实面包屑导航
- ✅ 产品和分类区分
- ❌ 无详细内容

### 5. 简易爬虫

**easy_crawler.py** - 快速获取单个产品基本信息

```bash
python easy_crawler.py "iPad_3G"
python easy_crawler.py "https://www.ifixit.com/Device/iPad_3G"
```

### 6. 批量爬取工具

**batch_crawler.py** - 批量处理多个URL或进行测试

```bash
python batch_crawler.py "test"  # 运行测试用例
python batch_crawler.py "iPad"  # 批量搜索
```

## 📊 输出格式

### JSON结构示例

```json
{
  "name": "iMac_M_Series",
  "url": "https://www.ifixit.com/Device/iMac_M_Series",
  "title": "iMac (Apple silicon) Repair",
  "view_statistics": {
    "past_24_hours": "20",
    "past_7_days": "182",
    "past_30_days": "723",
    "all_time": "54,046"
  },
  "guides": [
    {
      "title": "iMac M1 24\" Display Replacement",
      "url": "https://www.ifixit.com/Guide/...",
      "introduction": {
        "text": "Guide content...",
        "tools": ["Spudger", "Suction Handle"],
        "parts": ["Display Assembly"]
      },
      "steps": [...]
    }
  ],
  "troubleshooting": [
    {
      "title": "iMac Won't Turn On",
      "url": "https://www.ifixit.com/Answers/...",
      "causes": [...]
    }
  ]
}
```


## 🔧 高级功能

### 1. 企业级特性（auto_crawler.py）

- **代理池轮换**：避免IP封禁
- **数据库存储**：支持MySQL持久化
- **失败重试**：自动重试失败的请求
- **进度跟踪**：实时显示爬取进度
- **数据去重**：避免重复爬取

### 2. 反爬虫策略

- 遵循 robots.txt 规则
- 随机请求间隔（1-3秒）
- User-Agent 轮换
- 浏览器模拟（Playwright）
- 请求重试机制

### 3. 数据完整性

- 提取真实页面数据（非模拟）
- 基于面包屑导航的路径构建
- 完整的媒体文件链接
- 统计数据验证

## 📈 性能优化

- **异步处理**：支持并发请求
- **连接池**：复用HTTP连接
- **缓存机制**：避免重复请求
- **内存优化**：大数据集分批处理

## 🚨 注意事项

1. **遵守robots.txt**：所有爬虫都会检查并遵守网站的爬虫规则
2. **请求频率**：内置请求间隔，避免对服务器造成压力
3. **数据使用**：请合理使用爬取的数据，遵守相关法律法规
4. **网络环境**：建议在稳定的网络环境下运行

## 🐛 故障排除

### 常见问题

1. **连接超时**：检查网络连接，考虑使用代理
2. **数据不完整**：确保目标页面可正常访问
3. **内存不足**：对于大型数据集，使用数据库存储模式

### 调试模式

```bash
# 开启详细输出
python auto_crawler.py --verbose
```

## 📄 许可证

本项目仅供学习和研究使用，请遵守相关法律法规和网站使用条款。

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个项目。

---

**推荐使用 `auto_crawler.py` 获得最佳体验！**
