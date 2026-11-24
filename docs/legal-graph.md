# Đồ thị pháp luật

Mô hình áp dụng cho tài liệu DOCX nhập qua `/api/upload` và `backend/input.py`.
Nguồn kiểm thử: `data/10_2012_QH13_142187.docx` (17 chương, 30 mục, 242 điều).
Phần xác định tạo 1.118 đỉnh cấu trúc (gồm 629 khoản, 199 điểm), 1.117 cạnh
`CONTAINS` và 112 cạnh `REFERENCES`. Đây không phải thống kê phần ngữ nghĩa do LLM tạo.

## Hợp đồng dữ liệu

`.env` là nguồn chung cho loại đỉnh/cạnh và mô tả của chúng; `.env.example`
chứa danh mục mẫu. Hai biến đều là object JSON với tên loại làm khóa và mô tả làm giá trị:

- `APP_ENTITY_TYPE_DESCRIPTIONS`: loại đỉnh.
- `APP_EDGE_TYPE_DESCRIPTIONS`: loại cạnh.

`Settings.APP_ENTITY_TYPES` và `Settings.APP_EDGE_TYPES` được lấy từ các khóa này,
không còn danh mục dự phòng trong mã Python hoặc YAML. LightRAG, GraphRAG, local proxy
và bộ xuất đồ thị cùng sử dụng cấu hình này. Danh mục rỗng, tên/mô tả rỗng hoặc JSON
không hợp lệ bị từ chối khi khởi động. Khởi động lại backend sau khi chỉnh `.env`.

Các mã cấu trúc do parser tạo vẫn là hợp đồng dữ liệu; đổi mã cần cập nhật parser
và lập chỉ mục lại dữ liệu đã nhập.

- Các đề xuất duyệt cũ vẫn dùng `REPLACES`, `MODIFIES`, `SUPPLEMENTS`, `OVERLAPS`.
  Chúng không thay thế danh mục quan hệ trích xuất thông thường.

ID lấy số hiệu từ nội dung DOCX (kể cả bảng), ví dụ
`10_2012_qh13:dieu_37:khoan_2:diem_c`. Mục được định danh theo chương.
Nếu không có số hiệu, dùng tên file kèm hash tên file; không suy đoán số hiệu.
Parser giữ phần mở đầu, tiêu đề chương/mục tách dòng, nội dung khoản/điểm và
đoạn tiếp diễn. Không tự tạo khoản cho điều không đánh số khoản.

## Hai tầng trích xuất

1. **Cấu trúc xác định:** `build_legal_graph` tạo các đỉnh cấu trúc, cạnh `CONTAINS`
   và các dẫn chiếu nội bộ giải được bằng văn bản. Điểm kế thừa phần dẫn nhập của
   điều/khoản. Dẫn chiếu ngoài văn bản hoặc đích không tồn tại được trả trong
   `unresolved_references`, không tự ghép vào điều cùng số của tài liệu hiện tại.
2. **Ngữ nghĩa:** LightRAG và GraphRAG nhận cùng ontology và hướng dẫn giữ quyền,
   nghĩa vụ, cấm, thẩm quyền, AND/OR/NOT, ngoại lệ, nguồn trích và định lượng trong
   mô tả. Các QuyTac/DieuKien có ID theo nguồn. Các cạnh ngoài cấu trúc vẫn do LLM
   trích xuất; cấu hình này không chứng minh tính đầy đủ/chính xác của mọi kết quả.

LightRAG được bổ sung cấu trúc bằng API `ainsert_custom_kg`, gồm cả graph,
vector entities/relationships và text chunks làm bằng chứng. Hướng và nhiều loại
quan hệ trên cùng cặp đỉnh được giữ trong `legal_relations`, vì storage native
gộp quan hệ theo cặp không hướng. API `/graph` trả đúng hướng có bằng chứng;
cạnh cũ không rõ hướng không được vẽ mũi tên. Metadata và trích dẫn xem được trên UI.
  API serialize loại bỏ quan hệ đã biết là sai cặp loại đỉnh--loại cạnh hoặc thiếu
  bằng chứng nguồn. Các loại quan hệ tùy biến trong `.env` vẫn được chấp nhận và cần
  được kiểm tra theo ontology của deployment. Giới hạn số đỉnh của engine được báo bằng `is_truncated`.

GraphRAG sử dụng prompt pháp luật qua local proxy và cùng bản JSON nguồn. Nó vẫn
dùng pipeline trích xuất/cộng đồng native, không nhận trực tiếp graph cấu trúc của
LightRAG; SDK GraphRAG chuẩn hóa tên/type sang chữ hoa. Khi so sánh hai engine,
chuẩn hóa casing và đánh giá riêng kết quả trích xuất/truy xuất.

