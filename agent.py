import os
import re
import base64
import sqlite3
import requests
import concurrent.futures
import json
from datetime import datetime, timedelta
from openai import OpenAI
from dotenv import load_dotenv
from crawl4weibo import WeiboClient

# ================= 绝对生效的本地字典 =================
GROUPS = {
    "十个勤天": ["蒋敦豪", "鹭卓", "李耕耘", "李昊", "赵一博", "卓沅", "赵小童", "何浩楠", "陈少熙", "王一珩", "十个勤天"],
    "时代少年团": ["马嘉祺", "丁程鑫", "宋亚轩", "刘耀文", "张真源", "严浩翔", "贺峻霖", "时代少年团"],
    "TFBOYS": ["王俊凯", "王源", "易烊千玺", "TFBOYS"],
    "exo": ["金钟大", "边伯贤", "朴灿烈", "都暻秀", "金钟仁", "吴世勋", "金俊勉", "张艺兴", "EXO"], 
    "EXO": ["金钟大", "边伯贤", "朴灿烈", "都暻秀", "金钟仁", "吴世勋", "金俊勉", "张艺兴", "EXO"]
}

def expand_names(nicknames_str):
    names = [n.strip() for n in re.split(r'[,，\s]+', nicknames_str) if n.strip()]
    expanded_names = []
    for name in names:
        if name in GROUPS:
            expanded_names.extend(GROUPS[name])
        else:
            expanded_names.append(name)
    return list(set(expanded_names))

