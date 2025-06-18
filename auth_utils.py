"""
飞书授权相关工具函数
包含JWT token管理、飞书OAuth授权等功能
"""

import os
import logging
import secrets
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv
from flask import request, session
from lark_oapi.api.authen.v1 import *
import lark_oapi as lark

# 加载环境变量
load_dotenv()

# 配置日志
logger = logging.getLogger('doc-stats')

# --- 配置类 ---
@dataclass
class AuthConfig:
    """授权相关配置"""
    app_id: str = os.environ.get("FEISHU_APP_ID", "")
    app_secret: str = os.environ.get("FEISHU_APP_SECRET", "")
    user_access_token: str = os.environ.get("FEISHU_USER_ACCESS_TOKEN", "")
    # JWT配置
    jwt_secret: str = os.environ.get("JWT_SECRET", secrets.token_hex(32))
    # ngrok配置
    use_ngrok: bool = os.environ.get("USE_NGROK", "false").lower() == "true"

# 创建配置实例
auth_config = AuthConfig()

# 创建飞书客户端配置
def get_feishu_client() -> lark.Client:
    """获取飞书客户端实例"""
    client = lark.Client.builder() \
        .app_id(auth_config.app_id) \
        .app_secret(auth_config.app_secret) \
        .log_level(lark.LogLevel.DEBUG) \
        .build()
    return client

# --- JWT相关函数 ---
def create_jwt_token(user_access_token: str, expires_in: int) -> str:
    """创建JWT token
    
    Args:
        user_access_token: 飞书用户访问令牌
        
    Returns:
        JWT token字符串
    """
    expires_in_minutes = expires_in//60
    now = datetime.now(timezone.utc)
    payload = {
        'user_access_token': user_access_token,
        'exp': now + timedelta(minutes=expires_in_minutes),
        'iat': now,
        'iss': 'doc-stats-app'
    }
    
    token = jwt.encode(payload, auth_config.jwt_secret, algorithm='HS256')
    logger.info(f"创建JWT token，过期时间: {expires_in_minutes}分钟")
    return token

def verify_jwt_token(token: str) -> Optional[str]:
    """验证JWT token并提取user_access_token
    
    Args:
        token: JWT token字符串
        
    Returns:
        user_access_token，验证失败则返回None
    """
    try:
        payload = jwt.decode(token, auth_config.jwt_secret, algorithms=['HS256'])
        user_access_token = payload.get('user_access_token')
        
        if not user_access_token:
            logger.error("JWT token中缺少user_access_token")
            return None
    
        logger.info("JWT token验证成功")
        return user_access_token
        
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.error(f"JWT token验证失败: {e}")
        return None

def get_redirect_uri() -> str:
    """获取重定向URI
    
    Returns:
        重定向URI
    """
    if auth_config.use_ngrok:
        try:
            from ngrok_utils import get_ngrok_redirect_uri
            ngrok_uri = get_ngrok_redirect_uri()
            if ngrok_uri:
                logger.info(f"使用 ngrok 重定向URI: {ngrok_uri}")
                return ngrok_uri
        except ImportError:
            logger.warning("ngrok_utils 模块未找到，使用默认重定向URI")
        except Exception as e:
            logger.error(f"获取 ngrok 重定向URI失败: {e}")
    
    # 默认重定向URI
    if request.host_url:
        default_uri = request.host_url.rstrip('/') + "/auth/callback"
    else:
        default_uri = "https://zgmgmm.pythonanywhere.com/auth/callback"
    
    logger.info(f"使用默认重定向URI: {default_uri}")
    return default_uri

def get_authorization_url() -> str:
    """获取飞书授权URL
    
    Returns:
        授权URL
    """
    # 飞书授权URL
    base_url = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
    
    # 获取重定向URI
    redirect_uri = get_redirect_uri()
    
    scope = " ".join(["drive:drive.metadata:readonly","wiki:wiki:readonly", "wiki:node:retrieve"])
    # 授权参数
    params = {
        "app_id": auth_config.app_id,
        "redirect_uri": redirect_uri,
        "state": secrets.token_urlsafe(32),  # 防止CSRF攻击
        "response_type": "code",
        "scope": scope
    }
    
    # 构建授权URL
    param_str = "&".join([f"{k}={v}" for k, v in params.items()])
    auth_url = f"{base_url}?{param_str}"
    
    # 保存state到session
    session['auth_state'] = params['state']
    
    logger.info(f"生成授权URL: {auth_url}")
    return auth_url

