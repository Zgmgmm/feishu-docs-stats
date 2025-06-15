import lark_oapi as lark
from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest, GetNodeSpaceResponse, ListSpaceNodeRequest, ListSpaceNodeResponse
from lark_oapi.api.drive.v1 import GetFileStatisticsRequest, GetFileStatisticsResponse
from lark_oapi.api.auth.v3 import *
import os
import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any, Union
from dotenv import load_dotenv

load_dotenv() # 加载 .env 文件中的环境变量

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('doc-stats')

# --- 配置类 ---
@dataclass
class Config:
    """应用配置"""
    app_id: str = os.environ.get("FEISHU_APP_ID", "")
    app_secret: str = os.environ.get("FEISHU_APP_SECRET", "")
    user_access_token: str = os.environ.get("FEISHU_USER_ACCESS_TOKEN", "")
    tenant_access_token: str = os.environ.get("FEISHU_TENANT_ACCESS_TOKEN", "")
    max_depth: int = 5
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
    .log_level(lark.LogLevel.INFO) \
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

from urllib.parse import urlparse, unquote

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
    
    options = lark.RequestOption.builder().user_access_token(config.user_access_token).build()

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


def get_all_child_nodes(space_id: str, parent_node_token: str = None, max_depth: int = 5, current_depth: int = 0) -> List[Any]:
    """递归获取所有子节点
    
    Args:
        space_id: 知识空间ID
        parent_node_token: 父节点token，如果为None则获取根节点下的所有节点
        max_depth: 最大递归深度，防止过深递归
        current_depth: 当前递归深度，用于日志缩进和深度控制
        
    Returns:
        包含所有子节点的列表
    """
    # 超过最大深度，停止递归
    if current_depth > max_depth:
        logger.info(f"{'  ' * current_depth}达到最大递归深度 {max_depth}，停止递归")
        return []

    all_nodes = []
    page_token = None
    indent = "+" + "-" * current_depth  # 根据深度生成缩进，便于日志查看层级关系
    
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
        options = lark.RequestOption.builder().user_access_token(config.user_access_token).build()

        try:
            response: ListSpaceNodeResponse = client.wiki.v2.space_node.list(request, options)
            if not response.success():
                logger.error(f"{indent}扫描Wiki文档失败 (space_id: {space_id}, parent: {parent_node_token}): {response.code} {response.msg}")
                break
            
            # 处理返回的节点
            if response.data and response.data.items:
                for item in response.data.items:
                    all_nodes.append(item)
                    logger.info(f"{indent}{item.title} (token: {item.node_token}, type: {item.obj_type})")
                    
                    # 递归获取子节点
                    if item.has_child:
                        child_nodes = get_all_child_nodes(space_id, item.node_token, max_depth, current_depth + 1)
                        all_nodes.extend(child_nodes)
            
            # 处理分页
            if response.data and response.data.has_more:
                page_token = response.data.page_token
            else:
                break
        except Exception as e:
            logger.exception(f"{indent}扫描Wiki文档异常 (space_id: {space_id}, parent: {parent_node_token}): {e}")
            break
    
    return all_nodes

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
            node_url = f"{base_url}/wiki/{node.node_token}"
        
        # 创建统计对象
        return cls(
            title=node.title,
            token=token,
            type=node.obj_type,
            node_token=node.node_token,
            source_url=node_url,
            uv=stats.uv,
            pv=stats.pv,
            like_count=stats.like_count,
            comment_count=getattr(stats, 'comment_count', 0),
            edit_count=getattr(stats, 'edit_count', 0)
        )
        
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "title": self.title,
            "token": self.token,
            "type": self.type,
            "node_token": self.node_token,
            "source_url": self.source_url,
            "uv": self.uv,
            "pv": self.pv,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
            "edit_count": self.edit_count
        }


def get_file_stats(file_token: str, file_type: str) -> Optional[Any]:
    """获取文档统计信息
    
    Args:
        file_token: 文件token
        file_type: 文件类型，如'wiki'、'docx'等
        
    Returns:
        统计信息对象，如果获取失败则返回None
    """
    request = GetFileStatisticsRequest.builder() \
        .file_token(file_token) \
        .file_type(file_type) \
        .build()
    options = lark.RequestOption.builder().user_access_token(config.user_access_token).build()

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
        

