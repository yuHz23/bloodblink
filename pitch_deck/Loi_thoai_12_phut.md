# Lời thoại pitch 12 phút — BLOODBLINK

**Thời lượng:** 12:00 cho slide 1–13. Slide 14 là phụ lục nguồn, dùng khi hội đồng hỏi.  
**Cách trình bày:** nói rõ đây là prototype và mô phỏng; không mô tả số liệu giả định như kết quả bệnh viện.

## Slide 1 — BLOODBLINK (0:30)

BLOODBLINK là nền tảng điều phối máu liên viện. Chúng tôi kết nối ba mắt xích vốn thường được nhìn riêng: tồn kho giữa các cơ sở, nhân viên điều phối và mạng lưới người hiến. Ý tưởng trung tâm rất đơn giản: nhìn thấy nguồn phù hợp sớm hơn, điều chuyển có thứ tự, và chỉ huy động người hiến cho phần thiếu còn lại. Hôm nay tôi sẽ trình bày sản phẩm hiện có, điều gì đã được mô phỏng, và kế hoạch kiểm chứng an toàn trong một pilot bệnh viện.

## Slide 2 — Bài toán (1:05)

Theo báo cáo của Bộ Y tế, năm 2025 cả nước vận động và tiếp nhận gần 1,75 triệu đơn vị máu, đạt 94% kế hoạch. Con số này cho thấy quy mô của hệ thống, nhưng tự nó không chứng minh thiếu máu hay thất thoát. Vấn đề chúng tôi muốn kiểm chứng là bài toán điều phối: khi một cơ sở thiếu một nhóm máu hoặc chế phẩm cụ thể, người điều phối có thể khó nhìn cùng lúc nguồn ở nơi khác, hạn dùng, tương hợp và thời gian giao. Nếu phải chuyển sang gọi điện thủ công, quy trình phụ thuộc vào từng người và khó để lại dấu vết nhất quán. Đây là giả thuyết sản phẩm, cần phỏng vấn và đo tại bệnh viện trước khi khẳng định mức độ phổ biến.

## Slide 3 — Giải pháp (0:55)

BLOODBLINK áp dụng thứ tự “tìm kho trước, gọi người hiến sau”. Bệnh viện nhập cơ sở nhận, nhóm ABO/RhD, chế phẩm, số lượng, thời điểm cần và mức khẩn. Bộ điều phối lọc nguồn tương hợp, ưu tiên hạn dùng và ETA, đồng thời gửi đề nghị điều chuyển có thời hạn. Cơ sở nguồn quyết định nhận hay từ chối và đơn vị được giữ khi chấp nhận. Nếu kho chỉ đáp ứng một phần, hệ thống mở SOS cho đúng phần còn thiếu. Mỗi bước đều nằm trong một ca để nhân viên theo dõi được trạng thái.

## Slide 4 — Luồng ca minh họa (0:55)

Đây là tình huống minh họa, không phải ca thật. Bệnh viện A cần bốn đơn vị RBC O+ trước 14 giờ. BB-Core rà tồn kho đã được chia sẻ, lọc tương hợp, hạn dùng và ETA. Các bệnh viện nguồn nhận offer và tự phản hồi. Giả sử ba đơn vị được xác nhận: hệ thống giữ lại đúng một đơn vị còn thiếu để kích hoạt SOS. Sau đó điều phối viên theo dõi tuyến giao, người nhận lời và lịch sử thay đổi trên cùng một bản đồ. Mục tiêu là tránh gọi cộng đồng cho lượng mà kho liên viện đã có.

## Slide 5 — MVP (0:55)

Repository hiện có bốn phần ghép với nhau. BB-Console là bản đồ và bảng điều phối cho cơ sở y tế. BB-Core chạy API, ghép tương hợp, quản lý offer và lịch SOS. BB-SOS là ứng dụng người hiến để đăng ký và phản hồi lời mời. BB-Box là firmware ESP32-S3 đọc cảm biến nhiệt, tách ngưỡng bảo quản khỏi ngưỡng vận chuyển. Đây là phạm vi phần mềm trong repository, không phải khẳng định các thiết bị đã được hiệu chuẩn hoặc triển khai ở bệnh viện. Thông báo FCM chưa cấu hình; cần kiểm tra tích hợp và quy trình thực tế cùng đơn vị pilot.

## Slide 6 — Mô phỏng (1:10)

README báo cáo một mô phỏng 90 ngày, tám bệnh viện TP.HCM: tỷ lệ đáp ứng tăng từ 97,7 lên 99,8%; khớp chính xác từ 94,2 lên 99%; thời gian trung bình từ năm giờ xuống bảy phút; và số đơn vị hủy giảm từ 1.095 xuống 695. Xin nhấn mạnh: đây không phải dữ liệu vận hành. Trong mã mô phỏng, baseline chỉ tìm nguồn tại cơ sở và gán thời gian gọi điện từ bốn đến sáu giờ; hệ thống mới tìm cả mạng lưới, dùng tốc độ khẩn giả định 40 km/h, tỷ lệ hao hụt lạnh 10% so với 4%, và pool 200 người hiến giả lập. Vì vậy đây là tín hiệu để định hướng pilot, không phải bằng chứng tác động hay lời hứa lâm sàng.

## Slide 7 — Kiến trúc (1:00)

Kiến trúc gồm ba bề mặt: BB-Console cho nhân viên, BB-SOS cho người hiến và BB-Box cho cảm biến. Các bề mặt gọi API REST/JSON có xác thực để tới BB-Core. Core chạy FastAPI và dùng PostgreSQL/PostGIS; bên trong có logic ABO/RhD, FEFO, routing ETA, offer điều chuyển, bộ lập lịch SOS và nhật ký audit. Code cũng có lớp ánh xạ FHIR, nhưng chúng tôi chưa tuyên bố đã kết nối HIS, LIS hay EMR của bất kỳ bệnh viện nào. Tích hợp thật cần mapping, phân quyền và kiểm thử riêng theo từng đơn vị.

