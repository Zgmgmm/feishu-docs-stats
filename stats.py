import asyncio
import logging
import json
from typing import *
from lark_oapi.api.wiki.v2 import *
from dataclasses import dataclass, field
from urllib.parse import urlparse
import lark_oapi as lark
from doc_stats_utils import client, parse_lark_url, logger, batch_get_stats_async, get_node_space_id_async
from itertools import tee
from lark_oapi.api.drive.v1.model import MetaRequest, RequestDoc, Meta
from lark_oapi.api.drive.v1.resource.meta import BatchQueryMetaRequest, BatchQueryMetaResponse

from typing import Callable


logger = logging.getLogger('doc-stats')


fake_tree = {
    "A": ["B", "C", "D", "E"],
    "B": ["F", "G", "H", "I"],
    "C": ["J", "K", "L", "M"],
    "D": ["N", "O", "P", "Q"],
    "E": ["R", "S", "T", "U"],
    "F": ["V"],
    "G": ["W"],
    "H": ["X"],
    "I": ["Y"],
    "J": ["Z"],
    "K": ["AA"],
    "L": ["AB"],
    "M": ["AC"],
    "N": ["AD"],
    "O": ["AE"],
    "P": ["AF"],
    "Q": [],
    "R": [],
    "S": [],
    "T": [],
    "U": [],
    "V": [],
    "W": [],
    "X": [],
    "Y": [],
    "Z": [],
    "AA": [],
    "AB": [],
    "AC": [],
    "AD": [],
    "AE": [],
    "AF": [],
}

# 模拟异步获取子节点的函数
async def mock_get_children(node: Node) -> List[Node]:
    await asyncio.sleep(random.uniform(1, 3))  # 模拟网络延迟
    print(f"获取 {node} 的子节点：{fake_tree.get(node, [])}")
    tokens = fake_tree.get(node, [])
    return [NodeBuilder().node_token(token).build() for token in tokens]

def has_children(node):
    return len(fake_tree.get(node, [])) > 0


from asyncio_throttle import Throttler  # 导入现成限流器

# ✅ 支持流式输出的并发 BFS（适用于树结构）
async def walk_tree_concurrent(roots: list[Node], throttler: Throttler, user_token: str) -> Node:
    q_nodes = asyncio.Queue[Node]()
    q_parents = asyncio.Queue[Node]()

    async def worker():
        node = await q_parents.get()
        await q_nodes.put(node)
        # API调用前进行QPS限流
        async with throttler:
            children = await get_children(node, user_token)  # 实际接口调用
            for child in children:
                if child.has_child:
                    await q_parents.put(child)
                    asyncio.create_task(worker())
                else:
                    await q_nodes.put(child)
        q_parents.task_done()
        
    async def add_parent(node: Node):
        await q_parents.put(node)
        asyncio.create_task(worker())

    async def wait_for_completion():
        await q_parents.join()
        await q_nodes.put(None)

    for root in roots:
        await add_parent(root)
        
    asyncio.create_task(wait_for_completion())

    # 👇 用 async generator 持续 yield 流式数据
    while True:
        item = await q_nodes.get()
        if item is None:
            break
        yield item

# 这是批量收集器，异步迭代器输入，批量输出 list
async def batcher(iter: Iterator[Node], batch_size: int) -> List[Node]:
    batch:List[Node] = []
    async for item in iter:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    # 最后一批不足 batch_size，也输出
    if batch[0]:
        yield batch


async def batch_get_meta_async(docs: List[RequestDoc], user_token: str = None) -> List[Meta]:
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
            return response.data.metas
        else:
            logger.warning("API返回成功但未获取到元数据")
            return []
            
    except Exception as e:
        logger.exception(f"批量获取元数据时发生异常: {e}")
        return []

async def get_wiki_node(token: str, user_token: str) -> Optional[Node]:
    """获取根节点信息
    
    Args:
        root_node_token: 根节点token
        
    Returns:
        根节点信息对象
    """
    node_info_request = GetNodeSpaceRequest.builder().token(token).obj_type("wiki").build()
    node_info_options = lark.RequestOption.builder().user_access_token(user_token).build()
    
    try:
        node_info_resp = await client.wiki.v2.space.aget_node(node_info_request, node_info_options)
        if not node_info_resp.success() or not node_info_resp.data or not node_info_resp.data.node:
            logger.error(f"无法获取根节点信息: {root_node_ttokenoken}")
            return None
            
        return node_info_resp.data.node
    except Exception as e:
        logger.exception(f"获取根节点信息时发生异常: {e}")
        return None


