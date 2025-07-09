#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
整合爬虫工具 - 结合树形结构和详细内容提取 + 企业级功能
将iFixit网站的设备分类以层级树形结构展示，并为每个节点提取详细内容
支持代理池、MySQL存储、失败重试等企业级功能
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
import pymysql
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 导入两个基础爬虫
from enhanced_crawler import EnhancedIFixitCrawler
from tree_crawler import TreeCrawler

class CombinedIFixitCrawler(EnhancedIFixitCrawler):
    def __init__(self, base_url="https://www.ifixit.com", verbose=False, use_proxy=False, use_database=False):
        super().__init__(base_url, verbose)
        self.tree_crawler = TreeCrawler(base_url)
        self.processed_nodes = set()
        self.target_url = None

        # 企业级功能
        self.use_proxy = use_proxy
        self.use_database = use_database
        self.proxy_pool = []
        self.current_proxy_index = 0
        self.db_connection = None
        self.failed_urls = set()

        if use_proxy:
            self._init_proxy_pool()
        if use_database:
            self._init_database()

        # 复制树形爬虫的重要方法到当前类
        self.find_exact_path = self.tree_crawler.find_exact_path
        self.extract_breadcrumbs_from_page = self.tree_crawler.extract_breadcrumbs_from_page
        self._build_tree_from_path = self.tree_crawler._build_tree_from_path
        self._find_node_by_url = self.tree_crawler._find_node_by_url
        self.ensure_instruction_url_in_leaf_nodes = self.tree_crawler.ensure_instruction_url_in_leaf_nodes

        # 重写tree_crawler的get_soup方法，让它使用我们的增强版本
        self.tree_crawler.get_soup = self._tree_crawler_get_soup

    def _init_proxy_pool(self):
        """初始化代理池"""
        self.proxy_pool = [
            {'http': 'http://proxy1:8080', 'https': 'https://proxy1:8080'},
            {'http': 'http://proxy2:8080', 'https': 'https://proxy2:8080'},
        ]

    def _init_database(self):
        """初始化MySQL数据库连接"""
        try:
            self.db_connection = pymysql.connect(
                host='localhost',
                user='root',
                password='password',
                database='ifixit_crawler',
                charset='utf8mb4'
            )
            self._create_tables()
        except Exception as e:
            print(f"数据库连接失败: {e}")
            self.use_database = False

    def _create_tables(self):
        """创建数据库表"""
        if not self.db_connection:
            return

        cursor = self.db_connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS crawl_data (
                id INT AUTO_INCREMENT PRIMARY KEY,
                url VARCHAR(500) UNIQUE,
                name VARCHAR(200),
                title VARCHAR(500),
                content LONGTEXT,
                status ENUM('pending', 'success', 'failed') DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        self.db_connection.commit()

    def _get_next_proxy(self):
        """获取下一个代理"""
        if not self.proxy_pool:
            return None
        proxy = self.proxy_pool[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxy_pool)
        return proxy

    def _save_to_database(self, data, url):
        """保存数据到数据库"""
        if not self.use_database or not self.db_connection:
            return

        try:
            cursor = self.db_connection.cursor()
            cursor.execute("""
                INSERT INTO crawl_data (url, name, title, content, status)
                VALUES (%s, %s, %s, %s, 'success')
                ON DUPLICATE KEY UPDATE
                name = VALUES(name), title = VALUES(title),
                content = VALUES(content), status = 'success'
            """, (url, data.get('name', ''), data.get('title', ''), json.dumps(data, ensure_ascii=False)))
            self.db_connection.commit()
        except Exception as e:
            print(f"数据库保存失败: {e}")

    def get_soup(self, url, use_playwright=False):
        """重写get_soup方法，支持代理池、重试机制和Playwright渲染"""
        if not url:
            return None

        if url in self.failed_urls:
            return None

        if 'zh.ifixit.com' in url:
            url = url.replace('zh.ifixit.com', 'www.ifixit.com')

        if '?' in url:
            url += '&lang=en'
        else:
            url += '?lang=en'

        # 如果需要JavaScript渲染，使用Playwright
        if use_playwright:
            return self._get_soup_with_playwright(url)

        # 否则使用传统的requests方法
        max_retries = 3
        for attempt in range(max_retries):
            try:
                session = requests.Session()
                retry_strategy = Retry(
                    total=3,
                    backoff_factor=1,
                    status_forcelist=[429, 500, 502, 503, 504],
                )
                adapter = HTTPAdapter(max_retries=retry_strategy)
                session.mount("http://", adapter)
                session.mount("https://", adapter)

                proxies = self._get_next_proxy() if self.use_proxy else None

                response = session.get(
                    url,
                    headers=self.headers,
                    timeout=30,
                    proxies=proxies
                )
                response.raise_for_status()

                from bs4 import BeautifulSoup
                return BeautifulSoup(response.content, 'html.parser')

            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"获取页面失败 {url}: {e}")
                    self.failed_urls.add(url)
                    return None
                time.sleep(random.uniform(1, 3))

        return None

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

    def extract_real_view_statistics(self, soup, url):
        """从页面HTML中提取真实的浏览统计数据"""
        if not soup:
            return {}

        stats = {}
        stat_selectors = [
            '.view-count', '.stats-item', '.view-stats', '[data-stats]', '.page-stats'
        ]

        for selector in stat_selectors:
            elements = soup.select(selector)
            for elem in elements:
                text = elem.get_text().strip()
                if 'past 24 hours' in text.lower() or '24h' in text.lower():
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

        if not stats:
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string:
                    script_content = script.string
                    if 'viewCount' in script_content or 'statistics' in script_content:
                        import re
                        view_matches = re.findall(r'"viewCount[^"]*":\s*"?(\d+[,\d]*)"?', script_content)
                        if view_matches:
                            stats['all_time'] = view_matches[0]

        return stats

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
            path_parts = [p for p in parsed.path.split('/') if p]

            # 添加新的路径段
            path_parts.append(segment)

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

        self.processed_nodes.add(url)

        time.sleep(random.uniform(0.5, 1.0))
        soup = self.get_soup(url)

        # 确保所有节点都经过fix_node_data处理
        node = self.fix_node_data(node, soup)

        if self.verbose:
            print(f"处理节点: {node.get('name', '')} - {url}")
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
        


    def count_detailed_nodes(self, node):
        """
        统计树中包含详细内容的节点数量
        """
        count = {'guides': 0, 'troubleshooting': 0, 'products': 0, 'categories': 0}

        if 'title' in node and 'steps' in node:
            count['guides'] += 1
        elif 'causes' in node:
            count['troubleshooting'] += 1
        elif 'product_name' in node:
            count['products'] += 1
        else:
            count['categories'] += 1

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

                    guides_data = []
                    troubleshooting_data = []

                    for guide_link in guide_links:
                        guide_content = self.extract_guide_content(guide_link)
                        if guide_content:
                            guide_content['url'] = guide_link
                            guides_data.append(guide_content)
                            print(f"    ✓ 指南: {guide_content.get('title', '')}")

                    if not skip_troubleshooting:
                        troubleshooting_links = self.extract_troubleshooting_from_device_page(soup, url)
                        print(f"  找到 {len(troubleshooting_links)} 个故障排除页面")

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
                                    print(f"    ✓ 故障排除: {ts_content.get('title', '')}")

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

                    if self.use_database:
                        self._save_to_database(node, url)

            except Exception as e:
                print(f"  ✗ 深入爬取时出错: {str(e)}")

        elif 'children' in node and node['children']:
            for i, child in enumerate(node['children']):
                node['children'][i] = self.deep_crawl_product_content(child, skip_troubleshooting)

        return node
        
    def save_combined_result(self, tree_data, filename=None, target_name=None):
        """保存整合结果到JSON文件或数据库"""
        if self.use_database:
            self._save_to_database(tree_data, tree_data.get('url', ''))
            print(f"\n整合结果已保存到数据库")
            return "database"

        os.makedirs("results", exist_ok=True)

        if not filename:
            if target_name:
                safe_name = target_name.replace("/", "_").replace("\\", "_").replace(":", "_")
                filename = f"results/auto_{safe_name}.json"
            else:
                root_name = tree_data.get("name", "auto")
                if " > " in root_name:
                    root_name = root_name.split(" > ")[-1]
                root_name = root_name.replace("/", "_").replace("\\", "_").replace(":", "_")
                filename = f"results/auto_{root_name}.json"

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(tree_data, f, ensure_ascii=False, indent=2)

        print(f"\n整合结果已保存到: {filename}")
        return filename
        
    def print_combined_tree_structure(self, node, level=0):
        """
        打印整合后的树形结构，显示节点类型和内容丰富程度
        """
        indent = "  " * level
        name = node.get('name', 'Unknown')
        
        # 判断节点类型并显示相应信息
        if 'title' in node and 'steps' in node:
            # 指南节点
            steps_count = len(node.get('steps', []))
            print(f"{indent}📖 {name} [指南 - {steps_count}步骤]")
        elif 'causes' in node:
            # 故障排除节点  
            causes_count = len(node.get('causes', []))
            print(f"{indent}🔧 {name} [故障排除 - {causes_count}原因]")
        elif 'product_name' in node:
            # 产品节点
            print(f"{indent}📱 {name} [产品]")
        elif 'children' in node and node['children']:
            # 分类节点
            children_count = len(node['children'])
            print(f"{indent}📁 {name} [分类 - {children_count}子项]")
        else:
            # 其他节点
            print(f"{indent}❓ {name} [未知类型]")
            
        # 递归打印子节点
        if 'children' in node and node['children']:
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
    print("使用方法:")
    print("python auto_crawler.py [URL或设备名] [verbose] [use_proxy] [use_database]")
    print("例如: python auto_crawler.py https://www.ifixit.com/Device/Television")
    print("      python auto_crawler.py Television verbose false false")
    print("      python auto_crawler.py --retry  # 重试失败的URL")

