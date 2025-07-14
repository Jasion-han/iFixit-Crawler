#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
from crawler import IFixitCrawler

def crawl_batch(search_term, debug=False):
    """批量爬取搜索结果中的所有产品信息"""
    crawler = IFixitCrawler()
    crawler.debug = debug  # 设置debug属性
    # 首先获取搜索结果页面
    search_url = f"https://www.ifixit.com/Search?query={search_term}"
    soup = crawler.get_soup(search_url)
    if not soup:
        print(f"无法获取搜索页面: {search_url}")
        return None
    
    # 获取搜索结果中的所有产品链接
    product_links = []
    search_results = soup.find_all("div", class_="search-results")
    if search_results:
        for result in search_results:
            links = result.find_all("a")
            for link in links:
                href = link.get("href")
                if href and "/Device/" in href:
                    # 构建完整URL
                    if not href.startswith("http"):
                        href = "https://www.ifixit.com" + href
                    product_links.append(href)
    
    if not product_links:
        print(f"没有找到产品链接，尝试查找其他类型的链接")
        # 尝试其他可能的搜索结果结构
        items = soup.select(".search-results-items a, .searchResults a")
        for item in items:
            href = item.get("href")
            if href and ("/Device/" in href or "/Guide/" in href or "/Teardown/" in href):
                # 构建完整URL
                if not href.startswith("http"):
                    href = "https://www.ifixit.com" + href
                product_links.append(href)
    
    if not product_links:
        print(f"未找到任何产品链接：{search_url}")
        return None
    
    # 去重
    product_links = list(set(product_links))
    print(f"📋 找到 {len(product_links)} 个产品链接")

    # 爬取每个产品的详细信息
    results = []
    for i, link in enumerate(product_links, 1):
        print(f"[{i}/{len(product_links)}] 正在爬取...")
        product_info = crawler.extract_product_info_from_url(link)
        if product_info:
            results.append(product_info)
        # 添加延迟，避免请求过于频繁
        time.sleep(1)

    # 保存结果到JSON文件
    filename = f"results/batch_{search_term.replace(' ', '_')}.json"
    os.makedirs("results", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"✅ 批量爬取完成，已保存 {len(results)} 个产品信息到 {filename}")
    return results

def test_url(url, debug=False):
    """测试直接爬取特定URL"""
    crawler = IFixitCrawler()
    crawler.debug = debug
    
    print(f"爬取URL: {url}")
    product_info = crawler.extract_product_info_from_url(url)
    
    if product_info:
        print("\n爬取结果:")
        print(f"产品名称: {product_info.get('product_name', 'N/A')}")
        print(f"产品URL: {product_info.get('product_url', 'N/A')}")
        print(f"说明书链接: {product_info.get('instruction_url', 'N/A')}")
        
        # 保存结果到JSON文件
        # 从URL中提取最后一个部分作为文件名
        url_parts = product_info.get('product_url', '').split('/')
        file_name = url_parts[-1] if url_parts and url_parts[-1] else "unknown"
        filename = f"results/batch_{file_name}.json"
        os.makedirs("results", exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            # 将单个产品信息包装在数组中
            json.dump([product_info], f, ensure_ascii=False, indent=2)
        
        print(f"\n已保存产品信息到 {filename}")
        return product_info
    else:
        print("未能提取产品信息")
        return None

def test_multiple_urls(debug=False):
    """测试多个预定义的URL"""
    # 定义测试URL列表，包含不同类型的产品
    urls = [
        "https://www.ifixit.com/Device/Golf_Cart",  # 有视频指南的产品
        "https://www.ifixit.com/Device/iPad_3G",    # 可能有PDF文档的产品
        "https://www.ifixit.com/Device/LG_37LG10-UM"  # 有锚点链接的产品
    ]
    
    crawler = IFixitCrawler()
    crawler.debug = debug
    
    results = []
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] 测试URL: {url}")
        product_info = crawler.extract_product_info_from_url(url)
        
        if product_info:
            results.append(product_info)
            print(f"产品: {product_info.get('product_name', 'N/A')}")
            print(f"说明书: {product_info.get('instruction_url', 'N/A')}")
        else:
            print(f"未能提取产品信息: {url}")
            
        # 添加延迟
        if i < len(urls):
            time.sleep(2)
    
    # 如果有结果，使用第一个URL的最后部分作为文件名
    if results:
        url_parts = results[0].get("product_url", "").split("/")
        file_name = url_parts[-1] if url_parts and url_parts[-1] else "multiple_urls"
        filename = f"results/batch_{file_name}.json"
    else:
        filename = "results/batch_multiple_urls.json"
    
    os.makedirs("results", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        # results已经是数组，直接保存
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n测试完成，已保存 {len(results)} 个产品信息到 {filename}")
    return results

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
    
    # 否则视为产品名，进行搜索或构建URL
    return input_text

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python batch_crawler.py <搜索词/URL/产品名> [debug]")
        print("例如: python batch_crawler.py iPad")
        print("      python batch_crawler.py https://www.ifixit.com/Device/iPad_3G")
        print("      python batch_crawler.py iPad_3G")
        print("或者: python batch_crawler.py test [debug] - 测试多个预定义URL")
        sys.exit(1)
    
    input_text = sys.argv[1]
    debug = len(sys.argv) > 2 and sys.argv[2].lower() in ('debug', 'true', '1')
    
    # 判断输入类型
    if input_text.lower() == "test":
        test_multiple_urls(debug)
    elif input_text.startswith("http"):
        # 直接使用完整URL
        test_url(input_text, debug)
    elif "/Device/" in input_text:
        # 处理部分URL
        url = process_input(input_text)
        test_url(url, debug)
    else:
        # 尝试直接作为产品名构建URL
        product_url = f"https://www.ifixit.com/Device/{input_text}"
        print(f"尝试直接访问产品页面: {product_url}")
        
        # 创建爬虫实例并测试URL
        crawler = IFixitCrawler()
        crawler.debug = debug
        
        # 检查URL是否可访问
        soup = crawler.get_soup(product_url)
        if soup and soup.title and "Page Not Found" not in soup.title.text:
            print("找到产品页面，直接爬取...")
            test_url(product_url, debug)
        else:
            print(f"未找到产品页面，尝试搜索: {input_text}")
            crawl_batch(input_text, debug)
