import json, sys, re, html, datetime

# ===== 使い方 =====
# python3 build_html.py data_開始日.json
# → afternoon_tea_tokyo_開始日.html を同じフォルダに作る。このスクリプトは変更しない。

CSS = r""":root{--bg:#EEF1F4;--paper:#FFFFFF;--ink:#1C2733;--sub:#5E6B78;--mute:#98A3AE;--line:#DCE2E8;
--hotel:#2F5D86;--hotel-t:#E4EDF5;--lux:#8F6C22;--lux-t:#F4EDDC;--cafe:#4F6F55;--cafe-t:#E3EDE4;--ok:#2E6B4F;--ok-t:#DCEFE4;--no:#9AA3AC;
box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#12181E;--paper:#1A222B;--ink:#E6EBF0;--sub:#A4AFBA;--mute:#6D7985;--line:#2B3540;
--hotel:#8DB4D8;--hotel-t:#1F2E3C;--lux:#D9B770;--lux-t:#35301F;--cafe:#9EC3A3;--cafe-t:#1F3024;--ok:#8FD1AE;--ok-t:#1E3629;--no:#5F6B76}}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:calc(env(safe-area-inset-top,0px) + 16px)}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Noto Sans JP","Hiragino Sans","Yu Gothic",sans-serif;font-size:15px;line-height:1.7}
.hero{background:var(--paper);border-bottom:1px solid var(--line)}
.hero-in{max-width:1120px;margin:0 auto;padding:44px 24px 28px;display:grid;grid-template-columns:1.5fr 1fr;gap:32px;align-items:end}
h1{font-family:"Zen Old Mincho","Hiragino Mincho ProN",serif;font-size:clamp(26px,3.4vw,40px);word-break:keep-all;line-height:1.25;margin:0 0 10px;letter-spacing:.03em}
.lead{color:var(--sub);margin:0;max-width:62ch}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.stat{border-radius:12px;padding:12px 14px}.stat b{display:block;font-size:26px;font-family:"Zen Old Mincho",serif;line-height:1.2}.stat span{font-size:13px}
.s-hotel{background:var(--hotel-t);color:var(--hotel)}.s-lux{background:var(--lux-t);color:var(--lux)}.s-cafe{background:var(--cafe-t);color:var(--cafe)}
.fpanel{background:var(--paper);border-bottom:1px solid var(--line)}.fpanel-in{max-width:1120px;margin:0 auto;padding:14px 24px 16px;display:flex;flex-direction:column;gap:10px}
.frow{display:grid;grid-template-columns:5.5em 1fr;gap:8px 10px;align-items:start}.frow .lb{font-size:12.5px;color:var(--sub);padding-top:6px;white-space:nowrap}
.btns{display:grid;grid-template-columns:repeat(auto-fill,minmax(max(128px,calc((100% - 32px) / 5)),1fr));gap:8px}
.frow .hint{grid-column:2;color:var(--mute);font-size:11.5px;margin:-2px 0 0}
.totop{position:fixed;right:16px;bottom:calc(env(safe-area-inset-bottom,0px) + 16px);z-index:10;font-size:12.5px;font-weight:700;text-decoration:none;color:var(--ink);background:var(--paper);border:1.5px solid var(--line);border-radius:999px;padding:7px 14px;box-shadow:0 2px 8px rgba(0,0,0,.18);display:none}.totop.show{display:block}
.fb{font:inherit;font-size:13px;line-height:1.4;border:1.5px solid var(--line);background:var(--paper);color:var(--ink);border-radius:999px;padding:5px 8px;cursor:pointer;text-align:center;min-width:0;white-space:nowrap}
.fb[aria-pressed="true"]{border-color:currentColor;font-weight:700}
.fb.f-hotel[aria-pressed="true"]{color:var(--hotel);background:var(--hotel-t)}.fb.f-lux[aria-pressed="true"]{color:var(--lux);background:var(--lux-t)}.fb.f-cafe[aria-pressed="true"]{color:var(--cafe);background:var(--cafe-t)}
.fb.f-x[aria-pressed="true"]{color:var(--ok);background:var(--ok-t)}
.legendline{margin-top:12px;font-size:12.5px;display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center}.lg{white-space:nowrap;display:inline-flex;gap:6px;align-items:center}
.area-btn{color:var(--ink);text-decoration:none;font-size:13px;line-height:1.4;border:1.5px solid var(--line);background:var(--paper);border-radius:10px;padding:5px 8px;display:flex;gap:6px;align-items:center;justify-content:center;text-align:center;min-width:0;word-break:keep-all}
.area-btn:hover{border-color:var(--ink);background:var(--bg)}
button:focus-visible,a:focus-visible{outline:2px solid var(--hotel);outline-offset:2px}
main{max-width:1120px;margin:0 auto;padding:12px 24px 72px}
.area{margin-top:40px}
h2{font-family:"Zen Old Mincho",serif;font-size:26px;margin:0 0 6px;display:flex;align-items:baseline;gap:14px}
h2 .no{font-family:"Noto Sans JP",sans-serif;font-size:14px;color:var(--mute);font-weight:500}h2 .acnt{font-size:13px;color:var(--sub);font-family:"Noto Sans JP",sans-serif;font-weight:400}
.cat{margin:14px 0 8px}.cat.hide{display:none}
h3{margin:0 0 10px;display:flex;align-items:center;gap:10px;font-size:14px}
.tag{padding:2px 12px;border-radius:999px;font-weight:700}
.c-hotel .tag{background:var(--hotel-t);color:var(--hotel)}.c-lux .tag{background:var(--lux-t);color:var(--lux)}.c-cafe .tag{background:var(--cafe-t);color:var(--cafe)}
.cnt{color:var(--sub);font-weight:400;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.card{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:18px 18px 14px;display:flex;flex-direction:column;gap:8px;position:relative;overflow:hidden}.top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.card::before{content:"";position:absolute;inset:0 0 auto 0;height:4px}
.c-hotel .card::before,.card.c-hotel::before{background:var(--hotel)}.card.c-lux::before{background:var(--lux)}.card.c-cafe::before{background:var(--cafe)}
.card.hide{display:none}
.card header{min-width:0}
h4{margin:0;font-size:16.5px;line-height:1.45;font-family:"Zen Old Mincho",serif}

.shop{margin:1px 0 0;font-size:13px;color:var(--sub)}
.rnote{margin:-2px 0 0;font-size:11.5px;color:var(--mute)}
.loc,.theme,.time{margin:0;display:flex;gap:6px;align-items:flex-start;font-size:13.5px}
.loc{color:var(--sub)}
svg{width:15px;height:15px;flex:none;margin-top:3px;color:var(--mute)}.theme svg{width:17px;height:17px;margin-top:2px}
.price{border-top:1px dashed var(--line);padding-top:10px;display:flex;flex-direction:column}
.pbig{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.2}.pbig small{font-size:13px;font-weight:500;margin-left:2px}
.pdet{font-size:12.5px;color:var(--sub)}
.plans{display:flex;flex-direction:column;gap:10px;margin-top:auto}
.plan{--pc:var(--hotel);--pt:var(--hotel-t);display:flex;flex-direction:column;gap:6px;background:var(--pt);border:1px solid var(--line);border-left:5px solid var(--pc);border-radius:12px;padding:10px 12px 12px}
.card.c-lux .plan{--pc:var(--lux);--pt:var(--lux-t)}.card.c-cafe .plan{--pc:var(--cafe);--pt:var(--cafe-t)}
.plan .price{border-top:0;padding-top:0}.plan .when{margin-top:0;background:var(--paper)}.plan .theme{font-weight:700}.plan .theme svg{color:var(--pc)}
.plan-hd{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.pno{font-size:11.5px;font-weight:700;color:var(--paper);background:var(--pc);border-radius:999px;padding:1px 9px;white-space:nowrap}
.pper{margin:0;font-size:12.5px;font-weight:700;color:var(--pc);font-variant-numeric:tabular-nums}.pper.na{color:var(--sub);font-weight:500}
.pst{font-size:11px;font-weight:700;border-radius:999px;padding:0 8px;white-space:nowrap}.pst.now{background:var(--ok-t);color:var(--ok)}.pst.soon{color:var(--sub);border:1px dashed var(--mute)}
.period{margin:0 0 8px;font-size:clamp(17px,2vw,21px);font-weight:700;font-variant-numeric:tabular-nums}.period small{font-size:13px;font-weight:500;color:var(--sub);margin-left:4px}
.when{margin-top:auto;background:var(--bg);border-radius:10px;padding:9px 11px}
.chips{display:flex;gap:6px}
.chip{font-size:12px;font-weight:700;padding:1px 10px;border-radius:999px}
.chip.on{background:var(--ok-t);color:var(--ok)}.chip.no{color:var(--no);text-decoration:line-through;background:transparent;border:1px solid var(--line)}.chip.off{color:var(--mute);border:1px dashed var(--mute)}
.dtxt{margin:5px 0 3px;font-size:12.5px;color:var(--sub)}
.time{font-size:13px}
.meet{border:1px solid var(--line);border-radius:10px;padding:8px 11px;font-size:13px}.meet p{margin:0;display:flex;gap:8px;align-items:baseline}.meet p+p{margin-top:3px}
.mk{flex:none;font-size:11px;font-weight:700;color:var(--paper);background:var(--sub);border-radius:5px;padding:0 6px;line-height:1.7}
.vf{font-size:10.5px;color:#B5542B;border:1px solid #B5542B;border-radius:4px;padding:0 4px;margin:0 3px;white-space:nowrap}
.fb .bc{font-size:11px;color:var(--mute);margin-left:5px;font-weight:400}
.swt{margin:-2px 0 0;padding-left:23px;display:flex;flex-wrap:wrap;gap:4px}.swt span{font-size:11.5px;line-height:1.6;padding:0 8px;border-radius:999px;background:var(--bg);color:var(--sub);border:1px solid var(--line)}
.links{display:flex;flex-wrap:wrap;gap:6px;padding-left:23px}
.lk{display:inline-flex;align-items:center;gap:4px;font-size:12.5px;font-weight:500;text-decoration:none;color:var(--ink);border:1px solid var(--line);background:var(--paper);border-radius:8px;padding:3px 9px;transition:border-color .15s,background .15s}
.lk svg{width:11px;height:11px;margin:0;color:var(--mute)}.lk:hover{border-color:var(--ink);background:var(--bg)}
.lk-ik{border-left:3px solid #C9A33A}.lk-tb{border-left:3px solid #D0643A}.lk-tc{border-left:3px solid #2B8A8A}
.none{margin:0;padding:14px 16px;border:1px dashed var(--line);border-radius:12px;color:var(--sub);font-size:14px}
.aside{margin-top:64px;display:grid;grid-template-columns:1fr;gap:24px}
.box{min-width:0;overflow-wrap:anywhere;background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.clink{color:var(--hotel);text-decoration:underline;text-underline-offset:2px;display:inline-flex;align-items:center;gap:3px}.clink svg{width:11px;height:11px;margin:0;color:currentColor}.clink:hover{text-decoration-thickness:2px}
.box h2{font-size:19px}.box ul{list-style:none;margin:0;padding:0}.box li{padding:8px 0;border-top:1px solid var(--line);font-size:14px}.box li:first-child{border-top:0}
@media (max-width:820px){.hero-in{grid-template-columns:1fr}.aside{grid-template-columns:1fr}}
@media (max-width:420px){.grid{grid-template-columns:1fr}.hero-in,.fpanel-in,main{padding-left:16px;padding-right:16px}.frow{grid-template-columns:4em 1fr}.fb{white-space:normal}.btns{grid-template-columns:repeat(auto-fill,minmax(max(118px,calc((100% - 32px) / 5)),1fr))}}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}.lk{transition:none}}
.ctry{margin:0;padding-left:23px;display:flex;align-items:center;gap:6px;font-size:13px;font-weight:700;color:var(--ink)}.ctry svg{width:24px;height:16px;margin:0;border-radius:2px;box-shadow:0 0 0 1px var(--line)}
@media print{.totop{display:none}}"""
JS = r"""const st={cat:{hotel:true,lux:true,cafe:true},x:{wd:false,we:false,pk:false},sw:new Set()};
function apply(){
 document.querySelectorAll('.card').forEach(c=>{let ok=st.cat[c.dataset.cat];
  if(st.x.wd&&c.dataset.wd!=="1")ok=false; if(st.x.we&&c.dataset.we!=="1")ok=false; if(st.x.pk&&c.dataset.pk!=="1")ok=false;
  if(st.sw.size&&!(c.dataset.sw||"").split(" ").some(t=>st.sw.has(t)))ok=false;
  c.classList.toggle('hide',!ok);});
 document.querySelectorAll('.cat').forEach(b=>{const on=st.cat[b.dataset.cat];b.classList.toggle('hide',!on);
  const vis=b.querySelectorAll('.card:not(.hide)').length;const cn=b.querySelector('.cnt');if(cn)cn.textContent=vis+'件';});
}
document.querySelectorAll('.fb').forEach(b=>b.addEventListener('click',()=>{const on=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',on);
 if(b.dataset.cat)st.cat[b.dataset.cat]=on; else if(b.dataset.sw){on?st.sw.add(b.dataset.sw):st.sw.delete(b.dataset.sw);} else st.x[b.dataset.x]=on; apply();}));
const tp=document.getElementById('top'),tt=document.querySelector('.totop');
if(tp&&tt&&'IntersectionObserver'in window){new IntersectionObserver(e=>tt.classList.toggle('show',!e[0].isIntersecting)).observe(tp);}else if(tt){tt.classList.add('show');}"""

