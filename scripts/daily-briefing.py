#!/usr/bin/env python3
"""
每日信息简报 — Daily Briefing
======================
从 RSS 源采集全球财经、中国时事、科技AI、健康民生新闻，
用魔搭社区 (ModelScope) 免费 API 整理摘要，生成 Markdown 简报，
通过 Server酱 推送到微信。

运行模式（BRIEFING_MODE 环境变量）：
  global → 全球简报（world + finance + tech）
  china  → 中国简报（china + 百度热搜）
  wechat → 公众号素材筛选（77爸爸：从当天热点筛出适合普通家庭的真实素材线索，
           输出"今日最值得写 + 2-4条候选"，不编造故事，只提供角度和回忆问题）
  空/其他 → 全部源（手动测试用）

部署方式：
  A) 本地 Windows 定时任务 (schtasks) — 每天 9:20，需管理员权限
     scripts/ps1/setup-schtasks.ps1
  B) GitHub Actions — 备份方案，每天 UTC 1:20 (即北京时间 9:20)

用法：
    set PYTHONIOENCODING=utf-8
    set MODELSCOPE_TOKEN="ms-xxx"   # 魔搭 SDK Token（必填）
    set SERVERCHAN_KEY="SCTxxx"     # Server酱 SendKey（有默认值）
    set BRIEFING_MODE=wechat        # 公众号素材筛选模式
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
from urllib.parse import quote_plus
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
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "")
if not SERVERCHAN_KEY:
    print("ℹ️  未设置 SERVERCHAN_KEY，简报仅存档不推送")

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
BRIEFING_VERSION = "v4-hotsearch"

# ---- 运行模式 ----
# global → 全球简报（world + finance + tech）
# china → 中国简报（china + browser domestic news）
# wechat → 公众号素材筛选（77爸爸：从热点筛出适合普通家庭的真实素材线索）
# 空/其他 → 全部源（手动测试用）
BRIEFING_MODE = os.environ.get("BRIEFING_MODE", "").lower()

# ---- 时区 ----
TZ = timezone(timedelta(hours=8))  # 北京时间

# ============================================================
# RSS 源配置（在魔搭云上可直连海外站点）
# ============================================================

RSS_FEEDS = {
    "world": [
        {"name": "BBC", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
        {"name": "Guardian", "url": "https://www.theguardian.com/world/rss"},
        {"name": "France 24", "url": "https://www.france24.com/en/rss"},
        {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    ],
    "finance": [
        {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
        {"name": "MarketWatch", "url": "https://feeds.marketwatch.com/marketwatch/topstories"},
        {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex"},
        {"name": "FT", "url": "https://www.ft.com/rss/world"},
    ],
    "tech": [
        {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
        {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index"},
    ],
    "china": [
        {"name": "BBC中文", "url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"},
        {"name": "36Kr", "url": "https://36kr.com/feed"},
        {"name": "新华网", "url": "http://www.xinhuanet.com/politics/news_politics.xml"},
        {"name": "人民网", "url": "http://www.people.com.cn/rss/politics.xml"},
    ],
}

# ---- 根据运行模式筛选源 ----
MODE_SECTIONS = {
    "global": ["world", "finance", "tech"],
    "china": ["china"],
    "wechat": [],  # 公众号素材筛选：只用百度热搜（当天热点最可靠）
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

        # 每源取前3条
        return entries[:3]

    except Exception as e:
        log(f"⚠️  RSS 获取失败 {url[:50]}: {e}")
        return []


def fetch_baidu_hotsearch(max_items: int = 20) -> list:
    """采集百度实时热搜榜（top.baidu.com）"""
    url = "https://top.baidu.com/board?tab=realtime"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
    }
    try:
        session = _get_session()
        resp = session.get(url, headers=headers, timeout=15)
        resp.encoding = "utf-8"
        text = resp.text

        words = re.findall(r'"word":"([^"]+)"', text)
        scores = re.findall(r'"hotScore":"([^"]+)"', text)
        # 去重
        seen = set()
        results = []
        for i, w in enumerate(words):
            if w not in seen:
                seen.add(w)
                score = int(scores[i]) if i < len(scores) and scores[i].isdigit() else 0
                results.append({
                    "title": w,
                    "hotScore": score,
                    "source": "百度热搜",
                    "observed_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
                    "link": f"https://www.baidu.com/s?wd={quote_plus(w)}",
                })
            if len(results) >= max_items:
                break
        log(f"🔥 百度热搜采集完成: {len(results)} 条")
        return results
    except Exception as e:
        log(f"⚠️  百度热搜采集失败: {e}")
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
                resp_body = e.response.text[:500]
                log(f"   返回: {resp_body}")
                # Token 过期检测 (401 Unauthorized)
                if e.response.status_code == 401:
                    alert_msg = (
                        f"🚨 **ModelScope Token 过期告警**\n\n"
                        f"时间: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}\n\n"
                        f"简报任务因 token 认证失败中断。\n\n"
                        f"**修复方法:**\n"
                        f"1. 打开 https://modelscope.cn/my/myaccesstoken\n"
                        f"2. 生成新 SDK Token\n"
                        f"3. 更新到: 本地 modelscope-token.txt + GitHub Secret\n\n"
                        f"响应: {resp_body[:200]}"
                    )
                    try:
                        push_serverchan("⚠️ ModelScope Token 过期，简报停推", alert_msg)
                    except Exception:
                        pass
            except Exception:
                pass
        return None


def push_serverchan(title: str, content: str) -> bool:
    """通过 Server酱 推送到微信"""
    if not SERVERCHAN_KEY:
        log("ℹ️  未设置 SERVERCHAN_KEY，跳过推送")
        return False
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
    """从 RSS 源采集新闻（根据 BRIEFING_MODE 筛选分类）"""
    log("📡 开始采集新闻...")

    # 根据模式筛选分类
    if BRIEFING_MODE in MODE_SECTIONS:
        enabled = MODE_SECTIONS[BRIEFING_MODE]
        feeds_to_fetch = {k: v for k, v in RSS_FEEDS.items() if k in enabled}
        mode_label = {"global": "🌍 全球简报", "china": "🇨🇳 中国简报"}.get(BRIEFING_MODE, "")
        if mode_label:
            log(f"📋 模式: {mode_label}")
    else:
        feeds_to_fetch = RSS_FEEDS

    all_news = {}
    for category, feeds in feeds_to_fetch.items():
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

    # 采集百度热搜
    if BRIEFING_MODE in ("china", "wechat", "") or BRIEFING_MODE not in MODE_SECTIONS:
        hotsearch = fetch_baidu_hotsearch(20)
        if hotsearch:
            all_news["hotsearch"] = hotsearch

    return all_news


def generate_briefing(news_data: dict) -> Optional[str]:
    """用 AI 生成简报"""
    log("🧠 正在用 AI 生成简报...")

    sections_text = []
    all_labels = {
        "world": "🌍 全球要闻",
        "finance": "💰 财经",
        "tech": "💻 科技",
        "china": "🇨🇳 中国",
    }
    # 只输出当前模式包含的分类
    if BRIEFING_MODE in MODE_SECTIONS:
        section_labels = {k: v for k, v in all_labels.items() if k in MODE_SECTIONS[BRIEFING_MODE]}
    else:
        section_labels = all_labels

    total_items = 0

    # 先输出热搜（如果有）
    hotsearch = news_data.get("hotsearch", [])
    if hotsearch:
        hs_section = "## 🔥 今日热搜 TOP10\n\n"
        for i, item in enumerate(hotsearch[:10], 1):
            score_display = f"(热度: {item['hotScore']:,})" if item.get("hotScore") else ""
            hs_section += f"{i}. **{item['title']}** {score_display}\n"
        hs_section += "\n"
        sections_text.insert(0, hs_section)  # 热搜放最前面
        total_items += len(hotsearch[:10])

    for cat, label in section_labels.items():
        items = news_data.get(cat, [])
        if items:
            section = f"## {label}\n\n"
            for i, item in enumerate(items, 1):
                section += f"{i}. **{item['title']}**\n"
                if item.get("summary"):
                    section += f"   {item['summary'][:200]}\n"
                section += f"   [{item.get('source','')}]({item['link']})\n\n"
            sections_text.append(section)
            total_items += len(items)

    if total_items == 0:
        log("⚠️  没有采集到任何新闻")
        return None

    raw_material = "\n".join(sections_text)

    system_prompt = """你是一个专业的新闻编辑，负责整合热搜数据与权威媒体新闻，生成信息密度高的每日简报。