home = Node({
    "creator": "ou_12281da53242d092b4f94fd05a8db87d",
    "has_child": True,
    "node_create_time": "1720163737",
    "node_creator": "ou_12281da53242d092b4f94fd05a8db87d",
    "node_token": "GQ0Owf7EmirsookHOh4cpx4XnMf",
    "node_type": "origin",
    "obj_create_time": "1720163737",
    "obj_edit_time": "1749977983",
    "obj_token": "QVIndcvtbocvZjxaOuJcgid5nFe",
    "obj_type": "docx",
    "origin_node_token": "GQ0Owf7EmirsookHOh4cpx4XnMf",
    "origin_space_id": "7064927739869954076",
    "owner": "ou_12281da53242d092b4f94fd05a8db87d",
    "parent_node_token": "wikcn6YQbanr7yHT1pucnHeewcc",
    "space_id": "7064927739869954076",
    "title": "首页框架"
})
node = Node({
    "creator": "ou_12281da53242d092b4f94fd05a8db87d",
    "has_child": True,
    "node_create_time": "1735452354",
    "node_creator": "ou_12281da53242d092b4f94fd05a8db87d",
    "node_token": "R7oQwIXvUixG3FkimMBcTx2Inxh",
    "node_type": "origin",
    "obj_create_time": "1735452354",
    "obj_edit_time": "1736610706",
    "obj_token": "Jv1ndYk7DoUP4jxnI3ZcGfjqnSc",
    "obj_type": "docx",
    "origin_node_token": "R7oQwIXvUixG3FkimMBcTx2Inxh",
    "origin_space_id": "7064927739869954076",
    "owner": "ou_12281da53242d092b4f94fd05a8db87d",
    "parent_node_token": "GQ0Owf7EmirsookHOh4cpx4XnMf",
    "space_id": "7064927739869954076",
    "title": "总结&规划"
})
async def get_wiki_info(tokens: List[str], user_token: str):
    roots = [await get_wiki_node(token, user_token) for token in tokens]
    async_gen = walk_tree_concurrent(roots, throttler, user_token)
    res = []
    async for batch in batcher(async_gen, batch_size = 200):
        docs = [RequestDoc.builder().doc_token(doc.obj_token).doc_type(doc.obj_type).build() for doc in batch]
        infos = await get_doc_info(docs, user_token)
        res += infos
        # files = [(node.obj_token, node.obj_type) for node in batch]
        # stats_task = batch_get_stats_async(files, user_token)
        # docs = [RequestDoc.builder().doc_token(doc.obj_token).doc_type(doc.obj_type).build() for doc in batch]
        # meta_task = batch_get_meta_async(docs, user_token)
        # stats_dict, metas = await asyncio.gather(stats_task, meta_task)
        # meta_dict = {meta.doc_token: meta for meta in metas}
        # for node in batch: 
        #     token = node.obj_token
        #     stat = stats_dict[(node.obj_token, node.obj_type)]
        #     meta = meta_dict[token]
        #     res.append({
        #         "title": meta.title,
        #         "type": meta.doc_type,
        #         "token": meta.doc_token,
        #         "node_token": node.node_token,
        #         "source_url": f"https://docs.feishu.cn/{meta.doc_type}/{meta.doc_token}",
        #         "uv": stat.uv,
        #         "pv": stat.pv,
        #         "like_count": max(stat.like_count,0),
        #         "timestamp": meta.latest_modify_time,
        #         "uv_today": stat.uv_today,
        #         "pv_today": stat.pv_today,
        #         "like_count_today": stat.like_count_today,
        #         "update_time": meta.latest_modify_time,
        #     })
        #     i += 1
        #     print(f"Doc {i} {vars(meta)}：{vars(stat)}")
        # print(f"批量处理：{batch}")
        # 这里可以用 await 调用批量接口、批量数据库写入等
    return res
