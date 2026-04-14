import os
import re
import threading
import socket
import time
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from urllib.parse import urljoin
from datetime import datetime
import argparse  # 新增导入

def parse_ip_line(line):
    """
    解析ip文件中的一行
    格式: ip:port 或 ip:port,option
    支持IP段范围格式: 192.168.1-10.1-100:80,1
    """
    line = line.strip()
    if not line or line.startswith('#'):  # 跳过空行和注释
        return None
    
    # 移除可能的空白字符
    line = line.replace(' ', '')
    
    parts = line.split(',')
    ip_port = parts[0]
    option = int(parts[1]) if len(parts) > 1 else 0
    
    ip_port_parts = ip_port.split(':')
    if len(ip_port_parts) != 2:
        return None
    
    ip_str = ip_port_parts[0]
    port = ip_port_parts[1]
    
    # 解析IP段，支持范围格式如 192.168.1-10.1-100
    ip_segments = ip_str.split('.')
    if len(ip_segments) != 4:
        return None
    
    # 解析每个段，支持范围格式
    parsed_segments = []
    for segment in ip_segments:
        if '-' in segment:
            # 范围格式，如 1-10
            range_parts = segment.split('-')
            if len(range_parts) != 2:
                return None
            start, end = int(range_parts[0]), int(range_parts[1])
            parsed_segments.append((start, end, 'range'))
        else:
            # 单个值
            value = int(segment)
            parsed_segments.append((value, value, 'fixed'))
    
    # 验证端口
    try:
        if not 1 <= int(port) <= 65535:
            return None
    except ValueError:
        return None
    
    # 验证option
    if option not in [0, 1, 2]:
        option = 0
    
    return {
        'ip_segments': parsed_segments,  # 格式: [(start, end, type), ...]
        'port': port,
        'option': option
    }

def generate_ips_from_segments(segments, port, option):
    """
    根据解析的IP段和option值生成要扫描的IP列表
    """
    ip_list = []
    
    # 根据option值确定每段的处理方式
    # 0: 扫描D段, 1: 扫描B、C、D段, 2: 扫描C、D段
    segment_ranges = []
    
    for i, (start, end, seg_type) in enumerate(segments):
        if seg_type == 'fixed':
            # 如果是固定值
            if option == 0 and i == 3:  # 扫描D段
                segment_ranges.append((1, 255))
            elif option == 1 and i >= 1:  # 扫描B、C、D段
                segment_ranges.append((1, 255))
            elif option == 2 and i >= 2:  # 扫描C、D段
                segment_ranges.append((1, 255))
            else:
                segment_ranges.append((start, end))  # 保持固定
        else:
            # 如果是范围，使用指定的范围
            segment_ranges.append((start, end))
    
    # 生成所有IP组合
    for d in range(segment_ranges[3][0], segment_ranges[3][1] + 1):
        for c in range(segment_ranges[2][0], segment_ranges[2][1] + 1):
            for b in range(segment_ranges[1][0], segment_ranges[1][1] + 1):
                for a in range(segment_ranges[0][0], segment_ranges[0][1] + 1):
                    ip_list.append(f"{a}.{b}.{c}.{d}:{port}")
    
    return ip_list

def check_ip_with_timeout(ip_port, timeout=3):
    """
    检查IP是否可用，带超时设置
    """
    start_time = time.time()
    ip, port = ip_port.split(':')
    
    try:
        base_url = f"http://{ip}:{port}"
        
        # 第一个测试URL
        test_url1 = urljoin(base_url, "/iptv/live/1000.json?key=txiptv")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
        }
        
        response1 = requests.get(test_url1, headers=headers, timeout=timeout, allow_redirects=False)
        
        if response1.status_code == 200:
            response_time = (time.time() - start_time) * 1000
            return {
                'status': 'success',
                'ip': ip_port,
                'response_time': response_time,
                'source': '1000.json',
                'status_code': response1.status_code
            }
        
        # 如果第一个URL没有响应，尝试第二个URL
        test_url2 = urljoin(base_url, "/ZHGXTV/Public/json/live_interface.txt")
        response2 = requests.get(test_url2, headers=headers, timeout=timeout, allow_redirects=False)
        
        if response2.status_code == 200:
            response_time = (time.time() - start_time) * 1000
            return {
                'status': 'success',
                'ip': ip_port,
                'response_time': response_time,
                'source': 'live_interface.txt',
                'status_code': response2.status_code
            }
        
        return {
            'status': 'no_response',
            'ip': ip_port,
            'response_time': (time.time() - start_time) * 1000
        }
        
    except requests.exceptions.Timeout:
        return {
            'status': 'timeout',
            'ip': ip_port
        }
    except requests.exceptions.ConnectionError:
        return {
            'status': 'connection_error',
            'ip': ip_port
        }
    except requests.exceptions.RequestException:
        return {
            'status': 'request_error',
            'ip': ip_port
        }
    except Exception:
        return {
            'status': 'unknown_error',
            'ip': ip_port
        }

