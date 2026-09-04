import asyncio
import re
import os
import json
from playwright.async_api import async_playwright
import urllib.request
from PIL import Image
import io
import time
import sys
import datetime

if len(sys.argv) < 2:
    print("用法: python saven.py <页码>")
    sys.exit(1)

os.environ['PYTHONUNBUFFERED'] = '1'
page_no = sys.argv[1]
FORUM_URL = f"https://vcsss.869o4.com//forum-117-{page_no}.html"
OUTPUT_DIR = r"D:\python\uploads"
TMP_DIR = os.path.join(OUTPUT_DIR, r"tmp")

def safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:150]

# 先滚完整个页面，触发所有懒加载
async def preload_and_reset(page):
    await page.evaluate(r'''() => {
        const navBar = document.getElementById('nv');
        if (navBar) {
            navBar.style.display = 'none';
        }
    }''')

    await page.evaluate('''() => {
        return new Promise(resolve => {
            const step = 800;
            const timer = setInterval(() => {
                window.scrollBy(0, step);
                if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 50) {
                    clearInterval(timer);
                    window.scrollTo(0, 0);  // 滚回顶部
                    resolve();
                }
            }, 2000);
        });
    }''')
    await page.wait_for_timeout(2*5000)

# 截图单张
async def screenshot_one(page, img_url, img_path):
    img_loca = page.locator(f'img[src="{img_url}"]')
    await img_loca.scroll_into_view_if_needed()
    await img_loca.wait_for(state="visible", timeout=10000)
    await img_loca.screenshot(path=img_path, timeout=5000)

def image_generator(img_count):
    for i in range(1, img_count+1):
        filename = f"{i:03d}.jpg"
        path = os.path.join(TMP_DIR, filename)
        if os.path.exists(path):
            yield Image.open(path).convert("RGB")
        else:
            break

async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1200, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        await page.goto(FORUM_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        await page.get_by_role("link", name="满18岁，请点此进入").click()
        await page.wait_for_timeout(5000)

        # Also try thread- format
        threads2 = await page.evaluate(r'''() => {
            const links = document.querySelectorAll('a[href*="thread-"]');
            const results = [];
            links.forEach(a => {
                const href = a.href;
                const tidMatch = href.match(/thread-(\d+)-/);
                if (tidMatch) {
                    const text = a.textContent.trim();
                    if (/^\[韩漫\]|^\【韩漫\】/.test(text)) {
                        results.push({
                            url: href,
                            title: text.replace(/\s+/g, ' ')
                        });
                    }
                }
            });
            return results;
        }''')

        # Merge and deduplicate
        seen_tids = set()
        all_threads = []
        for t in threads2:
            tid_match = re.search(r'thread=(\d+)|thread-(\d+)-', t['url'])
            if tid_match:
                tid = tid_match.group(1) or tid_match.group(2)
                if tid not in seen_tids:
                    seen_tids.add(tid)
                    all_threads.append(t)

        pdf_list = f"{int(page_no):03d}-" + datetime.datetime.now().strftime("%Y%m%d-%H%M") + ".txt"

        with open(pdf_list, "w", encoding="utf-8") as f:
            for i, thread in enumerate(all_threads):
                title = thread['title']
                url = thread['url']
                filename = safe_filename(title)

                f.write(f"{filename}==={url}\n")

asyncio.run(main())