#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
整合爬虫工具 - 结合树形结构和详细内容提取 + 代理池 + 本地文件存储
将iFixit网站的设备分类以层级树形结构展示，并为每个节点提取详细内容
支持天启IP代理池、本地文件夹存储、媒体文件下载等功能
用法: python auto_crawler.py [URL或设备名]
示例: python auto_crawler.py https://www.ifixit.com/Device/Television
      python auto_crawler.py Television
"""

import os
import sys
import json
import time
import random
import re
import requests
from urllib.parse import urlparse, urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path
import hashlib
import mimetypes
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import queue

# 导入两个基础爬虫
from enhanced_crawler import EnhancedIFixitCrawler
from tree_crawler import TreeCrawler


class ProxyManager:
    """代理管理器 - 从本地proxy.txt文件管理代理池"""

    def __init__(self, proxy_file="proxy.txt", username=None, password=None, max_reset_cycles=3):
        self.proxy_file = proxy_file
        self.username = username
        self.password = password

        self.proxy_pool = []
        self.current_proxy = None
        self.failed_proxies = []
        self.proxy_switch_count = 0
        self.proxy_lock = threading.Lock()

        # 添加重置循环限制
        self.max_reset_cycles = max_reset_cycles
        self.reset_cycle_count = 0

        # 加载代理
        self._load_proxies()

    def _load_proxies(self):
        """从proxy.txt文件加载代理列表"""
        proxy_list = []

        try:
            if not os.path.exists(self.proxy_file):
                print(f"❌ 代理文件不存在: {self.proxy_file}")
                return

            with open(self.proxy_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line in lines:
                line = line.strip()
                if line and ':' in line and not line.startswith('#'):
                    try:
                        # 支持两种格式：
                        # 1. username:password@host:port (带认证)
                        # 2. host:port (无认证)
                        if '@' in line:
                            # 带认证的代理格式
                            auth_part, host_port = line.split('@', 1)
                            username, password = auth_part.split(':', 1)
                            host, port = host_port.split(':', 1)
                            proxy_config = {
                                'http': f"http://{username}:{password}@{host.strip()}:{port.strip()}",
                                'https': f"http://{username}:{password}@{host.strip()}:{port.strip()}"
                            }
                        else:
                            # 无认证的代理格式
                            host, port = line.split(':', 1)
                            if self.username and self.password:
                                # 如果设置了默认认证信息，使用默认认证
                                proxy_config = {
                                    'http': f"http://{self.username}:{self.password}@{host.strip()}:{port.strip()}",
                                    'https': f"http://{self.username}:{self.password}@{host.strip()}:{port.strip()}"
                                }
                            else:
                                # 无认证代理
                                proxy_config = {
                                    'http': f"http://{host.strip()}:{port.strip()}",
                                    'https': f"http://{host.strip()}:{port.strip()}"
                                }
                        proxy_list.append(proxy_config)
                    except ValueError:
                        print(f"⚠️  跳过格式错误的代理: {line}")

            self.proxy_pool = proxy_list
            print(f"📋 从 {self.proxy_file} 加载了 {len(proxy_list)} 个代理")

        except Exception as e:
            print(f"❌ 读取代理文件失败: {e}")

    def get_proxy(self):
        """获取一个可用的代理"""
        with self.proxy_lock:
            # 如果当前代理可用，直接返回
            if self.current_proxy and self.current_proxy not in self.failed_proxies:
                return self.current_proxy

            # 从代理池中选择一个未失效的代理
            available_proxies = []
            for p in self.proxy_pool:
                is_failed = False
                for failed in self.failed_proxies:
                    if p['http'] == failed['http']:
                        is_failed = True
                        break
                if not is_failed:
                    available_proxies.append(p)

            if not available_proxies:
                # 检查是否已达到最大重置次数
                if self.reset_cycle_count >= self.max_reset_cycles:
                    print(f"❌ 已达到最大重置次数({self.max_reset_cycles})，所有代理均不可用")
                    return None

                # 如果所有代理都失效了，重置失效列表，重新开始
                self.reset_cycle_count += 1
                print(f"⚠️  所有代理都已失效，重置代理池... (第{self.reset_cycle_count}/{self.max_reset_cycles}次)")
                self.failed_proxies.clear()
                available_proxies = self.proxy_pool

            if available_proxies:
                self.current_proxy = random.choice(available_proxies)
                self.proxy_switch_count += 1

                # 提取IP和端口用于显示
                proxy_url = self.current_proxy['http']
                if '@' in proxy_url:
                    ip_port = proxy_url.split('@')[1]
                    if ':' in ip_port:
                        display_ip, display_port = ip_port.rsplit(':', 1)
                    else:
                        display_ip, display_port = ip_port, "Unknown"
                else:
                    display_ip, display_port = "Unknown", "Unknown"

                print(f"🔄 切换代理 (第{self.proxy_switch_count}次): {display_ip}:{display_port} [重置周期: {self.reset_cycle_count}/{self.max_reset_cycles}]")

                return self.current_proxy
            else:
                print("❌ 没有可用的代理")
                return None

    def mark_proxy_failed(self, proxy, reason=""):
        """标记代理为失效"""
        with self.proxy_lock:
            # 检查是否已经在失效列表中
            already_failed = False
            for failed in self.failed_proxies:
                if failed['http'] == proxy['http']:
                    already_failed = True
                    break

            if not already_failed:
                self.failed_proxies.append(proxy)

            # 提取IP和端口用于显示
            proxy_url = proxy['http']
            if '@' in proxy_url:
                ip_port = proxy_url.split('@')[1]
                if ':' in ip_port:
                    display_ip, display_port = ip_port.rsplit(':', 1)
                else:
                    display_ip, display_port = ip_port, "Unknown"
            else:
                display_ip, display_port = "Unknown", "Unknown"

            print(f"❌ 代理失效: {display_ip}:{display_port} - {reason}")

            # 如果失效的是当前代理，清除当前代理
            if self.current_proxy == proxy:
                self.current_proxy = None

    def get_stats(self):
        """获取代理池统计信息"""
        return {
            'total_proxies': len(self.proxy_pool),
            'failed_proxies': len(self.failed_proxies),
            'available_proxies': len(self.proxy_pool) - len(self.failed_proxies),
            'switch_count': self.proxy_switch_count,
            'reset_cycles': self.reset_cycle_count,
            'max_reset_cycles': self.max_reset_cycles
        }

    def reset_stats(self):
        """重置统计信息"""
        self.proxy_switch_count = 0
        self.reset_cycle_count = 0
        self.failed_proxies.clear()


class CacheManager:
    """智能缓存管理器 - 优化爬虫重复执行效率"""

    def __init__(self, storage_root, logger=None):
        self.storage_root = Path(storage_root)
        self.logger = logger or logging.getLogger(__name__)
        self.cache_index_file = self.storage_root / "cache_index.json"
        self.cache_index = {}
        self.stats = {
            'total_urls': 0,
            'cached_urls': 0,
            'new_urls': 0,
            'invalid_cache': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        self.load_cache_index()

    def load_cache_index(self):
        """加载缓存索引文件"""
        try:
            if self.cache_index_file.exists():
                with open(self.cache_index_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.cache_index = data.get('entries', {})
                    self.logger.info(f"已加载缓存索引，包含 {len(self.cache_index)} 个条目")
            else:
                self.cache_index = {}
                self.logger.info("缓存索引文件不存在，创建新的索引")
        except Exception as e:
            self.logger.error(f"加载缓存索引失败: {e}")
            self.cache_index = {}

    def save_cache_index(self):
        """保存缓存索引文件"""
        try:
            self.storage_root.mkdir(parents=True, exist_ok=True)
            cache_data = {
                'version': '1.0',
                'last_updated': datetime.now(timezone.utc).isoformat(),
                'entries': self.cache_index
            }
            with open(self.cache_index_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"缓存索引已保存，包含 {len(self.cache_index)} 个条目")
        except Exception as e:
            self.logger.error(f"保存缓存索引失败: {e}")

    def get_url_hash(self, url):
        """生成URL的哈希值作为缓存键"""
        return hashlib.md5(url.encode('utf-8')).hexdigest()

    def is_url_cached_and_valid(self, url, local_path):
        """检查URL是否已缓存且数据有效"""
        url_hash = self.get_url_hash(url)
        self.stats['total_urls'] += 1

        self.logger.info(f"🔍 检查缓存: {url}")
        self.logger.info(f"   URL哈希: {url_hash}")
        self.logger.info(f"   本地路径: {local_path}")

        # 检查缓存索引中是否存在
        if url_hash not in self.cache_index:
            self.logger.info(f"   ❌ 缓存索引中不存在此URL")
            self.stats['new_urls'] += 1
            self.stats['cache_misses'] += 1
            return False

        cache_entry = self.cache_index[url_hash]
        self.logger.info(f"   📋 找到缓存条目: {cache_entry.get('processed_time', 'N/A')}")

        # 检查本地路径是否存在
        if not local_path.exists():
            self.logger.info(f"   ❌ 本地路径不存在: {local_path}")
            self.stats['invalid_cache'] += 1
            self.stats['cache_misses'] += 1
            return False

        # 验证数据完整性
        if not self._validate_cached_data(local_path, cache_entry):
            self.logger.info(f"   ❌ 数据完整性验证失败")
            self.stats['invalid_cache'] += 1
            self.stats['cache_misses'] += 1
            return False

        self.logger.info(f"   ✅ 缓存有效，命中!")
        self.stats['cached_urls'] += 1
        self.stats['cache_hits'] += 1
        return True

    def _validate_cached_data(self, local_path, cache_entry):
        """验证缓存数据的完整性"""
        try:
            self.logger.info(f"   🔍 验证数据完整性...")

            # 检查info.json文件
            info_file = local_path / "info.json"
            if not info_file.exists():
                self.logger.info(f"   ❌ info.json文件不存在")
                return False

            with open(info_file, 'r', encoding='utf-8') as f:
                info_data = json.load(f)

            structure = cache_entry.get('structure', {})
            self.logger.info(f"   📊 预期结构: {structure}")

            # 验证guides目录和文件
            if structure.get('has_guides', False):
                guides_dir = local_path / "guides"
                if not guides_dir.exists():
                    self.logger.info(f"   ❌ guides目录不存在")
                    return False

                guide_files = list(guides_dir.glob("*.json"))
                expected_count = structure.get('guides_count', 0)
                if len(guide_files) != expected_count:
                    self.logger.info(f"   ❌ 指南文件数量不匹配: 期望 {expected_count}, 实际 {len(guide_files)}")
                    return False
                else:
                    self.logger.info(f"   ✅ 指南文件验证通过: {len(guide_files)} 个")

            # 验证troubleshooting目录和文件
            if structure.get('has_troubleshooting', False):
                ts_dir = local_path / "troubleshooting"
                if not ts_dir.exists():
                    self.logger.info(f"   ❌ troubleshooting目录不存在")
                    return False

                ts_files = list(ts_dir.glob("*.json"))
                expected_count = structure.get('troubleshooting_count', 0)
                if len(ts_files) != expected_count:
                    self.logger.info(f"   ❌ 故障排除文件数量不匹配: 期望 {expected_count}, 实际 {len(ts_files)}")
                    return False
                else:
                    self.logger.info(f"   ✅ 故障排除文件验证通过: {len(ts_files)} 个")

            # 验证媒体文件
            if structure.get('has_media', False):
                media_dir = local_path / "media"
                if media_dir.exists():
                    media_files = list(media_dir.glob("*"))
                    if len(media_files) == 0 and structure.get('media_count', 0) > 0:
                        self.logger.info(f"   ❌ 媒体文件缺失")
                        return False
                    else:
                        self.logger.info(f"   ✅ 媒体文件验证通过: {len(media_files)} 个")

            self.logger.info(f"   ✅ 数据完整性验证通过")
            return True

        except Exception as e:
            self.logger.error(f"   ❌ 验证缓存数据时出错: {e}")
            return False

    def add_to_cache(self, url, local_path, guides_count=0, troubleshooting_count=0, media_count=0):
        """添加URL到缓存索引"""
        url_hash = self.get_url_hash(url)

        # 分析本地数据结构
        structure = self._analyze_local_structure(local_path, guides_count, troubleshooting_count, media_count)

        cache_entry = {
            'url': url,
            'local_path': str(local_path.relative_to(self.storage_root)),
            'processed_time': datetime.now(timezone.utc).isoformat(),
            'content_hash': self._generate_content_hash(local_path),
            'structure': structure,
            'status': 'complete'
        }

        self.cache_index[url_hash] = cache_entry
        self.logger.info(f"已添加到缓存: {url}")

    def _analyze_local_structure(self, local_path, guides_count=0, troubleshooting_count=0, media_count=0):
        """分析本地数据结构"""
        structure = {
            'has_guides': False,
            'guides_count': 0,
            'has_troubleshooting': False,
            'troubleshooting_count': 0,
            'has_media': False,
            'media_count': 0
        }

        try:
            # 检查guides目录
            guides_dir = local_path / "guides"
            if guides_dir.exists():
                guide_files = list(guides_dir.glob("*.json"))
                structure['has_guides'] = len(guide_files) > 0
                structure['guides_count'] = len(guide_files)
            elif guides_count > 0:
                structure['has_guides'] = True
                structure['guides_count'] = guides_count

            # 检查troubleshooting目录
            ts_dir = local_path / "troubleshooting"
            if ts_dir.exists():
                ts_files = list(ts_dir.glob("*.json"))
                structure['has_troubleshooting'] = len(ts_files) > 0
                structure['troubleshooting_count'] = len(ts_files)
            elif troubleshooting_count > 0:
                structure['has_troubleshooting'] = True
                structure['troubleshooting_count'] = troubleshooting_count

            # 检查media目录
            media_dir = local_path / "media"
            if media_dir.exists():
                media_files = list(media_dir.glob("*"))
                structure['has_media'] = len(media_files) > 0
                structure['media_count'] = len(media_files)
            elif media_count > 0:
                structure['has_media'] = True
                structure['media_count'] = media_count

        except Exception as e:
            self.logger.error(f"分析本地结构时出错: {e}")

        return structure

    def _generate_content_hash(self, local_path):
        """生成内容哈希值"""
        try:
            info_file = local_path / "info.json"
            if info_file.exists():
                with open(info_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                return hashlib.md5(content.encode('utf-8')).hexdigest()[:16]
        except Exception as e:
            self.logger.error(f"生成内容哈希时出错: {e}")
        return ""

    def get_cache_stats(self):
        """获取缓存统计信息"""
        return self.stats.copy()

    def display_cache_report(self):
        """显示缓存报告"""
        print("\n" + "="*60)
        print("📊 智能缓存报告")
        print("="*60)
        print(f"总URL数量: {self.stats['total_urls']}")
        print(f"缓存命中: {self.stats['cached_urls']} (跳过处理)")
        print(f"需要处理: {self.stats['new_urls']} (新增或更新)")
        print(f"无效缓存: {self.stats['invalid_cache']} (需要重新处理)")

        if self.stats['total_urls'] > 0:
            hit_rate = (self.stats['cached_urls'] / self.stats['total_urls']) * 100
            print(f"缓存命中率: {hit_rate:.1f}%")

        print("="*60)

    def clean_invalid_cache(self):
        """清理无效的缓存条目"""
        invalid_keys = []

        for url_hash, cache_entry in self.cache_index.items():
            local_path = self.storage_root / cache_entry['local_path']
            if not local_path.exists() or not self._validate_cached_data(local_path, cache_entry):
                invalid_keys.append(url_hash)

        for key in invalid_keys:
            del self.cache_index[key]

        if invalid_keys:
            self.logger.info(f"已清理 {len(invalid_keys)} 个无效缓存条目")
            self.save_cache_index()

        return len(invalid_keys)


class CombinedIFixitCrawler(EnhancedIFixitCrawler):
    def __init__(self, base_url="https://www.ifixit.com", verbose=False, use_proxy=True,
                 use_cache=True, force_refresh=False, max_workers=4, max_retries=3,
                 download_videos=False, max_video_size_mb=50):
        super().__init__(base_url, verbose)

        # 立即初始化日志系统，确保logger可用
        self._setup_logging()

        self.tree_crawler = TreeCrawler(base_url)
        self.processed_nodes = set()
        self.target_url = None

        # 本地存储配置（需要在缓存管理器之前设置）
        self.storage_root = "ifixit_data"
        self.media_folder = "media"

        # 缓存配置
        self.use_cache = use_cache
        self.force_refresh = force_refresh
        self.cache_manager = CacheManager(self.storage_root, self.logger) if use_cache else None

        # 代理池配置
        self.use_proxy = use_proxy
        self.proxy_manager = ProxyManager() if use_proxy else None
        self.failed_urls = set()  # 添加失败URL集合

        # 视频处理配置
        self.download_videos = download_videos
        self.max_video_size_mb = max_video_size_mb
        self.video_extensions = ['.mp4', '.mov', '.avi', '.webm', '.mkv', '.flv']

        # 性能统计
        self.stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "retry_success": 0,
            "retry_failed": 0,
            "total_retries": 0,  # 添加缺失的total_retries键
            "media_downloaded": 0,
            "media_failed": 0,
            "videos_skipped": 0,
            "videos_downloaded": 0
        }

        # 并发配置
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.thread_local = threading.local()

        # 错误处理配置
        self.failed_log_file = "failed_urls.log"

        # 打印视频处理配置
        if self.download_videos:
            self.logger.info(f"✅ 视频下载已启用，最大文件大小: {max_video_size_mb}MB")
        else:
            self.logger.info("⚠️ 视频下载已禁用，将保留原始URL")

    def _load_proxy_config(self):
        """加载代理配置"""
        print("📋 使用天启IP代理服务")

        # 天启IP代理认证信息
        self.proxy_username = "yjnvjx"  # 您的天启IP用户名
        self.proxy_password = "gkmb3obc"  # 您的天启IP密码

        self.current_proxy = None
        self.proxy_switch_count = 0
        self.failed_urls = set()

        # 这些配置已在__init__中设置，此处不再重复

        # 初始化日志
        self._setup_logging()

        if self.use_proxy:
            self._init_proxy_pool()

        # 复制树形爬虫的重要方法到当前类
        self.find_exact_path = self.tree_crawler.find_exact_path
        self.extract_breadcrumbs_from_page = self.tree_crawler.extract_breadcrumbs_from_page
        self._build_tree_from_path = self.tree_crawler._build_tree_from_path
        self._find_node_by_url = self.tree_crawler._find_node_by_url
        self.ensure_instruction_url_in_leaf_nodes = self.tree_crawler.ensure_instruction_url_in_leaf_nodes

        # 重写tree_crawler的get_soup方法，让它使用我们的增强版本
        self.tree_crawler.get_soup = self._tree_crawler_get_soup

    def _setup_logging(self):
        """设置日志系统"""
        log_format = '%(asctime)s - %(levelname)s - %(message)s'
        logging.basicConfig(
            level=logging.INFO if self.verbose else logging.WARNING,
            format=log_format,
            handlers=[
                logging.FileHandler('crawler.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def _check_cache_validity(self, url, local_path):
        """检查本地缓存是否有效 - 使用智能缓存管理器"""
        if not self.use_cache or self.force_refresh:
            return False

        # 使用CacheManager进行智能缓存检查
        if self.cache_manager:
            return self.cache_manager.is_url_cached_and_valid(url, local_path)

        # 后备方案：使用原有的简单缓存检查
        return self._legacy_cache_check(url, local_path)

    def _legacy_cache_check(self, url, local_path):
        """原有的缓存检查逻辑（后备方案）"""
        if not local_path.exists():
            return False

        # 检查info.json是否存在
        info_file = local_path / "info.json"
        if not info_file.exists():
            self.logger.info(f"缓存无效: 缺少info.json - {url}")
            return False

        try:
            with open(info_file, 'r', encoding='utf-8') as f:
                info_data = json.load(f)

            # 检查guides目录
            if 'guides' in info_data:
                guides_dir = local_path / "guides"
                if not guides_dir.exists():
                    self.logger.info(f"缓存无效: 缺少guides目录 - {url}")
                    return False

            # 检查troubleshooting目录
            if 'troubleshooting' in info_data:
                ts_dir = local_path / "troubleshooting"
                if not ts_dir.exists():
                    self.logger.info(f"缓存无效: 缺少troubleshooting目录 - {url}")
                    return False

            # 检查media文件
            media_dir = local_path / self.media_folder
            if media_dir.exists():
                # 简单检查：如果media目录存在但为空，可能是下载失败
                media_files = list(media_dir.glob("*"))
                if len(media_files) == 0:
                    # 检查是否应该有媒体文件
                    if self._should_have_media(info_data):
                        self.logger.info(f"缓存无效: media目录为空但应该有媒体文件 - {url}")
                        return False

            self.logger.info(f"✅ 缓存命中，跳过爬取: {url}")
            return True

        except Exception as e:
            self.logger.error(f"缓存检查失败: {e} - {url}")
            return False

    def _should_have_media(self, data):
        """检查数据中是否应该包含媒体文件"""
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ['image', 'video', 'thumbnail', 'photo'] and value:
                    return True
                elif key == 'images' and isinstance(value, list) and value:
                    return True
                elif isinstance(value, (dict, list)):
                    if self._should_have_media(value):
                        return True
        elif isinstance(data, list):
            for item in data:
                if self._should_have_media(item):
                    return True
        return False

    def _log_failed_url(self, url, error, retry_count=0):
        """记录失败的URL到日志文件"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} | {url} | {error} | retry_count: {retry_count}\n"

        try:
            with open(self.failed_log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            self.logger.error(f"无法写入失败日志: {e}")

    def _log_failed_media(self, url, error_msg):
        """记录失败的媒体文件到专门的日志"""
        try:
            failed_media_log = "failed_media.log"
            with open(failed_media_log, 'a', encoding='utf-8') as f:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] {url} - {error_msg}\n")
        except Exception as e:
            self.logger.error(f"无法写入媒体失败日志: {e}")

    def _exponential_backoff(self, attempt):
        """指数退避延迟"""
        delay = min(300, (2 ** attempt) + random.uniform(0, 1))
        time.sleep(delay)
        return delay

    def _is_temporary_error(self, error):
        """判断是否为临时性错误"""
        temporary_errors = [
            "timeout", "connection", "network", "502", "503", "504",
            "429", "500", "ConnectionError", "Timeout", "ReadTimeout"
        ]
        error_str = str(error).lower()
        return any(temp_err in error_str for temp_err in temporary_errors)

    def _retry_with_backoff(self, func, *args, **kwargs):
        """带指数退避的重试机制"""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                result = func(*args, **kwargs)
                if attempt > 0:
                    self.stats["retry_success"] += 1
                    self.logger.info(f"重试成功 (第{attempt+1}次尝试)")
                return result

            except Exception as e:
                last_error = e
                self.stats["total_retries"] += 1

                if not self._is_temporary_error(e):
                    self.logger.error(f"永久性错误，停止重试: {e}")
                    break

                if attempt < self.max_retries - 1:
                    delay = self._exponential_backoff(attempt)
                    self.logger.warning(f"重试 {attempt+1}/{self.max_retries} (延迟{delay:.1f}s): {e}")

                    # 网络错误时切换代理
                    if self.use_proxy and "network" in str(e).lower():
                        self._switch_proxy(f"重试时网络错误: {str(e)}")
                else:
                    self.logger.error(f"重试失败，已达最大重试次数: {e}")

        self.stats["retry_failed"] += 1
        if last_error:
            raise last_error
        else:
            raise Exception("重试失败，未知错误")

    def _init_proxy_pool(self):
        """初始化代理池 - 从天启IP API获取代理"""
        print("=" * 50)
        print("🚀 启动代理池系统")
        print("=" * 50)
        self._get_new_proxy()

    def _get_new_proxy(self):
        """从天启IP API获取新的代理IP"""
        api_url = "http://api.tianqiip.com/getip"
        params = {
            'secret': 'c3ljdpezjim64de5',
            'num': '200',
            'type': 'txt',
            'port': '2',
            'time': '3',
            'mr': '1',
            'sign': '2704663b3f023a2e4097093d70f24acb'
        }

        try:
            print(f"📡 正在从天启IP API获取代理...")
            print(f"🔗 API地址: {api_url}")

            response = requests.get(api_url, params=params, timeout=15)

            if response.status_code == 200:
                proxy_text = response.text.strip()
                print(f"🔍 API响应内容预览: {proxy_text[:200]}...")

                # 解析文本格式的代理列表 (IP:PORT格式)
                proxy_lines = [line.strip() for line in proxy_text.split('\n') if line.strip()]

                if proxy_lines:
                    # 随机选择一个代理
                    import random
                    selected_proxy = random.choice(proxy_lines)

                    if ':' in selected_proxy:
                        proxy_host, proxy_port = selected_proxy.split(':', 1)

                        # 构建带认证的代理配置
                        proxy_meta = f"http://{self.proxy_username}:{self.proxy_password}@{proxy_host}:{proxy_port}"
                        self.current_proxy = {
                            'http': proxy_meta,
                            'https': proxy_meta
                        }

                        self.proxy_switch_count += 1
                        current_time = time.strftime("%Y-%m-%d %H:%M:%S")

                        print("✅ 天启IP代理获取成功!")
                        print(f"🕒 时间: {current_time}")
                        print(f"🌐 代理IP: {proxy_host}")
                        print(f"🔌 端口: {proxy_port}")
                        print(f"🔄 切换次数: 第 {self.proxy_switch_count} 次")
                        print(f"📊 可用代理总数: {len(proxy_lines)}")
                        print("=" * 50)

                        # 代理获取成功

                        return True
                    else:
                        print(f"❌ 代理格式错误: {selected_proxy}")
                else:
                    print("❌ 未获取到有效的代理列表")
            else:
                print(f"❌ HTTP状态码: {response.status_code}")
                print(f"❌ 响应内容: {response.text[:200]}")

        except Exception as e:
            print(f"❌ 获取天启IP代理失败: {e}")

        # API失败时使用演示模式
        print("⚠️  天启IP API调用失败，使用演示模式")
        print("💡 请检查:")
        print("   1. 天启IP账号是否有效")
        print("   2. 账号余额是否充足")
        print("   3. API参数是否正确")
        print("   4. 网络连接是否正常")
        return self._get_demo_proxy()

    def _get_demo_proxy(self):
        """获取模拟代理用于演示"""
        import random

        # 模拟代理IP池
        demo_proxies = [
            {"ip": "192.168.1.100", "port": "8080"},
            {"ip": "10.0.0.50", "port": "3128"},
            {"ip": "172.16.0.25", "port": "8888"},
        ]

        proxy_info = random.choice(demo_proxies)
        proxy_host = proxy_info['ip']
        proxy_port = proxy_info['port']

        # 演示模式也使用认证信息
        proxy_meta = f"http://{self.proxy_username}:{self.proxy_password}@{proxy_host}:{proxy_port}"
        self.current_proxy = {
            'http': proxy_meta,
            'https': proxy_meta
        }

        self.proxy_switch_count += 1
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")

        print("✅ 模拟代理获取成功! (演示模式)")
        print(f"🕒 时间: {current_time}")
        print(f"🌐 代理IP: {proxy_host}")
        print(f"🔌 端口: {proxy_port}")
        print(f"🔄 切换次数: 第 {self.proxy_switch_count} 次")
        print("💡 注意: 这是演示模式，实际使用需要配置真实的天启IP API")
        print("=" * 50)
        return True



    def _get_next_proxy(self):
        """获取当前代理或切换新代理"""
        if not self.use_proxy or not self.proxy_manager:
            return None

        return self.proxy_manager.get_proxy()

    def _switch_proxy(self, reason="请求失败"):
        """切换代理IP"""
        self.logger.warning(f"⚠️  代理切换原因: {reason}")

        if not self.use_proxy or not self.proxy_manager:
            return False

        # 标记当前代理为失效
        current_proxy = self.proxy_manager.current_proxy
        if current_proxy:
            self.proxy_manager.mark_proxy_failed(current_proxy, reason)

        # 获取新代理
        new_proxy = self.proxy_manager.get_proxy()
        return new_proxy is not None

    # 代理池相关方法已集成到ProxyManager类中



    def get_soup(self, url, use_playwright=False):
        """重写get_soup方法，支持代理池、重试机制和Playwright渲染"""
        if not url:
            return None

        if url in self.failed_urls:
            self.logger.warning(f"跳过已知失败URL: {url}")
            return None

        if 'zh.ifixit.com' in url:
            url = url.replace('zh.ifixit.com', 'www.ifixit.com')

        if '?' in url:
            url += '&lang=en'
        else:
            url += '?lang=en'

        self.stats["total_requests"] += 1

        # 如果需要JavaScript渲染，使用Playwright
        if use_playwright:
            return self._retry_with_backoff(self._get_soup_with_playwright, url)

        # 否则使用传统的requests方法
        return self._retry_with_backoff(self._get_soup_requests, url)

    def _get_soup_requests(self, url):
        """使用requests获取页面内容，支持智能代理切换"""
        session = requests.Session()
        retry_strategy = Retry(
            total=1,  # 减少重试次数，避免与上层重试机制冲突
            backoff_factor=1,  # 减少退避因子
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False  # 不在状态码错误时立即抛出异常
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # 获取代理
        proxies = self._get_next_proxy() if self.use_proxy else None

        try:
            response = session.get(
                url,
                headers=self.headers,
                timeout=30,
                proxies=proxies
            )
            response.raise_for_status()

            from bs4 import BeautifulSoup
            return BeautifulSoup(response.content, 'html.parser')

        except (requests.exceptions.ProxyError,
                requests.exceptions.ConnectTimeout,
                requests.exceptions.ConnectionError) as e:
            # 代理相关错误，尝试切换代理
            if self.use_proxy:
                print(f"🔄 代理错误，尝试切换: {str(e)[:100]}")
                if self._switch_proxy(f"代理错误: {str(e)[:50]}"):
                    # 使用新代理重试一次
                    new_proxies = self._get_next_proxy()
                    response = session.get(
                        url,
                        headers=self.headers,
                        timeout=30,
                        proxies=new_proxies
                    )
                    response.raise_for_status()

                    from bs4 import BeautifulSoup
                    return BeautifulSoup(response.content, 'html.parser')
            # 如果切换代理失败或不使用代理，重新抛出异常
            raise

    def _get_soup_with_playwright(self, url):
        """使用Playwright获取JavaScript渲染后的页面内容"""
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                # 设置请求头
                page.set_extra_http_headers({
                    'Accept-Language': 'en-US,en;q=0.9',
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                })

                # 导航到页面并等待加载
                page.goto(url, wait_until='networkidle')

                # 获取页面内容
                content = page.content()
                browser.close()

                from bs4 import BeautifulSoup
                return BeautifulSoup(content, 'html.parser')

        except Exception as e:
            print(f"Playwright获取页面失败 {url}: {e}")
            self.failed_urls.add(url)
            return None

    def _create_local_directory(self, path):
        """创建本地目录结构"""
        full_path = Path(self.storage_root) / path
        full_path.mkdir(parents=True, exist_ok=True)
        return full_path

    def _get_file_size_from_url(self, url):
        """获取URL文件的大小（MB）"""
        try:
            # 修复URL格式：将.thumbnail.medium替换为.medium，解决403 Forbidden问题
            if '.thumbnail.medium' in url:
                url = url.replace('.thumbnail.medium', '.medium')

            # 使用与下载相同的请求头
            media_headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://www.ifixit.com/",
                "Origin": "https://www.ifixit.com",
                "Sec-Fetch-Dest": "image",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "same-site",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache"
            }

            proxies = self._get_next_proxy() if self.use_proxy else None
            response = requests.head(url, headers=media_headers, timeout=10, proxies=proxies)
            if response.status_code == 200:
                content_length = response.headers.get('content-length')
                if content_length:
                    size_bytes = int(content_length)
                    size_mb = size_bytes / (1024 * 1024)
                    return size_mb
        except Exception as e:
            self.logger.warning(f"无法获取文件大小 {url}: {e}")
        return None

    def _is_video_file(self, url):
        """检查URL是否为视频文件"""
        if not url:
            return False
        url_path = url.split('?')[0].lower()
        return any(url_path.endswith(ext) for ext in self.video_extensions)

    def _download_media_file(self, url, local_dir, filename=None):
        """下载媒体文件到本地（带重试机制和视频处理策略，支持跨页面去重）"""
        if not url or not url.startswith('http'):
            return None

        # 先计算文件名和本地路径，用于检查文件是否已存在
        if not filename:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            url_path = url.split('?')[0]
            if '.' in url_path:
                ext = '.' + url_path.split('.')[-1].lower()
                if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.mov', '.avi']:
                    ext = '.jpg'
            else:
                ext = '.jpg'
            filename = f"{url_hash}{ext}"

        local_path = local_dir / self.media_folder / filename

        # 检查是否是troubleshooting目录，如果是则不使用跨页面去重
        is_troubleshooting = "troubleshooting" in str(local_dir)

        if not is_troubleshooting:
            # 检查文件是否已存在（支持跨页面去重）
            existing_file_path = self._find_existing_media_file(url, filename)
            if existing_file_path:
                # 文件已存在于其他位置，返回相对于当前目录的路径
                if self.verbose:
                    self.logger.info(f"媒体文件已存在，跳过下载: {filename}")
                else:
                    # 静默跳过，不显示消息避免日志过多
                    pass
                self.stats["media_downloaded"] += 1
                return existing_file_path

        # 如果文件在当前目录已存在，直接返回路径
        if local_path.exists():
            if self.verbose:
                self.logger.info(f"媒体文件已存在于当前目录: {filename}")
            self.stats["media_downloaded"] += 1
            # 对于troubleshooting目录，返回相对于troubleshooting目录的路径
            if is_troubleshooting:
                return str(local_path.relative_to(local_dir))
            else:
                # 计算相对路径，如果local_dir不是storage_root的子目录，则使用local_dir作为基准
                try:
                    return str(local_path.relative_to(Path(self.storage_root)))
                except ValueError:
                    # 如果不在storage_root下，返回相对于local_dir的路径
                    return str(local_path.relative_to(local_dir))

        # 检查是否为视频文件
        if self._is_video_file(url):
            if not self.download_videos:
                self.logger.info(f"跳过视频下载（已禁用）: {url}")
                self.stats["videos_skipped"] += 1
                return url

            # 检查视频文件大小
            file_size_mb = self._get_file_size_from_url(url)
            if file_size_mb and file_size_mb > self.max_video_size_mb:
                self.logger.warning(f"跳过大视频文件 ({file_size_mb:.1f}MB > {self.max_video_size_mb}MB): {url}")
                self.stats["videos_skipped"] += 1
                return url

            self.logger.info(f"准备下载视频文件 ({file_size_mb:.1f}MB): {url}")

        try:
            result = self._retry_with_backoff(self._download_media_file_impl, url, local_dir, filename)
            if self._is_video_file(url) and result != url:
                self.stats["videos_downloaded"] += 1
            return result
        except Exception as e:
            self.logger.error(f"媒体文件下载最终失败 {url}: {e}")
            self.stats["media_failed"] += 1
            self._log_failed_url(url, f"媒体下载失败: {str(e)}")
            # 记录失败的媒体文件到专门的日志
            self._log_failed_media(url, str(e))
            return url

    def _find_existing_media_file(self, url, filename):
        """查找是否已存在相同的媒体文件（跨页面去重）"""
        try:
            # 基于URL的MD5哈希来查找文件
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]

            # 在整个storage_root目录下搜索具有相同哈希的文件
            storage_path = Path(self.storage_root)
            if not storage_path.exists():
                return None

            # 搜索所有media目录下的文件
            for media_dir in storage_path.rglob("media"):
                if media_dir.is_dir():
                    # 查找具有相同哈希前缀的文件
                    for existing_file in media_dir.glob(f"{url_hash}.*"):
                        if existing_file.is_file():
                            # 返回相对于storage_root的路径
                            return str(existing_file.relative_to(storage_path))

            return None

        except Exception as e:
            if self.verbose:
                self.logger.warning(f"查找已存在媒体文件时出错: {e}")
            return None

    def _download_media_file_impl(self, url, local_dir, filename):
        """媒体文件下载的具体实现"""
        local_path = local_dir / self.media_folder / filename
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # 修复URL格式：将.thumbnail.medium替换为.medium，解决403 Forbidden问题
        if '.thumbnail.medium' in url:
            url = url.replace('.thumbnail.medium', '.medium')
            if self.verbose:
                self.logger.info(f"URL格式修复: .thumbnail.medium -> .medium")

        # 为媒体文件下载创建专门的请求头
        media_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.ifixit.com/",
            "Origin": "https://www.ifixit.com",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-site",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }

        proxies = self._get_next_proxy() if self.use_proxy else None
        response = requests.get(url, headers=media_headers, timeout=30, proxies=proxies)
        response.raise_for_status()

        with open(local_path, 'wb') as f:
            f.write(response.content)

        self.stats["media_downloaded"] += 1
        if self.verbose:
            self.logger.info(f"媒体文件下载成功: {filename}")
        else:
            # 简化的进度提示
            if self.stats["media_downloaded"] % 10 == 0:
                print(f"      📥 已下载 {self.stats['media_downloaded']} 个媒体文件...")

        # 检查是否是troubleshooting目录，如果是则返回相对于troubleshooting目录的路径
        is_troubleshooting = "troubleshooting" in str(local_dir)
        if is_troubleshooting:
            return str(local_path.relative_to(local_dir))
        else:
            # 计算相对路径，如果local_dir不是storage_root的子目录，则使用local_dir作为基准
            try:
                return str(local_path.relative_to(Path(self.storage_root)))
            except ValueError:
                # 如果不在storage_root下，返回相对于local_dir的路径
                return str(local_path.relative_to(local_dir))

    def _process_media_urls(self, data, local_dir):
        """递归处理数据中的媒体URL，下载并替换为本地路径"""
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ['image', 'video', 'thumbnail', 'photo'] and isinstance(value, str) and value.startswith('http'):
                    data[key] = self._download_media_file(value, local_dir)
                elif key == 'images' and isinstance(value, list):
                    for i, img_item in enumerate(value):
                        if isinstance(img_item, str) and img_item.startswith('http'):
                            # 直接是URL字符串
                            value[i] = self._download_media_file(img_item, local_dir)
                        elif isinstance(img_item, dict) and 'url' in img_item:
                            # 是包含url字段的字典
                            img_url = img_item['url']
                            if isinstance(img_url, str) and img_url.startswith('http'):
                                img_item['url'] = self._download_media_file(img_url, local_dir)
                elif key == 'videos' and isinstance(value, list):
                    for i, video_item in enumerate(value):
                        if isinstance(video_item, str) and video_item.startswith('http'):
                            # 直接是URL字符串
                            if self.download_videos:
                                value[i] = self._download_media_file(video_item, local_dir)
                        elif isinstance(video_item, dict) and 'url' in video_item:
                            # 是包含url字段的字典
                            video_url = video_item['url']
                            if isinstance(video_url, str) and video_url.startswith('http'):
                                if self.download_videos:
                                    video_item['url'] = self._download_media_file(video_url, local_dir)
                elif isinstance(value, (dict, list)):
                    self._process_media_urls(value, local_dir)
        elif isinstance(data, list):
            for item in data:
                self._process_media_urls(item, local_dir)

    def _tree_crawler_get_soup(self, url):
        """为tree_crawler提供的get_soup方法，在需要面包屑导航时使用Playwright"""
        # 对于需要提取面包屑导航的页面，使用Playwright
        if '/Teardown/' in url or '/Guide/' in url or '/Device/' in url:
            return self.get_soup(url, use_playwright=True)
        else:
            return self.get_soup(url, use_playwright=False)

    def extract_real_name_from_url(self, url):
        """
        从URL中提取真实的name字段（URL路径的最后一个标识符）
        """
        if not url:
            return ""

        # 移除查询参数和锚点
        clean_url = url.split('?')[0].split('#')[0]

        # 移除末尾的斜杠
        clean_url = clean_url.rstrip('/')

        # 提取最后一个路径段
        path_parts = clean_url.split('/')
        if path_parts:
            name = path_parts[-1]
            # URL解码
            import urllib.parse
            name = urllib.parse.unquote(name)
            # 修复引号编码问题：将 \" 转换为 "
            name = name.replace('\\"', '"')
            return name

        return ""

    def extract_real_title_from_page(self, soup):
        """
        从页面HTML中提取真实的title字段
        """
        if not soup:
            return ""

        # 优先从h1标签提取
        h1_elem = soup.select_one("h1")
        if h1_elem:
            title = h1_elem.get_text().strip()
            if title:
                return title

        # 其次从title标签提取
        title_elem = soup.select_one("title")
        if title_elem:
            title = title_elem.get_text().strip()
            # 移除常见的网站后缀
            title = title.replace(" - iFixit", "").replace(" | iFixit", "").strip()
            if title:
                return title

        return ""

    def extract_real_title_from_page(self, soup):
        """从页面HTML中提取真实的title字段"""
        if not soup:
            return ""

        h1_elem = soup.select_one("h1")
        if h1_elem:
            title = h1_elem.get_text().strip()
            if title:
                return title

        title_elem = soup.select_one("title")
        if title_elem:
            title = title_elem.get_text().strip()
            title = title.replace(" - iFixit", "").replace(" | iFixit", "").strip()
            if title:
                return title

        return ""

    # 第一个extract_real_view_statistics方法已移除，使用下面的实现

    def _is_specified_target_url(self, url):
        """
        检查URL是否是用户指定的目标URL
        """
        if not self.target_url or not url:
            return False

        # 标准化URL进行比较
        def normalize_url(u):
            import urllib.parse
            # URL解码，然后标准化
            decoded = urllib.parse.unquote(u)
            return decoded.rstrip('/').lower()

        return normalize_url(url) == normalize_url(self.target_url)

    def discover_subcategories_from_page(self, soup, base_url):
        """
        动态发现页面中的子类别链接
        """
        if not soup:
            return []

        subcategories = []

        # 查找设备类别链接的多种选择器
        category_selectors = [
            'a[href*="/Device/"]',  # 包含/Device/的链接
            '.category-link',       # 类别链接类
            '.device-link',         # 设备链接类
            '.subcategory',         # 子类别类
            'a[href^="/Device/"]'   # 以/Device/开头的链接
        ]

        found_links = set()

        for selector in category_selectors:
            links = soup.select(selector)
            for link in links:
                href = link.get('href', '')
                if href and '/Device/' in href:
                    # 构建完整URL
                    if href.startswith('/'):
                        full_url = f"{self.base_url}{href}"
                    elif href.startswith('http'):
                        full_url = href
                    else:
                        continue

                    # 过滤掉不需要的链接
                    skip_patterns = [
                        '/Guide/', '/Troubleshooting/', '/Edit/', '/History/',
                        '/Answers/', '?revision', 'action=edit', 'action=create'
                    ]

                    if not any(pattern in full_url for pattern in skip_patterns):
                        # 确保这是一个子类别（URL比当前页面更深一层）
                        if full_url != base_url and full_url not in found_links:
                            # 提取链接文本作为名称
                            link_text = link.get_text().strip()
                            if link_text:
                                subcategories.append({
                                    'name': self.extract_real_name_from_url(full_url),
                                    'url': full_url,
                                    'title': link_text
                                })
                                found_links.add(full_url)

        return subcategories

    def extract_real_view_statistics(self, soup, url):
        """
        从页面HTML中提取真实的浏览统计数据
        """
        if not soup:
            return {}

        stats = {}

        # 查找统计数据的各种可能位置
        stat_selectors = [
            '.view-count',
            '.stats-item',
            '.view-stats',
            '[data-stats]',
            '.page-stats'
        ]

        for selector in stat_selectors:
            elements = soup.select(selector)
            for elem in elements:
                text = elem.get_text().strip()
                # 解析统计数据格式
                if 'past 24 hours' in text.lower() or '24h' in text.lower():
                    # 提取数字
                    import re
                    numbers = re.findall(r'[\d,]+', text)
                    if numbers:
                        stats['past_24_hours'] = numbers[0]
                elif 'past 7 days' in text.lower() or '7d' in text.lower():
                    numbers = re.findall(r'[\d,]+', text)
                    if numbers:
                        stats['past_7_days'] = numbers[0]
                elif 'past 30 days' in text.lower() or '30d' in text.lower():
                    numbers = re.findall(r'[\d,]+', text)
                    if numbers:
                        stats['past_30_days'] = numbers[0]
                elif 'all time' in text.lower() or 'total' in text.lower():
                    numbers = re.findall(r'[\d,]+', text)
                    if numbers:
                        stats['all_time'] = numbers[0]

        # 如果没有找到统计数据，尝试从API或其他位置获取
        if not stats:
            # 尝试从页面的JavaScript数据中提取
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string:
                    script_content = script.string
                    if 'viewCount' in script_content or 'statistics' in script_content:
                        import re
                        # 查找可能的统计数据
                        view_matches = re.findall(r'"viewCount[^"]*":\s*"?(\d+[,\d]*)"?', script_content)
                        if view_matches:
                            stats['all_time'] = view_matches[0]

        return stats

    def build_correct_url_from_path(self, base_url, path_segments):
        """
        根据路径段正确构建URL，而不是简单拼接
        """
        if not path_segments:
            return base_url

        # 从base_url开始，逐步替换路径段
        current_url = base_url

        for segment in path_segments:
            # 获取当前URL的路径部分
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(current_url)
            path_parts = [p for p in str(parsed.path).split('/') if p]

            # 添加新的路径段
            path_parts.append(str(segment))

            # 重新构建URL
            new_path = '/' + '/'.join(path_parts)
            new_parsed = parsed._replace(path=new_path)
            current_url = urlunparse(new_parsed)

        return current_url

    def restructure_target_content(self, node, is_target_page=False):
        """
        重构目标文件的内容结构，使用guides[]和troubleshooting[]而非children[]
        """
        if not node or not isinstance(node, dict):
            return node

        # 如果这是目标页面且有children包含guides和troubleshooting
        if is_target_page and 'children' in node and node['children']:
            guides = []
            troubleshooting = []
            real_children = []

            for child in node['children']:
                if 'steps' in child and 'title' in child:
                    # 这是一个指南
                    guide_data = {k: v for k, v in child.items() if k not in ['children']}
                    guides.append(guide_data)
                elif 'causes' in child and 'title' in child:
                    # 这是一个故障排除
                    ts_data = {k: v for k, v in child.items() if k not in ['children']}
                    troubleshooting.append(ts_data)
                else:
                    # 这是真正的子类别
                    real_children.append(child)

            # 重构节点
            if guides:
                node['guides'] = guides
            if troubleshooting:
                node['troubleshooting'] = troubleshooting

            # 只有真正的子类别才保留在children中
            if real_children:
                node['children'] = real_children
            else:
                # 如果没有真正的子类别，移除children字段
                if 'children' in node:
                    del node['children']

        return node

    def fix_node_data(self, node, soup=None):
        """修复节点的name字段，只在最终产品页面添加其他字段"""
        if not node or not isinstance(node, dict):
            return node

        url = node.get('url', '')
        is_root_device = url == f"{self.base_url}/Device"

        # 所有节点都修复name字段
        real_name = self.extract_real_name_from_url(url)
        if real_name:
            node['name'] = real_name

        # 只有在deep_crawl_product_content中被识别为目标页面时才添加其他字段
        # 这里不添加title、instruction_url、view_statistics等字段
        # 这些字段将在deep_crawl_product_content方法中添加

        return node

    def extract_what_you_need_enhanced(self, guide_url):
        """
        增强版"What You Need"部分提取方法，确保真实页面访问和数据完整性
        """
        if not guide_url:
            return {}

        print(f"    增强提取What You Need: {guide_url}")

        try:
            # 使用Playwright获取完整渲染的页面
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                # 设置请求头确保英文内容
                page.set_extra_http_headers({
                    'Accept-Language': 'en-US,en;q=0.9',
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                })

                # 导航到页面并等待完全加载
                page.goto(guide_url, wait_until='networkidle')
                page.wait_for_timeout(5000)  # 增加等待时间确保完全加载

                # 获取页面HTML
                html_content = page.content()
                browser.close()

                # 解析HTML
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_content, 'html.parser')

                # 尝试多种方法提取"What You Need"数据
                what_you_need = {}

                # 方法1：从React组件的data-props中提取（最准确）
                what_you_need = self._extract_from_react_props_enhanced(soup)

                # 方法2：如果React方法失败，尝试从页面的What You Need区域提取
                if not what_you_need:
                    what_you_need = self._extract_from_what_you_need_section(soup)

                # 方法3：如果仍然失败，尝试从页面的产品链接提取
                if not what_you_need:
                    what_you_need = self._extract_from_product_links(soup)

                # 方法4：最后尝试从页面文本中提取
                if not what_you_need:
                    what_you_need = self._extract_from_page_text(soup)

                if what_you_need:
                    print(f"    成功提取到: {list(what_you_need.keys())}")
                    # 验证数据完整性
                    total_items = sum(len(items) if isinstance(items, list) else 1
                                    for items in what_you_need.values())
                    print(f"    总计项目数: {total_items}")
                else:
                    print(f"    未找到What You Need数据")

                return what_you_need

        except Exception as e:
            print(f"    增强提取失败: {str(e)}")
            return {}

    def _extract_from_react_props_enhanced(self, soup):
        """从React组件的data-props中提取What you need数据（增强版）"""
        what_you_need = {}

        try:
            # 查找多种可能的React组件
            component_selectors = [
                'div[data-name="GuideTopComponent"]',
                'div[data-name="GuideComponent"]',
                'div[data-name="WhatYouNeedComponent"]',
                'div[data-props*="tools"]',
                'div[data-props*="parts"]',
                'div[data-props*="kits"]',
                'div[data-props*="materials"]'
            ]

            for selector in component_selectors:
                component = soup.select_one(selector)
                if component:
                    data_props = component.get('data-props')
                    if data_props:
                        try:
                            import json
                            import html

                            # HTML解码并解析JSON
                            decoded_props = html.unescape(data_props)
                            props_data = json.loads(decoded_props)

                            # 提取productData
                            product_data = props_data.get('productData', {})

                            # 提取Fix Kits/Parts
                            kits = product_data.get('kits', [])
                            if kits:
                                fix_kits = []
                                parts = []
                                materials = []
                                for kit in kits:
                                    name = kit.get('name', '').strip()
                                    if name:
                                        name = self.clean_product_name(name)
                                        if name:
                                            if 'kit' in name.lower() or 'fix kit' in name.lower():
                                                fix_kits.append(name)
                                            elif 'material' in name.lower():
                                                materials.append(name)
                                            else:
                                                parts.append(name)

                                if fix_kits:
                                    what_you_need['Fix Kits'] = fix_kits
                                if parts:
                                    what_you_need['Parts'] = parts
                                if materials:
                                    what_you_need['Materials'] = materials

                            # 提取Tools
                            tools = product_data.get('tools', [])
                            if tools:
                                tool_names = []
                                for tool in tools:
                                    name = tool.get('name', '').strip()
                                    if name:
                                        name = self.clean_product_name(name)
                                        if name:
                                            tool_names.append(name)

                                if tool_names:
                                    what_you_need['Tools'] = tool_names

                            # 提取其他可能的类别
                            for category_key in ['supplies', 'components', 'accessories']:
                                category_items = product_data.get(category_key, [])
                                if category_items:
                                    category_names = []
                                    for item in category_items:
                                        name = item.get('name', '').strip()
                                        if name:
                                            name = self.clean_product_name(name)
                                            if name:
                                                category_names.append(name)

                                    if category_names:
                                        category_title = category_key.title()
                                        what_you_need[category_title] = category_names

                            if what_you_need:
                                break

                        except Exception as e:
                            continue

            return what_you_need

        except Exception as e:
            return what_you_need

    def _extract_from_what_you_need_section(self, soup):
        """从页面的What You Need专门区域提取数据"""
        what_you_need = {}

        try:
            # 查找What You Need标题
            what_you_need_headers = soup.find_all(string=lambda text: text and
                'what you need' in text.lower())

            for header in what_you_need_headers:
                parent = header.parent
                if parent:
                    # 查找父级容器
                    container = parent.find_parent(['div', 'section'])
                    if container:
                        # 查找工具和零件列表
                        lists = container.find_all(['ul', 'ol'])
                        for list_elem in lists:
                            items = list_elem.find_all('li')
                            if items:
                                category_items = []
                                for item in items:
                                    text = item.get_text().strip()
                                    if text and len(text) > 2:
                                        cleaned_text = self.clean_product_name(text)
                                        if cleaned_text:
                                            category_items.append(cleaned_text)

                                if category_items:
                                    # 根据上下文判断类别
                                    context = container.get_text().lower()
                                    if 'tool' in context:
                                        what_you_need['Tools'] = category_items
                                    elif 'part' in context:
                                        what_you_need['Parts'] = category_items
                                    elif 'kit' in context:
                                        what_you_need['Fix Kits'] = category_items
                                    else:
                                        what_you_need['Items'] = category_items
                                    break

                        if what_you_need:
                            break

            return what_you_need

        except Exception:
            return what_you_need

    def _extract_from_product_links(self, soup):
        """从页面的产品链接中提取What You Need数据"""
        what_you_need = {}

        try:
            # 查找产品链接
            product_links = soup.find_all('a', href=lambda x: x and
                any(domain in x for domain in ['ifixit.com/products', 'ifixit.com/store']))

            tools = []
            parts = []
            fix_kits = []

            for link in product_links:
                text = link.get_text().strip()
                if text and len(text) > 2:
                    cleaned_text = self.clean_product_name(text)
                    if cleaned_text:
                        text_lower = cleaned_text.lower()
                        if any(tool_word in text_lower for tool_word in
                               ['screwdriver', 'spudger', 'pick', 'driver', 'tool']):
                            tools.append(cleaned_text)
                        elif any(kit_word in text_lower for kit_word in
                                ['kit', 'set']):
                            fix_kits.append(cleaned_text)
                        else:
                            parts.append(cleaned_text)

            if tools:
                what_you_need['Tools'] = list(dict.fromkeys(tools))  # 去重
            if parts:
                what_you_need['Parts'] = list(dict.fromkeys(parts))
            if fix_kits:
                what_you_need['Fix Kits'] = list(dict.fromkeys(fix_kits))

            return what_you_need

        except Exception:
            return what_you_need

    def _extract_from_html_structure(self, soup):
        """从HTML结构中直接提取What You Need数据"""
        what_you_need = {}

        try:
            # 查找"What You Need"标题
            what_you_need_headers = soup.find_all(string=lambda text: text and
                any(phrase in text.lower() for phrase in ['what you need', 'tools', 'parts', 'materials']))

            for header in what_you_need_headers:
                parent = header.parent
                if parent:
                    # 查找后续的列表或内容
                    next_elements = parent.find_next_siblings(['ul', 'ol', 'div', 'section'])
                    for elem in next_elements:
                        # 提取列表项
                        items = elem.find_all(['li', 'a'])
                        if items:
                            category_items = []
                            for item in items:
                                text = item.get_text().strip()
                                if text and len(text) > 2:
                                    text = self.clean_product_name(text)
                                    if text:
                                        category_items.append(text)

                            if category_items:
                                # 根据内容判断类别
                                header_text = header.lower()
                                if 'tool' in header_text:
                                    what_you_need['Tools'] = category_items
                                elif 'part' in header_text:
                                    what_you_need['Parts'] = category_items
                                elif 'kit' in header_text:
                                    what_you_need['Fix Kits'] = category_items
                                else:
                                    what_you_need['Items'] = category_items
                                break

            return what_you_need

        except Exception:
            return what_you_need

    def _extract_from_page_text(self, soup):
        """从页面文本中提取What You Need数据"""
        what_you_need = {}

        try:
            # 查找包含工具和零件信息的文本
            text_content = soup.get_text()
            lines = text_content.split('\n')

            current_category = None
            items = []

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # 检查是否是类别标题
                line_lower = line.lower()
                if any(keyword in line_lower for keyword in ['tools:', 'parts:', 'materials:', 'what you need:']):
                    if current_category and items:
                        what_you_need[current_category] = items

                    if 'tool' in line_lower:
                        current_category = 'Tools'
                    elif 'part' in line_lower:
                        current_category = 'Parts'
                    elif 'material' in line_lower:
                        current_category = 'Materials'
                    else:
                        current_category = 'Items'

                    items = []

                # 检查是否是项目
                elif current_category and len(line) > 2 and len(line) < 100:
                    cleaned_item = self.clean_product_name(line)
                    if cleaned_item:
                        items.append(cleaned_item)

            # 添加最后一个类别
            if current_category and items:
                what_you_need[current_category] = items

            return what_you_need

        except Exception:
            return what_you_need

    def _extract_troubleshooting_images_from_section(self, section):
        """从troubleshooting section中提取图片，使用enhanced_crawler的过滤逻辑并下载到本地"""
        images = []
        seen_urls = set()

        try:
            if not section:
                if self.verbose:
                    print("❌ Section为空")
                return images

            # 查找该section内的所有图片
            img_elements = section.find_all('img')
            if self.verbose:
                print(f"📷 找到 {len(img_elements)} 个图片元素")

            for img in img_elements:
                try:
                    # 检查是否在商业推广区域内
                    if self._is_element_in_promotional_area(img):
                        if self.verbose:
                            print(f"⏭️ 跳过推广区域图片")
                        continue

                    # 额外检查：检查图片的alt文本是否包含推荐内容特征
                    alt_text = img.get('alt', '').strip().lower()
                    if self._is_recommendation_image_alt(alt_text):
                        if self.verbose:
                            print(f"⏭️ 跳过推荐内容图片: {alt_text}")
                        continue

                    img_src = img.get('src') or img.get('data-src')
                    if img_src and isinstance(img_src, str):
                        # 构建完整URL
                        if img_src.startswith("//"):
                            img_src = "https:" + img_src
                        elif img_src.startswith("/"):
                            img_src = self.base_url + img_src

                        # 使用enhanced_crawler的过滤逻辑
                        if self._is_valid_troubleshooting_image_enhanced(img_src, img):
                            # 确保使用medium尺寸
                            if 'guide-images.cdn.ifixit.com' in img_src and not img_src.endswith('.medium'):
                                # 移除现有的尺寸后缀并添加.medium
                                if '.standard' in img_src or '.large' in img_src or '.small' in img_src:
                                    img_src = img_src.replace('.standard', '.medium').replace('.large', '.medium').replace('.small', '.medium')
                                elif not any(suffix in img_src for suffix in ['.medium', '.jpg', '.png', '.gif']):
                                    img_src += '.medium'

                            # 去重并添加
                            if img_src not in seen_urls:
                                seen_urls.add(img_src)

                                # 获取图片描述（使用原始alt文本，不是小写版本）
                                alt_text = img.get('alt', '').strip()
                                title_text = img.get('title', '').strip()
                                description = alt_text or title_text or "Block Image"

                                # 检查描述是否是商业内容
                                if not self._is_commercial_text(description):
                                    # 在troubleshooting提取阶段，先保存原始URL
                                    # 图片下载将在保存阶段进行，确保下载到正确的目录
                                    images.append({
                                        "url": img_src,  # 保存原始URL，稍后在保存时下载
                                        "description": description
                                    })

                                    if self.verbose:
                                        print(f"✅ 添加图片: {description}")
                                else:
                                    if self.verbose:
                                        print(f"⏭️ 跳过商业描述: {description}")
                            else:
                                if self.verbose:
                                    print(f"⏭️ 跳过重复URL: {img_src}")
                        else:
                            if self.verbose:
                                print(f"⏭️ 跳过无效URL: {img_src}")
                    else:
                        if self.verbose:
                            print(f"⏭️ 跳过无效src")
                except Exception as e:
                    if self.verbose:
                        print(f"❌ 处理图片时出错: {e}")
                    continue

            if self.verbose:
                print(f"📷 最终提取到 {len(images)} 个图片")
            return images

        except Exception as e:
            if self.verbose:
                print(f"❌ 提取图片时出错: {e}")
            return images

    def _remove_promotional_content_from_section(self, section):
        """移除section中的推广内容"""
        try:
            # 移除推广相关的元素
            promotional_selectors = [
                '.promo', '.promotion', '.ad', '.advertisement',
                '.product-card', '.shop-card', '.buy-now',
                '[class*="promo"]', '[class*="shop"]', '[class*="buy"]'
            ]

            for selector in promotional_selectors:
                elements = section.select(selector)
                for elem in elements:
                    elem.decompose()

        except Exception:
            pass

    def _is_valid_troubleshooting_image_enhanced(self, img_src, img_elem=None):
        """判断是否是有效的troubleshooting图片 - 使用enhanced_crawler的逻辑"""
        try:
            if not img_src:
                return False

            img_src_lower = img_src.lower()

            # 过滤掉小图标、logo和商业图片
            skip_keywords = [
                'icon', 'logo', 'flag', 'avatar', 'ad', 'banner',
                'promo', 'cart', 'buy', 'purchase', 'shop', 'header',
                'footer', 'nav', 'menu', 'sidebar'
            ]
            if any(keyword in img_src_lower for keyword in skip_keywords):
                return False

            # 如果有img_elem，检查alt属性
            if img_elem:
                alt_text = img_elem.get('alt', '').lower()
                title_text = img_elem.get('title', '').lower()

                # 排除商业描述
                commercial_keywords = [
                    'buy', 'purchase', 'cart', 'shop', 'price', 'review',
                    'advertisement', 'sponsor'
                ]
                if any(keyword in alt_text or keyword in title_text for keyword in commercial_keywords):
                    return False

                # 过滤装饰性图片
                decorative_alt_keywords = [
                    'decoration', 'ornament', 'divider', 'spacer',
                    'bullet', 'arrow', 'pointer', 'separator'
                ]
                if any(keyword in alt_text for keyword in decorative_alt_keywords):
                    return False

            return True

        except Exception:
            return False



    def _is_valid_troubleshooting_image(self, img_src, img_elem=None):
        """判断是否是有效的troubleshooting图片 - 简化版本，只保留guide-images.cdn.ifixit.com的图片"""
        try:
            if not img_src:
                return False

            img_src_lower = img_src.lower()

            # 只允许来自guide-images.cdn.ifixit.com的图片
            if 'guide-images.cdn.ifixit.com' not in img_src_lower:
                return False

            # 过滤掉明显的装饰性图片和图标
            skip_keywords = [
                'icon', 'logo', 'avatar', 'badge', 'star', 'rating',
                'promo', 'ad', 'banner', 'shop', 'buy', 'cart'
            ]
            if any(keyword in img_src_lower for keyword in skip_keywords):
                return False

            # 如果有img_elem，检查alt属性
            if img_elem:
                alt_text = img_elem.get('alt', '').lower()
                if alt_text:
                    decorative_alt_keywords = [
                        'decoration', 'ornament', 'divider', 'spacer',
                        'bullet', 'arrow', 'pointer', 'separator'
                    ]
                    if any(keyword in alt_text for keyword in decorative_alt_keywords):
                        return False

            return True

        except Exception:
            return False

        except Exception:
            return False

    def _is_element_in_promotional_area(self, element):
        """检查元素是否在推广区域内 - 改进版本，更精确地识别推广容器"""
        try:
            # 向上遍历DOM树检查是否在推广容器中
            current = element
            level = 0
            while current and current.name and level < 5:  # 限制遍历层数
                # 优先通过class名称识别推广容器
                classes = current.get('class', [])
                if isinstance(classes, list):
                    class_str = ' '.join(classes).lower()
                else:
                    class_str = str(classes).lower()

                # 明确的推广容器class名称
                promo_class_keywords = [
                    'guide-recommendation', 'guide-promo', 'view-guide',
                    'product-box', 'product-purchase', 'buy-box', 'purchase-box',
                    'product-card', 'shop-card', 'buy-now',
                    'parts-finder', 'find-parts'
                ]

                # 如果有明确的推广class，直接返回True
                if any(keyword in class_str for keyword in promo_class_keywords):
                    return True

                # 对于没有明确class的元素，使用更严格的文本检测
                # 只有当元素相对较小且明确包含推广内容时才认为是推广容器
                if (level <= 2 and  # 只检查前3层
                    self._is_specific_promotional_container(current)):
                    return True

                current = current.parent
                level += 1
            return False
        except Exception:
            return False

    def _is_specific_promotional_container(self, element):
        """检查是否是特定的推广容器（更严格的检测）"""
        try:
            text = element.get_text().lower()

            # 文本太长的不太可能是推广容器
            if len(text) > 300:
                return False

            # 检查是否包含"View Guide"按钮
            has_view_guide = 'view guide' in text

            # 检查时间格式模式
            import re
            time_pattern = r'\d+\s*(minute|hour)s?(\s*-\s*\d+\s*(minute|hour)s?)?'
            has_time_pattern = bool(re.search(time_pattern, text))

            # 检查难度等级
            difficulty_levels = ['very easy', 'easy', 'moderate', 'difficult', 'very difficult']
            has_difficulty = any(level in text for level in difficulty_levels)

            # 检查指南相关特征
            guide_features = ['how to', 'guide', 'tutorial', 'install', 'replace', 'repair', 'fix']
            has_guide_features = any(feature in text for feature in guide_features)

            # 检查购买相关特征
            purchase_features = ['buy', 'purchase', '$', '€', '£', '¥', 'add to cart', 'shop']
            has_purchase = any(feature in text for feature in purchase_features)

            # 推广容器的判断条件：
            # 1. 包含购买相关内容 OR
            # 2. 包含"View Guide"按钮 OR
            # 3. 同时包含时间模式和难度等级 OR
            # 4. 同时包含时间模式和指南特征
            return (
                has_purchase or
                has_view_guide or
                (has_time_pattern and has_difficulty) or
                (has_time_pattern and has_guide_features)
            )
        except Exception:
            return False

    def _is_recommendation_image_alt(self, alt_text):
        """检查图片的alt文本是否包含推荐内容特征"""
        try:
            if not alt_text:
                return False

            alt_text_lower = alt_text.lower()

            # 精确的推荐指南标题模式 - 更全面的模式匹配
            guide_title_patterns = [
                # 特定模式
                r'how to boot.*into safe mode',
                r'how to use internet recovery',
                r'how to recover data from',
                r'how to install.*to.*ssd',
                r'how to replace.*battery',
                r'how to repair.*screen',
                r'how to fix.*display',
                r'how to troubleshoot',
                r'how to run.*with disk utility',
                r'how to start up.*in.*recovery mode',
                r'how to create a bootable',
                # 通用模式
                r'how to .*removal',
                r'how to .*replace',
                r'how to .*install',
                r'how to .*repair',
                r'how to .*upgrade',
                r'how to .*fix',
                r'replacement.*guide',
                r'repair.*guide',
                r'installation.*guide',
                r'removal.*guide',
                # 特定设备模式
                r'macbook pro.*unibody.*removal',
                r'macbook pro.*key.*removal',
                r'macbook air.*display',
                r'macbook.*retina.*replacement'
            ]

            # 检查精确的推荐指南标题模式
            import re
            for pattern in guide_title_patterns:
                if re.search(pattern, alt_text_lower):
                    return True

            # 检查是否包含指南推荐的关键特征
            recommendation_keywords = [
                'how to use', 'how to install', 'how to replace', 'how to repair',
                'guide', 'tutorial', 'installation', 'replacement', 'repair guide'
            ]

            # 检查是否包含推荐相关的词汇
            has_recommendation_keywords = any(keyword in alt_text_lower for keyword in recommendation_keywords)

            # 检查是否包含设备/产品名称（通常推荐内容会包含具体的设备名）
            device_keywords = ['macbook', 'iphone', 'ipad', 'ssd', 'battery', 'screen', 'display']
            has_device_keywords = any(keyword in alt_text_lower for keyword in device_keywords)

            # 如果同时包含推荐关键词和设备关键词，很可能是推荐内容
            return has_recommendation_keywords and has_device_keywords

        except Exception:
            return False

    def _is_guide_recommendation_container(self, element):
        """检查是否是指南推荐容器 - 改进版本，更精确地识别推荐框"""
        try:
            # 只检查当前元素的直接文本内容，不包括深层子元素
            # 这样可以避免整个文档被误判为推广容器
            if element.name in ['html', '[document]', 'body']:
                return False

            # 检查class属性，优先通过class识别
            classes = element.get('class', [])
            if isinstance(classes, list):
                class_str = ' '.join(classes).lower()
            else:
                class_str = str(classes).lower()

            # 通过class名称快速识别
            guide_class_keywords = [
                'guide-recommendation', 'guide-promo', 'view-guide',
                'recommendation', 'promo-guide', 'guide-card', 'related-guide'
            ]
            if any(keyword in class_str for keyword in guide_class_keywords):
                return True

            text = element.get_text().lower()

            # 如果文本太长，很可能不是推荐框（除非有明确的class标识）
            if len(text) > 500:
                return False

            # 检查是否包含"View Guide"按钮文本
            has_view_guide = 'view guide' in text

            # 检查时间格式模式 (如 "30 minutes - 1 hour", "5 minutes", "2 hours")
            import re
            time_pattern = r'\d+\s*(minute|hour)s?(\s*-\s*\d+\s*(minute|hour)s?)?'
            has_time_pattern = bool(re.search(time_pattern, text))

            # 检查难度等级
            difficulty_levels = ['very easy', 'easy', 'moderate', 'difficult', 'very difficult']
            has_difficulty = any(level in text for level in difficulty_levels)

            # 检查是否包含指南相关的关键词
            guide_keywords = ['how to', 'guide', 'tutorial', 'install', 'replace', 'repair', 'fix']
            has_guide_keywords = any(keyword in text for keyword in guide_keywords)

            # 推荐框的特征：
            # 1. 包含"View Guide"按钮 OR
            # 2. 同时包含时间信息和难度等级 OR
            # 3. 同时包含时间模式和指南关键词
            is_recommendation = (
                has_view_guide or
                (has_time_pattern and has_difficulty) or
                (has_time_pattern and has_guide_keywords)
            )

            # 文本长度限制：推荐框通常比较简洁
            return is_recommendation and len(text) < 400

        except Exception:
            return False

    def _is_product_purchase_container(self, element):
        """检查是否是产品购买容器 - 从enhanced_crawler移植，改进版本"""
        try:
            # 跳过文档级别的元素
            if element.name in ['html', '[document]', 'body']:
                return False

            # 检查class属性，优先通过class识别
            classes = element.get('class', [])
            if isinstance(classes, list):
                class_str = ' '.join(classes).lower()
            else:
                class_str = str(classes).lower()

            # 通过class名称快速识别
            product_class_keywords = [
                'product-box', 'product-purchase', 'buy-box', 'purchase-box',
                'product-card', 'shop-card', 'buy-now'
            ]
            if any(keyword in class_str for keyword in product_class_keywords):
                return True

            text = element.get_text().lower()

            # 如果文本太长，很可能不是购买框
            if len(text) > 400:
                return False

            import re
            has_price = bool(re.search(r'[\$€£¥]\s*\d+\.?\d*', text))
            has_buy = 'buy' in text
            has_reviews = bool(re.search(r'\d+\.?\d*\s*(reviews?|stars?)', text))
            # 购买框通常包含价格、购买按钮或评价信息
            return (has_price or has_buy or has_reviews) and len(text) < 200
        except Exception:
            return False

    def _is_parts_finder_container(self, element):
        """检查是否是配件查找容器 - 从enhanced_crawler移植，改进版本"""
        try:
            # 跳过文档级别的元素
            if element.name in ['html', '[document]', 'body']:
                return False

            text = element.get_text().lower()

            # 如果文本太长，很可能不是配件查找框
            if len(text) > 500:
                return False

            has_parts_text = any(keyword in text for keyword in [
                'find your parts', 'select my model', 'compatible replacement'
            ])
            return has_parts_text and len(text) < 300
        except Exception:
            return False

    def _is_commercial_text(self, text):
        """检查文本是否是商业内容 - 从enhanced_crawler移植"""
        try:
            text_lower = text.lower()
            # 商业内容关键词
            commercial_keywords = [
                'buy', 'purchase', 'view guide', 'find your parts', 'select my model',
                'add to cart', 'quality guarantee', 'compatible replacement'
            ]

            # 检查价格模式
            import re
            if re.search(r'[\$€£¥]\s*\d+\.?\d*', text):
                return True

            # 检查评分模式
            if re.search(r'\d+\.?\d*\s*(reviews?|stars?)', text_lower):
                return True

            # 检查商业关键词
            keyword_count = sum(1 for keyword in commercial_keywords if keyword in text_lower)
            return keyword_count >= 1

        except Exception:
            return False

    def _is_image_in_commercial_area(self, img_elem):
        """检查图片是否在商业区域内"""
        try:
            # 向上查找父元素，检查是否在商业相关的容器中
            current = img_elem
            for _ in range(5):  # 最多向上查找5层
                if not current or not hasattr(current, 'parent'):
                    break

                current = current.parent
                if not current:
                    break

                # 检查class属性
                class_attr = current.get('class', [])
                if isinstance(class_attr, list):
                    class_str = ' '.join(class_attr).lower()
                else:
                    class_str = str(class_attr).lower()

                # 商业区域的class关键词
                commercial_keywords = [
                    'shop', 'store', 'buy', 'purchase', 'cart', 'checkout',
                    'product', 'price', 'sale', 'offer', 'deal', 'promo',
                    'advertisement', 'ad-', 'banner', 'sponsor'
                ]

                if any(keyword in class_str for keyword in commercial_keywords):
                    return True

                # 检查id属性
                id_attr = current.get('id', '')
                if id_attr and any(keyword in id_attr.lower() for keyword in commercial_keywords):
                    return True

            return False
        except Exception:
            return False

    def _is_valid_guide_image(self, img_src, img_elem=None):
        """判断是否是有效的guide图片 - 简化版本，只保留guide-images.cdn.ifixit.com的图片"""
        try:
            if not img_src:
                return False

            img_src_lower = img_src.lower()

            # 只允许来自guide-images.cdn.ifixit.com的图片
            if 'guide-images.cdn.ifixit.com' not in img_src_lower:
                return False

            # 过滤掉明显的装饰性图片
            skip_keywords = ['icon', 'logo', 'avatar', 'badge', 'star', 'rating']
            if any(keyword in img_src_lower for keyword in skip_keywords):
                return False

            return True

        except Exception:
            return False

    def extract_guide_content(self, guide_url):
        """重写父类方法，使用简化的图片过滤逻辑"""
        # 调用父类方法获取基本内容
        guide_data = super().extract_guide_content(guide_url)

        if not guide_data:
            return None

        # 简化图片处理：只确保使用正确的URL格式，不重新提取
        if 'steps' in guide_data and guide_data['steps']:
            for step in guide_data['steps']:
                if 'images' in step and step['images']:
                    filtered_images = []
                    seen_urls = set()

                    for img_src in step['images']:
                        if isinstance(img_src, str) and img_src:
                            # 确保使用完整URL
                            if img_src.startswith("//"):
                                img_src = "https:" + img_src
                            elif img_src.startswith("/"):
                                img_src = self.base_url + img_src

                            # 简单过滤：只保留guide-images.cdn.ifixit.com的图片
                            if self._is_valid_guide_image(img_src):
                                # 确保使用medium尺寸
                                if 'guide-images.cdn.ifixit.com' in img_src and not img_src.endswith('.medium'):
                                    # 移除现有的尺寸后缀并添加.medium
                                    if '.standard' in img_src or '.large' in img_src or '.small' in img_src:
                                        img_src = img_src.replace('.standard', '.medium').replace('.large', '.medium').replace('.small', '.medium')
                                    elif not any(suffix in img_src for suffix in ['.medium', '.jpg', '.png', '.gif']):
                                        img_src += '.medium'

                                # 去重
                                if img_src not in seen_urls:
                                    seen_urls.add(img_src)
                                    filtered_images.append(img_src)

                    step['images'] = filtered_images

        return guide_data

    def clean_product_name(self, text):
        """清理产品名称，移除价格、评分等无关信息"""
        if not text:
            return ""

        # 移除价格信息
        text = re.sub(r'\$[\d.,]+.*$', '', text).strip()
        # 移除评分信息
        text = re.sub(r'[\d.]+\s*out of.*$', '', text).strip()
        text = re.sub(r'Sale price.*$', '', text).strip()
        text = re.sub(r'Rated [\d.]+.*$', '', text).strip()
        # 移除常见的无关词汇
        unwanted_words = ['View', 'view', '查看', 'Add to cart', '添加到购物车', 'Buy', 'Sale', 'Available']
        for word in unwanted_words:
            if text.strip() == word:
                return ""

        # 移除描述性文本
        text = re.sub(r'This kit contains.*$', '', text).strip()
        text = re.sub(r'Available for sale.*$', '', text).strip()

        return text.strip()

    def crawl_combined_tree(self, start_url, category_name=None):
        """
        整合爬取：构建树形结构并为每个节点提取详细内容
        """
        print(f"🚀 开始整合爬取: {start_url}")
        print("=" * 60)

        # 设置目标URL
        self.target_url = start_url

        # 智能缓存预检查
        if self.cache_manager and self.use_cache and not self.force_refresh:
            print("🔍 执行智能缓存预检查...")
            self._perform_cache_precheck(start_url, category_name)
            self.cache_manager.display_cache_report()

        # 第一步：使用 tree_crawler 逻辑构建基础树结构
        print("📊 阶段 1/3: 构建基础树形结构...")
        print("   正在分析页面结构和分类层次...")
        base_tree = self.tree_crawler.crawl_tree(start_url, category_name)

        if not base_tree:
            print("❌ 无法构建基础树结构")
            return None

        print(f"✅ 基础树结构构建完成")
        print("=" * 60)

        # 第二步：为树中的每个节点提取详细内容
        print("📝 阶段 2/3: 为每个节点提取详细内容...")
        print("   正在处理节点基本信息和元数据...")
        enriched_tree = self.enrich_tree_with_detailed_content(base_tree)

        # 第三步：对于产品页面，深入爬取其指南和故障排除内容
        print("🔍 阶段 3/3: 深入爬取产品页面的子内容...")
        print("   正在提取指南和故障排除详细信息...")
        final_tree = self.deep_crawl_product_content(enriched_tree)

        return final_tree

    def _perform_cache_precheck(self, start_url, category_name=None):
        """执行缓存预检查，分析哪些内容需要重新处理"""
        try:
            # 清理无效缓存
            cleaned_count = self.cache_manager.clean_invalid_cache()
            if cleaned_count > 0:
                print(f"   已清理 {cleaned_count} 个无效缓存条目")

            # 这里可以添加更多的预检查逻辑
            # 比如检查目标URL的整体缓存状态
            print("   缓存预检查完成")

        except Exception as e:
            self.logger.error(f"缓存预检查失败: {e}")

    def _get_node_cache_path(self, url, node_name):
        """获取节点的缓存路径，确保与保存时的路径一致"""
        # 首先检查缓存索引中是否有这个URL的记录
        if self.cache_manager:
            url_hash = self.cache_manager.get_url_hash(url)
            if url_hash in self.cache_manager.cache_index:
                cache_entry = self.cache_manager.cache_index[url_hash]
                cached_path = cache_entry.get('local_path', '')
                if cached_path:
                    return Path(self.storage_root) / cached_path

        # 如果缓存中没有记录，使用标准路径构建逻辑
        if '/Device/' in url:
            # 使用与_get_target_root_dir相同的逻辑
            device_path = url.split('/Device/')[-1]
            if '?' in device_path:
                device_path = device_path.split('?')[0]
            device_path = device_path.rstrip('/')

            if device_path:
                import urllib.parse
                device_path = urllib.parse.unquote(device_path)
                return Path(self.storage_root) / "Device" / device_path
            else:
                return Path(self.storage_root) / "Device"
        else:
            # 后备方案：使用节点名称
            safe_name = node_name.replace("/", "_").replace("\\", "_").replace(":", "_")
            return Path(self.storage_root) / safe_name

    def _load_cached_node_data(self, local_path):
        """从缓存加载节点数据"""
        try:
            # 加载基本信息
            info_file = local_path / "info.json"
            if not info_file.exists():
                return None

            with open(info_file, 'r', encoding='utf-8') as f:
                node_data = json.load(f)

            # 加载guides数据
            guides_dir = local_path / "guides"
            if guides_dir.exists():
                guides = []
                for guide_file in sorted(guides_dir.glob("guide_*.json")):
                    with open(guide_file, 'r', encoding='utf-8') as f:
                        guides.append(json.load(f))
                if guides:
                    node_data['guides'] = guides

            # 加载troubleshooting数据
            ts_dir = local_path / "troubleshooting"
            if ts_dir.exists():
                troubleshooting = []
                for ts_file in sorted(ts_dir.glob("troubleshooting_*.json")):
                    with open(ts_file, 'r', encoding='utf-8') as f:
                        troubleshooting.append(json.load(f))
                if troubleshooting:
                    node_data['troubleshooting'] = troubleshooting

            return node_data

        except Exception as e:
            self.logger.error(f"加载缓存数据失败: {e}")
            return None

    def enrich_tree_with_detailed_content(self, node):
        """修复节点的基本数据，确保所有节点都有正确的字段"""
        if not node or not isinstance(node, dict):
            return node

        url = node.get('url', '')
        if not url or url in self.processed_nodes:
            return node

        # 检查缓存 - 使用与保存时一致的路径构建逻辑
        local_path = self._get_node_cache_path(url, node.get('name', 'unknown'))

        if self.verbose:
            print(f"🔍 检查缓存: {url}")
            print(f"   缓存路径: {local_path}")

        if self._check_cache_validity(url, local_path):
            self.stats["cache_hits"] += 1
            if self.verbose:
                print(f"✅ 缓存命中，跳过处理: {node.get('name', '')}")
            else:
                print(f"   ✅ 跳过已缓存: {node.get('name', '')}")
            return node

        self.processed_nodes.add(url)
        self.stats["cache_misses"] += 1

        time.sleep(random.uniform(0.5, 1.0))
        soup = self.get_soup(url)

        # 确保所有节点都经过fix_node_data处理
        node = self.fix_node_data(node, soup)

        if self.verbose:
            self.logger.info(f"处理节点: {node.get('name', '')} - {url}")
        else:
            print(f"   📄 处理节点: {node.get('name', '')}")

        # 递归处理子节点
        if 'children' in node and node['children']:
            children_count = len(node['children'])
            if children_count > 0:
                print(f"   🌳 处理 {children_count} 个子节点...")
            enriched_children = []
            for i, child in enumerate(node['children'], 1):
                if children_count > 1:
                    print(f"      └─ [{i}/{children_count}] {child.get('name', 'Unknown')}")
                enriched_child = self.enrich_tree_with_detailed_content(child)
                if enriched_child:
                    enriched_children.append(enriched_child)
            node['children'] = enriched_children

        return node

    def _process_content_concurrently(self, guide_links, device_url, skip_troubleshooting, soup):
        """并发处理guides和troubleshooting内容"""
        guides_data = []
        troubleshooting_data = []

        # 准备任务列表
        tasks = []

        # 添加guide任务
        for guide_link in guide_links:
            tasks.append(('guide', guide_link))

        # 添加troubleshooting任务
        if not skip_troubleshooting:
            print(f"    🔧 正在搜索故障排除页面...")
            troubleshooting_links = self.extract_troubleshooting_from_device_page(soup, device_url)
            print(f"    🔧 找到 {len(troubleshooting_links)} 个故障排除页面")

            for ts_link in troubleshooting_links:
                if isinstance(ts_link, dict):
                    ts_url = ts_link.get('url', '')
                else:
                    ts_url = ts_link
                if ts_url:
                    tasks.append(('troubleshooting', ts_url))

        # 使用线程池并发处理
        if self.max_workers > 1 and len(tasks) > 1:
            print(f"    🔄 启动并发处理 ({self.max_workers} 线程处理 {len(tasks)} 个任务)...")
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as executor:
                future_to_task = {}
                completed_count = 0
                total_tasks = len(tasks)

                for task_type, url in tasks:
                    if task_type == 'guide':
                        future = executor.submit(self._process_guide_task, url)
                    else:  # troubleshooting
                        future = executor.submit(self._process_troubleshooting_task, url)
                    future_to_task[future] = (task_type, url)

                # 收集结果
                for future in as_completed(future_to_task):
                    task_type, url = future_to_task[future]
                    completed_count += 1
                    try:
                        result = future.result()
                        if result:
                            if task_type == 'guide':
                                guides_data.append(result)
                                print(f"    ✅ [{completed_count}/{total_tasks}] 指南: {result.get('title', '')}")
                            else:
                                troubleshooting_data.append(result)
                                print(f"    ✅ [{completed_count}/{total_tasks}] 故障排除: {result.get('title', '')}")
                        else:
                            print(f"    ⚠️  [{completed_count}/{total_tasks}] {task_type} 处理失败")
                    except Exception as e:
                        print(f"    ❌ [{completed_count}/{total_tasks}] {task_type} 任务失败: {str(e)[:50]}...")
                        self.logger.error(f"并发任务失败 {task_type} {url}: {e}")
        else:
            # 单线程处理
            print(f"    🔄 顺序处理 {len(tasks)} 个任务...")
            for i, (task_type, url) in enumerate(tasks, 1):
                try:
                    print(f"    ⏳ [{i}/{len(tasks)}] 正在处理 {task_type}...")
                    if task_type == 'guide':
                        result = self._process_guide_task(url)
                        if result:
                            guides_data.append(result)
                            print(f"    ✅ [{i}/{len(tasks)}] 指南: {result.get('title', '')}")
                        else:
                            print(f"    ⚠️  [{i}/{len(tasks)}] 指南处理失败")
                    else:
                        result = self._process_troubleshooting_task(url)
                        if result:
                            troubleshooting_data.append(result)
                            print(f"    ✅ [{i}/{len(tasks)}] 故障排除: {result.get('title', '')}")
                        else:
                            print(f"    ⚠️  [{i}/{len(tasks)}] 故障排除处理失败")
                except Exception as e:
                    self.logger.error(f"任务失败 {task_type} {url}: {e}")

        return guides_data, troubleshooting_data

    def _process_guide_task(self, guide_url):
        """处理单个guide任务"""
        try:
            guide_content = self.extract_guide_content(guide_url)
            if guide_content:
                guide_content['url'] = guide_url

                # 确保"What You Need"部分被正确提取
                if 'what_you_need' not in guide_content or not guide_content['what_you_need']:
                    print(f"  重新尝试提取What You Need部分: {guide_url}")
                    what_you_need = self.extract_what_you_need_enhanced(guide_url)
                    if what_you_need:
                        guide_content['what_you_need'] = what_you_need
                        print(f"  成功提取What You Need: {list(what_you_need.keys())}")

                return guide_content
        except Exception as e:
            self.logger.error(f"处理guide失败 {guide_url}: {e}")
            self._log_failed_url(guide_url, f"Guide处理失败: {str(e)}")
        return None

    def _process_troubleshooting_task(self, ts_url):
        """处理单个troubleshooting任务"""
        try:
            ts_content = self.extract_troubleshooting_content(ts_url)
            if ts_content:
                ts_content['url'] = ts_url
                return ts_content
        except Exception as e:
            self.logger.error(f"处理troubleshooting失败 {ts_url}: {e}")
            self._log_failed_url(ts_url, f"Troubleshooting处理失败: {str(e)}")
        return None

    def _print_performance_stats(self):
        """打印性能统计信息"""
        print("\n" + "=" * 60)
        print("📊 性能统计报告")
        print("=" * 60)

        total_requests = self.stats["total_requests"]
        cache_hits = self.stats["cache_hits"]
        cache_misses = self.stats["cache_misses"]

        if total_requests > 0:
            cache_hit_rate = (cache_hits / (cache_hits + cache_misses)) * 100 if (cache_hits + cache_misses) > 0 else 0
            print(f"🌐 总请求数: {total_requests}")
            print(f"💾 缓存命中: {cache_hits} ({cache_hit_rate:.1f}%)")
            print(f"🔄 缓存未命中: {cache_misses}")

        retry_success = self.stats["retry_success"]
        retry_failed = self.stats["retry_failed"]
        total_retries = retry_success + retry_failed

        if total_retries > 0:
            retry_success_rate = (retry_success / total_retries) * 100
            print(f"🔁 重试成功: {retry_success}/{total_retries} ({retry_success_rate:.1f}%)")
            print(f"❌ 重试失败: {retry_failed}")

        media_downloaded = self.stats["media_downloaded"]
        media_failed = self.stats["media_failed"]
        total_media = media_downloaded + media_failed

        if total_media > 0:
            media_success_rate = (media_downloaded / total_media) * 100
            print(f"📁 媒体下载成功: {media_downloaded}/{total_media} ({media_success_rate:.1f}%)")
            print(f"📁 媒体下载失败: {media_failed}")

        # 视频处理统计
        videos_downloaded = self.stats.get("videos_downloaded", 0)
        videos_skipped = self.stats.get("videos_skipped", 0)
        total_videos = videos_downloaded + videos_skipped

        if total_videos > 0:
            print(f"🎥 视频文件处理:")
            print(f"   ✅ 已下载: {videos_downloaded}")
            print(f"   ⏭️ 已跳过: {videos_skipped}")
            if not self.download_videos:
                print(f"   💡 提示: 视频下载已禁用，如需下载请设置 download_videos=True")
            else:
                print(f"   📏 大小限制: {self.max_video_size_mb}MB")

        if self.use_proxy and hasattr(self, 'proxy_switch_count'):
            print(f"🔄 代理切换次数: {self.proxy_switch_count}")

        print("=" * 60)
        


    def count_detailed_nodes(self, node):
        """
        统计树中包含详细内容的节点数量
        """
        count = {'guides': 0, 'troubleshooting': 0, 'products': 0, 'categories': 0}

        # 统计当前节点的guides和troubleshooting数组
        if 'guides' in node and isinstance(node['guides'], list):
            count['guides'] += len(node['guides'])

        if 'troubleshooting' in node and isinstance(node['troubleshooting'], list):
            count['troubleshooting'] += len(node['troubleshooting'])

        # 判断节点类型
        if 'title' in node and 'steps' in node:
            # 这是一个独立的指南节点（不在guides数组中）
            count['guides'] += 1
        elif 'causes' in node:
            # 这是一个独立的故障排除节点（不在troubleshooting数组中）
            count['troubleshooting'] += 1
        elif 'product_name' in node or ('title' in node and 'instruction_url' in node):
            # 产品节点
            count['products'] += 1
        else:
            # 分类节点
            count['categories'] += 1

        # 递归统计子节点
        if 'children' in node and node['children']:
            for child in node['children']:
                child_count = self.count_detailed_nodes(child)
                for key in count:
                    count[key] += child_count[key]

        return count

    def extract_guides_from_device_page(self, soup, device_url):
        """
        从设备页面提取指南链接，改进版本，支持多种页面布局
        """
        guides = []
        seen_guide_urls = set()

        if not soup:
            return guides

        # 查找所有指南链接（包括Guide和Teardown）
        guide_links = soup.select("a[href*='/Guide/'], a[href*='/Teardown/']")

        for link in guide_links:
            href = link.get("href")
            text = link.get_text().strip()

            # 过滤掉不需要的链接
            skip_patterns = [
                "Create Guide", "创建指南", "Guide/new", "Guide/edit", "/edit/",
                "Guide/history", "/history/", "Edit Guide", "编辑指南",
                "Version History", "版本历史", "Teardown/edit", "#comment", "permalink=comment"
            ]

            if href and text and not any(pattern in href or pattern in text for pattern in skip_patterns):
                # 确保使用英文版本的URL
                if href.startswith("/"):
                    href = self.base_url + href
                if 'zh.ifixit.com' in href:
                    href = href.replace('zh.ifixit.com', 'www.ifixit.com')

                # 添加lang=en参数
                if '?' in href:
                    if 'lang=' not in href:
                        href += '&lang=en'
                else:
                    href += '?lang=en'

                if href not in seen_guide_urls:
                    seen_guide_urls.add(href)
                    guides.append({
                        "title": text,
                        "url": href
                    })

        return guides

    def extract_troubleshooting_from_device_page(self, soup, device_url):
        """
        从设备页面提取故障排除链接，改进版本
        """
        troubleshooting_links = []
        seen_ts_urls = set()

        if not soup:
            return troubleshooting_links

        # 查找所有故障排除相关的链接
        # 1. 直接的Troubleshooting链接
        ts_links = soup.select("a[href*='/Troubleshooting/']")

        # 2. 查找包含故障排除文本的链接
        all_links = soup.select("a[href]")
        for link in all_links:
            text = link.get_text().strip().lower()
            href = link.get("href", "")

            # 检查是否是故障排除相关的链接
            troubleshooting_keywords = [
                'troubleshooting', '故障排除', '故障', 'problems', 'issues',
                'won\'t turn on', 'not working', 'broken'
            ]

            if any(keyword in text for keyword in troubleshooting_keywords) or '/Troubleshooting/' in href:
                ts_links.append(link)

        # 处理找到的链接
        for link in ts_links:
            href = link.get("href")
            text = link.get_text().strip()

            if href and text:
                # 确保使用英文版本的URL
                if href.startswith("/"):
                    href = self.base_url + href
                if 'zh.ifixit.com' in href:
                    href = href.replace('zh.ifixit.com', 'www.ifixit.com')

                # 添加lang=en参数
                if '?' in href:
                    if 'lang=' not in href:
                        href += '&lang=en'
                else:
                    href += '?lang=en'

                if href not in seen_ts_urls and '/Troubleshooting/' in href:
                    seen_ts_urls.add(href)
                    troubleshooting_links.append({
                        "title": text,
                        "url": href
                    })

        return troubleshooting_links

    def extract_troubleshooting_content(self, troubleshooting_url):
        """
        提取故障排除页面的详细内容 - 完全按照combined_crawler.py的逻辑
        """
        if not troubleshooting_url:
            return None

        # 确保使用英文版本
        if 'zh.ifixit.com' in troubleshooting_url:
            troubleshooting_url = troubleshooting_url.replace('zh.ifixit.com', 'www.ifixit.com')

        # 添加lang=en参数
        if '?' in troubleshooting_url:
            if 'lang=' not in troubleshooting_url:
                troubleshooting_url += '&lang=en'
        else:
            troubleshooting_url += '?lang=en'

        print(f"Crawling troubleshooting content: {troubleshooting_url}")

        # 添加延迟避免过快请求
        time.sleep(random.uniform(1, 2))

        soup = self.get_soup(troubleshooting_url)
        if not soup:
            return None

        troubleshooting_data = {
            "url": troubleshooting_url,
            "title": "",
            "causes": []
        }

        try:
            # 提取标题
            title_elem = soup.select_one("h1")
            if title_elem:
                title_text = title_elem.get_text().strip()
                title_text = re.sub(r'\s+', ' ', title_text)
                troubleshooting_data["title"] = title_text
                print(f"提取标题: {title_text}")

            # 动态提取页面上的真实字段内容（如first_steps等）
            dynamic_sections = self.extract_dynamic_sections(soup)
            troubleshooting_data.update(dynamic_sections)

            # 提取causes并为每个cause提取对应的图片和视频
            troubleshooting_data["causes"] = self.extract_causes_sections_with_media(soup)

            # 验证是否为有效的故障排除页面
            if not self._is_valid_troubleshooting_page(troubleshooting_data):
                print(f"跳过通用或无效的故障排除页面: {troubleshooting_data.get('title', '')}")
                return None

            # 提取统计数据
            statistics = self.extract_page_statistics(soup)

            # 重构统计数据结构 - 将view_statistics移动到title下面
            # 重新构建troubleshooting_data，确保字段顺序正确
            ordered_ts_data = {}
            ordered_ts_data["url"] = troubleshooting_data["url"]
            ordered_ts_data["title"] = troubleshooting_data["title"]

            # 将统计数据紧跟在title后面（如果有的话）
            if statistics:
                # 创建view_statistics对象，只包含时间相关的统计
                view_stats = {}
                if 'past_24_hours' in statistics:
                    view_stats['past_24_hours'] = statistics['past_24_hours']
                if 'past_7_days' in statistics:
                    view_stats['past_7_days'] = statistics['past_7_days']
                if 'past_30_days' in statistics:
                    view_stats['past_30_days'] = statistics['past_30_days']
                if 'all_time' in statistics:
                    view_stats['all_time'] = statistics['all_time']

                if view_stats:
                    ordered_ts_data["view_statistics"] = view_stats
                if 'completed' in statistics:
                    ordered_ts_data["completed"] = statistics['completed']
                if 'favorites' in statistics:
                    ordered_ts_data["favorites"] = statistics['favorites']

            # 添加动态提取的字段（按页面实际字段名称）
            for key, value in troubleshooting_data.items():
                if key not in ["url", "title", "causes", "images", "videos"] and value:
                    ordered_ts_data[key] = value

            # 添加其他字段
            if "causes" in troubleshooting_data and troubleshooting_data["causes"]:
                ordered_ts_data["causes"] = troubleshooting_data["causes"]

            troubleshooting_data = ordered_ts_data

            # 打印提取结果统计
            dynamic_fields = [k for k in troubleshooting_data.keys()
                            if k not in ['url', 'title', 'causes', 'view_statistics', 'completed', 'favorites']]

            print(f"提取完成:")
            for field in dynamic_fields:
                content = troubleshooting_data.get(field, '')
                if content:
                    print(f"  {field}: {len(content)} 字符")

            causes = troubleshooting_data.get('causes', [])
            print(f"  Causes: {len(causes)} 个")

            # 统计每个cause中的图片和视频数量
            total_images = sum(len(cause.get('images', [])) for cause in causes)
            total_videos = sum(len(cause.get('videos', [])) for cause in causes)
            print(f"  Images (in causes): {total_images} 个")
            print(f"  Videos (in causes): {total_videos} 个")

            if statistics:
                print(f"  Statistics: {len(statistics)} 项")

            return troubleshooting_data

        except Exception as e:
            print(f"提取故障排除内容时发生错误: {str(e)}")
            return None

    def _is_valid_troubleshooting_page(self, troubleshooting_data):
        """验证是否为有效的具体故障排除页面，而不是通用页面"""
        if not troubleshooting_data:
            return False

        title = troubleshooting_data.get('title', '').lower()
        causes = troubleshooting_data.get('causes', [])

        # 检查是否为通用页面的标题
        generic_keywords = [
            'common problems', 'fix common', 'general troubleshooting',
            'troubleshooting guide', 'basic troubleshooting', 'general issues',
            'common issues', 'general problems'
        ]

        for keyword in generic_keywords:
            if keyword in title:
                print(f"检测到通用页面标题关键词: {keyword}")
                return False

        # 检查是否有具体的故障原因
        if not causes or len(causes) == 0:
            print("没有找到具体的故障原因")
            return False

        # 检查causes内容是否足够具体
        if len(causes) < 2:  # 至少要有2个具体的故障原因
            print(f"故障原因太少: {len(causes)} 个")
            return False

        # 检查causes是否有实际内容
        valid_causes = 0
        for cause in causes:
            content = cause.get('content', '')
            if content and len(content.strip()) > 50:  # 内容要足够详细
                valid_causes += 1

        if valid_causes < 2:
            print(f"有效的故障原因太少: {valid_causes} 个")
            return False

        print(f"验证通过: {len(causes)} 个故障原因, {valid_causes} 个有效")
        return True

    def deep_crawl_product_content(self, node, skip_troubleshooting=False):
        """深入爬取产品页面的指南和故障排除内容，并正确构建数据结构"""
        if not node or not isinstance(node, dict):
            return node

        url = node.get('url', '')
        is_specified_target = self._is_specified_target_url(url)

        is_target_page = (
            '/Device/' in url and
            not any(skip in url for skip in ['/Guide/', '/Troubleshooting/', '/Edit/', '/History/', '/Answers/']) and
            (is_specified_target or not node.get('children') or len(node.get('children', [])) == 0)
        )

        if is_target_page:
            # 检查深度内容的缓存
            local_path = self._get_node_cache_path(url, node.get('name', 'unknown'))

            if self.verbose:
                print(f"🔍 检查深度内容缓存: {url}")
                print(f"   缓存路径: {local_path}")

            if self._check_cache_validity(url, local_path):
                if self.verbose:
                    print(f"✅ 深度内容缓存命中，跳过处理: {node.get('name', '')}")
                else:
                    print(f"   ✅ 跳过已缓存的深度内容: {node.get('name', '')}")

                # 从缓存加载数据
                try:
                    cached_node = self._load_cached_node_data(local_path)
                    if cached_node:
                        return cached_node
                except Exception as e:
                    if self.verbose:
                        print(f"   ⚠️ 缓存加载失败，重新处理: {e}")

            if self.verbose:
                print(f"🔄 缓存未命中，开始深度处理: {node.get('name', '')}")
            print(f"🎯 深入爬取目标产品页面: {node.get('name', '')}")
            print(f"   📍 URL: {url}")

            try:
                print(f"   🌐 正在获取页面内容...")
                soup = self.get_soup(url)
                if soup:
                    # 基本数据修复
                    node = self.fix_node_data(node, soup)

                    # 只在目标产品页面添加这些字段
                    is_root_device = url == f"{self.base_url}/Device"
                    if not is_root_device:
                        # 添加title字段
                        real_title = self.extract_real_title_from_page(soup)
                        if real_title:
                            node['title'] = real_title

                        # 添加instruction_url字段
                        node['instruction_url'] = ""

                        # 添加view_statistics字段
                        real_stats = self.extract_real_view_statistics(soup, url)
                        if real_stats:
                            node['view_statistics'] = real_stats

                    print(f"   🔍 正在搜索指南和故障排除内容...")
                    guides = self.extract_guides_from_device_page(soup, url)
                    guide_links = [guide["url"] for guide in guides]
                    print(f"   📖 找到 {len(guide_links)} 个指南")

                    # 使用并发处理guides和troubleshooting
                    print(f"   ⚙️  开始处理详细内容...")
                    guides_data, troubleshooting_data = self._process_content_concurrently(
                        guide_links, url, skip_troubleshooting, soup
                    )

                    if guides_data:
                        node['guides'] = guides_data
                    if troubleshooting_data:
                        node['troubleshooting'] = troubleshooting_data

                    # 处理子类别 - 无论是否为指定目标都要保持层级结构
                    if is_specified_target:
                        # 如果是指定目标，尝试发现新的子类别
                        subcategories = self.discover_subcategories_from_page(soup, url)
                        if subcategories:
                            print(f"  发现 {len(subcategories)} 个子类别，开始处理...")

                            subcategory_children = []
                            for subcat in subcategories:
                                print(f"    处理子类别: {subcat['name']}")

                                subcat_node = {
                                    'name': subcat['name'],
                                    'url': subcat['url'],
                                    'title': subcat['title']
                                }

                                processed_subcat = self.deep_crawl_product_content(subcat_node, skip_troubleshooting=True)
                                if processed_subcat:
                                    subcategory_children.append(processed_subcat)

                            if subcategory_children:
                                node['children'] = subcategory_children
                                print(f"  成功处理 {len(subcategory_children)} 个子类别")

                    # 保持现有的children结构，不要删除层级关系

                    print(f"  总计: {len(guides_data)} 个指南, {len(troubleshooting_data)} 个故障排除")

            except Exception as e:
                print(f"  ✗ 深入爬取时出错: {str(e)}")

        elif 'children' in node and node['children']:
            children_count = len(node['children'])
            if children_count > 0:
                print(f"🔄 递归处理 {children_count} 个子节点...")
            for i, child in enumerate(node['children']):
                if children_count > 1:
                    print(f"   └─ [{i+1}/{children_count}] 处理子节点: {child.get('name', 'Unknown')}")
                node['children'][i] = self.deep_crawl_product_content(child, skip_troubleshooting)

        return node
        
    def _check_target_completeness(self, target_name):
        """检查目标产品目录是否已存在完整的文件结构"""
        if not target_name:
            return False, None

        safe_name = target_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        target_dir = Path(self.storage_root) / f"auto_{safe_name}"

        if not target_dir.exists():
            return False, target_dir

        # 检查基本文件结构
        info_file = target_dir / "info.json"
        if not info_file.exists():
            return False, target_dir

        # 检查是否有guides或troubleshooting目录
        guides_dir = target_dir / "guides"
        troubleshooting_dir = target_dir / "troubleshooting"

        has_content = False
        if guides_dir.exists() and list(guides_dir.glob("*.json")):
            has_content = True
        if troubleshooting_dir.exists() and list(troubleshooting_dir.glob("*.json")):
            has_content = True

        return has_content, target_dir

    def _get_target_root_dir(self, target_url):
        """从目标URL获取真实的设备路径"""
        if not target_url:
            return None

        # 从URL中提取Device后的路径
        if '/Device/' in target_url:
            # 提取Device后面的路径部分
            device_path = target_url.split('/Device/')[-1]
            # 移除查询参数
            if '?' in device_path:
                device_path = device_path.split('?')[0]
            # 移除末尾的斜杠
            device_path = device_path.rstrip('/')

            if device_path:
                # URL解码
                import urllib.parse
                device_path = urllib.parse.unquote(device_path)
                # 构建完整路径：ifixit_data/Device/...
                return Path(self.storage_root) / "Device" / device_path
            else:
                # 如果是根Device页面
                return Path(self.storage_root) / "Device"

        # 如果不是Device URL，使用原来的逻辑作为后备
        safe_name = target_url.replace("/", "_").replace("\\", "_").replace(":", "_")
        return Path(self.storage_root) / "Device" / safe_name

    def save_combined_result(self, tree_data, target_name=None):
        """保存整合结果到真实的设备路径结构"""
        print("   📁 创建目录结构...")

        # 使用目标URL来构建真实路径
        target_url = getattr(self, 'target_url', None)
        if target_url:
            root_dir = self._get_target_root_dir(target_url)
        elif target_name:
            # 如果没有URL，尝试从target_name构建
            if target_name.startswith('http'):
                root_dir = self._get_target_root_dir(target_name)
            else:
                # 假设是设备名称，构建Device路径
                safe_name = target_name.replace("/", "_").replace("\\", "_").replace(":", "_")
                root_dir = Path(self.storage_root) / "Device" / safe_name
        else:
            # 从树数据中提取路径信息
            root_name = tree_data.get("name", "Unknown")
            if " > " in root_name:
                root_name = root_name.split(" > ")[-1]
            safe_name = root_name.replace("/", "_").replace("\\", "_").replace(":", "_")
            root_dir = Path(self.storage_root) / "Device" / safe_name

        if root_dir:
            root_dir.mkdir(parents=True, exist_ok=True)
            print(f"   📂 目标路径: {root_dir}")

            # 保存整个树结构，而不是只保存根节点
            print("   💾 保存内容和下载媒体文件...")
            self._save_tree_structure(tree_data, root_dir)

        print(f"\n📁 整合结果已保存到本地文件夹: {root_dir}")
        return str(root_dir)

    def _save_tree_structure(self, tree_data, base_dir):
        """保存整个树结构到真实的设备路径"""
        if not tree_data or not isinstance(tree_data, dict):
            return

        # 如果是目标节点（有guides或troubleshooting），直接保存
        if tree_data.get('guides') or tree_data.get('troubleshooting'):
            self._save_node_content(tree_data, base_dir)

        # 递归处理子节点
        if 'children' in tree_data and tree_data['children']:
            for child in tree_data['children']:
                # 为子节点创建目录
                child_name = child.get('name', 'Unknown')
                safe_name = child_name.replace("/", "_").replace("\\", "_").replace(":", "_")
                child_dir = base_dir / safe_name

                # 递归保存子节点
                self._save_tree_structure(child, child_dir)

    def _save_node_content(self, node_data, node_dir):
        """保存单个节点的内容（guides和troubleshooting）"""
        if not node_data or not isinstance(node_data, dict):
            return

        # 创建节点目录
        node_dir.mkdir(parents=True, exist_ok=True)

        # 保存节点基本信息
        info_data = {k: v for k, v in node_data.items()
                    if k not in ['children', 'guides', 'troubleshooting']}

        if info_data:
            info_file = node_dir / "info.json"
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(info_data, f, ensure_ascii=False, indent=2)

        # 处理guides
        if 'guides' in node_data and node_data['guides']:
            guides_dir = node_dir / "guides"
            guides_dir.mkdir(exist_ok=True)
            # 确保media文件夹存在
            guides_media_dir = guides_dir / "media"
            guides_media_dir.mkdir(exist_ok=True)

            for i, guide in enumerate(node_data['guides']):
                guide_data = guide.copy()
                self._process_media_urls(guide_data, guides_dir)  # 使用guides目录的media文件夹
                guide_file = guides_dir / f"guide_{i+1}.json"
                with open(guide_file, 'w', encoding='utf-8') as f:
                    json.dump(guide_data, f, ensure_ascii=False, indent=2)

        # 处理troubleshooting
        if 'troubleshooting' in node_data and node_data['troubleshooting']:
            ts_dir = node_dir / "troubleshooting"
            ts_dir.mkdir(exist_ok=True)
            # 确保media文件夹存在
            ts_media_dir = ts_dir / "media"
            ts_media_dir.mkdir(exist_ok=True)

            for i, ts in enumerate(node_data['troubleshooting']):
                ts_data = ts.copy()
                self._process_media_urls(ts_data, ts_dir)  # 使用troubleshooting目录的media文件夹
                ts_file = ts_dir / f"troubleshooting_{i+1}.json"
                with open(ts_file, 'w', encoding='utf-8') as f:
                    json.dump(ts_data, f, ensure_ascii=False, indent=2)

        # 更新缓存索引
        self._update_cache_for_node(node_data, node_dir)

    def _update_cache_for_node(self, node_data, node_dir):
        """为节点更新缓存索引"""
        if not self.cache_manager or not node_data:
            return

        url = node_data.get('url', '')
        if not url:
            return

        try:
            # 统计内容数量
            guides_count = len(node_data.get('guides', []))
            troubleshooting_count = len(node_data.get('troubleshooting', []))

            # 统计媒体文件数量
            media_count = 0
            media_dir = node_dir / "media"
            if media_dir.exists():
                media_count = len(list(media_dir.glob("*")))

            # 添加到缓存
            self.cache_manager.add_to_cache(
                url, node_dir,
                guides_count=guides_count,
                troubleshooting_count=troubleshooting_count,
                media_count=media_count
            )

        except Exception as e:
            self.logger.error(f"更新缓存索引失败: {e}")

    def _save_target_content_to_root(self, tree_data, root_dir):
        """将目标产品内容直接保存到根目录，优化目录结构"""
        if not tree_data or not isinstance(tree_data, dict):
            return

        # 复制数据并处理媒体URL
        node_data = tree_data.copy()
        self._process_media_urls(node_data, root_dir)

        # 保存主要信息到根目录的info.json
        info_data = {k: v for k, v in node_data.items()
                    if k not in ['children', 'guides', 'troubleshooting']}

        info_file = root_dir / "info.json"
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(info_data, f, ensure_ascii=False, indent=2)

        # 处理guides - 直接保存到根目录的guides文件夹
        if 'guides' in node_data and node_data['guides']:
            guides_dir = root_dir / "guides"
            guides_dir.mkdir(exist_ok=True)
            # 确保media文件夹存在
            guides_media_dir = guides_dir / "media"
            guides_media_dir.mkdir(exist_ok=True)

            for i, guide in enumerate(node_data['guides']):
                guide_data = guide.copy()
                self._process_media_urls(guide_data, guides_dir)  # 使用guides目录的media文件夹
                guide_file = guides_dir / f"guide_{i+1}.json"
                with open(guide_file, 'w', encoding='utf-8') as f:
                    json.dump(guide_data, f, ensure_ascii=False, indent=2)

        # 处理troubleshooting - 直接保存到根目录的troubleshooting文件夹
        if 'troubleshooting' in node_data and node_data['troubleshooting']:
            ts_dir = root_dir / "troubleshooting"
            ts_dir.mkdir(exist_ok=True)
            # 确保media文件夹存在
            ts_media_dir = ts_dir / "media"
            ts_media_dir.mkdir(exist_ok=True)

            for i, ts in enumerate(node_data['troubleshooting']):
                ts_data = ts.copy()
                self._process_media_urls(ts_data, ts_dir)  # 使用troubleshooting目录的media文件夹
                ts_file = ts_dir / f"troubleshooting_{i+1}.json"
                with open(ts_file, 'w', encoding='utf-8') as f:
                    json.dump(ts_data, f, ensure_ascii=False, indent=2)

        # 处理子类别 - 保存到subcategories文件夹
        if 'children' in node_data and node_data['children']:
            subcategories_dir = root_dir / "subcategories"
            subcategories_dir.mkdir(exist_ok=True)
            for child in node_data['children']:
                self._save_subcategory_to_filesystem(child, subcategories_dir)

    def _save_subcategory_to_filesystem(self, node, subcategories_dir):
        """保存子类别到subcategories目录"""
        if not node or not isinstance(node, dict):
            return

        node_name = node.get('name', 'unknown')
        safe_name = node_name.replace("/", "_").replace("\\", "_").replace(":", "_")

        # 创建子类别目录
        subcat_dir = subcategories_dir / safe_name
        subcat_dir.mkdir(parents=True, exist_ok=True)

        # 复制节点数据并处理媒体URL
        node_data = node.copy()
        self._process_media_urls(node_data, subcat_dir)

        # 保存子类别信息
        info_file = subcat_dir / "info.json"
        node_info = {k: v for k, v in node_data.items() if k not in ['children', 'guides', 'troubleshooting']}
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(node_info, f, ensure_ascii=False, indent=2)

        # 处理子类别的guides和troubleshooting
        if 'guides' in node_data and node_data['guides']:
            guides_dir = subcat_dir / "guides"
            guides_dir.mkdir(exist_ok=True)
            # 确保media文件夹存在
            guides_media_dir = guides_dir / "media"
            guides_media_dir.mkdir(exist_ok=True)

            for i, guide in enumerate(node_data['guides']):
                guide_data = guide.copy()
                self._process_media_urls(guide_data, guides_dir)  # 使用guides目录的media文件夹
                guide_file = guides_dir / f"guide_{i+1}.json"
                with open(guide_file, 'w', encoding='utf-8') as f:
                    json.dump(guide_data, f, ensure_ascii=False, indent=2)

        if 'troubleshooting' in node_data and node_data['troubleshooting']:
            ts_dir = subcat_dir / "troubleshooting"
            ts_dir.mkdir(exist_ok=True)
            # 确保media文件夹存在
            ts_media_dir = ts_dir / "media"
            ts_media_dir.mkdir(exist_ok=True)

            for i, ts in enumerate(node_data['troubleshooting']):
                ts_data = ts.copy()
                self._process_media_urls(ts_data, ts_dir)  # 使用troubleshooting目录的media文件夹
                ts_file = ts_dir / f"troubleshooting_{i+1}.json"
                with open(ts_file, 'w', encoding='utf-8') as f:
                    json.dump(ts_data, f, ensure_ascii=False, indent=2)

        # 递归处理更深层的子类别
        if 'children' in node_data and node_data['children']:
            for child in node_data['children']:
                self._save_subcategory_to_filesystem(child, subcat_dir)

    def _save_node_to_filesystem(self, node, base_dir, path_prefix):
        """递归保存节点到文件系统"""
        if not node or not isinstance(node, dict):
            return

        node_name = node.get('name', 'unknown')
        safe_name = node_name.replace("/", "_").replace("\\", "_").replace(":", "_")

        # 创建当前节点目录
        current_path = path_prefix + "/" + safe_name if path_prefix else safe_name
        node_dir = base_dir / current_path
        node_dir.mkdir(parents=True, exist_ok=True)

        # 复制节点数据并处理媒体URL
        node_data = node.copy()
        self._process_media_urls(node_data, node_dir)

        # 保存节点信息到JSON文件
        info_file = node_dir / "info.json"
        node_info = {k: v for k, v in node_data.items() if k not in ['children', 'guides', 'troubleshooting']}
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(node_info, f, ensure_ascii=False, indent=2)

        # 处理guides
        if 'guides' in node_data and node_data['guides']:
            guides_dir = node_dir / "guides"
            guides_dir.mkdir(exist_ok=True)
            # 确保media文件夹存在
            guides_media_dir = guides_dir / "media"
            guides_media_dir.mkdir(exist_ok=True)

            for i, guide in enumerate(node_data['guides']):
                guide_data = guide.copy()
                self._process_media_urls(guide_data, guides_dir)
                guide_file = guides_dir / f"guide_{i+1}.json"
                with open(guide_file, 'w', encoding='utf-8') as f:
                    json.dump(guide_data, f, ensure_ascii=False, indent=2)

        # 处理troubleshooting
        if 'troubleshooting' in node_data and node_data['troubleshooting']:
            ts_dir = node_dir / "troubleshooting"
            ts_dir.mkdir(exist_ok=True)
            # 确保media文件夹存在
            ts_media_dir = ts_dir / "media"
            ts_media_dir.mkdir(exist_ok=True)

            for i, ts in enumerate(node_data['troubleshooting']):
                ts_data = ts.copy()
                self._process_media_urls(ts_data, ts_dir)
                ts_file = ts_dir / f"troubleshooting_{i+1}.json"
                with open(ts_file, 'w', encoding='utf-8') as f:
                    json.dump(ts_data, f, ensure_ascii=False, indent=2)

        # 递归处理子节点
        if 'children' in node_data and node_data['children']:
            for child in node_data['children']:
                self._save_node_to_filesystem(child, base_dir, current_path)
        
    def print_combined_tree_structure(self, node, level=0):
        """
        打印整合后的树形结构，显示节点类型和内容丰富程度
        """
        if not node:
            return

        indent = "  " * level
        name = node.get('name', 'Unknown')

        # 统计当前节点的内容
        guides_count = len(node.get('guides', []))
        troubleshooting_count = len(node.get('troubleshooting', []))
        children_count = len(node.get('children', []))

        # 判断节点类型并显示相应信息
        if 'title' in node and 'steps' in node:
            # 独立的指南节点
            steps_count = len(node.get('steps', []))
            print(f"{indent}📖 {name} [指南 - {steps_count}步骤]")
        elif 'causes' in node:
            # 独立的故障排除节点
            causes_count = len(node.get('causes', []))
            print(f"{indent}🔧 {name} [故障排除 - {causes_count}原因]")
        elif 'product_name' in node or ('title' in node and 'instruction_url' in node):
            # 产品节点
            content_info = []
            if guides_count > 0:
                content_info.append(f"{guides_count}指南")
            if troubleshooting_count > 0:
                content_info.append(f"{troubleshooting_count}故障排除")
            if children_count > 0:
                content_info.append(f"{children_count}子项")

            content_str = " - " + ", ".join(content_info) if content_info else ""
            print(f"{indent}📱 {name} [产品{content_str}]")
        elif children_count > 0 or guides_count > 0 or troubleshooting_count > 0:
            # 分类节点
            content_info = []
            if guides_count > 0:
                content_info.append(f"{guides_count}指南")
            if troubleshooting_count > 0:
                content_info.append(f"{troubleshooting_count}故障排除")
            if children_count > 0:
                content_info.append(f"{children_count}子项")

            content_str = " - " + ", ".join(content_info) if content_info else ""
            print(f"{indent}📁 {name} [分类{content_str}]")
        else:
            # 其他节点
            print(f"{indent}❓ {name} [未知类型]")

        # 显示guides内容（缩进显示）
        if guides_count > 0:
            for guide in node.get('guides', []):
                guide_name = guide.get('title', 'Unknown Guide')
                steps_count = len(guide.get('steps', []))
                print(f"{indent}  📖 {guide_name} [{steps_count}步骤]")

        # 显示troubleshooting内容（缩进显示）
        if troubleshooting_count > 0:
            for ts in node.get('troubleshooting', []):
                ts_name = ts.get('title', 'Unknown Troubleshooting')
                causes_count = len(ts.get('causes', []))
                print(f"{indent}  🔧 {ts_name} [{causes_count}原因]")

        # 递归打印子节点
        if children_count > 0:
            for child in node['children']:
                self.print_combined_tree_structure(child, level + 1)

    def extract_dynamic_sections(self, soup):
        """动态提取页面上的真实字段名称和内容，基于实际页面结构，确保字段分离和无重复"""
        sections = {}
        seen_content = set()  # 用于去重
        processed_elements = set()  # 记录已处理的元素，避免重复处理

        try:
            # 查找主要内容区域，避免导航和页脚
            main_content = soup.find('main') or soup.find('article') or soup.find('div', class_=lambda x: x and 'content' in str(x).lower())
            if not main_content:
                main_content = soup

            # 首先通过ID和标题文本精确定位各个独立部分
            section_mappings = [
                ('introduction', ['#introduction']),
                ('first_steps', ['#Section_First_Steps']),
                ('triage', ['#Section_Triage'])
            ]

            for field_name, selectors in section_mappings:
                found = False
                for selector in selectors:
                    section_element = main_content.select_one(selector)
                    if section_element and id(section_element) not in processed_elements:
                        content = self.extract_section_content_precisely(section_element, main_content, field_name)
                        if content and content.strip():
                            # 检查内容是否与已有内容重复
                            if not self.is_content_duplicate(content, seen_content):
                                sections[field_name] = content.strip()
                                seen_content.add(content.strip())
                                processed_elements.add(id(section_element))
                                print(f"精确提取字段: {field_name} ({len(content)} 字符)")
                                found = True
                                break

                # 如果通过ID没找到，尝试通过标题文本查找
                if not found:
                    target_texts = {
                        'introduction': ['introduction'],
                        'first_steps': ['first steps', 'before undertaking'],
                        'triage': ['triage']
                    }

                    if field_name in target_texts:
                        for heading in main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                            heading_text = heading.get_text().strip().lower()
                            if any(target in heading_text for target in target_texts[field_name]):
                                if id(heading) not in processed_elements:
                                    content = self.extract_section_content_precisely(heading, main_content, field_name)
                                    if content and content.strip():
                                        if not self.is_content_duplicate(content, seen_content):
                                            sections[field_name] = content.strip()
                                            seen_content.add(content.strip())
                                            processed_elements.add(id(heading))
                                            print(f"通过标题提取字段: {field_name} ({len(content)} 字符)")
                                            found = True
                                            break

        except Exception as e:
            print(f"动态提取sections时发生错误: {str(e)}")

        return sections

    def extract_section_content_precisely(self, element, main_content, field_name):
        """精确提取section内容"""
        try:
            content_parts = []

            # 从元素后面开始提取内容
            next_elem = element.find_next_sibling()
            while next_elem and next_elem.name not in ['h1', 'h2', 'h3']:
                if next_elem.name in ['p', 'div', 'ul', 'ol']:
                    text = next_elem.get_text().strip()
                    if text and len(text) > 10 and not self.is_commercial_text(text):
                        content_parts.append(text)
                next_elem = next_elem.find_next_sibling()

            return '\n\n'.join(content_parts) if content_parts else ""
        except Exception:
            return ""

    def is_content_duplicate(self, content, seen_content):
        """检查内容是否重复"""
        content_clean = content.strip()
        return content_clean in seen_content

    def extract_causes_sections_with_media(self, soup):
        """提取Causes部分内容，并为每个cause提取对应的图片和视频"""
        causes = []
        seen_numbers = set()  # 防止重复

        try:
            # 查找所有带编号的链接，这些通常是causes
            cause_links = soup.find_all('a', href=lambda x: x and '#Section_' in x)

            for link in cause_links:
                href = link.get('href', '')
                if '#Section_' in href:
                    # 提取编号和标题
                    link_text = link.get_text().strip()

                    # 跳过非编号的链接
                    if not any(char.isdigit() for char in link_text):
                        continue

                    # 提取编号
                    number_match = re.search(r'^(\d+)', link_text)
                    if number_match:
                        number = number_match.group(1)

                        # 防止重复
                        if number in seen_numbers:
                            continue
                        seen_numbers.add(number)

                        title = re.sub(r'^\d+\s*', '', link_text).strip()

                        # 查找对应的内容部分
                        section_id = href.split('#')[-1]
                        content_section = soup.find(id=section_id)

                        content = ""
                        images = []
                        videos = []

                        if content_section:
                            content = self.extract_section_content(content_section)
                            # 从该section中提取图片和视频
                            images = self._extract_troubleshooting_images_from_section(content_section)
                            videos = self.extract_videos_from_section(content_section)

                        cause_data = {
                            "number": number,
                            "title": title,
                            "content": content
                        }

                        # 只有当有图片时才添加images字段
                        if images:
                            cause_data["images"] = images

                        # 只有当有视频时才添加videos字段
                        if videos:
                            cause_data["videos"] = videos

                        causes.append(cause_data)

                        if self.verbose:
                            print(f"提取Cause {number}: {title} ({len(content)} 字符, {len(images)} 图片, {len(videos)} 视频)")

            return causes
        except Exception as e:
            print(f"提取Causes时发生错误: {str(e)}")
            return []

    def extract_section_content(self, section):
        """从section中提取文本内容"""
        try:
            content_parts = []
            p_elements = section.find_all('p')
            for p in p_elements:
                p_text = p.get_text().strip()
                if self.is_commercial_text(p_text):
                    continue
                if p_text and len(p_text) > 10:
                    content_parts.append(p_text)
            return '\n\n'.join(content_parts)
        except Exception:
            return ""

    def extract_videos_from_section(self, section):
        """从section中提取视频"""
        videos = []
        try:
            video_elements = section.find_all(['video', 'iframe'])
            for video in video_elements:
                try:
                    from bs4 import Tag
                    if isinstance(video, Tag):
                        video_src = video.get('src') or video.get('data-src')
                        if video_src and isinstance(video_src, str):
                            if 'youtube.com' in video_src or 'youtu.be' in video_src:
                                video_data = {
                                    "url": video_src,
                                    "title": video.get('title', 'Video')
                                }
                                videos.append(video_data)
                except Exception:
                    continue
        except Exception:
            pass
        return videos

