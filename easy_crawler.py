#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
简易iFixit爬虫工具
用法: python easy_crawler.py [URL或产品名]
示例: python easy_crawler.py https://zh.ifixit.com/Device/iPad_3G
      python easy_crawler.py iPad_3G
"""

import sys
import json
import os
from crawler import IFixitCrawler

def print_usage():
    print("使用方法:")
    print("python easy_crawler.py [URL或产品名]")
    print("例如: python easy_crawler.py https://zh.ifixit.com/Device/iPad_3G")
    print("或者: python easy_crawler.py iPad_3G")
    print("\n或者直接运行脚本，然后按提示输入URL或产品名")

def crawl_url(url):
    print(f"开始爬取: {url}")
    
    # 创建爬虫实例
    crawler = IFixitCrawler()
    crawler.debug = True  # 开启调试模式以查看更多信息
    
    # 获取页面内容
    soup = crawler.get_soup(url)
    if not soup:
        print("无法获取页面内容，请检查URL是否正确")
        return
    
    # 检查是否为最终产品页面
    is_final_page = crawler.is_final_product_page(soup, url)
    
    # 提取类别信息
    categories = crawler.extract_categories(soup, url)
    real_categories = [c for c in categories if not any(x in c["name"] or x in c["url"] for x in ["创建指南", "Guide/new"])]
    
    if not is_final_page:
        print(f"\n警告: 该页面不是最终产品页面，而是类别页面")
        print(f"找到 {len(real_categories)} 个子类别:")
        for i, category in enumerate(real_categories[:10]):  # 只显示前10个
            print(f"  {i+1}. {category['name']}: {category['url']}")
        if len(real_categories) > 10:
            print(f"  ...还有 {len(real_categories) - 10} 个")
        
        print("\n您可以选择爬取以下子类别之一:")
        for i, category in enumerate(real_categories[:5]):  # 只显示前5个选项
            print(f"  {i+1}. {category['name']}")
        
        choice = input("\n请选择要爬取的子类别编号(1-5)，或直接按回车继续爬取当前页面: ")
        if choice.isdigit() and 1 <= int(choice) <= min(5, len(real_categories)):
            idx = int(choice) - 1
            selected_url = real_categories[idx]["url"]
            print(f"\n正在爬取子类别: {real_categories[idx]['name']}")
            crawl_url(selected_url)  # 递归爬取选择的子类别
            return
    
    # 提取产品信息
    product_info = crawler.extract_product_info(soup, url, [])
    
    if not product_info["product_name"]:
        print("未能提取到产品信息，可能不是产品页面")
        return
    
    # 打印结果
    print("\n爬取结果:")
    print(f"产品名称: {product_info['product_name']}")
    print(f"产品URL: {product_info['product_url']}")
    print(f"说明书链接: {product_info['instruction_url'] or '无'}")
    print(f"是否为最终产品页面: {'是' if is_final_page else '否 (还有子类别)'}")
    
    # 保存结果
    crawler.save_result(product_info)
    
    if not is_final_page:
        print("\n注意: 此页面还有子类别，您可能想要爬取具体的子类别产品。")

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
            return "https://zh.ifixit.com" + input_text
        return input_text
    
    # 否则视为产品名，构建URL
    return f"https://zh.ifixit.com/Device/{input_text}"

def main():
    # 检查是否提供了URL参数
    if len(sys.argv) > 1:
        input_text = sys.argv[1]
    else:
        print("请输入要爬取的iFixit产品页面URL或产品名:")
        print("例如: https://zh.ifixit.com/Device/iPad_3G 或 iPad_3G")
        input_text = input("> ").strip()
    
    if not input_text:
        print_usage()
        return
    
    # 处理输入，支持URL或产品名
    url = process_input(input_text)
    
    if url:
        crawl_url(url)
    else:
        print_usage()

if __name__ == "__main__":
    main() 