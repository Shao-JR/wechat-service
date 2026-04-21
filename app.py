# app.py
from flask import Flask, request, jsonify, render_template_string
import sqlite3
from datetime import datetime
from wechat_service import WeChatService
import config
import json

app = Flask(__name__)
app.config.from_object(config.Config)

# 初始化微信服务
wechat = WeChatService(
    appid=app.config['WECHAT_APPID'],
    secret=app.config['WECHAT_APPSECRET'],
    db_path=app.config['DATABASE_PATH']
)

# 初始化数据库
def init_database():
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    cursor = conn.cursor()
    
    # 创建表
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        openid VARCHAR(64) UNIQUE NOT NULL,
        nickname VARCHAR(100),
        subscribe_time DATETIME,
        is_subscribed BOOLEAN DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS user_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        device_id VARCHAR(50) NOT NULL,
        device_name VARCHAR(100),
        is_active BOOLEAN DEFAULT 1,
        bind_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(user_id, device_id)
    );
    
    CREATE TABLE IF NOT EXISTS message_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(50) NOT NULL,
        content TEXT NOT NULL,
        msg_type VARCHAR(20) DEFAULT 'text',
        is_active BOOLEAN DEFAULT 1
    );
    
    CREATE TABLE IF NOT EXISTS send_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_type VARCHAR(20),
        user_id INTEGER,
        device_id VARCHAR(50),
        template_id INTEGER,
        template_data TEXT,
        scheduled_time DATETIME,
        status VARCHAR(20) DEFAULT 'pending',
        result TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (template_id) REFERENCES message_templates(id)
    );
    
    CREATE TABLE IF NOT EXISTS send_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        openid VARCHAR(64) NOT NULL,
        content TEXT NOT NULL,
        msg_type VARCHAR(20) NOT NULL,
        success BOOLEAN DEFAULT 0,
        error_msg TEXT,
        sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (task_id) REFERENCES send_tasks(id)
    );
    """)
    
    # 插入默认消息模板
    cursor.execute("SELECT COUNT(*) FROM message_templates WHERE name = 'default_alert'")
    if cursor.fetchone()[0] == 0:
        default_template = """【设备告警】