写作要求：
1. 【热搜板块】列出今日最热话题，加一句话说明为什么大家都在讨论
2. 【时政要闻】选择最重要的政策/国家大事，每条写1-2句解读
3. 【民生热点】聚焦普通人关心的消费、健康、教育、住房等话题
4. 【国际/财经/科技】根据素材适量补充
5. 每条新闻写1-2句点评，让读者知道"这件事跟普通人有啥关系"
6. 语言简短干脆，适合手机上快速阅读
7. 只写真实素材中有依据的事，不确定的不要写

输出格式：纯 Markdown，不需要额外解释。"""

    if BRIEFING_MODE == "global":
        prompt_structure = """1. 🔥 全球热搜（3-5条）
2. 🌍 全球要闻（各平台头版观点，4-6条）
3. 💰 财经（来自不同财经媒体，3-5条）
4. 💻 科技（2-3条）
5. 📝 简要评述（200字以内，综合全球趋势）"""
        briefing_type = "全球简报"
    elif BRIEFING_MODE == "china":
        prompt_structure = """1. 🔥 今日热搜 TOP10（直接引用热搜数据，每条加一句热度解读）
2. 📰 时政要闻（3-5条，来自权威媒体）
3. 🏠 民生与社会（3-5条，普通人关心的）
4. 💡 一句话评述（100字以内，今天的核心信号）"""
        briefing_type = "中国简报"
    else:
        prompt_structure = """1. 🔥 今日热搜（5-8条）
