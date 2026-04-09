import os
import time
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
import argparse
from typing import List, Tuple
import sys
from datetime import datetime

# 添加代理设置（如果需要的话）
# 取消注释以下行以设置代理
# proxies = {
#     'http': 'http://127.0.0.1:7890',
#     'https': 'http://127.0.0.1:7890'
# }
proxies = None

def expand_part(part: str) -> List[str]:
    """扩展单个部分，支持范围和单个值"""
    if '-' in part:
        start, end = part.split('-')
        return [str(i) for i in range(int(start), int(end) + 1)]
    else:
        return [part]

def expand_ip_range(ip_str: str) -> List[str]:
    """扩展IP范围，返回IP列表"""
    ip_list = []
    
    # 分割IP的四个部分
    parts = ip_str.split('.')
    if len(parts) != 4:
        return [ip_str]
    
    # 扩展每个部分
    a_list = expand_part(parts[0])
    b_list = expand_part(parts[1])
    c_list = expand_part(parts[2])
    d_list = expand_part(parts[3])
    
    # 生成所有IP组合
    for a in a_list:
        for b in b_list:
            for c in c_list:
                for d in d_list:
                    ip_list.append(f"{a}.{b}.{c}.{d}")
    
    return ip_list

def generate_ip_ports(base_ip: str, port: str, option: int) -> List[str]:
    """根据选项生成要扫描的IP地址列表"""
    a, b, c, d = base_ip.split('.')
    
    # 获取option的个位数，用于判断扫描范围
    option_mod = option % 10
    
    if option_mod == 0:  # 扫描D段1-255
        # 示例: 120.202.94.181:9446,0 -> 扫描 120.202.94.1-255:9446
        return [f"{a}.{b}.{c}.{y}:{port}" for y in range(1, 256)]
        
    elif option_mod == 2:  # 扫描C段和D段
        # 示例: 120.202.94.181:9446,2 -> 扫描 120.202.94.1-255:9446
        # 示例: 120.202.94-102.1-255:9446,2 -> 扫描 120.202.94-102.1-255:9446
        ip_ports = []
        
        # 处理B段
        b_list = expand_part(b)
        
        for b_val in b_list:
            # 处理C段
            c_list = expand_part(c)
            
            for c_val in c_list:
                # 处理D段
                d_list = expand_part(d)
                
                for d_val in d_list:
                    if d_val == '0':  # 跳过D段为0的情况
                        continue
                    ip_ports.append(f"{a}.{b_val}.{c_val}.{d_val}:{port}")
        
        return ip_ports
        
    elif option_mod == 1:  # 扫描B段、C段和D段
        # 示例: 120.202.94.181:9446,1 -> 扫描 120.202.0-255.1-255:9446
        # 示例: 120.202-222.94-102.1-255:9446,1 -> 扫描 120.202-222.94-102.1-255:9446
        ip_ports = []
        
        # 处理B段
        b_list = expand_part(b)
        
        for b_val in b_list:
            # 处理C段
            c_list = expand_part(c)
            
            for c_val in c_list:
                # 处理D段
                d_list = expand_part(d)
                
                for d_val in d_list:
                    if d_val == '0':  # 跳过D段为0的情况
                        continue
                    ip_ports.append(f"{a}.{b_val}.{c_val}.{d_val}:{port}")
        
        return ip_ports
    
    else:  # 默认使用option=0的逻辑
        return [f"{a}.{b}.{c}.{y}:{port}" for y in range(1, 256)]

def check_ip_port(ip_port: str, url_end: str, timeout: int = 2) -> Tuple[str, dict]:
    """发送get请求检测url是否可访问，返回详细请求信息"""
    try:
        url = f"http://{ip_port}{url_end}"
        start_time = time.time()
        resp = requests.get(url, timeout=timeout, proxies=proxies)
        end_time = time.time()
        resp_time = end_time - start_time
        
        resp.raise_for_status()
        if "tsfile" in resp.text or "hls" in resp.text:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ {url} 访问成功 (响应时间: {resp_time:.2f}s, 状态码: {resp.status_code})")
            return ip_port, {
                'url': url,
                'status_code': resp.status_code,
                'response_time': resp_time,
                'success': True,
                'timestamp': datetime.now().isoformat()
            }
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ {url} 无有效内容 (响应时间: {resp_time:.2f}s, 状态码: {resp.status_code})")
            return None, {
                'url': url,
                'status_code': resp.status_code,
                'response_time': resp_time,
                'success': False,
                'timestamp': datetime.now().isoformat(),
                'reason': '无tsfile或hls内容'
            }
    except requests.exceptions.Timeout:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ {url} 请求超时")
        return None, {
            'url': url,
            'status_code': None,
            'response_time': None,
            'success': False,
            'timestamp': datetime.now().isoformat(),
            'reason': '请求超时'
        }
    except requests.exceptions.ConnectionError:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ {url} 连接失败")
        return None, {
            'url': url,
            'status_code': None,
            'response_time': None,
            'success': False,
            'timestamp': datetime.now().isoformat(),
            'reason': '连接失败'
        }
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ {url} 请求异常: {str(e)}")
        return None, {
            'url': url,
            'status_code': None,
            'response_time': None,
            'success': False,
            'timestamp': datetime.now().isoformat(),
            'reason': f'请求异常: {str(e)}'
        }