用户：{{nickname}}
设备：{{device_name}} ({{device_id}})
级别：{{alert_level}}
详情：{{alert_detail}}
数值：{{alert_value}}
时间：{{alert_time}}
请及时处理！"""
        
        cursor.execute(
            "INSERT INTO message_templates (name, content, msg_type) VALUES (?, ?, ?)",
            ('default_alert', default_template, 'text')
        )
    
    conn.commit()
    conn.close()
    print("数据库初始化完成")

# 设备告警接口
@app.route('/api/alert', methods=['POST'])
def handle_alert():
    """接收设备告警并发送微信通知"""
    data = request.json
    if not data or 'device_id' not in data:
        return jsonify({'code': 400, 'msg': '缺少device_id'})
    
    device_id = data['device_id']
    alert_data = {
        'level': data.get('level', '警告'),
        'detail': data.get('detail', ''),
        'value': data.get('value', '')
    }
    
    # 发送告警
    results = wechat.send_to_user_by_device(device_id, alert_data)
    
    if results:
        return jsonify({
            'code': 200,
            'msg': f'已向 {len(results)} 个用户发送告警',
            'data': results
        })
    else:
        return jsonify({
            'code': 404,
            'msg': '未找到该设备的绑定用户'
        })

# 手动发送消息接口
@app.route('/api/send', methods=['POST'])
def send_message():
    """手动发送消息给指定用户"""
    data = request.json
    openid = data.get('openid')
    content = data.get('content')
    
    if not openid or not content:
        return jsonify({'code': 400, 'msg': '缺少openid或content'})
    
    result = wechat.send_text_message(openid, content)
    
    if result.get('errcode') == 0:
        return jsonify({'code': 200, 'msg': '发送成功'})
    else:
        return jsonify({'code': 500, 'msg': '发送失败', 'detail': result})

# 同步用户接口
@app.route('/api/sync-users', methods=['POST'])
def sync_users():
    """手动同步关注用户"""
    wechat.sync_followers()
    return jsonify({'code': 200, 'msg': '同步完成'})

# 用户绑定设备接口
@app.route('/api/bind', methods=['POST'])
def bind_device():
    """用户绑定设备（实际需要网页授权获取openid，这里简化）"""
    data = request.json
    openid = data.get('openid')
    device_id = data.get('device_id')
    device_name = data.get('device_name', '')
    
    if not openid or not device_id:
        return jsonify({'code': 400, 'msg': '缺少openid或device_id'})
    
    # 检查用户是否存在
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM users WHERE openid = ?", (openid,))
    user = cursor.fetchone()
    
    if not user:
        # 创建新用户
        cursor.execute(
            "INSERT INTO users (openid, subscribe_time, is_subscribed) VALUES (?, ?, 1)",
            (openid, datetime.now())
        )
        user_id = cursor.lastrowid
    else:
        user_id = user[0]
    
    # 检查是否已绑定
    cursor.execute(
        "SELECT id FROM user_devices WHERE user_id = ? AND device_id = ?",
        (user_id, device_id)
    )
    if cursor.fetchone():
        conn.close()
        return jsonify({'code': 400, 'msg': '设备已绑定'})
    
    # 绑定设备
    cursor.execute(
        "INSERT INTO user_devices (user_id, device_id, device_name) VALUES (?, ?, ?)",
        (user_id, device_id, device_name)
    )
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'code': 200,
        'msg': '绑定成功',
        'data': {'user_id': user_id, 'device_id': device_id}
    })

# 简单的管理后台页面
@app.route('/admin')
def admin_page():
    """简单的管理后台"""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 获取统计数据
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE is_subscribed = 1")
    user_count = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(DISTINCT device_id) as total FROM user_devices WHERE is_active = 1")
    device_count = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM send_logs WHERE date(sent_at) = date('now')")
    today_sent = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as success FROM send_logs WHERE success = 1 AND date(sent_at) = date('now')")
    today_success = cursor.fetchone()['success']
    
    conn.close()
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>微信推送管理后台</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.1.3/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-4">
            <h1>微信推送管理系统</h1>
            
            <div class="row mt-4">
                <div class="col-md-3">
                    <div class="card text-white bg-primary mb-3">
                        <div class="card-body">
                            <h5 class="card-title">关注用户</h5>
                            <p class="card-text display-4">{{ user_count }}</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card text-white bg-success mb-3">
                        <div class="card-body">
                            <h5 class="card-title">设备数量</h5>
                            <p class="card-text display-4">{{ device_count }}</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card text-white bg-info mb-3">
                        <div class="card-body">
                            <h5 class="card-title">今日发送</h5>
                            <p class="card-text display-4">{{ today_sent }}</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card text-white bg-warning mb-3">
                        <div class="card-body">
                            <h5 class="card-title">今日成功</h5>
                            <p class="card-text display-4">{{ today_success }}</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="row mt-4">
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">发送测试消息</div>
                        <div class="card-body">
                            <form id="sendForm">
                                <div class="mb-3">
                                    <label class="form-label">OpenID</label>
                                    <input type="text" class="form-control" id="openid" 
                                           placeholder="用户的OpenID" required>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">消息内容</label>
                                    <textarea class="form-control" id="content" rows="3" 
                                              placeholder="请输入消息内容..." required></textarea>
                                </div>
                                <button type="submit" class="btn btn-primary">发送</button>
                            </form>
                        </div>
                    </div>
                </div>
                
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">系统操作</div>
                        <div class="card-body">
                            <button onclick="syncUsers()" class="btn btn-secondary mb-2">同步用户列表</button>
                            <button onclick="sendAlert()" class="btn btn-danger mb-2">发送测试告警</button>
                            <button onclick="viewLogs()" class="btn btn-info mb-2">查看发送日志</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
        document.getElementById('sendForm').onsubmit = async (e) => {
            e.preventDefault();
            const openid = document.getElementById('openid').value;
            const content = document.getElementById('content').value;
            
            const resp = await fetch('/api/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({openid, content})
            });
            
            const result = await resp.json();
            alert(result.msg);
        };
        
        async function syncUsers() {
            const resp = await fetch('/api/sync-users', {method: 'POST'});
            const result = await resp.json();
            alert(result.msg);
            location.reload();
        }
        
        async function sendAlert() {
            const deviceId = prompt('请输入测试设备ID:', 'device-001');
            if (deviceId) {
                const resp = await fetch('/api/alert', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        device_id: deviceId,
                        level: '测试',
                        detail: '这是一条测试告警消息',
                        value: '100'
                    })
                });
                const result = await resp.json();
                alert(result.msg);
            }
        }
        
        function viewLogs() {
            window.open('/admin/logs');
        }
        </script>
    </body>
    </html>
    """
    
    return render_template_string(html, 
                                 user_count=user_count,
                                 device_count=device_count,
                                 today_sent=today_sent,
                                 today_success=today_success)

# 启动服务
if __name__ == '__main__':
    # 初始化数据库
    init_database()
    
    # 首次启动时同步用户
    wechat.sync_followers()
    
    print("=" * 50)
    print("微信自动推送系统启动成功！")
    print(f"管理后台: http://localhost:5000/admin")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=True)