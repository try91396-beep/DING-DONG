import io
import pandas as pd
import threading
import traceback
from flask import Blueprint, request, redirect, url_for, jsonify, send_file, current_app, render_template

# 匯入資料庫連線模組
from database import get_db_connection

# 匯入 utils.py 中的發信函式
# 注意：請確保 utils.py 檔案在同一層目錄下
from utils import send_daily_report 

# 定義 Blueprint
admin_bp = Blueprint('admin', __name__)

# --- 1. 後台主面板 (顯示列表與設定) ---
@admin_bp.route('/', methods=['GET', 'POST'])
def admin_panel():
    conn = get_db_connection()
    cur = conn.cursor()
    msg = request.args.get('msg', '')
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        # [功能 1] 儲存設定
        if action == 'save_settings':
            settings = {
                'report_email': request.form.get('report_email', '').strip(),
                'sender_email': request.form.get('sender_email', '').strip(),
                'resend_api_key': request.form.get('resend_api_key', '').strip()
            }
            try:
                for k, v in settings.items():
                    # 使用 Upsert 語法確保設定值被更新或插入
                    cur.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (k, v))
                conn.commit()
                msg = "✅ 設定已儲存"
            except Exception as e:
                conn.rollback()
                msg = f"❌ 設定儲存失敗: {e}"
            finally:
                conn.close()
            return redirect(url_for('admin.admin_panel', msg=msg))
        
        # [功能 2] 測試發信 (串接 utils.send_daily_report)
        elif action == 'test_email':
            # 組裝臨時設定，不讀取資料庫，直接用表單的輸入值進行測試
            temp_config = {
                'report_email': request.form.get('report_email'),
                'sender_email': request.form.get('sender_email'),
                'resend_api_key': request.form.get('resend_api_key')
            }
            conn.close() # 釋放連線，讓背景執行緒自己建立
            
            # 啟動背景執行緒發信，傳入 manual_config=temp_config, is_test=True
            # 這樣 utils.send_daily_report 就會知道這是測試模式
            threading.Thread(target=send_daily_report, kwargs={'manual_config': temp_config, 'is_test': True}).start()
            
            return redirect(url_for('admin.admin_panel', msg="🧪 測試信件發送請求已送出..."))

        # [功能 3] 手動發送今日報表 (串接 utils.send_daily_report)
        elif action == 'send_report_now':
            conn.close() # 釋放連線
            
            # 啟動背景執行緒發信，傳入 manual_config=None (讀取 DB), is_test=False (正式報表)
            threading.Thread(target=send_daily_report, kwargs={'manual_config': None, 'is_test': False}).start()
            
            return redirect(url_for('admin.admin_panel', msg="📊 正式報表發送請求已送出..."))

        # [功能 4] 新增產品
        elif action == 'add_product':
            try:
                cur.execute("""
                    INSERT INTO products (
                        name, price, category, print_category, image_url, 
                        name_en, name_jp, name_kr,
                        category_en, category_jp, category_kr,
                        custom_options, custom_options_en, custom_options_jp, custom_options_kr
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    request.form.get('name'), request.form.get('price'), request.form.get('category'), 
                    request.form.get('print_category'), request.form.get('image_url'),
                    request.form.get('name_en'), request.form.get('name_jp'), request.form.get('name_kr'),
                    request.form.get('category_en'), request.form.get('category_jp'), request.form.get('category_kr'),
                    request.form.get('custom_options'), request.form.get('custom_options_en'), 
                    request.form.get('custom_options_jp'), request.form.get('custom_options_kr')
                ))
                conn.commit()
                msg = "✅ 產品新增成功"
            except Exception as e:
                conn.rollback()
                msg = f"❌ 新增失敗: {e}"
            finally:
                conn.close()
            return redirect(url_for('admin.admin_panel', msg=msg))

    # --- GET 請求：讀取資料以顯示頁面 ---
    try:
        cur.execute("SELECT key, value FROM settings")
        config = dict(cur.fetchall())
        
        cur.execute("""
            SELECT id, name, price, category, is_available, print_category, sort_order, image_url 
            FROM products ORDER BY sort_order ASC, id DESC
        """)
        prods = cur.fetchall()
    except Exception as e:
        msg = f"❌ 資料讀取錯誤: {e}"
        config = {}
        prods = []
    finally:
        conn.close()

    # 渲染 admin.html 模板
    return render_template('admin.html', config=config, prods=prods, msg=msg)


# --- 2. 編輯產品 (獨立頁面) ---
@admin_bp.route('/edit_product/<int:pid>', methods=['GET', 'POST'])
def edit_product(pid):
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        try:
            cur.execute("""
                UPDATE products SET 
                name=%s, price=%s, category=%s, print_category=%s, image_url=%s,
                name_en=%s, name_jp=%s, name_kr=%s,
                category_en=%s, category_jp=%s, category_kr=%s,
                custom_options=%s, custom_options_en=%s, custom_options_jp=%s, custom_options_kr=%s
                WHERE id=%s
            """, (
                request.form.get('name'), request.form.get('price'), request.form.get('category'), 
                request.form.get('print_category'), request.form.get('image_url'),
                request.form.get('name_en'), request.form.get('name_jp'), request.form.get('name_kr'),
                request.form.get('category_en'), request.form.get('category_jp'), request.form.get('category_kr'),
                request.form.get('custom_options'), request.form.get('custom_options_en'), 
                request.form.get('custom_options_jp'), request.form.get('custom_options_kr'),
                pid
            ))
            conn.commit()
            return redirect(url_for('admin.admin_panel', msg="✅ 產品已更新"))
        except Exception as e:
            conn.rollback()
            return f"Update Error: {e}"
        finally:
            conn.close()

    # 讀取現有資料
    cur.execute("SELECT * FROM products WHERE id = %s", (pid,))
    if cur.description:
        columns = [desc[0] for desc in cur.description]
        row = cur.fetchone()
    else:
        row = None
        
    conn.close()
    
    if not row: return "Product not found", 404
    p = dict(zip(columns, row))
    
    # 內嵌簡單的 HTML 表單，方便直接使用
    def v(key): return p.get(key, '') or ''
    
    return f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/milligram/1.4.1/milligram.min.css">
    <style>.container{{max-width:800px;padding:20px}}</style></head><body><div class="container">
        <h3>✏️ 編輯產品: {v('name')}</h3>
        <form method="POST">
            <div class="row">
                <div class="column"><label>名稱</label><input type="text" name="name" value="{v('name')}" required></div>
                <div class="column"><label>價格</label><input type="number" name="price" value="{v('price')}" required></div>
            </div>
            <div class="row">
                <div class="column"><label>分類</label><input type="text" name="category" value="{v('category')}"></div>
                <div class="column"><label>出單區</label>
                    <select name="print_category">
                        <option value="Noodle" {'selected' if v('print_category')=='Noodle' else ''}>🍜 麵台</option>
                        <option value="Soup" {'selected' if v('print_category')=='Soup' else ''}>🍲 湯台</option>
                    </select>
                </div>
            </div>
            <label>圖片 URL</label><input type="text" name="image_url" value="{v('image_url')}">
            <details open><summary>多國語言與選項</summary>
                <div class="row">
                    <div class="column"><input type="text" name="name_en" value="{v('name_en')}" placeholder="Name EN"></div>
                    <div class="column"><input type="text" name="name_jp" value="{v('name_jp')}" placeholder="Name JP"></div>
                    <div class="column"><input type="text" name="name_kr" value="{v('name_kr')}" placeholder="Name KR"></div>
                </div>
                <label>選項 (中文)</label><input type="text" name="custom_options" value="{v('custom_options')}">
            </details>
            <br><button type="submit">💾 儲存</button> <a href="/admin" class="button button-outline">取消</a>
        </form>
    </div></body></html>
    """

# --- 3. 匯出/匯入/重置/其他操作 ---

@admin_bp.route('/export_menu')
def export_menu():
    try:
        conn = get_db_connection()
        # 利用 pandas 讀取 SQL 並轉為 DataFrame
        df = pd.read_sql("SELECT * FROM products ORDER BY sort_order ASC", conn)
        conn.close()
        
        # 寫入 Excel (需安裝 openpyxl)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        
        return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name="menu_export.xlsx")
    except Exception as e:
         return redirect(url_for('admin.admin_panel', msg=f"❌ 匯出失敗: {e}"))

