# Document Q&A Bot (Discord + Telegram)

Bot hỏi đáp tài liệu với AI, hỗ trợ xuất Excel. Data lưu trên **Supabase** (free).
Chạy được trên **Discord** hoặc **Telegram** (hoặc cả hai).

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
Document → Extract Text → Chunk → Embed (OpenAI) → Store (Supabase pgvector)
(PDF/DOCX/TXT/CSV/...)                                      ↓
Discord / Telegram → Embed Query → Search Similar → GPT-4o-mini → Answer
       "/ask"                                            ↓
                                              "/export" → Excel file
```

## Yêu cầu

1. **Python 3.11+**
2. **OpenAI API Key** – [platform.openai.com](https://platform.openai.com)
3. **Bot Token** (một hoặc cả hai):
   - **Discord** – [discord.com/developers](https://discord.com/developers/applications)
   - **Telegram** – [@BotFather](https://t.me/BotFather)
4. **Supabase Account** (free) – [supabase.com](https://supabase.com)

## Setup

### 1. Supabase (Free Cloud Database)

1. Tạo account tại [supabase.com](https://supabase.com)
2. Tạo project mới (chọn region gần bạn)
3. Vào **SQL Editor** → chạy nội dung file `setup_supabase.sql`
4. Lấy thông tin từ **Settings → API**:
   - `SUPABASE_URL` = Project URL
   - `SUPABASE_KEY` = anon public key
   - `SUPABASE_DB_URL` = **Settings → Database → Connection string (URI)** (thay `[YOUR-PASSWORD]` bằng database password)

### 2a. Tạo Discord Bot

1. Vào [Discord Developer Portal](https://discord.com/developers/applications)
2. **New Application** → đặt tên
3. **Bot** tab → **Reset Token** → copy token → dán vào `DISCORD_BOT_TOKEN` trong `.env`
4. **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Attach Files`, `Use Slash Commands`, `Read Message History`
5. Copy URL → mở trong browser → chọn server → **Authorize**

#### Thêm Discord Bot vào Server / Kênh khác

- **Thêm vào server mới:** Dùng lại invite URL ở bước 5, mở trên browser, chọn server khác → Authorize
- **Chia sẻ cho người khác:** Gửi invite URL cho họ, họ cần quyền `Manage Server` để add bot
- **Giới hạn kênh:** Vào server → chuột phải channel → **Edit Channel → Permissions** → chỉ cho phép bot ở kênh đó
- Bot sẽ tự đồng bộ slash commands khi khởi động (có thể mất vài phút lần đầu)

### 2b. Tạo Telegram Bot

1. Mở Telegram, tìm **@BotFather**
2. Gửi `/newbot` → đặt tên hiển thị → đặt username (phải kết thúc bằng `bot`, VD: `my_qa_bot`)
3. Copy token BotFather trả về → dán vào `TELEGRAM_BOT_TOKEN` trong `.env`
4. (Tùy chọn) Cấu hình thêm với BotFather:
   - `/setdescription` – mô tả bot hiện ở màn hình welcome
   - `/setcommands` – hiển thị gợi ý commands trong menu

   ```
   upload - Upload file để index (PDF, DOCX, TXT...)
   ask - Hỏi về tài liệu đã upload
   extract - Trích xuất data có cấu trúc → Excel
   export - Xuất lịch sử Q&A ra Excel
   files - Xem danh sách file đã index
   delete - Xóa file khỏi vector store theo tên
   ```

#### Thêm Telegram Bot vào Group / Chia sẻ

- **Chat riêng (private):** Tìm `@your_bot_username` trong Telegram → nhấn **Start**
- **Thêm vào Group:**
  1. Mở group chat → nhấn tên group
  2. **Add Members** → tìm `@your_bot_username` → Add
  3. Gửi `/start` trong group để kích hoạt
- **Chia sẻ link:** Gửi link `https://t.me/your_bot_username` cho người khác, họ nhấn vào là chat được ngay
- **Lưu ý Group:** Mặc định bot không đọc được tin nhắn thường trong group (privacy mode). Chỉ đọc được commands (`/ask`, `/upload`...). Nếu muốn bot đọc mọi tin nhắn: vào BotFather → `/mybots` → chọn bot → **Bot Settings → Group Privacy → Turn off**