def collect_node_stats(node: Union[NodeInfo, Any], stats: Optional[Any], source_url: str, is_root: bool = False) -> Optional[Dict[str, Any]]:
    """收集节点的统计信息并创建统计字典
    
    Args:
        node: 节点对象，包含title、token等信息
        stats: 统计信息对象
        source_url: 源URL
        is_root: 是否为根节点
        
    Returns:
        包含统计信息的字典，如果stats为None则返回None
    """
    # 使用DocumentStats类创建统计信息
    doc_stats = DocumentStats.from_api_stats(node, stats, source_url, is_root)
    if not doc_stats:
        return None
        
    return doc_stats.to_dict()

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


def build_wiki_tree(space_id: str, root_node_token: str, max_depth: int = 5) -> Optional[WikiNode]:
    """构建Wiki节点的树形结构
    
    Args:
        space_id: 知识空间ID
        root_node_token: 根节点token
        max_depth: 最大递归深度
        
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
        _build_subtree(space_id, root_node_token, tree, 1, max_depth)
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
    node_info_options = lark.RequestOption.builder().user_access_token(config.user_access_token).build()
    
    try:
        node_info_resp = client.wiki.v2.space.get_node(node_info_request, node_info_options)
        if not node_info_resp.success() or not node_info_resp.data or not node_info_resp.data.node:
            logger.error(f"无法获取根节点信息: {root_node_token}")
            return None
            
        return node_info_resp.data.node
    except Exception as e:
        logger.exception(f"获取根节点信息时发生异常: {e}")
        return None


def _build_subtree(space_id: str, parent_token: str, current_tree: WikiNode, current_depth: int, max_depth: int) -> None:
    """递归构建子节点树
    
    Args:
        space_id: 知识空间ID
        parent_token: 父节点token
        current_tree: 当前树节点
        current_depth: 当前递归深度
        max_depth: 最大递归深度
    """
    if current_depth > max_depth:
        return
        
    child_nodes = get_all_child_nodes(space_id, parent_token, max_depth=1, current_depth=0)
    for node in child_nodes:
        child = WikiNode(
            title=node.title,
            token=node.node_token,
            type=node.obj_type
        )
        current_tree.children.append(child)
        
        # 如果是wiki类型，递归获取其子节点
        if node.obj_type == "wiki":
            _build_subtree(space_id, node.node_token, child, current_depth + 1, max_depth)


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
        file_token: 节点token
        space_id: 知识空间ID
        url: 文档URL
        
    Returns:
        节点统计信息和Wiki信息的元组
    """
    node_info_request = GetNodeSpaceRequest.builder().token(file_token).obj_type("wiki").build()
    node_info_options = lark.RequestOption.builder().user_access_token(config.user_access_token).build()
    
    try:
        node_info_resp = client.wiki.v2.space.get_node(node_info_request, node_info_options)
        if not node_info_resp.success() or not node_info_resp.data or not node_info_resp.data.node:
            logger.error(f"无法获取节点信息: {file_token}")
            return None, None
            
        root_node = node_info_resp.data.node
        initial_node_obj_type = root_node.obj_type # 这应该是 'wiki'
        initial_node_title = root_node.title
        
        # Wiki 节点本身也可能有 obj_token，指向其对应的文档实体，统计时用 obj_token
        token_for_stats = root_node.obj_token if hasattr(root_node, 'obj_token') and root_node.obj_token else file_token
        type_for_stats = initial_node_obj_type # 通常是 'wiki'
        
        logger.info(f"获取Wiki根节点 '{initial_node_title}' (token_for_stats: {token_for_stats}, type: {type_for_stats}) 的统计信息...")
        stats = get_file_stats(token_for_stats, type_for_stats)
        
        # 收集根节点统计信息
        doc_stats = collect_node_stats(root_node, stats, url, is_root=True)
        
        # 记录处理过的Wiki信息，用于生成树结构
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
    """处理Wiki的所有子节点
    
    Args:
        space_id: 知识空间ID
        parent_token: 父节点token
        url: 文档URL
        
    Returns:
        子节点统计信息列表
    """
    child_stats_list = []
    
    try:
        logger.info(f"扫描Wiki节点 {parent_token} (space_id: {space_id}) 的子节点...")
        child_nodes = get_all_child_nodes(space_id, parent_token, config.max_depth)
        
        if child_nodes:
            total_nodes = len(child_nodes)
            logger.info(f"发现 {total_nodes} 个子节点，开始获取统计信息...")
            
            # 处理每个子节点
            for i, node in enumerate(child_nodes, 1):
                logger.info(f"处理子节点 [{i}/{total_nodes}]: '{node.title}'")
                
                if node.obj_token and node.obj_type:
                    logger.info(f"  获取子节点 '{node.title}' (obj_token: {node.obj_token}, type: {node.obj_type}) 的统计信息...")
                    stats = get_file_stats(node.obj_token, node.obj_type)
                    
                    # 收集子节点统计信息
                    doc_stats = collect_node_stats(node, stats, url, is_root=False)
                    if doc_stats:
                        child_stats_list.append(doc_stats)
                    else:
                        logger.warning(f"  无法获取子节点 '{node.title}' 的统计信息")
                else:
                    logger.warning(f"  子节点 '{node.title}' (node_token: {node.node_token})缺少 obj_token 或 obj_type，无法获取统计信息。")
        else:
            logger.info(f"Wiki节点 {parent_token} 没有子节点或无法获取子节点列表。")
            
        return child_stats_list
        
    except Exception as e:
        logger.exception(f"处理Wiki子节点时发生异常: {e}")
        return child_stats_list


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
    
    # 尝试获取文档标题，如果失败则使用token作为标题
    title = file_token # 默认标题
    
    # 获取文档统计信息
    stats = get_file_stats(file_token, file_type)
    
    # 使用全局定义的DocxNode类创建实例
    docx_node = DocxNode(title, file_token, file_token, file_type)
    
    # 使用辅助函数收集统计信息
    return collect_node_stats(docx_node, stats, url, is_root=True)


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


