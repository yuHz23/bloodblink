"""
Khoá logic nối Ghép nguồn với SOS.

Đây là phần mang luận điểm của đồ án — thứ tự kho-trước-người-sau, và ý "mở SOS
để BÙ lại chỗ vừa rút". Nếu ai đó nới các test này thì luận điểm cũng mất theo,
nên mỗi test ghi rõ nó bảo vệ điều gì.
"""

from app.services.sos_advice import advise


def call(**kw):
    """Gọi `advise` với một ca mặc định lành mạnh, ghi đè phần cần thử."""
    base = dict(
        qty_needed=2,
        compatible_count=10,
        urgency="emergency",
        rh="+",
        taken_by_facility={"fac-a": 2},
        stock_by_facility={"fac-a": 500},
        thresholds_by_facility={"fac-a": 50},
    )
    base.update(kw)
    return advise(**base)


class TestKhongDuNguon:
    """Không đủ kho thì PHẢI gọi người, dù chậm vẫn là đường duy nhất."""

    def test_khong_co_don_vi_nao_thi_bat_buoc_mo_sos(self):
        a = call(compatible_count=0)
        assert a.action == "required"
        assert a.should_open
        # Giữ nguyên mức khẩn của ca — đây là cứu chính ca này.
        assert a.urgency == "emergency"
        # Không đủ thì đi từ vòng hẹp nhất, gần nhất tới trước.
        assert a.start_ring == 0

    def test_thieu_mot_phan_thi_chi_goi_phan_thieu(self):
        a = call(qty_needed=5, compatible_count=3)
        assert a.action == "required"
        # Gọi 5 người trong khi kho đã có 3 là làm phiền thừa 3 người.
        assert a.target_count == 2
        assert "3/5" in a.reason


class TestBuLaiKhoVuaRut:
    """
    Điểm đảo ngược cách hiểu thông thường: điều chuyển THÀNH CÔNG vẫn nên mở SOS.

    Rút một đơn vị khỏi kho thành phố là làm mỏng lớp phòng thủ cho ca kế tiếp,
    và không ai đang cuống mà nhớ ra điều đó.
    """

    def test_rut_xong_tut_sat_nguong_thi_khuyen_nghi_bu(self):
        # Còn 55 sau khi rút, ngưỡng 50 → chỉ dư 10%, coi là sát.
        a = call(taken_by_facility={"fac-a": 5},
                 stock_by_facility={"fac-a": 60},
                 thresholds_by_facility={"fac-a": 50})
        assert a.action == "advised"
        assert a.depleted_facilities == ["fac-a"]

    def test_sos_bu_kho_KHONG_duoc_gan_nhan_cap_cuu(self):
        # Ca gốc là cấp cứu, nhưng việc BÙ kho thì không. Gắn nhãn cấp cứu cho
        # việc không cấp cứu sẽ làm nhãn đó mất thiêng với người hiến.
        a = call(urgency="emergency",
                 taken_by_facility={"fac-a": 5},
                 stock_by_facility={"fac-a": 60},
                 thresholds_by_facility={"fac-a": 50})
        assert a.urgency == "routine"
        # Không vội thì đi rộng ngay, không cần quét vòng hẹp trước.
        assert a.start_ring == 2

    def test_kho_van_day_thi_khong_de_xuat_gi(self):
        a = call(taken_by_facility={"fac-a": 2},
                 stock_by_facility={"fac-a": 500},
                 thresholds_by_facility={"fac-a": 50})
        assert a.action == "not_needed"
        assert not a.should_open

    def test_khong_biet_ton_kho_thi_khong_doan_bua(self):
        # Thiếu dữ liệu ngưỡng thì im lặng, đừng cảnh báo hú hoạ.
        a = call(taken_by_facility={"fac-la": 5},
                 stock_by_facility={}, thresholds_by_facility={})
        assert a.action == "not_needed"


class TestNhomHiem:
    """RhD âm chiếm ~0,1% dân số VN nên kho luôn mỏng."""

    def test_rhd_am_thi_khuyen_nghi_du_kho_dang_du(self):
        a = call(rh="-")
        assert a.action == "advised"
        assert a.urgency == "routine"
        assert "0,1%" in a.reason

    def test_rhd_duong_du_kho_thi_thoi(self):
        assert call(rh="+").action == "not_needed"

    def test_thieu_nguon_uu_tien_hon_nhom_hiem(self):
        # Vừa hiếm vừa thiếu thì lý do phải là THIẾU — cụ thể và khẩn hơn.
        a = call(rh="-", compatible_count=0)
        assert a.action == "required"
        assert a.urgency == "emergency"

    def test_tut_nguong_uu_tien_hon_nhom_hiem(self):
        # Cả hai cùng đúng thì báo cái chỉ ra ĐƯỢC cơ sở nào sắp mỏng.
        a = call(rh="-",
                 taken_by_facility={"fac-a": 5},
                 stock_by_facility={"fac-a": 60},
                 thresholds_by_facility={"fac-a": 50})
        assert a.depleted_facilities == ["fac-a"]
        assert "ngưỡng" in a.reason


class TestNhieuCoSo:
    def test_chi_bao_co_so_that_su_sat_nguong(self):
        a = call(taken_by_facility={"fac-a": 5, "fac-b": 5},
                 stock_by_facility={"fac-a": 60, "fac-b": 900},
                 thresholds_by_facility={"fac-a": 50, "fac-b": 50})
        assert a.depleted_facilities == ["fac-a"]