def main():
    # 检查是否提供了参数
    if len(sys.argv) > 1:
        input_text = sys.argv[1]

        # 检查帮助参数
        if input_text.lower() in ['--help', '-h', 'help']:
            print_usage()
            return

        verbose = len(sys.argv) > 2 and sys.argv[2].lower() in ('verbose', 'debug', 'true', '1')
        use_proxy = len(sys.argv) > 3 and sys.argv[3].lower() in ('true', '1', 'yes')
        use_database = len(sys.argv) > 4 and sys.argv[4].lower() in ('true', '1', 'yes')
    else:
        print("=" * 60)
        print("iFixit整合爬虫工具 - 树形结构 + 详细内容 + 企业级功能")
        print("=" * 60)
        print("\n请输入要爬取的iFixit产品名称或URL:")
        print("例如: 70UK6570PUB            - 指定产品型号")
        print("      https://www.ifixit.com/Device/70UK6570PUB - 指定产品URL")
        print("      Television             - 电视类别")
        print("      LG_Television          - 品牌电视类别")

        input_text = input("\n> ").strip()
        verbose = input("\n是否开启详细输出? (y/n): ").strip().lower() == 'y'
        use_proxy = input("是否使用代理池? (y/n): ").strip().lower() == 'y'
        use_database = input("是否使用MySQL存储? (y/n): ").strip().lower() == 'y'

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

        # 创建整合爬虫
        crawler = CombinedIFixitCrawler(verbose=verbose, use_proxy=use_proxy, use_database=use_database)

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

                print(f"\n✓ 整合爬取完成!")
                print(f"✓ 结果已保存到: {filename}")

                # 提供使用建议
                print(f"\n使用建议:")
                print(f"- 查看JSON文件了解完整的数据结构")
                print(f"- 树形结构保持了从根目录到目标的完整路径")
                print(f"- 每个节点都包含了相应的详细内容数据")

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

if __name__ == "__main__":
    main()
