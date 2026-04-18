import urllib.request
import ssl
import socket
import statistics
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
import concurrent.futures
import time
import json
import os

# 禁用SSL警告
ssl._create_default_https_context = ssl._create_unverified_context

# ====================== 配置类 ======================
class SpeedTestConfig:
    """测速配置类"""
    # 测速阈值
    SPEED_THRESHOLD = 100  # KB/s
    CHECK_TIMEOUT = 5
    MAX_WORKERS = 20
    
    # 深度测速参数
    DEEP_TEST_SIZE = 1024 * 1024  # 1MB
    CHUNK_SIZE = 64 * 1024  # 64KB
    MAX_DEEP_TIME = 1.2
    MIN_SPEED_SAMPLES = 3  # 最少采样次数
    
    # 分组定义
    DEEP_SPEED_GROUPS = ['freetv', 'freetv_cctv', 'freetv_ws', 'freetv_other']
    
    # 重试策略
    MAX_RETRIES = 2
    RETRY_DELAY = 0.5
    
    # 头信息
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3',
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
    }


# ====================== 测速引擎 ======================
class SpeedTestEngine:
    """测速引擎类"""
    
    def __init__(self, config):
        self.config = config
        self.speed_results = {}
        self.failed_urls = set()  # 记录失败的URL避免重复测速
        self.cache = {}  # 简单的结果缓存
        self.cache_ttl = 300  # 5分钟缓存
        self.stats = {
            'total_tested': 0,
            'passed': 0,
            'failed': 0,
            'retried': 0,
            'cached': 0,
            'avg_speed': 0,
            'max_speed': 0,
            'min_speed': float('inf'),
            'speed_samples': []
        }
        
    def _clean_url(self, url):
        """清理URL参数，用于去重"""
        try:
            parsed = urlparse(url)
            # 移除查询参数和片段
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        except:
            return url
            
    def _is_cached(self, url, group_name):
        """检查是否有缓存结果"""
        cache_key = f"{self._clean_url(url)}_{group_name}"
        if cache_key in self.cache:
            result, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return result
        return None
    
    def _set_cache(self, url, group_name, result):
        """设置缓存"""
        cache_key = f"{self._clean_url(url)}_{group_name}"
        self.cache[cache_key] = (result, time.time())
        
    def _check_url_safety(self, url):
        """URL安全检查"""
        try:
            parsed = urlparse(url)
            if not parsed.scheme in ('http', 'https'):
                return False, "不支持的协议"
            if not parsed.netloc:
                return False, "无效的域名"
            # 检查常见问题
            if ' ' in url:
                return False, "URL包含空格"
            return True, "OK"
        except Exception as e:
            return False, f"URL解析失败: {str(e)[:30]}"
            
    def _get_speed_with_retry(self, url, group_name, retry_count=0):
        """带重试的测速函数"""
        if url in self.failed_urls and retry_count == 0:
            print(f"  ⚠ {url[:50]:<50} | 之前已失败，跳过重试")
            return 0.0
            
        # 检查缓存
        cached_result = self._is_cached(url, group_name)
        if cached_result is not None:
            self.stats['cached'] += 1
            print(f"  ♻ {url[:50]:<50} | 使用缓存结果: {cached_result:.1f}KB/s")
            return cached_result
            
        is_deep = group_name in self.config.DEEP_SPEED_GROUPS
        start_time = time.time()
        
        try:
            # URL安全检查
            is_safe, reason = self._check_url_safety(url)
            if not is_safe:
                print(f"  ✗ {url[:50]:<50} | URL安全检查失败: {reason}")
                return 0.0
                
            # 创建请求
            req = urllib.request.Request(url, headers=self.config.HEADERS)
            
            # 打开连接
            response = urllib.request.urlopen(req, timeout=self.config.CHECK_TIMEOUT)
            
            # 测量TTFB
            ttfb = time.time() - start_time
            
            if ttfb > 3:  # TTFB过长直接返回
                print(f"  ⚠ {url[:50]:<50} | TTFB过长: {ttfb*1000:.1f}ms")
                response.close()
                return 0.0
                
            if is_deep:
                result = self._deep_speed_test(url, response, ttfb)
            else:
                result = self._quick_speed_test(url, ttfb)
            
            # 缓存结果
            if result > 0:
                self._set_cache(url, group_name, result)
                
            return result
            
        except urllib.error.HTTPError as e:
            if e.code in [403, 404, 500, 502, 503]:
                print(f"  ✗ {url[:50]:<50} | HTTP错误: {e.code}")
                self.failed_urls.add(url)
                return 0.0
            elif retry_count < self.config.MAX_RETRIES:
                time.sleep(self.config.RETRY_DELAY * (retry_count + 1))
                self.stats['retried'] += 1
                return self._get_speed_with_retry(url, group_name, retry_count + 1)
            else:
                print(f"  ✗ {url[:50]:<50} | HTTP错误: {e.code} (重试{retry_count}次后失败)")
                return 0.0
                
        except (urllib.error.URLError, socket.timeout) as e:
            if retry_count < self.config.MAX_RETRIES:
                time.sleep(self.config.RETRY_DELAY * (retry_count + 1))
                self.stats['retried'] += 1
                return self._get_speed_with_retry(url, group_name, retry_count + 1)
            else:
                print(f"  ✗ {url[:50]:<50} | 连接失败: {str(e)[:30]}")
                self.failed_urls.add(url)
                return 0.0
                
        except Exception as e:
            print(f"  ✗ {url[:50]:<50} | 测速异常: {str(e)[:30]}")
            return 0.0
                
    def _deep_speed_test(self, url, response, ttfb):
        """深度测速实现"""
        downloaded = 0
        speed_samples = []
        test_start = time.time()
        
        try:
            # 分块读取并记录每个块的速度
            while downloaded < self.config.DEEP_TEST_SIZE:
                chunk_start = time.time()
                chunk = response.read(min(self.config.CHUNK_SIZE, 
                                        self.config.DEEP_TEST_SIZE - downloaded))
                if not chunk:
                    break
                    
                chunk_time = time.time() - chunk_start
                if chunk_time > 0:
                    chunk_speed = len(chunk) / chunk_time / 1024  # KB/s
                    speed_samples.append(chunk_speed)
                
                downloaded += len(chunk)
                
                # 检查超时
                if time.time() - test_start > self.config.MAX_DEEP_TIME:
                    break
                    
            # 关闭响应
            response.close()
            
            if not speed_samples or downloaded == 0:
                return 0.0
                
            # 计算有效速度（排除异常值）
            if len(speed_samples) >= 5:
                # 计算中位数，排除极端值
                median_speed = statistics.median(speed_samples)
                # 过滤掉偏离中位数过大的值
                filtered_speeds = [s for s in speed_samples if 0.5 <= s/median_speed <= 2.0]
                if filtered_speeds:
                    avg_speed = sum(filtered_speeds) / len(filtered_speeds)
                else:
                    avg_speed = median_speed
            else:
                avg_speed = sum(speed_samples) / len(speed_samples)
                
            # 计算稳定性评分
            if len(speed_samples) > 1:
                try:
                    speed_std = statistics.stdev(speed_samples) if len(speed_samples) >= 2 else 0
                    stability = 1.0 - min(speed_std / avg_speed, 1.0) if avg_speed > 0 else 0
                except:
                    stability = 1.0
            else:
                stability = 1.0
                
            duration = time.time() - test_start
            ttfb_ms = ttfb * 1000
            
            # 根据稳定性调整最终速度
            final_speed = avg_speed * (0.7 + 0.3 * stability)
            
            # 更新统计
            self.stats['max_speed'] = max(self.stats['max_speed'], final_speed)
            self.stats['min_speed'] = min(self.stats['min_speed'], final_speed)
            self.stats['speed_samples'].append(final_speed)
            
            print(f"  ✓ {url[:50]:<50} | TTFB: {ttfb_ms:5.1f}ms | "
                  f"下载: {downloaded/1024:6.1f}KB | 耗时: {duration:4.2f}s | "
                  f"速度: {final_speed:7.1f}KB/s | 样本: {len(speed_samples)} | "
                  f"稳定性: {stability:.2f}")
                  
            return final_speed
            
        except Exception as e:
            try:
                response.close()
            except:
                pass
            print(f"  ✗ {url[:50]:<50} | 深度测速失败: {str(e)[:30]}")
            return 0.0
            
    def _quick_speed_test(self, url, ttfb):
        """快速测速实现"""
        ttfb_ms = ttfb * 1000
        
        # 更精确的速度估算公式
        if ttfb < 0.1:  # TTFB非常快
            speed = 2000.0 / (ttfb + 0.001)
        elif ttfb < 0.5:  # TTFB较快
            speed = 1000.0 / (ttfb + 0.001)
        else:  # TTFB较慢
            speed = 500.0 / (ttfb + 0.001)
            
        # 更新统计
        self.stats['max_speed'] = max(self.stats['max_speed'], speed)
        self.stats['min_speed'] = min(self.stats['min_speed'], speed)
        self.stats['speed_samples'].append(speed)
            
        print(f"  ✓ {url[:50]:<50} | TTFB: {ttfb_ms:5.1f}ms | 预估速度: {speed:7.1f}KB/s")
        return speed
        
    def get_stats(self):
        """获取统计信息"""
        if self.stats['speed_samples']:
            self.stats['avg_speed'] = sum(self.stats['speed_samples']) / len(self.stats['speed_samples'])
        return self.stats


