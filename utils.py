import json
import urllib.request
import urllib.error
import threading
import time
import ssl
import traceback
from datetime import datetime, timedelta
from database import get_db_connection

# === 🛡️ 引入 Flask 相關工具 ===
from flask import session, redirect, url_for, request, jsonify
from functools import wraps
from werkzeug.routing import BuildError

# ==========================================
# 0. 🛡️ 多重權限防護罩系統 (Decorators)
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Unauthorized: 請先登入'}), 401
            bp = request.blueprint or ''
            if bp in ['admin', 'kitchen', 'try', 'try_debug']:
                # 修正：try 藍圖通常對應 try_debug.login
                target = 'try_debug.login' if bp in ['try', 'try_debug'] else f'{bp}.login'
                return redirect(url_for(target))
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                bp = request.blueprint or ''
                login_route = f'{bp}.login' if bp in ['kitchen', 'try_debug'] else 'admin.login'
                return redirect(url_for(login_route))
            if session.get('role') not in allowed_roles:
                return "<h3>❌ 權限不足</h3> <a href='javascript:history.back()'>回上一頁</a>", 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ==========================================
# 1. Email 報告發送核心 (加入值班人員資訊)
# ==========================================
def send_daily_report(app, manual_config=None, is_test=False):
    conn, cur = None, None
    with app.app_context():
        try:
            # 取得當前操作者 (如果是手動觸發才有 session)
            operator_name = session.get('username', '系統自動發送')
            operator_role = session.get('role', 'System')
            
            conn = get_db_connection()
            cur = conn.cursor()
            
            # 讀取設定
            if manual_config:
                config = manual_config
            else:
                cur.execute("SELECT key, value FROM settings")
                config = dict(cur.fetchall())

            api_key = config.get('resend_api_key', '').strip()
            to_email = config.get('report_email', '').strip()
            sender_email = (config.get('sender_email') or 'onboarding@resend.dev').strip()

            if not api_key or not to_email:
                return "❌ 設定不完整"

            tw_now = datetime.utcnow() + timedelta(hours=8)
            today_str = tw_now.strftime('%Y-%m-%d')

            if is_test:
                subject = f"【測試】Resend API 設定確認 ({today_str})"
                email_content = (
                    f"👤 值班人員: {operator_name} ({operator_role})\n"
                    f"------------------------\n"
                    f"✅ 連線測試成功！\n"
                    f"寄件者: {sender_email}\n"
                    f"收件者: {to_email}"
                )
            else:
                # 時間過濾器 (台灣當日 00:00 ~ 23:59)
                tw_start = tw_now.replace(hour=0, minute=0, second=0, microsecond=0)
                utc_start = tw_start - timedelta(hours=8)
                utc_end = utc_start + timedelta(hours=24)
                time_filter = f"created_at >= '{utc_start}' AND created_at < '{utc_end}'"

                # 1. 有效訂單統計
                cur.execute(f"SELECT COUNT(*), SUM(total_price) FROM orders WHERE {time_filter} AND status != 'Cancelled'")
                v_res = cur.fetchone()
                v_count, v_total = (v_res[0] or 0), (v_res[1] or 0)

                cur.execute(f"SELECT content_json FROM orders WHERE {time_filter} AND status != 'Cancelled'")
                v_rows = cur.fetchall()
                v_stats = {}
                for r in v_rows:
                    try:
                        items = json.loads(r[0]) if isinstance(r[0], str) else r[0]
                        if isinstance(items, dict): items = [items]
                        for i in items:
                            name = i.get('name_zh', i.get('name', '未知'))
                            v_stats[name] = v_stats.get(name, 0) + int(i.get('qty', 0))
                    except: pass

                # 2. 作廢訂單統計
                cur.execute(f"SELECT COUNT(*), SUM(total_price) FROM orders WHERE {time_filter} AND status = 'Cancelled'")
                x_res = cur.fetchone()
                x_count, x_total = (x_res[0] or 0), (x_res[1] or 0)

                cur.execute(f"SELECT content_json FROM orders WHERE {time_filter} AND status = 'Cancelled'")
                x_rows = cur.fetchall()
                x_stats = {}
                for r in x_rows:
                    try:
                        items = json.loads(r[0]) if isinstance(r[0], str) else r[0]
                        if isinstance(items, dict): items = [items]
                        for i in items:
                            name = i.get('name_zh', i.get('name', '未知'))
                            x_stats[name] = x_stats.get(name, 0) + int(i.get('qty', 0))
                    except: pass

                # 格式化品項文字
                v_list = sorted(v_stats.items(), key=lambda x:x[1], reverse=True)
                v_text = "\n".join([f"• {k}: {v}" for k, v in v_list]) if v_list else "(無銷量)"
                
                x_list = sorted(x_stats.items(), key=lambda x:x[1], reverse=True)
                x_text = "\n".join([f"• {k}: {v}" for k, v in x_list]) if x_list else "(無作廢)"

                subject = f"【日結單】{today_str} 營業報告"
                email_content = (
                    f"👤 值班人員: {operator_name} ({operator_role})\n"
                    f"🍴 餐廳日結 ({today_str})\n"
                    f"------------------------\n"
                    f"✅ 有效: {v_count} 筆 (${int(v_total):,})\n"
                    f"{v_text}\n"
                    f"------------------------\n"
                    f"❌ 作廢: {x_count} 筆 (${int(x_total):,})\n"
                    f"{x_text}\n"
                    f"------------------------\n"
                    f"💰 實收總計: ${int(v_total):,}"
                )

            # --- API 發送邏輯 ---
            payload = {"from": sender_email, "to": [to_email], "subject": subject, "text": email_content}
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            }

            req = urllib.request.Request("https://api.resend.com/emails", 
                                          data=json.dumps(payload).encode('utf-8'), 
                                          headers=headers, method='POST')
            
            with urllib.request.urlopen(req, context=ctx, timeout=10) as res:
                print(f"✅ Email 發送成功: {res.status}")
                return "✅ 發送成功"

        except Exception as e:
            print(f"❌ Email 任務出錯: {e}")
            traceback.print_exc()
            return f"❌ 錯誤: {str(e)}"
        finally:
            if cur: cur.close()
            if conn: conn.close()

