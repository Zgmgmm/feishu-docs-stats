import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from auth_utils import *
from doc_stats_utils import *
# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('doc-stats')

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # 请替换为安全的密钥

# ================= 路由部分 =================

@app.route('/auth')
def auth():
    auth_url = get_authorization_url()
    return redirect(auth_url)

@app.route('/auth/callback')
def auth_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    if state != session.get('auth_state'):
        return jsonify({"error": "Invalid state parameter"}), 400
    if not code:
        return jsonify({"error": "Missing authorization code"}), 400
    user_access_token = exchange_code_for_token(code)
    if not user_access_token:
        return jsonify({"error": "Failed to get access token"}), 500
    jwt_token = create_jwt_token(user_access_token)
    session.pop('auth_state', None)
    return redirect(url_for('index', token=jwt_token))

@app.route('/auth/status')
def auth_status():
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        jwt_token = auth_header[7:]
        user_access_token = verify_jwt_token(jwt_token)
        if user_access_token:
            return jsonify({
                "authorized": True,
                "has_token": True,
                "expires_in": auth_config.jwt_expire_minutes * 60
            })
    jwt_token = request.args.get('token')
    if jwt_token:
        user_access_token = verify_jwt_token(jwt_token)
        if user_access_token:
            return jsonify({
                "authorized": True,
                "has_token": True,
                "token": jwt_token,
                "expires_in": auth_config.jwt_expire_minutes * 60
            })
    return jsonify({
        "authorized": False,
        "has_token": False
    })

@app.route('/auth/logout')
def auth_logout():
    return jsonify({"message": "已退出授权", "success": True})

@app.route('/auth/user-info')
def get_user_info_route():
    """获取当前登录用户的信息"""
    user_info = get_current_user_info()
    
    if user_info:
        return jsonify({
            "success": True,
            "user_info": user_info
        })
    else:
        return jsonify({
            "success": False,
            "message": "获取用户信息失败，请检查授权状态"
        }), 401

# ngrok 相关路由
@app.route('/ngrok/start')
def start_ngrok():
    """启动 ngrok 隧道"""
    try:
        from ngrok_utils import start_ngrok_tunnel
        port = request.args.get('port', 5001, type=int)
        public_url = start_ngrok_tunnel(port)
        
        if public_url:
            return jsonify({
                "success": True,
                "public_url": public_url,
                "redirect_uri": f"{public_url}/auth/callback",
                "message": "ngrok 隧道启动成功"
            })
        else:
            return jsonify({
                "success": False,
                "message": "启动 ngrok 隧道失败"
            }), 500
            
    except ImportError:
        return jsonify({
            "success": False,
            "message": "ngrok 模块未安装，请运行: pip install ngrok"
        }), 500
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"启动 ngrok 隧道时发生错误: {str(e)}"
        }), 500

@app.route('/ngrok/stop')
def stop_ngrok():
    """停止 ngrok 隧道"""
    try:
        from ngrok_utils import stop_ngrok_tunnel
        stop_ngrok_tunnel()
        return jsonify({
            "success": True,
            "message": "ngrok 隧道已停止"
        })
    except ImportError:
        return jsonify({
            "success": False,
            "message": "ngrok 模块未安装"
        }), 500
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"停止 ngrok 隧道时发生错误: {str(e)}"
        }), 500

@app.route('/ngrok/status')
def ngrok_status():
    """获取 ngrok 隧道状态"""
    try:
        from ngrok_utils import get_tunnel_status
        status = get_tunnel_status()
        return jsonify({
            "success": True,
            "status": status
        })
    except ImportError:
        return jsonify({
            "success": False,
            "message": "ngrok 模块未安装"
        }), 500
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"获取 ngrok 状态时发生错误: {str(e)}"
        }), 500

@app.route('/ngrok/redirect-uri')
def get_ngrok_redirect_uri():
    """获取 ngrok 重定向 URI"""
    try:
        from ngrok_utils import get_ngrok_redirect_uri
        redirect_uri = get_ngrok_redirect_uri()
        
        if redirect_uri:
            return jsonify({
                "success": True,
                "redirect_uri": redirect_uri,
                "message": "获取重定向 URI 成功"
            })
        else:
            return jsonify({
                "success": False,
                "message": "ngrok 隧道未启动或获取重定向 URI 失败"
            }), 404
            
    except ImportError:
        return jsonify({
            "success": False,
            "message": "ngrok 模块未安装"
        }), 500
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"获取重定向 URI 时发生错误: {str(e)}"
        }), 500

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ngrok')
def ngrok_management():
    """ngrok 管理页面"""
    return render_template('ngrok.html')

@app.route('/test')
def test():
    return render_template('test.html')

@app.route('/stats', methods=['POST','GET'])
def handle_stats_request():
    user_token = get_user_access_token()
    if not user_token:
        return jsonify({"error": "未授权，请先进行飞书授权", "need_auth": True}), 401
    data = request.get_json()
    if not data or 'urls' not in data:
        return jsonify({"error": "Missing 'urls' in request body"}), 400
    input_urls = data['urls']
    if not isinstance(input_urls, list):
        return jsonify({"error": "'urls' must be a list"}), 400
    
    # 默认使用异步处理
    try:
        import asyncio
        from doc_stats_utils import get_document_statistics_async
        from stats import get_document_statistics_async_v2
        
        # 创建新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            start_time = asyncio.get_event_loop().time()
            doc_stats, processed_wikis = loop.run_until_complete(
                # get_document_statistics_async(input_urls, user_token)
                get_document_statistics_async_v2(input_urls, user_token)
            )
            end_time = asyncio.get_event_loop().time()
            
            processing_time = end_time - start_time
            
        finally:
            loop.close()
            
    except Exception as e:
        logger.exception(f"异步处理文档统计时发生异常: {e}")
        return jsonify({"error": f"处理失败: {str(e)}"}), 500
    
    # 计算性能指标
    performance = {
        "total_urls": len(input_urls),
        "processed_docs": len(doc_stats),
        "processing_time_seconds": round(processing_time, 2),
        "docs_per_second": round(len(doc_stats) / processing_time, 2) if processing_time > 0 else 0
    }
    
    response_data = {
        "statistics": doc_stats,
        "processed_wikis": processed_wikis,
        "performance": performance,
        "async_mode": True
    }
    return jsonify(response_data)

