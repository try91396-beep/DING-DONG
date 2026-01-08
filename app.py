import os
import psycopg2
import json
import threading
import urllib.request
import time  
import io  
import pandas as pd  
from flask import Flask, request, redirect, url_for, jsonify, send_file 
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
            "print_receipt_opt": "列印收據", "daily_seq_prefix": "單號", "ai_note": "翻譯由 AI 提供"
        },
        "en": {
            "title": "Order", "welcome": "Welcome", "table_placeholder": "Table No.",
            "table_label": "Table", "add": "Add", "sold_out": "Sold Out", "cart_detail": "Cart",
            "total": "Total", "checkout": "Checkout", "cart_title": "Cart", "empty_cart": "Empty",
            "close": "Close", "confirm_delete": "Remove?", "confirm_order": "Submit?",
            "modal_unit_price": "Price", "modal_add_cart": "Add to Cart", "modal_cancel": "Cancel",
            "custom_options": "Options", "order_success": "Success!", "kitchen_prep": "Preparing...",
            "pay_at_counter": "Please pay at counter", "order_details": "Order Details",
            "print_receipt_opt": "Print Receipt", "daily_seq_prefix": "No.", "ai_note": "Translated by AI"
        },
        "jp": {
            "title": "注文", "welcome": "ようこそ", "table_placeholder": "卓番",
            "table_label": "卓番", "add": "追加", "sold_out": "完売", "cart_detail": "カート",
            "total": "合計", "checkout": "会計", "cart_title": "詳細", "empty_cart": "空です",
            "close": "閉じる", "confirm_delete": "削除？", "confirm_order": "送信？",
            "modal_unit_price": "単価", "modal_add_cart": "カートへ", "modal_cancel": "キャンセル",
            "custom_options": "オプション", "order_success": "送信完了", "kitchen_prep": "調理中...",
            "pay_at_counter": "レジでお会計ください", "order_details": "注文詳細",
            "print_receipt_opt": "レシート印刷", "daily_seq_prefix": "番号", "ai_note": "AIによる翻訳"
        },
        "kr": {
            "title": "주문", "welcome": "환영합니다", "table_placeholder": "테이블 번호",
            "table_label": "테이블", "add": "추가", "sold_out": "매진", "cart_detail": "장바구니",
            "total": "합계", "checkout": "결제하기", "cart_title": "상세 내역", "empty_cart": "비어 있음",
            "close": "닫기", "confirm_delete": "삭제하시겠습니까?", "confirm_order": "주문하시겠습니까?",
            "modal_unit_price": "단가", "modal_add_cart": "장바구니 담기", "modal_cancel": "취소",
            "custom_options": "옵션", "order_success": "주문 성공!", "kitchen_prep": "준비 중...",
            "pay_at_counter": "카운터에서 결제해주세요", "order_details": "주문 내역",
            "print_receipt_opt": "영수증 출력", "daily_seq_prefix": "번호", "ai_note": "AI 번역"
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
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS daily_seq INTEGER DEFAULT 0;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS content_json TEXT;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS need_receipt BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS lang VARCHAR(10) DEFAULT 'zh';"
        ]
        for cmd in alters:
            try: cur.execute(cmd)
            except: pass

        return "資料庫結構檢查完成。<a href='/'>回首頁</a> | <a href='/admin'>回後台</a>"
    except Exception as e:
        return f"DB Error: {e}"
    finally:
        cur.close(); conn.close()

# --- 2. 首頁與語言選擇 ---
@app.route('/')
def language_select():
    tbl = request.args.get('table', '')
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

