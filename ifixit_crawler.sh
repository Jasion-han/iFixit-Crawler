#!/bin/bash

# 记录日志
echo "===== 开始更新 $(date) =====" >> ifixit_log.txt

# 激活conda环境
source ~/miniconda/bin/activate py312

# 进入项目目录
cd /root/SpiderDY

# 保存当前修改（如果有）
git stash

# 拉取最新代码
git pull
if [ $? -ne 0 ]; then
    echo "Git pull 失败" >> ifixit_log.txt
    exit 1
fi

# 更新依赖
pip install -r requirements.txt

# 停止当前运行的爬虫
pkill -f "python auto_crawler.py"

# 等待进程完全终止
sleep 5

# 重启爬虫
nohup python auto_crawler.py https://www.ifixit.com/Guide > crawler_output.log 2>&1 &

# 记录新进程ID
echo "新进程ID: $!" >> ifixit_log.txt
echo "===== 更新完成 $(date) =====" >> ifixit_log.txt 