SITES = [("ik", "一休.com"), ("tb", "食べログ"), ("tc", "TableCheck")]
SWEETS = [("ichigo", "いちご"), ("melon", "メロン"), ("peach", "桃"), ("mango", "マンゴー"), ("grape", "ぶどう・マスカット"),
          ("kuri", "栗・マロン"), ("imo", "芋・かぼちゃ"), ("kaki", "柿・洋梨・いちじく"), ("citrus", "柑橘"), ("choco", "チョコレート"),
          ("wa", "抹茶・和"), ("macaron", "マカロン"), ("parfait", "パフェ"), ("scone", "スコーン"), ("halloween", "ハロウィン"), ("xmas", "クリスマス"), ("valentine", "バレンタイン"), ("whiteday", "ホワイトデー"), ("collab", "コラボ企画"), ("season", "季節の味覚"), ("other", "その他")]
CATS = [("cafe", "カフェ", "c-cafe"), ("hotel", "ホテル", "c-hotel"), ("lux", "ホテル（高級）", "c-lux")]
SVG_LOC = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5a4.5 4.5 0 0 0-4.5 4.5c0 3.4 4.5 8.5 4.5 8.5s4.5-5.1 4.5-8.5A4.5 4.5 0 0 0 8 1.5zm0 6.2a1.7 1.7 0 1 1 0-3.4 1.7 1.7 0 0 1 0 3.4z" fill="currentColor"/></svg>'
SVG_TEA = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h13v4a6 6 0 0 1-6 6H10a6 6 0 0 1-6-6V9zm13 1h1.5a2.5 2.5 0 0 1 0 5H17" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M8 3.5c0 1.5 1.2 1.5 1.2 3M11.5 3.5c0 1.5 1.2 1.5 1.2 3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>'
SVG_EXT = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h7v7M13 3 6.5 9.5M11 9.5V13H3V5h3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
def _star(cx, cy, r, fill="none", stroke="none", sw=0):
    import math
    pts = [(cx + r * math.sin(math.radians(144 * i)), cy - r * math.cos(math.radians(144 * i))) for i in range(5)]
    d = "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z"
    return f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="miter"/>'
