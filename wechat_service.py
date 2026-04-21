# wechat_service.py
import requests
import json
import time
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WeChatService:
    def __init__(self, appid: str, secret: str, db_path: str = 'wechat_bot.db'):
        self.appid = appid
        self.secret = secret
        self.db_path = db_path
        self.access_token = None
        self.token_expire_time = 0
        
    def _get_db_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)
    
    def _execute_query(self, query: str, params: tuple = (), fetch_one: bool = False):
        """执行SQL查询"""
        conn = self._get_db_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        
        if fetch_one:
            result = cursor.fetchone()
        else:
            result = cursor.fetchall()
        
        conn.commit()
        conn.close()
        return result
    
    def get_access_token(self, force_refresh: bool = False) -> Optional[str]:
        """获取access_token（带缓存）"""
        # 如果token有效且不强制刷新，直接返回
        if not force_refresh and self.access_token and time.time() < self.token_expire_time:
            return self.access_token
            
        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={self.appid}&secret={self.secret}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            if 'access_token' in data:
                self.access_token = data['access_token']
                self.token_expire_time = time.time() + data.get('expires_in', 7200) - 300  # 提前5分钟过期
                logger.info(f"获取access_token成功: {self.access_token[:20]}...")
                return self.access_token
            else:
                logger.error(f"获取access_token失败: {data}")
                return None
        except Exception as e:
            logger.error(f"获取access_token异常: {e}")
            return None
    
    def send_text_message(self, openid: str, content: str) -> Dict:
        """发送文本消息（客服消息接口）"""
        token = self.get_access_token()
        if not token:
            return {'errcode': -1, 'errmsg': '获取token失败'}
            
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
        data = {
            "touser": openid,
            "msgtype": "text",
            "text": {"content": content}
        }
        
        try:
            resp = requests.post(url, 
                                data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
                                timeout=10)
            result = resp.json()
            
            # 记录发送日志
            self._log_message_send(openid, content, 'text', result.get('errcode') == 0, result)
            
            return result
        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            return {'errcode': -2, 'errmsg': str(e)}
    
    def send_template_message(self, openid: str, template_id: str, 
                            data: Dict, url: str = None, mini_program: Dict = None) -> Dict:
        """发送模板消息（仅服务号可用）"""
        token = self.get_access_token()
        if not token:
            return {'errcode': -1, 'errmsg': '获取token失败'}
            
        post_data = {
            "touser": openid,
            "template_id": template_id,
            "data": data
        }
        
        if url:
            post_data["url"] = url
        if mini_program:
            post_data["miniprogram"] = mini_program
            
        api_url = f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={token}"
        
        try:
            resp = requests.post(api_url,
                                data=json.dumps(post_data, ensure_ascii=False).encode('utf-8'),
                                timeout=10)
            return resp.json()
        except Exception as e:
            logger.error(f"发送模板消息异常: {e}")
            return {'errcode': -2, 'errmsg': str(e)}
    
    def get_user_list(self, next_openid: str = None) -> Dict:
        """获取关注用户列表"""
        token = self.get_access_token()
        if not token:
            return {'errcode': -1, 'errmsg': '获取token失败'}
            
        url = f"https://api.weixin.qq.com/cgi-bin/user/get?access_token={token}"
        if next_openid:
            url += f"&next_openid={next_openid}"
            
        try:
            resp = requests.get(url, timeout=10)
            return resp.json()
        except Exception as e:
            logger.error(f"获取用户列表异常: {e}")
            return {'errcode': -2, 'errmsg': str(e)}
    
    def sync_followers(self):
        """同步关注者到本地数据库"""
        logger.info("开始同步关注用户...")
        result = self.get_user_list()
        
        if 'data' in result and 'openid' in result['data']:
            openids = result['data']['openid']
            total = result.get('total', 0)
            logger.info(f"从微信获取到 {total} 个关注用户")
            
            for openid in openids:
                # 检查用户是否已在数据库
                check_sql = "SELECT id FROM users WHERE openid = ?"
                existing = self._execute_query(check_sql, (openid,), fetch_one=True)
                
                if not existing:
                    # 插入新用户
                    insert_sql = """
                    INSERT INTO users (openid, subscribe_time, is_subscribed) 
                    VALUES (?, ?, 1)
                    """
                    self._execute_query(insert_sql, (openid, datetime.now()))
                    logger.info(f"新增用户: {openid}")
                else:
                    # 更新订阅状态
                    update_sql = "UPDATE users SET is_subscribed = 1 WHERE openid = ?"
                    self._execute_query(update_sql, (openid,))
            
            # 标记已取消关注的用户
            all_db_users = self._execute_query("SELECT openid FROM users WHERE is_subscribed = 1")
            db_openids = {row[0] for row in all_db_users}
            unsubscribed = db_openids - set(openids)
            
            for openid in unsubscribed:
                update_sql = "UPDATE users SET is_subscribed = 0 WHERE openid = ?"
                self._execute_query(update_sql, (openid,))
                logger.info(f"用户取消关注: {openid}")
                
            logger.info("同步完成")
        else:
            logger.error(f"获取用户列表失败: {result}")
    
    def send_to_user_by_device(self, device_id: str, alert_data: Dict, 
                             template_name: str = "default_alert") -> List[Dict]:
        """根据设备ID向绑定用户发送告警"""
        # 1. 查询哪些用户绑定了此设备
        query = """
        SELECT u.openid, u.nickname, ud.device_name 
        FROM users u
        JOIN user_devices ud ON u.id = ud.user_id
        WHERE ud.device_id = ? AND ud.is_active = 1 AND u.is_subscribed = 1
        """
        users = self._execute_query(query, (device_id,))
        
        if not users:
            logger.warning(f"设备 {device_id} 未绑定任何有效用户")
            return []
        
        # 2. 获取消息模板
        template_query = "SELECT content, msg_type FROM message_templates WHERE name = ? AND is_active = 1"
        template = self._execute_query(template_query, (template_name,), fetch_one=True)
        
        if not template:
            logger.error(f"模板 {template_name} 不存在或未启用")
            return []
        
        template_content, msg_type = template
        results = []
        
        # 3. 为每个用户发送个性化消息
        for user in users:
            openid, nickname, device_name = user
            
            # 替换模板变量
            message = template_content
            variables = {
                '{{nickname}}': nickname or '用户',
                '{{device_id}}': device_id,
                '{{device_name}}': device_name or device_id,
                '{{alert_time}}': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                '{{alert_level}}': alert_data.get('level', '警告'),
                '{{alert_detail}}': alert_data.get('detail', ''),
                '{{alert_value}}': alert_data.get('value', ''),
            }
            
            for var, val in variables.items():
                message = message.replace(var, str(val))
            
            # 发送消息
            if msg_type == 'text':
                result = self.send_text_message(openid, message)
            else:
                # 其他消息类型处理
                result = {'errcode': -3, 'errmsg': f'不支持的msg_type: {msg_type}'}
            
            results.append({
                'openid': openid,
                'nickname': nickname,
                'device_id': device_id,
                'result': result
            })
            
            # 记录发送任务
            self._record_send_task(openid, device_id, template_name, 
                                 json.dumps(alert_data, ensure_ascii=False))
        
        return results
    
    def _log_message_send(self, openid: str, content: str, msg_type: str, 
                         success: bool, result: Dict):
        """记录消息发送日志"""
        insert_sql = """
        INSERT INTO send_logs (openid, content, msg_type, success, error_msg, sent_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        error_msg = json.dumps(result, ensure_ascii=False) if not success else None
        self._execute_query(insert_sql, (openid, content, msg_type, 
                                       1 if success else 0, error_msg, datetime.now()))
    
    def _record_send_task(self, openid: str, device_id: str, 
                         template_name: str, template_data: str):
        """记录发送任务"""
        # 获取user_id
        user_query = "SELECT id FROM users WHERE openid = ?"
        user_result = self._execute_query(user_query, (openid,), fetch_one=True)
        
        if user_result:
            user_id = user_result[0]
            # 获取template_id
            template_query = "SELECT id FROM message_templates WHERE name = ?"
            template_result = self._execute_query(template_query, (template_name,), fetch_one=True)
            template_id = template_result[0] if template_result else None
            
            insert_sql = """
            INSERT INTO send_tasks (task_type, user_id, device_id, template_id, 
                                  template_data, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            self._execute_query(insert_sql, ('alert', user_id, device_id, 
                                           template_id, template_data, 'success', datetime.now()))