# ==========================================
# 2. 背景維護工作
# ==========================================
def run_maintenance_tasks(app):
    time.sleep(30)
    print("🚀 背景維護執行緒啟動")
    last_sent_time = ""
    next_ping_time = datetime.now()

    while True:
        try:
            now_obj = datetime.now()
            tw_time = datetime.utcnow() + timedelta(hours=8)
            current_hm = tw_time.strftime("%H:%M")
            
            # 定時發信時間點
            if current_hm in ["13:00", "18:00", "20:30", "09:25"] and current_hm != last_sent_time:
                send_daily_report(app)
                last_sent_time = current_hm

            # 每 5 分鐘執行保活 Ping
            if now_obj >= next_ping_time:
                try:
                    urllib.request.urlopen("https://ding-dong-tipi.onrender.com", timeout=5)
                    conn = get_db_connection()
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1;")
                    conn.close()
                    print(f"[{now_obj.strftime('%H:%M')}] 💓 Heartbeat Success")
                except: pass
                next_ping_time = now_obj + timedelta(seconds=300)

            time.sleep(30)
        except Exception as e:
            print(f"⚠️ 背景錯誤: {e}")
            time.sleep(60)

def start_background_tasks(app):
    threading.Thread(target=run_maintenance_tasks, args=(app,), daemon=True).start()

# ==========================================
# 3. 👤 Context Processor (自動注入導航欄資訊)
# ==========================================
def inject_user_info():
    current_username = session.get('username')
    current_bp = request.blueprint
    try:
        logout_url = url_for(f'{current_bp}.logout') if current_username and current_bp else '#'
    except BuildError:
        logout_url = '#'
    return {
        'current_username': current_username,
        'current_role': session.get('role', '未知角色'),
        'logout_url': logout_url
    }