def analyze_group_query(query):
    # 优先查本地字典，0.01秒瞬间返回
    if query in GROUPS:
        return {
            "is_group": True,
            "group_name": query,
            "members": GROUPS[query]
        }

    # 如果本地没命中，再去调大模型
    prompt = f"""
    你是一个智能数据解析助手。请判断用户输入的词 "{query}" 是否为一个偶像团体、乐队或多人组合。
    如果是，请提取官方名和全部成员名。
    【强制要求】如果不是组合或你不确定，必须返回 is_group: false，绝对禁止胡编乱造。
    必须严格输出 JSON 格式（不要 Markdown 符号）：
    {{"is_group": true, "group_name": "官方名", "members": ["成员1", "成员2"]}}
    """
    try:
        res = client.chat.completions.create(
            model="glm-4-flash",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        result_text = res.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(result_text)
    except Exception as e:
        print(f"组合解析失败: {e}")
        return {"is_group": False, "group_name": "", "members": []}

load_dotenv()
client = OpenAI(
    api_key=os.getenv("ZHIPU_API_KEY"),
    base_url="https://open.bigmodel.cn/api/paas/v4/"
)

DB_PATH = "fans_trend.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS trends (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, name TEXT, followers INTEGER)')
    # 新增：预警日志表
    c.execute('CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, message TEXT)')
    # 新增：用户记忆/上下文表
    c.execute('CREATE TABLE IF NOT EXISTS user_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT, context TEXT)')
    conn.commit()
    conn.close()

init_db()

def parse_followers_count(f_str):
    if not f_str: return 0
    if isinstance(f_str, int): return f_str
    f_str = str(f_str).strip()
    try:
        if '亿' in f_str: return int(float(f_str.replace('亿', '')) * 100000000)
        if '万' in f_str or 'w' in f_str.lower(): return int(float(f_str.lower().replace('万', '').replace('w', '')) * 10000)
        return int(float(f_str))
    except: return 0

def record_fans_data(name, followers):
    date_str = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM trends WHERE date=? AND name=?", (date_str, name))
    c.execute("INSERT INTO trends (date, name, followers) VALUES (?, ?, ?)", (date_str, name, followers))
    conn.commit()
    conn.close()

def url_to_base64(img_url, referer="https://weibo.com/"):
    if not img_url: return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Referer": referer}
        response = requests.get(img_url, headers=headers, timeout=10)
        if response.status_code == 200:
            return f"data:image/jpeg;base64,{base64.b64encode(response.content).decode('utf-8')}"
    except: pass
    return ""

def fetch_current_fans(nicknames_str):
    # 1. 自动展开组合
    nicknames = expand_names(nicknames_str)
    wb = WeiboClient()
    current_data = []
    
    # 2. 定义单个用户抓取任务
    def fetch_single(name):
        try:
            users = wb.search_users(name, count=1)
            if users:
                user = users[0]
                followers = parse_followers_count(getattr(user, 'followers_count', 0))
                if followers > 0:
                    record_fans_data(user.screen_name, followers)
                    return {"name": user.screen_name, "followers": followers}
        except Exception as e:
            print(f"⚠️ 获取 {name} 失败: {e}")
        return None

    # 3. 使用线程池并发抓取（解决速度慢的问题）
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(fetch_single, nicknames)
        for res in results:
            if res:
                current_data.append(res)
                
    return current_data

def fetch_multi_weibo(nicknames_str, limit=5, days=7):
    nicknames = [n.strip() for n in re.split(r'[,，\s]+', nicknames_str) if n.strip()]
    wb = WeiboClient()
    result_dict = {}
    all_images = []
    time_threshold = datetime.now() - timedelta(days=days)

    for name in nicknames:
        try:
            search_name = name
            users = wb.search_users(search_name, count=1)
            if not users and len(name) > 3:
                search_name = name[-3:]
                users = wb.search_users(search_name, count=1)
            if not users: continue
            
            user = users[0]
            user_posts = []
            for page in range(1, 3): 
                if len(user_posts) >= limit: break
                posts = wb.get_user_posts(user.id, page=page, expand=True)
                for p in posts:
                    if len(user_posts) >= limit: break
                    p_time = p.created_at
                    if isinstance(p_time, str):
                        try: dt = datetime.strptime(p_time, "%a %b %d %H:%M:%S %z %Y").replace(tzinfo=None)
                        except: dt = datetime.now()
                    else: dt = p_time.replace(tzinfo=None)
                    
                    if dt < time_threshold: continue
                    clean_text = re.sub(r'<[^>]+>', '', p.text).strip()
                    if not clean_text: continue
                    
                    img_base64 = ""
                    if getattr(p, 'pic_urls', []):
                        pic = p.pic_urls[0]
                        img_url = pic.get('large', {}).get('url') if isinstance(pic, dict) else pic
                        if img_url:
                            img_url = img_url.replace("/thumb150/", "/large/").replace("/orj360/", "/large/")
                            img_base64 = url_to_base64(img_url)
                            if img_base64: all_images.append(img_base64)
                        
                    user_posts.append({
                        "member": user.screen_name, "content": clean_text, 
                        "time": dt.strftime("%Y-%m-%d"), "url": f"https://weibo.com/{user.id}/{p.bid}",
                        "image": img_base64
                    })
            if user_posts: result_dict[user.screen_name] = user_posts
        except Exception as e:
            print(f"⚠️ 抓取 {name} 发生异常: {e}")
            continue
    return result_dict, all_images

# ==========================================
# 🌟 核心升级 1：多智能体协作 (Multi-Agent)
# ==========================================
def generate_multi_agent_draft(posts_dict, target_names):
    if not posts_dict: return "近期暂无动态，建议发布一条考古或日常问候语。"
    
    context = ""
    for name, posts in posts_dict.items():
        for p in posts[:2]: context += f"[{name}] {p['content'][:100]}\n"

    # Agent 1: 文案主笔 (Writer)
    writer_prompt = f"""
    你是一个资深的“十个勤天”粉丝站运营者。
    请根据以下抓取到的成员动态（涉及：{target_names}），写一段适合发布在微博的文案。
    【要求】1. 带话题 #十个勤天# #种地吧#。2. 语气治愈真诚。3. 适当分段带 Emoji。
    动态数据：{context}
    """
    try:
        res_writer = client.chat.completions.create(model="glm-4-flash", messages=[{"role": "user", "content": writer_prompt}], temperature=0.7)
        draft_v1 = res_writer.choices[0].message.content.strip()
    except Exception as e:
        return f"主笔生成失败: {e}"

    # Agent 2: 毒舌主编 (Critic)
    critic_prompt = f"""
    你是一个极其严苛的微博文案主编。你的任务是审查以下文案：
    【文案】：{draft_v1}
    【审查标准】：
    1. 是否包含了 #十个勤天# 和 #种地吧# 这两个绝对话题？
    2. 语气是否足够饭圈化？是否带够了 Emoji？
    3. 有没有错别字？
    如果满足所有标准，直接原样输出文案。如果不满足，请**直接输出修改后的最终完美版本**，绝对不要写任何“修改意见”或多余的解释文字。
    """
    try:
        res_critic = client.chat.completions.create(model="glm-4-flash", messages=[{"role": "user", "content": critic_prompt}], temperature=0.3)
        final_draft = res_critic.choices[0].message.content.strip()
        return final_draft
    except Exception as e:
        return draft_v1 # 如果主编挂了，退回主笔的版本

# ==========================================
# 🌟 核心升级 2：主动预警工具 (Tool Use)
# ==========================================
def check_and_trigger_alert(pos, neg, neu):
    """如果负面情绪过多，触发预警并存入数据库"""
    total = pos + neg + neu
    if total > 0 and (neg / total) >= 0.3 and neg >= 2:  # 负面占比超30%且至少有2条
        alert_msg = f"⚠️ 负面舆情预警：当前负面情绪占比达 {(neg/total)*100:.1f}%，请立即检查评论区！"
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # 避免短时间内重复触发
        c.execute("SELECT count(*) FROM alerts WHERE time > datetime('now', '-1 hour')")
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO alerts (time, message) VALUES (datetime('now', 'localtime'), ?)", (alert_msg,))
            conn.commit()
            print(alert_msg)
        conn.close()

# 其他原有 AI 功能保持不变
def generate_summary(posts_dict, all_nicknames):
    if not posts_dict: return "⚠️ 未检索到有效动态。"
    context = ""
    for name in all_nicknames:
        context += f"\n【{name}】\n" + "\n".join([p['content'][:100] for p in posts_dict.get(name, ["（未抓取到动态）"])])
    prompt = f"你是社交媒体课代表。请根据数据写一段【300字以上】的详细总结。必须提及名单中的所有人：{', '.join(all_nicknames)}。数据：{context}"
    try:
        res = client.chat.completions.create(model="glm-4-flash", messages=[{"role": "user", "content": prompt}], temperature=0.6)
        return res.choices[0].message.content.strip()
    except: return "总结生成失败。"

def extract_keywords(question):
    prompt = f"请从用户的提问中，提取出需要在微博搜索的“人名”或“核心关键词”。如果有多个，用英文逗号隔开。不要输出任何其他多余的解释。问题：{question}"
    try:
        res = client.chat.completions.create(model="glm-4-flash", messages=[{"role": "user", "content": prompt}], temperature=0.1)
        res_text = res.choices[0].message.content.strip()
        return [k.strip() for k in res_text.replace("，", ",").split(",") if k.strip()]
    except: return [question]

def generate_cross_answer(question, w_dict):
    if not w_dict: return "抱歉，没有检索到相关数据。"
    context = "【微博数据】\n"
    for name, posts in w_dict.items():
        for p in posts: context += f"[{name}] {p['content'][:100]}... 来源:{p['url']}\n"
    prompt = f"你是微博搜索助手。严格根据数据回答。使用 Markdown，事实后附 `[来源](链接)`。\n问题：{question}\n数据：{context}"
    try:
        res = client.chat.completions.create(model="glm-4-flash", messages=[{"role": "user", "content": prompt}], temperature=0.3, stream=True)
        for chunk in res:
            if chunk.choices[0].delta.content: yield chunk.choices[0].delta.content
    except Exception as e:
        yield f"生成失败: {e}"

# ================= 新增：搜索候选账号列表 =================
def search_candidate_users(query):
    """仅搜索不抓取，用于用户前端确认"""
    wb = WeiboClient()
    try:
        users = wb.search_users(query, count=5) # 最多返回5个候选
        result = []
        for u in users:
            result.append({
                "id": str(u.id),
                "screen_name": u.screen_name,
                "followers": parse_followers_count(getattr(u, 'followers_count', 0)),
                "avatar": getattr(u, 'profile_image_url', '')
            })
        # 🌟 核心优化：按照粉丝数从大到小排序，官方号大概率在第一！
        result.sort(key=lambda x: x['followers'], reverse=True)
        return result
    except Exception as e:
        print(f"搜索候选失败: {e}")
        return []
# =======================================================

# ================= 新增：大模型智能组合解析 Agent =================
def analyze_group_query(query):
    """
    利用大模型判断用户输入是否为组合，并拆解成员。
    """
    # 1. 先查本地字典，如果命中了直接返回，速度最快
    if query in GROUPS:
        return {
            "is_group": True,
            "group_name": query,
            "members": GROUPS[query]
        }

    # 2. 本地没命中，调用大模型进行推理（Zero-shot 拆解）
    prompt = f"""
    你是一个智能数据解析助手。请判断用户输入的词 "{query}" 是否为一个已知的偶像团体、乐队、或者多人组合。
    如果是组合，请提取出该组合的官方名称，以及尽可能准确的全部成员真实姓名（如果有官方微博账号名，请使用官方名，例如“种地吧蒋敦豪”）。
    如果不是组合（只是一个普通的人名），请将 is_group 设置为 false。

    【输出要求】
    必须严格输出 JSON 格式，不要包含任何 Markdown 代码块符号（如 ```json）。格式如下：
    {{
        "is_group": true,
        "group_name": "组合的官方名称",
        "members": ["成员1", "成员2", "成员3"]
    }}
    如果判断不是组合，输出：
    {{
        "is_group": false,
        "group_name": "",
        "members": []
    }}
    """
    try:
        res = client.chat.completions.create(
            model="glm-4-flash",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        result_text = res.choices[0].message.content.strip()
        result_text = result_text.replace("```json", "").replace("```", "").strip()
        result_dict = json.loads(result_text)
        return result_dict
    except Exception as e:
        print(f"组合解析失败，降级为单人: {e}")
        return {"is_group": False, "group_name": "", "members": []}
    
