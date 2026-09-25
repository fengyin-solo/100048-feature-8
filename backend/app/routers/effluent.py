"""出水监测接口：维护出水记录，覆盖开始检测、判定达标、标记超标等动作。"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.effluent import EffluentService

router = APIRouter(prefix="/api/effluent", tags=["出水监测"])

service = EffluentService()

LIST_FIELDS = ["监测编号", "采样时间", "出水流量", "化学需氧量", "氨氮浓度", "总磷浓度", "达标判定", "监测状态"]
STATUSES = ["待检测", "检测中", "已达标", "已超标"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按监测编号检索"),
    status: str | None = Query(default=None, description="待检测、检测中、已达标、已超标"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按监测编号与状态过滤出水监测列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/compliance/export")
def export_compliance_report(period: str = Query(default="", description="统计周期，格式 YYYY-MM，如 2026-09")) -> Response:
    """按周期导出出水达标率报表（CSV 下载）：汇总出水流量、化学需氧量、总磷浓度等指标的
    达标判定结果并附超标清单。无数据周期、重复导出、周期格式错误都返回可读说明，不生成空文件。
    路径用两段式，避免被上面的 /{entry_id} 抢占。"""
    report, message, status_code = service.build_compliance_report(period.strip())
    if report is None:
        raise HTTPException(status_code=status_code, detail=message)
    csv_text = service.render_compliance_csv(report)
    filename = quote(f"出水达标率报表_{report['period']}.csv")
    return Response(
        # 带 BOM 的 UTF-8，保证 Excel 直接打开中文不乱码
        content="\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条出水记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"出水记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条出水记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="出水记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条出水记录执行开始检测、判定达标、标记超标；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出出水监测清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "effluent", "total": total, "items": items}
