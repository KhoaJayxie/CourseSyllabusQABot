# Đặc tả schema thống nhất cho 3 file chunk của sách "Practical Natural Language Processing"

> Tài liệu này dành cho AI/engineer cần **chuyển 3 file nguồn sang một schema chung** mà **không làm mất ngữ nghĩa** của từng loại dữ liệu. Hãy đọc hết trước khi viết code.

## 1. Mục tiêu và nguyên tắc

- Gộp 3 file thành một tập chunk (`chunks.jsonl`, mỗi dòng một JSON object) dùng cho RAG / tìm kiếm.
- **Thống nhất phần "vỏ"** (định danh, loại, vị trí trang, quan hệ, nguồn gốc, chất lượng).
- **Giữ nguyên phần "ruột" riêng từng loại** trong `content` (bảng giữ `rows` có cấu trúc, code giữ nguyên văn).
- **Tách `embed_text` khỏi `content`**: `content` là dữ liệu gốc để trả về/trích dẫn; `embed_text` là chuỗi tối ưu để tạo embedding.
- **Không được** làm phẳng mọi thứ thành một cột `text`. **Không được** sửa/làm sạch dữ liệu trong `content` (chỉ làm sạch trong `embed_text`).

## 2. Ba file nguồn (đường dẫn upload)

| File | Định dạng | Số bản ghi | Loại |
|---|---|---|---|
| `practical_nlp_text_chunks.jsonl` | JSONL | 87 | `text` (80), `toc` (7) |
| `practical_natural_language_processing_tables.json` | JSON array | 10 | table |
| `practical_nlp_code_chunks.jsonl` | JSONL | 56 | code (`script` 47, `function` 9), toàn bộ Python |

### 2.1 Schema gốc: text
`chunk_id, document_id, type, text, page_start, page_end, line_start, line_end, source_line_ids`
- `document_id` = `"Practical Natural Language Processing"` (có dấu cách, KHÔNG phải slug).
- Mỗi chunk nằm trong 1 trang (`page_start == page_end`), phủ trang 9–63.
- `chunk_id` dạng `practical-natural-language-processing:text:0010`.
- `line_start`/`line_end` là số dòng trong trang; `source_line_ids` dạng `"<doc>:p9:l1"`.
- Văn bản chứa lỗi tách từ do gạch nối: `chal‐ lenges` (ký tự `‐` + dấu cách), có ở 58/87 chunk.
- Chunk `type=toc` là mục lục, nhiều dấu chấm `. . . .`.

### 2.2 Schema gốc: table
`chunk_id, parent_id, document_id, type, table_id, caption, unit, related_table_ids, page_start, page_end, page_inferred, header_type, columns, context, text, rows, source_line_ids, status, review_reasons, notes`
- `document_id` = `"practical-natural-language-processing"` (slug).
- `chunk_id` dạng `...:table2-1:p97-p97:full`; `parent_id` dạng `...:table2-1` (mức bảng).
- `rows` là list object `{tên_cột: giá_trị}`. `text` là bản làm phẳng của bảng để embed.
- `header_type`: `column_headers` (9 bảng) hoặc `row_headers_only` (Table 4-1).
- `page_inferred` đều `true`; `source_line_ids` đều rỗng; `unit`, `notes`, `related_table_ids` hiện đều rỗng/null.
- `status`: `needs_review` (8/10), `ok` (2/10). `review_reasons` mô tả ký tự thay thế (�) trong caption/công thức.
- 10 bảng: 2-1, 2-2, 2-3, 2-4, 3-1, 3-2, 4-1, 6-1, 6-2, 7-1 (trang 97–271).

### 2.3 Schema gốc: code
`id, file, language, chunk_type, symbol, step, page, start_line, end_line, depends_on, description, text`
- `id` dạng `practical-natural-language-processing.pdf::<symbol>`; `symbol` là duy nhất.
- `file` = `"Practical Natural Language Processing.pdf"`; **không có `document_id`**.
- `page` là int, **riêng 2 chunk là list** `[174,175]` và `[317,318]`.
- `step` là thứ tự (int, 1..56) trong toàn bộ tập code.
- `depends_on` là list tên (class/hàm/biến) mà đoạn code dùng.
- `description` **bằng tiếng Việt**; `text` là mã nguồn Python nguyên văn.
- Trang phủ 74–416. `start_line`/`end_line` là dòng trong trang/listing (xác nhận lại ngữ nghĩa với người dùng nếu cần dùng).