@app.route('/stats/batch', methods=['POST'])
def handle_batch_stats_request():
    """批量处理文档统计信息的优化接口
    
    支持：
    - 异步并发处理
    - 批量API调用
    - 进度跟踪
    """
    user_token = get_user_access_token()
    if not user_token:
        return jsonify({"error": "未授权，请先进行飞书授权", "need_auth": True}), 401
    
    data = request.get_json()
    if not data or 'urls' not in data:
        return jsonify({"error": "Missing 'urls' in request body"}), 400
    
    input_urls = data['urls']
    if not isinstance(input_urls, list):
        return jsonify({"error": "'urls' must be a list"}), 400
    
    # 获取配置参数
    max_concurrent = data.get('max_concurrent', 10)  # 最大并发数
    batch_size = data.get('batch_size', 20)  # 批量大小
    enable_progress = data.get('progress', False)  # 是否启用进度跟踪
    
    try:
        import asyncio
        from doc_stats_utils import get_document_statistics_async, MAX_CONCURRENT_REQUESTS, BATCH_SIZE
        
        # 临时更新配置
        original_max_concurrent = MAX_CONCURRENT_REQUESTS
        original_batch_size = BATCH_SIZE
        
        # 动态更新配置
        import doc_stats_utils
        doc_stats_utils.MAX_CONCURRENT_REQUESTS = max_concurrent
        doc_stats_utils.BATCH_SIZE = batch_size
        
        # 创建新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            start_time = asyncio.get_event_loop().time()
            doc_stats, processed_wikis = loop.run_until_complete(
                get_document_statistics_async(input_urls, user_token)
            )
            end_time = asyncio.get_event_loop().time()
            
            processing_time = end_time - start_time
            
        finally:
            loop.close()
            # 恢复原始配置
            doc_stats_utils.MAX_CONCURRENT_REQUESTS = original_max_concurrent
            doc_stats_utils.BATCH_SIZE = original_batch_size
            
    except Exception as e:
        logger.exception(f"批量处理文档统计时发生异常: {e}")
        return jsonify({"error": f"处理失败: {str(e)}"}), 500
    
    response_data = {
        "statistics": doc_stats,
        "processed_wikis": processed_wikis,
        "performance": {
            "total_urls": len(input_urls),
            "processed_docs": len(doc_stats),
            "processing_time_seconds": round(processing_time, 2),
            "docs_per_second": round(len(doc_stats) / processing_time, 2) if processing_time > 0 else 0,
            "max_concurrent": max_concurrent,
            "batch_size": batch_size
        },
        "async_mode": True
    }
    
    return jsonify(response_data)

@app.route('/doc-meta', methods=['POST'])
def get_doc_meta():
    """获取单个文档的元数据"""
    user_token = get_user_access_token()
    if not user_token:
        return jsonify({"error": "未授权，请先进行飞书授权", "need_auth": True}), 401
    
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "Missing 'url' in request body"}), 400
    
    url = data['url']
    
    try:
        # 解析URL
        file_type, file_token = parse_lark_url(url)
        if not file_type or not file_token:
            return jsonify({"error": f"无法解析URL: {url}"}), 400
        
        # 创建RequestDoc对象
        from lark_oapi.api.drive.v1.model import RequestDoc
        request_doc = RequestDoc.builder() \
            .doc_token(file_token) \
            .doc_type(file_type) \
            .build()
        
        # 获取元数据
        metas = batch_get_meta([request_doc])
        if metas and len(metas) > 0:
            meta = metas[0]
            return jsonify({
                "success": True,
                "title": meta.title,
                "type": meta.type if hasattr(meta, 'type') else file_type,
                "token": meta.doc_token if hasattr(meta, 'doc_token') else file_token,
                "update_time": meta.latest_modify_time,
                "create_time": meta.create_time
            })
        else:
            return jsonify({
                "success": False,
                "error": "无法获取文档元数据"
            }), 404
            
    except Exception as e:
        logger.exception(f"获取文档元数据时发生异常: {e}")
        return jsonify({
            "success": False,
            "error": f"获取文档元数据失败: {str(e)}"
        }), 500

# ================ 主入口 ================
if __name__ == "__main__":
    logger.info("启动Flask服务器...")
    
    # 如果配置了使用 ngrok，自动启动隧道
    if auth_config.use_ngrok:
        try:
            from ngrok_utils import start_ngrok_tunnel
            public_url = start_ngrok_tunnel(5001)
            if public_url:
                logger.info(f"ngrok 隧道已启动: {public_url}")
                logger.info(f"重定向 URI: {public_url}/auth/callback")
            else:
                logger.warning("启动 ngrok 隧道失败")
        except ImportError:
            logger.warning("ngrok 模块未安装，跳过自动启动")
        except Exception as e:
            logger.error(f"启动 ngrok 隧道时发生错误: {e}")
    
    app.run(debug=True, host='0.0.0.0', port=5001)
