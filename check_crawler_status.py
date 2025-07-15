#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
检查爬虫状态和数据保存情况
"""

import os
import json
import glob
from pathlib import Path

def check_crawler_status():
    """检查爬虫当前状态"""
    print("🔍 检查爬虫状态...")
    
    # 检查当前目录
    current_dir = Path.cwd()
    print(f"📁 当前目录: {current_dir}")
    
    # 检查进度文件
    progress_files = glob.glob("tree_progress_*.json")
    if progress_files:
        print(f"📊 找到进度文件: {len(progress_files)} 个")
        for pf in progress_files:
            try:
                with open(pf, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"   - {pf}: {data.get('status', 'unknown')} 阶段")
                    if 'current_phase' in data:
                        print(f"     当前阶段: {data['current_phase']}")
                    if 'progress' in data:
                        print(f"     进度: {data['progress']}")
            except Exception as e:
                print(f"   - {pf}: 读取失败 - {e}")
    else:
        print("❌ 未找到进度文件")
    
    # 检查数据目录
    data_dirs = ['ifixit_data', '/home/data/ifixit_data', 'data']
    for data_dir in data_dirs:
        if os.path.exists(data_dir):
            print(f"📂 找到数据目录: {data_dir}")
            # 统计内容
            try:
                path = Path(data_dir)
                subdirs = [d for d in path.iterdir() if d.is_dir()]
                files = [f for f in path.iterdir() if f.is_file()]
                print(f"   - 子目录: {len(subdirs)} 个")
                print(f"   - 文件: {len(files)} 个")
                
                # 显示前几个子目录
                for i, subdir in enumerate(subdirs[:5]):
                    print(f"     {i+1}. {subdir.name}")
                if len(subdirs) > 5:
                    print(f"     ... 还有 {len(subdirs)-5} 个")
                    
            except Exception as e:
                print(f"   读取目录失败: {e}")
        else:
            print(f"❌ 数据目录不存在: {data_dir}")
    
    # 检查环境变量
    ifixit_data_dir = os.getenv('IFIXIT_DATA_DIR')
    if ifixit_data_dir:
        print(f"🌍 环境变量 IFIXIT_DATA_DIR: {ifixit_data_dir}")
        if os.path.exists(ifixit_data_dir):
            print(f"   ✅ 目录存在")
        else:
            print(f"   ❌ 目录不存在")
    else:
        print("🌍 未设置环境变量 IFIXIT_DATA_DIR (将使用默认路径 ifixit_data)")

if __name__ == "__main__":
    check_crawler_status()