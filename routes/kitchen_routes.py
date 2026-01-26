from flask import Blueprint, render_template, request, jsonify
import json
from datetime import datetime, timedelta
from database import get_db_connection 

kitchen_bp = Blueprint('kitchen', __name__)

def get_tw_time_range(target_date_str=None, end_date_str=None):
    """計算台灣時間的 UTC 起始與結束範圍 (支援報表與查詢)"""
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

# --- 2. 檢查新訂單 API (含作廢單渲染邏輯) ---
@kitchen_bp.route('/check_new_orders')
def check_new_orders():
    current_max = request.args.get('current_seq', 0, type=int)
    utc_start, utc_end = get_tw_time_range()

    conn = get_db_connection()
    cur = conn.cursor()
    
    # 查詢當日所有訂單 (Pending, Completed, Cancelled)
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
    if current_max > 0:
        cur.execute("SELECT id FROM orders WHERE daily_seq > %s AND created_at >= %s", (current_max, utc_start))
        new_order_ids = [r[0] for r in cur.fetchall()]
    conn.close()

    html_content = ""
    if not orders: 
        html_content = "<div id='loading-msg' style='grid-column:1/-1;text-align:center;padding:100px;font-size:1.5em;color:#888;'>🍽️ 目前沒有訂單</div>"
    
    for o in orders:
        oid, table, raw_items, total, status, created, order_lang, seq_num, c_json = o
        status_cls = status.lower() # 'pending', 'completed', 'cancelled'
        tw_time = created + timedelta(hours=8)
        
        # 處理品項 HTML
        items_html = ""
        try:
            cart = json.loads(c_json) if c_json else []
            for item in cart:
                name = item.get('name_zh', item.get('name', '商品'))
                qty = item.get('qty', 1)
                options = item.get('options_zh', item.get('options', []))
                opts_html = f"<div class='item-opts' style='font-size:0.85em; color:#666;'>└ {' / '.join(options)}</div>" if options else ""
                items_html += f"<div class='item-row' style='margin-bottom:5px; border-bottom:1px solid #eee; padding-bottom:3px;'><div class='item-name' style='display:flex; justify-content:space-between; font-weight:bold;'><span>{name}</span><span class='item-qty'>x{qty}</span></div>{opts_html}</div>"
        except: 
            items_html = "<div class='item-row'>資料解析錯誤</div>"

        formatted_total = f"{int(total)}" 
        buttons = ""

        # 根據狀態決定顯示樣式與按鈕
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
            # 作廢單按鈕區域 (僅保留補印，且文字提示已作廢)
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

        # 生成卡片，特別處理 cancelled class
        html_content += f"""
        <div class="card {status_cls}" data-id="{oid}">
            <div class="card-header" style="display:flex; justify-content:space-between; align-items:start; margin-bottom:10px; border-bottom:2px solid #eee; padding-bottom:5px;">
                <div><div class="seq-num" style="font-size:1.5em; font-weight:900;">#{seq_num:03d}</div><div class="time-stamp" style="font-size:0.8em; color:#666;">{tw_time.strftime('%H:%M')} ({order_lang})</div></div>
                <div class="table-num" style="background:#333; color:white; padding:4px 10px; border-radius:4px; font-weight:bold;">桌號 {table}</div>
            </div>
            <div class="items" style="min-height:80px;">{items_html}</div>
            <div class="actions" style="margin-top:15px;">{buttons}</div>
        </div>"""
        
    return jsonify({'html': html_content, 'max_seq': max_seq_val, 'new_ids': new_order_ids})

