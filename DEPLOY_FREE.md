# Chạy BB-Core miễn phí

## Cấu hình đã chuẩn bị

- API FastAPI dùng [Dockerfile](bb-core/Dockerfile).
- Backend tự tạo các bảng còn thiếu khi khởi động; PostGIS cần bật một lần trong PostgreSQL trước lần chạy đầu tiên.
- URL PostgreSQL dạng `postgresql://` được chuyển sang driver `asyncpg`; hỗ trợ bật TLS qua `DATABASE_SSL=true`.

## Tạo môi trường Northflank

1. Tạo tài khoản Northflank, chọn gói Developer Sandbox, rồi tạo project ở vùng **US Central**. Theo danh sách hiện tại, đây là một trong các vùng có PostgreSQL miễn phí. Vùng project không đổi được sau khi tạo.
2. Tạo PostgreSQL addon, bật TLS và giữ kết nối database ở chế độ riêng tư trong cùng project. Từ kết nối quản trị của addon, bật PostGIS một lần:

   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   ```

3. Tạo service từ repo GitHub, chọn thư mục `bb-core` làm build context và Dockerfile `Dockerfile`. Mở cổng HTTP `8000`; health check là `/api/health`.
4. Nối biến `POSTGRES_URI` của addon vào service với tên `DATABASE_URL`. Đặt `DATABASE_SSL=true`, `JWT_SECRET` thành chuỗi ngẫu nhiên riêng của dự án, và `OSRM_URL=https://router.project-osrm.org` để dùng tuyến đường bộ demo.
5. Khi service báo chạy, kiểm tra `https://<địa-chỉ-service>/api/health`.
6. Trong Vercel, đặt `VITE_API_URL=https://<địa-chỉ-service>/api` cho Production (và Preview nếu cần), rồi tạo deployment mới.

Không đưa `DATABASE_URL` hoặc `JWT_SECRET` vào Git hay gửi trong chat; nhập chúng ở phần Variables/Secrets của Northflank. Database mới sẽ rỗng, chưa có bệnh viện, kho máu hay tài khoản mẫu. Không chạy seed demo công khai vì seed hiện có chứa mật khẩu mẫu cố định.

## Giới hạn gói miễn phí

Northflank Developer Sandbox có compute luôn hoạt động, tối đa hai service, một database và hai job. Northflank yêu cầu thêm phương thức thanh toán để xác minh tài khoản; chọn đúng tài nguyên miễn phí để tránh phát sinh phí. Gói này dành cho demo/thử nghiệm, không dùng để điều phối hiến máu cấp cứu thật. OSRM public demo cũng không có cam kết ổn định.
