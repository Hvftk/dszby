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

def parse_ip_segment(segment_str):
    """解析IP段，支持数字范围如'94-112'"""
    if '-' in segment_str:
        try:
            start, end = segment_str.split('-')
            start_num = int(start)
            end_num = int(end)
            if 0 <= start_num <= 255 and 0 <= end_num <= 255 and start_num <= end_num:
                return list(range(start_num, end_num + 1))
            else:
                return []
        except:
            return []
    else:
        try:
            num = int(segment_str)
            if 0 <= num <= 255:
                return [num]
            else:
                return []
        except:
            return []

def parse_ip_line(line):
    """
    解析ip文件中的一行
    格式: ip:port 或 ip:port,option
    支持格式: 120.202.94-112.181:9446,2
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
    
    # 分割IP段
    ip_segments = ip_str.split('.')
    if len(ip_segments) != 4:
        return None
    
    # 解析每个段
    segment_ranges = []
    for segment in ip_segments:
        parsed_segment = parse_ip_segment(segment)
        if not parsed_segment:
            return None
        segment_ranges.append(parsed_segment)
    
    # 验证端口
    try:
        if not 1 <= int(port) <= 65535:
            return None
    except:
        return None
    
    # 验证option
    if option not in [0, 1, 2]:
        option = 0
    
    return {
        'segment_ranges': segment_ranges,  # 每个段的范围列表
        'port': port,
        'option': option
    }

def generate_ips_from_segments(segment_ranges, port, option):
    """
    根据segment_ranges和option生成要扫描的IP列表
    segment_ranges: 每个段的可能值列表
    """
    a_range, b_range, c_range, d_range = segment_ranges
    
    ip_list = []
    
    if option == 0:  # 扫描D段
        # 固定A,B,C段，扫描D段
        for a in a_range:
            for b in b_range:
                for c in c_range:
                    for d in range(1, 256):  # 扫描1-255
                        new_ip = f"{a}.{b}.{c}.{d}"
                        ip_list.append(f"{new_ip}:{port}")
    
    elif option == 1:  # 扫描B、C、D段
        # 固定A段，扫描B,C,D段
        for a in a_range:
            for b in range(1, 256):  # 扫描B段1-255
                for c in range(1, 256):  # 扫描C段1-255
                    for d in range(1, 256):  # 扫描D段1-255
                        new_ip = f"{a}.{b}.{c}.{d}"
                        ip_list.append(f"{new_ip}:{port}")
    
    elif option == 2:  # 扫描C、D段
        # 固定A,B段，扫描C,D段
        for a in a_range:
            for b in b_range:
                for c in range(1, 256):  # 扫描C段1-255
                    for d in range(1, 256):  # 扫描D段1-255
                        new_ip = f"{a}.{b}.{c}.{d}"
                        ip_list.append(f"{new_ip}:{port}")
    
    return ip_list

def check_ip_with_timeout(ip_port, timeout=3):
    """检查IP是否可用，带超时设置"""
    start_time = time.time()
    ip, port = ip_port.split(':')
    
    try:
        base_url = f"http://{ip}:{port}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Connection': 'close'
        }
        
        # 第一个测试URL
        test_url1 = urljoin(base_url, "/iptv/live/1000.json?key=txiptv")
        response1 = requests.get(test_url1, headers=headers, timeout=timeout, allow_redirects=False)
        
        if response1.status_code == 200:
            response_time = (time.time() - start_time) * 1000
            return {
                'status': 'success',
                'ip': ip_port,
                'response_time': response_time,
                'source': '1000.json'
            }
        
        # 第二个测试URL
        test_url2 = urljoin(base_url, "/ZHGXTV/Public/json/live_interface.txt")
        response2 = requests.get(test_url2, headers=headers, timeout=timeout, allow_redirects=False)
        
        if response2.status_code == 200:
            response_time = (time.time() - start_time) * 1000
            return {
                'status': 'success',
                'ip': ip_port,
                'response_time': response_time,
                'source': 'live_interface.txt'
            }
        
        return {
            'status': 'no_response',
            'ip': ip_port
        }
        
    except requests.exceptions.Timeout:
        return {'status': 'timeout', 'ip': ip_port}
    except requests.exceptions.ConnectionError:
        return {'status': 'connection_error', 'ip': ip_port}
    except Exception as e:
        return {'status': 'error', 'ip': ip_port, 'error': str(e)}

def scan_ips(ip_list, max_workers=20):
    """并发扫描IP列表"""
    valid_ips = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ip = {executor.submit(check_ip_with_timeout, ip): ip for ip in ip_list}
        
        for future in as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                result = future.result()
                if result['status'] == 'success':
                    valid_ips.append({
                        'ip_port': result['ip'],
                        'response_time': result.get('response_time', 0),
                        'source': result.get('source', 'unknown')
                    })
            except:
                pass
    
    return valid_ips

def process_file(input_file_path, output_dir, max_workers=20):
    """处理单个文件"""
    all_ip_to_scan = []
    
    with open(input_file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            parsed = parse_ip_line(line)
            if parsed:
                ips_to_scan = generate_ips_from_segments(
                    parsed['segment_ranges'], 
                    parsed['port'], 
                    parsed['option']
                )
                all_ip_to_scan.extend(ips_to_scan)
    
    if not all_ip_to_scan:
        return 0, 0
    
    all_ip_to_scan = list(set(all_ip_to_scan))
    batch_size = 1000
    all_valid_ips = []
    
    for i in range(0, len(all_ip_to_scan), batch_size):
        batch = all_ip_to_scan[i:i + batch_size]
        valid_ips = scan_ips(batch, max_workers)
        all_valid_ips.extend(valid_ips)
    
    if all_valid_ips:
        output_file_name = os.path.basename(input_file_path)
        output_file_path = os.path.join(output_dir, output_file_name)
        
        with open(output_file_path, 'w', encoding='utf-8') as f:
            for ip_info in sorted(all_valid_ips, key=lambda x: x['response_time']):
                f.write(f"{ip_info['ip_port']}\n")
    
    return len(all_ip_to_scan), len(all_valid_ips)

def main():
    input_dir = "Hotel/ip/ip/"
    output_dir = "Hotel/ip/"
    
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(input_dir, exist_ok=True)
    
    if not os.path.exists(input_dir):
        return
    
    txt_files = []
    for file in os.listdir(input_dir):
        if file.endswith('.txt'):
            txt_files.append(os.path.join(input_dir, file))
    
    if not txt_files:
        return
    
    total_ips_scanned = 0
    total_valid_ips = 0
    
    for txt_file in txt_files:
        ips_scanned, valid_ips = process_file(txt_file, output_dir)
        total_ips_scanned += ips_scanned
        total_valid_ips += valid_ips
    
    print(f"总扫描IP数: {total_ips_scanned}")
    print(f"总有效IP数: {total_valid_ips}")

if __name__ == "__main__":
    main()
