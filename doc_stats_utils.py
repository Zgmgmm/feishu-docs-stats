"""
文档统计相关工具函数
包含文档解析、统计、树结构等功能
"""

import os
import json
import logging
import asyncio
import aiohttp
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any, Union
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv
import lark_oapi as lark
from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest, GetNodeSpaceResponse, ListSpaceNodeRequest, ListSpaceNodeResponse, Node
from lark_oapi.api.drive.v1 import GetFileStatisticsRequest, GetFileStatisticsResponse
from lark_oapi.api.drive.v1.resource.meta import BatchQueryMetaRequest, BatchQueryMetaResponse
from lark_oapi.api.drive.v1.model import MetaRequest, RequestDoc, Meta
# 导入授权相关函数
from auth_utils import get_user_access_token, auth_config

# 加载环境变量
load_dotenv()

# 配置日志
logger = logging.getLogger('doc-stats')

# 并发控制配置
MAX_CONCURRENT_REQUESTS = 10  # 最大并发请求数
BATCH_SIZE = 20  # 批量处理大小

# --- 配置类 ---
@dataclass
class Config:
    """应用配置"""
    app_id: str = os.environ.get("FEISHU_APP_ID", "")
    app_secret: str = os.environ.get("FEISHU_APP_SECRET", "")
    user_access_token: str = os.environ.get("FEISHU_USER_ACCESS_TOKEN", "")
    input_urls: List[str] = field(default_factory=lambda: [
        "https://bytedance.larkoffice.com/wiki/GQ0Owf7EmirsookHOh4cpx4XnMf"
        # "https://bytedance.sg.larkoffice.com/docx/Hvjcd6E7uoJP5exO8K2leqlegcc",
        # "https://bytedance.larkoffice.com/wiki/YB5mwIfOVi4jPmkt5e7cuGDenDA"
    ])

# 创建配置实例
config = Config()

# 创建Lark客户端
client = lark.Client.builder() \
    .app_id(config.app_id) \
    .app_secret(config.app_secret) \
    .log_level(lark.LogLevel.DEBUG) \
    .enable_set_token(True) \
    .build()

# --- 数据模型 ---
@dataclass
class NodeInfo:
    """节点信息"""
    title: str
    node_token: str
    obj_token: Optional[str] = None
    obj_type: str = "wiki"
    has_child: bool = False
    
@dataclass
class WikiInfo:
    """Wiki信息"""
    token: str
    space_id: str
    url: str

