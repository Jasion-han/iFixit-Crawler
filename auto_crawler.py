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
from datetime import datetime
import queue

# 导入两个基础爬虫
from enhanced_crawler import EnhancedIFixitCrawler
from tree_crawler import TreeCrawler


class ProxyManager:
    """代理管理器 - 从本地proxy.txt文件管理代理池"""

    def __init__(self, proxy_file="proxy.txt", username="yjnvjx", password="gkmb3obc"):
        self.proxy_file = proxy_file
        self.username = username
        self.password = password

        self.proxy_pool = []
        self.current_proxy = None
        self.failed_proxies = []
        self.proxy_switch_count = 0
        self.proxy_lock = threading.Lock()

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
                        host, port = line.split(':', 1)
                        proxy_config = {
                            'http': f"http://{self.username}:{self.password}@{host.strip()}:{port.strip()}",
                            'https': f"http://{self.username}:{self.password}@{host.strip()}:{port.strip()}"
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
                # 如果所有代理都失效了，重置失效列表，重新开始
                print("⚠️  所有代理都已失效，重置代理池...")
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

                current_time = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"🔄 切换代理 (第{self.proxy_switch_count}次): {display_ip}:{display_port}")

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
            'switch_count': self.proxy_switch_count
        }

class CombinedIFixitCrawler(EnhancedIFixitCrawler):
    def __init__(self, base_url="https://www.ifixit.com", verbose=False, use_proxy=True,
                 use_cache=True, force_refresh=False, max_workers=4, max_retries=5,
                 download_videos=False, max_video_size_mb=50):
        super().__init__(base_url, verbose)

        # 立即初始化日志系统，确保logger可用
        self._setup_logging()

        self.tree_crawler = TreeCrawler(base_url)
        self.processed_nodes = set()
        self.target_url = None

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
            "media_downloaded": 0,
            "media_failed": 0,
            "videos_skipped": 0,
            "videos_downloaded": 0
        }

        # 本地存储配置
        self.storage_root = "ifixit_data"
        self.media_folder = "media"

        # 缓存配置
        self.use_cache = use_cache
        self.force_refresh = force_refresh

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
        """检查本地缓存是否有效"""
        if not self.use_cache or self.force_refresh:
            return False

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
            total=2,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
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
            proxies = self._get_next_proxy() if self.use_proxy else None
            response = requests.head(url, headers=self.headers, timeout=10, proxies=proxies)
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
        """下载媒体文件到本地（带重试机制和视频处理策略）"""
        if not url or not url.startswith('http'):
            return None

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
            return url

    def _download_media_file_impl(self, url, local_dir, filename=None):
        """媒体文件下载的具体实现"""
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
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if local_path.exists():
            self.stats["media_downloaded"] += 1
            return str(local_path.relative_to(Path(self.storage_root)))

        proxies = self._get_next_proxy() if self.use_proxy else None
        response = requests.get(url, headers=self.headers, timeout=30, proxies=proxies)
        response.raise_for_status()

        with open(local_path, 'wb') as f:
            f.write(response.content)

        self.stats["media_downloaded"] += 1
        self.logger.info(f"媒体文件下载成功: {filename}")
        return str(local_path.relative_to(Path(self.storage_root)))

    def _process_media_urls(self, data, local_dir):
        """递归处理数据中的媒体URL，下载并替换为本地路径"""
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ['image', 'video', 'thumbnail', 'photo'] and isinstance(value, str) and value.startswith('http'):
                    data[key] = self._download_media_file(value, local_dir)
                elif key == 'images' and isinstance(value, list):
                    for i, img_url in enumerate(value):
                        if isinstance(img_url, str) and img_url.startswith('http'):
                            value[i] = self._download_media_file(img_url, local_dir)
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
        
    def crawl_combined_tree(self, start_url, category_name=None):
        """
        整合爬取：构建树形结构并为每个节点提取详细内容
        """
        print(f"开始整合爬取: {start_url}")
        print("=" * 60)

        # 设置目标URL
        self.target_url = start_url

        # 第一步：使用 tree_crawler 逻辑构建基础树结构
        print("1. 构建基础树形结构...")
        base_tree = self.tree_crawler.crawl_tree(start_url, category_name)

        if not base_tree:
            print("无法构建基础树结构")
            return None

        print(f"基础树结构构建完成，开始提取详细内容...")
        print("=" * 60)

        # 第二步：为树中的每个节点提取详细内容
        print("2. 为每个节点提取详细内容...")
        enriched_tree = self.enrich_tree_with_detailed_content(base_tree)

        # 第三步：对于产品页面，深入爬取其指南和故障排除内容
        print("3. 深入爬取产品页面的子内容...")
        final_tree = self.deep_crawl_product_content(enriched_tree)

        return final_tree
        
    def enrich_tree_with_detailed_content(self, node):
        """修复节点的基本数据，确保所有节点都有正确的字段"""
        if not node or not isinstance(node, dict):
            return node

        url = node.get('url', '')
        if not url or url in self.processed_nodes:
            return node

        # 检查缓存
        node_name = node.get('name', 'unknown')
        safe_name = node_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        local_path = Path(self.storage_root) / safe_name

        if self._check_cache_validity(url, local_path):
            self.stats["cache_hits"] += 1
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
            print(f"处理: {node.get('name', '')}")

        # 递归处理子节点
        if 'children' in node and node['children']:
            enriched_children = []
            for child in node['children']:
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
            troubleshooting_links = self.extract_troubleshooting_from_device_page(soup, device_url)
            print(f"  找到 {len(troubleshooting_links)} 个故障排除页面")

            for ts_link in troubleshooting_links:
                if isinstance(ts_link, dict):
                    ts_url = ts_link.get('url', '')
                else:
                    ts_url = ts_link
                if ts_url:
                    tasks.append(('troubleshooting', ts_url))

        # 使用线程池并发处理
        if self.max_workers > 1 and len(tasks) > 1:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as executor:
                future_to_task = {}

                for task_type, url in tasks:
                    if task_type == 'guide':
                        future = executor.submit(self._process_guide_task, url)
                    else:  # troubleshooting
                        future = executor.submit(self._process_troubleshooting_task, url)
                    future_to_task[future] = (task_type, url)

                # 收集结果
                for future in as_completed(future_to_task):
                    task_type, url = future_to_task[future]
                    try:
                        result = future.result()
                        if result:
                            if task_type == 'guide':
                                guides_data.append(result)
                                print(f"    ✓ 指南: {result.get('title', '')}")
                            else:
                                troubleshooting_data.append(result)
                                print(f"    ✓ 故障排除: {result.get('title', '')}")
                    except Exception as e:
                        self.logger.error(f"并发任务失败 {task_type} {url}: {e}")
        else:
            # 单线程处理
            for task_type, url in tasks:
                try:
                    if task_type == 'guide':
                        result = self._process_guide_task(url)
                        if result:
                            guides_data.append(result)
                            print(f"    ✓ 指南: {result.get('title', '')}")
                    else:
                        result = self._process_troubleshooting_task(url)
                        if result:
                            troubleshooting_data.append(result)
                            print(f"    ✓ 故障排除: {result.get('title', '')}")
                except Exception as e:
                    self.logger.error(f"任务失败 {task_type} {url}: {e}")

        return guides_data, troubleshooting_data

    def _process_guide_task(self, guide_url):
        """处理单个guide任务"""
        try:
            guide_content = self.extract_guide_content(guide_url)
            if guide_content:
                guide_content['url'] = guide_url
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
        重写troubleshooting内容提取方法，修复causes提取问题
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
            title_elem = soup.select_one("h1, h2[data-testid='troubleshooting-title']")
            if title_elem:
                title_text = title_elem.get_text().strip()
                title_text = re.sub(r'\s+', ' ', title_text)
                troubleshooting_data["title"] = title_text
                print(f"提取标题: {title_text}")

            # 提取causes - 查找所有Section_开头的div
            causes = []
            section_divs = soup.find_all('div', id=re.compile(r'^Section_'))

            for i, section_div in enumerate(section_divs, 1):
                from bs4 import Tag
                if not isinstance(section_div, Tag):
                    continue

                cause_data = {
                    "number": str(i),
                    "title": "",
                    "content": ""
                }

                # 提取标题
                title_elem = section_div.find('h2')
                if title_elem:
                    title_text = title_elem.get_text().strip()
                    cause_data["title"] = title_text

                # 提取内容 - 查找所有p元素
                content_parts = []
                p_elements = section_div.find_all('p')
                for p in p_elements:
                    p_text = p.get_text().strip()
                    if self.is_commercial_text(p_text):
                        continue

                    if p_text and len(p_text) > 10:
                        content_parts.append(p_text)

                if content_parts:
                    cause_data["content"] = '\n\n'.join(content_parts)

                # 只添加有内容的cause
                if cause_data["title"] or cause_data["content"]:
                    causes.append(cause_data)
                    print(f"  提取Cause {i}: {cause_data['title']}")

            troubleshooting_data["causes"] = causes

            # 提取统计数据
            statistics = self.extract_page_statistics(soup)
            if statistics:
                # 创建view_statistics对象
                view_stats = {}
                for key in ['past_24_hours', 'past_7_days', 'past_30_days', 'all_time']:
                    if key in statistics:
                        view_stats[key] = statistics[key]

                if view_stats:
                    troubleshooting_data["view_statistics"] = view_stats

                for key in ['completed', 'favorites']:
                    if key in statistics:
                        troubleshooting_data[key] = statistics[key]

            print(f"  总计提取到 {len(causes)} 个causes")
            return troubleshooting_data

        except Exception as e:
            print(f"提取故障排除内容时发生错误: {str(e)}")
            return None

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
            print(f"深入爬取目标产品页面: {node.get('name', '')}")

            try:
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

                    guides = self.extract_guides_from_device_page(soup, url)
                    guide_links = [guide["url"] for guide in guides]
                    print(f"  找到 {len(guide_links)} 个指南")

                    # 使用并发处理guides和troubleshooting
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
            for i, child in enumerate(node['children']):
                node['children'][i] = self.deep_crawl_product_content(child, skip_troubleshooting)

        return node
        
    def save_combined_result(self, tree_data, target_name=None):
        """保存整合结果到本地文件夹结构"""
        # 创建根目录
        if target_name:
            safe_name = target_name.replace("/", "_").replace("\\", "_").replace(":", "_")
            root_dir = self._create_local_directory(f"auto_{safe_name}")
        else:
            root_name = tree_data.get("name", "auto")
            if " > " in root_name:
                root_name = root_name.split(" > ")[-1]
            root_name = root_name.replace("/", "_").replace("\\", "_").replace(":", "_")
            root_dir = self._create_local_directory(f"auto_{root_name}")

        # 处理媒体文件并保存数据结构
        self._save_node_to_filesystem(tree_data, root_dir, "")

        print(f"\n整合结果已保存到本地文件夹: {root_dir}")
        return str(root_dir)

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
    max_retries = 5
    if '--max-retries' in args:
        try:
            retries_idx = args.index('--max-retries')
            if retries_idx + 1 < len(args):
                max_retries = int(args[retries_idx + 1])
        except (ValueError, IndexError):
            print("警告: max-retries参数无效，使用默认值5")

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
                filename = crawler.save_combined_result(combined_data, target_name=input_text)

                print(f"\n✅ 整合爬取完成!")
                print(f"📁 数据已保存到本地文件夹: {filename}")

                # 显示性能统计
                crawler._print_performance_stats()

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
        except Exception as e:
            print(f"\n✗ 爬取过程中发生错误: {str(e)}")
            if verbose:
                import traceback
                traceback.print_exc()
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
