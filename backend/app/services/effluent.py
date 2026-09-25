"""出水监测业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "effluent"
REQUIRED_FIELDS = ["监测编号", "采样时间", "出水流量"]
STATUS_ORDER = ["待检测", "检测中", "已达标", "已超标"]
ACTION_RULES = {"开始检测": "检测中", "判定达标": "已达标", "标记超标": "已超标"}
NEGATIVE_ACTIONS = []
REPORT_INDICATORS = ["出水流量", "化学需氧量", "氨氮浓度", "总磷浓度"]
JUDGED_STATUSES = ("已达标", "已超标")


class EffluentService:
    def __init__(self) -> None:
        # 记录每个周期已导出次数，用于重复导出的兜底说明；内存态，重启即清零。
        self._export_counts: dict[str, int] = {}

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

    def compliance_report(self, *, period: str, keyword: str | None = None) -> dict[str, Any] | None:
        """按周期（YYYY-MM，对齐采样时间）汇总达标判定并给出超标清单。

        与列表页保持同一筛选口径：监测编号关键字过滤后再按周期截取；
        周期内一条记录都没有时返回 None，由路由层转成可读的兜底说明。
        """
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("监测编号", ""))]
        rows = [row for row in rows if str(row.get("采样时间", "")).startswith(period)]
        if not rows:
            return None
        judged = [row for row in rows if row.get("status") in JUDGED_STATUSES]
        passed = [row for row in judged if row.get("status") == "已达标"]
        exceeded = [row for row in rows if row.get("status") == "已超标"]
        rate = f"{len(passed) / len(judged) * 100:.1f}%" if judged else "—"
        indicators = []
        for name in REPORT_INDICATORS:
            values: list[float] = []
            for row in rows:
                try:
                    values.append(float(str(row.get(name, "")).strip()))
                except (TypeError, ValueError):
                    continue  # 样例数据里存在非数值占位，跳过但不影响其它指标
            indicators.append({
                "指标": name,
                "有效读数": len(values),
                "平均值": round(sum(values) / len(values), 2) if values else None,
                "最大值": max(values) if values else None,
            })
        self._export_counts[period] = self._export_counts.get(period, 0) + 1
        return {
            "period": period,
            "keyword": keyword,
            "total": len(rows),
            "pending": len(rows) - len(judged),
            "passed": len(passed),
            "exceeded": len(exceeded),
            "rate": rate,
            "indicators": indicators,
            "exceedances": exceeded,
            "export_count": self._export_counts[period],
        }
