# Deploy bjt_app lên Cloud Run (GCP serverless)

Kiến trúc: **Cloud Run** (host app, scale-to-zero, free tier) + **Firestore**
(lưu `progress.json` + passages, thay cho Neon/local JSON — bền vững qua các
lần container restart) + **Kaggle Model Proxy** (gen text, giữ nguyên, chỉ đổi
cách nạp credentials) + **Vertex AI** (fallback, dùng ADC thay vì file JSON
key) + **Cloud Text-to-Speech** (audio narration) + **Cloud Storage** (cache
audio). Project dùng chung: `feednotebooklm`, region `us-central1`.

Vì sao `us-central1`: giá Cloud Run/Firestore rẻ nhất trong các region GCP,
và app chỉ mở 2-3 lần/ngày (cá nhân) nên vài chục ms latency thêm do ở xa
VN/Nhật không đáng kể so với mức tiết kiệm chi phí.

Tài liệu chia 2 phần theo tần suất bạn thực sự cần làm:
- **Phần A — Deploy mới**: chỉ làm khi setup project lần đầu, hoặc khi thêm
  một hạ tầng mới (API, bucket, secret...) — không phải việc lặp lại mỗi
  lần sửa code.
- **Phần B — Deploy mỗi khi có thay đổi mới**: quy trình lặp lại mỗi lần
  đổi code, chỉ 1 lệnh.

---

## Phần A — Deploy mới (one-time, chỉ làm khi setup lần đầu / thêm hạ tầng)

## A.1. Cài & đăng nhập gcloud CLI

```powershell
gcloud auth login
gcloud config set project feednotebooklm
```

## A.2. Bật các API cần thiết

```powershell
gcloud services enable `
  run.googleapis.com `
  firestore.googleapis.com `
  secretmanager.googleapis.com `
  cloudbuild.googleapis.com `
  aiplatform.googleapis.com `
  artifactregistry.googleapis.com `
  texttospeech.googleapis.com `
  --project feednotebooklm
```

## A.3. Tạo Firestore database (Native mode)

```powershell
gcloud firestore databases create --project=feednotebooklm --location=us-central1 --type=firestore-native
```

## A.4. Tạo secret cho Kaggle credentials

`ai_module/credentials/kaggle/kaggle.json` hiện chỉ có `username`/`api_key`
điền sẵn (`model_proxy_url`/`model_proxy_api_key` để trống — account chưa
chạy `kaggle benchmarks auth`), nên secret cần tạo là **username + api_key**,
không phải model-proxy. Lấy 2 giá trị đó từ file (không paste secret vào
chat với AI hay commit vào git), rồi tạo secret:

```powershell
"<YOUR_KAGGLE_USERNAME>" | gcloud secrets create bjt-kaggle-username --data-file=- --project feednotebooklm
"<YOUR_KAGGLE_API_KEY>"  | gcloud secrets create bjt-kaggle-api-key  --data-file=- --project feednotebooklm
```

Nếu sau này đổi key (đổi account, hoặc re-generate API key trên Kaggle),
update bằng:

```powershell
"<NEW_VALUE>" | gcloud secrets versions add bjt-kaggle-api-key --data-file=- --project feednotebooklm
```

> Nếu sau này bạn chạy `kaggle benchmarks auth` và có được
> `model_proxy_url`/`model_proxy_api_key` (auth trực tiếp, không cần đổi
> proxy token mỗi ~2h), có thể tạo thêm 2 secret `bjt-model-proxy-url` /
> `bjt-model-proxy-api-key` và đổi `--set-secrets` trong `deploy.ps1` thành
> `MODEL_PROXY_URL=...,MODEL_PROXY_API_KEY=...` — `kaggle_client.py` đã hỗ
> trợ sẵn cả hai cách, ưu tiên model-proxy nếu có.

## A.5. Tạo bucket GCS cho cache audio TTS

Audio narration (mục C.2) được cache trong Cloud Storage thay vì Firestore
(blob nhị phân không hợp với giới hạn 1MB/doc của Firestore). Tạo bucket
1 lần, region trùng với Cloud Run để tránh phí egress liên vùng:

```powershell
gcloud storage buckets create gs://feednotebooklm-bjt-tts-cache --project=feednotebooklm --location=us-central1 --uniform-bucket-level-access
```

(Đổi tên bucket bằng cách set env `BJT_TTS_BUCKET` trong `deploy.ps1` nếu
muốn dùng tên khác.)