def check_with_url_ends(ip_port: str, url_ends: List[str], timeout: int = 2) -> Tuple[bool, dict]:
    """用多个URL端点检查IP端口，返回详细请求信息"""
    best_response = None
    best_status = False
    
    for url_end in url_ends:
        try:
            url = f"http://{ip_port}{url_end}"
            start_time = time.time()
            resp = requests.get(url, timeout=timeout, proxies=proxies)
            end_time = time.time()
            resp_time = end_time - start_time
            
            if resp.status_code == 200:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ 二次验证成功: {url} (响应时间: {resp_time:.2f}s)")
                return True, {
                    'url': url,
                    'status_code': resp.status_code,
                    'response_time': resp_time,
                    'success': True,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ 二次验证失败: {url} (状态码: {resp.status_code}, 响应时间: {resp_time:.2f}s)")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ 二次验证异常: {url} - {str(e)}")
    
    return False, best_response

def scan_ip_port(base_ip: str, port: str, option: int, url_end: str, progress_queue: Queue = None) -> Tuple[List[str], List[dict]]:
    """扫描IP端口，返回有效IP列表和所有请求信息"""
    valid_ip_ports = []
    all_requests_info = []
    ip_ports = generate_ip_ports(base_ip, port, option)
    total = len(ip_ports)
    
    print(f"开始扫描: {base_ip}:{port}, option={option}, 总IP数: {total}")
    
    # 根据option设置线程数
    max_workers = 300 if option % 2 == 1 else 100
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_ip_port, ip_port, url_end): ip_port for ip_port in ip_ports}
        
        for i, future in enumerate(as_completed(futures), 1):
            ip_port = futures[future]
            result, request_info = future.result()
            
            # 保存请求信息
            all_requests_info.append(request_info)
            
            if result:
                valid_ip_ports.append(result)
            
            # 更新进度
            if progress_queue and i % 100 == 0:
                progress_queue.put((i, total))
    
    return valid_ip_ports, all_requests_info

def read_config(config_file: str) -> Tuple[List[Tuple], List[str]]:
    """读取配置文件，返回配置行列表和原始行列表"""
    print(f"读取设置文件：{config_file}")
    ip_configs = []
    original_lines = []
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        for line_num, line in enumerate(lines, 1):
            original_line = line.rstrip('\n')
            original_lines.append(original_line)
            line = line.strip()
            
            if not line or line.startswith("#"):
                continue
                
            try:
                if "," in line:
                    parts = line.split(',')
                    ip_part_port = parts[0].strip()
                    option = int(parts[1].strip())
                else:
                    ip_part_port = line.strip()
                    option = 0  # 修改：默认值为0而不是12
                
                if ":" not in ip_part_port:
                    print(f"第{line_num}行格式错误: 缺少端口号 - {line}")
                    continue
                    
                # 分离IP和端口
                ip_part, port = ip_part_port.split(':')
                
                # 检查是否是带范围的IP
                if '-' in ip_part:
                    # 扩展带范围的IP
                    expanded_ips = expand_ip_range(ip_part)
                    print(f"  第{line_num}行IP扩展: {ip_part} -> {len(expanded_ips)} 个IP")
                    
                    # 为每个扩展的IP创建配置
                    for expanded_ip in expanded_ips:
                        ip_parts = expanded_ip.split('.')
                        a, b, c, d = ip_parts
                        url_end = "/status" if option >= 10 else "/stat"
                        base_ip = f"{a}.{b}.{c}.{d}"
                        
                        # 保存原始行（如果有option就包含，没有就不包含）
                        if "," in original_line:
                            original_for_ip = f"{expanded_ip}:{port},{option}"
                        else:
                            original_for_ip = f"{expanded_ip}:{port}"
                        
                        ip_configs.append((base_ip, port, option, url_end, line_num-1, original_for_ip))
                else:
                    # 原来的逻辑，处理普通IP
                    ip_parts = ip_part.split('.')
                    if len(ip_parts) != 4:
                        print(f"第{line_num}行格式错误: IP地址格式不正确 - {line}")
                        continue
                    
                    a, b, c, d = ip_parts
                    url_end = "/status" if option >= 10 else "/stat"
                    base_ip = f"{a}.{b}.{c}.{d}"
                    
                    ip_configs.append((base_ip, port, option, url_end, line_num-1, original_line))
                    
            except Exception as e:
                print(f"第{line_num}行格式错误: {e} - {line}")
                continue
                
        return ip_configs, original_lines
    except Exception as e:
        print(f"读取文件错误: {e}")
        return [], []

