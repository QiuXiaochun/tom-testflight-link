#!/usr/bin/python
import asyncio
import aiohttp
import re
import random
import os
import requests
from utils import TODAY, renew_readme, load_links, save_links

def load_env_from_file():
    """从 .env 文件加载环境变量"""
    env_file = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_file):
        print(f"[info] 找到 .env 文件: {env_file}")
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key] = value
                        print(f"[info] 加载环境变量: {key}={value[:20] if value else 'None'}...")
        print("[info] .env 文件加载完成")
    else:
        print(f"[warn] 未找到 .env 文件: {env_file}")

# 加载 .env 文件
load_env_from_file()

BASE_URL = "https://testflight.apple.com/"
FULL_PATTERN = re.compile(r"版本的测试员已满|This beta is full")
NO_PATTERN = re.compile(r"版本目前不接受任何新测试员|This beta isn't accepting any new testers right now")

def send_notification(app_name, link_key, old_status, new_status):
    """发送通知到飞书"""
    webhook = os.environ.get('NOTIFICATION_WEBHOOK')
    print(f"[debug] webhook = {webhook[:50] if webhook else 'None'}")  # 调试用，只打印前50字符
    if not webhook:
        print("[warn] NOTIFICATION_WEBHOOK not set, skipping notification")
        return
    
    # 只通知失效的情况 (Y -> N, Y -> F, Y -> D)
    # if old_status != 'Y':
    #     return
    if new_status not in ['N', 'F', 'D']:
        return
    
    # 状态映射
    status_names = {'N': '不接受新测试员', 'F': '测试员已满', 'D': '链接已删除'}
    status_name = status_names.get(new_status, new_status)
    
    link = f"https://testflight.apple.com/join/{link_key}"
    
    # 飞书消息格式
    message = {
        "msg_type": "text",
        "content": {
            "text": f"⚠️ TestFlight 监控提醒\n\n应用：{app_name}\n状态：{old_status} → {status_name}\n链接：{link}"
        }
    }
    
    try:
        response = requests.post(webhook, json=message, timeout=10)
        if response.status_code == 200:
            print(f"[info] 通知已发送: {app_name} {old_status}→{new_status}")
        else:
            print(f"[warn] 通知发送失败: {response.status_code}")
    except Exception as e:
        print(f"[warn] 通知发送异常: {e}")

async def check_status(session, key, current_status, app_name=None, retry=5):
    """获取应用状态"""
    for i in range(retry):
        try:
            ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            async with session.get(f'/join/{key}', headers={'User-Agent': ua}) as resp:
                if resp.status == 404:
                    print(f"[info] {key} - 404 Deleted")
                    return (key, 'D')

                resp.raise_for_status()
                resp_html = await resp.text()

                if NO_PATTERN.search(resp_html):
                    return (key, 'N')
                elif FULL_PATTERN.search(resp_html):
                    return (key, 'F')
                elif "TestFlight" in resp_html:
                    return (key, 'Y')
                else:
                    print(f"[warn] {key} - Unexpected HTML content")
                    return (key, current_status)
        except Exception as e:
            print(f"[warn] {key} - {e}, retry {i+1}/{retry}")
            await asyncio.sleep(i + random.random())

    print(f"[error] Failed to get status for {key} after {retry} retries")
    return (key, current_status)

async def update_all_links(links_data):
    """更新所有链接的状态"""
    print(f"[info] Updating all links...")
    all_links = links_data.get("_links", {})
    links = list(all_links.keys())

    if not links:
        print("[warn] No links found")
        return

    conn_config = aiohttp.TCPConnector(limit=5, limit_per_host=2)
    async with aiohttp.ClientSession(base_url=BASE_URL, connector=conn_config) as session:
        tasks = [
            check_status(session, link, all_links[link].get('status', 'N'), all_links[link].get('app_name'))
            for link in links
        ]
        results = await asyncio.gather(*tasks)

    updated_count = 0

    for link, status in results:
        if link not in all_links:
            continue

        link_info = all_links[link]
        old_status = link_info.get('status')

        # 只要是不可用状态（N/F/D）就发送通知
        if status in ['N', 'F', 'D']:
           send_notification(link_info.get('app_name'), link, old_status, status)
           # 继续更新状态
           link_info['status'] = status
           link_info['last_modify'] = TODAY
           updated_count += 1
        elif old_status != status:
            # 状态变化时发送通知
            send_notification(link_info.get('app_name'), link, old_status, status)
            link_info['status'] = status
            link_info['last_modify'] = TODAY
            updated_count += 1

    print(f"[info] Status updated: {updated_count}")

async def main():
    links_data = load_links()
    await update_all_links(links_data)
    save_links(links_data)
    renew_readme()

if __name__ == "__main__":
    asyncio.run(main())
