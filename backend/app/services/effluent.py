"""出水监测业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "effluent"
REQUIRED_FIELDS = ["监测编号", "采样时间", "出水流量"]
STATUS_ORDER = ["待检测", "检测中", "已达标", "已超标"]
ACTION_RULES = {"开始检测": "检测中", "判定达标": "已达标", "标记超标": "已超标"}
NEGATIVE_ACTIONS = []

# 达标率报表口径：按「采样时间」归属 YYYY-MM 周期，判定沿用列表的监测状态——
# 已达标记达标、已超标记超标，其余状态算未判定，不进达标率分母。
REPORT_PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
REPORT_METRICS = ["出水流量", "化学需氧量", "氨氮浓度", "总磷浓度"]
REPORT_COLUMNS = ["监测编号", "采样时间", *REPORT_METRICS, "达标判定", "监测状态"]


class EffluentService:
    def __init__(self) -> None:
        # 记录每个周期首次导出时间，用于拦下同一周期的重复导出
        self._export_log: dict[str, str] = {}

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("监测编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"出水记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于出水监测可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"出水记录已{action}"

    def build_compliance_report(self, period: str) -> tuple[dict[str, Any] | None, str, int]:
        """汇总指定周期的达标判定并生成报表结构；失败时给出状态码与可读说明。"""
        if not REPORT_PERIOD_PATTERN.match(period):
            return None, f"统计周期「{period}」格式不正确，请按 YYYY-MM 选择（如 2026-09）", 400
        if period in self._export_log:
            first_exported = self._export_log[period]
            return (
                None,
                f"周期 {period} 的达标率报表已于 {first_exported} 导出过，"
                "为避免口径混淆未重复生成；请使用已下载的文件，或更换统计周期",
                409,
            )
        rows = [row for row in store.rows(MODULE) if str(row.get("采样时间", "")).startswith(period)]
        if not rows:
            return None, f"周期 {period} 内没有出水监测数据，未生成达标率报表", 404
        passed = [row for row in rows if row.get("status") == "已达标"]
        failed = [row for row in rows if row.get("status") == "已超标"]
        judged = len(passed) + len(failed)
        exported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report = {
            "period": period,
            "exported_at": exported_at,
            "metrics": REPORT_METRICS,
            "columns": REPORT_COLUMNS,
            "total": len(rows),
            "judged": judged,
            "passed": len(passed),
            "failed": len(failed),
            "rate": f"{len(passed) / judged * 100:.1f}%" if judged else "—",
            "violations": failed,
        }
        self._export_log[period] = exported_at
        return report, f"周期 {period} 的达标率报表已生成", 200

    @staticmethod
    def render_compliance_csv(report: dict[str, Any]) -> str:
        """把报表结构渲染成 CSV：先汇总块，再超标清单块。"""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["出水达标率报表"])
        writer.writerow(["统计周期", report["period"]])
        writer.writerow(["导出时间", report["exported_at"]])
        writer.writerow(["统计指标", "、".join(report["metrics"])])
        writer.writerow(["记录总数", report["total"]])
        writer.writerow(["已判定", report["judged"]])
        writer.writerow(["达标", report["passed"]])
        writer.writerow(["超标", report["failed"]])
        writer.writerow(["达标率", report["rate"]])
        writer.writerow([])
        writer.writerow(["超标清单"])
        writer.writerow(report["columns"])
        for row in report["violations"]:
            writer.writerow([row.get(column, "") for column in report["columns"]])
        if not report["violations"]:
            writer.writerow(["本周期无超标记录"])
        return buffer.getvalue()