def scan_ips(ip_list, max_workers=20):
    """
    并发扫描IP列表
    """
    valid_ips = []
    scan_stats = {
        'total': len(ip_list),
        'success': 0,
        'no_response': 0,
        'timeout': 0,
        'connection_error': 0,
        'request_error': 0,
        'other_error': 0
    }
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ip = {
            executor.submit(check_ip_with_timeout, ip): ip 
            for ip in ip_list
        }
        
        completed = 0
        for future in as_completed(future_to_ip):
            completed += 1
            ip = future_to_ip[future]
            
            try:
                result = future.result()
                status = result['status']
                scan_stats[status] += 1
                
                if status == 'success':
                    valid_ips.append({
                        'ip_port': result['ip'],
                        'response_time': result.get('response_time', 0),
                        'source': result.get('source', 'unknown')
                    })
                    
                    if completed % 10 == 0:
                        print(f"  [✓] {result['ip']} - 响应: {result.get('response_time', 0):.0f}ms")
                
                if completed % 100 == 0:
                    progress = (completed / len(ip_list)) * 100
                    print(f"    进度: {completed}/{len(ip_list)} ({progress:.1f}%) - 成功: {scan_stats['success']}")
                    
            except Exception:
                scan_stats['other_error'] += 1
    
    return valid_ips, scan_stats

