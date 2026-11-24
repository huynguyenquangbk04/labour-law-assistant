---
name: payroll
description: Kiểm tra dữ liệu và tính tiền lương, làm thêm giờ, bảo hiểm, thuế TNCN từ tiền lương và chênh lệch quyết toán cho người lao động tại Việt Nam.
---

# Tính lương và thuế thu nhập từ tiền lương

Skill này được law-agent nạp khi câu hỏi liên quan đến lương hoặc thuế lao động.
Bạn lập kế hoạch tính theo schema `PayrollPlan`; chương trình thực hiện phép tính
bằng `Decimal` trong `backend/services/payroll.py`. Không tự nhẩm kết quả.

## Xác định yêu cầu

- Phân biệt lương gross/net, tiền làm thêm, khoản phải khấu trừ, chi phí của doanh
  nghiệp, thuế khấu trừ trong kỳ và quyết toán thuế năm. Ghi rõ bên trả/bên nhận.
- Xác nhận Việt Nam, VND và kỳ tính `YYYY-MM` hoặc năm quyết toán `YYYY`.
  Với “tháng này/năm nay”, dùng ngày hiện tại được chương trình cung cấp.
- Thu thập các dữ liệu cần cho đúng phép tính: lương và phụ cấp/tiền thưởng;
  khoản miễn thuế; cơ sở, tỷ lệ, trần đóng BHXH/BHYT/BHTN; số người phụ thuộc
  đủ điều kiện và thời gian giảm trừ; tình trạng cư trú và loại hợp đồng;
  giờ làm việc, làm thêm, ban đêm và loại ngày; thuế đã khấu trừ nếu quyết toán.
  Chỉ hỏi dữ liệu còn thiếu có ảnh hưởng tới phép tính đang được yêu cầu.
- Dùng thông tin người hỏi đã cung cấp trong hội thoại; không tự mặc định không
  có người phụ thuộc, lương đóng bảo hiểm bằng lương gross hoặc tình trạng cư trú.
- Câu hỏi chỉ hỏi quy định, không yêu cầu tính hoặc kiểm tra số tiền, dùng
  `not_applicable`. Thuế doanh nghiệp/GTGT, thu nhập không phải từ lao động hoặc
  pháp luật nước khác không thuộc phạm vi skill này.

## Kiểm tra căn cứ trước khi tính

- Dùng nội dung truy xuất và kết quả tìm kiếm đã cung cấp để xác định quy định
  có hiệu lực cho kỳ tính; ưu tiên văn bản gốc và nguồn chính thức. Kiểm tra cả
  thời điểm áp dụng và quy định chuyển tiếp. Không coi luật cũ trong kho là luật
  đang áp dụng, hoặc lấy mức thuế/giảm trừ/bảo hiểm từ trí nhớ của model.
- Gắn mỗi căn cứ với `source` đúng khóa trong `sources` và `quote` trích nguyên
  văn từ nguồn đó. Không dựng URL, điều luật, tỷ lệ hoặc căn cứ không có trong nguồn.
- Nếu thiếu dữ liệu, thiếu căn cứ áp dụng, hoặc các nguồn mâu thuẫn, trả
  `needs_information` cùng các câu hỏi cụ thể. Không điền số 0 vào phần còn thiếu.
- Chỉ dùng `scenario` khi người hỏi đã cung cấp rõ toàn bộ thông số/công thức
  và muốn tính theo các thông số đó; đây không phải xác nhận nghĩa vụ pháp lý.
  Các phép tính áp dụng quy định pháp luật phải dùng `legal` và có căn cứ ngoài
  lời người hỏi. Không chuyển sang `scenario` để tự thêm mức luật còn thiếu.
- `scenario` vẫn bắt buộc có `evidence`: lấy `source: "user"`, `quote` là
  nguyên văn đoạn người hỏi đã cho số liệu/công thức trong `sources["user"]`.
  Không để `evidence: []` khi đã có dữ liệu người hỏi; không hỏi lại các số đã rõ.

## Lập kế hoạch tính

