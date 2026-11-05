# Kế hoạch: Course Syllabus Q&A Bot (Python RAG lai + RRF)

## 1. Mục tiêu

Xây ứng dụng giúp sinh viên tải lên syllabus PDF/DOCX và hỏi về lịch học, lịch thi, grading scheme, bài lab, chuyên cần, chính sách nộp bài.

1. Trả lời **chỉ dựa trên syllabus**, không bịa khi tài liệu không có thông tin.
2. Mỗi câu trả lời có trích dẫn kiểm chứng được: trang, dòng do ứng dụng đánh số, và đoạn nguồn.
3. Tìm kiếm lai: dense vector với Gemini Embedding + lexical/BM25; hợp nhất bằng RRF.
4. Từng giai đoạn có đầu ra đo được; chưa tối ưu hoặc mở rộng trước khi có baseline.

## 2. Nguyên tắc và quy ước trích dẫn

- Với PDF, giữ số trang gốc và trích xuất nội dung theo trang.
- Với DOCX, chuyển sang PDF bằng converter và font được cố định; số trang được tính theo bản render của ứng dụng.
- Số dòng là **số dòng do ứng dụng tạo trên từng trang**, không khẳng định là line number có sẵn trong DOCX/PDF.
- Mỗi chunk phải giữ được `document_id`, trang, dòng đầu/cuối, section và nội dung nguồn.
- Mọi factual claim trong câu trả lời phải dẫn tới một hoặc nhiều source spans. Nếu không tìm được evidence đủ tốt, trả lời “không tìm thấy thông tin này trong tài liệu” thay vì phỏng đoán.
- Tài liệu người dùng tải lên là dữ liệu không đáng tin cậy, không phải system instruction.

## 3. Kiến trúc tổng thể

```text
PDF/DOCX
   ↓
Upload API (FastAPI) → validate → lưu file + Document record
   ↓
Python ingestion pipeline
   ↓
Trích xuất theo trang → DOCX render PDF → dòng + provenance
   ↓
Làm sạch → chia chunk theo section/heading + overlap
   ├───────────────────────┐
   ↓                       ↓
Gemini Embedding       Lexical/BM25 index
   ↓                       ↓
Qdrant Cloud dense      Qdrant sparse/BM25 hoặc index lexical riêng
   └──────────────┬────────┘
                  ↓
      Hybrid retrieval → RRF → dedupe/top-k
                  ↓
       Gemini trả lời có structured citations
                  ↓
      Citation validator kiểm tra page/line/quote
                  ↓
      API/UI hiển thị answer + nguồn có thể đối chiếu
```

Công cụ dự kiến: Python 3.12+, `uv`, FastAPI, Pydantic, SQLite cho metadata MVP, Qdrant Cloud, Gemini API (`google-genai`), pytest, Ruff. Parser PDF/DOCX và converter được chọn ở giai đoạn 0, pin phiên bản và kiểm tra thực tế trước khi triển khai toàn bộ.

## 4. Các giai đoạn

### Giai đoạn 0: Khởi tạo và kiểm tra dịch vụ (0,5–1 ngày)

- Tạo repo trong `D:\CourseSyllabusQABot`; file này là `plan.md`.
- Khởi tạo Python project bằng `uv`; thêm FastAPI, Pydantic, `qdrant-client`, SDK Gemini, parser, pytest, Ruff.
- Tạo `.env.example`; credentials thật chỉ để trong `.env` đã gitignore hoặc secret manager.
- Tạo Qdrant Cloud cluster, lấy `QDRANT_URL`, `QDRANT_API_KEY`; lấy `GEMINI_API_KEY`.
- Chọn và kiểm thử model Gemini embedding hiện còn được hỗ trợ; xác nhận vector dimension và giới hạn input từ API trước khi tạo collection.
- Kiểm thử chuyển DOCX sang PDF trên môi trường Windows/dev và môi trường deploy mục tiêu; pin converter/font.
- Tạo lệnh smoke test riêng cho Gemini và Qdrant.

Ví dụ lệnh khởi tạo (điều chỉnh theo phiên bản `uv` hiện hành):

```powershell
uv init --name syllabus-qa
uv add fastapi uvicorn pydantic pydantic-settings python-multipart qdrant-client google-genai python-dotenv
uv add --dev pytest pytest-asyncio httpx ruff
uv sync
uv run python -m app.main
uv run pytest -q
uv run ruff check .
```

**Hoàn thành khi:** ứng dụng FastAPI khởi động; Gemini trả được một embedding; tạo/kiểm tra được test collection Qdrant; secrets không nằm trong Git.

