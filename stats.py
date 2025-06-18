import asyncio
import json
from typing import List, Dict, Any, Optional, Iterator
from urllib.parse import urlparse

import lark_oapi as lark
from lark_oapi.api.drive.v1 import GetFileStatisticsRequest, GetFileStatisticsResponse
from lark_oapi.api.drive.v1.model import Meta, MetaRequest, RequestDoc
from lark_oapi.api.drive.v1.resource.meta import (
    BatchQueryMetaRequest,
    BatchQueryMetaResponse,
)
from lark_oapi.api.wiki.v2 import (
    GetNodeSpaceRequest,
    GetNodeSpaceResponse,
    ListSpaceNodeRequest,
    ListSpaceNodeResponse,
    Node,
)

from init import (
    client,
    logger,
)


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


from asyncio_throttle import Throttler  # 导入现成限流器


def throttle(rate_limit: int, period: int):
    """限流装饰器：限制异步函数的调用频率"""

    def decorator(func):
        throttler_instance = Throttler(rate_limit, period)

        async def wrapper(*args, **kwargs):
            async with throttler_instance:
                return await func(*args, **kwargs)

        return wrapper

    return decorator


async def batch_get_stats_async(
    docs: List[RequestDoc], user_token: str
) -> Dict[RequestDoc, Any]:
    """异步批量获取文档统计信息

    Args:
        file_tokens: 包含(file_token, file_type)元组的列表
        user_token: 用户token

    Returns:
        以(file_token, file_type)为key的统计信息字典
    """
    semaphore = asyncio.Semaphore(100)
    results = {}

    async def get_single_stats(doc: RequestDoc):
        async with semaphore:
            try:
                # 使用同步API，但在异步环境中调用
                loop = asyncio.get_event_loop()
                stats = await loop.run_in_executor(
                    None, get_file_stats, doc.doc_token, doc.doc_type, user_token
                )
                return doc, stats
            except Exception as e:
                logger.error(f"获取统计信息失败 ({doc}): {e}")
                return doc, None

    # 创建所有任务
    tasks = [get_single_stats(doc) for doc in docs]

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


def get_file_stats(
    file_token: str, file_type: str, user_token: str = None
) -> Optional[Any]:
    """获取文档统计信息

    Args:
        file_token: 文件token
        file_type: 文件类型，如'wiki'、'docx'等
        user_token: 用户token

    Returns:
        统计信息对象，如果获取失败则返回None
    """
    request = (
        GetFileStatisticsRequest.builder()
        .file_token(file_token)
        .file_type(file_type)
        .build()
    )
    options = lark.RequestOption.builder().user_access_token(user_token).build()

    try:
        response: GetFileStatisticsResponse = client.drive.v1.file_statistics.get(
            request, options
        )
        if not response.success():
            logger.error(
                f"获取文档统计信息失败 (file_token: {file_token}, type: {file_type}): {response.code} {response.msg}"
            )
            return None

        stats = response.data.statistics
        logger.debug(
            f"统计信息 (token: {file_token}, type: {file_type}): stats: {vars(stats)}"
        )
        return stats
    except Exception as e:
        logger.exception(
            f"获取文档统计信息异常 (file_token: {file_token}, type: {file_type}): {e}"
        )
        return None


# ✅ 支持流式输出的并发 BFS（适用于树结构）
async def walk_tree_concurrent(roots: list[Node], user_token: str) -> Node:
    q_nodes = asyncio.Queue[Node]()
    q_parents = asyncio.Queue[Node]()

    async def worker():
        node = await q_parents.get()
        await q_nodes.put(node)
        # API调用前进行QPS限流
        # async with throttler:
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
    batch: List[Node] = []
    async for item in iter:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    # 最后一批不足 batch_size，也输出
    if batch[0]:
        yield batch


async def get_wiki_node(token: str, user_token: str) -> Optional[Node]:
    """获取根节点信息

    Args:
        root_node_token: 根节点token

    Returns:
        根节点信息对象
    """
    node_info_request = (
        GetNodeSpaceRequest.builder().token(token).obj_type("wiki").build()
    )
    node_info_options = (
        lark.RequestOption.builder().user_access_token(user_token).build()
    )

    try:
        node_info_resp: GetNodeSpaceResponse = await client.wiki.v2.space.aget_node(
            node_info_request, node_info_options
        )
        if (
            not node_info_resp.success()
            or not node_info_resp.data
            or not node_info_resp.data.node
        ):
            logger.error(f"无法获取根节点信息: {token}")
            return None

        return node_info_resp.data.node
    except Exception as e:
        logger.exception(f"获取根节点信息时发生异常: {e}")
        return None


async def get_wiki_info(tokens: List[str], user_token: str) -> List[Dict]:
    roots = [await get_wiki_node(token, user_token) for token in tokens]
    async_gen = walk_tree_concurrent(roots, user_token)
    res = []
    async for batch in batcher(async_gen, batch_size=200):
        docs = [
            RequestDoc.builder().doc_token(doc.obj_token).doc_type(doc.obj_type).build()
            for doc in batch
        ]
        infos = await get_doc_info(docs, user_token)
        res += infos
    return res


