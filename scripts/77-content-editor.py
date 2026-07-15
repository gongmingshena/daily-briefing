#!/usr/bin/env python3
"""
77 内容总编 V1.0 — 每日编辑部晨报
==================================
不是新闻摘要，而是内容总编。

你的任务不是告诉我今天发生了什么，而是帮助筛选出最值得写的内容。

输出：每天 TOP 5 条，每条带完整评分、创作建议、知识库关联。

用法：
    set PYTHONIOENCODING=utf-8
    set MODELSCOPE_TOKEN="ms-xxx"
    python 77-content-editor.py

依赖：
    pip install requests beautifulsoup4 lxml
"""

import os
import sys
import re
import json
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Tuple

try:
    import requests
except ImportError:
    print("缺少依赖：requests，请运行 pip install requests")
    sys.exit(1)

# ============================================================
# 配置
# ============================================================
MODELSCOPE_TOKEN = os.environ.get("MODELSCOPE_TOKEN", "")
MODELSCOPE_BASE_URL = os.environ.get(
    "MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1"
)
MODELSCOPE_MODEL = os.environ.get("MODELSCOPE_MODEL", "Qwen/Qwen3-8B")
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "")
SECOND_BRAIN_PATH = os.environ.get(
    "SECOND_BRAIN_PATH", r"E:\1-KnowledgeBase\2-my-secondbrain"
)
OUTPUT_DIR = os.environ.get(
    "OUTPUT_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "每日编辑部晨报"),
)
TZ = timezone(timedelta(hours=8))
VERSION = "v1.2"

if not MODELSCOPE_TOKEN:
    print("❌ 请设置 MODELSCOPE_TOKEN 环境变量")
    sys.exit(1)

# ============================================================
# RSS 源 — 聚焦政府+权威财经
# ============================================================
RSS_FEEDS = {
    "china": [
        {"name": "新华网", "url": "http://www.xinhuanet.com/politics/news_politics.xml"},
        {"name": "人民网", "url": "http://www.people.com.cn/rss/politics.xml"},
    ],
    "finance": [
        {"name": "36Kr", "url": "https://36kr.com/feed"},
    ],
}

# ============================================================
# 工具函数
# ============================================================
_HTTP_SESSION: Optional[requests.Session] = None


def log(msg: str):
    now = datetime.now(TZ).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


def get_session() -> requests.Session:
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
    return _HTTP_SESSION


def fetch_rss(url: str, timeout: int = 15) -> list:
    """获取 RSS feed，返回条目列表"""
    try:
        session = get_session()
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()

        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)

        entries = []
        # RSS 2.0
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = re.sub(r"<[^>]+>", "", item.findtext("description", "")).strip()[:300]
            if title:
                entries.append({"title": title, "link": link, "summary": desc})

        # Atom
        if not entries:
            ns = "{http://www.w3.org/2005/Atom}"
            for entry in root.iter(f"{ns}entry"):
                title = entry.findtext(f"{ns}title", "").strip()
                link_el = entry.find(f"{ns}link")
                link = link_el.get("href", "").strip() if link_el is not None else ""
                summary = re.sub(r"<[^>]+>", "", entry.findtext(f"{ns}summary", "")).strip()[:300]
                if title:
                    entries.append({"title": title, "link": link, "summary": summary})

        return entries[:5]

    except Exception as e:
        log(f"⚠️  RSS 获取失败 {url[:50]}: {e}")
        return []


def fetch_baidu_hotsearch(max_items: int = 20) -> list:
    """采集百度实时热搜榜"""
    url = "https://top.baidu.com/board?tab=realtime"
    try:
        session = get_session()
        resp = session.get(url, timeout=15)
        resp.encoding = "utf-8"

        words = re.findall(r'"word":"([^"]+)"', resp.text)
        scores = re.findall(r'"hotScore":"(\d+)"', resp.text)

        seen = set()
        results = []
        for i, w in enumerate(words):
            if w not in seen:
                seen.add(w)
                score = int(scores[i]) if i < len(scores) and scores[i].isdigit() else 0
                results.append({"title": w, "hotScore": score})
            if len(results) >= max_items:
                break
        log(f"🔥 百度热搜: {len(results)} 条")
        return results
    except Exception as e:
        log(f"⚠️  热搜采集失败: {e}")
        return []