## A.6. Bật tự động dọn dẹp audio cũ không dùng tới

Để cache audio không tăng vô hạn và luôn nằm trong free tier, gắn
**lifecycle rule** cho bucket: tự xóa file audio nào không được nghe lại
trong 30 ngày. App đã tự "chạm" (`custom_time`) vào file mỗi lần cache hit
(`bjt_app/storage.py::_touch_blob`), nên đây là kiểu dọn dẹp LRU theo lần
nghe gần nhất, không phải theo tuổi file — bài hay nghe lại dù cũ vẫn
không bị xóa, chỉ bài bỏ quên mới bị dọn. Không cần cron job riêng, GCS tự
làm nền:

```powershell
@'
{
  "rule": [
    {
      "action": { "type": "Delete" },
      "condition": { "daysSinceCustomTime": 30 }
    }
  ]
}
'@ | Out-File -Encoding utf8 lifecycle_tts_cache.json

gcloud storage buckets update gs://feednotebooklm-bjt-tts-cache --lifecycle-file=lifecycle_tts_cache.json
```

Kiểm tra rule đã áp dụng:

```powershell
gcloud storage buckets describe gs://feednotebooklm-bjt-tts-cache --format="default(lifecycle_config)"
```

(30 ngày là gợi ý — muốn giữ lâu/ngắn hơn thì đổi số trong
`daysSinceCustomTime` rồi chạy lại lệnh `buckets update` ở trên. Với tần
suất dùng 2-3 bài/ngày và ít khi nghe lại bài cũ quá 1 tháng, 30 ngày vẫn
đủ giữ audio đang dùng, đồng thời dọn dẹp nhanh hơn để bucket luôn nhỏ gọn.)

## A.7. Cấp quyền cho Cloud Run service account

```powershell
$PROJECT_NUMBER = (gcloud projects describe feednotebooklm --format="value(projectNumber)")
$SA = "$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding feednotebooklm --member="serviceAccount:$SA" --role="roles/datastore.user"
gcloud projects add-iam-policy-binding feednotebooklm --member="serviceAccount:$SA" --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding feednotebooklm --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor"
gcloud storage buckets add-iam-policy-binding gs://feednotebooklm-bjt-tts-cache --member="serviceAccount:$SA" --role="roles/storage.objectAdmin"
```

- `datastore.user` → đọc/ghi Firestore (progress + passages).
- `aiplatform.user` → gọi Vertex AI Gemini qua ADC (không cần file
  `service-account.json` nữa, xem Phần B).
- `secretmanager.secretAccessor` → đọc secret Kaggle ở mục A.4.
- `storage.objectAdmin` (chỉ trên bucket TTS cache) → đọc/ghi file audio đã
  sinh. Cloud Text-to-Speech API tự dùng ADC của service account này, không
  cần thêm role riêng (không có resource-level ACL để cấp).

## A.8. Kiểm tra nhanh ở local trước khi deploy lần đầu (khuyến nghị)

```powershell
cd "C:\4. DEV\GitHub(Onlyone)\BJT\BJT"
python -m bjt_app.app
```

Mở `http://localhost:5013`, vào menu **🌿 Life Style**, mở thử 1 bài, bấm
"🔊 Nghe bài đọc" — xác nhận chạy được ở máy local trước (dùng credentials
ADC cá nhân, không đụng tới Cloud Run) trước khi deploy thật.

Setup xong tới đây là **xong vĩnh viễn** — Phần B dưới đây mới là việc lặp
lại mỗi lần sửa code.

---

## Phần B — Deploy mỗi khi có thay đổi mới

## B.1. Chạy 1 lệnh

```powershell
cd "C:\4. DEV\GitHub(Onlyone)\BJT\BJT"
.\deploy.ps1
```

Script này chạy `gcloud run deploy --source .` — Cloud Build tự build Docker
image từ `Dockerfile`, push, và deploy bản mới lên Cloud Run, in ra URL khi
xong. Không cần build tay, không cần push registry tay.

**Lưu ý bảo mật:** `Dockerfile`/`.dockerignore` cố tình KHÔNG copy
`ai_module/credentials/` vào image. Kaggle credentials tới từ Secret Manager
(mục A.4), Vertex AI credentials tới từ service account gắn sẵn trên Cloud
Run (ADC) — cả hai không cần file JSON đóng gói trong image.

