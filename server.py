from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn
import sqlite3
import pandas as pd
from io import BytesIO
from apscheduler.schedulers.background import BackgroundScheduler
from snownlp import SnowNLP
import json

from agent import fetch_multi_weibo, generate_summary, generate_cross_answer, fetch_current_fans, generate_multi_agent_draft, extract_keywords, record_fans_data, check_and_trigger_alert, search_candidate_users, analyze_group_query

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_PATH = "fans_trend.db"

# ================= 新增：提供候选账号列表接口 =================
@app.get("/api/search_users")
async def api_search_users(query: str):
    return {"users": search_candidate_users(query)}
# ==============================================================

# ================= 修改：添加监控接口 =================
@app.get("/api/monitor/add")
async def add_monitor(name: str):
    # 这里的 name 可以是用确认过的确切 screen_name 或者 ID
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("INSERT INTO monitor_list (name) VALUES (?)", (name.strip(),))
        conn.commit(); return {"status": "success"}
    except sqlite3.IntegrityError: 
        return {"status": "exists"}
    finally: 
        conn.close()
# =======================================================

def init_monitor_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS monitor_list (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)')
    try:
        c.execute("INSERT INTO monitor_list (name) VALUES ('蒋敦豪'), ('鹭卓'), ('欧阳娜娜')")
    except sqlite3.IntegrityError:
        pass
    conn.commit()
    conn.close()
init_monitor_db()

def daily_job():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM monitor_list")
    names = [row[0] for row in c.fetchall()]
    conn.close()
    if names:
        print(f"⏰ 定时任务触发，监控名单: {names}")
        fetch_current_fans(",".join(names))

scheduler = BackgroundScheduler()
scheduler.add_job(daily_job, 'cron', hour=8, minute=0)
scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

# 升级版：使用 GLM-4 大模型进行情感分析
def get_sentiment_counts(comments_list):
    if not comments_list:
        return {"positive": 0, "negative": 0, "neutral": 0}
    
    # 为了防止一次发太多字把 token 撑爆，只取前 15 条微博正文
    texts_to_analyze = comments_list[:15]
    
    # 构造 Prompt，强制大模型返回 JSON 格式
    prompt = f"""
    你是一个专业的社交媒体舆情分析专家。
    请分析以下微博文本的情感倾向，它们可能包含饭圈黑话（如“绝绝子”通常是正向，“割韭菜”通常是负向）。
    请严格将它们分类为三种情绪：正向(positive)、负向(negative)、中立(neutral)。
    
    待分析的文本列表：
    {json.dumps(texts_to_analyze, ensure_ascii=False)}
    
    【强制要求】
    只输出一个 JSON 格式的结果，不要包含任何 Markdown 代码块符号（如 ```json ），也不要任何多余的解释。
    格式如下：
    {{"positive": 正向数量, "negative": 负向数量, "neutral": 中立数量}}
    """
    
    try:
        # 调用你 agent.py 里已经初始化好的 client
        from agent import client 
        res = client.chat.completions.create(
            model="glm-4-flash", 
            messages=[{"role": "user", "content": prompt}], 
            temperature=0.1
        )
        
        # 解析大模型返回的 JSON
        result_text = res.choices[0].message.content.strip()
        # 容错处理：有时候大模型会自作聪明加 ```json
        result_text = result_text.replace("```json", "").replace("```", "").strip()
        
        result_dict = json.loads(result_text)
        return {
            "positive": result_dict.get("positive", 0),
            "negative": result_dict.get("negative", 0),
            "neutral": result_dict.get("neutral", 0)
        }
        
    except Exception as e:
        print(f"大模型情感分析失败，降级为中立: {e}")
        # 如果大模型挂了，直接全返回中立，防止前端崩溃
        return {"positive": 0, "negative": 0, "neutral": len(texts_to_analyze)}
    
@app.get("/api/weibo")
async def api_weibo(nicknames: str, limit: int = 5, days: int = 7):
    try:
        posts_dict, images = fetch_multi_weibo(nicknames, limit, days)
        all_names = [n.strip() for n in nicknames.replace("，", ",").split(",") if n.strip()]
        if not posts_dict: return {"posts": {}, "images": [], "summary": "⚠️ 系统未检索到任何动态。"}
        summary = generate_summary(posts_dict, all_names)
        return {"posts": posts_dict, "images": images, "summary": summary}
    except Exception as e:
        return {"error": str(e), "posts": {}, "images": [], "summary": "抓取异常"}

