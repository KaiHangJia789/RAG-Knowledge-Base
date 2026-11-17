"""技术支持草稿评测。--validate-only 不调用模型；真实模式会产生 API 用量。"""
import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.support import load_support_dataset, score_support_result  # noqa: E402


def generation_parameters(prompt, config, settings) -> dict:
    """记录客户端实际发送的默认参数；None 温度表示未显式传入。"""
    from app.llm.support_prompts import SUPPORT_SYSTEMS
    support = prompt in SUPPORT_SYSTEMS
    return {
        "max_tokens": settings.LLM_MAX_TOKENS,
        "reasoning_effort": settings.LLM_REASONING_EFFORT or None,
        "thinking_enabled": False if support else settings.EVAL_GEN_THINKING_ENABLED,
        "temperature": config.temperature,
        "json_mode": support,
    }


async def run(args, dataset) -> int:
    from app.config import settings
    from app.llm.support_prompts import REWRITE_PROMPT_VERSION, SUPPORT_SYSTEMS
    from app.rag.support import SUPPORT_PARSER_VERSION
    from app.embedding.dashscope_embedding import DashscopeEmbeddingClient
    from app.llm.observability import flush
    from app.rag.models import RetrievalConfig
    from app.rag.pipeline import RagPipeline
    from app.services.index_service import IndexService

    index = IndexService(DashscopeEmbeddingClient())
    index.load()
    if not index.ready:
        raise ValueError("索引未就绪。请先导入示范语料并构建索引。")
    pipeline = RagPipeline(index_service=index)
    config = RetrievalConfig(prompt_name=args.prompt)
    def fingerprint(path):
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()

    effective_generation = generation_parameters(args.prompt, config, settings)
    run_context = {
        "generation_parameters": effective_generation,
        "generation_parameters_sha256": hashlib.sha256(json.dumps(effective_generation, sort_keys=True).encode("utf-8")).hexdigest(),
        "rewrite_parameters": {"max_tokens": 600, "thinking_enabled": False, "temperature": 0.0,
                               "reasoning_effort": settings.LLM_REASONING_EFFORT or None,
                               "json_mode": True, "timeout_seconds": 8} if args.prompt in SUPPORT_SYSTEMS else None,
        "configured_model": settings.DEEPSEEK_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dim": index.dim,
        "rewrite_prompt_version": REWRITE_PROMPT_VERSION if args.prompt in SUPPORT_SYSTEMS else None,
        "support_parser_version": SUPPORT_PARSER_VERSION if args.prompt in SUPPORT_SYSTEMS else None,
        "support_prompt_sha256": hashlib.sha256(SUPPORT_SYSTEMS[args.prompt].encode("utf-8")).hexdigest() if args.prompt in SUPPORT_SYSTEMS else None,
        "dataset_sha256": fingerprint(args.dataset),
        "index_strategy": index.strategy, "index_size": index.size,
        "index_sha256": fingerprint(index.index_path),
        "metadata_sha256": fingerprint(index.meta_path),
        "viewer_user_id": args.viewer_user_id,
    }
    items = dataset.items[:args.limit] if args.limit else dataset.items
    # 固定版本和配置写入每条结果，不能把结构检查当成正确率。
    args.output.parent.mkdir(parents=True, exist_ok=True)
    failures = 0
    errors = 0
    try:
        # 避免误覆盖历史对比结果。
        with args.output.open("x", encoding="utf-8") as output:
            for item in items:
                record = {"id": item.id, "dataset_version": dataset.version,
                          "prompt_version": args.prompt, "run_context": run_context, "input": item.input.model_dump(),
                          "expected_output": item.expected_output.model_dump(),
                          "metadata": item.metadata.model_dump()}
                try:
                    result = await pipeline.answer(
                        item.input.question, config,
                        history=[m.model_dump() for m in item.input.history] or None,
                        viewer_user_id=args.viewer_user_id,
                    )
                    scores = score_support_result(item, result)
                    record.update(result=result.model_dump(mode="json"), checks=scores)
                    failures += not scores["structural_pass"]
                except Exception as exc:
                    # SDK 异常消息可能有输入或凭据，只记录类型。
                    record["error_type"] = type(exc).__name__
                    errors += 1
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
    finally:
        flush()
    print(f"已完成 {len(items)} 条；结构未通过 {failures} 条；运行错误 {errors} 条。")
    print("语义正确性仍待人工复核；此结果不是产品解决率或正式行业准确率。")
    print(f"结果：{args.output}")
    return 1 if failures or errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "data/eval/support_eval_draft.json")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--viewer-user-id", help="评测账号 ID；始终沿用私有+共享文档权限过滤")
    parser.add_argument("--prompt", choices=["support_answer_v1", "support_answer_v2", "support_answer_v3", "rag_context_cited"], default="support_answer_v3")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports/support-eval.jsonl")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit 必须 >= 0")
    try:
        dataset = load_support_dataset(args.dataset)
        if args.validate_only:
            print(f"草稿校验通过：{len(dataset.items)} 条；预期答案仍需人工复核。未调用模型或数据库。")
            return 0
        if not args.viewer_user_id:
            parser.error("真实评测必须提供 --viewer-user-id；不得使用无范围的全库检索")
        return asyncio.run(run(args, dataset))
    except (ValueError, OSError) as exc:
        print(f"评测无法运行：{type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
