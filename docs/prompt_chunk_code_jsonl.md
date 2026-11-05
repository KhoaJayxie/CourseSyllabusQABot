# Prompt để AI tự chunk code và sinh file JSONL

Mục tiêu: đưa một file code cho AI, AI chia thành các chunk và trả về dữ liệu để ghi ra `chunks.jsonl`, ví dụ như sau:

```jsonl
{"id": "search_books.py::search_loop", "file": "search_books.py", "language": "python", "chunk_type": "script", "symbol": "search_loop", "step": 1, "start_line": 1, "end_line": 8, "depends_on": ["es", "myindex"], "description": "Vòng lặp nhận từ khóa từ người dùng, tìm cụm từ chính xác trong trường summary bằng match_phrase trên Elasticsearch rồi in tiêu đề sách.", "text": "# match: OR giữa các từ | match_phrase: khớp cụm chính xác\nwhile True:\n    query = input(\"Enter your search query: \")\n    ..."}
{"id": "search_books.py::snippet_extract", "file": "search_books.py", "language": "python", "chunk_type": "script", "symbol": "snippet_extract", "step": 2, "start_line": 9, "end_line": 12, "depends_on": ["hit", "query"], "description": "Lấy đoạn trích 100 ký tự trước và sau vị trí từ khóa trong summary; có thể lỗi nếu query có chữ hoa hoặc loc nhỏ hơn 100.", "text": "# (nằm trong vòng for hit ... của while True)\nloc = ..."}
```

## 1. Nguyên tắc quan trọng

**Đừng bắt AI tự viết cú pháp JSONL.** Việc escape `\"`, `\n`, `\\t` rất dễ sai. Hãy bắt AI trả về **JSON thường**, rồi để code Python ghi ra JSONL bằng `json.dumps`. Các trường máy tính tính được (`id`, `file`, `language`) cũng để code điền, AI chỉ lo phần cần hiểu code.

## 2. Phân việc

| Trường | Ai làm | Lý do |
|--------|--------|-------|
| `id`, `file`, `language` | Code Python | Tất định, không cần AI |
| `symbol`, `chunk_type`, `step` | AI | Cần hiểu ý nghĩa |
| `start_line`, `end_line` | AI (dựa vào số dòng bạn đánh sẵn) | Đưa số dòng để AI khỏi đoán |
| `depends_on` | AI | Cần phân tích biến dùng mà chưa khai báo |
| `description` | AI | Cần hiểu code, nên ghi cả lỗi tiềm ẩn |
| `text` | AI chép nguyên văn + thêm comment ngữ cảnh | Phải kiểm tra lại bằng code |

## 3. System prompt

```text
Bạn là công cụ chia code thành chunk phục vụ tìm kiếm ngữ nghĩa (RAG).
Nhiệm vụ: nhận code đã đánh số dòng, trả về danh sách chunk dưới dạng JSON.

## Quy luật chia
1. Hàm/class/method là 1 chunk nếu không quá ~60 dòng.
2. Code cấp module/script: gom theo BƯỚC LOGIC (nhập liệu, truy vấn, in kết quả, xử lý phụ).
3. Không cắt giữa chuỗi, dấu ngoặc hoặc khối thụt lề.
4. Nếu code ngắn và liền mạch, trả 1 chunk duy nhất.
5. Mỗi chunk phải tự đứng được. Nếu chunk nằm trong khối bao ngoài
   (vòng lặp, if, class...) thì thêm 1-2 dòng comment ở đầu "text" nói rõ nó nằm trong khối nào.
6. Giữ nguyên văn code, không sửa, không format lại. Chỉ được THÊM comment ngữ cảnh ở đầu.

## Quy luật các trường
- symbol: snake_case, ngắn, mô tả mục đích (vd: search_loop).
- chunk_type: một trong function | class | method | script.
- step: số thứ tự chunk, bắt đầu từ 1.
- start_line, end_line: số dòng trong code gốc (dùng số tôi đã đánh sẵn).
  Phần comment ngữ cảnh bạn thêm KHÔNG tính vào số dòng.
- depends_on: danh sách tên biến/import/dịch vụ mà chunk dùng nhưng KHÔNG tự khai báo trong chunk.
- description: đúng 1 câu tiếng Việt, tối đa 40 từ, nêu: làm gì, dùng thư viện/API nào,
  và nếu thấy bug hoặc rủi ro rõ ràng thì ghi ngắn gọn ở cuối.
- text: code nguyên văn của chunk, giữ nguyên xuống dòng và thụt lề.

## Đầu ra
Chỉ trả về JSON hợp lệ, không markdown, không lời dẫn:
{
  "reasoning": "1-2 câu vì sao chia như vậy",
  "chunks": [
    {"symbol": "...", "chunk_type": "...", "step": 1,
     "start_line": 0, "end_line": 0,
     "depends_on": [], "description": "...", "text": "..."}
  ]
}
```

## 4. Few-shot bằng chính ví dụ của bạn

Thêm vào cuối system prompt (hoặc làm thành cặp user/assistant). Đây là phần giúp AI ra đúng format mong muốn.