def exchange_code_for_token(authorization_code: str) -> tuple[str,int]:
    """使用授权码换取user_access_token
    
    Args:
        authorization_code: 飞书授权回调返回的授权码
        
    Returns:
        user_access_token，失败则返回None
    """
    try:
        # 创建飞书客户端
        client = get_feishu_client()
        
        # 创建请求对象
        request = CreateAccessTokenRequest.builder() \
            .request_body(CreateAccessTokenRequestBody.builder()
                .grant_type("authorization_code")
                .code(authorization_code)
                .build()) \
            .build()
        
        # 发送请求
        response = client.authen.v1.access_token.create(request)
        
        # 检查响应
        if response.code == 0:
            data = response.data
            user_access_token = data.access_token
            expires_in = data.expires_in
            
            if user_access_token:
                logger.info("成功获取user_access_token")
                return user_access_token, expires_in
            else:
                logger.error("响应中缺少access_token")
                return "", 0
        else:
            logger.error(f"获取user_access_token失败: {response.msg}")
            return "", 0
            
    except Exception as e:
        logger.error(f"换取user_access_token时发生异常: {e}")
        return "", 0

def get_user_access_token() -> Optional[str]:
    """获取当前用户的access_token
    
    Returns:
        user_access_token，如果没有则返回None
    """
    # 从请求头中获取JWT token
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        jwt_token = auth_header[7:]  # 移除 'Bearer ' 前缀
        user_access_token = verify_jwt_token(jwt_token)
        if user_access_token:
            return user_access_token
    
    # 如果没有JWT token，使用配置中的默认token
    if auth_config.user_access_token:
        return auth_config.user_access_token
    
    return None

def validate_auth_config() -> bool:
    """验证授权配置是否有效
    
    Returns:
        配置是否有效
    """
    if not auth_config.app_id or auth_config.app_id == "YOUR_APP_ID" or not auth_config.app_secret or auth_config.app_secret == "YOUR_APP_SECRET":
        logger.error("错误：请在配置中设置 app_id 和 app_secret。")
        return False
        
    return True

def get_user_info(user_access_token: str) -> Optional[dict]:
    """获取用户信息（名称和头像）
    
    Args:
        user_access_token: 飞书用户访问令牌
        
    Returns:
        包含用户信息的字典，失败则返回None
    """
    try:
        # 创建飞书客户端
        client = get_feishu_client()

        # 构造请求对象
        options = lark.RequestOption.builder().user_access_token(user_access_token).build()
        request: GetUserInfoRequest = GetUserInfoRequest.builder() \
            .build()

        # 发起请求
        response: GetUserInfoResponse = client.authen.v1.user_info.get(request, options)

        # 处理失败返回
        if not response.success():
            lark.logger.error(
                f"client.authen.v1.user_info.get failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}, resp: \n{json.dumps(json.loads(response.raw.content), indent=4, ensure_ascii=False)}")
            return

        # 处理业务结果
        lark.logger.info(lark.JSON.marshal(response.data, indent=4))
        return vars(response.data)
    except Exception as e:
        logger.error(f"获取用户信息时发生异常: {e}")
        return None

def get_current_user_info() -> Optional[dict]:
    """获取当前登录用户的信息
    
    Returns:
        包含用户信息的字典，失败则返回None
    """
    # 从请求头或参数中获取JWT token
    auth_header = request.headers.get('Authorization')
    jwt_token = None
    
    if auth_header and auth_header.startswith('Bearer '):
        jwt_token = auth_header[7:]
    else:
        jwt_token = request.args.get('token')
    
    if not jwt_token:
        logger.warning("未找到JWT token")
        return None
    
    # 验证JWT token并获取user_access_token
    user_access_token = verify_jwt_token(jwt_token)
    if not user_access_token:
        logger.warning("JWT token验证失败")
        return None
    
    # 获取用户信息
    return get_user_info(user_access_token) 