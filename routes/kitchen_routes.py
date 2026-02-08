from flask import Blueprint, render_template, request, jsonify
import json
import base64  # 用於 RawBT 編碼
import traceback 
from datetime import datetime, timedelta
from database import get_db_connection

kitchen_bp = Blueprint('kitchen', __name__)

# --- 輔助函式：取得當前台灣時間字串 (用於 Log) ---
def get_current_time_str():
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

# --- 輔助函式：計算台灣時間範圍 (已修正訂單消失 bug) ---
def get_tw_time_range(target_date_str=None, end_date_str=None):
    try:
        # 1. 決定起始時間 tw_start
        if target_date_str and 'T' in target_date_str:
            # 情況 A: 傳入完整時間 (例如 2023-10-01T14:30)
            tw_start = datetime.strptime(target_date_str, '%Y-%m-%dT%H:%M')
            is_specific_time = True
        elif target_date_str:
            # 情況 B: 傳入日期 (例如 2023-10-01)
            tw_start = datetime.strptime(target_date_str, '%Y-%m-%d')
            is_specific_time = False
        else:
            # 情況 C: 沒傳入 (預設為今日)
            tw_start = datetime.utcnow() + timedelta(hours=8)
            is_specific_time = False
        
        # 2. 關鍵修正：如果不是指定「特定時間點」，一律將時間歸零從 00:00:00 開始
        # 這樣才能抓到「今天」所有的單，而不是「現在這一秒以後」的單
        if not is_specific_time:
            tw_start = tw_start.replace(hour=0, minute=0, second=0, microsecond=0)

        # 3. 決定結束時間 tw_end
        if end_date_str and 'T' in end_date_str:
            tw_end = datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
        elif end_date_str:
            tw_end = datetime.strptime(end_date_str, '%Y-%m-%d')
            tw_end = tw_end.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            # 預設結束時間為當天最後一秒 (涵蓋整天)
            # 注意：這裡使用 tw_start 的日期部分來設定結束時間
            tw_end = tw_start.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # 4. 轉回 UTC 給資料庫查詢 (-8小時)
        return tw_start - timedelta(hours=8), tw_end - timedelta(hours=8)

    except Exception as e:
        print(f"Time Range Error: {e}")
        # 發生錯誤時的保險措施：回傳今日整天
        now = datetime.utcnow() + timedelta(hours=8)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start - timedelta(hours=8), end - timedelta(hours=8)


# --- 1. 廚房看板主頁 ---
@kitchen_bp.route('/')
def kitchen_panel():
    return render_template('kitchen.html')


# --- 2. 檢查訂單 API (精簡版，移除自動列印觸發) ---
@kitchen_bp.route('/check_new_orders')
def check_new_orders():
    try:
        current_max = request.args.get('current_seq', 0, type=int)
        utc_start, utc_end = get_tw_time_range()
        conn = get_db_connection(); cur = conn.cursor()
        
        cur.execute("""
            SELECT id, table_number, items, total_price, status, created_at, lang, daily_seq, content_json 
            FROM orders WHERE created_at >= %s AND created_at <= %s
            ORDER BY CASE WHEN status = 'Pending' THEN 0 WHEN status = 'Completed' THEN 1 ELSE 2 END, daily_seq DESC
        """, (utc_start, utc_end))
        orders = cur.fetchall()
        
        cur.execute("SELECT MAX(daily_seq) FROM orders WHERE created_at >= %s AND created_at <= %s", (utc_start, utc_end))
        max_seq_val = cur.fetchone()[0] or 0
        conn.close()

        html_content = ""
        if not orders:
            html_content = "<div style='text-align:center;padding:100px;color:#888;'>🍽️ 目前沒有訂單</div>"
        
        for o in orders:
            oid, table, _, total, status, created, lang, seq, c_json = o
            tw_time = created + timedelta(hours=8)
            items_html = ""
            try:
                cart = json.loads(c_json) if isinstance(c_json, str) else (c_json or [])
                for i in cart:
                    name = i.get('name_zh', i.get('name', '商品'))
                    items_html += f"<div style='border-bottom:1px solid #eee;padding:4px 0;'><b>{name}</b> x{i.get('qty',1)}</div>"
            except: items_html = "解析錯誤"

            status_cls = status.lower()
            # 統一呼叫 askPrintType
            btn_print = f"<button onclick='askPrintType({oid})' class='btn btn-print' style='flex:1;'>🖨️ 列印</button>"
            
            html_content += f"""
            <div class="card {status_cls}" data-id="{oid}" style="border:1px solid #ddd;padding:10px;margin:5px;background:#fff;border-radius:8px;">
                <div style="display:flex;justify-content:space-between;border-bottom:2px solid #333;">
                    <span style="font-size:20px;font-weight:900;">#{seq:03d}</span>
                    <span style="background:#333;color:#fff;padding:2px 8px;border-radius:4px;">桌號 {table}</span>
                </div>
                <div style="min-height:60px;margin:10px 0;">{items_html}</div>
                <div style="display:flex;gap:5px;">
                    {btn_print}
                    <button onclick='action(\"/kitchen/complete/{oid}\")' class='btn' style='background:#28a745;color:white;flex:1;'>OK</button>
                </div>
            </div>
            """
        return jsonify({'html': html_content, 'max_seq': max_seq_val})
    except:
        return jsonify({'html': '載入失敗', 'max_seq': 0})

