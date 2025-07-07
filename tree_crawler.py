#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
树形结构爬虫工具
将iFixit网站的设备分类以层级树形结构展示
用法: python tree_crawler.py [URL或设备名]
示例: python tree_crawler.py https://www.ifixit.com/Device/Television
      python tree_crawler.py Television
"""

import os
import sys
import json
import time
import random
import re
from crawler import IFixitCrawler

class TreeCrawler(IFixitCrawler):
    def __init__(self, base_url="https://www.ifixit.com"):
        super().__init__(base_url)
        self.tree_data = {}  # 存储树形结构数据
        
    def find_exact_path(self, target_url):
        """
        从根目录开始，找到到达目标URL的确切路径
        优先使用网页内面包屑导航提取完整路径
        """
        # 确保目标URL被正确编码
        import urllib.parse
        # 先解码再重新编码，确保一致性
        decoded_url = urllib.parse.unquote(target_url)
        # 重新编码，确保引号等特殊字符被正确处理
        target_url = urllib.parse.quote(decoded_url, safe=':/?#[]@!$&\'()*+,;=')

        # 始终从设备根目录开始
        device_url = self.base_url + "/Device"

        # 如果目标就是根目录，则直接返回
        if target_url == device_url:
            return [{"name": "设备", "url": device_url}]
        
        # 从目标页面提取面包屑导航
        target_soup = self.get_soup(target_url)
        if not target_soup:
            print(f"无法获取页面内容: {target_url}")
            return [{"name": "设备", "url": device_url}]
        
        # 尝试从页面提取面包屑导航
        breadcrumbs = self.extract_breadcrumbs_from_page(target_soup)
        
        # 如果成功提取到面包屑导航
        if breadcrumbs and len(breadcrumbs) > 1:
            print(f"从页面提取到面包屑导航: {' > '.join(breadcrumbs)}")
            
            # 构建完整的路径
            path = []
            
            # 映射常见的中文分类名称到URL路径部分
            category_map = {
                "设备": "Device",
                "电子产品": "Electronics",
                "电视": "Television",
                "耳机": "Headphone",
                "手机": "Phone",
                "平板电脑": "Tablet",
                "笔记本电脑": "Laptop",
                "游戏机": "Game_Console",
                "相机": "Camera"
            }
            
            # 重新设计URL构建逻辑：每个层级都是真实的页面URL，不是拼接路径
            # 从/Device页面开始，逐层查找真实的URL

            path = []
            current_page_url = f"{self.base_url}/Device"

            # 第一级：Device页面
            path.append({
                "name": breadcrumbs[0],
                "url": current_page_url
            })

            # 逐层查找真实URL
            for i in range(1, len(breadcrumbs)):
                crumb_name = breadcrumbs[i]

                # 如果是最后一级，确保目标URL被正确编码
                if i == len(breadcrumbs) - 1:
                    # 再次确保URL被正确编码
                    import urllib.parse
                    decoded_target = urllib.parse.unquote(target_url)
                    encoded_target = urllib.parse.quote(decoded_target, safe=':/?#[]@!$&\'()*+,;=')
                    path.append({
                        "name": crumb_name,
                        "url": encoded_target
                    })
                    break

                # 在当前页面中查找匹配的子类别链接
                real_url = self._find_real_url_for_category(current_page_url, crumb_name)

                if real_url:
                    current_page_url = real_url
                    path.append({
                        "name": crumb_name,
                        "url": real_url
                    })
                else:
                    # 如果找不到真实URL，使用fallback逻辑
                    print(f"警告：无法找到 '{crumb_name}' 的真实URL，使用fallback")
                    fallback_url = self._generate_fallback_url(crumb_name)
                    current_page_url = fallback_url
                    path.append({
                        "name": crumb_name,
                        "url": fallback_url
                    })
            
            # 修复URL路径
            fixed_path = []
            for item in path:
                url = item["url"]
                name = item["name"]
                
                # 处理一些常见的URL映射问题
                if "电子产品" in name and not "/Electronics" in url:
                    url = f"{self.base_url}/Device/Electronics"
                elif "耳机" in name and not "/Headphone" in url:
                    url = f"{self.base_url}/Device/Headphone"
                elif "电视" in name and not "/Television" in url:
                    url = f"{self.base_url}/Device/Television"
                elif "Apple Headphone" in name:
                    url = f"{self.base_url}/Device/Apple_Headphone"
                
                fixed_path.append({"name": name, "url": url})
            
            return fixed_path
        
        # 如果面包屑提取失败，尝试根据URL结构推断路径
        print("面包屑导航提取失败，尝试根据URL推断路径")
        
        # 从目标URL构建路径
        parts = target_url.split("/")
        if len(parts) >= 5 and "Device" in parts:
            device_index = parts.index("Device")
            if device_index < len(parts) - 1:
                # 提取Device后面的所有部分
                category_parts = parts[device_index+1:]
                
                # 构建标准路径
                path = [{"name": "设备", "url": device_url}]
                
                # 构建路径
                current_path = device_url
                for part in category_parts:
                    # 推断分类名称
                    if part == "Electronics":
                        name = "电子产品"
                    elif part == "Television":
                        name = "电视"
                    elif part == "Headphone":
                        name = "耳机"
                    else:
                        name = part.replace("_", " ")
                    
                    current_path = f"{current_path}/{part}"
                    path.append({"name": name, "url": current_path})
                
                return path
        
        # 最后的备选方案：使用传统的爬取方法
        print("URL推断失败，使用爬取方法查找路径")
        return self._find_path_to_target(device_url, target_url, [{"name": "设备", "url": device_url}])

    def _find_real_url_for_category(self, current_page_url, category_name):
        """
        在当前页面中查找指定类别的真实URL
        """
        try:
            soup = self.get_soup(current_page_url)
            if not soup:
                return None

            # 提取当前页面的所有子类别
            categories = self.extract_categories(soup, current_page_url)

            # 智能匹配类别名称
            for category in categories:
                if self._is_category_match(category["name"], category_name):
                    print(f"找到真实URL: {category_name} -> {category['url']}")
                    return category["url"]

            print(f"在页面 {current_page_url} 中未找到匹配的类别: {category_name}")
            return None

        except Exception as e:
            print(f"查找真实URL时出错: {str(e)}")
            return None

    def _is_category_match(self, page_link_name, breadcrumb_name):
        """
        智能匹配页面链接名称和面包屑名称
        """
        # 清理和标准化名称
        def normalize_name(name):
            return name.lower().strip().replace(" repair", "").replace(" devices", "")

        page_name = normalize_name(page_link_name)
        crumb_name = normalize_name(breadcrumb_name)

        # 精确匹配
        if page_name == crumb_name:
            return True

        # 包含匹配
        if crumb_name in page_name or page_name in crumb_name:
            return True

        # 特殊映射
        mappings = {
            "mac": ["mac", "macintosh"],
            "laptop": ["laptop", "notebook"],
            "macbook pro": ["macbook pro", "macbook_pro"],
            "17\"": ["17\"", "17 inch", "17-inch"]
        }

        for key, values in mappings.items():
            if crumb_name in values and any(v in page_name for v in values):
                return True

        return False

    def _generate_fallback_url(self, category_name):
        """
        生成fallback URL（当无法找到真实URL时使用）
        """
        # 简单的fallback：使用Device + 类别名称
        clean_name = category_name.replace(" ", "_").replace("\"", "%22")
        return f"{self.base_url}/Device/{clean_name}"

    def extract_breadcrumbs_from_page(self, soup):
        """从页面提取面包屑导航"""
        breadcrumbs = []
        
        try:
            # 方法1: 从React组件数据中提取完整面包屑 (最准确的方法)
            breadcrumb_component = soup.select_one(".component-NavBreadcrumbs")
            if breadcrumb_component:
                data_props = breadcrumb_component.get("data-props")
                if data_props:
                    # 尝试从JSON数据中提取面包屑
                    import json
                    import html
                    
                    # 解码HTML实体
                    decoded_props = html.unescape(data_props)
                    
                    # 解析JSON
                    try:
                        props_data = json.loads(decoded_props)
                        if "breadcrumbs" in props_data and isinstance(props_data["breadcrumbs"], list):
                            react_breadcrumbs = []
                            for crumb in props_data["breadcrumbs"]:
                                if "name" in crumb and crumb["name"]:
                                    # 这里的name可能是中文的"设备"、"电子产品"等
                                    react_breadcrumbs.append(crumb["name"])
                            
                            if react_breadcrumbs:
                                print(f"从React组件提取到面包屑: {' > '.join(react_breadcrumbs)}")
                                return react_breadcrumbs
                    except json.JSONDecodeError:
                        print("无法解析面包屑JSON数据")
            
            # 方法2: 从页面的meta标签中提取(备选方法)
            breadcrumb_items = soup.select("[itemtype='http://schema.org/BreadcrumbList'] [itemtype='http://schema.org/ListItem']")
            if breadcrumb_items:
                schema_breadcrumbs = []
                for item in breadcrumb_items:
                    name_meta = item.select_one("[itemprop='name']")
                    if name_meta and name_meta.get("content"):
                        schema_breadcrumbs.append(name_meta.get("content"))
                
                if schema_breadcrumbs:
                    print(f"从Schema.org标记提取到面包屑: {' > '.join(schema_breadcrumbs)}")
                    return schema_breadcrumbs
                
            # 方法3: 直接从面包屑容器中提取链接
            breadcrumbs_container = soup.select_one(".breadcrumbs-container")
            if breadcrumbs_container:
                links = breadcrumbs_container.select("a")
                if links:
                    container_breadcrumbs = []
                    for link in links:
                        text = link.get_text().strip()
                        if text:
                            container_breadcrumbs.append(text)
                    
                    if container_breadcrumbs:
                        print(f"从面包屑容器提取到: {' > '.join(container_breadcrumbs)}")
                        return container_breadcrumbs
            
            # 方法4: 从页面头部的导航链接中提取
            page_header = soup.select_one("#page-header-container")
            if page_header:
                nav_links = page_header.select("a")
                standard_breadcrumbs = []
                for link in nav_links:
                    href = link.get("href", "")
                    text = link.get_text().strip()
                    # 只保留有效的设备相关链接，过滤掉"创建指南"等
                    if ("/Device/" in href and 
                        text and 
                        not any(invalid in text.lower() for invalid in ["创建", "翻译", "贡献者", "论坛", "guide"])):
                        standard_breadcrumbs.append(text)
                
                if standard_breadcrumbs:
                    print(f"从页面顶部提取到面包屑: {' > '.join(standard_breadcrumbs)}")
                    return standard_breadcrumbs
            
            # 方法5: 从URL结构推断基本路径
            # 这是最后的备选方法，如果前面的方法都失败了
            url_path = soup.select_one("link[rel='canonical']")
            if url_path:
                url = url_path.get("href", "")
                if "Headphone" in url:
                    # 耳机类别的标准路径
                    return ["设备", "电子产品", "耳机", url.split("/")[-1].replace("_", " ")]
                elif "Television" in url:
                    # 电视类别的标准路径
                    if "_" in url:
                        brand = url.split("/")[-1].split("_")[0]
                        return ["设备", "电子产品", "电视", f"{brand} Television"]
                    else:
                        return ["设备", "电子产品", "电视"]
                elif "Electronics" in url:
                    return ["设备", "电子产品"]
                
            # 如果所有方法都失败，返回空列表
            print("无法提取面包屑导航")
            return []
                
        except Exception as e:
            print(f"提取面包屑时出错: {e}")
            
        return breadcrumbs
    
    def _find_path_to_target(self, current_url, target_url, current_path):
        """递归向下查找目标URL的路径"""
        print(f"检查路径: {current_url}")
        
        # 先检查当前URL是否就是目标URL
        if current_url == target_url:
            return current_path
            
        # 获取当前页面内容
        soup = self.get_soup(current_url)
        if not soup:
            return None
        
        # 提取当前页面上的所有子类别
        categories = self.extract_categories(soup, current_url)
        
        # 过滤掉"创建指南"等非实际类别
        real_categories = [c for c in categories if not any(x in c["name"] or x in c["url"] for x in ["创建指南", "Guide/new"])]
        
        # 检查目标URL是否在当前页面的直接子类别中
        for category in real_categories:
            if category["url"] == target_url:
                # 找到了目标，添加到路径并返回
                clean_name = category["name"].replace(" Repair", "")
                current_path.append({"name": clean_name, "url": target_url})
                return current_path
        
        # 特殊处理LG_Television的情况
        target_url_lower = target_url.lower()
        if "lg_television" in target_url_lower:
            # 检查是否在电视类别下
            if "television" in current_url.lower():
                for category in real_categories:
                    if "lg" in category["name"].lower() and "television" in category["name"].lower():
                        # 找到了LG Television类别
                        clean_name = category["name"].replace(" Repair", "")
                        current_path.append({"name": clean_name, "url": target_url})
                        return current_path
        
        # 如果目标不是当前页面的直接子类别，检查每个子类别下是否存在目标
        # 优先检查名称或URL中包含目标关键字的类别
        prioritized_categories = []
        other_categories = []
        
        # 从目标URL中提取关键字
        target_keywords = target_url.split("/")[-1].replace("_", " ").lower().split()
        
        for category in real_categories:
            # 避免重复访问已在路径中的URL
            if any(item["url"] == category["url"] for item in current_path):
                continue
                
            # 检查类别名称或URL是否包含目标关键字
            category_name_lower = category["name"].lower()
            category_url_lower = category["url"].lower()
            
            has_keyword = False
            for keyword in target_keywords:
                if len(keyword) > 2 and (keyword in category_name_lower or keyword in category_url_lower):
                    has_keyword = True
                    break
                    
            # 根据是否包含关键字分组
            if has_keyword:
                prioritized_categories.append(category)
            else:
                other_categories.append(category)
        
        # 先检查优先级高的类别
        for category in prioritized_categories:
            # 添加当前类别到临时路径
            clean_name = category["name"].replace(" Repair", "")
            temp_path = current_path.copy()
            temp_path.append({"name": clean_name, "url": category["url"]})
            
            # 递归检查该类别
            result = self._find_path_to_target(category["url"], target_url, temp_path)
            if result:
                return result
        
        # 如果在优先级高的类别中没有找到，检查其他类别
        for category in other_categories:
            # 添加当前类别到临时路径
            clean_name = category["name"].replace(" Repair", "")
            temp_path = current_path.copy()
            temp_path.append({"name": clean_name, "url": category["url"]})
            
            # 递归检查该类别
            result = self._find_path_to_target(category["url"], target_url, temp_path)
            if result:
                return result
        
        # 如果在所有子类别中都没有找到目标，返回None
        return None
        
    def find_parent_categories(self, url, current_name):
        """查找给定URL的所有父类别，构建完整的分类路径"""
        # 使用新的精确路径查找方法
        exact_path = self.find_exact_path(url)
        if exact_path:
            print(f"找到精确路径: {' > '.join([c['name'] for c in exact_path])}")
            return exact_path
        
        # 如果精确路径查找失败，回退到传统方法
        print("精确路径查找失败，尝试备用查找方法...")
        
        parent_categories = []
        
        # 先添加当前类别
        parent_categories.append({"name": current_name, "url": url})
        
        # 检查是否是设备根目录
        if url == self.base_url + "/Device":
            return parent_categories
        
        # 添加设备根目录作为最顶层
        if not any(c["url"] == self.base_url + "/Device" for c in parent_categories):
            parent_categories.append({"name": "设备", "url": self.base_url + "/Device"})
            
        # 返回找到的分类路径（反转顺序，从根到叶）
        return list(reversed(parent_categories))
        
    def _get_page_title(self, soup):
        """从页面提取更准确的标题"""
        # 尝试从标题标签获取
        title_elem = soup.select_one("div.device-title h1, h1.device-title, h1.title, h1")
        if title_elem:
            title = title_elem.get_text().strip()
            # 移除"Repair"等后缀
            title = title.replace(" Repair", "").replace(" repair", "")
            return title
            
        # 尝试从面包屑导航获取
        breadcrumbs = self.extract_breadcrumbs(soup)
        if breadcrumbs and len(breadcrumbs) > 0:
            return breadcrumbs[-1]
            
        # 尝试从页面标题获取
        if soup.title:
            title = soup.title.string
            # 移除网站名称和"Repair"等后缀
            title = title.replace(" - iFixit", "").replace(" - iFixit.cn", "")
            title = title.replace(" Repair", "").replace(" repair", "")
            return title
            
        return None

    def crawl_tree(self, start_url=None, category_name=None):
        """以树形结构爬取设备分类"""
        if not start_url:
            # 从设备页面开始
            start_url = self.base_url + "/Device"
            category_name = "设备"
            
        print(f"开始爬取: {start_url}")
        
        # 检查是否是品牌电视页面(如TCL_Television, LG_Television等)
        brand_match = re.search(r'([A-Za-z]+)_Television', start_url)
        if brand_match:
            brand_name = brand_match.group(1)
            print(f"检测到 {brand_name} Television 页面，构建标准路径")
            
            # 直接构建标准四级路径: 设备 > 电子产品 > 电视 > 品牌电视
            device_url = self.base_url + "/Device"
            electronics_url = self.base_url + "/Device/Electronics"
            tv_url = self.base_url + "/Device/Television"
            
            full_path = [
                {"name": "设备", "url": device_url},
                {"name": "电子产品", "url": electronics_url},
                {"name": "电视", "url": tv_url},
                {"name": f"{brand_name} Television", "url": start_url}
            ]
            
            print(f"标准路径构建完成: {' > '.join([c['name'] for c in full_path])}")
            
            # 构建树形结构
            tree = self._build_tree_from_path(full_path)
            
            # 找到目标节点
            target_node = self._find_node_by_url(tree, start_url)
            if not target_node:
                target_node = tree
            
            # 从目标节点开始爬取子类别
            print(f"开始从 {target_node['url']} 爬取子类别")
            self._crawl_recursive_tree(target_node["url"], target_node)
            
            return tree
        
        # 对于其他URL，尝试构建从根目录到目标URL的精确路径
        full_path = self.find_exact_path(start_url)
        if not full_path or len(full_path) < 2:
            print(f"无法找到从根目录到 {start_url} 的路径，尝试从页面元素中提取更多信息")
            
            # 尝试获取页面内容以检查页面结构
            target_soup = self.get_soup(start_url)
            if target_soup:
                # 从页面标题或面包屑中推断名称
                page_title = self._get_page_title(target_soup)
                
                # 检查是否包含电视相关内容
                if "Television" in start_url or "TV" in start_url or "电视" in page_title:
                    print("检测到电视相关页面，查找电视类别路径")
                    # 尝试构建电视相关路径
                    tv_path = self.find_tv_path(start_url, category_name)
                    if tv_path:
                        full_path = tv_path
                        
            # 如果仍然无法找到路径，使用基本路径
            if not full_path or len(full_path) < 2:
                print(f"无法找到完整路径，使用基本路径")
                full_path = [{"name": "设备", "url": self.base_url + "/Device"}]
                if start_url != self.base_url + "/Device":
                    full_path.append({"name": category_name or start_url.split("/")[-1].replace("_", " "), "url": start_url})
        
        print(f"完整路径: {' > '.join([c['name'] for c in full_path])}")
        
        # 2. 构建树形结构
        tree = self._build_tree_from_path(full_path)
        
        # 3. 根据完整路径找到目标节点
        target_node = self._find_node_by_url(tree, start_url)
        if not target_node:
            print("无法在树中找到目标节点，使用根节点")
            target_node = tree

        # 4. 只对目标节点进行内容爬取，保留完整路径结构
        print(f"开始从 {target_node['url']} 爬取子类别")

        # 检查目标节点是否是叶子节点（最终产品页面）
        soup = self.get_soup(target_node["url"])
        if soup:
            # 检查是否为最终产品页面
            is_final_page = self.is_final_product_page(soup, target_node["url"])

            if is_final_page:
                # 如果是最终产品页面，提取产品信息但保留路径结构
                product_info = self.extract_product_info(soup, target_node["url"], [])
                if product_info["product_name"]:
                    target_node["name"] = product_info["product_name"]
                    # 检查是否是根目录，不给根目录添加instruction_url
                    target_url = target_node.get("url", "")
                    is_root_device = target_url == f"{self.base_url}/Device"
                    if not is_root_device:
                        target_node["instruction_url"] = product_info["instruction_url"]
                    print(f"已找到产品: {product_info['product_name']}")
            else:
                # 如果不是最终产品页面，进行正常的子类别爬取
                self._crawl_recursive_tree(target_node["url"], target_node)

        return tree
        
    def find_tv_path(self, target_url, category_name):
        """
        尝试构建电视类别的路径
        首先查找Electronics页面，然后查找Television页面
        """
        path = []
        
        # 设备根目录
        device_url = self.base_url + "/Device"
        path.append({"name": "设备", "url": device_url})
        
        # 电子产品类别
        electronics_url = self.base_url + "/Device/Electronics"
        electronics_soup = self.get_soup(electronics_url)
        if electronics_soup:
            path.append({"name": "电子产品", "url": electronics_url})
            
            # 查找电视类别
            categories = self.extract_categories(electronics_soup, electronics_url)
            for category in categories:
                if "Television" in category["url"] or "电视" in category["name"]:
                    # 添加电视类别
                    tv_url = category["url"]
                    path.append({"name": "电视", "url": tv_url})
                    
                    # 在电视类别页面中查找目标类别
                    tv_soup = self.get_soup(tv_url)
                    if tv_soup:
                        tv_categories = self.extract_categories(tv_soup, tv_url)
                        for tv_cat in tv_categories:
                            # 检查是否是我们要找的目标类别
                            if tv_cat["url"] == target_url:
                                path.append({"name": tv_cat["name"], "url": tv_cat["url"]})
                                return path
                                
                            # 如果目标类别在下一级，继续查找
                            if category_name in tv_cat["name"] or category_name in tv_cat["url"]:
                                path.append({"name": tv_cat["name"], "url": tv_cat["url"]})
                                
                                # 查找下一级
                                sub_soup = self.get_soup(tv_cat["url"])
                                if sub_soup:
                                    sub_categories = self.extract_categories(sub_soup, tv_cat["url"])
                                    for sub_cat in sub_categories:
                                        if sub_cat["url"] == target_url:
                                            path.append({"name": sub_cat["name"], "url": sub_cat["url"]})
                                            return path
                                
                                # 即使没有找到确切匹配，也返回当前路径
                                return path
        
        return None
        
    def _build_tree_from_path(self, path):
        """根据路径构建树结构"""
        if not path:
            return None
            
                    # 根节点
        root_node = {
            "name": path[0]["name"],
            "url": path[0]["url"],
            "children": []
        }
        
        current_node = root_node
        
        # 构建路径上的每个节点
        for i in range(1, len(path)):
            new_node = {
                "name": path[i]["name"],
                "url": path[i]["url"],
                "children": []
            }
            
            # 添加为当前节点的子节点
            current_node["children"].append(new_node)
            
            # 更新当前节点
            current_node = new_node
            
        return root_node
        
    def _find_node_by_url(self, node, target_url):
        """在树中查找指定URL的节点"""
        if node["url"] == target_url:
            return node
            
        if "children" in node:
            for child in node["children"]:
                result = self._find_node_by_url(child, target_url)
                if result:
                    return result
                    
        return None
        
    def _crawl_recursive_tree(self, url, parent_node):
        """递归爬取树形结构"""
        # 防止重复访问同一URL
        if url in self.visited_urls:
            return
            
        # 跳过不应包含在树结构中的页面类型
        invalid_keywords = ["创建指南", "Guide/new", "翻译", "贡献者", "论坛问题", "其他贡献"]
        if any(keyword in url for keyword in invalid_keywords):
            print(f"跳过无效页面: {url}")
            return
            
        self.visited_urls.add(url)
        
        # 防止过快请求，添加延迟
        time.sleep(random.uniform(0.5, 1.0))
        
        # 构建当前位置的分类路径显示
        path_str = self._get_current_path(parent_node, self.tree_cache if hasattr(self, 'tree_cache') else None)
        print(f"爬取: {path_str} > {url.split('/')[-1]}")
        
        soup = self.get_soup(url)
        if not soup:
            return
            
        # 提取子类别
        categories = self.extract_categories(soup, url)
        
        # 过滤掉不应包含在树结构中的类别
        real_categories = []
        for category in categories:
            category_name = category["name"].lower()
            category_url = category["url"].lower()
            
            # 检查是否为有效类别
            if not any(keyword.lower() in category_name or keyword.lower() in category_url for keyword in invalid_keywords):
                # 额外检查确认是否为产品或产品类别
                if ("/Device/" in category["url"] and  
                    not any(x in category["url"] for x in ["/Edit/", "/History/", "?revision", "/Answers/"])):
                    real_categories.append(category)
        
        # 处理品牌电视页面，如TCL_Television或LG_Television
        brand_match = re.search(r'([A-Za-z]+)_Television', url)
        if brand_match:
            brand_name = brand_match.group(1)
            print(f"检测到{brand_name} Television页面，尝试查找所有子类别")
            
            # 查找类别数量提示
            category_count_elements = soup.find_all(string=re.compile(r"\d+\s*个类别"))
            for element in category_count_elements:
                count_text = element.strip()
                print(f"找到类别数量提示: {count_text}")
                
                # 查找包含类别的区域
                parent = element.parent
                if parent:
                    # 查找之后的div，通常包含类别列表
                    next_section = parent.find_next_sibling()
                    if next_section:
                        # 查找所有链接
                        links = next_section.find_all("a", href=True)
                        for link in links:
                            href = link.get("href")
                            text = link.text.strip()
                            
                            # 检查链接是否有效
                            if (href and text and "/Device/" in href and 
                                not any(invalid in text.lower() or invalid in href.lower() 
                                        for invalid in invalid_keywords)):
                                
                                full_url = self.base_url + href if href.startswith("/") else href
                                
                                # 检查是否已经在类别列表中
                                if not any(c["url"] == full_url for c in real_categories):
                                    print(f"添加品牌电视子类别: {text} - {full_url}")
                                    real_categories.append({
                                        "name": text,
                                        "url": full_url
                                    })
        
        # 检查是否为最终产品页面
        is_final_page = self.is_final_product_page(soup, url)
        
        # 如果是最终产品页面（没有子类别），则提取产品信息
        if is_final_page:
            product_info = self.extract_product_info(soup, url, [])

            # 只有当产品名称不为空时才添加到结果中
            if product_info["product_name"]:
                # 设置当前节点为叶子节点(产品)
                parent_node["name"] = product_info["product_name"]
                # 检查是否是根目录，不给根目录添加instruction_url
                is_root_device = url == f"{self.base_url}/Device"
                if not is_root_device:
                    parent_node["instruction_url"] = product_info["instruction_url"]
                print(f"已找到产品: {path_str} > {product_info['product_name']}")
        else:
            # 如果是我们的目标节点（如70UK6570PUB），将其视为产品和分类的混合类型
            if "70UK6570PUB" in url:
                # 先提取产品信息
                product_info = self.extract_product_info(soup, url, [])
                if product_info["product_name"]:
                    # 设置当前节点为产品
                    parent_node["name"] = product_info["product_name"]
                    # 检查是否是根目录，不给根目录添加instruction_url
                    is_root_device = url == f"{self.base_url}/Device"
                    if not is_root_device:
                        parent_node["instruction_url"] = product_info["instruction_url"]

                    # 同时让它保持category类型的children属性，继续向下爬取
                    print(f"找到产品与分类混合节点: {path_str} > {product_info['product_name']}")
            
            # 确保所有叶子节点(没有子节点的节点)都有instruction_url字段
            if not is_final_page and "children" in parent_node and (not parent_node["children"] or len(parent_node["children"]) == 0) and "instruction_url" not in parent_node:
                parent_node["instruction_url"] = ""
                print(f"添加缺失的instruction_url字段到叶子节点: {parent_node.get('name', '')}")
                
            # 如果有子类别，则继续递归爬取
            if real_categories:
                # 分类节点处理
                
                print(f"类别页面: {path_str}")
                print(f"找到 {len(real_categories)} 个子类别")
                
                # 限制子类别数量，避免爬取过多内容
                max_categories = 50  # 调整为适合的值
                if len(real_categories) > max_categories:
                    print(f"子类别数量过多，仅爬取前 {max_categories} 个")
                    real_categories = real_categories[:max_categories]
                
                # 遍历并爬取子类别
                for category in real_categories:
                    # 跳过已访问的链接
                    if category["url"] in self.visited_urls:
                        continue
                        
                    # 跳过编辑、历史、创建指南等非设备页面
                    if any(x in category["url"] or x in category["name"] for x in ["/Edit/", "/History/", "?revision", "/Answers/", "创建指南", "Guide/new"]):
                        continue
                    
                    # 清理类别名称（移除"Repair"等后缀）
                    clean_name = category["name"]
                    if " Repair" in clean_name:
                        clean_name = clean_name.replace(" Repair", "")
                    
                    # 创建子节点
                    child_node = {
                        "name": clean_name,
                        "url": category["url"],
                        "children": []
                    }
                    parent_node["children"].append(child_node)
                    
                    print(f"爬取类别: {path_str} > {clean_name}")
                    self._crawl_recursive_tree(category["url"], child_node)
            elif not is_final_page:
                # 如果没有找到子类别但也不符合最终产品页面的定义
                product_info = self.extract_product_info(soup, url, [])
                if product_info["product_name"]:
                    parent_node["name"] = product_info["product_name"]
                    # 检查是否是根目录，不给根目录添加instruction_url
                    is_root_device = url == f"{self.base_url}/Device"
                    if not is_root_device:
                        parent_node["instruction_url"] = product_info["instruction_url"]
                    print(f"已找到产品: {path_str} > {product_info['product_name']}")
        
    def _get_current_path(self, node, tree=None):
        """获取当前节点的完整路径字符串，用于调试输出"""
        if not tree:
            # 如果没有提供树，使用缓存的树结构
            if hasattr(self, 'tree_cache'):
                tree = self.tree_cache
            else:
                return node.get("name", "")
                
        # 在树中查找从根到当前节点的路径
        path = []
        self._find_path_in_tree(tree, node.get("url", ""), path)
        
        # 如果找到路径，返回完整路径字符串
        if path:
            return " > ".join([n.get("name", "") for n in path])
        
        # 如果找不到路径，返回节点名称
        return node.get("name", "")
        
    def _find_path_in_tree(self, current_node, target_url, path):
        """在树中查找从根到目标URL的路径"""
        # 添加当前节点到路径
        path.append(current_node)
        
        # 如果是目标节点，返回True
        if current_node.get("url", "") == target_url:
            return True
            
        # 递归检查子节点
        if "children" in current_node:
            for child in current_node["children"]:
                # 递归检查子节点
                if self._find_path_in_tree(child, target_url, path):
                    return True
                    
        # 如果在当前子树中没有找到目标，从路径中移除当前节点
        path.pop()
        return False
            
    def ensure_instruction_url_in_leaf_nodes(self, node):
        """
        确保正确的字段结构:
        1. 所有叶子节点(没有子节点)都有instruction_url字段，且字段顺序为name-url-instruction_url-children
        2. 所有分类节点(有子节点)都没有instruction_url字段，字段顺序为name-url-children
        3. 根目录（Device页面）不添加instruction_url字段
        """
        # 检查是否是根目录（Device页面）
        url = node.get('url', '')
        is_root_device = url == f"{self.base_url}/Device"

        if "children" in node:
            if not node["children"] or len(node["children"]) == 0:
                # 这是一个叶子节点，但排除根目录
                if not is_root_device:
                    # 确保instruction_url存在
                    if "instruction_url" not in node:
                        node["instruction_url"] = ""
                        print(f"后处理: 添加缺失的instruction_url字段到叶子节点: {node.get('name', '')}")

                    # 重新排序字段：name-url-instruction_url-children
                    name = node.get("name", "")
                    url = node.get("url", "")
                    instruction_url = node.get("instruction_url", "")
                    children = node.get("children", [])

                    # 清除所有键
                    node.clear()

                    # 按照正确的顺序添加回去
                    node["name"] = name
                    node["url"] = url
                    node["instruction_url"] = instruction_url
                    node["children"] = children
                else:
                    # 根目录节点，确保没有instruction_url字段
                    if "instruction_url" in node:
                        print(f"后处理: 删除根目录节点中的instruction_url字段: {node.get('name', '')}")
                        del node["instruction_url"]
            else:
                # 这是一个分类节点(有子节点)，确保没有instruction_url字段
                if "instruction_url" in node:
                    # 发现分类节点有instruction_url字段，需要删除
                    print(f"后处理: 删除分类节点中的instruction_url字段: {node.get('name', '')}")
                    
                    # 重新排序字段：name-url-children
                    name = node.get("name", "")
                    url = node.get("url", "")
                    children = node.get("children", [])
                    
                    # 清除所有键
                    node.clear()
                    
                    # 按照正确的顺序添加回去(不包括instruction_url)
                    node["name"] = name
                    node["url"] = url
                    node["children"] = children
                
                # 递归处理所有子节点
                for child in node["children"]:
                    self.ensure_instruction_url_in_leaf_nodes(child)
    
    def save_tree_result(self, tree_data, filename=None, target_name=None):
        """保存树形结构到JSON文件"""
        # 确保所有叶子节点都有instruction_url字段
        self.ensure_instruction_url_in_leaf_nodes(tree_data)
        
        # 确保结果目录存在
        os.makedirs("results", exist_ok=True)
        
        if not filename:
            # 优先使用命令行中指定的爬取目标名称
            if target_name:
                # 移除文件名中的特殊字符
                safe_name = target_name.replace("/", "_").replace("\\", "_").replace(":", "_")
                filename = f"results/tree_{safe_name}.json"
            else:
                # 从根节点名称构建文件名
                root_name = tree_data.get("name", "tree")
                # 如果是完整路径的最终节点名称，只取最后一部分作为文件名
                if " > " in root_name:
                    root_name = root_name.split(" > ")[-1]
                # 移除文件名中的特殊字符    
                root_name = root_name.replace("/", "_").replace("\\", "_").replace(":", "_")
                filename = f"results/tree_{root_name}.json"
            
        # 将树形结构保存为JSON
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(tree_data, f, ensure_ascii=False, indent=2)
            
        print(f"\n已保存树形结构到 {filename}")
        return filename
        
    def print_tree_structure(self, node, level=0):
        """打印树形结构，方便在控制台查看"""
        indent = "  " * level
        # 没有children或children为空的节点视为产品
        if "children" not in node or not node["children"]:
            print(f"{indent}- {node.get('name', 'Unknown')} [产品]")
        else:
            print(f"{indent}+ {node.get('name', 'Unknown')} [类别]")
            
        # 递归打印子节点
        if "children" in node:
            for child in node["children"]:
                self.print_tree_structure(child, level + 1)

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
    # 先检查是否包含空格，如果有，替换为下划线用于URL
    processed_input = input_text.replace(" ", "_")
    return f"https://www.ifixit.com/Device/{processed_input}", input_text

def print_usage():
    print("使用方法:")
    print("python tree_crawler.py [URL或设备名]")
    print("例如: python tree_crawler.py https://www.ifixit.com/Device/Television")
    print("      python tree_crawler.py Television")

def main():
    # 检查是否提供了参数
    if len(sys.argv) > 1:
        input_text = sys.argv[1]
        # 检查是否有调试参数
        debug_mode = len(sys.argv) > 2 and sys.argv[2].lower() in ('debug', 'true', '1')
    else:
        print("=" * 60)
        print("iFixit树形爬虫工具 - 以层级树形结构展示设备分类")
        print("=" * 60)
        print("\n请输入要爬取的iFixit产品名称或URL:")
        print("例如: 70UK6570PUB            - 指定产品型号")
        print("      https://www.ifixit.com/Device/70UK6570PUB - 指定产品URL")
        print("      Television             - 电视类别")
        print("      Electronics            - 电子产品类别")
        
        input_text = input("\n> ").strip()
        debug_mode = input("\n是否开启调试模式? (y/n): ").strip().lower() == 'y'
    
    if not input_text:
        print_usage()
        return
    
    # 处理输入
    url, name = process_input(input_text)
    
    if url:
        print("\n" + "=" * 60)
        print(f"开始爬取以 {name} 为目标的完整树形结构...")
        print("=" * 60)
        
        # 创建树形爬虫
        crawler = TreeCrawler()
        # 设置调试模式
        crawler.debug = debug_mode
        
        # 爬取树形结构
        print("\n1. 查找从根目录到目标产品的精确路径...")
        tree_data = crawler.crawl_tree(url, name)
        
        # 缓存树结构用于路径查找
        crawler.tree_cache = tree_data
        
        # 保存结果
        if tree_data:
            # 先显示树形结构摘要
            print("\n树形结构摘要 (+ 表示类别，- 表示产品):")
            print("=" * 60)
            crawler.print_tree_structure(tree_data)
            print("=" * 60)
            
            # 保存为JSON文件
            print("\n2. 保存树形结构到文件...")
            # 使用命令行参数中的原始输入作为文件名
            filename = crawler.save_tree_result(tree_data, target_name=input_text)
            
            # 显示汇总信息
            product_count = count_products_in_tree(tree_data)
            category_count = count_categories_in_tree(tree_data)
            
            print("\n爬取完成!")
            print(f"- 共找到 {category_count} 个分类")
            print(f"- 共找到 {product_count} 个产品")
            print(f"- 树形结构已保存到: {filename}")
            print("\n示例路径展示:")
            
            # 显示示例路径
            if product_count > 0:
                # 找到一个产品节点进行演示
                sample_product = find_sample_product(tree_data)
                if sample_product:
                    product_path = crawler._get_current_path(sample_product, tree_data)
                    print(f"产品路径: {product_path}")
            
            print("=" * 60)
        else:
            print("\n爬取失败，未获取到树形结构数据")
    else:
        print_usage()

def find_sample_product(tree):
    """在树中查找一个示例产品节点"""
    # 没有子节点的视为产品节点
    if "children" not in tree or not tree["children"]:
        return tree
        
    if "children" in tree:
        for child in tree["children"]:
            result = find_sample_product(child)
            if result:
                return result
                
    return None
        
def count_products_in_tree(node):
    """计算树中产品节点的数量"""
    count = 0
    # 没有子节点的视为产品节点
    if "children" not in node or not node["children"]:
        count = 1
    elif "children" in node:
        for child in node["children"]:
            count += count_products_in_tree(child)
    return count
    
def count_categories_in_tree(node):
    """计算树中分类节点的数量"""
    # 有子节点的视为分类节点
    if "children" not in node or not node["children"]:
        return 0
        
    count = 1  # 当前节点是一个分类
    if "children" in node:
        for child in node["children"]:
            count += count_categories_in_tree(child)
    return count

if __name__ == "__main__":
    main()