- `ready` yêu cầu kỳ tính, phạm vi VN, căn cứ, các bước và ít nhất một kết quả.
  Mỗi số đầu vào phải nằm trong `inputs`, có ID, nhãn, `literal` trích đúng cách
  viết trong căn cứ, `unit` và `evidence_index` trỏ vào phần tử của `evidence`.
  Dùng `million_VND` cho triệu, `thousand_VND` cho nghìn, `percent` cho phần trăm,
  `VND` cho tiền đồng và `number` cho số lượng. Chương trình tự đổi đơn vị.
  Ví dụ “30 triệu”: literal `30`, unit `million_VND`; “10%”: literal `10`, unit
  `percent`. Bắt buộc dùng ID đầu vào trong biểu thức; không tự chèn mức luật còn thiếu.
  Giá trị ID đã được đổi đơn vị TRƯỚC khi tính: `gross` = 30000000 và
  `rate` = 0.1 cho đầu vào 30 triệu và 10%. Công thức đúng là
  `gross - gross * rate`; KHÔNG chia `rate` hoặc `gross * rate` thêm cho 100.
  Không nhân thêm 1000000 vào ID có đơn vị `million_VND`.
  ID của bước phải khác mọi ID đầu vào; không tạo lại bước `gross` nếu đã có
  đầu vào `gross`. Nếu cần một hệ số độc lập bằng 100, khai báo nó trong inputs
  với căn cứ riêng và dùng ID đó thay cho hằng số đổi đơn vị.
  Trong biểu thức chỉ cho phép hằng số số học `0`, `1`; mọi số khác phải dùng ID
  từ `inputs`, kể cả số có căn cứ trong nguồn. Định dạng số Việt Nam dùng
  dấu chấm phân nhóm nghìn, dấu phẩy thập phân; hỏi lại khi cách viết mơ hồ.
- Mỗi bước có `id` duy nhất, nhãn tiếng Việt, `expression` và `unit`. Chỉ dùng
  số thập phân, ID của bước trước, `+ - * /`, ngoặc, `min(...)`, `max(...)`.
  Không xuất Python tùy ý. Dùng `ratio`, `hours`, `count` cho bước không phải tiền.
- Chia thuế lũy tiến thành từng phần theo đúng biểu thuế đã kiểm tra. Không áp
  thuế suất bậc cao nhất lên toàn bộ thu nhập. Chặn cơ sở tính thuế âm bằng `max`.
- Tách bảo hiểm người lao động và doanh nghiệp; không trừ phần doanh nghiệp
  đóng vào lương thực nhận. Áp dụng trần trên đúng cơ sở trước khi nhân tỷ lệ.
- Không tính toàn bộ tiền làm thêm là miễn thuế nếu chỉ phần chênh lệch được miễn.
  Không cộng lần nữa khoản lương đã nằm trong lương tháng; tiền lễ/ngày nghỉ phải
  theo đúng điều kiện của người hỏi và căn cứ đã truy xuất.
- Không mặc định tháng có 26 ngày hoặc ngày có 8 giờ. Phân biệt khấu trừ tháng
  với quyết toán năm; chỉ gọi chênh lệch âm là khoản có thể hoàn khi đủ điều kiện
  quyết toán, không coi đó là tiền tự động được hoàn.
- Đưa ID các bước tổng kết vào `result_ids`: số người lao động nhận, thuế phải
  nộp, hoặc chênh lệch cần nộp thêm/có thể hoàn. Nhãn phải thể hiện ý nghĩa dấu.

## Trả lời

Kết quả chương trình gồm từng khoản, công thức, số tiền VND, kỳ tính và căn cứ;
law-agent trả nguyên văn báo cáo trong câu trả lời và luồng streaming, không gọi
mô hình soạn thêm số tiền. Phản biện có thể yêu cầu lập lại kế hoạch, nhưng kế hoạch
mới vẫn phải được chương trình kiểm tra và tính lại. Góp ý không phải căn cứ hay
dữ liệu người hỏi đã xác nhận. Nêu rõ giả định và câu hỏi còn thiếu. Chỉ làm tròn
tiền đến đồng ở đầu ra theo `ROUND_HALF_UP`; không làm tròn các bước trung gian.