# --- 3. 核心列印路由 (針對 Windows USB 進行結構優化) ---
@kitchen_bp.route('/print_order/<int:oid>')
def print_order(oid):
    try:
        print_type = request.args.get('type', 'all')
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT table_number, total_price, daily_seq, content_json, created_at, status FROM orders WHERE id=%s", (oid,))
        order = cur.fetchone()
        cur.execute("SELECT name, print_category FROM products")
        p_map = {r[0]: r[1] for r in cur.fetchall()}
        conn.close()

        if not order: return "訂單不存在", 404
        table, total, seq, c_json, created, status = order
        items = json.loads(c_json) if isinstance(c_json, str) else (c_json or [])
        time_str = (created + timedelta(hours=8)).strftime('%H:%M:%S')

        # 分類邏輯
        cats = {'Noodle': [], 'Soup': [], 'Other': []}
        for i in items:
            name = i.get('name_zh') or i.get('name')
            c = p_map.get(name, 'Other')
            if c in cats: cats[c].append(i)
            else: cats['Other'].append(i)

        style = """
        <style>
            @page { size: 80mm auto; margin: 0; }
            body { font-family: 'Arial', sans-serif; width: 72mm; margin: 0; padding: 2mm; color: #000; }
            .ticket { border-bottom: 2px dashed #000; padding-bottom: 10px; margin-bottom: 10px; page-break-after: always; }
            .ticket:last-child { page-break-after: auto; }
            .title { text-align: center; font-size: 22px; font-weight: bold; border: 2px solid #000; }
            .seq { text-align: center; font-size: 40px; font-weight: 900; margin: 5px 0; }
            table { width: 100%; border-collapse: collapse; }
            .item-name { font-size: 18px; font-weight: bold; }
            .qty { font-size: 20px; font-weight: bold; text-align: right; }
        </style>
        """

        def gen_section(title, item_list, is_receipt=False):
            if not item_list: return ""
            h = f"<div class='ticket'><div class='title'>{title}</div><div class='seq'>#{seq:03d}</div>"
            h += f"<div style='text-align:center;'>桌號: <b>{table}</b> | {time_str}</div><hr>"
            h += "<table>"
            for i in item_list:
                name = i.get('name_zh') or i.get('name')
                h += f"<tr><td class='item-name'>{name}</td><td class='qty'>x{i.get('qty',1)}</td></tr>"
                opts = i.get('options_zh') or i.get('options', [])
                if opts: h += f"<tr><td colspan='2' style='font-size:14px;'>└ {','.join(opts)}</td></tr>"
            h += "</table>"
            if is_receipt: h += f"<div style='text-align:right;font-size:20px;border-top:2px solid #000;'>總計: ${int(total)}</div>"
            return h + "</div>"

        content = ""
        if print_type in ['all', 'receipt']: content += gen_section("結帳單 Receipt", items, True)
        if print_type in ['all', 'kitchen']:
            if cats['Noodle']: content += gen_section("廚房單-麵區", cats['Noodle'])
            if cats['Soup']: content += gen_section("廚房單-湯區", cats['Soup'])
            if cats['Other']: content += gen_section("廚房單-其他", cats['Other'])

        # RawBT Encoding (For Android)
        rawbt_html = f"<html><head>{style}</head><body>{content}</body></html>"
        b64_data = base64.b64encode(rawbt_html.encode('utf-8')).decode('utf-8')
        intent_url = f"intent:base64,{b64_data}#Intent;scheme=rawbt;package=ru.a402d.rawbtprinter;S.editor=false;end;"

        return f"""
        <html>
        <head>{style}</head>
        <body onload="doPrint()">
            {content}
            <script>
                function doPrint() {{
                    var isAndroid = /Android/i.test(navigator.userAgent);
                    if (isAndroid) {{
                        window.location.href = "{intent_url}";
                        setTimeout(() => window.close(), 2000);
                    }} else {{
                        window.print();
                        // Windows 下列印後嘗試關閉分頁
                        setTimeout(() => window.close(), 100);
                    }}
                }}
            </script>
        </body>
        </html>
        """
    except:
        traceback.print_exc(); return "Error", 500

