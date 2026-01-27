import json
import urllib.request
import urllib.error
import threading
import time
import ssl
import traceback
from datetime import datetime, timedelta
from database import get_db_connection

# --- 1. Email 報告發送核心 (修正版) ---
def send_daily_report(app, manual_config=None, is_test=False):
    """
    發送日結報告。
    :param app: Flask app 實體 (必須傳入以取得 Context)
    :param manual_config: dict, 若提供則使用此設定 (後台測試用)，否則讀取 DB。
    :param is_test: bool, 若為 True 則只發送測試內容。
    """
    # 關鍵修正：建立應用程式上下文，讓執行緒知道資料庫設定在哪
    with app.app_context():
        # print("🔄 準備發送報表...") # debug 用
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # 決定設定來源
            if manual_config:
                config = manual_config
            else:
                cur.execute("SELECT key, value FROM settings")
                config = dict(cur.fetchall())

            api_key = config.get('resend_api_key', '').strip()
            to_email = config.get('report_email', '').strip()
            sender_email = config.get('sender_email', 'onboarding@resend.dev').strip()

            if not api_key or not to_email:
                print("❌ 未設定 Email 或 API Key，取消發送")
                return "❌ 設定不完整"

            # 準備時間與內容
            utc_now = datetime.utcnow()
            tw_now = utc_now + timedelta(hours=8)
            today_str = tw_now.strftime('%Y-%m-%d')

            if is_test:
                subject = f"【測試】Resend API 設定確認 ({today_str})"
                email_content = "✅ Resend API 連線成功！\n此為測試信件。"
            else:
                # 抓取正式數據
                tw_start = tw_now.replace(hour=0, minute=0, second=0, microsecond=0)
                tw_end = tw_now.replace(hour=23, minute=59, second=59, microsecond=999999)
                utc_start = tw_start - timedelta(hours=8)
                utc_end = tw_end - timedelta(hours=8)
                time_filter = f"created_at >= '{utc_start}' AND created_at <= '{utc_end}'"

                # 統計數據
                cur.execute(f"SELECT COUNT(*), SUM(total_price) FROM orders WHERE {time_filter} AND status != 'Cancelled'")
                v_res = cur.fetchone()
                v_count, v_total = (v_res[0] or 0), (v_res[1] or 0)

                cur.execute(f"SELECT COUNT(*), SUM(total_price) FROM orders WHERE {time_filter} AND status = 'Cancelled'")
                x_res = cur.fetchone()
                x_count, x_total = (x_res[0] or 0), (x_res[1] or 0)

                # 品項統計
                cur.execute(f"SELECT content_json FROM orders WHERE {time_filter} AND status != 'Cancelled'")
                rows = cur.fetchall()
                stats = {}
                for r in rows:
                    if not r[0]: continue
                    try:
                        items = json.loads(r[0]) if isinstance(r[0], str) else r[0]
                        if isinstance(items, dict): items = [items]
                        for i in items:
                            name = i.get('name_zh', i.get('name', '未知'))
                            qty = int(i.get('qty', 0))
                            stats[name] = stats.get(name, 0) + qty
                    except: pass
                
                # 排序品項
                sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)
                item_text = "\n".join([f"• {k}: {v}" for k, v in sorted_stats]) if sorted_stats else "(無銷量)"

                subject = f"【日結單】{today_str} 營業報告"
                email_content = f"""
🍴 餐廳日結 ({today_str})
------------------------
✅ 有效: {v_count} 筆 (${int(v_total):,})
{item_text}
------------------------
❌ 作廢: {x_count} 筆 (${int(x_total):,})
"""

            # 發送請求 (SSL Fix)
            payload = {
                "from": sender_email,
                "to": [to_email],
                "subject": subject,
                "text": email_content
            }
            
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(
                "https://api.resend.com/emails",
                data=json.dumps(payload).encode('utf-8'),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method='POST'
            )
            
            print(f"📡 正在連線 Resend API 發送至 {to_email} ...")
            with urllib.request.urlopen(req, context=ctx, timeout=10) as res:
                print(f"✅ Email 發送成功: {res.status}")
                return "✅ 發送成功"

        except Exception as e:
            traceback.print_exc()
            print(f"❌ Email 發送失敗: {e}")
            return f"❌ 發送失敗: {str(e)}"
        finally:
            cur.close()
            conn.close()

# --- 2. 背景維護工作 (防休眠 + 自動發信) ---
# 修改：接收 app 參數
def run_maintenance_tasks(app):
    print("🚀 背景維護執行緒已啟動 (Maintenance Thread Started)")
    
    last_sent_time = ""
    next_ping_time = datetime.now()

    while True:
        try:
            now_obj = datetime.now()
            now_str = now_obj.strftime("%Y-%m-%d %H:%M:%S")
            
            # --- A. 自動發信檢查 (每分鐘檢查) ---
            tw_time = datetime.utcnow() + timedelta(hours=8)
            current_hm = tw_time.strftime("%H:%M")
            
            target_times = ["13:00", "18:00", "20:30"]
            
            if current_hm in target_times and current_hm != last_sent_time:
                print(f"[{now_str}] ⏰ 時間到 ({current_hm})，執行自動發信...")
                # 修改：傳入 app
                send_daily_report(app)
                last_sent_time = current_hm

            # --- B. 防休眠 Ping (每 5 分鐘執行一次) ---
            if now_obj >= next_ping_time:
                # 1. 防止 Render 休眠 (Ping 網址)
                try:
                    urllib.request.urlopen("https://ding-dong-tipi.onrender.com", timeout=10)
                    print(f"[{now_str}] ✅ Web Ping 成功")
                except Exception:
                    pass # 忽略錯誤保持安靜

                # 2. 防止 DB 休眠
                try:
                    conn = get_db_connection()
                    conn.close()
                    # print(f"[{now_str}] 💓 DB Heartbeat 成功")
                except Exception:
                    pass

                next_ping_time = now_obj + timedelta(seconds=300)

            time.sleep(60)

        except Exception as e:
            print(f"⚠️ 背景任務發生錯誤: {e}")
            time.sleep(60)

# 修改：接收 app 參數
def start_background_tasks(app):
    # 啟動守護執行緒 (Daemon Thread)，隨主程式結束
    # 將 app 傳入執行緒
    t = threading.Thread(target=run_maintenance_tasks, args=(app,), daemon=True)
    t.start()