## B.2. Kiểm tra sau khi deploy

1. Mở URL Cloud Run (in ra ở cuối bước B.1) → menu **🌿 Life Style** → danh
   sách hiện ra, có 2604 bài, chia 2 khu Chưa đọc/Đã đọc.
2. Mở 1 bài bất kỳ → chờ vài giây (lần đầu AI sinh từ vựng/ngữ pháp) → xác
   nhận hiện đúng, có nút ⭐ đánh dấu.
3. Bấm "🔊 Nghe bài đọc" → chờ vài giây (lần đầu sinh audio) → xác nhận
   phát được. Bấm lại (F5 refresh trang rồi bấm nghe lại) → phải phát gần
   như ngay lập tức (đang lấy từ cache, không gọi lại AI).
4. Tick "đã đọc" 1 bài trong danh sách → xác nhận bài chuyển sang khu vực
   "Đã đọc" đúng.
5. Vào `/settings` → xác nhận có phần "Giọng đọc audio", đổi thử giọng →
   lưu → mở lại 1 bài đã nghe trước đó, bấm nghe → phải sinh audio MỚI
   theo giọng vừa đổi (không phát nhầm giọng cũ đã cache).

## B.3. Xác nhận hạ tầng đã tạo đúng chỗ (tùy chọn, để yên tâm)

```powershell
# Kiểm tra bucket có file audio sau khi bấm nghe vài bài ở bước B.2
gcloud storage ls gs://feednotebooklm-bjt-tts-cache --project feednotebooklm

# Kiểm tra Firestore có collection mới
# (mở Firestore console: https://console.cloud.google.com/firestore/databases/-default-/data?project=feednotebooklm)
# -> phải thấy collection "bjt_lifestyle_analysis" và doc "bjt_state/lifestyle"
```

## B.4. Theo dõi free tier (không bắt buộc ngay, nhưng nên biết chỗ xem)

Mỗi dịch vụ có 1 trang xem dung lượng/usage riêng — bookmark lại, thỉnh
thoảng liếc qua vài giây là đủ, không cần theo dõi liên tục:

| Dịch vụ | Xem gì | Link | Ngưỡng free tier |
|---|---|---|---|
| **Cloud Storage** (bucket audio) | Tổng dung lượng đang lưu (byte) | [Bucket → tab "Configuration"](https://console.cloud.google.com/storage/browser/feednotebooklm-bjt-tts-cache;tab=configuration?project=feednotebooklm) | 5GB (Always Free) |
| **Cloud Storage** (chi tiết theo ngày) | Biểu đồ dung lượng + số request theo thời gian | [Monitoring → Metrics Explorer, lọc theo bucket](https://console.cloud.google.com/monitoring/metrics-explorer?project=feednotebooklm) | 5GB + 5K Class A / 50K Class B ops/tháng |
| **Text-to-Speech API** | Số request/ký tự đã gọi | [API → Metrics](https://console.cloud.google.com/apis/api/texttospeech.googleapis.com/metrics?project=feednotebooklm) | ~1 triệu ký tự/tháng (giọng Neural2) |
| **Firestore** | Dung lượng lưu + số đọc/ghi/xóa mỗi ngày | [Firestore → Usage](https://console.cloud.google.com/firestore/databases/-default-/usage?project=feednotebooklm) | 1GB storage, 50K đọc + 20K ghi + 20K xóa/ngày |
| **Firestore** (xem trực tiếp dữ liệu) | Từng collection/document thật | [Firestore → Data](https://console.cloud.google.com/firestore/databases/-default-/data?project=feednotebooklm) | — |
| **Vertex AI (Gemini)** | Số request/token đã gọi (khi Kaggle lỗi, fallback sang đây) | [Vertex AI → API Metrics](https://console.cloud.google.com/apis/api/aiplatform.googleapis.com/metrics?project=feednotebooklm) | tính phí theo token, không có free tier riêng — xem mục C.2 |
| **Cloud Run** | Số request, CPU/memory, instance-giờ | [Cloud Run → bjt-app → Metrics](https://console.cloud.google.com/run/detail/us-central1/bjt-app/metrics?project=feednotebooklm) | 2 triệu request + 360K GB-giây/tháng |
| **Tổng hợp mọi dịch vụ (đơn giản nhất)** | Có phát sinh phí ở đâu không — nếu vẫn trong free tier, các dòng ở đây phải là **$0.00** | [Billing → Reports](https://console.cloud.google.com/billing/reports?project=feednotebooklm) | mọi thứ ở trên |

Cách kiểm tra nhanh nhất khi lười mở từng trang: chỉ cần vào **Billing →
Reports** ở dòng cuối — nếu tổng chi phí project vẫn là $0.00 thì mọi dịch
vụ đều đang nằm trong free tier, không cần xem chi tiết từng cái.

Với tần suất dùng cá nhân 2-3 bài/ngày, các số liệu này sẽ nằm rất sâu
trong free tier (xem tính toán chi tiết ở mục C.1–C.2 dưới đây) — chỉ cần
liếc qua sau 1-2 tuần đầu dùng thật để chắc chắn không có gì bất thường
(ví dụ lỡ bấm nghe rất nhiều bài dài liên tục).

---

## Phần C — Kiến trúc & lý do thiết kế (tham khảo, không phải việc cần làm)

## C.0. Vì sao không cần Neon / vì sao BJT-Wiki vẫn giữ

- **BJT-Wiki (`BJT-Wiki/*.md`, 644KB)**: vẫn cần thiết, không phải gánh nặng
  lưu trữ — đây là kho từ vựng/ngữ pháp/mẫu câu đã phân loại JLPT level thủ
  công mà `progress.py` dùng để xoay vòng "focus" mỗi ngày (không lặp lại,
  không phụ thuộc AI tự bịa từ vựng sai cấp độ) và `passage_generator.py`
  dùng để seed prompt cho Kaggle/Vertex. Vì không đổi lúc runtime, nó được
  bake thẳng vào Docker image (đọc read-only), không tốn Firestore/Neon.
- **progress.json + passages**: chuyển từ file JSON local sang Firestore
  (`bjt_state`/`bjt_passages` collections, xem `bjt_app/storage.py`) vì Cloud
  Run xóa local disk mỗi lần container restart/scale-to-zero. Với dùng cá
  nhân (~1 bài/ngày, mỗi bài 10-25KB), kể cả dùng nhiều năm cũng chỉ vài MB —
  nằm sâu trong free tier Firestore (1GB storage, 50K đọc + 20K ghi/ngày) nên
  KHÔNG cần cơ chế dọn định kỳ cho phần này (khác với audio cache, vốn nặng
  hơn nhiều và đã xử lý bằng LRU cache, xem C.2).
- **Neon**: không dùng nữa — toàn bộ state chuyển sang Firestore, cùng một
  GCP project với phần hosting, tránh gọi chéo cloud (AWS Neon ↔ GCP Cloud
  Run) và không cần quản lý thêm 1 free-tier/credential riêng.

## C.1. Life Style (`bjt_app/lifestyle.py`) — cùng nguyên tắc tối ưu dung lượng

- **2604 bài đọc gốc** (`bjt_app/lifestyle_data/readings.json`, ~6.1MB): tĩnh,
  không đổi lúc runtime → bake thẳng vào Docker image như BJT-Wiki, không
  lưu Firestore. Furigana render on-the-fly bằng MeCab (`furigana.py`), như
  các bài đọc hằng ngày, không tốn AI call.
  > File Excel gốc có 2727 bài duy nhất, nhưng 123 bài dài bất thường
  > (>10.000 ký tự, có bài tới 32.767 ký tự = đúng giới hạn 1 cell Excel —
  > nhiều khả năng là lỗi gộp nhiều bài/nội dung không phải bài đọc ngắn
  > thông thường) đã bị loại bỏ khỏi kho, để tránh audio TTS phồng to bất
  > thường (xem C.2) và giữ độ dài mỗi bài đồng đều (~1.5-2K ký tự, tối đa
  > ~2060 ký tự) — đúng dạng bài đọc ngắn phù hợp luyện đọc hằng ngày.
- **Từ vựng/ngữ pháp trọng điểm mỗi bài**: sinh **lười (lazy)** bằng Kaggle/
  Vertex AI, chỉ khi user thực sự mở bài đó lần đầu (`lifestyle.get_or_create_analysis`),
  rồi cache trong Firestore collection `bjt_lifestyle_analysis` (1 doc/bài đã
  mở). Vì dùng cá nhân, số bài thực sự mở ra chỉ là một phần rất nhỏ trong
  2604 bài → tránh việc gọi AI + tốn quota cho toàn bộ kho ngay từ đầu.
- **Trạng thái đã đọc**: 1 doc nhỏ `bjt_state/lifestyle` (giống `bjt_state/progress`),
  chỉ chứa map `{reading_id: timestamp}` của các bài đã đọc.

## C.2. Text-to-speech (`bjt_app/tts.py`) — tính toán để ở trong free tier

- **Engine**: Cloud Text-to-Speech, giọng **Neural2** tiếng Nhật (mặc định
  `ja-JP-Neural2-B`, đổi được ở `/settings`) — KHÔNG dùng Gemini audio-out
  qua Vertex AI, vì Cloud TTS có free tier riêng vĩnh viễn (~1 triệu ký
  tự/tháng cho Neural2/WaveNet), còn Gemini audio-out tính phí theo token
  như text bình thường, không có hạn mức miễn phí riêng.
- **Ước tính dùng thực tế**: 2-3 bài/ngày × trung bình ~1.5-2K ký tự/bài
  (tối đa ~2060 ký tự/bài — 123 bài Life Style dài bất thường tới ~30K ký
  tự đã bị loại khỏi kho, xem C.1) × 30 ngày ≈ 100-150K ký tự/tháng, chỉ
  bằng 10-15% free tier Neural2 → còn nhiều dư địa kể cả khi nghe lại nhiều
  lần cùng 1 bài (cache tránh gọi lại API cho lần nghe sau, xem dưới).
- **Chunking**: Cloud TTS giới hạn 5000 byte/request; bài dài được cắt theo
  câu (`。！？`/xuống dòng) thành các đoạn ≤1400 ký tự rồi ghép các đoạn MP3
  lại. Với độ dài tối đa hiện tại (~2060 ký tự) mỗi bài chỉ cần tối đa ~2
  chunk, audio ra khoảng vài trăm KB/bài — không còn rủi ro file audio
  phồng to như trước khi loại bỏ các bài dài bất thường.
- **Cache 2 lớp, tránh gọi lại API**:
  1. **Server-side** (`storage.save_tts_audio`/`load_tts_audio`): GCS bucket
     `feednotebooklm-bjt-tts-cache` (không phải Firestore — blob nhị phân
     không hợp giới hạn 1MB/doc, và tách riêng khỏi free tier 1GB dành cho
     state text), key theo `{kind}__{id}__{voice}` — mỗi bài/giọng chỉ
     sinh audio đúng 1 lần trong suốt vòng đời app, dù ai/thiết bị nào mở.
  2. **Client-side**: response set `Cache-Control: public, max-age=31536000,
     immutable`, để trình duyệt/điện thoại tự cache file audio sau lần nghe
     đầu — nghe lại (kể cả offline nếu đã cache) không tốn round-trip mạng.
  Vì dùng cá nhân, chỉ những bài thực sự bấm nghe mới tốn dung lượng GCS —
  không có quy trình chạy trước cho toàn bộ kho.
- Audio sinh **lười theo yêu cầu** (bấm nút "🔊 Nghe bài đọc" mới gọi API),
  không tự động phát/tải khi mở trang, giống cách `lifestyle.get_or_create_analysis`
  xử lý từ vựng/ngữ pháp.
- **Dọn dẹp tự động (LRU theo lần nghe gần nhất, không phải theo tuổi file)**:
  mỗi lần cache hit, `storage._touch_blob` cập nhật `custom_time` của object
  trong GCS thành thời điểm hiện tại; bucket có lifecycle rule tự xóa object
  nào `daysSinceCustomTime` > 30 ngày (setup ở mục A.6). Nhờ "chạm" lại mỗi
  lần nghe, bài hay nghe lại dù cũ vẫn không bị xóa — chỉ audio thực sự bị
  bỏ quên >1 tháng mới bị GCS tự dọn, không cần cron job hay Cloud Scheduler
  riêng. Đây là cùng ý tưởng LRU cache cục bộ đã dùng cho audio cache ở app
  trước, chỉ khác là thực hiện bằng tính năng lifecycle có sẵn của GCS thay
  vì tự viết vòng lặp dọn dẹp.

---

## Phần D — Dev local (không đổi gì)

```powershell
python -m bjt_app.app
```

Không có `K_SERVICE` env var → `storage.py` tự dùng lại file JSON local dưới
`data/` như cũ, không cần Firestore/gcloud khi phát triển ở máy.
