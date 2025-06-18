"""
ngrok 工具模块
用于管理 ngrok 隧道，生成公网可访问的 redirect_uri
"""

from typing import Any, Dict, Optional

from ngrok import ngrok

from init import logger


class NgrokManager:
    """ngrok 隧道管理器"""

    def __init__(self, port: int = 5000):
        self.port = port
        self.tunnel = None
        self.public_url = None

    def start_tunnel(self) -> Optional[str]:
        """启动 ngrok 隧道

        Returns:
            公网URL，失败则返回None
        """
        try:
            # 检查是否已有隧道
            if self.tunnel:
                logger.info("ngrok 隧道已存在")
                return self.public_url

            # 启动隧道
            logger.info(f"启动 ngrok 隧道，端口: {self.port}")
            self.tunnel = ngrok.connect(self.port)

            # 获取公网URL
            self.public_url = self.tunnel.public_url

            # 确保使用 HTTPS
            if not self.public_url.startswith("https://"):
                self.public_url = self.public_url.replace("http://", "https://")

            logger.info(f"ngrok 隧道启动成功: {self.public_url}")
            return self.public_url

        except Exception as e:
            logger.error(f"启动 ngrok 隧道失败: {e}")
            return None

    def stop_tunnel(self):
        """停止 ngrok 隧道"""
        try:
            if self.tunnel:
                ngrok.disconnect(self.tunnel.public_url)
                self.tunnel = None
                self.public_url = None
                logger.info("ngrok 隧道已停止")
        except Exception as e:
            logger.error(f"停止 ngrok 隧道失败: {e}")

    def get_redirect_uri(self) -> Optional[str]:
        """获取重定向URI

        Returns:
            完整的重定向URI
        """
        if not self.public_url:
            self.start_tunnel()

        if self.public_url:
            return f"{self.public_url}/auth/callback"
        return None

    def get_tunnel_info(self) -> Dict[str, Any]:
        """获取隧道信息

        Returns:
            隧道信息字典
        """
        return {
            "public_url": self.public_url,
            "redirect_uri": self.get_redirect_uri(),
            "port": self.port,
            "is_active": self.tunnel is not None,
        }


# 全局 ngrok 管理器实例
ngrok_manager = NgrokManager()


def get_ngrok_redirect_uri() -> Optional[str]:
    """获取 ngrok 重定向 URI

    Returns:
        重定向URI，失败则返回None
    """
    return ngrok_manager.get_redirect_uri()


def start_ngrok_tunnel(port: int = 5000) -> Optional[str]:
    """启动 ngrok 隧道

    Args:
        port: 本地端口号

    Returns:
        公网URL，失败则返回None
    """
    global ngrok_manager
    ngrok_manager = NgrokManager(port)
    return ngrok_manager.start_tunnel()


def stop_ngrok_tunnel():
    """停止 ngrok 隧道"""
    ngrok_manager.stop_tunnel()


def get_tunnel_status() -> Dict[str, Any]:
    """获取隧道状态

    Returns:
        隧道状态信息
    """
    return ngrok_manager.get_tunnel_info()
