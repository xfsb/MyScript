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

os.environ['PYTHONUNBUFFERED'] = '1'
list_file = f"listfile.txt"

OUTPUT_DIR = r"C:\Program Files (x86)\Kingsoft\WPS Office\Python\uploads"
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
            }, 1500);
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

        success = 0
        failed = 0
        skipped = 0

        with open(list_file, "r", encoding="utf-8") as f:
            for list_count, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                list_parts = line.split('===', 1)
                if len(list_parts) == 2:
                    filename = list_parts[0]
                    url = list_parts[1]
                    
                    name_parts = filename.split(' ', 1)
                    if len(name_parts) == 2:
                        dir_name = name_parts[0]
                    else:
                        dir_name = ''

                    pdf_dir = os.path.join(OUTPUT_DIR, dir_name) if dir_name else OUTPUT_DIR
                    os.makedirs(pdf_dir, exist_ok=True)
                    pdf_path = os.path.join(pdf_dir, f"{filename}.pdf")
                    #pdf_path = os.path.join(OUTPUT_DIR, f"{filename}.pdf")

                    if os.path.exists(pdf_path):
                        #print(f"  SKIP: already exists")
                        print(f"SKIP: already exists   {list_count:03d}：{pdf_path}")
                        skipped += 1
                        continue

                    try:
                        resp = await page.goto(url, wait_until="networkidle", timeout=4*30000)
                        if resp and resp.status >= 400:
                            print(f"{list_count:03d}：{pdf_path}     HTTP {resp.status}, skip")
                            #print(f"  HTTP {resp.status}, skip")
                            failed += 1
                            continue
                        
                        element = page.get_by_role("link", name="满18岁，请点此进入")
                        count = await element.count()
                        if count > 0:
                            await element.click()
                            await page.wait_for_timeout(4*30000)

                        await preload_and_reset(page)

                        attachments = await page.evaluate(r'''() => {
                            const links = document.querySelectorAll('a[href$=".jpg"]');
                            return Array.from(links).filter(a => a.textContent.includes('下载附件')).map(a => a.href);
                        }''')

                        img_success = 1
                        if attachments:
                            images = []
                            img_count = 0
                            for img_url in attachments:
                                img_count += 1
                                for attempt in range(5):
                                    try:
                                        img_path = os.path.join(TMP_DIR, f"{img_count:03d}.jpg")
                                        await screenshot_one(page, img_url, img_path)

                                        img_size = os.path.getsize(img_path)
                                        if img_size < 1024:
                                            raise ValueError(f"文件过小 ({img_size} bytes < 1024)")

                                        break
                                    except Exception as e:
                                        if attempt < 4:
                                            await page.reload(wait_until="domcontentloaded")
                                            await page.wait_for_timeout(2000)
                                            await preload_and_reset(page)
                                        else:
                                            #print(f"  {filename}下载失败: 第{img_count}张 -> {e}")
                                            print(f"{list_count:03d}：{pdf_path}   下载失败")
                                            print(f"  FAILED: {e}")
                                            failed += 1
                                            img_success = 0
                                if img_success == 0:
                                    break
                        
                        if img_success == 0:
                            continue

                        gen = image_generator(img_count)
                        # 第一张作为 PDF 基础
                        first = next(gen)
                        first.save(
                            pdf_path,
                            save_all=True,
                            append_images=gen,   # 把生成器直接传给 append_images
                            resolution=150
                        )
                        first.close()
                        #print(f" 图片下载：{pdf_path} (共{len(attachments)}张，保存{img_count} 张)")
                        print(f"保存成功   {list_count:03d}：{pdf_path}")
                        success += 1
                        
                        for i in range(1, img_count+1):
                            path = os.path.join(TMP_DIR, f"{i:03d}.jpg")
                            os.remove(path)
                                            
                    except Exception as e:
                        print(f"下载失败   {list_count:03d}：{pdf_path}")
                        print(f"  FAILED: {e}")
                        failed += 1
   
                    #break
                    await page.wait_for_timeout(1*20000)
                else:
                    print(f"⚠️ 警告：第 {list_count+1} 行格式不正确，已跳过 -> {line}")                

        await browser.close()

        print()
        print("=" * 60)
        print(f"Done! Success: {success}, Failed: {failed}, Skipped: {skipped}, Total: {list_count+1}")
        print("=" * 60)

asyncio.run(main())