2. 🌍 全球要闻（各平台头版观点，4-6条）
3. 💰 财经（来自不同财经媒体，3-5条）
4. 💻 科技（2-3条）
5. 🇨🇳 中国（2-3条）
6. 📝 简要评述（200字以内，综合各平台趋势）"""
        briefing_type = "每日简报"

    user_prompt = f"""请根据以下来自不同平台的新闻素材，整理一份 {datetime.now(TZ).strftime('%Y年%m月%d日')} 的{briefing_type}。

素材（包含百度热搜 + 多个新闻源，每条都标注了来源）：
{raw_material}

请严格按以下结构输出，每条新闻附上来源：
{prompt_structure}

重点：热搜部分直接罗列今日真实热搜话题，不要编造。"""

    content = call_llm(user_prompt, system_prompt)
    return content


def generate_wechat_material_briefing(news_data: dict) -> Optional[str]:
    """用 AI 从当天热点中筛选适合"77爸爸"公众号的真实素材线索。

    核心原则：热点负责提供"今天为什么值得谈"，AI 负责找到
    "普通家庭为什么会停顿三秒"，真实故事由作者自己提供。
    """
    log("🧠 正在用 AI 筛选公众号素材...")

    # 组装素材：只用百度热搜（当天热点最可靠）
    sections_text = []
    hotsearch = news_data.get("hotsearch", [])
    if hotsearch:
        hs = "## 🔥 今日热搜 TOP20\n\n"
        for i, item in enumerate(hotsearch[:20], 1):
            score_display = f"(热度: {item['hotScore']:,})" if item.get("hotScore") else ""
            hs += (
                f"{i}. **{item['title']}** {score_display}\n"
                f"   来源：{item.get('source', '百度热搜')}｜采集时间：{item.get('observed_at', '')}｜"
                f"[检索链接]({item.get('link', '')})\n"
            )
        hs += "\n"
        sections_text.append(hs)

    if not sections_text:
        log("⚠️  没有采集到任何素材")
        return None

    raw_material = "\n".join(sections_text)

    system_prompt = """你是一个公众号"77爸爸"的素材筛选编辑。