FLAGS = {
    "jp": '<rect width="90" height="60" fill="#fff"/><circle cx="45" cy="30" r="18" fill="#BC002D"/>',
    "gb": '<rect width="60" height="30" fill="#012169"/><path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" stroke-width="6"/><path d="M0,0 L60,30 M60,0 L0,30" stroke="#C8102E" stroke-width="2"/><path d="M30,0 v30 M0,15 h60" stroke="#fff" stroke-width="10"/><path d="M30,0 v30 M0,15 h60" stroke="#C8102E" stroke-width="6"/>',
    "fr": '<rect width="90" height="60" fill="#CE1126"/><rect width="60" height="60" fill="#fff"/><rect width="30" height="60" fill="#002654"/>',
    "it": '<rect width="90" height="60" fill="#CE2B37"/><rect width="60" height="60" fill="#fff"/><rect width="30" height="60" fill="#009246"/>',
    "ma": '<rect width="90" height="60" fill="#C1272D"/>' + _star(45, 31, 13, stroke="#006233", sw=2.6),
    "cn": '<rect width="90" height="60" fill="#DE2910"/>' + _star(15, 15, 9, fill="#FFDE00") + _star(30, 6, 3, fill="#FFDE00") + _star(36, 12, 3, fill="#FFDE00") + _star(36, 21, 3, fill="#FFDE00") + _star(30, 27, 3, fill="#FFDE00"),
}
FLAG_VB = {"gb": "0 0 60 30"}