# ====================== 批量测速函数 ======================
def batch_speed_test_optimized(channel_list, group_name="freetv"):
    """优化的批量测速函数"""
    config = SpeedTestConfig()
    engine = SpeedTestEngine(config)
    
    print(f"开始对 {len(channel_list)} 个频道进行速度测试...")
    print("-" * 120)
    
    fast_channels = []
    total_channels = len(channel_list)
    
    def process_channel(channel_info):
        """处理单个频道"""
        channel_name, channel_url = channel_info
        
        # 检查URL格式
        if not channel_url.startswith(('http://', 'https://')):
            print(f"  ✗ {channel_name[:30]:<30} | 无效的URL协议")
            engine.stats['failed'] += 1
            return channel_info, 0.0, False
            
        # 测速
        print(f"测试: {channel_name[:30]:<30} | {channel_url[:50]:<50}")
        speed = engine._get_speed_with_retry(channel_url, group_name)
        
        # 记录结果
        engine.speed_results[channel_name] = speed
        
        if speed >= config.SPEED_THRESHOLD:
            result_str = f"  ✅ 通过 | 速度: {speed:7.1f}KB/s"
            print(result_str)
            engine.stats['passed'] += 1
            return channel_info, speed, True
        else:
            result_str = f"  ❌ 失败 | 速度: {speed:7.1f}KB/s"
            print(result_str)
            engine.stats['failed'] += 1
            return channel_info, speed, False
    
    # 使用线程池
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        # 提交任务
        future_to_channel = {
            executor.submit(process_channel, channel_info): channel_info 
            for channel_info in channel_list
        }
        
        # 处理结果
        completed = 0
        for future in concurrent.futures.as_completed(future_to_channel):
            completed += 1
            try:
                channel_info, speed, passed = future.result()
                channel_name, channel_url = channel_info
                
                if passed:
                    fast_channels.append(f"{channel_name},{channel_url}")
                
                # 进度显示
                if completed % 5 == 0 or completed == total_channels:
                    current_passed = len(fast_channels)
                    pass_rate = (current_passed / completed * 100) if completed > 0 else 0
                    
                    stats = engine.get_stats()
                    avg_speed = stats['avg_speed']
                    
                    print(f"\n进度: {completed}/{total_channels} ({completed/total_channels*100:.1f}%) | "
                          f"通过: {current_passed} ({pass_rate:.1f}%) | "
                          f"平均速度: {avg_speed:.1f} KB/s | "
                          f"缓存命中: {stats['cached']}")
                    print("-" * 120)
                    
            except Exception as e:
                print(f"\n处理频道出错: {e}")
                engine.stats['failed'] += 1
    
    engine.stats['total_tested'] = total_channels
    
    # 计算最终统计
    print("\n" + "=" * 120)
    print(f"速度测试完成!")
    print(f"总计测试: {engine.stats['total_tested']} 个频道")
    print(f"通过测试: {engine.stats['passed']} 个 (速度 ≥ {config.SPEED_THRESHOLD} KB/s)")
    print(f"失败: {engine.stats['failed']} 个")
    print(f"重试次数: {engine.stats['retried']} 次")
    print(f"缓存命中: {engine.stats['cached']} 次")
    
    if engine.stats['total_tested'] > 0:
        pass_rate = engine.stats['passed'] / engine.stats['total_tested'] * 100
        print(f"通过率: {pass_rate:.1f}%")
        print(f"平均速度: {engine.stats['avg_speed']:.1f} KB/s")
        print(f"最高速度: {engine.stats['max_speed']:.1f} KB/s")
        print(f"最低速度: {engine.stats['min_speed']:.1f} KB/s" if engine.stats['min_speed'] != float('inf') else "最低速度: 0.0 KB/s")
    
    print("=" * 120)
    
    return fast_channels, engine.speed_results, engine.get_stats()


