#!/usr/bin/env python3
"""
测试飞书用户信息API调用
"""

import os
from dotenv import load_dotenv
from lark_oapi.api.authen.v1 import *
import lark_oapi as lark

# 加载环境变量
load_dotenv()

def test_get_user_info():
    """测试获取用户信息"""
    
    # 配置
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    user_access_token = os.environ.get("FEISHU_USER_ACCESS_TOKEN", "")
    
    if not user_access_token:
        print("请设置 FEISHU_USER_ACCESS_TOKEN 环境变量")
        return
    
    try:
        # 创建飞书客户端
        client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark.LogLevel.DEBUG) \
            .build()
        
        # 创建请求对象
        request = GetAccessTokenRequest.builder() \
            .build()
        
        # 设置用户访问令牌
        client.authen.v1.access_token.set_user_access_token(user_access_token)
        
        # 发送请求
        response = client.authen.v1.access_token.get(request)
        
        print(f"响应状态码: {response.code}")
        print(f"响应消息: {response.msg}")
        
        if response.code == 0:
            data = response.data
            print(f"用户ID: {data.user_id}")
            print(f"用户名称: {data.name}")
            print(f"头像URL: {data.avatar_url}")
            print(f"邮箱: {getattr(data, 'email', 'N/A')}")
            print(f"手机: {getattr(data, 'mobile', 'N/A')}")
        else:
            print("获取用户信息失败")
            
    except Exception as e:
        print(f"发生异常: {e}")

if __name__ == "__main__":
    test_get_user_info() 