# iFixit 整合爬虫工具

一个功能强大的 iFixit 网站整合爬虫工具，结合树形结构和详细内容提取，支持代理池、本地存储、媒体下载等企业级功能。

## 🚀 核心特性

- **🌳 树形结构 + 详细内容**：完整的设备分类层级结构 + 深度内容提取
- **🔄 智能代理池**：天启IP代理自动切换，避免IP封禁
- **📁 本地文件存储**：层级文件夹结构，自动下载媒体文件
- **🚀 多线程并发**：指南和故障排除内容并发处理，提升效率
- **🎥 智能视频处理**：可选择性下载视频文件，支持大小限制
- **💾 智能缓存机制**：自动跳过已爬取内容，支持强制刷新
- **🔁 错误重试机制**：网络错误自动重试，指数退避策略
- **📊 详细性能统计**：实时显示爬取进度和性能指标

## 📁 项目结构

```
iFixit爬虫/
├── auto_crawler.py          # 🌟 主要工具：整合爬虫（推荐使用）
├── enhanced_crawler.py      # 详细内容爬虫（基础组件）
├── tree_crawler.py          # 树形结构爬虫（基础组件）
├── combined_crawler.py      # 基础整合爬虫（参考实现）
├── proxy.txt               # 代理配置文件
├── requirements.txt         # 依赖包列表
├── robots.txt              # 爬虫规则
└── ifixit_data/            # 爬取结果目录
    ├── media/              # 媒体文件存储
    └── [产品名]/           # 按产品分类的数据文件
```

## 🛠️ 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置代理（可选）

创建 `proxy.txt` 文件，每行一个代理地址：
```
proxy1.example.com:8080
proxy2.example.com:8080
```

### 3. 基本使用

```bash
# 最简单的使用方式
python auto_crawler.py iMac_M_Series

# 查看帮助信息
python auto_crawler.py --help
```

### 主要依赖
- `requests` - HTTP请求处理
- `beautifulsoup4` - HTML解析
- `urllib3` - 连接池和重试机制
- `pathlib` - 文件路径处理

## 📖 详细使用指南

### 基本语法

```bash
python auto_crawler.py [目标] [选项...]
```

### 🎯 目标参数

支持多种输入格式：

```bash
# 产品名称
python auto_crawler.py iMac_M_Series
python auto_crawler.py Television

# 完整URL
python auto_crawler.py https://www.ifixit.com/Device/iPhone

# 部分URL
python auto_crawler.py /Device/MacBook_Pro
```

### ⚙️ 常用选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--verbose` | 启用详细输出 | 否 |
| `--no-proxy` | 关闭代理池 | 启用代理 |
| `--no-cache` | 禁用缓存检查 | 启用缓存 |
| `--force-refresh` | 强制重新爬取 | 否 |
| `--workers N` | 并发线程数 | 4 |
| `--max-retries N` | 最大重试次数 | 5 |

### 🎥 视频处理选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--download-videos` | 启用视频文件下载 | 禁用 |
| `--max-video-size N` | 视频大小限制(MB) | 50 |

### 📝 使用示例

#### 基本爬取（推荐）
```bash
# 快速爬取，不下载视频
python auto_crawler.py iMac_M_Series

# 禁用代理，启用详细输出
python auto_crawler.py Television --no-proxy --verbose
```

#### 完整内容爬取
```bash
# 启用视频下载，限制10MB
python auto_crawler.py iPhone --download-videos --max-video-size 10

# 强制刷新，获取最新数据
python auto_crawler.py MacBook --force-refresh
```

#### 性能调优
```bash
# 增加并发数，适合网络良好的环境
python auto_crawler.py iPad --workers 8

# 减少重试次数，快速失败
python auto_crawler.py Television --max-retries 2

# 禁用缓存，确保数据最新
python auto_crawler.py iPhone --no-cache
```

#### 调试模式
```bash
# 详细输出，便于调试
python auto_crawler.py iMac_M_Series --verbose --no-proxy

# 查看帮助信息
python auto_crawler.py --help
```

## 📊 输出结果

### 📁 文件结构

