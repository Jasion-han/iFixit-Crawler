import requests
from bs4 import BeautifulSoup
import json
import time
import random
import os
import re
from urllib.parse import urljoin, urlparse
from crawler import IFixitCrawler

class EnhancedIFixitCrawler(IFixitCrawler):
    def __init__(self, base_url="https://www.ifixit.com", verbose=False):
        super().__init__(base_url)
        self.guides_data = []  # 存储指南数据
        self.troubleshooting_data = []  # 存储故障排除数据
        self.troubleshooting_visited = set()  # 记录已访问的故障排除页面，避免重复
        self.processed_guides = set()  # 记录已处理的指南，避免重复
        self.verbose = verbose  # 控制详细输出

        # 强制使用英文，添加英文语言头
        self.headers.update({
            'Accept-Language': 'en-US,en;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def is_allowed_by_robots(self, url):
        """检查URL是否被robots.txt允许"""
        # 根据robots.txt规则检查
        disallowed_patterns = [
            '/api/',
            '/warenkorb', '/cart', '/carrito', '/panier', '/carrello',
            '/Warenkorb', '/Cart', '/Carrito', '/Panier', '/Carrello',
            '/Contribute/', '/Participate/',
            '/Store/Guide/', '/Tienda/Guide/', '/Boutique/Guide/',
            '/Team/Reports/',
            '/User/sso'
        ]

        for pattern in disallowed_patterns:
            if pattern in url:
                return False

        # 检查查询参数限制
        if '?filter' in url or '?q=' in url:
            if any(x in url for x in ['/Parts', '/Tools', '/Shop']):
                return False

        return True

    def is_commercial_content(self, element):
        """检查元素是否属于商业广告内容"""
        if not element:
            return False

        # 检查元素及其父元素的class和id
        current = element
        for _ in range(5):  # 向上检查5层父元素
            if not current:
                break

            # 检查class属性
            classes = current.get('class', [])
            if isinstance(classes, list):
                classes = ' '.join(classes).lower()
            else:
                classes = str(classes).lower()

            # 检查id属性
            element_id = current.get('id', '').lower()

            # 商业内容相关的关键词
            commercial_keywords = [
                'ad', 'ads', 'advertisement', 'promo', 'promotion', 'sponsor',
                'buy', 'purchase', 'cart', 'shop', 'store', 'product-box',
                'commercial', 'banner', 'sidebar', 'widget', 'affiliate',
                'price', 'review', 'rating', 'buy-now', 'add-to-cart'
            ]

            # 检查是否包含商业关键词
            for keyword in commercial_keywords:
                if keyword in classes or keyword in element_id:
                    return True

            # 检查是否是购买相关的链接
            if current.name == 'a':
                href = current.get('href', '').lower()
                if any(word in href for word in ['buy', 'cart', 'shop', 'store', 'purchase']):
                    return True

            current = current.parent

        return False

    def extract_product_info(self, soup, url, breadcrumb):
        """重写父类方法，确保产品信息为英文"""
        product_info = {
            "product_name": "",
            "product_url": url,
            "instruction_url": ""
        }

        try:
            # 提取产品名称（页面标题）- 确保英文
            title_selectors = [
                "div.device-title h1",
                "h1.device-title",
                "h1.title",
                "h1"
            ]

            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    # 清理产品名称，确保英文格式
                    product_name = title_elem.text.strip()

                    # 移除中文字符，保持英文内容
                    product_name = re.sub(r'[\u4e00-\u9fff]+', '', product_name)  # 移除中文字符

                    # 保持英寸符号为英文格式
                    product_name = product_name.replace('\\"', '"').replace('\\"', '"')
                    product_name = re.sub(r'\s+', ' ', product_name).strip()  # 处理多余空格

                    # 确保产品名称不为空且有意义
                    if product_name and len(product_name) > 3:
                        product_info["product_name"] = product_name
                        break

            # 如果没有找到合适的产品名称，尝试从URL中提取
            if not product_info["product_name"]:
                url_path = url.split("/")[-1].split("?")[0]  # 移除查询参数
                product_name = url_path.replace("_", " ").replace("-", " ")
                product_name = product_name.replace('%22', '"').replace('%E2%80%9D', '"')  # 保持英文引号
                product_name = re.sub(r'[\u4e00-\u9fff]+', '', product_name)  # 移除中文字符
                product_name = re.sub(r'\s+', ' ', product_name).strip()

                if product_name and len(product_name) > 3:
                    product_info["product_name"] = product_name
                else:
                    # 最后的备选方案
                    product_info["product_name"] = "Device Repair"

            # 确保产品名称以"Repair"结尾，如果还没有的话
            if not product_info["product_name"].endswith("Repair"):
                product_info["product_name"] += " Repair"

            # 简化版本：不提取instruction_url，专注于产品名称的英文化
            product_info["instruction_url"] = ""

        except Exception as e:
            print(f"Error extracting product info: {str(e)}")
            # 提供默认值
            if not product_info["product_name"]:
                product_info["product_name"] = "Device Repair"

        return product_info

    def ensure_english_url(self, url):
        """确保URL使用英文版本"""
        if '?' in url:
            if 'lang=' not in url:
                url += '&lang=en'
            else:
                # 替换现有的lang参数
                url = re.sub(r'lang=[^&]*', 'lang=en', url)
        else:
            url += '?lang=en'
        return url

    def extract_guide_content(self, guide_url):
        """提取指南页面的详细内容"""
        if not self.is_allowed_by_robots(guide_url):
            print(f"跳过被robots.txt禁止的URL: {guide_url}")
            return None

        if guide_url in self.processed_guides:
            print(f"Guide already processed, skipping: {guide_url}")
            return None

        # 确保使用英文版本
        guide_url = self.ensure_english_url(guide_url)
        self.processed_guides.add(guide_url)

        print(f"Crawling guide content: {guide_url}")

        # 添加延迟避免过快请求
        time.sleep(random.uniform(1, 2))

        soup = self.get_soup(guide_url)
        if not soup:
            return None

        guide_data = {
            "url": guide_url,
            "title": "",
            "introduction": "",
            "videos": [],
            "steps": []
        }

        try:
            # 提取指南标题 - 确保英文
            title_elem = soup.select_one("h1.guide-title, h1.title, h1")
            if title_elem:
                title_text = title_elem.get_text().strip()
                # 移除中文字符，保持英文内容
                title_text = re.sub(r'[\u4e00-\u9fff]+', '', title_text)
                title_text = re.sub(r'\s+', ' ', title_text).strip()
                guide_data["title"] = title_text

            # 提取介绍内容 - 精确提取，避免包含步骤内容
            intro_selectors = [
                ".guide-introduction",
                ".introduction",
                ".guide-summary",
                ".summary",
                ".guide-description",
                ".description",
                ".guide-intro",
                ".intro"
            ]

            # 方法1：尝试专门的介绍区域选择器
            for selector in intro_selectors:
                intro_elem = soup.select_one(selector)
                if intro_elem:
                    intro_text = intro_elem.get_text().strip()
                    # 清理多余的空白字符，但保留段落分隔
                    intro_text = re.sub(r'\n\s*\n', '\n\n', intro_text)
                    intro_text = re.sub(r'[ \t]+', ' ', intro_text)
                    if len(intro_text) > 20:
                        guide_data["introduction"] = intro_text
                        break

            # 方法2：查找页面中明确标识为简介的内容
            if not guide_data["introduction"]:
                # 查找包含"Introduction"或"简介"标题的区域 (英文优先)
                intro_headers = soup.find_all(string=lambda text: text and
                    any(word in text for word in ["Introduction", "Overview", "About", "简介"]))

                for header in intro_headers:
                    # 找到简介标题后，获取其后的内容
                    parent = header.parent
                    if parent:
                        intro_parts = []

                        # 方法2a：查找同级或下级的段落
                        next_elements = parent.find_next_siblings(['p', 'div'])
                        for elem in next_elements:
                            elem_text = elem.get_text().strip()
                            # 如果遇到步骤内容或其他标题，停止
                            if (any(stop_word in elem_text.lower() for stop_word in
                                   ['step 1', 'what you need', 'tools', 'parts']) or
                                elem.find(['h1', 'h2', 'h3', 'h4'])):
                                break
                            # 对于div元素，提取其中的所有段落
                            if elem.name == 'div':
                                # 查找div中的所有段落
                                paragraphs = elem.find_all('p')
                                if paragraphs:
                                    for p in paragraphs:
                                        p_text = p.get_text().strip()
                                        if (p_text and len(p_text) > 20 and
                                            not any(step_word in p_text.lower() for step_word in
                                                   ['step 1', 'step 2', 'remove the', 'install the', 'screw', 'phillips', 'following', '步骤'])):
                                            intro_parts.append(p_text)
                                else:
                                    # 如果div中没有p标签，直接取div的文本
                                    if (elem_text and len(elem_text) > 20 and
                                        not any(step_word in elem_text.lower() for step_word in
                                               ['step 1', 'step 2', 'remove the', 'install the', 'screw', 'phillips', 'following', '步骤'])):
                                        intro_parts.append(elem_text)
                            else:
                                # 对于p元素，直接提取文本
                                if (elem_text and len(elem_text) > 20 and
                                    not any(step_word in elem_text.lower() for step_word in
                                           ['step 1', 'step 2', 'remove the', 'install the', 'screw', 'phillips', 'following', '步骤'])):
                                    intro_parts.append(elem_text)

                        # 方法2b：如果没找到兄弟元素，查找父元素的下一个兄弟元素
                        if not intro_parts:
                            parent_next = parent.find_next_sibling()
                            while parent_next:
                                if parent_next.name in ['p', 'div']:
                                    elem_text = parent_next.get_text().strip()
                                    # 如果遇到步骤内容或其他标题，停止
                                    if (any(stop_word in elem_text.lower() for stop_word in
                                           ['step 1', 'what you need', 'tools', 'parts']) or
                                        parent_next.find(['h1', 'h2', 'h3', 'h4'])):
                                        break
                                    if (elem_text and len(elem_text) > 20 and
                                        not any(step_word in elem_text.lower() for step_word in
                                               ['step 1', 'step 2', 'remove the', 'install the', 'screw', 'phillips', 'following', '步骤'])):
                                        intro_parts.append(elem_text)
                                elif parent_next.name and parent_next.name.startswith('h'):
                                    break
                                parent_next = parent_next.find_next_sibling()

                        if intro_parts:
                            intro_text = '\n\n'.join(intro_parts)
                            intro_text = re.sub(r'[ \t]+', ' ', intro_text)
                            guide_data["introduction"] = intro_text
                            break

            # 方法3：查找页面开头的描述性段落，但要避免步骤内容
            if not guide_data["introduction"]:
                # 查找页面中的段落，但要过滤掉步骤相关内容
                all_paragraphs = soup.select("p")
                intro_parts = []

                for p in all_paragraphs[:15]:  # 检查前15个段落
                    p_text = p.get_text().strip()

                    # 如果遇到步骤内容，停止收集
                    if any(stop_word in p_text.lower() for stop_word in
                           ['step 1', 'what you need', 'tools', 'parts']):
                        break

                    # 检查是否是合适的简介内容 (英文关键词优先)
                    if (p_text and 30 <= len(p_text) <= 500 and  # 长度适中，增加上限
                        not any(skip_word in p_text.lower() for skip_word in [
                            'step 1', 'step 2', 'remove the', 'install the', 'screw', 'phillips',
                            'menu', 'navigation', 'login', 'register', 'cookie', 'privacy',
                            'following', 'securing', 'mm', 'torx',  # 常见步骤用词
                            '步骤'  # 中文步骤
                        ]) and
                        # 确保包含描述性词汇 (英文优先)
                        any(desc_word in p_text.lower() for desc_word in [
                            'guide', 'replace', 'repair', 'fix', 'problem', 'issue',
                            'help', 'show', 'how to', 'this will', 'use this', 'tutorial',
                            'connectivity', 'airport', 'wireless', 'display frame'
                        ])):

                        intro_text = re.sub(r'[ \t]+', ' ', p_text)
                        intro_parts.append(intro_text)

                        # 如果已经收集到足够的内容，继续查找相关段落
                        if len(intro_parts) >= 2:
                            break

                if intro_parts:
                    guide_data["introduction"] = '\n\n'.join(intro_parts)

            # 提取步骤
            steps = soup.select(".guide-step, .step")
            processed_steps = set()  # 用于去重

            for step in steps:
                step_data = {
                    "title": "",
                    "content": "",
                    "images": [],
                    "videos": []
                }

                # 步骤标题 - 清理格式，确保英文
                step_title = step.select_one(".step-title, h3, h4")
                if step_title:
                    title_text = step_title.get_text().strip()
                    # 移除中文字符
                    title_text = re.sub(r'[\u4e00-\u9fff]+', '', title_text)
                    # 清理多余的空白字符和换行符
                    title_text = re.sub(r'\s+', ' ', title_text).strip()
                    step_data["title"] = title_text

                # 步骤内容 - 清理格式，确保英文，支持自适应换行
                step_content = step.select_one(".step-content, .step-text")
                if step_content:
                    content_text = step_content.get_text().strip()
                    # 移除中文字符
                    content_text = re.sub(r'[\u4e00-\u9fff]+', '', content_text)
                    # 保留句子间的换行，但清理多余的空白字符
                    content_text = re.sub(r'\n\s*\n', '\n', content_text)  # 合并多个换行为单个
                    content_text = re.sub(r'[ \t]+', ' ', content_text)  # 清理空格和制表符
                    content_text = content_text.strip()
                    step_data["content"] = content_text

                # 创建步骤唯一标识符用于去重
                step_identifier = f"{step_data['title']}_{step_data['content'][:50]}"
                if step_identifier in processed_steps:
                    continue  # 跳过重复步骤
                processed_steps.add(step_identifier)

                # 步骤图片 - 只保留medium格式，去重
                step_images = step.select("img")
                seen_images = set()
                for img in step_images:
                    img_src = img.get("src") or img.get("data-src")
                    if img_src:
                        if img_src.startswith("//"):
                            img_src = "https:" + img_src
                        elif img_src.startswith("/"):
                            img_src = self.base_url + img_src

                        # 只保留medium格式的图片，去除其他格式
                        if ".medium" in img_src:
                            # 提取基础URL用于去重
                            base_img_url = img_src.split('.medium')[0]
                            if base_img_url not in seen_images:
                                seen_images.add(base_img_url)
                                step_data["images"].append(img_src)
                        elif not any(suffix in img_src for suffix in [".200x150", ".standard", ".large", ".small"]):
                            # 如果没有格式后缀，也包含进来
                            if img_src not in seen_images:
                                seen_images.add(img_src)
                                step_data["images"].append(img_src)

                # 步骤中的视频 - 去重
                step_videos = step.select("[videoid], .video")
                seen_videos = set()
                for video in step_videos:
                    video_id = video.get("videoid")
                    if video_id and video_id not in seen_videos:
                        seen_videos.add(video_id)
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        step_data["videos"].append(video_url)

                # 只添加有内容的步骤
                if step_data["title"] or step_data["content"] or step_data["images"]:
                    guide_data["steps"].append(step_data)



            # 提取视频 - 去重
            videos = self.extract_youtube_videos(soup, guide_url)
            seen_video_urls = set()
            for video in videos:
                video_url = video.get("url", "")
                if video_url and video_url not in seen_video_urls:
                    seen_video_urls.add(video_url)
                    guide_data["videos"].append(video)

            # 提取时间和难度信息
            time_difficulty = self.extract_time_and_difficulty(soup, guide_url)

            # 提取What you need部分
            what_you_need = self.extract_what_you_need(soup, guide_url)

            # 提取统计数据
            statistics = self.extract_page_statistics(soup)

            # 重构统计数据结构 - 将统计数据插入到introduction之后
            # 重新构建guide_data，确保字段顺序正确
            ordered_guide_data = {}
            ordered_guide_data["url"] = guide_data["url"]
            ordered_guide_data["title"] = guide_data["title"]

            # 添加时间和难度字段（如果存在）
            if time_difficulty.get("time_required"):
                ordered_guide_data["time_required"] = time_difficulty["time_required"]
            if time_difficulty.get("difficulty"):
                ordered_guide_data["difficulty"] = time_difficulty["difficulty"]

            ordered_guide_data["introduction"] = guide_data["introduction"]

            # 添加What you need部分（如果有的话）
            if what_you_need:
                ordered_guide_data["what_you_need"] = what_you_need

            # 将统计数据插入到introduction之后（如果有的话）
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
                    ordered_guide_data["view_statistics"] = view_stats
                if 'completed' in statistics:
                    ordered_guide_data["completed"] = statistics['completed']
                if 'favorites' in statistics:
                    ordered_guide_data["favorites"] = statistics['favorites']

            # 添加其他字段
            if "videos" in guide_data:
                ordered_guide_data["videos"] = guide_data["videos"]
            if "steps" in guide_data:
                ordered_guide_data["steps"] = guide_data["steps"]

            guide_data = ordered_guide_data

            return guide_data

        except Exception as e:
            print(f"提取指南内容时发生错误: {str(e)}")
            return None

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

    def extract_what_you_need(self, soup, guide_url=None):
        """提取指南页面的'What you need'部分内容，支持动态内容"""
        what_you_need = {}

        try:
            # 如果内容是动态加载的，尝试使用Playwright获取完整页面
            if guide_url:
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
                        page.goto(guide_url, wait_until='networkidle')

                        # 等待一下确保动态内容加载完成
                        page.wait_for_timeout(3000)

                        # 获取页面HTML
                        html_content = page.content()
                        browser.close()

                        # 重新解析HTML
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html_content, 'html.parser')

                except Exception as e:
                    if self.verbose:
                        print(f"使用Playwright获取页面失败，使用原始soup: {str(e)}")

            # 查找"What you need"部分的标题
            what_you_need_keywords = [
                "What you need", "what you need", "WHAT YOU NEED",
                "你所需要的", "所需工具", "需要的工具", "Tools and Parts"
            ]

            what_you_need_section = None

            # 方法1：通过标题文本查找
            for keyword in what_you_need_keywords:
                headers = soup.find_all(string=lambda text: text and keyword in text)
                for header in headers:
                    parent = header.parent
                    if parent and parent.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                        # 找到标题后，查找其父容器
                        container = parent.parent
                        if container:
                            what_you_need_section = container
                            break
                if what_you_need_section:
                    break

            # 方法2：通过常见的CSS类名查找
            if not what_you_need_section:
                selectors = [
                    ".what-you-need", ".tools-parts", ".requirements",
                    ".guide-requirements", ".needed-items"
                ]
                for selector in selectors:
                    section = soup.select_one(selector)
                    if section:
                        what_you_need_section = section
                        break

            if not what_you_need_section:
                return what_you_need

            # 在找到的区域内查找分类和产品
            # 查找所有可能的分类标题
            category_keywords = [
                'Tools', 'Parts', 'Fix Kit', 'Kit', 'Components', 'Fix Kits',
                '工具', '配件', '零件', '套件', '修复工具包'
            ]

            category_elements = []
            for keyword in category_keywords:
                elements = what_you_need_section.find_all(['h2', 'h3', 'h4', 'h5', 'p'],
                                                         string=lambda text: text and keyword in text.strip())
                category_elements.extend(elements)

            # 如果没有找到明确的分类，查找所有段落和标题
            if not category_elements:
                category_elements = what_you_need_section.find_all(['p', 'h2', 'h3', 'h4', 'h5'])

            processed_categories = set()  # 避免重复处理相同的分类

            for category_elem in category_elements:
                category_text = category_elem.get_text().strip()

                # 跳过太短或无意义的文本
                if len(category_text) < 2 or category_text.lower() in ['view', 'more', '更多', 'see', 'all']:
                    continue

                # 确定分类名称
                category_name = category_text

                # 避免重复处理相同的分类
                if category_name in processed_categories:
                    continue
                processed_categories.add(category_name)

                # 查找该分类下的产品列表
                items = []

                # 方法1：查找分类元素后面的列表项
                next_element = category_elem.find_next_sibling()
                while next_element and len(items) < 20:  # 限制最多20个产品
                    if next_element.name == 'ul' or next_element.name == 'list':
                        # 找到列表，提取产品链接
                        product_links = next_element.find_all('a', href=lambda x: x and '/products/' in x)
                        for link in product_links:
                            item_text = link.get_text().strip()
                            # 清理产品名称
                            item_text = self.clean_product_name(item_text)
                            if item_text and len(item_text) > 2 and item_text not in items:
                                items.append(item_text)
                        break
                    elif next_element.name in ['h2', 'h3', 'h4', 'h5', 'p'] and any(
                        cat in next_element.get_text() for cat in category_keywords
                    ):
                        # 遇到下一个分类，停止
                        break
                    next_element = next_element.find_next_sibling()

                # 方法2：在分类元素的父容器中查找产品
                if not items:
                    # 查找分类元素后面的兄弟元素中的产品
                    current = category_elem
                    for _ in range(10):  # 最多查找10个兄弟元素
                        current = current.find_next_sibling()
                        if not current:
                            break

                        # 如果遇到下一个分类标题，停止
                        if current.name in ['h2', 'h3', 'h4', 'h5', 'p'] and any(
                            cat in current.get_text() for cat in category_keywords
                        ):
                            break

                        # 查找当前元素中的产品链接
                        product_links = current.find_all('a', href=lambda x: x and '/products/' in x)
                        for link in product_links:
                            item_text = link.get_text().strip()
                            item_text = self.clean_product_name(item_text)
                            if item_text and len(item_text) > 2 and item_text not in items:
                                items.append(item_text)

                # 如果找到了产品，添加到结果中
                if items:
                    what_you_need[category_name] = items

            # 如果没有找到分类，尝试直接提取所有产品
            if not what_you_need:
                all_product_links = what_you_need_section.find_all('a', href=lambda x: x and '/products/' in x)
                if all_product_links:
                    items = []
                    for link in all_product_links:
                        item_text = link.get_text().strip()
                        # 清理产品名称
                        item_text = re.sub(r'\$[\d.,]+.*$', '', item_text).strip()
                        item_text = re.sub(r'[\d.]+\s*out of.*$', '', item_text).strip()
                        item_text = re.sub(r'Sale price.*$', '', item_text).strip()
                        if item_text and len(item_text) > 2:
                            items.append(item_text)

                    if items:
                        # 去重
                        items = list(dict.fromkeys(items))
                        what_you_need["Items"] = items

        except Exception as e:
            if self.verbose:
                print(f"提取What you need部分时发生错误: {str(e)}")

        return what_you_need

    def extract_time_and_difficulty(self, soup, guide_url=None):
        """从页面中提取真实的时间和难度信息"""
        time_difficulty = {}

        try:
            # 方法1：使用iFixit API获取准确的数据
            if guide_url:
                # 从URL中提取guide ID
                guide_id_match = re.search(r'/Guide/[^/]+/(\d+)', guide_url)
                if guide_id_match:
                    guide_id = guide_id_match.group(1)
                    api_url = f"https://www.ifixit.com/api/2.0/guides/{guide_id}"

                    try:
                        import requests
                        response = requests.get(api_url, headers=self.headers, timeout=10)
                        if response.status_code == 200:
                            api_data = response.json()

                            # 从API数据中提取难度信息
                            if 'difficulty' in api_data:
                                difficulty = api_data['difficulty']
                                time_difficulty["difficulty"] = self.standardize_difficulty(difficulty)

                            # 从API数据中提取时间信息
                            time_fields = ['time_required', 'duration', 'time', 'estimate']
                            for field in time_fields:
                                if field in api_data and api_data[field]:
                                    time_difficulty["time_required"] = api_data[field]
                                    break

                            # 如果API中没有时间信息，查找其他可能的字段
                            if not time_difficulty.get("time_required"):
                                # 查找可能包含时间信息的字段
                                for key, value in api_data.items():
                                    if isinstance(value, str) and re.search(r'\d+\s*[-–]\s*\d+\s*(?:minutes?|hours?)', value, re.IGNORECASE):
                                        time_difficulty["time_required"] = value
                                        break

                            if self.verbose:
                                print(f"从API获取到时间和难度信息: {time_difficulty}")
                            if time_difficulty:
                                return time_difficulty

                    except Exception as e:
                        print(f"API调用失败: {str(e)}")

            # 方法2：查找页面中的JavaScript数据（备用方法）
            # 时间和难度信息可能在页面的JavaScript变量中
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    script_content = script.string

                    # 查找时间信息的JSON数据
                    time_patterns = [
                        r'"time_required"\s*:\s*"([^"]+)"',
                        r'"duration"\s*:\s*"([^"]+)"',
                        r'"timeRequired"\s*:\s*"([^"]+)"',
                        r'timeRequired["\']?\s*:\s*["\']([^"\']+)["\']',
                        r'time["\']?\s*:\s*["\']([^"\']*(?:\d+\s*[-–]\s*\d+|\d+)\s*(?:minutes?|hours?)[^"\']*)["\']'
                    ]

                    for pattern in time_patterns:
                        match = re.search(pattern, script_content, re.IGNORECASE)
                        if match:
                            time_difficulty["time_required"] = match.group(1).strip()
                            break

                    # 查找难度信息的JSON数据
                    difficulty_patterns = [
                        r'"difficulty"\s*:\s*"([^"]+)"',
                        r'"level"\s*:\s*"([^"]+)"',
                        r'difficulty["\']?\s*:\s*["\']([^"\']+)["\']',
                        r'level["\']?\s*:\s*["\']([^"\']*(?:Very\s+easy|Easy|Moderate|Difficult|Hard)[^"\']*)["\']'
                    ]

                    for pattern in difficulty_patterns:
                        match = re.search(pattern, script_content, re.IGNORECASE)
                        if match:
                            difficulty = match.group(1).strip()
                            time_difficulty["difficulty"] = self.standardize_difficulty(difficulty)
                            break

                    # 如果两个都找到了，就停止搜索
                    if time_difficulty.get("time_required") and time_difficulty.get("difficulty"):
                        break

            # 方法2：查找页面中的特定HTML结构
            # 基于iFixit页面的实际结构查找时间和难度信息
            if not time_difficulty:
                # 查找可能包含时间信息的元素（基于常见的HTML结构）
                time_selectors = [
                    'span[title*="minute"]',
                    'span[title*="hour"]',
                    'div[title*="minute"]',
                    'div[title*="hour"]',
                    '.time',
                    '.duration',
                    '.estimate'
                ]

                for selector in time_selectors:
                    time_elem = soup.select_one(selector)
                    if time_elem:
                        time_text = time_elem.get_text().strip()
                        if re.search(r'\d+\s*[-–]\s*\d+\s*(?:minutes?|hours?)', time_text, re.IGNORECASE):
                            time_difficulty["time_required"] = time_text
                            break
                        # 也检查title属性
                        title = time_elem.get('title', '')
                        if re.search(r'\d+\s*[-–]\s*\d+\s*(?:minutes?|hours?)', title, re.IGNORECASE):
                            time_difficulty["time_required"] = title
                            break

                # 查找可能包含难度信息的元素
                difficulty_selectors = [
                    'span[title*="easy"]',
                    'span[title*="moderate"]',
                    'span[title*="difficult"]',
                    'div[title*="easy"]',
                    'div[title*="moderate"]',
                    'div[title*="difficult"]',
                    '.difficulty',
                    '.level'
                ]

                for selector in difficulty_selectors:
                    diff_elem = soup.select_one(selector)
                    if diff_elem:
                        diff_text = diff_elem.get_text().strip()
                        if re.search(r'(?:Very\s+easy|Easy|Moderate|Difficult|Hard)', diff_text, re.IGNORECASE):
                            time_difficulty["difficulty"] = self.standardize_difficulty(diff_text)
                            break
                        # 也检查title属性
                        title = diff_elem.get('title', '')
                        if re.search(r'(?:Very\s+easy|Easy|Moderate|Difficult|Hard)', title, re.IGNORECASE):
                            time_difficulty["difficulty"] = self.standardize_difficulty(title)
                            break

            # 方法3：查找页面中的时间和难度信息框
            # 通常在页面顶部的信息区域
            if not time_difficulty:
                info_selectors = [
                    ".guide-info",
                    ".guide-meta",
                    ".guide-header",
                    ".guide-stats",
                    ".guide-difficulty",
                    ".guide-time",
                    ".meta-info",
                    ".difficulty-time",
                    ".guide-details",
                    ".guide-metadata",
                    ".metadata",
                    ".stats"
                ]

                for selector in info_selectors:
                    info_section = soup.select_one(selector)
                    if info_section:
                        # 在信息区域中查找时间和难度
                        time_diff = self.parse_time_difficulty_from_section(info_section)
                        if time_diff:
                            time_difficulty.update(time_diff)
                            break

            # 方法2：如果没有找到专门的信息区域，在整个页面中搜索
            if not time_difficulty:
                page_text = soup.get_text()

                # 查找包含时间信息的元素 - 改进的模式，包含完整的时间表达
                time_patterns = [
                    r'(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?))',  # 分钟
                    r'(\d+\s*(?:-\s*\d+)?\s*(?:hours?|hrs?))',     # 小时
                    r'(\d+\s*hours?)',                             # 简单小时
                    r'(\d+\s*minutes?)',                           # 简单分钟
                    r'(No\s+estimate)',                            # 无估计
                    r'(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))', # 通用模式
                ]

                # 查找难度信息 - 改进的模式
                difficulty_patterns = [
                    r'(Very\s+easy|Easy|Moderate|Difficult|Hard)',
                    r'(很简单|简单|中等|困难|很困难)'
                ]

                # 提取时间信息
                for pattern in time_patterns:
                    match = re.search(pattern, page_text, re.IGNORECASE)
                    if match:
                        time_text = match.group(1).strip()
                        # 确保时间信息包含单位
                        if not re.search(r'(?:minutes?|mins?|hours?|hrs?|estimate)', time_text, re.IGNORECASE):
                            # 如果没有单位，尝试从上下文中推断
                            context_match = re.search(rf'{re.escape(time_text)}\s*(minutes?|mins?|hours?|hrs?)', page_text, re.IGNORECASE)
                            if context_match:
                                time_text += " " + context_match.group(1)
                            else:
                                # 默认假设是小时（基于观察到的数据）
                                time_text += " Hours"
                        time_difficulty["time_required"] = time_text
                        break

                # 提取难度信息
                for pattern in difficulty_patterns:
                    match = re.search(pattern, page_text, re.IGNORECASE)
                    if match:
                        difficulty = match.group(1).strip()
                        # 标准化难度值为英文
                        difficulty_mapping = {
                            "很简单": "Very easy",
                            "简单": "Easy",
                            "中等": "Moderate",
                            "困难": "Difficult",
                            "很困难": "Very difficult"
                        }
                        mapped_difficulty = difficulty_mapping.get(difficulty, difficulty)
                        time_difficulty["difficulty"] = self.standardize_difficulty(mapped_difficulty)
                        break

            # 方法3：查找特定的HTML结构（基于实际页面结构）
            if not time_difficulty:
                # 查找可能包含时间和难度的span或div元素
                time_elements = soup.find_all(['span', 'div'], string=re.compile(r'\d+\s*(?:minutes?|hours?)', re.IGNORECASE))
                for elem in time_elements:
                    text = elem.get_text().strip()
                    if re.search(r'\d+\s*(?:minutes?|hours?)', text, re.IGNORECASE):
                        time_difficulty["time_required"] = text
                        break

                difficulty_elements = soup.find_all(['span', 'div'], string=re.compile(r'(?:Very\s+easy|Easy|Moderate|Difficult|Hard)', re.IGNORECASE))
                for elem in difficulty_elements:
                    text = elem.get_text().strip()
                    if re.search(r'(?:Very\s+easy|Easy|Moderate|Difficult|Hard)', text, re.IGNORECASE):
                        time_difficulty["difficulty"] = self.standardize_difficulty(text)
                        break

            # 方法5：查找页面中的特定CSS类或属性（基于iFixit页面结构）
            if not time_difficulty:
                # 查找可能的时间和难度容器
                meta_containers = soup.find_all(['div', 'section', 'span'], class_=re.compile(r'guide|meta|info|stats|difficulty|time', re.IGNORECASE))
                for container in meta_containers:
                    container_text = container.get_text()

                    # 在容器中查找时间信息
                    if not time_difficulty.get("time_required"):
                        time_match = re.search(r'(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))', container_text, re.IGNORECASE)
                        if time_match:
                            time_difficulty["time_required"] = time_match.group(1).strip()

                    # 在容器中查找难度信息
                    if not time_difficulty.get("difficulty"):
                        diff_match = re.search(r'(Very\s+easy|Easy|Moderate|Difficult|Hard)', container_text, re.IGNORECASE)
                        if diff_match:
                            difficulty = diff_match.group(1).strip()
                            time_difficulty["difficulty"] = self.standardize_difficulty(difficulty)

                    # 如果两个都找到了，就停止搜索
                    if time_difficulty.get("time_required") and time_difficulty.get("difficulty"):
                        break

            # 方法4：查找页面中的图标或标签附近的文本
            if not time_difficulty:
                # 查找时钟图标或时间相关的类名附近的文本
                time_icons = soup.find_all(['i', 'span', 'div'], class_=re.compile(r'time|clock|duration', re.IGNORECASE))
                for icon in time_icons:
                    parent = icon.parent
                    if parent:
                        parent_text = parent.get_text().strip()
                        time_match = re.search(r'(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))', parent_text, re.IGNORECASE)
                        if time_match:
                            time_difficulty["time_required"] = time_match.group(1).strip()
                            break

                # 查找难度图标或难度相关的类名附近的文本
                difficulty_icons = soup.find_all(['i', 'span', 'div'], class_=re.compile(r'difficulty|level', re.IGNORECASE))
                for icon in difficulty_icons:
                    parent = icon.parent
                    if parent:
                        parent_text = parent.get_text().strip()
                        diff_match = re.search(r'(Very\s+easy|Easy|Moderate|Difficult|Hard)', parent_text, re.IGNORECASE)
                        if diff_match:
                            difficulty = diff_match.group(1).strip()
                            time_difficulty["difficulty"] = self.standardize_difficulty(difficulty)
                            break

            # 方法6：查找页面头部区域的时间和难度信息（基于用户图片显示的位置）
            if not time_difficulty:
                # 查找页面头部的信息区域
                header_areas = soup.find_all(['header', 'div'], class_=re.compile(r'header|top|intro|guide-header', re.IGNORECASE))
                for header in header_areas:
                    header_text = header.get_text()

                    # 在头部区域查找时间信息
                    if not time_difficulty.get("time_required"):
                        time_match = re.search(r'(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))', header_text, re.IGNORECASE)
                        if time_match:
                            time_difficulty["time_required"] = time_match.group(1).strip()

                    # 在头部区域查找难度信息
                    if not time_difficulty.get("difficulty"):
                        diff_match = re.search(r'(Very\s+easy|Easy|Moderate|Difficult|Hard)', header_text, re.IGNORECASE)
                        if diff_match:
                            difficulty = diff_match.group(1).strip()
                            time_difficulty["difficulty"] = self.standardize_difficulty(difficulty)

                # 如果头部区域没有找到，查找页面中所有包含这些信息的文本节点
                if not time_difficulty.get("time_required") or not time_difficulty.get("difficulty"):
                    # 查找所有文本节点
                    all_text_elements = soup.find_all(string=True)
                    for text_node in all_text_elements:
                        text = str(text_node).strip()

                        # 查找时间信息
                        if not time_difficulty.get("time_required"):
                            time_match = re.search(r'(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))', text, re.IGNORECASE)
                            if time_match:
                                time_difficulty["time_required"] = time_match.group(1).strip()

                        # 查找难度信息
                        if not time_difficulty.get("difficulty"):
                            diff_match = re.search(r'(Very\s+easy|Easy|Moderate|Difficult|Hard)', text, re.IGNORECASE)
                            if diff_match:
                                difficulty = diff_match.group(1).strip()
                                # 标准化难度值格式
                                time_difficulty["difficulty"] = self.standardize_difficulty(difficulty)

                        # 如果两个都找到了，就停止搜索
                        if time_difficulty.get("time_required") and time_difficulty.get("difficulty"):
                            break

            print(f"提取到时间和难度信息: {time_difficulty}")
            return time_difficulty

        except Exception as e:
            print(f"提取时间和难度信息时发生错误: {str(e)}")
            return {}

    def standardize_difficulty(self, difficulty):
        """标准化难度值格式"""
        if not difficulty:
            return difficulty

        # 转换为标准格式
        difficulty_lower = difficulty.lower().strip()

        if difficulty_lower in ['very easy', 'very_easy']:
            return "Very easy"
        elif difficulty_lower == 'easy':
            return "Easy"
        elif difficulty_lower in ['moderate', 'medium']:
            return "Moderate"
        elif difficulty_lower in ['difficult', 'hard']:
            return "Difficult"
        elif difficulty_lower in ['very difficult', 'very hard', 'very_difficult', 'very_hard']:
            return "Very difficult"
        else:
            # 如果不匹配已知模式，返回首字母大写的版本
            return difficulty.capitalize()

    def parse_time_difficulty_from_section(self, section):
        """从特定区域解析时间和难度信息"""
        result = {}

        try:
            section_text = section.get_text()

            # 提取时间信息 - 改进的模式
            time_patterns = [
                r'(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?))',  # 分钟
                r'(\d+\s*(?:-\s*\d+)?\s*(?:hours?|hrs?))',     # 小时
                r'(\d+\s*hours?)',                             # 简单小时
                r'(\d+\s*minutes?)',                           # 简单分钟
                r'(No\s+estimate)',                            # 无估计
                r'(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))', # 通用模式
            ]

            for pattern in time_patterns:
                match = re.search(pattern, section_text, re.IGNORECASE)
                if match:
                    time_text = match.group(1).strip()
                    # 确保时间信息包含单位
                    if not re.search(r'(?:minutes?|mins?|hours?|hrs?|estimate)', time_text, re.IGNORECASE):
                        # 如果没有单位，尝试从上下文中推断
                        context_match = re.search(rf'{re.escape(time_text)}\s*(minutes?|mins?|hours?|hrs?)', section_text, re.IGNORECASE)
                        if context_match:
                            time_text += " " + context_match.group(1)
                        else:
                            # 默认假设是小时（基于观察到的数据）
                            time_text += " Hours"
                    result["time_required"] = time_text
                    break

            # 提取难度信息
            difficulty_patterns = [
                r'(Very\s+easy|Easy|Moderate|Difficult|Hard)',
                r'(很简单|简单|中等|困难|很困难)'
            ]

            for pattern in difficulty_patterns:
                match = re.search(pattern, section_text, re.IGNORECASE)
                if match:
                    difficulty = match.group(1).strip()
                    # 标准化难度值为英文
                    difficulty_mapping = {
                        "很简单": "Very easy",
                        "简单": "Easy",
                        "中等": "Moderate",
                        "困难": "Difficult",
                        "很困难": "Very difficult"
                    }
                    mapped_difficulty = difficulty_mapping.get(difficulty, difficulty)
                    result["difficulty"] = self.standardize_difficulty(mapped_difficulty)
                    break

            return result

        except Exception as e:
            print(f"解析区域时间和难度信息时发生错误: {str(e)}")
            return {}

    def extract_page_statistics(self, soup):
        """提取页面统计数据 - 支持guide和troubleshooting页面"""
        statistics = {}

        try:
            import re

            # 方法1：提取guide页面的statValue数据
            stat_values = soup.find_all('span', class_='statValue')
            for stat in stat_values:
                if not stat.parent:
                    continue

                parent_text = stat.parent.get_text().strip()
                value = stat.get_text().strip()

                if 'Past 24 Hours' in parent_text:
                    statistics['past_24_hours'] = value
                elif 'Past 7 Days' in parent_text:
                    statistics['past_7_days'] = value
                elif 'Past 30 Days' in parent_text:
                    statistics['past_30_days'] = value
                elif 'All Time' in parent_text:
                    statistics['all_time'] = value

            # 方法2：如果没有找到statValue，尝试从整个页面文本中提取统计数据
            if not statistics:
                # 获取整个页面的文本内容
                full_text = soup.get_text()

                # 使用正则表达式提取统计数据
                past_24_match = re.search(r'Past 24 Hours:\s*(\d+(?:,\d+)*)', full_text)
                past_7_match = re.search(r'Past 7 Days:\s*(\d+(?:,\d+)*)', full_text)
                past_30_match = re.search(r'Past 30 Days:\s*(\d+(?:,\d+)*)', full_text)
                all_time_match = re.search(r'All Time:\s*(\d+(?:,\d+)*)', full_text)

                if past_24_match:
                    statistics['past_24_hours'] = past_24_match.group(1)
                if past_7_match:
                    statistics['past_7_days'] = past_7_match.group(1)
                if past_30_match:
                    statistics['past_30_days'] = past_30_match.group(1)
                if all_time_match:
                    statistics['all_time'] = all_time_match.group(1)

            # 提取完成数
            completed_text = soup.find(string=lambda text: text and 'completed this guide' in text)
            if completed_text:
                numbers = re.findall(r'(\d+)', completed_text)
                if numbers:
                    statistics['completed'] = numbers[0]

            # 如果没有找到完成数，尝试其他方式
            if 'completed' not in statistics:
                # 查找可能的完成数文本模式
                for text in soup.find_all(string=lambda t: t and 'people completed' in t):
                    numbers = re.findall(r'(\d+)', text)
                    if numbers:
                        statistics['completed'] = numbers[0]
                        break

            # 提取收藏数 - 从页面的JavaScript数据中提取
            try:
                # 获取页面的原始HTML内容
                page_content = str(soup)

                # 查找favoriteCount
                favorite_match = re.search(r'"favoriteCount"\s*:\s*(\d+)', page_content)
                if favorite_match:
                    statistics['favorites'] = favorite_match.group(1)
                else:
                    # 尝试其他可能的模式
                    favorite_patterns = [
                        r'favoriteCount[^\d]*(\d+)',
                        r'"favorites?"\s*:\s*(\d+)',
                        r'favorites?[^\d]*(\d+)'
                    ]
                    for pattern in favorite_patterns:
                        match = re.search(pattern, page_content, re.IGNORECASE)
                        if match:
                            statistics['favorites'] = match.group(1)
                            break
            except Exception as e:
                print(f"提取收藏数时发生错误: {str(e)}")

            return statistics

        except Exception as e:
            print(f"提取统计数据时发生错误: {str(e)}")
            return {}

    def extract_troubleshooting_content(self, troubleshooting_url):
        """提取故障排除页面的详细内容 - 基于真实页面结构分析"""
        if not self.is_allowed_by_robots(troubleshooting_url):
            print(f"跳过被robots.txt禁止的URL: {troubleshooting_url}")
            return None

        if troubleshooting_url in self.troubleshooting_visited:
            print(f"Troubleshooting page already processed, skipping: {troubleshooting_url}")
            return None

        # 确保使用英文版本
        troubleshooting_url = self.ensure_english_url(troubleshooting_url)
        self.troubleshooting_visited.add(troubleshooting_url)

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

            # 动态提取页面上的真实字段内容
            dynamic_sections = self.extract_dynamic_sections(soup)
            troubleshooting_data.update(dynamic_sections)

            # 提取causes并为每个cause提取对应的图片和视频
            troubleshooting_data["causes"] = self.extract_causes_sections_with_media(soup)

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
                            images = self.extract_images_from_section(content_section)
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

    def extract_images_from_section(self, section):
        """从特定section中提取图片 - 使用精确边界检测"""
        images = []
        seen_urls = set()

        try:
            if not section:
                return images

            if self.verbose:
                print(f"开始从section提取图片，section ID: {section.get('id', 'unknown')}")

            # 创建section副本并移除推广内容
            from bs4 import BeautifulSoup
            section_copy = BeautifulSoup(str(section), 'html.parser')
            self.remove_promotional_content_from_section(section_copy)

            # 查找该section内的所有图片
            img_elements = section_copy.find_all('img')
            if self.verbose:
                print(f"移除推广内容后找到 {len(img_elements)} 个图片元素")

            for img in img_elements:
                # 再次检查是否在推广区域（双重保险）
                if self.is_element_in_promotional_area(img):
                    continue

                src = img.get('src', '') or img.get('data-src', '')
                if src and src not in seen_urls:
                    # 过滤掉小图标、logo
                    if any(skip in src.lower() for skip in [
                        'icon', 'logo', 'flag', 'avatar', 'ad', 'banner',
                        'header', 'footer', 'nav', 'menu', 'sidebar'
                    ]):
                        continue

                    # 确保是完整URL
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = 'https://www.ifixit.com' + src

                    # 获取图片描述
                    alt_text = img.get('alt', '').strip()
                    title_text = img.get('title', '').strip()
                    description = alt_text or title_text or ""

                    # 检查描述是否是商业内容
                    if not self.is_commercial_text(description):
                        images.append({
                            "url": src,
                            "description": description
                        })
                        seen_urls.add(src)

            if self.verbose:
                print(f"最终提取到 {len(images)} 个有效图片")
            return images
        except Exception as e:
            print(f"从section提取图片时发生错误: {str(e)}")
            return []

    def extract_videos_from_section(self, section):
        """从特定section中提取视频 - 使用精确边界检测"""
        videos = []
        seen_urls = set()

        try:
            if not section:
                return videos

            if self.verbose:
                print(f"开始从section提取视频，section ID: {section.get('id', 'unknown')}")

            # 创建section副本并移除推广内容
            from bs4 import BeautifulSoup
            section_copy = BeautifulSoup(str(section), 'html.parser')
            self.remove_promotional_content_from_section(section_copy)

            # 查找该section内的视频元素
            video_elements = section_copy.find_all(['video', 'iframe', 'embed'])
            links = section_copy.find_all('a', href=True)

            if self.verbose:
                print(f"移除推广内容后找到 {len(video_elements)} 个视频元素和 {len(links)} 个链接")

            # 处理视频元素
            for elem in video_elements:
                # 再次检查是否在推广区域（双重保险）
                if self.is_element_in_promotional_area(elem):
                    continue

                src = elem.get('src', '') or elem.get('data-src', '')
                if src and src not in seen_urls and self.is_valid_video_url(src):
                    # 确保是完整URL
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = 'https://www.ifixit.com' + src

                    # 获取视频描述
                    title = elem.get('title', '').strip()

                    videos.append({
                        "url": src,
                        "title": title
                    })
                    seen_urls.add(src)

            # 查找YouTube等视频链接
            for link in links:
                # 再次检查是否在推广区域（双重保险）
                if self.is_element_in_promotional_area(link):
                    continue

                href = link.get('href', '')
                if href and href not in seen_urls and self.is_valid_video_url(href):
                    link_text = link.get_text().strip()

                    # 检查链接文本是否是商业内容
                    if not self.is_commercial_text(link_text):
                        videos.append({
                            "url": href,
                            "title": link_text
                        })
                        seen_urls.add(href)

            if self.verbose:
                print(f"最终提取到 {len(videos)} 个有效视频")
            return videos
        except Exception as e:
            print(f"从section提取视频时发生错误: {str(e)}")
            return []

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

            # 特殊处理triage：先单独提取
            triage_element = main_content.select_one('#Section_Triage')
            if triage_element:
                print(f"找到triage元素: {triage_element.name}, ID: {triage_element.get('id', '')}")
                if triage_element.name == 'h3':
                    content = self.extract_triage_content_specifically(triage_element, main_content)
                    if content and content.strip():
                        if not self.is_content_duplicate(content, seen_content):
                            sections['triage'] = content.strip()
                            seen_content.add(content.strip())
                            processed_elements.add(id(triage_element))
                            print(f"特殊提取triage字段: ({len(content)} 字符)")
                        else:
                            print("Triage内容与已有内容重复，跳过")
                    else:
                        print("Triage内容为空")
                else:
                    print(f"Triage元素不是h3标签: {triage_element.name}")
            else:
                print("未找到#Section_Triage元素")

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
                        'introduction': ['introduction'],  # 只匹配完全的introduction标题
                        'first_steps': ['first steps', 'before undertaking'],
                        'triage': ['triage']
                    }

                    if field_name in target_texts:
                        for heading in main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                            heading_text = heading.get_text().strip().lower()
                            # 对于introduction，只匹配完全相同的标题
                            if field_name == 'introduction':
                                if heading_text == 'introduction':
                                    if id(heading) not in processed_elements:
                                        content = self.extract_section_content_precisely(heading, main_content, field_name)
                                        if content and content.strip():
                                            # 额外检查：确保内容不是作者信息
                                            if not self._is_author_or_meta_content(content):
                                                if not self.is_content_duplicate(content, seen_content):
                                                    sections[field_name] = content.strip()
                                                    seen_content.add(content.strip())
                                                    processed_elements.add(id(heading))
                                                    print(f"通过标题提取字段: {field_name} ({len(content)} 字符)")
                                                    found = True
                                                    break
                                            else:
                                                print(f"跳过作者信息，不作为{field_name}提取")
                            else:
                                # 对于其他字段，使用原来的逻辑
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

                # 特殊处理introduction：只有在页面上真实存在Introduction标题时才尝试提取
                if not found and field_name == 'introduction':
                    # 先检查页面是否真的有Introduction标题
                    intro_heading_exists = False
                    intro_heading = None

                    # 使用更直接的方法检查Introduction标题是否存在
                    for heading in main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                        heading_text = heading.get_text().strip().lower()
                        if heading_text == 'introduction':
                            intro_heading_exists = True
                            intro_heading = heading
                            break

                    # 只有在确实存在Introduction标题时才尝试提取
                    if intro_heading_exists and intro_heading:
                        print(f"找到Introduction标题，尝试提取内容...")
                        # 直接从Introduction标题后提取内容
                        intro_content = self.extract_content_under_heading_strict(intro_heading, main_content, processed_elements)
                        if not intro_content or len(intro_content.strip()) < 50:
                            # 如果直接提取失败，尝试从页面开头提取
                            intro_content = self._extract_introduction_from_page_start(main_content, processed_elements, soup)

                        if intro_content and intro_content.strip():
                            # 确保内容不是作者信息
                            if not self._is_author_or_meta_content(intro_content):
                                if not self.is_content_duplicate(intro_content, seen_content):
                                    sections[field_name] = intro_content.strip()
                                    seen_content.add(intro_content.strip())
                                    processed_elements.add(id(intro_heading))
                                    print(f"成功提取introduction: ({len(intro_content)} 字符)")
                                    found = True
                                else:
                                    print(f"Introduction内容重复，跳过")
                            else:
                                print(f"Introduction内容是作者信息，跳过")
                        else:
                            print(f"Introduction内容为空或太短，跳过")
                    else:
                        print(f"页面上不存在Introduction标题，跳过{field_name}提取")

                # 特殊处理triage：它可能在first_steps的div容器内
                if not found and field_name == 'triage':
                    # 查找first_steps容器内的triage标题
                    first_steps_div = main_content.select_one('#Section_First_Steps')
                    if first_steps_div:
                        triage_heading = first_steps_div.find('h3', string=lambda text: text and 'triage' in text.lower())
                        if triage_heading and id(triage_heading) not in processed_elements:
                            content = self.extract_content_under_heading_strict(triage_heading, main_content, processed_elements)
                            if content and content.strip():
                                if not self.is_content_duplicate(content, seen_content):
                                    sections[field_name] = content.strip()
                                    seen_content.add(content.strip())
                                    processed_elements.add(id(triage_heading))
                                    print(f"从first_steps容器提取字段: {field_name} ({len(content)} 字符)")
                                    found = True

            # 然后查找其他可能的独立标题部分
            headings = main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])

            for heading in headings:
                if id(heading) in processed_elements:
                    continue

                heading_text = heading.get_text().strip()
                heading_text_lower = heading_text.lower()

                # 跳过不相关的标题
                if any(skip_word in heading_text_lower for skip_word in [
                    'causes', 'related pages', 'additional resources', 'related problems',
                    'related answers', 'buy', 'purchase', 'tools', 'parts', 'comments',
                    'share', 'social', 'view statistics', 'past 24 hours', 'past 7 days',
                    'all time', 'haven\'t found', 'browse our forum', 'select my model',
                    'find your parts', 'view guide', 'view all', 'macbook black screen'
                ]):
                    continue

                # 跳过数字编号的causes
                if re.match(r'^\d+\s*$', heading_text_lower.strip()):
                    continue

                # 动态识别标题 - 更严格的验证
                field_name = None

                # 严格匹配 introduction - 只有完全匹配"Introduction"标题的才被认为是 introduction
                if heading_text_lower == 'introduction' and 'introduction' not in sections:
                    # 额外验证：确保这个标题下有实际的介绍性内容
                    test_content = self.extract_content_under_heading_strict(heading, main_content, set())
                    if test_content and len(test_content) > 50:
                        # 检查内容是否真的是介绍性的，而不是其他类型的内容
                        if not self._is_author_or_meta_content(test_content):
                            field_name = 'introduction'

                elif 'first steps' in heading_text_lower and 'first_steps' not in sections:
                    field_name = 'first_steps'
                elif heading_text_lower == 'triage' and 'triage' not in sections:
                    field_name = 'triage'
                elif heading_text_lower in ['getting started', 'before you begin', 'preparation']:
                    field_name = heading_text_lower.replace(' ', '_')
                else:
                    # 对于其他有意义的标题，但要排除明显不相关的内容
                    if (len(heading_text) > 3 and len(heading_text) < 100 and
                        not any(exclude_word in heading_text_lower for exclude_word in [
                            'about the author', 'author', 'contributor', 'last updated',
                            'acmt certification', 'technician', 'cobbled together'
                        ])):
                        field_name = re.sub(r'[^\w\s]', '', heading_text).strip()
                        field_name = re.sub(r'\s+', '_', field_name).lower()
                        if len(field_name) > 50:
                            field_name = field_name[:50]

                if field_name and field_name not in sections:
                    content = self.extract_content_under_heading_strict(heading, main_content, processed_elements)
                    if content and content.strip():
                        # 额外验证：确保内容不是作者信息或其他元数据
                        if not self._is_author_or_meta_content(content):
                            if not self.is_content_duplicate(content, seen_content):
                                sections[field_name] = content.strip()
                                seen_content.add(content.strip())
                                processed_elements.add(id(heading))
                                print(f"动态提取字段: {field_name} ({len(content)} 字符)")
                        else:
                            print(f"跳过作者或元数据内容: {field_name}")

            return sections

        except Exception as e:
            print(f"动态提取字段时发生错误: {str(e)}")
            return {}

    def _is_author_or_meta_content(self, content):
        """检测内容是否是作者信息或元数据"""
        if not content:
            return False

        content_lower = content.lower()

        # 检测作者信息的特征
        author_indicators = [
            'acmt certification', 'certification', 'technician', 'cobbled together',
            'touchpad is entirely the wrong color', 'three separate machines',
            'despite holding', 'maybe specifically because of this',
            'says everything you need to know about me', 'mac technician',
            'contributor', 'last updated on', 'and 1 contributor',
            'and 2 contributors', 'and 3 contributors', 'and 4 contributors',
            'and 5 contributors', 'and 6 contributors', 'and 7 contributors'
        ]

        # 检测元数据的特征
        meta_indicators = [
            'last updated', 'contributors', 'updated on', 'written by',
            'authored by', 'created by', 'edited by'
        ]

        # 如果内容包含作者或元数据指标，认为是作者/元数据内容
        if any(indicator in content_lower for indicator in author_indicators + meta_indicators):
            return True

        # 检测特定的作者信息模式
        author_patterns = [
            r'despite\s+holding.*certification',
            r'macbook.*cobbled\s+together.*machines',
            r'touchpad.*wrong\s+color',
            r'says\s+everything.*about\s+me.*technician'
        ]

        if any(re.search(pattern, content_lower) for pattern in author_patterns):
            return True

        return False

    def extract_section_content_precisely(self, element, main_content, section_type):
        """精确提取特定部分的内容，避免包含其他部分的内容，增强边界检测"""
        try:
            content_parts = []
            seen_texts = set()

            # 如果element是div容器，直接提取其内部内容
            if element.name == 'div':
                # 对于div容器，提取其内部的文本内容，但排除子标题部分
                for child in element.find_all(['p', 'div', 'ul', 'ol', 'li', 'span'], recursive=True):
                    # 跳过包含causes编号的内容
                    if child.get_text().strip().startswith(('1', '2', '3', '4', '5', '6', '7', '8')) and len(child.get_text().strip()) < 50:
                        continue

                    # 跳过子标题区域
                    if child.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                        continue

                    if not self.is_commercial_content(child):
                        # 检查内容边界
                        child_text = child.get_text().strip()
                        if self._should_stop_extraction(child_text, section_type, content_parts):
                            print(f"在{section_type}部分检测到内容边界，停止提取: {child_text[:100]}...")
                            break
                        self._extract_text_from_element_strict(child, content_parts, seen_texts)

                # 特殊处理：如果是first_steps，需要排除triage部分
                if section_type == 'first_steps':
                    # 查找triage标题，如果找到则在该位置截断内容
                    triage_element = element.find('h3', string=lambda text: text and 'triage' in text.lower())
                    if triage_element:
                        # 移除triage及其后面的内容
                        filtered_parts = []
                        for part in content_parts:
                            if 'troubleshooting is a process' in part.lower():
                                break
                            filtered_parts.append(part)
                        content_parts = filtered_parts

                # 使用全面去重函数处理内容
                final_content_parts = self.comprehensive_content_deduplication(content_parts)
                return '\n\n'.join(final_content_parts) if final_content_parts else ""

            elif element.name and element.name.startswith('h'):
                # 如果element是标题，提取标题下的内容
                return self.extract_content_under_heading_strict(element, main_content, set())

            else:
                # 其他情况，尝试提取文本内容
                text = element.get_text().strip()
                if text and len(text) > 20:
                    return text
                return ""

        except Exception as e:
            print(f"精确提取{section_type}内容时发生错误: {str(e)}")
            return ""

    def extract_content_under_heading_strict(self, heading, main_content, processed_elements):
        """严格提取标题下的内容，避免重复和交叉，增强边界检测 - 支持各种HTML结构"""
        content_parts = []
        seen_texts = set()

        try:
            heading_level = int(heading.name[1]) if heading.name and heading.name.startswith('h') else 3
            heading_text = heading.get_text().strip().lower()

            print(f"开始提取标题 '{heading_text}' 下的内容...")

            # 方法1：查找直接的兄弟元素
            current = heading.next_sibling
            found_content = False

            while current:
                if hasattr(current, 'name') and current.name:
                    # 遇到同级或更高级标题时停止
                    if (current.name.startswith('h') and
                        len(current.name) == 2 and current.name[1].isdigit() and
                        int(current.name[1]) <= heading_level):
                        print(f"遇到同级标题 {current.name}，停止提取")
                        break

                    # 跳过已处理的元素
                    if id(current) in processed_elements:
                        current = current.next_sibling
                        continue

                    if current.name in ['p', 'div', 'ul', 'ol', 'li', 'section']:
                        if not self.is_commercial_content(current):
                            # 检查内容边界 - 避免混入其他部分的内容
                            element_text = current.get_text().strip()
                            if self._should_stop_extraction(element_text, heading_text, content_parts):
                                print(f"检测到内容边界，停止提取: {element_text[:100]}...")
                                break

                            # 提取内容
                            if element_text and len(element_text) > 10:
                                self._extract_text_from_element_strict(current, content_parts, seen_texts)
                                found_content = True
                                print(f"从 {current.name} 提取内容: {element_text[:100]}...")

                current = current.next_sibling

            # 方法2：如果方法1没有找到内容，尝试查找标题所在容器的后续内容
            if not found_content:
                print("方法1未找到内容，尝试方法2...")
                parent_container = heading.parent
                if parent_container:
                    # 查找标题后面的所有段落和内容元素
                    all_elements = parent_container.find_all(['p', 'div', 'ul', 'ol', 'section'], recursive=True)
                    heading_found = False

                    for elem in all_elements:
                        # 找到标题后开始提取
                        if not heading_found:
                            if elem.find(heading):
                                heading_found = True
                            continue

                        # 检查是否遇到下一个标题
                        if elem.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                            next_heading = elem.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                            if next_heading and next_heading != heading:
                                next_level = int(next_heading.name[1]) if next_heading.name.startswith('h') else 6
                                if next_level <= heading_level:
                                    print(f"方法2遇到下一个标题，停止提取")
                                    break

                        # 提取内容
                        if not self.is_commercial_content(elem):
                            element_text = elem.get_text().strip()
                            if element_text and len(element_text) > 10:
                                if not self._should_stop_extraction(element_text, heading_text, content_parts):
                                    self._extract_text_from_element_strict(elem, content_parts, seen_texts)
                                    found_content = True
                                    print(f"方法2从 {elem.name} 提取内容: {element_text[:100]}...")
                                else:
                                    print(f"方法2检测到内容边界，停止提取")
                                    break

            # 最终去重和清理 - 使用新的全面去重函数
            final_content_parts = self.comprehensive_content_deduplication(content_parts)
            result = '\n\n'.join(final_content_parts) if final_content_parts else ""

            if result:
                print(f"成功提取内容，总长度: {len(result)} 字符")
            else:
                print("未提取到任何内容")

            return result

        except Exception as e:
            print(f"严格提取标题下内容时发生错误: {str(e)}")
            return ""

    def _should_stop_extraction(self, element_text, heading_text, content_parts):
        """检测是否应该停止内容提取，避免混入其他部分的内容"""
        if not element_text or len(element_text) < 20:
            return False

        element_text_lower = element_text.lower()

        # 检测明显的部分分隔符
        section_separators = [
            'causes', 'related pages', 'about the author', 'additional resources',
            'see also', 'external links', 'references', 'further reading',
            'troubleshooting steps', 'next steps', 'conclusion'
        ]

        # 如果遇到明显的部分分隔符，停止提取
        for separator in section_separators:
            if element_text_lower.strip().startswith(separator):
                return True

        # 特殊检测：如果当前是triage部分，检测特定的结束模式
        if 'triage' in heading_text:
            # 检测triage部分的典型结束模式
            triage_end_patterns = [
                'the layout of this connector',  # 这是混入的其他内容的开始
                'liquid in your electronics',    # 液体损坏相关内容
                'even if you don\'t know much about circuit board',  # 电路板相关内容
                'backlight circuits appear in similar places',  # 背光电路相关内容
                'they typically rely on a large number of capacitors'  # 电容器相关内容
            ]

            for pattern in triage_end_patterns:
                if pattern in element_text_lower:
                    return True

        # 检测内容主题的突然变化
        if content_parts:
            # 获取已有内容的主要关键词
            existing_content = ' '.join(content_parts).lower()

            # 如果当前元素包含与已有内容完全不相关的技术术语，可能是混入的内容
            technical_terms = [
                'connector positions', 'power line', 'data between the display and cpu',
                'capacitors in a row', 'display connector', 'circuit board design'
            ]

            for term in technical_terms:
                if term in element_text_lower and term not in existing_content:
                    # 进一步验证：如果这个技术术语出现在一个明显不相关的上下文中
                    if len(element_text) > 100 and 'firmware issue' not in element_text_lower:
                        return True

        return False

    def _clean_and_deduplicate_content(self, content_parts):
        """清理和去重内容"""
        if not content_parts:
            return ""

        # 合并所有内容
        full_text = '\n\n'.join(content_parts)

        # 按段落分割，同时处理单个换行符分隔的内容
        paragraphs = []
        for part in content_parts:
            # 先按双换行符分割
            double_split = [p.strip() for p in part.split('\n\n') if p.strip()]
            for p in double_split:
                # 再按单换行符分割，但保持相关内容在一起
                if '\n' in p and len(p) > 100:  # 长段落可能包含多个句子
                    # 按句子分割并重新组合
                    sentences = [s.strip() for s in re.split(r'[.!?]\s+', p) if s.strip()]
                    if sentences:
                        paragraphs.append('. '.join(sentences) + '.')
                else:
                    paragraphs.append(p)

        # 去重段落 - 使用更严格的去重逻辑
        unique_paragraphs = []
        seen_normalized = set()
        seen_sentences = set()

        for paragraph in paragraphs:
            if len(paragraph) > 20:  # 只保留有意义的段落
                normalized = re.sub(r'\s+', ' ', paragraph.lower()).strip()

                # 检查整个段落是否重复
                is_duplicate = False
                for seen in seen_normalized:
                    if self._calculate_text_similarity(normalized, seen) > 0.9:
                        is_duplicate = True
                        break

                if not is_duplicate:
                    # 检查句子级别的重复
                    paragraph_sentences = [s.strip() for s in re.split(r'[.!?]\s+', paragraph) if s.strip()]
                    new_sentences = []

                    for sentence in paragraph_sentences:
                        if len(sentence) > 15:  # 只检查有意义的句子
                            sentence_normalized = re.sub(r'\s+', ' ', sentence.lower()).strip()

                            # 检查这个句子是否已经出现过
                            sentence_duplicate = False
                            for seen_sentence in seen_sentences:
                                if self._calculate_text_similarity(sentence_normalized, seen_sentence) > 0.95:
                                    sentence_duplicate = True
                                    break

                            if not sentence_duplicate:
                                new_sentences.append(sentence)
                                seen_sentences.add(sentence_normalized)

                    # 如果有新的句子，重新组合段落
                    if new_sentences:
                        new_paragraph = '. '.join(new_sentences)
                        if not new_paragraph.endswith('.'):
                            new_paragraph += '.'
                        unique_paragraphs.append(new_paragraph)
                        seen_normalized.add(normalized)

        return '\n\n'.join(unique_paragraphs)

    def _super_clean_and_deduplicate(self, content_parts):
        """超强力去重和清理内容"""
        if not content_parts:
            return ""

        # 合并所有内容
        full_text = '\n\n'.join(content_parts)

        # 按句子分割所有内容
        all_sentences = []
        for part in content_parts:
            # 按句子分割
            sentences = re.split(r'[.!?]\s+', part)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) > 15:  # 只保留有意义的句子
                    all_sentences.append(sentence)

        # 去重句子
        unique_sentences = []
        seen_normalized = set()

        for sentence in all_sentences:
            # 标准化句子用于比较
            normalized = re.sub(r'\s+', ' ', sentence.lower()).strip()

            # 检查是否重复
            is_duplicate = False
            for seen in seen_normalized:
                if self._calculate_text_similarity(normalized, seen) > 0.95:
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique_sentences.append(sentence)
                seen_normalized.add(normalized)

        # 重新组合成段落
        if not unique_sentences:
            return ""

        # 将句子重新组合成段落，每3-5个句子一个段落
        paragraphs = []
        current_paragraph = []

        for i, sentence in enumerate(unique_sentences):
            current_paragraph.append(sentence)

            # 每3-5个句子组成一个段落，或者到达最后一个句子
            if len(current_paragraph) >= 3 and (
                i == len(unique_sentences) - 1 or
                len(current_paragraph) >= 5 or
                sentence.endswith(('?', '!')) or
                (i < len(unique_sentences) - 1 and
                 any(keyword in unique_sentences[i+1].lower() for keyword in
                     ['perform', 'reset', 'try', 'check', 'if', 'connect', 'disconnect']))
            ):
                paragraph_text = '. '.join(current_paragraph)
                if not paragraph_text.endswith('.'):
                    paragraph_text += '.'
                paragraphs.append(paragraph_text)
                current_paragraph = []

        # 如果还有剩余的句子，组成最后一个段落
        if current_paragraph:
            paragraph_text = '. '.join(current_paragraph)
            if not paragraph_text.endswith('.'):
                paragraph_text += '.'
            paragraphs.append(paragraph_text)

        return '\n\n'.join(paragraphs)

    def _extract_introduction_from_page_start(self, main_content, processed_elements, soup=None):
        """从页面开头提取introduction内容 - 增强版本，支持更多页面布局"""
        try:
            intro_parts = []
            seen_texts = set()

            # 跳过通用的网站文本
            generic_texts = [
                'learn how to fix just about anything',
                'share solutions and get help',
                'get a sneak peek inside',
                'your destination for tech repair',
                'help teach people to make'
            ]

            # 方法1：查找页面开头的段落，但要避免步骤相关内容
            all_paragraphs = main_content.select("p")

            # 扩展的introduction指标，包含更多可能的描述性文本
            intro_indicators = [
                'macbook', 'problem', 'issue', 'error', 'screen', 'display',
                'boot', 'startup', 'turn on', 'power', 'folder', 'question mark',
                'loading', 'stuck', 'black screen', 'won\'t', 'not working',
                'have you ever', 'if you have', 'when your', 'this guide',
                'before you', 'if your', 'troubleshooting', 'symptom', 'experiencing',
                'don\'t panic', 'it\'s possible', 'you may', 'this can happen',
                'operating system', 'disk', 'drive', 'storage', 'data corruption',
                'hard drive', 'ssd', 'startup disk', 'it seems logical', 'expect that',
                'what if instead', 'faced with', 'mysterious', 'flashing'
            ]

            for p in all_paragraphs[:25]:  # 增加检查范围到25个段落
                if id(p) in processed_elements:
                    continue

                p_text = p.get_text().strip()

                # 跳过通用网站文本
                if any(generic in p_text.lower() for generic in generic_texts):
                    continue

                # 如果遇到步骤内容或其他section标题，停止收集
                if any(stop_word in p_text.lower() for stop_word in
                       ['step 1', 'what you need', 'tools', 'parts', 'first steps', 'triage', 'causes']):
                    break

                # 跳过太短的文本 - 降低最小长度要求
                if len(p_text) < 30:
                    continue

                # 跳过商业内容
                if self.is_commercial_content(p):
                    continue

                # 检查是否是真正的介绍性内容
                has_intro_indicator = any(indicator in p_text.lower() for indicator in intro_indicators)

                # 如果没有明确指标，检查是否是描述性文本
                if not has_intro_indicator:
                    descriptive_patterns = [
                        r'if\s+you.*?(?:encounter|experience|see|find|have)',
                        r'when.*?(?:boot|start|turn|power)',
                        r'this.*?(?:issue|problem|error|guide)',
                        r'you.*?(?:may|might|can|should)',
                        r'don\'t\s+panic',
                        r'it\'s\s+possible',
                        r'keeping\s+track.*?macbook',
                        r'data.*?(?:corruption|records|change)',
                        r'operating\s+system'
                    ]

                    if any(re.search(pattern, p_text.lower()) for pattern in descriptive_patterns):
                        has_intro_indicator = True

                # Special case: For pages without clear intro, look for problem-specific content
                page_title = soup.select_one('h1')
                if page_title and not has_intro_indicator:
                    title_text = page_title.get_text().lower()
                    if 'folder' in title_text and 'question mark' in title_text:
                        # For folder with question mark, look for content about data/disk issues
                        if any(keyword in p_text.lower() for keyword in
                               ['data', 'disk', 'drive', 'storage', 'operating system', 'corruption']):
                            has_intro_indicator = True

                if not has_intro_indicator:
                    continue

                # 清理文本
                p_text = re.sub(r'\n\s*\n+', '\n\n', p_text)
                p_text = re.sub(r'[ \t]+', ' ', p_text)
                p_text = p_text.strip()

                # 检查重复
                if not self._is_text_duplicate_enhanced(p_text, seen_texts):
                    intro_parts.append(p_text)
                    seen_texts.add(p_text)
                    processed_elements.add(id(p))

                    # 如果已经收集到足够的内容，停止
                    if len('\n\n'.join(intro_parts)) > 400:  # 增加内容长度限制
                        break

            # 方法2：如果方法1没有找到足够内容，在页面特定区域查找介绍性内容
            if len('\n\n'.join(intro_parts)) < 100:
                print("方法1未找到足够introduction内容，尝试方法2...")

                # 限制搜索范围到页面的前半部分，避免获取causes或其他部分的内容
                # 查找页面标题后的前几个段落，但要避免causes部分
                page_title = soup.select_one("h1")
                if page_title:
                    # 从标题开始，查找后续的段落，但在遇到causes相关内容前停止
                    title_parent = page_title.parent
                    search_area = title_parent if title_parent else main_content

                    # 获取标题后的段落，但限制数量避免获取causes内容
                    all_paragraphs_method2 = search_area.select("p")[:15]  # 只检查前15个段落
                else:
                    # 如果没有找到标题，限制在页面前部分
                    all_paragraphs_method2 = main_content.select("p")[:10]  # 只检查前10个段落

                for p in all_paragraphs_method2:
                    if id(p) in processed_elements:
                        continue

                    p_text = p.get_text().strip()

                    # 跳过太短的文本
                    if len(p_text) < 30:
                        continue

                    # 跳过通用网站文本
                    if any(generic in p_text.lower() for generic in generic_texts):
                        continue

                    # 严格验证：确保内容与当前页面标题相关
                    page_title_text = ""
                    if page_title:
                        page_title_text = page_title.get_text().lower()

                    # 检查段落是否与页面主题相关
                    is_relevant_to_page = False
                    if page_title_text:
                        # 提取页面主题关键词
                        title_keywords = []
                        if 'black screen' in page_title_text:
                            title_keywords = ['black screen', 'display', 'screen', 'boot', 'startup']
                        elif 'folder' in page_title_text and 'question mark' in page_title_text:
                            title_keywords = ['folder', 'question mark', 'operating system', 'disk', 'startup']
                        elif 'stuck' in page_title_text and 'loading' in page_title_text:
                            title_keywords = ['loading', 'stuck', 'boot', 'startup', 'progress']
                        elif 'slow' in page_title_text:
                            title_keywords = ['slow', 'performance', 'speed', 'lag']
                        elif 'won\'t turn on' in page_title_text or 'will not turn on' in page_title_text:
                            title_keywords = ['power', 'turn on', 'boot', 'startup']

                        # 检查段落是否包含相关关键词
                        if title_keywords and any(keyword in p_text.lower() for keyword in title_keywords):
                            is_relevant_to_page = True

                    # 排除明显属于其他问题的内容
                    exclude_patterns = [
                        r'storage.*full.*sock drawer',  # 存储空间问题的特征文本
                        r'think of it like your sock drawer',
                        r'squish.*pairs of socks',
                        r'drawer will stop closing'
                    ]

                    is_excluded = any(re.search(pattern, p_text.lower()) for pattern in exclude_patterns)

                    if is_excluded:
                        print(f"排除不相关内容: {p_text[:100]}...")
                        continue

                    # 检查是否包含介绍性内容
                    has_intro_indicator = any(indicator in p_text.lower() for indicator in intro_indicators)

                    # 如果没有明确指标，检查是否是描述性文本
                    if not has_intro_indicator:
                        descriptive_patterns = [
                            r'it\s+seems\s+logical',
                            r'expect\s+that.*?macbook',
                            r'what\s+if\s+instead',
                            r'faced\s+with.*?mysterious',
                            r'if\s+you.*?(?:encounter|experience|see|find|have)',
                            r'when.*?(?:boot|start|turn|power)',
                            r'this.*?(?:issue|problem|error|guide)',
                            r'you.*?(?:may|might|can|should)',
                            r'keeping\s+track.*?macbook',
                            r'data.*?(?:corruption|records|change)',
                            r'operating\s+system'
                        ]

                        if any(re.search(pattern, p_text.lower()) for pattern in descriptive_patterns):
                            has_intro_indicator = True

                    # 只有在内容相关且有介绍指标时才添加
                    if has_intro_indicator and (is_relevant_to_page or not page_title_text):
                        # 清理文本
                        p_text = re.sub(r'\n\s*\n+', '\n\n', p_text)
                        p_text = re.sub(r'[ \t]+', ' ', p_text)
                        p_text = p_text.strip()

                        # 检查重复
                        if not self._is_text_duplicate_enhanced(p_text, seen_texts):
                            intro_parts.append(p_text)
                            seen_texts.add(p_text)
                            processed_elements.add(id(p))
                            print(f"方法2找到相关introduction内容: {p_text[:100]}...")

                            # 如果已经收集到足够的内容，停止
                            if len('\n\n'.join(intro_parts)) > 300:
                                break

            # 使用新的去重函数处理最终结果
            if intro_parts:
                final_intro_parts = self.comprehensive_content_deduplication(intro_parts)
                return '\n\n'.join(final_intro_parts) if final_intro_parts else ""

            return ""

        except Exception as e:
            print(f"从页面开头提取introduction时发生错误: {str(e)}")
            return ""

    def _extract_text_from_element_strict(self, element, content_parts, seen_texts):
        """严格的文本提取，避免重复内容"""
        try:
            if self.is_commercial_content(element):
                print(f"跳过商业内容: {element.get_text().strip()[:50]}...")
                return

            text = element.get_text().strip()
            if text and len(text) > 20:
                # 清理文本格式，但保留段落分隔
                text = re.sub(r'\n\s*\n+', '\n\n', text)
                text = re.sub(r'[ \t]+', ' ', text)
                text = text.strip()

                # 排除导航和无关内容 - 使用更精确的模式避免误过滤
                skip_patterns = [
                    'related pages', 'buy now', 'purchase', 'add to cart',
                    'register', 'menu', 'navigation', 'view guide',
                    'find your parts', 'select my model', 'view all',
                    'past 24 hours', 'past 7 days', 'all time',
                    'browse our forum', 'haven\'t found'
                    # 移除 'login' 因为正常内容可能包含 'login screen'
                    # 移除 'causes' 因为它可能误过滤正常内容
                ]

                skip_found = False
                for skip_word in skip_patterns:
                    if skip_word in text.lower():
                        print(f"跳过包含'{skip_word}'的内容: {text[:50]}...")
                        skip_found = True
                        break

                if not skip_found:
                    # 强化去重逻辑：检查句子级别的重复
                    if not self._is_text_duplicate_enhanced(text, seen_texts):
                        content_parts.append(text)
                        seen_texts.add(text)
                        print(f"成功添加文本: {text[:50]}...")
                    else:
                        print(f"跳过重复文本: {text[:50]}...")
            else:
                print(f"跳过太短的文本: {text[:50]}...")

        except Exception as e:
            print(f"严格提取文本时发生错误: {str(e)}")

    def _is_text_duplicate_enhanced(self, new_text, seen_texts):
        """增强的重复检测，检查句子级别的重复 - 修复版本，更严格的去重"""
        try:
            # 将文本分割成句子
            new_sentences = [s.strip() for s in re.split(r'[.!?]\s+', new_text) if s.strip()]
            normalized_new = re.sub(r'\s+', ' ', new_text.lower()).strip()

            # 如果文本太短，直接检查是否已存在
            if len(normalized_new) < 50:
                for seen_text in seen_texts:
                    normalized_seen = re.sub(r'\s+', ' ', seen_text.lower()).strip()
                    if normalized_new == normalized_seen or normalized_new in normalized_seen:
                        return True
                return False

            for seen_text in seen_texts:
                normalized_seen = re.sub(r'\s+', ' ', seen_text.lower()).strip()

                # 1. 检查整体相似度 - 降低阈值，更严格
                if self._calculate_text_similarity(normalized_new, normalized_seen) > 0.6:
                    return True

                # 2. 检查是否一个文本包含另一个文本
                if normalized_new in normalized_seen or normalized_seen in normalized_new:
                    return True

                # 3. 检查句子级别的重复 - 更严格的阈值
                seen_sentences = [s.strip() for s in re.split(r'[.!?]\s+', seen_text) if s.strip()]

                # 如果新文本的大部分句子都在已有文本中出现过，认为是重复
                duplicate_count = 0
                for new_sentence in new_sentences:
                    if len(new_sentence) > 10:  # 只检查有意义的句子
                        normalized_new_sentence = re.sub(r'\s+', ' ', new_sentence.lower()).strip()
                        for seen_sentence in seen_sentences:
                            if len(seen_sentence) > 10:
                                normalized_seen_sentence = re.sub(r'\s+', ' ', seen_sentence.lower()).strip()
                                # 检查完全匹配或高度相似
                                if (normalized_new_sentence == normalized_seen_sentence or
                                    normalized_new_sentence in normalized_seen_sentence or
                                    normalized_seen_sentence in normalized_new_sentence or
                                    self._calculate_text_similarity(normalized_new_sentence, normalized_seen_sentence) > 0.85):
                                    duplicate_count += 1
                                    break

                # 如果超过40%的句子重复，认为是重复内容 - 降低阈值，更严格
                if new_sentences and duplicate_count / len(new_sentences) > 0.4:
                    return True

            return False
        except:
            return False

    def is_content_duplicate(self, content, seen_content):
        """检查内容是否与已有内容重复 - 修复版本，更严格的去重"""
        try:
            normalized_content = re.sub(r'\s+', ' ', content.lower()).strip()

            # 如果内容为空或太短，跳过
            if not normalized_content or len(normalized_content) < 20:
                return False

            for seen in seen_content:
                normalized_seen = re.sub(r'\s+', ' ', seen.lower()).strip()

                # 1. 检查完全匹配
                if normalized_content == normalized_seen:
                    return True

                # 2. 检查包含关系
                if normalized_content in normalized_seen or normalized_seen in normalized_content:
                    return True

                # 3. 检查相似度 - 降低阈值，更严格
                if self._calculate_text_similarity(normalized_content, normalized_seen) > 0.6:
                    return True

                # 4. 检查句子级别的重复
                content_sentences = [s.strip() for s in re.split(r'[.!?]\s+', normalized_content) if s.strip()]
                seen_sentences = [s.strip() for s in re.split(r'[.!?]\s+', normalized_seen) if s.strip()]

                if content_sentences and seen_sentences:
                    duplicate_count = 0
                    for content_sentence in content_sentences:
                        if len(content_sentence) > 15:
                            for seen_sentence in seen_sentences:
                                if len(seen_sentence) > 15:
                                    if (content_sentence == seen_sentence or
                                        content_sentence in seen_sentence or
                                        seen_sentence in content_sentence or
                                        self._calculate_text_similarity(content_sentence, seen_sentence) > 0.8):
                                        duplicate_count += 1
                                        break

                    # 如果超过30%的句子重复，认为是重复内容
                    if duplicate_count / len(content_sentences) > 0.3:
                        return True

            return False
        except:
            return False

    def comprehensive_content_deduplication(self, content_parts):
        """全面的内容去重，防止任何形式的重复"""
        if not content_parts:
            return []

        try:
            # 第一步：基本清理和标准化，同时过滤商业内容
            cleaned_parts = []
            for part in content_parts:
                if isinstance(part, str) and part.strip():
                    # 检查是否包含商业内容
                    commercial_patterns = [
                        r'\$\d+\.\d+',  # 价格信息
                        r'\d+\s+reviews?',  # 评论数量
                        r'macbook\s+pro:.*display.*not\s+recognized',  # 特定链接文本
                        r'display\s+backlight\s+cables',  # 产品名称
                        r'retina\s+\(\d{4}-\d{4}\)',  # 产品型号年份
                        r'buy\s*$',  # 购买链接
                        r'precision\s+tweezers\s+set',  # 工具产品
                    ]

                    is_commercial = any(re.search(pattern, part.lower()) for pattern in commercial_patterns)

                    if not is_commercial:
                        # 清理文本格式
                        cleaned = re.sub(r'\n\s*\n+', '\n\n', part.strip())
                        cleaned = re.sub(r'[ \t]+', ' ', cleaned)
                        if len(cleaned) > 15:  # 只保留有意义的内容
                            cleaned_parts.append(cleaned)

            if not cleaned_parts:
                return []

            # 第二步：句子级别的去重 - 改进版本
            all_sentences = []
            seen_sentences = set()

            for part in cleaned_parts:
                # 更精确的句子分割，处理多种情况
                sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', part)
                for sentence in sentences:
                    sentence = sentence.strip()
                    if len(sentence) > 15:
                        # 移除句末标点符号进行比较
                        sentence_for_comparison = re.sub(r'[.!?]+$', '', sentence).strip()
                        normalized = re.sub(r'\s+', ' ', sentence_for_comparison.lower()).strip()

                        # 检查是否已存在相似句子 - 更严格的去重
                        is_duplicate = False
                        for seen_sentence in seen_sentences:
                            # 完全相同
                            if normalized == seen_sentence:
                                is_duplicate = True
                                break
                            # 一个句子完全包含另一个（长度差异不大时）
                            elif (len(normalized) > 30 and len(seen_sentence) > 30 and
                                  abs(len(normalized) - len(seen_sentence)) < 20):
                                if (normalized in seen_sentence or seen_sentence in normalized):
                                    is_duplicate = True
                                    break
                            # 高相似度
                            elif self._calculate_text_similarity(normalized, seen_sentence) > 0.9:
                                is_duplicate = True
                                break

                        if not is_duplicate:
                            all_sentences.append(sentence)
                            seen_sentences.add(normalized)

            # 第三步：重新组织成段落，并进行段落内去重
            if not all_sentences:
                return []

            # 将句子重新组合成段落，避免过短的段落，同时确保段落内无重复
            paragraphs = []
            current_paragraph = []
            current_length = 0
            paragraph_seen_sentences = set()

            for sentence in all_sentences:
                # 检查这个句子是否已经在当前段落中
                sentence_normalized = re.sub(r'\s+', ' ', sentence.lower()).strip()
                sentence_normalized = re.sub(r'[.!?]+$', '', sentence_normalized).strip()

                if sentence_normalized not in paragraph_seen_sentences:
                    current_paragraph.append(sentence)
                    paragraph_seen_sentences.add(sentence_normalized)
                    current_length += len(sentence)

                    # 如果当前段落足够长，或者遇到明显的段落分隔符，结束当前段落
                    if (current_length > 200 or
                        sentence.endswith('.') and len(current_paragraph) >= 2):
                        paragraph_text = '. '.join(current_paragraph)
                        if not paragraph_text.endswith('.'):
                            paragraph_text += '.'
                        paragraphs.append(paragraph_text)
                        current_paragraph = []
                        current_length = 0
                        paragraph_seen_sentences = set()

            # 处理剩余的句子
            if current_paragraph:
                paragraph_text = '. '.join(current_paragraph)
                if not paragraph_text.endswith('.'):
                    paragraph_text += '.'
                paragraphs.append(paragraph_text)

            # 第四步：段落级别的最终去重
            final_paragraphs = []
            seen_paragraph_hashes = set()

            for paragraph in paragraphs:
                normalized = re.sub(r'\s+', ' ', paragraph.lower()).strip()
                paragraph_hash = hash(normalized)

                if paragraph_hash not in seen_paragraph_hashes:
                    # 检查与已有段落的相似度
                    is_similar = False
                    for existing_para in final_paragraphs:
                        existing_normalized = re.sub(r'\s+', ' ', existing_para.lower()).strip()
                        if self._calculate_text_similarity(normalized, existing_normalized) > 0.7:
                            is_similar = True
                            break

                    if not is_similar:
                        final_paragraphs.append(paragraph)
                        seen_paragraph_hashes.add(paragraph_hash)

            return final_paragraphs

        except Exception as e:
            print(f"全面去重时发生错误: {str(e)}")
            return content_parts

    def _calculate_text_similarity(self, text1, text2):
        """计算两个文本的相似度"""
        try:
            if not text1 or not text2:
                return 0

            # 如果文本长度差异很大，相似度较低
            len_ratio = min(len(text1), len(text2)) / max(len(text1), len(text2))
            if len_ratio < 0.5:
                return 0

            # 计算单词级别的相似度
            words1 = set(text1.split())
            words2 = set(text2.split())

            if not words1 or not words2:
                return 0

            intersection = words1.intersection(words2)
            union = words1.union(words2)

            return len(intersection) / len(union) if union else 0
        except:
            return 0

    def extract_triage_content_specifically(self, triage_heading, main_content):
        """专门提取Triage部分的内容"""
        try:
            content_parts = []
            seen_texts = set()

            print(f"开始提取Triage内容，标题: {triage_heading.get_text().strip()}")

            # 方法1: 查找triage标题所在的容器，然后提取该容器内triage标题后的所有内容
            triage_container = triage_heading.parent
            if triage_container:
                print(f"Triage容器: {triage_container.name}, class: {triage_container.get('class', [])}")

                # 查找triage标题在容器中的位置
                all_elements = list(triage_container.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'ul', 'ol']))
                triage_index = -1

                for i, element in enumerate(all_elements):
                    if element == triage_heading:
                        triage_index = i
                        print(f"找到triage标题位置: 索引 {i}")
                        break

                if triage_index >= 0:
                    # 提取triage标题后的内容，直到遇到下一个标题或容器结束
                    for i in range(triage_index + 1, len(all_elements)):
                        element = all_elements[i]

                        # 如果遇到标题，停止
                        if element.name and element.name.startswith('h'):
                            print(f"遇到下一个标题: {element.get_text().strip()[:50]}，停止")
                            break

                        if element.name in ['p', 'div', 'ul', 'ol', 'li']:
                            if not self.is_commercial_content(element):
                                text = element.get_text().strip()
                                if text and len(text) > 20:
                                    # 检查是否应该停止提取（边界检测）
                                    if self._should_stop_extraction(text, 'triage', content_parts):
                                        print(f"在Triage部分检测到内容边界，停止提取: {text[:100]}...")
                                        break

                                    # 清理文本格式
                                    text = re.sub(r'\n\s*\n+', '\n', text)
                                    text = re.sub(r'[ \t]+', ' ', text)
                                    text = text.strip()

                                    # 排除明显的导航内容
                                    if not any(skip in text.lower() for skip in ['causes', 'buggy software', 'firmware corruption']):
                                        if text not in seen_texts:
                                            content_parts.append(text)
                                            seen_texts.add(text)
                                            print(f"添加Triage内容: {text[:100]}...")

            # 方法2: 如果方法1没有找到足够内容，尝试从页面内容中直接搜索triage相关内容
            if len('\n'.join(content_parts)) < 100:
                print("方法1内容不足，尝试方法2 - 搜索triage相关内容...")
                content_parts = []
                seen_texts = set()

                # 在整个页面中查找包含triage关键内容的段落
                all_paragraphs = main_content.find_all(['p', 'div', 'li'])
                for para in all_paragraphs:
                    text = para.get_text().strip()
                    if text and len(text) > 50 and len(text) < 2000:  # 限制长度，避免提取整页内容
                        # 检查是否包含triage相关的关键词
                        triage_keywords = [
                            'troubleshooting is a process', 'medical diagnosis', 'cursor around',
                            'screen lighting up', 'backlight', 'flashlight', 'external display',
                            'trackpad click', 'caps lock led'
                        ]

                        # 排除明显不相关的内容
                        exclude_keywords = [
                            'fix your stuff', 'repair guides', 'answers forum', 'teardowns',
                            'community', 'store', 'tools', 'parts', 'buy', 'purchase',
                            'buggy software', 'firmware corruption', 'damaged or faulty',
                            'faulty flex cables', 'liquid damage', 'logic board',
                            'additional resources', 'related answers', 'related problems'
                        ]

                        if (any(keyword in text.lower() for keyword in triage_keywords) and
                            not any(exclude in text.lower() for exclude in exclude_keywords)):
                            if not self.is_commercial_content(para):
                                # 额外检查：排除商业产品信息和链接
                                commercial_patterns = [
                                    r'\$\d+\.\d+',  # 价格信息
                                    r'\d+\s+reviews?',  # 评论数量
                                    r'macbook\s+pro:.*display.*not\s+recognized',  # 特定链接文本
                                    r'display\s+backlight\s+cables',  # 产品名称
                                    r'retina\s+\(\d{4}-\d{4}\)',  # 产品型号年份
                                ]

                                is_commercial = any(re.search(pattern, text.lower()) for pattern in commercial_patterns)

                                if not is_commercial:
                                    # 检查是否应该停止提取（边界检测）
                                    if self._should_stop_extraction(text, 'triage', content_parts):
                                        print(f"方法2在Triage部分检测到内容边界，跳过: {text[:100]}...")
                                        continue

                                    # 清理文本格式
                                    text = re.sub(r'\n\s*\n+', '\n', text)
                                    text = re.sub(r'[ \t]+', ' ', text)
                                    text = text.strip()

                                    if text not in seen_texts:
                                        content_parts.append(text)
                                        seen_texts.add(text)
                                        print(f"方法2找到triage内容: {text[:100]}...")
                                else:
                                    print(f"排除商业内容: {text[:100]}...")

            # 使用全面去重函数处理triage内容
            if content_parts:
                final_triage_parts = self.comprehensive_content_deduplication(content_parts)
                result = '\n\n'.join(final_triage_parts) if final_triage_parts else ""
            else:
                result = ""

            print(f"Triage内容提取完成，总长度: {len(result)} 字符")
            return result

        except Exception as e:
            print(f"提取Triage内容时发生错误: {str(e)}")
            return ""

    def extract_content_under_heading(self, heading, soup):
        """提取标题下的内容，直到下一个同级或更高级标题，改进版本"""
        content_parts = []
        seen_texts = set()

        try:
            heading_level = int(heading.name[1])  # 获取标题级别 (h1->1, h2->2, etc.)

            # 方法1: 通过next_sibling遍历
            current = heading.next_sibling
            while current:
                if hasattr(current, 'name') and current.name:
                    # 如果遇到同级或更高级标题，停止
                    if (current.name.startswith('h') and
                        len(current.name) == 2 and current.name[1].isdigit() and
                        int(current.name[1]) <= heading_level):
                        break

                    # 提取有意义的内容元素
                    if current.name in ['p', 'div', 'ul', 'ol', 'li', 'section', 'article']:
                        self._extract_text_from_element(current, content_parts, seen_texts)

                elif hasattr(current, 'string') and current.string:
                    # 处理纯文本节点
                    text = current.string.strip()
                    if text and len(text) > 10 and text not in seen_texts:
                        content_parts.append(text)
                        seen_texts.add(text)

                current = current.next_sibling

            # 方法2: 如果通过sibling没找到足够内容，尝试查找heading后面的内容区域
            if len('\n'.join(content_parts)) < 100:
                content_parts = []
                seen_texts = set()

                # 查找heading的父容器
                parent = heading.parent
                if parent:
                    # 在父容器中查找heading之后的所有内容
                    heading_found = False
                    for element in parent.find_all(['p', 'div', 'ul', 'ol', 'section']):
                        if heading_found:
                            # 检查是否遇到下一个标题
                            next_heading = element.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                            if next_heading and int(next_heading.name[1]) <= heading_level:
                                break

                            self._extract_text_from_element(element, content_parts, seen_texts)
                        elif element == heading or heading in element.find_all():
                            heading_found = True

            return '\n\n'.join(content_parts) if content_parts else ""

        except Exception as e:
            print(f"提取标题下内容时发生错误: {str(e)}")
            return ""

    def _extract_text_from_element(self, element, content_parts, seen_texts):
        """从元素中提取文本内容的辅助方法"""
        try:
            # 检查是否是商业内容或推广内容
            if self.is_commercial_content(element):
                return

            text = element.get_text().strip()
            if text and len(text) > 10:
                # 清理文本格式
                text = re.sub(r'\n\s*\n+', '\n', text)
                text = re.sub(r'[ \t]+', ' ', text)
                text = text.strip()

                # 排除明显的导航或无关内容
                skip_patterns = [
                    'related pages', 'buy now', 'purchase', 'add to cart',
                    'login', 'register', 'menu', 'navigation', 'view guide',
                    'find your parts', 'select my model', 'view all',
                    'past 24 hours', 'past 7 days', 'all time',
                    'browse our forum', 'haven\'t found'
                ]

                if not any(skip_word in text.lower() for skip_word in skip_patterns):
                    # 进一步检查是否是有意义的内容
                    if len(text) > 20 and not re.match(r'^[\d\s\$\.\,\%]+$', text):
                        # 更严格的去重：检查是否与已有内容有显著重叠
                        is_duplicate = False
                        normalized_text = re.sub(r'\s+', ' ', text.lower()).strip()

                        for seen_text in seen_texts:
                            normalized_seen = re.sub(r'\s+', ' ', seen_text.lower()).strip()
                            # 如果新文本与已有文本有80%以上的重叠，认为是重复
                            if len(normalized_text) > 50 and len(normalized_seen) > 50:
                                overlap = self._calculate_text_overlap(normalized_text, normalized_seen)
                                if overlap > 0.8:
                                    is_duplicate = True
                                    break

                        if not is_duplicate:
                            content_parts.append(text)
                            seen_texts.add(text)

        except Exception as e:
            print(f"从元素提取文本时发生错误: {str(e)}")

    def _calculate_text_overlap(self, text1, text2):
        """计算两个文本的重叠度"""
        try:
            # 简单的重叠度计算：计算共同单词的比例
            words1 = set(text1.split())
            words2 = set(text2.split())

            if not words1 or not words2:
                return 0

            intersection = words1.intersection(words2)
            union = words1.union(words2)

            return len(intersection) / len(union) if union else 0
        except:
            return 0





    def extract_section_content_deduplicated(self, section_element):
        """提取section内容的强力去重版本"""
        try:
            content_parts = []
            seen_texts = set()
            seen_normalized = set()
            processed_elements = set()

            # 递归处理元素，避免嵌套重复
            def process_section_element(elem, depth=0):
                if depth > 2 or id(elem) in processed_elements:  # 限制递归深度
                    return

                processed_elements.add(id(elem))

                # 如果是容器元素，处理其直接子元素
                if elem.name in ['div', 'section', 'article']:
                    for child in elem.find_all(['p', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'], recursive=False):
                        process_section_element(child, depth + 1)
                    return

                # 处理文本内容
                text = elem.get_text().strip()
                if text and len(text) > 15:  # 过滤太短的文本
                    # 清理文本
                    text = re.sub(r'\s+', ' ', text)

                    # 移除编号和标题前缀
                    text = re.sub(r'^\d+[A-Za-z\s]*?(?=[A-Z][a-z])', '', text).strip()

                    # 标准化文本用于比较
                    normalized_text = re.sub(r'\s+', ' ', text.lower()).strip()

                    # 强力去重：多重检查
                    if normalized_text in seen_normalized:
                        return

                    # 检查是否与已有文本过于相似
                    is_duplicate = False
                    for seen_text in seen_normalized:
                        similarity = self.calculate_text_similarity(normalized_text, seen_text)
                        if similarity > 0.75:  # 75%相似度认为是重复
                            is_duplicate = True
                            break

                    if not is_duplicate and len(text) > 20:  # 确保文本有意义
                        content_parts.append(text)
                        seen_texts.add(text)
                        seen_normalized.add(normalized_text)

            # 处理section中的所有相关元素
            process_section_element(section_element)

            # 最终去重和清理
            if content_parts:
                # 再次去重，防止任何遗漏
                final_parts = []
                final_seen = set()

                for part in content_parts:
                    normalized = re.sub(r'\s+', ' ', part.lower()).strip()
                    if normalized not in final_seen and len(normalized) > 20:
                        final_parts.append(part)
                        final_seen.add(normalized)

                full_content = '\n\n'.join(final_parts)

                # 移除开头的"First Steps"标题
                full_content = re.sub(r'^First Steps\s*', '', full_content, flags=re.IGNORECASE).strip()

                # 清理多余的换行和空格
                full_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', full_content)
                full_content = re.sub(r'[ \t]+', ' ', full_content)

                return full_content.strip()

            return ""
        except Exception as e:
            print(f"提取去重内容时发生错误: {str(e)}")
            return ""

    def calculate_text_similarity(self, text1, text2):
        """计算两个文本的相似度"""
        try:
            # 简单的相似度计算：基于共同单词的比例
            words1 = set(text1.lower().split())
            words2 = set(text2.lower().split())

            if not words1 or not words2:
                return 0

            intersection = words1.intersection(words2)
            union = words1.union(words2)

            return len(intersection) / len(union) if union else 0
        except Exception:
            return 0

    def extract_causes_sections(self, soup):
        """提取Causes部分内容 - 基于真实页面结构"""
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
                        if content_section:
                            content = self.extract_section_content(content_section)

                        causes.append({
                            "number": number,
                            "title": title,
                            "content": content
                        })

                        if self.verbose:
                            print(f"提取Cause {number}: {title} ({len(content)} 字符)")

            return causes
        except Exception as e:
            print(f"提取Causes时发生错误: {str(e)}")
            return []

    def extract_section_content(self, section_element):
        """提取单个section的内容 - 精确边界检测版本"""
        try:
            if not section_element:
                return ""

            if self.verbose:
                print(f"开始提取section内容，section ID: {section_element.get('id', 'unknown')}")

            # 创建section副本以避免修改原始内容
            from bs4 import BeautifulSoup
            section_copy = BeautifulSoup(str(section_element), 'html.parser')

            # 首先移除所有商业推广和指南推荐框
            self.remove_promotional_content_from_section(section_copy)

            # 提取主要文本内容
            content_parts = []
            seen_texts = set()

            # 查找主要内容元素，按优先级处理
            main_content_elements = []

            # 优先处理段落和列表
            for elem in section_copy.find_all(['p', 'ul', 'ol'], recursive=True):
                if not self.is_element_in_promotional_area(elem):
                    main_content_elements.append(elem)

            # 如果没有找到段落和列表，查找div中的文本
            if not main_content_elements:
                for elem in section_copy.find_all(['div'], recursive=True):
                    if not self.is_element_in_promotional_area(elem) and elem.get_text().strip():
                        main_content_elements.append(elem)

            # 处理找到的内容元素
            for elem in main_content_elements:
                text = elem.get_text().strip()
                if text and len(text) > 20:  # 过滤太短的文本
                    # 清理文本
                    text = re.sub(r'\s+', ' ', text)

                    # 移除编号前缀
                    text = re.sub(r'^\d+[A-Za-z\s]*?(?=[A-Z][a-z])', '', text).strip()

                    # 检查是否是商业内容
                    if not self.is_commercial_text(text):
                        # 去重检查
                        normalized_text = text.lower().strip()
                        if normalized_text not in seen_texts and len(text) > 30:
                            content_parts.append(text)
                            seen_texts.add(normalized_text)

            # 使用全面去重函数处理内容
            if content_parts:
                # 使用改进的去重逻辑
                deduplicated_parts = self.comprehensive_content_deduplication(content_parts)
                if deduplicated_parts:
                    full_content = '\n\n'.join(deduplicated_parts)
                    full_content = full_content.strip()

                    if self.verbose:
                        print(f"去重后内容长度: {len(full_content)} 字符")
                    return full_content
                else:
                    print("去重后无有效内容")
                    return ""
            else:
                print("未找到有效内容")
                return ""

        except Exception as e:
            print(f"提取section内容时发生错误: {str(e)}")
            return ""

    def remove_promotional_content_from_section(self, section_soup):
        """从section中移除所有推广内容"""
        try:
            # 移除指南推荐框（包含"View Guide"按钮的框）
            guide_boxes = section_soup.find_all(['div', 'a'],
                                               string=lambda text: text and 'view guide' in text.lower())
            for box in guide_boxes:
                # 向上查找包含整个推荐框的容器
                container = box
                for _ in range(5):  # 最多向上查找5层
                    parent = container.parent
                    if not parent:
                        break
                    # 检查是否是推荐框容器
                    if self.is_guide_recommendation_container(parent):
                        container = parent
                    else:
                        break
                if container:
                    container.decompose()

            # 移除产品购买框（包含价格和"Buy"按钮的框）
            buy_boxes = section_soup.find_all(['div', 'a'],
                                            string=lambda text: text and 'buy' in text.lower())
            for box in buy_boxes:
                container = box
                for _ in range(5):
                    parent = container.parent
                    if not parent:
                        break
                    if self.is_product_purchase_container(parent):
                        container = parent
                    else:
                        break
                if container:
                    container.decompose()

            # 移除"Find Your Parts"框
            parts_boxes = section_soup.find_all(['div', 'a'],
                                              string=lambda text: text and 'find your parts' in text.lower())
            for box in parts_boxes:
                container = box
                for _ in range(5):
                    parent = container.parent
                    if not parent:
                        break
                    if self.is_parts_finder_container(parent):
                        container = parent
                    else:
                        break
                if container:
                    container.decompose()

            # 移除包含价格信息的元素
            import re
            price_elements = section_soup.find_all(string=re.compile(r'[\$€£¥]\s*\d+\.?\d*'))
            for elem in price_elements:
                if elem.parent:
                    # 向上查找包含价格的容器
                    container = elem.parent
                    for _ in range(3):
                        if container.parent and len(container.get_text().strip()) < 200:
                            container = container.parent
                        else:
                            break
                    container.decompose()

        except Exception as e:
            print(f"移除推广内容时发生错误: {str(e)}")

    def is_guide_recommendation_container(self, element):
        """检查是否是指南推荐容器"""
        try:
            text = element.get_text().lower()
            # 检查是否包含指南推荐的特征
            has_guide_text = any(keyword in text for keyword in [
                'view guide', 'how to', 'minutes', 'very easy', 'easy', 'moderate', 'difficult'
            ])
            has_time_info = any(time_word in text for time_word in [
                'minute', 'hour', 'very easy', 'easy', 'difficult', 'moderate'
            ])
            # 推荐框通常文本较短且包含特定模式
            return has_guide_text and has_time_info and len(text) < 300
        except Exception:
            return False

    def is_product_purchase_container(self, element):
        """检查是否是产品购买容器"""
        try:
            text = element.get_text().lower()
            import re
            has_price = bool(re.search(r'[\$€£¥]\s*\d+\.?\d*', text))
            has_buy = 'buy' in text
            has_reviews = bool(re.search(r'\d+\.?\d*\s*(reviews?|stars?)', text))
            # 购买框通常包含价格、购买按钮或评价信息
            return (has_price or has_buy or has_reviews) and len(text) < 200
        except Exception:
            return False

    def is_parts_finder_container(self, element):
        """检查是否是配件查找容器"""
        try:
            text = element.get_text().lower()
            has_parts_text = any(keyword in text for keyword in [
                'find your parts', 'select my model', 'compatible replacement'
            ])
            return has_parts_text and len(text) < 300
        except Exception:
            return False

    def is_element_in_promotional_area(self, element):
        """检查元素是否在推广区域内"""
        try:
            # 向上遍历DOM树检查是否在推广容器中
            current = element
            while current and current.name:
                if (self.is_guide_recommendation_container(current) or
                    self.is_product_purchase_container(current) or
                    self.is_parts_finder_container(current)):
                    return True
                current = current.parent
            return False
        except Exception:
            return False

    def is_commercial_text(self, text):
        """检查文本是否是商业内容"""
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

    def get_section_title(self, section_element):
        """获取section的标题"""
        try:
            # 查找section内的标题元素
            title_elem = section_element.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if title_elem:
                return title_elem.get_text().strip()
            return ""
        except Exception:
            return ""



    def extract_troubleshooting_images_new(self, soup):
        """提取troubleshooting页面的图片 - 新版本，只从正文内容区域提取"""
        images = []
        seen_urls = set()

        try:
            # 首先尝试找到主要内容区域
            main_content = self.find_main_content_area(soup)
            if main_content:
                img_elements = main_content.find_all('img')
            else:
                # 如果找不到主要内容区域，从整个页面查找但加强过滤
                img_elements = soup.find_all('img')

            for img in img_elements:
                # 检查是否在商业内容区域
                if self.is_in_commercial_area(img):
                    continue

                src = img.get('src', '') or img.get('data-src', '')
                if src and src not in seen_urls:
                    # 过滤掉小图标、logo和商业图片
                    if any(skip in src.lower() for skip in [
                        'icon', 'logo', 'flag', 'avatar', 'ad', 'banner',
                        'promo', 'cart', 'buy', 'purchase', 'shop', 'header',
                        'footer', 'nav', 'menu', 'sidebar'
                    ]):
                        continue

                    # 确保是完整URL
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = 'https://www.ifixit.com' + src

                    # 获取图片描述
                    alt_text = img.get('alt', '').strip()
                    title_text = img.get('title', '').strip()
                    description = alt_text or title_text or ""

                    # 排除商业描述
                    if any(commercial in description.lower() for commercial in [
                        'buy', 'purchase', 'cart', 'shop', 'price', 'review',
                        'advertisement', 'sponsor'
                    ]):
                        continue

                    images.append({
                        "url": src,
                        "description": description
                    })
                    seen_urls.add(src)

            print(f"提取到 {len(images)} 个有效图片")
            return images
        except Exception as e:
            print(f"提取图片时发生错误: {str(e)}")
            return []



    def extract_troubleshooting_videos_new(self, soup):
        """提取troubleshooting页面的视频链接 - 新版本，只从正文内容区域提取"""
        videos = []
        seen_urls = set()

        try:
            # 首先尝试找到主要内容区域
            main_content = self.find_main_content_area(soup)
            if main_content:
                video_elements = main_content.find_all(['video', 'iframe', 'embed'])
                links = main_content.find_all('a', href=True)
            else:
                # 如果找不到主要内容区域，从整个页面查找但加强过滤
                video_elements = soup.find_all(['video', 'iframe', 'embed'])
                links = soup.find_all('a', href=True)

            # 处理视频元素
            for elem in video_elements:
                # 检查是否在商业内容区域
                if self.is_in_commercial_area(elem):
                    continue

                src = elem.get('src', '') or elem.get('data-src', '')
                if src and src not in seen_urls and self.is_valid_video_url(src):
                    # 确保是完整URL
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = 'https://www.ifixit.com' + src

                    # 获取视频描述
                    title = elem.get('title', '').strip()

                    videos.append({
                        "url": src,
                        "title": title
                    })
                    seen_urls.add(src)

            # 查找YouTube等视频链接
            for link in links:
                # 检查是否在商业内容区域
                if self.is_in_commercial_area(link):
                    continue

                href = link.get('href', '')
                if href and href not in seen_urls and self.is_valid_video_url(href):
                    link_text = link.get_text().strip()

                    # 排除商业链接文本
                    if any(commercial in link_text.lower() for commercial in [
                        'buy', 'purchase', 'cart', 'shop', 'price', 'review',
                        'advertisement', 'sponsor'
                    ]):
                        continue

                    videos.append({
                        "url": href,
                        "title": link_text
                    })
                    seen_urls.add(href)

            print(f"提取到 {len(videos)} 个有效视频")
            return videos
        except Exception as e:
            print(f"提取视频时发生错误: {str(e)}")
            return []

    def find_main_content_area(self, soup):
        """查找页面的主要内容区域"""
        try:
            # 尝试多种方式找到主要内容区域
            content_selectors = [
                'main',
                '[role="main"]',
                '.main-content',
                '.content',
                '.article-content',
                '.page-content',
                '#content',
                '.troubleshooting-content'
            ]

            for selector in content_selectors:
                content_area = soup.select_one(selector)
                if content_area:
                    return content_area

            # 如果找不到明确的内容区域，尝试找到包含最多文本的区域
            all_divs = soup.find_all('div')
            max_text_length = 0
            best_div = None

            for div in all_divs:
                # 排除明显的导航、头部、尾部区域
                if any(class_name in str(div.get('class', [])).lower() for class_name in [
                    'nav', 'header', 'footer', 'sidebar', 'menu', 'ad', 'banner'
                ]):
                    continue

                text_length = len(div.get_text().strip())
                if text_length > max_text_length:
                    max_text_length = text_length
                    best_div = div

            return best_div

        except Exception as e:
            print(f"查找主要内容区域时发生错误: {str(e)}")
            return None

    def is_in_commercial_area(self, element):
        """检查元素是否在商业内容区域"""
        try:
            # 向上遍历DOM树，检查父元素
            current = element
            while current and current.name:
                # 检查class和id
                classes = current.get('class', [])
                element_id = current.get('id', '')

                # 商业内容的常见标识
                commercial_indicators = [
                    'ad', 'advertisement', 'promo', 'promotion', 'banner',
                    'shop', 'buy', 'purchase', 'cart', 'price', 'product',
                    'sponsor', 'affiliate', 'commercial', 'marketing'
                ]

                # 检查class名称
                for class_name in classes:
                    if any(indicator in class_name.lower() for indicator in commercial_indicators):
                        return True

                # 检查id
                if any(indicator in element_id.lower() for indicator in commercial_indicators):
                    return True

                # 检查data属性
                for attr_name, attr_value in current.attrs.items():
                    if attr_name.startswith('data-') and isinstance(attr_value, str):
                        if any(indicator in attr_value.lower() for indicator in commercial_indicators):
                            return True

                # 检查是否在商业推广容器中 - 更精确的识别
                if current.name in ['div', 'section', 'article', 'aside']:
                    text_content = current.get_text().strip()
                    text_lower = text_content.lower()

                    # 检查是否是典型的商业推广框框
                    # 1. 包含价格信息的短文本框
                    import re
                    has_price = bool(re.search(r'[\$€£¥]\s*\d+\.?\d*', text_content))
                    has_buy_button = any(buy_word in text_lower for buy_word in ['buy', 'purchase', 'add to cart', 'shop now'])
                    has_rating = bool(re.search(r'\d+\.?\d*\s*(reviews?|stars?)', text_lower))

                    # 如果是短文本且包含商业元素，认为是商业推广框
                    if (len(text_content) < 300 and  # 商业推广框通常文本较短
                        (has_price or has_buy_button or has_rating) and
                        any(commercial in text_lower for commercial in [
                            'buy', 'purchase', 'cart', 'price', 'review', 'rating',
                            'add to cart', 'shop now', 'order', 'checkout'
                        ])):
                        return True

                    # 2. 特别检查iFixit商品推广框的特征
                    # 这些框框通常包含产品名称、价格、评分和购买按钮
                    if (len(text_content) < 400 and
                        has_price and has_buy_button and
                        ('ifixit' in text_lower or 'tweezers' in text_lower or 'kit' in text_lower or 'set' in text_lower)):
                        return True

                    # 3. 检查是否包含典型的商品推广文本模式
                    # 例如："Precision Tweezers Set $9.95 4.9 213 reviews Buy"
                    if (len(text_content) < 200 and
                        has_price and has_rating and has_buy_button):
                        return True

                current = current.parent

            return False

        except Exception as e:
            print(f"检查商业内容区域时发生错误: {str(e)}")
            return False

    def is_in_guide_promotional_area(self, element):
        """检查元素是否在指南推广区域（如红框中的指南链接）"""
        try:
            # 向上遍历DOM树，检查父元素
            current = element
            while current and current.name:
                # 检查是否在指南推广容器中
                classes = current.get('class', [])
                element_id = current.get('id', '')

                # 更精确的指南推广区域标识，避免误过滤正文图片
                guide_promo_indicators = [
                    'related-guide', 'guide-recommendation', 'guide-promo',
                    'suggested-guide', 'guide-card', 'guide-tile',
                    'guide-thumbnail', 'guide-preview', 'guide-link-box'
                ]

                # 检查class名称 - 需要更精确匹配
                for class_name in classes:
                    class_lower = class_name.lower()
                    if any(indicator in class_lower for indicator in guide_promo_indicators):
                        return True
                    # 检查是否是明确的推广容器
                    if ('guide' in class_lower and
                        any(promo in class_lower for promo in ['card', 'box', 'tile', 'promo', 'recommend'])):
                        return True

                # 检查id
                element_id_lower = element_id.lower()
                if any(indicator in element_id_lower for indicator in guide_promo_indicators):
                    return True

                # 检查是否在明确的指南推广链接中
                if current.name == 'a':
                    href = current.get('href', '')
                    link_text = current.get_text().strip().lower()
                    # 只有当链接指向指南页面且包含推广性质的词汇时才认为是推广区域
                    if ('/Guide/' in href and
                        any(promo_word in link_text for promo_word in [
                            'view guide', 'replacement', 'repair guide'
                        ]) and any(time_indicator in link_text for time_indicator in [
                            'minute', 'hour', 'very easy', 'easy', 'difficult', 'moderate'
                        ])):
                        return True

                current = current.parent

            return False

        except Exception as e:
            print(f"检查指南推广区域时发生错误: {str(e)}")
            return False

    def is_valid_video_url(self, url):
        """检查URL是否是有效的视频链接"""
        if not url:
            return False

        url_lower = url.lower()

        # 排除明显不是视频的URL
        invalid_patterns = [
            'googletagmanager.com',
            'google-analytics.com',
            'facebook.com/tr',
            'doubleclick.net',
            'googlesyndication.com',
            'adsystem.com',
            '/ns.html',
            'gtm-',
            'analytics',
            'tracking'
        ]

        for pattern in invalid_patterns:
            if pattern in url_lower:
                return False

        # 检查是否是有效的视频域名
        valid_video_domains = [
            'youtube.com/watch',
            'youtube.com/embed',
            'youtu.be/',
            'vimeo.com/',
            'dailymotion.com/',
            'wistia.com/',
            'brightcove.com/',
            'jwplayer.com/'
        ]

        # 如果包含视频域名，进一步验证
        for domain in valid_video_domains:
            if domain in url_lower:
                # 对于YouTube playlist，需要特别检查
                if 'youtube.com/playlist' in url_lower:
                    return False  # 排除播放列表
                if 'youtube.com/user' in url_lower:
                    return False  # 排除用户页面
                if 'youtube.com/channel' in url_lower:
                    return False  # 排除频道页面
                return True

        # 检查是否是嵌入式视频
        if any(ext in url_lower for ext in ['.mp4', '.webm', '.ogg', '.mov', '.avi']):
            return True

        return False



    def extract_causes_from_numbered_text(self, text):
        """从编号文本中提取原因列表 - 基于实际格式"""
        causes = []

        try:
            # 基于调试结果，格式是：1Overheating2Dusty Internals or Obstructed Vents3Software...
            # 使用更精确的模式
            pattern = r'(\d+)([A-Z][^0-9]*?)(?=\d+[A-Z]|$)'
            matches = re.findall(pattern, text)

            for number, cause_text in matches:
                # 清理原因文本
                cause_text = cause_text.strip()
                cause_text = re.sub(r'\s+', ' ', cause_text)

                # 过滤掉太短的文本
                if len(cause_text) > 3 and len(cause_text) < 100:
                    causes.append({
                        "title": cause_text,
                        "content": ""
                    })

        except Exception as e:
            print(f"提取编号原因时发生错误: {str(e)}")

        return causes

    def extract_numbered_causes_from_text(self, text):
        """从文本中提取编号的原因列表"""
        causes = []

        try:
            # 查找编号模式 (1 xxx, 2 xxx, 3 xxx等)
            # 使用更宽松的模式匹配
            patterns = [
                r'(\d+)\s+([A-Z][^0-9]*?)(?=\d+\s+[A-Z]|$)',  # 数字 + 大写字母开头的文本
                r'(\d+)\.\s*([A-Z][^0-9]*?)(?=\d+\.|$)',      # 数字. + 文本
                r'(\d+)\)\s*([A-Z][^0-9]*?)(?=\d+\)|$)',      # 数字) + 文本
            ]

            for pattern in patterns:
                matches = re.findall(pattern, text, re.MULTILINE)
                if matches and len(matches) >= 3:  # 至少找到3个项目才认为是有效的列表
                    for number, cause_text in matches:
                        # 清理原因文本
                        cause_text = cause_text.strip()
                        cause_text = re.sub(r'\s+', ' ', cause_text)

                        # 过滤掉太短或包含CSS的文本
                        if (len(cause_text) > 5 and len(cause_text) < 200 and
                            not any(css_word in cause_text.lower() for css_word in ['css', 'webkit', 'chakra', 'transition', 'padding'])):

                            causes.append({
                                "title": cause_text,
                                "content": ""
                            })

                    if causes:  # 如果找到了有效的原因列表，就返回
                        break

        except Exception as e:
            print(f"提取编号原因时发生错误: {str(e)}")

        return causes





    def get_text_content_after_element(self, element):
        """获取元素后的文本内容"""
        try:
            # 获取元素及其后续兄弟元素的文本
            content_parts = []

            # 获取当前元素的文本
            current_text = element.get_text().strip()
            if current_text:
                content_parts.append(current_text)

            # 获取后续兄弟元素的文本
            current = element.next_sibling
            count = 0
            while current and count < 10:  # 限制查找范围
                if hasattr(current, 'get_text'):
                    text = current.get_text().strip()
                    if text and len(text) > 10:
                        content_parts.append(text)
                        count += 1
                current = current.next_sibling

            # 合并文本
            full_text = ' '.join(content_parts)
            full_text = re.sub(r'\s+', ' ', full_text)

            return full_text[:500]  # 限制长度

        except Exception as e:
            print(f"获取文本内容时发生错误: {str(e)}")
            return ""

    def extract_generic_sections(self, soup):
        """通用的章节提取方法"""
        sections = []

        try:
            # 查找主要内容区域，排除CSS和脚本
            main_content = soup.select_one("main, .content, .main-content, #content")
            if not main_content:
                main_content = soup.body

            if main_content:
                # 移除脚本和样式元素
                for script in main_content.select("script, style, noscript"):
                    script.decompose()

                # 查找文本内容
                text_content = main_content.get_text()

                # 简单的文本分段
                if text_content and len(text_content) > 100:
                    # 清理文本
                    clean_text = re.sub(r'\s+', ' ', text_content).strip()

                    sections.append({
                        "title": "Content",
                        "content": clean_text[:1000],  # 限制长度
                        "subsections": []
                    })

        except Exception as e:
            print(f"通用章节提取时发生错误: {str(e)}")

        return sections

    def should_skip_heading(self, heading_text):
        """判断是否应该跳过某个标题"""
        skip_keywords = [
            "Related Problems", "Related Answers", "Related Pages",
            "Comments", "Add Comment", "Tools", "Parts",
            "iFixit", "Troubleshooting", "css-", "self.__next_f"
        ]

        heading_lower = heading_text.lower()

        # 跳过包含特定关键词的标题
        for keyword in skip_keywords:
            if keyword.lower() in heading_lower:
                return True

        # 跳过太短或太长的标题
        if len(heading_text) < 3 or len(heading_text) > 100:
            return True

        # 跳过看起来像CSS或JavaScript的内容
        if heading_text.startswith('.') or heading_text.startswith('self.'):
            return True

        return False

    def get_content_after_heading(self, heading):
        """获取标题后的内容元素"""
        content_elements = []
        current = heading.next_sibling

        # 收集标题后的内容，直到遇到下一个同级或更高级的标题
        while current:
            if hasattr(current, 'name'):
                # 如果遇到同级或更高级的标题，停止
                if (current.name and current.name.startswith('h') and
                    int(current.name[1:]) <= int(heading.name[1:])):
                    break
                content_elements.append(current)
            current = current.next_sibling

        return content_elements

    def is_list_section(self, heading_text, content_elements):
        """判断是否是列表章节（如Causes）"""
        list_indicators = ["causes", "steps", "solutions", "problems", "issues"]

        if any(indicator in heading_text.lower() for indicator in list_indicators):
            return True

        # 检查内容中是否有编号列表
        for element in content_elements:
            if hasattr(element, 'select'):
                numbered_items = element.select("ol li, .numbered-list li, [class*='step']")
                if numbered_items:
                    return True

        return False

    def extract_numbered_list(self, content_elements):
        """提取编号列表项"""
        subsections = []

        for element in content_elements:
            if hasattr(element, 'select'):
                # 查找编号列表项
                list_items = element.select("ol li, .numbered-list li, [class*='step'], [class*='cause']")

                for item in list_items:
                    item_text = item.get_text().strip()
                    if item_text and len(item_text) > 3:
                        # 清理文本
                        item_text = re.sub(r'\s+', ' ', item_text)
                        subsections.append({
                            "title": item_text,
                            "content": ""
                        })

        return subsections

    def extract_section_text(self, content_elements):
        """提取章节的文本内容"""
        text_parts = []

        for element in content_elements:
            if hasattr(element, 'get_text'):
                text = element.get_text().strip()
                if text:
                    text_parts.append(text)

        # 合并文本并清理
        full_text = ' '.join(text_parts)
        full_text = re.sub(r'\s+', ' ', full_text)

        return full_text

    def find_troubleshooting_section(self, soup):
        """查找Troubleshooting区域，排除Related Pages - 改进版本，更准确地识别真正的Troubleshooting内容"""
        print("开始查找Troubleshooting区域...")

        # 方法1: 直接查找包含故障排除内容的主要区域
        # 查找包含多个故障原因的区域（如Overheating, Software Corruption等）
        main_content_areas = soup.find_all(['main', 'article', 'div', 'section'])

        for area in main_content_areas:
            area_text = area.get_text().lower()
            # 检查是否包含多个故障排除相关的关键词
            troubleshooting_indicators = [
                'overheating', 'dusty internals', 'software corruption', 'malware',
                'poor heat transfer', 'faulty fan', 'sensor data', 'logic board',
                'first steps', 'before undertaking', 'fundamentals'
            ]

            indicator_count = sum(1 for indicator in troubleshooting_indicators if indicator in area_text)
            if indicator_count >= 2:  # 至少包含2个相关指标
                print(f"通过内容分析找到故障排除区域，指标数量: {indicator_count}")
                # 排除Related Pages区域
                filtered_section = self.exclude_related_pages(area)
                if filtered_section and len(filtered_section.get_text().strip()) > 500:  # 确保内容足够丰富
                    print("成功找到并验证Troubleshooting区域")
                    return filtered_section

        # 方法2: 查找明确的Troubleshooting标题
        troubleshooting_keywords = [
            "Troubleshooting", "troubleshooting", "TROUBLESHOOTING",
            "故障排除", "故障", "问题排除", "疑难解答",
            "Common Problems", "Known Issues", "Problems", "Issues",
            "Repair", "Fix", "Solutions"
        ]

        troubleshooting_sections = []
        for keyword in troubleshooting_keywords:
            # 查找包含关键词的文本节点，但排除head元素
            headers = soup.find_all(string=lambda text: text and keyword in text)
            for header in headers:
                # 检查是否在head元素中，如果是则跳过
                if header.find_parent('head'):
                    continue

                # 检查是否是标题文本（不是正文中的普通文本）
                if header and hasattr(header, 'strip'):
                    header_text = header.strip()
                    # 确保是标题而不是正文中的词汇，且不是"Related Problems"
                    if (len(header_text) < 100 and  # 标题通常较短
                        'related' not in header_text.lower() and  # 排除Related Problems
                        (header_text.lower().startswith(keyword.lower()) or
                         header_text.lower() == keyword.lower() or
                         header_text.lower().endswith(keyword.lower()))):
                        troubleshooting_sections.append(header)

        print(f"找到 {len(troubleshooting_sections)} 个可能的Troubleshooting标题")

        # 处理找到的Troubleshooting标题
        for i, header in enumerate(troubleshooting_sections):
            print(f"处理第 {i+1} 个标题: {header.strip()[:50]}...")

            # 查找标题的容器元素，但排除head元素
            title_container = self.find_title_container(header)
            if title_container and title_container.name != 'head':
                print(f"找到标题容器: {title_container.name}, 类: {title_container.get('class', [])}")

                # 查找Troubleshooting内容区域
                content_section = self.find_content_after_title(title_container)
                if content_section:
                    print(f"找到内容区域，长度: {len(content_section.get_text())}")

                    # 验证内容是否真的是Troubleshooting相关，且不是Related Problems
                    content_text = content_section.get_text().lower()
                    if (self.validate_troubleshooting_content(content_section) and
                        'related problems' not in content_text and
                        len(content_section.get_text().strip()) > 500):  # 确保内容足够丰富
                        # 排除Related Pages区域
                        filtered_section = self.exclude_related_pages(content_section)
                        if filtered_section and len(filtered_section.get_text().strip()) > 500:
                            print("成功找到并验证Troubleshooting区域")
                            return filtered_section
                        else:
                            print("过滤后内容太少，继续查找...")

        # 方法3: 如果没有找到明确的标题，查找页面结构中的Troubleshooting区域
        print("尝试通过页面结构查找Troubleshooting区域...")
        structural_section = self.find_troubleshooting_by_structure(soup)
        if structural_section:
            return structural_section

        print("未找到合适的Troubleshooting区域")
        return None

    def find_title_container(self, header_text):
        """查找标题文本的容器元素"""
        parent = header_text.parent
        title_container = None

        # 向上查找标题容器，最多查找5层
        for level in range(5):
            if parent and parent.name:
                # 检查是否是标题元素
                if (parent.name.startswith('h') or  # h1, h2, h3等
                    any('heading' in str(cls).lower() for cls in parent.get('class', [])) or
                    any('title' in str(cls).lower() for cls in parent.get('class', [])) or
                    parent.name in ['div', 'section'] and
                    any(cls in str(parent.get('class', [])).lower() for cls in ['header', 'title', 'heading'])):
                    title_container = parent
                    break
            parent = parent.parent if parent else None

        return title_container

    def validate_troubleshooting_content(self, content_section):
        """验证内容是否真的是Troubleshooting相关内容"""
        if not content_section:
            return False

        content_text = content_section.get_text().lower()

        # 检查是否包含Troubleshooting相关的关键词
        troubleshooting_indicators = [
            'problem', 'issue', 'fix', 'repair', 'solution', 'solve',
            'not working', 'broken', 'error', 'fault', 'malfunction',
            'troubleshoot', 'diagnose', 'check', 'test', 'replace',
            'won\'t', 'can\'t', 'doesn\'t', 'fails', 'stuck',
            '问题', '故障', '修复', '解决', '不工作', '损坏', '错误'
        ]

        # 计算匹配的关键词数量
        matches = sum(1 for keyword in troubleshooting_indicators if keyword in content_text)

        # 如果内容足够长且包含足够的相关关键词，认为是有效的Troubleshooting内容
        return len(content_text) > 100 and matches >= 2

    def find_troubleshooting_by_structure(self, soup):
        """通过页面结构查找Troubleshooting区域"""
        # 查找可能包含Troubleshooting内容的结构元素
        potential_containers = soup.find_all(['div', 'section', 'article'],
                                           class_=lambda x: x and any(keyword in str(x).lower()
                                           for keyword in ['troubleshoot', 'problem', 'issue', 'repair']))

        for container in potential_containers:
            if self.validate_troubleshooting_content(container):
                print(f"通过结构找到Troubleshooting区域: {container.name}, 类: {container.get('class', [])}")
                return self.exclude_related_pages(container)

        return None

    def find_content_after_title(self, title_container):
        """查找标题后的内容区域"""
        print(f"查找标题后的内容，标题容器: {title_container.name}")

        # 方法1: 查找下一个兄弟元素
        current = title_container
        for level in range(3):
            next_sibling = current.find_next_sibling()
            if next_sibling:
                # 检查是否是内容区域
                if (next_sibling.name in ['div', 'section', 'article', 'ul', 'ol', 'p'] and
                    len(next_sibling.get_text().strip()) > 30):  # 降低内容长度要求
                    print(f"找到兄弟元素内容区域: {next_sibling.name}, 内容长度: {len(next_sibling.get_text())}")
                    return next_sibling
            current = current.parent if current.parent else None
            if not current:
                break

        # 方法2: 查找父容器中标题后的所有内容
        if title_container.parent:
            parent = title_container.parent
            print(f"在父容器中查找内容: {parent.name}")

            # 获取所有子元素
            all_children = list(parent.children)
            title_found = False
            content_elements = []

            for child in all_children:
                if hasattr(child, 'name') and child.name:  # 是标签元素
                    if child == title_container:
                        title_found = True
                        continue

                    if title_found:
                        # 检查是否是下一个标题（停止收集）
                        if (child.name.startswith('h') or
                            any('heading' in str(cls).lower() for cls in child.get('class', []))):
                            # 检查是否是同级或更高级的标题
                            if (child.name <= title_container.name or
                                any(keyword in child.get_text().lower() for keyword in
                                    ["related pages", "see also", "相关页面"])):
                                print(f"遇到下一个标题或Related Pages，停止收集: {child.name}")
                                break

                        content_elements.append(child)

            if content_elements:
                print(f"收集到 {len(content_elements)} 个内容元素")
                # 创建一个临时容器包含所有后续内容
                from bs4 import BeautifulSoup
                temp_soup = BeautifulSoup('<div></div>', 'html.parser')
                temp_container = temp_soup.div

                for content in content_elements:
                    # 复制元素而不是移动
                    temp_container.append(content.__copy__())

                if len(temp_container.get_text().strip()) > 30:
                    print(f"创建临时容器，内容长度: {len(temp_container.get_text())}")
                    return temp_container

        print("未找到合适的内容区域")
        return None

    def exclude_related_pages(self, content_section):
        """排除Related Pages区域"""
        if not content_section:
            return None

        print("开始排除Related Pages区域...")

        # 创建内容副本以避免修改原始内容
        from bs4 import BeautifulSoup
        content_copy = BeautifulSoup(str(content_section), 'html.parser')

        # 查找Related Pages标题并移除其后的内容
        related_keywords = ["related pages", "related", "see also", "相关页面", "另请参阅"]
        related_headers = content_copy.find_all(string=lambda text: text and
            any(keyword in text.lower() for keyword in related_keywords))

        print(f"找到 {len(related_headers)} 个可能的Related Pages标题")

        for i, header in enumerate(related_headers):
            print(f"处理第 {i+1} 个Related Pages标题: {header.strip()[:30]}...")

            # 找到Related Pages标题的容器
            header_parent = header.parent
            if header_parent:
                # 向上查找标题容器
                title_container = None
                for level in range(3):
                    if (header_parent.name and
                        (header_parent.name.startswith('h') or
                         any('heading' in str(cls).lower() for cls in header_parent.get('class', [])))):
                        title_container = header_parent
                        print(f"找到Related Pages标题容器: {header_parent.name}")
                        break
                    header_parent = header_parent.parent
                    if not header_parent:
                        break

                if title_container:
                    # 移除这个标题及其后的所有兄弟元素
                    elements_to_remove = [title_container]
                    current = title_container.find_next_sibling()
                    while current:
                        elements_to_remove.append(current)
                        current = current.find_next_sibling()

                    print(f"准备移除 {len(elements_to_remove)} 个Related Pages相关元素")
                    for element in elements_to_remove:
                        if element.parent:  # 确保元素还在DOM中
                            element.decompose()

        # 返回处理后的内容
        result = content_copy.find() if content_copy.contents else None
        if result and len(result.get_text().strip()) > 10:
            print(f"排除Related Pages后，剩余内容长度: {len(result.get_text())}")
            return result
        else:
            print("排除Related Pages后内容为空或太少")
            return content_section  # 如果过滤后没有内容，返回原始内容

    def remove_commercial_boxes(self, soup):
        """移除页面中的商业推广框框 - 基于HTML结构识别，特别针对指南推荐框"""
        if not soup:
            return soup

        print("开始移除商业推广框框...")
        removed_count = 0

        # 首先移除包含指南推荐的框框（如用户图片中显示的那种）
        # 这些框框通常包含图片、标题、时间估计和难度等级
        # 更精确地识别推荐框，避免误删主要内容
        guide_boxes = soup.find_all(['div', 'section', 'article', 'a'],
                                   class_=lambda x: x and any(cls in str(x).lower()
                                   for cls in ['guide', 'card', 'box', 'promo', 'recommendation', 'related']))

        for box in guide_boxes:
            box_text = box.get_text().strip()
            box_text_lower = box_text.lower()

            # 检查是否是推荐指南框的特征：
            # 1. 包含图片
            # 2. 文本较短（通常少于200字符）
            # 3. 包含时间估计和难度
            # 4. 包含"View Guide"按钮文本
            if (box.find('img') and  # 包含图片
                len(box_text) < 200 and  # 文本较短
                'view guide' in box_text_lower and  # 包含查看指南按钮
                ('minutes' in box_text_lower or 'easy' in box_text_lower)):  # 包含时间或难度
                print(f"移除指南推荐框: {box_text[:50]}...")
                box.decompose()
                removed_count += 1
                continue

        # 移除产品推荐框 - 通过特定的CSS类和结构识别
        commercial_selectors = [
            # 产品推荐框
            'div[class*="product"]',
            'div[class*="recommendation"]',
            'div[class*="purchase"]',
            'div[class*="buy"]',
            'div[class*="cart"]',
            'div[class*="price"]',
            # 指南推荐框
            'div[class*="guide-recommendation"]',
            'div[class*="related-guide"]',
            'a[href*="/Guide/"]',  # 指南链接
        ]

        for selector in commercial_selectors:
            try:
                elements = soup.select(selector)
                for element in elements:
                    # 检查是否是商业内容
                    if self.is_commercial_element(element):
                        element.decompose()
                        removed_count += 1
            except Exception:
                continue

        # 移除包含特定商业文本模式的元素（更精确的识别）
        all_elements = soup.find_all(['div', 'section', 'article', 'aside'])
        for element in all_elements:
            if element and element.parent:
                element_text = element.get_text().strip()
                element_text_lower = element_text.lower()

                # 检查是否是底部的推荐指南框（如用户图片中显示的）
                # 更严格的条件：必须同时满足多个特征
                if (len(element_text) < 200 and  # 推荐框通常文本很短
                    'view guide' in element_text_lower and  # 包含查看指南按钮
                    ('minutes' in element_text_lower or 'easy' in element_text_lower) and  # 包含时间或难度
                    element.find('img') and  # 包含图片
                    not any(main_content in element_text_lower for main_content in [
                        'overheating', 'dusty internals', 'software corruption', 'malware',
                        'poor heat transfer', 'faulty fan', 'sensor data', 'logic board'
                    ])):  # 不包含主要故障排除内容
                    print(f"移除底部推荐框: {element_text[:50]}...")
                    element.decompose()
                    removed_count += 1
                    continue

                # 检查是否是商品推广框（如Precision Tweezers Set的推广框）
                import re
                has_price = bool(re.search(r'[\$€£¥]\s*\d+\.?\d*', element_text))
                has_buy_button = any(buy_word in element_text_lower for buy_word in ['buy', 'purchase', 'add to cart'])
                has_rating = bool(re.search(r'\d+\.?\d*\s*(reviews?|stars?)', element_text_lower))

                # 如果是短文本且包含价格、评分和购买按钮，认为是商品推广框
                if (len(element_text) < 300 and
                    has_price and has_buy_button and has_rating and
                    not any(main_content in element_text_lower for main_content in [
                        'overheating', 'dusty internals', 'software corruption', 'malware',
                        'poor heat transfer', 'faulty fan', 'sensor data', 'logic board'
                    ])):
                    print(f"移除商品推广框: {element_text[:50]}...")
                    element.decompose()
                    removed_count += 1
                    continue

                # 检查是否包含典型的iFixit商品推广特征
                if (len(element_text) < 400 and
                    has_price and has_buy_button and
                    ('ifixit' in element_text_lower or 'tweezers' in element_text_lower or
                     'kit' in element_text_lower or 'set' in element_text_lower) and
                    not any(main_content in element_text_lower for main_content in [
                        'overheating', 'dusty internals', 'software corruption', 'malware',
                        'poor heat transfer', 'faulty fan', 'sensor data', 'logic board'
                    ])):
                    print(f"移除iFixit商品推广框: {element_text[:50]}...")
                    element.decompose()
                    removed_count += 1

        print(f"移除了 {removed_count} 个商业推广元素")
        return soup

    def is_commercial_element(self, element):
        """判断元素是否是商业内容，包括指南推荐框"""
        if not element:
            return False

        text = element.get_text().lower()

        # 商业内容关键词
        commercial_keywords = [
            'buy', 'purchase', 'price', '$', '€', '£', '¥',
            'view guide', 'find your parts', 'select my model',
            'quality guarantee', 'compatible replacement',
            'add to cart', 'reviews', 'rating', 'stars'
        ]

        # 指南推荐框特征关键词
        guide_recommendation_keywords = [
            'view guide', 'minutes', 'very easy', 'easy', 'moderate', 'difficult',
            'how to boot', 'how to use', 'replacement', 'repair guide'
        ]

        # 检查是否包含价格模式
        import re
        if re.search(r'[\$€£¥]\s*\d+\.?\d*', text):
            return True

        # 检查是否包含评分模式
        if re.search(r'\d+\.?\d*\s*(reviews?|stars?)', text):
            return True

        # 检查是否是指南推荐框（如用户图片中显示的）
        if (element.find('img') and  # 包含图片
            any(keyword in text for keyword in guide_recommendation_keywords) and
            len(text) < 300):  # 推荐框通常文本较短
            return True

        # 检查商业关键词
        keyword_count = sum(1 for keyword in commercial_keywords if keyword in text)

        # 如果包含多个商业关键词，认为是商业内容
        return keyword_count >= 2

    def extract_troubleshooting_text(self, content_section):
        """提取Troubleshooting区域的文本内容 - 改进版本，更准确地提取真正的故障排除内容"""
        if not content_section:
            return ""

        print("开始提取文本内容...")

        # 创建内容副本以避免修改原始内容
        from bs4 import BeautifulSoup
        content_copy = BeautifulSoup(str(content_section), 'html.parser')

        # 首先移除商业推广框框
        content_copy = self.remove_commercial_boxes(content_copy)

        # 排除不需要的元素 - 更全面的排除列表
        unwanted_selectors = [
            'nav', 'footer', 'header', 'aside',
            '.navigation', '.breadcrumb', '.sidebar', '.menu',
            'script', 'style', 'noscript',
            '.comments', '.comment', '.discussion', '.reply',
            '.social', '.share', '.rating', '.vote',
            '.advertisement', '.ad', '.ads', '.banner',
            '.translator-info', '.translation-info',
            '.edit-link', '.edit-button', '.edit-section',
            '.related-pages', '.see-also', '.external-links',
            '.user-info', '.author-info', '.meta-info',
            '.tags', '.categories', '.breadcrumbs',
            # 产品推荐和购买相关的元素
            '.product-card', '.product-box', '.product-recommendation',
            '.buy-button', '.purchase-button', '.add-to-cart',
            '.price', '.pricing', '.cost', '.shop', '.store',
            '.tool-recommendation', '.part-recommendation',
            '.compatible-parts', '.find-parts', '.select-model',
            # iFixit特定的产品推荐元素
            '.chakra-linkbox__overlay', '.chakra-stack',
            '.product-link', 'a[href*="/products/"]',
            '[class*="chakra-linkbox"]', '[class*="chakra-stack"]'
        ]

        for selector in unwanted_selectors:
            for element in content_copy.select(selector):
                element.decompose()

        # 移除包含导航内容的元素
        navigation_keywords = [
            '/cancel', 'fix your stuff', 'repair guides', 'answers forum',
            'teardowns', 'community', 'get involved', 'right to repair',
            'repairability', 'our manifesto', 'store', 'featured', 'tools',
            'parts', 'devices', 'news', 'learn', 'about', 'contact'
        ]

        elements_to_remove = []
        for element in content_copy.find_all():
            if hasattr(element, 'get_text'):
                text = element.get_text().lower().strip()
                # 如果元素包含多个导航关键词，则移除
                nav_count = sum(1 for keyword in navigation_keywords if keyword in text)
                if nav_count >= 3:  # 包含3个或更多导航关键词
                    elements_to_remove.append(element)

        for element in elements_to_remove:
            if element.parent:
                element.decompose()

        # 特别处理包含商业内容的元素 - 更保守的方法，只移除明确的商业元素
        import re
        elements_to_remove = []
        for element in content_copy.find_all():
            if hasattr(element, 'get_text'):
                text = element.get_text().strip()
                text_lower = text.lower()

                # 只移除明确的商业推广元素，避免误删主要内容
                # 检查是否是小的推广框（文本很短且包含商业内容）
                if (len(text) < 150 and  # 文本很短
                    any(pattern in text_lower for pattern in [
                        'view guide', 'buy', 'purchase', 'add to cart', 'checkout'
                    ])):
                    elements_to_remove.append(element)
                    continue

                # 检查是否包含价格信息（但文本很短）
                if (len(text) < 100 and
                    re.search(r'[\$€£¥]\s*\d+\.?\d*', text)):
                    elements_to_remove.append(element)
                    continue

                # 检查是否包含评分信息（但文本很短）
                if (len(text) < 100 and
                    re.search(r'\d+\.?\d*\s*(reviews?|stars?)', text_lower)):
                    elements_to_remove.append(element)
                    continue

        # 移除标记的元素
        for element in elements_to_remove:
            if element.parent:  # 确保元素还在DOM中
                element.decompose()

        # 排除评论和用户交互区域 - 通过文本内容识别
        unwanted_text_keywords = [
            '条评论', '添加评论', '回复', '发帖评论', '显示更多评论',
            '由衷感谢以下译者', '翻译', '编辑', '修改', '版本',
            'comments', 'add comment', 'reply', 'post comment', 'show more comments',
            'edit', 'modify', 'version', 'translate', 'translation',
            'login', 'register', 'sign up', 'sign in', 'logout',
            'cookie', 'privacy', 'terms', 'policy'
        ]

        for keyword in unwanted_text_keywords:
            for element in content_copy.find_all(string=lambda text: text and keyword in text.lower()):
                # 确保element有parent属性
                if not hasattr(element, 'parent'):
                    continue

                # 找到包含不需要关键词的父容器并移除
                parent = element.parent
                for _ in range(5):  # 向上查找最多5层
                    if parent and hasattr(parent, 'name') and parent.name in ['div', 'section', 'article', 'p']:
                        try:
                            # 检查是否整个容器都是不需要的内容
                            parent_text = parent.get_text().lower()
                            if len(parent_text) < 200 or any(kw in parent_text for kw in unwanted_text_keywords):
                                parent.decompose()
                                break
                        except Exception:
                            break
                    parent = parent.parent if parent and hasattr(parent, 'parent') else None

        # 获取文本内容，保持结构，专注于故障排除相关内容
        text_elements = []
        seen_texts = set()  # 用于去重
        seen_normalized_texts = set()  # 用于更强的去重

        # 优先处理有序的内容结构，但避免嵌套重复
        processed_elements = set()  # 记录已处理的元素
        content_elements = content_copy.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'li'], recursive=False)

        # 递归处理元素，但避免重复处理嵌套内容
        def process_element_recursively(element, depth=0):
            if depth > 3 or id(element) in processed_elements:  # 限制递归深度，避免重复处理
                return

            processed_elements.add(id(element))

            # 确保element是有效的Tag对象
            if not hasattr(element, 'get_text') or not hasattr(element, 'name'):
                return

            try:
                text = element.get_text().strip()
            except Exception:
                return

            # 基本过滤条件
            if not text or len(text) < 10:
                return

            # 跳过导航、菜单等元素
            try:
                element_classes = ' '.join(element.get('class', [])).lower()
                if any(skip_class in element_classes for skip_class in [
                    'nav', 'menu', 'header', 'footer', 'sidebar', 'breadcrumb',
                    'comment', 'social', 'ad', 'advertisement', 'banner'
                ]):
                    return
            except Exception:
                pass

            # 跳过明显不相关的内容
            if any(keyword in text.lower() for keyword in unwanted_text_keywords):
                return

            # 检查是否是有价值的故障排除内容
            if self.is_valuable_troubleshooting_text(text, element):
                # 强化去重 - 使用多种方法避免重复内容
                text_hash = hash(text)
                normalized_text = re.sub(r'\s+', ' ', text.lower()).strip()

                if text_hash in seen_texts or normalized_text in seen_normalized_texts:
                    return

                # 检查是否与已有文本过于相似
                is_similar = False
                for existing_text in seen_normalized_texts:
                    similarity = self.calculate_text_similarity(normalized_text, existing_text)
                    if similarity > 0.8:  # 80%相似度认为是重复
                        is_similar = True
                        break

                if is_similar:
                    return

                seen_texts.add(text_hash)
                seen_normalized_texts.add(normalized_text)

                # 格式化文本
                formatted_text = self.format_troubleshooting_text(text, element)
                if formatted_text and formatted_text.strip():
                    # 最后一道防线：移除商业内容
                    cleaned_text = self.remove_commercial_content(formatted_text.strip())
                    if cleaned_text:
                        text_elements.append(cleaned_text)

            # 如果当前元素没有直接的文本内容，递归处理子元素
            elif element.name in ['div', 'section', 'article'] and not text.strip():
                for child in element.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li'], recursive=False):
                    process_element_recursively(child, depth + 1)

        # 处理所有顶级元素
        for element in content_elements:
            process_element_recursively(element)

        # 合并文本，进行最终去重
        unique_texts = []
        seen_final = set()

        for text in text_elements:
            normalized = re.sub(r'\s+', ' ', text.lower()).strip()
            if normalized not in seen_final and len(normalized) > 15:
                unique_texts.append(text)
                seen_final.add(normalized)

        # 合并文本
        full_text = '\n\n'.join(unique_texts)

        # 清理文本格式
        full_text = re.sub(r'\n\s*\n\s*\n+', '\n\n', full_text)  # 清理多余换行
        full_text = re.sub(r'[ \t]+', ' ', full_text)  # 清理多余空格
        full_text = full_text.strip()

        print(f"提取到文本长度: {len(full_text)}")
        return full_text

    def is_valuable_troubleshooting_text(self, text, element):
        """判断文本是否是有价值的故障排除内容"""
        text_lower = text.lower()

        # 太短的文本通常不是有价值的内容
        if len(text) < 10:
            return False

        # 排除产品推荐和购买相关的内容 - 更精确的模式匹配
        commercial_patterns = [
            'buy', 'purchase', 'price', '$', '€', '£', '¥',
            'add to cart', 'checkout', 'order', 'shipping',
            'reviews', 'rating', 'stars', 'out of 5',
            'find your parts', 'select my model', 'compatible replacement',
            'backed by', 'quality guarantee', 'warranty'
        ]

        # 检查是否包含明确的商业内容
        if any(pattern in text_lower for pattern in commercial_patterns):
            return False

        # 检查是否是指南推荐框的特征文本（更精确的检测）
        # 只有当文本很短且同时包含多个推荐框特征时才排除
        if (len(text) < 150 and
            'view guide' in text_lower and
            any(pattern in text_lower for pattern in ['minutes', 'very easy', 'easy', 'moderate', 'difficult'])):
            return False

        # 排除包含价格信息的文本（如 $9.95, €15.99 等）
        import re
        if re.search(r'[\$€£¥]\s*\d+\.?\d*', text):
            return False

        # 排除评分信息（如 4.9213 reviews, 5 stars 等）
        if re.search(r'\d+\.?\d*\s*(reviews?|stars?|out of \d+)', text_lower):
            return False

        # 检查是否包含故障排除相关的关键词
        troubleshooting_keywords = [
            'problem', 'issue', 'fix', 'repair', 'solution', 'solve', 'check', 'test',
            'not working', 'broken', 'error', 'fault', 'malfunction', 'troubleshoot',
            'diagnose', 'replace', 'won\'t', 'can\'t', 'doesn\'t', 'fails', 'stuck',
            'slow', 'loud', 'hot', 'cold', 'dead', 'blank', 'black', 'white',
            'screen', 'display', 'battery', 'power', 'charge', 'boot', 'startup',
            'freeze', 'crash', 'restart', 'shutdown', 'overheat', 'noise',
            '问题', '故障', '修复', '解决', '不工作', '损坏', '错误', '检查', '测试',
            '更换', '无法', '不能', '失败', '卡住', '缓慢', '噪音', '过热', '死机'
        ]

        # 如果是标题元素，降低要求
        try:
            if hasattr(element, 'name') and element.name and element.name.startswith('h'):
                return any(keyword in text_lower for keyword in troubleshooting_keywords[:10])
        except Exception:
            pass

        # 对于普通文本，需要更多相关关键词
        keyword_count = sum(1 for keyword in troubleshooting_keywords if keyword in text_lower)
        return keyword_count >= 1 and len(text) >= 20

    def remove_commercial_content(self, text):
        """移除文本中的商业内容 - 最后一道防线"""
        if not text:
            return text

        import re

        # 移除产品推荐模式（产品名称 + 价格 + 评分 + 购买按钮）
        # 例如: "Precision Tweezers Set$9.954.9213 reviewsBuy"
        commercial_patterns = [
            r'Precision Tweezers Set\$[\d\.]+[\d\.]+\s*reviews?Buy',  # 特定产品
            r'[A-Za-z\s]+Set\$[\d\.]+[\d\.]+\s*reviews?Buy',         # 产品套装模式
            r'[A-Za-z\s]+\$[\d\.]+[\d\.]+\s*reviews?Buy',            # 一般产品模式
            r'\$[\d\.]+[\d\.]+\s*reviews?Buy',                       # 价格+评分+购买
            r'Precision Tweezers Set.*',                             # 移除从产品名开始的所有内容
            # 新增：更全面的商业内容模式
            r'[A-Za-z\s]+\$\d+\.?\d*\s*\d+\.?\d*\s*\d+\s*reviews?Buy',  # 产品+价格+评分+购买
            r'[A-Za-z\s]+(Fans?|Cables?|Batteries?|Motherboards?|Screens?|Storage)\s*Find compatible replacement.*',  # 配件推荐
            r'Find compatible replacement parts.*',  # 配件查找
            r'All parts and fix kits are backed by.*',  # 质量保证
            r'Select my model.*',  # 选择型号
            r'Find Your Parts.*',  # 查找配件
        ]

        # 新增：移除指南推荐框内容模式
        # 例如: "How to Boot a Mac Into Safe Mode5 minutesVery easyView Guide"
        guide_recommendation_patterns = [
            # 精确匹配实际出现的模式
            r'How to Boot a Mac Into Safe Mode\s*5\s*minutes\s*Very\s*easy\s*View\s*Guide',  # 具体示例
            r'How to use Internet Recovery to install macOS to a new SSD\s*30\s*minutes\s*-\s*1\s*hour\s*Very\s*easy\s*View\s*Guide',  # 具体示例
            r'How to Recover Data From a MacBook\s*No\s*estimate\s*Moderate\s*View\s*Guide',  # 具体示例
            # 通用模式
            r'How to [^\.]+\d+\s*minutes?\s*(Very\s*easy|Easy|Moderate|Difficult)\s*View\s*Guide',  # 标准指南推荐
            r'How to [^\.]+\d+\s*minutes?\s*-\s*\d+\s*hours?\s*(Very\s*easy|Easy|Moderate|Difficult)\s*View\s*Guide',  # 带时间范围的
            r'How to [^\.]+No\s*estimate\s*(Very\s*easy|Easy|Moderate|Difficult)\s*View\s*Guide',  # 无时间估计的
            r'[A-Za-z\s]+\d+\s*minutes?\s*(Very\s*easy|Easy|Moderate|Difficult)\s*View\s*Guide',  # 一般模式
            r'[A-Za-z\s]+\d+\s*minutes?\s*-\s*\d+\s*hours?\s*(Very\s*easy|Easy|Moderate|Difficult)\s*View\s*Guide',  # 带时间范围
            r'[A-Za-z\s]+No\s*estimate\s*(Very\s*easy|Easy|Moderate|Difficult)\s*View\s*Guide',  # 无时间估计
            r'\d+\s*minutes?\s*(Very\s*easy|Easy|Moderate|Difficult)\s*View\s*Guide',  # 简化模式
            r'\d+\s*minutes?\s*-\s*\d+\s*hours?\s*(Very\s*easy|Easy|Moderate|Difficult)\s*View\s*Guide',  # 时间范围简化
            r'No\s*estimate\s*(Very\s*easy|Easy|Moderate|Difficult)\s*View\s*Guide',  # 无估计简化
            # 移除连在一起的模式（没有空格分隔）
            r'[A-Za-z\s]+\d+minutes(Very)?easyView Guide',  # 连续文本
            r'[A-Za-z\s]+\d+minutes-\d+hour(Very)?easyView Guide',  # 连续文本带时间范围
        ]

        # 移除产品推荐框内容模式
        # 例如: "Mac Laptop StorageFind compatible replacement parts..."
        product_recommendation_patterns = [
            # 具体的产品推荐模式
            r'Mac Laptop Fans\s*Find compatible replacement parts.*?Find Your Parts\s*Select my model',
            r'Mac Laptop Cables\s*Find compatible replacement parts.*?Find Your Parts\s*Select my model',
            r'Mac Laptop Motherboards\s*Find compatible replacement parts.*?Find Your Parts\s*Select my model',
            r'Mac Laptop Storage\s*Find compatible replacement parts.*?Find Your Parts\s*Select my model',
            r'Mac Laptop Batteries\s*Find compatible replacement parts.*?Find Your Parts\s*Select my model',
            r'Mac Laptop Screens\s*Find compatible replacement parts.*?Find Your Parts\s*Select my model',
            # 通用模式
            r'Mac\s*Laptop\s*[A-Za-z\s]*Find\s*compatible\s*replacement\s*parts.*?Find\s*Your\s*Parts\s*Select\s*my\s*model',
            r'Find\s*compatible\s*replacement\s*parts.*?Find\s*Your\s*Parts\s*Select\s*my\s*model',
            r'All\s*parts\s*and\s*fix\s*kits\s*are\s*backed\s*by\s*the\s*iFixit\s*Quality\s*Guarantee.*',
            r'Find\s*Your\s*Parts\s*Select\s*my\s*model',
            # 连续文本模式（没有空格）
            r'Mac Laptop[A-Za-z]*Find compatible replacement.*',
            r'[A-Za-z\s]+(Fans|Cables|Motherboards|Storage|Batteries|Screens)Find compatible replacement.*',
        ]

        cleaned_text = text

        # 应用所有模式
        all_patterns = commercial_patterns + guide_recommendation_patterns + product_recommendation_patterns
        for pattern in all_patterns:
            cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE)

        # 移除孤立的商业关键词
        commercial_keywords = [
            r'\$\d+\.?\d*',  # 价格
            r'\d+\.?\d*\s*reviews?',  # 评分
            r'\bBuy\b',  # 购买按钮
            r'\bAdd to cart\b',  # 添加到购物车
            r'MacBook Pro USB-C to USB-C CableBuy',  # 具体的产品+购买
            r'[A-Za-z\s]+(Cable|Adapter|Charger|Battery|Screen|Part)\s*Buy',  # 产品+购买
            r'[A-Za-z\s]+Buy$',  # 以Buy结尾的产品名
        ]

        for keyword in commercial_keywords:
            cleaned_text = re.sub(keyword, '', cleaned_text, flags=re.IGNORECASE)

        # 清理多余的空白
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()

        return cleaned_text

    def format_troubleshooting_text(self, text, element):
        """格式化故障排除文本 - 改进版本，确保良好的可读性"""
        if not text:
            return ""

        try:
            # 清理基本文本格式
            text = re.sub(r'\s+', ' ', text).strip()

            # 为不同类型的元素添加适当的格式
            if hasattr(element, 'name') and element.name and element.name.startswith('h'):
                # 标题 - 添加适当的间距
                level = int(element.name[1]) if element.name[1].isdigit() else 2
                prefix = '#' * min(level + 1, 6)  # 最多6级标题
                return f"{prefix} {text}"
            elif hasattr(element, 'name') and element.name == 'li':
                # 列表项 - 确保适当的格式
                return f"• {text}"
            elif hasattr(element, 'name') and element.name in ['blockquote']:
                # 引用
                return f"> {text}"
            elif hasattr(element, 'name') and element.name in ['p', 'div']:
                # 段落 - 确保段落间有适当的分隔
                # 检查是否包含多个句子，如果是，添加适当的换行
                sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
                if len(sentences) > 2:
                    # 对于长段落，在句子间添加适当的换行
                    formatted_sentences = []
                    for i, sentence in enumerate(sentences):
                        formatted_sentences.append(sentence.strip())
                        # 每2-3个句子后添加换行，提高可读性
                        if (i + 1) % 3 == 0 and i < len(sentences) - 1:
                            formatted_sentences.append('\n')
                    return ' '.join(formatted_sentences)
                else:
                    return text
            else:
                # 普通文本
                return text
        except Exception:
            # 如果出现任何错误，返回清理后的原始文本
            return re.sub(r'\s+', ' ', text).strip()

    def extract_troubleshooting_images(self, content_section):
        """提取Troubleshooting区域的图片URL - 改进版本，更准确地识别相关图片"""
        if not content_section:
            return []

        print("开始提取图片URL...")
        images = []
        seen_urls = set()

        # 查找所有图片元素
        img_elements = content_section.find_all('img')
        print(f"找到 {len(img_elements)} 个图片元素")

        for img in img_elements:
            # 获取图片源URL，支持多种属性
            img_src = (img.get('src') or img.get('data-src') or
                      img.get('data-original') or img.get('data-lazy-src'))

            if not img_src:
                continue

            # 处理相对URL
            if img_src.startswith("//"):
                img_src = "https:" + img_src
            elif img_src.startswith("/"):
                img_src = self.base_url + img_src

            # 过滤掉不相关的图片
            if self.should_skip_image(img_src, img):
                continue

            # 去重处理
            base_url = self.get_base_image_url(img_src)
            if base_url in seen_urls:
                continue
            seen_urls.add(base_url)

            # 获取最佳质量的图片URL
            optimized_url = self.get_optimized_image_url(img_src)

            # 提取图片的描述信息
            image_info = {
                "url": optimized_url,
                "alt": img.get('alt', '').strip(),
                "title": img.get('title', '').strip(),
                "width": img.get('width', ''),
                "height": img.get('height', ''),
                "context": self.get_image_context(img)
            }

            # 清理空字段
            image_info = {k: v for k, v in image_info.items() if v}
            images.append(image_info)

        print(f"提取到 {len(images)} 个图片URL")
        return images

    def should_skip_image(self, img_src, img_element):
        """判断是否应该跳过某个图片"""
        img_src_lower = img_src.lower()

        # 跳过明显的装饰性图片
        skip_patterns = [
            'icon', 'logo', 'avatar', 'thumb', 'button', 'arrow',
            'bullet', 'star', 'rating', 'social', 'share',
            'advertisement', 'banner', 'ad_', '_ad', '/ads/',
            'spacer', 'pixel', '1x1', 'transparent'
        ]

        if any(pattern in img_src_lower for pattern in skip_patterns):
            return True

        # 检查图片尺寸，跳过太小的图片
        width = img_element.get('width')
        height = img_element.get('height')
        if width and height:
            try:
                w, h = int(width), int(height)
                if w < 50 or h < 50:  # 跳过小于50x50的图片
                    return True
            except (ValueError, TypeError):
                pass

        # 检查CSS类名
        img_classes = ' '.join(img_element.get('class', [])).lower()
        if any(skip_class in img_classes for skip_class in [
            'icon', 'logo', 'avatar', 'decoration', 'ornament'
        ]):
            return True

        return False

    def get_base_image_url(self, img_src):
        """获取图片的基础URL用于去重"""
        # 移除尺寸和格式后缀
        base_url = img_src

        # 移除常见的尺寸后缀
        size_patterns = ['.medium', '.large', '.small', '.thumb', '.200x150', '.standard']
        for pattern in size_patterns:
            if pattern in base_url:
                base_url = base_url.split(pattern)[0]
                break

        return base_url

    def get_optimized_image_url(self, img_src):
        """获取优化后的图片URL，优先使用medium格式"""
        # 如果已经是medium格式，直接返回
        if ".medium" in img_src:
            return img_src

        # 如果是iFixit的图片，尝试构造medium版本
        if "ifixit" in img_src.lower():
            # 移除现有的尺寸后缀
            base_url = self.get_base_image_url(img_src)

            # 构造medium版本URL
            if ".jpg" in base_url:
                return base_url + ".medium.jpg"
            elif ".png" in base_url:
                return base_url + ".medium.png"
            elif ".jpeg" in base_url:
                return base_url + ".medium.jpeg"

        return img_src

    def get_image_context(self, img_element):
        """获取图片的上下文信息"""
        context_info = []

        # 查找图片的标题或说明
        parent = img_element.parent
        for _ in range(3):  # 向上查找3层
            if parent:
                # 查找图片说明
                caption = parent.find(['figcaption', 'caption'])
                if caption:
                    caption_text = caption.get_text().strip()
                    if caption_text and len(caption_text) < 200:
                        context_info.append(f"Caption: {caption_text}")
                        break

                # 查找相邻的文本
                prev_text = parent.find_previous_sibling(string=True)
                if prev_text and len(prev_text.strip()) > 10:
                    context_info.append(f"Context: {prev_text.strip()[:100]}")
                    break

                parent = parent.parent
            else:
                break

        return '; '.join(context_info) if context_info else ""

    def extract_troubleshooting_videos(self, content_section):
        """提取Troubleshooting区域的视频URL - 改进版本，更全面地识别各种视频内容"""
        if not content_section:
            return []

        print("开始提取视频URL...")
        videos = []
        seen_urls = set()

        # 方法1: 查找嵌入的视频元素
        video_elements = content_section.find_all(['iframe', 'embed', 'object', 'video', 'source'])
        print(f"找到 {len(video_elements)} 个视频元素")

        for element in video_elements:
            video_info = self.extract_video_from_element(element)
            if video_info and video_info['url'] not in seen_urls:
                seen_urls.add(video_info['url'])
                videos.append(video_info)

        # 方法2: 查找视频链接
        video_links = content_section.find_all('a', href=True)
        for link in video_links:
            video_info = self.extract_video_from_link(link)
            if video_info and video_info['url'] not in seen_urls:
                seen_urls.add(video_info['url'])
                videos.append(video_info)

        # 方法3: 查找通过JavaScript或data属性嵌入的视频
        js_videos = self.extract_videos_from_data_attributes(content_section)
        for video_info in js_videos:
            if video_info['url'] not in seen_urls:
                seen_urls.add(video_info['url'])
                videos.append(video_info)

        print(f"提取到 {len(videos)} 个视频URL")
        return videos

    def extract_video_from_element(self, element):
        """从视频元素中提取视频信息"""
        src = (element.get('src') or element.get('data-src') or
               element.get('data-url') or element.get('data-video-src'))

        if not src:
            return None

        # 处理相对URL
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = self.base_url + src

        # 确定视频类型和平台
        video_type, platform = self.identify_video_platform(src)

        # 获取视频标题和描述
        title = (element.get('title') or element.get('alt') or
                element.get('data-title') or '')

        # 查找相邻的文本作为描述
        description = self.get_video_description(element)

        return {
            "url": src,
            "type": video_type,
            "platform": platform,
            "title": title.strip(),
            "description": description,
            "element_type": element.name
        }

    def extract_video_from_link(self, link):
        """从链接中提取视频信息"""
        href = link.get('href')
        text = link.get_text().strip()

        if not href:
            return None

        # 检查是否是视频链接
        video_domains = [
            'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com',
            'twitch.tv', 'facebook.com/watch', 'instagram.com/p',
            '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv',
            'video', 'watch', 'play'
        ]

        if not any(domain in href.lower() for domain in video_domains):
            return None

        # 处理相对URL
        if href.startswith("/"):
            href = self.base_url + href

        # 确定视频类型和平台
        video_type, platform = self.identify_video_platform(href)

        return {
            "url": href,
            "type": video_type,
            "platform": platform,
            "title": text or "Video",
            "description": "",
            "element_type": "link"
        }

    def extract_videos_from_data_attributes(self, content_section):
        """从data属性中提取视频信息"""
        videos = []

        # 查找包含视频ID的元素
        video_id_elements = content_section.find_all(attrs={'videoid': True})
        for element in video_id_elements:
            video_id = element.get('videoid')
            if video_id:
                # 假设是YouTube视频
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                videos.append({
                    "url": video_url,
                    "type": "embedded",
                    "platform": "youtube",
                    "title": element.get('title', ''),
                    "description": "",
                    "element_type": "data_attribute"
                })

        # 查找其他可能的视频数据属性
        data_video_elements = content_section.find_all(attrs=lambda x: x and
            hasattr(x, 'keys') and any(attr.startswith('data-video') for attr in x.keys() if isinstance(attr, str)))

        for element in data_video_elements:
            if hasattr(element, 'attrs') and element.attrs:
                for attr, value in element.attrs.items():
                    if isinstance(attr, str) and attr.startswith('data-video') and value:
                        if any(domain in str(value) for domain in ['youtube', 'vimeo', 'video']):
                            video_type, platform = self.identify_video_platform(str(value))
                            videos.append({
                                "url": str(value),
                                "type": video_type,
                                "platform": platform,
                                "title": element.get('title', ''),
                                "description": "",
                                "element_type": "data_attribute"
                            })

        return videos

    def identify_video_platform(self, url):
        """识别视频平台和类型"""
        url_lower = url.lower()

        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return "embedded", "youtube"
        elif 'vimeo.com' in url_lower:
            return "embedded", "vimeo"
        elif 'dailymotion.com' in url_lower:
            return "embedded", "dailymotion"
        elif 'twitch.tv' in url_lower:
            return "embedded", "twitch"
        elif any(ext in url_lower for ext in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm']):
            return "direct", "file"
        else:
            return "link", "unknown"

    def get_video_description(self, element):
        """获取视频的描述信息"""
        # 查找相邻的描述文本
        parent = element.parent
        description_parts = []

        for _ in range(3):  # 向上查找3层
            if parent:
                # 查找视频说明
                caption = parent.find(['figcaption', 'caption', 'p'])
                if caption and caption != element:
                    caption_text = caption.get_text().strip()
                    if caption_text and len(caption_text) < 300:
                        description_parts.append(caption_text)
                        break

                parent = parent.parent
            else:
                break

        return '; '.join(description_parts) if description_parts else ""

    def extract_troubleshooting_documents(self, content_section):
        """提取Troubleshooting区域的文档URL - 改进版本，更全面地识别各种文档类型"""
        if not content_section:
            return []

        print("开始提取文档URL...")
        documents = []
        seen_urls = set()

        # 查找所有链接
        all_links = content_section.find_all('a', href=True)
        print(f"找到 {len(all_links)} 个链接")

        for link in all_links:
            doc_info = self.extract_document_from_link(link)
            if doc_info and doc_info['url'] not in seen_urls:
                seen_urls.add(doc_info['url'])
                documents.append(doc_info)

        # 查找可能通过其他方式嵌入的文档
        embedded_docs = self.extract_embedded_documents(content_section)
        for doc_info in embedded_docs:
            if doc_info['url'] not in seen_urls:
                seen_urls.add(doc_info['url'])
                documents.append(doc_info)

        print(f"提取到 {len(documents)} 个文档URL")
        return documents

    def extract_document_from_link(self, link):
        """从链接中提取文档信息"""
        href = link.get('href')
        text = link.get_text().strip()

        if not href:
            return None

        # 扩展的文档类型检测
        document_patterns = [
            # 直接文件类型
            '.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt', '.pages',
            '.xls', '.xlsx', '.csv', '.ods', '.numbers',
            '.ppt', '.pptx', '.odp', '.key',
            '.zip', '.rar', '.7z', '.tar', '.gz',
            # URL路径关键词
            'document', 'manual', 'guide', 'instruction', 'handbook',
            'datasheet', 'specification', 'schematic', 'diagram',
            'download', 'file', 'attachment', 'resource'
        ]

        # 检查是否是文档链接
        href_lower = href.lower()
        text_lower = text.lower()

        is_document = (any(pattern in href_lower for pattern in document_patterns) or
                      any(pattern in text_lower for pattern in ['manual', 'guide', 'document', 'download', 'pdf']))

        if not is_document:
            return None

        # 处理相对URL
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = self.base_url + href

        # 过滤掉明显不是文档的链接
        if any(skip in href_lower for skip in ['javascript:', 'mailto:', '#', 'void(0)']):
            return None

        # 确定文档类型
        doc_type = self.get_document_type(href)

        # 获取文档大小信息（如果可用）
        size_info = self.extract_document_size(link)

        # 获取文档描述
        description = self.get_document_description(link)

        doc_info = {
            "url": href,
            "title": text or "Document",
            "type": doc_type,
            "description": description
        }

        # 添加大小信息（如果有）
        if size_info:
            doc_info["size"] = size_info

        return doc_info

    def extract_embedded_documents(self, content_section):
        """提取嵌入的文档"""
        documents = []

        # 查找嵌入的PDF或其他文档
        embedded_elements = content_section.find_all(['embed', 'object', 'iframe'])

        for element in embedded_elements:
            src = element.get('src') or element.get('data') or element.get('data-src')
            if src:
                # 检查是否是文档
                if any(doc_type in src.lower() for doc_type in ['.pdf', 'document', 'viewer']):
                    # 处理相对URL
                    if src.startswith("//"):
                        src = "https:" + src
                    elif src.startswith("/"):
                        src = self.base_url + src

                    documents.append({
                        "url": src,
                        "title": element.get('title', 'Embedded Document'),
                        "type": self.get_document_type(src),
                        "description": "Embedded document"
                    })

        return documents

    def get_document_type(self, url):
        """根据URL确定文档类型 - 扩展版本"""
        url_lower = url.lower()

        # 文件扩展名映射
        type_mapping = {
            '.pdf': 'pdf',
            '.doc': 'word', '.docx': 'word', '.odt': 'word', '.pages': 'word',
            '.xls': 'excel', '.xlsx': 'excel', '.csv': 'excel', '.ods': 'excel', '.numbers': 'excel',
            '.ppt': 'powerpoint', '.pptx': 'powerpoint', '.odp': 'powerpoint', '.key': 'powerpoint',
            '.txt': 'text', '.rtf': 'text',
            '.zip': 'archive', '.rar': 'archive', '.7z': 'archive', '.tar': 'archive', '.gz': 'archive'
        }

        for ext, doc_type in type_mapping.items():
            if ext in url_lower:
                return doc_type

        # 基于URL路径的类型判断
        if any(keyword in url_lower for keyword in ['manual', 'handbook']):
            return 'manual'
        elif any(keyword in url_lower for keyword in ['guide', 'instruction']):
            return 'guide'
        elif any(keyword in url_lower for keyword in ['datasheet', 'specification']):
            return 'specification'
        elif any(keyword in url_lower for keyword in ['schematic', 'diagram']):
            return 'diagram'
        elif 'ifixit.com/guide' in url_lower:
            return 'ifixit_guide'
        else:
            return 'document'

    def extract_document_size(self, link):
        """提取文档大小信息"""
        # 查找链接文本中的大小信息
        text = link.get_text()
        parent_text = ""

        # 也检查父元素的文本
        if link.parent:
            parent_text = link.parent.get_text()

        combined_text = f"{text} {parent_text}"

        # 查找大小模式 (例如: "2.5 MB", "1.2KB", "500 bytes")
        import re
        size_pattern = r'(\d+(?:\.\d+)?)\s*(KB|MB|GB|bytes?)\b'
        match = re.search(size_pattern, combined_text, re.IGNORECASE)

        if match:
            return f"{match.group(1)} {match.group(2).upper()}"

        return None

    def get_document_description(self, link):
        """获取文档的描述信息"""
        description_parts = []

        # 检查链接的title属性
        title = link.get('title')
        if title and title.strip():
            description_parts.append(title.strip())

        # 查找相邻的描述文本
        parent = link.parent
        for _ in range(2):  # 向上查找2层
            if parent:
                # 查找相邻的小文本（通常是描述）
                siblings = parent.find_all(['small', 'span', 'em', 'i'])
                for sibling in siblings:
                    sibling_text = sibling.get_text().strip()
                    if (sibling_text and len(sibling_text) < 200 and
                        sibling_text not in description_parts):
                        description_parts.append(sibling_text)
                        break

                parent = parent.parent
            else:
                break

        return '; '.join(description_parts) if description_parts else ""

    def get_document_type(self, url):
        """根据URL确定文档类型"""
        url_lower = url.lower()
        if '.pdf' in url_lower:
            return 'pdf'
        elif '.doc' in url_lower:
            return 'word'
        elif 'document' in url_lower:
            return 'document'
        else:
            return 'unknown'

    def extract_guides_from_device_page(self, soup, device_url):
        """从设备页面提取指南链接，包括Guide和Teardown"""
        guides = []
        seen_guide_urls = set()

        # 查找指南区域 - 支持英文和中文
        guide_keywords = ["Guides", "指南", "Teardowns", "Teardown"]
        guide_sections = []

        for keyword in guide_keywords:
            sections = soup.find_all(string=lambda text: text and keyword in text)
            guide_sections.extend(sections)

        for guide_section in guide_sections:
            # 向上查找包含指南链接的区域
            parent = guide_section.parent
            for _ in range(5):  # 向上查找最多5层
                if parent and parent.name in ['div', 'section']:
                    # 在这个区域内查找指南链接（包括Guide和Teardown）
                    guide_links = parent.select("a[href*='/Guide/'], a[href*='/Teardown/']")
                    for link in guide_links:
                        href = link.get("href")
                        text = link.get_text().strip()
                        if href and text and "Create Guide" not in text and "创建指南" not in text:
                            if href.startswith("/"):
                                href = self.base_url + href
                            if href not in seen_guide_urls:
                                seen_guide_urls.add(href)
                                guides.append({
                                    "title": text,
                                    "url": href
                                })
                    break
                parent = parent.parent if parent else None

        # 如果没有找到，直接在整个页面查找指南链接（包括Guide和Teardown）
        if not guides:
            guide_links = soup.select("a[href*='/Guide/'], a[href*='/Teardown/']")
            for link in guide_links:
                href = link.get("href")
                text = link.get_text().strip()
                if href and text and "Create Guide" not in text and "创建指南" not in text and "Guide/new" not in href:
                    if href.startswith("/"):
                        href = self.base_url + href
                    if href not in seen_guide_urls:
                        seen_guide_urls.add(href)
                        guides.append({
                            "title": text,
                            "url": href
                        })

        return guides

    def extract_troubleshooting_from_device_page(self, soup, device_url):
        """从设备页面提取故障排除链接 - 只提取指定范围内的内容"""
        troubleshooting_links = []
        seen_ts_urls = set()

        # 查找故障排除区域 - 主要支持英文，兼容中文
        troubleshooting_keywords = ["Troubleshooting", "troubleshooting", "故障排除", "故障", "问题排除"]
        troubleshooting_sections = []

        for keyword in troubleshooting_keywords:
            sections = soup.find_all(string=lambda text: text and keyword in text)
            troubleshooting_sections.extend(sections)

        for ts_section in troubleshooting_sections:
            # 查找故障排除标题的父容器
            parent = ts_section.parent

            # 向上查找标题容器
            title_container = None
            for _ in range(5):
                if parent and parent.name in ['div', 'section', 'h1', 'h2', 'h3']:
                    class_names = parent.get('class', [])
                    # 查找标题容器（通常包含heading相关的类名）
                    if (any('heading' in str(cls).lower() for cls in class_names) or
                        parent.name.startswith('h')):
                        title_container = parent
                        break
                parent = parent.parent if parent else None

            # 如果找到标题容器，查找其下一个兄弟元素
            if title_container:
                # 查找下一个兄弟元素，通常包含实际的故障排除链接
                next_sibling = title_container.find_next_sibling()
                content_containers = []

                if next_sibling:
                    content_containers.append(next_sibling)

                # 也检查后续的几个兄弟元素
                current = title_container
                for _ in range(3):
                    current = current.find_next_sibling()
                    if current:
                        content_containers.append(current)
                    else:
                        break

                # 在内容容器中查找故障排除链接
                for container in content_containers:
                    ts_links = container.select("a[href]")
                    if ts_links:  # 如果找到链接，处理这个容器
                        # 过滤并排序链接，只保留指定范围内的内容
                        filtered_links = self.filter_troubleshooting_links(ts_links)

                        for link_info in filtered_links:
                            href = link_info["url"]
                            text = link_info["title"]

                            if href not in seen_ts_urls:
                                seen_ts_urls.add(href)
                                troubleshooting_links.append({
                                    "title": text,
                                    "url": href
                                })
                        break  # 找到包含链接的容器后停止

                if troubleshooting_links:
                    break  # 找到故障排除链接后停止

        # 如果没有找到专门的故障排除区域，查找页面中的故障排除相关链接
        if not troubleshooting_links:
            # 查找包含故障排除关键词的链接
            all_links = soup.select("a[href]")
            filtered_links = self.filter_troubleshooting_links(all_links)

            for link_info in filtered_links:
                href = link_info["url"]
                text = link_info["title"]

                if href not in seen_ts_urls:
                    seen_ts_urls.add(href)
                    troubleshooting_links.append({
                        "title": text,
                        "url": href
                    })

        return troubleshooting_links

    def filter_troubleshooting_links(self, links):
        """过滤troubleshooting链接，只保留指定范围内的内容"""
        # 定义需要爬取的troubleshooting内容范围 - 只保留英文
        target_troubleshooting_items = [
            "MacBook Fan Loud",
            "MacBook Won't Turn On",
            "MacBook Will Not Turn On",
            "MacBook Keyboard Not Working",
            "MacBook Black Screen",
            "MacBook Pro Black Screen",  # 包含MacBook Pro特定的黑屏问题
            "MacBook Slow",
            "MacBook Folder With Question Mark",
            "MacBook Stuck On Loading Screen"
        ]

        # 定义URL关键词映射，用于识别特定的troubleshooting页面
        url_keywords = [
            "MacBook_Fan_Loud",
            "MacBook_Won't_Turn_On",
            "MacBook_Will_Not_Turn_On",
            "MacBook_Keyboard_Not_Working",
            "MacBook_Black_Screen",
            "MacBook_Pro_Black_Screen",
            "MacBook_Slow",
            "MacBook_Folder_With_Question_Mark",
            "MacBook_Stuck_On_Loading_Screen"
        ]

        filtered_links = []
        seen_urls = set()  # 用于去重

        for link in links:
            href = link.get("href", "")
            text = link.get_text().strip()

            # 基本过滤条件
            if (not href or not text or len(text) <= 3 or
                any(skip in href.lower() for skip in ['javascript:', 'mailto:', '#']) or
                any(skip in text.lower() for skip in ['more', 'view', 'back', 'new', '更多', '查看', '返回', '新页面'])):
                continue

            # 检查是否是目标troubleshooting内容
            is_target_item = False

            # 方法1: 检查链接文本是否匹配目标项目
            for target_item in target_troubleshooting_items:
                if target_item.lower() in text.lower():
                    is_target_item = True
                    break



            # 方法2: 检查URL是否包含目标关键词
            if not is_target_item:
                for keyword in url_keywords:
                    if keyword.lower() in href.lower():
                        is_target_item = True
                        break

            # 方法3: 检查是否包含特定的troubleshooting关键词组合
            if not is_target_item:
                text_lower = text.lower()
                href_lower = href.lower()

                # 检查特定的问题类型 - 只保留英文关键词
                problem_patterns = [
                    ("fan", "loud"),  # 风扇响动
                    ("won't", "turn"),  # 无法开机
                    ("will", "not", "turn"),  # 无法开机（另一种表达）
                    ("keyboard", "not working"),  # 键盘不工作
                    ("black", "screen"),  # 黑屏
                    ("slow",),  # 运行缓慢
                    ("folder", "question"),  # 文件夹问号
                    ("stuck", "loading")  # 卡在加载界面
                ]

                for pattern in problem_patterns:
                    if all(keyword in text_lower or keyword in href_lower for keyword in pattern):
                        is_target_item = True
                        break

            if is_target_item:
                # 处理相对URL
                if href.startswith("/"):
                    href = self.base_url + href

                # 去重：基于URL的核心部分进行去重
                url_key = href.lower()

                # 统一处理相似的URL
                if "macbook_pro_black_screen" in url_key:
                    url_key = url_key.replace("macbook_pro_black_screen", "macbook_black_screen")
                elif "macbook_will_not_turn_on" in url_key:
                    url_key = url_key.replace("macbook_will_not_turn_on", "macbook_won't_turn_on")

                # 基于URL路径的最后部分进行去重
                url_path = url_key.split('/')[-1] if '/' in url_key else url_key

                if url_path not in seen_urls:
                    seen_urls.add(url_path)
                    filtered_links.append({
                        "title": text,
                        "url": href
                    })

        # 确保我们有正确的7个链接
        expected_urls = [
            "macbook_fan_loud",
            "macbook_won't_turn_on",
            "macbook_will_not_turn_on",
            "macbook_keyboard_not_working",
            "macbook_black_screen",
            "macbook_slow",
            "macbook_folder_with_question_mark",
            "macbook_stuck_on_loading_screen"
        ]

        # 按照预期顺序排序
        ordered_links = []
        for expected_url in expected_urls:
            for link in filtered_links:
                if expected_url in link['url'].lower():
                    ordered_links.append(link)
                    break

        # 添加任何遗漏的链接
        for link in filtered_links:
            if link not in ordered_links:
                ordered_links.append(link)

        # 限制为7个链接
        final_links = ordered_links[:7]

        print(f"Filtered and kept {len(final_links)} target troubleshooting links")
        for link in final_links:
            print(f"  - {link['title']}: {link['url']}")

        return final_links

    def crawl_device_with_guides_and_troubleshooting(self, device_url):
        """爬取设备页面及其指南和故障排除内容"""
        # 确保使用英文版本
        device_url = self.ensure_english_url(device_url)
        print(f"Starting to crawl device page: {device_url}")

        # 首先获取基本的产品信息
        print("Getting device page content...")
        soup = self.get_soup(device_url)
        if not soup:
            print("Unable to get device page content")
            return None
        if not soup:
            return None

        # 提取基本产品信息
        product_info = self.extract_product_info(soup, device_url, [])

        # 提取指南链接
        print("Extracting guide links...")
        guides = self.extract_guides_from_device_page(soup, device_url)
        print(f"Found {len(guides)} guides")

        # 提取故障排除链接
        print("Extracting troubleshooting links...")
        troubleshooting_links = self.extract_troubleshooting_from_device_page(soup, device_url)
        print(f"Found {len(troubleshooting_links)} troubleshooting pages")

        # 爬取每个指南的详细内容
        guides_content = []
        for guide in guides:
            guide_content = self.extract_guide_content(guide["url"])
            if guide_content:
                guides_content.append(guide_content)

        # 爬取故障排除内容（只在第一次遇到时爬取）
        troubleshooting_content = []
        for ts_link in troubleshooting_links:
            ts_content = self.extract_troubleshooting_content(ts_link["url"])
            if ts_content:
                troubleshooting_content.append(ts_content)

        # 组合所有数据
        enhanced_product_info = {
            **product_info,
            "guides": guides_content,
            "troubleshooting": troubleshooting_content,
            "crawl_timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        return enhanced_product_info

    def save_enhanced_results(self, enhanced_data, filename=None):
        """保存增强版爬取结果"""
        if not enhanced_data:
            print("没有数据需要保存")
            return

        # 确保结果目录存在
        os.makedirs("results", exist_ok=True)

        if not filename:
            # 从产品URL生成文件名
            if "product_url" in enhanced_data:
                url_parts = enhanced_data["product_url"].split('/')
                filename = f"results/enhanced_{url_parts[-1]}.json"
            else:
                filename = "results/enhanced_product_info.json"

        # 处理产品名称中的引号问题
        if "product_name" in enhanced_data:
            enhanced_data["product_name"] = enhanced_data["product_name"].replace('\\"', '英寸').replace('\\"', '英寸')
            enhanced_data["product_name"] = enhanced_data["product_name"].replace('"', '英寸')
            enhanced_data["product_name"] = re.sub(r'(\d+)\"', r'\1英寸', enhanced_data["product_name"])

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(enhanced_data, f, ensure_ascii=False, indent=2)

        print(f"\n已保存增强版产品信息到 {filename}")
        print(f"包含 {len(enhanced_data.get('guides', []))} 个指南")
        print(f"包含 {len(enhanced_data.get('troubleshooting', []))} 个故障排除页面")

def test_troubleshooting_extraction():
    """测试故障排除内容提取的精确边界检测"""
    crawler = EnhancedIFixitCrawler(verbose=True)  # 测试时启用详细输出

    # 测试URL - MacBook Black Screen页面
    test_url = "https://www.ifixit.com/Troubleshooting/Mac_Laptop/MacBook+Black+Screen/478598?lang=en"

    print(f"测试URL: {test_url}")
    print("=" * 80)

    # 提取故障排除内容
    result = crawler.extract_troubleshooting_content(test_url)

    if result:
        print(f"提取成功！")
        print(f"标题: {result['title']}")
        print(f"Causes数量: {len(result.get('causes', []))}")
        print()

        # 检查每个cause的内容
        for i, cause in enumerate(result.get('causes', []), 1):
            print(f"Cause {cause.get('number', i)}: {cause.get('title', 'Unknown')}")
            print(f"内容长度: {len(cause.get('content', ''))} 字符")
            print(f"图片数量: {len(cause.get('images', []))}")
            print(f"视频数量: {len(cause.get('videos', []))}")

            # 显示内容的前200个字符
            content = cause.get('content', '')
            if content:
                print(f"内容预览: {content[:200]}...")

            # 显示图片URL（如果有）
            images = cause.get('images', [])
            if images:
                print("图片:")
                for img in images:
                    print(f"  - {img.get('url', 'No URL')}")
                    print(f"    描述: {img.get('description', 'No description')}")

            print("-" * 60)

        # 保存结果到文件
        output_file = "results/test_troubleshooting_result.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"结果已保存到: {output_file}")

    else:
        print("提取失败！")

def process_input(input_text):
    """处理输入，支持URL或产品名"""
    if not input_text:
        return None

    # 如果是完整URL，直接返回
    if input_text.startswith("http"):
        return input_text

    # 如果包含/Device/，可能是部分URL
    if "/Device/" in input_text:
        if not input_text.startswith("https://"):
            return "https://www.ifixit.com" + input_text
        return input_text

    # 否则视为产品名，构建URL
    return f"https://www.ifixit.com/Device/{input_text}"

def ensure_lang_param(url):
    """确保URL包含语言参数"""
    if "?lang=en" not in url:
        if "?" in url:
            url += "&lang=en"
        else:
            url += "?lang=en"
    return url

def main():
    """主函数 - 支持命令行参数指定URL或产品名"""
    import sys

    # 检查是否启用详细模式
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    if verbose:
        sys.argv = [arg for arg in sys.argv if arg not in ["--verbose", "-v"]]

    crawler = EnhancedIFixitCrawler(verbose=verbose)

    # 检查命令行参数
    if len(sys.argv) > 1:
        input_text = sys.argv[1]

        # 处理特殊命令
        if input_text == "test":
            test_troubleshooting_extraction()
            return

        # 处理输入（URL或产品名）
        if input_text.startswith("http"):
            # 直接使用完整URL
            device_url = ensure_lang_param(input_text)
            print(f"使用提供的URL: {device_url}")
        elif "/Device/" in input_text:
            # 处理部分URL
            device_url = process_input(input_text)
            device_url = ensure_lang_param(device_url)
            print(f"构建完整URL: {device_url}")
        else:
            # 尝试直接作为产品名构建URL
            product_url = f"https://www.ifixit.com/Device/{input_text}"
            device_url = ensure_lang_param(product_url)
            print(f"尝试产品名: {input_text}")
            print(f"构建URL: {device_url}")

            # 检查URL是否可访问
            print("检查产品页面是否存在...")
            try:
                import requests
                response = requests.get(device_url, headers=crawler.headers, timeout=10)
                if response.status_code == 404:
                    print(f"❌ 产品页面不存在: {device_url}")
                    print("请检查产品名是否正确，或使用完整URL")
                    sys.exit(1)
                elif response.status_code != 200:
                    print(f"⚠️  页面访问异常 (状态码: {response.status_code})")
                else:
                    print("✅ 产品页面存在，开始爬取...")
            except Exception as e:
                print(f"⚠️  无法验证页面存在性: {str(e)}")
                print("继续尝试爬取...")
    else:
        # 默认URL - MacBook Pro 17" Unibody
        device_url = "https://www.ifixit.com/Device/MacBook_Pro_17%22_Unibody?lang=en"
        print("未指定URL，使用默认URL: MacBook Pro 17\" Unibody")

    print(f"开始增强版爬取...")
    print(f"目标URL: {device_url}")
    print("=" * 80)

    try:
        enhanced_data = crawler.crawl_device_with_guides_and_troubleshooting(device_url)

        if enhanced_data:
            crawler.save_enhanced_results(enhanced_data)
            if crawler.verbose:
                print("=" * 80)
                print("🎉 爬取完成！")

                # 显示统计信息
                guides_count = len(enhanced_data.get('guides', []))
                troubleshooting_count = len(enhanced_data.get('troubleshooting', []))
                print(f"📊 统计信息:")
                print(f"   - 指南数量: {guides_count}")
                print(f"   - 故障排除页面: {troubleshooting_count}")

                # 显示保存的文件名
                device_name = device_url.split('/')[-1].replace('?lang=en', '')
                output_file = f"results/enhanced_{device_name}.json"
                print(f"   - 保存文件: {output_file}")

        else:
            print("❌ 爬取失败")

    except KeyboardInterrupt:
        print("\n⚠️  用户中断了爬取过程")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 爬取过程中发生错误: {str(e)}")
        sys.exit(1)

def print_usage():
    """打印使用说明"""
    print("使用方法:")
    print("  python3 enhanced_crawler.py [选项] [URL或产品名]")
    print("")
    print("选项:")
    print("  --verbose, -v    启用详细输出模式（显示调试信息）")
    print("  -h, --help       显示此帮助信息")
    print("")
    print("示例:")
    print("  # 使用完整URL")
    print("  python3 enhanced_crawler.py https://www.ifixit.com/Device/MacBook_Pro_17%22_Unibody")
    print("  python3 enhanced_crawler.py https://www.ifixit.com/Device/iPhone_12")
    print("")
    print("  # 使用产品名（推荐）")
    print("  python3 enhanced_crawler.py MacBook_Pro_17%22_Unibody")
    print("  python3 enhanced_crawler.py iPhone_12")
    print("  python3 enhanced_crawler.py iPad_Air_2")
    print("")
    print("  # 启用详细输出")
    print("  python3 enhanced_crawler.py --verbose MacBook_Pro_17%22_Unibody")
    print("  python3 enhanced_crawler.py -v iPhone_12")
    print("")
    print("  # 使用部分URL")
    print("  python3 enhanced_crawler.py /Device/MacBook_Pro_17%22_Unibody")
    print("")
    print("  # 特殊命令")
    print("  python3 enhanced_crawler.py test  # 运行测试")
    print("")
    print("注意:")
    print("  - 产品名格式：使用下划线分隔，特殊字符需要URL编码")
    print("  - 如果URL中没有?lang=en参数，会自动添加")
    print("  - 不指定参数时，默认爬取MacBook Pro 17\" Unibody")
    print("  - 程序会自动检查产品页面是否存在")
    print("  - 默认情况下不显示详细调试信息，使用 --verbose 启用")

if __name__ == "__main__":
    import sys

    # 检查是否需要显示帮助
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help", "help"]:
        print_usage()
        sys.exit(0)

    main()