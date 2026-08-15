#!/usr/bin/env python3
"""
合并公众号素材筛选 + 编辑部晨报为一条 Server酱 推送
用于 GitHub Actions 合并步骤
"""
import os
import sys
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
today = datetime.now(TZ).strftime("%Y-%m-%d")
key = os.environ.get("SERVERCHAN_KEY", "")

if not key:
    print("⚠️  SERVERCHAN_KEY 未配置，跳过推送")
    sys.exit(0)

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(script_dir)

# 读取公众号素材筛选
material_path = os.path.join(script_dir, "output", "每日简报", f"公众号素材筛选_{today}.md")
if os.path.isfile(material_path):
    with open(material_path, "r", encoding="utf-8") as f:
        material = f.read().strip()
else:
    material = f"# ✍️ 公众号素材筛选 — {today}\n\n（今日未生成）"

# 读取编辑部晨报
editor_path = os.path.join(script_dir, "output", "每日编辑部晨报", f"每日编辑部晨报_{today}.md")
if os.path.isfile(editor_path):
    with open(editor_path, "r", encoding="utf-8") as f:
        editor = f.read().strip()
else:
    editor = f"# 📰 每日编辑部晨报 — {today}\n\n（今日未生成）"

# 合并
merged = material + "\n\n---\n\n" + editor

# 截断（Server酱约 32KB 上限）
if len(merged.encode("utf-8")) > 28000:
    merged = merged[:10000] + "\n\n...（内容过长已截断）"

# 推送
title = f"✍️ 77素材筛选 + 📰 编辑部晨报 | {today}"
url = f"https://sctapi.ftqq.com/{key}.send"

try:
    import requests
    resp = requests.post(url, data={"title": title, "desp": merged}, timeout=30)
    result = resp.json()
    if result.get("code") == 0:
        print(f"✅ 合并推送成功: {title}")
    else:
        print(f"⚠️  推送失败: {result}")
except Exception as e:
    print(f"⚠️  推送异常: {e}")