77爸爸是一个40岁上下的普通中年男人，做过15年设计，现在做家庭风险和保险规划。公众号记录普通家庭的安全感，研究普通家庭怎么面对风险。定位语：记录普通家庭的安全感，也研究普通家庭怎么面对风险。

你的任务：从当天百度热搜词条中，筛选出适合77爸爸公众号的真实素材线索。不要编造故事、人物对话和作者经历，而是通过问题提醒作者回忆自己的真实生活素材。

证据边界：输入只证明“该词条在采集时出现在百度热搜”，不证明词条背后的完整事实。除非输入明确提供，否则不得补写发布机构、人物动机、法律规则、医学结论、心理判断、研究结论、事件经过或因果关系。来源只能写“百度热搜”，时间只能使用输入中的采集时间，链接只能使用输入中的检索链接。信息不足时必须明确写“仅有热搜词条，事件细节待核验”。

事实与判断必须分栏：只有“公开线索”属于事实；“一句话信号”“文章切口”“推荐理由”都属于编辑判断，必须以“编辑判断：”开头，并使用“可能、值得追问、可以观察”等非确定表达。不得把编辑判断写成法律、医学、心理或因果事实。

筛选优先寻找：
- 身体出现的小变化，推翻过去的认知
- 父母老去、孩子长大带来的家庭责任变化
- 裁员、收入变化、行业下行带来的安全感问题
- 普通家庭明知道该准备，却一直拖着没做的事情
- 一个具体动作、数字或生活细节，能够形成电影画面

主动排除：
- 单纯的AI产品发布和技术参数
- 与普通家庭没有关系的行业融资新闻
- 只有热度、没有可靠来源的信息
- 需要虚构作者经历才能成立的选题
- 借疾病、事故或悲剧制造焦虑的内容
- 最后只能硬转保险产品的选题

核心原则：热点负责提供"今天为什么值得谈"，你负责找到"普通家庭为什么会停顿三秒"，真实故事由作者自己提供。"""

    user_prompt = f"""请根据以下当天百度热搜，筛选出适合"77爸爸"公众号的素材线索。

素材（每条都标注了热度）：
{raw_material}

请严格按以下格式输出，每天推荐3-5条，并明确选出最值得写的一条。候选不得与“今日最值得写”重复：

### 今日最值得写
**公开线索：**只复述热搜词条，并附“百度热搜”、采集时间和检索链接；不得把标题扩写成已核实事实。
**一句话信号：**以“编辑判断：”开头，用可能性或问题表达这条线索为什么值得普通家庭停顿三秒。
**适合人群：**40岁上下、有父母和孩子的家庭。
**可连接方向：**身体／家庭／职场／金钱／养老。
**回忆问题：**"你最近有没有遇到类似的一刻？"
**文章切口：**以“编辑判断：”开头，只提供角度，不替你编故事。
**素材等级：**S级母题／B级可复用／A级时效热点。
**推荐理由：**以“编辑判断：”开头，说明为什么它适合77爸爸，而不只是因为它热。

### 另外2—4条候选
每条只保留：
- 公开线索（只复述词条；标注百度热搜、采集时间和检索链接）
- 一句话信号（以“编辑判断：”开头，只写可能性或值得追问的问题）
- 与普通家庭的关系
- 可写角度（以“编辑判断：”开头）
- 来源链接（必须原样输出输入中的 Markdown 检索链接）
- 风险提示

只写输入中有依据的信息，不确定的明确标注“待核验”。不要编造来源、事实、故事、人物对话和作者经历。"""

    content = call_llm(user_prompt, system_prompt)
    return content


def save_and_push(content: str) -> str:
    """保存简报并推送（根据 BRIEFING_MODE 区分文件名和标题）"""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now(TZ).weekday()]

    mode_tag = {"global": "🌍 全球简报", "china": "🇨🇳 中国简报", "wechat": "✍️ 公众号素材筛选"}.get(BRIEFING_MODE, "📰 每日简报")
    header = f"""# {mode_tag} — {today}（{weekday_cn}）

