#!/usr/bin/env python3
# 全局刷新库：重抓 Best Designs On X（时间窗口）+ Refero（API 翻页）+ posts.design（sitemap 近期）
# + 保留 others，合并去重后安全重写 HTML。供 server.py 的 /api/refresh 与命令行调用。
import re, json, os, sys, html as ihtml, datetime, concurrent.futures, urllib.request, urllib.parse, urllib.error
from collections import Counter

WS = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(WS, "design-resources-dashboard.html")
SITEMAP_CACHE = os.path.join(WS, ".cache", "posts_sitemap.xml")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}

SUPABASE = "https://tuzpqmdnxvlzwqthgseg.supabase.co"
ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InR1enBxbWRu"
        "eHZsendxdGhnc2VnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MzUxOTY4MjYsImV4cCI6MjA1MDc3MjgyNn0."
        "rIjO0FCY9rPgsJXCxBho3sCRiepy3s319_BoK6DPZ-U")
TODAY = datetime.datetime.now(datetime.timezone.utc).date()

# ---------- 内容类型分类 ----------
RULES = {
    "Dashboard":[r"\bdashboard",r"analytics",r"\badmin\b",r"metrics",r"data viz",r"\bcharts?\b",r"reporting",r"monitoring",r"\bkpi\b",r"\binsights?\b",r"\bcrm\b",r"\bsaas\b",r"\bpanel\b"],
    "E-commerce":[r"e-?commerce",r"\bshop\b",r"\bshopify",r"\bstore\b",r"checkout",r"\bcart\b",r"product page",r"\bpricing\b",r"\bbuy\b",r"\bcommerce\b"],
    "Branding":[r"\blogos?\b",r"branding",r"brand identity",r"\bbrand\b",r"wordmark",r"rebrand"],
    "Landing":[r"landing page",r"\blanding\b",r"hero section",r"waitlist",r"\bsign ?up\b",r"onboarding",r"\bhero\b"],
    "Typography":[r"typography",r"\bfonts?\b",r"typeface",r"lettering",r"\btype\b",r"\bglyph"],
    "AI":[r"\bai\b",r"\bgpt",r"claude",r"\bllm",r"\bagent",r"chatgpt",r"generative",r"copilot",r"openai",r"\bprompt"],
    "Component":[r"ui kit",r"\bcomponents?\b",r"design system",r"\blibrary\b",r"figma community",r"design tokens",r"\bcomponent\b"],
    "3D":[r"\b3[- ]?d\b",r"three\.js",r"webgl",r"blender",r"\brender",r"isometric",r"\bc4d\b"],
    "Illustration":[r"illustration",r"illustrator",r"\bart\b",r"\bdrawing",r"\bdoodle",r"icon set",r"\bicons\b"],
    "App":[r"\bapps?\b",r"\bios\b",r"\bandroid\b",r"\bmobile\b",r"iphone",r"\bphone\b",r"\bscreen\b",r"uikit"],
    "Web":[r"website",r"web app",r"webpage",r"\bsite\b",r"portfolio",r"\bblog\b",r"\bweb\b"],
    "UI / Interface":[r"\binterface",r"\bui\b",r"\bux\b",r"\bsidebar",r"\binbox",r"\bbutton",r"\bcursor",r"\bcarousel",r"\btestimonials?\b",r"\bwidget",r"\bmenu\b",r"\blayout\b",r"\bcard\b",r"\bmodal\b",r"\bform\b",r"\binput\b",r"\btoggle",r"\blist\b",r"\btable\b",r"\boverview",r"\btracking",r"\bscanning",r"\bbriefing",r"\bpackage\b",r"\brow\b",r"\bnav\b",r"\bnavigation"],
    "Animation":[r"\banimation",r"\bmotion\b",r"\binteraction",r"\bmorph",r"\bshader",r"\btransition",r"\bhover\b",r"\bswipe",r"\bspring\b",r"\bbento\b",r"\bstoryboard",r"\bloop",r"\bparallax",r"\bkinetic",r"\bgif\b",r"\brotation"],
}
CAP = 4
SITE_MAP = {"navbar":["Component"],"cta":["Component"],"supahero":["Landing"]}
def classify(it):
    d = it.get("detail") or {}
    parts = [it.get("title",""), it.get("author","")] + (it.get("source") or [])
    parts.append(d.get("text",""))
    if d.get("tags"): parts += d["tags"]
    if d.get("md"): parts.append(d["md"][:20000])
    hay = " ".join(parts).lower()
    cats = []
    for cat, pats in RULES.items():
        for p in pats:
            if re.search(p, hay):
                cats.append(cat); break
    site = it.get("site","")
    if site in SITE_MAP:
        for c in SITE_MAP[site]:
            if c not in cats: cats.append(c)
    seen=set(); cats=[c for c in cats if not (c in seen or seen.add(c))]
    if len(cats) > CAP: cats = cats[:CAP]
    if not cats: cats.append("Other")
    return cats