## Slide 8 — An toàn và riêng tư (1:00)

Trong y tế, tốc độ không được đánh đổi bằng an toàn. Hệ thống chỉ xếp hạng nguồn; nhân viên y tế giữ quyền xác nhận chuyên môn. Quy tắc tương hợp, thời gian đủ điều kiện hiến và phân quyền được áp dụng ở backend. Với vị trí người hiến, app chuyển thành ô H3 xấp xỉ 1,2 km, có thời hạn bốn giờ; ô quá ít người sẽ bị ẩn. Danh tính liên hệ chỉ được chia sẻ khi người hiến chủ động nhận lời, và thao tác truy cập được ghi audit. Phần cảm biến cần hiệu chuẩn, quy trình bàn giao và xác nhận chuyên môn theo quy định trước khi dùng thật.

## Slide 9 — Khác biệt (0:55)

Chúng tôi không tuyên bố chưa có giải pháp nào trên thị trường làm các phần riêng lẻ. Bệnh viện có thể đã dùng hệ thống tồn kho tại chỗ; nhân viên có thể phối hợp qua điện thoại; nhiều ứng dụng tập trung vào tuyển người hiến. Khác biệt thiết kế của BLOODBLINK là ghép các bước thành một luồng: tìm kho xuyên cơ sở, đưa ra offer có thời hạn, chuyển phần thiếu sang SOS, và theo dõi chuỗi lạnh. Bảng này so sánh các nhóm quy trình thay thế, không phải đánh giá vendor. Trước thương mại hóa, chúng tôi cần hỏi bệnh viện họ đang dùng gì và phần nào thực sự còn trống.

## Slide 10 — Khách hàng và mô hình kinh doanh (0:55)

Bên mua là mạng lưới bệnh viện, trung tâm máu hoặc nhóm bệnh viện có nhu cầu phối hợp. Người dùng hằng ngày là điều phối viên và nhân viên quản lý kho. Người hiến không trả phí. Mô hình doanh thu đề xuất gồm thuê bao theo cơ sở hoặc mạng lưới, phí triển khai và tích hợp ban đầu, và tùy chọn thiết bị BB-Box cùng bảo trì. Chúng tôi chưa có giá bán hay hợp đồng trong repository, nên các con số ở slide tài chính chỉ là kịch bản để kiểm tra mức sẵn sàng chi trả và chi phí triển khai.

## Slide 11 — Go-to-market (0:55)

Kế hoạch vào thị trường bắt đầu bằng bán hàng trực tiếp trong một cụm bệnh viện, không chạy quảng cáo người dùng đại trà. Trong ba tháng đầu, nhóm tìm ba bệnh viện neo và cố vấn truyền máu, xác định dữ liệu tối thiểu và thống nhất quy trình. Sáu tháng tiếp theo chạy pilot có kiểm soát tại ba cơ sở, đo baseline, thời gian tìm nguồn, tỷ lệ offer được nhận, tỷ lệ đáp ứng đúng hạn, hao hụt và phản hồi SOS. Nếu quy trình an toàn và có người dùng muốn gia hạn, mở rộng mục tiêu lên tám cơ sở trong năm đầu. Mọi KPI đều phải lấy từ dữ liệu vận hành được bệnh viện chấp thuận.

## Slide 12 — Tài chính (1:05)

Kịch bản giả định của năm đầu là tám cơ sở, trung bình sáu tháng trả phí, năm triệu đồng mỗi cơ sở mỗi tháng, cộng mười lăm triệu phí triển khai một lần. Doanh thu mục tiêu khi đó là 360 triệu đồng. Chi phí ước tính khoảng 959 triệu, gồm sản phẩm-kỹ thuật, tích hợp, cloud và bảo mật, tám thiết bị pilot, bán hàng-đào tạo, tư vấn lâm sàng-pháp lý và dự phòng 10%. Năm đầu dự kiến lỗ vận hành khoảng 599 triệu; chưa đặt mục tiêu hòa vốn. Đề nghị 800 triệu đồng gồm bù khoảng chênh lệch và vốn lưu động nếu chu kỳ thu phí kéo dài. Đây là giả định lập kế hoạch, cần chốt lại bằng báo giá và cam kết thực tế.

## Slide 13 — Đội ngũ, lộ trình và đề nghị (0:40)

Nền tảng kỹ thuật đã có trong repository; để chuyển sang vận hành, chúng tôi cần đồng hành với chuyên gia truyền máu, đầu mối công nghệ bệnh viện và đơn vị pilot. Lộ trình là ba tháng chuẩn bị, ba tháng thử tại ba cơ sở, rồi chỉ mở rộng lên tám nếu đạt tiêu chí an toàn và vận hành. Hôm nay chúng tôi đề nghị ba đối tác bệnh viện, một cố vấn chuyên môn truyền máu và nguồn vốn hoặc tài trợ 800 triệu đồng cho 12 tháng. BLOODBLINK không hứa thay đổi kết quả điều trị; chúng tôi đề nghị cơ hội đo xem phối hợp tốt hơn có thể giúp mạng lưới vận hành tốt hơn hay không.

## Slide 14 — Phụ lục nguồn

Không cần trình bày nếu không có câu hỏi. Dùng để dẫn nguồn số liệu năm 2025 và Thông tư 26/2013/TT-BYT; đồng thời chỉ ra giả định mô phỏng, thiếu xác nhận tích hợp và việc chưa có hợp đồng hay báo giá thật.
