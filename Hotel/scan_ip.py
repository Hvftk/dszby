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
    
    print(f"    生成规则: IP={base_ip}, 端口={port}, 选项={option}")
    
    if option == 0:  # 扫描D段
        print(f"    扫描D段: {a}.{b}.{c}.1-255")
        for i in range(1, 256):
            new_ip = f"{a}.{b}.{c}.{i}"
            ip_list.append(f"{new_ip}:{port}")
    
    elif option == 1:  # 扫描B、C、D段
        print(f"    扫描B、C、D段: {a}.1-255.1-255.1-255")
        for i in range(1, 256):  # B段
            for j in range(1, 256):  # C段
                for k in range(1, 256):  # D段
                    new_ip = f"{a}.{i}.{j}.{k}"
                    ip_list.append(f"{new_ip}:{port}")
    
    elif option == 2:  # 扫描C、D段
        print(f"    扫描C、D段: {a}.{b}.1-255.1-255")
        for i in range(1, 256):  # C段
            for j in range(1, 256):  # D段
                new_ip = f"{a}.{b}.{i}.{j}"
                ip_list.append(f"{new_ip}:{port}")
    
    else:
        print(f"    未知选项 {option}，跳过")
    
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
        response1 = requests.get(test_url1, timeout=timeout)
        
        if response1.status_code == 200:
            response_time = (time.time() - start_time) * 1000
            return {
                'status': 'success',
                'ip': ip_port,
                'url': test_url1,
                'response_time': response_time,
                'source': '1000.json'
            }
        
        # 如果第一个URL没有响应，尝试第二个URL
        test_url2 = urljoin(base_url, "/ZHGXTV/Public/json/live_interface.txt")
        response2 = requests.get(test_url2, timeout=timeout)
        
        if response2.status_code == 200:
            response_time = (time.time() - start_time) * 1000
            return {
                'status': 'success',
                'ip': ip_port,
                'url': test_url2,
                'response_time': response_time,
                'source': 'live_interface.txt'
            }
        
        return {
            'status': 'timeout',
            'ip': ip_port,
            'response_time': (time.time() - start_time) * 1000
        }
        
    except requests.exceptions.Timeout:
        return {
            'status': 'timeout',
            'ip': ip_port,
            'response_time': timeout * 1000
        }
    except requests.exceptions.ConnectionError:
        return {
            'status': 'connection_error',
            'ip': ip_port
        }
    except requests.exceptions.RequestException as e:
        return {
            'status': 'error',
            'ip': ip_port,
            'error': str(e)
        }
    except Exception as e:
        return {
            'status': 'unknown_error',
            'ip': ip_port,
            'error': str(e)
        }

def scan_ips(ip_list, max_workers=50, verbose=True):
    """
    并发扫描IP列表
    """
    valid_ips = []
    scan_stats = {
        'total': len(ip_list),
        'success': 0,
        'timeout': 0,
        'connection_error': 0,
        'other_error': 0
    }
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_ip = {
            executor.submit(check_ip_with_timeout, ip): ip 
            for ip in ip_list
        }
        
        # 处理完成的任务
        completed = 0
        for future in as_completed(future_to_ip):
            completed += 1
            ip = future_to_ip[future]
            
            try:
                result = future.result()
                
                # 更新统计
                if result['status'] == 'success':
                    scan_stats['success'] += 1
                    valid_ips.append({
                        'ip_port': result['ip'],
                        'response_time': result.get('response_time', 0),
                        'source': result.get('source', 'unknown')
                    })
                    
                    if verbose:
                        print(f"  [✓] {result['ip']} - 响应时间: {result.get('response_time', 0):.2f}ms - 来源: {result.get('source', 'unknown')}")
                
                elif result['status'] == 'timeout':
                    scan_stats['timeout'] += 1
                    if verbose and completed % 100 == 0:  # 每100个超时打印一次
                        print(f"  [×] {result['ip']} - 超时")
                
                elif result['status'] == 'connection_error':
                    scan_stats['connection_error'] += 1
                    if verbose and completed % 100 == 0:  # 每100个连接错误打印一次
                        print(f"  [×] {result['ip']} - 连接错误")
                
                else:
                    scan_stats['other_error'] += 1
                
                # 每100个IP打印一次进度
                if completed % 100 == 0 and verbose:
                    progress = (completed / len(ip_list)) * 100
                    print(f"  进度: {completed}/{len(ip_list)} ({progress:.1f}%) - 成功: {scan_stats['success']} 超时: {scan_stats['timeout']} 连接错误: {scan_stats['connection_error']}")
                    
            except Exception as e:
                scan_stats['other_error'] += 1
                if verbose and completed % 100 == 0:
                    print(f"  [!] {ip} - 扫描异常: {str(e)[:50]}")
    
    return valid_ips, scan_stats

