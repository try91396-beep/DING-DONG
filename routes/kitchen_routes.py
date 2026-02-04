from flask import Blueprint, render_template, request, jsonify
import json
import base64  # <--- ⚠️ 核心新增：用於 RawBT 編碼
import traceback 
from datetime import datetime, timedelta
from database import get_db_connection

kitchen_bp = Blueprint('kitchen', __name__)

# --- 輔助函式：取得當前台灣時間字串 (用於 Log) ---
def get_current_time_str():
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

# --- 輔助函式：計算台灣時間範圍 ---
def get_tw_time_range(target_date_str=None, end_date_str=None):
    try:
        if target_date_str:
            tw_start = datetime.strptime(target_date_str, '%Y-%m-%d')
        else:
            tw_start = datetime.utcnow() + timedelta(hours=8)
        
        tw_start = tw_start.replace(hour=0, minute=0, second=0, microsecond=0)

        if end_date_str:
            tw_end = datetime.strptime(end_date_str, '%Y-%m-%d')
        else:
            tw_end = tw_start
        
        tw_end = tw_end.replace(hour=23, minute=59, second=59, microsecond=999999)
        return tw_start - timedelta(hours=8), tw_end - timedelta(hours=8)
    except:
        now = datetime.utcnow() + timedelta(hours=8)
        return now.replace(hour=0, minute=0, second=0) - timedelta(hours=8), \
               now.replace(hour=23, minute=59, second=59) - timedelta(hours=8)


# --- 1. 廚房看板主頁 ---
@kitchen_bp.route('/')
def kitchen_panel():
    return render_template('kitchen.html')