@dataclass
class DocumentStats:
    """文档统计信息"""
    title: str
    token: str
    type: str
    node_token: str
    source_url: str
    uv: int = 0
    pv: int = 0
    like_count: int = 0
    comment_count: int = 0
    edit_count: int = 0
    timestamp: int = 0
    uv_today: int = 0
    pv_today: int = 0
    like_count_today: int = 0
    update_time: int = 0
    
    @classmethod
    def from_api_stats(cls, node, stats, source_url, is_root=False):
        """从API返回的统计信息创建DocumentStats对象
        
        Args:
            node: 节点对象
            stats: API返回的统计信息
            source_url: 源URL
            is_root: 是否为根节点
            
        Returns:
            DocumentStats对象
        """
        if not stats:
            return None
            
        # 构造基本URL
        base_url = "https://bytedance.larkoffice.com"
        
        # 确定节点token和URL
        token = node.obj_token if hasattr(node, 'obj_token') and node.obj_token else node.node_token
        if is_root:
            node_url = source_url
        else:
            # 对于子节点，使用与token字段相同的值生成URL，确保标题和链接对应
            node_url = f"{base_url}/wiki/{node.node_token}"
        
        # 创建统计对象
        return cls(
            title=node.title,
            token=token,
            type=node.obj_type,
            node_token=node.node_token,
            source_url=node_url,
            uv=getattr(stats, 'uv', 0),
            pv=getattr(stats, 'pv', 0),
            like_count=getattr(stats, 'like_count', 0),
            comment_count=getattr(stats, 'comment_count', 0),
            edit_count=getattr(stats, 'edit_count', 0),
            timestamp=getattr(stats, 'timestamp', 0),
            uv_today=getattr(stats, 'uv_today', 0),
            pv_today=getattr(stats, 'pv_today', 0),
            like_count_today=getattr(stats, 'like_count_today', 0),
            update_time=getattr(stats, 'update_time', 0)
        )
        
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，字段名全部英文，顺序与FileStatistics一致，保留文档信息"""
        return {
            "title": self.title,
            "type": self.type,
            "token": self.token,
            "node_token": self.node_token,
            "source_url": self.source_url,
            "uv": self.uv,
            "pv": self.pv,
            "like_count": max(self.like_count,0),
            "timestamp": self.timestamp,
            "uv_today": self.uv_today,
            "pv_today": self.pv_today,
            "like_count_today": self.like_count_today,
            "update_time": self.update_time
        }

@dataclass
class WikiNode:
    """Wiki节点"""
    title: str
    token: str
    type: str
    children: List[Any] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "title": self.title,
            "token": self.token,
            "type": self.type,
            "children": [child.to_dict() for child in self.children]
        }

@dataclass
class DocxNode:
    """Docx文档节点"""
    title: str
    obj_token: str
    node_token: str  # docx没有node_token，使用file_token代替
    obj_type: str

# --- 工具函数 ---
def parse_lark_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """解析飞书文档URL，提取 file_type 和 file_token
    
    Args:
        url: 飞书文档URL
        
    Returns:
        元组 (file_type, file_token)，解析失败则返回 (None, None)
    """
    try:
        # 解析URL
        parsed = urlparse(url)
        
        # 验证域名
        if not parsed.netloc.endswith('larkoffice.com'):
            logger.error(f"无效的飞书文档URL: '{url}'，域名必须是larkoffice.com")
            return None, None
            
        # 分割路径部分
        path_parts = [p for p in parsed.path.split('/') if p]
        if len(path_parts) < 2:
            logger.error(f"无法从URL '{url}' 中解析出有效的文件类型和Token")
            return None, None
            
        file_type = path_parts[0]
        file_token = path_parts[1]
        
        # 将通用的 'docs' 映射到更具体的 'docx' 以便API调用
        if file_type.lower() in ['wiki', 'docx']:
            api_file_type = file_type.lower()
        else:
            logger.warning(f"URL中的文件类型 '{file_type}' 未知或不支持直接统计，将作为原始类型传递")
            api_file_type = file_type
            
        return api_file_type, file_token
        
    except Exception as e:
        logger.exception(f"解析URL时发生异常: {e}")
        return None, None

def get_node_space_id(node_token: str) -> Optional[str]:
    """获取文档的空间ID
    
    Args:
        node_token: 节点token
        
    Returns:
        空间ID，获取失败则返回None
    """
    request = GetNodeSpaceRequest.builder() \
        .token(node_token) \
        .obj_type("wiki") \
        .build()
    
    user_token = get_user_access_token()
    if not user_token:
        logger.error("未找到有效的user_access_token")
        return None
    
    options = lark.RequestOption.builder().user_access_token(user_token).build()

    try:
        response: GetNodeSpaceResponse = client.wiki.v2.space.get_node(request, options)
        if not response.success():
            logger.error(f"获取空间ID失败 (token: {node_token}): {response.code} {response.msg}")
            return None
            
        space_id = response.data.node.space_id
        logger.info(f"获取到空间ID: {space_id} (来自节点: {node_token})")
        return space_id
    except Exception as e:
        logger.exception(f"获取空间ID异常 (token: {node_token}): {e}")
        return None

def get_all_child_nodes(space_id: str, parent_node_token: str = None) -> List[Any]:
    """递归获取所有子节点
    
    Args:
        space_id: 知识空间ID
        parent_node_token: 父节点token，如果为None则获取根节点下的所有节点
        
    Returns:
        包含所有子节点的列表
    """
    all_nodes = []
    page_token = None
    
    while True:
        # 构建请求
        builder = ListSpaceNodeRequest.builder() \
            .space_id(space_id) \
            .page_size(50)
        
        if parent_node_token:
            builder.parent_node_token(parent_node_token)
        if page_token:
            builder.page_token(page_token)
            
        request = builder.build()
        user_token = get_user_access_token()
        if not user_token:
            logger.error("未找到有效的user_access_token")
            return []
        
        options = lark.RequestOption.builder().user_access_token(user_token).build()

        try:
            response: ListSpaceNodeResponse = client.wiki.v2.space_node.list(request, options)
            if not response.success():
                logger.error(f"扫描Wiki文档失败 (space_id: {space_id}, parent: {parent_node_token}): {response.code} {response.msg}")
                break
            
            # 处理返回的节点
            if response.data and response.data.items:
                for item in response.data.items:
                    all_nodes.append(item)
                    logger.info(f"{item.title} (token: {item.node_token}, type: {item.obj_type})")
                    
                    # 递归获取子节点
                    if item.has_child:
                        child_nodes = get_all_child_nodes(space_id, item.node_token)
                        all_nodes.extend(child_nodes)
            
            # 处理分页
            if response.data and response.data.has_more:
                page_token = response.data.page_token
            else:
                break
        except Exception as e:
            logger.exception(f"扫描Wiki文档异常 (space_id: {space_id}, parent: {parent_node_token}): {e}")
            break
    
    return all_nodes

async def get_all_child_nodes_async(space_id: str, user_token: str, parent_node_token: str = None) -> List[Any]:
    """异步递归获取所有子节点
    
    Args:
        space_id: 知识空间ID
        user_token: 用户token
        parent_node_token: 父节点token，如果为None则获取根节点下的所有节点
        
    Returns:
        包含所有子节点的列表
    """
    all_nodes = []
    page_token = None
    
    while True:
        # 构建请求
        builder = ListSpaceNodeRequest.builder() \
            .space_id(space_id) \
            .page_size(50)
        
        if parent_node_token:
            builder.parent_node_token(parent_node_token)
        if page_token:
            builder.page_token(page_token)
            
        request = builder.build()
        if not user_token:
            logger.error("未找到有效的user_access_token")
            return []
        
        options = lark.RequestOption.builder().user_access_token(user_token).build()

        try:
            # 在异步环境中调用同步API
            loop = asyncio.get_event_loop()
            response: ListSpaceNodeResponse = await loop.run_in_executor(
                None, 
                lambda: client.wiki.v2.space_node.list(request, options)
            )
            
            if not response.success():
                logger.error(f"扫描Wiki文档失败 (space_id: {space_id}, parent: {parent_node_token}): {response.code} {response.msg}")
                break
            
            # 处理返回的节点
            if response.data and response.data.items:
                for item in response.data.items:
                    all_nodes.append(item)
                    logger.info(f"{item.title} (token: {item.node_token}, type: {item.obj_type})")
                    
                    # 递归获取子节点（异步）
                    if item.has_child:
                        child_nodes = await get_all_child_nodes_async(space_id, user_token, item.node_token)
                        all_nodes.extend(child_nodes)
            
            # 处理分页
            if response.data and response.data.has_more:
                page_token = response.data.page_token
            else:
                break
        except Exception as e:
            logger.exception(f"扫描Wiki文档异常 (space_id: {space_id}, parent: {parent_node_token}): {e}")
            break
    
    return all_nodes

async def get_node_space_id_async(node_token: str, user_token: str) -> Optional[str]:
    """异步获取文档的空间ID
    
    Args:
        node_token: 节点token
        user_token: 用户token
        
    Returns:
        空间ID，获取失败则返回None
    """
    request = GetNodeSpaceRequest.builder() \
        .token(node_token) \
        .obj_type("wiki") \
        .build()
    if not user_token:
        logger.error("未找到有效的user_access_token")
        return None
    options = lark.RequestOption.builder().user_access_token(user_token).build()
    try:
        loop = asyncio.get_event_loop()
        response: GetNodeSpaceResponse = await loop.run_in_executor(
            None,
            lambda: client.wiki.v2.space.get_node(request, options)
        )
        if not response.success():
            logger.error(f"获取空间ID失败 (token: {node_token}): {response.code} {response.msg}")
            return None
        space_id = response.data.node.space_id
        logger.info(f"获取到空间ID: {space_id} (来自节点: {node_token})")
        return space_id
    except Exception as e:
        logger.exception(f"获取空间ID异常 (token: {node_token}): {e}")
        return None

def batch_get_meta(docs: List[RequestDoc], user_token: str = None) -> List[Meta]:
    """批量获取文档元数据，支持分批处理以避免超过API限制
    
    Args:
        docs: RequestDoc对象列表
        user_token: 用户token
        
    Returns:
        元数据列表
    """
    if not docs:
        return []
    
    # 飞书API限制：request_docs最大长度为200
    BATCH_SIZE = 200
    all_metas = []
    total_batches = (len(docs) + BATCH_SIZE - 1) // BATCH_SIZE
    
    logger.info(f"开始批量获取元数据，共 {len(docs)} 个文档，分 {total_batches} 批处理")
    
    # 分批处理
    for i in range(0, len(docs), BATCH_SIZE):
        batch_docs = docs[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        
        logger.info(f"处理第 {batch_num}/{total_batches} 批，包含 {len(batch_docs)} 个文档")
        
        # 使用单个批次处理函数
        batch_metas = batch_get_meta_single(batch_docs, user_token)
        all_metas.extend(batch_metas)
        
        logger.info(f"第 {batch_num} 批处理完成，获取到 {len(batch_metas)} 个元数据")
    
    logger.info(f"批量获取元数据完成，总共获取到 {len(all_metas)} 个元数据")
    return all_metas

def batch_get_meta_single(docs: List[RequestDoc], user_token: str = None) -> List[Meta]:
    """获取单个批次的文档元数据（内部函数）
    
    Args:
        docs: RequestDoc对象列表（不超过200个）
        user_token: 用户token
        
    Returns:
        元数据列表
    """
    if not docs:
        return []
    
    if len(docs) > 200:
        logger.warning(f"单个批次文档数量超过200个限制: {len(docs)}，将截取前200个")
        docs = docs[:200]
    
    # 构造请求对象
    request: BatchQueryMetaRequest = BatchQueryMetaRequest.builder() \
        .user_id_type("open_id") \
        .request_body(MetaRequest.builder()
            .request_docs(docs)
            .with_url(False)
            .build()) \
        .build()

    try:
        options = lark.RequestOption.builder().user_access_token(user_token).build()
        response: BatchQueryMetaResponse = client.drive.v1.meta.batch_query(request, options)
        
        # 处理失败返回
        if not response.success():
            error_msg = f"client.drive.v1.meta.batch_query failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
            if response.raw and response.raw.content:
                try:
                    error_detail = json.loads(response.raw.content)
                    error_msg += f", resp: \n{json.dumps(error_detail, indent=4, ensure_ascii=False)}"
                except:
                    error_msg += f", raw content: {response.raw.content}"
            
            lark.logger.error(error_msg)
            logger.error(f"批量获取元数据失败: {response.code} - {response.msg}")
            return []
            
        # 返回元数据
        if response.data and response.data.metas:
            logger.debug(f"成功获取 {len(response.data.metas)} 个元数据")
            return response.data.metas
        else:
            logger.warning("API返回成功但未获取到元数据")
            return []
            
    except Exception as e:
        logger.exception(f"批量获取元数据时发生异常: {e}")
        return []

async def batch_get_stats_async(file_tokens: List[Tuple[str, str]], user_token: str) -> Dict[Tuple[str, str], Any]:
    """异步批量获取文档统计信息
    
    Args:
        file_tokens: 包含(file_token, file_type)元组的列表
        user_token: 用户token
        
    Returns:
        以(file_token, file_type)为key的统计信息字典
    """
    semaphore = asyncio.Semaphore(100)
    results = {}
    
    async def get_single_stats(file_token: str, file_type: str):
        async with semaphore:
            try:
                # 使用同步API，但在异步环境中调用
                loop = asyncio.get_event_loop()
                stats = await loop.run_in_executor(None, get_file_stats, file_token, file_type, user_token)
                return (file_token, file_type), stats
            except Exception as e:
                logger.error(f"获取统计信息失败 (file_token: {file_token}, type: {file_type}): {e}")
                return (file_token, file_type), None
    
    # 创建所有任务
    tasks = [get_single_stats(token, file_type) for token, file_type in file_tokens]
    
    # 并发执行
    completed_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理结果
    for result in completed_results:
        if isinstance(result, Exception):
            logger.error(f"任务执行异常: {result}")
            continue
        key, stats = result
        results[key] = stats
    
    return results

async def batch_get_meta_async(docs: List[RequestDoc], user_token: str) -> List[Meta]:
    """异步批量获取文档元数据，支持分批处理以避免超过API限制
    
    Args:
        docs: RequestDoc对象列表
        user_token: 用户token
        
    Returns:
        元数据列表
    """
    if not docs:
        return []
    
    # 飞书API限制：request_docs最大长度为200
    BATCH_SIZE = 200
    all_metas = []
    
    # 分批处理
    for i in range(0, len(docs), BATCH_SIZE):
        batch_docs = docs[i:i + BATCH_SIZE]
        # 构造请求对象
        request: BatchQueryMetaRequest = BatchQueryMetaRequest.builder() \
            .user_id_type("open_id") \
            .request_body(MetaRequest.builder()
                .request_docs(batch_docs)
                .with_url(False)
                .build()) \
            .build()
        try:
            options = lark.RequestOption.builder().user_access_token(user_token).build()
            response: BatchQueryMetaResponse = await client.drive.v1.meta.abatch_query(request, options)
            
            # 处理失败返回
            if not response.success():
                error_msg = f"client.drive.v1.meta.batch_query failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
                if response.raw and response.raw.content:
                    try:
                        error_detail = json.loads(response.raw.content)
                        error_msg += f", resp: \n{json.dumps(error_detail, indent=4, ensure_ascii=False)}"
                    except:
                        error_msg += f", raw content: {response.raw.content}"
                
                lark.logger.error(error_msg)
                logger.error(f"批量获取元数据失败: {response.code} - {response.msg}")
                return []
                
            # 返回元数据
            if response.data and response.data.metas:
                logger.debug(f"成功获取 {len(response.data.metas)} 个元数据")
                all_metas.extend(response.data.metas)
            else:
                logger.warning("API返回成功但未获取到元数据")
                return []
                
        except Exception as e:
            logger.exception(f"批量获取元数据时发生异常: {e}")
            return []
    return all_metas
    
def batch_get_stats(file_tokens: List[Tuple[str, str]], user_token: str = None) -> Dict[Tuple[str, str], Any]:
    """同步批量获取文档统计信息
    
    Args:
        file_tokens: 包含(file_token, file_type)元组的列表
        user_token: 用户token
        
    Returns:
        以(file_token, file_type)为key的统计信息字典
    """
    if not user_token:
        user_token = get_user_access_token()
    if not user_token:
        logger.error("未找到有效的user_access_token")
        return {}
    
    results = {}
    
    for file_token, file_type in file_tokens:
        try:
            stats = get_file_stats(file_token, file_type, user_token)
            results[(file_token, file_type)] = stats
        except Exception as e:
            logger.error(f"获取统计信息失败 (file_token: {file_token}, type: {file_type}): {e}")
            results[(file_token, file_type)] = None
    
    return results

def get_file_stats(file_token: str, file_type: str, user_token: str = None) -> Optional[Any]:
    """获取文档统计信息
    
    Args:
        file_token: 文件token
        file_type: 文件类型，如'wiki'、'docx'等
        user_token: 用户token
        
    Returns:
        统计信息对象，如果获取失败则返回None
    """
    request = GetFileStatisticsRequest.builder() \
        .file_token(file_token) \
        .file_type(file_type) \
        .build()
    options = lark.RequestOption.builder().user_access_token(user_token).build()

    try:
        response: GetFileStatisticsResponse = client.drive.v1.file_statistics.get(request, options)
        if not response.success():
            logger.error(f"获取文档统计信息失败 (file_token: {file_token}, type: {file_type}): {response.code} {response.msg}")
            return None
        
        stats = response.data.statistics
        logger.info(f"统计信息 (token: {file_token}, type: {file_type}): stats: {vars(stats)}")
        return stats
    except Exception as e:
        logger.exception(f"获取文档统计信息异常 (file_token: {file_token}, type: {file_type}): {e}")
        return None

def get_doc_update_time(file_token: str, file_type: str, user_token: str = None) -> int:
    """获取文档的更新时间
    
    Args:
        file_token: 文件token
        file_type: 文件类型
        user_token: 用户token
        
    Returns:
        更新时间字符串，如果获取失败则返回空字符串
    """
    try:
        if not user_token:
            user_token = get_user_access_token()
        if not user_token:
            logger.error("未找到有效的user_access_token")
            return 0
        
        # 创建RequestDoc对象
        request_doc = RequestDoc.builder() \
            .doc_token(file_token) \
            .doc_type(file_type) \
            .build()
        
        # 获取元数据
        metas = batch_get_meta([request_doc], user_token)
        if metas and len(metas) > 0:
            meta = metas[0]
            return meta.latest_modify_time
        return 0
    except Exception as e:
        logger.exception(f"获取文档更新时间失败 (file_token: {file_token}, type: {file_type}): {e}")
        return 0

def collect_node_stats(node: Union[NodeInfo, Any], stats: Optional[Any], source_url: str, user_token: str = None, is_root: bool = False) -> Optional[Dict[str, Any]]:
    """收集节点的统计信息并创建统计字典
    
    Args:
        node: 节点对象，包含title、token等信息
        stats: 统计信息对象
        source_url: 源URL
        user_token: 用户token
        is_root: 是否为根节点
        
    Returns:
        包含统计信息的字典，如果stats为None则返回None
    """
    # 确定节点token和类型
    token = node.obj_token if hasattr(node, 'obj_token') and node.obj_token else node.node_token
    node_type = node.obj_type if hasattr(node, 'obj_type') else "wiki"
    
    # 获取文档更新时间
    update_time = get_doc_update_time(token, node_type, user_token)
    
    # 使用DocumentStats类创建统计信息
    doc_stats = DocumentStats.from_api_stats(node, stats, source_url, is_root)
    if not doc_stats:
        return None
    
    # 设置更新时间
    doc_stats.update_time = update_time
        
    return doc_stats.to_dict()

def build_wiki_tree(space_id: str, root_node_token: str) -> Optional[WikiNode]:
    """构建Wiki节点的树形结构
    
    Args:
        space_id: 知识空间ID
        root_node_token: 根节点token
        
    Returns:
        表示树形结构的WikiNode对象
    """
    # 获取根节点信息
    try:
        root_node = _get_root_node_info(root_node_token)
        if not root_node:
            return None
            
        tree = WikiNode(
            title=root_node.title,
            token=root_node.node_token,
            type=root_node.obj_type
        )
        
        # 从根节点开始构建树
        _build_subtree(space_id, root_node_token, tree)
        return tree
        
    except Exception as e:
        logger.exception(f"构建Wiki树结构时发生异常: {e}")
        return None

def _get_root_node_info(root_node_token: str) -> Optional[Any]:
    """获取根节点信息
    
    Args:
        root_node_token: 根节点token
        
    Returns:
        根节点信息对象
    """
    node_info_request = GetNodeSpaceRequest.builder().token(root_node_token).obj_type("wiki").build()
    user_token = get_user_access_token()
    if not user_token:
        logger.error("未找到有效的user_access_token")
        return None
    
    node_info_options = lark.RequestOption.builder().user_access_token(user_token).build()
    
    try:
        node_info_resp = client.wiki.v2.space.get_node(node_info_request, node_info_options)
        if not node_info_resp.success() or not node_info_resp.data or not node_info_resp.data.node:
            logger.error(f"无法获取根节点信息: {root_node_token}")
            return None
            
        return node_info_resp.data.node
    except Exception as e:
        logger.exception(f"获取根节点信息时发生异常: {e}")
        return None

def _build_subtree(space_id: str, parent_token: str, current_tree: WikiNode) -> None:
    """递归构建子节点树
    
    Args:
        space_id: 知识空间ID
        parent_token: 父节点token
        current_tree: 当前树节点
    """
    child_nodes = get_all_child_nodes(space_id, parent_token)
    for node in child_nodes:
        child = WikiNode(
            title=node.title,
            token=node.node_token,
            type=node.obj_type
        )
        current_tree.children.append(child)
        
        # 如果是wiki类型，递归获取其子节点
        if node.obj_type == "wiki":
            _build_subtree(space_id, node.node_token, child)

def print_wiki_tree(tree: Optional[WikiNode], indent: int = 0, prefix: str = "") -> None:
    """打印Wiki树形结构
    
    Args:
        tree: 树形结构对象
        indent: 缩进级别
        prefix: 前缀字符串
    """
    if not tree:
        return
        
    # 打印当前节点
    if indent == 0:
        logger.info(f"{tree.title} ({tree.type})")
    else:
        logger.info(f"{'  ' * (indent-1)}{prefix} {tree.title} ({tree.type})")
    
    # 打印子节点
    for i, child in enumerate(tree.children):
        is_last = i == len(tree.children) - 1
        child_prefix = "└─" if is_last else "├─"
        
        # 递归打印子节点
        print_wiki_tree(child, indent + 1, child_prefix)

def export_wiki_tree(tree: Optional[WikiNode], filename: str = "wiki_tree.json") -> None:
    """将Wiki树结构导出为JSON文件
    
    Args:
        tree: 树形结构对象
        filename: 输出文件名
    """
    if not tree:
        return
        
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(tree.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info(f"Wiki树结构已导出到 {filename}")

def process_wiki_node(file_token: str, space_id: str, url: str) -> Tuple[Optional[Dict[str, Any]], Optional[WikiInfo]]:
    """处理Wiki节点
    
    Args:
        file_token: 文件token
        space_id: 知识空间ID
        url: 文档URL
        
    Returns:
        包含统计信息和Wiki信息的元组
    """
    try:
        logger.info(f"处理Wiki节点: {file_token} (space_id: {space_id})")
        
        # 获取用户token
        user_token = get_user_access_token()
        if not user_token:
            logger.error("未找到有效的user_access_token")
            return None, None
        
        # 获取文档标题和更新时间
        request_doc = RequestDoc.builder() \
            .doc_token(file_token) \
            .doc_type("wiki") \
            .build()
        
        metas = batch_get_meta([request_doc], user_token)
        title = file_token  # 默认使用token作为标题
        update_time = 0
        
        if metas and len(metas) > 0:
            meta = metas[0]
            update_time = meta.latest_modify_time
            # 使用真实标题
            if hasattr(meta, 'title') and meta.title:
                title = meta.title
            logger.info(f"获取到Wiki节点标题: {title}")
        
        # 获取统计信息
        stats = get_file_stats(file_token, "wiki", user_token)
        
        # 创建NodeInfo对象，使用真实标题
        node_info = NodeInfo(
            title=title,
            node_token=file_token,
            obj_token=file_token,
            obj_type="wiki"
        )
        
        # 收集统计信息
        doc_stats = collect_node_stats(node_info, stats, url, user_token, is_root=True)
        
        # 创建WikiInfo对象
        wiki_info = WikiInfo(
            token=file_token,
            space_id=space_id,
            url=url
        )
        
        return doc_stats, wiki_info
        
    except Exception as e:
        logger.exception(f"处理Wiki节点时发生异常: {e}")
        return None, None

def process_wiki_children(space_id: str, parent_token: str, url: str) -> List[Dict[str, Any]]:
    """处理Wiki的所有子节点（优化版本）
    
    Args:
        space_id: 知识空间ID
        parent_token: 父节点token
        url: 文档URL
        
    Returns:
        子节点统计信息列表
    """
    try:
        logger.info(f"扫描Wiki节点 {parent_token} (space_id: {space_id}) 的子节点...")
        
        # 获取用户token
        user_token = get_user_access_token()
        if not user_token:
            logger.error("未找到有效的user_access_token")
            return []
        
        child_nodes = get_all_child_nodes(space_id, parent_token)
        
        if not child_nodes:
            logger.info(f"Wiki节点 {parent_token} 没有子节点或无法获取子节点列表。")
            return []
        
        total_nodes = len(child_nodes)
        logger.info(f"发现 {total_nodes} 个子节点，开始批量获取统计信息...")
        
        # 收集所有需要获取统计信息的节点
        nodes_with_tokens = []
        for node in child_nodes:
            if node.obj_token and node.obj_type:
                nodes_with_tokens.append((node.obj_token, node.obj_type))
        
        if not nodes_with_tokens:
            logger.warning("没有找到有效的子节点token")
            return []
        
        # 批量获取统计信息
        stats_dict = batch_get_stats(nodes_with_tokens, user_token)
        
        # 批量获取元数据（用于更新时间和标题）
        request_docs = []
        token_to_index = {}  # 用于跟踪token到索引的映射
        for i, node in enumerate(child_nodes):
            if node.obj_token and node.obj_type:
                request_doc = RequestDoc.builder() \
                    .doc_token(node.obj_token) \
                    .doc_type(node.obj_type) \
                    .build()
                request_docs.append(request_doc)
                token_to_index[node.obj_token] = i
        
        metas = batch_get_meta(request_docs, user_token)
        meta_dict = {}
        
        meta_dict = {meta.doc_token: meta for meta in metas}
        
        # 处理结果
        child_stats_list = []
        for node in child_nodes:
            if node.obj_token and node.obj_type:
                stats = stats_dict.get((node.obj_token, node.obj_type))
                
                # 获取更新时间和标题
                update_time = 0
                title = node.title  # 使用节点原始标题作为默认值
                
                if node.obj_token in meta_dict:
                    meta = meta_dict[node.obj_token]
                    update_time = meta.latest_modify_time
                    # 使用元数据中的真实标题
                    if hasattr(meta, 'title') and meta.title:
                        title = meta.title
                        logger.debug(f"节点 {node.obj_token} 使用元数据标题: {title}")
                    else:
                        logger.debug(f"节点 {node.obj_token} 使用原始标题: {title}")
                else:
                    logger.debug(f"节点 {node.obj_token} 未找到元数据，使用原始标题: {title}")
                
                # 创建带有真实标题的节点对象
                node_with_title = NodeInfo(
                    title=title,
                    node_token=node.node_token,
                    obj_token=node.obj_token,
                    obj_type=node.obj_type
                )
                
                # 创建统计信息
                doc_stats = collect_node_stats(node_with_title, stats, url, user_token, is_root=False)
                if doc_stats:
                    child_stats_list.append(doc_stats)
        
        logger.info(f"成功处理 {len(child_stats_list)} 个子节点的统计信息")
        return child_stats_list
        
    except Exception as e:
        logger.exception(f"处理Wiki子节点时发生异常: {e}")
        return []

async def process_wiki_children_async(space_id: str, parent_token: str, url: str, user_token: str) -> List[Dict[str, Any]]:
    """异步处理Wiki的所有子节点（优化版本）
    
    Args:
        space_id: 知识空间ID
        parent_token: 父节点token
        url: 文档URL
        user_token: 用户token
        
    Returns:
        子节点统计信息列表
    """
    try:
        logger.info(f"异步扫描Wiki节点 {parent_token} (space_id: {space_id}) 的子节点...")
        child_nodes = await get_all_child_nodes_async(space_id, user_token, parent_token)
        
        if not child_nodes:
            logger.info(f"Wiki节点 {parent_token} 没有子节点或无法获取子节点列表。")
            return []
        
        total_nodes = len(child_nodes)
        logger.info(f"发现 {total_nodes} 个子节点，开始批量获取统计信息...")
        
        # 收集所有需要获取统计信息的节点
        nodes_with_tokens = []
        for node in child_nodes:
            if node.obj_token and node.obj_type:
                nodes_with_tokens.append((node.obj_token, node.obj_type))
        
        if not nodes_with_tokens:
            logger.warning("没有找到有效的子节点token")
            return []
        
        # 批量获取统计信息
        stats_dict = await batch_get_stats_async(nodes_with_tokens, user_token)
        
        # 批量获取元数据（用于更新时间和标题）
        request_docs = []
        token_to_index = {}  # 用于跟踪token到索引的映射
        for i, node in enumerate(child_nodes):
            if node.obj_token and node.obj_type:
                request_doc = RequestDoc.builder() \
                    .doc_token(node.obj_token) \
                    .doc_type(node.obj_type) \
                    .build()
                request_docs.append(request_doc)
                token_to_index[node.obj_token] = i
        
        metas = await batch_get_meta_async(request_docs, user_token)
        meta_dict = {}
        
        meta_dict = {meta.doc_token: meta for meta in metas}
        
        # 处理结果
        child_stats_list = []
        for node in child_nodes:
            if node.obj_token and node.obj_type:
                stats = stats_dict.get((node.obj_token, node.obj_type))
                
                # 获取更新时间和标题
                update_time = 0
                title = node.title  # 使用节点原始标题作为默认值
                
                if node.obj_token in meta_dict:
                    meta = meta_dict[node.obj_token]
                    update_time = meta.latest_modify_time
                    # 使用元数据中的真实标题
                    if hasattr(meta, 'title') and meta.title:
                        title = meta.title
                        logger.debug(f"节点 {node.obj_token} 使用元数据标题: {title}")
                    else:
                        logger.debug(f"节点 {node.obj_token} 使用原始标题: {title}")
                else:
                    logger.debug(f"节点 {node.obj_token} 未找到元数据，使用原始标题: {title}")
                
                # 创建带有真实标题的节点对象
                node_with_title = NodeInfo(
                    title=title,
                    node_token=node.node_token,
                    obj_token=node.obj_token,
                    obj_type=node.obj_type
                )
                
                # 创建统计信息
                doc_stats = collect_node_stats(node_with_title, stats, url, user_token, is_root=False)
                if doc_stats:
                    child_stats_list.append(doc_stats)
        
        logger.info(f"成功处理 {len(child_stats_list)} 个子节点的统计信息")
        return child_stats_list
        
    except Exception as e:
        logger.exception(f"异步处理Wiki子节点时发生异常: {e}")
        return []

def collect_node_stats_optimized(node: Union[NodeInfo, Any], stats: Optional[Any], source_url: str, update_time: int, is_root: bool = False) -> Optional[Dict[str, Any]]:
    """优化的节点统计信息收集函数（避免重复API调用）
    
    Args:
        node: 节点对象，包含title、token等信息
        stats: 统计信息对象
        source_url: 源URL
        update_time: 更新时间（已预先获取）
        is_root: 是否为根节点
        
    Returns:
        包含统计信息的字典，如果stats为None则返回None
    """
    # 确定节点token和类型
    token = node.obj_token if hasattr(node, 'obj_token') and node.obj_token else node.node_token
    node_type = node.obj_type if hasattr(node, 'obj_type') else "wiki"
    
    # 使用DocumentStats类创建统计信息
    doc_stats = DocumentStats.from_api_stats(node, stats, source_url, is_root)
    if not doc_stats:
        return None
    
    # 设置更新时间（使用预先获取的值）
    doc_stats.update_time = update_time
        
    return doc_stats.to_dict()

def process_docx(file_token: str, file_type: str, url: str) -> Optional[Dict[str, Any]]:
    """处理docx文档
    
    Args:
        file_token: 文档token
        file_type: 文档类型
        url: 文档URL
        
    Returns:
        文档统计信息
    """
    logger.info(f"获取文档 '{file_token}' (type: {file_type}) 的统计信息...")
    
    try:
        # 获取用户token
        user_token = get_user_access_token()
        if not user_token:
            logger.error("未找到有效的user_access_token")
            return None
        
        # 获取文档标题和更新时间
        request_doc = RequestDoc.builder() \
            .doc_token(file_token) \
            .doc_type(file_type) \
            .build()
        
        metas = batch_get_meta([request_doc], user_token)
        title = file_token  # 默认使用token作为标题
        update_time = 0
        
        if metas and len(metas) > 0:
            meta = metas[0]
            update_time = meta.latest_modify_time
            # 使用真实标题
            if hasattr(meta, 'title') and meta.title:
                title = meta.title
            logger.info(f"获取到文档标题: {title}")
        
        # 获取文档统计信息
        stats = get_file_stats(file_token, file_type, user_token)
        
        # 创建DocxNode对象，使用真实标题
        docx_node = DocxNode(title, file_token, file_token, file_type)
        
        # 使用优化的函数收集统计信息
        return collect_node_stats(docx_node, stats, url, user_token, is_root=True)
        
    except Exception as e:
        logger.exception(f"处理docx文档时发生异常: {e}")
        return None

async def process_docx_async(file_token: str, file_type: str, url: str, user_token: str) -> Optional[Dict[str, Any]]:
    """异步处理docx文档
    
    Args:
        file_token: 文档token
        file_type: 文档类型
        url: 文档URL
        user_token: 用户token
        
    Returns:
        文档统计信息
    """
    logger.info(f"异步获取文档 '{file_token}' (type: {file_type}) 的统计信息...")
    
    try:
        # 并发获取统计信息和元数据
        loop = asyncio.get_event_loop()
        
        # 获取统计信息
        stats_task = loop.run_in_executor(None, get_file_stats, file_token, file_type, user_token)
        
        # 获取元数据
        request_doc = RequestDoc.builder() \
            .doc_token(file_token) \
            .doc_type(file_type) \
            .build()
        meta_task = batch_get_meta_async([request_doc], user_token)
        
        # 等待两个任务完成
        stats, metas = await asyncio.gather(stats_task, meta_task, return_exceptions=True)
        
        # 处理异常
        if isinstance(stats, Exception):
            logger.error(f"获取统计信息异常: {stats}")
            stats = None
        if isinstance(metas, Exception):
            logger.error(f"获取元数据异常: {metas}")
            metas = []
        
        # 获取更新时间和标题
        update_time = 0
        title = file_token  # 默认使用token作为标题
        
        if metas and len(metas) > 0:
            meta = metas[0]
            update_time = meta.latest_modify_time
            # 使用真实标题
            if hasattr(meta, 'title') and meta.title:
                title = meta.title
            logger.info(f"获取到文档标题: {title}")
        
        # 创建DocxNode对象，使用真实标题
        docx_node = DocxNode(title, file_token, file_token, file_type)
        
        # 使用优化的函数收集统计信息
        return collect_node_stats(docx_node, stats, url, user_token, is_root=True)
        
    except Exception as e:
        logger.exception(f"异步处理docx文档时发生异常: {e}")
        return None

async def process_wiki_node_async(file_token: str, space_id: str, url: str, user_token: str) -> Tuple[Optional[Dict[str, Any]], Optional[WikiInfo]]:
    """异步处理Wiki节点
    
    Args:
        file_token: 文件token
        space_id: 知识空间ID
        url: 文档URL
        user_token: 用户token
        
    Returns:
        包含统计信息和Wiki信息的元组
    """
    try:
        logger.info(f"异步处理Wiki节点: {file_token} (space_id: {space_id})")
        
        # 并发获取统计信息和元数据
        loop = asyncio.get_event_loop()
        
        # 获取统计信息
        stats_task = loop.run_in_executor(None, get_file_stats, file_token, "wiki", user_token)
        
        # 获取元数据
        request_doc = RequestDoc.builder() \
            .doc_token(file_token) \
            .doc_type("wiki") \
            .build()
        meta_task = batch_get_meta_async([request_doc], user_token)
        
        # 等待两个任务完成
        stats, metas = await asyncio.gather(stats_task, meta_task, return_exceptions=True)
        
        # 处理异常
        if isinstance(stats, Exception):
            logger.error(f"获取统计信息异常: {stats}")
            stats = None
        if isinstance(metas, Exception):
            logger.error(f"获取元数据异常: {metas}")
            metas = []
        
        # 获取更新时间和标题
        update_time = 0
        title = file_token  # 默认使用token作为标题
        file_type = "wiki"
        if metas and len(metas) > 0:
            meta = metas[0]
            update_time = meta.latest_modify_time
            # 使用真实标题
            title = meta.title
            file_type = meta.doc_type
            logger.info(f"获取到Wiki节点标题: {title}")
        
        # 创建NodeInfo对象，使用真实标题
        node_info = NodeInfo(
            title=title,
            node_token=file_token,
            obj_token=file_token,
            obj_type=file_type
        )
        
        # 收集统计信息
        doc_stats = collect_node_stats(node_info, stats, url, user_token, is_root=True)
        
        # 创建WikiInfo对象
        wiki_info = WikiInfo(
            token=file_token,
            space_id=space_id,
            url=url
        )
        
        return doc_stats, wiki_info
        
    except Exception as e:
        logger.exception(f"异步处理Wiki节点时发生异常: {e}")
        return None, None

def save_doc_stats(all_doc_stats: List[Dict[str, Any]], filename: str = "doc_stats.json") -> None:
    """保存文档统计信息到文件
    
    Args:
        all_doc_stats: 文档统计信息列表
        filename: 输出文件名
    """
    if not all_doc_stats:
        logger.warning("未收集到任何文档统计信息。")
        return
        
    # 按照UV值对文档统计信息进行降序排序
    all_doc_stats.sort(key=lambda x: x.get("uv", 0), reverse=True)
    logger.info(f"已按照UV值降序排序，共 {len(all_doc_stats)} 个文档")
    
    # 保存为JSON文件
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(all_doc_stats, f, ensure_ascii=False, indent=4)
    logger.info(f"统计结果已保存到 {filename}")

def generate_wiki_trees(processed_wikis: List[WikiInfo]) -> None:
    """生成Wiki树结构
    
    Args:
        processed_wikis: 处理过的Wiki信息列表
    """
    if not processed_wikis:
        return
        
    logger.info("\n--- 生成Wiki树结构 ---")
    generate_tree = input("是否生成Wiki树结构？(y/n): ").lower().strip() == 'y'
    if not generate_tree:
        logger.info("跳过生成Wiki树结构。")
        return
        
    for wiki in processed_wikis:
        logger.info(f"\n生成Wiki树结构: {wiki.url}")
        tree = build_wiki_tree(wiki.space_id, wiki.token)
        if tree:
            logger.info("\nWiki树结构:")
            print_wiki_tree(tree)
            
            # 导出树结构到JSON文件
            tree_filename = f"wiki_tree_{wiki.token}.json"
            export_wiki_tree(tree, tree_filename)
        else:
            logger.error(f"无法生成Wiki树结构: {wiki.token}")

def validate_config() -> bool:
    """验证配置是否有效
    
    Returns:
        配置是否有效
    """
    if not config.app_id or config.app_id == "YOUR_APP_ID" or not config.app_secret or config.app_secret == "YOUR_APP_SECRET":
        logger.error("错误：请在配置中设置 app_id 和 app_secret。")
        return False

    if not config.input_urls:
        logger.info("提示：input_urls 列表为空，请在配置中指定要处理的文档URL。")
        return False
        
    return True 


def get_document_statistics(urls: List[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """获取文档统计信息并构建Wiki树（如果适用）

    Args:
        urls: 要处理的文档URL列表

    Returns:
        包含所有文档统计信息和处理过的Wiki信息的元组
    """
    logger.info("开始处理文档统计...")

    # 验证配置
    if not validate_config(): # 假设 validate_config 不需要修改，或者根据需要调整
        return [], []

    all_doc_stats = []
    processed_wikis_data = [] # 用于存储可序列化的wiki信息

    for url_item in urls:
        logger.info(f"\n处理URL: {url_item}")
        file_type, file_token = parse_lark_url(url_item)

        if not file_type or not file_token:
            logger.error(f"无法解析URL: {url_item}")
            continue

        logger.info(f"解析结果: file_type='{file_type}', file_token='{file_token}'")

        if file_type == 'wiki':
            space_id = get_node_space_id(file_token)
            if not space_id:
                logger.error(f"无法获取知识空间ID: {file_token}")
                continue

            doc_stats, wiki_info_obj = process_wiki_node(file_token, space_id, url_item)
            if doc_stats:
                all_doc_stats.append(doc_stats)
            if wiki_info_obj:
                # 将WikiInfo对象转换为字典以便序列化
                processed_wikis_data.append({
                    "token": wiki_info_obj.token,
                    "space_id": wiki_info_obj.space_id,
                    "url": wiki_info_obj.url
                })

            child_stats_list = process_wiki_children(space_id, file_token, url_item)
            all_doc_stats.extend(child_stats_list)

        elif file_type == 'docx':
            doc_stats = process_docx(file_token, file_type, url_item)
            if doc_stats:
                all_doc_stats.append(doc_stats)
        else:
            logger.warning(f"警告：文件类型 '{file_type}' (来自URL: {url_item}) 不是 'wiki' 或 'docx'，跳过处理。")

    # 对统计结果进行排序
    all_doc_stats.sort(key=lambda x: x.get("uv", 0), reverse=True)

    return all_doc_stats, processed_wikis_data

async def get_document_statistics_async(urls: List[str], user_token: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """异步获取文档统计信息（优化版本）

    Args:
        urls: 要处理的文档URL列表

    Returns:
        包含所有文档统计信息和处理过的Wiki信息的元组
    """
    logger.info("开始异步处理文档统计...")

    # 验证配置
    if not validate_config():
        return [], []

    all_doc_stats = []
    processed_wikis_data = []

    # 第一步：解析所有URL并获取空间ID
    url_tasks = []
    for url_item in urls:
        logger.info(f"解析URL: {url_item}")
        file_type, file_token = parse_lark_url(url_item)
        
        if not file_type or not file_token:
            logger.error(f"无法解析URL: {url_item}")
            continue
            
        logger.info(f"解析结果: file_type='{file_type}', file_token='{file_token}'")
        
        if file_type == 'wiki':
            # 异步获取空间ID
            space_id_task = get_node_space_id_async(file_token, user_token)
            url_tasks.append((url_item, file_type, file_token, space_id_task))
        else:
            # 非Wiki文档，直接处理
            url_tasks.append((url_item, file_type, file_token, None))

    # 等待所有空间ID获取完成
    wiki_tasks = []
    docx_tasks = []
    
    for url_item, file_type, file_token, space_id_task in url_tasks:
        if file_type == 'wiki':
            space_id = await space_id_task
            if not space_id:
                logger.error(f"无法获取知识空间ID: {file_token}")
                continue
                
            # 创建Wiki处理任务
            wiki_task = process_wiki_node_async(file_token, space_id, url_item, user_token)
            wiki_tasks.append((url_item, file_token, space_id, wiki_task))
        elif file_type == 'docx':
            # 创建docx处理任务
            docx_task = process_docx_async(file_token, file_type, url_item, user_token)
            docx_tasks.append((url_item, docx_task))

    # 并发处理所有Wiki节点
    if wiki_tasks:
        logger.info(f"开始并发处理 {len(wiki_tasks)} 个Wiki节点...")
        wiki_results = await asyncio.gather(*[task for _, _, _, task in wiki_tasks], return_exceptions=True)
        
        for i, (url_item, file_token, space_id, _) in enumerate(wiki_tasks):
            result = wiki_results[i]
            if isinstance(result, Exception):
                logger.error(f"处理Wiki节点失败: {result}")
                continue
                
            doc_stats, wiki_info_obj = result
            if doc_stats:
                all_doc_stats.append(doc_stats)
            if wiki_info_obj:
                processed_wikis_data.append({
                    "token": wiki_info_obj.token,
                    "space_id": wiki_info_obj.space_id,
                    "url": wiki_info_obj.url
                })
            
            # 异步处理子节点
            child_task = process_wiki_children_async(space_id, file_token, url_item, user_token)
            child_stats = await child_task
            all_doc_stats.extend(child_stats)

    # 并发处理所有docx文档
    if docx_tasks:
        logger.info(f"开始并发处理 {len(docx_tasks)} 个docx文档...")
        docx_results = await asyncio.gather(*[task for _, task in docx_tasks], return_exceptions=True)
        
        for i, (url_item, _) in enumerate(docx_tasks):
            result = docx_results[i]
            if isinstance(result, Exception):
                logger.error(f"处理docx文档失败: {result}")
                continue
                
            if result:
                all_doc_stats.append(result)

    # 对统计结果进行排序
    all_doc_stats.sort(key=lambda x: x.get("uv", 0), reverse=True)
    
    logger.info(f"异步处理完成，共获取 {len(all_doc_stats)} 个文档的统计信息")
    return all_doc_stats, processed_wikis_data