def progress_monitor(progress_queue: Queue, total_configs: int):
    """进度监视器"""
    config_count = 0
    while True:
        try:
            item = progress_queue.get(timeout=300)  # 5分钟超时
            if item is None:  # 结束信号
                break
            
            if isinstance(item, tuple) and len(item) == 2:
                current, total = item
                print(f"进度: {current}/{total} ({current/total*100:.1f}%)")
            elif item == "CONFIG_COMPLETE":
                config_count += 1
                print(f"配置 {config_count}/{total_configs} 扫描完成")
        except:
            break

def save_requests_log(requests_info: List[dict], output_file: str):
    """保存请求日志到文件"""
    if not requests_info:
        return
    
    # 确保目录存在
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("请求时间,URL,状态码,响应时间(秒),是否成功,失败原因\n")
        for req in requests_info:
            timestamp = req.get('timestamp', '')
            url = req.get('url', '')
            status_code = req.get('status_code', '')
            response_time = req.get('response_time', '')
            success = req.get('success', False)
            reason = req.get('reason', '')
            
            f.write(f"{timestamp},{url},{status_code},{response_time},{success},{reason}\n")

def scan_single_file(input_file: str, output_dir: str = "Hotel/ip/results"):
    """扫描单个IP文件"""
    # 获取文件名
    filename = os.path.basename(input_file)
    output_file = os.path.join(output_dir, filename)
    log_file = os.path.join(output_dir, f"{os.path.splitext(filename)[0]}_requests.log")
    
    # 读取配置
    ip_configs, original_lines = read_config(input_file)
    
    if not ip_configs:
        print(f"文件中没有有效的配置: {input_file}")
        return []
    
    print(f"找到 {len(ip_configs)} 个IP配置")
    
    # 创建进度队列
    progress_queue = Queue()
    
    # 启动进度监视器
    progress_thread = threading.Thread(target=progress_monitor, args=(progress_queue, len(ip_configs)))
    progress_thread.daemon = True
    progress_thread.start()
    
    all_valid_ips = []
    all_requests_info = []
    
    # 二次验证的URL端点
    url_ends = ["/iptv/live/1000.json?key=txiptv", "/ZHGXTV/Public/json/live_interface.txt"]
    
    # 扫描每个配置
    for i, (base_ip, port, option, url_end, line_num, original_line) in enumerate(ip_configs, 1):
        print(f"\n{'='*60}")
        print(f"处理配置 {i}/{len(ip_configs)}: {original_line}")
        print(f"  option={option}, 扫描范围: ", end="")
        
        # 解释option的含义
        option_mod = option % 10
        if option_mod == 0:
            print(f"D段1-255 (基于 {base_ip})")
        elif option_mod == 1:
            print(f"B段、C段、D段 (基于 {base_ip})")
        elif option_mod == 2:
            print(f"C段、D段 (基于 {base_ip})")
        else:
            print(f"未知选项: {option_mod}")
        
        # 计算总IP数用于预估
        ip_ports = generate_ip_ports(base_ip, port, option)
        print(f"  预估扫描IP数: {len(ip_ports)}")
        
        # 扫描IP端口
        valid_ips, requests_info = scan_ip_port(base_ip, port, option, url_end, progress_queue)
        all_requests_info.extend(requests_info)
        
        if valid_ips:
            print(f"找到 {len(valid_ips)} 个有效IP")
            
            # 二次验证
            print("开始二次验证...")
            final_valid_ips = []
            second_stage_info = []
            
            with ThreadPoolExecutor(max_workers=50) as executor:
                futures = {}
                for ip_port in valid_ips:
                    future = executor.submit(check_with_url_ends, ip_port, url_ends)
                    futures[future] = ip_port
                
                for future in as_completed(futures):
                    ip_port = futures[future]
                    result, request_info = future.result()
                    if request_info:
                        second_stage_info.append(request_info)
                    if result:
                        final_valid_ips.append(ip_port)
            
            all_requests_info.extend(second_stage_info)
            print(f"二次验证后剩余 {len(final_valid_ips)} 个IP")
            all_valid_ips.extend(final_valid_ips)
        
        # 发送配置完成信号
        progress_queue.put("CONFIG_COMPLETE")
    
    # 发送结束信号
    progress_queue.put(None)
    progress_thread.join(timeout=10)
    
    # 去重并保存结果
    if all_valid_ips:
        unique_ips = list(set(all_valid_ips))
        print(f"\n扫描完成! 共找到 {len(unique_ips)} 个唯一有效IP")
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        # 保存有效IP到文件
        with open(output_file, 'w', encoding='utf-8') as f:
            for ip in unique_ips:
                f.write(f"{ip}\n")
        
        print(f"结果已保存到: {output_file}")
        
        # 保存请求日志
        save_requests_log(all_requests_info, log_file)
        print(f"请求日志已保存到: {log_file}")
        
        # 打印摘要统计
        print(f"\n扫描统计:")
        print(f"  总请求数: {len(all_requests_info)}")
        print(f"  成功请求数: {sum(1 for req in all_requests_info if req.get('success'))}")
        print(f"  失败请求数: {sum(1 for req in all_requests_info if not req.get('success'))}")
    else:
        print("\n没有找到有效IP")
    
    return all_valid_ips

