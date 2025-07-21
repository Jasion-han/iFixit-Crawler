# iFixit 高性能爬虫工具

一个企业级的 iFixit 网站高性能爬虫工具，**默认启用8线程并发+隧道代理池**，结合智能缓存、断点续爬和媒体下载，提供极致的爬取体验。

## 🚀 核心特性

### 🔥 高性能架构
- **⚡ 默认高并发**：8线程并发 + 80连接池，性能翻倍提升
- **🌐 智能代理池**：HTTP隧道代理池，每次请求自动切换IP，避免封禁
- **📊 预设模式**：快速/稳定/企业三种一键配置，适应不同场景
- **🎯 智能调优**：20+性能参数，支持从4线程到20+线程的灵活配置

### 🌳 内容提取
- **🌳 完整结构**：设备分类层级结构 + 深度内容提取
- **📁 灵活存储**：支持本地存储和阿里云服务器部署，通过环境变量配置
- **🎥 媒体处理**：智能视频下载，支持大小限制和格式过滤
- **🖼️ 图片优化**：跨页面去重，精准过滤，节省存储空间

### 💾 智能系统
- **🧠 智能缓存**：长期保存到本地文件，自动跳过已爬取内容
- **🔄 断点续爬**：自动记录树构建进度，支持中断恢复
- **🔁 错误重试**：指数退避策略，网络错误自动恢复
- **📊 实时统计**：详细性能指标，爬取进度可视化
- **🔧 故障排除**：智能去重处理，避免重复收集
- **🔍 智能检测**：自动检测缺失文件和目录，精准补全数据

### 🛠️ 完整工具链
- **🌟 主力工具**：`auto_crawler.py` - 一站式高性能爬虫解决方案
- **🔧 调试工具**：状态检查、实时监控
- **📦 批处理**：批量爬取、自动化处理、企业级部署
- **🧪 测试工具**：文件名生成测试、开发调试
- **📋 辅助工具**：简易爬虫、基础组件、开发参考

## 📁 项目结构

```
iFixit爬虫/
├── 🌟 主要爬虫工具
│   ├── auto_crawler.py                    # 🌟 高性能整合爬虫（推荐使用）
│   ├── enhanced_crawler.py               # 详细内容爬虫（基础组件）
│   ├── tree_crawler.py                   # 树形结构爬虫（基础组件）
│   ├── tree_building_progress.py         # 断点续爬进度管理
│   ├── combined_crawler.py               # 基础整合爬虫（参考实现）
│   └── crawler.py                        # 原始爬虫基础类
├── 🔧 调试和检查工具
│   └── check_crawler_status.py           # 爬虫状态检查工具
├── 📦 批处理和辅助工具
│   ├── batch_crawler.py                  # 批量爬虫工具
│   └── easy_crawler.py                   # 简易爬虫工具
├── 📋 配置和部署文件
│   ├── intro.txt                         # 隧道代理使用说明
│   ├── requirements.txt                  # 依赖包列表
│   ├── robots.txt                        # 爬虫规则
│   ├── ifixit_crawler.sh                 # 自动化部署脚本
│   └── 阿里云部署说明.md                  # 阿里云服务器部署指南
├── 🧪 测试和开发工具
│   └── test_filename_generation.py       # 文件名生成测试工具
└── 📁 数据目录（默认，可通过环境变量配置）
    └── ifixit_data/                      # 爬取结果目录
        ├── cache_index.json              # 缓存索引文件
        ├── tree_progress_*.json          # 树构建进度文件
        └── Device/                       # 按设备层级结构存储
            └── [产品路径]/               # 完整的产品分类路径
                ├── info.json             # 产品基本信息
                ├── guides/               # 指南目录
                │   ├── guide_*/          # 指南子目录（新格式）
                │   │   ├── guide.json    # 指南详细内容
                │   │   └── media/        # 指南相关媒体文件
                │   └── guide_*.json      # 指南文件（旧格式兼容）
                ├── troubleshooting/      # 故障排除目录
                │   ├── troubleshooting_*/ # 故障排除子目录
                │   │   ├── troubleshooting.json # 故障排除内容
                │   │   └── media/        # 故障排除相关媒体文件
                │   └── troubleshooting_cache.json # 故障排除缓存
                └── media/                # 通用媒体文件目录
```

## 🛠️ 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 数据存储配置

#### 本地开发（默认）
```bash
# 数据保存到当前目录的 ifixit_data/ 文件夹
python auto_crawler.py iPhone
```

#### 阿里云服务器部署
```bash
# 设置环境变量，数据直接保存到 /home/data 目录
export IFIXIT_DATA_DIR="/home/data"
python auto_crawler.py iPhone

# 或者永久设置
echo 'export IFIXIT_DATA_DIR="/home/data"' >> ~/.bashrc
source ~/.bashrc
```

#### 自定义存储路径
```bash
# 保存到任意指定目录
export IFIXIT_DATA_DIR="/path/to/your/data"
python auto_crawler.py iPhone
```

### 3. 立即开始（推荐）

```bash
# 🚀 默认高性能模式（8线程+代理池）
python auto_crawler.py iPhone

# ⚡ 快速模式（12线程+爆发模式）
python auto_crawler.py iPhone --fast

# 🏢 企业模式（16线程+超高并发）
python auto_crawler.py MacBook --enterprise

# 🛡️ 稳定模式（适合网络不稳定）
python auto_crawler.py iPad --stable

# 🔄 断点续爬功能
python auto_crawler.py Television --show-progress    # 查看进度
python auto_crawler.py Television --reset-progress   # 重置进度
python auto_crawler.py Television                    # 自动从断点恢复

# 查看完整帮助
python auto_crawler.py --help
```

### 4. 性能对比

