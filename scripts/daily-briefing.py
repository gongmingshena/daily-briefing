#!/usr/bin/env python3
"""
每日信息简报 — Daily Briefing
======================
从 RSS 源采集全球财经、中国时事、科技AI、健康民生新闻，
用魔搭社区 (ModelScope) 免费 API 整理摘要，生成 Markdown 简报，
通过 Server酱 推送到微信。

部署方式：
  A) 本地 Windows 定时任务 (schtasks) — 每天 9:20，需管理员权限
     scripts/ps1/setup-schtasks.ps1
  B) GitHub Actions — 备份方案，每天 UTC 1:20 (即北京时间 9:20)

用法：
    set PYTHONIOENCODING=utf-8
    set MODELSCOPE_TOKEN="ms-xxx"   # 魔搭 SDK Token（必填）
    set SERVERCHAN_KEY="SCTxxx"     # Server酱 SendKey（有默认值）
    python daily-briefing.py

魔搭免费 API 说明（每天 2000 次免费）：
    - Endpoint: https://api-inference.modelscope.cn/v1/chat/completions
    - Token 获取: https://modelscope.cn/my/myaccesstoken
    - 模型列表: https://www.modelscope.cn/models（筛选"API 推理"）

依赖（pip install）：
    requests           # HTTP 请求
    beautifulsoup4     # HTML 解析
    lxml               # XML/RSS 解析
"""

import os
import sys
import re
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("❌ 缺少依赖：requests，请运行 pip install requests")
    sys.exit(1)

# ============================================================
# 配置（优先读环境变量，其次用默认值）
# ============================================================

# ---- 魔搭 (ModelScope) ----
# Token 获取: https://modelscope.cn/my/myaccesstoken
# 模型推荐（免费）: Qwen/Qwen3-32B, deepseek-ai/DeepSeek-V3.1, Qwen/Qwen3-Coder-30B-A3B
MODELSCOPE_TOKEN = os.environ.get("MODELSCOPE_TOKEN", "")
MODELSCOPE_BASE_URL = os.environ.get(
    "MODELSCOPE_BASE_URL",
    "https://api-inference.modelscope.cn/v1"
)
MODELSCOPE_MODEL = os.environ.get(
    "MODELSCOPE_MODEL",
    "Qwen/Qwen3-8B"  # 免费模型，流式模式已测试通过
)

if not MODELSCOPE_TOKEN:
    print("❌ 请设置 MODELSCOPE_TOKEN 环境变量")
    print("   1. 打开 https://modelscope.cn/my/myaccesstoken")
    print("   2. 创建 SDK Token（格式: ms-xxx）")
    print("   3. 执行: export MODELSCOPE_TOKEN=\"ms-你的token\"")
    sys.exit(1)

# ---- Server酱 ----
SERVERCHAN_KEY = os.environ.get(
    "SERVERCHAN_KEY",
    "SCT352036ToJIzPCe6DmfvV0oIbAMIYiZw"
)

# ---- 输出目录 ----
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "output", "每日简报"
))

# ---- 存档目录（仓库根目录下的 briefings/） ----
SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
REPO_ROOT = SCRIPT_DIR.parent
BRIEFING_ARCHIVE_DIR = os.environ.get(
    "BRIEFING_ARCHIVE_DIR",
    str(REPO_ROOT / "briefings")
)

# ---- 简报版本 ----
BRIEFING_VERSION = "v2-modelscope"

# ---- 时区 ----
TZ = timezone(timedelta(hours=8))  # 北京时间

# ============================================================
# RSS 源配置（在魔搭云上可直连海外站点）
# ============================================================

RSS_FEEDS = {
    "global_finance": [
        {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
        {"name": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
        {"name": "BBC Tech", "url": "https://feeds.bbci.co.uk/news/technology/rss.xml"},
    ],
    "china_news": [
        {"name": "China Daily", "url": "https://www.chinadaily.com.cn/rss/world_rss.xml"},
    ],
    "tech": [
        {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
        {"name": "HN Frontpage", "url": "https://hnrss.org/frontpage?count=15"},
        {"name": "arXiv AI", "url": "http://export.arxiv.org/rss/cs.AI"},
    ],
    "china_tech": [
        {"name": "36Kr", "url": "https://36kr.com/feed"},
    ],
}

# ============================================================
# 工具函数
# ============================================================

def log(msg: str):
    now = datetime.now(TZ).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


_HTTP_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        _HTTP_SESSION = requests.Session()
        _HTTP_SESSION.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        })
        proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        if proxy:
            _HTTP_SESSION.proxies = {"http": proxy, "https": proxy}
            log(f"🔌 使用代理: {proxy}")
    return _HTTP_SESSION


def fetch_rss(url: str, timeout: int = 15) -> Optional[list]:
    """获取 RSS feed，返回条目列表"""
    try:
        session = _get_session()
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()

        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)

        entries = []
        # RSS 2.0
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            desc = item.findtext("description", "")
            entries.append({
                "title": title.strip(),
                "link": link.strip(),
                "summary": re.sub(r"<[^>]+>", "", desc).strip()[:300],
            })

        # Atom
        if not entries:
            ns = "{http://www.w3.org/2005/Atom}"
            for entry in root.iter(f"{ns}entry"):
                title = entry.findtext(f"{ns}title", "")
                link_el = entry.find(f"{ns}link")
                link = link_el.get("href", "") if link_el is not None else ""
                summary = entry.findtext(f"{ns}summary", "")
                entries.append({
                    "title": title.strip(),
                    "link": link.strip(),
                    "summary": re.sub(r"<[^>]+>", "", summary).strip()[:300],
                })

        return entries[:10]

    except Exception as e:
        log(f"⚠️  RSS 获取失败 {url[:50]}: {e}")
        return []