def process_input(input_text):
    """处理输入，支持URL或设备名"""
    if not input_text:
        return None, "设备"
        
    # 如果是完整URL，直接返回
    if input_text.startswith("http"):
        parts = input_text.split("/")
        name = parts[-1].replace("_", " ")
        return input_text, name
    
    # 如果包含/Device/，可能是部分URL
    if "/Device/" in input_text:
        parts = input_text.split("/")
        name = parts[-1].replace("_", " ")
        if not input_text.startswith("https://"):
            return "https://www.ifixit.com" + input_text, name
        return input_text, name
    
    # 否则视为设备名/产品名，构建URL
    processed_input = input_text.replace(" ", "_")
    return f"https://www.ifixit.com/Device/{processed_input}", input_text

def print_usage():
    print("=" * 60)
    print("iFixit整合爬虫工具 - 使用说明")
    print("=" * 60)
    print("使用方法:")
    print("python auto_crawler.py [URL或设备名] [选项...]")
    print("\n基本用法:")
    print("  python auto_crawler.py iMac_M_Series")
    print("  python auto_crawler.py https://www.ifixit.com/Device/Television")
    print("  python auto_crawler.py Television")
    print("\n常用选项:")
    print("  --verbose              启用详细输出")
    print("  --no-proxy             关闭代理池")
    print("  --no-cache             禁用缓存检查")
    print("  --force-refresh        强制重新爬取（忽略缓存）")
    print("  --workers N            设置并发线程数（默认4）")
    print("  --max-retries N        设置最大重试次数（默认5）")
    print("\n视频处理选项:")
    print("  --download-videos      启用视频文件下载（默认禁用）")
    print("  --max-video-size N     设置视频文件大小限制（MB，默认50）")
    print("\n示例:")
    print("  # 基本爬取（不下载视频）")
    print("  python auto_crawler.py iMac_M_Series")
    print("")
    print("  # 启用视频下载，限制10MB")
    print("  python auto_crawler.py iMac_M_Series --download-videos --max-video-size 10")
    print("")
    print("  # 详细输出，禁用代理")
    print("  python auto_crawler.py Television --verbose --no-proxy")
    print("\n功能说明:")
    print("- 智能缓存：自动跳过已爬取的内容")
    print("- 代理池：天启IP自动切换，避免封禁")
    print("- 并发爬取：多线程提升爬取速度")
    print("- 错误重试：网络错误自动重试")
    print("- 媒体下载：自动下载并本地化所有媒体文件")
    print("- 视频处理：可选择性下载视频文件，支持大小限制")
    print("=" * 60)

