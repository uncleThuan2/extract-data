# Document Q&A Bot (Telegram)

Bot Telegram hỏi đáp tài liệu với AI, hỗ trợ trích xuất data và xuất Excel.  
Data lưu trên **Supabase pgvector** (free). Chạy trên **Render.com** (free).

## Supported File Types

| Loại | Extensions |
|------|------------|
| PDF | `.pdf` |
| Word | `.docx` |
| Excel | `.xlsx`, `.xls` |
| CSV | `.csv` |
| Plain Text | `.txt`, `.md`, `.rst`, `.log` |
| Data | `.json`, `.xml`, `.yaml`, `.yml` |
| Web | `.html`, `.htm` |
| Rich Text | `.rtf` |

> ⚠️ **Không hỗ trợ:** ảnh, video, audio, file binary.

## Kiến trúc

```
[Telegram bot]  gửi file  →  upload_service.py
                               ├─ Kiểm tra duplicate (filename đã index chưa?)
                               ├─ Extract text   (document_processor.py)
                               ├─ Chunk text     (RecursiveCharacterTextSplitter)
                               └─ Embed + Store  (Jina AI → Supabase pgvector)

[Telegram bot]  /ask  →  qa_engine.py
                           ├─ Embed query  (Jina AI)
                           ├─ Search top-K chunks  (Supabase pgvector)
                           └─ Chat  (Groq → Gemini fallback)  →  Answer

[Google Colab]  colab_upload.ipynb  →  Upload hàng loạt file ngoài bot
```

## AI Providers

| Provider | Dùng cho | Free tier |
|---------|----------|-----------|
| **Jina AI** | Embedding (hardcoded) | 1M tokens/tháng, không giới hạn RPM |
| **Groq** | Chat (primary) | 14,400 req/ngày — `llama-3.1-8b-instant` |
| **Gemini** | Chat (fallback) | 1,500 req/ngày — `gemini-2.0-flash-lite` |

Thứ tự fallback cấu hình qua `CHAT_PROVIDERS=groq,gemini`. Khi provider hết quota ngày, tự động chuyển sang provider tiếp theo.


## Yêu cầu

