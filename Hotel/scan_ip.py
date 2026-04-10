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
    """
    解析IP段，支持以下格式：
    - 单个数字: "94" -> [94]
    - 范围: "94-112" -> [94, 95, ..., 112]
    """
    if '-' in segment_str:
        start, end = segment_str.split('-')
        try:
            start_num = int(start)
            end_num = int(end)
            if 0 <= start_num <= 255 and 0 <= end_num <= 255 and start_num <= end_num:
                return list(range(start_num, end_num + 1))
            else:
                print(f"    [!] IP段范围无效: {segment_str} (应为0-255且开始<=结束)")
                return None
        except ValueError:
            print(f"    [!] IP段格式错误: {segment_str}")
            return None
    else:
        try:
            num = int(segment_str)
            if 0 <= num <= 255:
                return [num]
            else:
                print(f"    [!] IP段超出范围: {segment_str} (应为0-255)")
                return None
        except ValueError:
            print(f"    [!] IP段格式错误: {segment_str}")
            return None

def parse_ip_line(line):
    """
    解析ip文件中的一行
    格式: ip:port 或 ip:port,option
    支持IP段范围，例如: 120.202.94-112.181:9446,2
    """
    line = line.strip()
    if not line or line.startswith('#'):  # 跳过空行和注释
        return None
    
    # 移除可能的空白字符
    line = line.replace(' ', '')
    
    # 分割IP:端口和选项
    if ',' in line:
        ip_port_part, option_part = line.rsplit(',', 1)
        try:
            option = int(option_part)
        except ValueError:
            print(f"    [!] 选项值格式错误: {option_part}")
            option = 0
    else:
        ip_port_part = line
        option = 0
    
    # 分割IP和端口
    if ':' not in ip_port_part:
        print(f"    [!] 格式错误: {line} (缺少端口)")
        return None
    
    # 分割IP和端口
    ip_part, port_part = ip_port_part.rsplit(':', 1)
    
    # 验证端口
    try:
        port = int(port_part)
        if not 1 <= port <= 65535:
            print(f"    [!] 端口超出范围: {port} (1-65535之间)")
            return None
    except ValueError:
        print(f"    [!] 端口格式错误: {port_part}")
        return None
    
    # 分割IP段
    ip_segments = ip_part.split('.')
    if len(ip_segments) != 4:
        print(f"    [!] IP格式错误: {ip_part} (应为4段)")
        return None
    
    # 解析每个IP段
    segments = []
    for i, seg_str in enumerate(ip_segments):
        seg_range = parse_ip_segment(seg_str)
        if seg_range is None:
            print(f"    [!] 第{i+1}段IP格式错误: {seg_str}")
            return None
        segments.append(seg_range)
    
    # 验证option
    if option not in [0, 1, 2]:
        print(f"    [!] 选项值无效: {option} (应为0,1,2)，使用默认值0")
        option = 0
    
    return {
        'segments': segments,  # 每个段是一个列表，如[[120], [202], [94,95,...,112], [181]]
        'port': port,
        'option': option,
        'original_ip': ip_part
    }

