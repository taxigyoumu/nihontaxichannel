#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公的フィードから岐阜県向けのニュース・気象情報を取得し news.json に保存する。
GitHub Actions から定期実行される想定。

取得元（いずれも機械可読・規約クリーン）:
  1. 気象庁 高頻度フィード（随時）= 気象警報・注意報
  2. 気象庁 高頻度フィード（地震火山）= 地震情報
  3. NHK 主要ニュース（タイトルと出典リンクのみ／本文は転載しない）

著作権配慮:
  - NHK等の一般ニュースは「見出し（タイトル）」と「出典名」のみ保持。
  - 本文・要約は保存・表示しない。リンクは出典表示のために保持。
"""

import json
import sys
import datetime
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error

JST = datetime.timezone(datetime.timedelta(hours=9))

# 岐阜県に関係するキーワード（気象警報の絞り込み用）
GIFU_KEYWORDS = ["岐阜", "美濃", "飛騨"]

# 取得タイムアウト
TIMEOUT = 20

# User-Agent（明示しておく）
HEADERS = {"User-Agent": "NitakuSignage/1.0 (taxi dispatch room signage; contact via GitHub)"}


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.read()


def parse_atom_entries(xml_bytes, limit=30):
    """気象庁Atomフィードのentryを (title, updated, content) で返す"""
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for entry in root.findall("atom:entry", ns)[:limit]:
        title = entry.findtext("atom:title", default="", namespaces=ns) or ""
        updated = entry.findtext("atom:updated", default="", namespaces=ns) or ""
        content = entry.findtext("atom:content", default="", namespaces=ns) or ""
        author = ""
        author_el = entry.find("atom:author/atom:name", ns)
        if author_el is not None and author_el.text:
            author = author_el.text
        out.append({"title": title.strip(), "updated": updated.strip(),
                    "content": content.strip(), "author": author.strip()})
    return out


def get_jma_warnings():
    """気象庁 高頻度フィード（随時=警報注意報）から岐阜県関連を抽出"""
    url = "https://www.data.jma.go.jp/developer/xml/feed/extra.xml"
    items = []
    try:
        entries = parse_atom_entries(fetch(url))
    except Exception as e:
        print(f"[warn] JMA extra feed error: {e}", file=sys.stderr)
        return items
    for e in entries:
        # 岐阜地方気象台発表のものに絞る
        blob = (e["author"] + " " + e["title"] + " " + e["content"])
        if "岐阜" in e["author"] or any(k in blob for k in GIFU_KEYWORDS):
            # 警報・注意報・気象情報のみ
            if any(w in e["title"] for w in ["警報", "注意報", "気象情報", "土砂災害", "記録的"]):
                # 表示テキストは具体的な警報文(content)を優先。無ければtitle。
                display = e["content"] if e["content"] else e["title"]
                items.append({
                    "category": "weather",
                    "label": "気象",
                    "text": display,
                    "source": e["author"] or "気象庁",
                    "time": e["updated"],
                })
    return items


def get_jma_quake():
    """気象庁 高頻度フィード（地震火山）から最新の地震情報を抽出"""
    url = "https://www.data.jma.go.jp/developer/xml/feed/eqvol.xml"
    items = []
    try:
        entries = parse_atom_entries(fetch(url))
    except Exception as e:
        print(f"[warn] JMA eqvol feed error: {e}", file=sys.stderr)
        return items
    for e in entries[:5]:
        if any(k in e["title"] for k in ["震源", "震度", "地震", "津波"]):
            display = e["content"] if e["content"] else e["title"]
            items.append({
                "category": "quake",
                "label": "地震",
                "text": display,
                "source": e["author"] or "気象庁",
                "time": e["updated"],
            })
    return items


def get_nhk_headlines():
    """NHK主要ニュースの見出しのみ取得（本文は保存しない・出典明記）"""
    url = "https://www.nhk.or.jp/rss/news/cat0.xml"
    items = []
    try:
        xml_bytes = fetch(url)
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        print(f"[warn] NHK feed error: {e}", file=sys.stderr)
        return items
    # RSS 2.0形式
    for item in root.findall(".//item")[:8]:
        title = (item.findtext("title") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if title:
            items.append({
                "category": "news",
                "label": "ニュース",
                "text": title,          # 見出しのみ
                "source": "NHK",        # 出典明記
                "time": pub,
            })
    return items


def main():
    all_items = []

    # 優先順位：警報 → 地震 → 一般ニュース
    warnings = get_jma_warnings()
    quakes = get_jma_quake()
    news = get_nhk_headlines()

    all_items.extend(warnings)
    all_items.extend(quakes)
    all_items.extend(news)

    # 警報がない平常時のフォールバック
    has_alert = len(warnings) > 0 or len(quakes) > 0

    result = {
        "updated_at": datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "has_alert": has_alert,
        "items": all_items,
    }

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[ok] wrote news.json: {len(all_items)} items "
          f"(warnings={len(warnings)}, quakes={len(quakes)}, news={len(news)})")


if __name__ == "__main__":
    main()