def flag_svg(cc):
    if cc not in FLAGS: return ""
    return f'<svg viewBox="{FLAG_VB.get(cc, "0 0 90 60")}" preserveAspectRatio="none" role="img" aria-label="国旗">{FLAGS[cc]}</svg>'

SVG_CLK = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.6V8l2.4 1.6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>'

def esc(t):
    return html.escape(str(t or ""), quote=False)

def vf(t):
    return re.sub(r"［要検証(?:：([^］]*))?］",
                  lambda m: '<span class="vf">要検証</span>' + (f"［{m.group(1)}］" if m.group(1) else ""), esc(t))

def chip(state, name):
    return {"on": f'<span class="chip on">{name}</span>', "no": f'<span class="chip no">{name} ✕</span>'}.get(
        state, f'<span class="chip off">{name} ?</span>')

def ymd(t):
    try:
        return datetime.date.fromisoformat(t) if t else None
    except ValueError:
        return None

def md(x):
    return f"{x.month}/{x.day}"

def plans_of(s):
    if s.get("plans"):
        return s["plans"]
    return [{k: s.get(k) for k in ("theme", "sw", "price_min", "price_text", "wd", "we", "days_text", "time_text")}]

def agg(s):
    ps = plans_of(s)
    prices = [p["price_min"] for p in ps if p.get("price_min") is not None]
    sw = []
    for p in ps:
        for k in (p.get("sw") or ["other"]):
            if k not in sw: sw.append(k)
    if len(sw) > 1 and "other" in sw: sw.remove("other")
    return {"price_min": min(prices) if prices else None, "sw": sw,
            "wd": "on" if any(p.get("wd") == "on" for p in ps) else "off",
            "we": "on" if any(p.get("we") == "on" for p in ps) else "off"}