def fetch_url(url, timeout=30, binary=False):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read() if binary else r.read().decode("utf-8", "ignore")
    except Exception:
        # 回退 curl：绕过部分站点（如 posts.design）urllib 的 SSL 握手失败 / 超时
        import subprocess
        out = subprocess.run(["curl","-sL","--max-time",str(timeout),"-A",UA["User-Agent"],url],
                             capture_output=True)
        return out.stdout if binary else out.stdout.decode("utf-8", "ignore")

# ---------- bdx ----------
def build_item(r):
    media = r.get("media") or []
    vids = [m for m in media if m.get("type") in ("video","animated_gif")]
    phos = [m for m in media if m.get("type")=="photo"]
    video_url = vids[0].get("video_url","") if vids else ""
    image = (vids[0].get("cover","") if vids else (phos[0].get("original_image_url") or phos[0].get("image","") if phos else r.get("avatar","")))
    inter = r.get("interaction") or {}
    likes, views = inter.get("likes"), inter.get("views")
    tags = r.get("tags") or []
    handle = r.get("handle","")
    author_name = r.get("author_name","")
    tweet = (r.get("tweet_text") or "").strip()
    title = (tweet.split("\n")[0][:90] if tweet else f"@{handle} showcase")
    author = f"{author_name} @{handle}".strip()
    link = "https://x.com" + r.get("post_url","")
    source = ["X"] + (["Motion"] if vids else [])
    posted = (r.get("time") or "")[:10]
    meta = [["Author",author],["Handle","@"+handle]]
    if likes is not None: meta.append(["Likes",f"{likes:,}"])
    if views is not None: meta.append(["Views",f"{views:,}"])
    if tags: meta.append(["Tags",", ".join(tags)])
    meta.append(["Posted",posted]); meta.append(["Original",link])
    it = {
        "site":"bestdesignsonx","siteUrl":"https://bestdesignsonx.com","source":source,
        "title":title,"author":author,"video":video_url,"image":image,"link":link,
        "detail":{"kind":"post","text":tweet,"tags":tags,"meta":meta},
    }
    try:
        it["ts"] = int(datetime.datetime.strptime(posted,"%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp())
    except Exception:
        it["ts"] = None
    it["uid"] = str(r.get("id") or link)
    it["fetched"] = TODAY.isoformat()
    it["cats"] = classify(it)
    return it

def fetch_bdx(days):
    from_date = (TODAY - datetime.timedelta(days=days)).isoformat()
    params = {
        "select":"id,author_name,handle,tweet_text,time,post_url,interaction,media,avatar,tags,status",
        "status":"eq.Published",
        "created_at":f"gte.{from_date}",
        "order":"created_at.desc",
        "limit":"300",
    }
    url = f"{SUPABASE}/rest/v1/bestdesignsonx?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"apikey":ANON,"Authorization":f"Bearer {ANON}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"Supabase 请求失败: {e}")
    return [build_item(r) for r in rows]

# ---------- refero (API 翻页) ----------
from urllib.parse import urlparse
def fetch_refero(max_pages=10):
    items=[]; seen=set(); page=1
    while page<=max_pages:
        try:
            d=json.loads(fetch_url(f"https://styles.refero.design/api/styles?page={page}"))
        except Exception as e:
            print("refero page",page,"err",e); break
        styles=d.get("styles",[])
        if not styles: break
        for s in styles:
            sid=s["id"]
            if sid in seen: continue
            seen.add(sid)
            title=s.get("siteName") or "Untitled"
            domain=urlparse(s.get("url","")).netloc.replace("www.","") or "Refero Styles"
            video=s.get("previewVideoUrl") or ""
            thumb=s.get("thumbnailUrl") or s.get("screenshotUrl") or ""
            link=f"https://styles.refero.design/style/{sid}"
            it={
                "site":"styles.refero","siteUrl":"https://styles.refero.design","source":[],
                "title":title,"author":domain,"video":video,
                "image":(thumb if not video else ""),"link":link,
                "detail":{"kind":"","tags":[],"text":title,"meta":[["Source","Refero Styles"],["Site",domain]],"md":""},
                "ts":None,"uid":link,"fetched":TODAY.isoformat(),
            }
            it["cats"]=classify(it)
            items.append(it)
        np_=d.get("nextPage")
        if not np_: break
        page=np_
    return items

# ---------- posts.design (sitemap 近期) ----------
def fetch_posts(recent_days=45, cap=200):
    # 下载 sitemap（失败回退缓存）
    sm=None
    try:
        sm=fetch_url("https://posts.design/sitemap.xml", timeout=25)
    except Exception:
        try:
            sm=open(SITEMAP_CACHE,encoding="utf-8").read()
        except Exception:
            return []
    slugs_dates=sorted(set(re.findall(r'https://posts\.design/([a-z0-9-]+-(\d{4}-\d\d-\d\d))', sm)),
                       key=lambda x:x[1], reverse=True)
    cutoff=(TODAY-datetime.timedelta(days=recent_days)).isoformat()
    pick=[s for s,d in slugs_dates if d>=cutoff][:cap]
    def fetch_post(slug):
        url=f"https://posts.design/{slug}"
        try: h=fetch_url(url)
        except Exception: return None
        tm=re.search(r'<meta property="og:title" content="([^"]*)"',h)
        im=re.search(r'<meta property="og:image" content="([^"]*)"',h)
        vm=re.search(r'<meta property="og:video" content="([^"]*)"',h)
        title=ihtml.unescape(tm.group(1)).replace(" - posts.design","") if tm else slug
        author=title.split(":")[0].strip() if ":" in title else ""
        image=im.group(1) if im else ""
        video=vm.group(1) if vm else ""
        dm=re.search(r'(20\d\d-\d\d-\d\d)$',slug)
        ts=None
        if dm:
            try: ts=int(datetime.datetime.strptime(dm.group(1),"%Y-%m-%d").timestamp())
            except: pass
        it={
            "site":"posts.design","siteUrl":"https://posts.design","source":[],
            "title":title,"author":author,"video":video,
            "image":(image if not video else ""),"link":url,
            "detail":{"kind":"","tags":[],"text":title,"meta":[["Source","posts.design"]],"md":""},
            "ts":ts,"uid":url,"fetched":TODAY.isoformat(),
        }
        it["cats"]=classify(it)
        return it
    out=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=14) as ex:
        for r in ex.map(fetch_post, pick):
            if r: out.append(r)
    return out