def main():
    # 解析命令行参数
    args = sys.argv[1:]

    # 检查帮助参数
    if not args or args[0].lower() in ['--help', '-h', 'help']:
        print_usage()
        return

    # 获取目标URL/名称
    input_text = args[0]

    # 解析选项
    verbose = '--verbose' in args
    use_proxy = '--no-proxy' not in args  # 默认启用代理
    use_cache = '--no-cache' not in args  # 默认启用缓存
    force_refresh = '--force-refresh' in args

    # 解析workers参数
    max_workers = 4
    if '--workers' in args:
        try:
            workers_idx = args.index('--workers')
            if workers_idx + 1 < len(args):
                max_workers = int(args[workers_idx + 1])
        except (ValueError, IndexError):
            print("警告: workers参数无效，使用默认值4")

    # 解析max-retries参数
    max_retries = 3  # 减少默认重试次数
    if '--max-retries' in args:
        try:
            retries_idx = args.index('--max-retries')
            if retries_idx + 1 < len(args):
                max_retries = int(args[retries_idx + 1])
        except (ValueError, IndexError):
            print("警告: max-retries参数无效，使用默认值3")

    # 解析视频下载参数
    download_videos = '--download-videos' in args
    max_video_size_mb = 50
    if '--max-video-size' in args:
        try:
            size_idx = args.index('--max-video-size')
            if size_idx + 1 < len(args):
                max_video_size_mb = int(args[size_idx + 1])
        except (ValueError, IndexError):
            print("警告: max-video-size参数无效，使用默认值50MB")

    if not input_text:
        print_usage()
        return

    # 处理输入
    url, name = process_input(input_text)

    if url:
        # 创建整合爬虫实例（用于检测）
        temp_crawler = CombinedIFixitCrawler(verbose=False, use_proxy=False)

        # 检查目标是否已经完整爬取
        is_complete, target_dir = temp_crawler._check_target_completeness(input_text)

        if is_complete and not force_refresh and target_dir:
            print("\n" + "=" * 60)
            print(f"🎯 检测到目标已完成爬取: {name}")
            print(f"📁 目录位置: {target_dir}")
            print("=" * 60)

            # 检查目录内容
            info_file = target_dir / "info.json"
            guides_dir = target_dir / "guides"
            troubleshooting_dir = target_dir / "troubleshooting"
            media_dir = target_dir / "media"

            guides_count = len(list(guides_dir.glob("*.json"))) if guides_dir.exists() else 0
            ts_count = len(list(troubleshooting_dir.glob("*.json"))) if troubleshooting_dir.exists() else 0
            media_count = len(list(media_dir.glob("*"))) if media_dir.exists() else 0

            print(f"📊 已有内容统计:")
            print(f"   基本信息: {'✅' if info_file.exists() else '❌'}")
            print(f"   指南数量: {guides_count}")
            print(f"   故障排除数量: {ts_count}")
            print(f"   媒体文件数量: {media_count}")

            print(f"\n💡 选项:")
            print(f"   1. 跳过爬取，使用现有数据")
            print(f"   2. 重新爬取（覆盖现有数据）")
            print(f"   3. 退出程序")

            while True:
                choice = input("\n请选择 (1/2/3): ").strip()
                if choice == "1":
                    print(f"✅ 跳过爬取，现有数据位置: {target_dir}")
                    return
                elif choice == "2":
                    print("🔄 将重新爬取并覆盖现有数据...")
                    force_refresh = True
                    break
                elif choice == "3":
                    print("👋 程序退出")
                    return
                else:
                    print("❌ 无效选择，请输入 1、2 或 3")

        print("\n" + "=" * 60)
        print(f"开始整合爬取: {name}")
        print("阶段1: 构建完整树形结构")
        print("阶段2: 为每个节点提取详细内容")
        print("=" * 60)

        # 显示配置信息
        print(f"📋 爬取配置:")
        print(f"   目标: {name}")
        print(f"   详细输出: {'是' if verbose else '否'}")
        print(f"   使用代理: {'是' if use_proxy else '否'}")
        print(f"   使用缓存: {'是' if use_cache else '否'}")
        print(f"   强制刷新: {'是' if force_refresh else '否'}")
        print(f"   并发数: {max_workers}")
        print(f"   最大重试: {max_retries}")
        print(f"   下载视频: {'是' if download_videos else '否'}")
        if download_videos:
            print(f"   视频大小限制: {max_video_size_mb}MB")

        # 创建整合爬虫
        crawler = CombinedIFixitCrawler(
            verbose=verbose,
            use_proxy=use_proxy,
            use_cache=use_cache,
            force_refresh=force_refresh,
            max_workers=max_workers,
            max_retries=max_retries,
            download_videos=download_videos,
            max_video_size_mb=max_video_size_mb
        )

        # 记录开始时间
        start_time = time.time()

        # 执行整合爬取
        try:
            combined_data = crawler.crawl_combined_tree(url, name)

            if combined_data:
                # 计算统计信息
                stats = crawler.count_detailed_nodes(combined_data)
                elapsed_time = time.time() - start_time

                # 显示整合后的树形结构
                print("\n整合后的树形结构:")
                print("=" * 60)
                crawler.print_combined_tree_structure(combined_data)
                print("=" * 60)

                # 显示统计信息
                print(f"\n整合爬取统计:")
                print(f"- 指南节点: {stats['guides']} 个")
                print(f"- 故障排除节点: {stats['troubleshooting']} 个")
                print(f"- 产品节点: {stats['products']} 个")
                print(f"- 分类节点: {stats['categories']} 个")
                print(f"- 总计: {sum(stats.values())} 个节点")
                print(f"- 耗时: {elapsed_time:.1f} 秒")

                # 保存结果
                print(f"\n💾 正在保存数据到本地文件夹...")
                filename = crawler.save_combined_result(combined_data, target_name=input_text)

                print(f"\n✅ 整合爬取完成!")
                print(f"📁 数据已保存到本地文件夹: {filename}")

                # 显示性能统计
                crawler._print_performance_stats()

                # 保存缓存索引
                if crawler.cache_manager:
                    crawler.cache_manager.save_cache_index()
                    cache_stats = crawler.cache_manager.get_cache_stats()
                    print(f"\n📊 缓存统计:")
                    print(f"- 总处理URL: {cache_stats['total_urls']}")
                    print(f"- 缓存命中: {cache_stats['cached_urls']}")
                    print(f"- 新增处理: {cache_stats['new_urls']}")
                    if cache_stats['total_urls'] > 0:
                        hit_rate = (cache_stats['cached_urls'] / cache_stats['total_urls']) * 100
                        print(f"- 缓存命中率: {hit_rate:.1f}%")

                # 提供使用建议
                print(f"\n💡 使用建议:")
                print(f"- 查看文件夹结构了解完整的数据层级")
                print(f"- 每个目录包含info.json、guides/、troubleshooting/子目录")
                print(f"- 所有媒体文件已下载到media/目录，URL已替换为本地路径")
                print(f"- 下次爬取相同内容将自动使用缓存，大幅提升速度")

            else:
                print("\n✗ 整合爬取失败")

        except KeyboardInterrupt:
            print("\n\n用户中断爬取")
            # 即使中断也保存缓存索引
            if crawler.cache_manager:
                crawler.cache_manager.save_cache_index()
        except Exception as e:
            print(f"\n✗ 爬取过程中发生错误: {str(e)}")
            # 即使出错也保存缓存索引
            if crawler.cache_manager:
                crawler.cache_manager.save_cache_index()
            if verbose:
                import traceback
                traceback.print_exc()
        finally:
            # 确保缓存索引被保存
            if 'crawler' in locals() and crawler.cache_manager:
                crawler.cache_manager.save_cache_index()
    else:
        print_usage()