def ref_price(s):
    p = agg(s)["price_min"]
    if p is not None: return p
    nums = []
    for q in plans_of(s):
        m = re.search(r"([0-9][0-9,]{2,})\s*円", str(q.get("price_text") or ""))
        if m: nums.append(int(m.group(1).replace(",", "")))
    return min(nums) if nums else None

def regroup(a):
    hs = a["cats"]["hotel"]["shops"] + a["cats"]["lux"]["shops"]
    for ck in ("hotel", "lux"):
        c = a["cats"][ck]
        c["shops"] = [s for s in hs if (ck == "lux") == ((ref_price(s) or 0) >= 9000)]
        if c["shops"]: c["status"] = "ok"
        elif c["status"] == "ok": c["status"] = "none"

def check(d):
    errs = []
    sw_ok = {k for k, _ in SWEETS}; site_ok = {k for k, _ in SITES}
    per = d.get("period") or {}
    ps, pe = ymd(per.get("start")), ymd(per.get("end"))
    if not ps or not pe:
        errs.append("period の start / end がない（YYYY-MM-DD）")
    elif pe != ps + datetime.timedelta(days=40):
        errs.append(f"period の end は start の40日後（{ps + datetime.timedelta(days=40)}）にする")
    for a in d["areas"]:
        for ck, _, _ in CATS:
            c = a["cats"].get(ck)
            if c is None: errs.append(f'エリア{a["no"]} に {ck} がない'); continue
            if c["status"] not in ("ok", "none", "unchecked"): errs.append(f'エリア{a["no"]} {ck} の status が不正')
            for s in c["shops"]:
                for l in s.get("links", []):
                    if l["site"] not in site_ok: errs.append(f'{s["name"]}: site「{l["site"]}」が不正')
                for p in plans_of(s):
                    for k in (p.get("sw") or []):
                        if k not in sw_ok: errs.append(f'{s["name"]}: sw「{k}」が不正')
                    for k in ("wd", "we"):
                        if p.get(k) not in ("on", "no", "off"): errs.append(f'{s["name"]}: {k} が不正')
                    st, en = ymd(p.get("start")), ymd(p.get("end"))
                    if ps and pe and ((en and en < ps) or (st and st > pe)):
                        errs.append(f'{s["name"]}: 調査期間の外のプラン「{p.get("theme")}」が入っている')
    if errs:
        print("データに誤りがあります:\n" + "\n".join(errs)); sys.exit(1)

