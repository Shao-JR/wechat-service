# config.py
import os
from datetime import timedelta

class Config:
    # 微信配置
    WECHAT_APPID = os.getenv('WECHAT_APPID', '你的AppID')
    WECHAT_APPSECRET = os.getenv('WECHAT_APPSECRET', '你的AppSecret')
    
    # 服务器配置
    SERVER_URL = os.getenv('SERVER_URL', 'https://your-domain.com')  # 你的服务器域名
    TOKEN = os.getenv('WECHAT_TOKEN', 'your_token_here')  # 公众号后台配置的Token
    
    # 数据库配置
    DATABASE_PATH = os.getenv('DATABASE_PATH', 'wechat_bot.db')
    
    # Redis配置（可选，用于缓存access_token）
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)
    
    # 定时任务配置
    SCHEDULER_API_ENABLED = True
    JOBS = [
        {
            'id': 'refresh_token',
            'func': 'app.tasks:refresh_access_token',
            'trigger': 'interval',
            'seconds': 7000  # 微信token 7200秒过期，提前刷新
        },
        {
            'id': 'send_scheduled',
            'func': 'app.tasks:send_scheduled_messages',
            'trigger': 'interval',
            'seconds': 60  # 每分钟检查一次定时任务
        }
    ]