def generate_ips_from_segments(segments, port, option):
    """
    根据segments和option生成要扫描的IP列表
    segments: 包含4个列表的列表，每个列表是该段的所有可能值
    option: 0=扫描D段, 1=扫描B/C/D段, 2=扫描C/D段
    """
    a_seg, b_seg, c_seg, d_seg = segments
    
    ip_list = []
    
    # 根据option确定每段的范围
    if option == 0:  # 只扫描D段
        # A,B,C段固定，D段使用指定范围
        a_values = a_seg
        b_values = b_seg
        c_values = c_seg
        
        # D段：如果指定了范围则使用指定范围，否则扩展为1-255
        if len(d_seg) == 1 and d_seg[0] == 0:
            # 特殊处理：如果D段是0，通常表示整个段
            d_values = list(range(1, 256))
        else:
            d_values = d_seg
    
    elif option == 1:  # 扫描B、C、D段
        # A段固定
        a_values = a_seg
        
        # B段：如果指定了范围则使用指定范围，否则扩展为1-255
        if len(b_seg) == 1 and b_seg[0] == 0:
            b_values = list(range(1, 256))
        else:
            b_values = b_seg
        
        # C段：如果指定了范围则使用指定范围，否则扩展为1-255
        if len(c_seg) == 1 and c_seg[0] == 0:
            c_values = list(range(1, 256))
        else:
            c_values = c_seg
        
        # D段：如果指定了范围则使用指定范围，否则扩展为1-255
        if len(d_seg) == 1 and d_seg[0] == 0:
            d_values = list(range(1, 256))
        else:
            d_values = d_seg
    
    elif option == 2:  # 扫描C、D段
        # A、B段固定
        a_values = a_seg
        b_values = b_seg
        
        # C段：如果指定了范围则使用指定范围，否则扩展为1-255
        if len(c_seg) == 1 and c_seg[0] == 0:
            c_values = list(range(1, 256))
        else:
            c_values = c_seg
        
        # D段：如果指定了范围则使用指定范围，否则扩展为1-255
        if len(d_seg) == 1 and d_seg[0] == 0:
            d_values = list(range(1, 256))
        else:
            d_values = d_seg
    
    else:
        print(f"    未知选项 {option}，默认为0")
        a_values = a_seg
        b_values = b_seg
        c_values = c_seg
        d_values = d_seg
    
    # 生成所有IP组合
    total_ips = len(a_values) * len(b_values) * len(c_values) * len(d_values)
    
    print(f"    生成规则: IP={segments_to_str(segments)}, 端口={port}, 选项={option}")
    print(f"    A段: {len(a_values)}个值 ({format_segment_display(a_values)})")
    print(f"    B段: {len(b_values)}个值 ({format_segment_display(b_values)})")
    print(f"    C段: {len(c_values)}个值 ({format_segment_display(c_values)})")
    print(f"    D段: {len(d_values)}个值 ({format_segment_display(d_values)})")
    print(f"    总共生成 {total_ips:,} 个IP")
    
    # 生成IP列表
    for a in a_values:
        for b in b_values:
            for c in c_values:
                for d in d_values:
                    ip_list.append(f"{a}.{b}.{c}.{d}:{port}")
    
    return ip_list

def segments_to_str(segments):
    """将segments转换为字符串表示"""
    result = []
    for seg in segments:
        if len(seg) == 1:
            result.append(str(seg[0]))
        else:
            result.append(f"{seg[0]}-{seg[-1]}")
    return ".".join(result)

def format_segment_display(values):
    """格式化段显示"""
    if len(values) == 1:
        return str(values[0])
    elif len(values) <= 5:
        return f"{values[0]}-{values[-1]}"
    else:
        return f"{values[0]}-{values[-1]} (共{len(values)}个值)"

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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        
        response1 = requests.get(test_url1, headers=headers, timeout=timeout, allow_redirects=False)
        
        if response1.status_code == 200:
            response_time = (time.time() - start_time) * 1000
            return {
                'status': 'success',
                'ip': ip_port,
                'url': test_url1,
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
                'url': test_url2,
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
            'status': 'request_error',
            'ip': ip_port,
            'error': str(e)
        }
    except Exception as e:
        return {
            'status': 'unknown_error',
            'ip': ip_port,
            'error': str(e)
        }

def scan_ips(ip_list, max_workers=100, verbose=True):
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
    
    print(f"    开始扫描，使用 {max_workers} 个线程")
    
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
                status = result['status']
                scan_stats[status] += 1
                
                if status == 'success':
                    valid_ips.append({
                        'ip_port': result['ip'],
                        'response_time': result.get('response_time', 0),
                        'source': result.get('source', 'unknown'),
                        'url': result.get('url', ''),
                        'status_code': result.get('status_code', 0)
                    })
                    
                    if verbose:
                        print(f"    [✓] {result['ip']} - 响应: {result.get('response_time', 0):.0f}ms - 来源: {result.get('source', 'unknown')}")
                
                # 每扫描100个IP打印一次进度
                if verbose and completed % 100 == 0:
                    progress = (completed / len(ip_list)) * 100
                    print(f"    进度: {completed}/{len(ip_list)} ({progress:.1f}%) - 成功: {scan_stats['success']} 无响应: {scan_stats['no_response']} 超时: {scan_stats['timeout']}")
                    
            except Exception as e:
                scan_stats['other_error'] += 1
                if verbose and completed % 100 == 0:
                    print(f"    [!] {ip} - 扫描异常: {str(e)[:50]}")
    
    return valid_ips, scan_stats