@kitchen_bp.route('/complete/<int:oid>')
def complete_order(oid):
    c=get_db_connection(); cur=c.cursor()
    cur.execute("UPDATE orders SET status='Completed' WHERE id=%s",(oid,))
    c.commit(); c.close(); return "OK"


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


# --- 5. 銷售排名 API (配合前端的 fetchSalesRanking) ---
@kitchen_bp.route('/sales_ranking')
def sales_ranking():
    start_time_str = request.args.get('start_time')
    end_time_str = request.args.get('end_time')
    
    # 使用 get_tw_time_range 處理帶 'T' 的時間格式並轉為 UTC
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


# --- 6. 日結報表 (HTML) ---
@kitchen_bp.route('/report')
def daily_report():
    target_date_str = request.args.get('date') or (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m-%d')
    utc_start, utc_end = get_tw_time_range(target_date_str)
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT name, price FROM products")
    price_map = {row[0]: row[1] for row in cur.fetchall()}
    
    # 有效訂單
    cur.execute("""
        SELECT COUNT(*), SUM(total_price), content_json 
        FROM orders 
        WHERE created_at >= %s AND created_at <= %s 
        AND status IN ('Pending', 'Completed')
        GROUP BY id
    """, (utc_start, utc_end))
    v_rows = cur.fetchall()
    
    v_count = len(v_rows)
    v_total = sum([r[1] for r in v_rows if r[1]])

    # 作廢訂單
    cur.execute("""
        SELECT COUNT(*), SUM(total_price), content_json 
        FROM orders 
        WHERE created_at >= %s AND created_at <= %s 
        AND status = 'Cancelled'
        GROUP BY id
    """, (utc_start, utc_end))
    x_rows = cur.fetchall()

    x_count = len(x_rows)
    x_total = sum([r[1] for r in x_rows if r[1]])
    
    conn.close()

    def agg(rows):
        res = {}
        for r in rows:
            # r[2] 是 content_json
            if not r[2]: continue
            try:
                items = json.loads(r[2]) if isinstance(r[2], str) else r[2]
                if not isinstance(items, list): items = []
                
                for i in items:
                    name = i.get('name_zh', i.get('name', '商品'))
                    qty = int(float(i.get('qty', 1)))
                    price_val = i.get('price')
                    price = int(float(price_val)) if price_val is not None else price_map.get(name, 0)
                    
                    if name not in res: res[name] = {'qty':0, 'amt':0}
                    res[name]['qty'] += qty
                    res[name]['amt'] += (qty * price)
            except: continue
        return res

    v_stats = agg(v_rows)
    x_stats = agg(x_rows)

    def tbl(stats_dict):
        if not stats_dict: return "<p style='text-align:center;color:#888;'>無數據</p>"
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
            <div class="summary"><b>✅ 有效營收 (含進行中)</b><br>單數: {v_count} | 總計: <span style="font-size:1.2em; color:#2e7d32;">${int(v_total):,}</span></div>
            {tbl(v_stats)}
            <div class="summary void-sum" style="margin-top:20px;"><b>❌ 作廢統計</b><br>單數: {x_count} | 金額: ${int(x_total):,}</div>
            {tbl(x_stats)}
            <p style="text-align:center; font-size:10px; color:#999; margin-top:20px;">列印時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        </div>
    </body></html>
    """


