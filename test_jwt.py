#!/usr/bin/env python3
"""
JWT功能测试脚本
用于测试JWT token的生成和验证功能
"""

import jwt
import secrets
from datetime import datetime, timedelta, timezone

def test_jwt_creation():
    """测试JWT token创建"""
    print("=== JWT Token创建测试 ===")
    
    # 模拟配置
    jwt_secret = secrets.token_hex(32)
    user_access_token = "test_user_access_token_12345"
    expire_minutes = 30
    
    # 创建payload
    now = datetime.now(timezone.utc)
    payload = {
        'user_access_token': user_access_token,
        'exp': now + timedelta(minutes=expire_minutes),
        'iat': now,
        'iss': 'doc-stats-app'
    }
    
    # 生成JWT token
    token = jwt.encode(payload, jwt_secret, algorithm='HS256')
    print(f"✅ JWT token创建成功")
    print(f"Token长度: {len(token)} 字符")
    print(f"Token前缀: {token[:20]}...")
    
    return token, jwt_secret

def test_jwt_verification(token, jwt_secret):
    """测试JWT token验证"""
    print("\n=== JWT Token验证测试 ===")
    
    try:
        # 验证JWT token
        payload = jwt.decode(token, jwt_secret, algorithms=['HS256'])
        user_access_token = payload.get('user_access_token')
        
        print(f"✅ JWT token验证成功")
        print(f"提取的user_access_token: {user_access_token}")
        print(f"发行者: {payload.get('iss')}")
        print(f"过期时间: {datetime.fromtimestamp(payload.get('exp'), tz=timezone.utc)}")
        
        return True
        
    except jwt.ExpiredSignatureError:
        print("❌ JWT token已过期")
        return False
    except jwt.InvalidTokenError as e:
        print(f"❌ JWT token验证失败: {e}")
        return False

def test_jwt_expiration():
    """测试JWT token过期"""
    print("\n=== JWT Token过期测试 ===")
    
    jwt_secret = secrets.token_hex(32)
    user_access_token = "test_user_access_token_12345"
    
    # 创建已过期的payload
    now = datetime.now(timezone.utc)
    payload = {
        'user_access_token': user_access_token,
        'exp': now - timedelta(minutes=1),  # 1分钟前过期
        'iat': now - timedelta(minutes=2),
        'iss': 'doc-stats-app'
    }
    
    # 生成JWT token
    token = jwt.encode(payload, jwt_secret, algorithm='HS256')
    print(f"✅ 过期JWT token创建成功")
    
    # 验证过期token
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=['HS256'])
        print("❌ 过期token验证成功（不应该发生）")
        return False
    except jwt.ExpiredSignatureError:
        print("✅ 正确检测到过期token")
        return True
    except jwt.InvalidTokenError as e:
        print(f"❌ Token验证失败: {e}")
        return False

def main():
    """主测试函数"""
    print("开始JWT功能测试...\n")
    
    # 测试1: JWT token创建
    token, jwt_secret = test_jwt_creation()
    
    # 测试2: JWT token验证
    success1 = test_jwt_verification(token, jwt_secret)
    
    # 测试3: JWT token过期
    success2 = test_jwt_expiration()
    
    # 测试4: 错误密钥验证
    print("\n=== 错误密钥验证测试 ===")
    wrong_secret = secrets.token_hex(32)
    try:
        payload = jwt.decode(token, wrong_secret, algorithms=['HS256'])
        print("❌ 错误密钥验证成功（不应该发生）")
        success3 = False
    except jwt.InvalidTokenError:
        print("✅ 正确拒绝错误密钥")
        success3 = True
    
    # 总结
    print("\n=== 测试总结 ===")
    print(f"JWT token创建: {'✅ 通过' if token else '❌ 失败'}")
    print(f"JWT token验证: {'✅ 通过' if success1 else '❌ 失败'}")
    print(f"JWT token过期: {'✅ 通过' if success2 else '❌ 失败'}")
    print(f"错误密钥验证: {'✅ 通过' if success3 else '❌ 失败'}")
    
    if all([token, success1, success2, success3]):
        print("\n🎉 所有JWT功能测试通过！")
    else:
        print("\n⚠️ 部分JWT功能测试失败，请检查实现。")

if __name__ == "__main__":
    main() 