| 模式 | 命令 | 线程数 | 连接数 | 适用场景 |
|------|------|--------|--------|----------|
| **默认** | `python auto_crawler.py device` | 8 | 80 | 日常使用 |
| **快速** | `python auto_crawler.py device --fast` | 12 | 120 | 网络良好 |
| **稳定** | `python auto_crawler.py device --stable` | 4 | 40 | 网络不稳定 |
| **企业** | `python auto_crawler.py device --enterprise` | 16 | 160 | 高性能服务器 |

### 5. 代理配置（可选）

工具内置HTTP隧道代理池，默认启用。如需自定义代理，编辑 `auto_crawler.py` 中的配置：

```python
# 隧道代理配置（默认已配置）
tunnel_host = "b353.kdltpspro.com"
tunnel_port = 15818
username = "your-username"
password = "your-password"
```

### 主要依赖
- `requests>=2.31.0` - HTTP请求处理
- `beautifulsoup4>=4.12.0` - HTML解析
- `httpx>=0.25.0` - 异步HTTP客户端
- `aiohttp>=3.8.0` - 异步HTTP客户端
- `urllib3>=2.0.0` - 连接池和重试机制
- `lxml>=4.9.0` - XML/HTML解析器
- `pandas>=2.0.0` - 数据处理
- `numpy>=1.24.0` - 数值计算
- `psutil>=5.9.0` - 系统监控

## 🌐 部署配置

### 📁 数据存储路径配置

工具支持通过环境变量 `IFIXIT_DATA_DIR` 灵活配置数据保存路径：

#### 本地开发环境
```bash
# 默认保存到当前目录的 ifixit_data/ 文件夹
python auto_crawler.py iPhone
```

#### 阿里云服务器部署
```bash
# 方法1: 临时设置（推荐用于测试）
export IFIXIT_DATA_DIR="/home/data"
python auto_crawler.py iPhone

# 方法2: 永久设置（推荐用于生产环境）
echo 'export IFIXIT_DATA_DIR="/home/data"' >> ~/.bashrc
source ~/.bashrc
python auto_crawler.py iPhone

# 方法3: 系统级设置
sudo nano /etc/environment
# 添加: IFIXIT_DATA_DIR="/home/data"
```

#### 自定义存储路径
```bash
# 保存到任意指定目录
export IFIXIT_DATA_DIR="/path/to/your/data"
python auto_crawler.py iPhone
```

### 🔧 配置验证

验证环境变量配置：
```bash
# 检查环境变量是否设置
echo $IFIXIT_DATA_DIR

# 检查目录是否存在且有权限
ls -la $IFIXIT_DATA_DIR
```

### 📋 部署检查清单

1. **目录权限**：确保目标目录有写入权限
   ```bash
   sudo mkdir -p /home/data
   sudo chown -R $USER:$USER /home/data
   sudo chmod -R 755 /home/data
   ```

2. **环境变量**：验证环境变量设置
   ```bash
   echo $IFIXIT_DATA_DIR  # 应输出: /home/data
   ```

3. **磁盘空间**：确保有足够的存储空间
   ```bash
   df -h /home/data
   ```

详细部署说明请参考：[阿里云部署说明.md](./阿里云部署说明.md)

## 📖 详细使用指南

### 基本语法

```bash
python auto_crawler.py [目标] [选项...]
```

### 🎯 目标参数

支持多种输入格式：

```bash
# 产品名称（URL编码格式）
python auto_crawler.py 'MacBook_Pro_17%22'
python auto_crawler.py 'iMac_M_Series'

# 完整URL
python auto_crawler.py 'https://www.ifixit.com/Device/MacBook_Pro_17%22'

# 部分URL
python auto_crawler.py '/Device/MacBook_Pro_17%22'
```

### 🚀 性能调优选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--workers N` | 并发线程数 | **8** |
| `--max-connections N` | 最大连接数 | **80** |
| `--max-retries N` | 最大重试次数 | 1 |
| `--timeout N` | 请求超时时间(秒) | 30 |
| `--delay N` | 请求间隔(秒) | 0.5 |
| `--burst-mode` | 启用爆发模式 | 否 |
| `--conservative` | 启用保守模式 | 否 |

### 🌐 网络和代理选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--no-proxy` | 关闭隧道代理 | **启用代理** |
| `--proxy-switch N` | 代理切换频率(请求数) | 100 |
| `--user-agent TEXT` | 自定义User-Agent | 默认 |

### 💾 缓存和数据选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--no-cache` | 禁用缓存检查 | **启用缓存** |
| `--force-refresh` | 强制重新爬取 | 否 |
| `--cache-ttl N` | 缓存配置参数（保留兼容性，实际为长期保存） | 24 |

###  断点续爬选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--no-resume` | 禁用断点续爬功能 | **启用续爬** |
| `--reset-progress` | 重置树构建进度（清除断点记录） | 否 |
| `--reset-only` | 仅重置进度后退出（不开始爬取） | 否 |
| `--show-progress` | 显示当前树构建进度 | 否 |
| `--progress-only` | 仅显示进度后退出（不开始爬取） | 否 |

### 📹 媒体处理选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--download-videos` | 启用视频文件下载 | 禁用 |
| `--max-video-size N` | 视频大小限制(MB) | 50 |
| `--skip-images` | 跳过图片下载 | 否 |

### 🔧 调试选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--verbose` | 启用详细输出 | 否 |
| `--debug` | 启用调试模式 | 否 |
| `--stats` | 显示详细统计 | 否 |

### 📊 预设配置

| 选项 | 说明 | 等效配置 |
|------|------|----------|
| `--fast` | 快速模式 | `--workers 12 --burst-mode --delay 0.3` |
| `--stable` | 稳定模式 | `--workers 4 --conservative --delay 1.0` |
| `--enterprise` | 企业模式 | `--workers 16 --max-connections 160 --delay 0.2` |

### 📝 使用示例

#### 🚀 默认高性能模式（推荐）
```bash
# 默认8线程并发 + 隧道代理池 + 智能缓存
python auto_crawler.py 'MacBook_Pro_17%22'

# 默认高性能 + 详细输出
python auto_crawler.py 'iMac_M_Series' --verbose
```

