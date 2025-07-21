#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
树构建进度管理器 - 为iFixit爬虫的文件树构建阶段实现断点续爬功能
支持大规模分类树构建的中断恢复，避免重复工作，提高效率
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from urllib.parse import urlparse


class TreeBuildingProgressManager:
    """树构建进度管理器 - 实现断点续爬功能"""
    
    def __init__(self, target_url: str, storage_root: str = None,
                 logger: Optional[logging.Logger] = None, command_arg: str = None):
        """
        初始化树构建进度管理器

        Args:
            target_url: 目标URL
            storage_root: 存储根目录
            logger: 日志记录器
            command_arg: 命令行参数，用于生成更友好的文件名
        """
        self.command_arg = command_arg
        self.target_url = target_url
        # 支持通过环境变量配置数据保存路径，默认为 ifixit_data
        if storage_root is None:
            storage_root = os.getenv('IFIXIT_DATA_DIR', 'ifixit_data')
        self.storage_root = Path(storage_root)
        self.logger = logger or logging.getLogger(__name__)
        
        # 生成进度文件路径
        self.progress_file = self._get_progress_file_path()
        
        # 进度状态
        self.progress_data = {
            "version": "1.0",
            "target_url": target_url,
            "start_time": None,
            "last_update": None,
            "status": "not_started",  # not_started, in_progress, completed, failed
            "tree_structure": None,
            "processed_urls": set(),
            "current_processing": None,
            "failed_urls": set(),
            "statistics": {
                "total_discovered": 0,
                "total_processed": 0,
                "total_failed": 0,
                "session_start_time": None
            }
        }
        
        # 加载现有进度
        self.load_progress()
        
    def _get_progress_file_path(self) -> Path:
        """生成进度文件路径 - 基于目标名称，不使用哈希值"""
        # 优先使用命令行参数作为文件名
        if hasattr(self, 'command_arg') and self.command_arg:
            # 清理命令行参数，移除URL前缀和特殊字符
            clean_name = self.command_arg
            if clean_name.startswith('https://www.ifixit.com/'):
                clean_name = clean_name.replace('https://www.ifixit.com/', '')
            if clean_name.startswith('Device/'):
                clean_name = clean_name.replace('Device/', '')
            if clean_name.startswith('Guide/'):
                clean_name = clean_name.replace('Guide/', '')

            # 清理特殊字符，保留字母数字和下划线
            clean_name = ''.join(c if c.isalnum() or c in '_-' else '_' for c in clean_name)
            clean_name = clean_name.strip('_')

            if clean_name:
                filename = f"tree_progress_{clean_name}.json"
                return self.storage_root / filename

        # 从URL提取可读的名称部分作为后备方案
        parsed_url = urlparse(self.target_url)
        path_parts = parsed_url.path.strip('/').split('/')

        if len(path_parts) >= 2 and path_parts[0] in ['Device', 'Guide']:
            # 使用路径的最后一部分作为文件名
            target_name = path_parts[-1] if path_parts[-1] else path_parts[-2]
            # URL解码并清理特殊字符
            from urllib.parse import unquote
            target_name = unquote(target_name)
            clean_name = ''.join(c if c.isalnum() or c in '_-' else '_' for c in target_name)
            clean_name = clean_name.strip('_')
            filename = f"tree_progress_{clean_name}.json"
        else:
            # 最后的后备方案
            filename = "tree_progress_default.json"

        return self.storage_root / filename
    
    def load_progress(self) -> bool:
        """加载现有进度"""
        try:
            if not self.progress_file.exists():
                self.logger.info(f"进度文件不存在，将创建新的进度记录: {self.progress_file}")
                return False
                
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
                
            # 验证进度文件的有效性
            if saved_data.get('target_url') != self.target_url:
                self.logger.warning(f"进度文件目标URL不匹配，创建新的进度记录")
                return False
                
            # 恢复进度数据
            self.progress_data.update(saved_data)
            
            # 转换集合类型（JSON不支持set）
            self.progress_data['processed_urls'] = set(saved_data.get('processed_urls', []))
            self.progress_data['failed_urls'] = set(saved_data.get('failed_urls', []))
            
            self.logger.info(f"成功加载进度文件: {len(self.progress_data['processed_urls'])} 个已处理URL")
            return True
            
        except Exception as e:
            self.logger.error(f"加载进度文件失败: {e}")
            return False
    
    def save_progress(self):
        """保存当前进度"""
        try:
            # 确保目录存在
            self.progress_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 准备保存数据（转换set为list）
            save_data = self.progress_data.copy()
            save_data['processed_urls'] = list(self.progress_data['processed_urls'])
            save_data['failed_urls'] = list(self.progress_data['failed_urls'])
            save_data['last_update'] = datetime.now(timezone.utc).isoformat()
            
            # 保存到文件
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
                
            self.logger.debug(f"进度已保存: {len(self.progress_data['processed_urls'])} 个已处理URL")
            
        except Exception as e:
            self.logger.error(f"保存进度文件失败: {e}")
    
    def start_session(self):
        """开始新的构建会话"""
        if self.progress_data['status'] == 'not_started':
            self.progress_data['start_time'] = datetime.now(timezone.utc).isoformat()
            
        self.progress_data['status'] = 'in_progress'
        self.progress_data['statistics']['session_start_time'] = datetime.now(timezone.utc).isoformat()
        
        self.logger.info(f"开始树构建会话: {self.target_url}")
        self.save_progress()
    
    def is_url_processed(self, url: str) -> bool:
        """检查URL是否已经处理完成"""
        return url in self.progress_data['processed_urls']
    
    def is_url_failed(self, url: str) -> bool:
        """检查URL是否处理失败"""
        return url in self.progress_data['failed_urls']
    
    def mark_url_processing(self, url: str, parent_path: List[str] = None):
        """标记URL开始处理"""
        self.progress_data['current_processing'] = {
            "url": url,
            "parent_path": parent_path or [],
            "start_time": datetime.now(timezone.utc).isoformat(),
            "children_discovered": 0,
            "children_processed": 0
        }

        self.logger.debug(f"开始处理URL: {url}")

        # 保存当前处理状态
        self.save_progress()
        
    def mark_url_completed(self, url: str, children_count: int = 0):
        """标记URL处理完成"""
        self.progress_data['processed_urls'].add(url)
        self.progress_data['statistics']['total_processed'] += 1

        # 清除当前处理状态
        if (self.progress_data['current_processing'] and
            self.progress_data['current_processing']['url'] == url):
            self.progress_data['current_processing'] = None

        self.logger.debug(f"URL处理完成: {url} (子分类: {children_count})")

        # 立即保存进度，确保数据不丢失
        self.save_progress()
    
    def mark_url_failed(self, url: str, error: str = ""):
        """标记URL处理失败"""
        self.progress_data['failed_urls'].add(url)
        self.progress_data['statistics']['total_failed'] += 1
        
        # 清除当前处理状态
        if (self.progress_data['current_processing'] and 
            self.progress_data['current_processing']['url'] == url):
            self.progress_data['current_processing'] = None
            
        self.logger.warning(f"URL处理失败: {url} - {error}")
        self.save_progress()
    
    def update_children_discovered(self, count: int):
        """更新发现的子分类数量"""
        if self.progress_data['current_processing']:
            self.progress_data['current_processing']['children_discovered'] = count
            self.progress_data['statistics']['total_discovered'] += count
    
    def update_children_processed(self, count: int):
        """更新已处理的子分类数量"""
        if self.progress_data['current_processing']:
            self.progress_data['current_processing']['children_processed'] = count
    
    def save_tree_structure(self, tree_structure: Dict[str, Any]):
        """保存当前的树形结构"""
        self.progress_data['tree_structure'] = tree_structure
        self.save_progress()
    
    def get_tree_structure(self) -> Optional[Dict[str, Any]]:
        """获取已保存的树形结构"""
        return self.progress_data.get('tree_structure')
    
    def complete_session(self):
        """完成构建会话"""
        self.progress_data['status'] = 'completed'
        self.progress_data['current_processing'] = None
        
        self.logger.info(f"树构建会话完成: 处理了 {len(self.progress_data['processed_urls'])} 个URL")
        self.save_progress()
    
    def fail_session(self, error: str = ""):
        """标记会话失败"""
        self.progress_data['status'] = 'failed'
        self.progress_data['error'] = error
        
        self.logger.error(f"树构建会话失败: {error}")
        self.save_progress()
    
    def get_progress_stats(self) -> Dict[str, Any]:
        """获取进度统计信息"""
        stats = self.progress_data['statistics'].copy()
        stats.update({
            'processed_count': len(self.progress_data['processed_urls']),
            'failed_count': len(self.progress_data['failed_urls']),
            'status': self.progress_data['status'],
            'current_processing': self.progress_data['current_processing']
        })
        return stats
    
    def reset_progress(self):
        """重置进度（强制重新开始）"""
        self.logger.info("重置树构建进度")
        
        # 备份当前进度文件
        if self.progress_file.exists():
            backup_file = self.progress_file.with_suffix('.backup.json')
            self.progress_file.rename(backup_file)
            self.logger.info(f"已备份现有进度文件到: {backup_file}")
        
        # 重置进度数据
        self.progress_data = {
            "version": "1.0",
            "target_url": self.target_url,
            "start_time": None,
            "last_update": None,
            "status": "not_started",
            "tree_structure": None,
            "processed_urls": set(),
            "current_processing": None,
            "failed_urls": set(),
            "statistics": {
                "total_discovered": 0,
                "total_processed": 0,
                "total_failed": 0,
                "session_start_time": None
            }
        }
    
    def display_progress_report(self):
        """显示进度报告"""
        stats = self.get_progress_stats()
        
        print("\n" + "="*60)
        print("🌳 树构建进度报告")
        print("="*60)
        print(f"目标URL: {self.target_url}")
        print(f"状态: {stats['status']}")
        print(f"已处理URL: {stats['processed_count']}")
        print(f"失败URL: {stats['failed_count']}")
        print(f"总发现数: {stats['total_discovered']}")
        
        if stats['current_processing']:
            current = stats['current_processing']
            print(f"当前处理: {current['url']}")
            print(f"父路径: {' > '.join(current.get('parent_path', []))}")
            print(f"子分类进度: {current.get('children_processed', 0)}/{current.get('children_discovered', 0)}")
        
        if stats['processed_count'] > 0 and stats['total_discovered'] > 0:
            progress_rate = (stats['processed_count'] / stats['total_discovered']) * 100
            print(f"整体进度: {progress_rate:.1f}%")
        
        print("="*60)
    
    def cleanup_progress_file(self):
        """清理进度文件（在成功完成后调用）"""
        try:
            if self.progress_file.exists():
                self.progress_file.unlink()
                self.logger.info("已清理进度文件")
        except Exception as e:
            self.logger.error(f"清理进度文件失败: {e}")

    def get_resume_point(self) -> Optional[Dict[str, Any]]:
        """获取恢复点信息"""
        if self.progress_data['status'] != 'in_progress':
            return None

        return {
            'tree_structure': self.progress_data.get('tree_structure'),
            'processed_urls': self.progress_data['processed_urls'],
            'failed_urls': self.progress_data['failed_urls'],
            'current_processing': self.progress_data.get('current_processing')
        }

    def should_skip_url(self, url: str) -> bool:
        """判断是否应该跳过某个URL的重新处理"""
        return self.is_url_processed(url) or self.is_url_failed(url)

    def should_skip_url_processing_only(self, url: str) -> bool:
        """判断是否应该跳过URL的处理，但仍需要遍历其子节点"""
        return self.is_url_processed(url)

    def get_failed_urls_for_retry(self) -> Set[str]:
        """获取需要重试的失败URL"""
        return self.progress_data['failed_urls'].copy()

    def clear_failed_url(self, url: str):
        """清除失败URL标记（用于重试）"""
        self.progress_data['failed_urls'].discard(url)
        if self.progress_data['statistics']['total_failed'] > 0:
            self.progress_data['statistics']['total_failed'] -= 1