# --- 3. 點餐頁面 ---
@app.route('/menu', methods=['GET', 'POST'])
def menu():
    lang = request.args.get('lang', 'zh')
    t = load_translations().get(lang, load_translations()['zh'])
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        try:
            table_number = request.form.get('table_number')
            cart_json = request.form.get('cart_data')
            need_receipt = request.form.get('need_receipt') == 'on'
            lang_from_page = request.form.get('lang_input', 'zh')
            old_order_id = request.form.get('old_order_id')

            if not cart_json or cart_json == '[]': return "Empty Cart"

            cart_items = json.loads(cart_json)
            total_price = 0
            display_list = []

            final_lang = lang_from_page 
            if old_order_id:
                cur.execute("SELECT lang FROM orders WHERE id=%s", (old_order_id,))
                orig_res = cur.fetchone()
                if orig_res:
                    final_lang = orig_res[0] 

            for item in cart_items:
                price = int(float(item['unit_price']))
                qty = int(float(item['qty']))
                total_price += (price * qty)
                
                n_field = f"name_{final_lang}" if f"name_{final_lang}" in item else "name_zh"
                n_display = item.get(n_field, item.get('name_zh'))
                
                opt_key = f"options_{final_lang}" if f"options_{final_lang}" in item else "options_zh"
                opts = item.get(opt_key, item.get('options_zh', []))
                opt_str = f"({','.join(opts)})" if opts else ""
                display_list.append(f"{n_display} {opt_str} x{qty}")

            items_str = " + ".join(display_list)

            cur.execute("SELECT COUNT(*) FROM orders WHERE created_at >= CURRENT_DATE")
            new_seq = cur.fetchone()[0] + 1

            cur.execute("""
                INSERT INTO orders (table_number, items, total_price, lang, daily_seq, content_json, need_receipt)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (table_number, items_str, total_price, final_lang, new_seq, cart_json, need_receipt))

            oid = cur.fetchone()[0]
            if old_order_id:
                cur.execute("UPDATE orders SET status='Cancelled' WHERE id=%s", (old_order_id,))
                conn.commit()
                return "<script>window.close();</script>"

            conn.commit()
            return redirect(url_for('order_success', order_id=oid, lang=final_lang))

        except Exception as e:
            conn.rollback()
            return f"Order Failed: {e}"
        finally:
            cur.close(); conn.close()

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
                name_en, name_jp, name_kr, custom_options_en, custom_options_jp, custom_options_kr, print_category
        FROM products ORDER BY sort_order ASC, id ASC
    """)
    products = cur.fetchall()
    cur.close(); conn.close()

    p_list = []
    for p in products:
        p_list.append({
            'id': p[0], 
            'name_zh': p[1],
            'name_en': p[8] or p[1],
            'name_jp': p[9] or p[1],
            'name_kr': p[10] or p[1],
            'price': p[2], 
            'category': p[3],
            'image_url': p[4] or '', 
            'is_available': p[5], 
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
    edit_notice = f'<div style="background:#fff3cd;padding:10px;color:#856404;text-align:center;">⚠️ 正在編輯 #{edit_oid} (語言自動適配)</div>' if edit_oid else ''

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
    const P={p_json}, T={t_json}, PRELOAD={preload_cart}, CUR_LANG="{lang}";
    let C=[], cur=null, q=1, selectedOptIndices=[], addP=0;

    if(PRELOAD && PRELOAD.length > 0) C = PRELOAD;
    
    let h="", cat="";
    P.forEach(p=>{{
        if(p.category!=cat) {{ h+=`<div class="cat-header">${{p.category}}</div>`; cat=p.category; }}
        let isAvail = p.is_available;
        let d_name = p['name_' + CUR_LANG] || p.name_zh;
        h+=`<div class="menu-item ${{isAvail ? '' : 'sold-out'}}">
            ${{isAvail ? '' : `<div class="sold-out-badge">${{T.sold_out}}</div>`}}
            ${{p.image_url ? `<img src="${{p.image_url}}" class="menu-img">` : ''}}
            <div class="menu-info">
                <div><b>${{d_name}}</b><div style="color:#e91e63">$${{p.price}}</div></div>
                <button class="add-btn" onclick="openOpt(${{p.id}})" ${{isAvail ? '' : 'disabled'}}>${{isAvail ? T.add : T.sold_out}}</button>
            </div>
        </div>`;
    }});
    document.getElementById('list').innerHTML=h;
    upd();

    function openOpt(id){{
        cur=P.find(x=>x.id==id); q=1; selectedOptIndices=[]; addP=0;
        document.getElementById('m-name').innerText = cur['name_' + CUR_LANG] || cur.name_zh;
        let area=document.getElementById('m-opts'); area.innerHTML="";
        let opts = cur['custom_options_' + CUR_LANG] || cur.custom_options_zh;
        opts.forEach((o, index)=>{{
            let parts = o.split(/[+]/);
            let n = parts[0].trim(), p = parts.length>1 ? parseInt(parts[1]) : 0;
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

    function addC(){{
        C.push({{ 
            id: cur.id, 
            name: cur.name_en, 
            name_zh: cur.name_zh, 
            name_jp: cur.name_jp, 
            name_kr: cur.name_kr, 
            unit_price: cur.price + addP, 
            qty: q, 
            options: selectedOptIndices.map(idx => cur.custom_options_en[idx]),
            options_zh: selectedOptIndices.map(idx => cur.custom_options_zh[idx]),
            options_jp: selectedOptIndices.map(idx => cur.custom_options_jp[idx]),
            options_kr: selectedOptIndices.map(idx => cur.custom_options_kr[idx]),
            category: cur.category, 
            print_category: cur.print_category 
        }});
        document.getElementById('opt-m').style.display='none'; upd();
    }}

    function cq(n){{ if(q+n>0) {{q+=n; document.getElementById('m-q').innerText=q;}} }}
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
                <div><b>${{i['name_' + CUR_LANG] || i.name_zh}}</b> x${{i.qty}}</div>
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

# --- 4. 下單成功 ---
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
        d_name = i.get(f'name_{lang}', i.get('name_zh', i.get('name')))
        ops = i.get(f'options_{lang}', i.get('options_zh', i.get('options', [])))
        opt_str = f" <br><small style='color:#888;'>└ {','.join(ops)}</small>" if ops else ""
        items_html += f"""
        <div style='display:flex; justify-content:space-between; border-bottom:1px dashed #ddd; padding:10px 0;'>
            <span><b style="font-size:1.1em;">{d_name}</b> x{i['qty']}{opt_str}</span>
            <span style="font-weight:bold;">${i['unit_price'] * i['qty']}</span>
        </div>
        """
    return f"""
    <div style="max-width:450px; margin:30px auto; text-align:center; font-family:'Microsoft JhengHei', sans-serif; padding:25px; border:1px solid #eee; border-radius:15px; box-shadow:0 4px 12px rgba(0,0,0,0.1);">
        <div style="font-size:50px; margin-bottom:10px;">✅</div>
        <h1 style="color:#28a745; margin:0;">{t['order_success']}</h1>
        <div style="margin:20px 0; padding:15px; background:#fff5f8; border-radius:10px;">
            <div style="font-size:0.9em; color:#e91e63; font-weight:bold; margin-bottom:5px;">取餐單號 / Order Number</div>
            <div style="font-size:4em; font-weight:bold; color:#e91e63; line-height:1;">#{seq:03d}</div>
        </div>
        <p style="color:#666; font-size:0.9em;">時間: {time_str}</p>
        <div style="background:#fdf6e3; padding:15px; border-left:5px solid #ff9800; border-radius:5px; margin-bottom:20px; text-align:left;">
            <p style="margin:0; font-weight:bold; color:#856404; font-size:1.2em;">⚠️ {t['pay_at_counter']}</p>
            <p style="margin:5px 0 0 0; color:#856404;">{t['kitchen_prep']}</p>
        </div>
        <div style="text-align:left; margin-top:20px;">
            <h3 style="border-bottom:2px solid #333; padding-bottom:10px; margin-bottom:10px;">🧾 {t['order_details']}</h3>
            {items_html}
            <div style="text-align:right; font-weight:bold; font-size:1.4em; margin-top:15px; color:#d32f2f;">{t['total']}: ${total}</div>
        </div>
        <br><a href="/" style="display:block; padding:15px; background:#007bff; color:white; text-decoration:none; border-radius:8px; font-weight:bold; font-size:1.1em;">回首頁 / Back to Menu</a>
    </div>
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
        if status == 'Pending': btns += f"<button onclick='action(\"/kitchen/complete/{oid}\")' class='btn btn-complete'>✔️ 完成</button>"
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

# --- 8. 列印路由 (修正版：解決結帳單列印仍是英文的問題) ---
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
        items = json.loads(c_json) if c_json else [{"name": n, "qty": 1, "unit_price": 0, "options": [], "options_zh": []} for n in raw_items.split("+")]
    except: return "解析失敗"

    is_void = (status == 'Cancelled')
    tw_time = created_at + timedelta(hours=8)
    time_str = tw_time.strftime('%Y-%m-%d %H:%M:%S')
    title = "❌ 作廢單 (VOID)" if is_void else "結帳單 (Receipt)"
    style = "text-decoration: line-through; color:red;" if is_void else ""

    # --- [關鍵修正邏輯] ---
    def get_display_name(item):
        n_zh = item.get('name_zh', '商品')
        # 如果是中文訂單，只顯示中文
        if order_lang == 'zh': return n_zh
        # 如果是外國語系，顯示「該語言名稱」+「(中文名稱)」
        n_foreign = item.get(f'name_{order_lang}', item.get('name', n_zh))
        return f"{n_foreign}<br><small>({n_zh})</small>"

    def mk_ticket(t_name, item_list, show_total=False, is_kitchen=False):
        if not item_list and not show_total: return ""
        h = f"<div class='ticket' style='{style}'><div class='head'><h2>{t_name}</h2><h1>#{seq}</h1><p>Table: {table_num}</p><small>{time_str}</small></div><hr>"
        for i in item_list:
            qty = i.get('qty', 1); u_p = i.get('unit_price', 0)
            if is_kitchen:
                d_name = i.get('name_zh', '商品')
                ops = i.get('options_zh', [])
            else:
                d_name = get_display_name(i)
                ops = i.get(f'options_{order_lang}', i.get('options', []))
            
            if isinstance(ops, str): ops = [ops]
            h += f"<div class='row'><span>{qty} x {d_name}</span><span>${u_p * qty}</span></div>"
            if ops: h += f"<div class='opt'>└ {', '.join(ops)}</div>"
        if show_total: h += f"<hr><div style='text-align:right;font-size:1.2em;font-weight:bold;'>Total: ${total_val}</div>"
        return h + "</div><div class='break'></div>"

    body = mk_ticket(title, items, show_total=True, is_kitchen=False)
    if not is_void:
        noodles = [i for i in items if i.get('print_category', 'Noodle') == 'Noodle']
        soups = [i for i in items if i.get('print_category') == 'Soup']
        if noodles: body += mk_ticket("🍜 麵區工單", noodles, is_kitchen=True)
        if soups: body += mk_ticket("🍲 湯區工單", soups, is_kitchen=True)

    return f"""
    <html><head><meta charset="UTF-8">
    <style>
        body {{ font-family: 'Microsoft JhengHei', sans-serif; font-size: 14px; background: #eee; padding: 20px; }} 
        .ticket {{ width: 58mm; background: white; margin: 0 auto 10px auto; padding: 10px; border: 1px dashed #ccc; }} 
        .head {{ text-align: center; }} 
        .row {{ display: flex; justify-content: space-between; margin-top: 8px; font-weight: bold; }} 
        .opt {{ font-size: 12px; color: #444; margin-left: 15px; }} 
        .break {{ page-break-after: always; }} 
        h1 {{ margin: 5px 0; font-size: 2.5em; }}
        @media print {{ body {{ background: white; padding: 0; }} .ticket {{ width: 100%; border: none; }} }}
    </style></head>
    <body onload='window.print(); setTimeout(function(){{ window.close(); }}, 1000);'>{body}</body></html>
    """

# --- 9. 後台管理 ---
@app.route('/admin/reorder_products', methods=['POST'])
def reorder_products():
    data = request.get_json(); new_order = data.get('order', [])
    conn = get_db_connection(); cur = conn.cursor()
    for index, prod_id in enumerate(new_order): cur.execute("UPDATE products SET sort_order = %s WHERE id = %s", (index + 1, prod_id))
    conn.commit(); conn.close(); return jsonify({'status': 'success'})

@app.route('/admin/toggle_product/<int:pid>')
def toggle_product(pid):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("UPDATE products SET is_available = NOT is_available WHERE id = %s", (pid,)); conn.commit(); conn.close(); return redirect('/admin')

@app.route('/admin/delete_product/<int:pid>')
def delete_product(pid):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("DELETE FROM products WHERE id = %s", (pid,)); conn.commit(); conn.close(); return redirect('/admin')

@app.route('/admin/reset_orders')
def reset_orders():
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("DELETE FROM orders"); cur.execute("ALTER SEQUENCE IF EXISTS orders_id_seq RESTART WITH 1"); conn.commit(); conn.close(); return redirect('/admin')

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    conn = get_db_connection(); cur = conn.cursor()
    if request.method == 'POST':
        cur.execute("""INSERT INTO products (name, price, category, image_url, custom_options, name_en, name_jp, name_kr, custom_options_en, custom_options_jp, custom_options_kr, print_category, sort_order) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 9999)""", (request.form.get('name'), request.form.get('price'), request.form.get('category'), request.form.get('image_url'), request.form.get('custom_options'), request.form.get('name_en'), request.form.get('name_jp'), request.form.get('name_kr'), request.form.get('custom_options_en'), request.form.get('custom_options_jp'), request.form.get('custom_options_kr'), request.form.get('print_category', 'Noodle')))
        conn.commit(); return redirect('/admin')
    cur.execute("SELECT id, name, price, category, image_url, is_available, custom_options, sort_order, name_en, name_jp, name_kr, custom_options_en, custom_options_jp, custom_options_kr, print_category FROM products ORDER BY sort_order ASC, id DESC")
    prods = cur.fetchall(); conn.close()
    rows = ""
    for p in prods:
        row_style = "" if p[5] else "background-color: #f0f0f0; opacity: 0.7;"
        rows += f"""<tr data-id="{p[0]}" class="draggable-item" style="{row_style}"><td class="handle">☰</td><td>{p[0]}</td><td><b>{p[1]}</b><br><small>{p[3]}</small></td><td>{p[2]}</td><td>{p[14]}</td><td>{'上架' if p[5] else '下架'} <a href='/admin/toggle_product/{p[0]}'>[切換]</a></td><td><a href='/admin/edit_product/{p[0]}'>編輯</a> | <a href='/admin/delete_product/{p[0]}' style='color:red;'>刪除</a></td></tr>"""
    return f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><title>餐廳後台</title><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/milligram/1.4.1/milligram.min.css"><script src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.14.0/Sortable.min.js"></script></head>
    <body style="padding:20px;"><h4>➕ 新增產品</h4><form method="POST"><div class="row"><div class="column"><label>名稱(中)</label><input type="text" name="name" required></div><div class="column"><label>價格</label><input type="number" name="price" required></div><div class="column"><label>分類</label><input type="text" name="category" required></div><div class="column"><label>出單區</label><select name="print_category"><option value="Noodle">麵區</option><option value="Soup">湯區</option></select></div></div><div class="row"><div class="column"><label>EN</label><input type="text" name="name_en"></div><div class="column"><label>JP</label><input type="text" name="name_jp"></div><div class="column"><label>KR</label><input type="text" name="name_kr"></div></div><label>中文選項</label><input type="text" name="custom_options"><button type="submit">新增</button></form><hr><h3>📦 產品列表</h3><table><tbody id="menu-list">{rows}</tbody></table><script>Sortable.create(document.getElementById('menu-list'), {{ handle: '.handle', onEnd: function () {{ /* Save logic */ }} }});</script></body></html>
    """

# --- 編輯產品頁面 ---
@app.route('/admin/edit_product/<int:pid>', methods=['GET','POST'])
def edit_product(pid):
    conn = get_db_connection(); cur = conn.cursor()
    if request.method == 'POST':
        cur.execute("""UPDATE products SET name=%s, price=%s, category=%s, image_url=%s, custom_options=%s, name_en=%s, name_jp=%s, name_kr=%s, custom_options_en=%s, custom_options_jp=%s, custom_options_kr=%s, print_category=%s, sort_order=%s WHERE id=%s""", (request.form.get('name'), request.form.get('price'), request.form.get('category'), request.form.get('image_url'), request.form.get('custom_options'), request.form.get('name_en'), request.form.get('name_jp'), request.form.get('name_kr'), request.form.get('custom_options_en'), request.form.get('custom_options_jp'), request.form.get('custom_options_kr'), request.form.get('print_category'), request.form.get('sort_order'), pid))
        conn.commit(); conn.close(); return redirect('/admin')
    cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
    p = cur.fetchone(); conn.close()
    return f"""<!DOCTYPE html><html><body style="padding:20px;"><h3>編輯 #{p[0]}</h3><form method="POST"><label>名稱</label><input type="text" name="name" value="{p[1]}"><label>價格</label><input type="number" name="price" value="{p[2]}"><button type="submit">儲存</button></form></body></html>"""

# --- 防休眠 ---
def keep_alive():
    while True:
        try: urllib.request.urlopen("https://ding-dong-tipi.onrender.com")
        except: pass
        time.sleep(800)
threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
