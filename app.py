import os
import psycopg2
import json
import threading
import urllib.request
import time  
import io  
import pandas as pd  
from flask import Flask, request, jsonify, redirect, url_for, Response, send_file 
from datetime import datetime, date
from datetime import timedelta 

app = Flask(__name__)

# --- 資料庫連線 ---
def get_db_connection():
    db_uri = os.environ.get("DATABASE_URL")
    return psycopg2.connect(db_uri)

# --- 翻譯字典 ---
def load_translations():
    return {
        "zh": {
            "title": "線上點餐", "welcome": "歡迎點餐", "table_placeholder": "請輸入桌號", 
            "table_label": "桌號", "add": "加入", "sold_out": "已售完", "cart_detail": "查看明細", 
            "total": "合計", "checkout": "去結帳", "cart_title": "購物車明細", "empty_cart": "購物車是空的", 
            "close": "關閉", "confirm_delete": "確定刪除？", "confirm_order": "確定送出訂單？", 
            "modal_unit_price": "單價", "modal_add_cart": "加入購物車", "modal_cancel": "取消", 
            "custom_options": "客製化選項", "order_success": "下單成功！", "kitchen_prep": "廚房備餐中", 
            "pay_at_counter": "請至櫃檯結帳", "order_details": "訂單明細", 
            "print_receipt_opt": "列印收據", "daily_seq_prefix": "單號", "ai_note": "翻譯由 AI 提供",
            "edit_options": "重選選項"
        },
        "en": {
            "title": "Order", "welcome": "Welcome", "table_placeholder": "Table No.",
            "table_label": "Table", "add": "Add", "sold_out": "Sold Out", "cart_detail": "Cart",
            "total": "Total", "checkout": "Checkout", "cart_title": "Cart", "empty_cart": "Empty",
            "close": "Close", "confirm_delete": "Remove?", "confirm_order": "Submit?",
            "modal_unit_price": "Price", "modal_add_cart": "Add to Cart", "modal_cancel": "Cancel",
            "custom_options": "Options", "order_success": "Success!", "kitchen_prep": "Preparing...",
            "pay_at_counter": "Please pay at counter", "order_details": "Order Details",
            "print_receipt_opt": "Print Receipt", "daily_seq_prefix": "No.", "ai_note": "Translated by AI",
            "edit_options": "Edit Options"
        },
        "jp": {
            "title": "注文", "welcome": "ようこそ", "table_placeholder": "卓番",
            "table_label": "卓番", "add": "追加", "sold_out": "完売", "cart_detail": "カート",
            "total": "合計", "checkout": "会計", "cart_title": "詳細", "empty_cart": "空です",
            "close": "閉じる", "confirm_delete": "削除？", "confirm_order": "送信？",
            "modal_unit_price": "単価", "modal_add_cart": "カートへ", "modal_cancel": "キャンセル",
            "custom_options": "オプション", "order_success": "送信完了", "kitchen_prep": "調理中...",
            "pay_at_counter": "レジでお会計ください", "order_details": "注文詳細",
            "print_receipt_opt": "レシート印刷", "daily_seq_prefix": "番号", "ai_note": "AIによる翻訳",
            "edit_options": "オプション変更"
        },
        "kr": {
            "title": "주문", "welcome": "환영합니다", "table_placeholder": "테이블 번호",
            "table_label": "테이블", "add": "추가", "sold_out": "매진", "cart_detail": "장바구니",
            "total": "합계", "checkout": "결제하기", "cart_title": "상세 내역", "empty_cart": "비어 있음",
            "close": "닫기", "confirm_delete": "삭제하시겠습니까?", "confirm_order": "주문하시겠습니까?",
            "modal_unit_price": "단가", "modal_add_cart": "장바구니 담기", "modal_cancel": "취소",
            "custom_options": "옵션", "order_success": "주문 성공!", "kitchen_prep": "준비 중...",
            "pay_at_counter": "카운터에서 결제해주세요", "order_details": "주문 내역",
            "print_receipt_opt": "영수증 출력", "daily_seq_prefix": "번호", "ai_note": "AI 번역",
            "edit_options": "옵션 변경"
        }
    }