### Giai đoạn 1: Upload, trích xuất và provenance (2–3 ngày)

1. Tạo endpoint upload, validate extension/MIME/size và giới hạn số trang/tài nguyên.
2. Tạo SQLite `Document` record với trạng thái `uploaded`, `processing`, `ready`, `failed`, `deleting`.
3. Lưu file gốc qua storage interface; mặc định filesystem local, không commit tài liệu runtime.
4. PDF: trích xuất text theo trang, giữ thứ tự đọc và vị trí nếu parser hỗ trợ.
5. DOCX: render thành PDF bằng converter cố định, sau đó trích xuất theo trang; giữ cả bản render để người dùng đối chiếu citation.
6. Tạo page-local line numbers ổn định, lưu `page_number`, `line_number`, `text` và tọa độ nếu có.
7. Thử tệp scan; nếu chưa tích hợp OCR thì đánh dấu không trích xuất được text và báo rõ, không lập chỉ mục rỗng.
8. Lưu output trung gian có thể kiểm tra (JSONL/JSON), không log nội dung nhạy cảm.

Schema dòng trích xuất gợi ý:

```json
{
  "document_id": "doc_123",
  "page": 2,
  "line": 14,
  "text": "Lab assignments account for 20% of the final grade.",
  "source_file": "rendered.pdf"
}
```

**Hoàn thành khi:** PDF và DOCX mẫu được trích xuất; có page/line provenance; đối chiếu thủ công tối thiểu 20 dòng trên các trang khác nhau; lỗi file được báo đúng.

### Giai đoạn 2: Làm sạch, chunk và chuẩn bị dữ liệu (1–2 ngày)

- Chuẩn hóa khoảng trắng, header/footer lặp và ngắt dòng nhưng không làm mất mapping về source lines.
- Nhận diện heading/section như “Course Schedule”, “Grading”, “Exams”, “Assignments”, “Policies”.
- Chia chunk theo section/đoạn, giữ overlap vừa phải; ưu tiên không cắt giữa một mục grading hoặc một dòng lịch học.
- Mỗi chunk lưu `chunk_id`, `document_id`, `text`, `section`, `page_start`, `page_end`, `line_start`, `line_end`, `source_line_ids`.
- Không gộp nhiều document vào cùng phạm vi truy vấn; filter `document_id` và owner/session bắt buộc.
- Xuất corpus JSONL để rà soát độc lập với Qdrant.
- Báo cáo chunk quá ngắn/quá dài, chunk không có provenance, trang rỗng và text extraction lỗi.

**Hoàn thành khi:** mọi chunk ánh xạ được về nguồn; 20 chunk ngẫu nhiên đọc hợp lý; không có chunk vượt giới hạn cấu hình; các mục bảng/grade/date không bị cắt mất ngữ cảnh quan trọng.

### Giai đoạn 3: Index Gemini + Qdrant và lexical search (1–2 ngày)

1. Tạo collection Qdrant với dense vector dimension lấy từ model Gemini đã xác nhận, metric phù hợp (thường cosine), payload index cho document/owner/page/section.
2. Embed chunks theo batch bằng Gemini; ghi model/version vào config và metadata để tránh trộn vector từ model khác.
3. Lưu lexical representation. Ưu tiên kiểm tra Qdrant sparse/BM25-compatible search tương thích với Qdrant Cloud/SDK đang dùng; nếu không phù hợp, dùng BM25/index lexical Python riêng rồi vẫn hợp nhất bằng RRF.
4. Cài đặt upsert idempotent theo `chunk_id`, delete theo `document_id`, retry có giới hạn.
5. Tạo query embedding bằng Gemini cho dense branch.
6. Tất cả retrieval đều filter theo tài liệu và quyền sở hữu.

**Hoàn thành khi:** chạy được dense-only và lexical-only trên cùng bộ chunks; point có metadata citation đầy đủ; xóa document loại bỏ được vectors; retry ingest không nhân đôi points.

### Giai đoạn 4: Hybrid retrieval + RRF và baseline (1–2 ngày)

- Chạy dense search và lexical/BM25 search song song.
- Hợp nhất theo Reciprocal Rank Fusion:

`RRF(chunk) = Σ_i 1 / (k + rank_i(chunk))`