def process_file(input_file_path, output_dir, max_workers=20, verbose=True):
    """
    处理单个文件
    """
    print(f"\n{'='*60}")
    print(f"处理文件: {os.path.basename(input_file_path)}")
    print(f"文件路径: {input_file_path}")
    print(f"{'='*60}")
    
    # 检查文件是否存在
    if not os.path.exists(input_file_path):
        print(f"  [!] 错误: 文件不存在")
        return 0, 0, {}
    
    all_ip_to_scan = []
    original_ips = []
    
    # 读取文件并解析
    try:
        with open(input_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            print(f"  文件读取成功，共 {len(lines)} 行")
            
            valid_lines = 0
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                    
                parsed = parse_ip_line(line)
                if parsed:
                    valid_lines += 1
                    ip_str = segments_to_str(parsed['segments'])
                    original_ips.append(f"{ip_str}:{parsed['port']},option={parsed['option']}")
                    print(f"    第{line_num}行: {ip_str}:{parsed['port']}, 选项={parsed['option']}")
                    
                    # 生成要扫描的IP
                    ips_to_scan = generate_ips_from_segments(parsed['segments'], parsed['port'], parsed['option'])
                    all_ip_to_scan.extend(ips_to_scan)
                elif line.strip():  # 如果不是空行，打印警告
                    print(f"    [!] 第{line_num}行解析失败: {line}")
        
        if valid_lines == 0:
            print(f"  [!] 警告: 文件 {input_file_path} 中没有找到有效IP行")
            print(f"  文件内容示例:")
            if len(lines) > 0:
                for i, line in enumerate(lines[:5]):  # 显示前5行
                    print(f"    行{i+1}: {line.rstrip()}")
            return 0, 0, {}
            
        print(f"  有效行数: {valid_lines}")
        print(f"  原始IP列表:")
        for ip in original_ips[:10]:  # 只显示前10个原始IP
            print(f"    - {ip}")
        if len(original_ips) > 10:
            print(f"    ... 还有 {len(original_ips) - 10} 个IP")
        
    except Exception as e:
        print(f"  [!] 读取文件时出错: {e}")
        return 0, 0, {}
    
    if not all_ip_to_scan:
        print(f"  [!] 警告: 没有生成要扫描的IP")
        return 0, 0, {}
    
    print(f"  总共生成 {len(all_ip_to_scan):,} 个IP需要扫描")
    
    # 去重
    unique_count_before = len(all_ip_to_scan)
    all_ip_to_scan = list(set(all_ip_to_scan))
    unique_count_after = len(all_ip_to_scan)
    print(f"  去重: {unique_count_before:,} -> {unique_count_after:,} (去重 {unique_count_before - unique_count_after:,} 个)")
    
    # 分批扫描，避免内存不足
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
        
        print(f"\n  {'-'*50}")
        print(f"  批次 {batch_num}/{total_batches}: {len(batch):,} 个IP")
        if len(batch) > 0:
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
        print(f"  批次统计: 成功 {batch_stats['success']}, 无响应 {batch_stats['no_response']}, 超时 {batch_stats['timeout']}, 连接错误 {batch_stats['connection_error']}")
        if batch_time > 0:
            print(f"  批次耗时: {batch_time:.2f}秒, 平均每个IP: {batch_time/len(batch)*1000:.1f}毫秒")
        else:
            print(f"  批次耗时: {batch_time:.2f}秒")
    
    # 汇总统计
    print(f"\n{'='*60}")
    print(f"文件 {os.path.basename(input_file_path)} 扫描汇总:")
    print(f"  原始IP行数: {valid_lines}")
    print(f"  生成IP总数: {total_stats['total']:,}")
    
    if total_stats['total'] > 0:
        print(f"  成功IP数: {total_stats['success']} ({total_stats['success']/total_stats['total']*100:.2f}%)")
        print(f"  无响应IP数: {total_stats['no_response']} ({total_stats['no_response']/total_stats['total']*100:.2f}%)")
        print(f"  超时IP数: {total_stats['timeout']} ({total_stats['timeout']/total_stats['total']*100:.2f}%)")
        print(f"  连接错误: {total_stats['connection_error']} ({total_stats['connection_error']/total_stats['total']*100:.2f}%)")
        print(f"  请求错误: {total_stats['request_error']} ({total_stats['request_error']/total_stats['total']*100:.2f}%)")
    else:
        print(f"  没有生成可扫描的IP")
    
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
            print(f"    {i:2d}. {ip_info['ip_port']} - {ip_info['response_time']:.0f}ms (来源: {ip_info['source']})")
        
        print(f"\n  保存 {len(all_valid_ips)} 个有效IP到: {output_file_path}")
    else:
        print(f"\n  [!] 没有发现有效IP")
    
    return total_stats['total'], len(all_valid_ips), total_stats

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
        print(f"尝试创建目录...")
        os.makedirs(input_dir, exist_ok=True)
        print(f"已创建目录: {input_dir}")
        print(f"请将IP文件放入此目录，然后重新运行")
        return
    
    # 查找所有txt文件
    txt_files = []
    for file in os.listdir(input_dir):
        if file.endswith('.txt'):
            txt_files.append(os.path.join(input_dir, file))
    
    if not txt_files:
        print(f"在目录 {input_dir} 中没有找到txt文件")
        print(f"目录内容: {os.listdir(input_dir)}")
        
        # 创建示例文件
        example_file = os.path.join(input_dir, "example.txt")
        with open(example_file, 'w', encoding='utf-8') as f:
            f.write("# IP扫描文件示例\n")
            f.write("# 格式: IP:端口,选项\n")
            f.write("# 选项: 0=扫描D段, 1=扫描B/C/D段, 2=扫描C/D段\n")
            f.write("# IP支持范围表示，如: 192.168.1-10.0-255\n")
            f.write("# 示例:\n")
            f.write("192.168.1.1:80,0\n")
            f.write("10.0-10.1.0-255:8080,1\n")
            f.write("172.16-20.1-10.0:443,2\n")
            f.write("120.202.94-112.181:9446,2\n")
            f.write("120.202-206.94-112.181:9446,1\n")
        
        print(f"已创建示例文件: {example_file}")
        print(f"请编辑此文件添加您的IP，然后重新运行")
        return
    
    print(f"{'='*60}")
    print(f"开始IP扫描 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print(f"找到 {len(txt_files)} 个txt文件:")
    for i, file in enumerate(txt_files, 1):
        file_size = os.path.getsize(file)
        print(f"  {i}. {os.path.basename(file)} ({file_size} 字节)")
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
    
    if file_stats:
        print(f"\n文件扫描统计:")
        for stat in file_stats:
            if stat['scanned'] > 0:
                success_rate = (stat['valid'] / stat['scanned'] * 100) 
                print(f"  {stat['file']}:")
                print(f"    扫描IP数: {stat['scanned']:,}")
                print(f"    有效IP数: {stat['valid']} ({success_rate:.2f}%)")
                print(f"    扫描耗时: {stat['time']:.2f}秒")
            else:
                print(f"  {stat['file']}: 没有扫描任何IP")
    
    print(f"\n总体统计:")
    print(f"  总扫描IP数: {total_ips_scanned:,}")
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
            if stat['scanned'] > 0:
                success_rate = (stat['valid'] / stat['scanned'] * 100) 
                f.write(f"  {stat['file']}:\n")
                f.write(f"    扫描IP数: {stat['scanned']}\n")
                f.write(f"    有效IP数: {stat['valid']} ({success_rate:.2f}%)\n")
                f.write(f"    扫描耗时: {stat['time']:.2f}秒\n")
            else:
                f.write(f"  {stat['file']}: 没有扫描任何IP\n")
    
    print(f"\n详细报告已保存到: {report_file}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
