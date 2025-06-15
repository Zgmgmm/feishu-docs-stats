#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档统计分析系统启动脚本
"""

import os
import sys
from flask_app import app

def main():
    """主函数"""
    print("🚀 启动文档统计分析系统...")
    print("📊 访问地址: http://localhost:5000")
    print("⚠️  请确保已正确配置 .env 文件")
    print("=" * 50)
    
    try:
        app.run(debug=True, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\n👋 应用已停止")
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 