> 生成时间: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')} | 模型: {MODELSCOPE_MODEL}

---
"""
    full_content = header + "\n" + content + f"\n\n---\n\n*由 Daily Briefing {BRIEFING_VERSION} 自动生成*"

    # 本地输出
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    mode_suffix = {"global": "全球简报", "china": "中国简报", "wechat": "公众号素材筛选"}.get(BRIEFING_MODE, "每日简报")
    filename = f"{mode_suffix}_{today}.md"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_content)
    log(f"💾 简报已保存: {filepath}")

    # 存档到仓库（按模式区分文件名）
    os.makedirs(BRIEFING_ARCHIVE_DIR, exist_ok=True)
    archive_suffix = f"-{BRIEFING_MODE}" if BRIEFING_MODE in ("global", "china") else ""
    archive_path = os.path.join(BRIEFING_ARCHIVE_DIR, f"{today}{archive_suffix}.md")
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(full_content)
    log(f"📚 简报已存档: {archive_path}")

    # 推送
    title = f"{mode_tag} {today}"
    push_content = full_content
    if len(push_content.encode("utf-8")) > 30000:
        push_content = push_content[:10000] + f"\n\n...（内容过长已截断，完整版见仓库 briefings/）"
    push_serverchan(title, push_content)

    return filepath


# ============================================================
# 主入口
# ============================================================

def main():
    log("=" * 50)
    log(f"📰 Daily Briefing — {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}")
    log(f"🤖 模型: {MODELSCOPE_MODEL}")
    mode_label = {"global": "🌍 全球模式", "china": "🇨🇳 中国模式", "wechat": "✍️ 公众号素材筛选模式"}.get(BRIEFING_MODE, "📋 全源模式")
    log(f"📌 模式: {mode_label}")
    log(f"📤 Server酱: {'✅ 已配置' if SERVERCHAN_KEY else '⚠️  未配置'}")
    log(f"📂 输出目录: {OUTPUT_DIR}")
    log("=" * 50)

    # 采集新闻
    news_data = collect_news()

    # AI 生成简报
    if BRIEFING_MODE == "wechat":
        content = generate_wechat_material_briefing(news_data)
    else:
        content = generate_briefing(news_data)
    if not content:
        log("❌ 简报生成失败，尝试无素材直接生成...")
        # 即使没 RSS 素材，也让 AI 基于知识生成
        if BRIEFING_MODE == "global":
            fb_type = "全球简报"
            fb_structure = """1. 全球要闻（4-6条）
2. 财经（3-5条）
3. 科技（2-3条）
4. 简要评述"""
        elif BRIEFING_MODE == "china":
            fb_type = "中国简报"
            fb_structure = """1. 中国时事（2-4条）
2. 民生与社会（2-3条）
3. 简要评述"""
        elif BRIEFING_MODE == "wechat":
            fb_type = "公众号素材筛选"
            fb_structure = """### 今日最值得写
**公开事件：**（据公开报道）
**一句话信号：**
**适合人群：**40岁上下、有父母和孩子的家庭。
**可连接方向：**身体／家庭／职场／金钱／养老。
**回忆问题：**"你最近有没有遇到类似的一刻？"
**文章切口：**只提供角度，不替你编故事。
**素材等级：**S级母题／B级可复用／A级时效热点。
**推荐理由：**

### 另外2—4条候选
每条只保留：公开事实、一句话信号、与普通家庭的关系、可写角度、来源链接、风险提示"""
        else:
            fb_type = "每日简报"
            fb_structure = """1. 全球财经头条（3-5条）
2. 中国时事动态（3-5条）
3. 财经与商业（3-5条）
4. 科技与AI（3-5条）
5. 健康与民生（2-3条）
6. 简要评述"""
        fallback_prompt = f"""请基于你的知识，生成一份 {datetime.now(TZ).strftime('%Y年%m月%d日')} 的{fb_type}。
今天没有采集到最新新闻素材，请用已有知识输出。

结构：
{fb_structure}

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
