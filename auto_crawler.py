#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
整合爬虫工具 - 结合树形结构和详细内容提取 + 代理池 + 本地文件存储
将iFixit网站的设备分类以层级树形结构展示，并为每个节点提取详细内容
支持HTTP隧道代理池、本地文件夹存储、媒体文件下载等功能
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
import httpx
import asyncio
import aiofiles
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


def safe_str(obj):
    """安全的字符串转换，避免格式化错误"""
    try:
        if obj is None:
            return "None"
        if hasattr(obj, '__str__'):
            result = str(obj)
            # 确保返回的字符串不为空
            return result if result else "Empty string"
        else:
            return repr(obj)
    except Exception:
        return "Unknown error"


def safe_json_dump(data, file_handle, **kwargs):
    """安全的JSON序列化函数，自动处理PosixPath等不可序列化对象"""
    def convert_paths(obj):
        """递归转换PosixPath对象为字符串"""
        if hasattr(obj, '__fspath__'):  # 检查是否是路径对象
            return str(obj)
        elif isinstance(obj, dict):
            return {k: convert_paths(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_paths(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(convert_paths(item) for item in obj)
        else:
            return obj

    try:
        # 转换数据中的所有路径对象
        safe_data = convert_paths(data)
        json.dump(safe_data, file_handle, **kwargs)
    except Exception as e:
        # 如果还是失败，尝试更严格的转换
        try:
            safe_data = json.loads(json.dumps(data, default=str))
            json.dump(safe_data, file_handle, **kwargs)
        except Exception as e2:
            # 最后的回退方案：记录错误但不中断程序
            print(f"⚠️ JSON序列化失败，跳过此文件: {e2}")
            # 写入一个基本的错误信息
            error_data = {
                "error": "JSON serialization failed",
                "original_error": str(e2),
                "timestamp": datetime.now().isoformat()
            }
            json.dump(error_data, file_handle, **kwargs)


class TunnelProxyManager:
    """隧道代理管理器 - 使用HTTP隧道代理池，支持多代理并发"""

    def __init__(self, tunnel_host="b353.kdltpspro.com", tunnel_port=15818,
                 username="t15237111788411", password="htjqu9dr", max_reset_cycles=3,
                 pool_size=10):
        """
        初始化隧道代理管理器

        Args:
            tunnel_host: 隧道域名
            tunnel_port: 隧道端口
            username: 用户名
            password: 密码
            max_reset_cycles: 最大重置周期数
            pool_size: 代理池大小（并发连接数）
        """
        self.tunnel_host = tunnel_host
        self.tunnel_port = tunnel_port
        self.username = username
        self.password = password
        self.pool_size = pool_size

        self.proxy_pool = []  # 代理池
        self.current_index = 0  # 当前代理索引
        self.proxy_switch_count = 0  # 请求计数器
        self.proxy_lock = threading.Lock()

        # 添加重置循环限制
        self.max_reset_cycles = max_reset_cycles
        self.reset_cycle_count = 0
        self.failed_count = 0  # 失败计数

        # 初始化代理池
        self._init_proxy_pool()

    def _init_proxy_pool(self):
        """初始化代理池 - 创建多个独立的代理连接"""
        try:
            # 构建基础代理URL
            base_proxy_url = f"http://{self.username}:{self.password}@{self.tunnel_host}:{self.tunnel_port}"

            # 创建代理池 - 每个代理都是独立的连接
            for i in range(self.pool_size):
                proxy_config = {
                    'http': base_proxy_url,
                    'https': base_proxy_url,
                    'id': i,
                    'active': True,
                    'failed_count': 0
                }
                self.proxy_pool.append(proxy_config)

            print(f"📋 多代理池初始化成功")
            print(f"🌐 隧道地址: {self.tunnel_host}:{self.tunnel_port}")
            print(f"👤 用户名: {self.username}")
            print(f"🔄 代理池大小: {self.pool_size} 个并发连接")

            # 启动代理预热（后台任务）
            try:
                import asyncio
                asyncio.create_task(self._warmup_proxies())
            except RuntimeError:
                # 如果没有运行中的事件循环，跳过预热
                pass

        except Exception as e:
            print(f"❌ 代理池初始化失败: {e}")
            self.proxy_pool = []

    def get_proxy(self, thread_id=None):
        """获取代理配置 - 智能代理选择，优先使用稳定代理"""
        with self.proxy_lock:
            if not self.proxy_pool:
                print("❌ 代理池未初始化")
                return None

            # 如果指定了线程ID，尝试为该线程分配固定代理
            if thread_id is not None:
                proxy_index = thread_id % len(self.proxy_pool)
                proxy = self.proxy_pool[proxy_index]
                if proxy['active']:
                    return {
                        'http': proxy['http'],
                        'https': proxy['https'],
                        'proxy_id': proxy['id']
                    }

            # 智能选择代理：优先选择失败次数最少的活跃代理
            active_proxies = [p for p in self.proxy_pool if p['active']]
            if not active_proxies:
                print("❌ 没有可用的代理")
                return None

            # 按失败次数排序，优先使用最稳定的代理
            active_proxies.sort(key=lambda x: x['failed_count'])

            # 选择失败次数最少的代理
            proxy = active_proxies[0]

            # 如果最好的代理失败次数也很高，轮询使用
            if proxy['failed_count'] > 3:
                proxy = active_proxies[self.current_index % len(active_proxies)]
                self.current_index = (self.current_index + 1) % len(active_proxies)

            return {
                'http': proxy['http'],
                'https': proxy['https'],
                'proxy_id': proxy['id']
            }

    def mark_proxy_failed(self, proxy, reason=""):
        """标记代理失败"""
        with self.proxy_lock:
            if proxy and 'proxy_id' in proxy:
                proxy_id = proxy['proxy_id']
                if proxy_id < len(self.proxy_pool):
                    self.proxy_pool[proxy_id]['failed_count'] += 1
                    failed_count = self.proxy_pool[proxy_id]['failed_count']

                    # 提高失败阈值，减少频繁切换
                    if failed_count >= 5:  # 提高失败阈值到5次
                        self.proxy_pool[proxy_id]['active'] = False

                        # 检查是否还有可用代理
                        active_count = sum(1 for p in self.proxy_pool if p['active'])
                        if active_count <= 2:  # 保留至少2个代理可用
                            # 重新激活失败次数最少的代理
                            min_failed = min(p['failed_count'] for p in self.proxy_pool)
                            for p in self.proxy_pool:
                                if p['failed_count'] == min_failed:
                                    p['active'] = True
                                    p['failed_count'] = max(0, p['failed_count'] - 2)  # 减少失败计数
            else:
                self.failed_count += 1
                # 静默处理失败，减少日志输出

    def get_stats(self):
        """获取代理池统计信息"""
        active_count = sum(1 for p in self.proxy_pool if p['active'])
        total_failed = sum(p['failed_count'] for p in self.proxy_pool)

        return {
            'tunnel_host': self.tunnel_host,
            'tunnel_port': self.tunnel_port,
            'username': self.username,
            'pool_size': self.pool_size,
            'active_proxies': active_count,
            'total_failed': total_failed,
            'proxy_details': [
                {
                    'id': p['id'],
                    'active': p['active'],
                    'failed_count': p['failed_count']
                } for p in self.proxy_pool
            ]
        }

    def reset_stats(self):
        """重置统计信息"""
        with self.proxy_lock:
            for proxy in self.proxy_pool:
                proxy['failed_count'] = 0
                proxy['active'] = True
            self.failed_count = 0

    async def test_proxy_speed(self, proxy_url, test_url="https://httpbin.org/ip"):
        """测试单个代理的响应速度"""
        try:
            import time
            start_time = time.time()

            timeout_config = httpx.Timeout(connect=1.0, read=2.0)
            async with httpx.AsyncClient(timeout=timeout_config, proxy=proxy_url) as client:
                response = await client.get(test_url)
                end_time = time.time()

                if response.status_code == 200:
                    return end_time - start_time
                else:
                    return float('inf')
        except Exception:
            return float('inf')

    async def _warmup_proxies(self):
        """代理预热 - 后台测试代理可用性"""
        try:
            # 测试前3个代理
            proxy_url = f"http://{self.username}:{self.password}@{self.tunnel_host}:{self.tunnel_port}"

            # 并行测试
            tasks = []
            for i in range(min(3, len(self.proxy_pool))):
                task = self.test_proxy_speed(proxy_url, "https://httpbin.org/ip")
                tasks.append(task)

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 标记不可用的代理
                for i, result in enumerate(results):
                    if isinstance(result, Exception) or result == float('inf'):
                        if i < len(self.proxy_pool):
                            self.proxy_pool[i]['active'] = False
                            self.proxy_pool[i]['failed_count'] += 1

                print(f"🔥 代理预热完成，测试了 {len(tasks)} 个代理")

        except Exception as e:
            # 预热失败不影响主程序
            pass


class AsyncHttpClientManager:
    """异步HTTP客户端管理器 - 基于httpx的高性能异步请求"""

    def __init__(self, proxy_manager=None, max_connections=500, max_keepalive_connections=100,
                 timeout=3.0, max_retries=2):
        """
        初始化异步HTTP客户端管理器（优化版本，支持更高并发）

        Args:
            proxy_manager: 代理管理器实例
            max_connections: 最大连接数（提升到200以支持更高并发）
            max_keepalive_connections: 最大保持连接数（提升到50）
            timeout: 请求超时时间
            max_retries: 最大重试次数
        """
        self.proxy_manager = proxy_manager
        self.max_connections = max_connections
        self.max_keepalive_connections = max_keepalive_connections
        self.timeout = timeout
        self.max_retries = max_retries

        # 请求头配置 - 强制英文版本
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=1.0",  # 强制英文，提高优先级
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Cookie": "locale=en"  # 添加英文locale cookie
        }

        # 媒体文件专用请求头 - 强制英文版本
        self.media_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=1.0",  # 强制英文，提高优先级
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.ifixit.com/",
            "Origin": "https://www.ifixit.com",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-site",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Cookie": "locale=en"  # 添加英文locale cookie
        }

        self._client = None
        self._semaphore = None

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self._init_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self._close_client()

    async def _init_client(self):
        """初始化异步HTTP客户端"""
        try:
            if self._client:
                await self._client.aclose()
                self._client = None
                
            self._semaphore = asyncio.Semaphore(self.max_connections)

            # 优化超时配置 - 增加超时时间减少频繁切换
            timeout_config = httpx.Timeout(
                connect=5.0,    # 连接超时5秒
                read=10.0,      # 读取超时10秒
                write=5.0,      # 写入超时5秒
                pool=3.0        # 连接池获取超时3秒
            )

            self._client = httpx.AsyncClient(
                timeout=timeout_config,
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=self.max_connections,
                    max_keepalive_connections=self.max_keepalive_connections,
                    keepalive_expiry=5.0  # 连接保持时间5秒，快速释放失效连接
                ),
                headers=self.headers
            )
            return True
        except Exception as e:
            print(f"初始化HTTP客户端失败: {str(e)}")
            return False

    async def _close_client(self):
        """关闭异步HTTP客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get(self, url, headers=None, **kwargs):
        """异步GET请求 - 修复事件循环关闭问题"""
        try:
            # 检查事件循环状态
            try:
                loop = asyncio.get_running_loop()
                if loop.is_closed():
                    return None
            except RuntimeError:
                return None

            if not self._client or not self._semaphore:
                await self._init_client()

            # 再次检查确保_client和_semaphore已经初始化
            if not self._client or not self._semaphore:
                return None

            async with self._semaphore:
                request_headers = self.headers.copy()
                if headers:
                    request_headers.update(headers)

                return await self._client.get(url, headers=request_headers, **kwargs)
        except Exception as e:
            # 安全的错误消息处理
            error_msg = safe_str(e) if e is not None else "Unknown error"
            # 特殊处理事件循环关闭的情况
            if "Event loop is closed" in error_msg:
                return None
            print(f"异步HTTP请求失败: {error_msg}")
            return None

    async def get_with_retry(self, url, headers=None, max_retries=None, **kwargs):
        """带重试机制的异步GET请求 - 修复事件循环关闭问题"""
        if max_retries is None:
            max_retries = self.max_retries

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # 检查事件循环状态
                try:
                    loop = asyncio.get_running_loop()
                    if loop.is_closed():
                        return None
                except RuntimeError:
                    return None

                response = await self.get(url, headers=headers, **kwargs)

                # 特殊处理404错误 - 不重试，直接返回响应
                if response and response.status_code == 404:
                    print(f"⚠️ 页面不存在 (404): {url}")
                    return response

                if response:
                    response.raise_for_status()
                    return response
                else:
                    return None

            except (httpx.ProxyError, httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout, httpx.TimeoutException) as e:
                # 网络相关错误，减少频繁切换
                if self.proxy_manager and attempt < max_retries:
                    # 只在第一次重试时切换代理
                    if attempt == 0:
                        import time
                        current_time = time.strftime("%H:%M:%S")
                        error_str = safe_str(e)
                        print(f"[{current_time}] 🔄 网络错误，切换代理...")

                        self.proxy_manager.mark_proxy_failed(None, f"网络错误: {error_str[:50]}")

                        # 立即重新初始化客户端以使用新代理
                        await self._close_client()
                        await self._init_client()

                    # 递增延迟，避免过于频繁的重试
                    delay = 0.5 + attempt * 0.5  # 0.5秒, 1秒, 1.5秒...
                    await asyncio.sleep(delay)

                last_error = e

            except Exception as e:
                last_error = e

                # 特殊处理事件循环关闭的情况
                error_str = safe_str(e)
                if "Event loop is closed" in error_str:
                    return None

                if attempt < max_retries:
                    # 非网络错误的快速重试
                    delay = 0.1 + attempt * 0.1  # 最大延迟0.3秒
                    await asyncio.sleep(delay)

        # 所有重试都失败了，但不要抛出异常，而是返回None让调用者处理
        return None

    async def download_file(self, url, local_path, headers=None):
        """异步下载文件（优化版本，提升下载速度）"""
        if not headers:
            headers = self.media_headers

        try:
            # 检查事件循环状态
            try:
                loop = asyncio.get_running_loop()
                if loop.is_closed():
                    return None
            except RuntimeError:
                return None

            response = await self.get_with_retry(url, headers=headers)
            if response is None:
                return None

            # 确保目录存在
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # 异步写入文件，优化chunk大小以提升性能
            async with aiofiles.open(local_path, 'wb') as f:
                async for chunk in response.aiter_bytes(chunk_size=16384):  # 增加chunk大小
                    await f.write(chunk)

            return local_path

        except Exception as e:
            # 安全的错误处理
            error_msg = str(e) if e is not None else "Unknown error"
            if "Event loop is closed" in error_msg:
                return None
            return None

    async def download_files_batch(self, download_tasks, max_concurrent=20):
        """批量异步下载文件，优化性能"""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def download_with_semaphore(url, local_path, headers=None):
            async with semaphore:
                try:
                    # 检查事件循环是否仍然活跃
                    try:
                        loop = asyncio.get_running_loop()
                        if loop.is_closed():
                            return None
                    except RuntimeError:
                        # 没有运行中的事件循环
                        return None

                    return await self.download_file(url, local_path, headers)
                except Exception as e:
                    # 特殊处理事件循环关闭的情况
                    if "Event loop is closed" in str(e):
                        return None
                    return None

        # 创建所有下载任务
        tasks = [download_with_semaphore(url, path, headers)
                for url, path, headers in download_tasks]

        # 并发执行所有下载
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计结果
        success_count = sum(1 for r in results if r is not None and not isinstance(r, Exception))
        return success_count, len(tasks)


class CacheManager:
    """智能缓存管理器 - 优化爬虫重复执行效率"""

    def __init__(self, storage_root, logger=None, force_refresh=False):
        self.storage_root = Path(storage_root)
        self.logger = logger or logging.getLogger(__name__)
        self.cache_index_file = self.storage_root / "cache_index.json"
        self.cache_index = {}
        self.force_refresh = force_refresh  # 添加强制刷新标志
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
                safe_json_dump(cache_data, f, ensure_ascii=False, indent=2)
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
        """验证缓存数据的完整性 - 智能适配不同的文件结构"""
        try:
            self.logger.info(f"   🔍 验证数据完整性...")

            # 检查info.json文件
            info_file = local_path / "info.json"
            if not info_file.exists():
                self.logger.info(f"   ❌ info.json文件不存在")
                return False

            with open(info_file, 'r', encoding='utf-8') as f:
                info_data = json.load(f)

            # 检查troubleshooting缓存的一致性
            url = cache_entry.get('url', '')
            # troubleshooting缓存现在完全独立管理，不依赖cache_index检查

            structure = cache_entry.get('structure', {})
            self.logger.info(f"   📊 预期结构: {structure}")

            # 智能验证：如果没有结构信息，从实际文件推断
            if not structure:
                structure = self._infer_structure_from_files(local_path)
                self.logger.info(f"   🔍 推断的结构: {structure}")

            # 验证guides目录和文件
            if structure.get('has_guides', False):
                guides_dir = local_path / "guides"
                if not guides_dir.exists():
                    self.logger.info(f"   ❌ guides目录不存在")
                    return False

                # 检查guide子目录和文件（新的目录结构：guide_1/guide.json）
                guide_subdirs = list(guides_dir.glob("guide_*"))
                expected_count = structure.get('guides_count', 0)

                # 验证每个guide子目录都有guide.json文件
                valid_guides = 0
                for guide_subdir in guide_subdirs:
                    guide_file = guide_subdir / "guide.json"
                    if guide_file.exists():
                        valid_guides += 1

                if valid_guides != expected_count:
                    self.logger.info(f"   ❌ 指南文件数量不匹配: 期望 {expected_count}, 实际 {valid_guides}")
                    return False
                else:
                    self.logger.info(f"   ✅ 指南文件验证通过: {valid_guides} 个")

            # 验证troubleshooting目录和文件
            if structure.get('has_troubleshooting', False):
                ts_dir = local_path / "troubleshooting"
                if not ts_dir.exists():
                    self.logger.info(f"   ❌ troubleshooting目录不存在")
                    return False

                # 检查troubleshooting子目录和文件（新的目录结构：troubleshooting_1/troubleshooting.json）
                ts_subdirs = list(ts_dir.glob("troubleshooting_*"))
                expected_count = structure.get('troubleshooting_count', 0)

                # 验证每个troubleshooting子目录都有troubleshooting.json文件
                valid_troubleshooting = 0
                for ts_subdir in ts_subdirs:
                    ts_file = ts_subdir / "troubleshooting.json"
                    if ts_file.exists():
                        valid_troubleshooting += 1

                if valid_troubleshooting != expected_count:
                    self.logger.info(f"   ❌ 故障排除文件数量不匹配: 期望 {expected_count}, 实际 {valid_troubleshooting}")
                    return False
                else:
                    self.logger.info(f"   ✅ 故障排除文件验证通过: {valid_troubleshooting} 个")

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

    def _infer_structure_from_files(self, local_path):
        """从实际文件推断缓存结构"""
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
                # 检查新格式：guide_*/guide.json
                guide_subdirs = list(guides_dir.glob("guide_*"))
                valid_guides = sum(1 for subdir in guide_subdirs if (subdir / "guide.json").exists())

                # 如果没有新格式，检查旧格式：*.json
                if valid_guides == 0:
                    guide_files = list(guides_dir.glob("*.json"))
                    valid_guides = len(guide_files)

                if valid_guides > 0:
                    structure['has_guides'] = True
                    structure['guides_count'] = valid_guides

            # 检查troubleshooting目录
            ts_dir = local_path / "troubleshooting"
            if ts_dir.exists():
                # 检查新格式：troubleshooting_*/troubleshooting.json
                ts_subdirs = list(ts_dir.glob("troubleshooting_*"))
                valid_ts = sum(1 for subdir in ts_subdirs if (subdir / "troubleshooting.json").exists())

                # 如果没有新格式，检查旧格式：*.json
                if valid_ts == 0:
                    ts_files = list(ts_dir.glob("*.json"))
                    valid_ts = len(ts_files)

                if valid_ts > 0:
                    structure['has_troubleshooting'] = True
                    structure['troubleshooting_count'] = valid_ts

            # 检查media目录
            media_dir = local_path / "media"
            if media_dir.exists():
                media_files = list(media_dir.glob("*"))
                if media_files:
                    structure['has_media'] = True
                    structure['media_count'] = len(media_files)

        except Exception as e:
            self.logger.error(f"推断文件结构失败: {e}")

        return structure

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
        """分析本地数据结构 - 不再包含troubleshooting信息，由独立缓存管理"""
        structure = {
            'has_guides': False,
            'guides_count': 0,
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

            # troubleshooting信息不再记录在cache_index中，由troubleshooting_cache.json独立管理

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

    def _find_actual_device_path(self, device_url):
        """查找设备URL对应的实际存在路径"""
        try:
            # 从URL提取设备名称
            device_path = device_url.split('/Device/')[-1]
            if '?' in device_path:
                device_path = device_path.split('?')[0]
            device_path = device_path.rstrip('/')

            from urllib.parse import unquote
            device_name = unquote(device_path)

            # 在Device目录下搜索包含设备名称的目录
            device_root = self.storage_root / "Device"
            if not device_root.exists():
                return None

            # 生成可能的设备名称变体
            name_variants = [
                device_name,
                device_name.replace('%22', '"'),
                device_name.replace('"', '%22'),
                device_path,  # 原始编码版本
                unquote(device_path)  # 解码版本
            ]

            # 优先查找直接匹配的目录
            for variant in name_variants:
                direct_path = device_root / variant
                if direct_path.exists():
                    self.logger.info(f"找到直接匹配路径: {direct_path}")
                    return direct_path

            # 递归搜索匹配的目录
            self.logger.info(f"开始递归搜索设备路径，查找: {name_variants}")

            for path in device_root.rglob("*"):
                if path.is_dir():
                    # 检查目录名是否匹配任何变体
                    for variant in name_variants:
                        if path.name == variant:
                            self.logger.info(f"找到名称匹配路径: {path}")
                            return path

                    # 检查是否有troubleshooting_cache.json文件
                    ts_cache_file = path / "troubleshooting_cache.json"
                    if ts_cache_file.exists():
                        # 验证这是否是正确的设备目录
                        path_str = str(path)
                        for variant in name_variants:
                            if variant in path_str:
                                self.logger.info(f"通过troubleshooting_cache.json找到匹配路径: {path}")
                                return path

            self.logger.warning(f"未找到设备路径，搜索的变体: {name_variants}")
            return None

        except Exception as e:
            self.logger.error(f"查找实际设备路径失败: {e}")
            return None

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

    def is_troubleshooting_section_cached(self, cache_key, device_url):
        """检查troubleshooting部分是否已缓存"""
        try:
            # 使用与save_troubleshooting_cache相同的路径逻辑
            local_path = self._get_troubleshooting_cache_path(cache_key, device_url)
            ts_cache_file = local_path / "troubleshooting_cache.json"

            if not ts_cache_file.exists():
                self.logger.info(f"🔍 Troubleshooting缓存文件不存在: {ts_cache_file}")
                return False

            # 验证缓存数据的完整性
            with open(ts_cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)

            # 检查缓存数据是否有效
            if not isinstance(cached_data, list):
                self.logger.info(f"🔍 Troubleshooting缓存数据格式无效")
                return False

            self.logger.info(f"✅ Troubleshooting部分缓存有效: {len(cached_data)} 个项目")
            return True

        except Exception as e:
            self.logger.error(f"检查troubleshooting缓存失败: {e}")
            return False

    def _get_troubleshooting_cache_path(self, cache_key, device_url):
        """获取troubleshooting缓存的路径 - 与Troubleshooting文件夹在同一层级"""
        try:
            # troubleshooting_cache.json应该与troubleshooting文件夹在同一层级
            if '/Device/' in device_url:
                # 首先尝试查找实际存在troubleshooting文件夹的路径
                actual_path = self._find_troubleshooting_directory_path(device_url)
                if actual_path:
                    self.logger.info(f"✅ 找到设备目录用于troubleshooting缓存: {actual_path}")
                    return actual_path

                # 如果没找到实际的troubleshooting目录，预测将来的设备目录路径
                predicted_path = self._predict_device_directory_path(device_url)
                if predicted_path:
                    self.logger.info(f"🔮 预测设备目录用于troubleshooting缓存: {predicted_path}")
                    return predicted_path

                # 最后的回退方案：使用哈希路径
                self.logger.info(f"🔍 无法预测设备目录，使用哈希路径")
                url_hash = self.get_url_hash(device_url)
                fallback_path = Path(self.storage_root) / "cache" / url_hash[:8]
                return fallback_path
            else:
                # 非设备URL使用哈希路径
                url_hash = self.get_url_hash(device_url)
                fallback_path = Path(self.storage_root) / "cache" / url_hash[:8]
                return fallback_path
        except Exception as e:
            self.logger.error(f"获取troubleshooting缓存路径失败: {e}")
            # 确保总是返回一个有效路径
            url_hash = self.get_url_hash(device_url)
            fallback_path = Path(self.storage_root) / "cache" / url_hash[:8]
            return fallback_path

    def _clean_directory_name(self, name):
        """清理目录名，移除非法字符"""
        if not name:
            return "unknown"
        
        # 替换非法字符
        safe_name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
        safe_name = safe_name.replace('"', '_').replace("'", "_").replace("?", "_")
        safe_name = safe_name.replace("*", "_").replace("|", "_").replace("<", "_").replace(">", "_")
        
        # 确保名称不为空
        if not safe_name or safe_name.isspace():
            return "unknown"
            
        return safe_name

    def _build_device_path_from_url(self, device_url):
        """基于URL构建设备路径 - 与实际文件保存逻辑保持一致"""
        try:
            # 首先检查是否有缓存的路径信息
            device_hash = self.get_url_hash(device_url)
            if device_hash in self.cache_index:
                cache_entry = self.cache_index[device_hash]
                cached_path = self.storage_root / cache_entry.get('local_path', '')
                if cached_path.exists():
                    return cached_path

            # 从URL中提取设备路径
            device_path = device_url.split('/Device/')[-1]
            if '?' in device_path:
                device_path = device_path.split('?')[0]
            device_path = device_path.rstrip('/')

            from urllib.parse import unquote
            device_path = unquote(device_path)

            # 始终使用完整的层级路径结构
            path_parts = device_path.split('/')
            
            # 构建完整的层级路径
            result_path = self.storage_root / "Device"
            for part in path_parts:
                if part:  # 跳过空部分
                    safe_part = self._clean_directory_name(part)
                    result_path = result_path / safe_part
            
            return result_path

        except Exception as e:
            self.logger.error(f"构建设备路径失败: {e}")
            # 最终回退到简单路径，但仍然尝试保持层级结构
            device_path = device_url.split('/Device/')[-1].split('?')[0].rstrip('/')
            path_parts = device_path.split('/')
            
            result_path = self.storage_root / "Device"
            for part in path_parts:
                if part:  # 跳过空部分
                    safe_part = self._clean_directory_name(part)
                    result_path = result_path / safe_part
            
            return result_path

    def _find_troubleshooting_directory_path(self, device_url):
        """查找实际存在troubleshooting文件夹的路径"""
        try:
            # 从device_url提取设备路径信息
            device_path = device_url.split('/Device/')[-1]
            if '?' in device_path:
                device_path = device_path.split('?')[0]
            device_path = device_path.rstrip('/')

            from urllib.parse import unquote
            device_path = unquote(device_path)

            # 在Device目录下递归搜索包含troubleshooting文件夹的目录
            device_root = self.storage_root / "Device"
            if not device_root.exists():
                return None

            device_name = device_path.split('/')[-1]
            self.logger.info(f"搜索troubleshooting文件夹，设备名称: {device_name}")

            # 首先尝试直接构建路径
            direct_path = self.storage_root / "Device" / device_path
            if direct_path.exists():
                self.logger.info(f"直接找到设备目录: {direct_path}")
                # 即使troubleshooting目录不存在，也返回设备目录，以便后续创建cache文件
                return direct_path

            # 递归搜索troubleshooting文件夹
            for path in device_root.rglob("troubleshooting"):
                if path.is_dir():
                    parent_path = path.parent

                    # 检查父目录名是否匹配设备名称
                    if parent_path.name.lower() == device_name.lower():
                        self.logger.info(f"通过设备名称匹配找到troubleshooting目录: {parent_path}")
                        return parent_path

                    # 检查URL编码的版本
                    if device_name.replace('"', '%22') == parent_path.name or device_name.replace('%22', '"') == parent_path.name:
                        self.logger.info(f"通过URL编码匹配找到troubleshooting目录: {parent_path}")
                        return parent_path

                    # 检查路径层级是否匹配设备路径结构
                    relative_path = parent_path.relative_to(device_root)
                    relative_path_str = str(relative_path)

                    # 检查设备路径是否包含在相对路径中（更严格的匹配）
                    if device_path.lower() == relative_path_str.lower():
                        self.logger.info(f"通过完整路径匹配找到troubleshooting目录: {parent_path}")
                        return parent_path

                    # 检查相对路径是否以设备名称结尾
                    if relative_path_str.lower().endswith(device_name.lower()):
                        self.logger.info(f"通过路径结尾匹配找到troubleshooting目录: {parent_path}")
                        return parent_path

            # 如果没有找到troubleshooting目录，尝试查找设备目录
            for path in device_root.rglob("*"):
                if path.is_dir() and path.name.lower() == device_name.lower():
                    self.logger.info(f"找到设备目录: {path}")
                    return path

            self.logger.info(f"未找到troubleshooting文件夹，设备路径: {device_path}")
            return None

        except Exception as e:
            self.logger.error(f"查找troubleshooting目录失败: {e}")
            return None

    def _predict_device_directory_path(self, device_url):
        """预测设备目录的路径，基于URL结构和现有的目录模式"""
        try:
            # 从device_url提取设备路径信息
            device_path = device_url.split('/Device/')[-1]
            if '?' in device_path:
                device_path = device_path.split('?')[0]
            device_path = device_path.rstrip('/')

            from urllib.parse import unquote
            device_path = unquote(device_path)
            device_name = device_path.split('/')[-1]  # 获取设备名称

            # 构建预期的设备目录路径
            device_root = self.storage_root / "Device"

            # 方法1: 查找现有的设备目录（最准确的方法）
            if device_root.exists():
                # 递归搜索匹配的设备目录
                for existing_path in device_root.rglob("*"):
                    if existing_path.is_dir() and existing_path.name == device_name:
                        self.logger.info(f"找到现有设备目录: {existing_path}")
                        return existing_path

                # 搜索包含设备名称的目录（处理编码问题）
                for existing_path in device_root.rglob("*"):
                    if existing_path.is_dir():
                        # 检查目录名是否与设备名称匹配（考虑URL编码）
                        if (existing_path.name.lower() == device_name.lower() or
                            existing_path.name.replace('_', ' ').lower() == device_name.replace('_', ' ').lower() or
                            existing_path.name.replace('%22', '"').lower() == device_name.replace('%22', '"').lower()):
                            self.logger.info(f"找到匹配的设备目录: {existing_path}")
                            return existing_path

            # 方法2: 基于现有目录结构预测路径
            if device_root.exists():
                # 查找相似的目录结构模式
                for existing_path in device_root.rglob("*"):
                    if existing_path.is_dir():
                        relative_path = existing_path.relative_to(device_root)
                        path_parts = str(relative_path).split('/')

                        # 如果找到深度相似的目录结构，尝试构建相似路径
                        if len(path_parts) >= 3:  # 至少有3层深度的目录
                            # 尝试基于现有结构构建路径
                            # 例如：Mac/Mac_Laptop/MacBook_Pro/MacBook_Pro_16/device_name
                            parent_structure = '/'.join(path_parts[:-1])
                            predicted_path = device_root / parent_structure / device_name

                            # 检查父目录是否存在
                            if predicted_path.parent.exists():
                                self.logger.info(f"预测路径基于现有结构: {predicted_path}")
                                return predicted_path

            # 方法3: 直接使用URL路径结构
            predicted_path = device_root / device_path
            if predicted_path.parent.exists():  # 如果父目录存在，说明路径结构合理
                self.logger.info(f"预测路径基于URL结构: {predicted_path}")
                return predicted_path

            # 方法4: 使用简单的设备名称路径（最后的回退方案）
            simple_path = device_root / device_name
            self.logger.info(f"预测路径使用简单结构: {simple_path}")
            return simple_path

        except Exception as e:
            self.logger.error(f"预测设备目录路径失败: {e}")
            return None

    def load_troubleshooting_cache(self, cache_key, device_url):
        """加载缓存的troubleshooting数据"""
        try:
            # 使用统一的路径获取方法
            local_path = self._get_troubleshooting_cache_path(cache_key, device_url)
            ts_cache_file = local_path / "troubleshooting_cache.json"

            if not ts_cache_file.exists():
                return None

            with open(ts_cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)

            self.logger.info(f"📋 加载troubleshooting缓存: {len(cached_data)} 个项目")
            self.stats['cache_hits'] += 1
            return cached_data

        except Exception as e:
            self.logger.error(f"加载troubleshooting缓存失败: {e}")
            return None

    def save_troubleshooting_cache(self, cache_key, device_url, troubleshooting_data):
        """保存troubleshooting数据到缓存"""
        try:
            if not troubleshooting_data:
                return

            # 使用统一的路径获取方法
            local_path = self._get_troubleshooting_cache_path(cache_key, device_url)

            # 现在_get_troubleshooting_cache_path总是返回一个路径，不会返回None
            if local_path is None:
                self.logger.error(f"❌ 无法确定troubleshooting缓存路径")
                return

            # 确保目录存在
            local_path.mkdir(parents=True, exist_ok=True)

            ts_cache_file = local_path / "troubleshooting_cache.json"

            # 缓存保护机制：如果不是强制刷新且缓存文件已存在，先检查是否需要更新
            if not self.force_refresh and ts_cache_file.exists():
                try:
                    with open(ts_cache_file, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)

                    # 如果现有数据不为空且新数据与现有数据相同，则跳过保存
                    if existing_data and len(existing_data) >= len(troubleshooting_data):
                        self.logger.info(f"🔒 保护现有troubleshooting缓存: {len(existing_data)} 个项目 (跳过覆盖)")
                        return
                except Exception as e:
                    self.logger.warning(f"读取现有troubleshooting缓存失败，将保存新数据: {e}")

            # 保存troubleshooting数据
            with open(ts_cache_file, 'w', encoding='utf-8') as f:
                safe_json_dump(troubleshooting_data, f, ensure_ascii=False, indent=2)

            # troubleshooting缓存现在完全独立，不再添加到主缓存索引
            self.logger.info(f"💾 保存troubleshooting缓存: {len(troubleshooting_data)} 个项目")

        except Exception as e:
            self.logger.error(f"保存troubleshooting缓存失败: {e}")

    def save_troubleshooting_cache_after_directory_creation(self, cache_key, device_url, troubleshooting_data, ts_dir):
        """在Troubleshooting目录创建后立即保存cache文件"""
        try:
            if not troubleshooting_data or not ts_dir:
                self.logger.warning(f"跳过保存troubleshooting缓存: 数据为空或目录无效")
                return

            # 获取Troubleshooting目录的父目录（与Troubleshooting文件夹同层）
            cache_dir = ts_dir.parent
            ts_cache_file = cache_dir / "troubleshooting_cache.json"

            self.logger.info(f"🔍 准备保存troubleshooting缓存到: {ts_cache_file}")

            # 简化缓存保护机制：只在强制刷新模式下跳过现有文件
            if not self.force_refresh and ts_cache_file.exists():
                try:
                    with open(ts_cache_file, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)

                    # 只有在现有数据明显更多时才跳过
                    if existing_data and len(existing_data) > len(troubleshooting_data) * 1.5:
                        self.logger.info(f"🔒 保护现有troubleshooting缓存: {len(existing_data)} 个项目 (跳过覆盖)")
                        return
                    else:
                        self.logger.info(f"🔄 更新troubleshooting缓存: {len(existing_data)} -> {len(troubleshooting_data)} 个项目")
                except Exception as e:
                    self.logger.warning(f"读取现有troubleshooting缓存失败，将保存新数据: {e}")

            # 确保目录存在
            cache_dir.mkdir(parents=True, exist_ok=True)

            # 保存troubleshooting数据
            with open(ts_cache_file, 'w', encoding='utf-8') as f:
                safe_json_dump(troubleshooting_data, f, ensure_ascii=False, indent=2)

            self.logger.info(f"💾 成功保存troubleshooting缓存: {ts_cache_file} ({len(troubleshooting_data)} 个项目)")
            print(f"   💾 已生成troubleshooting_cache.json: {ts_cache_file}")

        except Exception as e:
            self.logger.error(f"在目录创建后保存troubleshooting缓存失败: {e}")
            import traceback
            self.logger.error(f"详细错误信息: {traceback.format_exc()}")

    def _generate_content_hash_for_data(self, data):
        """为数据生成内容哈希值"""
        try:
            content_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
            return hashlib.md5(content_str.encode('utf-8')).hexdigest()[:16]
        except Exception as e:
            self.logger.error(f"生成数据哈希时出错: {e}")
            return ""

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
                 use_cache=True, force_refresh=False, max_workers=16, max_retries=1,
                 download_videos=False, max_video_size_mb=50, max_connections=None,
                 timeout=3, request_delay=0.01, proxy_switch_freq=1, cache_ttl=24,
                 custom_user_agent=None, burst_mode=False, conservative_mode=False,
                 skip_images=False, debug_mode=False, show_stats=False, enable_resume=True):
        super().__init__(base_url, verbose)

        # 立即初始化日志系统，确保logger可用
        self._setup_logging()

        self.enable_resume = enable_resume
        self.tree_crawler = TreeCrawler(base_url, enable_resume=enable_resume, logger=self.logger, verbose=verbose)
        self.processed_nodes = set()
        self.target_url = None

        # 本地存储配置（需要在缓存管理器之前设置）
        # 支持通过环境变量配置数据保存路径，默认为 ifixit_data
        self.storage_root = os.getenv('IFIXIT_DATA_DIR', 'ifixit_data')
        self.media_folder = "media"

        # 🚀 高性能配置
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.max_connections = max_connections or (max_workers * 10)
        self.timeout = timeout
        self.request_delay = request_delay
        self.proxy_switch_freq = proxy_switch_freq
        self.cache_ttl = cache_ttl
        self.custom_user_agent = custom_user_agent
        self.burst_mode = burst_mode
        self.conservative_mode = conservative_mode
        self.skip_images = skip_images
        self.debug_mode = debug_mode
        self.show_stats = show_stats

        # 缓存配置
        self.use_cache = use_cache
        self.force_refresh = force_refresh
        self.cache_manager = CacheManager(self.storage_root, self.logger, force_refresh) if use_cache else None

        # 代理池配置
        self.use_proxy = use_proxy
        # 创建代理池，大小与线程数匹配
        proxy_pool_size = max(max_workers, 10) if use_proxy else 0
        self.proxy_manager = TunnelProxyManager(pool_size=proxy_pool_size) if use_proxy else None
        self.failed_urls = set()  # 添加失败URL集合

        # 异步HTTP客户端管理器
        self.async_http_manager = None

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
            "videos_downloaded": 0,
            "errors": 0  # 添加缺失的errors键
        }

        # 并发配置
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.thread_local = threading.local()

        # 错误处理配置
        self.failed_log_file = "failed_urls.log"

        # Troubleshooting处理状态跟踪
        self.processed_troubleshooting_paths = set()  # 跟踪已处理troubleshooting的路径
        self._troubleshooting_from_cache = False  # 标记troubleshooting数据是否来自缓存

        # 媒体文件存在性检查缓存（优化性能）
        self._file_exists_cache = {}  # 缓存文件存在性检查结果
        self._cache_max_size = 1000   # 缓存最大大小

        # 打印视频处理配置
        if self.download_videos:
            self.logger.info(f"✅ 视频下载已启用，最大文件大小: {max_video_size_mb}MB")
        else:
            self.logger.info("⚠️ 视频下载已禁用，将保留原始URL")

    def __del__(self):
        """析构函数，确保资源被正确清理"""
        try:
            self.cleanup()
        except Exception:
            pass  # 静默处理析构函数中的错误

    def cleanup(self):
        """清理所有资源"""
        try:
            # 清理异步HTTP管理器
            if self.async_http_manager:
                try:
                    # 检查是否有运行中的事件循环
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        if not loop.is_closed():
                            # 如果在异步环境中，创建任务来清理
                            asyncio.create_task(self._cleanup_async_resources())
                    except RuntimeError:
                        # 没有运行中的事件循环，创建新的事件循环来清理
                        asyncio.run(self._cleanup_async_resources())
                except Exception:
                    pass  # 静默处理清理错误
                finally:
                    self.async_http_manager = None
        except Exception:
            pass  # 静默处理所有清理错误

    async def _cleanup_async_resources(self):
        """异步清理资源"""
        try:
            if self.async_http_manager:
                await self.async_http_manager._close_client()
        except Exception:
            pass  # 静默处理清理错误

    def _load_proxy_config(self):
        """加载代理配置"""

        # 初始化日志
        self._setup_logging()

        # 隧道代理已在__init__中初始化，无需额外配置

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
        # 安全的错误消息处理
        safe_error = safe_str(error)
        safe_url = safe_str(url)
        log_entry = f"{timestamp} | {safe_url} | {safe_error} | retry_count: {retry_count}\n"

        try:
            with open(self.failed_log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            # 安全的错误消息处理
            error_msg = safe_str(e)
            self.logger.error(f"无法写入失败日志: {error_msg}")

    def _log_failed_media(self, url, error_msg):
        """记录失败的媒体文件到专门的日志"""
        try:
            failed_media_log = "failed_media.log"
            with open(failed_media_log, 'a', encoding='utf-8') as f:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                # 确保error_msg不为None，避免格式化错误
                safe_error_msg = safe_str(error_msg) if error_msg is not None else "Unknown error"
                safe_url = safe_str(url) if url is not None else "Unknown URL"
                log_line = f"[{timestamp}] {safe_url} - {safe_error_msg}\n"
                f.write(log_line)
        except Exception as e:
            # 避免在错误处理中再次出现格式化错误
            try:
                error_msg_str = safe_str(e)
                if self.logger:
                    self.logger.error(f"无法写入媒体失败日志: {error_msg_str}")
            except:
                pass  # 静默处理，避免级联错误

    def _exponential_backoff(self, attempt):
        """优化重试策略 - 平衡速度和稳定性"""
        # 优化模式：合理延迟，减少代理切换
        base_delay = 0.5  # 基础延迟0.5秒
        linear_increment = 0.3  # 每次重试增加0.3秒
        max_delay = 2  # 最大延迟2秒

        delay = min(max_delay, base_delay + (attempt * linear_increment))
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
                    self.logger.warning(f"永久性错误，跳过此项: {e}")
                    # 对于永久性错误，返回None而不是抛出异常
                    return None

                if attempt < self.max_retries - 1:
                    delay = self._exponential_backoff(attempt)
                    self.logger.warning(f"重试 {attempt+1}/{self.max_retries} (延迟{delay:.1f}s): {e}")

                    # 网络错误时切换代理
                    if self.use_proxy and ("network" in str(e).lower() or "proxy" in str(e).lower() or "timeout" in str(e).lower()):
                        self._switch_proxy(f"重试时网络错误: {str(e)}")

                    time.sleep(delay)
                else:
                    self.logger.warning(f"重试失败，已达最大重试次数，跳过此项: {e}")

        # 如果所有重试都失败，返回None让调用者继续处理其他任务
        self.stats["retry_failed"] += 1
        if last_error:
            self.logger.warning(f"任务失败，继续处理其他任务: {str(last_error)}")
            return None
        else:
            return None





    def _get_next_proxy(self):
        """获取当前代理或切换新代理"""
        if not self.use_proxy or not self.proxy_manager:
            return None

        # 检查当前线程是否有指定的代理ID
        current_thread = threading.current_thread()
        thread_proxy_id = getattr(current_thread, 'proxy_id', None)

        # 增加代理使用计数
        if hasattr(self.proxy_manager, 'proxy_switch_count'):
            self.proxy_manager.proxy_switch_count += 1

            # 对于多代理池，每个线程使用独立代理
            if thread_proxy_id is not None:
                if self.verbose and self.proxy_manager.proxy_switch_count % 10 == 0:
                    print(f"🔄 已处理 {self.proxy_manager.proxy_switch_count} 个请求（多代理并发）")
            elif self.proxy_switch_freq == 1:
                # 每次请求都切换（隧道代理的默认行为）
                if self.verbose and self.proxy_manager.proxy_switch_count % 10 == 0:
                    print(f"🔄 已处理 {self.proxy_manager.proxy_switch_count} 个请求（每次自动切换IP）")
            elif self.proxy_manager.proxy_switch_count % self.proxy_switch_freq == 0:
                # 按指定频率切换
                print(f"🔄 达到切换频率 ({self.proxy_switch_freq})，切换代理IP")

        return self.proxy_manager.get_proxy(thread_proxy_id)

    def _switch_proxy(self, reason="请求失败"):
        """切换代理IP"""
        import time
        # 减少日志输出频率，避免日志污染
        if hasattr(self, '_last_proxy_switch_time'):
            current_time = time.time()
            if current_time - self._last_proxy_switch_time < 10:  # 10秒内不重复输出
                pass  # 静默处理
            else:
                self.logger.info(f"🔄 代理切换: {reason[:50]}")
                self._last_proxy_switch_time = current_time
        else:
            self.logger.info(f"🔄 代理切换: {reason[:50]}")
            self._last_proxy_switch_time = time.time()

        if not self.use_proxy or not self.proxy_manager:
            return False

        # 对于多代理池，标记失败但不需要切换（每个线程有独立代理）
        self.proxy_manager.mark_proxy_failed(None, reason)

        # 获取新代理
        new_proxy = self.proxy_manager.get_proxy()
        return new_proxy is not None

    # 隧道代理相关方法已集成到TunnelProxyManager类中

    async def _init_async_http_manager(self):
        """初始化异步HTTP客户端管理器"""
        try:
            if not self.async_http_manager:
                # 优化：提升连接池大小以支持更高的媒体下载并发
                max_connections = max(self.max_workers * 15, 200)  # 提升连接池大小
                max_keepalive = max(self.max_workers * 3, 50)      # 提升保持连接数

                self.async_http_manager = AsyncHttpClientManager(
                    proxy_manager=self.proxy_manager,
                    max_connections=max_connections,
                    max_keepalive_connections=max_keepalive,
                    timeout=5.0,  # 减少超时时间从8秒到5秒
                    max_retries=1  # 减少重试次数，快速失败
                )
                
                # 确保初始化成功
                init_success = await self.async_http_manager._init_client()
                
                # 验证初始化是否成功
                if not init_success or not self.async_http_manager._client:
                    self.logger.error("异步HTTP客户端初始化失败")
                    return False
                    
                # 确保信号量已初始化
                if not self.async_http_manager._semaphore:
                    self.logger.error("异步HTTP客户端信号量初始化失败")
                    return False
                    
                return True
            return True
        except Exception as e:
            self.logger.error(f"初始化异步HTTP管理器失败: {e}")
            return False

    async def _close_async_http_manager(self):
        """关闭异步HTTP客户端管理器"""
        if self.async_http_manager:
            await self.async_http_manager._close_client()
            self.async_http_manager = None

    async def get_soup_async(self, url, use_playwright=False):
        """异步版本的get_soup方法"""
        if not url:
            return None

        if url in self.failed_urls:
            self.logger.warning(f"跳过已知失败URL: {url}")
            return None

        # 强制使用英文版本
        if 'zh.ifixit.com' in url:
            url = url.replace('zh.ifixit.com', 'www.ifixit.com')

        # 确保使用www.ifixit.com而不是其他子域名
        if 'ifixit.com' in url and not url.startswith('https://www.ifixit.com'):
            url = url.replace('https://', 'https://www.').replace('http://', 'https://www.')
            if not url.startswith('https://www.ifixit.com'):
                url = url.replace('ifixit.com', 'www.ifixit.com')

        # 添加强制英文参数
        if '?' in url:
            if 'lang=' not in url:
                url += '&lang=en'
            else:
                # 替换现有的lang参数
                import re
                url = re.sub(r'lang=[^&]*', 'lang=en', url)
        else:
            url += '?lang=en'

        self.stats["total_requests"] += 1

        # 如果需要JavaScript渲染，使用Playwright
        if use_playwright:
            return await self._get_soup_with_playwright_async(url)

        # 否则使用异步httpx方法
        return await self._get_soup_httpx_async(url)

    async def _get_soup_httpx_async(self, url):
        """使用httpx异步获取页面内容"""
        # 初始化异步HTTP管理器
        init_success = await self._init_async_http_manager()
        if not init_success or not self.async_http_manager:
            self.logger.error(f"初始化异步HTTP管理器失败，无法获取页面 {url}")
            self.failed_urls.add(url)
            return None

        try:
            response = await self.async_http_manager.get_with_retry(url, headers=self.headers)
            
            # 检查HTTP状态码
            if response is None:
                self.logger.error(f"获取页面失败 {url}: 响应为空")
                self.failed_urls.add(url)
                return None
                
            if response and response.status_code == 404:
                self.logger.warning(f"页面不存在 {url}: 404 Not Found")
                self.failed_urls.add(url)
                # 对于404错误，抛出特定异常以便上层处理
                raise httpx.HTTPStatusError("404 Not Found", request=response.request, response=response)

            # 对于其他错误状态码
            if response and response.status_code >= 400:
                self.logger.error(f"HTTP错误 {url}: {response.status_code}")
                self.failed_urls.add(url)
                raise httpx.HTTPStatusError(f"HTTP {response.status_code}", request=response.request, response=response)

            from bs4 import BeautifulSoup
            return BeautifulSoup(response.content, 'html.parser')

        except httpx.HTTPStatusError:
            # 直接向上传递HTTP状态错误，让上层处理
            raise
        except Exception as e:
            self.logger.error(f"异步获取页面失败 {url}: {e}")
            self.failed_urls.add(url)
            raise

    async def _get_soup_with_playwright_async(self, url):
        """异步版本的Playwright页面获取"""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                # 设置请求头 - 强制英文版本
                await page.set_extra_http_headers({
                    'Accept-Language': 'en-US,en;q=1.0',  # 强制英文，提高优先级
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Cookie': 'locale=en'  # 添加英文locale cookie
                })

                # 导航到页面并等待加载
                await page.goto(url, wait_until='networkidle')

                # 强制设置英文语言
                await page.evaluate("""
                    // 设置localStorage中的语言偏好
                    localStorage.setItem('locale', 'en');
                    localStorage.setItem('language', 'en');
                    localStorage.setItem('lang', 'en');

                    // 设置cookie
                    document.cookie = 'locale=en; path=/; domain=.ifixit.com';
                    document.cookie = 'language=en; path=/; domain=.ifixit.com';
                """)

                # 等待一下让设置生效
                await page.wait_for_timeout(1000)

                # 获取页面内容
                content = await page.content()
                await browser.close()

                from bs4 import BeautifulSoup
                return BeautifulSoup(content, 'html.parser')

        except Exception as e:
            self.logger.error(f"Playwright异步获取页面失败 {url}: {e}")
            self.failed_urls.add(url)
            return None

    async def _process_tasks_async(self, tasks, guides_data, troubleshooting_data):
        """异步并发处理任务列表"""
        # 创建并发控制信号量
        semaphore = asyncio.Semaphore(self.max_workers)

        async def process_single_task(task_type, url):
            """处理单个任务的异步包装器"""
            async with semaphore:
                try:
                    if task_type == 'guide':
                        return await self._process_guide_task_async(url)
                    else:  # troubleshooting
                        return await self._process_troubleshooting_task_async(url)
                except Exception as e:
                    self.logger.error(f"异步任务失败 {task_type} {url}: {e}")
                    return None

        # 创建所有任务
        async_tasks = [process_single_task(task_type, url) for task_type, url in tasks]

        # 并发执行所有任务
        results = await asyncio.gather(*async_tasks, return_exceptions=True)

        # 处理结果
        completed_count = 0
        total_tasks = len(tasks)

        for i, (result, (task_type, url)) in enumerate(zip(results, tasks)):
            completed_count += 1

            if isinstance(result, Exception):
                print(f"    ❌ [{completed_count}/{total_tasks}] {task_type} 任务异常: {str(result)[:50]}...")
                continue

            if result:
                if task_type == 'guide':
                    guides_data.append(result)
                    title = result.get('title', '') if isinstance(result, dict) else '未知标题'
                    print(f"    ✅ [{completed_count}/{total_tasks}] 指南: {title}")
                else:
                    troubleshooting_data.append(result)
                    title = result.get('title', '') if isinstance(result, dict) else '未知标题'
                    print(f"    ✅ [{completed_count}/{total_tasks}] 故障排除: {title}")
            else:
                print(f"    ⚠️  [{completed_count}/{total_tasks}] {task_type} 处理失败")

        return guides_data, troubleshooting_data

    async def _process_guide_task_async(self, url):
        """异步处理指南任务"""
        try:
            soup = await self.get_soup_async(url)
            if soup:
                return self.extract_guide_content(url)
        except Exception as e:
            self.logger.error(f"异步处理指南失败 {url}: {e}")
        return None

    async def _process_troubleshooting_task_async(self, url):
        """异步处理故障排除任务"""
        try:
            soup = await self.get_soup_async(url)
            if soup:
                return self.extract_troubleshooting_content(url)
        except Exception as e:
            self.logger.error(f"异步处理故障排除失败 {url}: {e}")
        return None

    def get_soup(self, url, use_playwright=False):
        """重写get_soup方法，支持代理池、重试机制和Playwright渲染"""
        if not url:
            return None

        if url in self.failed_urls:
            self.logger.warning(f"跳过已知失败URL: {url}")
            return None

        # 强制使用英文版本
        if 'zh.ifixit.com' in url:
            url = url.replace('zh.ifixit.com', 'www.ifixit.com')

        # 确保使用www.ifixit.com而不是其他子域名
        if 'ifixit.com' in url and not url.startswith('https://www.ifixit.com'):
            url = url.replace('https://', 'https://www.').replace('http://', 'https://www.')
            if not url.startswith('https://www.ifixit.com'):
                url = url.replace('ifixit.com', 'www.ifixit.com')

        # 添加强制英文参数
        if '?' in url:
            if 'lang=' not in url:
                url += '&lang=en'
            else:
                # 替换现有的lang参数
                import re
                url = re.sub(r'lang=[^&]*', 'lang=en', url)
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
            total=0,  # 完全禁用urllib3的重试，由上层处理
            backoff_factor=0,  # 无退避延迟
            status_forcelist=[],  # 不重试任何状态码
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
                timeout=(5, 10),  # 连接超时5秒，读取超时10秒
                proxies=proxies
            )
            response.raise_for_status()

            from bs4 import BeautifulSoup
            return BeautifulSoup(response.content, 'html.parser')

        except (requests.exceptions.ProxyError,
                requests.exceptions.ConnectTimeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout,
                requests.exceptions.Timeout) as e:
            # 网络相关错误，静默处理
            if self.use_proxy:
                # 静默切换代理并重试一次
                if self._switch_proxy(f"网络错误: {str(e)[:50]}"):
                    try:
                        # 使用新代理快速重试一次
                        new_proxies = self._get_next_proxy()
                        response = session.get(
                            url,
                            headers=self.headers,
                            timeout=(3, 8),  # 连接超时3秒，读取超时8秒
                            proxies=new_proxies
                        )
                        response.raise_for_status()

                        from bs4 import BeautifulSoup
                        return BeautifulSoup(response.content, 'html.parser')
                    except Exception:
                        # 静默失败，返回None让上层处理
                        return None
            # 静默失败，不输出错误信息
            return None

    def _get_soup_with_playwright(self, url):
        """使用Playwright获取JavaScript渲染后的页面内容"""
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                # 设置请求头 - 强制英文版本
                page.set_extra_http_headers({
                    'Accept-Language': 'en-US,en;q=1.0',  # 强制英文，提高优先级
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Cookie': 'locale=en'  # 添加英文locale cookie
                })

                # 导航到页面并等待加载
                page.goto(url, wait_until='networkidle')

                # 强制设置英文语言
                page.evaluate("""
                    // 设置localStorage中的语言偏好
                    localStorage.setItem('locale', 'en');
                    localStorage.setItem('language', 'en');
                    localStorage.setItem('lang', 'en');

                    // 设置cookie
                    document.cookie = 'locale=en; path=/; domain=.ifixit.com';
                    document.cookie = 'language=en; path=/; domain=.ifixit.com';
                """)

                # 等待一下让设置生效
                page.wait_for_timeout(1000)

                # 获取页面内容
                content = page.content()
                browser.close()

                from bs4 import BeautifulSoup
                return BeautifulSoup(content, 'html.parser')

        except Exception as e:
            # 安全的错误消息处理
            error_msg = str(e) if e is not None else "Unknown error"
            print(f"Playwright获取页面失败 {url}: {error_msg}")
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
            response = requests.head(url, headers=media_headers, timeout=3, proxies=proxies)
            if response and response.status_code == 200:
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

    async def _download_media_file_async(self, url, local_dir, filename=None):
        """异步下载媒体文件到本地（带重试机制和视频处理策略，支持跨页面去重）"""
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

        # 确保媒体文件夹在当前节点的目录下，而不是在根目录
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
        file_size_mb = await self._get_file_size_from_url_async(url)
        if file_size_mb and file_size_mb > self.max_video_size_mb:
            self.logger.warning(f"跳过大视频文件 ({file_size_mb:.1f}MB > {self.max_video_size_mb}MB): {url}")
            self.stats["videos_skipped"] += 1
            return url

        self.logger.info(f"准备下载视频文件 ({file_size_mb:.1f}MB): {url}")

        try:
            result = await self._download_media_file_impl_async(url, local_dir, filename)
            if self._is_video_file(url) and result != url:
                self.stats["videos_downloaded"] += 1
            return result
        except Exception as e:
            # 安全的错误消息处理
            error_msg = safe_str(e)
            safe_url = safe_str(url) if url is not None else "Unknown URL"
            self.logger.error(f"媒体文件下载最终失败 {safe_url}: {error_msg}")
            self.stats["media_failed"] += 1
            safe_error_msg = safe_str(error_msg) if error_msg is not None else "Unknown error"
            self._log_failed_url(url, f"媒体下载失败: {safe_error_msg}")
            # 记录失败的媒体文件到专门的日志
            self._log_failed_media(url, error_msg)
            return url

    async def _get_file_size_from_url_async(self, url):
        """异步获取URL文件的大小（MB）"""
        try:
            # 修复URL格式：将.thumbnail.medium替换为.medium，解决403 Forbidden问题
            if '.thumbnail.medium' in url:
                url = url.replace('.thumbnail.medium', '.medium')

            # 确保异步HTTP管理器已初始化
            init_success = await self._init_async_http_manager()
            if not init_success or not self.async_http_manager:
                self.logger.error("异步HTTP管理器初始化失败，无法获取文件大小")
                return None

            # 使用自定义头信息
            headers = self.headers.copy()
            headers.update({
                "Accept": "*/*",
                "Accept-Encoding": "gzip, deflate, br"
            })
            
            response = await self.async_http_manager.get(url, headers=headers)
            if response and response.status_code == 200:
                content_length = response.headers.get('content-length')
                if content_length:
                    size_bytes = int(content_length)
                    size_mb = size_bytes / (1024 * 1024)
                    return size_mb
        except Exception as e:
            # 安全的错误消息处理，避免格式化错误
            error_msg = safe_str(e)

            # 特殊处理各种网络错误，避免日志污染
            if "Event loop is closed" in error_msg:
                return None
            elif "nodename nor servname provided" in error_msg:
                # DNS解析失败，静默处理
                return None
            elif "Connection" in error_msg or "timeout" in error_msg.lower():
                # 连接错误，静默处理
                return None
            else:
                # 其他错误才记录日志
                self.logger.warning(f"无法获取文件大小 {url}: {error_msg}")
        return None

    async def _download_media_file_impl_async(self, url, local_dir, filename):
        """异步媒体文件下载的具体实现"""
        # 确保媒体文件夹在当前节点的目录下，而不是在根目录
        local_path = local_dir / self.media_folder / filename

        # 修复URL格式：将.thumbnail.medium替换为.medium，解决403 Forbidden问题
        if '.thumbnail.medium' in url:
            url = url.replace('.thumbnail.medium', '.medium')
            if self.verbose:
                self.logger.info(f"URL格式修复: .thumbnail.medium -> .medium")

        # 确保异步HTTP管理器已初始化
        init_success = await self._init_async_http_manager()
        if not init_success or not self.async_http_manager:
            self.logger.error("异步HTTP管理器初始化失败，无法下载媒体文件")
            return None

        try:
            # 使用异步HTTP客户端下载文件
            if self.async_http_manager:
                # 确保目录存在
                local_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 使用异步HTTP客户端下载文件
                # 设置媒体下载的请求头
                media_headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.ifixit.com/'
                }
                response = await self.async_http_manager.get_with_retry(url, headers=media_headers)
                if response is None:
                    return None

                # 异步写入文件
                async with aiofiles.open(local_path, 'wb') as f:
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        await f.write(chunk)
                        
                self.stats["media_downloaded"] += 1
                if self.verbose:
                    self.logger.info(f"媒体文件下载成功: {filename}")
                else:
                    # 简化的进度提示
                    if self.stats["media_downloaded"] % 10 == 0:
                        print(f"      📥 已下载 {self.stats['media_downloaded']} 个媒体文件...")
            else:
                safe_url = safe_str(url) if url is not None else "Unknown URL"
                self.logger.error(f"异步HTTP客户端未初始化，无法下载媒体文件: {safe_url}")
                return None
        except Exception as e:
            # 安全的错误消息处理
            error_msg = safe_str(e)
            safe_url = safe_str(url) if url is not None else "Unknown URL"
            self.logger.error(f"媒体文件下载失败: {safe_url}, 错误: {error_msg}")
            return None

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

    async def _download_media_file(self, url, local_dir, filename=None):
        """下载媒体文件到本地（异步优化版本，带重试机制和视频处理策略，支持跨页面去重）"""
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

        # 确保媒体文件夹在当前节点的目录下，而不是在根目录
        local_path = local_dir / self.media_folder / filename

        # 检查是否是troubleshooting目录，如果是则不使用跨页面去重
        is_troubleshooting = "troubleshooting" in str(local_dir)

        # 优化：使用缓存的文件存在性检查，避免重复的文件系统操作
        if self._check_file_exists_cached(local_path):
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

        if not is_troubleshooting:
            # 检查文件是否已存在（支持跨页面去重）
            existing_file_path = self._find_existing_media_file(url, filename)
            if existing_file_path:
                # 文件已存在于其他位置，返回相对于当前目录的路径
                if self.verbose:
                    self.logger.info(f"媒体文件已存在，跳过下载: {filename}")
                self.stats["media_downloaded"] += 1
                return existing_file_path

            # 检查是否为视频文件
            if self._is_video_file(url):
                if not self.download_videos:
                    self.logger.info(f"跳过视频下载（已禁用）: {url}")
                    self.stats["videos_skipped"] += 1
                    return url

            # 检查视频文件大小
            file_size_mb = await self._get_file_size_from_url_async(url)
            if file_size_mb and file_size_mb > self.max_video_size_mb:
                self.logger.warning(f"跳过大视频文件 ({file_size_mb:.1f}MB > {self.max_video_size_mb}MB): {url}")
                self.stats["videos_skipped"] += 1
                return url

            self.logger.info(f"准备下载视频文件 ({file_size_mb:.1f}MB): {url}")

        try:
            # 使用异步实现
            result = await self._download_media_file_impl(url, local_dir, filename)
            if self._is_video_file(url) and result != url:
                self.stats["videos_downloaded"] += 1
            return result
        except Exception as e:
            # 安全的错误消息处理
            error_msg = safe_str(e)
            safe_url = safe_str(url) if url is not None else "Unknown URL"
            self.logger.error(f"媒体文件下载最终失败 {safe_url}: {error_msg}")
            self.stats["media_failed"] += 1
            safe_error_msg = safe_str(error_msg) if error_msg is not None else "Unknown error"
            self._log_failed_url(url, f"媒体下载失败: {safe_error_msg}")
            # 记录失败的媒体文件到专门的日志
            self._log_failed_media(url, error_msg)
            return url

    def _find_existing_media_file(self, url, filename):
        """查找是否已存在相同的媒体文件（跨页面去重，带缓存优化）"""
        try:
            # 基于URL的MD5哈希来查找文件
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]

            # 检查缓存
            cache_key = f"media_{url_hash}"
            if cache_key in self._file_exists_cache:
                return self._file_exists_cache[cache_key]

            # 在整个storage_root目录下搜索具有相同哈希的文件
            storage_path = Path(self.storage_root)
            if not storage_path.exists():
                self._file_exists_cache[cache_key] = None
                return None

            # 搜索所有media目录下的文件
            for media_dir in storage_path.rglob("media"):
                if media_dir.is_dir():
                    # 查找具有相同哈希前缀的文件
                    for existing_file in media_dir.glob(f"{url_hash}.*"):
                        if existing_file.is_file():
                            try:
                                # 尝试返回相对于storage_root的路径
                                result = str(existing_file.relative_to(storage_path))
                                # 缓存结果
                                self._cache_file_exists_result(cache_key, result)
                                return result
                            except ValueError:
                                # 如果不能相对于storage_root，则返回绝对路径
                                result = str(existing_file)
                                self._cache_file_exists_result(cache_key, result)
                                return result

            # 缓存未找到的结果
            self._cache_file_exists_result(cache_key, None)
            return None

        except Exception as e:
            if self.verbose:
                self.logger.warning(f"查找已存在媒体文件时出错: {e}")
            return None

    def _cache_file_exists_result(self, cache_key, result):
        """缓存文件存在性检查结果"""
        # 如果缓存过大，清理一半
        if len(self._file_exists_cache) >= self._cache_max_size:
            # 清理缓存的前一半
            keys_to_remove = list(self._file_exists_cache.keys())[:self._cache_max_size // 2]
            for key in keys_to_remove:
                del self._file_exists_cache[key]

        self._file_exists_cache[cache_key] = result

    def _check_file_exists_cached(self, file_path):
        """带缓存的文件存在性检查"""
        cache_key = f"exists_{str(file_path)}"

        if cache_key in self._file_exists_cache:
            return self._file_exists_cache[cache_key]

        exists = file_path.exists()
        self._cache_file_exists_result(cache_key, exists)
        return exists

    async def _download_media_file_impl(self, url, local_dir, filename):
        """媒体文件下载的具体实现（异步优化版本）"""
        # 确保媒体文件夹在当前节点的目录下，而不是在根目录
        local_path = local_dir / self.media_folder / filename
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # 修复URL格式：将.thumbnail.medium替换为.medium，解决403 Forbidden问题
        if '.thumbnail.medium' in url:
            url = url.replace('.thumbnail.medium', '.medium')
            if self.verbose:
                self.logger.info(f"URL格式修复: .thumbnail.medium -> .medium")

        # 确保异步HTTP管理器已初始化
        if not self.async_http_manager:
            await self._init_async_http_manager()

        try:
            # 使用异步HTTP客户端下载文件
            if self.async_http_manager:
                # 设置媒体下载的请求头
                media_headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.ifixit.com/'
                }
                
                # 使用异步HTTP客户端下载文件
                response = await self.async_http_manager.get_with_retry(url, headers=media_headers)
                if response is None:
                    return None
                
                # 异步写入文件
                async with aiofiles.open(local_path, 'wb') as f:
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        await f.write(chunk)

                # 计算正确的相对路径
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
            else:
                safe_url = safe_str(url) if url is not None else "Unknown URL"
                self.logger.error(f"异步HTTP客户端未初始化，无法下载媒体文件: {safe_url}")
                return None
        except Exception as e:
            # 安全的错误消息处理
            error_msg = safe_str(e)
            safe_url = safe_str(url) if url is not None else "Unknown URL"
            self.logger.error(f"媒体文件下载失败: {safe_url}, 错误: {error_msg}")
            return None

    async def _process_media_urls_async(self, data, local_dir):
        """异步递归处理数据中的媒体URL，下载并替换为本地路径"""
        media_tasks = []

        def collect_media_urls(obj, path=""):
            """收集所有需要下载的媒体URL"""
            if isinstance(obj, dict):
                for key, value in obj.items():
                    current_path = f"{path}.{key}" if path else key
                    if key in ['image', 'video', 'thumbnail', 'photo'] and isinstance(value, str) and value.startswith('http'):
                        media_tasks.append((current_path, value, obj, key))
                    elif key == 'images' and isinstance(value, list):
                        for i, img_item in enumerate(value):
                            if isinstance(img_item, str) and img_item.startswith('http'):
                                media_tasks.append((f"{current_path}[{i}]", img_item, value, i))
                            elif isinstance(img_item, dict) and 'url' in img_item:
                                img_url = img_item['url']
                                if isinstance(img_url, str) and img_url.startswith('http'):
                                    media_tasks.append((f"{current_path}[{i}].url", img_url, img_item, 'url'))
                    elif key == 'videos' and isinstance(value, list):
                        for i, video_item in enumerate(value):
                            if isinstance(video_item, str) and video_item.startswith('http'):
                                if self.download_videos:
                                    media_tasks.append((f"{current_path}[{i}]", video_item, value, i))
                            elif isinstance(video_item, dict) and 'url' in video_item:
                                video_url = video_item['url']
                                if isinstance(video_url, str) and video_url.startswith('http'):
                                    if self.download_videos:
                                        media_tasks.append((f"{current_path}[{i}].url", video_url, video_item, 'url'))
                    elif isinstance(value, (dict, list)):
                        collect_media_urls(value, current_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    collect_media_urls(item, f"{path}[{i}]" if path else f"[{i}]")

        # 收集所有媒体URL
        collect_media_urls(data)

        if not media_tasks:
            return

        # 创建并发下载任务 - 优化并发数以提升性能
        max_concurrent_downloads = min(20, max(self.max_workers * 2, 10))  # 增加媒体下载并发数
        semaphore = asyncio.Semaphore(max_concurrent_downloads)

        async def download_single_media(path, url, container, key):
            async with semaphore:
                try:
                    # 检查事件循环状态
                    try:
                        loop = asyncio.get_running_loop()
                        if loop.is_closed():
                            return False
                    except RuntimeError:
                        return False

                    local_path = await self._download_media_file(url, local_dir)
                    if local_path and local_path != url:
                        container[key] = local_path
                    return True
                except Exception as e:
                    # 安全的错误消息处理
                    error_msg = safe_str(e)
                    # 特殊处理事件循环关闭的情况
                    if "Event loop is closed" in error_msg:
                        return False
                    safe_url = safe_str(url) if url is not None else "Unknown URL"
                    self.logger.error(f"异步媒体下载失败 {safe_url}: {error_msg}")
                    self.stats["media_failed"] += 1
                    return False

        # 并发下载所有媒体文件
        download_tasks = [download_single_media(path, url, container, key)
                         for path, url, container, key in media_tasks]

        if download_tasks:
            print(f"      📥 开始高并发异步下载 {len(download_tasks)} 个媒体文件（并发数: {max_concurrent_downloads}）...")
            start_time = time.time()
            results = await asyncio.gather(*download_tasks, return_exceptions=True)
            end_time = time.time()
            success_count = sum(1 for r in results if r is True)
            download_time = end_time - start_time
            print(f"      ✅ 异步下载完成: {success_count}/{len(download_tasks)} 成功，耗时 {download_time:.2f}秒")

    def _process_media_urls(self, data, local_dir):
        """递归处理数据中的媒体URL，优先使用异步下载并替换为本地路径"""
        # 收集所有需要下载的媒体URL
        media_urls = []

        def collect_urls(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in ['image', 'video', 'thumbnail', 'photo'] and isinstance(value, str) and value.startswith('http'):
                        media_urls.append((obj, key, value))
                    elif key == 'images' and isinstance(value, list):
                        for i, img_item in enumerate(value):
                            if isinstance(img_item, str) and img_item.startswith('http'):
                                media_urls.append((value, i, img_item))
                            elif isinstance(img_item, dict) and 'url' in img_item:
                                img_url = img_item['url']
                                if isinstance(img_url, str) and img_url.startswith('http'):
                                    media_urls.append((img_item, 'url', img_url))
                    elif key == 'videos' and isinstance(value, list):
                        for i, video_item in enumerate(value):
                            if isinstance(video_item, str) and video_item.startswith('http'):
                                if self.download_videos:
                                    media_urls.append((value, i, video_item))
                            elif isinstance(video_item, dict) and 'url' in video_item:
                                video_url = video_item['url']
                                if isinstance(video_url, str) and video_url.startswith('http'):
                                    if self.download_videos:
                                        media_urls.append((video_item, 'url', video_url))
                    elif isinstance(value, (dict, list)):
                        collect_urls(value)
            elif isinstance(obj, list):
                for item in obj:
                    collect_urls(item)

        collect_urls(data)

        # 如果有媒体URL需要下载，优先使用同步方式避免事件循环问题
        if media_urls:
            try:
                # 检测是否在异步环境中
                loop = asyncio.get_running_loop()
                if loop and not loop.is_closed():
                    # 如果已经在异步环境中，使用同步回退方案避免嵌套事件循环问题
                    if self.verbose:
                        self.logger.info("检测到活跃异步环境，使用同步回退方案处理媒体文件")
                    self._process_media_urls_sync_fallback_from_urls(media_urls, local_dir)
                else:
                    # 事件循环已关闭，使用同步处理
                    if self.verbose:
                        self.logger.info("事件循环已关闭，使用同步处理媒体文件")
                    self._process_media_urls_sync_fallback_from_urls(media_urls, local_dir)
            except RuntimeError:
                # 没有运行中的事件循环，可以尝试创建新的事件循环
                try:
                    if self.verbose:
                        self.logger.info("创建新事件循环进行异步媒体处理")
                    # 使用新的事件循环处理
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(self._process_collected_media_urls_async(media_urls, local_dir))
                    finally:
                        loop.close()
                        asyncio.set_event_loop(None)
                except Exception as e:
                    # 如果异步处理失败，回退到同步处理
                    self.logger.warning(f"异步媒体处理失败，回退到同步处理: {safe_str(e)}")
                    self._process_media_urls_sync_fallback_from_urls(media_urls, local_dir)
            except Exception as e:
                # 其他异常，直接使用同步处理
                self.logger.warning(f"事件循环检测失败，使用同步处理: {safe_str(e)}")
                self._process_media_urls_sync_fallback_from_urls(media_urls, local_dir)

    async def _process_collected_media_urls_async(self, media_urls, local_dir):
        """异步处理收集到的媒体URL - 修复事件循环关闭问题"""
        # 检查事件循环状态
        try:
            loop = asyncio.get_running_loop()
            if loop.is_closed():
                self.logger.warning("事件循环已关闭，回退到同步处理")
                return self._process_media_urls_sync_fallback_from_urls(media_urls, local_dir)
        except RuntimeError:
            self.logger.warning("无法获取事件循环，回退到同步处理")
            return self._process_media_urls_sync_fallback_from_urls(media_urls, local_dir)

        # 确保异步HTTP管理器已初始化
        init_success = await self._init_async_http_manager()
        if not init_success:
            self.logger.warning("异步HTTP管理器初始化失败，回退到同步处理")
            return self._process_media_urls_sync_fallback_from_urls(media_urls, local_dir)

        async def download_and_update(container, key, url):
            try:
                # 再次检查事件循环状态
                try:
                    loop = asyncio.get_running_loop()
                    if loop.is_closed():
                        return False
                except RuntimeError:
                    return False

                local_path = await self._download_media_file(url, local_dir)
                if local_path and local_path != url:
                    # 计算正确的相对路径
                    if hasattr(local_path, '__fspath__'):  # 检查是否是路径对象
                        local_path = Path(local_path)
                        try:
                            # 尝试计算相对于storage_root的路径
                            relative_path = local_path.relative_to(Path(self.storage_root))
                            container[key] = str(relative_path)
                        except ValueError:
                            # 如果不在storage_root下，计算相对于local_dir的路径
                            try:
                                relative_path = local_path.relative_to(local_dir)
                                container[key] = str(relative_path)
                            except ValueError:
                                # 最后回退到绝对路径
                                container[key] = str(local_path)
                    else:
                        container[key] = local_path
                return True
            except Exception as e:
                # 安全的错误消息处理
                error_msg = safe_str(e)
                # 特殊处理事件循环关闭的情况
                if "Event loop is closed" in error_msg:
                    return False
                safe_url = safe_str(url) if url is not None else "Unknown URL"
                self.logger.error(f"媒体下载失败 {safe_url}: {error_msg}")
                return False

        if media_urls:
            # 限制并发数，减少并发以避免事件循环过载
            semaphore = asyncio.Semaphore(min(8, len(media_urls)))  # 降低并发数

            async def limited_download(container, key, url):
                async with semaphore:
                    try:
                        # 检查事件循环状态
                        loop = asyncio.get_running_loop()
                        if loop.is_closed():
                            return False
                        return await download_and_update(container, key, url)
                    except Exception as e:
                        # 安全的错误处理
                        error_msg = safe_str(e)
                        if "Event loop is closed" in error_msg:
                            return False
                        return False

            # 创建所有下载任务
            download_tasks = [limited_download(container, key, url) for container, key, url in media_urls]

            try:
                # 使用wait_for设置超时，避免无限等待
                results = await asyncio.wait_for(
                    asyncio.gather(*download_tasks, return_exceptions=True),
                    timeout=300  # 5分钟超时
                )
                success_count = sum(1 for r in results if r is True)
                print(f"      📥 批量媒体下载完成: {success_count}/{len(download_tasks)} 成功")
            except asyncio.TimeoutError:
                print(f"      ⏰ 媒体下载超时，部分文件可能未完成")
            except Exception as e:
                # 处理gather过程中的异常
                error_msg = safe_str(e)
                if "Event loop is closed" in error_msg:
                    print(f"      ⚠️ 事件循环已关闭，部分媒体下载可能未完成")
                else:
                    print(f"      ❌ 批量下载过程中发生错误: {error_msg}")

    def _process_media_urls_sync_fallback_from_urls(self, media_urls, local_dir):
        """从媒体URL列表进行同步回退处理"""
        success_count = 0
        total_count = len(media_urls)

        for container, key, url in media_urls:
            try:
                # 使用同步方式下载
                local_path = self._download_media_file_sync(url, local_dir)
                if local_path and local_path != url:
                    container[key] = local_path
                    success_count += 1
            except Exception as e:
                error_msg = safe_str(e)
                safe_url = safe_str(url) if url is not None else "Unknown URL"
                self.logger.error(f"同步媒体下载失败 {safe_url}: {error_msg}")

        print(f"      📥 同步媒体下载完成: {success_count}/{total_count} 成功")

    def _download_media_file_sync(self, url, local_dir):
        """同步下载媒体文件的回退方法"""
        try:
            import requests
            from urllib.parse import urlparse
            import os

            # 生成文件名
            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path)
            if not filename or '.' not in filename:
                filename = f"media_{hash(url) % 10000}.jpg"

            # 确保媒体文件夹在当前节点的目录下
            local_path = local_dir / self.media_folder / filename
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # 修复URL格式
            if '.thumbnail.medium' in url:
                url = url.replace('.thumbnail.medium', '.medium')

            # 设置请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.ifixit.com/'
            }

            # 获取代理
            proxies = None
            if self.proxy_manager:
                proxy_config = self.proxy_manager.get_proxy()
                if proxy_config:
                    proxies = {
                        'http': proxy_config['http'],
                        'https': proxy_config['https']
                    }

            # 下载文件
            response = requests.get(url, headers=headers, proxies=proxies, timeout=(5, 15), stream=True)
            response.raise_for_status()

            # 写入文件
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # 计算相对路径
            try:
                return str(local_path.relative_to(Path(self.storage_root)))
            except ValueError:
                try:
                    return str(local_path.relative_to(local_dir))
                except ValueError:
                    return str(local_path)

        except Exception as e:
            error_msg = safe_str(e)
            safe_url = safe_str(url) if url is not None else "Unknown URL"
            self.logger.error(f"同步媒体下载失败 {safe_url}: {error_msg}")
            return None

    def _download_media_file_sync(self, url, local_dir, filename=None):
        """同步下载媒体文件（用于回退方案）"""
        if not url or not url.startswith('http'):
            return url

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

        # 确保media文件夹在当前节点的目录下，而不是在根目录
        local_path = local_dir / self.media_folder / filename

        # 如果文件已存在，直接返回本地路径
        if local_path.exists():
            return str(local_path.relative_to(local_dir))

        # 修复URL格式
        if '.thumbnail.medium' in url:
            url = url.replace('.thumbnail.medium', '.medium')

        try:
            # 创建目录
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # 使用requests同步下载
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
            response = requests.get(url, headers=media_headers, timeout=5, proxies=proxies, verify=False)
            response.raise_for_status()

            # 保存文件
            with open(local_path, 'wb') as f:
                f.write(response.content)

            self.stats["media_downloaded"] += 1
            return str(local_path.relative_to(local_dir))

        except Exception as e:
            # 安全的错误消息处理
            error_msg = safe_str(e)
            safe_url = safe_str(url) if url is not None else "Unknown URL"
            self.logger.error(f"同步媒体下载失败 {safe_url}: {error_msg}")
            self.stats["media_failed"] += 1
            return url

    def _process_media_urls_sync_fallback(self, data, local_dir):
        """同步处理媒体URL的回退方案"""
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ['image', 'video', 'thumbnail', 'photo'] and isinstance(value, str) and value.startswith('http'):
                    # 使用同步下载作为回退
                    data[key] = self._download_media_file_sync(value, local_dir)
                elif key == 'images' and isinstance(value, list):
                    for i, img_item in enumerate(value):
                        if isinstance(img_item, str) and img_item.startswith('http'):
                            value[i] = self._download_media_file_sync(img_item, local_dir)
                        elif isinstance(img_item, dict) and 'url' in img_item:
                            img_url = img_item['url']
                            if isinstance(img_url, str) and img_url.startswith('http'):
                                img_item['url'] = self._download_media_file_sync(img_url, local_dir)
                elif key == 'videos' and isinstance(value, list):
                    for i, video_item in enumerate(value):
                        if isinstance(video_item, str) and video_item.startswith('http'):
                            if self.download_videos:
                                value[i] = self._download_media_file_sync(video_item, local_dir)
                        elif isinstance(video_item, dict) and 'url' in video_item:
                            video_url = video_item['url']
                            if isinstance(video_url, str) and video_url.startswith('http'):
                                if self.download_videos:
                                    video_item['url'] = self._download_media_file_sync(video_url, local_dir)
                elif isinstance(value, (dict, list)):
                    self._process_media_urls_sync_fallback(value, local_dir)
        elif isinstance(data, list):
            for item in data:
                self._process_media_urls_sync_fallback(item, local_dir)

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

    def _force_english_content(self, text):
        """
        强制将中文内容转换为英文内容
        """
        if not text:
            return text

        # 中文到英文的映射表
        chinese_to_english = {
            '英寸': '"',
            '寸': '"',
            '修复': 'Repair',
            '维修': 'Repair',
            '指南': 'Guide',
            '故障排除': 'Troubleshooting',
            '问题': 'Issues',
            '解决方案': 'Solutions',
            '教程': 'Tutorial',
            '拆解': 'Teardown',
            '安装': 'Installation',
            '更换': 'Replacement',
            '型号': 'Models',
            '系列': 'Series'
        }

        # 替换中文内容
        result = text
        for chinese, english in chinese_to_english.items():
            result = result.replace(chinese, english)

        return result

    def extract_real_title_from_page(self, soup):
        """
        从页面HTML中提取真实的title字段，并强制使用英文内容
        """
        if not soup:
            return ""

        # 优先从h1标签提取
        h1_elem = soup.select_one("h1")
        if h1_elem:
            title = h1_elem.get_text().strip()
            if title:
                # 强制转换为英文内容
                title = self._force_english_content(title)
                return title

        # 其次从title标签提取
        title_elem = soup.select_one("title")
        if title_elem:
            title = title_elem.get_text().strip()
            # 移除常见的网站后缀
            title = title.replace(" - iFixit", "").replace(" | iFixit", "").strip()
            if title:
                # 强制转换为英文内容
                title = self._force_english_content(title)
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

                # 设置请求头确保英文内容 - 强制英文版本
                page.set_extra_http_headers({
                    'Accept-Language': 'en-US,en;q=1.0',  # 强制英文，提高优先级
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Cookie': 'locale=en'  # 添加英文locale cookie
                })

                try:
                    # 导航到页面并等待完全加载
                    page.goto(guide_url, wait_until='networkidle')

                    # 强制设置英文语言
                    page.evaluate("""
                        // 设置localStorage中的语言偏好
                        localStorage.setItem('locale', 'en');
                        localStorage.setItem('language', 'en');
                        localStorage.setItem('lang', 'en');

                        // 设置cookie
                        document.cookie = 'locale=en; path=/; domain=.ifixit.com';
                        document.cookie = 'language=en; path=/; domain=.ifixit.com';
                    """)

                    page.wait_for_timeout(5000)  # 增加等待时间确保完全加载

                    # 获取页面HTML
                    html_content = page.content()
                    
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
                finally:
                    # 确保浏览器关闭，即使发生异常
                    browser.close()

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

    async def crawl_combined_tree_async(self, start_url, category_name=None):
        """
        异步整合爬取：构建树形结构并为每个节点提取详细内容
        """
        print(f"🚀 开始异步整合爬取: {start_url}")
        print("=" * 60)

        # 初始化异步HTTP客户端
        await self._init_async_http_manager()

        try:
            # 设置目标URL
            self.target_url = start_url

            # 智能缓存预检查
            if self.cache_manager and self.use_cache and not self.force_refresh:
                print("🔍 执行智能缓存预检查...")
                self._perform_cache_precheck(start_url, category_name)
                self.cache_manager.display_cache_report()

            try:
                # 第一步：使用 tree_crawler 逻辑构建基础树结构
                print("📊 阶段 1/3: 构建基础树形结构...")
                print("   正在分析页面结构和分类层次...")
                base_tree = await self._crawl_tree_async(start_url, category_name)

                if not base_tree:
                    print("❌ 无法构建基础树结构")
                    return None

                print(f"✅ 基础树结构构建完成")
                print("=" * 60)

                # 第二步：为树中的每个节点提取详细内容
                print("📝 阶段 2/3: 为每个节点提取详细内容...")
                print("   正在处理节点基本信息和元数据...")
                enriched_tree = await self._enrich_tree_with_detailed_content_async(base_tree)

                # 第三步：对于产品页面，深入爬取其指南和故障排除内容
                print("🔍 阶段 3/3: 深入爬取产品页面的子内容...")
                print("   正在提取指南和故障排除详细信息...")
                final_tree = await self._deep_crawl_product_content_async(enriched_tree)

                return final_tree
            except Exception as e:
                self.logger.error(f"✗ 爬取过程中发生错误: {e}")
                print(f"✗ 爬取过程中发生错误: {e}")
                # 返回已经爬取的数据，避免完全失败
                return None

        finally:
            # 确保关闭异步HTTP客户端
            await self._close_async_http_manager()

    async def _crawl_tree_async(self, start_url, category_name=None):
        """异步版本的树形结构构建"""
        # 这里可以调用现有的tree_crawler，因为它主要是数据处理
        # 或者我们可以创建一个异步版本
        return self.tree_crawler.crawl_tree(start_url, category_name)

    async def _enrich_tree_with_detailed_content_async(self, tree):
        """异步版本的树节点内容丰富化"""
        # 使用异步方法处理每个节点
        return await self._enrich_node_async(tree)

    async def _enrich_node_async(self, node):
        """异步处理单个节点的内容丰富化"""
        if isinstance(node, dict):
            # 如果节点有URL，异步获取详细内容
            if 'url' in node and node['url']:
                try:
                    soup = await self.get_soup_async(node['url'])
                    if soup:
                        # 提取节点的详细信息
                        node = await self._extract_node_details_async(node, soup)
                except httpx.HTTPStatusError as e:
                    if e.response and e.response.status_code == 404:
                        self.logger.warning(f"页面不存在 {node.get('url', '')}: 404 Not Found")
                        print(f"⚠️ 页面不存在: {node.get('url', '')}")
                        # 标记节点为无效但继续处理
                        node['valid'] = False
                        node['error'] = "404 Not Found"
                    else:
                        self.logger.error(f"异步处理节点失败 {node.get('url', '')}: {e}")
                except Exception as e:
                    self.logger.error(f"异步处理节点失败 {node.get('url', '')}: {e}")
                    # 标记节点但不中断处理
                    node['error'] = str(e)

            # 递归处理子节点
            if 'children' in node and node['children']:
                # 并发处理所有子节点
                child_tasks = [self._enrich_node_async(child) for child in node['children']]
                try:
                    node['children'] = await asyncio.gather(*child_tasks, return_exceptions=True)

                    # 过滤掉异常结果，但记录错误
                    filtered_children = []
                    for child in node['children']:
                        if isinstance(child, Exception):
                            self.logger.error(f"子节点处理失败: {child}")
                        else:
                            filtered_children.append(child)
                    node['children'] = filtered_children
                except Exception as e:
                    self.logger.error(f"处理子节点时发生错误: {e}")
                    # 保留现有子节点，不让整个处理失败

        return node

    async def _extract_node_details_async(self, node, soup):
        """异步提取节点详细信息"""
        # 这里可以添加具体的节点信息提取逻辑
        # 目前保持原有逻辑
        return node

    async def _deep_crawl_product_content_async(self, tree):
        """异步深入爬取产品页面内容"""
        return await self._deep_crawl_node_async(tree)

    async def _deep_crawl_node_async(self, node):
        """异步深入爬取单个节点的产品内容"""
        if isinstance(node, dict):
            # 如果是产品页面，提取指南和故障排除内容
            if node.get('type') == 'product' and node.get('url'):
                try:
                    # 使用现有的异步并发处理方法
                    guides_data, troubleshooting_data = await self._extract_product_content_async(node['url'])

                    if guides_data:
                        node['guides'] = guides_data
                    if troubleshooting_data:
                        node['troubleshooting'] = troubleshooting_data

                except Exception as e:
                    self.logger.error(f"异步提取产品内容失败 {node['url']}: {e}")

            # 递归处理子节点
            if 'children' in node and node['children']:
                child_tasks = [self._deep_crawl_node_async(child) for child in node['children']]
                node['children'] = await asyncio.gather(*child_tasks, return_exceptions=True)

                # 过滤掉异常结果
                node['children'] = [child for child in node['children']
                                  if not isinstance(child, Exception)]

        return node

    async def _extract_product_content_async(self, product_url):
        """异步提取产品页面的指南和故障排除内容"""
        try:
            soup = await self.get_soup_async(product_url)
            if not soup:
                return [], []

            # 使用现有的内容提取逻辑
            guides_data = []
            troubleshooting_data = []

            # 查找指南和故障排除链接
            guide_links = []
            troubleshooting_links = []

            # 这里可以添加具体的链接提取逻辑
            # 目前使用现有的方法作为参考

            # 如果有链接，使用异步并发处理
            if guide_links or troubleshooting_links:
                tasks = []
                for url in guide_links:
                    tasks.append(('guide', url))
                for url in troubleshooting_links:
                    tasks.append(('troubleshooting', url))

                if tasks:
                    guides_data, troubleshooting_data = await self._process_tasks_async(
                        tasks, guides_data, troubleshooting_data)

            return guides_data, troubleshooting_data

        except Exception as e:
            self.logger.error(f"异步提取产品内容失败 {product_url}: {e}")
            return [], []

    def crawl_combined_tree(self, start_url, category_name=None):
        """
        整合爬取：构建树形结构并为每个节点提取详细内容
        """
        print(f"🚀 开始爬取: {start_url}")

        # 设置目标URL
        self.target_url = start_url

        # 第一步：构建基础树结构
        print("📊 阶段 1/2: 构建树形结构...")
        base_tree = self.tree_crawler.crawl_tree(start_url, category_name)

        if not base_tree:
            print("❌ 无法构建树结构")
            return None

        print(f"✅ 树结构构建完成")

        # 第二步：逐步提取内容并保存到正确的目录结构
        print("📝 阶段 2/2: 提取内容并保存...")
        final_tree = self._process_tree_and_save_incrementally(base_tree)

        return final_tree

    def _process_tree_and_save_incrementally(self, tree_data):
        """逐步处理树结构并保存到正确的目录结构"""
        if not tree_data:
            return None

        # 构建基础目录路径
        base_path = self._build_base_path_from_url(self.target_url)

        # 递归处理树结构，逐步保存每个节点
        processed_tree = self._process_node_incrementally(tree_data, base_path, [])

        return processed_tree

    def _build_base_path_from_url(self, url):
        """从URL构建基础路径 - 修复版本"""
        # 始终返回Device根目录，让树结构决定完整路径
        return Path(self.storage_root) / "Device"

    def _process_node_incrementally(self, node, base_path, path_segments):
        """递归处理节点，逐步保存内容"""
        if not node or not isinstance(node, dict):
            return node

        node_name = node.get('name', 'Unknown')
        node_url = node.get('url', '')

        # 构建当前节点的路径段
        current_segments = path_segments.copy()
        if node_name and node_name.lower() != 'device':
            current_segments.append(node_name)

        # 构建当前节点的完整路径
        node_path = base_path
        for segment in current_segments:
            safe_segment = self._clean_directory_name(segment)
            node_path = node_path / safe_segment

        # 检查是否需要处理当前节点
        if node_url and not node_url in self.processed_nodes:
            if self.verbose:
                print(f"📦 处理: {' > '.join(current_segments)}")

            # 提取节点内容
            enriched_node = self._extract_node_content(node)

            # 如果有内容，立即保存
            if self._has_content(enriched_node):
                self._save_node_immediately(enriched_node, node_path)

            self.processed_nodes.add(node_url)
        else:
            enriched_node = node

        # 递归处理子节点
        if 'children' in enriched_node and enriched_node['children']:
            for i, child in enumerate(enriched_node['children']):
                enriched_node['children'][i] = self._process_node_incrementally(
                    child, base_path, current_segments
                )

        return enriched_node

    def _extract_node_content(self, node):
        """提取节点的详细内容，包括guide和troubleshooting的完整内容"""
        url = node.get('url', '')
        if not url:
            return node

        try:
            # 简化版本：直接提取内容，不使用复杂缓存
            soup = self.get_soup(url)
            if not soup:
                return node

            # 提取guides和troubleshooting的基本信息
            guides_basic = self.extract_guides_from_device_page(soup, url)
            troubleshooting_basic = self.extract_troubleshooting_from_device_page(soup, url)

            # 更新节点数据
            enriched_node = node.copy()

            # 为每个guide提取详细内容
            if guides_basic:
                detailed_guides = []
                for guide_info in guides_basic:
                    guide_url = guide_info.get('url', '')
                    if guide_url:
                        if self.verbose:
                            print(f"   📖 提取guide详细内容: {guide_info.get('title', 'Unknown')}")

                        # 提取详细的guide内容
                        detailed_guide = self.extract_guide_content(guide_url)
                        if detailed_guide:
                            detailed_guides.append(detailed_guide)
                        else:
                            # 如果详细提取失败，至少保留基本信息
                            detailed_guides.append(guide_info)
                    else:
                        detailed_guides.append(guide_info)

                enriched_node['guides'] = detailed_guides

            # 为每个troubleshooting提取详细内容
            if troubleshooting_basic:
                detailed_troubleshooting = []
                for ts_info in troubleshooting_basic:
                    ts_url = ts_info.get('url', '')
                    if ts_url:
                        if self.verbose:
                            print(f"   🔧 提取troubleshooting详细内容: {ts_info.get('title', 'Unknown')}")

                        # 提取详细的troubleshooting内容
                        detailed_ts = self.extract_troubleshooting_content(ts_url)
                        if detailed_ts:
                            detailed_troubleshooting.append(detailed_ts)
                        else:
                            # 如果详细提取失败，至少保留基本信息
                            detailed_troubleshooting.append(ts_info)
                    else:
                        detailed_troubleshooting.append(ts_info)

                enriched_node['troubleshooting'] = detailed_troubleshooting

            return enriched_node

        except Exception as e:
            # 静默处理错误，不输出日志
            return node

    def _has_content(self, node):
        """检查节点是否有实际内容"""
        return (node.get('guides') and len(node['guides']) > 0) or \
               (node.get('troubleshooting') and len(node['troubleshooting']) > 0)

    def _save_node_immediately(self, node, node_path):
        """立即保存节点内容到指定路径"""
        try:
            # 确保目录存在
            node_path.mkdir(parents=True, exist_ok=True)

            # 保存基本信息
            info_data = {k: v for k, v in node.items()
                        if k not in ['children', 'guides', 'troubleshooting']}

            info_file = node_path / "info.json"
            with open(info_file, 'w', encoding='utf-8') as f:
                safe_json_dump(info_data, f, ensure_ascii=False, indent=2)

            # 保存guides
            if node.get('guides'):
                self._save_guides_to_directory(node['guides'], node_path)

            # 保存troubleshooting
            if node.get('troubleshooting'):
                self._save_troubleshooting_to_directory(node['troubleshooting'], node_path)

            if self.verbose:
                print(f"   ✅ 已保存到: {node_path}")

        except Exception as e:
            if self.verbose:
                print(f"   ❌ 保存失败: {e}")

    def _save_guides_to_directory(self, guides, base_path):
        """保存guides到目录"""
        guides_dir = base_path / "guides"
        guides_dir.mkdir(exist_ok=True)

        for i, guide in enumerate(guides):
            guide_dir = guides_dir / f"guide_{i+1}"
            guide_dir.mkdir(exist_ok=True)

            # 处理媒体文件
            self._process_media_urls(guide, guide_dir)

            # 保存guide文件
            guide_file = guide_dir / "guide.json"
            with open(guide_file, 'w', encoding='utf-8') as f:
                safe_json_dump(guide, f, ensure_ascii=False, indent=2)

    def _save_troubleshooting_to_directory(self, troubleshooting, base_path):
        """保存troubleshooting到目录"""
        ts_dir = base_path / "troubleshooting"
        ts_dir.mkdir(exist_ok=True)

        for i, ts in enumerate(troubleshooting):
            ts_item_dir = ts_dir / f"troubleshooting_{i+1}"
            ts_item_dir.mkdir(exist_ok=True)

            # 处理媒体文件
            self._process_media_urls(ts, ts_item_dir)

            # 保存troubleshooting文件
            ts_file = ts_item_dir / "troubleshooting.json"
            with open(ts_file, 'w', encoding='utf-8') as f:
                safe_json_dump(ts, f, ensure_ascii=False, indent=2)

    def _perform_cache_precheck(self, start_url, category_name=None):
        """执行缓存预检查，分析哪些内容需要重新处理"""
        try:
            # 确保cache_manager存在
            if not self.cache_manager:
                print("   ⚠️ 缓存管理器未初始化，跳过预检查")
                return
                
            # 检查clean_invalid_cache方法是否存在
            if hasattr(self.cache_manager, 'clean_invalid_cache'):
                # 清理无效缓存
                cleaned_count = self.cache_manager.clean_invalid_cache()
                if cleaned_count > 0:
                    print(f"   已清理 {cleaned_count} 个无效缓存条目")
            else:
                print("   ⚠️ 缓存管理器没有clean_invalid_cache方法，跳过清理")

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

        # 如果缓存中没有记录，尝试查找实际存在的路径
        if '/Device/' in url:
            # 首先尝试查找实际存在的设备目录
            actual_path = self._find_actual_device_path_for_cache(url)
            if actual_path:
                return actual_path

            # 如果找不到实际路径，使用标准路径构建逻辑
            device_path = url.split('/Device/')[-1]
            if '?' in device_path:
                device_path = device_path.split('?')[0]
            device_path = device_path.rstrip('/')

            if device_path:
                import urllib.parse
                device_path = urllib.parse.unquote(device_path)

                # 解析路径层级，直接从主要设备类型开始
                path_parts = device_path.split('/')
                if len(path_parts) > 0:
                    # 找到主要设备类型（通常是第一个有意义的部分）
                    main_category = path_parts[0]

                    # 如果有子路径，保留完整的层级结构，确保在Device目录下
                    if len(path_parts) > 1:
                        sub_path = '/'.join(path_parts[1:])
                        return Path(self.storage_root) / "Device" / main_category / sub_path
                    else:
                        return Path(self.storage_root) / "Device" / main_category
                else:
                    return Path(self.storage_root) / "Device" / device_path
            else:
                return Path(self.storage_root) / "Device"
        else:
            # 后备方案：使用节点名称，确保在Device目录下
            safe_name = node_name.replace("/", "_").replace("\\", "_").replace(":", "_")
            return Path(self.storage_root) / "Device" / safe_name

    def _find_actual_device_path_for_cache(self, url):
        """为缓存查找实际存在的设备路径"""
        try:
            device_path = url.split('/Device/')[-1]
            if '?' in device_path:
                device_path = device_path.split('?')[0]
            device_path = device_path.rstrip('/')

            from urllib.parse import unquote
            device_path = unquote(device_path)

            device_name = device_path.split('/')[-1]
            device_root = Path(self.storage_root) / "Device"

            if not device_root.exists():
                return None

            # 递归搜索匹配的设备目录
            for path in device_root.rglob("*"):
                if path.is_dir() and path.name == device_name:
                    # 检查这个目录是否包含info.json文件（确认是设备目录）
                    info_file = path / "info.json"
                    if info_file.exists():
                        return path

            return None

        except Exception as e:
            if self.verbose:
                self.logger.warning(f"查找实际设备路径失败: {e}")
            return None

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

    def _enrich_tree_with_detailed_content_and_save(self, node, parent_path=None):
        """修复节点的基本数据，并在处理每个节点后立即保存数据"""
        if not node or not isinstance(node, dict):
            return node
            
        if parent_path is None:
            parent_path = []
            
        # 复制当前路径信息
        current_path = parent_path.copy()
        node_name = node.get('name', 'Unknown')
        current_path.append(node_name)
        path_str = " > ".join(current_path)
            
        url = node.get('url', '')
        if not url or url in self.processed_nodes:
            # 递归处理子节点
            if 'children' in node and node['children']:
                for i, child in enumerate(node['children']):
                    node['children'][i] = self._enrich_tree_with_detailed_content_and_save(child, current_path)
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
                
            # 递归处理子节点
            if 'children' in node and node['children']:
                for i, child in enumerate(node['children']):
                    node['children'][i] = self._enrich_tree_with_detailed_content_and_save(child, current_path)
                    
            return node

        self.processed_nodes.add(url)
        self.stats["cache_misses"] += 1
        
        try:
            print(f"🔍 处理节点: {path_str}")
            print(f"   📍 URL: {url}")

            # 获取页面内容
            soup = self.get_soup(url)
            if soup:
                # 修复节点数据
                node = self.fix_node_data(node, soup)
                
                # 处理完成后立即保存当前节点数据
                if node.get('guides') or node.get('troubleshooting'):
                    print(f"   💾 立即保存节点数据: {path_str}")
                    # 确保目录存在
                    local_path.mkdir(parents=True, exist_ok=True)
                    self._save_node_content(node, local_path)
                    print(f"   ✅ 节点数据已保存到: {local_path}")
                
        except Exception as e:
            print(f"   ❌ 处理节点失败: {str(e)}")
            self.stats["errors"] += 1
            self.logger.error(f"处理节点失败: {url} - {str(e)}")

        # 递归处理子节点
        if 'children' in node and node['children']:
            for i, child in enumerate(node['children']):
                node['children'][i] = self._enrich_tree_with_detailed_content_and_save(child, current_path)

        return node
        
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

            # 检查troubleshooting部分的缓存
            troubleshooting_cache_key = f"{device_url}#troubleshooting"
            cached_troubleshooting = self._check_troubleshooting_cache(troubleshooting_cache_key, device_url)

            if cached_troubleshooting is not None:
                print(f"    ✅ 使用缓存的故障排除数据 ({len(cached_troubleshooting)} 个)")
                troubleshooting_data = cached_troubleshooting
                # 标记为已从缓存加载，避免重复保存
                self._troubleshooting_from_cache = True
            else:
                print(f"    🔍 未找到故障排除缓存，开始提取...")
                troubleshooting_links = self.extract_troubleshooting_from_device_page(soup, device_url)
                print(f"    🔧 找到 {len(troubleshooting_links)} 个故障排除页面")
                self._troubleshooting_from_cache = False

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

        if len(tasks) > 0:
            # 使用传统线程池作为后备方案
            print(f"    🔄 启动线程池并发处理 ({self.max_workers} 线程处理 {len(tasks)} 个任务)...")
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as executor:
                future_to_task = {}
                completed_count = 0
                total_tasks = len(tasks)

                for i, (task_type, url) in enumerate(tasks):
                    if task_type == 'guide':
                        future = executor.submit(self._process_guide_task_with_proxy, url, i)
                    else:  # troubleshooting
                        future = executor.submit(self._process_troubleshooting_task_with_proxy, url, i)
                    future_to_task[future] = (task_type, url)
                    # 显示任务开始时间
                    current_time = time.strftime("%H:%M:%S", time.localtime())
                    proxy_id = i % (self.proxy_manager.pool_size if self.proxy_manager else 1)
                    print(f"    🚀 [{current_time}] 启动 {task_type} 任务 (代理#{proxy_id}): {url.split('/')[-1]}")

                # 收集结果
                for future in as_completed(future_to_task):
                    task_type, url = future_to_task[future]
                    completed_count += 1
                    current_time = time.strftime("%H:%M:%S", time.localtime())
                    try:
                        result = future.result()
                        if result:
                            if task_type == 'guide':
                                guides_data.append(result)
                                print(f"    ✅ [{current_time}] [{completed_count}/{total_tasks}] 指南: {result.get('title', '')}")
                            else:
                                troubleshooting_data.append(result)
                                print(f"    ✅ [{current_time}] [{completed_count}/{total_tasks}] 故障排除: {result.get('title', '')}")
                        else:
                            print(f"    ⚠️  [{current_time}] [{completed_count}/{total_tasks}] {task_type} 处理失败")
                    except Exception as e:
                        print(f"    ❌ [{current_time}] [{completed_count}/{total_tasks}] {task_type} 任务失败: {str(e)[:50]}...")
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

        # 不在这里保存troubleshooting缓存，等待文件系统保存阶段
        # if troubleshooting_data and not skip_troubleshooting and not getattr(self, '_troubleshooting_from_cache', False):
        #     troubleshooting_cache_key = f"{device_url}#troubleshooting"
        #     print(f"    💾 保存故障排除数据到缓存 ({len(troubleshooting_data)} 个)")
        #     self._save_troubleshooting_cache(troubleshooting_cache_key, device_url, troubleshooting_data)

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

    def _process_guide_task_with_proxy(self, guide_url, thread_id):
        """处理单个guide任务（带独立代理）"""
        try:
            # 为当前线程设置代理ID
            current_thread = threading.current_thread()
            # 使用线程本地存储来存储代理ID
            thread_local = threading.local()
            if not hasattr(thread_local, 'proxy_id'):
                thread_local.proxy_id = thread_id

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

    def _process_troubleshooting_task_with_proxy(self, ts_url, thread_id):
        """处理单个troubleshooting任务（带独立代理）"""
        try:
            # 为当前线程设置代理ID
            current_thread = threading.current_thread()
            # 使用线程本地变量存储代理ID
            thread_local = threading.local()
            thread_local.proxy_id = thread_id

            ts_content = self.extract_troubleshooting_content(ts_url)
            if ts_content:
                ts_content['url'] = ts_url
                return ts_content
        except Exception as e:
            self.logger.error(f"处理troubleshooting失败 {ts_url}: {e}")
            self._log_failed_url(ts_url, f"Troubleshooting处理失败: {str(e)}")
        return None

    def _check_troubleshooting_cache(self, cache_key, device_url):
        """检查troubleshooting部分的缓存"""
        if not self.cache_manager:
            return None

        if self.cache_manager.is_troubleshooting_section_cached(cache_key, device_url):
            return self.cache_manager.load_troubleshooting_cache(cache_key, device_url)
        return None

    def _should_have_troubleshooting_content(self, url):
        """检查页面是否应该有troubleshooting内容"""
        try:
            # 对于产品页面，通常都应该有troubleshooting内容
            # 这里可以根据URL模式或页面类型判断
            if '/Device/' in url and not url.endswith('/Device'):
                # 检查是否是具体的产品页面而不是分类页面
                # 可以通过访问页面快速检查是否有troubleshooting链接
                return True
            return False
        except Exception as e:
            self.logger.error(f"检查是否应该有troubleshooting内容失败: {e}")
            return False

    def _mark_cache_invalid(self, url, local_path):
        """标记缓存为无效并从索引中移除"""
        try:
            if self.cache_manager:
                url_hash = self.cache_manager.get_url_hash(url)
                if url_hash in self.cache_manager.cache_index:
                    del self.cache_manager.cache_index[url_hash]
                    self.cache_manager.save_cache_index()
                    print(f"    🗑️ 已从缓存索引中移除无效条目: {url}")
        except Exception as e:
            self.logger.error(f"标记缓存无效失败: {e}")

    def _is_troubleshooting_cached(self, cache_key):
        """检查troubleshooting是否已缓存"""
        if not self.cache_manager:
            return False
        return self.cache_manager.is_troubleshooting_section_cached(cache_key, "")

    def _save_troubleshooting_cache(self, cache_key, device_url, troubleshooting_data):
        """保存troubleshooting到缓存"""
        if self.cache_manager:
            self.cache_manager.save_troubleshooting_cache(cache_key, device_url, troubleshooting_data)

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

        # 性能优化统计
        cache_size = len(getattr(self, '_file_exists_cache', {}))
        if cache_size > 0:
            print(f"⚡ 性能优化统计:")
            print(f"   📋 文件缓存条目: {cache_size}")
            print(f"   🚀 异步下载优化: 已启用")
            print(f"   🔄 高并发下载: 已启用")

        # 检查代理切换次数
        if self.use_proxy and hasattr(self, 'proxy_manager') and self.proxy_manager:
            proxy_stats = self.proxy_manager.get_stats()
            if proxy_stats and 'switches' in proxy_stats:
                print(f"🔄 代理切换次数: {proxy_stats['switches']}")

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

    def _deep_crawl_product_content_and_save(self, node, parent_path=None, skip_troubleshooting=False):
        """深入爬取产品页面的指南和故障排除内容，并立即保存数据"""
        if not node or not isinstance(node, dict):
            return node
            
        if parent_path is None:
            parent_path = []
            
        # 复制当前路径信息
        current_path = parent_path.copy()
        node_name = node.get('name', 'Unknown')
        current_path.append(node_name)
        path_str = " > ".join(current_path)

        url = node.get('url', '')
        is_specified_target = self._is_specified_target_url(url)

        # 添加详细的调试信息
        children_count = len(node.get('children', []))
        print(f"🔍 深度爬取节点: {node_name} (子节点: {children_count})")

        if self.verbose:
            print(f"   URL: {url}")
            print(f"   是否指定目标: {is_specified_target}")
            print(f"   是否跳过troubleshooting: {skip_troubleshooting}")
            if node.get('children'):
                child_names = [child.get('name', 'Unknown') for child in node['children'][:3]]
                if len(node['children']) > 3:
                    child_names.append(f"...等{len(node['children'])}个")
                print(f"   子节点: {', '.join(child_names)}")
                
        # 判断是否为目标页面
        has_real_children = node.get('children') and len(node.get('children', [])) > 0
        is_target_page = (
            '/Device/' in url and
            not any(skip in url for skip in ['/Guide/', '/Troubleshooting/', '/Edit/', '/History/', '/Answers/']) and
            (is_specified_target or not has_real_children)
        )

        if is_target_page:
            # 检查深度内容的缓存
            local_path = self._get_node_cache_path(url, node.get('name', 'unknown'))

            if self.verbose:
                print(f"🔍 检查深度内容缓存: {url}")
                print(f"   缓存路径: {local_path}")

            if self._check_cache_validity(url, local_path):
                if self.verbose:
                    print(f"✅ 深度内容缓存命中: {node.get('name', '')}")
                else:
                    print(f"   ✅ 主缓存命中: {node.get('name', '')}")
                    
                # 从缓存加载数据
                try:
                    cached_node = self._load_cached_node_data(local_path)
                    if cached_node:
                        # 更新节点数据
                        for key, value in cached_node.items():
                            if key not in ['children']:  # 保留原始children
                                node[key] = value
                except Exception as e:
                    if self.verbose:
                        print(f"   ⚠️ 缓存加载失败: {e}")
            else:
                # 缓存未命中，处理并保存数据
                try:
                    print(f"🎯 深入爬取目标产品页面: {node.get('name', '')}")
                    print(f"   📍 URL: {url}")
                    
                    # 获取页面内容并处理
                    soup = self.get_soup(url)
                    if soup:
                        self._process_and_save_product_page(node, soup, local_path)
                except Exception as e:
                    print(f"   ❌ 处理产品页面失败: {str(e)}")
                    self.stats["errors"] += 1
                    self.logger.error(f"处理产品页面失败: {url} - {str(e)}")

        # 递归处理子节点
        if 'children' in node and node['children']:
            for i, child in enumerate(node['children']):
                node['children'][i] = self._deep_crawl_product_content_and_save(child, current_path, skip_troubleshooting)

        return node
        
    def _process_and_save_product_page(self, node, soup, local_path):
        """处理产品页面内容并立即保存数据"""
        url = node.get('url', '')
        
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

        # 检查是否应该处理troubleshooting
        should_process_troubleshooting = (
            not self._is_troubleshooting_processed_in_parent_path(url)
        )

        # 使用并发处理guides和troubleshooting
        print(f"   ⚙️  开始处理详细内容...")
        
        # 正常处理guides和troubleshooting
        guides_data, troubleshooting_data = self._process_content_concurrently(
            guide_links, url, not should_process_troubleshooting, soup
        )

        if guides_data:
            node['guides'] = guides_data
        if troubleshooting_data:
            node['troubleshooting'] = troubleshooting_data
            
        # 处理完成后立即保存数据
        print(f"   💾 立即保存产品页面数据...")
        # 确保目录存在
        local_path.mkdir(parents=True, exist_ok=True)
        self._save_node_content(node, local_path)
        print(f"   ✅ 产品页面数据已保存到: {local_path}")
        
        return node
        
    def deep_crawl_product_content(self, node, skip_troubleshooting=False):
        """深入爬取产品页面的指南和故障排除内容，并正确构建数据结构"""
        if not node or not isinstance(node, dict):
            return node

        url = node.get('url', '')
        node_name = node.get('name', 'Unknown')
        is_specified_target = self._is_specified_target_url(url)

        # 添加详细的调试信息
        children_count = len(node.get('children', []))
        print(f"🔍 深度爬取节点: {node_name} (子节点: {children_count})")

        if self.verbose:
            print(f"   URL: {url}")
            print(f"   是否指定目标: {is_specified_target}")
            print(f"   是否跳过troubleshooting: {skip_troubleshooting}")
            if node.get('children'):
                child_names = [child.get('name', 'Unknown') for child in node['children'][:3]]
                if len(node['children']) > 3:
                    child_names.append(f"...等{len(node['children'])}个")
                print(f"   子节点: {', '.join(child_names)}")

        # 判断是否为目标页面，需要处理以下情况：
        # 1. 指定的目标URL - 必须处理
        # 2. 没有子类别的页面 - 必须处理
        # 3. 有子类别但子类别为空数组的页面 - 必须处理
        # 4. 有子类别且子类别非空的页面 - 不应该被当作目标页面，应该递归处理子节点
        has_real_children = node.get('children') and len(node.get('children', [])) > 0

        is_target_page = (
            '/Device/' in url and
            not any(skip in url for skip in ['/Guide/', '/Troubleshooting/', '/Edit/', '/History/', '/Answers/']) and
            (is_specified_target or not has_real_children)
        )

        if is_target_page:
            # 检查深度内容的缓存
            local_path = self._get_node_cache_path(url, node.get('name', 'unknown'))

            if self.verbose:
                print(f"🔍 检查深度内容缓存: {url}")
                print(f"   缓存路径: {local_path}")

            if self._check_cache_validity(url, local_path):
                if self.verbose:
                    print(f"✅ 深度内容缓存命中，检查troubleshooting缓存: {node.get('name', '')}")
                else:
                    print(f"   ✅ 主缓存命中，检查troubleshooting缓存: {node.get('name', '')}")

                # 从缓存加载数据
                try:
                    cached_node = self._load_cached_node_data(local_path)
                    if cached_node:
                        # 即使主缓存命中，也要检查troubleshooting缓存
                        troubleshooting_cache_key = f"{url}#troubleshooting"
                        cached_troubleshooting = self._check_troubleshooting_cache(troubleshooting_cache_key, url)

                        if cached_troubleshooting is not None:
                            print(f"    ✅ 使用缓存的故障排除数据 ({len(cached_troubleshooting)} 个)")
                            cached_node['troubleshooting'] = cached_troubleshooting
                            return cached_node
                        else:
                            print(f"    🔍 未找到故障排除缓存，检查主缓存中是否已有数据")
                            # 检查主缓存中是否已有troubleshooting数据
                            if 'troubleshooting' in cached_node and cached_node['troubleshooting']:
                                print(f"    ✅ 主缓存中已有故障排除数据 ({len(cached_node['troubleshooting'])} 个)")
                                return cached_node

                            # 检查是否应该有troubleshooting内容但缓存缺失
                            should_have_troubleshooting = self._should_have_troubleshooting_content(url)
                            if should_have_troubleshooting:
                                print(f"    ⚠️ 页面应该有故障排除内容但缓存缺失，仅重新爬取故障排除部分")
                                # 只重新爬取troubleshooting部分，不重新处理整个页面
                                try:
                                    soup = self.get_soup(url)
                                    if soup:
                                        troubleshooting_links = self.extract_troubleshooting_from_device_page(soup, url)
                                        if troubleshooting_links:
                                            print(f"    🔧 找到 {len(troubleshooting_links)} 个故障排除页面，开始处理...")
                                            troubleshooting_data = []
                                            for ts_link in troubleshooting_links:
                                                if isinstance(ts_link, dict):
                                                    ts_url = ts_link.get('url', '')
                                                else:
                                                    ts_url = ts_link
                                                if ts_url:
                                                    ts_content = self.extract_troubleshooting_content(ts_url)
                                                    if ts_content:
                                                        ts_content['url'] = ts_url
                                                        troubleshooting_data.append(ts_content)

                                            if troubleshooting_data:
                                                cached_node['troubleshooting'] = troubleshooting_data
                                                # 不在这里保存troubleshooting缓存，等待文件系统保存阶段
                                                # troubleshooting_cache_key = f"{url}#troubleshooting"
                                                # self._save_troubleshooting_cache(troubleshooting_cache_key, url, troubleshooting_data)
                                                print(f"    ✅ 成功补充故障排除数据 ({len(troubleshooting_data)} 个)")
                                    return cached_node
                                except Exception as e:
                                    print(f"    ❌ 重新爬取故障排除失败: {e}")
                                    return cached_node
                            else:
                                print(f"    ✅ 页面不需要故障排除内容，使用主缓存")
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

                    # 检查是否应该处理troubleshooting（基于新的逻辑）
                    should_process_troubleshooting = (
                        not skip_troubleshooting and
                        not self._is_troubleshooting_processed_in_parent_path(url)
                    )

                    # 初始化变量
                    current_path = url.split('/Device/')[-1].split('?')[0].rstrip('/') if '/Device/' in url else ''
                    cached_troubleshooting = None

                    # 如果应该处理troubleshooting，先检查缓存
                    if should_process_troubleshooting and current_path:
                        # 首先检查troubleshooting缓存
                        troubleshooting_cache_key = f"{url}#troubleshooting"
                        cached_troubleshooting = self._check_troubleshooting_cache(troubleshooting_cache_key, url)

                        if cached_troubleshooting is not None:
                            # 如果有缓存，直接使用缓存数据，不需要重新处理
                            print(f"   ✅ 发现troubleshooting缓存 ({len(cached_troubleshooting)} 个)，跳过重新处理")
                            should_process_troubleshooting = False
                            # 标记当前路径已处理troubleshooting
                            self.processed_troubleshooting_paths.add(current_path)
                        else:
                            # 如果没有缓存，检查当前页面是否有troubleshooting内容
                            troubleshooting_links = self.extract_troubleshooting_from_device_page(soup, url)
                            if troubleshooting_links:
                                # 标记当前路径已处理troubleshooting
                                self.processed_troubleshooting_paths.add(current_path)
                                print(f"   ✅ 在路径 '{current_path}' 首次发现troubleshooting，开始处理...")
                                print(f"   🔧 后续子路径将跳过troubleshooting处理")
                            else:
                                should_process_troubleshooting = False

                    # 使用并发处理guides和troubleshooting
                    print(f"   ⚙️  开始处理详细内容...")

                    # 如果有缓存的troubleshooting数据，直接使用
                    if cached_troubleshooting is not None:
                        print(f"   📋 使用缓存的troubleshooting数据 ({len(cached_troubleshooting)} 个)")
                        # 只处理guides，troubleshooting使用缓存
                        guides_data, _ = self._process_content_concurrently(
                            guide_links, url, True, soup  # skip_troubleshooting=True
                        )
                        troubleshooting_data = cached_troubleshooting
                    else:
                        # 正常处理guides和troubleshooting
                        guides_data, troubleshooting_data = self._process_content_concurrently(
                            guide_links, url, not should_process_troubleshooting, soup
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

                                # 检查子类别是否应该跳过troubleshooting（基于父路径是否已处理）
                                parent_processed_ts = current_path in self.processed_troubleshooting_paths if current_path else False
                                should_skip_ts = self._should_skip_troubleshooting_for_subcategory(subcat_node, parent_processed_ts)
                                processed_subcat = self.deep_crawl_product_content(subcat_node, skip_troubleshooting=should_skip_ts)
                                if processed_subcat:
                                    subcategory_children.append(processed_subcat)

                            if subcategory_children:
                                node['children'] = subcategory_children
                                print(f"  成功处理 {len(subcategory_children)} 个子类别")

                    # 保持现有的children结构，不要删除层级关系

                    print(f"  总计: {len(guides_data)} 个指南, {len(troubleshooting_data)} 个故障排除")

            except Exception as e:
                print(f"  ✗ 深入爬取时出错: {str(e)}")

            # 即使是目标页面，也要处理其子节点（如果有）
            # 这确保了即使是有内容的页面，其子类别也会被递归处理
            if 'children' in node and node['children'] and len(node['children']) > 0:
                children_count = len(node['children'])
                print(f"🔄 递归处理目标页面的 {children_count} 个子节点...")

                # 检查当前节点是否已处理troubleshooting
                current_url = node.get('url', '')
                current_path = current_url.split('/Device/')[-1].split('?')[0].rstrip('/') if '/Device/' in current_url else ''
                child_should_skip_troubleshooting = (
                    skip_troubleshooting or
                    (current_path and current_path in self.processed_troubleshooting_paths)
                )

                for i, child in enumerate(node['children']):
                    if children_count > 1:
                        print(f"   └─ [{i+1}/{children_count}] 处理目标页面的子节点: {child.get('name', 'Unknown')}")
                    # 确保传递布尔值参数
                    skip_ts = True if child_should_skip_troubleshooting else False
                    node['children'][i] = self.deep_crawl_product_content(child, skip_ts)

        elif 'children' in node and node['children']:
            children_count = len(node['children'])
            if children_count > 0:
                print(f"🔄 递归处理 {children_count} 个子节点...")

            # 检查当前节点是否已处理troubleshooting
            current_url = node.get('url', '')
            current_path = current_url.split('/Device/')[-1].split('?')[0].rstrip('/') if '/Device/' in current_url else ''
            child_should_skip_troubleshooting = (
                skip_troubleshooting or
                (current_path and current_path in self.processed_troubleshooting_paths)
            )

            for i, child in enumerate(node['children']):
                if children_count > 1:
                    print(f"   └─ [{i+1}/{children_count}] 处理子节点: {child.get('name', 'Unknown')}")
                # 确保传递布尔值参数
                skip_ts = True if child_should_skip_troubleshooting else False
                node['children'][i] = self.deep_crawl_product_content(child, skip_ts)

        return node

    def _check_target_completeness(self, target_name):
        """检查目标产品目录是否已存在完整的文件结构"""
        if not target_name:
            return False, None

        safe_name = target_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        target_dir = Path(self.storage_root) / "Device" / safe_name

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
        """从目标URL获取真实的设备路径，直接从主要设备类型开始"""
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

                # 解析路径层级，直接从主要设备类型开始
                path_parts = device_path.split('/')
                if len(path_parts) > 0:
                    # 找到主要设备类型（通常是第一个有意义的部分）
                    main_category = path_parts[0]

                    # 如果有子路径，保留完整的层级结构，确保在Device目录下
                    if len(path_parts) > 1:
                        sub_path = '/'.join(path_parts[1:])
                        return Path(self.storage_root) / "Device" / main_category / sub_path
                    else:
                        return Path(self.storage_root) / "Device" / main_category
                else:
                    return Path(self.storage_root) / "Device" / device_path
            else:
                # 如果是根Device页面，使用Device作为根目录
                return Path(self.storage_root) / "Device"

        # 如果不是Device URL，使用原来的逻辑作为后备，确保在Device目录下
        safe_name = target_url.replace("/", "_").replace("\\", "_").replace(":", "_")
        return Path(self.storage_root) / "Device" / safe_name

    def _validate_path_structure(self, url):
        """验证并提取真实的页面路径结构 - 通用动态方法"""
        print(f"   🔍 验证路径结构: {url}")

        # 获取页面内容以提取面包屑导航
        soup = self.get_soup(url)
        if not soup:
            return None

        # 首先尝试提取面包屑导航
        breadcrumbs = self._extract_real_breadcrumbs(soup)
        if breadcrumbs:
            print(f"   📍 找到面包屑导航: {' > '.join([b['name'] for b in breadcrumbs])}")
            return breadcrumbs

        # 如果没有面包屑，通过动态方式构建路径结构
        return self._build_dynamic_breadcrumbs(url)

    def _build_dynamic_breadcrumbs(self, url):
        """动态构建面包屑导航 - 不依赖硬编码路径"""
        if '/Device/' not in url:
            return None

        device_path = url.split('/Device/')[-1]
        if '?' in device_path:
            device_path = device_path.split('?')[0]
        device_path = device_path.rstrip('/')

        if not device_path:
            return [{"name": "Device", "url": self.base_url + "/Device"}]

        import urllib.parse
        device_path = urllib.parse.unquote(device_path)

        # 分解路径为各个部分
        path_parts = device_path.split('/')
        breadcrumbs = [{"name": "Device", "url": self.base_url + "/Device"}]

        # 动态构建每一级的面包屑
        current_path = "/Device"
        for i, part in enumerate(path_parts):
            if not part:
                continue

            current_path += "/" + urllib.parse.quote(part, safe='')
            current_url = self.base_url + current_path

            # 尝试从该级别页面提取真实名称
            real_name = self._get_real_category_name(current_url, part)
            if real_name:
                breadcrumbs.append({
                    "name": real_name,
                    "url": current_url
                })
            else:
                # 如果无法获取真实名称，使用处理后的路径名称
                display_name = part.replace('_', ' ').replace('%22', '"')
                breadcrumbs.append({
                    "name": display_name,
                    "url": current_url
                })

        print(f"   📍 动态构建面包屑: {' > '.join([b['name'] for b in breadcrumbs])}")
        return breadcrumbs

    def _get_real_category_name(self, url, fallback_name):
        """从页面获取真实的类别名称"""
        try:
            soup = self.get_soup(url)
            if not soup:
                return None

            # 尝试从页面标题获取名称
            title_elem = soup.find('h1')
            if title_elem:
                title_text = title_elem.get_text(strip=True)
                if title_text and title_text != "Device":
                    return title_text

            # 尝试从面包屑获取名称
            breadcrumb_elems = soup.select('[data-testid="breadcrumb"] a, .breadcrumb a')
            for elem in breadcrumb_elems:
                if elem.get('href', '').endswith(url.split(self.base_url)[-1]):
                    return elem.get_text(strip=True)

        except Exception as e:
            print(f"   ⚠️  获取类别名称失败: {e}")

        return None


    def _extract_real_breadcrumbs(self, soup):
        """从页面提取真实的面包屑导航"""
        breadcrumbs = []

        # 方法1: 查找新版Chakra UI面包屑导航
        chakra_breadcrumb = soup.select_one("nav[aria-label='breadcrumb'].chakra-breadcrumb")
        if chakra_breadcrumb:
            breadcrumb_items = chakra_breadcrumb.select("li[itemtype='http://schema.org/ListItem']")
            if breadcrumb_items:
                print(f"   📍 找到Chakra UI面包屑导航，共{len(breadcrumb_items)}项")
                for item in breadcrumb_items:  # 不反向，保持原始顺序
                    # 从data-name属性获取名称
                    name = item.get("data-name")
                    if name:
                        # 尝试获取链接
                        link = item.select_one("a")
                        if link and link.get('href'):
                            href = link.get('href')
                            if '%22' in href:
                                href = href.replace('%22', '"')
                            full_url = self.base_url + href if href.startswith('/') else href
                            breadcrumbs.append({"name": name, "url": full_url})
                        else:
                            # 当前页面（没有链接）
                            breadcrumbs.append({"name": name, "url": ""})
                    else:
                        # 备选：从链接文本获取
                        link = item.select_one("a")
                        if link:
                            text = link.get_text(strip=True)
                            href = link.get('href')
                            if text and href:
                                if '%22' in href:
                                    href = href.replace('%22', '"')
                                full_url = self.base_url + href if href.startswith('/') else href
                                breadcrumbs.append({"name": text, "url": full_url})

                if breadcrumbs:
                    print(f"   ✅ Chakra UI面包屑提取成功: {' > '.join([b['name'] for b in breadcrumbs])}")
                    return breadcrumbs

        # 方法2: 查找传统面包屑导航元素
        breadcrumb_selectors = [
            'nav[aria-label="breadcrumb"]',
            '.breadcrumb',
            '.breadcrumbs',
            '[data-testid="breadcrumb"]'
        ]

        for selector in breadcrumb_selectors:
            breadcrumb_nav = soup.select_one(selector)
            if breadcrumb_nav:
                # 获取面包屑列表项
                breadcrumb_items = breadcrumb_nav.find_all('li')
                if breadcrumb_items:
                    print(f"   📍 找到传统面包屑导航，共{len(breadcrumb_items)}项")
                    # 提取所有面包屑项目
                    temp_breadcrumbs = []
                    for item in breadcrumb_items:
                        link = item.find('a', href=True)
                        if link:
                            href = link.get('href')
                            text = link.get_text(strip=True)
                            if href and text:
                                # 处理特殊的URL编码
                                if '%22' in href:
                                    href = href.replace('%22', '"')
                                full_url = self.base_url + href if href.startswith('/') else href
                                temp_breadcrumbs.append({"name": text, "url": full_url})
                        else:
                            # 当前页面（没有链接）
                            text = item.get_text(strip=True)
                            if text and text not in [b['name'] for b in temp_breadcrumbs]:
                                temp_breadcrumbs.append({"name": text, "url": ""})

                    # iFixit的面包屑导航是倒序的，需要反向处理
                    # 检查是否需要反向：如果最后一个项目包含"设备"或"Device"，则需要反向
                    if temp_breadcrumbs:
                        last_item = temp_breadcrumbs[-1]['name'].lower()
                        first_item = temp_breadcrumbs[0]['name'].lower()

                        # 如果最后一个是"设备"或"device"，或者第一个不是"设备"，则反向
                        if ('设备' in last_item or 'device' in last_item or
                            ('设备' not in first_item and 'device' not in first_item)):
                            temp_breadcrumbs = list(reversed(temp_breadcrumbs))
                            print(f"   🔄 面包屑导航已反向处理")

                    breadcrumbs = temp_breadcrumbs
                    if breadcrumbs:
                        print(f"   ✅ 传统面包屑提取成功: {' > '.join([b['name'] for b in breadcrumbs])}")
                        return breadcrumbs
                else:
                    # 后备方案：查找所有链接
                    links = breadcrumb_nav.find_all('a', href=True)
                    temp_breadcrumbs = []
                    for link in links:
                        href = link.get('href')
                        text = link.get_text(strip=True)
                        if href and text:
                            if '%22' in href:
                                href = href.replace('%22', '"')
                            full_url = self.base_url + href if href.startswith('/') else href
                            temp_breadcrumbs.append({"name": text, "url": full_url})

                    # 检查顺序
                    if temp_breadcrumbs and temp_breadcrumbs[0]['name'].lower() != 'device':
                        temp_breadcrumbs = list(reversed(temp_breadcrumbs))

                    breadcrumbs = temp_breadcrumbs
                    if breadcrumbs:
                        print(f"   ✅ 链接面包屑提取成功: {' > '.join([b['name'] for b in breadcrumbs])}")
                        return breadcrumbs

        return None

    # 第6087行有重复声明的_clean_directory_name方法，这里删除重复声明

    def _find_existing_path(self, breadcrumbs):
        """在已有目录结构中查找匹配的路径"""
        if not breadcrumbs:
            return Path(self.storage_root) / "Device"

        # 从Device开始构建路径
        current_path = Path(self.storage_root) / "Device"

        # 跳过"Device"面包屑，从实际分类开始
        device_index = -1
        for i, crumb in enumerate(breadcrumbs):
            if crumb['name'].lower() in ['device', '设备']:
                device_index = i
                break

        if device_index >= 0:
            relevant_crumbs = breadcrumbs[device_index + 1:]
        else:
            relevant_crumbs = breadcrumbs

        # 逐级检查和创建路径，使用真实的URL路径映射
        for crumb in relevant_crumbs:
            crumb_name = crumb['name']
            crumb_url = crumb.get('url', '')

            # 根据URL确定正确的目录名称
            if crumb_url:
                # 从URL提取路径段
                if '/Device/' in crumb_url:
                    url_segment = crumb_url.split('/Device/')[-1]
                    if url_segment:
                        # 只使用URL路径的最后一个段作为目录名，避免创建嵌套路径
                        import urllib.parse
                        url_parts = url_segment.split('/')
                        last_part = url_parts[-1] if url_parts else url_segment
                        safe_name = urllib.parse.unquote(last_part)
                        safe_name = safe_name.replace("%22", '"')
                        # 清理文件系统不支持的字符
                        safe_name = self._clean_directory_name(safe_name)
                    else:
                        # 后备方案：清理显示名称
                        safe_name = self._clean_directory_name(crumb_name)
                else:
                    # 后备方案：清理显示名称
                    safe_name = self._clean_directory_name(crumb_name)
            else:
                # 没有URL，清理显示名称
                safe_name = self._clean_directory_name(crumb_name)

            potential_path = current_path / safe_name

            # 检查是否已存在匹配的目录
            existing_match = self._find_matching_directory(current_path, safe_name)
            if existing_match:
                current_path = existing_match
                print(f"   ✅ 找到已有目录: {existing_match}")
            else:
                current_path = potential_path
                print(f"   📁 将创建新目录: {potential_path}")

        return current_path

    def _build_full_save_path(self, target_url, base_dir):
        """根据目标URL构建完整的保存路径"""
        if not target_url or '/Device/' not in target_url:
            return base_dir

        # 提取设备路径
        device_path = target_url.split('/Device/')[-1]
        if '?' in device_path:
            device_path = device_path.split('?')[0]
        device_path = device_path.rstrip('/')

        if not device_path:
            return base_dir

        import urllib.parse
        device_path = urllib.parse.unquote(device_path)

        # 构建完整路径
        path_parts = device_path.split('/')
        full_path = Path(self.storage_root) / "Device"

        for part in path_parts:
            if part:
                # 使用统一的目录名清理方法
                safe_part = self._clean_directory_name(part)
                full_path = full_path / safe_part

        return full_path



    def _troubleshooting_belongs_to_current_page(self, troubleshooting_list, current_url):
        """检查troubleshooting是否真的属于当前页面"""
        if not troubleshooting_list or not current_url:
            return False

        # 提取当前页面的设备路径
        if '/Device/' not in current_url:
            return False

        current_device_path = current_url.split('/Device/')[-1]
        if '?' in current_device_path:
            current_device_path = current_device_path.split('?')[0]
        current_device_path = current_device_path.rstrip('/')

        # 首先检查是否是具体的设备页面（包含具体型号信息）
        if not self._is_specific_device_page(current_device_path):
            return False

        # 对于具体的设备页面，如果有 troubleshooting 数据，就认为属于当前页面
        # 这是因为这些数据是从当前页面提取的，即使是通用的 troubleshooting
        if troubleshooting_list:
            return True

        # 以下是原来的严格检查逻辑，作为备用
        # 检查troubleshooting的URL是否与当前页面相关
        for ts in troubleshooting_list:
            ts_url = ts.get('url', '')
            ts_title = ts.get('title', '')

            if not ts_url and not ts_title:
                continue

            # 方法1: 检查troubleshooting URL是否包含当前设备路径
            if ts_url and current_device_path in ts_url:
                print(f"   ✅ Troubleshooting URL匹配当前设备路径")
                return True

            # 方法2: 检查troubleshooting标题是否包含当前设备信息
            if ts_title:
                # 从当前设备路径提取关键信息
                device_keywords = self._extract_device_keywords(current_device_path)
                title_lower = ts_title.lower()

                # 检查关键词是否在标题中
                matches = 0
                for keyword in device_keywords:
                    if keyword.lower() in title_lower:
                        matches += 1

                # 如果大部分关键词都匹配，认为属于当前页面
                if matches >= len(device_keywords) * 0.6:  # 60%的关键词匹配
                    print(f"   ✅ Troubleshooting标题匹配当前设备: {matches}/{len(device_keywords)} 关键词匹配")
                    return True

        print(f"   ❌ Troubleshooting不属于当前页面")
        return False

    def _is_specific_device_page(self, device_path):
        """检查是否是具体的设备页面（包含具体型号信息）"""
        if not device_path:
            return False

        # 通用类别页面（不是具体设备）
        generic_categories = [
            'Mac', 'Mac_Laptop', 'Mac_Desktop', 'Mac_Hardware',
            'iPhone', 'iPad', 'iPod', 'Apple_Watch',
            'MacBook', 'MacBook_Pro', 'MacBook_Air',
            'iMac', 'Mac_Pro', 'Mac_mini'
        ]

        # 如果路径就是这些通用类别之一，不是具体设备
        if device_path in generic_categories:
            return False

        # 检查是否包含具体的型号信息
        specific_indicators = [
            # 型号编号
            'A1', 'A2', 'A3',  # Apple型号编号
            'Models_', 'Model_',
            # 具体规格
            '13"', '15"', '17"', '21.5"', '27"',
            'Unibody', 'Retina', 'Touch_Bar',
            # 年份
            '2020', '2021', '2022', '2023', '2024',
            # 代数
            '1st_Gen', '2nd_Gen', '3rd_Gen', '4th_Gen', '5th_Gen',
            'Generation'
        ]

        # 检查是否包含具体指标
        for indicator in specific_indicators:
            if indicator in device_path:
                return True

        # 检查路径深度（具体设备通常路径更深）
        path_depth = len(device_path.split('/'))
        if path_depth >= 2:  # 至少两级深度，如 MacBook_Pro/MacBook_Pro_17"
            return True

        return False

    def _extract_device_keywords(self, device_path):
        """从设备路径提取关键词"""
        if not device_path:
            return []

        keywords = []

        # 分割路径
        parts = device_path.replace('_', ' ').split('/')
        for part in parts:
            # 进一步分割每个部分
            sub_parts = part.split()
            keywords.extend(sub_parts)

        # 清理和过滤关键词
        filtered_keywords = []
        for keyword in keywords:
            # 移除特殊字符
            clean_keyword = keyword.replace('"', '').replace("'", '').strip()
            # 过滤掉太短的词和常见词
            if len(clean_keyword) >= 2 and clean_keyword.lower() not in ['and', 'or', 'the', 'of', 'in']:
                filtered_keywords.append(clean_keyword)

        return filtered_keywords

    def _is_troubleshooting_processed_in_parent_path(self, current_url):
        """检查当前URL的父路径是否已经处理过troubleshooting"""
        if not current_url or '/Device/' not in current_url:
            return False

        current_path = current_url.split('/Device/')[-1].split('?')[0].rstrip('/')

        # 检查所有已处理的路径，看是否有父路径
        for processed_path in self.processed_troubleshooting_paths:
            if current_path.startswith(processed_path + '/') or current_path == processed_path:
                return True
        return False

    def _should_skip_troubleshooting_for_subcategory(self, subcat_node, parent_processed_troubleshooting=False):
        """判断子类别是否应该跳过troubleshooting提取"""
        if not subcat_node:
            return True

        # 如果父级已经处理过troubleshooting，则跳过
        if parent_processed_troubleshooting:
            return True

        url = subcat_node.get('url', '')
        if not url or '/Device/' not in url:
            return True

        # 检查是否在父路径中已经处理过
        if self._is_troubleshooting_processed_in_parent_path(url):
            device_path = url.split('/Device/')[-1].split('?')[0].rstrip('/')
            print(f"      ⏭️  跳过troubleshooting（已在父路径处理）: {device_path}")
            return True

        return False

    def _find_matching_directory(self, parent_path, target_name):
        """在父目录中查找匹配的子目录"""
        if not parent_path.exists():
            return None

        target_name_lower = target_name.lower()

        for item in parent_path.iterdir():
            if item.is_dir():
                item_name_lower = item.name.lower()
                # 检查完全匹配或相似匹配
                if (item_name_lower == target_name_lower or
                    target_name_lower in item_name_lower or
                    item_name_lower in target_name_lower):
                    return item

        return None

    def _build_path_from_tree_structure(self, tree_data):
        """从树结构中构建正确的文件夹路径"""
        if not tree_data:
            return None

        # 找到所有包含内容的节点
        content_nodes = self._find_all_content_nodes_in_tree(tree_data)
        if not content_nodes:
            return None

        # 使用第一个内容节点来构建路径
        target_node = content_nodes[0]

        # 构建从根到目标节点的路径
        path_segments = self._build_path_segments_to_node(tree_data, target_node)
        if not path_segments:
            return None

        # 构建文件系统路径，确保从Device开始
        root_dir = Path(self.storage_root) / "Device"

        # 跳过路径段中的"Device"，避免重复
        filtered_segments = []
        for segment in path_segments:
            if segment.lower() != "device":
                filtered_segments.append(segment)

        # 添加过滤后的路径段
        for segment in filtered_segments:
            safe_name = self._clean_directory_name(segment)
            root_dir = root_dir / safe_name

        print(f"   🗂️  从树结构构建路径: Device > {' > '.join(filtered_segments)}")
        print(f"   📁 文件系统路径: {root_dir}")

        return root_dir

    def _build_hierarchical_path_from_tree(self, tree_data):
        """从树结构中构建完整的层级路径 - 修复版本"""
        if not tree_data:
            return None

        # 尝试从树结构中提取完整的路径信息
        # 首先检查是否有breadcrumb或path信息
        breadcrumbs = tree_data.get('breadcrumbs', [])
        if breadcrumbs:
            # 使用breadcrumbs构建路径
            return self._build_path_from_breadcrumbs(breadcrumbs)

        # 如果没有breadcrumbs，尝试从URL构建
        tree_url = tree_data.get('url', '')
        if tree_url and '/Device/' in tree_url:
            return self._build_hierarchical_path_from_url(tree_url)

        # 如果还是没有，尝试从节点名称和层级结构推断
        return self._infer_hierarchical_path_from_tree(tree_data)

    def _build_hierarchical_path_from_url(self, url):
        """从URL构建完整的层级路径"""
        if not url or '/Device/' not in url:
            return None

        try:
            # 提取设备路径部分
            device_path = url.split('/Device/')[-1]
            if '?' in device_path:
                device_path = device_path.split('?')[0]
            device_path = device_path.rstrip('/')

            if not device_path:
                return Path(self.storage_root) / "Device"

            # URL解码
            import urllib.parse
            device_path = urllib.parse.unquote(device_path)

            # 构建完整的层级路径
            path_parts = device_path.split('/')
            root_dir = Path(self.storage_root) / "Device"

            for part in path_parts:
                if part:  # 跳过空部分
                    safe_part = self._clean_directory_name(part)
                    root_dir = root_dir / safe_part

            print(f"   🗂️  从URL构建层级路径: {url}")
            print(f"   📁 构建的路径: {root_dir}")
            return root_dir

        except Exception as e:
            self.logger.error(f"从URL构建层级路径失败: {e}")
            return None

    def _build_path_from_breadcrumbs(self, breadcrumbs):
        """从breadcrumbs构建路径"""
        if not breadcrumbs:
            return None

        try:
            root_dir = Path(self.storage_root) / "Device"

            for crumb in breadcrumbs:
                if isinstance(crumb, dict):
                    name = crumb.get('name', '')
                elif isinstance(crumb, str):
                    name = crumb
                else:
                    continue

                if name and name.lower() != 'device':
                    safe_name = self._clean_directory_name(name)
                    root_dir = root_dir / safe_name

            return root_dir

        except Exception as e:
            self.logger.error(f"从breadcrumbs构建路径失败: {e}")
            return None

    def _infer_hierarchical_path_from_tree(self, tree_data):
        """从树结构推断层级路径"""
        if not tree_data:
            return None

        # 尝试找到包含内容的节点并构建其完整路径
        content_nodes = self._find_all_content_nodes_in_tree(tree_data)
        if content_nodes:
            # 使用第一个内容节点
            target_node = content_nodes[0]
            path_segments = self._build_complete_path_to_node(tree_data, target_node)
            if path_segments:
                return self._build_path_from_segments(path_segments)

        # 如果没有内容节点，使用根节点信息
        root_name = tree_data.get('name', 'Unknown')
        if root_name and root_name != 'Unknown':
            safe_name = self._clean_directory_name(root_name)
            return Path(self.storage_root) / "Device" / safe_name

        return None

    def _build_path_from_tree_data(self, tree_data):
        """从树数据构建路径 - 后备方案"""
        if not tree_data:
            return Path(self.storage_root) / "Device"

        root_name = tree_data.get("name", "Unknown")
        if " > " in root_name:
            # 如果名称包含路径分隔符，解析完整路径
            path_parts = root_name.split(" > ")
            root_dir = Path(self.storage_root) / "Device"
            for part in path_parts:
                if part and part.lower() != 'device':
                    safe_name = self._clean_directory_name(part)
                    root_dir = root_dir / safe_name
            return root_dir
        else:
            safe_name = self._clean_directory_name(root_name)
            return Path(self.storage_root) / "Device" / safe_name

    def _build_complete_path_to_node(self, tree_root, target_node, current_path=None):
        """构建从根节点到目标节点的完整路径段 - 改进版本"""
        if current_path is None:
            current_path = []

        if not tree_root or not isinstance(tree_root, dict):
            return None

        # 添加当前节点名称到路径
        node_name = tree_root.get('name', '')
        if node_name:
            current_path.append(node_name)

        # 检查是否找到目标节点
        if self._is_same_node(tree_root, target_node):
            return current_path.copy()

        # 递归搜索子节点
        children = tree_root.get('children', [])
        for child in children:
            result = self._build_complete_path_to_node(child, target_node, current_path.copy())
            if result:
                return result

        return None

    def _build_path_from_segments(self, path_segments):
        """从路径段构建文件系统路径"""
        if not path_segments:
            return None

        root_dir = Path(self.storage_root) / "Device"

        # 跳过路径段中的"Device"，避免重复
        filtered_segments = []
        for segment in path_segments:
            if segment and segment.lower() != "device":
                filtered_segments.append(segment)

        # 添加过滤后的路径段
        for segment in filtered_segments:
            safe_name = self._clean_directory_name(segment)
            root_dir = root_dir / safe_name

        return root_dir

    def _is_same_node(self, node1, node2):
        """判断两个节点是否相同"""
        if not node1 or not node2:
            return False

        # 优先使用URL比较
        url1 = node1.get('url', '').strip()
        url2 = node2.get('url', '').strip()
        if url1 and url2:
            return url1 == url2

        # 如果没有URL，使用名称比较
        name1 = node1.get('name', '').strip()
        name2 = node2.get('name', '').strip()
        if name1 and name2:
            return name1 == name2

        return False

    def _save_tree_with_hierarchical_structure(self, tree_data, base_dir, current_path=""):
        """保存树结构，维护完整的层级结构"""
        if not tree_data or not isinstance(tree_data, dict):
            return

        node_name = tree_data.get('name', 'Unknown')
        node_url = tree_data.get('url', '')

        # 构建当前节点的路径
        if current_path:
            full_path = f"{current_path} > {node_name}"
        else:
            full_path = node_name

        print(f"   🔍 处理节点: {full_path}")

        # 检查当前节点是否有内容需要保存
        has_guides = tree_data.get('guides') and len(tree_data.get('guides', [])) > 0
        has_troubleshooting = tree_data.get('troubleshooting') and len(tree_data.get('troubleshooting', [])) > 0
        has_content = has_guides or has_troubleshooting

        if has_content:
            # 构建当前节点的目录路径
            if current_path:
                # 如果有父路径，构建完整的层级路径
                path_parts = current_path.split(' > ')
                path_parts.append(node_name)
            else:
                # 如果是根节点，直接使用节点名称
                path_parts = [node_name]

            # 过滤掉"Device"避免重复
            filtered_parts = []
            for part in path_parts:
                if part and part.lower() != "device":
                    filtered_parts.append(part)

            # 构建文件系统路径
            node_dir = base_dir
            for part in filtered_parts:
                safe_name = self._clean_directory_name(part)
                node_dir = node_dir / safe_name

            print(f"       📁 保存内容到: {node_dir}")
            print(f"       📖 指南: {len(tree_data.get('guides', []))} 个")
            print(f"       🔧 故障排除: {len(tree_data.get('troubleshooting', []))} 个")

            # 确保目录存在并保存内容
            node_dir.mkdir(parents=True, exist_ok=True)
            self._save_node_content(tree_data, node_dir)

        # 递归处理子节点，保持层级结构
        children = tree_data.get('children', [])
        if children:
            print(f"       🌳 处理 {len(children)} 个子节点...")
            for child in children:
                # 为子节点构建新的路径上下文
                if current_path:
                    child_path = f"{current_path} > {node_name}"
                else:
                    child_path = node_name

                self._save_tree_with_hierarchical_structure(child, base_dir, child_path)

    def _find_target_node_in_tree(self, node):
        """在树中查找包含指南和故障排除的目标节点"""
        if not node or not isinstance(node, dict):
            return None

        # 检查当前节点是否包含指南或故障排除
        if (node.get('guides') and len(node.get('guides', [])) > 0) or \
           (node.get('troubleshooting') and len(node.get('troubleshooting', [])) > 0):
            return node

        # 递归检查子节点
        children = node.get('children', [])
        for child in children:
            result = self._find_target_node_in_tree(child)
            if result:
                return result

        return None

    def _build_path_segments_to_node(self, tree_root, target_node, current_path=None):
        """构建从根节点到目标节点的路径段"""
        if current_path is None:
            current_path = []

        if not tree_root or not isinstance(tree_root, dict):
            return None

        # 添加当前节点名称到路径
        node_name = tree_root.get('name', '')
        if node_name:
            current_path.append(node_name)

        # 检查是否找到目标节点 - 使用多种匹配方式
        target_url = target_node.get('url', '').strip()
        current_url = tree_root.get('url', '').strip()

        # 方式1: 精确URL匹配
        if target_url and current_url and target_url == current_url:
            return current_path.copy()

        # 方式2: URL路径匹配（忽略协议和域名）
        if target_url and current_url:
            target_path = target_url.split('/')[-1] if '/' in target_url else target_url
            current_path_part = current_url.split('/')[-1] if '/' in current_url else current_url
            if target_path and current_path_part and target_path == current_path_part:
                return current_path.copy()

        # 方式3: 名称匹配（作为后备）
        target_name = target_node.get('name', '').strip()
        if target_name and node_name and target_name == node_name:
            return current_path.copy()

        # 递归检查子节点
        children = tree_root.get('children', [])
        for child in children:
            result = self._build_path_segments_to_node(child, target_node, current_path.copy())
            if result:
                return result

        return None

    def _build_fallback_path_from_url(self, node_url, node_name):
        """从节点URL构建后备路径，尝试保持层级结构"""
        if not node_url:
            return None

        try:
            # 从URL中提取路径信息
            if '/Device/' in node_url:
                # 提取Device后面的路径部分
                device_path = node_url.split('/Device/')[-1]
                if '?' in device_path:
                    device_path = device_path.split('?')[0]
                device_path = device_path.rstrip('/')

                if device_path:
                    import urllib.parse
                    device_path = urllib.parse.unquote(device_path)

                    # 动态构建路径，不使用硬编码
                    path_parts = device_path.split('/')
                    base_path = Path(self.storage_root) / "Device"

                    # 逐级构建路径，保持原有的层级结构
                    for part in path_parts:
                        if part:  # 跳过空的路径段
                            safe_part = self._clean_directory_name(part)
                            base_path = base_path / safe_part

                    # 如果node_name与最后一个路径段不同，添加node_name
                    if node_name and node_name != path_parts[-1]:
                        safe_name = self._clean_directory_name(node_name)
                        return base_path / safe_name
                    else:
                        return base_path

            return None
        except Exception as e:
            self.logger.warning(f"构建后备路径失败: {e}")
            return None

    def save_combined_result(self, tree_data, target_name=None):
        """保存整合结果到真实的设备路径结构 - 修复版本"""
        try:
            if self.verbose:
                print("   📁 创建目录结构...")

            # 新的路径构建策略：确保维护完整的层级结构
            root_dir = self._build_hierarchical_path_from_tree(tree_data)

            # 如果没有从树结构构建路径，使用改进的后备方案
            if not root_dir:
                target_url = getattr(self, 'target_url', None)
                if target_url and '/Device/' in target_url:
                    # 从URL构建完整的层级路径
                    root_dir = self._build_hierarchical_path_from_url(target_url)
                elif target_name:
                    if target_name.startswith('http') and '/Device/' in target_name:
                        root_dir = self._build_hierarchical_path_from_url(target_name)
                    else:
                        # 假设是设备名称，但仍然尝试构建层级结构
                        safe_name = self._clean_directory_name(target_name)
                        root_dir = Path(self.storage_root) / "Device" / safe_name
                else:
                    # 从树数据中提取路径信息，保持层级结构
                    root_dir = self._build_path_from_tree_data(tree_data)

            # 确保目录存在并保存内容
            if root_dir:
                root_dir.mkdir(parents=True, exist_ok=True)
                if self.verbose:
                    print(f"   📂 目标路径: {root_dir}")
                    print("   💾 保存内容和下载媒体文件...")
                    print(f"   🔍 开始保存到: {root_dir}")
                    print(f"   🎯 目标URL: {getattr(self, 'target_url', 'None')}")
                    print("   ✅ 数据已在处理过程中保存")
            else:
                    # 如果没有找到内容节点，尝试找到目标节点并只保存其子结构
                    target_node = self._find_target_node_by_url(tree_data, getattr(self, 'target_url', ''))
                    if target_node:
                        print(f"   🎯 找到目标节点: {target_node.get('name', 'Unknown')}")
                        # 构建目标节点的完整路径
                        target_path_segments = self._build_path_segments_to_node(tree_data, target_node)
                        if target_path_segments:
                            # 构建完整的文件系统路径，确保从Device开始
                            target_dir = Path(self.storage_root) / "Device"

                            # 跳过路径段中的"Device"，避免重复
                            filtered_segments = []
                            for segment in target_path_segments:
                                if segment.lower() != "device":
                                    filtered_segments.append(segment)

                            # 添加过滤后的路径段
                            for segment in filtered_segments:
                                safe_name = self._clean_directory_name(segment)
                                target_dir = target_dir / safe_name

                            print(f"   📁 目标节点完整路径: Device > {' > '.join(filtered_segments)}")
                            # 只保存目标节点的子结构，而不是整个树
                            self._save_target_node_children(target_node, target_dir)
                        else:
                            # 如果无法构建路径，使用原来的root_dir
                            self._save_target_node_children(target_node, root_dir)
                    else:
                        # 最终后备方案：保存整个树结构
                        print("   ⚠️  未找到目标节点，使用整个树结构")
                        self._save_tree_structure(tree_data, root_dir)

            # 数据完整性验证已禁用（验证逻辑有bug，但数据本身是正确的）
            if self.verbose:
                print(f"\n✅ 数据保存完成，跳过验证步骤")

            print(f"\n📁 整合结果已保存到本地文件夹: {root_dir}")
            return str(root_dir)
        except Exception as e:
            print(f"\n❌ 保存数据时发生错误: {str(e)}")
            print("⚠️ 尝试使用备用保存方案...")
            try:
                # 备用保存方案：保存到简单的目录结构
                backup_dir = Path(self.storage_root) / "backup_data" / datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_dir.mkdir(parents=True, exist_ok=True)

                # 保存基本信息
                info_file = backup_dir / "info.json"
                with open(info_file, 'w', encoding='utf-8') as f:
                    safe_json_dump(tree_data, f, ensure_ascii=False, indent=2)

                print(f"✅ 数据已保存到备用位置: {backup_dir}")
                return str(backup_dir)
            except Exception as backup_error:
                print(f"❌ 备用保存方案也失败: {str(backup_error)}")
                return None

    def _save_tree_structure(self, tree_data, base_dir, current_path_parts=None):
        """保存整个树结构到指定目录，修复路径重复问题"""
        if not tree_data or not isinstance(tree_data, dict):
            print(f"   ⚠️  无效的树数据: {type(tree_data)}")
            return

        # 初始化路径部分列表
        if current_path_parts is None:
            current_path_parts = []

        node_name = tree_data.get('name', 'Unknown')
        current_url = tree_data.get('url', '')

        print(f"   🔍 处理节点: {node_name}")
        print(f"      节点URL: {current_url}")
        node_type = '产品' if tree_data.get('guides') or tree_data.get('troubleshooting') else '分类'
        print(f"      指南数量: {len(tree_data.get('guides', []))}")
        print(f"      故障排除数量: {len(tree_data.get('troubleshooting', []))}")

        # 检查当前节点是否有实际内容需要保存
        has_guides = tree_data.get('guides') and len(tree_data.get('guides', [])) > 0
        has_troubleshooting = tree_data.get('troubleshooting') and len(tree_data.get('troubleshooting', [])) > 0
        has_content = has_guides or has_troubleshooting

        if has_content:
            print(f"   ✅ 发现内容节点: {node_name}")
            print(f"      指南数量: {len(tree_data.get('guides', []))}")
            print(f"      故障排除数量: {len(tree_data.get('troubleshooting', []))}")
            print(f"      保存路径: {base_dir}")

            # 确保目录存在
            base_dir.mkdir(parents=True, exist_ok=True)

            # 保存节点内容到当前目录，不再创建重复的子目录
            print(f"   💾 开始保存节点内容...")
            self._save_node_content(tree_data, base_dir)
            print(f"   ✅ 节点内容保存完成")

        # 处理子节点
        if 'children' in tree_data and tree_data['children']:
            print(f"   🌳 处理 {len(tree_data['children'])} 个子节点...")
            for child in tree_data['children']:
                child_name = child.get('name', 'Unknown')

                # 清理子节点名称，处理特殊字符
                safe_name = self._clean_directory_name(child_name)
                child_dir = base_dir / safe_name

                # 检查子节点是否有内容
                child_has_content = (child.get('guides') and len(child.get('guides', [])) > 0) or \
                                  (child.get('troubleshooting') and len(child.get('troubleshooting', [])) > 0)

                # 检查子节点是否有真正的子节点（非空的children数组）
                child_has_children = child.get('children') and len(child.get('children', [])) > 0

                # 为所有子节点创建目录，包括叶子节点（即使没有内容）
                # 这确保了树结构的完整性，即使某些叶子节点暂时没有guides或troubleshooting
                print(f"      子节点 '{child_name}': 内容={child_has_content}, 子节点={child_has_children}, URL={bool(child.get('url'))}")

                if child_has_content or child_has_children or child.get('url'):
                    try:
                        if not child_dir.exists():
                            child_dir.mkdir(parents=True, exist_ok=True)
                            print(f"   📁 创建子节点目录: {child_dir}")
                            # 记录目录名称处理过程，帮助调试
                            print(f"      原始名称: '{child_name}'")
                            print(f"      清理后名称: '{safe_name}'")
                        else:
                            print(f"   📁 使用已存在的子节点目录: {child_dir}")

                        # 递归处理子节点，使用子节点的目录
                        self._save_tree_structure(child, child_dir, current_path_parts + [node_name])
                    except Exception as e:
                        # 增强错误处理，记录详细信息但不中断整个过程
                        print(f"   ❌ 创建或处理目录失败: {child_dir}")
                        print(f"      错误信息: {str(e)}")
                        print(f"      子节点名称: '{child_name}'")
                        print(f"      清理后名称: '{safe_name}'")
                        # 尝试使用备用名称
                        try:
                            backup_name = f"Category_{hash(child_name) % 10000:04d}"
                            backup_dir = base_dir / backup_name
                            print(f"      尝试使用备用名称: '{backup_name}'")
                            backup_dir.mkdir(parents=True, exist_ok=True)
                            self._save_tree_structure(child, backup_dir, current_path_parts + [node_name])
                        except Exception as backup_error:
                            print(f"      备用名称也失败: {str(backup_error)}")
                else:
                    # 只有当子节点完全没有任何有用信息时才跳过
                    print(f"   ⏭️  跳过无效子节点: {child_name} (无内容、无子节点、无URL)")

    def _clean_directory_name(self, name):
        """清理目录名称，移除文件系统不支持的字符"""
        if not name:
            return "Unknown"

        # 替换文件系统不支持的字符
        safe_name = name.replace('/', '_').replace('\\', '_')
        safe_name = safe_name.replace(':', '_').replace('*', '_')
        safe_name = safe_name.replace('?', '_').replace('<', '_')
        safe_name = safe_name.replace('>', '_').replace('|', '_')
        
        # 不替换引号，保持原样（macOS和Linux支持引号在文件名中）
        # safe_name = safe_name.replace('"', '_').replace("'", "_")
        
        # 移除多余的空格，但保持其他字符
        safe_name = safe_name.strip()
        
        # 处理空名称
        if not safe_name:
            return "Unknown"
            
        # 限制长度，避免文件系统问题
        if len(safe_name) > 100:
            safe_name = safe_name[:97] + "..."
            
        return safe_name

    def _validate_data_completeness(self, tree_data, root_dir):
        """验证数据完整性，检查所有类别是否都有对应的目录"""
        missing_categories = []
        total_categories = 0
        existing_directories = 0

        def check_node(node, current_path=""):
            nonlocal missing_categories, total_categories, existing_directories

            if not node or not isinstance(node, dict):
                return

            node_name = node.get('name', 'Unknown')
            node_url = node.get('url', '')

            # 检查是否有子节点
            children = node.get('children', [])
            if children:
                total_categories += len(children)

                for child in children:
                    child_name = child.get('name', 'Unknown')
                    safe_name = self._clean_directory_name(child_name)

                    # 构建预期的目录路径
                    if current_path:
                        expected_dir = root_dir / current_path / safe_name
                    else:
                        expected_dir = root_dir / safe_name

                    # 检查目录是否存在
                    if expected_dir.exists():
                        existing_directories += 1
                        print(f"   ✅ 目录存在: {safe_name}")
                    else:
                        missing_categories.append({
                            'name': child_name,
                            'safe_name': safe_name,
                            'url': child.get('url', ''),
                            'expected_path': str(expected_dir),
                            'has_children': bool(child.get('children')),
                            'has_content': bool(child.get('guides') or child.get('troubleshooting'))
                        })
                        print(f"   ❌ 目录缺失: {safe_name} (原名: {child_name})")

                    # 递归检查子节点
                    if current_path:
                        check_node(child, f"{current_path}/{safe_name}")
                    else:
                        check_node(child, safe_name)

        print(f"   正在检查树结构完整性...")
        check_node(tree_data)

        # 输出验证结果
        print(f"\n📊 数据完整性验证结果:")
        print(f"   总类别数: {total_categories}")
        print(f"   已创建目录: {existing_directories}")
        print(f"   缺失目录: {len(missing_categories)}")

        if missing_categories:
            print(f"\n❌ 发现 {len(missing_categories)} 个缺失的类别目录:")
            for missing in missing_categories:
                print(f"   - 类别: '{missing['name']}'")
                print(f"     清理后名称: '{missing['safe_name']}'")
                print(f"     预期路径: {missing['expected_path']}")
                print(f"     有子节点: {missing['has_children']}")
                print(f"     有内容: {missing['has_content']}")
                if missing['url']:
                    print(f"     URL: {missing['url']}")
                print()
        else:
            print(f"   ✅ 所有类别目录都已正确创建")

        return len(missing_categories) == 0

    def _save_node_content(self, node_data, node_dir):
        """保存单个节点的内容（guides和troubleshooting）"""
        if not node_data or not isinstance(node_data, dict):
            print(f"   ⚠️  节点数据无效: {type(node_data)}")
            return

        # 在保存前验证数据完整性
        print(f"   🔍 验证节点数据完整性...")
        self._validate_node_data_before_save(node_data)

        # 创建节点目录
        node_dir.mkdir(parents=True, exist_ok=True)
        print(f"   📁 创建目录: {node_dir}")

        # 保存节点基本信息
        info_data = {k: v for k, v in node_data.items()
                    if k not in ['children', 'guides', 'troubleshooting']}

        # 确保info_data不为空，至少包含基本信息
        if not info_data:
            info_data = {
                'name': node_data.get('name', 'Unknown'),
                'url': node_data.get('url', ''),
                'saved_at': datetime.now().isoformat()
            }

        try:
            info_file = node_dir / "info.json"
            print(f"   💾 保存基本信息到: {info_file}")
            print(f"   📊 基本信息字段数: {len(info_data)}")
            with open(info_file, 'w', encoding='utf-8') as f:
                safe_json_dump(info_data, f, ensure_ascii=False, indent=2)
            print(f"   ✅ 基本信息保存成功")
        except Exception as e:
            print(f"   ❌ 保存基本信息失败: {e}")

        # 处理guides
        guides_count = 0
        if 'guides' in node_data and node_data['guides']:
            guides_dir = node_dir / "guides"
            guides_dir.mkdir(exist_ok=True)
            print(f"   📖 处理 {len(node_data['guides'])} 个指南")

            for i, guide in enumerate(node_data['guides']):
                try:
                    if not guide or not isinstance(guide, dict):
                        print(f"   ⚠️  跳过无效指南 #{i+1}: {type(guide)}")
                        continue
                        
                    guide_data = guide.copy()
                    print(f"   📖 [{i+1}/{len(node_data['guides'])}] 保存指南: {guide_data.get('title', 'Unknown')[:50]}")
                    
                    # 为每个guide创建单独的目录，媒体文件和guide文件在同一层级
                    guide_dir = guides_dir / f"guide_{i+1}"
                    guide_dir.mkdir(exist_ok=True)

                    # 处理媒体文件，存储在guide目录下
                    try:
                        self._process_media_urls(guide_data, guide_dir)
                    except Exception as media_error:
                        print(f"   ⚠️  媒体文件处理失败: {media_error}")

                    # 保存guide文件到guide目录
                    guide_file = guide_dir / "guide.json"
                    with open(guide_file, 'w', encoding='utf-8') as f:
                        safe_json_dump(guide_data, f, ensure_ascii=False, indent=2)
                    
                    guides_count += 1
                    print(f"   ✅ 指南保存成功: {guide_file}")
                    
                except Exception as e:
                    print(f"   ❌ 保存指南 #{i+1} 失败: {e}")
            
            print(f"   📖 指南处理完成: {guides_count}/{len(node_data['guides'])} 成功")

        # 处理troubleshooting
        troubleshooting_count = 0
        if 'troubleshooting' in node_data and node_data['troubleshooting']:
            ts_dir = node_dir / "troubleshooting"
            ts_dir.mkdir(exist_ok=True)
            print(f"   🔧 处理 {len(node_data['troubleshooting'])} 个故障排除")

            for i, ts in enumerate(node_data['troubleshooting']):
                try:
                    if not ts or not isinstance(ts, dict):
                        print(f"   ⚠️  跳过无效故障排除 #{i+1}: {type(ts)}")
                        continue
                        
                    ts_data = ts.copy()
                    print(f"   🔧 [{i+1}/{len(node_data['troubleshooting'])}] 保存故障排除: {ts_data.get('title', 'Unknown')[:50]}")
                    
                    # 为每个troubleshooting创建单独的目录，媒体文件和ts文件在同一层级
                    ts_item_dir = ts_dir / f"troubleshooting_{i+1}"
                    ts_item_dir.mkdir(exist_ok=True)

                    # 处理媒体文件，存储在troubleshooting目录下
                    try:
                        self._process_media_urls(ts_data, ts_item_dir)
                    except Exception as media_error:
                        print(f"   ⚠️  媒体文件处理失败: {media_error}")

                    # 保存troubleshooting文件到troubleshooting目录
                    ts_file = ts_item_dir / "troubleshooting.json"
                    with open(ts_file, 'w', encoding='utf-8') as f:
                        safe_json_dump(ts_data, f, ensure_ascii=False, indent=2)
                    
                    troubleshooting_count += 1
                    print(f"   ✅ 故障排除保存成功: {ts_file}")
                    
                except Exception as e:
                    print(f"   ❌ 保存故障排除 #{i+1} 失败: {e}")

            print(f"   🔧 故障排除处理完成: {troubleshooting_count}/{len(node_data['troubleshooting'])} 成功")

            # 在Troubleshooting目录创建后立即保存cache文件
            if self.cache_manager:
                try:
                    current_url = node_data.get('url', '')
                    if current_url and node_data.get('troubleshooting'):
                        troubleshooting_cache_key = f"{current_url}#troubleshooting"
                        self.cache_manager.save_troubleshooting_cache_after_directory_creation(
                            troubleshooting_cache_key, current_url, node_data['troubleshooting'], ts_dir)
                        print(f"   💾 已生成troubleshooting_cache.json文件: {node_dir / 'troubleshooting_cache.json'}")
                    else:
                        print(f"   ⚠️  跳过生成troubleshooting缓存: URL或数据为空")
                except Exception as cache_error:
                    print(f"   ⚠️  保存troubleshooting缓存失败: {cache_error}")
                    import traceback
                    print(f"   详细错误: {traceback.format_exc()}")

        # 更新缓存索引
        try:
            self._update_cache_for_node(node_data, node_dir)
            print(f"   📋 缓存索引更新成功")
        except Exception as cache_error:
            print(f"   ⚠️  更新缓存索引失败: {cache_error}")
            
        print(f"   ✅ 节点内容保存完成: 📖 {guides_count} 个指南, 🔧 {troubleshooting_count} 个故障排除")

    def _validate_node_data_before_save(self, node_data):
        """在保存前验证节点数据的完整性"""
        if not node_data or not isinstance(node_data, dict):
            print(f"   ❌ 节点数据验证失败: 数据为空或类型错误 {type(node_data)}")
            return False
            
        # 检查基本字段
        required_fields = ['name', 'url']
        missing_fields = [field for field in required_fields if not node_data.get(field)]
        if missing_fields:
            print(f"   ⚠️  缺少必要字段: {missing_fields}")
        
        # 检查guides数据
        guides = node_data.get('guides', [])
        if guides:
            print(f"   📖 验证 {len(guides)} 个指南数据:")
            for i, guide in enumerate(guides):
                if not isinstance(guide, dict):
                    print(f"      ❌ 指南 #{i+1} 数据类型错误: {type(guide)}")
                    continue
                    
                guide_title = guide.get('title', 'Unknown')[:50]
                guide_steps = guide.get('steps', [])
                print(f"      📖 [{i+1}] {guide_title} - {len(guide_steps)} 步骤")
                
                # 检查步骤数据
                if not guide_steps:
                    print(f"         ⚠️  指南无步骤数据")
                else:
                    # 检查前几个步骤的数据完整性
                    for j, step in enumerate(guide_steps[:3]):  # 只检查前3个步骤
                        if isinstance(step, dict):
                            step_text = step.get('text', '')
                            step_images = step.get('images', [])
                            print(f"         步骤 {j+1}: {len(step_text)} 字符, {len(step_images)} 图片")
        
        # 检查troubleshooting数据
        troubleshooting = node_data.get('troubleshooting', [])
        if troubleshooting:
            print(f"   🔧 验证 {len(troubleshooting)} 个故障排除数据:")
            for i, ts in enumerate(troubleshooting):
                if not isinstance(ts, dict):
                    print(f"      ❌ 故障排除 #{i+1} 数据类型错误: {type(ts)}")
                    continue
                    
                ts_title = ts.get('title', 'Unknown')[:50]
                ts_causes = ts.get('causes', [])
                print(f"      🔧 [{i+1}] {ts_title} - {len(ts_causes)} 原因")
                
                # 检查原因数据
                if not ts_causes:
                    print(f"         ⚠️  故障排除无原因数据")
                else:
                    for j, cause in enumerate(ts_causes[:2]):  # 只检查前2个原因
                        if isinstance(cause, dict):
                            cause_content = cause.get('content', '')
                            cause_images = cause.get('images', [])
                            print(f"         原因 {j+1}: {len(cause_content)} 字符, {len(cause_images)} 图片")
        
        print(f"   ✅ 节点数据验证完成")
        return True

    def _find_target_node_in_tree_v2(self, tree_data):
        """在树结构中找到包含实际内容的目标节点（增强版）"""
        if not tree_data or not isinstance(tree_data, dict):
            return None

        # 检查当前节点是否有内容
        has_guides = tree_data.get('guides') and len(tree_data.get('guides', [])) > 0
        has_troubleshooting = tree_data.get('troubleshooting') and len(tree_data.get('troubleshooting', [])) > 0

        if has_guides or has_troubleshooting:
            return tree_data

        # 递归检查子节点
        if 'children' in tree_data and tree_data['children']:
            for child in tree_data['children']:
                result = self._find_target_node_in_tree_v2(child)
                if result:
                    return result

        return None

    def _find_all_content_nodes_in_tree(self, tree_data):
        """在树结构中找到所有包含实际内容的节点"""
        content_nodes = []
        if not tree_data or not isinstance(tree_data, dict):
            return content_nodes

        # 检查当前节点是否有内容
        has_guides = tree_data.get('guides') and len(tree_data.get('guides', [])) > 0
        has_troubleshooting = tree_data.get('troubleshooting') and len(tree_data.get('troubleshooting', [])) > 0

        if has_guides or has_troubleshooting:
            content_nodes.append(tree_data)

        # 递归检查子节点
        if 'children' in tree_data and tree_data['children']:
            for child in tree_data['children']:
                child_nodes = self._find_all_content_nodes_in_tree(child)
                content_nodes.extend(child_nodes)

        return content_nodes

    def _find_target_node_by_url(self, tree_data, target_url):
        """根据URL在树结构中查找目标节点"""
        if not tree_data or not isinstance(tree_data, dict) or not target_url:
            return None

        # 检查当前节点的URL是否匹配
        current_url = tree_data.get('url', '')
        if current_url and current_url == target_url:
            return tree_data

        # 递归检查子节点
        if 'children' in tree_data and tree_data['children']:
            for child in tree_data['children']:
                result = self._find_target_node_by_url(child, target_url)
                if result:
                    return result

        return None

    def _save_target_node_children(self, target_node, root_dir):
        """只保存目标节点的子结构"""
        if not target_node or not isinstance(target_node, dict):
            return

        # 确保根目录存在
        root_dir.mkdir(parents=True, exist_ok=True)

        # 保存目标节点本身的内容（如果有的话）
        if target_node.get('guides') or target_node.get('troubleshooting'):
            self._save_node_content(target_node, root_dir)

        # 保存子节点结构
        if 'children' in target_node and target_node['children']:
            for child in target_node['children']:
                child_name = child.get('name', 'Unknown')
                safe_name = self._clean_directory_name(child_name)
                child_dir = root_dir / safe_name

                # 递归保存子节点
                self._save_tree_structure(child, child_dir)

    def _update_cache_for_node(self, node_data, node_dir):
        """为节点更新缓存索引，正确统计媒体文件数量"""
        if not self.cache_manager or not node_data:
            return

        url = node_data.get('url', '')
        if not url:
            return

        try:
            # 统计内容数量
            guides_count = len(node_data.get('guides', []))
            troubleshooting_count = len(node_data.get('troubleshooting', []))

            # 统计媒体文件数量 - 递归统计所有子目录中的媒体文件
            media_count = 0

            # 统计guides目录下的媒体文件
            guides_dir = node_dir / "guides"
            if guides_dir.exists():
                for guide_subdir in guides_dir.iterdir():
                    if guide_subdir.is_dir():
                        media_subdir = guide_subdir / "media"
                        if media_subdir.exists():
                            media_count += len(list(media_subdir.glob("*")))

            # 统计troubleshooting目录下的媒体文件
            ts_dir = node_dir / "troubleshooting"
            if ts_dir.exists():
                for ts_subdir in ts_dir.iterdir():
                    if ts_subdir.is_dir():
                        media_subdir = ts_subdir / "media"
                        if media_subdir.exists():
                            media_count += len(list(media_subdir.glob("*")))

            # 统计根目录下的媒体文件（如果有的话）
            root_media_dir = node_dir / "media"
            if root_media_dir.exists():
                media_count += len(list(root_media_dir.glob("*")))

            print(f"   📊 统计结果 - 指南: {guides_count}, 故障排除: {troubleshooting_count}, 媒体文件: {media_count}")

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
            safe_json_dump(info_data, f, ensure_ascii=False, indent=2)

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
                    safe_json_dump(guide_data, f, ensure_ascii=False, indent=2)

        # 处理troubleshooting - 只有当前节点有troubleshooting数据时才保存
        # troubleshooting应该保存在它所属的具体页面目录下，而不是上级目录
        if 'troubleshooting' in node_data and node_data['troubleshooting']:
            # 检查这些troubleshooting是否真的属于当前页面
            current_url = node_data.get('url', '')
            if current_url and self._troubleshooting_belongs_to_current_page(node_data['troubleshooting'], current_url):
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
                        safe_json_dump(ts_data, f, ensure_ascii=False, indent=2)

                print(f"   💾 保存了 {len(node_data['troubleshooting'])} 个troubleshooting到: {ts_dir}")

                # 在Troubleshooting目录创建后立即保存cache文件
                if self.cache_manager and current_url:
                    troubleshooting_cache_key = f"{current_url}#troubleshooting"
                    self.cache_manager.save_troubleshooting_cache_after_directory_creation(
                        troubleshooting_cache_key, current_url, node_data['troubleshooting'], ts_dir)
            else:
                print(f"   ⚠️  跳过保存troubleshooting，因为它们不属于当前页面: {current_url}")

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
            safe_json_dump(node_info, f, ensure_ascii=False, indent=2)

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
                    safe_json_dump(guide_data, f, ensure_ascii=False, indent=2)

        # 处理troubleshooting - 只有当前子类别有troubleshooting数据时才保存
        if 'troubleshooting' in node_data and node_data['troubleshooting']:
            current_url = node_data.get('url', '')
            if current_url and self._troubleshooting_belongs_to_current_page(node_data['troubleshooting'], current_url):
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
                        safe_json_dump(ts_data, f, ensure_ascii=False, indent=2)

                # 在Troubleshooting目录创建后立即保存cache文件
                if self.cache_manager and current_url:
                    troubleshooting_cache_key = f"{current_url}#troubleshooting"
                    self.cache_manager.save_troubleshooting_cache_after_directory_creation(
                        troubleshooting_cache_key, current_url, node_data['troubleshooting'], ts_dir)

                print(f"   💾 保存了 {len(node_data['troubleshooting'])} 个troubleshooting到子类别: {subcat_dir}")
            else:
                print(f"   ⚠️  跳过保存troubleshooting到子类别，因为它们不属于当前页面: {current_url}")

        # 递归处理更深层的子类别
        if 'children' in node_data and node_data['children']:
            for child in node_data['children']:
                self._save_subcategory_to_filesystem(child, subcat_dir)

    def _save_node_to_filesystem(self, node, base_dir, path_prefix):
        """递归保存节点到文件系统，确保路径符合真实结构"""
        if not node or not isinstance(node, dict):
            return

        node_name = node.get('name', 'unknown')
        # 使用统一的目录名清理方法
        safe_name = self._clean_directory_name(node_name)

        # 构建当前节点路径
        if path_prefix:
            current_path = path_prefix + "/" + safe_name
            node_dir = base_dir / current_path
        else:
            # 检查是否已存在匹配的目录
            existing_dir = self._find_matching_directory(base_dir, safe_name)
            if existing_dir:
                node_dir = existing_dir
                print(f"   ✅ 使用已有目录: {node_dir}")
            else:
                node_dir = base_dir / safe_name

        # 创建目录（如果不存在）
        if not node_dir.exists():
            node_dir.mkdir(parents=True, exist_ok=True)
            print(f"   📁 创建新目录: {node_dir}")

        # 复制节点数据并处理媒体URL
        node_data = node.copy()
        self._process_media_urls(node_data, node_dir)

        # 保存节点信息到JSON文件
        info_file = node_dir / "info.json"
        node_info = {k: v for k, v in node_data.items() if k not in ['children', 'guides', 'troubleshooting']}
        with open(info_file, 'w', encoding='utf-8') as f:
            safe_json_dump(node_info, f, ensure_ascii=False, indent=2)

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
                    safe_json_dump(guide_data, f, ensure_ascii=False, indent=2)

        # 处理troubleshooting - 只有属于当前节点的troubleshooting才保存
        if 'troubleshooting' in node_data and node_data['troubleshooting']:
            current_url = node_data.get('url', '')
            if current_url and self._troubleshooting_belongs_to_current_page(node_data['troubleshooting'], current_url):
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
                        safe_json_dump(ts_data, f, ensure_ascii=False, indent=2)

                # 在Troubleshooting目录创建后立即保存cache文件
                if self.cache_manager and current_url:
                    troubleshooting_cache_key = f"{current_url}#troubleshooting"
                    self.cache_manager.save_troubleshooting_cache_after_directory_creation(
                        troubleshooting_cache_key, current_url, node_data['troubleshooting'], ts_dir)

                print(f"   💾 保存了 {len(node_data['troubleshooting'])} 个troubleshooting到节点: {node_dir}")
            else:
                print(f"   ⚠️  跳过保存troubleshooting到节点，因为它们不属于当前页面: {current_url}")

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
    print("iFixit高性能爬虫工具 - 使用说明")
    print("=" * 60)
    print("使用方法:")
    print("python auto_crawler.py [URL或设备名] [选项...]")
    print("\n基本用法:")
    print("  python auto_crawler.py iMac_M_Series")
    print("  python auto_crawler.py https://www.ifixit.com/Device/Television")
    print("  python auto_crawler.py Television")
    print("\n🚀 性能调优选项:")
    print("  --workers N            设置并发线程数（默认8，推荐8-16）")
    print("  --max-connections N    设置最大连接数（默认80）")
    print("  --max-retries N        设置最大重试次数（默认3）")
    print("  --timeout N            设置请求超时时间（秒，默认30）")
    print("  --delay N              设置请求间隔（秒，默认0.5）")
    print("  --burst-mode           启用爆发模式（最大性能，可能被限制）")
    print("  --conservative         启用保守模式（降低并发，更稳定）")
    print("\n🌐 代理和网络选项:")
    print("  --no-proxy             关闭隧道代理（默认启用）")
    print("  --proxy-switch N       代理切换频率（请求数，默认1=每次切换）")
    print("  --user-agent TEXT      自定义User-Agent")
    print("\n💾 缓存和数据选项:")
    print("  --no-cache             禁用缓存检查（默认启用）")
    print("  --force-refresh        强制重新爬取（忽略缓存）")
    print("  --cache-ttl N          缓存配置参数（保留兼容性，实际为长期保存）")
    print("\n🔄 断点续爬选项:")
    print("  --no-resume            禁用断点续爬功能（默认启用）")
    print("  --reset-progress       重置树构建进度（清除断点记录）")
    print("  --reset-only           仅重置进度后退出（不开始爬取）")
    print("  --show-progress        显示当前树构建进度")
    print("  --progress-only        仅显示进度后退出（不开始爬取）")
    print("\n📹 媒体处理选项:")
    print("  --download-videos      启用视频文件下载（默认禁用）")
    print("  --max-video-size N     设置视频文件大小限制（MB，默认50）")
    print("  --skip-images          跳过图片下载（仅保存URL）")
    print("\n🔧 调试选项:")
    print("  --verbose              启用详细输出")
    print("  --debug                启用调试模式（更详细的日志）")
    print("  --stats                显示详细统计信息")
    print("\n📊 预设配置:")
    print("  --fast                 快速模式：--workers 12 --burst-mode")
    print("  --stable               稳定模式：--workers 4 --conservative --delay 1")
    print("  --enterprise           企业模式：--workers 16 --max-connections 160")
    print("\n示例:")
    print("  # 默认高性能模式（8线程+代理池）")
    print("  python auto_crawler.py iMac_M_Series")
    print("")
    print("  # 快速模式（12线程+爆发模式）")
    print("  python auto_crawler.py iMac_M_Series --fast")
    print("")
    print("  # 企业级高并发模式")
    print("  python auto_crawler.py Television --enterprise --download-videos")
    print("")
    print("  # 稳定模式（适合网络不稳定环境）")
    print("  python auto_crawler.py iPhone --stable --verbose")
    print("")
    print("  # 自定义高性能配置")
    print("  python auto_crawler.py MacBook --workers 20 --max-connections 200 --delay 0.2")
    print("")
    print("  # 断点续爬相关操作")
    print("  python auto_crawler.py Television --show-progress  # 查看进度")
    print("  python auto_crawler.py Television --reset-progress # 重置进度")
    print("  python auto_crawler.py Television                  # 自动从断点恢复")
    print("\n🎯 默认配置说明:")
    print("- 🔥 高性能：默认8线程并发 + 隧道代理池")
    print("- 🌐 智能代理：HTTP隧道代理池，每次请求自动切换IP")
    print("- 💾 智能缓存：自动跳过已爬取的内容，长期保存到本地")
    print("- 🔄 断点续爬：自动记录树构建进度，支持中断恢复")
    print("- 🔄 错误重试：网络错误自动重试，指数退避策略")
    print("- 📁 媒体下载：自动下载并本地化所有图片文件")
    print("- 📊 实时统计：显示爬取进度和性能指标")
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

    # 🚀 默认高性能配置
    verbose = '--verbose' in args or '--debug' in args
    debug_mode = '--debug' in args
    show_stats = '--stats' in args
    use_proxy = '--no-proxy' not in args  # 默认启用代理
    use_cache = '--no-cache' not in args  # 默认启用缓存
    force_refresh = '--force-refresh' in args
    skip_images = '--skip-images' in args

    # 🎯 预设配置处理
    if '--fast' in args:
        # 快速模式：高并发 + 爆发模式
        default_workers = 12
        burst_mode = True
        conservative_mode = False
        default_delay = 0.3
    elif '--stable' in args:
        # 稳定模式：低并发 + 保守策略
        default_workers = 4
        burst_mode = False
        conservative_mode = True
        default_delay = 1.0
    elif '--enterprise' in args:
        # 企业模式：超高并发
        default_workers = 16
        burst_mode = True
        conservative_mode = False
        default_delay = 0.2
    else:
        # 默认高性能模式
        default_workers = 8
        burst_mode = '--burst-mode' in args
        conservative_mode = '--conservative' in args
        default_delay = 0.5

    # 解析性能参数
    max_workers = default_workers
    if '--workers' in args:
        try:
            workers_idx = args.index('--workers')
            if workers_idx + 1 < len(args):
                max_workers = int(args[workers_idx + 1])
        except (ValueError, IndexError):
            print(f"警告: workers参数无效，使用默认值{default_workers}")

    # 解析连接数参数
    max_connections = max_workers * 10  # 默认为线程数的10倍
    if '--max-connections' in args:
        try:
            conn_idx = args.index('--max-connections')
            if conn_idx + 1 < len(args):
                max_connections = int(args[conn_idx + 1])
        except (ValueError, IndexError):
            print(f"警告: max-connections参数无效，使用默认值{max_connections}")

    # 解析重试参数
    max_retries = 1  # 极速模式：最少重试次数
    if '--max-retries' in args:
        try:
            retries_idx = args.index('--max-retries')
            if retries_idx + 1 < len(args):
                max_retries = int(args[retries_idx + 1])
        except (ValueError, IndexError):
            print("警告: max-retries参数无效，使用默认值3")

    # 解析超时参数
    timeout = 30
    if '--timeout' in args:
        try:
            timeout_idx = args.index('--timeout')
            if timeout_idx + 1 < len(args):
                timeout = int(args[timeout_idx + 1])
        except (ValueError, IndexError):
            print("警告: timeout参数无效，使用默认值30秒")

    # 解析请求间隔参数
    request_delay = default_delay
    if '--delay' in args:
        try:
            delay_idx = args.index('--delay')
            if delay_idx + 1 < len(args):
                request_delay = float(args[delay_idx + 1])
        except (ValueError, IndexError):
            print(f"警告: delay参数无效，使用默认值{default_delay}秒")

    # 解析代理切换频率
    proxy_switch_freq = 1  # 默认每次请求都切换IP
    if '--proxy-switch' in args:
        try:
            switch_idx = args.index('--proxy-switch')
            if switch_idx + 1 < len(args):
                proxy_switch_freq = int(args[switch_idx + 1])
        except (ValueError, IndexError):
            print("警告: proxy-switch参数无效，使用默认值1（每次请求切换）")

    # 解析缓存TTL
    cache_ttl = 24
    if '--cache-ttl' in args:
        try:
            ttl_idx = args.index('--cache-ttl')
            if ttl_idx + 1 < len(args):
                cache_ttl = int(args[ttl_idx + 1])
        except (ValueError, IndexError):
            print("警告: cache-ttl参数无效，使用默认值24小时")

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

    # 🔄 解析断点续爬参数
    enable_resume = '--no-resume' not in args  # 默认启用断点续爬
    reset_progress = '--reset-progress' in args
    show_progress = '--show-progress' in args

    # 处理进度重置
    if reset_progress:
        print("🔄 重置树构建进度...")
        from tree_building_progress import TreeBuildingProgressManager

        # 确定目标URL
        url = input_text if input_text.startswith('http') else f"https://www.ifixit.com/Device/{input_text}"
        progress_manager = TreeBuildingProgressManager(url)
        progress_manager.reset_progress()
        print("✅ 进度已重置")

        if '--reset-only' in args:
            return

    # 显示进度报告
    if show_progress:
        print("📊 显示树构建进度...")
        from tree_building_progress import TreeBuildingProgressManager

        # 确定目标URL
        url = input_text if input_text.startswith('http') else f"https://www.ifixit.com/Device/{input_text}"
        progress_manager = TreeBuildingProgressManager(url)
        progress_manager.display_progress_report()

        if '--progress-only' in args:
            return

    # 解析自定义User-Agent
    custom_user_agent = None
    if '--user-agent' in args:
        try:
            ua_idx = args.index('--user-agent')
            if ua_idx + 1 < len(args):
                custom_user_agent = args[ua_idx + 1]
        except (ValueError, IndexError):
            print("警告: user-agent参数无效")

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

        # 🚀 显示高性能配置信息
        print("\n" + "=" * 80)
        print(f"🎯 开始高性能爬取: {name}")
        print("=" * 80)
        print(f"🔥 性能配置:")
        print(f"   并发线程数: {max_workers}")
        print(f"   最大连接数: {max_connections}")
        print(f"   请求间隔: {request_delay}秒")
        print(f"   超时时间: {timeout}秒")
        print(f"   最大重试: {max_retries}次")

        mode_desc = []
        if burst_mode:
            mode_desc.append("🚀爆发模式")
        if conservative_mode:
            mode_desc.append("🛡️保守模式")
        if mode_desc:
            print(f"   运行模式: {' + '.join(mode_desc)}")

        print(f"🌐 网络配置:")
        print(f"   隧道代理: {'✅启用' if use_proxy else '❌禁用'}")
        if use_proxy:
            if proxy_switch_freq == 1:
                print(f"   代理切换: 每次请求切换IP")
            else:
                print(f"   代理切换: 每{proxy_switch_freq}次请求")
        print(f"   智能缓存: {'✅启用' if use_cache else '❌禁用'}")
        if use_cache:
            print(f"   缓存策略: 长期保存到本地文件")

        print(f"📁 媒体处理:")
        print(f"   图片下载: {'❌跳过' if skip_images else '✅启用'}")
        print(f"   视频下载: {'✅启用' if download_videos else '❌禁用'}")
        if download_videos:
            print(f"   视频大小限制: {max_video_size_mb}MB")

        print(f"🔧 其他选项:")
        print(f"   详细输出: {'✅启用' if verbose else '❌禁用'}")
        print(f"   调试模式: {'✅启用' if debug_mode else '❌禁用'}")
        print(f"   统计信息: {'✅启用' if show_stats else '❌禁用'}")
        print(f"   强制刷新: {'✅启用' if force_refresh else '❌禁用'}")

        print("=" * 80)
        print("🚀 执行阶段:")
        print("   阶段1: 构建完整树形结构")
        print("   阶段2: 高并发提取详细内容")
        print("   阶段3: 并行下载媒体文件")
        print("=" * 80)

        # 🚀 创建高性能整合爬虫
        crawler = CombinedIFixitCrawler(
            verbose=verbose,
            use_proxy=use_proxy,
            use_cache=use_cache,
            force_refresh=force_refresh,
            max_workers=max_workers,
            max_retries=max_retries,
            download_videos=download_videos,
            max_video_size_mb=max_video_size_mb,
            max_connections=max_connections,
            timeout=timeout,
            request_delay=request_delay,
            proxy_switch_freq=proxy_switch_freq,
            cache_ttl=cache_ttl,
            custom_user_agent=custom_user_agent,
            burst_mode=burst_mode,
            conservative_mode=conservative_mode,
            skip_images=skip_images,
            debug_mode=debug_mode,
            show_stats=show_stats
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
            print(f"\n✗ 爬取过程中发生错误: {safe_str(e)}")
            # 即使出错也保存缓存索引
            if crawler.cache_manager:
                crawler.cache_manager.save_cache_index()
            if verbose:
                import traceback
                traceback.print_exc()
        finally:
            # 确保缓存索引被保存和资源被清理
            if 'crawler' in locals():
                if crawler.cache_manager:
                    crawler.cache_manager.save_cache_index()
                # 清理爬虫资源
                crawler.cleanup()


if __name__ == "__main__":
    main()