async def get_doc_info(docs: List[RequestDoc], user_token: str):
    files = [(doc.doc_token, doc.doc_type) for doc in docs]
    stats_task = batch_get_stats_async(files, user_token)
    meta_task = batch_get_meta_async(docs, user_token)
    stats_dict, metas = await asyncio.gather(stats_task, meta_task)
    meta_dict = {meta.doc_token: meta for meta in metas}
    res = []
    for doc in docs:
        stat = stats_dict.get((doc.doc_token, doc.doc_type))
        meta = meta_dict.get(doc.doc_token)
        if not stat or not meta:
            print(f"Doc failed {vars(doc)}")
            continue
        res.append({
            "title": meta.title,
            "type": meta.doc_type,
            "token": meta.doc_token,
            "node_token": doc.doc_token,
            "source_url": f"https://bytedance.larkoffice.com/{meta.doc_type}/{meta.doc_token}",
            "uv": stat.uv,
            "pv": stat.pv,
            "like_count": max(stat.like_count,0),
            "timestamp": meta.latest_modify_time,
            "uv_today": stat.uv_today,
            "pv_today": stat.pv_today,
            "like_count_today": stat.like_count_today,
            "update_time": meta.latest_modify_time,
        })
        print(f"Doc {vars(meta)}：{vars(stat)}")
    return res
async def get_children(parent: Node, user_token: str) -> List[Node]:
    all_nodes = []
    page_token = None
    space_id = parent.space_id
    while True:
        # 构建请求
        builder = ListSpaceNodeRequest.builder() \
            .space_id(space_id) \
            .page_size(50) \
            .parent_node_token(parent.node_token)
        if page_token:
            builder.page_token(page_token)
            
        request = builder.build()
        options = lark.RequestOption.builder().user_access_token(user_token).build()

        try:
            response: ListSpaceNodeResponse = await client.wiki.v2.space_node.alist(request, options)
            if not response.success():
                logger.error(f"扫描Wiki文档失败 (space_id: {space_id}, parent: {parent.node_token}): {response.code} {response.msg}")
                break
            
            # 处理返回的节点
            if response.data and response.data.items:
                for item in response.data.items:
                    all_nodes.append(item)
                    logger.info(f"{item.title} (token: {item.node_token}, type: {item.obj_type})")
            # 处理分页
            if response.data and response.data.has_more:
                page_token = response.data.page_token
            else:
                break
        except Exception as e:
            logger.exception(f"扫描Wiki文档异常 (space_id: {space_id}, parent: {parent.node_token}): {e}")
            break
    return all_nodes


def parse_doc_url(url: str) -> RequestDoc:
    try:
        # 解析URL
        parsed = urlparse(url)
        
        # 验证域名
        if not parsed.netloc.endswith('larkoffice.com'):
            logger.error(f"无效的飞书文档URL: '{url}'，域名必须是larkoffice.com")
            return None
            
        # 分割路径部分
        path_parts = [p for p in parsed.path.split('/') if p]
        if len(path_parts) < 2:
            logger.error(f"无法从URL '{url}' 中解析出有效的文件类型和Token")
            return None
            
        file_type = path_parts[0]
        file_token = path_parts[1]
        
        return RequestDoc.builder().doc_type(file_type).doc_token(file_token).build()
        
    except Exception as e:
        logger.exception(f"解析URL时发生异常: {e}")
        return None, None

async def get_document_statistics_async_v2(urls: List[str], user_token: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:        
    docs = [parse_doc_url(url) for url in urls]
    wikis = filter(lambda doc:doc.doc_type == "wiki", docs)
    wiki_tokens = list(map(lambda doc:doc.doc_token, wikis))
    wiki_infos = await get_wiki_info(wiki_tokens, user_token)
    non_wikis = list(filter(lambda doc:doc.doc_type != "wiki", docs))
    doc_infos = await get_doc_info(non_wikis, user_token)
    infos = wiki_infos + doc_infos
    print(infos)
    return infos, None

throttler = Throttler(rate_limit=100, period=60)
async def main():
    user_token = "u-g4K9iOW4l54qLbdLf.fKrv40nWNx14aNVG204kUwwIBb"
    # wiki_tokens = ["GQ0Owf7EmirsookHOh4cpx4XnMf"]
    # stats = await get_wiki_info(wiki_tokens, user_token)
    urls = [
        "https://bytedance.larkoffice.com/wiki/Is5WwlqG1iIkA5kVfwdcVhSMnBe",
        "https://bytedance.larkoffice.com/wiki/MImZwhOfuisCC8kip9icDdcanVb"
    ]
    stats = await get_document_statistics_async_v2(urls, user_token)
    pass

# 示例使用
if __name__ == "__main__":
    # root = mock_node("1")
    # qNodes = asyncio.Queue()
    # task = walk_tree(root, mock_get_children, "user_token", qNodes)
    # asyncio.get_event_loop().run_until_complete(task)
    
    asyncio.run(main())
    