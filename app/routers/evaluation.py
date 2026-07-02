# app/routers/evaluation.py
"""
评估 API 端点

支持手动触发离线评估和查看历史报告。
"""
import json
import os
import time
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.logger import get_logger
from app.core.auth import get_current_user
from app.db.models import User
from app.evaluation.runner import evaluate_full

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/evaluation", tags=["评估"])

DEFAULT_DATASET = "dataset/eval_dataset_ip_customs_balanced_30.json"
DEFAULT_RESULTS_DIR = "eval_results"


class EvalRequest(BaseModel):
    dataset_path: str = DEFAULT_DATASET
    knowledge_id: int
    output_path: Optional[str] = None
    compare_baseline: Optional[str] = None
    use_ragas: bool = True


@router.post("/run", summary="触发离线评估")
def run_evaluation(
    req: EvalRequest,
    current_user: User = Depends(get_current_user),
):
    """触发完整评估，返回指标报告"""
    if not os.path.exists(req.dataset_path):
        raise HTTPException(status_code=400, detail=f"数据集文件不存在: {req.dataset_path}")

    output_path = req.output_path or os.path.join(
        DEFAULT_RESULTS_DIR,
        f"eval_{int(time.time())}.json",
    )

    logger.info(f"用户 {current_user.id} 触发评估: dataset={req.dataset_path}")

    try:
        result = evaluate_full(
            knowledge_id=req.knowledge_id,
            dataset_path=req.dataset_path,
            output_path=output_path,
            compare_baseline=req.compare_baseline,
            use_ragas=req.use_ragas,
        )
    except Exception as e:
        logger.error(f"评估执行失败: {e}")
        raise HTTPException(status_code=500, detail=f"评估执行失败: {str(e)}")

    return {
        "status": "ok",
        "output_path": output_path,
        "summary": {
            "n_samples": result.get("n_samples"),
            "retrieval": result.get("retrieval"),
            "ragas": result.get("ragas"),
            "regression": result.get("regression"),
        },
    }


@router.get("/reports", summary="历史评估报告列表")
def list_reports(
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=10, ge=1, le=100),
):
    """返回最近的历史评估报告列表"""
    results_dir = DEFAULT_RESULTS_DIR
    if not os.path.isdir(results_dir):
        return {"reports": []}

    reports = []
    for fname in sorted(os.listdir(results_dir), reverse=True):
        if fname.endswith(".json"):
            fpath = os.path.join(results_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                reports.append({
                    "file": fname,
                    "timestamp": data.get("timestamp"),
                    "n_samples": data.get("n_samples"),
                    "dataset": data.get("dataset"),
                    "type": data.get("type"),
                })
            except Exception:
                reports.append({"file": fname, "error": "无法解析"})
            if len(reports) >= limit:
                    break

    return {"reports": reports}
