import json
import urllib.request
import threading
import time
from datetime import datetime, timedelta
from database import get_db_connection

# --- 1. Email 報告發送邏輯 ---
def send_daily_report():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT key, value FROM settings")
        config = dict(cur.fetchall())
        api_key = config.get('resend_api_key', '').strip()
        to_email = config.get('report_email', '').strip()
        if not api_key or not to_email: 
            print("❌ 未設定 Email 或 API Key，取消發送報表")
            return

        # 計算台灣時間與 UTC 時間範圍
        utc_now = datetime.utcnow()
        tw_now = utc_now + timedelta(hours=8)
        tw_start_of_day = tw_now.replace(hour=0, minute=0, second=0, microsecond=0)
        tw_end_of_day = tw_now.replace(hour=23, minute=59, second=59, microsecond=999999)

        utc_start_query = tw_start_of_day - timedelta(hours=8)
        utc_end_query = tw_end_of_day - timedelta(hours=8)
        time_filter = f"created_at >= '{utc_start_query}' AND created_at <= '{utc_end_query}'"

        # 抓取統計數據
        cur.execute(f"SELECT COUNT(*), SUM(total_price) FROM orders WHERE {time_filter} AND status != 'Cancelled'")
        v_count, v_total = cur.fetchone()
        
        cur.execute(f"SELECT COUNT(*), SUM(total_price) FROM orders WHERE {time_filter} AND status = 'Cancelled'")
        x_count, x_total = cur.fetchone()

        # 抓取並統計品項
        cur.execute(f"SELECT content_json FROM orders WHERE {time_filter} AND status != 'Cancelled'")
        valid_rows = cur.fetchall()
        
        stats = {}
        for r in valid_rows:
            if not r[0]: continue
            try:
                items = json.loads(r[0]) if isinstance(r[0], str) else r[0]
                for i in items:
                    name = i.get('name_zh', i.get('name', '未知'))
                    qty = int(i.get('qty', 0))
                    stats[name] = stats.get(name, 0) + qty
            except: pass

        today_str = tw_now.strftime('%Y-%m-%d')
        item_detail_text = "\n【品項銷量統計】\n" + "\n".join([f"• {k}: {v}" for k, v in stats.items()]) if stats else "\n(今日尚無有效銷量)\n"

        email_content = f"""
🍴 餐廳日結報表 ({today_str})
---------------------------------
✅ 【有效營收】
單量：{v_count or 0} 筆
總額：${v_total or 0}
{item_detail_text}
---------------------------------
❌ 【作廢統計】
單量：{x_count or 0} 筆
總額：${x_total or 0}
---------------------------------
報告產出時間：{tw_now.strftime('%Y-%m-%d %H:%M:%S')} (Taiwan Time)
"""
        # 發送請求至 Resend API
        payload = {
            "from": config.get('sender_email', 'onboarding@resend.dev').strip(),
            "to": [to_email],
            "subject": f"【日結單】{today_str} 營業統計報告",
            "text": email_content
        }
        
        req = urllib.request.Request(
            "https://api.resend.com/emails", 
            data=json.dumps(payload).encode('utf-8'),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, 
            method='POST'
        )
        with urllib.request.urlopen(req) as res:
            print(f"[{tw_now}] ✅ 日結報表已發送至 {to_email}")
            
    except Exception as e:
        print(f"❌ 報表發送失敗: {e}")
    finally: 
        cur.close(); conn.close()

# --- 2. 自動排程 (發信) ---
def scheduler_loop():
    print("⏰ 排程執行緒已啟動 (Scheduler Started)")
    last_sent_time = ""
    while True:
        now_tw = datetime.utcnow() + timedelta(hours=8)
        current_time = now_tw.strftime("%H:%M")
        # 設定發信時間點
        if current_time in ["13:00", "18:00", "20:30"] and current_time != last_sent_time:
            send_daily_report()
            last_sent_time = current_time
        time.sleep(30)

# --- 3. 背景維護工作 (防休眠) ---
def run_maintenance_tasks():
    print("🚀 背景維護執行緒已啟動 (Maintenance Started)")
    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 防止 Render 休眠
        try:
            # 替換成你實際的 Render 網址
            urllib.request.urlopen("https://ding-dong-tipi.onrender.com", timeout=10)
            print(f"[{now}] ✅ Web Ping 成功")
        except Exception as e:
            print(f"[{now}] ❌ Web Ping 失敗: {e}")

        # 防止資料庫休眠 (Aiven Heartbeat)
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close(); conn.close()
            print(f"[{now}] 💓 DB Heartbeat 成功")
        except Exception as e:
            print(f"[{now}] ❌ DB Heartbeat 失敗: {e}")

        time.sleep(600)  # 每 10 分鐘執行一次

# --- 4. 啟動所有背景任務 ---
def start_background_tasks():
    """在 app.py 中呼叫此函式即可啟動所有背景任務"""
    # 使用 daemon=True 確保主程式關閉時，執行緒也會跟著關閉
    threading.Thread(target=scheduler_loop, daemon=True).start()
    threading.Thread(target=run_maintenance_tasks, daemon=True).start()