@app.get("/api/chat")
async def api_chat(q: str):
    try:
        keywords = extract_keywords(q)
        search_query = ",".join(keywords)
        w_dict, _ = fetch_multi_weibo(search_query, limit=3, days=30)
        full_ans = ""
        for chunk in generate_cross_answer(q, w_dict): full_ans += chunk
        return {"answer": full_ans}
    except Exception as e:
        return {"answer": f"检索错误：{e}"}

@app.get("/api/monitor/list")
async def get_monitor_list():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT name FROM monitor_list")
    names = [row[0] for row in c.fetchall()]; conn.close()
    return {"names": names}

@app.get("/api/monitor/add")
async def add_monitor(name: str):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("INSERT INTO monitor_list (name) VALUES (?)", (name.strip(),))
        conn.commit(); return {"status": "success"}
    except sqlite3.IntegrityError: return {"status": "exists"}
    finally: conn.close()

@app.get("/api/monitor/remove")
async def remove_monitor(name: str):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("DELETE FROM monitor_list WHERE name=?", (name,))
    c.execute("DELETE FROM trends WHERE name=?", (name,))
    conn.commit(); conn.close(); return {"status": "success"}

@app.get("/api/fans/current")
async def api_fans_current():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT name FROM monitor_list")
    names = [row[0] for row in c.fetchall()]; conn.close()
    if not names: return {"current": []}
    return {"current": fetch_current_fans(",".join(names))}

@app.get("/api/trend")
async def api_trend():
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT date, name, followers FROM trends ORDER BY date ASC", conn)
        conn.close()
        df['followers'] = pd.to_numeric(df['followers'], errors='coerce')
        return {"trends": df.to_dict('records')}
    except Exception as e: return {"error": str(e), "trends": []}

@app.get("/api/export/excel")
async def export_excel():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM trends", conn); conn.close()
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Fans_Trend')
    output.seek(0)
    return StreamingResponse(output, headers={'Content-Disposition': 'attachment; filename="fans_trend.xlsx"'}, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.get("/api/generate_draft")
async def api_generate_draft(nicknames: str):
    try:
        posts_dict, _ = fetch_multi_weibo(nicknames, limit=3, days=7)
        target_names = [n.strip() for n in nicknames.replace("，", ",").split(",") if n.strip()]
        # 调用多智能体
        draft = generate_multi_agent_draft(posts_dict, target_names)
        return {"draft": draft}
    except Exception as e: return {"draft": f"生成失败: {e}"}

@app.get("/api/sentiment")
async def api_sentiment():
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT name FROM monitor_list")
        names = [row[0] for row in c.fetchall()]; conn.close()
        if not names: return {"positive": 0, "negative": 0, "neutral": 0}
        
        posts_dict, _ = fetch_multi_weibo(",".join(names), limit=5, days=7)
        all_texts = []
        for name, posts in posts_dict.items():
            for post in posts:
                text = post.get('text') or post.get('content')
                if text: all_texts.append(text)
        if not all_texts: all_texts = ["今天天气真不错", "这个剪辑太烂了", "期待下一期节目"]

        result = get_sentiment_counts(all_texts)
        # 🌟 核心升级：主动触发预警工具
        check_and_trigger_alert(result['positive'], result['negative'], result['neutral'])
        return result
    except Exception as e:
        print(f"情感分析出错: {e}")
        return {"positive": 0, "negative": 0, "neutral": 0, "error": str(e)}

# 🌟 新增：获取最新的预警信息
@app.get("/api/alerts")
async def api_alerts():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT time, message FROM alerts ORDER BY id DESC LIMIT 3")
    alerts = [{"time": row[0], "message": row[1]} for row in c.fetchall()]
    conn.close()
    return {"alerts": alerts}

@app.get("/api/check_group")
async def api_check_group(query: str):
    return analyze_group_query(query)

@app.get("/api/test-browser")
def test_browser():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # 尝试启动 chromium
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://weibo.com", timeout=15000)
            title = page.title()
            browser.close()
            return {"ok": True, "title": title, "message": "浏览器启动成功，微博访问正常！"}
    except Exception as e:
        # 这里会打印出真实的报错，比如缺库、找不到浏览器等
        print(f"❌ 浏览器测试失败: {e}") 
        return {"ok": False, "error": str(e)}

app.mount("/", StaticFiles(directory="public", html=True), name="public")

if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)