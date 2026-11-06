"""Inspect every generated tag, card, plan and anchor using the stdlib parser."""
import ast
import re
from collections import Counter
from html.parser import HTMLParser

from .master import ROOT
from .validation import allowed_url, expected_category, normalize, require

VOID = set("area base br col embed hr img input link meta param source track wbr".split())


class Node:
    def __init__(self, tag="root", attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def text(self):
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def nodes(self, tag=None, cls=None):
        found = []
        for c in self.children:
            if isinstance(c, Node):
                if (tag is None or c.tag == tag) and (cls is None or cls in c.attrs.get("class", "").split()):
                    found.append(c)
                found.extend(c.nodes(tag, cls))
        return found


class Structure(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.ids = set()
        self.doctype = False

    def handle_decl(self, decl):
        require(decl.lower() == "doctype html" and not self.doctype, "HTML doctypeが不正")
        self.doctype = True

    def handle_starttag(self, tag, attrs):
        require(len(dict(attrs)) == len(attrs), "HTML属性の重複")
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if "id" in node.attrs:
            require(node.attrs["id"] not in self.ids, "HTML idの重複")
            self.ids.add(node.attrs["id"])
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        require(len(self.stack) > 1 and self.stack[-1].tag == tag, "HTML開閉タグの不一致: " + tag)
        self.stack.pop()

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def validate_html(text, data):
    parser = Structure()
    parser.feed(text)
    parser.close()
    require(parser.doctype and len(parser.stack) == 1, "HTML未閉鎖タグがあります")
    root = parser.root
    for tag in ("html", "head", "body", "main", "style", "script"):
        require(len(root.nodes(tag)) == 1, "HTMLの必須構造が不正: " + tag)
    # The unchanged builder is the single source of CSS/JS; reject unexpected code.
    constants, functions = {}, []
    for node in ast.parse((ROOT / "build_html.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("CSS", "JS"):
                    constants[target.id] = node.value.value
        if isinstance(node, ast.FunctionDef) and node.name in ("clean", "known"):
            functions.append(node)
    namespace = {"re": re}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<builder display helpers>", "exec"), namespace)
    clean, known = namespace["clean"], namespace["known"]
    require(root.nodes("style")[0].text() == constants["CSS"] and
            root.nodes("script")[0].text() == constants["JS"], "CSS/JSが生成スクリプトと不一致")
    sections = root.nodes("section", "area")
    require([n.attrs.get("id") for n in sections] == [f"a{i}" for i in range(1, 15)], "HTMLの14エリアが不一致")
    all_ids = {n.attrs["id"] for n in root.nodes() if "id" in n.attrs}
    for anchor in root.nodes("a"):
        href = anchor.attrs.get("href", "")
        if href.startswith("#"):
            require(href[1:] in all_ids, "内部リンク切れ")
        else:
            allowed_url(href)
    cards = root.nodes("article", "card")
    expected = {(a["no"], normalize(s["name"]), normalize(s["shop"] or "")): s
                for a in data["areas"] for cat in a["cats"].values() for s in cat["shops"] if s["links"]}
    require(len(cards) == len(expected), "HTMLカード数がJSONと不一致")
    found = set()
    for area, section in zip(data["areas"], sections):
        groups = section.nodes("div", "cat")
        require([g.attrs.get("data-cat") for g in groups] == ["cafe", "hotel", "lux"], "HTML分類が不一致")
        area_total = len(section.nodes("article", "card"))
        require(section.nodes(cls="acnt")[0].text() == f"{area_total}件", "エリア件数表示が不一致")
        for group in groups:
            require(group.nodes(cls="cnt")[0].text() == f"{len(group.nodes('article', 'card'))}件", "分類件数表示が不一致")
            for card in group.nodes("article", "card"):
                names = card.nodes("h4")
                require(len(names) == 1, "カード店舗名が不正")
                shop_nodes = card.nodes(cls="shop")
                key = (area["no"], normalize(names[0].text()), normalize(shop_nodes[0].text() if shop_nodes else ""))
                require(key in expected and key not in found, "HTML店舗の重複・不明なカード")
                found.add(key)
                source = expected[key]
                require(card.attrs.get("data-cat") == group.attrs["data-cat"] == expected_category(source), "HTMLカード分類が不一致")
                require([n.attrs["href"] for n in card.nodes("a")] == [l["url"] for l in source["links"]], "HTML予約リンクが不一致")
                plans = sorted(source["plans"], key=lambda p: p["start"] or "")
                output_plans = card.nodes("div", "plan")
                require(len(output_plans) == len(plans), "HTMLプラン数が不一致")
                prices = [p["price_min"] for p in plans if p["price_min"] is not None]
                require(card.attrs.get("data-pk") == str(int(bool(prices))), "未確認料金が確定扱いです")
                for day in ("wd", "we"):
                    require(card.attrs.get("data-" + day) == str(int(any(p[day] == "on" for p in plans))), "未確認曜日が提供あり扱いです")
                for plan, output in zip(plans, output_plans):
                    for key, cls in (("theme", "theme"), ("time_text", "time"), ("days_text", "dtxt")):
                        fields = output.nodes(cls=cls)
                        require(len(fields) == int(known(plan[key])), "未確認情報の表示がJSONと不一致: " + key)
                        if fields:
                            require(fields[0].text() == clean(plan[key]), "HTMLの値がJSONと不一致: " + key)
                    if plan["wd"] == "off" and plan["we"] == "off":
                        require(any(n.text() == "曜日未確認" for n in output.nodes(cls="chip")), "曜日未確認の表示がありません")
                    price_nodes = output.nodes(cls="pbig")
                    require(bool(price_nodes) == (plan["price_min"] is not None), "未確認料金の数値表示")
                    if price_nodes:
                        require(price_nodes[0].text() == f"{plan['price_min']:,}円〜", "HTML料金が不一致")
                    if not plan["start"] and not plan["end"]:
                        require(not output.nodes(cls="pst"), "期間不明が提供中扱いです")
                    chips = output.nodes(cls="chip")
                    require(Counter(n.text() for n in chips if "on" in n.attrs.get("class", "").split()) ==
                            Counter(label for k, label in (("wd", "平日"), ("we", "土日祝")) if plan[k] == "on"), "HTML曜日表示が不一致")
    require(found == set(expected), "HTML店舗の欠落")
    return {"cards": len(cards), "areas": len(sections), "structure": "valid",
            "css_js": "unchanged", "reservation_domains": "valid"}