```text
## Ví dụ

Đầu vào:
1: while True:
2:     query = input("Enter your search query: ")
3:     if query == "STOP":
4:         break
5:     res = es.search(index="myindex", body={"query": {"match_phrase": {"summary": query}}})
6:     print("Your search returned %d results:" %res['hits']['total']['value'])
7:     for hit in res["hits"]["hits"]:
8:         print(hit["_source"]["title"])
9:         #to get a snippet 100 characters before and after the match
10:        loc = hit["_source"]["summary"].lower().index(query)
11:        print(hit["_source"]["summary"][:100])
12:        print(hit["_source"]["summary"][loc-100:loc+100])

Đầu ra:
{
  "reasoning": "Phần truy vấn và in tiêu đề là một bước; phần lấy snippet là bước hiển thị riêng, có rủi ro lỗi nên tách ra.",
  "chunks": [
    {"symbol": "search_loop", "chunk_type": "script", "step": 1,
     "start_line": 1, "end_line": 8,
     "depends_on": ["es", "myindex"],
     "description": "Vòng lặp nhận từ khóa, tìm cụm từ chính xác trong trường summary bằng match_phrase trên Elasticsearch rồi in tiêu đề sách.",
     "text": "while True:\n    query = input(\"Enter your search query: \")\n    ..."},
    {"symbol": "snippet_extract", "chunk_type": "script", "step": 2,
     "start_line": 9, "end_line": 12,
     "depends_on": ["hit", "query"],
     "description": "Lấy đoạn trích 100 ký tự quanh từ khóa trong summary; lỗi nếu query có chữ hoa hoặc loc nhỏ hơn 100.",
     "text": "# (nằm trong vòng for hit ... của while True)\nloc = ..."}
  ]
}
```

Trong prompt thật, hãy dán `text` đầy đủ thay cho `...`.

## 5. Code gọi AI, ghi JSONL và kiểm tra

```python
import json
import anthropic

client = anthropic.Anthropic()  # đọc ANTHROPIC_API_KEY từ biến môi trường

SYSTEM_PROMPT = "..."  # dán system prompt + few-shot ở trên

def verify(chunk, lines):
    """Kiểm tra mọi dòng code gốc trong khoảng start-end đều có mặt trong text."""
    seg = lines[chunk["start_line"]-1 : chunk["end_line"]]
    return all(l.strip() in chunk["text"] for l in seg if l.strip())

def chunk_file(path: str, language: str = "python") -> list[dict]:
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    numbered = "\n".join(f"{i+1}: {l}" for i, l in enumerate(lines))

    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": numbered}],
    )
    data = json.loads(resp.content[0].text)
    print("Lý do chia:", data["reasoning"])

    chunks = []
    for c in data["chunks"]:
        assert verify(c, lines), f"Chunk {c['symbol']} không khớp code gốc"
        chunks.append({"id": f"{path}::{c['symbol']}",
                       "file": path, "language": language, **c})
    return chunks

chunks = chunk_file("search_books.py")
with open("chunks.jsonl", "w", encoding="utf-8") as f:
    for c in chunks:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")
```

## 6. Mẹo chỉnh prompt

- **Thứ tự key trong JSONL**: nếu cần đúng thứ tự `id, file, language, chunk_type, symbol, step, ...`, hãy dựng dict theo thứ tự đó trong code thay vì dựa vào AI.
- **Nếu AI hay chép sai `text`**: đổi sang cách bắt AI chỉ trả `start_line`/`end_line`, còn `text` do code tự cắt từ file gốc rồi ghép thêm comment ngữ cảnh. Đây là cách chắc chắn nhất.
- **Nếu JSON hay lỗi**: dùng structured output / tool use với schema, hoặc thử lại khi `json.loads` lỗi.
- **Nếu AI chia quá nhỏ hoặc quá to**: chỉnh ngưỡng "~60 dòng", thêm câu "ưu tiên ít chunk hơn" hoặc "ưu tiên chunk nhỏ hơn".
- **Kiểm tra bằng mắt** vài chunk đầu: `description` là suy diễn của AI, không phải sự thật tuyệt đối.
- **Lưu thêm** `desc_model` và `prompt_version` vào chunk để biết khi nào cần sinh lại.

## 7. Lỗi tiềm ẩn trong code mẫu (nên ghi vào description hoặc sửa)

1. `.index(query)` phân biệt hoa/thường vì summary đã `.lower()` còn `query` thì chưa. Sửa: `query.lower()`.
2. `loc-100` có thể âm khi match nằm trong 100 ký tự đầu, cho snippet sai. Sửa: `max(0, loc-100)`.
3. `.index()` ném `ValueError` nếu không tìm thấy (ví dụ Elasticsearch khớp qua stemming). Dùng `.find()` rồi kiểm tra `-1`.
4. Dòng `print(summary[:100])` có vẻ là debug còn sót.

Bản sửa gọn:

```python
summary = hit["_source"]["summary"]
loc = summary.lower().find(query.lower())
if loc != -1:
    print(summary[max(0, loc-100): loc+len(query)+100])
```
