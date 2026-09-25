"""出水监测接口：维护出水记录，覆盖开始检测、判定达标、标记超标等动作。"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.effluent import EffluentService

router = APIRouter(prefix="/api/effluent", tags=["出水监测"])

service = EffluentService()

LIST_FIELDS = ["监测编号", "采样时间", "出水流量", "化学需氧量", "氨氮浓度", "总磷浓度", "达标判定", "监测状态"]
STATUSES = ["待检测", "检测中", "已达标", "已超标"]
PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


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


@router.get("/compliance-report")
def export_compliance_report(
    period: str = Query(description="统计周期，格式 YYYY-MM，按采样时间归集"),
    keyword: str | None = Query(default=None, description="与列表页一致的监测编号筛选"),
) -> Response:
    """导出达标率报表：汇总周期内达标判定结果，并附超标清单，以 CSV 文件下载。

    文件内容完全由当前查询条件生成，与页面所选周期、筛选保持一致；
    周期内无数据时返回 404 与可读说明，由页面提示而不是生成空文件。
    """
    if not PERIOD_PATTERN.match(period):
        raise HTTPException(status_code=400, detail=f"统计周期「{period}」格式应为 YYYY-MM，例如 2026-09")
    report = service.compliance_report(period=period, keyword=keyword or None)
    if report is None:
        raise HTTPException(status_code=404, detail=f"周期 {period} 内没有出水监测记录，未生成达标率报表")
    filename = f"effluent-compliance-{period}.csv"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Exceedance-Count": str(report["exceeded"]),
        "X-Export-Count": str(report["export_count"]),
    }
    return Response(
        content="\ufeff" + _render_report_csv(report),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


def _render_report_csv(report: dict[str, Any]) -> str:
    """把报表结果渲染成 CSV 文本；数值缺失时写「—」，保证 Excel 打开不乱码、不断列。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["出水监测达标率报表"])
    writer.writerow(["统计周期", report["period"]])
    writer.writerow(["监测编号筛选", report["keyword"] or "全部"])
    writer.writerow(["生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow([])
    writer.writerow(["达标判定汇总"])
    writer.writerow(["周期内记录数", report["total"]])
    writer.writerow(["未判定（待检测/检测中）", report["pending"]])
    writer.writerow(["已达标", report["passed"]])
    writer.writerow(["已超标", report["exceeded"]])
    writer.writerow(["达标率", report["rate"]])
    writer.writerow([])
    writer.writerow(["指标汇总", "有效读数", "平均值", "最大值"])
    for item in report["indicators"]:
        writer.writerow([
            item["指标"],
            item["有效读数"],
            item["平均值"] if item["平均值"] is not None else "—",
            item["最大值"] if item["最大值"] is not None else "—",
        ])
    writer.writerow([])
    writer.writerow(["超标清单"])
    writer.writerow(LIST_FIELDS)
    if report["exceedances"]:
        for row in report["exceedances"]:
            writer.writerow([row.get(field, "—") for field in LIST_FIELDS])
    else:
        writer.writerow(["本周期无超标记录"])
    return buffer.getvalue()


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
