#!/usr/bin/env python3
"""
飞书授权功能测试脚本
"""

import os
import sys
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def test_auth_imports():
    """测试授权模块导入"""
    try:
        from auth_utils import (
            AuthConfig, 
            create_jwt_token, 
            verify_jwt_token, 
            get_authorization_url,
            exchange_code_for_token,
            get_user_access_token,
            validate_auth_config,
            get_feishu_client
        )
        print("✅ 所有授权模块导入成功")
        return True
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        return False

def test_auth_config():
    """测试授权配置"""
    try:
        from auth_utils import auth_config
        
        print(f"App ID: {auth_config.app_id}")
        print(f"App Secret: {'*' * len(auth_config.app_secret) if auth_config.app_secret else '未设置'}")
        print(f"JWT Secret: {'*' * len(auth_config.jwt_secret) if auth_config.jwt_secret else '未设置'}")
        print(f"JWT 过期时间: {auth_config.jwt_expire_minutes} 分钟")
        
        if auth_config.app_id and auth_config.app_id != "YOUR_APP_ID":
            print("✅ 授权配置有效")
            return True
        else:
            print("❌ 授权配置无效，请检查环境变量")
            return False
            
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")
        return False

def test_jwt_functions():
    """测试JWT相关函数"""
    try:
        from auth_utils import create_jwt_token, verify_jwt_token
        
        # 测试创建JWT token
        test_token = "test_user_access_token_123"
        jwt_token = create_jwt_token(test_token)
        print(f"✅ JWT token 创建成功: {jwt_token[:20]}...")
        
        # 测试验证JWT token
        verified_token = verify_jwt_token(jwt_token)
        if verified_token == test_token:
            print("✅ JWT token 验证成功")
            return True
        else:
            print("❌ JWT token 验证失败")
            return False
            
    except Exception as e:
        print(f"❌ JWT 测试失败: {e}")
        return False

def test_feishu_client():
    """测试飞书客户端创建"""
    try:
        from auth_utils import get_feishu_client, auth_config
        
        if not auth_config.app_id or auth_config.app_id == "YOUR_APP_ID":
            print("⚠️  跳过飞书客户端测试（缺少有效配置）")
            return True
            
        client = get_feishu_client()
        print("✅ 飞书客户端创建成功")
        return True
        
    except Exception as e:
        print(f"❌ 飞书客户端测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("🚀 开始测试飞书授权功能...\n")
    
    tests = [
        ("模块导入", test_auth_imports),
        ("授权配置", test_auth_config),
        ("JWT功能", test_jwt_functions),
        ("飞书客户端", test_feishu_client),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"📋 测试: {test_name}")
        if test_func():
            passed += 1
        print()
    
    print(f"📊 测试结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过！授权功能已准备就绪。")
    else:
        print("⚠️  部分测试失败，请检查配置和依赖。")

if __name__ == "__main__":
    main() 