def call_llm(prompt: str, system: str = "你是一个专业的财经新闻编辑。") -> Optional[str]:
    """调用魔搭 ModelScope 免费 API (OpenAI 兼容接口)

    注意：魔搭免费 API 的 /chat/completions 仅在流式模式 (stream=True) 下
    返回有效结果；非流式模式会返回 choices: null。这里使用流式请求并拼接。
    """
    url = f"{MODELSCOPE_BASE_URL}/chat/completions"
    session = _get_session()
    body = {
        "model": MODELSCOPE_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
        "stream": True,
    }

    try:
        resp = session.post(
            url,
            headers={
                "Authorization": f"Bearer {MODELSCOPE_TOKEN}",
                "Content-Type": "application/json",
            },
            json=body,
            stream=True,
            timeout=300,
        )
        resp.raise_for_status()

        # 拼接流式 SSE 数据
        # BUGFIX 2026-06-14: 必须用 decode_unicode=False，手动 decode('utf-8')，
        # 否则 Windows 上 decode_unicode=True 会用系统编码(GBK)解析，导致中文乱码
        collected_content = ""
        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            line = raw_line.decode("utf-8")
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    # Qwen3 模型会输出 reasoning_content (思考过程) 和 content (最终回答)
                    # 我们只需要 content
                    content_piece = delta.get("content", "")
                    if content_piece:
                        collected_content += content_piece
                except json.JSONDecodeError:
                    continue

        if not collected_content:
            log("⚠️  流式响应完成但未收集到有效内容")
            return None

        # 清理 LLM 返回内容
        # 1) 去掉 ```markdown ... ``` 代码块包裹
        collected_content = collected_content.strip()
        if collected_content.startswith("```"):
            # 去掉开头的 ``` 及语言标记
            first_newline = collected_content.find("\n")
            if first_newline > 0:
                collected_content = collected_content[first_newline + 1:]
            else:
                collected_content = collected_content[3:]
        if collected_content.endswith("```"):
            collected_content = collected_content[:-3].rstrip()

        log(f"✅ LLM 调用成功 ({MODELSCOPE_MODEL})")
        return collected_content

    except Exception as e:
        log(f"⚠️  LLM API 调用失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                log(f"   返回: {e.response.text[:500]}")
            except Exception:
                pass
        return None


def push_serverchan(title: str, content: str) -> bool:
    """通过 Server酱 推送到微信"""
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    data = {"title": title, "desp": content}

    try:
        session = _get_session()
        resp = session.post(url, data=data, timeout=30)
        result = resp.json()
        if result.get("code") == 0:
            log(f"✅ Server酱 推送成功: {title[:40]}")
            return True
        else:
            log(f"⚠️  Server酱 推送失败: {result}")
            return False
    except Exception as e:
        log(f"⚠️  Server酱 请求异常: {e}")
        return False


# ============================================================
# 核心逻辑
# ============================================================

def collect_news() -> dict:
    """从 RSS 源采集新闻"""
    log("📡 开始采集新闻...")
    all_news = {}

    for category, feeds in RSS_FEEDS.items():
        category_news = []
        for feed in feeds:
            entries = fetch_rss(feed["url"])
            if entries:
                log(f"  ✓ {feed['name']}: {len(entries)} 条")
                for e in entries:
                    e["source"] = feed["name"]
                category_news.extend(entries)
            else:
                log(f"  ✗ {feed['name']}: 无数据")

        # 去重
        seen = set()
        unique = []
        for item in category_news:
            key = item["title"][:50]
            if key not in seen:
                seen.add(key)
                unique.append(item)
        all_news[category] = unique[:15]

    return all_news


def generate_briefing(news_data: dict) -> Optional[str]:
    """用 AI 生成简报"""
    log("🧠 正在用 AI 生成简报...")

    sections_text = []
    section_labels = {
        "global_finance": "🌍 全球财经与国际时事",
        "china_news": "🇨🇳 中国时事动态",
        "tech": "🤖 科技与 AI",
        "china_tech": "💻 国内科技产业",
    }

    total_items = 0
    for cat, label in section_labels.items():
        items = news_data.get(cat, [])
        if items:
            section = f"## {label}\n\n"
            for i, item in enumerate(items[:8], 1):
                section += f"{i}. **{item['title']}**\n"
                if item.get("summary"):
                    section += f"   {item['summary'][:200]}\n"
                section += f"   [{item.get('source','')}]({item['link']})\n\n"
            sections_text.append(section)
            total_items += len(items[:8])

    if total_items == 0:
        log("⚠️  没有采集到任何新闻")
        return None

    raw_material = "\n".join(sections_text)

    system_prompt = """你是一个专业的财经新闻编辑，负责将原始新闻素材整理成结构清晰的每日简报。

要求：
1. 从中精选最重要的新闻，每条写 1-2 句简评
2. 语言通俗易懂，适合 35-50 岁普通读者
3. 保持客观，不夸大
4. 每个分类保留 3-5 条最重要内容
5. 如果素材不足，可以根据你的知识补充相关背景（但不要编造新闻）

输出格式：纯 Markdown，不需要额外解释。"""

    user_prompt = f"""请根据以下新闻素材，整理一份 {datetime.now(TZ).strftime('%Y年%m月%d日')} 的每日信息简报。

素材：
{raw_material}

请按以下结构输出：
1. 全球财经头条（3-5条）
2. 中国时事动态（3-5条）
3. 财经与商业（3-5条）
4. 科技与AI（3-5条）
5. 健康与民生（2-3条）
6. 简要评述（200字以内）

每条新闻请附上来源链接（如有）。"""

    content = call_llm(user_prompt, system_prompt)
    return content


def save_and_push(content: str) -> str:
    """保存简报并推送"""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now(TZ).weekday()]

    header = f"""# 每日简报 — {today}（{weekday_cn}）

> 生成时间: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')} | 模型: {MODELSCOPE_MODEL}

---
"""
    full_content = header + "\n" + content + f"\n\n---\n\n*由 Daily Briefing {BRIEFING_VERSION} 自动生成*"

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"每日简报_{today}.md"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_content)
    log(f"💾 简报已保存: {filepath}")

    # 存档到仓库（简版文件名 YYYY-MM-DD.md）
    os.makedirs(BRIEFING_ARCHIVE_DIR, exist_ok=True)
    archive_path = os.path.join(BRIEFING_ARCHIVE_DIR, f"{today}.md")
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(full_content)
    log(f"📚 简报已存档: {archive_path}")

    # 推送（截断到 30KB 以内）
    title = f"📰 每日简报 {today}"
    push_content = full_content
    if len(push_content.encode("utf-8")) > 30000:
        push_content = push_content[:10000] + "\n\n...（内容过长已截断，完整版见仓库 briefings/）"
    push_serverchan(title, push_content)

    return filepath


