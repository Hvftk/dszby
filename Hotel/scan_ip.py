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

def parse_ip_line(line):
    """
    解析ip文件中的一行
    格式: ip:port 或 ip:port,option
    """
    line = line.strip()
    if not line:
        return None
    
    parts = line.split(',')
    ip_port = parts[0]
    option = int(parts[1]) if len(parts) > 1 else 0
    
    ip_port_parts = ip_port.split(':')
    if len(ip_port_parts) != 2:
        return None
    
    ip = ip_port_parts[0]
    port = ip_port_parts[1]
    
    # 验证IP格式
    ip_parts = ip.split('.')
    if len(ip_parts) != 4:
        return None
    
    return {
        'ip': ip,
        'port': port,
        'option': option
    }

def generate_ips(base_ip, port, option):
    """
    根据option生成要扫描的IP列表
    """
    ip_parts = list(map(int, base_ip.split('.')))
    a, b, c, d = ip_parts
    
    ip_list = []
    
    if option == 0:  # 扫描D段
        for i in range(1, 256):
            new_ip = f"{a}.{b}.{c}.{i}"
            ip_list.append(f"{new_ip}:{port}")
    
    elif option == 1:  # 扫描B、C、D段
        for i in range(1, 256):  # B段
            for j in range(1, 256):  # C段
                for k in range(1, 256):  # D段
                    new_ip = f"{a}.{i}.{j}.{k}"
                    ip_list.append(f"{new_ip}:{port}")
    
    elif option == 2:  # 扫描C、D段
        for i in range(1, 256):  # C段
            for j in range(1, 256):  # D段
                new_ip = f"{a}.{b}.{i}.{j}"
                ip_list.append(f"{new_ip}:{port}")
    
    return ip_list

def check_ip_with_timeout(ip_port, test_url, timeout=3):
    """
    检查IP是否可用，带超时设置
    """
    try:
        ip, port = ip_port.split(':')
        base_url = f"http://{ip}:{port}"
        
        # 第一个测试URL
        test_url1 = urljoin(base_url, "/iptv/live/1000.json?key=txiptv")
        response1 = requests.get(test_url1, timeout=timeout)
        
        if response1.status_code == 200:
            return True
        
        # 如果第一个URL没有响应，尝试第二个URL
        test_url2 = urljoin(base_url, "/ZHGXTV/Public/json/live_interface.txt")
        response2 = requests.get(test_url2, timeout=timeout)
        
        if response2.status_code == 200:
            return True
        
        return False
        
    except Exception as e:
        return False

def scan_ips(ip_list, max_workers=50):
    """
    并发扫描IP列表
    """
    valid_ips = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_ip = {
            executor.submit(check_ip_with_timeout, ip, ""): ip 
            for ip in ip_list
        }
        
        # 处理完成的任务
        for future in as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                result = future.result()
                if result:
                    valid_ips.append(ip)
            except Exception as e:
                continue
    
    return valid_ips

def process_file(input_file_path, output_dir, max_workers=50):
    """
    处理单个文件
    """
    print(f"处理文件: {input_file_path}")
    
    all_ip_to_scan = []
    
    # 读取文件并解析
    with open(input_file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            parsed = parse_ip_line(line)
            if parsed:
                print(f"  解析第{line_num}行: {parsed['ip']}:{parsed['port']}, option={parsed['option']}")
                
                # 生成要扫描的IP
                ips_to_scan = generate_ips(parsed['ip'], parsed['port'], parsed['option'])
                all_ip_to_scan.extend(ips_to_scan)
    
    if not all_ip_to_scan:
        print(f"  文件 {input_file_path} 没有找到有效的IP")
        return
    
    print(f"  总共生成 {len(all_ip_to_scan)} 个IP需要扫描")
    
    # 去重
    all_ip_to_scan = list(set(all_ip_to_scan))
    print(f"  去重后 {len(all_ip_to_scan)} 个IP需要扫描")
    
    # 分批扫描，避免内存不足
    batch_size = 10000
    all_valid_ips = []
    
    for i in range(0, len(all_ip_to_scan), batch_size):
        batch = all_ip_to_scan[i:i + batch_size]
        print(f"  扫描批次 {i//batch_size + 1}/{(len(all_ip_to_scan)-1)//batch_size + 1}: {len(batch)} 个IP")
        
        valid_ips = scan_ips(batch, max_workers)
        all_valid_ips.extend(valid_ips)
        
        print(f"    批次发现 {len(valid_ips)} 个有效IP")
    
    # 保存结果
    if all_valid_ips:
        output_file_name = os.path.basename(input_file_path)
        output_file_path = os.path.join(output_dir, output_file_name)
        
        with open(output_file_path, 'w', encoding='utf-8') as f:
            for ip in sorted(all_valid_ips):
                f.write(f"{ip}\n")
        
        print(f"  保存 {len(all_valid_ips)} 个有效IP到: {output_file_path}")
    else:
        print(f"  没有发现有效IP")

def main():
    # 设置路径
    input_dir = "Hotel/ip/ip/"
    output_dir = "Hotel/ip/"
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(input_dir, exist_ok=True)
    
    # 检查输入目录是否存在
    if not os.path.exists(input_dir):
        print(f"错误: 输入目录不存在: {input_dir}")
        return
    
    # 查找所有txt文件
    txt_files = []
    for file in os.listdir(input_dir):
        if file.endswith('.txt'):
            txt_files.append(os.path.join(input_dir, file))
    
    if not txt_files:
        print(f"在目录 {input_dir} 中没有找到txt文件")
        return
    
    print(f"找到 {len(txt_files)} 个txt文件")
    
    # 处理每个文件
    for i, txt_file in enumerate(txt_files, 1):
        print(f"\n[{i}/{len(txt_files)}] ", end="")
        process_file(txt_file, output_dir)
    
    print("\n扫描完成!")

if __name__ == "__main__":
    main()