def test_tianqi_proxy():
    """测试天启IP代理池功能"""
    print("=" * 60)
    print("🧪 测试天启IP代理池功能")
    print("=" * 60)

    # 创建爬虫实例，启用代理
    crawler = CombinedIFixitCrawler(
        verbose=True,
        use_proxy=True,
        use_cache=False,
        max_workers=1
    )

    # 测试代理获取
    print("\n1. 测试代理获取...")
    if crawler.proxy_manager:
        proxy = crawler.proxy_manager.get_proxy()
        if proxy:
            print("✅ 代理获取成功")
            print(f"当前代理: {proxy}")
            stats = crawler.proxy_manager.get_stats()
            print(f"代理池统计: {stats}")
        else:
            print("❌ 代理获取失败")
            return
    else:
        print("❌ 代理管理器未初始化")
        return

    # 测试代理切换
    print("\n2. 测试代理切换...")
    old_proxy = crawler.current_proxy.copy() if crawler.current_proxy else None
    if crawler._switch_proxy("测试切换"):
        new_proxy = crawler.current_proxy
        if new_proxy != old_proxy:
            print("✅ 代理切换成功")
            print(f"新代理: {new_proxy}")
        else:
            print("⚠️  代理未变化（可能是代理池为空）")
    else:
        print("❌ 代理切换失败")

    # 测试实际网络请求
    print("\n3. 测试实际网络请求...")
    test_url = "https://www.ifixit.com/Device"
    try:
        soup = crawler.get_soup(test_url)
        if soup:
            title = soup.find('title')
            print(f"✅ 网络请求成功")
            print(f"页面标题: {title.get_text() if title else 'No title'}")
        else:
            print("❌ 网络请求失败，未获取到页面内容")
    except Exception as e:
        print(f"❌ 网络请求异常: {e}")

    print("\n" + "=" * 60)
    print("🏁 代理池测试完成")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    # 检查是否是测试模式
    if len(sys.argv) > 1 and sys.argv[1] == "--test-proxy":
        test_tianqi_proxy()
        sys.exit(0)

    main()