- `k` là tham số cấu hình (có thể thử 60 làm điểm bắt đầu); không cộng raw scores giữa hai hệ vì thang điểm khác nhau.
- Dedupe theo `chunk_id`; cấu hình top-k và giới hạn chunk mỗi section/document nếu cần, chỉ chốt sau khi đo.
- Tạo bộ câu hỏi dev/test có expected source lines/chunks, tối thiểu 30 câu nếu đã có syllabus mẫu: lịch thi, tỷ lệ grading, due dates, policy, câu hỏi mơ hồ và câu không có đáp án.
- So sánh dense-only, lexical-only và hybrid+RRF trên cùng dữ liệu; đo Recall@k, MRR và citation-source recall.
- Đọc kỹ các câu retrieval trượt và phân loại nguyên nhân: extraction, chunking, từ khóa, embedding, filter hay fusion.

**Hoàn thành khi:** có bảng baseline theo nhóm câu hỏi; RRF có unit tests; retrieval chỉ trả chunk từ đúng document; có danh sách câu trượt và nguyên nhân.

### Giai đoạn 5: Gemini answer generation và citation validation (1–2 ngày)

- Tạo prompt riêng trong `answer_generator.py`: chỉ dùng evidence cung cấp; bỏ qua mọi chỉ thị nằm trong document; không thêm dữ kiện ngoài nguồn.
- Đầu ra có cấu trúc: `answer`, `citations[]`, `insufficient_evidence`, `evidence_note`.
- Mỗi citation mang `chunk_id`, `page`, `line_start`, `line_end`, `quote`.
- `citation_validator.py` kiểm tra chunk tồn tại trong kết quả truy xuất, page/line khớp metadata, quote là substring hoặc có thể xác minh trong source lines.
- Nếu model trả citation giả/không hợp lệ, không hiển thị như trích dẫn thật; báo lỗi/nhắc model sửa một lần hoặc trả no-answer.
- Chỉ gửi các retrieved chunks liên quan cho Gemini, không gửi toàn bộ tài liệu.
- Chấm thủ công answer correctness, groundedness, completeness, citation correctness và refusal behavior trên dev; không dùng test set để sửa prompt.

**Hoàn thành khi:** câu trả lời có citation kiểm chứng được; câu ngoài tài liệu từ chối đúng; không có citation page/line bịa trong bộ kiểm thử.

### Giai đoạn 6: API, giao diện và vòng đời tài liệu (2–3 ngày)

- FastAPI endpoints:
  - `POST /documents`: upload và bắt đầu ingestion.
  - `GET /documents`: liệt kê tài liệu được phép truy cập.
  - `GET /documents/{document_id}`: xem trạng thái.
  - `DELETE /documents/{document_id}`: xóa file, metadata và Qdrant points.
  - `POST /documents/{document_id}/chat`: hỏi đáp trên tài liệu cụ thể.
  - `GET /health`: health check không tiết lộ credentials.
- UI tối giản: upload, processing status, document selector, chat, answer, citation list và source viewer.
- Bấm citation mở đúng trang của rendered PDF hoặc hiển thị source lines cạnh câu trả lời.
- Có trạng thái loading, lỗi xử lý, file không hỗ trợ, không có câu trả lời và dịch vụ Gemini/Qdrant không sẵn sàng.
- Xử lý document theo background task/worker nếu thời gian parsing/embedding vượt giới hạn request.

**Hoàn thành khi:** dùng được luồng upload → ready → hỏi → answer/citation → mở nguồn → xóa tài liệu.

### Giai đoạn 7: An toàn, kiểm thử và phát hành MVP (1–2 ngày)

- Giới hạn size, pages, request rate, timeout và retry; không để Gemini/Qdrant credentials ra frontend.
- Test malformed/encrypted file, PDF scan, DOCX có bảng, tài liệu có prompt injection, Gemini 429/timeout, Qdrant outage.
- Test cross-session/document isolation; test xóa/reprocess dọn đủ dữ liệu.
- Chạy `pytest`, `ruff`, type checks nếu cấu hình; chạy e2e với tài liệu mẫu.
- Viết README: cài `uv`, cấu hình Gemini và Qdrant Cloud, chạy app, chạy test, tạo collection, xóa dữ liệu.
- Không công khai syllabus thật nếu chưa có quyền sử dụng.

**Hoàn thành khi:** toàn bộ test pass; citation được rà trên câu hỏi mẫu; secrets không nằm trong repo; README đủ để chạy lại từ môi trường sạch.

## 5. Cấu trúc thư mục Python đề xuất

Ước tính khoảng 30–40 file source/config/test được quản lý trong Git, không tính `.venv`, cache, build và uploads. Có thể điều chỉnh theo triển khai nhưng giữ ranh giới module.