爬取完成后，会在 `ifixit_data/` 目录下生成以下结构：

```
ifixit_data/
├── media/                          # 媒体文件存储
│   ├── images/                     # 图片文件
│   └── videos/                     # 视频文件（如果启用下载）
└── auto_[产品名]_[时间戳].json      # 爬取数据文件
```

### 📄 JSON数据结构

```json
{
  "name": "iMac_M_Series",
  "url": "https://www.ifixit.com/Device/iMac_M_Series",
  "title": "iMac (Apple silicon) Repair",
  "instruction_url": "",
  "view_statistics": {
    "past_24_hours": "20",
    "past_7_days": "182",
    "past_30_days": "723",
    "all_time": "54,046"
  },
  "completed": "1,234",
  "favorites": "567",
  "guides": [
    {
      "title": "iMac M1 24\" Teardown",
      "url": "https://www.ifixit.com/Guide/...",
      "difficulty": "Moderate",
      "time_required": "45 minutes - 1 hour",
      "introduction": {
        "text": "This guide will show you...",
        "tools": ["Spudger", "Suction Handle"],
        "parts": ["Display Assembly"]
      },
      "steps": [
        {
          "title": "Remove the Stand",
          "content": "Step instructions...",
          "images": ["./media/images/step1_image1.jpg"],
          "videos": ["./media/videos/step1_video.mp4"]
        }
      ]
    }
  ],
  "troubleshooting": [
    {
      "title": "iMac Won't Turn On",
      "url": "https://www.ifixit.com/Answers/...",
      "causes": [
        {
          "title": "Power Supply Issue",
          "content": "Check the power connection...",
          "images": ["./media/images/power_check.jpg"]
        }
      ]
    }
  ],
  "children": [
    {
      "name": "iMac_M1_24\"",
      "url": "https://www.ifixit.com/Device/iMac_M1_24%22",
      "guides": [...],
      "troubleshooting": [...]
    }
  ]
}
```


## 🔧 核心功能详解

### 🌳 树形结构 + 详细内容

- **完整层级结构**：基于真实面包屑导航构建设备分类树
- **深度内容提取**：每个节点包含完整的指南和故障排除内容
- **智能节点识别**：自动区分产品节点和分类节点

### 🔄 智能代理池

- **文件配置**：从 `proxy.txt` 读取代理列表
- **自动切换**：网络错误时自动切换代理
- **认证支持**：支持用户名密码认证
- **失败标记**：记录失败的代理，避免重复使用

### 🚀 多线程并发

- **指南并发处理**：多个指南页面同时爬取
- **故障排除并发**：多个故障排除页面同时处理
- **智能调度**：根据任务数量自动选择单线程或多线程
- **线程安全**：确保文件操作和统计数据的线程安全

### 🎥 智能视频处理

- **可选下载**：通过 `--download-videos` 控制是否下载视频
- **大小限制**：通过 `--max-video-size` 限制视频文件大小
- **格式支持**：支持 .mp4, .mov, .avi, .webm, .mkv, .flv 等格式
- **智能跳过**：超过大小限制的视频自动跳过，保留原始URL

### 💾 智能缓存机制

- **文件缓存**：基于文件修改时间的缓存检查
- **强制刷新**：`--force-refresh` 忽略所有缓存
- **缓存统计**：详细的缓存命中率统计

### 🔁 错误重试机制

- **指数退避**：重试间隔逐渐增加
- **最大重试**：可配置的最大重试次数
- **错误分类**：区分临时错误和永久错误
- **失败记录**：记录失败的URL到日志文件

## 📈 性能统计

爬取完成后会显示详细的性能统计信息：

```
📊 性能统计报告
============================================================
🌐 总请求数: 16
💾 缓存命中: 0 (0.0%)
🔄 缓存未命中: 8
📁 媒体下载成功: 73/73 (100.0%)
📁 媒体下载失败: 0
🎥 视频文件处理:
   ✅ 已下载: 0
   ⏭️ 已跳过: 5
   💡 提示: 视频下载已禁用，如需下载请设置 download_videos=True
🔄 代理切换次数: 3
============================================================
```