def scan_all_files(input_dir: str = "Hotel/ip/ip", output_dir: str = "Hotel/ip/results"):
    """扫描指定目录下的所有IP文件"""
    # 确保目录存在
    if not os.path.exists(input_dir):
        print(f"输入目录不存在: {input_dir}")
        return {}
    
    # 获取所有txt文件
    ip_files = [f for f in os.listdir(input_dir) if f.endswith('.txt')]
    
    if not ip_files:
        print(f"在目录 {input_dir} 中没有找到txt文件")
        return {}
    
    print(f"找到 {len(ip_files)} 个IP文件")
    
    all_results = {}
    
    for ip_file in ip_files:
        print(f"\n{'='*60}")
        print(f"处理文件: {ip_file}")
        print('='*60)
        
        input_file = os.path.join(input_dir, ip_file)
        valid_ips = scan_single_file(input_file, output_dir)
        
        if valid_ips:
            all_results[ip_file] = valid_ips
        
        time.sleep(1)  # 避免请求过于频繁
    
    return all_results

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='IP扫描工具')
    parser.add_argument('--file', type=str, help='指定单个IP文件进行扫描')
    parser.add_argument('--dir', type=str, default='Hotel/ip/ip', help='IP文件目录，默认为 Hotel/ip/ip')
    parser.add_argument('--output', type=str, default='Hotel/ip/results', help='输出目录，默认为 Hotel/ip/results')
    parser.add_argument('--region', type=str, default='', help='指定地区文件（不带扩展名）')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细日志')
    
    args = parser.parse_args()
    
    # 设置requests超时和重试
    import requests.adapters
    requests.adapters.DEFAULT_RETRIES = 2
    
    # 打印开始时间
    start_time = time.time()
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print('='*60)
    
    if args.region:
        # 扫描指定地区
        input_file = os.path.join(args.dir, f"{args.region}.txt")
        if os.path.exists(input_file):
            print(f"扫描指定地区: {args.region}")
            scan_single_file(input_file, args.output)
        else:
            print(f"地区文件不存在: {input_file}")
            # 尝试扫描所有文件
            scan_all_files(args.dir, args.output)
    elif args.file:
        # 扫描单个文件
        if os.path.exists(args.file):
            scan_single_file(args.file, args.output)
        else:
            print(f"文件不存在: {args.file}")
    else:
        # 扫描目录下所有文件
        scan_all_files(args.dir, args.output)
    
    # 打印结束时间和总耗时
    end_time = time.time()
    print(f"\n{'='*60}")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"总耗时: {end_time - start_time:.2f}秒")
    print('='*60)

if __name__ == "__main__":
    main()
