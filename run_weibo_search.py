"""
Local web interface wrapper for the ``weiboSearch`` project.

This script starts a simple HTTP server on ``localhost:8080``.  When you
navigate to that address in your browser you will see a form where you can
enter the search keywords and other optional parameters.  Submitting the
form launches the existing Scrapy spider (`SearchSpider`) programmatically
with the provided settings.  Results are written to the same output
locations as the original command‐line usage (e.g., CSV files under the
``结果文件`` directory).

The goal of this wrapper is to make it easier for non‑technical users to
run the Weibo search crawler: they only need to double‑click the compiled
``.exe`` and use a web browser to specify what they want to search for.

Usage (development):
    python run_weibo_search.py

After packaging with PyInstaller (see README for instructions) the
generated executable works the same way: double‑click it and then open
``http://localhost:8080`` in a browser.
"""

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import webbrowser  # 自动打开浏览器和文件

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

try:
    # Import the spider directly from the project
    from weibo.spiders.search import SearchSpider  # type: ignore
except ImportError as e:
    raise SystemExit(
        "Unable to import the SearchSpider. Make sure this script is placed "
        "in the root of the weiboSearch project and that the `weibo` package "
        "is accessible."
    ) from e


HTML_FORM = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>微博关键词搜索</title>
    <style>
        body {font-family: sans-serif; margin: 40px;}
        label {display: block; margin-top: 1em;}
        input[type=text], input[type=date], select {
            width: 300px; padding: 5px; margin-top: 0.5em;
        }
        textarea {
            width: 300px; height: 80px; padding: 5px; margin-top: 0.5em;
        }
        button {margin-top: 1.5em; padding: 10px 20px;}
    </style>
</head>
<body>
    <h1>微博关键词搜索</h1>
    <p>在下面的表格中填写要搜索的关键词和其他参数，然后点击“开始搜索”。
       搜索将在后台执行，并将结果保存到项目的默认目录中。</p>
    <form method="post" action="/run">
        <label>关键词（可多行，每行一个或多个关键词，用空格分隔）
            <textarea name="keywords"></textarea>
        </label>
        <label>起始日期（yyyy-mm-dd）
            <input type="date" name="start_date" value="2025-10-01">
        </label>
        <label>结束日期（yyyy-mm-dd）
            <input type="date" name="end_date" value="2025-10-28">
        </label>
        <label>微博类型
            <select name="weibo_type">
                <option value="0">全部微博</option>
                <option value="1" selected>原创微博</option>
                <option value="2">热门微博</option>
                <option value="3">关注人微博</option>
                <option value="4">认证用户微博</option>
                <option value="5">媒体微博</option>
                <option value="6">观点微博</option>
            </select>
        </label>
        <label>必需包含内容
            <select name="contain_type">
                <option value="0" selected>不筛选</option>
                <option value="1">包含图片</option>
                <option value="2">包含视频</option>
                <option value="3">包含音乐</option>
                <option value="4">包含短链接</option>
            </select>
        </label>
        <label>地区（省/直辖市名称，多个请用逗号分隔；填“全部”表示不筛选）
            <input type="text" name="region" value="全部">
        </label>
        <button type="submit">开始搜索</button>
    </form>
</body>
</html>
"""


def run_spider(params: dict) -> None:
    """Run the Scrapy spider with dynamic settings derived from HTML form.

    Args:
        params: A dictionary with keys corresponding to form field names.
    """
    # Prepare dynamic settings
    keywords_raw = params.get("keywords", "").strip()
    if keywords_raw:
        # Split lines and then split by whitespace within each line
        keyword_list = []
        for line in keywords_raw.splitlines():
            line = line.strip()
            if not line:
                continue
            # If the line contains spaces, treat the entire line as one
            # keyword (Scrapy accepts space‐separated keywords for AND search)
            keyword_list.append(line)
    else:
        keyword_list = []

    # Convert numeric parameters; default to 0 if missing
    weibo_type = int(params.get("weibo_type", 0))
    contain_type = int(params.get("contain_type", 0))

    # Region: split by comma and strip whitespace
    region_raw = params.get("region", "全部").strip()
    if region_raw:
        region_list = [r.strip() for r in region_raw.split(",") if r.strip()]
    else:
        region_list = ["全部"]

    start_date = params.get("start_date") or "2025-10-01"
    end_date = params.get("end_date") or "2025-10-28"

    # Retrieve project settings and override the relevant values
    settings = get_project_settings().copy()
    if keyword_list:
        settings.set("KEYWORD_LIST", keyword_list)
    settings.set("START_DATE", start_date)
    settings.set("END_DATE", end_date)
    settings.set("WEIBO_TYPE", weibo_type)
    settings.set("CONTAIN_TYPE", contain_type)
    # If region_list contains only one element which is '全部', keep the default
    if not (len(region_list) == 1 and region_list[0] == "全部"):
        settings.set("REGION", region_list)

    # Instantiate a CrawlerProcess with the overridden settings
    process = CrawlerProcess(settings)
    process.crawl(SearchSpider)
    # 阻塞直到爬虫结束
    process.start()

    # 爬虫运行结束后尝试打开生成的结果文件，并关闭HTTP服务器
    try:
        from pathlib import Path

        results_base = Path.cwd() / "结果文件"
        opened = False
        if results_base.exists() and results_base.is_dir():
            # 找到第一个关键词目录
            keyword_dirs = [d for d in results_base.iterdir() if d.is_dir()]
            if keyword_dirs:
                first_dir = keyword_dirs[0]
                # 寻找CSV文件
                csv_files = list(first_dir.glob("*.csv"))
                target = csv_files[0] if csv_files else first_dir
                # 使用文件URI打开
                try:
                    webbrowser.open_new(f"file://{target.resolve()}")
                    opened = True
                except Exception:
                    opened = False
        if not opened:
            print("未找到结果文件，请检查爬虫输出目录。")
    finally:
        # 在控制台提示用户可以关闭浏览器页面
        print("爬取完成，您可以关闭浏览器页面了。")


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler serving a simple form and launching the spider."""

    def do_GET(self) -> None:
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_FORM.encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        if self.path == "/run":
            # 读取表单数据
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            params = urllib.parse.parse_qs(body)
            flattened = {k: v[0] for k, v in params.items()}

            # 同步运行爬虫，阻塞直到结束
            run_spider(flattened)

            # 返回爬取完成页面
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("爬取完成，请关闭此页面。".encode("utf-8"))

            # 爬虫结束后关闭HTTP服务器
            def shutdown_server():
                httpd = globals().get("HTTPD")
                if httpd:
                    httpd.shutdown()
            # 使用计时器延迟关闭，确保响应完成发送
            threading.Timer(0.5, shutdown_server).start()
        else:
            self.send_error(404, "Not Found")


def main() -> None:
    """Entry point for the web server."""
    host = "localhost"
    port = 8080
    httpd = HTTPServer((host, port), RequestHandler)
    # 将HTTP服务器对象保存到全局，便于爬虫结束时关闭
    globals()["HTTPD"] = httpd
    print(f"服务器已启动，访问 http://{host}:{port} 使用网页填写搜索条件。")
    # 自动打开网页
    url = f"http://{host}:{port}"
    try:
        webbrowser.open_new(url)
    except Exception:
        print(f"无法自动打开浏览器，请手动访问 {url}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n收到中断信号，正在关闭服务器...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()