# --- 2. 檢查新訂單 API ---
@kitchen_bp.route('/check_new_orders')
def check_new_orders():
    try:
        current_max = request.args.get('current_seq', 0, type=int)
        utc_start, utc_end = get_tw_time_range()

        conn = get_db_connection()
        cur = conn.cursor()
        
        query = """
            SELECT id, table_number, items, total_price, status, created_at, lang, daily_seq, content_json 
            FROM orders 
            WHERE created_at >= %s AND created_at <= %s
            ORDER BY 
                CASE WHEN status = 'Pending' THEN 0 
                     WHEN status = 'Completed' THEN 1 
                     ELSE 2 END, 
                daily_seq DESC
        """
        cur.execute(query, (utc_start, utc_end))
        orders = cur.fetchall()
        
        cur.execute("SELECT MAX(daily_seq) FROM orders WHERE created_at >= %s AND created_at <= %s", (utc_start, utc_end))
        res_max = cur.fetchone()
        max_seq_val = res_max[0] if res_max and res_max[0] else 0
        
        new_order_ids = []
        if current_max > 0 and max_seq_val > current_max:
            cur.execute("SELECT id, daily_seq FROM orders WHERE daily_seq > %s AND created_at >= %s", (current_max, utc_start))
            new_orders_data = cur.fetchall()
            new_order_ids = [r[0] for r in new_orders_data]

            if new_order_ids:
                seq_list = [f"#{r[1]}" for r in new_orders_data]
                print(f"[{get_current_time_str()}] 🔔 偵測到新訂單: {', '.join(seq_list)}")
        
        conn.close()

        html_content = ""
        if not orders: 
            html_content = "<div id='loading-msg' style='grid-column:1/-1;text-align:center;padding:100px;font-size:1.5em;color:#888;'>🍽️ 目前沒有訂單</div>"
        
        for o in orders:
            oid, table, raw_items, total, status, created, order_lang, seq_num, c_json = o
            status_cls = status.lower()
            tw_time = created + timedelta(hours=8)
            
            items_html = ""
            try:
                # 處理 JSON 格式相容性
                if isinstance(c_json, str):
                    cart = json.loads(c_json)
                elif isinstance(c_json, (list, dict)):
                    cart = c_json if isinstance(c_json, list) else [c_json]
                else:
                    cart = []

                for item in cart:
                    name = item.get('name_zh', item.get('name', '商品'))
                    qty = item.get('qty', 1)
                    options = item.get('options_zh', item.get('options', []))
                    opts_html = f"<div class='item-opts' style='font-size:0.85em; color:#666;'>└ {' / '.join(options)}</div>" if options else ""
                    items_html += f"<div class='item-row' style='margin-bottom:5px; border-bottom:1px solid #eee; padding-bottom:3px;'><div class='item-name' style='display:flex; justify-content:space-between; font-weight:bold;'><span>{name}</span><span class='item-qty'>x{qty}</span></div>{opts_html}</div>"
            except Exception as e: 
                print(f"JSON Parse Error (OID {oid}): {e}")
                items_html = "<div class='item-row'>資料解析錯誤</div>"

            formatted_total = f"{int(total or 0)}" 
            buttons = ""

            if status == 'Pending':
                buttons += f"""
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; padding:0 5px;">
                        <span style="font-size:14px; color:#666; font-weight:bold;">應收總計:</span>
                        <span style="font-size:22px; color:#d32f2f; font-weight:900;">${formatted_total}</span>
                    </div>
                """
                buttons += f"<button onclick='action(\"/kitchen/complete/{oid}\")' class='btn btn-main' style='width:100%; background:#28a745; color:white; border:none; padding:10px; border-radius:5px; font-weight:bold; cursor:pointer;'>✅ 出餐 / 付款</button>"
                buttons += f"""<div class="btn-group" style="margin-top:8px; display:flex; gap:5px;">
                    <button onclick='askPrintType({oid})' class='btn btn-print' style='flex:1; padding:8px;'>🖨️ 列印</button>
                    <a href='/menu?edit_oid={oid}&lang=zh' target='_blank' class='btn' style='flex:1; background:#ff9800; color:white; text-decoration:none; text-align:center; padding:8px; border-radius:4px;'>✏️ 修改</a>
                    <button onclick='if(confirm(\"⚠️ 確定作廢此單？\")) action(\"/kitchen/cancel/{oid}\")' class='btn btn-void' style='background:#f44336; color:white; border:none; padding:8px; border-radius:4px;'>🗑️</button>
                </div>"""
            elif status == 'Cancelled':
                buttons += f"<div style='text-align:center; color:#d32f2f; font-weight:bold; margin-bottom:5px;'>【此單已作廢】</div>"
                buttons += f"<button onclick='askPrintType({oid})' class='btn btn-print' style='width:100%; padding:8px; opacity:0.6;'>🖨️ 補印作廢單</button>"
            else: # Completed
                buttons += f"""
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; padding:0 5px; opacity:0.7;">
                        <span style="font-size:13px; color:#666;">實收總計:</span>
                        <span style="font-size:18px; color:#333; font-weight:bold;">${formatted_total}</span>
                    </div>
                """
                buttons += f"<button onclick='askPrintType({oid})' class='btn btn-print' style='width:100%; padding:10px;'>🖨️ 補印單據</button>"

            html_content += f"""
            <div class="card {status_cls}" data-id="{oid}" style="background:white; border:1px solid #ddd; border-radius:8px; padding:15px; box-shadow:0 2px 5px rgba(0,0,0,0.1);">
                <div class="card-header" style="display:flex; justify-content:space-between; align-items:start; margin-bottom:10px; border-bottom:2px solid #eee; padding-bottom:5px;">
                    <div><div class="seq-num" style="font-size:1.5em; font-weight:900;">#{seq_num:03d}</div><div class="time-stamp" style="font-size:0.8em; color:#666;">{tw_time.strftime('%H:%M')} ({order_lang})</div></div>
                    <div class="table-num" style="background:#333; color:white; padding:4px 10px; border-radius:4px; font-weight:bold;">桌號 {table}</div>
                </div>
                <div class="items" style="min-height:80px;">{items_html}</div>
                <div class="actions" style="margin-top:15px;">{buttons}</div>
            </div>"""
            
        return jsonify({
            'html': html_content, 
            'max_seq': max_seq_val, 
            'new_ids': new_order_ids
        })
    except Exception as e:
        print(f"Check Orders Error: {e}")
        return jsonify({'html': f"載入錯誤: {str(e)}", 'max_seq': 0, 'new_ids': []})