#### ⚡ 预设性能模式
```bash
# 快速模式：12线程 + 爆发模式
python auto_crawler.py 'iPhone' --fast

# 稳定模式：4线程 + 保守策略（适合网络不稳定）
python auto_crawler.py 'Television' --stable

# 企业模式：16线程 + 超高并发
python auto_crawler.py 'iPad' --enterprise --download-videos
```

#### 🎯 自定义高性能配置
```bash
# 超高并发：20线程 + 200连接
python auto_crawler.py 'MacBook' --workers 20 --max-connections 200

# 快速爬取：减少延迟 + 爆发模式
python auto_crawler.py 'iPhone' --delay 0.1 --burst-mode

# 稳定爬取：增加延迟 + 保守模式
python auto_crawler.py 'Television' --delay 2 --conservative
```

#### 🔄 断点续爬功能
```bash
# 查看当前树构建进度
python auto_crawler.py 'iPhone' --show-progress

# 重置树构建进度（清除断点记录）
python auto_crawler.py 'iPhone' --reset-progress

# 自动从断点恢复爬取
python auto_crawler.py 'iPhone'

# 仅重置进度后退出
python auto_crawler.py 'iPhone' --reset-progress --reset-only
```

#### 📹 完整内容爬取
```bash
# 启用视频下载，限制10MB
python auto_crawler.py 'iPhone' --download-videos --max-video-size 10

# 强制刷新，获取最新数据
python auto_crawler.py 'MacBook_Pro_17%22' --force-refresh

# 跳过图片下载，仅保存URL
python auto_crawler.py 'iPad' --skip-images
```

#### 🌐 网络和代理配置
```bash
# 禁用代理（如果代理不稳定）
python auto_crawler.py 'MacBook' --no-proxy

# 自定义代理切换频率
python auto_crawler.py 'iPhone' --proxy-switch 50

# 自定义User-Agent
python auto_crawler.py 'iPad' --user-agent "Custom Bot 1.0"
```

#### 🔧 调试和统计
```bash
# 调试模式 + 详细统计
python auto_crawler.py 'MacBook_Pro_17%22' --debug --stats

# 禁用缓存，确保数据最新
python auto_crawler.py 'iPhone' --no-cache

# 查看帮助信息
python auto_crawler.py --help
```

## 🚀 性能特性详解

### ⚡ 高性能架构

#### 默认配置优势
- **8线程并发**: 相比原4线程，性能提升100%
- **80连接池**: 智能连接复用，减少建连开销
- **隧道代理池**: 每次请求自动切换IP，避免封禁
- **智能缓存**: 长期保存到本地文件，避免重复爬取
- **断点续爬**: 自动记录树构建进度，支持中断恢复

#### 预设模式对比

| 特性 | 默认模式 | 快速模式 | 稳定模式 | 企业模式 |
|------|----------|----------|----------|----------|
| 线程数 | 8 | 12 | 4 | 16 |
| 连接数 | 80 | 120 | 40 | 160 |
| 请求间隔 | 0.5s | 0.3s | 1.0s | 0.2s |
| 适用场景 | 日常使用 | 网络良好 | 网络不稳定 | 高性能服务器 |
| 预估速度 | 基准 | +50% | -50% | +100% |

#### 智能优化特性
- **动态负载均衡**: 自动调整请求频率
- **指数退避重试**: 网络错误智能恢复
- **内存优化**: 大文件流式处理
- **并发控制**: 防止资源过载

### 🎯 使用建议

#### 场景选择
```bash
# 🏠 家庭网络 - 默认模式
python auto_crawler.py iPhone

# 🏢 办公网络 - 快速模式
python auto_crawler.py iPhone --fast

# 📱 移动网络 - 稳定模式
python auto_crawler.py iPhone --stable

# 🖥️ 服务器环境 - 企业模式
python auto_crawler.py iPhone --enterprise
```

#### 性能调优
```bash
# 网络良好时提升并发
python auto_crawler.py device --workers 16 --delay 0.2

# 网络不稳定时降低并发
python auto_crawler.py device --workers 4 --delay 2 --conservative

# 最大性能模式（谨慎使用）
python auto_crawler.py device --workers 20 --burst-mode --delay 0.1
```

## �📊 输出结果

### 📁 文件结构

爬取完成后，会在 `ifixit_data/` 目录下生成以下结构：

```
ifixit_data/
└── Device/                                    # 设备根目录
    └── Mac/                                   # 主要设备类型
        └── Mac_Laptop/                        # 设备子类型
            ├── info.json                      # 类型基本信息
            ├── troubleshooting/               # 故障排除目录（首次出现层级）
            │   ├── troubleshooting_1.json    # 故障排除内容
            │   ├── troubleshooting_2.json
            │   └── media/                     # 故障排除相关媒体文件
            │       ├── cfda85ed.jpg
            │       └── e26cd639.jpg
            └── MacBook_Pro/                   # 具体产品系列
                └── MacBook_Pro_17"/           # 具体产品型号
                    ├── info.json              # 产品基本信息
                    ├── guides/                # 指南目录
                    │   ├── guide_1.json      # 指南详细内容
                    │   ├── guide_2.json
                    │   └── media/             # 指南相关媒体文件
                    │       ├── 7bfd7f8b.jpg  # 图片文件（MD5命名）
                    │       └── 861cb4de.jpg
                    └── MacBook_Pro_17"_Models_A1151_A1212_A1229_and_A1261/
                        ├── info.json          # 具体型号信息
                        └── guides/            # 型号专用指南
                            └── guide_1.json
```

**注意**：Troubleshooting内容保存在首次出现的层级（如Mac_Laptop），而不是在每个子产品中重复保存。

### 📄 JSON数据结构