def process_file(input_file_path, output_dir, max_workers=20):
    """
    处理单个文件
    """
    print(f"\n处理文件: {os.path.basename(input_file_path)}")
    
    all_ip_to_scan = []
    
    # 读取文件并解析
    with open(input_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
        valid_lines = 0
        for line_num, line in enumerate(lines, 1):
            parsed = parse_ip_line(line)
            if parsed:
                valid_lines += 1
                
                # 显示IP段信息
                segments_str = []
                for seg in parsed['ip_segments']:
                    if seg[2] == 'fixed':
                        segments_str.append(str(seg[0]))
                    else:
                        segments_str.append(f"{seg[0]}-{seg[1]}")
                
                print(f"  第{line_num}行: {'.'.join(segments_str)}:{parsed['port']}, 选项={parsed['option']}")
                
                # 生成要扫描的IP
                ips_to_scan = generate_ips_from_segments(
                    parsed['ip_segments'], 
                    parsed['port'], 
                    parsed['option']
                )
                all_ip_to_scan.extend(ips_to_scan)
    
    if not all_ip_to_scan:
        print(f"  没有找到有效的IP")
        return 0, 0, {}
    
    print(f"  总共生成 {len(all_ip_to_scan)} 个IP需要扫描")
    
    # 去重
    all_ip_to_scan = list(set(all_ip_to_scan))
    print(f"  去重后 {len(all_ip_to_scan)} 个IP需要扫描")
    
    # 分批扫描
    batch_size = 1000
    all_valid_ips = []
    total_stats = {
        'total': 0,
        'success': 0,
        'no_response': 0,
        'timeout': 0,
        'connection_error': 0,
        'request_error': 0,
        'other_error': 0
    }
    
    for i in range(0, len(all_ip_to_scan), batch_size):
        batch = all_ip_to_scan[i:i + batch_size]
        batch_num = i//batch_size + 1
        total_batches = (len(all_ip_to_scan)-1)//batch_size + 1
        
        print(f"\n  批次 {batch_num}/{total_batches}: {len(batch)} 个IP")
        
        batch_start_time = time.time()
        valid_ips, batch_stats = scan_ips(batch, max_workers)
        batch_time = time.time() - batch_start_time
        
        all_valid_ips.extend(valid_ips)
        
        for key in total_stats:
            total_stats[key] += batch_stats[key]
        
        print(f"  批次完成: 成功 {len(valid_ips)} 个IP")
        print(f"  批次耗时: {batch_time:.2f}秒")
    
    # 汇总统计
    print(f"\n扫描汇总:")
    print(f"  扫描IP总数: {total_stats['total']}")
    print(f"  成功IP数: {total_stats['success']} ({total_stats['success']/total_stats['total']*100:.2f}%)")
    
    # 保存结果
    if all_valid_ips:
        output_file_name = os.path.basename(input_file_path)
        output_file_path = os.path.join(output_dir, output_file_name)
        
        sorted_ips = sorted(all_valid_ips, key=lambda x: x['response_time'])
        
        with open(output_file_path, 'w', encoding='utf-8') as f:
            for ip_info in sorted_ips:
                f.write(f"{ip_info['ip_port']}\n")
        
        print(f"  保存 {len(all_valid_ips)} 个有效IP")
    else:
        print(f"  没有发现有效IP")
    
    return total_stats['total'], len(all_valid_ips), total_stats

def get_files_to_process(input_dir, specified_files=None):
    """
    获取要处理的文件列表
    """
    txt_files = []
    
    if specified_files:
        # 如果指定了文件，只处理这些文件
        for file_name in specified_files:
            file_path = os.path.join(input_dir, file_name)
            if os.path.exists(file_path):
                if file_path.endswith('.txt'):
                    txt_files.append(file_path)
                else:
                    print(f"警告: {file_name} 不是txt文件，已跳过")
            else:
                print(f"警告: 文件 {file_name} 不存在，已跳过")
    else:
        # 如果没有指定文件，处理所有txt文件
        for file in os.listdir(input_dir):
            if file.endswith('.txt'):
                txt_files.append(os.path.join(input_dir, file))
    
    return txt_files


def main():
    # 设置路径
    input_dir = "Hotel/ip/ip/ip/"
    output_dir = "Hotel/ip/"
    
    # 配置文件路径
    config_file = "Hotel/ip/ip/ip/scan_config.txt"
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(input_dir, exist_ok=True)
    
    # 检查输入目录是否存在
    if not os.path.exists(input_dir):
        print(f"错误: 输入目录 {input_dir} 不存在")
        return
    
    # 获取要处理的文件列表
    txt_files = []
    
    # 如果存在配置文件，读取配置文件
    if os.path.exists(config_file):
        print(f"从配置文件 {config_file} 读取文件列表")
        with open(config_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):  # 跳过空行和注释
                    file_name = line
                    file_path = os.path.join(input_dir, file_name)
                    if os.path.exists(file_path) and file_name.endswith('.txt'):
                        txt_files.append(file_path)
                    else:
                        print(f"警告: 配置文件中的文件 {file_name} 不存在或不是txt文件，已跳过")
    else:
        # 如果没有配置文件，扫描所有txt文件
        print("未找到配置文件，将扫描所有txt文件")
        for file in os.listdir(input_dir):
            if file.endswith('.txt'):
                txt_files.append(os.path.join(input_dir, file))
    
    if not txt_files:
        print(f"没有找到要处理的txt文件")
        return
    
    print(f"开始IP扫描 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"找到 {len(txt_files)} 个txt文件")
    
    # 处理每个文件
    total_ips_scanned = 0
    total_valid_ips = 0
    
    for i, txt_file in enumerate(txt_files, 1):
        print(f"\n[文件 {i}/{len(txt_files)}] {os.path.basename(txt_file)}")
        
        start_time = time.time()
        ips_scanned, valid_ips, stats = process_file(txt_file, output_dir)
        scan_time = time.time() - start_time
        
        total_ips_scanned += ips_scanned
        total_valid_ips += valid_ips
        
        print(f"  文件耗时: {scan_time:.2f}秒")
    
    # 打印总统计
    print(f"\n扫描完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"总扫描IP数: {total_ips_scanned}")
    print(f"总有效IP数: {total_valid_ips}")
    if total_ips_scanned > 0:
        print(f"总体成功率: {total_valid_ips/total_ips_scanned*100:.2f}%")

if __name__ == "__main__":
    main()