# ====================== 报告生成 ======================
def generate_speed_report(speed_results, fast_channels, config, test_time, stats):
    """生成详细测速报告"""
    
    if not speed_results:
        return ""
        
    # 按速度排序
    sorted_speeds = sorted(speed_results.items(), key=lambda x: x[1], reverse=True)
    
    # 统计不同速度区间
    speed_ranges = [
        (0, 50, "0-50 KB/s"),
        (50, 100, "50-100 KB/s"),
        (100, 300, "100-300 KB/s"),
        (300, 1000, "300-1000 KB/s"),
        (1000, 5000, "1-5 MB/s"),
        (5000, float('inf'), "5+ MB/s")
    ]
    
    range_stats = {}
    for min_speed, max_speed, label in speed_ranges:
        count = len([s for s in speed_results.values() if min_speed <= s < max_speed])
        if count > 0:
            range_stats[label] = count
    
    # 生成报告
    report_lines = [
        "=" * 80,
        f"IPTV频道测速报告",
        f"测试时间: {test_time}",
        f"速度阈值: {config.SPEED_THRESHOLD} KB/s",
        f"总频道数: {len(speed_results)}",
        f"通过数: {len(fast_channels)}",
        f"通过率: {len(fast_channels)/len(speed_results)*100:.2f}%" if speed_results else "0.00%",
        f"平均速度: {stats['avg_speed']:.1f} KB/s",
        f"最高速度: {stats['max_speed']:.1f} KB/s",
        f"最低速度: {stats['min_speed']:.1f} KB/s" if stats['min_speed'] != float('inf') else "最低速度: 0.0 KB/s",
        f"重试次数: {stats['retried']}",
        f"缓存命中: {stats['cached']}",
        "-" * 80,
        f"速度分布统计:"
    ]
    
    for label, count in sorted(range_stats.items(), key=lambda x: x[1], reverse=True):
        percentage = count / len(speed_results) * 100
        report_lines.append(f"  {label:<12} : {count:4d} 个 ({percentage:6.2f}%)")
    
    # 速度最快的20个频道
    report_lines.extend([
        "-" * 80,
        "速度排名 (前20名):"
    ])
    
    for i, (name, speed) in enumerate(sorted_speeds[:20], 1):
        status = "✓" if speed >= config.SPEED_THRESHOLD else "✗"
        report_lines.append(f"{i:3d}. [{status}] {name[:40]:<40} : {speed:7.1f} KB/s")
    
    report_lines.append("=" * 80)
    
    return "\n".join(report_lines)


