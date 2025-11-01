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
import os

os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "weibo.settings")

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
    """
    读取网页表单参数，并在开爬前直接覆盖 SearchSpider 的类属性，
    以绕过其在类定义阶段就从 settings 取默认值的问题。
    """
    # 1) 解析表单（多行=OR；行内空格=AND）
    keywords_raw = params.get("keywords", "").strip()
    # 目标结构：List[Union[str, List[str]]]
    #   - 单词行 -> "关键词"
    #   - 多词行 -> ["词1", "词2", ...]  表示 AND
    keyword_items: list[object] = []
    if keywords_raw:
        for line in keywords_raw.splitlines():
            line = line.strip()
            if not line:
                continue
            tokens = [t for t in line.split() if t]  # 按空格切 AND
            if not tokens:
                continue
            keyword_items.append(tokens if len(tokens) > 1 else tokens[0])

    weibo_type = int(params.get("weibo_type", 0))
    contain_type = int(params.get("contain_type", 0))

    region_raw = params.get("region", "全部").strip()
    region_list = [r.strip() for r in region_raw.split(",") if r.strip()] or ["全部"]

    start_date = params.get("start_date") or "2025-10-01"
    end_date   = params.get("end_date")   or "2025-10-28"

    # 2) 导入工具并做和原 spider 相同的转换
    from weibo.utils import util
    from weibo.spiders.search import SearchSpider  # 放到函数里导入，确保拿到类本体

    # 2.1 话题 #...# 转 %23...%23（逐 token 转换）
    def conv_token(tok: str) -> str:
        tok = tok.strip()
        if len(tok) > 2 and tok[0] == '#' and tok[-1] == '#':
            return '%23' + tok[1:-1] + '%23'
        return tok

    kw_conv: list[object] = []
    for item in keyword_items:
        if isinstance(item, list):
            kw_conv.append([conv_token(t) for t in item])
        else:
            kw_conv.append(conv_token(str(item)))

    weibo_type_conv   = util.convert_weibo_type(weibo_type)
    contain_type_conv = util.convert_contain_type(contain_type)
    regions_conv      = util.get_regions(region_list) if not (len(region_list)==1 and region_list[0]=="全部") else {}

    # 3) 覆盖 SearchSpider 的类属性 + settings（两处都写，最大化兼容它的判断逻辑）
    if kw_conv:  # 用户真的填了关键词才覆盖，否则保持原默认
        SearchSpider.keyword_list = kw_conv
        try:
            # 有的逻辑会直接从 settings 里读 KEYWORD_LIST
            SearchSpider.settings.set("KEYWORD_LIST", kw_conv)
        except Exception:
            pass

    SearchSpider.weibo_type   = weibo_type_conv
    SearchSpider.contain_type = contain_type_conv
    SearchSpider.start_date   = start_date
    SearchSpider.end_date     = end_date

    if regions_conv:
        SearchSpider.regions = regions_conv
        try:
            # start_requests 里可能用 self.settings.get('REGION') 来判分支
            SearchSpider.settings.set("REGION", region_list)
        except Exception:
            pass


    # 4) 启动 Scrapy（不再依赖额外拼 settings；类属性已覆盖）
    process = CrawlerProcess(get_project_settings())
    process.crawl(SearchSpider)
    process.start()

    # 5) 爬虫结束后尝试打开结果文件/目录
    try:
        from pathlib import Path
        results_base = Path.cwd() / "结果文件"
        opened = False
        if results_base.exists() and results_base.is_dir():
            # 尝试优先打开“用户本次第一个关键词”的目录；否则退化为第一个目录
            prefer_name = None
            if kw_conv:
                # 将 %23...%23 还原为 #...# 来匹配目录名（如果你的保存目录名就是原始关键词，可以直接用原关键词）
                def restore_hashtag(s: str) -> str:
                    if s.startswith("%23") and s.endswith("%23"):
                        return f"#{s[3:-3]}#"
                    return s
                prefer_name = restore_hashtag(kw_conv[0])

            target_dir = None
            for d in results_base.iterdir():
                if d.is_dir() and (prefer_name is None or prefer_name in d.name):
                    target_dir = d
                    break
            if not target_dir:
                cand = [d for d in results_base.iterdir() if d.is_dir()]
                if cand:
                    target_dir = cand[0]

            if target_dir:
                csv_files = list(target_dir.glob("*.csv"))
                target = csv_files[0] if csv_files else target_dir
                try:
                    webbrowser.open_new(f"file://{target.resolve()}")
                    opened = True
                except Exception:
                    opened = False
        if not opened:
            print("未找到结果文件，请检查爬虫输出目录。")
    finally:
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