### 3. Install & Run

```bash
# Clone / copy project
cd pdf-qa-discord-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Copy env file and fill in your keys
cp .env.example .env
# Edit .env with your actual keys

# Run Discord bot
python run.py discord

# OR run Telegram bot
python run.py telegram

# OR run both (2 terminals)
python run.py discord &
python run.py telegram &
```

## Commands

| Command | Discord | Telegram | Mô tả |
|---------|---------|----------| ------|
| `/upload` | ✅ | ✅ (hoặc gửi file trực tiếp) | Upload file để index |
| `/ask <câu hỏi>` | ✅ | ✅ | Hỏi về tài liệu |
| `/extract <mô tả>` | ✅ | ✅ | Trích xuất data → Excel |
| `/export` | ✅ | ✅ | Xuất lịch sử Q&A → Excel |
| `/files` | ✅ | ✅ | Xem danh sách + số thứ tự file đã index |
| `/delete <tên file>` | ✅ | ✅ | Xóa file khỏi vector store |
| `/storage` | ✅ | ✅ | Dung lượng |


## Ví dụ sử dụng

```
/upload          → Attach file (PDF, DOCX, TXT, CSV...) qua Discord hoặc Telegram
/ask Tóm tắt nội dung chính của tài liệu
/ask Liệt kê tất cả các điều khoản về thanh toán
/extract tất cả tên công ty và địa chỉ
/export          → Download Excel with all Q&A history
/storage  Dung lượng
```

## Chi phí

| Service | Cost |
|---------|------|
| Supabase | **Free** (500MB DB, 1GB storage) |
| Discord / Telegram Bot | **Free** |
| OpenAI Embedding | ~$0.02 / 1M tokens (~100 page PDF ≈ $0.01) |
| OpenAI GPT-4o-mini | ~$0.15 / 1M input tokens (mỗi câu hỏi ~$0.001) |

**→ Tổng chi phí cho 100 trang PDF + 100 câu hỏi ≈ $0.10 - $0.20**

## Ai cũng truy cập được?

Data lưu trên Supabase cloud. Để cho người khác truy cập:

1. **Cùng Discord server / Telegram group**: Ai cũng dùng `/ask` được
2. **Qua Supabase REST API**: Uncomment phần view trong `setup_supabase.sql`, người khác query qua:
   ```
   GET https://your-project.supabase.co/rest/v1/pdf_search_documents
   Header: apikey: your-anon-key
   ```
3. **Build thêm web UI**: Dùng Supabase JS client kết nối trực tiếp

## Deploy (Free)

### Option A – Render.com (Web Service free + keep-alive trick)

Bot có sẵn health server tại `GET /health`. Kết hợp với **UptimeRobot** free để không bao giờ sleep:

1. Push code lên GitHub
2. Vào [render.com](https://render.com) → **New → Web Service** (không phải Background Worker)
3. Connect GitHub repo
4. Cấu hình:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python run.py both`
   - **Environment Variables:** điền đủ keys từ `.env.example`
5. Deploy xong → copy URL của service (dạng `https://your-bot.onrender.com`)
6. Vào [uptimerobot.com](https://uptimerobot.com) (free) → **New Monitor**:
   - Type: `HTTP(s)`
   - URL: `https://your-bot.onrender.com/health`
   - Interval: **5 minutes**
7. Bot sẽ không bao giờ sleep vì cứ 5 phút có 1 ping!

### Option B – Railway.app

- Free $5 credit/tháng (~500 giờ chạy)
- Start Command: `python run.py both`
- Sau khi hết credit tháng đó bot tắt, đầu tháng sau tự động bật lại

### Option C – Oracle Cloud Always Free (tốt nhất)

- VPS 2 CPU + 1GB RAM miễn phí **mãi mãi**
- SSH vào, chạy:
  ```bash
  git clone https://github.com/your/repo.git && cd repo
  pip install -r requirements.txt
  cp .env.example .env && nano .env
  screen -S bot
  python run.py both --no-health  # không cần health server trên VPS
  # Ctrl+A, D để detach
  ```
