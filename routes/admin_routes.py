import io
import json
import ssl
import threading
import urllib.request
import traceback
from datetime import datetime, timedelta
import pandas as pd
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, send_file, current_app

# 從資料庫模組匯入連線函式
from database import get_db_connection 
# 從 utils 匯入 send_daily_report，統一由這裡處理發信 (包含測試與日結)
from utils import send_daily_report

admin_bp = Blueprint('admin', __name__)

# --- 路由：後台主面板 ---
@admin_bp.route('/', methods=['GET', 'POST'])
def admin_panel():
    conn = get_db_connection()
    cur = conn.cursor()
    msg = request.args.get('msg', '')
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'save_settings':
            # 1. 取得表單資料
            new_config = {}
            for k in ['report_email', 'sender_email', 'resend_api_key']:
                val = request.form.get(k, '').strip()
                new_config[k] = val
                # 寫入資料庫
                cur.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (k, val))
            
            conn.commit()
            
            # 2. 如果使用者勾選了「測試連線」
            if request.form.get('test_connection') == 'on':
                try:
                    # 直接呼叫 utils.py 的函式，並傳入 manual_config 與 is_test=True
                    # 這樣可以測試「剛輸入但尚未生效」的設定，並確保使用與日結單相同的 SSL 邏輯
                    test_result = send_daily_report(manual_config=new_config, is_test=True)
                    return redirect(url_for('admin.admin_panel', msg=f"✅ 設定已儲存 / {test_result}"))
                except Exception as e:
                    return redirect(url_for('admin.admin_panel', msg=f"✅ 設定已儲存 / ❌ 測試失敗: {str(e)}"))
            
            return redirect(url_for('admin.admin_panel', msg="✅ 設定已儲存"))
        
        elif action == 'add_product':
            cur.execute("""INSERT INTO products (name, price, category, print_category, image_url, name_en, name_jp, name_kr) 
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", 
                       (request.form.get('name'), request.form.get('price'), request.form.get('category'), 
                        request.form.get('print_category'), request.form.get('image_url'),
                        request.form.get('name_en'), request.form.get('name_jp'), request.form.get('name_kr')))
            conn.commit()
            return redirect(url_for('admin.admin_panel', msg="✅ 品項已新增"))

    cur.execute("SELECT key, value FROM settings")
    config = dict(cur.fetchall())
    cur.execute("SELECT id, name, price, category, is_available, print_category, sort_order, image_url, name_en, name_jp, name_kr FROM products ORDER BY sort_order ASC, id DESC")
    prods = cur.fetchall()
    conn.close()
    return render_template('admin.html', config=config, prods=prods, msg=msg)

# --- 路由：手動觸發日結報表 ---
@admin_bp.route('/manual_report')
def manual_report():
    try:
        # 直接呼叫 utils.py 中的 send_daily_report
        # 不需要手動處理 DB 連線或 SSL，utils 裡都做好了
        result_msg = send_daily_report(is_test=False)
        
        # result_msg 會是 "✅ 發送成功" 或 "❌ ..."
        return redirect(url_for('admin.admin_panel', msg=f"手動發送結果: {result_msg}"))
    except Exception as e:
        traceback.print_exc()
        return redirect(url_for('admin.admin_panel', msg=f"❌ 發送失敗 (系統錯誤): {str(e)}"))

# --- 路由：編輯產品 (完整多國語言版) ---
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
            traceback.print_exc()
            return f"Update Error: {e}"
        finally:
            conn.close()

    # 明確指定 SELECT 欄位順序
    sql_query = """
        SELECT 
            id, name, price, category, image_url, 
            custom_options, sort_order,
            name_en, name_jp, name_kr,
            custom_options_en, custom_options_jp, custom_options_kr,
            print_category,
            category_en, category_jp, category_kr
        FROM products WHERE id=%s
    """
    cur.execute(sql_query, (pid,))
    row = cur.fetchone()
    conn.close()
    
    if not row: return "找不到該產品", 404

    # 建立絕對對應表
    idx = {
        'id': 0, 'name': 1, 'price': 2, 'category': 3, 'image_url': 4,
        'custom_options': 5, 'sort_order': 6,
        'name_en': 7, 'name_jp': 8, 'name_kr': 9,
        'custom_options_en': 10, 'custom_options_jp': 11, 'custom_options_kr': 12,
        'print_category': 13,
        'category_en': 14, 'category_jp': 15, 'category_kr': 16
    }

    def v(key):
        val = row[idx[key]]
        return val if val is not None else ""

    return f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>編輯產品</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/milligram/1.4.1/milligram.min.css">
    <style>
        body {{ padding: 20px; background: #f4f7f6; font-family: sans-serif; }}
        .container {{ background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 900px; margin: auto; }}
        h5 {{ background: #9b4dca; color: white; padding: 5px 10px; border-radius: 4px; margin-top: 25px; }}
        label {{ font-weight: bold; margin-top: 10px; }}
        hr {{ margin: 30px 0; }}
        .row {{ margin-bottom: 1.5rem; }}
    </style>
    </head>
    <body>
        <div class="container">
            <h3>📝 編輯產品 #{v('id')}</h3>
            <form method="POST">
                <h5>1. 基本資料 & 區域</h5>
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

                <h5>2. 分類多語翻譯 (Category)</h5>
                <div class="row">
                    <div class="column"><label>中文分類</label><input type="text" name="category" value="{v('category')}"></div>
                    <div class="column"><label>English 分類</label><input type="text" name="category_en" value="{v('category_en')}"></div>
                    <div class="column"><label>日本語 分類</label><input type="text" name="category_jp" value="{v('category_jp')}"></div>
                    <div class="column"><label>한국어 分類</label><input type="text" name="category_kr" value="{v('category_kr')}"></div>
                </div>

                <h5>3. 品名多語翻譯 (Name)</h5>
                <div class="row">
                    <div class="column"><label>English 品名</label><input type="text" name="name_en" value="{v('name_en')}"></div>
                    <div class="column"><label>日本語 品名</label><input type="text" name="name_jp" value="{v('name_jp')}"></div>
                    <div class="column"><label>한국어 品名</label><input type="text" name="name_kr" value="{v('name_kr')}"></div>
                </div>

                <h5>4. 客製化選項多語翻譯 (Options)</h5>
                <label>中文選項 (例如: 加麵,去蔥)</label>
                <input type="text" name="custom_options" value="{v('custom_options')}">
                <div class="row">
                    <div class="column"><label>English 客製化選項</label><input type="text" name="custom_options_en" value="{v('custom_options_en')}"></div>
                    <div class="column"><label>日本語 客製化選項</label><input type="text" name="custom_options_jp" value="{v('custom_options_jp')}"></div>
                    <div class="column"><label>한국어 客製化選項</label><input type="text" name="custom_options_kr" value="{v('custom_options_kr')}"></div>
                </div>

                <div style="margin-top:40px; text-align: right; border-top: 1px solid #eee; padding-top: 20px;">
                    <a href="{url_for('admin.admin_panel')}" class="button button-outline">❌ 取消回後台</a>
                    <button type="submit" style="margin-left:10px;">💾 儲存所有變更</button>
                </div>
            </form>
        </div>
    </body></html>"""

# --- 其他功能路由 ---
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

# --- 新增：清空訂單功能 ---
@admin_bp.route('/reset_orders')
def reset_orders():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 清空 orders 資料表
        # 注意：使用 DELETE 比較安全；若使用 PostgreSQL 且想重置 ID 可用 "TRUNCATE TABLE orders RESTART IDENTITY;"
        cur.execute("DELETE FROM orders;") 
        conn.commit()
        msg = "✅ 所有歷史訂單已清空！"
    except Exception as e:
        conn.rollback()
        msg = f"❌ 清空失敗: {e}"
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('admin.admin_panel', msg=msg))