#### info.json（产品基本信息）
```json
{
  "name": "MacBook_Pro_17\"",
  "url": "https://www.ifixit.com/Device/MacBook_Pro_17%22",
  "title": "MacBook Pro 17英寸 Repair",
  "introduction": {
    "text": "The MacBook Pro 17-inch was a laptop computer...",
    "videos": [],
    "documents": []
  },
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
      "title": "MacBook Pro 17\" Models A1151 A1212 A1229 and A1261 Battery Replacement",
      "url": "https://www.ifixit.com/Guide/...",
      "difficulty": "Moderate",
      "time_required": "45 minutes - 1 hour"
    }
  ],
  "troubleshooting": [
    {
      "title": "MacBook Won't Turn On",
      "url": "https://www.ifixit.com/Troubleshooting/...",
      "causes_count": 8
    }
  ],
  "children": [
    {
      "name": "MacBook_Pro_17\"_Models_A1151_A1212_A1229_and_A1261",
      "url": "https://www.ifixit.com/Device/MacBook_Pro_17%22_Models_A1151_A1212_A1229_and_A1261",
      "title": "MacBook Pro 17英寸 Models A1151 A1212 A1229 and A1261 Repair"
    }
  ]
}
```

#### guide_*.json（指南详细内容）
```json
{
  "title": "MacBook Pro 17\" Models A1151 A1212 A1229 and A1261 Battery Replacement",
  "url": "https://www.ifixit.com/Guide/...",
  "difficulty": "Moderate",
  "time_required": "45 minutes - 1 hour",
  "introduction": {
    "text": "This guide will show you how to replace...",
    "Tools": ["Spudger", "Suction Handle"],
    "Parts": ["MacBook Pro 17\" Battery"]
  },
  "view_statistics": {
    "past_24_hours": "5",
    "past_7_days": "42",
    "past_30_days": "156",
    "all_time": "12,345"
  },
  "completed": "234",
  "favorites": "89",
  "steps": [
    {
      "title": "Remove the Battery",
      "content": "Use the spudger to carefully disconnect...",
      "images": ["Device/MacBook_Pro_17\"/Mac/Mac_Laptop/MacBook_Pro/MacBook_Pro_17\"/MacBook_Pro_17\"_Models_A1151_A1212_A1229_and_A1261/guides/media/7bfd7f8b.jpg"]
    }
  ]
}
```

#### troubleshooting_*.json（故障排除内容）
```json
{
  "title": "MacBook Won't Turn On",
  "url": "https://www.ifixit.com/Troubleshooting/...",
  "introduction": "If your MacBook won't turn on, try these solutions...",
  "first_steps": "Before diving into complex repairs...",
  "view_statistics": {
    "past_24_hours": "15",
    "past_7_days": "89",
    "past_30_days": "345",
    "all_time": "8,765"
  },
  "completed": "456",
  "favorites": "123",
  "causes": [
    {
      "title": "Power Supply Issue",
      "content": "Check the power connection and adapter...",
      "images": [
        {
          "url": "Device/MacBook_Pro_17\"/Mac/Mac_Laptop/MacBook_Pro/MacBook_Pro_17\"/troubleshooting/media/cfda85ed.jpg",
          "description": "Power adapter connection"
        }
      ]
    }
  ]
}
```


## 🔧 核心功能详解

### 🌳 树形结构 + 详细内容

- **完整层级结构**：基于真实面包屑导航构建设备分类树
- **深度内容提取**：每个节点包含完整的指南和故障排除内容
- **智能节点识别**：自动区分产品节点和分类节点

### 🔧 智能Troubleshooting处理机制

#### 处理原则
- **首次遇到处理**：在遍历设备分类树的过程中，当第一次遇到Troubleshooting内容时立即处理
- **层级优先保存**：将Troubleshooting内容保存在最早出现的层级目录中
- **子路径自动跳过**：已处理路径的所有子路径自动跳过Troubleshooting处理

#### 工作流程示例
以MacBook为例的处理流程：

```
1. 遍历 /Device/Mac → 无Troubleshooting内容，继续
2. 遍历 /Device/Mac/Mac_Laptop → 发现Troubleshooting内容
   ✅ 首次发现，开始处理并保存到 Mac_Laptop/troubleshooting/
   📝 标记路径 "Mac/Mac_Laptop" 为已处理
3. 遍历 /Device/Mac/Mac_Laptop/MacBook_Pro → 检查父路径
   ⏭️ 父路径已处理，跳过Troubleshooting处理
4. 遍历 /Device/Mac/Mac_Laptop/MacBook_Pro/MacBook_Pro_17" → 检查父路径
   ⏭️ 父路径已处理，跳过Troubleshooting处理
```

#### 技术实现
- **路径跟踪**：使用 `processed_troubleshooting_paths` 集合跟踪已处理的路径
- **父路径检查**：自动检查当前路径的父路径是否已经处理过Troubleshooting
- **智能跳过**：基于路径层级关系自动决定是否跳过处理

#### 优势
- **避免重复**：确保相同的Troubleshooting内容不会在多个层级重复保存
- **结构清晰**：内容保存在最合适的层级，便于查找和管理
- **性能优化**：减少不必要的网络请求和处理时间
- **存储优化**：避免重复存储相同内容，节省磁盘空间

### 🔄 智能代理池

- **隧道代理**：使用HTTP隧道代理池，每次请求自动切换IP
- **自动切换**：每次请求使用不同IP，无需手动切换
- **认证支持**：内置用户名密码认证
- **失败监控**：记录失败次数，智能监控代理状态

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

### 🖼️ 智能图片处理

- **跨页面去重**：基于URL的MD5哈希，避免重复下载相同图片
- **精准过滤**：只保留guide-images.cdn.ifixit.com的相关图片
- **商业内容过滤**：自动过滤掉商业、宣传、装饰性图片
- **本地存储优化**：图片文件使用MD5哈希命名，便于管理
- **格式统一**：确保所有图片URL使用.medium格式，保证质量一致性