# --- 1. 資料庫初始化 ---
@app.route('/init_db')
def init_db():
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                price INTEGER NOT NULL,
                category VARCHAR(50),
                image_url TEXT,
                is_available BOOLEAN DEFAULT TRUE,
                custom_options TEXT,
                sort_order INTEGER DEFAULT 100,
                name_en VARCHAR(100), name_jp VARCHAR(100), name_kr VARCHAR(100),
                custom_options_en TEXT, custom_options_jp TEXT, custom_options_kr TEXT,
                print_category VARCHAR(20) DEFAULT 'Noodle',
                category_en VARCHAR(50), category_jp VARCHAR(50), category_kr VARCHAR(50)
            );
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                table_number VARCHAR(10),
                items TEXT NOT NULL, 
                total_price INTEGER NOT NULL,
                status VARCHAR(20) DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                daily_seq INTEGER DEFAULT 0,
                content_json TEXT,
                need_receipt BOOLEAN DEFAULT FALSE,
                lang VARCHAR(10) DEFAULT 'zh'
            );
        ''')
        alters = [
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_available BOOLEAN DEFAULT TRUE;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS image_url TEXT;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS name_en VARCHAR(100);",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS name_jp VARCHAR(100);",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS name_kr VARCHAR(100);",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS custom_options_en TEXT;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS custom_options_jp TEXT;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS custom_options_kr TEXT;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS print_category VARCHAR(20) DEFAULT 'Noodle';",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS category_en VARCHAR(50);",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS category_jp VARCHAR(50);",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS category_kr VARCHAR(50);",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS daily_seq INTEGER DEFAULT 0;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS content_json TEXT;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS need_receipt BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS lang VARCHAR(10) DEFAULT 'zh';"
        ]
        for cmd in alters:
            try: cur.execute(cmd)
            except: pass

        return "資料庫結構檢查完成。<a href='/'>回首頁</a>"
    except Exception as e:
        return f"DB Error: {e}"
    finally:
        cur.close(); conn.close()


# --- 2. 首頁與語言選擇 (加大文字與視覺優化版) ---
@app.route('/')
def language_select():
    tbl = request.args.get('table', '')
    qs_table = f"&table={tbl}" if tbl else ""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Select Language</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
        <style>
            body {{
                font-family: 'Microsoft JhengHei', -apple-system, sans-serif;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                margin: 0;
                background: #ffffff;
                padding: 20px;
                box-sizing: border-box;
            }}
            .header-info {{
                text-align: center;
                margin-bottom: 40px;
            }}
            h2 {{
                color: #333;
                font-size: 2.2em; /* 放大店名文字 */
                margin: 0 0 10px 0;
                font-weight: 900;
            }}
            .sub-title {{
                color: #666;
                font-size: 1.2em;
                margin-bottom: 20px;
            }}
            .btn-container {{
                display: flex;
                flex-direction: column;
                width: 100%;
                max-width: 350px;
            }}
            .btn {{
                padding: 22px; /* 增加點擊區域 */
                margin: 12px 0;
                text-align: center;
                text-decoration: none;
                font-size: 1.6em; /* 放大按鈕文字 */
                font-weight: bold;
                border-radius: 60px;
                color: white;
                box-shadow: 0 6px 15px rgba(0,0,0,0.15);
                transition: transform 0.1s, box-shadow 0.1s;
                border: none;
            }}
            .btn:active {{
                transform: scale(0.95);
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }}
            /* 語言按鈕顏色 */
            .zh {{ background: linear-gradient(135deg, #e91e63, #c2185b); }} 
            .en {{ background: linear-gradient(135deg, #007bff, #0056b3); }} 
            .jp {{ background: linear-gradient(135deg, #ff9800, #f57c00); }} 
            .kr {{ background: linear-gradient(135deg, #20c997, #17a2b8); }}

            .footer-info {{
                margin-top: 50px;
                text-align: center;
                color: #555;
            }}
            .footer-info h3 {{
                font-size: 1.5em; /* 放大電話 */
                margin: 5px 0;
                color: #000;
            }}
            .footer-info h4 {{
                font-size: 1.1em; /* 放大地址 */
                margin: 5px 0;
                font-weight: normal;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <div class="header-info">
            <h2>龍江路大鼎豬血湯專門店</h2>
            <div class="sub-title">請選擇語言 / Select Language</div>
        </div>

        <div class="btn-container">
            <a href="/menu?lang=zh{qs_table}" class="btn zh">中文</a>
            <a href="/menu?lang=en{qs_table}" class="btn en">English</a>
            <a href="/menu?lang=jp{qs_table}" class="btn jp">日本語</a>
            <a href="/menu?lang=kr{qs_table}" class="btn kr">한국어</a>
        </div>

        <div class="footer-info">
            <h3>📞 02-2515-2519</h3>
            <h4>📍 10491臺北市中山區龍江路164號</h4>
        </div>
    </body>
    </html>
    """


# --- 3. 點餐頁面 ---
@app.route('/menu', methods=['GET', 'POST'])
def menu():
    # 1. 取得當前語系，預設為 'zh'
    lang = request.args.get('lang', 'zh')
    translations = load_translations()
    t = translations.get(lang, translations['zh'])
    
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        try:
            table_number = request.form.get('table_number')
            cart_json = request.form.get('cart_data')
            need_receipt = request.form.get('need_receipt') == 'on'
            # 從表單隱藏欄位抓回使用者當前的語系
            final_lang = request.form.get('lang_input', lang)
            old_order_id = request.form.get('old_order_id')

            if not cart_json or cart_json == '[]': 
                return "Empty Cart"
            
            cart_items = json.loads(cart_json)
            total_price = 0
            display_list = []

            for item in cart_items:
                price = int(float(item['unit_price']))
                qty = int(float(item['qty']))
                total_price += (price * qty)
                
                # 根據語系決定顯示名稱
                name_key = f"name_{final_lang}"
                n_display = item.get(name_key, item.get('name_zh'))
                opt_key = f"options_{final_lang}"
                opts = item.get(opt_key, item.get('options_zh', []))
                opt_str = f"({','.join(opts)})" if opts else ""
                display_list.append(f"{n_display} {opt_str} x{qty}")

            items_str = " + ".join(display_list)
            
            # 寫入資料庫
            cur.execute("""
                INSERT INTO orders (table_number, items, total_price, lang, daily_seq, content_json, need_receipt)
                VALUES (%s, %s, %s, %s, (SELECT COALESCE(MAX(daily_seq), 0) + 1 FROM orders WHERE created_at >= CURRENT_DATE), %s, %s) 
                RETURNING id
            """, (table_number, items_str, total_price, final_lang, cart_json, need_receipt))

            oid = cur.fetchone()[0]
            
            if old_order_id:
                cur.execute("UPDATE orders SET status='Cancelled' WHERE id=%s", (old_order_id,))
            
            conn.commit()
            
            # 如果是修改訂單，關閉視窗；如果是新訂單，導向成功頁面並帶上語系
            if old_order_id: 
                return "<script>window.close();</script>"
            return redirect(url_for('order_success', order_id=oid, lang=final_lang))
            
        except Exception as e:
            conn.rollback()
            return f"Order Failed: {e}"
        finally:
            cur.close()
            conn.close()

    # GET 請求部分
    url_table = request.args.get('table', '')
    edit_oid = request.args.get('edit_oid')
    preload_cart = "[]"
    
    if edit_oid:
        cur.execute("SELECT table_number, content_json FROM orders WHERE id=%s", (edit_oid,))
        old_data = cur.fetchone()
        if old_data:
            if not url_table: url_table = old_data[0]
            preload_cart = old_data[1]

    cur.execute("""
        SELECT id, name, price, category, image_url, is_available, custom_options, sort_order,
                name_en, name_jp, name_kr, custom_options_en, custom_options_jp, custom_options_kr, 
                print_category, category_en, category_jp, category_kr
        FROM products ORDER BY sort_order ASC, id ASC
    """)
    products = cur.fetchall()
    cur.close()
    conn.close()

    p_list = []
    for p in products:
        p_list.append({
            'id': p[0], 'name_zh': p[1], 'name_en': p[8] or p[1], 'name_jp': p[9] or p[1], 'name_kr': p[10] or p[1],
            'price': p[2], 
            'category_zh': p[3], 'category_en': p[15] or p[3], 'category_jp': p[16] or p[3], 'category_kr': p[17] or p[3],
            'image_url': p[4] or '', 'is_available': p[5], 
            'custom_options_zh': p[6].split(',') if p[6] else [],
            'custom_options_en': p[11].split(',') if p[11] else (p[6].split(',') if p[6] else []),
            'custom_options_jp': p[12].split(',') if p[12] else (p[6].split(',') if p[6] else []),
            'custom_options_kr': p[13].split(',') if p[13] else (p[6].split(',') if p[6] else []),
            'print_category': p[14] or 'Noodle'
        })
    return render_frontend(p_list, t, url_table, lang, preload_cart, edit_oid)

def render_frontend(products, t, default_table, lang, preload_cart, edit_oid):
    p_json = json.dumps(products)
    t_json = json.dumps(t)
    old_oid_input = f'<input type="hidden" name="old_order_id" value="{edit_oid}">' if edit_oid else ''
    edit_notice = f'<div style="background:#fff3cd;padding:12px;color:#856404;text-align:center;font-weight:bold;font-size:1.1em;">⚠️ 正在編輯 #{edit_oid}</div>' if edit_oid else ''

    return f"""
    <!DOCTYPE html>
    <html><head><title>{t['title']}</title><meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=0">
    <style>
        body{{font-family:'Microsoft JhengHei',sans-serif;margin:0;padding-bottom:160px;background:#f8f9fa;touch-action:manipulation; font-size: 16px;}}
        .header{{background:white;padding:15px;position:sticky;top:0;z-index:99;box-shadow:0 2px 5px rgba(0,0,0,0.1);}}
        #visible_table {{ padding:12px; width:100%; box-sizing:border-box; border:2px solid #ddd; border-radius:8px; font-size:1.2em; margin-bottom:10px; font-weight:bold; }}
        .cat-bar {{ display: flex; overflow-x: auto; white-space: nowrap; padding: 10px 0; gap: 12px; scrollbar-width: none; }}
        .cat-bar::-webkit-scrollbar {{ display: none; }}
        .cat-btn {{ background: #f1f3f5; border: 1px solid #dee2e6; padding: 8px 20px; border-radius: 25px; font-size: 1.1em; color: #495057; cursor: pointer; font-weight: bold; }}
        .cat-btn.active {{ background: #28a745; color: white; border-color: #28a745; }}
        .menu-item{{background:white;margin:12px;padding:15px;border-radius:12px;display:flex;box-shadow:0 2px 8px rgba(0,0,0,0.08);position:relative;}}
        .menu-img{{width:90px;height:90px;border-radius:10px;object-fit:cover;background:#eee;}}
        .menu-info{{flex:1;padding-left:15px;display:flex;flex-direction:column;justify-content:space-between;}}
        .menu-info b {{ font-size: 1.25em; color: #333; }}
        .menu-price {{ color:#e91e63; font-size: 1.2em; font-weight: bold; margin-top: 5px; }}
        .add-btn{{background:#28a745;color:white;border:none;padding:8px 20px;border-radius:20px;align-self:flex-end; font-size: 1.05em; font-weight: bold;}}
        .sold-out {{ filter: grayscale(1); opacity: 0.6; pointer-events: none; }}
        .sold-out-badge {{ position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.7); color: white; padding: 4px 10px; border-radius: 5px; font-size: 0.9em; font-weight: bold; z-index: 5; }}
        .cart-bar{{position:fixed;bottom:0;width:100%;background:white;padding:15px;box-shadow:0 -4px 15px rgba(0,0,0,0.15);display:none;flex-direction:column;box-sizing:border-box;z-index:100;border-radius: 20px 20px 0 0;}}
        .cart-summary{{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;padding:0 5px;}}
        .cart-summary div {{ font-size: 1.3em !important; }}
        .cart-buttons{{display:flex;gap:12px;}}
        .btn-view-cart{{background:#ff9800;color:white;border:none;flex:1;padding:15px;border-radius:12px;font-weight:bold;font-size:1.2em;}}
        .btn-checkout{{background:#28a745;color:white;border:none;flex:1;padding:15px;border-radius:12px;font-weight:bold;font-size:1.2em;}}
        .modal{{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);display:none;z-index:200;justify-content:center;align-items:flex-end;}}
        .modal-c{{background:white;width:100%;padding:25px 20px;border-radius:25px 25px 0 0;max-height:85vh;overflow-y:auto;box-sizing:border-box;position:relative;}}
        .opt-tag{{border:2px solid #ddd;padding:10px 18px;border-radius:25px;margin:5px;display:inline-block;cursor:pointer; font-size: 1.1em; font-weight: 500;}}
        .opt-tag.sel{{background:#e3f2fd;border-color:#2196f3;color:#2196f3; font-weight: bold;}}
        .cat-header {{padding:12px 15px;font-weight:bold;color:#444;background:#eee;margin-top:10px; scroll-margin-top: 150px; font-size: 1.2em;}}
        .qty-ctrl{{display:flex;align-items:center;gap:15px;justify-content:center;margin:20px 0;}}
        .qty-ctrl button{{width:50px;height:50px;border-radius:25px;border:2px solid #ccc;background:white;font-size:1.8em;line-height:1; font-weight: bold;}}
        .qty-input{{width:80px;text-align:center;font-size:1.4em;border:2px solid #ddd;padding:8px;border-radius:8px;font-weight:bold;}}
        .cart-item-row{{border-bottom:1px solid #eee;padding:15px 0;display:flex;flex-direction:column;gap:8px;}}
        .cart-item-main{{display:flex; justify-content:space-between; align-items:flex-start;}}
        .cart-item-main b {{ font-size: 1.3em; }}
        .cart-qty-sub{{display:flex;align-items:center;justify-content:space-between;margin-top:8px;}}
        .btn-edit-item {{ border: 2px solid #2196f3; background: #fff; color: #2196f3; padding: 6px 15px; border-radius: 15px; font-size: 1em; font-weight: bold; cursor: pointer; margin-left: 10px; }}
        .btn-delete-item {{ color: #dc3545; border: none; background: none; font-size: 1.6em; padding: 0 10px; cursor: pointer; }}
    </style></head><body>
    <div class="header">
        {edit_notice}
        <h3 style="margin:0 0 10px 0;">{t['welcome']}</h3>
        <input type="text" id="visible_table" value="{default_table}" placeholder="{t['table_placeholder']}" inputmode="numeric">
        <div class="cat-bar" id="cat-nav"></div>
    </div>
    <div id="list"></div>
    <form id="order-form" method="POST" action="/menu">
        <input type="hidden" name="cart_data" id="cart_input">
        <input type="hidden" name="table_number" id="tbl_input">
        <input type="hidden" name="lang_input" id="lang_final_input" value="{lang}">
        {old_oid_input}
        <div class="cart-bar" id="bar">
            <div class="cart-summary">
                <div style="font-weight:900;">Total: $<span id="tot">0</span> (<span id="cnt">0</span>)</div>
                <label style="font-weight:bold;"><input type="checkbox" name="need_receipt" checked style="transform: scale(1.3); margin-right: 8px;"> {t['print_receipt_opt']}</label>
            </div>
            <div class="cart-buttons">
                <button type="button" class="btn-view-cart" onclick="showCart()">🛒 {t['cart_detail']}</button>
                <button type="button" class="btn-checkout" onclick="sub()">{t['checkout']}</button>
            </div>
        </div>
    </form>
    <div class="modal" id="opt-m" onclick="closeModalByBg(event, 'opt-m')">
        <div class="modal-c" onclick="event.stopPropagation()">
            <h3 id="m-name"></h3><div id="m-opts"></div>
            <div class="qty-ctrl">
                <button onclick="cq(-1)">-</button>
                <input type="number" id="m-q" class="qty-input" value="1" min="1" inputmode="numeric">
                <button onclick="cq(1)">+</button>
            </div>
            <button id="m-confirm-btn" onclick="addC()" style="width:100%;background:#28a745;color:white;padding:16px;border:none;border-radius:12px;margin-top:15px;font-size:1.3em;font-weight:bold;">{t['modal_add_cart']}</button>
            <button onclick="document.getElementById('opt-m').style.display='none'" style="width:100%;background:white;padding:12px;border:none;margin-top:10px;font-size:1.1em;color:#666;">{t['modal_cancel']}</button>
        </div>
    </div>
    <div class="modal" id="cart-m" onclick="closeModalByBg(event, 'cart-m')">
        <div class="modal-c" onclick="event.stopPropagation()">
            <h3 style="border-bottom: 2px solid #eee; padding-bottom: 10px;">{t['cart_title']}</h3>
            <div id="c-list"></div>
            <button onclick="document.getElementById('cart-m').style.display='none'" style="width:100%;padding:15px;margin-top:20px;border:2px solid #ddd;border-radius:12px;background:#f8f9fa;font-size:1.2em;font-weight:bold;">{t['close']}</button>
        </div>
    </div>

    <script>
    const P={p_json}, T={t_json}, PRELOAD={preload_cart}, CUR_LANG="{lang}";
    let C=[], cur=null, selectedOptIndices=[], addP=0, editIndex=-1;
    if(PRELOAD && PRELOAD.length > 0) C = PRELOAD;

    let h="", lastCatKey="", cats=[];
    P.forEach(p=>{{
        let currentCatName = p['category_' + CUR_LANG] || p.category_zh;
        let catId = "cat-" + p.category_zh; 
        if(p.category_zh != lastCatKey) {{ 
            h+=`<div class="cat-header" id="${{catId}}">${{currentCatName}}</div>`; 
            lastCatKey=p.category_zh; 
            cats.push({{ id: catId, name: currentCatName }});
        }}
        let isAvail = p.is_available;
        let d_name = p['name_' + CUR_LANG] || p.name_zh;
        h+=`<div class="menu-item ${{isAvail ? '' : 'sold-out'}}">
            ${{isAvail ? '' : `<div class="sold-out-badge">${{T.sold_out}}</div>`}}
            ${{p.image_url ? `<img src="${{p.image_url}}" class="menu-img">` : ''}}
            <div class="menu-info">
                <div><b>${{d_name}}</b><div class="menu-price">$${{p.price}}</div></div>
                <button class="add-btn" onclick="openOpt(${{p.id}})" ${{isAvail ? '' : 'disabled'}}>${{isAvail ? T.add : T.sold_out}}</button>
            </div>
        </div>`;
    }});
    document.getElementById('list').innerHTML=h;

    let navH = "";
    cats.forEach(c => {{ navH += `<div class="cat-btn" onclick="scrollToCat('${{c.id}}', this)">${{c.name}}</div>`; }});
    document.getElementById('cat-nav').innerHTML = navH;

    function scrollToCat(catId, btn) {{
        const el = document.getElementById(catId);
        if(el) {{
            const offset = 150;
            const elementPosition = el.getBoundingClientRect().top + window.pageYOffset - offset;
            window.scrollTo({{ top: elementPosition, behavior: 'smooth' }});
            document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        }}
    }}

    function closeModalByBg(e, id) {{ document.getElementById(id).style.display = 'none'; }}

    function openOpt(productId, cartIndex = -1){{
        cur = P.find(x=>x.id==productId);
        editIndex = cartIndex;
        selectedOptIndices = [];
        addP = 0;
        
        let d_name = cur['name_' + CUR_LANG] || cur.name_zh;
        document.getElementById('m-name').innerText = (editIndex > -1 ? "✏️ " : "") + d_name;
        
        // 修改儲存修改的按鈕文字
        let saveText = CUR_LANG === 'en' ? 'Save Changes' : (CUR_LANG === 'jp' ? '変更を保存' : (CUR_LANG === 'kr' ? '변경 사항 저장' : '儲存修改'));
        document.getElementById('m-confirm-btn').innerText = editIndex > -1 ? saveText : T.modal_add_cart;
        
        let area = document.getElementById('m-opts'); 
        area.innerHTML = "";
        let opts = cur['custom_options_' + CUR_LANG] || cur.custom_options_zh;
        let existingOpts = editIndex > -1 ? C[editIndex].options_zh : [];

        opts.forEach((o, index)=>{{
            let parts = o.split(/[+]/);
            let n = parts[0].trim(), p = parts.length>1 ? parseInt(parts[1]) : 0;
            let d = document.createElement('div'); d.className='opt-tag';
            d.innerText = n + (p?` (+$${{p}})`:'');
            
            if(editIndex > -1 && existingOpts.includes(cur.custom_options_zh[index])) {{
                selectedOptIndices.push(index); addP += p; d.classList.add('sel');
            }}
            d.onclick=()=>{{
                if(selectedOptIndices.includes(index)){{
                    selectedOptIndices = selectedOptIndices.filter(i=>i!=index);
                    addP-=p; d.classList.remove('sel');
                }} else {{
                    selectedOptIndices.push(index);
                    addP+=p; d.classList.add('sel');
                }}
            }};
            area.appendChild(d);
        }});
        document.getElementById('m-q').value = editIndex > -1 ? C[editIndex].qty : 1;
        document.getElementById('opt-m').style.display = 'flex';
        document.getElementById('cart-m').style.display = 'none';
    }}

    function cq(n){{
        let input = document.getElementById('m-q');
        let val = parseInt(input.value) || 1;
        if(val + n >= 1) input.value = val + n;
    }}

    function addC(){{
        let q = parseInt(document.getElementById('m-q').value) || 1;
        let itemData = {{ 
            id: cur.id, 
            name_zh: cur.name_zh, name_en: cur.name_en, name_jp: cur.name_jp, name_kr: cur.name_kr, 
            unit_price: cur.price + addP, qty: q, 
            options_zh: selectedOptIndices.map(idx => cur.custom_options_zh[idx]),
            options_en: selectedOptIndices.map(idx => cur.custom_options_en[idx]),
            options_jp: selectedOptIndices.map(idx => cur.custom_options_jp[idx]),
            options_kr: selectedOptIndices.map(idx => cur.custom_options_kr[idx]),
            category: cur.category_zh, print_category: cur.print_category 
        }};
        if(editIndex > -1) C[editIndex] = itemData;
        else C.push(itemData);
        document.getElementById('opt-m').style.display='none'; 
        upd();
        if(editIndex > -1) showCart();
    }}

    function upd(){{
        if(C.length){{
            document.getElementById('bar').style.display='flex';
            document.getElementById('tot').innerText = C.reduce((a,b)=>a+b.unit_price*b.qty,0);
            document.getElementById('cnt').innerText = C.reduce((a,b)=>a+b.qty,0);
        }} else document.getElementById('bar').style.display='none';
    }}

    function updateCartQty(idx, n){{
        C[idx].qty += n;
        if(C[idx].qty <= 0) C.splice(idx, 1);
        showCart(); upd();
    }}

    function showCart(){{
        let h="";
        C.forEach((i,x)=>{{
            let d_name = i['name_' + CUR_LANG] || i.name_zh;
            let opts = i['options_' + CUR_LANG] || i.options_zh || [];
            let opt_str = opts.length ? `<div style="font-size:0.95em;color:#666;margin-top:2px;">(${{opts.join(',')}})</div>` : '';
            
            h+=`<div class="cart-item-row">
                <div class="cart-item-main">
                    <div style="flex:1;">
                        <b>${{d_name}}</b>${{opt_str}}
                    </div>
                    <div style="font-weight:900;color:#e91e63;font-size:1.25em;margin-left:10px;">$${{i.unit_price * i.qty}}</div>
                </div>
                <div class="cart-qty-sub">
                    <div style="display:flex; align-items:center;">
                        <button class="btn-delete-item" onclick="if(confirm(T.confirm_delete)){{C.splice(${{x}},1);upd();showCart();}}">🗑️</button>
                        <button class="btn-edit-item" onclick="openOpt(${{i.id}}, ${{x}})">${{T.edit_options}}</button>
                    </div>
                    <div class="qty-ctrl" style="margin:0;">
                        <button onclick="updateCartQty(${{x}}, -1)">-</button>
                        <input type="number" class="qty-input" value="${{i.qty}}" readonly style="border:none; width:40px;">
                        <button onclick="updateCartQty(${{x}}, 1)">+</button>
                    </div>
                </div>
            </div>`;
        }});
        document.getElementById('c-list').innerHTML=h || `<p style="text-align:center;font-size:1.2em;padding:20px;">${{T.empty_cart}}</p>`;
        document.getElementById('cart-m').style.display='flex';
    }}

    function sub(){{
        let t = document.getElementById('visible_table').value;
        if(!t) return alert(T.table_placeholder);
        // 關鍵：提交前確保隱藏欄位的語系與當前一致
        document.getElementById('lang_final_input').value = CUR_LANG;
        document.getElementById('tbl_input').value = t;
        document.getElementById('cart_input').value = JSON.stringify(C);
        if(confirm(T.confirm_order)) document.getElementById('order-form').submit();
    }}
    upd(); 
    </script></body></html>
    """

    
# --- 4. 下單成功 (滿版優化版) ---
@app.route('/order_success')
def order_success():
    oid = request.args.get('order_id')
    lang = request.args.get('lang', 'zh')
    translations = load_translations()
    t = translations.get(lang, translations['zh'])
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT daily_seq, content_json, total_price, created_at FROM orders WHERE id=%s", (oid,))
    row = cur.fetchone(); conn.close()
    if not row: return "Order Not Found"
    
    seq, json_str, total, created_at = row
    tw_time = created_at + timedelta(hours=8)
    time_str = tw_time.strftime('%Y-%m-%d %H:%M:%S')
    items = json.loads(json_str) if json_str else []
    
    items_html = ""
    for i in items:
        # 取得對應語言名稱
        d_name = i.get(f'name_{lang}', i.get('name_zh', i.get('name', 'Product')))
        # 取得客製化選項
        ops = i.get(f'options_{lang}', i.get('options_zh', i.get('options', [])))
        opt_str = f" <br><small style='color:#777; font-size:0.9em;'>└ {', '.join(ops)}</small>" if ops else ""
        
        items_html += f"""
        <div style='display:flex; justify-content:space-between; align-items: flex-start; border-bottom:1px solid #eee; padding:15px 0;'>
            <div style="text-align: left; padding-right: 10px;">
                <div style="font-size:1.1em; font-weight:bold; color:#333;">{d_name} <span style="color:#888; font-weight:normal;">x{i['qty']}</span></div>
                {opt_str}
            </div>
            <div style="font-weight:bold; font-size:1.1em; white-space:nowrap;">${i['unit_price'] * i['qty']}</div>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Order Success</title>
        <style>
            body {{ margin: 0; padding: 0; background: #fdfdfd; font-family: 'Microsoft JhengHei', -apple-system, sans-serif; }}
            .container {{ 
                min-height: 100vh; 
                display: flex; 
                flex-direction: column; 
                padding: 20px; 
                box-sizing: border-box; 
            }}
            .card {{ 
                background: #fff; 
                flex-grow: 1; 
                border-radius: 20px; 
                box-shadow: 0 4px 20px rgba(0,0,0,0.08); 
                padding: 30px 20px; 
                text-align: center;
                display: flex;
                flex-direction: column;
            }}
            .success-icon {{ font-size: 60px; margin-bottom: 10px; }}
            .status-title {{ color: #28a745; margin: 0 0 20px 0; font-size: 1.8em; }}
            .seq-box {{ 
                background: #fff5f8; 
                border-radius: 15px; 
                padding: 20px; 
                margin-bottom: 25px; 
                border: 2px solid #ffeef2;
            }}
            .seq-label {{ font-size: 1em; color: #e91e63; font-weight: bold; margin-bottom: 8px; letter-spacing: 1px; }}
            .seq-number {{ font-size: 5em; font-weight: 900; color: #e91e63; line-height: 1; }}
            .notice-box {{ 
                background: #fdf6e3; 
                padding: 18px; 
                border-left: 6px solid #ff9800; 
                border-radius: 8px; 
                margin-bottom: 30px; 
                text-align: left; 
            }}
            .details-area {{ text-align: left; margin-bottom: 30px; }}
            .total-row {{ 
                text-align: right; 
                font-weight: 900; 
                font-size: 1.8em; 
                margin-top: 20px; 
                color: #d32f2f; 
                border-top: 2px solid #333; 
                padding-top: 15px; 
            }}
            .home-btn {{ 
                display: block; 
                padding: 18px; 
                background: #007bff; 
                color: white !important; 
                text-decoration: none; 
                border-radius: 12px; 
                font-weight: bold; 
                font-size: 1.2em; 
                margin-top: auto;
                box-shadow: 0 4px 10px rgba(0,123,255,0.3);
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <div class="success-icon">✅</div>
                <h1 class="status-title">{t['order_success']}</h1>
                
                <div class="seq-box">
                    <div class="seq-label">取餐單號 / ORDER NO.</div>
                    <div class="seq-number">#{seq:03d}</div>
                </div>

                <div class="notice-box">
                    <div style="font-weight:bold; color:#856404; font-size:1.3em; margin-bottom:5px;">⚠️ {t['pay_at_counter']}</div>
                    <div style="color:#856404; font-size:1em; line-height:1.4;">{t['kitchen_prep']}</div>
                </div>

                <div class="details-area">
                    <h3 style="border-bottom:2px solid #eee; padding-bottom:10px; margin-bottom:10px; color:#444;">🧾 {t['order_details']}</h3>
                    {items_html}
                    <div class="total-row">{t['total']}: ${total}</div>
                </div>

                <p style="color:#999; font-size:0.85em; margin: 20px 0;">下單時間: {time_str}</p>
                
                <a href="/?lang={lang}" class="home-btn">回首頁 / Back to Menu</a>
            </div>
        </div>
    </body>
    </html>
    """

# --- 5. 廚房看板 ---
@app.route('/kitchen')
def kitchen_panel():
    return """
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head><meta charset="UTF-8"><title>👨‍🍳 廚房出單看板</title>
    <style>
        body { background: #1a1a1a; color: #eee; font-family: "Microsoft JhengHei", sans-serif; padding: 0; margin: 0; }
        .header-container { display: flex; justify-content: space-between; align-items: center; padding: 15px 25px; background: #222; border-bottom: 3px solid #ff9800; }
        h1 { color: #ff9800; margin: 0; font-size: 28px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 20px; padding: 25px; }
        .card { background: #2d2d2d; border-radius: 12px; padding: 20px; box-shadow: 0 6px 20px rgba(0,0,0,0.4); border-top: 10px solid #ff9800; position: relative; transition: transform 0.2s; }
        .card.completed { border-top-color: #28a745; opacity: 0.6; }
        .card.cancelled { border-top-color: #dc3545; opacity: 0.5; text-decoration: line-through; }
        .tag { position: absolute; top: 12px; right: 15px; font-weight: bold; font-size: 1.1em; }
        .items { background: #383838; padding: 18px; border-radius: 8px; margin: 15px 0; font-size: 1.3em; line-height: 1.6; border: 1px solid #444; }
        .btn { display: inline-block; padding: 12px 18px; border-radius: 8px; text-decoration: none; color: white; margin-right: 8px; font-size: 1em; border: none; cursor: pointer; font-weight: bold; }
        .btn-report { background: #6f42c1; } .btn-complete { background: #28a745; } .btn-print { background: #17a2b8; } .btn-void { background: #822; } .btn-edit { background: #555; }
        #audio-banner { background: #d32f2f; color: white; text-align: center; padding: 10px; font-weight: bold; cursor: pointer; }
    </style></head><body>
    <div id="audio-banner" onclick="enableAudio()">🔔 點擊此處啟動「新訂單語音」與「自動列印」功能</div>
    <div class="header-container"><h1>👨‍🍳 廚房出單看板</h1><div><a href="/kitchen/report" class="btn btn-report">📊 當日營收報表</a></div></div>
    <div id="order-grid" class="grid">正在同步訂單數據...</div>
    <audio id="notice-sound" preload="auto"><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg"></audio>
    <script>
        let lastMaxSeq = 0, isFirstLoad = true, audioUnlocked = false;
        function enableAudio() { audioUnlocked = true; document.getElementById('audio-banner').style.display = 'none'; const audio = document.getElementById('notice-sound'); audio.play().then(() => { audio.pause(); audio.currentTime = 0; }); alert("功能已啟動！"); }
        function action(url) { fetch(url).then(() => { refreshOrders(); }); }
        function refreshOrders() {
            fetch('/check_new_orders?current_seq=' + lastMaxSeq).then(res => res.json()).then(data => {
                if (data.html) document.getElementById('order-grid').innerHTML = data.html;
                if (!isFirstLoad && data.new_ids && data.new_ids.length > 0) {
                    if (audioUnlocked) { document.getElementById('notice-sound').play(); data.new_ids.forEach(id => { window.open('/print_order/' + id, '_blank'); }); }
                }
                lastMaxSeq = data.max_seq; isFirstLoad = false;
            });
        }
        setInterval(refreshOrders, 5000); refreshOrders();
    </script></body></html>
    """

# --- 5. 廚房看板 API ---
@app.route('/check_new_orders')
def check_new_orders():
    current_max = request.args.get('current_seq', 0, type=int)
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT id, table_number, items, total_price, status, created_at, lang, daily_seq, content_json 
        FROM orders WHERE created_at > (NOW() - INTERVAL '18 hours') 
        ORDER BY CASE WHEN status = 'Pending' THEN 0 ELSE 1 END, daily_seq DESC
    """)
    orders = cur.fetchall()
    cur.execute("SELECT MAX(daily_seq) FROM orders WHERE created_at > (NOW() - INTERVAL '18 hours')")
    max_seq_val = cur.fetchone()[0] or 0
    new_order_ids = []
    if current_max > 0:
        cur.execute("SELECT id FROM orders WHERE daily_seq > %s AND created_at > (NOW() - INTERVAL '18 hours')", (current_max,))
        new_order_ids = [r[0] for r in cur.fetchall()]
    conn.close()
    html_content = ""
    if not orders: html_content = "<div style='grid-column:1/-1;text-align:center;padding:100px;font-size:1.5em;color:#666;'>目前無新訂單</div>"
    for o in orders:
        oid, table, raw_items, total, status, created, order_lang, seq_num, c_json = o
        cls, seq = status.lower(), f"{seq_num:03d}"
        tw_time = created + timedelta(hours=8)
        time_str = tw_time.strftime('%H:%M:%S')
        items_html = ""
        try:
            if c_json:
                cart = json.loads(c_json)
                for item in cart:
                    n = item.get('name_zh', item.get('name', '商品'))
                    ops = item.get('options_zh', item.get('options', []))
                    ops_str = f"<br><small style='color:#aaa'>└ {', '.join(ops)}</small>" if ops else ""
                    items_html += f"<div>● {n} <span style='color:#ff9800'>x{item['qty']}</span> {ops_str}</div>"
            else: items_html = raw_items.replace("+", "<br>● ")
        except: items_html = f"解析錯誤: {raw_items}"
        tag = "已完成" if status == 'Completed' else "已作廢" if status == 'Cancelled' else "● 新訂單"
        btns = ""
        if status == 'Pending': btns += f"<button onclick='action(\"/kitchen/complete/{oid}\")' class='btn btn-complete'>✔️ 付款完成</button>"
        if status != 'Cancelled':
            btns += f"<a href='/menu?edit_oid={oid}&lang=zh' target='_blank' class='btn btn-edit'>✏️ 修改 (中)</a>"
            btns += f"<button onclick='if(confirm(\"確定作廢？\")) action(\"/order/cancel/{oid}\")' class='btn btn-void'>🗑️ 作廢</button>"
        btns += f"<a href='/print_order/{oid}' target='_blank' class='btn btn-print'>🖨️ 列印 ({order_lang})</a>"
        html_content += f"""
        <div class="card {cls}"><div class="tag" style="color:{'#28a745' if status=='Completed' else '#ff9800'}">{tag}</div>
            <div style="font-size:0.9em; color:#888;">{time_str} (TPE) | 原始語系: <b>{order_lang}</b></div>
            <div style="margin: 10px 0;"><span style="font-size:2.5em; color:#ff9800; font-weight:bold; margin-right:10px;">#{seq}</span><span style="font-size:1.8em; background:#444; padding:2px 12px; border-radius:6px;">桌: {table}</span></div>
            <div class="items">{items_html}</div><div style="border-top: 1px solid #444; padding-top: 15px;">{btns}</div></div>"""
    return jsonify({'html': html_content, 'max_seq': max_seq_val, 'new_ids': new_order_ids})

# --- 6. 日結報表 ---
@app.route('/kitchen/report')
def daily_report():
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(total_price) FROM orders WHERE created_at >= CURRENT_DATE AND status != 'Cancelled'")
    valid_count, valid_total = cur.fetchone()
    cur.execute("SELECT COUNT(*), SUM(total_price) FROM orders WHERE created_at >= CURRENT_DATE AND status = 'Cancelled'")
    void_count, void_total = cur.fetchone()
    cur.execute("SELECT content_json FROM orders WHERE created_at >= CURRENT_DATE AND status != 'Cancelled'")
    valid_rows = cur.fetchall()
    cur.execute("SELECT content_json FROM orders WHERE created_at >= CURRENT_DATE AND status = 'Cancelled'")
    void_rows = cur.fetchall(); conn.close()
    def agg_items(rows):
        stats = {}
        for r in rows:
            if not r[0]: continue
            try:
                items = json.loads(r[0])
                for i in items:
                    name = i.get('name_zh', i.get('name', '未知'))
                    qty = int(i.get('qty', 0))
                    stats[name] = stats.get(name, 0) + qty
            except: pass
        return stats
    valid_stats, void_stats = agg_items(valid_rows), agg_items(void_rows)
    def render_table(stats_dict):
        if not stats_dict: return "<p style='text-align:center; color:#888;'>無資料</p>"
        h = "<table style='width:100%; border-collapse:collapse; font-size:14px; margin-top:5px;'><tr style='border-bottom:1px solid #000;'><th style='text-align:left;'>品項</th><th style='text-align:right;'>數量</th></tr>"
        for name, qty in sorted(stats_dict.items(), key=lambda x: x[1], reverse=True): h += f"<tr><td style='padding:4px 0;'>{name}</td><td style='text-align:right;'>{qty}</td></tr>"
        return h + "</table>"
    today_str = date.today().strftime('%Y-%m-%d')
    return f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><title>本日結帳單_{today_str}</title>
    <style>body {{ font-family: sans-serif; background: #eee; padding: 20px; display: flex; flex-direction: column; align-items: center; }} .ticket {{ background: white; width: 58mm; padding: 15px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }} h2, h3 {{ text-align: center; margin: 10px 0; }} hr {{ border: 0; border-top: 1px dashed #000; margin: 10px 0; }} .summary-box {{ margin-bottom: 15px; font-size: 15px; }} .summary-box b {{ font-size: 18px; color: green; }} .no-print {{ margin-top: 20px; display: flex; gap: 10px; }} .btn {{ padding: 10px 20px; border-radius: 5px; text-decoration: none; color: white; cursor: pointer; border: none; }} @media print {{ .no-print {{ display: none; }} body {{ background: white; padding: 0; }} .ticket {{ box-shadow: none; border: none; width: 100%; }} }}</style>
    </head><body><div class="ticket"><h2>日結報表</h2><p style="text-align:center; font-size:12px;">日期: {today_str}</p><hr><div class="summary-box"><b>✅ 有效營收</b><br>單量: {valid_count or 0} 筆<br>總額: <b>${valid_total or 0}</b></div>{render_table(valid_stats)}<hr><div class="summary-box" style="color:#822;"><b>❌ 作廢統計</b><br>單量: {void_count or 0} 筆<br>總額: ${void_total or 0}</div>{render_table(void_stats)}<hr><p style="text-align:center; font-size:10px; color:#888;">列印時間: {today_str}</p></div><div class="no-print"><button onclick="window.print()" class="btn" style="background:#28a745;">🖨️ 列印報表</button><a href="/kitchen" class="btn" style="background:#007bff;">🔙 回廚房看板</a></div></body></html>
    """

# --- 7. 狀態變更 ---
@app.route('/kitchen/complete/<int:oid>')
def complete_order(oid):
    c=get_db_connection(); c.cursor().execute("UPDATE orders SET status='Completed' WHERE id=%s",(oid,)); c.commit(); c.close()
    return redirect('/kitchen')

@app.route('/order/cancel/<int:oid>')
def cancel_order(oid):
    c=get_db_connection(); c.cursor().execute("UPDATE orders SET status='Cancelled' WHERE id=%s",(oid,)); c.commit(); c.close()
    return redirect('/kitchen')

# --- 8. 列印路由 (修正長訂單自動分頁問題，寬度長度全自動) ---
@app.route('/print_order/<int:oid>')
def print_order(oid):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT id, table_number, items, total_price, status, created_at, daily_seq, content_json, lang 
        FROM orders WHERE id=%s
    """, (oid,))
    o = cur.fetchone(); conn.close()
    if not o: return "No Data"

    oid_db, table_num, raw_items, total_val, status, created_at, daily_seq, c_json, order_lang = o
    seq = f"{daily_seq:03d}"
    items = []
    try:
        items = json.loads(c_json) if c_json else []
    except: return "解析失敗"

    is_void = (status == 'Cancelled')
    tw_time = created_at + timedelta(hours=8)
    time_str = tw_time.strftime('%Y-%m-%d %H:%M:%S')
    title = "❌ 作廢單 (VOID)" if is_void else "結帳單 (Receipt)"
    style = "text-decoration: line-through; color:red;" if is_void else ""

    def get_display_name(item):
        n_zh = item.get('name_zh', '商品')
        if order_lang == 'zh': return n_zh
        n_foreign = item.get(f'name_{order_lang}', item.get('name', n_zh))
        return f"{n_foreign}<br><small>({n_zh})</small>"

    def mk_ticket(t_name, item_list, show_total=False, is_kitchen=False):
        if not item_list and not show_total: return ""
        h = f"<div class='ticket' style='{style}'><div class='head'><h2>{t_name}</h2><h1>#{seq}</h1><p>Table: {table_num}</p><small>{time_str}</small></div><hr>"
        for i in item_list:
            qty = i.get('qty', 1); u_p = i.get('unit_price', 0)
            d_name = i.get('name_zh', '商品') if is_kitchen else get_display_name(i)
            ops = i.get('options_zh', []) if is_kitchen else i.get(f'options_{order_lang}', i.get('options', []))
            if isinstance(ops, str): ops = [ops]
            h += f"<div class='row'><span>{qty} x {d_name}</span><span>${u_p * qty}</span></div>"
            if ops: h += f"<div class='opt'>└ {', '.join(ops)}</div>"
        if show_total: h += f"<hr><div style='text-align:right;font-size:1.2em;font-weight:bold;'>Total: ${total_val}</div>"
        return h + "</div><div class='break'></div>"

    body = mk_ticket(title, items, show_total=True)
    if not is_void:
        noodles = [i for i in items if i.get('print_category', 'Noodle') == 'Noodle']
        soups = [i for i in items if i.get('print_category') == 'Soup']
        if noodles: body += mk_ticket("🍜 麵區工單", noodles, is_kitchen=True)
        if soups: body += mk_ticket("🍲 湯區工單", soups, is_kitchen=True)

    return f"""
    <html><head><meta charset="UTF-8">
    <style>
        /* 設定紙張：完全由內容決定大小 (auto) */
        @page {{ 
            size: auto; 
            margin: 0; 
        }}
        
        html, body {{
            margin: 0;
            padding: 0;
            background: #fff;
            font-family: 'Microsoft JhengHei', sans-serif;
            font-size: 14px;
            width: auto; /* 寬度自動 */
        }}

        .ticket {{ 
            padding: 4mm;
            box-sizing: border-box;
            page-break-inside: avoid; /* 防止單張票據內部被切斷 */
            overflow: visible;
        }} 

        .head {{ text-align: center; }} 
        .row {{ display: flex; justify-content: space-between; margin-top: 8px; font-weight: bold; gap: 10px; }} 
        .opt {{ font-size: 12px; color: #444; margin-left: 15px; }} 

        .break {{ 
            page-break-after: always; /* 不同工單之間強制換頁，確保自動切紙觸發 */
        }} 

        h1 {{ margin: 5px 0; font-size: 2.5em; }}
        h2 {{ margin: 5px 0; font-size: 1.5em; }}
        hr {{ border: none; border-top: 1px dashed #000; }}
        
        @media print {{ 
            body {{ width: auto; }} 
            .ticket {{ border: none; }}
        }}
    </style></head>
    <body onload='window.print(); setTimeout(function(){{ window.close(); }}, 1200);'>{body}</body></html>
    """

    
# --- 9. 後台管理 (Excel 匯入/匯出/一鍵清空版) ---

@app.route('/admin/reorder_products', methods=['POST'])
def reorder_products():
    try:
        data = request.get_json()
        new_order = data.get('order', [])
        conn = get_db_connection(); cur = conn.cursor()
        for index, prod_id in enumerate(new_order):
            cur.execute("UPDATE products SET sort_order = %s WHERE id = %s", (index + 1, prod_id))
        conn.commit(); cur.close(); conn.close()
        return jsonify({'status': 'success', 'message': '排序已更新'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/admin/toggle_product/<int:pid>')
def toggle_product(pid):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE products SET is_available = NOT is_available WHERE id = %s", (pid,))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/delete_product/<int:pid>')
def delete_product(pid):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id = %s", (pid,))
    conn.commit(); conn.close()
    return redirect('/admin')

# --- 核心新增功能：Excel 匯出 / Excel 匯入 / 清空 ---

@app.route('/admin/export_menu')
def export_menu():
    try:
        conn = get_db_connection()
        # 抓取所有欄位
        df = pd.read_sql("SELECT * FROM products ORDER BY sort_order ASC", conn)
        conn.close()

        # 將 DataFrame 轉換成 Excel 檔案
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Menu')
        output.seek(0)

        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="menu_export.xlsx"
        )
    except Exception as e:
        return f"匯出失敗: {e}"

@app.route('/admin/import_menu', methods=['POST'])
def import_menu():
    if 'menu_file' not in request.files: return "無檔案", 400
    file = request.files['menu_file']
    if file.filename == '': return "未選擇檔案", 400
    
    try:
        # 讀取 Excel 檔案
        df = pd.read_excel(file)
        # 將 NaN 替換為空字串，避免寫入資料庫出錯
        df = df.where(pd.notnull(df), None)
        
        conn = get_db_connection(); cur = conn.cursor()
        for _, p in df.iterrows():
            # 排除 ID，讓資料庫自動生成新 ID，避免衝突
            cur.execute("""
                INSERT INTO products (name, price, category, image_url, custom_options, 
                name_en, name_jp, name_kr, custom_options_en, custom_options_jp, custom_options_kr,
                print_category, category_en, category_jp, category_kr, sort_order, is_available)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                p.get('name'), p.get('price'), p.get('category'), p.get('image_url'), p.get('custom_options'),
                p.get('name_en'), p.get('name_jp'), p.get('name_kr'),
                p.get('custom_options_en'), p.get('custom_options_jp'), p.get('custom_options_kr'),
                p.get('print_category', 'Noodle'), p.get('category_en'), p.get('category_jp'), p.get('category_kr'),
                p.get('sort_order', 999), p.get('is_available', True)
            ))
        conn.commit(); conn.close()
        return redirect('/admin')
    except Exception as e:
        return f"匯入失敗 (請確保欄位名稱正確): {e}"

@app.route('/admin/reset_menu')
def reset_menu():
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("TRUNCATE TABLE products RESTART IDENTITY CASCADE")
        conn.commit(); conn.close()
        return redirect('/admin')
    except Exception as e:
        return f"清空失敗: {e}"

@app.route('/admin/reset_orders')
def reset_orders():
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("TRUNCATE TABLE orders RESTART IDENTITY CASCADE")
        conn.commit(); conn.close()
        return redirect('/admin')
    except Exception as e:
        return f"清空失敗: {e}"

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    conn = get_db_connection(); cur = conn.cursor()
    if request.method == 'POST':
        try:
            cur.execute("""
                INSERT INTO products (name, price, category, image_url, custom_options, 
                name_en, name_jp, name_kr,
                custom_options_en, custom_options_jp, custom_options_kr,
                print_category, category_en, category_jp, category_kr, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 9999)
            """, (
                request.form.get('name'), request.form.get('price'), request.form.get('category'), 
                request.form.get('image_url'), request.form.get('custom_options'),
                request.form.get('name_en'), request.form.get('name_jp'), request.form.get('name_kr'),
                request.form.get('custom_options_en'), request.form.get('custom_options_jp'), request.form.get('custom_options_kr'),
                request.form.get('print_category', 'Noodle'),
                request.form.get('category_en'), request.form.get('category_jp'), request.form.get('category_kr')
            ))
            conn.commit()
            return redirect('/admin')
        except Exception as e:
            return f"Error: {e}"
        finally:
            cur.close(); conn.close()

    cur.execute("""
        SELECT id, name, price, category, image_url, is_available, custom_options, sort_order, 
               name_en, name_jp, name_kr, custom_options_en, custom_options_jp, custom_options_kr, 
               print_category, category_en, category_jp, category_kr
        FROM products 
        ORDER BY sort_order ASC, id DESC
    """)
    prods = cur.fetchall()
    conn.close()

    rows = ""
    for p in prods:
        row_style = "" if p[5] else "background-color: #f0f0f0; opacity: 0.7;"
        status_text = "<span style='color:green'>上架</span>" if p[5] else "<span style='color:red'>下架</span>"
        toggle_link = f"<a href='/admin/toggle_product/{p[0]}' class='button button-clear' style='display:inline;padding:0;height:auto;line-height:normal;font-size:12px;'>[切換]</a>"
        p_cat = p[14] if len(p)>14 and p[14] else 'Noodle'
        cat_display = f"{p[3]} <br><small style='color:#666'>(EN:{p[15] or '-'} JP:{p[16] or '-'})</small>"

        rows += f"""
        <tr data-id="{p[0]}" class="draggable-item" style="{row_style}">
            <td style="cursor:move;font-size:1.5em;color:#888;width:50px;text-align:center;" class="handle">☰</td>
            <td>{p[0]}</td>
            <td><b>{p[1]}</b><br><small style="color:#888">{cat_display}</small></td>
            <td>{p[2]}</td>
            <td>{p_cat}</td>
            <td>{status_text} <br> {toggle_link}</td>
            <td>
                <a href='/admin/edit_product/{p[0]}'>編輯</a> | 
                <a href='/admin/delete_product/{p[0]}' onclick='return confirm(\"確定刪除？\")' style='color:red;'>刪除</a>
            </td>
        </tr>"""

    return f"""
    <!DOCTYPE html><html><head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>餐廳後台管理</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/milligram/1.4.1/milligram.min.css">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.14.0/Sortable.min.js"></script>
        <style>
            .draggable-item {{ background: white; transition: background 0.3s; }}
            .sortable-ghost {{ background: #e3f2fd; opacity: 0.5; }}
            .handle {{ touch-action: none; }} 
            h5 {{ margin-bottom: 5px; color: #9b4dca; border-left: 4px solid #9b4dca; padding-left: 10px; }}
            .button-clear {{ text-decoration: underline; }}
            .tool-bar {{ background: #fff; padding: 15px; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 20px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
        </style>
    </head>
    <body style="padding:20px;">
    
    <div style="background:#f4f7f6; padding:20px; border-radius:8px; margin-bottom:30px; border:1px solid #ddd;">
        <h4 style="margin-top:0;">➕ 新增產品</h4>
        <form method="POST">
            <h5>1. 基本資料 & 分類翻譯</h5>
            <div class="row">
                <div class="column"><label>名稱 (中文)</label><input type="text" name="name" required></div>
                <div class="column"><label>價格</label><input type="number" name="price" required></div>
                <div class="column">
                    <label>出單區域</label>
                    <select name="print_category">
                        <option value="Noodle">麵區 (Noodle)</option>
                        <option value="Soup">湯區 (Soup)</option>
                    </select>
                </div>
            </div>
            <div class="row">
                <div class="column"><label>分類 (中文)</label><input type="text" name="category" required></div>
                <div class="column"><label>分類 (EN)</label><input type="text" name="category_en"></div>
                <div class="column"><label>分類 (JP)</label><input type="text" name="category_jp"></div>
                <div class="column"><label>分類 (KR)</label><input type="text" name="category_kr"></div>
            </div>
            <h5>2. 品名翻譯</h5>
            <div class="row">
                <div class="column"><label>English</label><input type="text" name="name_en"></div>
                <div class="column"><label>日本語</label><input type="text" name="name_jp"></div>
                <div class="column"><label>韓國語</label><input type="text" name="name_kr"></div>
            </div>
            <h5>3. 客製選項</h5>
            <div class="row">
                <div class="column"><label>中文選項</label><input type="text" name="custom_options"></div>
                <div class="column"><label>English</label><input type="text" name="custom_options_en"></div>
            </div>
            <div class="row">
                <div class="column"><label>日本語</label><input type="text" name="custom_options_jp"></div>
                <div class="column"><label>韓國語</label><input type="text" name="custom_options_kr"></div>
            </div>
            <label>圖片 URL</label><input type="text" name="image_url">
            <button type="submit" style="width:100%;">🚀 新增產品</button>
        </form>
    </div>

    <div class="tool-bar">
        <a href="/admin/export_menu" class="button button-outline">📤 匯出菜單 (Excel)</a>
        
        <form action="/admin/import_menu" method="POST" enctype="multipart/form-data" style="margin:0; display:flex; gap:5px; border-left: 2px solid #eee; padding-left: 15px;">
            <input type="file" name="menu_file" accept=".xlsx, .xls" required style="margin:0; width:220px; font-size:12px;">
            <button type="submit" class="button button-outline">📥 匯入菜單 (Excel)</button>
        </form>
        
        <div style="flex-grow: 1; text-align: right;">
            <a href="/admin/reset_menu" onclick="return confirm('危險！這將刪除所有菜單且無法復原。確定？')" class="button" style="background:#e91e63; border-color:#e91e63;">🗑️ 一鍵刪除所有菜單</a>
        </div>
    </div>

    <div style="position:sticky; top:0; background:white; z-index:100; padding:10px 0; border-bottom:1px solid #eee;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <h3>📦 產品列表 (可拖曳排序)</h3>
            <div>
                 <button id="save-btn" onclick="saveOrder()" class="button" style="background:#9c27b0;border-color:#9c27b0;display:none;">💾 儲存排序</button>
                 <a href="/admin/reset_orders" onclick="return confirm('確定清空所有訂單記錄嗎？')" class="button button-clear" style="color:red;">⚠️ 清空訂單記錄</a>
            </div>
        </div>
    </div>

    <table>
        <thead><tr><th>序</th><th>ID</th><th>品名/分類</th><th>價</th><th>出單區</th><th>狀態</th><th>操作</th></tr></thead>
        <tbody id="menu-list">{rows}</tbody>
    </table>

    <script>
        var sortable = Sortable.create(document.getElementById('menu-list'), {{
            handle: '.handle', animation: 150,
            onEnd: function () {{ document.getElementById('save-btn').style.display = 'inline-block'; }}
        }});

        function saveOrder() {{
            var order = Array.from(document.querySelectorAll('#menu-list tr')).map(row => row.getAttribute('data-id'));
            fetch('/admin/reorder_products', {{
                method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ order: order }})
            }}).then(r => r.json()).then(data => {{
                if(data.status === 'success') {{
                    alert('排序已儲存！');
                    location.reload();
                }}
            }});
        }}
    </script>
    </body></html>
    """

# --- 編輯產品頁面 (維持原樣) ---
@app.route('/admin/edit_product/<int:pid>', methods=['GET','POST'])
def edit_product(pid):
    conn = get_db_connection(); cur = conn.cursor()
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
            return redirect('/admin')
        except Exception as e:
            return f"Update Error: {e}"
        finally:
            conn.close()

    cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
    p = cur.fetchone()
    conn.close()
    
    def v(val): return val if val else "" 

    return f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/milligram/1.4.1/milligram.min.css"></head>
    <body style="padding:20px;">
        <h3>編輯產品 #{p[0]}</h3>
        <form method="POST">
            <h5>1. 基本資料 & 排序</h5>
            <div class="row">
                <div class="column"><label>名稱 (中文)</label><input type="text" name="name" value="{v(p[1])}"></div>
                <div class="column"><label>價格</label><input type="number" name="price" value="{p[2]}"></div>
                <div class="column"><label>排序</label><input type="number" name="sort_order" value="{p[7]}"></div>
            </div>
            <h5>2. 分類與區域</h5>
            <div class="row">
                <div class="column"><label>分類 (中文)</label><input type="text" name="category" value="{v(p[3])}"></div>
                <div class="column"><label>分類 (EN)</label><input type="text" name="category_en" value="{v(p[15])}"></div>
                <div class="column"><label>分類 (JP)</label><input type="text" name="category_jp" value="{v(p[16])}"></div>
                <div class="column"><label>分類 (KR)</label><input type="text" name="category_kr" value="{v(p[17])}"></div>
            </div>
            <div class="row">
                <div class="column"><label>出單區域</label>
                    <select name="print_category">
                        <option value="Noodle" {'selected' if p[14]=='Noodle' else ''}>麵區</option>
                        <option value="Soup" {'selected' if p[14]=='Soup' else ''}>湯區</option>
                    </select>
                </div>
                <div class="column"><label>圖片 URL</label><input type="text" name="image_url" value="{v(p[4])}"></div>
            </div>
            <hr>
            <h5>🌐 品名多國語言</h5>
            <div class="row">
                <div class="column"><label>English</label><input type="text" name="name_en" value="{v(p[8])}"></div>
                <div class="column"><label>日本語</label><input type="text" name="name_jp" value="{v(p[9])}"></div>
                <div class="column"><label>韓國語</label><input type="text" name="name_kr" value="{v(p[10])}"></div>
            </div>
            <hr>
            <h5>🛠️ 客製化選項翻譯</h5>
            <label>中文選項</label><input type="text" name="custom_options" value="{v(p[6])}">
            <div class="row">
                <div class="column"><label>English</label><input type="text" name="custom_options_en" value="{v(p[11])}"></div>
                <div class="column"><label>日本語</label><input type="text" name="custom_options_jp" value="{v(p[12])}"></div>
                <div class="column"><label>韓國語</label><input type="text" name="custom_options_kr" value="{v(p[13])}"></div>
            </div>
            <div style="margin-top:20px;">
                <button type="submit">💾 儲存</button>
                <a href="/admin" class="button button-outline">取消</a>
            </div>
        </form>
    </body></html>"""
    
# --- 防休眠 ---
def keep_alive():
    while True:
        try: urllib.request.urlopen("https://ding-dong-tipi.onrender.com")
        except: pass
        time.sleep(800)
threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