def process_file(input_file_path, output_dir, max_workers=50, verbose=True):
    """
    处理单个文件
    """
    print(f"\n{'='*60}")
    print(f"处理文件: {input_file_path}")
    print(f"{'='*60}")
    
    all_ip_to_scan = []
    
    # 读取文件并解析
    with open(input_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        print(f"  读取到 {len(lines)} 行数据")
        
        valid_lines = 0
        for line_num, line in enumerate(f, 1):
            parsed = parse_ip_line(line)
            if parsed:
                valid_lines += 1
                print(f"  第{line_num}行: {parsed['ip']}:{parsed['port']}, 选项={parsed['option']}")
                
                # 生成要扫描的IP
                ips_to_scan = generate_ips(parsed['ip'], parsed['port'], parsed['option'])
                all_ip_to_scan.extend(ips_to_scan)
        
        print(f"  有效行数: {valid_lines}")
    
    if not all_ip_to_scan:
        print(f"  文件 {input_file_path} 没有找到有效的IP")
        return 0, 0, {}
    
    print(f"  总共生成 {len(all_ip_to_scan)} 个IP需要扫描")
    
    # 去重
    all_ip_to_scan = list(set(all_ip_to_scan))
    print(f"  去重后 {len(all_ip_to_scan)} 个IP需要扫描")
    
    # 分批扫描，避免内存不足
    batch_size = 10000
    all_valid_ips = []
    total_stats = {
        'total': 0,
        'success': 0,
        'timeout': 0,
        'connection_error': 0,
        'other_error': 0
    }
    
    for i in range(0, len(all_ip_to_scan), batch_size):
        batch = all_ip_to_scan[i:i + batch_size]
        batch_num = i//batch_size + 1
        total_batches = (len(all_ip_to_scan)-1)//batch_size + 1
        
        print(f"\n  {'-'*50}")
        print(f"  批次 {batch_num}/{total_batches}: {len(batch)} 个IP")
        print(f"  批次IP范围: {batch[0]} 到 {batch[-1]}")
        print(f"  {'-'*50}")
        
        batch_start_time = time.time()
        valid_ips, batch_stats = scan_ips(batch, max_workers, verbose)
        batch_time = time.time() - batch_start_time
        
        all_valid_ips.extend(valid_ips)
        
        # 更新总统计
        for key in total_stats:
            total_stats[key] += batch_stats[key]
        
        print(f"  {'-'*50}")
        print(f"  批次完成: 成功 {len(valid_ips)} 个IP")
        print(f"  批次统计: 成功 {batch_stats['success']}, 超时 {batch_stats['timeout']}, 连接错误 {batch_stats['connection_error']}, 其他错误 {batch_stats.get('other_error', 0)}")
        print(f"  批次耗时: {batch_time:.2f}秒, 平均每个IP: {batch_time/len(batch)*1000:.2f}毫秒")
    
    # 汇总统计
    print(f"\n{'='*60}")
    print(f"文件 {os.path.basename(input_file_path)} 扫描汇总:")
    print(f"  扫描IP总数: {total_stats['total']}")
    print(f"  成功IP数: {total_stats['success']} ({total_stats['success']/total_stats['total']*100:.2f}%)")
    print(f"  超时IP数: {total_stats['timeout']} ({total_stats['timeout']/total_stats['total']*100:.2f}%)")
    print(f"  连接错误: {total_stats['connection_error']} ({total_stats['connection_error']/total_stats['total']*100:.2f}%)")
    print(f"  其他错误: {total_stats.get('other_error', 0)} ({total_stats.get('other_error', 0)/total_stats['total']*100:.2f}%)")
    
    # 保存结果
    if all_valid_ips:
        output_file_name = os.path.basename(input_file_path)
        output_file_path = os.path.join(output_dir, output_file_name)
        
        # 按响应时间排序
        sorted_ips = sorted(all_valid_ips, key=lambda x: x['response_time'])
        
        with open(output_file_path, 'w', encoding='utf-8') as f:
            for ip_info in sorted_ips:
                f.write(f"{ip_info['ip_port']}\n")
        
        # 打印前10个最快的IP
        print(f"\n  最快的前10个IP:")
        for i, ip_info in enumerate(sorted_ips[:10], 1):
            print(f"    {i:2d}. {ip_info['ip_port']} - {ip_info['response_time']:.2f}ms (来源: {ip_info['source']})")
        
        print(f"\n  保存 {len(all_valid_ips)} 个有效IP到: {output_file_path}")
    else:
        print(f"\n  没有发现有效IP")
    
    return len(all_ip_to_scan), len(all_valid_ips), total_stats

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
    
    print(f"{'='*60}")
    print(f"开始IP扫描 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print(f"找到 {len(txt_files)} 个txt文件")
    print(f"{'='*60}")
    
    # 处理每个文件
    total_ips_scanned = 0
    total_valid_ips = 0
    file_stats = []
    
    for i, txt_file in enumerate(txt_files, 1):
        print(f"\n{'='*60}")
        print(f"[文件 {i}/{len(txt_files)}] {os.path.basename(txt_file)}")
        print(f"{'='*60}")
        
        start_time = time.time()
        ips_scanned, valid_ips, stats = process_file(txt_file, output_dir)
        scan_time = time.time() - start_time
        
        total_ips_scanned += ips_scanned
        total_valid_ips += valid_ips
        
        file_stats.append({
            'file': os.path.basename(txt_file),
            'scanned': ips_scanned,
            'valid': valid_ips,
            'time': scan_time,
            'stats': stats
        })
    
    # 打印总统计
    print(f"\n{'='*60}")
    print(f"扫描完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    print(f"\n文件扫描统计:")
    for stat in file_stats:
        success_rate = (stat['valid'] / stat['scanned'] * 100) if stat['scanned'] > 0 else 0
        print(f"  {stat['file']}:")
        print(f"    扫描IP数: {stat['scanned']}")
        print(f"    有效IP数: {stat['valid']} ({success_rate:.2f}%)")
        print(f"    扫描耗时: {stat['time']:.2f}秒")
    
    print(f"\n总体统计:")
    print(f"  总扫描IP数: {total_ips_scanned}")
    print(f"  总有效IP数: {total_valid_ips}")
    if total_ips_scanned > 0:
        print(f"  总体成功率: {total_valid_ips/total_ips_scanned*100:.2f}%")
    
    # 生成报告文件
    report_file = os.path.join(output_dir, f"scan_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"IP扫描报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*60}\n")
        f.write(f"总扫描IP数: {total_ips_scanned}\n")
        f.write(f"总有效IP数: {total_valid_ips}\n")
        if total_ips_scanned > 0:
            f.write(f"总体成功率: {total_valid_ips/total_ips_scanned*100:.2f}%\n")
        
        f.write(f"\n文件详情:\n")
        for stat in file_stats:
            success_rate = (stat['valid'] / stat['scanned'] * 100) if stat['scanned'] > 0 else 0
            f.write(f"  {stat['file']}:\n")
            f.write(f"    扫描IP数: {stat['scanned']}\n")
            f.write(f"    有效IP数: {stat['valid']} ({success_rate:.2f}%)\n")
            f.write(f"    扫描耗时: {stat['time']:.2f}秒\n")
    
    print(f"\n详细报告已保存到: {report_file}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