# --- 3. 補印功能 (整合 Windows/iOS 一般列印 + Android RawBT 靜默列印) ---
@kitchen_bp.route('/print_order/<int:oid>')
def print_order(oid):
    try:
        print_type = request.args.get('type', 'all')
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT table_number, total_price, daily_seq, content_json, created_at, status FROM orders WHERE id=%s", (oid,))
        order = cur.fetchone()
        conn.close()
        
        if not order:
            return "訂單不存在", 404
        
        table_num, total_price, seq, content_json, created_at, status = order
        
        # 資料解析防呆
        if isinstance(content_json, str):
            items = json.loads(content_json)
        elif isinstance(content_json, (list, dict)):
            items = content_json if isinstance(content_json, list) else [content_json]
        else:
            items = []
        
        time_str = (created_at + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')

        # 取得產品分類
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, print_category FROM products")
        product_map = {row[0]: row[1] for row in cur.fetchall()}
        conn.close()

        noodle_items, soup_items, other_items = [], [], []
        for item in items:
            p_name = item.get('name_zh') or item.get('name')
            p_cat = product_map.get(p_name, 'Noodle') 
            
            if p_cat == 'Noodle': noodle_items.append(item)
            elif p_cat == 'Soup': soup_items.append(item)
            else: other_items.append(item)

        # --- CSS 樣式 ---
        style = """
        <style>
            @page { size: 80mm auto; margin: 0mm; }
            body { 
                font-family: 'Microsoft JhengHei', sans-serif; 
                width: 78mm;      
                margin: 0 auto; 
                padding: 2px; 
                color: #000;
                background: #fff;
            }
            .ticket { 
                border-bottom: 3px dashed #000; 
                padding: 10px 0 30px 0; 
                margin-bottom: 10px;
                page-break-after: always; 
                position: relative; 
            }
            .ticket:last-child { page-break-after: auto; }
            .void-watermark { 
                position: absolute; top: 30%; left: 5%; 
                font-size: 50px; color: rgba(0,0,0,0.2); 
                transform: rotate(-30deg); border: 5px solid rgba(0,0,0,0.2); 
                padding: 10px; z-index: 100; pointer-events: none; font-weight: 900;
            }
            .head { text-align: center; margin-bottom: 10px; }
            .head h2 { font-size: 22px; margin: 0; background: #000; color: #fff; padding: 5px; border-radius: 4px; display:inline-block; }
            .head h1 { font-size: 48px; margin: 5px 0; line-height: 1; }
            
            .info-box { border-bottom: 3px solid #000; padding-bottom: 5px; margin-bottom: 10px; }
            .table-row { display: flex; justify-content: center; align-items: baseline; gap: 15px; }
            .table-label { font-size: 24px; font-weight: bold; }
            .table-val { font-size: 42px; font-weight: 900; line-height: 1; }
            .time-row { font-size: 14px; text-align: center; margin-top: 5px; }

            .item-row { display: flex; justify-content: space-between; align-items: flex-start; margin-top: 10px; line-height: 1.2; }
            .name-col { width: 85%; display: flex; flex-direction: column; }
            .item-name-main { font-size: 24px; font-weight: 900; word-wrap: break-word; line-height: 1.1; }
            .item-name-sub { font-size: 16px; font-weight: bold; color: #444; margin-top: 2px; }
            .item-qty { font-size: 24px; font-weight: 900; white-space: nowrap; }
            
            .opt { font-size: 18px; font-weight: bold; color: #000; padding-left: 15px; margin-top: 2px; margin-bottom: 5px; }
            .opt-sub { font-size: 14px; color: #555; margin-top: -2px; }
            .total { text-align: right; font-size: 24px; font-weight: 900; margin-top: 15px; padding-top: 10px; border-top: 2px solid #000; }
        </style>
        """

        def generate_html(title, item_list, is_receipt=False):
            if not item_list: return ""
            void_mark = "<div class='void-watermark'>作廢單</div>" if status == 'Cancelled' else ""
            h = f"<div class='ticket'>{void_mark}<div class='head'><h2>{title}</h2><h1>#{seq:03d}</h1></div>"
            h += f"<div class='info-box'><div class='table-row'><span class='table-label'>桌號 Table</span><span class='table-val'>{table_num}</span></div><div class='time-row'>{time_str}</div></div>"
            
            for i in item_list:
                main_name = i.get('name') or i.get('name_en') or i.get('name_zh') or 'Unknown'
                sub_name = i.get('name_zh', '')
                
                name_html = f"<div class='name-col'><span class='item-name-main'>{main_name}</span>"
                # 結帳單顯示雙語，廚房單如果主名稱不是中文才顯示中文
                if is_receipt:
                    if sub_name and sub_name != main_name: name_html += f"<span class='item-name-sub'>{sub_name}</span>"
                else:
                    # 廚房單強制優先顯示中文
                    kitchen_name = i.get('name_zh') or main_name
                    name_html = f"<div class='name-col'><span class='item-name-main'>{kitchen_name}</span>"

                name_html += "</div>"
                qty = i.get('qty', 1)
                h += f"<div class='item-row'>{name_html}<span class='item-qty'>x{qty}</span></div>"

                opts_main = i.get('options') or i.get('options_zh', [])
                opts_sub = i.get('options_zh', [])
                
                if opts_main: h += f"<div class='opt'>└ {', '.join(opts_main)}</div>"
                if is_receipt and opts_sub and opts_sub != opts_main:
                    h += f"<div class='opt opt-sub'>({', '.join(opts_sub)})</div>"
            
            if is_receipt: h += f"<div class='total'>Total: ${int(total_price or 0)}</div>"
            return h + "</div>"

        # 生成內容
        content = ""
        has_content = False
        
        if print_type in ['all', 'receipt']:
            content += generate_html("結帳單 Receipt", items, is_receipt=True)
            if items: has_content = True
            
        if print_type in ['all', 'kitchen']:
            if noodle_items: content += generate_html("廚房單 - 麵區", noodle_items); has_content = True
            if soup_items: content += generate_html("廚房單 - 湯區", soup_items); has_content = True
            if other_items: content += generate_html("廚房單 - 其他", other_items); has_content = True

        if not has_content:
            return "<script>alert('無可列印內容');window.close();</script>", 200

        # --- 雙模組核心邏輯 ---
        
        # 1. 準備 Android RawBT 用的 Base64 (必須包含 HTML 結構)
        rawbt_html_source = f"<html><head>{style}</head><body>{content}</body></html>"
        b64_data = base64.b64encode(rawbt_html_source.encode('utf-8')).decode('utf-8')
        
        # RawBT Intent (加入 S.editor=false 確保靜默)
        intent_url = (
            f"intent:base64,{b64_data}#Intent;"
            f"scheme=rawbt;"
            f"package=ru.a402d.rawbtprinter;"
            f"S.jobName=Order_{seq};"
            f"S.editor=false;"
            f"end;"
        )

        # 2. 準備回傳給瀏覽器的 HTML (包含內容 + 裝置判斷 JS)
        # 注意：不再使用 body onload="window.print()"，改由 JS 判斷
        final_html = f"""
        <!DOCTYPE html>
        <html>
        <head>{style}</head>
        <body>
            {content}
            <script>
                document.addEventListener("DOMContentLoaded", function() {{
                    var userAgent = navigator.userAgent || navigator.vendor || window.opera;
                    
                    // 偵測 Android 裝置
                    if (/android/i.test(userAgent)) {{
                        // --- Android 模式: 呼叫 RawBT ---
                        // 在頁面上顯示訊息
                        var msg = document.createElement('div');
                        msg.innerHTML = '<h2 style="text-align:center;color:green;margin-top:20px;">🖨️ 正在傳送至出單機...</h2>';
                        document.body.appendChild(msg);
                        
                        // 執行跳轉
                        window.location.href = "{intent_url}";
                        
                        // 嘗試關閉視窗 (對於彈出視窗有效)
                        setTimeout(function() {{
                            if(window.opener) window.close();
                        }}, 2000);
                        
                    }} else {{
                        // --- Windows / iOS 模式: 呼叫瀏覽器列印 ---
                        window.print();
                        
                        // Windows 通常不建議自動關閉，因為會中斷預覽
                        // 若需自動關閉可取消下方註解
                        /*
                        setTimeout(function() {{
                            if(window.opener) window.close();
                        }}, 500);
                        */
                    }}
                }});
            </script>
        </body>
        </html>
        """
        return final_html

    except Exception as e:
        traceback.print_exc()
        return f"列印發生錯誤: {str(e)}", 500


# --- 4. 狀態變更 (完成/作廢) ---
@kitchen_bp.route('/complete/<int:oid>')
def complete_order(oid):
    c=get_db_connection(); cur=c.cursor()
    cur.execute("UPDATE orders SET status='Completed' WHERE id=%s",(oid,))
    c.commit(); c.close(); 
    
    print(f"[{get_current_time_str()}] ✅ 訂單完成: ID {oid}")
    return "OK"

@kitchen_bp.route('/cancel/<int:oid>')
def cancel_order(oid):
    c=get_db_connection(); cur=c.cursor()
    cur.execute("UPDATE orders SET status='Cancelled' WHERE id=%s",(oid,))
    c.commit(); c.close(); 
    
    print(f"[{get_current_time_str()}] 🗑️ 訂單作廢: ID {oid}")
    return "OK"


# --- 5. 日結報表與銷售排名 ---
@kitchen_bp.route('/sales_ranking')
def sales_ranking():
    start_time_str = request.args.get('start_time') or request.args.get('start')
    end_time_str = request.args.get('end_time') or request.args.get('end')
    
    utc_start, utc_end = None, None

    if start_time_str and 'T' in start_time_str:
        try:
            tw_start = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M').replace(second=0)
            tw_end = datetime.strptime(end_time_str, '%Y-%m-%dT%H:%M') if (end_time_str and 'T' in end_time_str) else datetime.now()
            utc_start = tw_start - timedelta(hours=8)
            utc_end = tw_end - timedelta(hours=8)
        except ValueError: pass

    if not utc_start:
        utc_start, utc_end = get_tw_time_range(start_time_str, end_time_str)

    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT content_json FROM orders 
        WHERE created_at >= %s AND created_at <= %s 
        AND status IN ('Pending', 'Completed')
    """, (utc_start, utc_end))
    
    rows = cur.fetchall()
    conn.close()
    
    stats = {}
    for r in rows:
        if not r[0]: continue
        try:
            items = json.loads(r[0]) if isinstance(r[0], str) else r[0]
            if not isinstance(items, list): items = []
            
            for i in items:
                name = i.get('name_zh', i.get('name', '未知品項'))
                qty = int(float(i.get('qty', 1)))
                stats[name] = stats.get(name, 0) + qty
        except: continue
        
    sorted_data = [{"name": k, "count": v} for k, v in sorted(stats.items(), key=lambda item: item[1], reverse=True)]
    return jsonify(sorted_data)


@kitchen_bp.route('/report')
def daily_report():
    target_date_str = request.args.get('date') or (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m-%d')
    utc_start, utc_end = get_tw_time_range(target_date_str)
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT name, price FROM products")
    price_map = {row[0]: row[1] for row in cur.fetchall()}
    
    cur.execute("""
        SELECT COUNT(*), SUM(total_price) 
        FROM orders 
        WHERE created_at >= %s AND created_at <= %s 
        AND status IN ('Pending', 'Completed')
    """, (utc_start, utc_end))
    v_count, v_total = cur.fetchone()

    cur.execute("""
        SELECT content_json 
        FROM orders 
        WHERE created_at >= %s AND created_at <= %s 
        AND status IN ('Pending', 'Completed')
    """, (utc_start, utc_end))
    v_rows = cur.fetchall()
    
    cur.execute("""
        SELECT COUNT(*), SUM(total_price) 
        FROM orders 
        WHERE created_at >= %s AND created_at <= %s 
        AND status = 'Cancelled'
    """, (utc_start, utc_end))
    x_count, x_total = cur.fetchone()
    
    cur.execute("""
        SELECT content_json 
        FROM orders 
        WHERE created_at >= %s AND created_at <= %s 
        AND status = 'Cancelled'
    """, (utc_start, utc_end))
    x_rows = cur.fetchall()
    
    conn.close()

    def agg(rows):
        res = {}
        for r in rows:
            if not r[0]: continue
            try:
                items = json.loads(r[0]) if isinstance(r[0], str) else r[0]
                if not isinstance(items, list): items = []
                
                for i in items:
                    name = i.get('name_zh', i.get('name', '商品'))
                    qty_val = i.get('qty')
                    qty = int(float(qty_val)) if qty_val is not None else 1
                    
                    price_val = i.get('price')
                    if price_val is not None: 
                        price = int(float(price_val))
                    else: 
                        price = price_map.get(name, 0)
                    
                    if name not in res: res[name] = {'qty':0, 'amt':0}
                    res[name]['qty'] += qty
                    res[name]['amt'] += (qty * price)
            except: continue
        return res

    v_stats = agg(v_rows)
    x_stats = agg(x_rows)

    def tbl(stats_dict):
        if not stats_dict: return "<p style='text-align:center;color:#888;'>無銷售數據</p>"
        h = "<table style='width:100%; border-collapse:collapse; margin-top:10px;'><thead><tr style='border-bottom:2px solid #333;'><th style='text-align:left;'>品項</th><th style='text-align:right;'>數</th><th style='text-align:right;'>額</th></tr></thead><tbody>"
        for k, v in sorted(stats_dict.items(), key=lambda x:x[1]['qty'], reverse=True):
            h += f"<tr style='border-bottom:1px solid #eee;'><td>{k}</td><td style='text-align:right;'>{v['qty']}</td><td style='text-align:right;'>${v['amt']:,}</td></tr>"
        return h + "</tbody></table>"

    return f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><title>日結報表_{target_date_str}</title>
    <style>
        body {{ font-family: sans-serif; background: #f4f4f4; display:flex; flex-direction:column; align-items:center; padding:20px; }}
        .ticket {{ background: white; width: 80mm; padding: 15px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); border-radius: 5px; }}
        .summary {{ background: #e8f5e9; padding: 10px; border-radius: 5px; margin: 10px 0; border-left: 5px solid #2e7d32; }}
        .void-sum {{ background: #ffebee; border-left-color: #c62828; }}
        @media print {{ .no-print {{ display: none; }} body {{ background: white; padding: 0; }} .ticket {{ box-shadow: none; width: 100%; }} }}
    </style></head>
    <body>
        <div class="no-print" style="margin-bottom:20px;">
            <input type="date" id="dateInput" value="{target_date_str}" onchange="location.href='/kitchen/report?date='+this.value">
            <button onclick="window.print()">列印</button> <button onclick="location.href='/kitchen'">返回</button>
        </div>
        <div class="ticket">
            <h2 style="text-align:center; margin:0;">日結營收報表</h2>
            <p style="text-align:center; font-size:14px;">日期: {target_date_str}</p>
            <div class="summary"><b>✅ 有效營收 (含進行中)</b><br>單數: {v_count} | 總計: <span style="font-size:1.2em; color:#2e7d32;">${int(v_total or 0):,}</span></div>
            {tbl(v_stats)}
            <div class="summary void-sum" style="margin-top:20px;"><b>❌ 作廢統計</b><br>單數: {x_count} | 金額: ${int(x_total or 0):,}</div>
            {tbl(x_stats)}
            <p style="text-align:center; font-size:10px; color:#999; margin-top:20px;">列印時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        </div>
    </body></html>
    """
