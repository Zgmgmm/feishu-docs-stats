#!/usr/bin/env python3
"""
ngrok 功能测试脚本
"""

import os
import sys
import time
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def test_ngrok_imports():
    """测试 ngrok 模块导入"""
    try:
        from ngrok_utils import (
            NgrokManager,
            get_ngrok_redirect_uri,
            start_ngrok_tunnel,
            stop_ngrok_tunnel,
            get_tunnel_status
        )
        print("✅ ngrok 模块导入成功")
        return True
    except ImportError as e:
        print(f"❌ ngrok 模块导入失败: {e}")
        return False

def test_ngrok_installation():
    """测试 ngrok 是否已安装"""
    try:
        import ngrok
        print("✅ ngrok Python SDK 已安装")
        return True
    except ImportError:
        print("❌ ngrok Python SDK 未安装，请运行: pip install ngrok")
        return False

def test_ngrok_manager():
    """测试 NgrokManager 类"""
    try:
        from ngrok_utils import NgrokManager
        
        manager = NgrokManager(5000)
        print(f"✅ NgrokManager 创建成功，端口: {manager.port}")
        
        # 测试获取隧道信息
        info = manager.get_tunnel_info()
        print(f"✅ 隧道信息获取成功: {info}")
        
        return True
    except Exception as e:
        print(f"❌ NgrokManager 测试失败: {e}")
        return False

def test_tunnel_operations():
    """测试隧道操作（不实际启动）"""
    try:
        from ngrok_utils import get_tunnel_status
        
        # 获取隧道状态
        status = get_tunnel_status()
        print(f"✅ 隧道状态获取成功: {status}")
        
        return True
    except Exception as e:
        print(f"❌ 隧道操作测试失败: {e}")
        return False

def test_auth_integration():
    """测试与授权模块的集成"""
    try:
        from auth_utils import auth_config, get_redirect_uri
        
        print(f"✅ 授权配置加载成功")
        print(f"   - 使用 ngrok: {auth_config.use_ngrok}")
        print(f"   - App ID: {auth_config.app_id}")
        
        # 测试获取重定向 URI
        redirect_uri = get_redirect_uri()
        print(f"✅ 重定向 URI 获取成功: {redirect_uri}")
        
        return True
    except Exception as e:
        print(f"❌ 授权集成测试失败: {e}")
        return False

def test_flask_routes():
    """测试 Flask 路由（模拟）"""
    try:
        from flask_app import app
        
        with app.test_client() as client:
            # 测试 ngrok 状态路由
            response = client.get('/ngrok/status')
            print(f"✅ ngrok 状态路由测试成功，状态码: {response.status_code}")
            
            # 测试重定向 URI 路由
            response = client.get('/ngrok/redirect-uri')
            print(f"✅ 重定向 URI 路由测试成功，状态码: {response.status_code}")
            
        return True
    except Exception as e:
        print(f"❌ Flask 路由测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("🚀 开始测试 ngrok 功能...\n")
    
    tests = [
        ("ngrok 安装检查", test_ngrok_installation),
        ("ngrok 模块导入", test_ngrok_imports),
        ("NgrokManager 类", test_ngrok_manager),
        ("隧道操作", test_tunnel_operations),
        ("授权集成", test_auth_integration),
        ("Flask 路由", test_flask_routes),
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
        print("🎉 所有测试通过！ngrok 功能已准备就绪。")
        print("\n📝 使用说明:")
        print("1. 访问 http://localhost:5000/ngrok 管理隧道")
        print("2. 启动隧道后复制重定向 URI")
        print("3. 在飞书开放平台配置重定向 URL")
        print("4. 使用公网 URL 测试授权功能")
    else:
        print("⚠️  部分测试失败，请检查配置和依赖。")
        print("\n🔧 故障排除:")
        print("1. 确保已安装 ngrok: pip install ngrok")
        print("2. 检查环境变量配置")
        print("3. 确保网络连接正常")

if __name__ == "__main__":
    main() 