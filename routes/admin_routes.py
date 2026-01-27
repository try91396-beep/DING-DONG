import io
import json
import threading
import traceback
import pandas as pd
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, send_file, current_app

# 從資料庫模組匯入連線函式
from database import get_db_connection 
# 從 utils 匯入發信功能
from utils import send_daily_report

admin_bp = Blueprint('admin', __name__)

# ==========================================
# 核心路由：後台主面板
# ==========================================
@admin_bp.route('/', methods=['GET', 'POST'])
def admin_panel():
    conn = get_db_connection()
    cur = conn.cursor()
    msg = request.args.get('msg', '')
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        # --- 功能 1: 儲存設定 & 測試連線 ---
        if action == 'save_settings':
            # ... (取得 sender_input 與 new_config 的程式碼保持不變) ...
            
            # 2. 寫入資料庫 (這部分保持不變)
            try:
                for k, v in new_config.items():
                    cur.execute("""
                        INSERT INTO settings (key, value) 
                        VALUES (%s, %s) 
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """, (k, v))
                conn.commit()
                
                # 3. 處理「測試連線」
                if request.form.get('test_connection') == 'on':
                    try:
                        # [修改重點 1] 傳入 current_app._get_current_object()
                        app_obj = current_app._get_current_object()
                        result_msg = send_daily_report(app_obj, manual_config=new_config, is_test=True)
                        
                        if "✅" in result_msg:
                            msg = f"✅ 設定已儲存 / {result_msg}"
                        else:
                            msg = f"⚠️ 設定已存，但連線測試失敗: {result_msg}"
                            
                    except Exception as e:
                        traceback.print_exc()
                        msg = f"✅ 設定已儲存 / ❌ 測試失敗: {str(e)}"
                else:
                    msg = "✅ 設定已儲存"
                    
            except Exception as e:
                conn.rollback()
                msg = f"❌ 儲存失敗: {e}"

            cur.close(); conn.close()
            return redirect(url_for('admin.admin_panel', msg=msg))

        # --- 功能 2: 手動觸發日結報表 (背景執行) ---
        elif action == 'send_report_now':
            # [修改重點 2] 獲取真實的 app 物件並傳入執行緒
            try:
                # 取得 app 實體 (Thread 內無法直接用 current_app)
                app_obj = current_app._get_current_object()
                
                # 將 app_obj 作為參數 (args) 傳入
                threading.Thread(target=send_daily_report, args=(app_obj,), kwargs={'is_test': False}).start()
                
                msg = "🚀 報表正在背景發送中，請稍候檢查信箱"
            except Exception as e:
                msg = f"❌ 無法啟動背景任務: {e}"
            
            cur.close(); conn.close()
            return redirect(url_for('admin.admin_panel', msg=msg))

        # --- 功能 3: 新增產品 ---
        elif action == 'add_product':
            try:
                cur.execute("""
                    INSERT INTO products (
                        name, price, category, print_category, image_url, sort_order,
                        name_en, name_jp, name_kr,
                        custom_options, custom_options_en, custom_options_jp, custom_options_kr,
                        category_en, category_jp, category_kr
                    ) VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    request.form.get('name'), request.form.get('price'), request.form.get('category'), 
                    request.form.get('print_category'), request.form.get('image_url'),
                    request.form.get('name_en'), request.form.get('name_jp'), request.form.get('name_kr'),
                    request.form.get('custom_options'), request.form.get('custom_options_en'), request.form.get('custom_options_jp'), request.form.get('custom_options_kr'),
                    request.form.get('category_en'), request.form.get('category_jp'), request.form.get('category_kr')
                ))
                conn.commit()
                msg = "✅ 品項已新增"
            except Exception as e:
                conn.rollback()
                msg = f"❌ 新增失敗: {e}"
            finally:
                cur.close(); conn.close()
            return redirect(url_for('admin.admin_panel', msg=msg))

    # --- GET: 讀取資料顯示頁面 ---
    cur.execute("SELECT key, value FROM settings")
    config = dict(cur.fetchall())
    
    cur.execute("""
        SELECT id, name, price, category, is_available, print_category, sort_order, image_url, 
               name_en, name_jp, name_kr 
        FROM products 
        ORDER BY sort_order ASC, id DESC
    """)
    prods = cur.fetchall()
    cur.close(); conn.close()
    
    return render_template('admin.html', config=config, prods=prods, msg=msg)


# ==========================================
# 編輯產品 (獨立頁面)
# ==========================================
@admin_bp.route('/edit_product/<int:pid>', methods=['GET','POST'])
def edit_product(pid):
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        try:
            cur.execute("""
                UPDATE products SET 
                name=%s, price=%s, category=%s, image_url=%s, custom_options=%s,
                name_en=%s, name_jp=%s, name_kr=%s,
                custom_options_en=%s, custom_options_jp=%s, custom_options_kr=%s,
                print_category=%s, sort_order=%s,
                category_en=%s, category_jp=%s, category_kr=%s
                WHERE id=%s
            """, (
                request.form.get('name'), request.form.get('price'), request.form.get('category'),
                request.form.get('image_url'), request.form.get('custom_options'),
                request.form.get('name_en'), request.form.get('name_jp'), request.form.get('name_kr'),
                request.form.get('custom_options_en'), request.form.get('custom_options_jp'), request.form.get('custom_options_kr'),
                request.form.get('print_category'), request.form.get('sort_order'),
                request.form.get('category_en'), request.form.get('category_jp'), request.form.get('category_kr'),
                pid
            ))
            conn.commit()
            return redirect(url_for('admin.admin_panel', msg="✅ 產品已更新"))
        except Exception as e:
            conn.rollback()
            return f"Update Error: {e}"
        finally:
            cur.close(); conn.close()

    # 讀取現有資料
    cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
    columns = [desc[0] for desc in cur.description]
    row = cur.fetchone()
    cur.close(); conn.close()
    
    if not row: return "找不到該產品", 404

    # 將資料轉換為字典以便存取
    p = dict(zip(columns, row))
    def v(key): return p.get(key) if p.get(key) is not None else ""

    # 這裡直接回傳簡易的編輯 HTML
    return f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>編輯產品</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/milligram/1.4.1/milligram.min.css">
    <style>
        body {{ padding: 20px; background: #f4f7f6; font-family: sans-serif; }}
        .container {{ background: white; padding: 30px; border-radius: 10px; max-width: 900px; margin: auto; }}
        h5 {{ background: #9b4dca; color: white; padding: 5px 10px; border-radius: 4px; margin-top: 25px; }}
        label {{ font-weight: bold; margin-top: 10px; }}
        .row {{ margin-bottom: 1rem; }}
    </style>
    </head>
    <body>
        <div class="container">
            <h3>📝 編輯產品 #{v('id')}</h3>
            <form method="POST">
                <h5>1. 基本資料</h5>
                <div class="row">
                    <div class="column column-40"><label>名稱 (中文)</label><input type="text" name="name" value="{v('name')}" required></div>
                    <div class="column"><label>價格</label><input type="number" name="price" value="{v('price')}" required></div>
                    <div class="column"><label>排序</label><input type="number" name="sort_order" value="{v('sort_order')}"></div>
                </div>
                <div class="row">
                    <div class="column">
                        <label>出單區域</label>
                        <select name="print_category">
                            <option value="Noodle" {'selected' if v('print_category')=='Noodle' else ''}>🍜 麵區</option>
                            <option value="Soup" {'selected' if v('print_category')=='Soup' else ''}>🍲 湯區</option>
                        </select>
                    </div>
                    <div class="column column-67"><label>圖片 URL</label><input type="text" name="image_url" value="{v('image_url')}"></div>
                </div>

                <h5>2. 分類 (Category)</h5>
                <div class="row">
                    <div class="column"><label>中文</label><input type="text" name="category" value="{v('category')}"></div>
                    <div class="column"><label>English</label><input type="text" name="category_en" value="{v('category_en')}"></div>
                    <div class="column"><label>日本語</label><input type="text" name="category_jp" value="{v('category_jp')}"></div>
                    <div class="column"><label>한국어</label><input type="text" name="category_kr" value="{v('category_kr')}"></div>
                </div>

                <h5>3. 多語品名 (Name)</h5>
                <div class="row">
                    <div class="column"><label>English</label><input type="text" name="name_en" value="{v('name_en')}"></div>
                    <div class="column"><label>日本語</label><input type="text" name="name_jp" value="{v('name_jp')}"></div>
                    <div class="column"><label>한국어</label><input type="text" name="name_kr" value="{v('name_kr')}"></div>
                </div>

                <h5>4. 客製化選項 (Options)</h5>
                <label>中文選項 (逗號分隔)</label>
                <input type="text" name="custom_options" value="{v('custom_options')}">
                <div class="row">
                    <div class="column"><label>English Options</label><input type="text" name="custom_options_en" value="{v('custom_options_en')}"></div>
                    <div class="column"><label>日本語 Options</label><input type="text" name="custom_options_jp" value="{v('custom_options_jp')}"></div>
                    <div class="column"><label>한국어 Options</label><input type="text" name="custom_options_kr" value="{v('custom_options_kr')}"></div>
                </div>

                <div style="margin-top:30px; text-align: right;">
                    <a href="{url_for('admin.admin_panel')}" class="button button-outline">❌ 取消</a>
                    <button type="submit">💾 儲存變更</button>
                </div>
            </form>
        </div>
    </body></html>"""


# ==========================================
# 匯入 / 匯出 / 重置 / 其他
# ==========================================

@admin_bp.route('/export_menu')
def export_menu():
    try:
        conn = get_db_connection()
        # 讀取完整欄位以便備份
        df = pd.read_sql("SELECT * FROM products ORDER BY sort_order ASC", conn)
        conn.close()
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        
        return send_file(
            output, 
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            as_attachment=True, 
            download_name=f"menu_export_{pd.Timestamp.now().strftime('%Y%m%d')}.xlsx"
        )
    except Exception as e:
         return redirect(url_for('admin.admin_panel', msg=f"❌ 匯出失敗: {e}"))

@admin_bp.route('/import_menu', methods=['POST'])
def import_menu():
    try:
        file = request.files.get('menu_file')
        if not file: return redirect(url_for('admin.admin_panel', msg="❌ 無檔案"))
        
        # 讀取 Excel
        df = pd.read_excel(file, engine='openpyxl')
        
        # 將空值 NaN 轉為 None，避免 SQL 錯誤
        df = df.where(pd.notnull(df), None)
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        cnt = 0
        for _, p in df.iterrows():
            # 確保有名稱才匯入
            if not p.get('name'): continue
            
            # 處理布林值：Excel 中的 TRUE/FALSE 或 1/0 轉為 Python bool
            is_avail = True
            if p.get('is_available') is not None:
                val = str(p.get('is_available')).lower()
                is_avail = val in ['1', 'true', 'yes', 't']

            # 準備 SQL (不匯入 id，讓資料庫自動產生)
            sql = """
                INSERT INTO products (
                    name, price, category, image_url, is_available, custom_options, sort_order,
                    name_en, name_jp, name_kr,
                    custom_options_en, custom_options_jp, custom_options_kr,
                    print_category,
                    category_en, category_jp, category_kr
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, 
                    %s, %s, %s, 
                    %s, %s, %s, 
                    %s, 
                    %s, %s, %s
                )
            """
            
            # 準備參數 (依照 SQL 順序)
            params = (
                str(p.get('name')),
                p.get('price', 0),
                p.get('category'),
                p.get('image_url'),
                is_avail,
                p.get('custom_options'),
                p.get('sort_order', 0), # 預設排序 0
                
                p.get('name_en'),
                p.get('name_jp'),
                p.get('name_kr'),
                
                p.get('custom_options_en'),
                p.get('custom_options_jp'),
                p.get('custom_options_kr'),
                
                p.get('print_category', 'Noodle'), # 預設麵區
                
                p.get('category_en'),
                p.get('category_jp'),
                p.get('category_kr')
            )
            
            cur.execute(sql, params)
            cnt += 1
            
        conn.commit()
        cur.close(); conn.close()
        return redirect(url_for('admin.admin_panel', msg=f"✅ 完整匯入成功！共 {cnt} 筆資料"))
        
    except Exception as e:
        traceback.print_exc() # 在後台印出詳細錯誤以便除錯
        return redirect(url_for('admin.admin_panel', msg=f"❌ 匯入失敗: {e}"))

@admin_bp.route('/reset_menu')
def reset_menu():
    conn = get_db_connection(); cur = conn.cursor()
    # 清空產品表並重置 ID 計數
    cur.execute("TRUNCATE TABLE products RESTART IDENTITY CASCADE")
    conn.commit(); cur.close(); conn.close()
    return redirect(url_for('admin.admin_panel', msg="🗑️ 菜單已清空"))

@admin_bp.route('/reset_orders', methods=['POST'])
def reset_orders():
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 取得刪除模式：'all' 或 'range'
        delete_mode = request.form.get('delete_mode')
        
        if delete_mode == 'all':
            # --- 模式一：清空全部 (原本的功能) ---
            # TRUNCATE 速度快且會重置 ID
            cur.execute("TRUNCATE TABLE orders RESTART IDENTITY CASCADE")
            msg = "💥 已清空所有歷史訂單，流水號已重置！"
            
        elif delete_mode == 'range':
            # --- 模式二：指定日期區間 ---
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            
            if not start_date or not end_date:
                return redirect(url_for('admin.admin_panel', msg="❌ 請選擇完整的開始與結束日期"))
            
            # 補上時間，確保涵蓋整天
            # 例如：2023-10-27 變成 2023-10-27 00:00:00 到 2023-10-27 23:59:59
            start_ts = f"{start_date} 00:00:00"
            end_ts = f"{end_date} 23:59:59"
            
            # 使用 DELETE 刪除指定範圍 (不會重置 ID 流水號，這是正常的資料庫行為)
            cur.execute("""
                DELETE FROM orders 
                WHERE created_at >= %s AND created_at <= %s
            """, (start_ts, end_ts))
            
            deleted_count = cur.rowcount
            msg = f"🗑️ 已刪除 {start_date} 至 {end_date} 期間的訂單，共 {deleted_count} 筆。"
            
        else:
            msg = "❌ 無效的操作"

        conn.commit()
        
    except Exception as e:
        conn.rollback()
        msg = f"❌ 刪除失敗: {str(e)}"
        
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin.admin_panel', msg=msg))

@admin_bp.route('/toggle_product/<int:pid>', methods=['POST'])
def toggle_product(pid):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT is_available FROM products WHERE id = %s", (pid,))
    row = cur.fetchone()
    if row:
        new_s = not row[0]
        cur.execute("UPDATE products SET is_available = %s WHERE id = %s", (new_s, pid))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'status': 'success', 'is_available': new_s})
    
    cur.close(); conn.close()
    return jsonify({'status': 'error'}), 404

@admin_bp.route('/delete_product/<int:pid>')
def delete_product(pid):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id = %s", (pid,))
    conn.commit(); cur.close(); conn.close()
    return redirect(url_for('admin.admin_panel', msg="🗑️ 產品已刪除"))

@admin_bp.route('/reorder_products', methods=['POST'])
def reorder_products():
    data = request.json
    conn = get_db_connection(); cur = conn.cursor()
    try:
        for idx, pid in enumerate(data.get('order', [])):
            cur.execute("UPDATE products SET sort_order = %s WHERE id = %s", (idx, pid))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cur.close(); conn.close()
