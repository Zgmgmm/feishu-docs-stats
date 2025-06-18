"""
文档统计相关工具函数
包含文档解析、统计、树结构等功能
"""

import logging
import os
import secrets

import lark_oapi as lark
from dotenv import load_dotenv
from types import SimpleNamespace

# 加载环境变量
load_dotenv()

config_dict = dict(
    app_id=os.environ.get("FEISHU_APP_ID", ""),
    app_secret=os.environ.get("FEISHU_APP_SECRET", ""),
    jwt_secret=os.environ.get("JWT_SECRET", secrets.token_hex(32)),
    use_ngrok=os.environ.get("USE_NGROK", "false").lower() == "true",
)
config = SimpleNamespace(**config_dict)

# 配置日志
logger = logging.getLogger("doc-stats")

app_id = os.environ.get("FEISHU_APP_ID", "")
app_secret = os.environ.get("FEISHU_APP_SECRET", "")

jwt_secret: str = os.environ.get("JWT_SECRET", secrets.token_hex(32))

use_ngrok: bool = os.environ.get("USE_NGROK", "false").lower() == "true"

# 创建Lark客户端
client = (
    lark.Client.builder()
    .app_id(app_id)
    .app_secret(app_secret)
    .log_level(lark.LogLevel.INFO)
    .enable_set_token(True)
    .build()
)
