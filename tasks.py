# tasks.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import sqlite3
from wechat_service import WeChatService
import config

scheduler = BackgroundScheduler()
wechat = WeChatService(config.WECHAT_APPID, config.WECHAT_APPSECRET, config.DATABASE_PATH)

def refresh_access_token():
    """定时刷新access_token"""
    print(f"[{datetime.now()}] 刷新access_token...")
    wechat.get_access_token(force_refresh=True)

def send_scheduled_messages():
    """检查并发送定时消息"""
    print(f"[{datetime.now()}] 检查定时任务...")
    
    conn = sqlite3.connect(config.DATABASE_PATH)
    cursor = conn.cursor()
    
    # 查找待发送的定时任务
    cursor.execute("""
    SELECT st.id, u.openid, mt.content, st.template_data
    FROM send_tasks st
    JOIN users u ON st.user_id = u.id
    JOIN message_templates mt ON st.template_id = mt.id
    WHERE st.task_type = 'schedule' 
    AND st.status = 'pending'
    AND st.scheduled_time <= datetime('now')
    AND u.is_subscribed = 1
    LIMIT 10
    """)
    
    tasks = cursor.fetchall()
    
    for task_id, openid, template_content, template_data_json in tasks:
        try:
            # 更新任务状态为发送中
            cursor.execute("UPDATE send_tasks SET status = 'sending' WHERE id = ?", (task_id,))
            conn.commit()
            
            # 发送消息
            result = wechat.send_text_message(openid, template_content)
            
            # 更新任务状态
            status = 'success' if result.get('errcode') == 0 else 'failed'
            cursor.execute(
                "UPDATE send_tasks SET status = ?, result = ? WHERE id = ?",
                (status, str(result), task_id)
            )
            conn.commit()
            
            print(f"发送定时任务 {task_id} 到 {openid[:10]}... {status}")
            
        except Exception as e:
            print(f"发送定时任务 {task_id} 失败: {e}")
            cursor.execute(
                "UPDATE send_tasks SET status = 'failed', result = ? WHERE id = ?",
                (str(e), task_id)
            )
            conn.commit()
    
    conn.close()

def add_daily_report_task(hour=9, minute=0):
    """添加每日报表任务示例"""
    conn = sqlite3.connect(config.DATABASE_PATH)
    cursor = conn.cursor()
    
    # 获取所有用户
    cursor.execute("SELECT id FROM users WHERE is_subscribed = 1")
    users = cursor.fetchall()
    
    for (user_id,) in users:
        # 计算明天的发送时间
        from datetime import datetime, timedelta
        scheduled_time = (datetime.now() + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        
        cursor.execute("""
        INSERT INTO send_tasks (task_type, user_id, template_id, scheduled_time, status)
        SELECT 'schedule', ?, id, ?, 'pending'
        FROM message_templates WHERE name = 'daily_report' AND is_active = 1
        """, (user_id, scheduled_time))
    
    conn.commit()
    conn.close()
    print(f"已为 {len(users)} 个用户添加每日 {hour}:{minute} 的报表任务")

def start_scheduler():
    """启动定时任务调度器"""
    # 添加定时任务
    scheduler.add_job(
        refresh_access_token,
        'interval',
        seconds=7000,  # 每7000秒刷新一次
        id='refresh_token'
    )
    
    scheduler.add_job(
        send_scheduled_messages,
        'interval',
        seconds=60,  # 每分钟检查一次
        id='check_scheduled'
    )
    
    # 示例：每天9点发送日报
    scheduler.add_job(
        add_daily_report_task,
        CronTrigger(hour=0, minute=1),  # 每天00:01准备第二天的任务
        id='prepare_daily_report'
    )
    
    scheduler.start()
    print("定时任务调度器已启动")