## 3. Các bất nhất cần xử lý

1. Khóa chính: `chunk_id` (text, table) vs `id` (code).
2. Loại: `type` (text, table) vs `chunk_type` (code).
3. `document_id`: 3 giá trị khác nhau cho cùng một cuốn sách.
4. Trang: `page_start/page_end` vs `page` (int | list).
5. Dòng: `line_start/line_end` + `source_line_ids` vs `start_line/end_line`.
6. Chất lượng: chỉ table có `status/review_reasons/notes`.
7. Ngôn ngữ: text/table tiếng Anh; `description` của code tiếng Việt.

## 4. Schema đích

```json
{
  "chunk_id": "string, duy nhất toàn tập",
  "document_id": "practical-natural-language-processing",
  "chunk_type": "text | toc | table | code",
  "subtype": "script | function | null",
  "order": 0,

  "page_start": 0,
  "page_end": 0,
  "page_inferred": false,

  "embed_text": "string dùng để embedding",
  "content": {},

  "relations": {
    "parent_id": null,
    "related_table_ids": [],
    "depends_on": [],
    "step": null,
    "prev_id": null,
    "next_id": null
  },

  "provenance": {
    "source_line_ids": [],
    "line_start": null,
    "line_end": null
  },

  "quality": {
    "status": "ok | needs_review",
    "review_reasons": [],
    "notes": []
  },

  "lang": "en | vi | code"
}
```

### 4.1 `content` theo từng `chunk_type`

| chunk_type | content |
|---|---|
| `text`, `toc` | `{ "text": "<nguyên văn, không sửa>" }` |
| `table` | `{ "table_id", "caption", "columns", "header_type", "rows": [...], "context", "unit" }` |
| `code` | `{ "code": "<nguyên văn>", "language": "python", "symbol", "description", "description_lang": "vi" }` |

### 4.2 `embed_text` theo từng loại

- **text:** `content.text` sau khi làm sạch gạch nối: thay `‐ ` (U+2010 + space) giữa hai mảnh từ bằng chuỗi rỗng (`chal‐ lenges` → `challenges`). Chuẩn hóa khoảng trắng.
- **toc:** có thể để trống hoặc giữ nguyên; **mặc định loại khỏi index tìm kiếm** (đánh dấu để filter).
- **table:** `caption + "\n" + context + "\n" + từng hàng "Cột: giá trị; Cột: giá trị"`. Trường `text` gốc của bảng gần đúng như vậy, có thể tái sử dụng.
- **code:** `description + "\n" + symbol + "\n" + code`. Nếu embedder không đa ngữ, thêm một dòng mô tả tiếng Anh.

## 5. Quy tắc ánh xạ

| Từ | Sang |
|---|---|
| `document_id` (mọi file), `file` | `document_id = "practical-natural-language-processing"` (hằng số). Tên file gốc để ngoài, trong bảng metadata tài liệu |
| text `chunk_id` | `chunk_id` (giữ nguyên) |
| table `chunk_id` | `chunk_id` (giữ nguyên) |
| code `id` | `chunk_id = "practical-natural-language-processing:code:" + symbol` |
| text `type` | `chunk_type` (`text` / `toc`) |
| table `type` | `chunk_type = "table"` |
| code `chunk_type` | `chunk_type = "code"`, `subtype = <script|function>` |
| code `page` int | `page_start = page_end = page` |
| code `page` list | `page_start = page[0]`, `page_end = page[-1]` |
| table/text `page_start/page_end` | giữ nguyên; table giữ `page_inferred`, text/code đặt `false` |
| text `line_start/line_end/source_line_ids` | `provenance.*` |
| code `start_line/end_line` | `provenance.line_start/line_end` (`source_line_ids = []`) |
| table `parent_id`, `related_table_ids` | `relations.parent_id`, `relations.related_table_ids` |
| code `depends_on`, `step` | `relations.depends_on`, `relations.step` |
| table `status/review_reasons/notes` | `quality.*` |
| text & code (không có trường chất lượng) | `quality = { status: "ok", review_reasons: [], notes: [] }` |
| `lang` | text/table/toc = `en`; code = `code` (description vẫn là `vi`) |