### 💾 智能缓存机制

- **完整性验证**：检查缓存数据的完整性，包括文件结构和内容验证
- **智能索引**：基于URL哈希的缓存索引系统，快速定位缓存状态
- **长期保存**：缓存数据长期保存到本地文件，无过期时间限制
- **增量更新**：只处理新增或变更的内容，跳过已验证的缓存
- **强制刷新**：`--force-refresh` 忽略所有缓存
- **缓存统计**：详细的缓存命中率统计和性能报告
- **自动清理**：自动清理无效的缓存条目

### 🔍 智能缺失数据检测和补全

- **深度完整性检查**：自动检测缺失的文件夹、文件和媒体资源
- **精准补全机制**：只重新爬取缺失的内容，跳过已存在的完整数据
- **兼容新旧格式**：支持扁平文件结构和目录结构两种格式
- **智能缓存失效**：自动清理与缺失内容相关的无效缓存条目
- **无需强制刷新**：无需使用 `--force-refresh`，自动检测并补全缺失数据
- **实时进度显示**：显示检测到的缺失内容和补全进度
- **数据结构升级**：自动将旧格式数据升级为新的目录结构

#### 工作原理示例
```bash
# 手动删除guides文件夹后
rm -rf "ifixit_data/Device/.../guides"

# 直接运行爬虫，无需额外参数
python auto_crawler.py 'MacBook_Pro_17%22'

# 输出示例：
# 🔍 检测到目标目录存在但不完整: MacBook_Pro_17%22
# ⚠️ 发现guides目录缺失，将重新爬取
# ✅ troubleshooting目录完整
# 🔄 将自动补全缺失的内容...
```

### 🔄 断点续爬机制

- **进度记录**：自动记录树构建进度，包括已处理的URL和当前阶段
- **中断恢复**：程序中断后可自动从上次停止的位置继续
- **进度查看**：`--show-progress` 查看当前树构建进度和统计信息
- **进度重置**：`--reset-progress` 清除所有进度记录，重新开始
- **智能检测**：自动检测是否存在进度文件，决定是否启用续爬
- **多目标支持**：不同目标的进度文件独立管理，互不干扰

### 🔁 错误重试机制

- **指数退避**：重试间隔逐渐增加，避免频繁请求
- **最大重试**：可配置的最大重试次数
- **错误分类**：区分临时错误和永久错误，智能重试策略
- **代理切换**：网络错误时自动切换代理，提高成功率
- **失败记录**：记录失败的URL到日志文件，便于问题排查

### 🔧 智能故障排除处理

- **首次处理原则**：在遍历过程中首次遇到Troubleshooting内容时进行处理
- **路径层级跟踪**：自动跟踪已处理Troubleshooting的路径层级
- **子路径自动跳过**：已处理路径的子路径自动跳过，避免重复收集
- **层级结构保持**：确保Troubleshooting内容保存在最早出现的层级目录中
- **智能去重**：避免在不同层级重复保存相同的Troubleshooting内容

## 📈 性能统计

爬取完成后会显示详细的性能统计信息：

```
📊 智能缓存报告
============================================================
总URL数量: 45
缓存命中: 38 (跳过处理)
需要处理: 7 (新增或更新)
无效缓存: 0 (需要重新处理)
缓存命中率: 84.4%
============================================================

📊 性能统计报告
============================================================
🌐 总请求数: 90
💾 缓存命中: 38 (84.4%)
🔄 缓存未命中: 7
🔁 重试成功: 2/5 (40.0%)
❌ 重试失败: 3
📁 媒体下载成功: 2367/2393 (98.9%)
📁 媒体下载失败: 26
🎥 视频文件处理:
   ✅ 已下载: 0
   ⏭️ 已跳过: 5
   💡 提示: 视频下载已禁用，如需下载请设置 download_videos=True
🖼️ 图片处理统计:
   ✅ 跨页面去重: 649张图片避免重复下载
   🎯 精准过滤: 只保留guide-images.cdn.ifixit.com相关图片
   ❌ 403错误: 26个thumbnail图片访问受限（正常现象）
🔧 Troubleshooting处理统计:
   ✅ 首次处理路径: Mac/Mac_Laptop (包含8个故障排除)
   ⏭️ 自动跳过子路径: 12个子路径跳过重复处理
   📁 层级结构保持: 内容保存在最早出现的层级
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
- 检查隧道代理配置是否正确（用户名、密码、地址）
- 检查网络连接是否正常
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
- 确保有写入目标目录的权限（默认 `ifixit_data/` 或环境变量指定的目录）
- 检查磁盘空间是否充足
- 如果使用自定义路径，确保目录存在且有权限：
  ```bash
  sudo mkdir -p /home/data
  sudo chown -R $USER:$USER /home/data
  sudo chmod -R 755 /home/data
  ```

#### 5. 环境变量配置错误
```
数据保存到了错误的目录
```
**解决方案**：
- 检查环境变量设置：`echo $IFIXIT_DATA_DIR`
- 重新设置环境变量：`export IFIXIT_DATA_DIR="/home/data"`
- 验证配置：`echo $IFIXIT_DATA_DIR` 确认环境变量已设置
- 永久设置：`echo 'export IFIXIT_DATA_DIR="/home/data"' >> ~/.bashrc && source ~/.bashrc`

#### 6. 目录不存在错误
```
FileNotFoundError: No such file or directory
```
**解决方案**：
- 创建目标目录：`mkdir -p /home/data`
- 检查路径拼写是否正确
- 确保使用绝对路径：`export IFIXIT_DATA_DIR="/home/data"`

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
python auto_crawler.py 'MacBook_Pro_17%22'
```
- 默认启用代理池，避免封禁
- 不下载视频，节省空间
- 使用缓存，避免重复爬取
- 智能图片去重，节省存储空间
- 自动断点续爬，支持中断恢复