LLM chỉ được dùng để đề xuất trạng thái hiệu lực trong conflict review; đề xuất đó
không phải kết luận pháp lý và phải qua human review. Ngày hiệu lực và phạm vi sửa
đổi phải có nguồn; không coi ngày bắt đầu hiệu lực là bằng chứng đang còn hiệu lực.

## Nhập và khôi phục

Upload bình thường, batch được duyệt và CLI dùng chung `ingest_document`.
File lock ngăn hai tiến trình lập chỉ mục đồng thời. JSON được ghi bằng thay thế
nguyên tử; bản chụp nguồn giữ lại khi lỗi. LightRAG phải hoàn tất từng chunk trước
khi bổ sung graph và lập chỉ mục GraphRAG. Batch chỉ bị xóa sau khi hoàn tất;
lần duyệt cuối giữ nguyên pending cho đến khi lập chỉ mục và ghi graph hoàn tất.
Mọi ID đề xuất được kiểm tra với graph nguồn xác định và graph đã có trước khi nhập.
Quyết định được ghi bằng thay thế file nguyên tử. Nếu request bị hủy hoặc backend
dừng giữa chừng, gửi lại cùng quyết định để tiếp tục; batch cũ đã ghi approved nhưng
còn bản chụp staged cũng được tiếp tục, không bỏ qua phần nhập đang dang dở.
Phân tích xung đột lỗi không được coi là không có xung đột. Các đoạn văn bản mới
được chia theo ranh giới chunk để không bỏ sót phần sau tài liệu; các Điều được
nhắc trong tài liệu được ưu tiên khi tóm tắt node cũ. Bộ phát hiện vẫn giới hạn
số node trong từng prompt và không tự xác minh hiệu lực toàn bộ corpus.
Phân tích dùng client LLM streaming chung, đợi kết quả JSON hoàn chỉnh và yêu cầu
trường `proposals` rõ ràng, kể cả danh sách rỗng. Lỗi model hoặc kết quả không hợp lệ
trả HTTP 502 và chặn lập chỉ mục. Log của bộ phân tích ghi loại lỗi/mã HTTP thay vì
nội dung phản hồi của nhà cung cấp.

Không có transaction chung giữa hai engine. Nếu GraphRAG thất bại sau LightRAG,
API báo lỗi và phải chạy lại cùng nguồn; không công bố là nhập thành công cả hai.
SDK custom-KG chưa có recovery journal hoặc đủ anchors cho cơ chế purge tài liệu
native. Vì vậy giữ bản chụp nguồn để chạy lại và dùng workspace mới cho migration;
không xóa hoặc thay thế dữ liệu cũ bằng API purge với giả định có rollback đầy đủ.

Đổi ontology không tự sửa index cũ. Trước khi áp dụng vào dữ liệu đang dùng, sao lưu
PostgreSQL và thư mục GraphRAG, cấu hình database/workspace mới rồi nhập lại DOCX.
Quay về cấu hình cũ để rollback. Không trộn JSON cũ có ID `dieu_1` vào corpus mới.
CLI từ chối JSON thiếu document_id; batch cũ thiếu parsed_chunks cần nhập lại DOCX.
Đoạn trích không đổi và bản đầy đủ có thể nhập bổ sung cùng ID văn bản. Bản chụp
nguồn giữ các phần đã có; GraphRAG hợp nhất những phần đã hoàn tất LightRAG, không
công bố các phần chỉ mới nằm trong bản chụp chờ thử lại. Nội dung khác cho cùng ID
điều vẫn bị từ chối với HTTP 409 trước khi lập chỉ mục để tránh lẫn phiên bản.

Khởi động database và local proxy theo cấu hình hiện có, sau đó chạy từ root:

```powershell
& .venv/Scripts/python.exe backend/input.py data/10_2012_QH13_142187.docx
```

Lệnh trên gọi các model đã cấu hình và ghi dữ liệu vào cả hai engine. Nó chưa được
chạy trên database đang dùng trong quá trình triển khai này.

## Kiểm chứng

```powershell
& .venv/Scripts/python.exe -m unittest discover -s backend/tests -v
node frontend/node_modules/typescript/bin/tsc --noEmit --jsx react-jsx --moduleResolution bundler --module esnext --target es2020 --esModuleInterop --skipLibCheck --strict frontend/src/components/GraphViewer.tsx
```

Test tích hợp dùng LightRAG thật với storage tạm và embedding giả; không gọi LLM
trả phí. Lần chạy đầu có thể cần tải tokenizer. Kiểm thử không thay thế đánh giá
pháp lý trên dữ liệu thật hoặc kiểm thử PostgreSQL/AGE và GraphRAG với model thật.