def main() -> None:
    """主函数"""
    logger.info("开始处理文档统计...")
    
    # 验证配置
    if not validate_config():
        return
    
    # 初始化结果列表
    all_doc_stats = []
    processed_wikis = []

    # 处理每个输入URL
    for url in config.input_urls:
        logger.info(f"\n处理URL: {url}")
        file_type, file_token = parse_lark_url(url)

        if not file_type or not file_token:
            logger.error(f"无法解析URL: {url}")
            continue

        logger.info(f"解析结果: file_type='{file_type}', file_token='{file_token}'")

        if file_type == 'wiki':
            # 获取知识空间ID
            space_id = get_node_space_id(file_token)
            if not space_id:
                logger.error(f"无法获取知识空间ID: {file_token}")
                continue
                
            # 处理Wiki根节点
            doc_stats, wiki_info = process_wiki_node(file_token, space_id, url)
            if doc_stats:
                all_doc_stats.append(doc_stats)
            if wiki_info:
                processed_wikis.append(wiki_info)
            
            # 处理Wiki子节点
            child_stats_list = process_wiki_children(space_id, file_token, url)
            all_doc_stats.extend(child_stats_list)
        
        elif file_type == 'docx': # 只支持 docx
            # 处理docx文档
            doc_stats = process_docx(file_token, file_type, url)
            if doc_stats:
                all_doc_stats.append(doc_stats)
        else:
            logger.warning(f"警告：文件类型 '{file_type}' (来自URL: {url}) 不是 'wiki' 或 'docx'，跳过处理。")

    # 保存统计结果
    save_doc_stats(all_doc_stats, "wiki_stats_output.json")
    
    # 生成Wiki树结构
    generate_wiki_trees(processed_wikis)
    
    logger.info("\n处理完成!")


if __name__ == "__main__":
    main()