TODAY = None

def clean(t):
    t = str(t or "").strip()
    if re.match(r"(要確認|未確認|不明|未調査)", t): return ""
    t = re.sub(r"[（(][^（）()]*(要確認|未確認|不明)[^（）()]*[）)]", "", t)
    t = re.sub(r"[・、]\s*(要確認|未確認)", "", t)
    t = re.sub(r"[。、／・]?[^。、／（）()]*(は要確認|は未確認|は不明)", "", t)
    t = re.sub(r"[。、／・]?[^。、／（）()]*(要確認|未確認)[。]?$", "", t)
    return t.strip(" 　。、／")

def known(t):
    t = clean(t)
    return bool(t) and not re.fullmatch(r"[\s（(]*(要確認|不明|未調査|未確認|期間要確認|記載なし|曜日の記載なし|—|-)[\s）)。．]*", t)

def plan_html(p, names, i=0, n=1):
    st, en = ymd(p.get("start")), ymd(p.get("end"))
    per = p.get("period_text") or ((md(st) if st else "") + "〜" + (md(en) if en else "") if (st or en) else "")
    sw = [k for k in (p.get("sw") or []) if k != "other"]
    stat = ""
    if TODAY and (st or en):
        if st and st > TODAY: stat = '<span class="pst soon">これから</span>'
        elif not en or en >= TODAY: stat = '<span class="pst now">提供中</span>'
    no = f'<span class="pno">プラン{i + 1}／{n}</span>' if n > 1 else ""
    body = []
    if known(p.get("theme")): body.append(f'<p class="theme">{SVG_TEA}<span>{esc(clean(p["theme"]))}</span></p>')
    if known(p.get("country")): body.append(f'<p class="ctry">{esc(clean(p["country"]))}：{flag_svg(p.get("cc"))}</p>')
    if sw: body.append('<p class="swt" aria-label="スイーツの分類">' + "".join(f"<span>{names[k]}</span>" for k in sw) + "</p>")
    pt = clean(p.get("price_text")) if known(p.get("price_text")) else ""
    if p.get("price_min") is not None:
        body.append(f'<div class="price"><span class="pbig">{p["price_min"]:,}<small>円〜</small></span>' + (f'<span class="pdet">{esc(pt)}</span>' if pt else "") + "</div>")
    elif pt:
        body.append(f'<div class="price"><span class="pdet">{esc(pt)}</span></div>')
    chips = "".join(chip(p.get(k), nm) for k, nm in (("wd", "平日"), ("we", "土日祝")) if p.get(k) in ("on", "no")) or '<span class="chip off">曜日未確認</span>'
    w = []
    if chips: w.append(f'<div class="chips" aria-label="提供日">{chips}</div>')
    if known(p.get("days_text")): w.append(f'<p class="dtxt">{esc(clean(p["days_text"]))}</p>')
    if known(p.get("time_text")): w.append(f'<p class="time">{SVG_CLK}<span>{esc(clean(p["time_text"]))}</span></p>')
    if w: body.append('<div class="when">' + "".join(w) + "</div>")
    if not body and not known(per): return ""
    hd = no + (f'<p class="pper">{esc(clean(per))}</p>' if known(per) else '<p class="pper na">期間不明</p>') + stat
    return '<div class="plan">' + (f'<div class="plan-hd">{hd}</div>' if hd else "") + "".join(body) + "</div>"