`order`: sắp theo `(page_start, thứ tự cục bộ)` trên toàn tài liệu. Thứ tự cục bộ: số cuối của `chunk_id` với text; `step` với code; thứ tự xuất hiện trong file với table. `prev_id`/`next_id` có thể tính từ `order` trong cùng `chunk_type`.

## 6. Ví dụ bản ghi đích (rút gọn)

```json
{
  "chunk_id": "practical-natural-language-processing:code:doc2vec_infer_classifier",
  "document_id": "practical-natural-language-processing",
  "chunk_type": "code",
  "subtype": "script",
  "order": 0,
  "page_start": 169,
  "page_end": 169,
  "page_inferred": false,
  "embed_text": "Tải model Doc2Vec, suy luận vector ... \ndoc2vec_infer_classifier\nmodel= Doc2Vec.load(\"d2v.model\") ...",
  "content": {
    "code": "model= Doc2Vec.load(\"d2v.model\")\n...",
    "language": "python",
    "symbol": "doc2vec_infer_classifier",
    "description": "Tải model Doc2Vec, suy luận vector cho train/test rồi huấn luyện bộ phân loại; ...",
    "description_lang": "vi"
  },
  "relations": { "parent_id": null, "related_table_ids": [], "depends_on": ["Doc2Vec", "train_data", "test_data"], "step": 29, "prev_id": null, "next_id": null },
  "provenance": { "source_line_ids": [], "line_start": 41, "line_end": 48 },
  "quality": { "status": "ok", "review_reasons": [], "notes": [] },
  "lang": "code"
}
```

(Giá trị `order`, `prev_id`, `next_id` được tính ở bước hậu xử lý.)

## 7. Vấn đề dữ liệu đã biết (không tự "sửa")

- **8/10 bảng `needs_review`**: có ký tự thay thế (�) trong caption/công thức F1 mà nguồn không khôi phục được. Giữ nguyên `quality.status` và `review_reasons`; khi truy xuất có thể cảnh báo người dùng. Không tự đoán ký tự gốc.
- **Độ phủ không đồng đều**: text chỉ trang 9–63; table trang 97–271; code trang 74–416. Nghĩa là bảng và code ở các chương sau **không có text giải thích đi kèm** trong dữ liệu này. Không giả định có text liên quan khi join theo trang.
- **Text hiện không chứa tham chiếu `Table x-y` và không chứa code**, nên chưa thể tự động điền `related_table_ids` từ text. Để trống, trừ khi người dùng cung cấp thêm dữ liệu.
- **Chưa có `section_path`** (chương/mục). Nên thêm sau bằng cách suy ra từ chunk `toc`, dạng `["Chapter 3", "Text Representation"]`, để lọc theo chương.

## 8. Kiểm tra sau khi chuyển đổi (validation)

1. Tổng số chunk = 87 + 10 + 56 = **153**.
2. `chunk_id` duy nhất toàn tập; `document_id` là một giá trị duy nhất.
3. `page_start <= page_end` và cả hai là int (không còn list).
4. Mỗi table: `len(content.rows)` bằng số hàng gốc; `content.columns` không đổi.
5. Mỗi code: `content.code` bằng đúng `text` gốc (so sánh từng ký tự).
6. Mỗi text: `content.text` bằng đúng `text` gốc; chỉ `embed_text` được làm sạch.
7. Số bảng `quality.status == "needs_review"` vẫn là 8.
8. Không còn field cũ (`id`, `file`, `type`, `page`, `start_line`, `end_line`) ở cấp trên cùng.