| Thứ | Service | Link | Bắt buộc? |
|-----|---------|------|-----------|
| 1 | **Python 3.11+** | — | ✅ |
| 2 | **Telegram Bot Token** | [@BotFather](https://t.me/BotFather) | ✅ |
| 3 | **Supabase** (free) | [supabase.com](https://supabase.com) | ✅ |
| 4 | **Jina AI API Key** | [jina.ai/embeddings](https://jina.ai/embeddings) | ✅ |
| 5 | **Groq API Key** | [console.groq.com](https://console.groq.com) | ✅ (primary chat) |
| 6 | **Gemini API Key** | [aistudio.google.com](https://aistudio.google.com) | Tùy chọn (fallback) |

## Setup

### 1. Supabase

1. Tạo account tại [supabase.com](https://supabase.com) → tạo project mới
2. Vào **SQL Editor** → chạy nội dung file `setup_supabase.sql`
3. Lấy thông tin từ **Settings → API**:
   - `SUPABASE_URL` = Project URL
   - `SUPABASE_KEY` = anon public key
   - `SUPABASE_DB_URL` = **Settings → Database → Connection string (URI)**  
     _(thay `[YOUR-PASSWORD]` bằng database password)_

### 2. Tạo Telegram Bot

1. Mở Telegram → tìm **@BotFather** → gửi `/newbot`
2. Copy token → dán vào `TELEGRAM_BOT_TOKEN` trong `.env`
3. (Tùy chọn) Cấu hình commands qua `/setcommands`:

   ```
   ask - Hỏi về tài liệu đã index
   extract - Trích xuất data có cấu trúc → Excel
   export - Xuất lịch sử Q&A ra Excel
   files - Xem danh sách file đã index
   delete - Xóa file khỏi vector store theo tên
   storage - Xem dung lượng Supabase
   ping - Kiểm tra bot còn sống không
   ```

#### Thêm bot vào Group

- **Chat riêng:** Tìm `@your_bot_username` → nhấn **Start**
- **Group:** Add Members → tìm username → Add → gửi `/start`
- **Link chia sẻ:** `https://t.me/your_bot_username`

### 3. Cài đặt và chạy local

```bash
git clone https://github.com/your/repo.git
cd extract-data

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt

cp .env.example .env
# Điền các API keys vào .env

python run.py              # chạy bot + health server
python run.py --no-health  # chỉ chạy bot (local dev)
```

## Commands

| Command | Mô tả |
|---------|-------|
| `/ask <câu hỏi>` | Hỏi về tài liệu đã index |
| `/extract <mô tả>` | Trích xuất data có cấu trúc → Excel |
| `/export` | Xuất toàn bộ lịch sử Q&A → Excel |
| `/files` | Xem danh sách file đã index |
| `/delete <tên file>` | Xóa file khỏi vector store |
| `/storage` | Xem dung lượng Supabase |
| `/ping` | Kiểm tra bot đang chạy |

> Gửi file PDF/DOCX/XLSX/CSV/TXT trực tiếp vào chat để index.  
> Bot sẽ báo lỗi nếu file đó đã được index rồi.

## Upload hàng loạt (Google Colab)

Dùng `colab_upload.ipynb` để upload nhiều file cùng lúc mà không cần qua bot:

1. Mở notebook trong [Google Colab](https://colab.research.google.com)
2. Điền `JINA_API_KEY`, `SUPABASE_DB_URL` vào cell **Cấu hình**
3. Chạy từng cell theo thứ tự: Upload → Extract → Embed → Insert
4. Notebook tự kiểm tra duplicate trước khi insert

## Ví dụ sử dụng

```
# Upload file qua Telegram (gửi file trực tiếp vào chat)
# Hoặc dùng colab_upload.ipynb để upload hàng loạt

/ask Tóm tắt nội dung chính của tài liệu
/ask Liệt kê tất cả các điều khoản về thanh toán
/extract tất cả tên công ty và địa chỉ → tải file Excel
/export    → Xuất toàn bộ Q&A ra Excel
/storage   → Xem dung lượng Supabase đang dùng
/files     → Xem danh sách file đã index
```

## Chi phí ước tính

| Service | Cost |
|---------|------|
| Supabase | **Free** (500MB DB) |
| Telegram Bot | **Free** |
| Jina AI Embedding | **Free** (1M tokens/tháng) |
| Groq Chat | **Free** (14,400 req/ngày) |
| Gemini Chat (fallback) | **Free** (1,500 req/ngày) |

**→ Tổng chi phí: $0/tháng cho hầu hết use case**

## Deploy lên Render.com (Free)

Bot có health server tại `GET /health`. Kết hợp **UptimeRobot** để không bao giờ sleep:

1. Push code lên GitHub
2. Vào [render.com](https://render.com) → **New → Web Service**
3. Connect GitHub repo, cấu hình:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python run.py`
4. Vào tab **Environment** → thêm tất cả biến từ `.env.example`
5. Deploy xong → copy URL (`https://your-bot.onrender.com`)
6. Vào [uptimerobot.com](https://uptimerobot.com) → **New Monitor**:
   - Type: `HTTP(s)` | URL: `https://your-bot.onrender.com/health` | Interval: **5 phút**

Bot sẽ không bao giờ sleep vì UptimeRobot ping mỗi 5 phút.

### Environment Variables cần thiết

```env
TELEGRAM_BOT_TOKEN=...
JINA_API_KEY=...
GROQ_API_KEY=...
CHAT_PROVIDERS=groq,gemini
GROQ_LLM_MODEL=llama-3.1-8b-instant
GEMINI_API_KEY=...          # tùy chọn – fallback khi Groq hết quota
GEMINI_LLM_MODEL=gemini-2.0-flash-lite
SUPABASE_URL=...
SUPABASE_KEY=...
SUPABASE_DB_URL=...
EMBEDDING_DIMENSION=768
```

### Deploy lên Oracle Cloud Always Free (VPS vĩnh viễn miễn phí)

```bash
git clone https://github.com/your/repo.git && cd extract-data
pip install -r requirements.txt
cp .env.example .env && nano .env
screen -S bot
python run.py --no-health
# Ctrl+A, D để detach
```
