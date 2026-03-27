#!/usr/bin/python
import os
import asyncio
import aiohttp
import re
import random
import requests
from datetime import datetime
from utils import TODAY, renew_readme, load_links, save_links

BASE_URL = "https://testflight.apple.com/"
FULL_PATTERN = re.compile(r"版本的测试员已满|This beta is full")
NO_PATTERN = re.compile(r"版本目前不接受任何新测试员|This beta isn't accepting any new testers right now")

# ========== 加载环境变量 ==========
def load_env_from_file():
    env_file = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
        print("[info] Loaded .env file")

load_env_from_file()

# ========== 通知功能 ==========
def send_notification(app_name, link_key, message_type, days_left=None):
    """发送通知到飞书"""
    webhook = os.environ.get('NOTIFICATION_WEBHOOK')
    if not webhook:
        return
    
    link = f"https://testflight.apple.com/join/{link_key}"
    
    if message_type == "expiry":
        text = f"⏰ TestFlight 即将过期\n\n应用：{app_name}\n剩余：{days_left} 天\n链接：{link}"
    elif message_type == "status_change":
        text = f"⚠️ TestFlight 状态变更\n\n应用：{app_name}\n链接：{link}"
    else:
        return
    
    try:
        requests.post(webhook, json={"msg_type": "text", "content": {"text": text}}, timeout=10)
        print(f"[info] 通知已发送: {app_name}")
    except Exception as e:
        print(f"[warn] 通知失败: {e}")

# ========== TestFlight 状态检查 ==========
async def check_status(session, key, current_status, retry=5):
    for i in range(retry):
        try:
            ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            async with session.get(f'/join/{key}', headers={'User-Agent': ua}) as resp:
                if resp.status == 404:
                    return (key, 'D')
                resp_html = await resp.text()
                if NO_PATTERN.search(resp_html):
                    return (key, 'N')
                elif FULL_PATTERN.search(resp_html):
                    return (key, 'F')
                elif "TestFlight" in resp_html:
                    return (key, 'Y')
                return (key, current_status)
        except:
            await asyncio.sleep(i + random.random())
    return (key, current_status)

async def update_all_links(links_data):
    all_links = links_data.get("_links", {})
    links = list(all_links.keys())
    if not links:
        return

    conn_config = aiohttp.TCPConnector(limit=5, limit_per_host=2)
    async with aiohttp.ClientSession(base_url=BASE_URL, connector=conn_config) as session:
        tasks = [check_status(session, link, all_links[link].get('status', 'N')) for link in links]
        results = await asyncio.gather(*tasks)

    today = TODAY
    updated = 0

    for link, status in results:
        if link not in all_links:
            continue

        info = all_links[link]
        old = info.get('status')
        
        # 天数递减（仅当状态为 Y 且今天未减过）
        if status == 'Y':
            last = info.get('last_check', '')
            days = info.get('expiry_days', 90)
            
            if last != today and days > 0:
                days -= 1
                info['expiry_days'] = days
                info['last_check'] = today
                print(f"[info] {info['app_name']} 剩余 {days} 天")
                
                # 提前 10 天预警
                if days <= 10:
                    send_notification(info['app_name'], link, "expiry", days)
        
        # 状态变化处理
        if old != status:
            info['status'] = status
            info['last_modify'] = today
            updated += 1
            
            # 失效时通知
            if status in ['N', 'F', 'D']:
                send_notification(info['app_name'], link, "status_change")
            # 恢复时重置天数
            elif status == 'Y':
                info['expiry_days'] = 90
                info['last_check'] = today
                print(f"[info] {info['app_name']} 恢复，重置为 90 天")

    print(f"[info] 状态更新: {updated}")

async def main():
    links_data = load_links()
    await update_all_links(links_data)
    save_links(links_data)
    renew_readme()

if __name__ == "__main__":
    asyncio.run(main())
