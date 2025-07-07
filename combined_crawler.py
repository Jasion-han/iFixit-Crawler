#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
整合爬虫工具 - 结合树形结构和详细内容提取
将iFixit网站的设备分类以层级树形结构展示，并为每个节点提取详细内容
用法: python combined_crawler.py [URL或设备名]
示例: python combined_crawler.py https://www.ifixit.com/Device/Television
      python combined_crawler.py Television
"""

import os
import sys
import json
import time
import random

# 导入两个基础爬虫
from enhanced_crawler import EnhancedIFixitCrawler
from tree_crawler import TreeCrawler

class CombinedIFixitCrawler(EnhancedIFixitCrawler):
    def __init__(self, base_url="https://www.ifixit.com", verbose=False):
        super().__init__(base_url, verbose)
        # 初始化树形爬虫的功能
        self.tree_crawler = TreeCrawler(base_url)
        self.processed_nodes = set()  # 记录已处理的节点，避免重复

        # 复制树形爬虫的重要方法到当前类
        self.find_exact_path = self.tree_crawler.find_exact_path
        self.extract_breadcrumbs_from_page = self.tree_crawler.extract_breadcrumbs_from_page
        self._build_tree_from_path = self.tree_crawler._build_tree_from_path
        self._find_node_by_url = self.tree_crawler._find_node_by_url
        self.ensure_instruction_url_in_leaf_nodes = self.tree_crawler.ensure_instruction_url_in_leaf_nodes

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

    def _is_specified_target_url(self, url):
        """
        检查URL是否是用户指定的目标URL
        """
        # 这里可以添加逻辑来检查是否是用户指定的目标URL
        # 目前简单返回False，让系统自动判断叶子节点
        return False

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
        """
        修复节点的name、title和view_statistics数据
        """
        if not node or not isinstance(node, dict):
            return node

        url = node.get('url', '')

        # 检查是否是根目录（Device页面）
        is_root_device = url == f"{self.base_url}/Device"

        # 修复name字段 - 从URL提取真实标识符
        real_name = self.extract_real_name_from_url(url)
        if real_name:
            node['name'] = real_name

        # 获取页面内容（如果还没有）
        if not soup and url:
            soup = self.get_soup(url)

        # 只对非根目录页面添加title字段
        if soup and not is_root_device:
            real_title = self.extract_real_title_from_page(soup)
            if real_title:
                node['title'] = real_title

            # 修复view_statistics - 从页面提取真实统计数据
            real_stats = self.extract_real_view_statistics(soup, url)
            if real_stats:
                node['view_statistics'] = real_stats

        return node
        
    def crawl_combined_tree(self, start_url, category_name=None):
        """
        整合爬取：构建树形结构并为每个节点提取详细内容
        """
        print(f"开始整合爬取: {start_url}")
        print("=" * 60)

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
        """
        递归地为树中的每个节点提取详细内容，并修复数据问题
        """
        if not node or not isinstance(node, dict):
            return node

        url = node.get('url', '')
        if not url or url in self.processed_nodes:
            return node

        self.processed_nodes.add(url)

        # 检查是否是根目录（Device页面）
        is_root_device = url == f"{self.base_url}/Device"

        # 添加延迟避免过快请求
        time.sleep(random.uniform(0.5, 1.0))

        # 获取页面内容
        soup = self.get_soup(url)

        # 修复节点的基本数据（name、title、view_statistics）
        node = self.fix_node_data(node, soup)

        # 判断节点类型并提取相应的详细内容
        node_type = self.get_node_type(url)

        if self.verbose:
            print(f"处理节点: {node.get('name', '')} ({node_type}) - {url}")
        else:
            print(f"处理: {node.get('name', '')} ({node_type})")

        # 根据节点类型提取详细内容
        try:
            # 检查是否应该提取详细内容
            if self.should_extract_detailed_content(url, node_type):

                if node_type == 'guide':
                    detailed_content = self.extract_guide_content(url)
                    if detailed_content:
                        node = self.merge_detailed_content_to_node(node, detailed_content, 'guide')
                        steps_count = len(detailed_content.get('steps', []))
                        videos_count = len(detailed_content.get('videos', []))
                        print(f"  ✓ 指南内容: {steps_count} 步骤, {videos_count} 视频")

                elif node_type == 'troubleshooting':
                    detailed_content = self.extract_troubleshooting_content(url)
                    if detailed_content:
                        node = self.merge_detailed_content_to_node(node, detailed_content, 'troubleshooting')
                        causes_count = len(detailed_content.get('causes', []))
                        print(f"  ✓ 故障排除内容: {causes_count} 原因")

                elif node_type == 'product':
                    # 对于产品节点，提取基本产品信息，但排除根目录
                    if soup and not is_root_device:
                        product_info = self.extract_product_info(soup, url, [])
                        if product_info and product_info.get('product_name'):
                            node['product_name'] = product_info['product_name']
                            if product_info.get('instruction_url'):
                                node['instruction_url'] = product_info['instruction_url']
                            print(f"  ✓ 产品信息: {product_info['product_name']}")
                    elif is_root_device:
                        print(f"  → 根目录节点，跳过产品信息提取")

            else:
                if node_type == 'category':
                    print(f"  → 分类节点，修复基本数据")
                else:
                    print(f"  → 跳过详细内容提取")

        except Exception as e:
            print(f"  ✗ 提取内容时出错: {str(e)}")
            if self.verbose:
                import traceback
                traceback.print_exc()

        # 递归处理子节点
        if 'children' in node and node['children']:
            enriched_children = []
            for child in node['children']:
                enriched_child = self.enrich_tree_with_detailed_content(child)
                if enriched_child:
                    enriched_children.append(enriched_child)
            node['children'] = enriched_children

        return node
        
    def get_node_type(self, url):
        """
        判断节点类型：guide, troubleshooting, product, category
        """
        if '/Guide/' in url:
            return 'guide'
        elif '/Troubleshooting/' in url:
            return 'troubleshooting'
        else:
            # 需要获取页面内容来进一步判断
            soup = self.get_soup(url)
            if soup:
                # 检查是否是故障排除页面
                if self.is_troubleshooting_page(soup):
                    return 'troubleshooting'
                # 检查是否是最终产品页面
                elif self.is_final_product_page(soup, url):
                    return 'product'
            
        return 'category'
        
    def is_troubleshooting_page(self, soup):
        """
        检查页面是否是故障排除页面
        """
        if not soup:
            return False

        # 检查页面标题
        title_elem = soup.select_one("h1")
        if title_elem:
            title_text = title_elem.get_text().lower()
            if any(keyword in title_text for keyword in ['troubleshooting', '故障排除', 'problems', 'issues']):
                return True

        # 检查页面内容中是否包含故障排除相关的结构
        troubleshooting_indicators = [
            '.troubleshooting-section',
            '.problem-section',
            '.issue-section',
            '[href*="#Section_"]'  # 故障排除页面通常有这种锚点链接
        ]

        for indicator in troubleshooting_indicators:
            if soup.select(indicator):
                return True

        # 检查是否有编号的原因链接（故障排除页面的特征）
        cause_links = soup.find_all('a', href=lambda x: x and '#Section_' in x)
        if len(cause_links) >= 2:  # 至少有2个原因链接
            return True

        return False

    def should_extract_detailed_content(self, url, node_type):
        """
        判断是否应该为该节点提取详细内容
        """
        # 跳过某些不需要详细内容的页面
        skip_patterns = [
            '/Edit/', '/History/', '?revision', '/Answers/',
            'action=edit', 'action=create', '/new'
        ]

        for pattern in skip_patterns:
            if pattern in url:
                return False

        # 对于指南和故障排除页面，总是提取详细内容
        if node_type in ['guide', 'troubleshooting']:
            return True

        # 对于产品页面，如果是叶子节点则提取
        if node_type == 'product':
            return True

        # 分类页面不需要详细内容
        return False
        
    def merge_detailed_content_to_node(self, node, detailed_content, content_type):
        """
        将详细内容合并到树节点中，保持树形结构
        """
        if not detailed_content:
            return node

        # 保留原有的树形结构字段
        original_name = node.get('name', '')
        original_url = node.get('url', '')
        original_children = node.get('children', [])

        # 合并详细内容，按照 enhanced_crawler 的字段顺序
        if content_type == 'guide':
            # 对于指南，按照 enhanced_crawler 的字段顺序合并
            ordered_fields = ['title', 'time_required', 'difficulty', 'introduction',
                            'what_you_need', 'view_statistics', 'completed', 'favorites',
                            'videos', 'steps']

            for field in ordered_fields:
                if field in detailed_content and detailed_content[field]:
                    node[field] = detailed_content[field]

            # 添加其他可能存在的字段
            for key, value in detailed_content.items():
                if key not in ['url'] + ordered_fields and value:
                    node[key] = value

        elif content_type == 'troubleshooting':
            # 对于故障排除，按照 enhanced_crawler 的字段顺序合并
            ordered_fields = ['title', 'view_statistics', 'completed', 'favorites', 'causes']

            for field in ordered_fields:
                if field in detailed_content and detailed_content[field]:
                    node[field] = detailed_content[field]

            # 添加动态提取的字段
            for key, value in detailed_content.items():
                if key not in ['url'] + ordered_fields and value:
                    node[key] = value

        # 确保树形结构字段存在且正确，并保持正确的字段顺序
        # 重新构建节点，确保字段顺序：name -> url -> title -> 其他详细内容字段 -> children
        new_node = {}
        new_node['name'] = original_name
        new_node['url'] = original_url

        # 优先添加title字段（如果存在）
        if 'title' in node:
            new_node['title'] = node['title']

        # 添加其他详细内容字段（排除已处理的字段）
        for key, value in node.items():
            if key not in ['name', 'url', 'title', 'children']:
                new_node[key] = value

        new_node['children'] = original_children

        return new_node

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

    def deep_crawl_product_content(self, node):
        """
        深入爬取产品页面的指南和故障排除内容，并正确构建数据结构
        """
        if not node or not isinstance(node, dict):
            return node

        url = node.get('url', '')

        # 检查是否是目标产品页面（叶子节点页面，包含实际的guides和troubleshooting内容）
        # 目标页面特征：
        # 1. 是Device页面
        # 2. 不是编辑、历史等功能页面
        # 3. 没有子类别（是叶子节点）或者是用户指定的目标URL
        is_target_page = (
            '/Device/' in url and
            not any(skip in url for skip in ['/Guide/', '/Troubleshooting/', '/Edit/', '/History/', '/Answers/']) and
            (not node.get('children') or len(node.get('children', [])) == 0 or self._is_specified_target_url(url))
        )

        if is_target_page:
            print(f"深入爬取目标产品页面: {node.get('name', '')}")

            # 使用 enhanced_crawler 的逻辑提取该页面的所有指南和故障排除内容
            try:
                # 获取页面内容
                soup = self.get_soup(url)
                if soup:
                    # 修复节点的基本数据
                    node = self.fix_node_data(node, soup)

                    # 提取指南链接
                    guides = self.extract_guides_from_device_page(soup, url)
                    guide_links = [guide["url"] for guide in guides]
                    print(f"  找到 {len(guide_links)} 个指南")

                    # 提取故障排除链接
                    troubleshooting_links = self.extract_troubleshooting_from_device_page(soup, url)
                    print(f"  找到 {len(troubleshooting_links)} 个故障排除页面")

                    # 创建guides和troubleshooting数组而不是children
                    guides_data = []
                    troubleshooting_data = []

                    # 添加指南数据 - 爬取所有指南，不限制数量
                    for guide_link in guide_links:
                        guide_content = self.extract_guide_content(guide_link)
                        if guide_content:
                            # 不添加name字段，只设置url
                            guide_content['url'] = guide_link
                            guides_data.append(guide_content)
                            print(f"    ✓ 指南: {guide_content.get('title', '')}")

                    # 添加故障排除数据 - 爬取所有故障排除，不限制数量
                    for ts_link in troubleshooting_links:
                        # 确保 ts_link 是字符串
                        if isinstance(ts_link, dict):
                            ts_url = ts_link.get('url', '')
                        else:
                            ts_url = ts_link

                        if ts_url:
                            ts_content = self.extract_troubleshooting_content(ts_url)
                            if ts_content:
                                # 不添加name字段，只设置url
                                ts_content['url'] = ts_url
                                troubleshooting_data.append(ts_content)
                                print(f"    ✓ 故障排除: {ts_content.get('title', '')}")

                    # 使用正确的数据结构
                    if guides_data:
                        node['guides'] = guides_data
                    if troubleshooting_data:
                        node['troubleshooting'] = troubleshooting_data

                    # 移除children字段，因为这是目标页面
                    if 'children' in node:
                        del node['children']

                    print(f"  总计: {len(guides_data)} 个指南, {len(troubleshooting_data)} 个故障排除")

            except Exception as e:
                print(f"  ✗ 深入爬取时出错: {str(e)}")

        # 递归处理子节点（对于非目标页面）
        elif 'children' in node and node['children']:
            for i, child in enumerate(node['children']):
                node['children'][i] = self.deep_crawl_product_content(child)

        return node
        
    def save_combined_result(self, tree_data, filename=None, target_name=None):
        """
        保存整合结果到JSON文件
        """
        # 确保结果目录存在
        os.makedirs("results", exist_ok=True)
        
        if not filename:
            if target_name:
                safe_name = target_name.replace("/", "_").replace("\\", "_").replace(":", "_")
                filename = f"results/combined_{safe_name}.json"
            else:
                root_name = tree_data.get("name", "combined")
                if " > " in root_name:
                    root_name = root_name.split(" > ")[-1]
                root_name = root_name.replace("/", "_").replace("\\", "_").replace(":", "_")
                filename = f"results/combined_{root_name}.json"
        
        # 保存为JSON文件
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
    print("python combined_crawler.py [URL或设备名]")
    print("例如: python combined_crawler.py https://www.ifixit.com/Device/Television")
    print("      python combined_crawler.py Television")

def main():
    # 检查是否提供了参数
    if len(sys.argv) > 1:
        input_text = sys.argv[1]

        # 检查帮助参数
        if input_text.lower() in ['--help', '-h', 'help']:
            print_usage()
            return

        verbose = len(sys.argv) > 2 and sys.argv[2].lower() in ('verbose', 'debug', 'true', '1')
    else:
        print("=" * 60)
        print("iFixit整合爬虫工具 - 树形结构 + 详细内容")
        print("=" * 60)
        print("\n请输入要爬取的iFixit产品名称或URL:")
        print("例如: 70UK6570PUB            - 指定产品型号")
        print("      https://www.ifixit.com/Device/70UK6570PUB - 指定产品URL")
        print("      Television             - 电视类别")
        print("      LG_Television          - 品牌电视类别")

        input_text = input("\n> ").strip()
        verbose = input("\n是否开启详细输出? (y/n): ").strip().lower() == 'y'

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
        crawler = CombinedIFixitCrawler(verbose=verbose)

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