## 🚨 注意事项

### 使用规范
1. **遵守robots.txt**：自动检查并遵守网站的爬虫规则
2. **请求频率控制**：内置请求间隔，避免对服务器造成压力
3. **数据使用合规**：请合理使用爬取的数据，遵守相关法律法规
4. **网络环境**：建议在稳定的网络环境下运行

### 存储空间管理
1. **视频文件**：视频文件通常很大，建议根据需要启用下载
2. **媒体文件**：图片文件会自动下载到本地，注意磁盘空间
3. **缓存文件**：定期清理过期的缓存文件

## 🐛 故障排除

### 常见错误及解决方案

#### 1. SSL连接错误
```
SSLEOFError: EOF occurred in violation of protocol
```
**解决方案**：
- 网络不稳定导致，系统会自动重试
- 如果频繁出现，可以降低并发数：`--workers 2`

#### 2. 代理连接失败
```
ProxyError: Cannot connect to proxy
```
**解决方案**：
- 检查 `proxy.txt` 文件中的代理地址是否正确
- 或者使用 `--no-proxy` 禁用代理

#### 3. 内存不足
```
MemoryError: Unable to allocate memory
```
**解决方案**：
- 禁用视频下载：不使用 `--download-videos`
- 降低并发数：`--workers 2`
- 分批处理大型数据集

#### 4. 权限错误
```
PermissionError: Access denied
```
**解决方案**：
- 确保有写入 `ifixit_data/` 目录的权限
- 检查磁盘空间是否充足

### 调试技巧

```bash
# 详细输出模式，显示所有处理步骤
python auto_crawler.py iMac_M_Series --verbose

# 禁用代理，避免网络问题
python auto_crawler.py iMac_M_Series --no-proxy

# 强制刷新，确保获取最新数据
python auto_crawler.py iMac_M_Series --force-refresh

# 单线程模式，便于调试
python auto_crawler.py iMac_M_Series --workers 1
```

## 🎯 最佳实践

### 推荐配置

#### 快速爬取（日常使用）
```bash
python auto_crawler.py [目标] --no-proxy
```
- 禁用代理，提升速度
- 不下载视频，节省空间
- 使用缓存，避免重复爬取

#### 完整内容爬取（研究用途）
```bash
python auto_crawler.py [目标] --download-videos --max-video-size 50
```
- 下载视频文件，获取完整内容
- 限制视频大小，避免过大文件
- 适合深度研究和分析

#### 大规模爬取（批量处理）
```bash
python auto_crawler.py [目标] --workers 8 --max-retries 3
```
- 增加并发数，提升效率
- 适当减少重试次数，快速失败
- 适合处理大量数据

#### 调试模式（开发测试）
```bash
python auto_crawler.py [目标] --verbose --no-proxy --force-refresh
```
- 详细输出，便于调试
- 禁用代理，避免网络问题
- 强制刷新，确保数据最新

### 性能优化建议

1. **网络优化**：
   - 稳定网络环境下可增加 `--workers` 数量
   - 网络不稳定时建议使用代理池
   - 海外服务器建议启用代理

2. **存储优化**：
   - 大规模爬取时禁用视频下载
   - 定期清理 `ifixit_data/media/` 目录
   - 使用SSD存储提升I/O性能

3. **内存优化**：
   - 大型数据集建议降低并发数
   - 及时清理不需要的缓存文件
   - 监控内存使用情况

## 📄 许可证

本项目仅供学习和研究使用，请遵守相关法律法规和网站使用条款。

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个项目。

---

## 🌟 特色功能总结

- **🎯 一键爬取**：简单命令即可获取完整设备信息
- **🌳 完整结构**：树形层级 + 详细内容，数据完整性最佳
- **🚀 高性能**：多线程并发，智能缓存，错误重试
- **🎥 智能媒体**：可选视频下载，大小限制，本地存储
- **🔄 企业级**：代理池，性能统计，错误处理
- **💡 易用性**：丰富的命令行选项，详细的帮助信息

**立即开始使用 `auto_crawler.py` 体验强大的iFixit数据爬取功能！**
