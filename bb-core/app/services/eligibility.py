"""
BB-Core — Khoảng cách giữa hai lần hiến (Điều 6 TT 26/2013/TT-BYT).

Trước đây logic này nằm rải rác trong `app/api/sos.py` và trong app Flutter.
Đưa về một chỗ để server là nơi phán quyết cuối cùng — app chỉ hiển thị.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

# Điều 6: máu toàn phần / khối hồng cầu = 12 tuần, tiểu cầu / huyết tương = 2 tuần
WB_RBC_MIN_DAYS = 84
PLT_PLASMA_MIN_DAYS = 14

MIN_DAYS_BY_COMPONENT: dict[str, int] = {
    "WB":   WB_RBC_MIN_DAYS,
    "RBC":  WB_RBC_MIN_DAYS,
    "PLT":  PLT_PLASMA_MIN_DAYS,
    "FFP":  PLT_PLASMA_MIN_DAYS,
    "CRYO": PLT_PLASMA_MIN_DAYS,
    "GRAN": 7,   # ≤3 lần/7 ngày → lấy 7 ngày làm biên an toàn
}


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Postgres trả về datetime naive — coi như UTC để trừ được với now()."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def donation_eligibility(
    last_donation_at: Optional[datetime],
    component: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """
    Tính điều kiện hiến của một người.

    `component` là chế phẩm đang cần (WB/RBC/PLT/FFP/CRYO). Nếu không truyền,
    `eligible` lấy mốc chặt nhất (12 tuần) cho an toàn.

    Trả về dict phẳng để ghép thẳng vào JSON response.
    """
    now = now or datetime.now(timezone.utc)
    last = _as_utc(last_donation_at)

    days_since = (now - last).days if last else None
    eligible_wb = days_since is None or days_since >= WB_RBC_MIN_DAYS
    eligible_plt = days_since is None or days_since >= PLT_PLASMA_MIN_DAYS

    min_days = MIN_DAYS_BY_COMPONENT.get((component or "WB").upper(), WB_RBC_MIN_DAYS)
    eligible = days_since is None or days_since >= min_days

    reason = None
    next_eligible_at = None
    if not eligible and last is not None:
        next_eligible_at = last + timedelta(days=min_days)
        remaining = min_days - (days_since or 0)
        reason = (
            f"Chưa đủ khoảng cách hiến: cần {min_days} ngày cho {component or 'WB'}, "
            f"còn {remaining} ngày (Điều 6 TT 26/2013/TT-BYT)"
        )

    return {
        "days_since_donation": days_since,
        "eligible": eligible,
        "eligible_wb_rbc": eligible_wb,
        "eligible_plt_plasma": eligible_plt,
        "ineligible_reason": reason,
        "next_eligible_at": next_eligible_at,
    }


def min_days_for(component: Optional[str]) -> int:
    """Số ngày tối thiểu giữa hai lần hiến cho một chế phẩm."""
    return MIN_DAYS_BY_COMPONENT.get((component or "WB").upper(), WB_RBC_MIN_DAYS)


def eligible_cutoff(component: Optional[str] = None,
                    now: Optional[datetime] = None) -> datetime:
    """
    Mốc thời gian để lọc NGAY TRONG SQL: người hiến đủ điều kiện là người có
    `last_donation_at` rỗng hoặc <= mốc này.

    Cần lọc ở tầng SQL vì `LIMIT` chạy trước mọi phép lọc bằng Python — lọc sau
    thì con số trả về là "số người đủ điều kiện trong N người đầu tiên", khiến
    vòng rộng hơn có thể ra ÍT người hơn vòng hẹp.
    """
    now = now or datetime.now(timezone.utc)
    return now - timedelta(days=min_days_for(component))
