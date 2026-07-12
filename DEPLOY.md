# Deploy bjt_app lên Cloud Run (GCP serverless)

Kiến trúc: **Cloud Run** (host app, scale-to-zero, free tier) + **Firestore**
(lưu `progress.json` + passages, thay cho Neon/local JSON — bền vững qua các
lần container restart) + **Kaggle Model Proxy** (gen text, giữ nguyên, chỉ đổi
cách nạp credentials) + **Vertex AI** (fallback, dùng ADC thay vì file JSON
key). Project dùng chung: `feednotebooklm`, region `us-central1`.

Vì sao `us-central1`: giá Cloud Run/Firestore rẻ nhất trong các region GCP,
và app chỉ mở 2-3 lần/ngày (cá nhân) nên vài chục ms latency thêm do ở xa
VN/Nhật không đáng kể so với mức tiết kiệm chi phí.

---

## 1. One-time setup (chỉ làm 1 lần)

### 1.1. Cài & đăng nhập gcloud CLI

```powershell
gcloud auth login
gcloud config set project feednotebooklm
```

### 1.2. Bật các API cần thiết

```powershell
gcloud services enable `
  run.googleapis.com `
  firestore.googleapis.com `
  secretmanager.googleapis.com `
  cloudbuild.googleapis.com `
  aiplatform.googleapis.com `
  artifactregistry.googleapis.com `
  --project feednotebooklm
```

### 1.3. Tạo Firestore database (Native mode)

```powershell
gcloud firestore databases create --project=feednotebooklm --location=us-central1 --type=firestore-native
```

### 1.4. Tạo secret cho Kaggle credentials

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

### 1.5. Cấp quyền cho Cloud Run service account

```powershell
$PROJECT_NUMBER = (gcloud projects describe feednotebooklm --format="value(projectNumber)")
$SA = "$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding feednotebooklm --member="serviceAccount:$SA" --role="roles/datastore.user"
gcloud projects add-iam-policy-binding feednotebooklm --member="serviceAccount:$SA" --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding feednotebooklm --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor"
```

- `datastore.user` → đọc/ghi Firestore (progress + passages).
- `aiplatform.user` → gọi Vertex AI Gemini qua ADC (không cần file
  `service-account.json` nữa, xem mục 2).
- `secretmanager.secretAccessor` → đọc secret Kaggle ở mục 1.4.

Setup xong tới đây là **xong vĩnh viễn** — các bước dưới đây mới là việc lặp
lại mỗi lần sửa code.

---

## 2. Từ nay về sau: đổi code xong chỉ cần 1 lệnh

```powershell
cd "C:\4. DEV\GitHub(Onlyone)\BJT\BJT"
.\deploy.ps1

```

Script này chạy `gcloud run deploy --source .` — Cloud Build tự build Docker
image từ `Dockerfile`, push, và deploy bản mới lên Cloud Run, in ra URL khi
xong. Không cần build tay, không cần push registry tay.

**Lưu ý bảo mật:** `Dockerfile`/`.dockerignore` cố tình KHÔNG copy
`ai_module/credentials/` vào image. Kaggle credentials tới từ Secret Manager
(mục 1.4), Vertex AI credentials tới từ service account gắn sẵn trên Cloud
Run (ADC) — cả hai không cần file JSON đóng gói trong image.

---

## 3. Vì sao không cần Neon / vì sao BJT-Wiki vẫn giữ

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
  hơn nhiều và đã xử lý bằng LRU cache cục bộ ở lần trước).
- **Neon**: không dùng nữa — toàn bộ state chuyển sang Firestore, cùng một
  GCP project với phần hosting, tránh gọi chéo cloud (AWS Neon ↔ GCP Cloud
  Run) và không cần quản lý thêm 1 free-tier/credential riêng.

---

## 4. Dev local (không đổi gì)

```powershell
python -m bjt_app.app
```

Không có `K_SERVICE` env var → `storage.py` tự dùng lại file JSON local dưới
`data/` như cũ, không cần Firestore/gcloud khi phát triển ở máy.