# --- 3. 補印功能 (整合分區列印) ---
@kitchen_bp.route('/print_order/<int:oid>')
def print_order(oid):
    print_type = request.args.get('type', 'all')
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT table_number, total_price, daily_seq, content_json, created_at, status FROM orders WHERE id=%s", (oid,))
    order = cur.fetchone()
    if not order:
        conn.close(); return "訂單不存在", 404
    
    table_num, total_price, seq, content_json, created_at, status = order
    items = json.loads(content_json) if content_json else []
    time_str = (created_at + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')

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

    style = """
    <style>
        body { font-family: 'Microsoft JhengHei', sans-serif; width: 58mm; margin: 0; padding: 2mm; }
        .ticket { border-bottom: 2px dashed #000; padding: 10px 0; page-break-after: always; position: relative; }
        .void-watermark { position: absolute; top: 40%; left: 10%; font-size: 40px; color: rgba(255,0,0,0.3); transform: rotate(-30deg); border: 4px solid rgba(255,0,0,0.3); padding: 5px; z-index: 100; pointer-events: none; }
        .head { text-align: center; }
        .head h1 { font-size: 40px; margin: 5px 0; }
        .head h2 { font-size: 18px; margin: 0; background: #333; color: #fff; padding: 2px; }
        .info { font-size: 14px; font-weight: bold; margin-bottom: 5px; }
        .item { display: flex; justify-content: space-between; font-size: 17px; font-weight: bold; margin: 4px 0; }
        .opt { font-size: 13px; color: #666; padding-left: 10px; margin-bottom: 5px; border-left: 2px solid #ccc; }
        .total { text-align: right; font-size: 18px; font-weight: bold; margin-top: 10px; border-top: 1px solid #000; }
    </style>
    """

    def generate_html(title, item_list, is_receipt=False):
        if not item_list: return ""
        void_mark = "<div class='void-watermark'>作廢單</div>" if status == 'Cancelled' else ""
        h = f"<div class='ticket'>{void_mark}<div class='head'><h2>{title}</h2><h1>#{seq:03d}</h1></div>"
        h += f"<div class='info'>桌號: {table_num}<br>時間: {time_str}</div><hr style='border:0; border-top:1px solid #000;'>"
        for i in item_list:
            name = i.get('name_zh') or i.get('name'); qty = i.get('qty', 1)
            opts = i.get('options_zh') or i.get('options', [])
            h += f"<div class='item'><span>{name}</span><span>x{qty}</span></div>"
            if opts: h += f"<div class='opt'>└ {', '.join(opts)}</div>"
        if is_receipt: h += f"<div class='total'>總計: ${int(total_price)}</div>"
        return h + "</div>"

    content = ""
    if print_type == 'receipt': content = generate_html("結帳單 (Receipt)", items, is_receipt=True)
    elif print_type == 'kitchen':
        content += generate_html("廚房單 - 面區", noodle_items)
        content += generate_html("廚房單 - 湯區", soup_items)
        content += generate_html("廚房單 - 其他", other_items)
    else: # all
        content = generate_html("結帳單 (Receipt)", items, is_receipt=True)
        content += generate_html("廚房單 - 面區", noodle_items)
        content += generate_html("廚房單 - 湯區", soup_items)
        content += generate_html("廚房單 - 其他", other_items)

    return f"<html><head>{style}</head><body onload='window.print();setTimeout(()=>window.close(),500);'>{content}</body></html>"

# --- 4. 狀態變更 ---
@kitchen_bp.route('/complete/<int:oid>')
def complete_order(oid):
    c=get_db_connection(); cur=c.cursor()
    cur.execute("UPDATE orders SET status='Completed' WHERE id=%s",(oid,))
    c.commit(); c.close(); return "OK"

@kitchen_bp.route('/cancel/<int:oid>')
def cancel_order(oid):
    c=get_db_connection(); cur=c.cursor()
    cur.execute("UPDATE orders SET status='Cancelled' WHERE id=%s",(oid,))
    c.commit(); c.close(); return "OK"

# --- 5. 日結報表與銷售排名 ---
@kitchen_bp.route('/sales_ranking')
def sales_ranking():
    # 支援來自 datetime-local 的 ISO 格式 (YYYY-MM-DDTHH:MM) 或舊版的日期格式
    start_time_str = request.args.get('start_time') or request.args.get('start')
    end_time_str = request.args.get('end_time') or request.args.get('end')
    
    utc_start, utc_end = None, None

    # 嘗試解析詳細時間 (YYYY-MM-DDTHH:MM)
    if start_time_str and 'T' in start_time_str:
        try:
            tw_start = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M')
            # 若無秒數補 00
            tw_start = tw_start.replace(second=0)
            
            if end_time_str and 'T' in end_time_str:
                tw_end = datetime.strptime(end_time_str, '%Y-%m-%dT%H:%M')
            else:
                tw_end = datetime.now() # 若無結束時間則設為現在

            # 轉換為 UTC (台灣為 +8，所以減 8)
            utc_start = tw_start - timedelta(hours=8)
            utc_end = tw_end - timedelta(hours=8)
        except ValueError:
            pass # 解析失敗則掉回下方邏輯

    # 如果上述解析未執行或失敗，使用舊有的整日邏輯
    if not utc_start:
        utc_start, utc_end = get_tw_time_range(start_time_str, end_time_str)

    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT content_json FROM orders WHERE created_at >= %s AND created_at <= %s AND status = 'Completed'", (utc_start, utc_end))
    rows = cur.fetchall(); conn.close()
    
    stats = {}
    for r in rows:
        if not r[0]: continue
        try:
            items = json.loads(r[0])
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
    
    conn = get_db_connection(); cur = conn.cursor()
    # 統計有效單
    cur.execute("SELECT COUNT(*), SUM(total_price) FROM orders WHERE created_at >= %s AND created_at <= %s AND status = 'Completed'", (utc_start, utc_end))
    v_count, v_total = cur.fetchone()
    cur.execute("SELECT content_json FROM orders WHERE created_at >= %s AND created_at <= %s AND status = 'Completed'", (utc_start, utc_end))
    v_rows = cur.fetchall()
    
    # 統計作廢單
    cur.execute("SELECT COUNT(*), SUM(total_price) FROM orders WHERE created_at >= %s AND created_at <= %s AND status = 'Cancelled'", (utc_start, utc_end))
    x_count, x_total = cur.fetchone()
    cur.execute("SELECT content_json FROM orders WHERE created_at >= %s AND created_at <= %s AND status = 'Cancelled'", (utc_start, utc_end))
    x_rows = cur.fetchall()
    conn.close()

    def agg(rows):
        res = {}
        for r in rows:
            if not r[0]: continue
            try:
                items = json.loads(r[0])
                for i in items:
                    name = i.get('name_zh', i.get('name', '商品'))
                    
                    # 修正：若 qty 欄位不存在，預設應為 1 (原為 0 會導致金額為 0)
                    qty_val = i.get('qty')
                    qty = int(float(qty_val)) if qty_val is not None else 1
                    
                    # 修正：確保 price 欄位讀取正確
                    price_val = i.get('price')
                    price = int(float(price_val)) if price_val is not None else 0
                    
                    if name not in res: res[name] = {'qty':0, 'amt':0}
                    res[name]['qty'] += qty
                    res[name]['amt'] += (qty * price)
            except: continue
        return res

    v_stats = agg(v_rows); x_stats = agg(x_rows)

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
            <div class="summary"><b>✅ 有效營收</b><br>單數: {v_count} | 總計: <span style="font-size:1.2em; color:#2e7d32;">${int(v_total or 0):,}</span></div>
            {tbl(v_stats)}
            <div class="summary void-sum" style="margin-top:20px;"><b>❌ 作廢統計</b><br>單數: {x_count} | 金額: ${int(x_total or 0):,}</div>
            {tbl(x_stats)}
            <p style="text-align:center; font-size:10px; color:#999; margin-top:20px;">列印時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        </div>
    </body></html>
    """