#### 完整内容爬取（研究用途）
```bash
python auto_crawler.py 'MacBook_Pro_17%22' --download-videos --max-video-size 50
```
- 下载视频文件，获取完整内容
- 限制视频大小，避免过大文件
- 适合深度研究和分析
- 包含完整的媒体资源

#### 大规模爬取（批量处理）
```bash
python auto_crawler.py 'MacBook_Pro_17%22' --workers 8 --max-retries 3
```
- 增加并发数，提升效率
- 适当减少重试次数，快速失败
- 适合处理大量数据
- 跨页面图片去重，避免重复下载

#### 调试模式（开发测试）
```bash
python auto_crawler.py 'MacBook_Pro_17%22' --verbose --debug --force-refresh
```
- 详细输出，便于调试
- 启用调试模式，显示更多信息
- 强制刷新，确保数据最新
- 显示详细的图片处理过程
- 显示Troubleshooting处理的层级决策过程
- 显示断点续爬的进度信息

## 🎯 使用场景说明

### 场景1：研究MacBook系列故障排除
```bash
python auto_crawler.py 'MacBook_Pro_17%22' --verbose --no-proxy
```

**处理结果**：
- Troubleshooting内容会保存在 `ifixit_data/Device/Mac/Mac_Laptop/troubleshooting/`
- 包含所有MacBook系列通用的故障排除方法
- MacBook_Pro、MacBook_Pro_17"等子目录不会重复保存相同内容
- 节省存储空间，避免内容冗余

### 场景2：获取完整设备层级结构
```bash
python auto_crawler.py 'Mac' --verbose --no-proxy
```

**处理结果**：
- 构建完整的Mac设备分类树
- 在每个首次出现Troubleshooting的层级保存内容
- 子层级自动跳过，避免重复处理
- 保持清晰的层级结构和内容组织

### 场景3：阿里云服务器部署
```bash
# 设置数据保存到 /home/data 目录
export IFIXIT_DATA_DIR="/home/data"

# 高性能企业模式爬取
python auto_crawler.py 'MacBook_Pro_17%22' --enterprise --verbose

# 验证数据保存位置
ls -la /home/data/Device/
```

**处理结果**：
- 数据直接保存到阿里云服务器的 `/home/data/Device/` 目录
- 利用服务器高性能配置，16线程并发处理
- 适合大规模数据采集和生产环境部署

### 场景4：批量处理多个设备类型
```bash
# 分别处理不同设备类型
python auto_crawler.py 'iPhone'
python auto_crawler.py 'iPad'
python auto_crawler.py 'Mac'
```

**处理结果**：
- 每个设备类型的Troubleshooting内容独立保存
- 智能缓存避免重复处理
- 跨设备类型的内容不会相互干扰
- 每个设备类型的进度独立管理，支持单独续爬

### 🚀 性能优化建议

#### 1. 并发配置优化
```bash
# 根据网络环境选择合适的并发数
python auto_crawler.py device --workers 8    # 默认推荐
python auto_crawler.py device --workers 12   # 网络良好
python auto_crawler.py device --workers 4    # 网络不稳定
python auto_crawler.py device --workers 20   # 高性能服务器
```

#### 2. 网络环境优化
- **家庭网络**: 使用默认模式或稳定模式
- **办公网络**: 推荐快速模式 `--fast`
- **服务器环境**: 推荐企业模式 `--enterprise`
- **移动网络**: 推荐稳定模式 `--stable`

#### 3. 代理策略优化
```bash
# 代理稳定时（推荐）
python auto_crawler.py device

# 代理不稳定时
python auto_crawler.py device --no-proxy

# 自定义代理切换频率
python auto_crawler.py device --proxy-switch 50
```

#### 4. 缓存策略优化
```bash
# 利用缓存提升速度（推荐）
python auto_crawler.py device

# 强制获取最新数据
python auto_crawler.py device --force-refresh

# 禁用缓存（不推荐）
python auto_crawler.py device --no-cache
```

#### 5. 断点续爬优化
```bash
# 查看当前进度
python auto_crawler.py device --show-progress

# 重置进度重新开始
python auto_crawler.py device --reset-progress

# 禁用断点续爬
python auto_crawler.py device --no-resume
```

#### 6. 资源使用优化
- **CPU密集**: 适当降低 `--workers` 数量
- **内存不足**: 使用 `--conservative` 模式
- **磁盘空间**: 使用 `--skip-images` 跳过图片
- **带宽限制**: 增加 `--delay` 请求间隔
- **中断恢复**: 利用断点续爬功能，避免重复工作

## 📄 许可证

本项目仅供学习和研究使用，请遵守相关法律法规和网站使用条款。

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个项目。

---

## 🌟 特色功能总结

### 🚀 高性能架构
- **⚡ 默认高并发**：8线程并发，性能翻倍提升
- **� 智能代理池**：HTTP隧道代理，自动IP切换，避免封禁
- **📊 预设模式**：快速/稳定/企业三种一键配置
- **�🎯 智能调优**：20+性能参数，灵活适应各种环境

### 🌳 内容提取
- **🎯 一键爬取**：简单命令即可获取完整设备信息
- **🌳 完整结构**：树形层级 + 详细内容，数据完整性最佳
- **🔧 智能去重**：Troubleshooting内容首次遇到时处理，避免重复收集
- **� 结构化存储**：层级目录结构，内容保存在最合适的层级

### 💾 智能系统
- **🧠 智能缓存**：24小时有效期，完整性验证，自动清理
- **🔁 错误重试**：指数退避策略，网络错误自动恢复
- **🎥 媒体处理**：可选视频下载，大小限制，本地存储
- **🖼️ 图片优化**：跨页面去重，精准过滤，避免重复下载

### 🔧 企业级特性
- **� 实时统计**：详细性能指标，爬取进度可视化
- **💡 易用性**：丰富的命令行选项，详细的帮助信息
- **🛡️ 稳定性**：多重错误处理，异常恢复机制
- **� 可扩展**：模块化设计，支持自定义扩展

