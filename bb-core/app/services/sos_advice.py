"""
BB-Core — Nối Ghép nguồn với SOS.

Trước module này, hai tính năng chạy song song mà không biết gì về nhau: nhân
viên tìm nguồn xong, thấy thiếu, rồi phải tự nhớ sang mục SOS mở lời kêu gọi —
và tự nhớ điền lại nhóm máu, chế phẩm, cơ sở. Không có gì nhắc, nên bước đó dễ
rơi đúng lúc đang cuống.

Thứ tự đã chốt: **TÌM KHO TRƯỚC, HUY ĐỘNG NGƯỜI HIẾN SAU** — và lý do là thời
gian, không phải sở thích. Một đơn vị máu vừa lấy phải qua sàng lọc bắt buộc
(HIV, HBV, HCV, giang mai — Điều 14–15 TT 26/2013), tách chế phẩm, định nhóm,
rồi phản ứng hoà hợp: nhanh nhất cũng vài giờ. Máu trong kho viện khác đã qua
hết các bước đó, chỉ còn hoà hợp và vận chuyển — ETA nội thành dưới 10 phút.

Nên với mức "Cấp cứu — cần trong 2 giờ", huy động người hiến KHÔNG kịp cứu chính
ca đó. SOS có nghĩa ở bốn chỗ, và mã dưới đây phân biệt đúng bốn chỗ ấy:

  1. Không đủ nguồn tương hợp   → phải gọi người, dù chậm vẫn là đường duy nhất
  2. Nhóm hiếm (RhD âm ~0,1%)   → kho mỏng, gọi để có đường lui
  3. Rút xong kho tụt sát ngưỡng → gọi để BÙ, cứu ca SAU chứ không phải ca này
  4. Đủ và kho vẫn dày           → không gọi, đừng làm phiền người hiến

Điểm (3) là chỗ dễ bỏ sót nhất: điều chuyển thành công không có nghĩa là xong.
Rút một đơn vị O− khỏi kho thành phố là làm mỏng đi lớp phòng thủ cho ca kế
tiếp, và không ai đang cuống mà nhớ ra điều đó.
"""

from dataclasses import dataclass, field
from typing import Optional

# Khi tồn còn lại chỉ hơn ngưỡng an toàn dưới mức này thì coi là "sát ngưỡng".
# 1.25 = còn dư chưa tới 25% trên ngưỡng.
NEAR_THRESHOLD_FACTOR = 1.25


@dataclass
class SOSAdvice:
    """Khuyến nghị có nên mở lời kêu gọi hay không, kèm lý do đọc được."""

    # required | advised | not_needed
    action: str
    reason: str

    # Mức khẩn đề nghị cho lời kêu gọi, nếu có mở.
    urgency: Optional[str] = None
    # Số người hiến nên gọi.
    target_count: int = 0
    # Vòng nên bắt đầu — bù kho thì đi rộng ngay, không cần gấp.
    start_ring: int = 0

    # Những cơ sở sẽ tụt sát ngưỡng an toàn sau khi rút.
    depleted_facilities: list[str] = field(default_factory=list)

    @property
    def should_open(self) -> bool:
        return self.action in ("required", "advised")


def advise(
    *,
    qty_needed: int,
    compatible_count: int,
    urgency: str,
    rh: Optional[str],
    taken_by_facility: dict[str, int],
    stock_by_facility: dict[str, int],
    thresholds_by_facility: dict[str, int],
) -> SOSAdvice:
    """
    Quyết định có nên mở SOS sau khi đã tìm nguồn trong kho.

    `taken_by_facility` là số đơn vị sẽ rút từ mỗi cơ sở nếu duyệt điều chuyển —
    tính trên các ứng viên xếp hạng cao nhất, không phải toàn bộ kho.
    """
    # ── (1) Không đủ nguồn ────────────────────────────────────────
    if compatible_count == 0:
        return SOSAdvice(
            action="required",
            reason="Không có đơn vị tương hợp nào trong toàn cụm. "
                   "Huy động người hiến là đường duy nhất còn lại.",
            urgency=urgency,
            target_count=max(qty_needed, 1),
            start_ring=0,
        )

    if compatible_count < qty_needed:
        thieu = qty_needed - compatible_count
        return SOSAdvice(
            action="required",
            reason=f"Kho chỉ đáp ứng được {compatible_count}/{qty_needed} đơn vị. "
                   f"Cần huy động người hiến cho {thieu} đơn vị còn lại.",
            urgency=urgency,
            target_count=thieu,
            start_ring=0,
        )

    # ── (3) Rút xong kho nguồn có tụt sát ngưỡng không? ───────────
    #
    # Kiểm TRƯỚC nhóm hiếm, vì đây là lý do cụ thể hơn: nó chỉ đúng ra cơ sở nào
    # sắp mỏng, còn "nhóm hiếm" chỉ là cảnh báo chung.
    depleted = []
    for fid, taken in taken_by_facility.items():
        stock = stock_by_facility.get(fid)
        threshold = thresholds_by_facility.get(fid)
        if stock is None or threshold is None:
            continue
        if stock - taken < threshold * NEAR_THRESHOLD_FACTOR:
            depleted.append(fid)

    if depleted:
        return SOSAdvice(
            action="advised",
            reason="Điều chuyển được, nhưng rút xong thì kho nguồn tụt sát ngưỡng "
                   "an toàn. Nên mở lời kêu gọi mức thấp để BÙ lại — việc này cứu "
                   "ca sau, không phải ca đang xử lý.",
            # Bù kho thì KHÔNG khẩn: người hiến tới trong ngày là được, và gắn
            # nhãn cấp cứu cho việc không cấp cứu sẽ làm nhãn đó mất thiêng.
            urgency="routine",
            target_count=max(qty_needed, 2),
            # Đi rộng ngay từ đầu: không vội thì không cần vòng hẹp.
            start_ring=2,
            depleted_facilities=depleted,
        )

    # ── (2) Nhóm hiếm ─────────────────────────────────────────────
    if rh == "-":
        return SOSAdvice(
            action="advised",
            reason="Đủ nguồn lần này, nhưng RhD âm chỉ chiếm khoảng 0,1% dân số "
                   "Việt Nam nên kho luôn mỏng. Nên mở lời kêu gọi mức thấp để "
                   "dựng sẵn đường lui.",
            urgency="routine",
            target_count=2,
            start_ring=2,
        )

    # ── (4) Đủ và kho vẫn dày ─────────────────────────────────────
    return SOSAdvice(
        action="not_needed",
        reason=f"Kho đáp ứng đủ {qty_needed} đơn vị và nguồn cho vẫn trên ngưỡng "
               "an toàn. Chưa cần làm phiền người hiến.",
    )