# ====================== 原有的数据处理函数 ======================
def load_modify_name(filename):
    """读取修改频道名称方法"""
    corrections = {}
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split(',')
            correct_name = parts[0]
            for name in parts[1:]:
                corrections[name] = correct_name
    return corrections

def rename_channel(corrections, data):
    """纠错频道名称"""
    corrected_data = []
    for line in data:
        name, url = line.split(',', 1)
        if name in corrections and name != corrections[name]:
            name = corrections[name]
        corrected_data.append(f"{name},{url}")
    return corrected_data

def read_txt_to_array(file_name):
    """读取文本方法"""
    try:
        with open(file_name, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            lines = [line.strip() for line in lines]
            return lines
    except FileNotFoundError:
        print(f"File '{file_name}' not found.")
        return []
    except Exception as e:
        print(f"An error occurred: {e}")
        return []

def process_channel_line(line, freetv_dictionary, freetv_lines):
    """组织过滤后的freetv"""
    if "#genre#" not in line and "," in line and "://" in line:
        try:
            channel_name, channel_address = line.split(',', 1)
            if channel_name in freetv_dictionary:
                freetv_lines.append(f"{channel_name},{channel_address}".strip())
        except ValueError:
            pass

def process_url(url, freetv_dictionary, freetv_lines):
    """处理URL获取频道"""
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3')

        with urllib.request.urlopen(req) as response:
            data = response.read()
            text = data.decode('utf-8')

            lines = text.split('\n')
            print(f"从URL获取到 {len(lines)} 行数据")
            
            for line in lines:
                line = line.strip()
                process_channel_line(line, freetv_dictionary, freetv_lines)
                        
            print(f"处理后得到 {len(freetv_lines)} 个有效频道")

    except Exception as e:
        print(f"处理URL时发生错误：{e}")


# ====================== 主程序 ======================
def main():
    # 首先读取字典文件
    print("正在加载频道字典...")
    rename_dic = load_modify_name('py/iptv源收集检测/assets/freetv/freetv_rename.txt')
    
    # 读取文本
    freetv_dictionary = read_txt_to_array('py/iptv源收集检测/assets/freetv/freetvlist.txt')
    freetv_dictionary_cctv = read_txt_to_array('py/iptv源收集检测/assets/freetv/freetvlist_cctv.txt')
    freetv_dictionary_ws = read_txt_to_array('py/iptv源收集检测/assets/freetv/freetvlist_ws.txt')
    
    print(f"加载频道字典: 全部 {len(freetv_dictionary)} 个, CCTV {len(freetv_dictionary_cctv)} 个, 卫视 {len(freetv_dictionary_ws)} 个")
    
    # 初始化分类列表
    freetv_lines = []
    freetv_cctv_lines = []
    freetv_ws_lines = []
    freetv_other_lines = []
    
    # 定义URLs
    urls = ["https://freetv.fun/test_channels_original_new.txt"]
    
    # 处理URL获取频道
    for url in urls:
        print(f"\n处理URL: {url}")
        process_url(url, freetv_dictionary, freetv_lines)
    
    # 检查是否获取到频道
    if not freetv_lines:
        print("错误: 没有获取到任何频道，请检查网络连接或URL")
        exit(1)
    
    print(f"\n成功获取 {len(freetv_lines)} 个频道")
    
    # 获取当前的 UTC 时间
    utc_time = datetime.now(timezone.utc)
    beijing_time = utc_time + timedelta(hours=8)
    formatted_time = beijing_time.strftime("%Y%m%d %H:%M:%S")
    
    # 重命名频道
    freetv_lines_renamed = rename_channel(rename_dic, freetv_lines)
    print(f"重命名后频道数: {len(freetv_lines_renamed)}")
    
    # 准备速度测试的频道列表
    channels_to_test = []
    for line in freetv_lines_renamed:
        if "#genre#" not in line and "," in line and "://" in line:
            try:
                channel_name, channel_address = line.split(',', 1)
                if channel_address.startswith(('http://', 'https://')):
                    channels_to_test.append((channel_name, channel_address))
            except:
                continue
    
    print(f"\n准备对 {len(channels_to_test)} 个频道进行速度测试...")
    
    # 进行速度测试
    if channels_to_test:
        config = SpeedTestConfig()
        fast_channels, speed_results, stats = batch_speed_test_optimized(channels_to_test, "freetv")
        
        # 生成并显示报告
        report = generate_speed_report(speed_results, fast_channels, config, formatted_time, stats)
        print("\n" + report)
        
        # 保存报告
        report_file = "py/iptv源收集检测/assets/freetv/freetv_speed_report.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"详细报告已保存到: {report_file}")
        
        # 保存速度统计信息
        if speed_results:
            speed_stats_file = "py/iptv源收集检测/assets/freetv/freetv_speed_stats.txt"
            with open(speed_stats_file, 'w', encoding='utf-8') as f:
                f.write(f"速度测试统计 - 阈值: {config.SPEED_THRESHOLD} KB/s\n")
                f.write(f"测试时间: {formatted_time}\n")
                f.write(f"总频道数: {len(channels_to_test)}\n")
                f.write(f"通过测试数: {len(fast_channels)}\n")
                f.write(f"通过率: {(len(fast_channels)/len(channels_to_test)*100 if channels_to_test else 0):.2f}%\n")
                f.write(f"平均速度: {stats['avg_speed']:.2f} KB/s\n")
                f.write(f"最高速度: {stats['max_speed']:.2f} KB/s\n")
                f.write(f"最低速度: {stats['min_speed']:.2f} KB/s\n")
                f.write(f"重试次数: {stats['retried']}\n")
                f.write(f"缓存命中: {stats['cached']}\n\n")
                
                # 按速度排序
                sorted_speeds = sorted(speed_results.items(), key=lambda x: x[1], reverse=True)
                f.write("频道速度排名 (前100名):\n")
                for i, (name, speed) in enumerate(sorted_speeds[:100], 1):
                    status = "✓" if speed >= config.SPEED_THRESHOLD else "✗"
                    f.write(f"{i:3d}. [{status}] {name}: {speed:.2f} KB/s\n")
                
                # 添加详细的速度统计
                speed_ranges = [
                    (0, 100, "0-100 KB/s"),
                    (100, 300, "100-300 KB/s"),
                    (300, 1000, "300-1000 KB/s"),
                    (1000, float('inf'), "1000+ KB/s")
                ]
                
                for min_speed, max_speed, label in speed_ranges:
                    count = len([s for s in speed_results.values() if min_speed <= s < max_speed])
                    f.write(f"- {label}: {count} 个频道\n")
                    
            print(f"速度统计已保存到: {speed_stats_file}")
        
        # 生成通过测速的频道列表
        version = f"更新时间,{formatted_time}"
        output_lines = ["#genre#"] + [version] + [''] + \
                       ["freetv,#genre#"] + sorted(set(fast_channels))
    else:
        print("错误: 没有需要测试的频道")
        output_lines = ["#genre#"]
        speed_results = {}
        fast_channels = []
    
    # 将合并后的文本写入文件：全集
    output_file = "py/iptv源收集检测/assets/freetv/freetv_output.txt"
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for line in output_lines:
                f.write(line + '\n')
        print(f"已保存到文件: {output_file}")
    except Exception as e:
        print(f"保存文件时发生错误：{e}")
    
    # 对通过测速的频道进行分类
    for line in fast_channels:
        if "#genre#" not in line and "," in line and "://" in line:
            try:
                channel_name = line.split(',')[0].strip()
                channel_address = line.split(',')[1].strip()
                
                if channel_name in freetv_dictionary_cctv:  # 央视频道
                    freetv_cctv_lines.append(f"{channel_name},{channel_address}")
                elif channel_name in freetv_dictionary_ws:  # 卫视频道
                    freetv_ws_lines.append(f"{channel_name},{channel_address}")
                else:
                    freetv_other_lines.append(f"{channel_name},{channel_address}")
            except:
                continue
    
    # 生成分类文件
    version_line = f"更新时间,{formatted_time}"
    
    # freetv_cctv
    if freetv_cctv_lines:
        output_lines_cctv = ["#genre#"] + [version_line] + [''] + \
                           ["freetv_cctv,#genre#"] + sorted(set(freetv_cctv_lines))
    else:
        output_lines_cctv = ["#genre#", version_line, '', "freetv_cctv,#genre#"]
    
    # freetv_ws
    if freetv_ws_lines:
        output_lines_ws = ["#genre#"] + [version_line] + [''] + \
                         ["freetv_ws,#genre#"] + sorted(set(freetv_ws_lines))
    else:
        output_lines_ws = ["#genre#", version_line, '', "freetv_ws,#genre#"]
    
    # freetv_other
    if freetv_other_lines:
        output_lines_other = ["#genre#"] + [version_line] + [''] + \
                            ["freetv_other,#genre#"] + sorted(set(freetv_other_lines))
    else:
        output_lines_other = ["#genre#", version_line, '', "freetv_other,#genre#"]
    
    # 再次写入文件：分开
    output_file_cctv = "py/iptv源收集检测/assets/freetv/freetv_output_cctv.txt"
    output_file_ws = "py/iptv源收集检测/assets/freetv/freetv_output_ws.txt"
    output_file_other = "py/iptv源收集检测/assets/freetv/freetv_output_other.txt"
    
    try:
        with open(output_file_cctv, 'w', encoding='utf-8') as f:
            for line in output_lines_cctv:
                f.write(line + '\n')
        print(f"已保存CCTV频道到文件: {output_file_cctv}，共 {len(freetv_cctv_lines)} 个频道")
    
        with open(output_file_ws, 'w', encoding='utf-8') as f:
            for line in output_lines_ws:
                f.write(line + '\n')
        print(f"已保存卫视频道到文件: {output_file_ws}，共 {len(freetv_ws_lines)} 个频道")
        
        with open(output_file_other, 'w', encoding='utf-8') as f:
            for line in output_lines_other:
                f.write(line + '\n')
        print(f"已保存其他频道到文件: {output_file_other}，共 {len(freetv_other_lines)} 个频道")
    
    except Exception as e:
        print(f"保存文件时发生错误：{e}")
    
    print("\n" + "=" * 100)
    print("=== 处理完成 ===")
    print(f"总计获取频道: {len(freetv_lines)}")
    print(f"通过测速的频道: {len(fast_channels)}")
    print(f"CCTV频道: {len(freetv_cctv_lines)}")
    print(f"卫视频道: {len(freetv_ws_lines)}")
    print(f"其他频道: {len(freetv_other_lines)}")
    print("=" * 100)


if __name__ == "__main__":
    main()