**🚀 立即开始使用高性能模式：`python auto_crawler.py iPhone`**

### 🆕 最新更新 - 高性能架构升级

#### 🚀 v2.0 高性能版本
- **⚡ 性能翻倍**：默认并发从4线程提升到8线程，性能提升100%
- **� 预设模式**：新增快速/稳定/企业三种一键配置模式
- **🎯 智能调优**：新增20+性能参数，支持4-20+线程灵活配置
- **🌐 代理优化**：默认启用隧道代理池，自动IP切换，避免封禁
- **💾 缓存升级**：智能缓存系统，24小时有效期，自动完整性验证

#### 🔧 智能系统优化
- **🧠 智能Troubleshooting处理**：首次遇到时处理原则，避免重复收集
- **🔄 断点续爬系统**：自动记录树构建进度，支持中断恢复
- **📊 实时配置显示**：运行时显示完整性能配置和执行阶段
- **🔁 错误处理增强**：指数退避重试，智能代理切换
- **✨ 图片去重优化**：基于MD5哈希的跨页面去重，节省存储空间
- **🎯 内容过滤精准**：只保留相关图片，过滤商业宣传内容

#### 💡 用户体验提升
- **🎯 一键启动**：`python auto_crawler.py device` 即享高性能
- **📋 丰富选项**：支持爆发模式、保守模式、自定义配置
- **📊 进度可视**：实时显示爬取进度和性能指标
- **🗂️ 结构优化**：层级目录结构，内容保存在最合适位置

## 📋 快速参考

### 🚀 常用命令
```bash
# 本地开发（默认）
python auto_crawler.py iPhone

# 阿里云部署
export IFIXIT_DATA_DIR="/home/data"
python auto_crawler.py iPhone --enterprise

# 高性能模式
python auto_crawler.py MacBook --fast --workers 12

# 调试模式
python auto_crawler.py iPad --verbose --debug

# 断点续爬
python auto_crawler.py Television --show-progress
python auto_crawler.py Television --reset-progress
python auto_crawler.py Television  # 自动续爬
```

### 🔧 环境变量
```bash
# 设置数据保存路径
export IFIXIT_DATA_DIR="/home/data"

# 验证设置
echo $IFIXIT_DATA_DIR

# 永久设置
echo 'export IFIXIT_DATA_DIR="/home/data"' >> ~/.bashrc
source ~/.bashrc
```

### 📁 目录结构
```
${IFIXIT_DATA_DIR}/
├── cache_index.json                              # 缓存索引文件
├── tree_progress_*.json                          # 树构建进度文件
└── Device/
    ├── Mac/Mac_Laptop/MacBook_Pro/MacBook_Pro_17"/
    │   ├── info.json
    │   ├── guides/
    │   └── troubleshooting/
    └── iPhone/iPhone_15/iPhone_15_Pro/
        ├── info.json
        ├── guides/
        └── troubleshooting/
```

### 🆘 故障排除
- **权限错误**：`sudo chown -R $USER:$USER /home/data`
- **环境变量**：检查 `echo $IFIXIT_DATA_DIR`
- **网络问题**：`--no-proxy --workers 4`
- **详细日志**：`--verbose --debug`
- **进度问题**：`--reset-progress` 重置进度
- **缓存问题**：`--force-refresh` 强制刷新

---

## 🛠️ Python脚本文件详细用法

### 🌟 主要爬虫工具

#### `auto_crawler.py` - 高性能整合爬虫（推荐使用）
**功能**：企业级高性能爬虫，集成所有功能的一站式解决方案
**特性**：
- ⚡ 默认8线程并发 + 隧道代理池
- 🧠 智能缓存 + 断点续爬
- 🔧 智能缺失数据检测和补全
- 📊 预设性能模式（快速/稳定/企业）

```bash
# 基本用法
python auto_crawler.py 'MacBook_Pro_17%22'

# 预设模式
python auto_crawler.py iPhone --fast        # 快速模式（12线程）
python auto_crawler.py iPad --stable        # 稳定模式（4线程）
python auto_crawler.py MacBook --enterprise # 企业模式（16线程）

# 自定义配置
python auto_crawler.py device --workers 20 --max-connections 200
python auto_crawler.py device --download-videos --max-video-size 50

# 断点续爬
python auto_crawler.py device --show-progress    # 查看进度
python auto_crawler.py device --reset-progress   # 重置进度
python auto_crawler.py device                    # 自动续爬

# 缓存管理
python auto_crawler.py device --force-refresh    # 强制刷新
python auto_crawler.py device --no-cache         # 禁用缓存

# 调试模式
python auto_crawler.py device --verbose --debug --stats

# 查看完整帮助
python auto_crawler.py --help
```

#### `enhanced_crawler.py` - 详细内容爬虫基础组件
**功能**：专门负责提取指南和故障排除的详细内容
**特性**：
- 📖 深度内容提取（指南步骤、故障排除原因）
- 🖼️ 智能图片处理和去重
- 🎥 可选视频下载
- 📊 统计信息提取

```bash
# 直接使用（不推荐，建议使用auto_crawler.py）
python enhanced_crawler.py

# 主要作为模块被其他脚本调用
from enhanced_crawler import EnhancedIFixitCrawler
crawler = EnhancedIFixitCrawler()
```

#### `tree_crawler.py` - 树形结构爬虫基础组件
**功能**：构建完整的设备分类层级结构
**特性**：
- 🌳 递归遍历设备分类树
- 📍 基于面包屑导航构建路径
- 🔗 提取指南和故障排除链接
- 📊 节点类型智能识别

```bash
# 直接使用（不推荐，建议使用auto_crawler.py）
python tree_crawler.py

# 主要作为模块被其他脚本调用
from tree_crawler import TreeCrawler
crawler = TreeCrawler()
```