def search_knowledge_base(news_items: list) -> str:
    """搜索知识库素材，返回关联的已有素材清单（跨平台：本地用 os.walk + 关键词匹配）"""
    material_dir = os.path.join(SECOND_BRAIN_PATH, "05-公众号内容", "3-素材库")
    if not os.path.isdir(material_dir):
        log(f"⚠️  知识库路径不可用: {material_dir}（GitHub runner 上正常）")
        return "（知识库路径不可用 — GitHub runner）"

    # 提取所有标题中的关键词（3~6字中文词组）
    all_titles = [item.get("title", "") for item in news_items]
    keywords = set()
    for title in all_titles:
        words = re.findall(r'[\u4e00-\u9fff]{3,6}', title)
        stop_words = {"什么", "如何", "为什么", "一个", "没有", "可以", "不是",
                      "我们", "他们", "这个", "那个", "自己", "已经", "就是",
                      "不会", "还有", "因为", "所以", "如果", "虽然", "可能"}
        for w in words:
            if w not in stop_words:
                keywords.add(w)

    if not keywords:
        return "（无有效关键词）"

    # 跨平台关键词搜索：遍历 .md 文件，逐文件匹配关键词
    found_files = set()
    for kw in sorted(keywords)[:15]:
        try:
            for root, dirs, files in os.walk(material_dir):
                for fname in files:
                    if not fname.endswith(".md"):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                            content = fh.read(4096)  # 只读前4KB
                            if kw in content:
                                try:
                                    rel = os.path.relpath(fpath, SECOND_BRAIN_PATH)
                                except ValueError:
                                    rel = os.path.basename(fpath)
                                found_files.add(rel)
                    except Exception:
                        continue
        except Exception:
            continue

    if found_files:
        result_lines = []
        for f in sorted(found_files)[:10]:
            fpath = os.path.join(SECOND_BRAIN_PATH, f)
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    first_line = fh.readline().strip().lstrip("#").strip()
                    if not first_line:
                        first_line = fh.readline().strip().lstrip("#").strip()
                    if first_line:
                        result_lines.append(f"- `{f}` → {first_line[:60]}")
                    else:
                        result_lines.append(f"- `{f}`")
            except Exception:
                result_lines.append(f"- `{f}`")
        return "\n".join(result_lines)

    return "（无直接关联素材）"