class TreeBuildingResumeHelper:
    """树构建恢复助手 - 辅助断点续爬的实现"""

    def __init__(self, progress_manager: TreeBuildingProgressManager, logger: Optional[logging.Logger] = None):
        self.progress_manager = progress_manager
        self.logger = logger or logging.getLogger(__name__)

    def can_resume(self) -> bool:
        """检查是否可以恢复构建"""
        return (self.progress_manager.progress_data['status'] == 'in_progress' and
                len(self.progress_manager.progress_data['processed_urls']) > 0)

    def get_resume_strategy(self) -> str:
        """获取恢复策略"""
        if not self.can_resume():
            return "fresh_start"

        processed_count = len(self.progress_manager.progress_data['processed_urls'])
        failed_count = len(self.progress_manager.progress_data['failed_urls'])

        if processed_count > 100:
            return "resume_from_checkpoint"
        elif failed_count > processed_count * 0.5:
            return "retry_failed_first"
        else:
            return "continue_normal"

    def prepare_resume_data(self) -> Dict[str, Any]:
        """准备恢复所需的数据"""
        resume_point = self.progress_manager.get_resume_point()
        if not resume_point:
            return {}

        return {
            'visited_urls': resume_point['processed_urls'].copy(),
            'tree_structure': resume_point.get('tree_structure'),
            'failed_urls': resume_point['failed_urls'].copy(),
            'current_processing': resume_point.get('current_processing'),
            'strategy': self.get_resume_strategy()
        }

    def merge_tree_structures(self, existing_tree: Dict[str, Any], new_tree: Dict[str, Any]) -> Dict[str, Any]:
        """合并树形结构"""
        if not existing_tree:
            return new_tree
        if not new_tree:
            return existing_tree

        # 简单的合并策略：保留现有结构，添加新的子节点
        merged = existing_tree.copy()

        # 递归合并子节点
        if 'children' in existing_tree and 'children' in new_tree:
            existing_children = {child['url']: child for child in existing_tree['children']}

            for new_child in new_tree['children']:
                child_url = new_child['url']
                if child_url in existing_children:
                    # 递归合并子节点
                    merged_child = self.merge_tree_structures(existing_children[child_url], new_child)
                    existing_children[child_url] = merged_child
                else:
                    # 添加新的子节点
                    existing_children[child_url] = new_child

            merged['children'] = list(existing_children.values())

        return merged