#### `tree_building_progress.py` - 断点续爬进度管理
**功能**：管理树构建过程的进度记录和恢复
**特性**：
- 💾 自动保存爬取进度
- 🔄 中断后自动恢复
- 📊 进度统计和报告
- 🗂️ 多目标独立管理

```bash
# 查看特定目标的进度
python tree_building_progress.py --target "MacBook_Pro_17%22" --show

# 重置特定目标的进度
python tree_building_progress.py --target "MacBook_Pro_17%22" --reset

# 清理所有过期进度文件
python tree_building_progress.py --cleanup

# 主要作为模块被其他脚本调用
from tree_building_progress import TreeBuildingProgress
progress = TreeBuildingProgress("target_name")
```

### 🔧 调试和检查工具

#### `check_crawler_status.py` - 爬虫状态检查工具
**功能**：检查爬虫运行状态和数据保存情况
**用途**：监控爬取进度、验证数据完整性

```bash
# 检查整体爬虫状态
python check_crawler_status.py

# 检查特定产品状态
python check_crawler_status.py --target "MacBook_Pro_17%22"

# 检查缓存状态
python check_crawler_status.py --check-cache

# 检查进度文件状态
python check_crawler_status.py --check-progress

# 生成详细报告
python check_crawler_status.py --detailed-report

# 检查数据目录完整性
python check_crawler_status.py --check-data-integrity
```



### 📦 批处理和辅助工具

#### `batch_crawler.py` - 批量爬虫工具
**功能**：支持批量处理多个目标，适合大规模数据采集
**用途**：批量爬取、自动化处理

```bash
# 批量爬取多个设备
python batch_crawler.py --targets "iPhone,iPad,MacBook"

# 从文件读取目标列表
python batch_crawler.py --targets-file targets.txt

# 批量爬取并行处理
python batch_crawler.py --targets "iPhone,iPad" --parallel

# 批量爬取高性能模式
python batch_crawler.py --targets "MacBook,iMac" --enterprise

# 批量爬取带进度报告
python batch_crawler.py --targets "iPhone,iPad" --progress-report

# 批量爬取错误恢复
python batch_crawler.py --targets-file targets.txt --resume-on-error

# 示例targets.txt文件内容：
# iPhone
# iPad
# MacBook_Pro_17%22
# iMac_M_Series
```

#### `easy_crawler.py` - 简易爬虫工具
**功能**：提供简化的爬取功能，适合快速测试和简单需求
**用途**：快速验证、简单爬取、学习参考

```bash
# 简单爬取（基础功能）
python easy_crawler.py "iPhone"

# 简单爬取带详细输出
python easy_crawler.py "MacBook" --verbose

# 简单爬取禁用代理
python easy_crawler.py "iPad" --no-proxy

# 简单爬取自定义保存路径
python easy_crawler.py "device" --output-dir "/path/to/save"

# 简单爬取只获取基本信息
python easy_crawler.py "device" --basic-only

# 简单爬取测试模式
python easy_crawler.py "device" --test-mode
```

#### `combined_crawler.py` - 基础整合爬虫
**功能**：基础的整合爬虫实现，参考代码
**用途**：代码参考、功能理解、自定义开发

```bash
# 基础整合爬取
python combined_crawler.py "MacBook_Pro_17%22"

# 基础整合爬取详细模式
python combined_crawler.py "iPhone" --verbose

# 主要作为参考实现，建议使用auto_crawler.py
```

#### `crawler.py` - 原始爬虫基础类
**功能**：提供基础的爬虫功能类，其他爬虫的基础组件
**用途**：代码复用、基础功能、模块开发

```bash
# 主要作为基础模块被其他脚本调用
from crawler import IFixitCrawler
crawler = IFixitCrawler()

# 不建议直接使用，建议使用auto_crawler.py
```

### 📋 使用建议和最佳实践

#### 🎯 场景选择指南

**日常使用（推荐）**：
```bash
python auto_crawler.py 'MacBook_Pro_17%22'
```

**开发调试**：
```bash
python check_crawler_status.py --target "MacBook_Pro_17%22"
python auto_crawler.py "MacBook_Pro_17%22" --verbose --debug
```

**批量处理**：
```bash
python batch_crawler.py --targets "iPhone,iPad,MacBook"
```

**测试和验证**：
```bash
python test_filename_generation.py
python auto_crawler.py "device" --force-refresh --verbose
```

#### 🔧 工具组合使用

**完整的数据采集流程**：
```bash
# 1. 主要爬取
python auto_crawler.py 'MacBook_Pro_17%22' --enterprise

# 2. 检查状态
python check_crawler_status.py --target "MacBook_Pro_17%22"

# 3. 如有问题，强制刷新重新爬取
python auto_crawler.py 'MacBook_Pro_17%22' --force-refresh --verbose
```

**批量处理流程**：
```bash
# 1. 批量爬取多个目标
python batch_crawler.py --targets "iPhone,iPad,MacBook"

# 2. 检查整体状态
python check_crawler_status.py

# 3. 测试文件名生成
python test_filename_generation.py
```

#### ⚠️ 注意事项

1. **推荐使用顺序**：
   - 首选：`auto_crawler.py`（功能最全面）
   - 调试：`check_crawler_status.py` + `--verbose --debug` 参数
   - 批量：`batch_crawler.py`
   - 测试：`test_filename_generation.py`

2. **避免同时运行**：
   - 不要同时运行多个爬虫脚本
   - 检查工具可以在爬虫运行时使用

3. **数据备份**：
   - 重要数据建议定期备份
   - 使用 `--force-refresh` 前建议备份现有数据

4. **性能考虑**：
   - 大规模操作使用 `--enterprise` 模式
   - 网络不稳定时使用 `--stable` 模式
   - 调试时使用 `--verbose` 获取详细信息

---

**📖 详细文档**：[阿里云部署说明.md](./阿里云部署说明.md)
