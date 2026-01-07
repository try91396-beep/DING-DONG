import os
import psycopg2
import json
import threading
import urllib.request
import time  
import io  # 處理檔案串流
import pandas as pd  # 處理 Excel 資料 
from flask import Flask, request, redirect, url_for, jsonify, send_file
from datetime import datetime, date, timedelta

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
            "print_receipt_opt": "列印收據", "daily_seq_prefix": "單號", "ai_note": "翻譯由 AI 提供", "table": "桌號"
        },
        "en": {
            "title": "Order", "welcome": "Welcome", "table_placeholder": "Table No.",
            "table_label": "Table", "add": "Add", "sold_out": "Sold Out", "cart_detail": "Cart",
            "total": "Total", "checkout": "Checkout", "cart_title": "Cart", "empty_cart": "Empty",
            "close": "Close", "confirm_delete": "Remove?", "confirm_order": "Submit?",
            "modal_unit_price": "Price", "modal_add_cart": "Add to Cart", "modal_cancel": "Cancel",
            "custom_options": "Options", "order_success": "Success!", "kitchen_prep": "Preparing...",
            "pay_at_counter": "Please pay at counter", "order_details": "Order Details",
            "print_receipt_opt": "Print Receipt", "daily_seq_prefix": "No.", "ai_note": "Translated by AI", "table": "Table"
        },
        "jp": {
            "title": "注文", "welcome": "ようこそ", "table_placeholder": "卓番",
            "table_label": "卓番", "add": "追加", "sold_out": "完売", "cart_detail": "カート",
            "total": "合計", "checkout": "会計", "cart_title": "詳細", "empty_cart": "空です",
            "close": "閉じる", "confirm_delete": "削除？", "confirm_order": "送信？",
            "modal_unit_price": "単価", "modal_add_cart": "カートへ", "modal_cancel": "キャンセル",
            "custom_options": "オプション", "order_success": "送信完了", "kitchen_prep": "調理中...",
            "pay_at_counter": "レジでお会計ください", "order_details": "注文詳細",
            "print_receipt_opt": "レシート印刷", "daily_seq_prefix": "番号", "ai_note": "AIによる翻訳", "table": "卓番"
        },
        "kr": {
            "title": "주문", "welcome": "환영합니다", "table_placeholder": "테이블 번호",
            "table_label": "테이블", "add": "추가", "sold_out": "매진", "cart_detail": "장바구니",
            "total": "합계", "checkout": "결제하기", "cart_title": "상세 내역", "empty_cart": "비어 있음",
            "close": "닫기", "confirm_delete": "삭제하시겠습니까?", "confirm_order": "주문하시겠습니까?",
            "modal_unit_price": "단가", "modal_add_cart": "장바구니 담기", "modal_cancel": "취소",
            "custom_options": "옵션", "order_success": "주문 성공!", "kitchen_prep": "준비 중...",
            "pay_at_counter": "카운터에서 결제해주세요", "order_details": "주문 내역",
            "print_receipt_opt": "영수증 출력", "daily_seq_prefix": "번호", "ai_note": "AI 번역", "table": "테이블"
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
                print_category VARCHAR(20) DEFAULT 'Noodle'
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
        # 補欄位檢查
        alters = [
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_available BOOLEAN DEFAULT TRUE;",
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


# --- 2. 首頁與語言選擇 ---
@app.route('/')
def language_select():
    # 1. 嘗試從 QR Code 的網址中抓取 table 參數
    tbl = request.args.get('table', '')
    
    # 2. 如果有桌號，就把它加到連結參數中 (例如 &table=1)
    # 這樣點擊中文時，網址就會變成 /menu?lang=zh&table=1
    qs_table = f"&table={tbl}" if tbl else ""

    return f"""
    <!DOCTYPE html>
    <html><head><title>Select Language</title><meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body{{font-family:sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;margin:0;background:#f4f7f6;}}
        h2{{color:#333;margin-bottom:30px;}}
        .btn{{width:200px;padding:15px;margin:10px;text-align:center;text-decoration:none;font-size:1.2em;border-radius:50px;color:white;box-shadow:0 4px 6px rgba(0,0,0,0.1);transition:transform 0.1s;}}
        .btn:active{{transform:scale(0.98);}}
        .zh{{background:#e91e63;}} .en{{background:#007bff;}} .jp{{background:#ff9800;}} .kr{{background:#20c997;}}
    </style></head>
    <body>
        <h2>Select Language / 請選擇語言</h2>
        <a href="/menu?lang=zh{qs_table}" class="btn zh">中文</a>
        <a href="/menu?lang=en{qs_table}" class="btn en">English</a>
        <a href="/menu?lang=jp{qs_table}" class="btn jp">日本語</a>
        <a href="/menu?lang=kr{qs_table}" class="btn kr">한국어</a>
    </body></html>
    """

# --- 3. 點餐頁面 (完整版：支援完售商品黑白顯示) ---
@app.route('/menu', methods=['GET', 'POST'])
def menu():
    lang = request.args.get('lang', 'zh')
    t = load_translations().get(lang, load_translations()['zh'])
    conn = get_db_connection()
    cur = conn.cursor()

    # --- 處理訂單送出 (POST) ---
    if request.method == 'POST':
        try:
            table_number = request.form.get('table_number')
            cart_json = request.form.get('cart_data')
            need_receipt = request.form.get('need_receipt') == 'on'
            lang_post = request.form.get('lang_input', 'zh')
            old_order_id = request.form.get('old_order_id')
            
            if not cart_json or cart_json == '[]': return "Empty Cart"
            
            cart_items = json.loads(cart_json)
            total_price = 0
            display_list = []
            
            for item in cart_items:
                price = int(float(item['unit_price']))
                qty = int(float(item['qty']))
                total_price += (price * qty)
                opts = item.get('options', [])
                opt_str = f"({','.join(opts)})" if opts else ""
                display_list.append(f"{item['name']} {opt_str} x{qty}")

            items_str = " + ".join(display_list)
            
            cur.execute("SELECT COUNT(*) FROM orders WHERE created_at >= CURRENT_DATE")
            new_seq = cur.fetchone()[0] + 1
            
            cur.execute("""
                INSERT INTO orders (table_number, items, total_price, lang, daily_seq, content_json, need_receipt)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (table_number, items_str, total_price, lang_post, new_seq, cart_json, need_receipt))
            
            oid = cur.fetchone()[0]
            
            if old_order_id:
                cur.execute("UPDATE orders SET status='Cancelled' WHERE id=%s", (old_order_id,))
                conn.commit()
                return "<script>window.close();</script>"
            
            conn.commit()
            return redirect(url_for('order_success', order_id=oid, lang=lang_post))
            
        except Exception as e:
            conn.rollback()
            return f"Order Failed: {e}"
        finally:
            cur.close(); conn.close()

    # --- 顯示菜單 (GET) ---
    url_table = request.args.get('table', '')
    edit_oid = request.args.get('edit_oid')
    preload_cart = "[]"
    
    if edit_oid:
        cur.execute("SELECT table_number, content_json FROM orders WHERE id=%s", (edit_oid,))
        old_data = cur.fetchone()
        if old_data:
            if not url_table: url_table = old_data[0]
            preload_cart = old_data[1]

    # [關鍵修改] 讀取所有產品，不使用 WHERE is_available=TRUE，改用 sort_order 排序
    cur.execute("""
        SELECT id, name, price, category, image_url, is_available, custom_options, sort_order,
               name_en, name_jp, name_kr, custom_options_en, custom_options_jp, custom_options_kr, print_category
        FROM products ORDER BY sort_order ASC, id ASC
    """)
    products = cur.fetchall()
    cur.close(); conn.close()
    
    p_list = []
    for p in products:
        name_zh = p[1]
        opts_zh = p[6].split(',') if p[6] else []
        d_name = p[1]
        d_opts_str = p[6]

        if lang == 'en':
            if p[8]: d_name = p[8]
            if p[11]: d_opts_str = p[11]
        elif lang == 'jp':
            if p[9]: d_name = p[9]
            if p[12]: d_opts_str = p[12]
        elif lang == 'kr':
            if p[10]: d_name = p[10]
            if p[13]: d_opts_str = p[13]

        d_opts = d_opts_str.split(',') if d_opts_str else []
        print_cat = p[14] if p[14] else 'Noodle'

        p_list.append({
            'id': p[0], 
            'name': d_name, 'name_zh': name_zh,        
            'price': p[2], 'category': p[3],
            'image_url': p[4] if p[4] else '', 
            'is_available': p[5], # 傳遞完售狀態
            'custom_options': d_opts, 'custom_options_zh': opts_zh,
            'print_category': print_cat
        })

    return render_frontend(p_list, t, url_table, lang, preload_cart, edit_oid)

def render_frontend(products, t, default_table, lang, preload_cart, edit_oid):
    p_json = json.dumps(products)
    t_json = json.dumps(t)
    old_oid_input = f'<input type="hidden" name="old_order_id" value="{edit_oid}">' if edit_oid else ''
    edit_notice = f'<div style="background:#fff3cd;padding:10px;color:#856404;text-align:center;">⚠️ 正在編輯 #{edit_oid}</div>' if edit_oid else ''
    ai_badge = f"<div style='text-align:center;color:#999;font-size:0.8em;padding:10px;'>🤖 {t.get('ai_note', 'Translated by AI')}</div>"

    return f"""
    <!DOCTYPE html>
    <html><head><title>{t['title']}</title><meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=0">
    <style>
        body{{font-family:'Microsoft JhengHei',sans-serif;margin:0;padding-bottom:100px;background:#f8f9fa;}}
        .header{{background:white;padding:15px;position:sticky;top:0;z-index:99;box-shadow:0 2px 5px rgba(0,0,0,0.1);}}
        .menu-item{{background:white;margin:10px;padding:10px;border-radius:10px;display:flex;box-shadow:0 2px 4px rgba(0,0,0,0.05);position:relative;}}
        .menu-img{{width:80px;height:80px;border-radius:8px;object-fit:cover;background:#eee;}}
        .menu-info{{flex:1;padding-left:15px;display:flex;flex-direction:column;justify-content:space-between;}}
        .add-btn{{background:#28a745;color:white;border:none;padding:5px 15px;border-radius:15px;align-self:flex-end;}}
        
        /* 完售黑白效果 */
        .sold-out {{ filter: grayscale(1); opacity: 0.6; pointer-events: none; }}
        .sold-out-badge {{ position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.7); color: white; padding: 2px 8px; border-radius: 5px; font-size: 0.8em; font-weight: bold; z-index: 5; }}

        .cart-bar{{position:fixed;bottom:0;width:100%;background:white;padding:15px;box-shadow:0 -2px 10px rgba(0,0,0,0.1);display:none;justify-content:space-between;align-items:center;box-sizing:border-box;z-index:100;}}
        .modal{{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);display:none;z-index:200;justify-content:center;align-items:flex-end;}}
        .modal-c{{background:white;width:100%;padding:20px;border-radius:20px 20px 0 0;max-height:80vh;overflow-y:auto;}}
        .opt-tag{{border:1px solid #ddd;padding:5px 10px;border-radius:15px;margin:3px;display:inline-block;cursor:pointer;}}
        .opt-tag.sel{{background:#e3f2fd;border-color:#2196f3;color:#2196f3;}}
        .cat-header {{padding:10px 15px;font-weight:bold;color:#444;background:#eee;margin-top:10px;}}
    </style></head><body>
    <div class="header">
        {edit_notice}
        <h3>{t['welcome']}</h3>
        <input type="text" id="visible_table" value="{default_table}" placeholder="{t['table_placeholder']}" 
               style="padding:10px;width:100%;box-sizing:border-box;border:1px solid #ddd;border-radius:5px;font-size:1.1em;">
    </div>
    
    <div id="list"></div>
    {ai_badge}
    
    <form id="order-form" method="POST" action="/menu">
        <input type="hidden" name="cart_data" id="cart_input">
        <input type="hidden" name="table_number" id="tbl_input">
        <input type="hidden" name="lang_input" value="{lang}">
        {old_oid_input}
        
        <div class="cart-bar" id="bar">
            <div onclick="showCart()" style="flex-grow:1;">Total: $<span id="tot">0</span> (<span id="cnt">0</span>)</div>
            <label style="margin-right:10px;"><input type="checkbox" name="need_receipt" checked> {t['print_receipt_opt']}</label>
            <button type="button" onclick="sub()" style="background:#28a745;color:white;border:none;padding:10px 20px;border-radius:20px;">{t['checkout']}</button>
        </div>
    </form>
    
    <div class="modal" id="opt-m"><div class="modal-c">
        <h3 id="m-name"></h3>
        <div id="m-opts"></div>
        <div style="margin-top:20px;text-align:center;">
            <button onclick="cq(-1)">-</button> <span id="m-q" style="margin:0 15px;font-weight:bold;">1</span> <button onclick="cq(1)">+</button>
        </div>
        <button onclick="addC()" style="width:100%;background:#28a745;color:white;padding:12px;border:none;border-radius:10px;margin-top:20px;">{t['modal_add_cart']}</button>
        <button onclick="document.getElementById('opt-m').style.display='none'" style="width:100%;background:white;padding:10px;border:none;margin-top:10px;">{t['modal_cancel']}</button>
    </div></div>

    <div class="modal" id="cart-m"><div class="modal-c">
        <h3>{t['cart_title']}</h3><div id="c-list"></div>
        <button onclick="document.getElementById('cart-m').style.display='none'" style="width:100%;padding:10px;margin-top:10px;">{t['close']}</button>
    </div></div>

    <script>
    const P={p_json}, T={t_json}, PRELOAD={preload_cart};
    let C=[], cur=null, q=1, selectedOptIndices=[], addP=0;

    if(PRELOAD && PRELOAD.length > 0){{ C = PRELOAD; setTimeout(upd, 100); }}
    
    let h="", cat="";
    P.forEach(p=>{{
        if(p.category!=cat) {{ h+=`<div class="cat-header">${{p.category}}</div>`; cat=p.category; }}
        
        let isAvail = p.is_available;
        let img = p.image_url ? `<img src="${{p.image_url}}" class="menu-img">` : '';
        let badge = isAvail ? '' : `<div class="sold-out-badge">${{T.sold_out}}</div>`;
        
        h+=`<div class="menu-item ${{isAvail ? '' : 'sold-out'}}">
            ${{badge}} ${{img}}
            <div class="menu-info">
                <div><b>${{p.name}}</b><div style="color:#e91e63">$${{p.price}}</div></div>
                <button class="add-btn" onclick="openOpt(${{p.id}})" ${{isAvail ? '' : 'disabled'}}>${{isAvail ? T.add : T.sold_out}}</button>
            </div>
        </div>`;
    }});
    document.getElementById('list').innerHTML=h;

    function openOpt(id){{
        cur=P.find(x=>x.id==id); q=1; selectedOptIndices=[]; addP=0;
        document.getElementById('m-name').innerText=cur.name;
        let area=document.getElementById('m-opts'); area.innerHTML="";
        cur.custom_options.forEach((o, index)=>{{
            let parts = o.split(/[:：+]/);
            let n = parts[0].trim(), p = parts.length>1 ? parseInt(parts[parts.length-1]) : 0;
            let d = document.createElement('div'); d.className='opt-tag';
            d.innerText = n + (p?` (+$${{p}})`:'');
            d.onclick=()=>{{
                if(selectedOptIndices.includes(index)){{ selectedOptIndices = selectedOptIndices.filter(i=>i!=index); addP-=p; d.classList.remove('sel'); }}
                else{{ selectedOptIndices.push(index); addP+=p; d.classList.add('sel'); }}
            }};
            area.appendChild(d);
        }});
        document.getElementById('m-q').innerText=1;
        document.getElementById('opt-m').style.display='flex';
    }}
    function cq(n){{ if(q+n>0) {{q+=n; document.getElementById('m-q').innerText=q;}} }}
    function addC(){{
        let finalOpts = selectedOptIndices.map(idx => cur.custom_options[idx]);
        let finalOptsZH = selectedOptIndices.map(idx => cur.custom_options_zh[idx] || cur.custom_options[idx]);
        C.push({{ id: cur.id, name: cur.name, name_zh: cur.name_zh, unit_price: cur.price + addP, qty: q, options: finalOpts, options_zh: finalOptsZH, category: cur.category, print_category: cur.print_category }});
        document.getElementById('opt-m').style.display='none'; upd();
    }}
    function upd(){{
        if(C.length){{
            document.getElementById('bar').style.display='flex';
            document.getElementById('tot').innerText = C.reduce((a,b)=>a+b.unit_price*b.qty,0);
            document.getElementById('cnt').innerText = C.reduce((a,b)=>a+b.qty,0);
        }} else document.getElementById('bar').style.display='none';
    }}
    function showCart(){{
        let h="";
        C.forEach((i,x)=>{{
            h+=`<div style="border-bottom:1px solid #eee;padding:10px;display:flex;justify-content:space-between;">
                <div><b>${{i.name}}</b> x${{i.qty}}<br><small>${{i.options.join(',')}}</small></div>
                <button onclick="C.splice(${{x}},1);upd();showCart()" style="color:red;border:none;background:none;">🗑️</button>
            </div>`;
        }});
        document.getElementById('c-list').innerHTML=h;
        document.getElementById('cart-m').style.display='flex';
    }}
    function sub(){{
        let t = document.getElementById('visible_table').value;
        if(!t) return alert(T.table_placeholder);
        document.getElementById('tbl_input').value=t;
        document.getElementById('cart_input').value=JSON.stringify(C);
        if(confirm(T.confirm_order)) document.getElementById('order-form').submit();
    }}
    </script></body></html>
    """

# --- 4. 下單成功 (台灣時間版) ---
@app.route('/order_success')
def order_success():
    oid = request.args.get('order_id')
    lang = request.args.get('lang', 'zh')
    t = load_translations().get(lang, load_translations()['zh'])
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT daily_seq, content_json, total_price, created_at FROM orders WHERE id=%s", (oid,))
    row = cur.fetchone()
    conn.close()

    if not row: return "Order Not Found"
    seq, json_str, total, created_at = row
    
    # 轉換台灣時間 (UTC+8)
    tw_time = created_at + timedelta(hours=8)
    time_str = tw_time.strftime('%Y-%m-%d %H:%M:%S')

    items = json.loads(json_str) if json_str else []
    items_html = ""
    for i in items:
        # 顯示對應語言名稱
        display_name = i.get(f'name_{lang}', i.get('name'))
        opt = f" <small>({','.join(i['options'])})</small>" if i['options'] else ""
        items_html += f"<div style='display:flex;justify-content:space-between;border-bottom:1px dashed #ddd;padding:5px;'><span>{display_name} x{i['qty']}{opt}</span><span>${i['unit_price']*i['qty']}</span></div>"

    return f"""
    <div style="max-width:400px;margin:20px auto;text-align:center;font-family:sans-serif;padding:20px;border:1px solid #ddd;border-radius:10px;">
        <h1 style="color:#28a745;">✅ {t['order_success']}</h1>
        <div style="font-size:3em;font-weight:bold;color:#e91e63;margin:10px;">#{seq:03d}</div>
        <p style="color:#666;">{time_str}</p>
        <p>{t['kitchen_prep']}</p>
        <h2 style="background:#eee;padding:10px;">{t['pay_at_counter']}</h2>
        <div style="text-align:left;margin-top:20px;">
            <h3>🧾 {t['order_details']}</h3>
            {items_html}
            <div style="text-align:right;font-weight:bold;font-size:1.2em;margin-top:10px;">{t['total']}: ${total}</div>
        </div>
        <br>
        <a href="/" style="display:block;padding:10px;background:#007bff;color:white;text-decoration:none;border-radius:5px;">Back to Home</a>
    </div>
    """

# --- 5. 廚房看板 - 修正語音、自動列印與語言顯示 ---
@app.route('/kitchen')
def kitchen_panel():
    return """
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <title>👨‍🍳 廚房出單看板</title>
        <style>
            body { background: #1a1a1a; color: #eee; font-family: "Microsoft JhengHei", sans-serif; margin: 0; }
            .header-container { display: flex; justify-content: space-between; align-items: center; padding: 15px 25px; background: #222; border-bottom: 3px solid #ff9800; }
            h1 { color: #ff9800; margin: 0; }
            .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 20px; padding: 25px; }
            .card { background: #2d2d2d; border-radius: 12px; padding: 20px; border-top: 10px solid #ff9800; position: relative; }
            .items { background: #383838; padding: 15px; border-radius: 8px; margin: 15px 0; font-size: 1.2em; line-height: 1.5; }
            .btn { padding: 10px 15px; border-radius: 6px; text-decoration: none; color: white; font-weight: bold; cursor: pointer; border: none; }
            .btn-complete { background: #28a745; } .btn-print { background: #17a2b8; } .btn-edit { background: #ff9800; }
            #audio-banner { background: #d32f2f; color: white; text-align: center; padding: 12px; font-weight: bold; cursor: pointer; }
        </style>
    </head>
    <body>
        <div id="audio-banner" onclick="enableAudio()">🔔 點擊此處：啟動新訂單「自動列印」與「語音提醒」功能</div>
        <div class="header-container">
            <h1>👨‍🍳 廚房出單看板</h1>
            <a href="/kitchen/report" class="btn" style="background:#6f42c1;">📊 營收報表</a>
        </div>
        <div id="order-grid" class="grid">正在連線中...</div>

        <audio id="notice-sound" preload="auto">
            <source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg">
        </audio>

        <script>
            let lastMaxSeq = 0;
            let isFirstLoad = true;
            let systemReady = false;

            function enableAudio() {
                systemReady = true;
                document.getElementById('audio-banner').style.display = 'none';
                const audio = document.getElementById('notice-sound');
                audio.play(); audio.pause(); // 激活瀏覽器權限
                console.log("系統已就緒，等待新訂單...");
            }

            function refreshOrders() {
                fetch('/check_new_orders?current_seq=' + lastMaxSeq)
                .then(res => res.json())
                .then(data => {
                    if (data.html) document.getElementById('order-grid').innerHTML = data.html;

                    // 偵測到新訂單
                    if (!isFirstLoad && data.new_ids && data.new_ids.length > 0) {
                        if (systemReady) {
                            // 1. 播放音效 (只播一次)
                            const audio = document.getElementById('notice-sound');
                            audio.currentTime = 0;
                            audio.play().catch(e => console.log("音效受阻"));

                            // 2. 自動列印新單 (彈出所有新單視窗)
                            data.new_ids.forEach(oid => {
                                window.open('/print_order/' + oid, '_blank', 'width=300,height=600');
                            });
                        }
                    }
                    lastMaxSeq = data.max_seq;
                    isFirstLoad = false;
                })
                .catch(err => console.error("同步失敗:", err));
            }

            setInterval(refreshOrders, 5000); 
            refreshOrders();
        </script>
    </body>
    </html>
    """

# --- 6. 多語系列印路由 - 確保語言抓取正確 ---
@app.route('/print_order/<int:oid>')
def print_order(oid):
    conn = get_db_connection(); cur = conn.cursor()
    # 這裡必須抓取當初存入的 lang
    cur.execute("SELECT table_number, content_json, total_price, created_at, daily_seq, lang FROM orders WHERE id=%s", (oid,))
    row = cur.fetchone()
    conn.close()
    
    if not row: return "訂單不存在"
    table, c_json, total, created, seq, order_lang = row
    
    # 讀取翻譯檔案
    translations = load_translations()
    t = translations.get(order_lang, translations['zh'])
    
    # 台灣時間
    tw_time = created + timedelta(hours=8)
    time_str = tw_time.strftime('%H:%M:%S')

    items = json.loads(c_json) if c_json else []
    items_html = ""
    for i in items:
        # 重點：根據 order_lang 抓取正確的翻譯欄位
        # 如果是 en -> name, 如果是 jp -> name_jp, 如果是 kr -> name_kr
        name_key = 'name' if order_lang == 'en' else f'name_{order_lang}'
        if order_lang == 'zh': name_key = 'name_zh'
        
        display_name = i.get(name_key, i.get('name_zh', i.get('name')))
        
        # 顯示中文備註
        zh_ref = f"<br><small>(中: {i.get('name_zh')})</small>" if order_lang != 'zh' else ""
        
        # 選項處理
        opt_key = 'options' if order_lang == 'en' else f'options_{order_lang}'
        if order_lang == 'zh': opt_key = 'options_zh'
        ops = i.get(opt_key, i.get('options_zh', []))
        opt_str = f"<br><small>└ {', '.join(ops)}</small>" if ops else ""
        
        items_html += f"""
        <tr style="border-bottom: 1px dashed #ccc;">
            <td style="padding:8px 0;">
                <strong style="font-size:1.1em;">{display_name}</strong>
                {zh_ref}{opt_str}
            </td>
            <td style="text-align:right;">x{i['qty']}</td>
            <td style="text-align:right;">${i['unit_price']*i['qty']}</td>
        </tr>"""

    return f"""
    <html>
    <head><meta charset="UTF-8"></head>
    <body onload="window.print(); setTimeout(window.close, 1000);" style="width:58mm; font-family:sans-serif; margin:0; padding:5px;">
        <div style="text-align:center; border-bottom:2px solid #000; padding-bottom:5px;">
            <h1 style="margin:5px 0; font-size:2em;">#{seq:03d}</h1>
            <div style="font-size:1.2em;">{t['table']}: {table}</div>
        </div>
        <div style="font-size:11px; margin:5px 0;">Time: {time_str}</div>
        <table style="width:100%; border-collapse:collapse; font-size:14px;">
            {items_html}
        </table>
        <div style="text-align:right; font-weight:bold; font-size:1.2em; border-top:2px solid #000; margin-top:10px; padding-top:5px;">
            {t['total']}: ${total}
        </div>
    </body>
    </html>
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



# --- 9. 後台管理 (完整修正版：支援全語系新增與編輯) ---

# [API] 接收前端拖拉後的 ID 順序
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

# [頁面] 後台主控台
@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    conn = get_db_connection(); cur = conn.cursor()
    
    # --- [POST] 手動新增產品 (修正：加入日韓文欄位) ---
    if request.method == 'POST':
        try:
            cur.execute("""
                INSERT INTO products (name, price, category, image_url, custom_options, 
                name_en, name_jp, name_kr,
                custom_options_en, custom_options_jp, custom_options_kr,
                print_category, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 9999)
            """, (
                request.form.get('name'), request.form.get('price'), request.form.get('category'), 
                request.form.get('image_url'), request.form.get('custom_options'),
                request.form.get('name_en'), request.form.get('name_jp'), request.form.get('name_kr'),
                request.form.get('custom_options_en'), request.form.get('custom_options_jp'), request.form.get('custom_options_kr'),
                request.form.get('print_category', 'Noodle')
            ))
            conn.commit()
            return redirect('/admin')
        except Exception as e:
            return f"Error: {e}"
        finally:
            cur.close(); conn.close()

    # --- [GET] 讀取產品列表 ---
    cur.execute("""
        SELECT id, name, price, category, image_url, is_available, custom_options, sort_order, 
               name_en, name_jp, name_kr, custom_options_en, custom_options_jp, custom_options_kr, print_category 
        FROM products 
        ORDER BY sort_order ASC, id DESC
    """)
    prods = cur.fetchall()
    conn.close()
    
    rows = ""
    for p in prods:
        row_style = "" if p[5] else "background-color: #f0f0f0; opacity: 0.7;"
        status_text = "<span style='color:green'>上架</span>" if p[5] else "<span style='color:red'>下架</span>"
        toggle = f"<a href='/admin/toggle_product/{p[0]}'>切換</a>"
        p_cat = p[14] if len(p)>14 and p[14] else 'Noodle'
        
        rows += f"""
        <tr data-id="{p[0]}" class="draggable-item" style="{row_style}">
            <td style="cursor:move;font-size:1.5em;color:#888;width:50px;text-align:center;" class="handle">☰</td>
            <td>{p[0]}</td>
            <td><b>{p[1]}</b><br><small style="color:#888">{p[3]}</small></td>
            <td>{p[2]}</td>
            <td>{p_cat}</td>
            <td>{status_text} {toggle}</td>
            <td>
                <a href='/admin/edit_product/{p[0]}'>編輯</a> | 
                <a href='/admin/delete_product/{p[0]}' onclick='return confirm(\"確定刪除？\")'>刪除</a>
            </td>
        </tr>"""

    return f"""
    <!DOCTYPE html><html><head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/milligram/1.4.1/milligram.min.css">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.14.0/Sortable.min.js"></script>
        <style>
            .draggable-item {{ background: white; transition: background 0.3s; }}
            .sortable-ghost {{ background: #e3f2fd; opacity: 0.5; }}
            .handle {{ touch-action: none; }} 
            h5 {{ margin-bottom: 5px; color: #9b4dca; border-left: 4px solid #9b4dca; padding-left: 10px; }}
        </style>
    </head>
    <body style="padding:20px;">
    
    <div style="background:#f4f7f6; padding:20px; border-radius:8px; margin-bottom:30px; border:1px solid #ddd;">
        <h4 style="margin-top:0;">➕ 新增產品 / 批次管理</h4>
        <div style="margin-bottom:20px;padding-bottom:15px;border-bottom:1px dashed #ccc;">
            <form action="/admin/import_excel" method="post" enctype="multipart/form-data" style="margin:0;display:flex;align-items:center;">
                <label style="margin-right:10px;margin-bottom:0;">Excel 匯入:</label>
                <input type="file" name="file" accept=".xlsx" required style="margin-right:10px;margin-bottom:0;">
                <button type="submit" class="button button-small button-outline" style="margin-bottom:0;">上傳匯入</button>
            </form>
        </div>

        <form method="POST">
            <h5>1. 基本資料</h5>
            <div class="row">
                <div class="column"><label>名稱 (中文)</label><input type="text" name="name" required></div>
                <div class="column"><label>價格</label><input type="number" name="price" required></div>
                <div class="column"><label>分類</label><input type="text" name="category" required></div>
                <div class="column">
                    <label>出單區域</label>
                    <select name="print_category">
                        <option value="Noodle">麵區 (Noodle)</option>
                        <option value="Soup">湯區 (Soup)</option>
                    </select>
                </div>
            </div>
            
            <h5>2. 多國語言名稱</h5>
            <div class="row">
                <div class="column"><label>English</label><input type="text" name="name_en"></div>
                <div class="column"><label>日本語</label><input type="text" name="name_jp"></div>
                <div class="column"><label>한국어</label><input type="text" name="name_kr"></div>
            </div>

            <h5>3. 客製選項 (例: 加麵:+20,不要蔥:+0)</h5>
            <div class="row">
                <div class="column"><label>中文選項</label><input type="text" name="custom_options"></div>
                <div class="column"><label>English</label><input type="text" name="custom_options_en"></div>
            </div>
            <div class="row">
                <div class="column"><label>日本語</label><input type="text" name="custom_options_jp"></div>
                <div class="column"><label>한국어</label><input type="text" name="custom_options_kr"></div>
            </div>

            <label>圖片 URL</label><input type="text" name="image_url">
            <button type="submit" style="width:100%;">🚀 新增產品</button>
        </form>
    </div>

    <div style="position:sticky; top:0; background:white; z-index:100; padding:10px 0; border-bottom:1px solid #eee;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <h3>📦 產品列表</h3>
            <div>
                 <button id="save-btn" onclick="saveOrder()" class="button" style="background:#9c27b0;border-color:#9c27b0;display:none;">💾 儲存排序</button>
                 <a href="/admin/export_excel" class="button button-outline">📥 匯出 Excel</a>
                 <a href="/admin/reset_orders" onclick="return confirm('確定清空所有訂單？')" class="button button-clear" style="color:red;">⚠️ 清空訂單</a>
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
                if(data.status === 'success') location.reload();
            }});
        }}
    </script>
    </body></html>
    """

# --- 編輯產品頁面 (保持不變，已支援全語系) ---
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
                print_category=%s, sort_order=%s
                WHERE id=%s
            """, (
                request.form.get('name'), request.form.get('price'), request.form.get('category'),
                request.form.get('image_url'), request.form.get('custom_options'),
                request.form.get('name_en'), request.form.get('name_jp'), request.form.get('name_kr'),
                request.form.get('custom_options_en'), request.form.get('custom_options_jp'), request.form.get('custom_options_kr'),
                request.form.get('print_category'), request.form.get('sort_order'),
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
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/milligram/1.4.1/milligram.min.css"></head>
    <body style="padding:20px;">
        <h3>編輯產品 #{p[0]}</h3>
        <form method="POST">
            <div class="row">
                <div class="column"><label>名稱 (中文)</label><input type="text" name="name" value="{v(p[1])}"></div>
                <div class="column"><label>價格</label><input type="number" name="price" value="{p[2]}"></div>
                <div class="column"><label>排序</label><input type="number" name="sort_order" value="{p[7]}"></div>
            </div>
            <div class="row">
                <div class="column"><label>分類</label><input type="text" name="category" value="{v(p[3])}"></div>
                <div class="column"><label>出單區域</label>
                    <select name="print_category">
                        <option value="Noodle" {'selected' if p[14]=='Noodle' else ''}>麵區</option>
                        <option value="Soup" {'selected' if p[14]=='Soup' else ''}>湯區</option>
                    </select>
                </div>
            </div>
            <label>圖片 URL</label><input type="text" name="image_url" value="{v(p[4])}">
            <hr>
            <h5>🌐 多國語言名稱</h5>
            <div class="row">
                <div class="column"><label>English</label><input type="text" name="name_en" value="{v(p[8])}"></div>
                <div class="column"><label>日本語</label><input type="text" name="name_jp" value="{v(p[9])}"></div>
                <div class="column"><label>한국어</label><input type="text" name="name_kr" value="{v(p[10])}"></div>
            </div>
            <hr>
            <h5>🛠️ 客製化選項</h5>
            <label>中文選項</label><input type="text" name="custom_options" value="{v(p[6])}">
            <label>English Options</label><input type="text" name="custom_options_en" value="{v(p[11])}">
            <label>日本語オプション</label><input type="text" name="custom_options_jp" value="{v(p[12])}">
            <label>한국어 옵션</label><input type="text" name="custom_options_kr" value="{v(p[13])}">
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