# ============================================================
# 主入口
# ============================================================

def main():
    log("=" * 50)
    log(f"📰 Daily Briefing — {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}")
    log(f"🤖 模型: {MODELSCOPE_MODEL}")
    log(f"📤 Server酱: {'✅ 已配置' if SERVERCHAN_KEY else '⚠️  未配置'}")
    log(f"📂 输出目录: {OUTPUT_DIR}")
    log("=" * 50)

    # 防重复检测：如果今天简报已在仓库存档，跳过执行
    today_str = datetime.now(TZ).strftime("%Y-%m-%d")
    archive_check_path = os.path.join(BRIEFING_ARCHIVE_DIR, f"{today_str}.md")
    if os.path.exists(archive_check_path):
        log(f"⏭️  简报已存在（{archive_check_path}），跳过执行——另一系统已生成")
        return 0

    # 采集新闻
    news_data = collect_news()

    # AI 生成简报
    content = generate_briefing(news_data)
    if not content:
        log("❌ 简报生成失败，尝试无素材直接生成...")
        # 即使没 RSS 素材，也让 AI 基于知识生成
        fallback_prompt = f"""请基于你的知识，生成一份 {datetime.now(TZ).strftime('%Y年%m月%d日')} 的每日信息简报。
今天没有采集到最新新闻素材，请用已有知识输出。

结构：
1. 全球财经头条（3-5条）
2. 中国时事动态（3-5条）
3. 财经与商业（3-5条）
4. 科技与AI（3-5条）
5. 健康与民生（2-3条）
6. 简要评述（200字以内）

注意：标注每条信息的可靠性，不确定的加上"据公开报道"等。"""
        content = call_llm(fallback_prompt)

    if not content:
        log("❌ 简报生成完全失败")
        sys.exit(1)

    # 保存 + 推送
    filepath = save_and_push(content)
    log(f"\n✅ 完成！简报: {filepath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
