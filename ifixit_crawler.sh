#!/bin/bash

# 设置错误处理
set -e  # 遇到错误立即退出
set -u  # 使用未定义变量时报错

# 配置变量
PROJECT_DIR="/root/SpiderDY"
LOG_FILE="ifixit_log.txt"
CRAWLER_LOG="crawler_output.log"
CONDA_ENV="py312"
CRAWLER_SCRIPT="auto_crawler.py"
CRAWLER_URL="https://www.ifixit.com/Guide"

# 日志函数
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 错误处理函数
handle_error() {
    log_message "❌ 脚本执行失败: $1"
    exit 1
}

# 开始执行
log_message "===== 开始更新部署 ====="

# 激活conda环境
log_message "🔧 激活conda环境: $CONDA_ENV"
if ! source ~/miniconda/bin/activate "$CONDA_ENV"; then
    handle_error "conda环境激活失败"
fi

# 进入项目目录
log_message "📁 进入项目目录: $PROJECT_DIR"
if ! cd "$PROJECT_DIR"; then
    handle_error "无法进入项目目录"
fi

# 检查是否有未提交的更改
if ! git diff --quiet || ! git diff --cached --quiet; then
    log_message "💾 保存当前修改"
    git stash push -m "Auto stash before update $(date)"
fi

# 拉取最新代码
log_message "⬇️  拉取最新代码"
if ! git pull; then
    handle_error "Git pull 失败"
fi

# 更新依赖（只在requirements.txt有变化时）
if git diff HEAD~1 HEAD --name-only | grep -q "requirements.txt"; then
    log_message "📦 更新Python依赖"
    if ! pip install -r requirements.txt; then
        log_message "⚠️  依赖更新失败，但继续执行"
    fi
else
    log_message "📦 依赖文件无变化，跳过更新"
fi

# 检查爬虫脚本语法
log_message "🔍 检查爬虫脚本语法"
if ! python -m py_compile "$CRAWLER_SCRIPT"; then
    handle_error "爬虫脚本语法检查失败"
fi

# 停止当前运行的爬虫
log_message "🛑 停止当前运行的爬虫"
if pgrep -f "python $CRAWLER_SCRIPT" > /dev/null; then
    pkill -f "python $CRAWLER_SCRIPT"
    log_message "⏳ 等待进程完全终止..."

    # 等待进程终止，最多等待30秒
    for i in {1..30}; do
        if ! pgrep -f "python $CRAWLER_SCRIPT" > /dev/null; then
            log_message "✅ 爬虫进程已停止"
            break
        fi
        sleep 1
        if [ $i -eq 30 ]; then
            log_message "⚠️  强制终止爬虫进程"
            pkill -9 -f "python $CRAWLER_SCRIPT" || true
        fi
    done
else
    log_message "ℹ️  没有发现运行中的爬虫进程"
fi

# 设置数据保存路径环境变量
log_message "🔧 设置数据保存路径: /home/data"
export IFIXIT_DATA_DIR="/home/data"

# 确保目标目录存在并有正确权限
if [ ! -d "/home/data" ]; then
    log_message "📁 创建数据目录: /home/data"
    mkdir -p /home/data
    chmod 755 /home/data
fi

# 重启爬虫
log_message "🚀 启动新的爬虫进程"
if nohup python "$CRAWLER_SCRIPT" "$CRAWLER_URL" > "$CRAWLER_LOG" 2>&1 & then
    NEW_PID=$!
    log_message "✅ 爬虫启动成功，进程ID: $NEW_PID"

    # 等待几秒检查进程是否正常启动
    sleep 3
    if kill -0 "$NEW_PID" 2>/dev/null; then
        log_message "✅ 爬虫进程运行正常"
    else
        handle_error "爬虫进程启动后异常退出"
    fi
else
    handle_error "爬虫启动失败"
fi

log_message "===== 更新部署完成 ====="
log_message "📊 可以使用以下命令查看运行状态:"
log_message "   tail -f $CRAWLER_LOG"
log_message "   ps aux | grep $CRAWLER_SCRIPT"