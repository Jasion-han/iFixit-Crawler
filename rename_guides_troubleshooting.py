#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重新命名Device目录下的guides和troubleshooting文件夹
命名规则：父节点名称 + JSON文件中的title
"""

import os
import json
import re
import shutil
from pathlib import Path


def sanitize_filename(filename):
    """
    清理文件名，移除或替换不合法的字符
    """
    # 移除或替换不合法的文件名字符
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # 移除多余的空格和换行符
    filename = re.sub(r'\s+', ' ', filename).strip()
    # 限制文件名长度
    if len(filename) > 200:
        filename = filename[:200]
    return filename


def get_parent_name(path):
    """
    获取父节点名称
    """
    parent_path = Path(path).parent
    return parent_path.name


def rename_guide_folders(device_root):
    """
    重新命名guides文件夹
    """
    device_path = Path(device_root)
    
    if not device_path.exists():
        print(f"错误：Device目录不存在: {device_root}")
        return
    
    renamed_count = 0
    error_count = 0
    
    # 遍历所有guides文件夹
    for guides_folder in device_path.rglob("guides"):
        if not guides_folder.is_dir():
            continue
            
        print(f"\n处理guides文件夹: {guides_folder}")
        parent_name = get_parent_name(guides_folder)
        
        # 遍历guides文件夹中的guide_x子文件夹
        guide_folders = [f for f in guides_folder.iterdir() if f.is_dir() and f.name.startswith('guide_')]
        guide_folders.sort(key=lambda x: int(x.name.split('_')[1]) if x.name.split('_')[1].isdigit() else 0)
        
        for guide_folder in guide_folders:
            try:
                guide_json_path = guide_folder / "guide.json"
                
                if not guide_json_path.exists():
                    print(f"  警告：找不到guide.json文件: {guide_json_path}")
                    error_count += 1
                    continue
                
                # 读取JSON文件获取title
                with open(guide_json_path, 'r', encoding='utf-8') as f:
                    guide_data = json.load(f)
                
                title = guide_data.get('title', '').strip()
                if not title:
                    print(f"  警告：guide.json中没有title字段: {guide_json_path}")
                    error_count += 1
                    continue
                
                # 构建新的文件夹名称
                new_folder_name = f"{parent_name}_{title}"
                new_folder_name = sanitize_filename(new_folder_name)
                
                new_folder_path = guide_folder.parent / new_folder_name
                
                # 检查新名称是否已存在
                if new_folder_path.exists() and new_folder_path != guide_folder:
                    print(f"  警告：目标文件夹已存在: {new_folder_path}")
                    # 添加数字后缀
                    counter = 1
                    while new_folder_path.exists():
                        new_folder_name_with_counter = f"{new_folder_name}_{counter}"
                        new_folder_path = guide_folder.parent / new_folder_name_with_counter
                        counter += 1
                
                # 重命名文件夹
                if new_folder_path != guide_folder:
                    print(f"  重命名: {guide_folder.name} -> {new_folder_path.name}")
                    shutil.move(str(guide_folder), str(new_folder_path))
                    renamed_count += 1
                else:
                    print(f"  跳过: {guide_folder.name} (名称未改变)")
                    
            except Exception as e:
                print(f"  错误：处理{guide_folder}时出错: {str(e)}")
                error_count += 1
    
    return renamed_count, error_count


def rename_troubleshooting_folders(device_root):
    """
    重新命名troubleshooting文件夹
    """
    device_path = Path(device_root)
    
    if not device_path.exists():
        print(f"错误：Device目录不存在: {device_root}")
        return
    
    renamed_count = 0
    error_count = 0
    
    # 遍历所有troubleshooting文件夹
    for troubleshooting_folder in device_path.rglob("troubleshooting"):
        if not troubleshooting_folder.is_dir():
            continue
            
        print(f"\n处理troubleshooting文件夹: {troubleshooting_folder}")
        parent_name = get_parent_name(troubleshooting_folder)
        
        # 遍历troubleshooting文件夹中的troubleshooting_x子文件夹
        ts_folders = [f for f in troubleshooting_folder.iterdir() if f.is_dir() and f.name.startswith('troubleshooting_')]
        ts_folders.sort(key=lambda x: int(x.name.split('_')[1]) if x.name.split('_')[1].isdigit() else 0)
        
        for ts_folder in ts_folders:
            try:
                ts_json_path = ts_folder / "troubleshooting.json"
                
                if not ts_json_path.exists():
                    print(f"  警告：找不到troubleshooting.json文件: {ts_json_path}")
                    error_count += 1
                    continue
                
                # 读取JSON文件获取title
                with open(ts_json_path, 'r', encoding='utf-8') as f:
                    ts_data = json.load(f)
                
                title = ts_data.get('title', '').strip()
                if not title:
                    print(f"  警告：troubleshooting.json中没有title字段: {ts_json_path}")
                    error_count += 1
                    continue
                
                # 构建新的文件夹名称
                new_folder_name = f"{parent_name}_{title}"
                new_folder_name = sanitize_filename(new_folder_name)
                
                new_folder_path = ts_folder.parent / new_folder_name
                
                # 检查新名称是否已存在
                if new_folder_path.exists() and new_folder_path != ts_folder:
                    print(f"  警告：目标文件夹已存在: {new_folder_path}")
                    # 添加数字后缀
                    counter = 1
                    while new_folder_path.exists():
                        new_folder_name_with_counter = f"{new_folder_name}_{counter}"
                        new_folder_path = ts_folder.parent / new_folder_name_with_counter
                        counter += 1
                
                # 重命名文件夹
                if new_folder_path != ts_folder:
                    print(f"  重命名: {ts_folder.name} -> {new_folder_path.name}")
                    shutil.move(str(ts_folder), str(new_folder_path))
                    renamed_count += 1
                else:
                    print(f"  跳过: {ts_folder.name} (名称未改变)")
                    
            except Exception as e:
                print(f"  错误：处理{ts_folder}时出错: {str(e)}")
                error_count += 1
    
    return renamed_count, error_count


def main():
    """
    主函数
    """
    import sys
    
    if len(sys.argv) != 2:
        print("使用方法: python rename_guides_troubleshooting.py <Device目录路径>")
        print("示例: python rename_guides_troubleshooting.py ./ifixit_data/Device")
        sys.exit(1)
    
    device_root = sys.argv[1]
    
    print(f"开始重命名Device目录下的guides和troubleshooting文件夹...")
    print(f"Device根目录: {device_root}")
    
    # 重命名guides文件夹
    print("\n=== 重命名guides文件夹 ===")
    guide_renamed, guide_errors = rename_guide_folders(device_root)
    
    # 重命名troubleshooting文件夹
    print("\n=== 重命名troubleshooting文件夹 ===")
    ts_renamed, ts_errors = rename_troubleshooting_folders(device_root)
    
    # 输出统计信息
    print(f"\n=== 重命名完成 ===")
    print(f"guides文件夹重命名: {guide_renamed} 个")
    print(f"troubleshooting文件夹重命名: {ts_renamed} 个")
    print(f"总计重命名: {guide_renamed + ts_renamed} 个")
    print(f"错误数量: {guide_errors + ts_errors} 个")
    
    if guide_errors + ts_errors > 0:
        print("\n注意：存在错误，请检查上面的警告信息")


if __name__ == "__main__":
    main()