def call_llm(prompt: str, system: str, temperature: float = 0.6,
             max_tokens: int = 8192) -> Optional[str]:
    """调用魔搭 ModelScope 免费 API（流式）"""
    url = f"{MODELSCOPE_BASE_URL}/chat/completions"
    body = {
        "model": MODELSCOPE_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }

    try:
        session = get_session()
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
                    content_piece = delta.get("content", "")
                    if content_piece:
                        collected_content += content_piece
                except json.JSONDecodeError:
                    continue

        # 清理可能的 markdown 包裹
        collected_content = collected_content.strip()
        if collected_content.startswith("```"):
            first_nl = collected_content.find("\n")
            if first_nl > 0:
                collected_content = collected_content[first_nl + 1:]
            else:
                collected_content = collected_content[3:]
        if collected_content.endswith("```"):
            collected_content = collected_content[:-3].rstrip()

        if collected_content:
            log(f"✅ LLM 生成完成 ({len(collected_content)} 字符)")
            return collected_content
        log("⚠️  LLM 返回为空")
        return None

    except Exception as e:
        log(f"⚠️  LLM 调用失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            if e.response.status_code == 401:
                log("🚨 Token 过期！请更新 MODELSCOPE_TOKEN")
        return None


def push_serverchan(title: str, content: str) -> bool:
    """通过 Server酱 推送到微信"""
    if not SERVERCHAN_KEY:
        log("⚠️  未配置 SERVERCHAN_KEY，跳过推送")
        return False
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    try:
        resp = get_session().post(url, data={"title": title, "desp": content}, timeout=30)
        result = resp.json()
        if result.get("code") == 0:
            log(f"✅ Server酱 推送成功: {title[:40]}")
            return True
        log(f"⚠️  Server酱 推送失败: {result}")
        return False
    except Exception as e:
        log(f"⚠️  Server酱 异常: {e}")
        return False


# ============================================================
# 编辑系统（核心 — 提示词）
# ============================================================

EDITOR_SYSTEM_PROMPT = """# 🧠 V2.0 总原则（先读三遍）

> **不是每天给你更多信息，而是每天帮你做一个决定。**

你真正缺的从来不是新闻。你真正缺的是：**今天，什么值得我投入两个小时。**

---

# 角色

你是77爸爸的内容总监。不是新闻编辑。不是AI。

你的工作不是筛选新闻，也不是写文章。是帮77做决策：

- 今天写什么
- 今天别写什么
- 今天先观察还是先发文
- 今天的时间花在哪一条上

**然后把素材给77，让他自己观察、自己写。**

---

# 77爸爸是谁

- 一个40岁上下、有家、有孩子、有老人的普通男人
- 以前画了15年施工图，现在做家庭风险和财务规划
- 不输出知识，输出**一个普通中年男人真实的心理变化**
- 所有内容来源于一个标准：**这件事让我停顿了三秒钟**

# 目标读者

30~55岁普通家庭：已婚、有孩子、有老人、上班族/小老板/自由职业者。对未来有焦虑，但不喜欢被推销。

---

# 核心工作流：不是打分，而是做判断

把每条新闻放进三个篮子之一：

```
┌─────────────────────────────────────┐
│         今天所有的新闻素材             │
└────────────┬────────────────────────┘
             │
     ┌───────┴───────┐
     ▼               ▼
  值得77写吗？     不值得 → C级直接丢弃
     │
     ▼
  只有77能写吗？    不是 → B级放知识库
     │
     ▼
  A级：今天就写
```

## A级 — 今天就写
必须同时满足：
- ✅ **77适配度高**：天然适合77的风格和母题
- ✅ **有真实的人**：有具体的人、一句话、一个动作
- ✅ **属于已验证母题**（看下面的母题列表）
- ✅ **为什么偏偏是77来写？** — 能诚实回答出来，不是硬拐

## B级 — 放知识库
符合筛选标准，但：
- 缺少"人"或"77适配度不够高"
- 或者：有素材价值但不是最佳写作窗口
- 存着，等更好的触发点

## C级 — 直接丢弃
以下情况直接丢：
- 娱乐八卦、明星新闻、网络口水战
- 别人写得更好（人民日报/央视/天气号）
- 没有长期价值，一年后没人记得

---

# 🧩 77已验证母题（每次判断前对照）

新闻每天会变。母题可以写很多年。

### 母题1：安全感
普通人的安全感是怎么一点点消失的？
- 已验证文章：医保反酸 | 身体恢复能力
- 最近例子：暴雨→停电→生活突然失去秩序

### 母题2：恢复能力
以前一片头孢就好，现在一周还没好。
- 核心观察：承压≠恢复

### 母题3：离开与留下
离开北京的人后来怎么样了？留下的人呢？
- 核心问题：普通人到底有没有选择

### 母题4：家庭责任
爸妈说"我没事"，子女说"我忙着呢"。
- 核心张力：爱和焦虑之间的空白地带

### 母题5：信息差
你知道的和你该知道的，差多少？
- 核心观察：没人告诉普通家庭的事

### 母题6：风险不是突然出现，而是逐渐累积
三个月前开始疼，三个月后发现是大事。
- 核心观察：裂缝还在加荷载

---

# 五大判断问题（每条新闻逐一回答）

### 问题1：这条新闻值得77写吗？
三个选项：A级今天就写 / B级放知识库 / C级直接丢弃

### 问题2：为什么偏偏是77来写？
人民日报可以写。央视可以写。天气号可以写。AI可以写。
**为什么是你？**
- 能回答出来 → 继续
- **回答不出来 → 诚实写"回答不了" → 降级到B或C**
- **严禁硬拐**：不要让AI为了"像77"而强行联系家庭/父母/保险。回答不了就是回答不了。

### 问题3：有没有真实的人？
77爸爸的爆款文章**全部有人**：
- 恢复能力 — 77自己
- 离开北京 — 设计院老同事
- 反酸 — 77自己
- 佛得角门将 — 一个40岁还在踢的人

标准：
- ✅ 有没有一个普通人？（名字不重要，但要具体）
- ✅ 有没有一句话？（他说了什么）
- ✅ 有没有一个动作？（他做了什么）
- ✅ 有没有一个细节？（画面是什么）
如果以上四个都没有 → 降级到B或C

### 问题4：属于哪个母题？
对照上面的母题列表，这条新闻链接到哪个母题？
如果连不上任何一个母题 → 降级到B或C

### 问题5：人们会因为什么记住77？
如果这篇文章火了，人们会因为什么记住77？
- ❌ 记住暴雨 → 错
- ❌ 记住新闻 → 错
- ✅ "原来他一直在观察普通家庭" → 对
- ✅ "他总能从一条新闻里看到普通人的生活" → 对
- ✅ "他说的就是我家" → 对

回答不出来 → 降级

---

# 输出格式模板（严格执行）

## 整体结构

先输出当天的**分级清单**（一目了然）：

```
═══ 今日分级清单 ═══

【A级-今天就写】  1条
1. [新闻标题]

【B级-放知识库】  X条
1. [新闻标题]

【C级-直接丢弃】  X条
1. [新闻标题]（原因）
```

然后对 **A级** 和 **B级** 的每条，输出完整分析。

C级只列标题和丢弃原因，不展开。

---

## A/B 级详细格式

每条用 `---` 开头。

```
---

## [新闻标题]

### 分级
[A级-今天就写 / B级-放知识库]

### 为什么偏偏是77来写？
[诚实回答。能回答就写。回答不了就写"回答不了，这条新闻没有77的独特角度"]
**严禁硬拐：不要让AI为了"像77"强行联系家庭/父母。没有就是没有。**

### 有没有真实的人？
- **人**：[具体的人，如"设计院老同事""小区物业群里的邻居"]
- **一句话**：[他说了什么，如"谁家有充电宝？"]
- **一个动作**：[他做了什么]
- **一个细节**：[画面是什么]
如果四个都没有 → 诚实写"无真实人物"

### 素材（不是观点）
不要写结论。只给原材料——具体的物、场景、动作。
例如（暴雨）：
- 地下车库
- 物业群突然安静
- 老人独居
- 停电
- 充电宝
- 孩子放学没人接
**禁止抽象概念**：不要写"教育内卷""社会焦虑""家庭伦理"这类词。

### 属于哪个母题？
[母题名称] — 一句话说明为什么
如果连不上任何一个母题 → 写"无直接关联"

### 77适配度
- **高**：天然适合77，别人写不了
- **中**：77可以写，但别人也能写
- **低**：不适合77

### 今天媒体已写什么
列出今天媒体/公号已经覆盖的角度：
- ① [角度一]
- ② [角度二]
- ③ [角度三]
→ 77不要重复

### 还能写什么
[77可以绕开以上角度，从什么方向切入]

### 历史呼应（母题相同的历史文章）
[这条新闻的母题，以前77写过什么？只列标题，不解释]
- 《反酸100+》
- 《身体恢复322》
如无历史文章 → 写"暂无"

### 如果火了，人们会因为什么记住77？
[一句话品牌定位，如："他不是在写天气，是在写普通人的安全感"]

### 以后自然可以关联
[这条内容积累的是哪个方向的信任？多重选择]
- 医疗
- 养老
- 教育
- 财富
- 家庭规划
- 保险（排在最后）
- 不用关联

---

## 结尾栏目（每天必出）

```

---

## 🌟 今天最值得观察的一句话

[不是金句。不是观点。不是结论。

是今天素材里最值得停下来的那一句话。

可能是一个画面：物业群安静了三分钟。
可能是一句反问：停电那一刻你第一个想到谁。
可能是一句发现：我们害怕的不是暴雨，是生活突然失去秩序。

**重点：只给这句话本身。不要解释，不要点评，不要写"这句话道出了……"。**

标准：这句话放出来，77就知道怎么写了。解释一句都是多余的。]

---

## 📋 今日总编意见

**今天如果只能花90分钟：**
[具体到分钟的建议，如：全部给暴雨，不要分散]

**今天值不值得发公众号：**
[值得发 / 先发朋友圈观察评论 / 只积累素材不要发]

**如果发，今天适合哪个平台：**
[公众号 / 朋友圈 / 小红书 / 都不发]

**一句话总编决策：**
[一条最终决定，如：今天不要急着发文，先发朋友圈看大家反应]
```
"""


def build_editorial_prompt(news_data: Dict, knowledge_refs: str, date_str: str) -> str:
    """组装用户提示词——把素材喂给 AI 总编"""
    sections = []

    # ---- 热搜 ----
    hotsearch = news_data.get("hotsearch", [])
    if hotsearch:
        section = "## 🔥 今日热搜\n\n"
        for i, item in enumerate(hotsearch[:10], 1):
            score = item.get("hotScore", 0)
            section += f"{i}. **{item['title']}** (热度: {score:,})\n"
        sections.append(section)

    # ---- 国内要闻 ----
    china = news_data.get("china", [])
    if china:
        section = "## 🇨🇳 国内要闻\n\n"
        for i, item in enumerate(china, 1):
            section += f"{i}. **{item['title']}**\n"
            if item.get("summary"):
                section += f"   {item['summary'][:200]}\n"
            if item.get("link"):
                section += f"   [{item.get('source','来源')}]({item['link']})\n"
            section += "\n"
        sections.append(section)

    # ---- 财经 ----
    finance = news_data.get("finance", [])
    if finance:
        section = "## 💰 财经动态\n\n"
        for i, item in enumerate(finance, 1):
            section += f"{i}. **{item['title']}**\n"
            if item.get("summary"):
                section += f"   {item['summary'][:200]}\n"
            section += "\n"
        sections.append(section)

    raw_material = "\n".join(sections) if sections else "（今日没有采集到新闻素材）"

    prompt = f"""今天是 {date_str}。

采集到的新闻素材如下：

{raw_material}

---

知识库中已有的关联素材：
{knowledge_refs}

---

请执行"每日编辑部晨报"工作流：

**第一步：分级** — 把每条新闻放进 A/B/C 三个篮子
**第二步：对 A级和B级** — 逐一回答五大判断问题
**第三步：输出** — 分级清单 + A/B级详细分析 + 最值得观察的一句话 + 今日总编意见

切记：
- 你不是在写文章。你是在帮77做决策。
- **回答不了比硬拐高级。** 如果一条新闻没有77的独特角度，诚实说"回答不了"。
- 素材必须具体（物/场景/动作），不要抽象概念。
- **不要替77写文章，不要替77下结论。**"""
    return prompt


# ============================================================
# 主流程
# ============================================================

def collect_news() -> Dict:
    """从所有源采集新闻"""
    log("📡 开始采集新闻...")
    all_news = {}

    # RSS 国内源
    china_news = []
    for feed in RSS_FEEDS["china"]:
        entries = fetch_rss(feed["url"])
        if entries:
            log(f"  ✓ {feed['name']}: {len(entries)} 条")
            for e in entries:
                e["source"] = feed["name"]
            china_news.extend(entries)
        else:
            log(f"  ✗ {feed['name']}: 无数据")

    # 去重
    seen = set()
    unique = []
    for item in china_news:
        key = item["title"][:40]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    all_news["china"] = unique[:15]

    # RSS 财经源
    finance_news = []
    for feed in RSS_FEEDS["finance"]:
        entries = fetch_rss(feed["url"])
        if entries:
            log(f"  ✓ {feed['name']}: {len(entries)} 条")
            for e in entries:
                e["source"] = feed["name"]
            finance_news.extend(entries)
        else:
            log(f"  ✗ {feed['name']}: 无数据")

    seen = set()
    unique = []
    for item in finance_news:
        key = item["title"][:40]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    all_news["finance"] = unique[:10]

    # 百度热搜
    hot = fetch_baidu_hotsearch(20)
    if hot:
        all_news["hotsearch"] = hot

    return all_news


def parse_args():
    parser = argparse.ArgumentParser(
        description="77 内容总编 V1.0 — 每日编辑部晨报"
    )
    parser.add_argument(
        "--push", action="store_true",
        help="推送到 Server酱（默认 dry-run 不推送）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="显式指定 dry-run 模式（不推送，默认行为）"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 推送开关：--push 显式开启，或 ENABLE_PUSH=true 环境变量
    enable_push = args.push or os.environ.get("ENABLE_PUSH", "").lower() in ("true", "1", "yes")

    log("=" * 50)
    log("📰 77 内容总编 " + VERSION)
    log("   每日编辑部晨报")
    log(f"🤖 模型: {MODELSCOPE_MODEL}")
    log(f"📂 输出目录: {OUTPUT_DIR}")
    log(f"📤 推送: {'✅ 开启' if enable_push else '❌ 关闭(dry-run)'}")
    log("=" * 50)

    now = datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")
    date_iso = now.strftime("%Y-%m-%d")
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]

    # Step 1: 采集新闻
    news_data = collect_news()

    # Step 2: 搜索知识库关联素材
    all_items = []
    for items in news_data.values():
        all_items.extend(items)
    log(f"🔍 搜索知识库关联素材...")
    knowledge_refs = search_knowledge_base(all_items)
    log(f"📚 知识库关联: {'找到匹配' if '无' not in knowledge_refs else '无匹配'}")

    # Step 3: 构建编辑提示词
    user_prompt = build_editorial_prompt(news_data, knowledge_refs, date_str)

    # Step 4: AI 编辑分析
    log("🧠 内容总编分析中...")
    editorial = call_llm(user_prompt, EDITOR_SYSTEM_PROMPT)

    if not editorial:
        log("❌ 编辑分析失败")
        # 重试一次
        log("🔄 重试一次...")
        editorial = call_llm(user_prompt, EDITOR_SYSTEM_PROMPT)
        if not editorial:
            log("❌ 重试仍然失败")
            sys.exit(1)

    # Step 5: 保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 添加完整头部信息
    header = f"""# 📰 每日编辑部晨报

> **{date_str}（{weekday_cn}）**
> 生成时间: {now.strftime('%Y-%m-%d %H:%M')}
> 角色: 77爸爸的内容总监（不是新闻编辑）
> 工作流: 母题驱动 → ABC分级 → 五大判断
> 模型: {MODELSCOPE_MODEL}
> 版本: {VERSION}

---

"""
    full = header + editorial + f"\n\n---\n*由 77 内容总编 {VERSION} 自动生成*"

    filepath = os.path.join(OUTPUT_DIR, f"每日编辑部晨报_{date_iso}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full)
    log(f"💾 已保存: {filepath}")

    # 也输出到控制台预览
    print("\n" + "=" * 50)
    print("📋 内容预览（前 2000 字符）：")
    print("=" * 50)
    print(editorial[:2000])
    print("...")
    print("=" * 50)

    # Step 6: 推送（仅 --push 或 ENABLE_PUSH=true 时执行）
    if enable_push:
        push_title = f"📰 77内容总编 | {date_str}"
        push_content = full
        if len(push_content.encode("utf-8")) > 28000:
            push_content = (
                editorial[:6000]
                + f"\n\n---\n📎 完整版见本地文件:\n{filepath}"
            )
            push_content = f"# 📰 每日编辑部晨报 — {date_str}\n\n" + push_content
        push_serverchan(push_title, push_content)
    else:
        log("⏭️  dry-run 模式，跳过推送")
        log("💡 使用 --push 参数或设置 ENABLE_PUSH=true 来启用推送")

    log(f"\n✅ 完成！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