# ---------- motionsites.ai (backgrounds：前端写死的 CloudFront mp4) ----------
def fetch_motionsites():
    # /backgrounds 页面 HTML 内含 backgrounds chunk 路径（assets/backgrounds-<hash>.js），从中提取视频数组
    try:
        page=fetch_url("https://motionsites.ai/backgrounds", timeout=25)
    except Exception:
        try: page=fetch_url("https://motionsites.ai/", timeout=25)
        except Exception as e: print("motionsites page err", e); return []
    m=re.search(r'(?:src|href)="(/assets/backgrounds-[A-Za-z0-9_-]+\.js)"', page)
    js=None
    if m:
        try: js=fetch_url("https://motionsites.ai"+m.group(1), timeout=25)
        except Exception as e: print("motionsites chunk err", e)
    if not js: js=page  # 兜底：直接从页面抓 cloudfront mp4
    urls=re.findall(r'https://d8j0ntlcm91z4\.cloudfront\.net/[^`"\'\s]+?\.mp4', js)
    items=[]
    for u in dict.fromkeys(urls):  # 去重保序
        fn=u.rsplit('/',1)[-1]
        dm=re.search(r'(\d{4})(\d{2})(\d{2})', fn)
        date=None; ts=None
        if dm:
            date=f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
            try: ts=int(datetime.datetime.strptime(date,"%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp())
            except Exception: ts=None
        title=f"AI Animated Background · {date}" if date else "AI Animated Background"
        it={
            "site":"motionsites","siteUrl":"https://motionsites.ai/backgrounds","source":[],
            "title":title,"author":"MotionSites AI","video":u,"image":"",
            "link":"https://motionsites.ai/backgrounds",
            "detail":{"kind":"motion","tags":["Background","Loop","Hero"],
                      "text":"MotionSites AI 生成的网站动效背景视频，可用于 Hero / 首屏循环背景。",
                      "meta":[["Source","MotionSites"],["Date",date or ""]]},
            "ts":ts,"uid":u,"fetched":TODAY.isoformat(),
        }
        it["cats"]=classify(it)
        items.append(it)
    return items

# ---------- recent.design (sitemap 近期 + 详情页取本条目 mp4/poster) ----------
def _pick_recent_video(videos):
    best=None; bw=0
    for v in videos:
        m=re.search(r'/0/(\d+)x(\d+)\.mp4', v)
        if not m: continue
        w=int(m.group(1))
        if w>=360 and (best is None or abs(w-960)<abs(bw-960)):
            best=v; bw=w
    return best

def fetch_recent(recent_days=30, cap=120):
    try:
        sm=fetch_url("https://recent.design/sitemap.xml", timeout=30)
    except Exception as e:
        print("recent sitemap err", e); return []
    pairs=re.findall(r'<url>\s*<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>', sm)
    cutoff=(TODAY-datetime.timedelta(days=recent_days)).isoformat()[:10]
    urls=[(loc, lm[:10]) for loc, lm in pairs if lm[:10]>=cutoff]
    urls.sort(key=lambda x: x[1], reverse=True)
    urls=urls[:cap]
    def fetch_one(loc_date):
        loc, d = loc_date
        try: h=fetch_url(loc, timeout=25)
        except Exception: return None
        sid=loc.rstrip('/').split('/')[-1].split('-')[0]
        tm=re.search(r'property="og:title"\s+content="([^"]*)"', h)
        title=ihtml.unescape(tm.group(1)) if tm else loc.split('/')[-1]
        title=re.sub(r'\s*[—-]\s*Recent$', '', title).strip()
        own=[v for v in re.findall(r'https?://[^\s"\'<>]+\.mp4', h) if f'/items/{sid}/' in v]
        video=_pick_recent_video(own)
        im=re.search(r'property="og:image"\s+content="([^"]*)"', h)
        image=im.group(1) if im else ""
        it={
            "site":"recent.design","siteUrl":"https://recent.design","source":[],
            "title":title,"author":"Recent","video":video or "",
            "image":(image if not video else ""),
            "link":loc,
            "detail":{"kind":"","tags":[],"text":title,"meta":[["Source","recent.design"],["Date",d]],"md":""},
            "ts":None,"uid":loc,"fetched":TODAY.isoformat(),
        }
        it["cats"]=classify(it)
        return it
    out=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for r in ex.map(fetch_one, urls):
            if r: out.append(r)
    return out

# ---------- 读取现有 HTML 的 others（保留） ----------
def load_others():
    s=open(DASH,encoding="utf-8").read()
    idx=s.index("const ITEMS"); k=s.index("[",idx)
    depth=0;j=k;instr=False;esc=False
    while j<len(s):
        c=s[j]
        if esc: esc=False;j+=1;continue
        if c=="\\": esc=True;j+=1;continue
        if c=='"': instr=not instr;j+=1;continue
        if not instr:
            if c=="[": depth+=1
            elif c=="]":
                depth-=1
                if depth==0: j+=1;break
        j+=1
    data=json.loads(s[k:j])
    LIVE=("bestdesignsonx","styles.refero","posts.design","motionsites","recent.design")
    existing={site:[] for site in LIVE}  # 兜底：保留文件内同站已有数据
    others=[]
    for it in data:
        st=it.get("site")
        if st in existing:
            existing[st].append(it)
        else:
            it["fetched"]=TODAY.isoformat()  # 刷新抓取日
            others.append(it)
    return s,k,j,others,existing

# ---------- 主入口 ----------
def run_refresh(days=None, auto_expand=True):
    log=[]
    # bdx 时间窗口
    if days:
        bdx=fetch_bdx(days); used=days
    else:
        w7=fetch_bdx(7)
        used=7 if len(w7)>=30 else 14
        bdx=fetch_bdx(used) if used==14 else w7
    log.append(f"bdx 近{used}天 {len(bdx)} 条")
    refero=fetch_refero()
    log.append(f"refero {len(refero)} 条")
    posts=fetch_posts()
    log.append(f"posts {len(posts)} 条")
    motionsites=fetch_motionsites()
    log.append(f"motionsites {len(motionsites)} 条")
    recents=fetch_recent()
    log.append(f"recents {len(recents)} 条")
    s,k,j,others,existing=load_others()
    log.append(f"others 保留 {len(others)} 条")

    # 安全回退：某源抓空时，保留文件里同站的已有数据，绝不留白
    fresh={"bestdesignsonx":bdx,"styles.refero":refero,"posts.design":posts,"motionsites":motionsites,"recent.design":recents}
    for site in fresh:
        if not fresh[site] and existing.get(site):
            log.append(f"⚠ {site} 抓取为空，回退保留文件中 {len(existing[site])} 条")
            fresh[site]=existing[site]
    merged=others+fresh["bestdesignsonx"]+fresh["styles.refero"]+fresh["posts.design"]+fresh["motionsites"]+fresh["recent.design"]
    u=set();final=[]
    for it in merged:
        if it.get("uid") in u: continue
        u.add(it.get("uid"));final.append(it)
    new_arr=json.dumps(final,ensure_ascii=False)
    open(DASH,"w",encoding="utf-8").write(s[:k]+new_arr+s[j:])
    by_site=dict(Counter(i["site"] for i in final))
    vids=sum(1 for i in final if i.get("video"))
    return {"ok":True,"total":len(final),"videos":vids,"bySite":by_site,
            "window":used,"log":log,"today":TODAY.isoformat()}

if __name__=="__main__":
    days=int(sys.argv[1]) if len(sys.argv)>1 else None
    res=run_refresh(days)
    print(json.dumps(res,ensure_ascii=False,indent=2))