async def get_doc_info(docs: List[RequestDoc], user_token: str) -> List[Dict]:
    stats_task = batch_get_stats_async(docs, user_token)
    meta_task = batch_get_meta_async(docs, user_token)
    stats_dict, metas = await asyncio.gather(stats_task, meta_task)
    meta_dict = {meta.doc_token: meta for meta in metas}
    res = []
    for doc in docs:
        stat = stats_dict.get(doc)
        meta = meta_dict.get(doc.doc_token)
        if not stat or not meta:
            logger.error(f"Doc failed {vars(doc)}")
            continue
        res.append(
            {
                "title": meta.title,
                "type": meta.doc_type,
                "token": meta.doc_token,
                "source_url": f"https://bytedance.larkoffice.com/{meta.doc_type}/{meta.doc_token}",
                "uv": stat.uv,
                "pv": stat.pv,
                "like_count": max(stat.like_count, 0),
                "timestamp": meta.latest_modify_time,
                "uv_today": stat.uv_today,
                "pv_today": stat.pv_today,
                "like_count_today": stat.like_count_today,
                "update_time": meta.latest_modify_time,
            }
        )
        logger.debug(f"Doc {vars(meta)}：{vars(stat)}")
    return res


@throttle(100, 60)
async def get_children(parent: Node, user_token: str) -> List[Node]:
    all_nodes = []
    page_token = None
    space_id = parent.space_id
    while True:
        # 构建请求
        builder = (
            ListSpaceNodeRequest.builder()
            .space_id(space_id)
            .page_size(50)
            .parent_node_token(parent.node_token)
        )
        if page_token:
            builder.page_token(page_token)

        request = builder.build()
        options = lark.RequestOption.builder().user_access_token(user_token).build()

        try:
            response: ListSpaceNodeResponse = await client.wiki.v2.space_node.alist(
                request, options
            )
            if not response.success():
                logger.error(
                    f"扫描Wiki文档失败 (space_id: {space_id}, parent: {parent.node_token}): {response.code} {response.msg}"
                )
                break

            # 处理返回的节点
            if response.data and response.data.items:
                for item in response.data.items:
                    all_nodes.append(item)
                    logger.debug(
                        f"{item.title} (token: {item.node_token}, type: {item.obj_type})"
                    )
            # 处理分页
            if response.data and response.data.has_more:
                page_token = response.data.page_token
            else:
                break
        except Exception as e:
            logger.exception(
                f"扫描Wiki文档异常 (space_id: {space_id}, parent: {parent.node_token}): {e}"
            )
            break
    return all_nodes


def parse_doc_url(url: str) -> RequestDoc:
    try:
        # 解析URL
        parsed = urlparse(url)

        # 验证域名
        if not parsed.netloc.endswith("larkoffice.com"):
            logger.error(f"无效的飞书文档URL: '{url}'，域名必须是larkoffice.com")
            return None

        # 分割路径部分
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2:
            logger.error(f"无法从URL '{url}' 中解析出有效的文件类型和Token")
            return None

        file_type = path_parts[0]
        file_token = path_parts[1]

        return RequestDoc.builder().doc_type(file_type).doc_token(file_token).build()

    except Exception as e:
        logger.exception(f"解析URL时发生异常: {e}")
        return None, None


async def get_document_statistics_async(urls: List[str], user_token: str) -> List[Dict]:
    docs = [parse_doc_url(url) for url in urls]
    infos = []
    wikis = list(filter(lambda doc: doc.doc_type == "wiki", docs))
    if len(wikis) > 0:
        wiki_tokens = list(map(lambda doc: doc.doc_token, wikis))
        wiki_infos = await get_wiki_info(wiki_tokens, user_token)
        infos += wiki_infos
    non_wikis = list(filter(lambda doc: doc.doc_type != "wiki", docs))
    if len(non_wikis) > 0:
        doc_infos = await get_doc_info(non_wikis, user_token)
        infos += doc_infos
    return infos, None


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
        batch_docs = docs[i : i + BATCH_SIZE]
        # 构造请求对象
        request: BatchQueryMetaRequest = (
            BatchQueryMetaRequest.builder()
            .user_id_type("open_id")
            .request_body(
                MetaRequest.builder().request_docs(batch_docs).with_url(False).build()
            )
            .build()
        )
        try:
            options = lark.RequestOption.builder().user_access_token(user_token).build()
            response: BatchQueryMetaResponse = await client.drive.v1.meta.abatch_query(
                request, options
            )

            # 处理失败返回
            if not response.success():
                error_msg = f"client.drive.v1.meta.batch_query failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
                if response.raw and response.raw.content:
                    try:
                        error_detail = json.loads(response.raw.content)
                        error_msg += f", resp: \n{json.dumps(error_detail, indent=4, ensure_ascii=False)}"
                    except:
                        error_msg += f", raw content: {response.raw.content}"

                logger.error(error_msg)
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


async def main():
    user_token = "u-g4K9iOW4l54qLbdLf.fKrv40nWNx14aNVG204kUwwIBb"
    # wiki_tokens = ["GQ0Owf7EmirsookHOh4cpx4XnMf"]
    # stats = await get_wiki_info(wiki_tokens, user_token)
    urls = [
        "https://bytedance.larkoffice.com/wiki/Is5WwlqG1iIkA5kVfwdcVhSMnBe",
        "https://bytedance.larkoffice.com/wiki/MImZwhOfuisCC8kip9icDdcanVb",
    ]
    stats = await get_document_statistics_async(urls, user_token)
    pass


# 示例使用
if __name__ == "__main__":
    asyncio.run(main())