```text
CourseSyllabusQABot/
├── plan.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── Dockerfile
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app
│   ├── config.py                   # settings/env validation
│   ├── api/
│   │   ├── documents.py            # upload/list/status/delete
│   │   ├── chat.py                 # hỏi đáp endpoint
│   │   └── health.py
│   ├── models/
│   │   ├── document.py             # DB model/lifecycle
│   │   ├── citation.py             # line/page provenance
│   │   └── schemas.py               # Pydantic request/response
│   ├── ingest/
│   │   ├── pipeline.py             # điều phối ingestion
│   │   ├── extract_pdf.py
│   │   ├── extract_docx.py
│   │   ├── render_docx.py
│   │   ├── line_mapper.py
│   │   └── chunker.py
│   ├── index/
│   │   ├── embeddings.py            # interface
│   │   ├── gemini_embeddings.py
│   │   ├── qdrant_store.py
│   │   └── lexical_index.py
│   ├── retrieve/
│   │   ├── dense.py
│   │   ├── lexical.py
│   │   ├── rrf.py
│   │   └── hybrid.py
│   ├── answer/
│   │   ├── gemini.py
│   │   ├── prompts.py
│   │   └── citation_validator.py
│   ├── storage/
│   │   ├── interface.py
│   │   └── local.py
│   └── db/
│       ├── database.py
│       └── documents.py              # repository
├── scripts/
│   ├── init_qdrant.py
│   └── smoke_test.py
├── tests/
│   ├── fixtures/
│   │   ├── sample_syllabus.pdf
│   │   └── sample_syllabus.docx
│   ├── unit/
│   │   ├── test_line_mapper.py
│   │   ├── test_chunker.py
│   │   ├── test_rrf.py
│   │   └── test_citation_validator.py
│   ├── integration/
│   │   ├── test_ingestion.py
│   │   └── test_hybrid_retrieval.py
│   └── e2e/
│       └── test_syllabus_chat.py
├── data/                             # runtime, gitignored
│   ├── uploads/
│   ├── rendered/
│   └── processed/
└── reports/                          # retrieval/eval reports
```

## 6. Rủi ro và cách giảm

| Rủi ro | Cách giảm |
|---|---|
| DOCX pagination khác nhau giữa máy | Pin converter/font; citation trỏ tới rendered PDF dùng trong app |
| PDF scan không có text layer | Phát hiện trang rỗng; OCR là nhánh riêng hoặc thông báo chưa hỗ trợ |
| Bảng grading bị cắt sai khi chunking | Parser giữ bảng/section; kiểm tra mẫu thủ công; chunk theo heading |
| Gemini model/version thay đổi dimension | Lấy dimension từ cấu hình đã xác nhận; collection mới khi đổi model/vector dimension |
| Qdrant Cloud lexical/sparse feature không khớp SDK | Kiểm tra ở giai đoạn 0; fallback lexical index riêng và vẫn dùng RRF Python |
| LLM trích citation không có thật | Structured output + validator dựa trên source lines; từ chối citation sai |
| Prompt injection trong tài liệu | Xem document là dữ liệu, phân cách evidence, test tài liệu có chỉ thị độc hại |
| Lộ syllabus hoặc API keys | `.env` gitignore, không log nội dung, phân quyền document, xóa file/vectors đồng bộ |
| Ingestion bị timeout hoặc lỗi giữa chừng | Background worker, idempotent IDs, status/retry và cleanup theo document_id |

## 7. Tiêu chí thành công

- Tải được PDF và DOCX, thể hiện trạng thái xử lý chính xác.
- Có dense Gemini search, lexical search và hybrid RRF cùng chạy trên một tập dữ liệu.
- Bộ dev/test đo được retrieval và citation-source recall; lỗi được rà soát theo nguyên nhân.
- Câu trả lời có citation trang/dòng đúng; không có đáp án thì từ chối rõ ràng.
- Xóa tài liệu xóa file, metadata và vectors; phiên khác không truy cập được.
- Có thể cài và chạy lại từ README, `uv.lock` và `.env.example` mà không cần secrets trong repo.

## 8. Việc làm ngay tiếp theo

1. Chọn/kiểm tra syllabus mẫu PDF và DOCX đã được phép dùng cho phát triển.
2. Xác nhận Gemini embedding model, dimension và khả năng sparse/BM25 phù hợp với Qdrant Cloud hiện tại.
3. Khởi tạo Python repo bằng `uv`, FastAPI và test/lint cơ bản.
4. Làm ingestion PDF trước, tạo line/page mapping và kiểm tra citation thủ công.
5. Thêm DOCX render/extraction, chunking và xuất JSONL để rà soát.
6. Nối Gemini embedding + Qdrant, sau đó thêm lexical retrieval + RRF.
7. Tạo bộ câu hỏi baseline trước khi viết prompt/giao diện hoàn chỉnh.