@admin_bp.route('/import_menu', methods=['POST'])
def import_menu():
    try:
        file = request.files.get('menu_file')
        if not file: return redirect(url_for('admin.admin_panel', msg="❌ 無檔案"))
        
        df = pd.read_excel(file, engine='openpyxl')
        df = df.where(pd.notnull(df), None) # 處理 NaN
        conn = get_db_connection(); cur = conn.cursor()
        
        cnt = 0
        for _, p in df.iterrows():
            if not p.get('name'): continue
            # 簡易匯入邏輯 (只示範主要欄位，可自行擴充)
            cur.execute("INSERT INTO products (name, price, category, print_category) VALUES (%s, %s, %s, %s)", 
                        (str(p.get('name')), p.get('price', 0), p.get('category'), p.get('print_category','Noodle')))
            cnt += 1
        conn.commit(); cur.close(); conn.close()
        return redirect(url_for('admin.admin_panel', msg=f"✅ 匯入 {cnt} 筆成功"))
    except Exception as e:
        return redirect(url_for('admin.admin_panel', msg=f"❌ 匯入失敗: {e}"))

@admin_bp.route('/reset_menu')
def reset_menu():
    conn = get_db_connection(); cur = conn.cursor()
    # TRUNCATE 會清空表格並重置 ID 計數
    cur.execute("TRUNCATE TABLE products RESTART IDENTITY CASCADE")
    conn.commit(); conn.close()
    return redirect(url_for('admin.admin_panel', msg="🗑️ 菜單已清空"))

@admin_bp.route('/reset_orders')
def reset_orders():
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("TRUNCATE TABLE orders RESTART IDENTITY CASCADE")
    conn.commit(); conn.close()
    return redirect(url_for('admin.admin_panel', msg="💥 訂單已清空"))

@admin_bp.route('/toggle_product/<int:pid>', methods=['POST'])
def toggle_product(pid):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT is_available FROM products WHERE id = %s", (pid,))
    row = cur.fetchone()
    if row:
        new_s = not row[0]
        cur.execute("UPDATE products SET is_available = %s WHERE id = %s", (new_s, pid))
        conn.commit(); conn.close()
        return jsonify({'status': 'success', 'is_available': new_s})
    conn.close()
    return jsonify({'status': 'error'}), 404

@admin_bp.route('/delete_product/<int:pid>')
def delete_product(pid):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id = %s", (pid,))
    conn.commit(); conn.close()
    return redirect(url_for('admin.admin_panel', msg="🗑️ 產品已刪除"))

@admin_bp.route('/reorder_products', methods=['POST'])
def reorder_products():
    data = request.json
    conn = get_db_connection(); cur = conn.cursor()
    for idx, pid in enumerate(data.get('order', [])):
        cur.execute("UPDATE products SET sort_order = %s WHERE id = %s", (idx, pid))
    conn.commit(); conn.close()
    return jsonify({'status': 'success'})
