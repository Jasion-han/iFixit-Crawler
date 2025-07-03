import requests
from bs4 import BeautifulSoup
import json
import time
import os
import random
import re

class IFixitCrawler:
    def __init__(self, base_url="https://zh.ifixit.com"):
        self.base_url = base_url
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self.results = []
        self.visited_urls = set()
        self.debug = False  # 默认关闭调试模式
        
    def get_soup(self, url):
        """获取页面内容并解析为BeautifulSoup对象"""
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")
        except Exception as e:
            print(f"获取页面时发生错误: {url}, 错误: {str(e)}")
            return None
    
    def print_debug(self, message):
        """打印调试信息"""
        if self.debug:
            print(f"[DEBUG] {message}")
            
    def extract_breadcrumbs(self, soup):
        """提取页面中的面包屑导航"""
        breadcrumbs = []
        try:
            # 查找面包屑导航元素
            breadcrumb_elements = soup.select("nav.breadcrumb li, .breadcrumbs a, .breadcrumb a")
            for element in breadcrumb_elements:
                text = element.get_text().strip()
                if text:
                    breadcrumbs.append(text)
                    
            if not breadcrumbs:
                # 第二种方法：检查页面顶部的导航路径
                nav_path = soup.select_one("div.container > div.row:first-child")
                if nav_path:
                    path_items = nav_path.get_text().strip().split(">")
                    breadcrumbs = [item.strip() for item in path_items if item.strip()]
                    
            if breadcrumbs:
                self.print_debug(f"面包屑导航: {' > '.join(breadcrumbs)}")
        except Exception as e:
            print(f"提取面包屑导航时发生错误: {str(e)}")
            
        return breadcrumbs
            
    def extract_categories(self, soup, url):
        """提取页面中的设备类别链接"""
        categories = []
        try:
            # 打印页面标题，帮助调试
            page_title = soup.title.text if soup.title else "无标题"
            self.print_debug(f"页面标题: {page_title}")
            
            # 从页面提取面包屑导航
            breadcrumbs = self.extract_breadcrumbs(soup)
            
            # 查找"个类别"标记
            category_sections = soup.find_all(string=re.compile(r"\d+\s*个类别"))
            if category_sections:
                self.print_debug(f"找到类别标题: {[section for section in category_sections]}")
                
                for section in category_sections:
                    # 查找包含类别的区域
                    parent = section.parent
                    if parent:
                        # 查找之后的div，通常包含类别列表
                        next_section = parent.find_next_sibling()
                        if next_section:
                            # 查找所有链接
                            links = next_section.find_all("a", href=True)
                            for link in links:
                                href = link.get("href")
                                text = link.text.strip()
                                if href and text and "/Device/" in href:
                                    full_url = self.base_url + href if href.startswith("/") else href
                                    categories.append({
                                        "name": text,
                                        "url": full_url
                                    })
            
            # 如果没有找到类别标题，尝试其他方法
            if not categories:
                # 查找可能包含类别的区域
                category_containers = soup.select("div.categories, div.category-grid, ul.browse-devices")
                for container in category_containers:
                    links = container.find_all("a", href=True)
                    for link in links:
                        href = link.get("href")
                        text = link.text.strip()
                        if href and text and "/Device/" in href:
                            full_url = self.base_url + href if href.startswith("/") else href
                            categories.append({
                                "name": text,
                                "url": full_url
                            })
            
            # 如果还是没有找到，尝试查找所有可能的设备链接
            if not categories:
                # 查找所有链接
                all_links = soup.find_all("a", href=True)
                for link in all_links:
                    href = link.get("href")
                    text = link.text.strip()
                    if href and text and "/Device/" in href and not any(x in href for x in ["/Edit/", "/History/", "?revision", "/Answers/"]):
                        full_url = self.base_url + href if href.startswith("/") else href
                        categories.append({
                            "name": text,
                            "url": full_url
                        })
            
            # 去重
            unique_categories = []
            urls = set()
            for category in categories:
                if category["url"] not in urls and not any(x in category["url"] for x in ["/Edit/", "/History/", "?revision", "/Answers/"]):
                    urls.add(category["url"])
                    unique_categories.append(category)
            
            categories = unique_categories
            self.print_debug(f"找到 {len(categories)} 个类别")
            for category in categories:
                self.print_debug(f"  - {category['name']}: {category['url']}")
            
        except Exception as e:
            print(f"提取类别时发生错误: {str(e)}")
        
        return categories
        
    def is_final_product_page(self, soup, url):
        """判断当前页面是否为最终产品页面（没有子类别的页面）"""
        # 检查是否有子类别
        sub_categories = self.extract_categories(soup, url)
        
        # 过滤掉"创建指南"等非实际类别
        real_categories = [c for c in sub_categories if not any(x in c["name"] or x in c["url"] for x in ["创建指南", "Guide/new"])]
        
        # 检查是否有产品标题
        product_title = soup.select_one("div.device-title h1, h1.device-title, h1.title, h1")
        
        # 打印调试信息
        if product_title:
            self.print_debug(f"找到产品标题: {product_title.text}")
        
        # 如果有产品标题但没有实际子类别，则认为是最终产品页面
        if product_title and len(real_categories) == 0:
            return True
            
        return False
        
    def extract_product_info(self, soup, url, breadcrumb):
        """提取产品名称和说明书信息"""
        product_info = {
            "product_name": "",
            "product_url": url,    # 产品URL放在第二个位置
            "instruction_url": ""  # 说明书URL放在第三个位置
        }
        
        try:
            # 提取产品名称（页面标题）
            title_selectors = [
                "div.device-title h1", 
                "h1.device-title", 
                "h1.title",
                "h1"
            ]
            
            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    # 清理产品名称，去除多余空格并处理引号
                    product_name = title_elem.text.strip()
                    # 处理转义引号和英寸符号，将其替换为"英寸"
                    product_name = product_name.replace('\\"', '英寸').replace('\\"', '英寸')
                    product_name = product_name.replace('"', '英寸').replace('"', '英寸')
                    product_name = re.sub(r'(\d+)\"', r'\1英寸', product_name)  # 将数字后面的英寸符号替换为"英寸"
                    product_name = re.sub(r'\s+', ' ', product_name)  # 处理多余空格
                    product_info["product_name"] = product_name
                    break
            
            # 如果没有找到产品名称，尝试从URL中提取
            if not product_info["product_name"]:
                url_path = url.split("/")[-1]
                product_name = url_path.replace("_", " ").replace("-", " ")
                product_name = product_name.replace('%22', '英寸').replace('%E2%80%9D', '英寸')  # 将%22替换为英寸
                product_info["product_name"] = product_name
            
            # 查找"文档"栏目下的链接
            pdf_link = None
            
            # 方法1：查找"文档"标题
            doc_headings = soup.find_all(string=lambda text: text and (("文档" in text or "Documents" in text)))
            for heading in doc_headings:
                self.print_debug(f"找到文档标题: {heading}")
                # 向上找到包含文档的区域
                section = None
                parent = heading.parent
                for _ in range(5):  # 向上查找最多5层
                    if parent and parent.name in ['div', 'section']:
                        section = parent
                        break
                    parent = parent.parent if parent else None
                
                if section:
                    # 在区域内查找所有链接
                    links = section.find_all('a', href=True)
                    best_link = None
                    best_priority = 0
                    
                    for link in links:
                        href = link.get('href')
                        text = link.text.strip()
                        if href and text:
                            # 处理锚点链接以便于显示
                            link_url = href
                            if link_url.startswith('#'):
                                link_url = url + link_url
                            self.print_debug(f"文档区域内链接: {text} -> {link_url}")
                            
                            # 给不同类型的文档链接分配优先级
                            text_lower = text.lower()
                            priority = 0
                            
                            # 服务文档、使用手册等有最高优先级
                            if any(kw in text_lower for kw in ['service document', 'service manual', '服务文档', '服务手册', '使用手册', '说明书']):
                                priority = 3
                            # 一般文档其次
                            elif any(kw in text_lower for kw in ['document', 'manual', '文档', '手册']):
                                priority = 2
                            # 技术规格最后
                            elif any(kw in text_lower for kw in ['spec', 'technical', '规格', '技术参数']):
                                priority = 1
                            
                            if priority > best_priority:
                                best_link = href
                                best_priority = priority
                    
                    # 使用最佳链接
                    if best_link:
                        pdf_link = best_link
                        # 处理锚点链接
                        if pdf_link.startswith('#'):
                            pdf_link = url + pdf_link
                        product_info["instruction_url"] = pdf_link
                        self.print_debug(f"找到文档链接: {product_info['instruction_url']} (优先级: {best_priority})")
                        
                        # 如果是锚点链接，尝试找到实际的PDF链接
                        if best_link.startswith('#'):
                            # 首先找到锚点所在的区域
                            anchor_id = best_link[1:]  # 去掉#号
                            anchor_section = soup.find(id=anchor_id)
                            
                            if anchor_section:
                                # 查找该区域下的所有链接
                                section_parent = anchor_section.parent
                                if section_parent:
                                    # 查找该区域下的实际PDF链接
                                    pdf_links = []
                                    # 向下查找最多5个兄弟元素
                                    next_elem = section_parent.next_sibling
                                    for _ in range(5):
                                        if not next_elem:
                                            break
                                        # 查找元素中的链接
                                        if hasattr(next_elem, 'find_all'):
                                            for link in next_elem.find_all('a', href=True):
                                                href = link.get('href')
                                                if href and (href.endswith('.pdf') or '/Document/' in href):
                                                    pdf_links.append(href)
                                        next_elem = next_elem.next_sibling
                                    
                                    # 如果找到PDF链接，使用第一个
                                    if pdf_links:
                                        pdf_link = pdf_links[0]
                                        if pdf_link.startswith('/'):
                                            pdf_link = self.base_url + pdf_link
                                        product_info["instruction_url"] = pdf_link
                                        self.print_debug(f"找到实际PDF文档链接: {product_info['instruction_url']}")
                        break
            
            # 方法2：直接查找Documents区块
            if not pdf_link:
                # 处理React组件中的文档
                doc_sections = soup.find_all('div', class_=lambda c: c and 'component-DocumentsSection' in c)
                for section in doc_sections:
                    self.print_debug(f"找到React文档组件: {section}")
                    # 从data-props属性中提取JSON数据
                    props_data = section.get('data-props')
                    if props_data:
                        try:
                            # 修复可能的JSON格式问题
                            props_data = props_data.replace('&quot;', '"')
                            import json
                            data = json.loads(props_data)
                            if 'documents' in data and len(data['documents']) > 0:
                                for doc in data['documents']:
                                    # 优先使用网页URL而不是下载链接
                                    if 'url' in doc:
                                        pdf_link = doc['url']
                                        # 如果是相对URL，转为绝对URL
                                        full_url = self.base_url + pdf_link if pdf_link.startswith("/") else pdf_link
                                        # 移除URL中的referrer参数，获取更干净的链接
                                        if '?' in full_url:
                                            full_url = full_url.split('?')[0]
                                        product_info["instruction_url"] = full_url
                                        self.print_debug(f"从React组件中找到文档页面链接: {product_info['instruction_url']}")
                                        break
                                    elif 'downloadUrl' in doc and not pdf_link:
                                        pdf_link = doc['downloadUrl']
                                        product_info["instruction_url"] = pdf_link
                                        self.print_debug(f"从React组件中找到文档下载链接: {pdf_link}")
                                        break
                        except Exception as e:
                            self.print_debug(f"解析React组件数据时出错: {str(e)}")
                
                # 查找常规文档区块
                if not pdf_link:
                    doc_sections = soup.find_all(['section', 'div'], string=lambda text: text and "Documents" in text)
                    if not doc_sections:
                        doc_sections = soup.find_all(['h2', 'h3', 'h4'], string=lambda text: text and "Documents" in text)
                    
                    for section in doc_sections:
                        self.print_debug(f"找到Documents区块: {section}")
                        # 找到文档区块后，查找其后的所有链接
                        parent_section = section.parent
                        if parent_section:
                            # 查找文档区块中的所有链接
                            links = parent_section.find_all('a', href=True)
                            if not links:
                                # 如果在父元素中没找到链接，尝试查找兄弟元素
                                next_elem = section.find_next_sibling()
                                if next_elem:
                                    links = next_elem.find_all('a', href=True)
                            
                            for link in links:
                                href = link.get('href')
                                text = link.text.strip()
                                self.print_debug(f"Documents区块内链接: {text} -> {href}")
                                if href and text and not text.lower() in ['create a guide', 'repair guides']:
                                    pdf_link = href
                                    product_info["instruction_url"] = self.base_url + pdf_link if pdf_link.startswith("/") else pdf_link
                                    self.print_debug(f"找到Documents区块中的链接: {product_info['instruction_url']}")
                                    break
                        
                        if pdf_link:
                            break
            
            # 方法3：查找含有"PDF"图标的链接
            if not pdf_link:
                pdf_icons = soup.select('img[src*="pdf"], .pdf-icon, .icon-pdf')
                for icon in pdf_icons:
                    self.print_debug(f"找到PDF图标: {icon}")
                    parent_link = icon.find_parent('a')
                    if parent_link and parent_link.get('href'):
                        pdf_link = parent_link.get('href')
                        product_info["instruction_url"] = self.base_url + pdf_link if pdf_link.startswith("/") else pdf_link
                        self.print_debug(f"找到PDF链接: {product_info['instruction_url']}")
                        break
            
            # 方法4：检查页面内所有可能的文档链接
            if not pdf_link:
                internal_links = []  # 存储ifixit内部网页链接
                external_web_links = []  # 存储外部网站的网页链接
                pdf_links = []  # 存储PDF下载链接
                
                all_links = soup.find_all('a', href=True)
                for link in all_links:
                    href = link.get('href')
                    text = link.text.strip()
                    if not href or not text:
                        continue
                        
                    # 检查链接URL和文本是否包含文档相关关键词
                    href_lower = href.lower()
                    text_lower = text.lower()
                    
                    # 判断是否是文档链接
                    is_doc_link = False
                    
                    # 检查链接是否是ifixit内部链接
                    is_internal = href.startswith('/') or self.base_url in href
                    
                    # 排除不相关的链接
                    if 'wikipedia.org' in href_lower:
                        continue  # 排除维基百科链接
                    
                    # 排除通用链接和创建指南链接
                    if href == '/Guide' or href == '/Answers' or href == '/Teardown' or href == '/News' or 'Guide/new' in href:
                        continue  # 排除网站通用导航链接和创建指南链接
                    
                    # 检查链接是否是产品相关的
                    product_name_lower = product_info["product_name"].lower()
                    # 尝试提取产品型号
                    product_model = re.search(r'(\w+[-\s]?\w+\d+\w*[-\w]*)', product_name_lower)
                    if product_model:
                        product_model = product_model.group(1).replace(' ', '').lower()
                        # 检查链接或文本是否包含产品型号
                        contains_model = product_model in href_lower or product_model in text_lower
                        
                        # 外部链接必须与产品型号相关
                        if not is_internal and not contains_model:
                            continue
                    
                    # URL中包含文档相关关键词
                    if any(kw in href_lower for kw in ['manual', 'document', 'pdf', 'guide', 'instruction', 'service', '手册', '文档', '说明书']):
                        # 增加相关性判断
                        relevance_score = 0
                        
                        # 基于链接类型的相关性
                        if href_lower.endswith('.pdf'):
                            relevance_score += 5  # PDF链接高相关性
                        if '/document/' in href_lower:
                            relevance_score += 4  # 文档路径高相关性
                        if 'service' in href_lower or 'manual' in href_lower:
                            relevance_score += 3  # 包含服务手册关键词
                            
                        # 基于文本的相关性
                        if product_model and product_model in text_lower:
                            relevance_score += 5  # 文本包含产品型号
                        if product_model and product_model in href_lower:
                            relevance_score += 4  # URL包含产品型号
                            
                        # 只有相关性足够高的链接才被考虑
                        if is_internal and relevance_score >= 2:
                            internal_links.append((href, text, relevance_score))
                            is_doc_link = True
                        elif relevance_score >= 4:  # 外部链接需要更高的相关性
                            if href_lower.endswith('.pdf'):
                                pdf_links.append((href, text, relevance_score))
                            else:
                                external_web_links.append((href, text, relevance_score))
                            is_doc_link = True
                    
                    # 链接文本包含文档相关关键词
                    elif any(kw in text_lower for kw in ['manual', 'service manual', 'guide', 'technician', '手册', '维修手册']):
                        # 增加相关性判断
                        relevance_score = 0
                        
                        # 基于文本的相关性
                        if 'service manual' in text_lower or '维修手册' in text_lower:
                            relevance_score += 4  # 服务手册高相关性
                        elif 'manual' in text_lower or '手册' in text_lower:
                            relevance_score += 2  # 手册一般相关性
                            
                        if product_model and product_model in text_lower:
                            relevance_score += 5  # 文本包含产品型号
                        if product_model and product_model in href_lower:
                            relevance_score += 4  # URL包含产品型号
                            
                        # 只有相关性足够高的链接才被考虑
                        if is_internal and relevance_score >= 3:
                            internal_links.append((href, text, relevance_score))
                            is_doc_link = True
                        elif relevance_score >= 5:  # 外部链接需要更高的相关性
                            external_web_links.append((href, text, relevance_score))
                            is_doc_link = True
                
                # 相关性分数不够时，设置为空
                if (internal_links and internal_links[0][2] < 2) or \
                   (external_web_links and external_web_links[0][2] < 4) or \
                   (pdf_links and pdf_links[0][2] < 3):
                    self.print_debug("找到的链接相关性不够，不设置文档链接")
                    product_info["instruction_url"] = ""
                    
                    # 尝试查找视频链接
                    videos = self.extract_youtube_videos(soup, url)
                    if videos:
                        video = videos[0]  # 使用第一个视频
                        product_info["instruction_url"] = video["url"]
                        self.print_debug(f"使用视频链接作为说明书: {video['title']} -> {video['url']}")
                    
                    return product_info
                
                # 按优先级选择链接
                if internal_links:
                    # 按相关性分数排序
                    internal_links.sort(key=lambda x: x[2], reverse=True)
                    # 优先使用ifixit内部链接
                    href, text, relevance = internal_links[0]
                    self.print_debug(f"选择内部链接: {text} -> {href} (相关性分数: {relevance})")
                    pdf_link = href
                    # 处理锚点链接（以#开头的链接）
                    if pdf_link.startswith('#'):
                        pdf_link = url + pdf_link  # 将锚点与当前页面URL合并
                    product_info["instruction_url"] = self.base_url + pdf_link if pdf_link.startswith("/") else pdf_link
                    self.print_debug(f"找到ifixit内部文档链接: {product_info['instruction_url']}")
                elif external_web_links:
                    # 按相关性分数排序
                    external_web_links.sort(key=lambda x: x[2], reverse=True)
                    # 其次使用外部网站的网页链接
                    href, text, relevance = external_web_links[0]
                    self.print_debug(f"选择外部链接: {text} -> {href} (相关性分数: {relevance})")
                    pdf_link = href
                    # 处理锚点链接（以#开头的链接）
                    if pdf_link.startswith('#'):
                        pdf_link = url + pdf_link  # 将锚点与当前页面URL合并
                    product_info["instruction_url"] = self.base_url + pdf_link if pdf_link.startswith("/") else pdf_link
                    self.print_debug(f"找到外部网站文档链接: {product_info['instruction_url']}")
                elif pdf_links:
                    # 按相关性分数排序
                    pdf_links.sort(key=lambda x: x[2], reverse=True)
                    # 最后才使用PDF下载链接
                    href, text, relevance = pdf_links[0]
                    self.print_debug(f"选择PDF链接: {text} -> {href} (相关性分数: {relevance})")
                    pdf_link = href
                    # 处理锚点链接（以#开头的链接）
                    if pdf_link.startswith('#'):
                        pdf_link = url + pdf_link  # 将锚点与当前页面URL合并
                    product_info["instruction_url"] = self.base_url + pdf_link if pdf_link.startswith("/") else pdf_link
                    self.print_debug(f"找到PDF文档下载链接: {product_info['instruction_url']}")
            
            # 如果最终链接是锚点，合并为完整URL
            if product_info.get("instruction_url", "").startswith('#'):
                product_info["instruction_url"] = url + product_info["instruction_url"]
                self.print_debug(f"合并锚点链接为完整URL: {product_info['instruction_url']}")
            
            # 如果没有找到任何文档链接，尝试查找视频链接
            if not product_info.get("instruction_url"):
                videos = self.extract_youtube_videos(soup, url)
                if videos:
                    video = videos[0]  # 使用第一个视频
                    product_info["instruction_url"] = video["url"]
                    self.print_debug(f"使用视频链接作为说明书: {video['title']} -> {video['url']}")
        
        except Exception as e:
            print(f"提取产品信息时发生错误: {str(e)}")
        
        return product_info
        
    def crawl_recursive(self, url, breadcrumb=None, parent_url=None):
        """递归爬取类别和产品"""
        # 避免重复访问
        if url in self.visited_urls:
            return
            
        # 跳过"创建指南"页面
        if "创建指南" in url or "Guide/new" in url:
            return
            
        self.visited_urls.add(url)
        
        if breadcrumb is None:
            breadcrumb = []
        
        # 防止过快请求，添加延迟
        time.sleep(random.uniform(2, 4))
        
        print(f"爬取: {url}")
        soup = self.get_soup(url)
        if not soup:
            return
            
        # 提取面包屑导航
        page_breadcrumbs = self.extract_breadcrumbs(soup)
        if page_breadcrumbs and len(page_breadcrumbs) > len(breadcrumb):
            breadcrumb = page_breadcrumbs
        
        # 提取子类别
        categories = self.extract_categories(soup, url)
        
        # 过滤掉"创建指南"等非实际类别
        real_categories = [c for c in categories if not any(x in c["name"] or x in c["url"] for x in ["创建指南", "Guide/new"])]
        
        # 检查是否为最终产品页面
        is_final_page = self.is_final_product_page(soup, url)
        
        # 如果是最终产品页面（没有子类别），则提取产品信息
        if is_final_page:
            product_info = self.extract_product_info(soup, url, breadcrumb)
            
            # 只有当产品名称不为空时才添加到结果中，并确保没有重复
            if product_info["product_name"] and not any(p["product_url"] == product_info["product_url"] for p in self.results):
                self.results.append(product_info)
                print(f"已找到产品: {product_info['product_name']}")
                print(f"产品URL: {product_info['product_url']}")
                print(f"说明书链接: {product_info['instruction_url'] or '无'}")
                print(f"状态: 最终产品页面 (无子类别)")
        else:
            # 如果有子类别，则打印信息
            if real_categories:
                print(f"类别页面: {url}")
                print(f"找到 {len(real_categories)} 个子类别")
        
        # 如果有子类别，则继续递归爬取
        if categories:
            for category in categories:
                # 跳过已访问的链接
                if category["url"] in self.visited_urls:
                    continue
                    
                # 跳过编辑、历史、创建指南等非设备页面
                if any(x in category["url"] or x in category["name"] for x in ["/Edit/", "/History/", "?revision", "/Answers/", "创建指南", "Guide/new"]):
                    continue
                
                # 更新面包屑 - 注意：这里不是追加路径，而是新的独立路径
                new_breadcrumb = breadcrumb.copy()
                if category["name"] not in new_breadcrumb:
                    new_breadcrumb.append(category["name"])
                
                print(f"爬取类别: {' > '.join(new_breadcrumb)}")
                self.crawl_recursive(category["url"], new_breadcrumb, url)
        else:
            # 如果没有找到子类别但也不符合最终产品页面的定义
            product_info = self.extract_product_info(soup, url, breadcrumb)
            if product_info["product_name"]:
                self.results.append(product_info)
                print(f"已找到产品: {product_info['product_name']}")
                print(f"产品URL: {product_info['product_url']}")
                print(f"说明书链接: {product_info['instruction_url'] or '无'}")
                print(f"状态: 最终产品页面 (无子类别)")
            
    def start_crawl(self, start_url=None):
        """开始爬取"""
        if not start_url:
            # 从设备页面开始
            start_url = self.base_url + "/Device"
        
        print(f"开始爬取: {start_url}")
        # 从起始页面开始爬取
        soup = self.get_soup(start_url)
        if not soup:
            print("无法获取起始页面")
            return
            
        # 从设备首页提取所有类别
        categories = self.extract_categories(soup, start_url)
        if not categories:
            print("未在首页找到设备类别，使用预定义的设备类别")
            categories = [
                {"name": "Apple iPhone", "url": "https://zh.ifixit.com/Device/iPhone"},
                {"name": "iPad", "url": "https://zh.ifixit.com/Device/iPad"},
                {"name": "平板电脑", "url": "https://zh.ifixit.com/Device/Tablet"},
                {"name": "手机", "url": "https://zh.ifixit.com/Device/Phone"},
                {"name": "电脑硬件", "url": "https://zh.ifixit.com/Device/Computer_Hardware"}
            ]
            
        for category in categories:
            # 跳过已访问的链接
            if category["url"] in self.visited_urls:
                continue
                
            # 跳过编辑、历史等非设备页面
            if any(x in category["url"] for x in ["/Edit/", "/History/", "?revision", "/Answers/"]):
                continue
                
            print(f"爬取主类别: {category['name']}")
            self.crawl_recursive(category["url"], [category["name"]])
        
        # 保存结果
        self.save_results()
        
    def save_results(self):
        """保存爬取结果到JSON文件"""
        if not self.results:
            print("没有找到任何产品信息")
            return
            
        # 确保结果目录存在
        os.makedirs("results", exist_ok=True)
        
        # 处理产品名称中的引号问题
        for item in self.results:
            if "product_name" in item:
                # 将引号替换为英寸
                item["product_name"] = item["product_name"].replace('\\"', '英寸').replace('\\"', '英寸')
                item["product_name"] = item["product_name"].replace('"', '英寸')
                item["product_name"] = re.sub(r'(\d+)\"', r'\1英寸', item["product_name"])
            
            # 兼容旧数据，将manual_url转为instruction_url
            if "manual_url" in item and "instruction_url" not in item:
                item["instruction_url"] = item["manual_url"]
                del item["manual_url"]
        
        # 保存为JSON文件
        with open("results/ifixit_products.json", "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        print(f"已保存 {len(self.results)} 条产品信息到 results/ifixit_products.json")
    
    def save_result(self, product_info, filename=None):
        """保存单个产品信息到JSON文件"""
        # 确保结果目录存在
        os.makedirs("results", exist_ok=True)
        
        if not filename:
            # 从URL中提取文件名
            if "product_url" in product_info:
                url_parts = product_info["product_url"].split('/')
                filename = f"results/{url_parts[-1]}.json"
            else:
                filename = "results/product_info.json"
        
        # 处理产品名称中的引号问题
        if "product_name" in product_info:
            # 将引号替换为英寸
            product_info["product_name"] = product_info["product_name"].replace('\\"', '英寸').replace('\\"', '英寸')
            product_info["product_name"] = product_info["product_name"].replace('"', '英寸')
            product_info["product_name"] = re.sub(r'(\d+)\"', r'\1英寸', product_info["product_name"])
            
        # 兼容旧数据，将manual_url转为instruction_url
        if "manual_url" in product_info and "instruction_url" not in product_info:
            product_info["instruction_url"] = product_info["manual_url"]
            del product_info["manual_url"]
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(product_info, f, ensure_ascii=False, indent=2)
        
        print(f"\n已保存产品信息到 {filename}")

    def extract_youtube_videos(self, soup, url):
        """提取页面中的YouTube视频链接"""
        videos = []
        try:
            # 查找视频指南区域
            video_guides_section = None
            video_sections = soup.find_all(id=lambda x: x and "Video_Guides" in x)
            if video_sections:
                video_guides_section = video_sections[0]
                self.print_debug(f"找到视频指南区域: {video_guides_section.get_text().strip()}")
                
            # 如果找不到专门的视频区域，则尝试查找页面中所有视频
            if video_guides_section:
                # 从视频指南区域开始查找
                parent = video_guides_section.parent
                if parent:
                    # 在同一个区域内查找所有视频框
                    video_boxes = []
                    # 查找下一个大标题之前的所有内容
                    next_elem = video_guides_section.find_next()
                    while next_elem and not (next_elem.name == 'h2' or next_elem.name == 'h1'):
                        if 'videoBox' in next_elem.get('class', []) or next_elem.find(class_='videoBox'):
                            video_boxes.append(next_elem)
                        elif next_elem.find(attrs={'videoid': True}):
                            video_boxes.append(next_elem)
                        next_elem = next_elem.find_next()
                    
                    # 如果没找到，尝试查找子元素
                    if not video_boxes:
                        video_boxes = parent.find_all(class_='videoBox') or parent.find_all(attrs={'videoid': True})
                        
                    for box in video_boxes:
                        # 尝试从元素中提取视频ID
                        video_elem = box.find(attrs={'videoid': True})
                        if not video_elem and 'videoid' in box.attrs:
                            video_elem = box
                            
                        if video_elem and 'videoid' in video_elem.attrs:
                            video_id = video_elem['videoid']
                            # 构建YouTube链接
                            video_url = f"https://www.youtube.com/watch?v={video_id}"

                            # 尝试提取视频标题
                            video_title = ""
                            # 查找视频标题，通常在前面的h3标签中
                            prev_header = box.find_previous(['h3', 'h4'])
                            if prev_header:
                                video_title = prev_header.get_text().strip()
                                # 移除中文字符，保持英文内容
                                video_title = re.sub(r'[\u4e00-\u9fff]+', '', video_title)
                                video_title = re.sub(r'\s+', ' ', video_title).strip()

                            if not video_title:
                                # 如果找不到标题，使用英文标题
                                video_title = "Video Guide"

                            videos.append({
                                "url": video_url,
                                "title": video_title,
                                "video_id": video_id
                            })
                            self.print_debug(f"找到视频: {video_title} -> {video_url}")
            
            # 如果没有从视频区域找到，尝试从整个页面查找
            if not videos:
                video_elems = soup.find_all(attrs={'videoid': True})
                for video_elem in video_elems:
                    video_id = video_elem['videoid']
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    # 尝试提取视频标题
                    video_title = "Video Guide"
                    # 查找最近的标题标签
                    prev_header = video_elem.find_previous(['h1', 'h2', 'h3', 'h4', 'h5'])
                    if prev_header:
                        video_title = prev_header.get_text().strip()
                        # 移除中文字符，保持英文内容
                        video_title = re.sub(r'[\u4e00-\u9fff]+', '', video_title)
                        video_title = re.sub(r'\s+', ' ', video_title).strip()

                    videos.append({
                        "url": video_url,
                        "title": video_title,
                        "video_id": video_id
                    })
                    self.print_debug(f"找到视频: {video_title} -> {video_url}")
                    
        except Exception as e:
            self.print_debug(f"提取视频时发生错误: {str(e)}")
            
        return videos

    def extract_product_info_from_url(self, url):
        """从URL直接提取产品信息，适用于直接调用的场景"""
        soup = self.get_soup(url)
        if not soup:
            self.print_debug(f"无法获取页面内容: {url}")
            return None
            
        return self.extract_product_info(soup, url, [])

if __name__ == "__main__":
    crawler = IFixitCrawler()
    # 从设备页面开始爬取
    crawler.start_crawl("https://zh.ifixit.com/Device")
 