def card(s, ck, cls, ym):
    g_ = agg(s)
    sw = g_["sw"]
    pk = 1 if g_["price_min"] is not None else 0
    wd = 1 if g_["wd"] == "on" else 0
    we = 1 if g_["we"] == "on" else 0
    h = [f'<article data-sw="{" ".join(sw)}" class="card {cls}" data-cat="{ck}" data-wd="{wd}" data-we="{we}" data-pk="{pk}">']
    head = f'<h4>{esc(s["name"])}</h4>' + (f'<p class="shop">{esc(s["shop"])}</p>' if s.get("shop") else "")
    h.append(f'<div class="top"><header>{head}</header></div>')  # 食べログ点数はカードに表示しない（データには残す）
    if s.get("new"): h.append(f'<p class="rnote">{ym}の調査で新規掲載</p>')
    h.append(f'<p class="loc">{SVG_LOC}{esc(s.get("station"))}</p>')
    if known(s.get("exit")): h.append(f'<div class="meet"><p><span class="mk">駅の出口</span>{vf(clean(s.get("exit")))}</p></div>')
    links = {l["site"]: l["url"] for l in s.get("links", [])}
    lk = "".join(f'<a class="lk lk-{k}" href="{html.escape(links[k])}" target="_blank" rel="noopener">{n}{SVG_EXT}</a>' for k, n in SITES if k in links)
    if lk: h.append(f'<div class="links" aria-label="予約・情報サイト">{lk}</div>')
    names = dict(SWEETS)
    ps = sorted(plans_of(s), key=lambda p: (ymd(p.get("start")) or datetime.date.min))
    ph = "".join(plan_html(p, names, i, len(ps)) for i, p in enumerate(ps))
    if ph: h.append('<div class="plans">' + ph + "</div>")
    h.append("</article>")
    return "\n".join(h)

def main():
    path = sys.argv[1]
    d = json.load(open(path, encoding="utf-8"))
    check(d)
    global TODAY
    dt = datetime.date.fromisoformat(d["generated"])
    TODAY = dt
    ps_, pe_ = ymd(d["period"]["start"]), ymd(d["period"]["end"])
    ym = f"{dt.month}月{dt.day}日"
    tot = {ck: 0 for ck, _, _ in CATS}; swc = {k: 0 for k, _ in SWEETS}; nlinks = 0
    for a in d["areas"]:
        regroup(a)
        for ck, _, _ in CATS:
            c = a["cats"][ck]
            if c["shops"] and not any(s.get("links") for s in c["shops"]): c["status"] = "unchecked"
            c["shops"] = [s for s in c["shops"] if s.get("links")]
            shops = c["shops"]
            shops.sort(key=lambda s: (agg(s)["price_min"] is None, agg(s)["price_min"] or 0))
            tot[ck] += len(shops)
            for s in shops:
                for k in agg(s)["sw"]: swc[k] += 1
                nlinks += len(s.get("links", []))
    out = ['<!doctype html><html lang="ja"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
           '<title>東京 アフタヌーンティー</title>',
           '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
           '<link href="https://fonts.googleapis.com/css2?family=Zen+Old+Mincho:wght@500;700&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">',
           "<style>" + CSS + "</style></head><body>"]
    out.append('<div class="hero"><div class="hero-in"><div>\n<h1>東京 アフタヌーンティー</h1>\n'
               f'<p class="period">{ps_.year}年{ps_.month}月{ps_.day}日〜{pe_.year}年{pe_.month}月{pe_.day}日<small>（40日間）</small></p>'
               '<p class="lead legendline"><span class="lg"><span class="chip on">平日</span> 提供あり</span><span class="lg"><span class="chip no">土日祝 ✕</span> そのプランでは提供なし</span></p></div>\n'
               f'<div class="stats"><div class="stat s-cafe"><b>{tot["cafe"]}</b><span>カフェ</span></div><div class="stat s-hotel"><b>{tot["hotel"]}</b><span>ホテル</span></div><div class="stat s-lux"><b>{tot["lux"]}</b><span>ホテル（高級）</span></div></div>\n</div></div>')
    EV = ("halloween", "xmas", "valentine", "whiteday", "collab", "season")
    def mk(keys):
        return "".join(f'<button class="fb f-x" data-sw="{k}" aria-pressed="false">{n}<span class="bc">{swc[k]}</span></button>' for k, n in SWEETS if k in keys and (swc[k] or k in ("macaron", "parfait", "scone", "valentine", "whiteday", "collab")))
    btn = mk([k for k, _ in SWEETS if k not in EV])
    btn_ev = mk(EV)
    nav = "".join(f'<a class="area-btn" href="#a{a["no"]}">{esc(a["name"]).replace("・", "・<wbr>")}</a>' for a in d["areas"])
    out.append('<div class="fpanel" id="top"><div class="fpanel-in">\n'
               '<div class="frow" role="group" aria-label="分類で絞り込み"><span class="lb">分類</span><div class="btns">'
               '<button class="fb f-cafe" data-cat="cafe" aria-pressed="true">カフェ</button><button class="fb f-hotel" data-cat="hotel" aria-pressed="true">ホテル</button><button class="fb f-lux" data-cat="lux" aria-pressed="true">ホテル（高級）</button></div></div>\n'
               '<div class="frow" role="group" aria-label="条件で絞り込み"><span class="lb">条件</span><div class="btns">'
               '<button class="fb f-x" data-x="wd" aria-pressed="false">平日に行ける</button><button class="fb f-x" data-x="we" aria-pressed="false">土日祝に行ける</button><button class="fb f-x" data-x="pk" aria-pressed="false">値段確認済</button></div></div>\n'
               f'<div class="frow" role="group" aria-label="スイーツで絞り込み"><span class="lb">スイーツ</span><div class="btns">{btn}</div><p class="hint">複数選択可（どれかに当てはまる店を表示）</p></div>\n'
               f'<div class="frow" role="group" aria-label="イベント・季節で絞り込み"><span class="lb">イベント<br>季節</span><div class="btns">{btn_ev}</div></div>\n'
               f'<nav class="frow" aria-label="エリア"><span class="lb">場所</span><div class="btns">{nav}</div></nav>\n'
               '</div></div>\n<a class="totop" href="#top">▲ 絞り込み・場所へ</a>\n<main>')
    for a in d["areas"]:
        n = sum(len(a["cats"][ck]["shops"]) for ck, _, _ in CATS)
        sec = [f'<section id="a{a["no"]}" class="area"><h2><span class="no">{a["no"]:02d}</span>{esc(a["name"])}<span class="acnt">{n}件</span></h2>']
        for ck, label, cls in CATS:
            c = a["cats"][ck]
            sec.append(f'<div class="cat {cls}" data-cat="{ck}"><h3><span class="tag">{label}</span><span class="cnt">{len(c["shops"])}件</span></h3>')
            if c["shops"]:
                sec.append('<div class="grid">' + "".join(card(s, ck, cls, ym) for s in c["shops"]) + "</div>")
            elif c["status"] == "unchecked":
                sec.append('<p class="none">未確認（確認できた範囲では該当なし）</p>')
            else:
                sec.append('<p class="none">該当なし（今回の調査で条件を満たす店を確認できず）</p>')
            sec.append("</div>")
        sec.append("</section>")
        out.append("".join(sec))
    cand = "".join(f'<li><b>{esc(c["area"])}</b>　' + (f'<a class="clink" href="{html.escape(c["url"])}" target="_blank" rel="noopener">{esc(c["name"])}{SVG_EXT}</a>' if c.get("url") else esc(c["name"])) + f'<br><small>{esc(c.get("note"))}</small></li>' for c in d.get("candidates", [])) or "<li>なし</li>"
    out.append(f'<div class="aside"><div class="box"><h2>未検証の候補</h2><ul>{cand}</ul></div></div>')
    out.append('</main>')
    out.append("<script>" + JS + "</script></body></html>")
    name = f"afternoon_tea_tokyo_{ps_.isoformat()}.html"
    open(name, "w", encoding="utf-8").write("\n".join(out))
    print(f"作成: {name}  店数 カフェ{tot['cafe']}・ホテル{tot['hotel']}・高級{tot['lux']}、リンク{nlinks}件")

main()