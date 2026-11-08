# Avatar LiveTalking chạy 0đ: vì sao phải đi qua HLS

Tài liệu này ghi lại các số đã **đo** ngày 31/10 khi nối phòng AVATAR lên staging mà không có máy chủ
riêng (Colab T4 free, không được mở port).

## 1. WebRTC thuần của LiveTalking không đi được từ Colab/tunnel

`--transport webrtc` (mặc định trong `config/livetalking.yaml`) chỉ trao đổi SDP qua HTTP; **media là
UDP WebRTC nối trực tiếp trình duyệt ↔ máy chủ**. Yêu cầu ghi trong `vendored/LiveTalking/README-EN.md:116`
là mở `TCP:8010 + UDP:1-65536`. Colab không cho inbound, còn ngrok/cloudflared chỉ tải HTTP — nên
đường này chỉ chạy khi avatar có IP public thật.

Đã đo thêm: `--stun` chỉ nhận **một** URL và `server/rtc_manager.py:45` dựng `RTCIceServer(urls=opt.stun)`
thẳng ra, không có chỗ cho TURN. Nghĩa là không còn đường nào khác: hết IP public là hết WebRTC.

## 2. Chuỗi đã chọn: rtcpush → MediaMTX → HLS → HTTPS

```
LiveTalking (--transport rtcpush --push_url http://127.0.0.1:8889/avatar/whip)
   │  WHIP (WebRTC publish, UDP loopback — cùng máy Colab nên không cần port mở ra ngoài)
   ▼
MediaMTX  ingest :8889   →   HLS out :8888
   │  chỉ HTTP
   ▼
cloudflared quick tunnel (HTTPS)   →   trình duyệt kéo bằng hls.js
```

`rtcpush` tự mở sẵn session `"0"` lúc khởi động (`app.py:211-216` gọi `handle_rtcpush(push_url, str(k))`
cho `k` từ 0 đến `max_session-1`), nên FE **không cần bắt tay `/offer`**: nó đọc `mediaUrl` từ
`GET /health` của AI service, phát HLS và mở phiên hội thoại với `avatarSessionId = "0"`. Các lệnh
`/human`, `/is_speaking`, `/interrupt_talk` vẫn đi qua AI service như cũ, và các endpoint đó là HTTP
nên tunnel tải được.

## 3. Các số đã đo với MediaMTX (`bluenviron/mediamtx`, 31/10)

| Kiểm tra | Kết quả |
| --- | --- |
| `POST /avatar/whip` kiểu LiveTalking (aiohttp `data=sdp`, không tự set header) | **400** `{"status":"error","error":"invalid Content-Type"}` — aiohttp gửi `Content-Type: text/plain; charset=utf-8` |
| Cùng request với `Content-Type: application/sdp` | **201**, `Content-Type: application/sdp`, body là **SDP trần** → `answer_sdp = await response.text()` của vendor xài được ngay |
| `GET /avatar/index.m3u8` khi chưa có publisher | 302 → `?cookieCheck=1` → **404** `no stream is available on path 'avatar'` |
| `GET /avatar/index.m3u8` khi có publisher | 302 set-cookie → playlist **200** dù request thứ hai **không** gửi cookie (`curl -L` không bật cookie jar) ⇒ `cookieCheck` chỉ để đếm người xem, không chặn playback |
| CORS trên mọi resource HLS | `Access-Control-Allow-Origin` được echo theo `Origin` gọi vào ⇒ FE ở origin khác phát được, không cần proxy |
| Cấu hình HLS | `EXT-X-TARGETDURATION:1`, part `0.2s`, `PART-HOLD-BACK=0.5`, fMP4 `EXT-X-MAP`, video/audio tách playlist |

Phòng AVATAR local phát chuỗi này bằng `hls.js@1.6.11`: `videoWidth=640`, `readyState=4`,
`currentTime` bám live edge (19.8s → 32.6s sau 14s thực, `paused=false`), nút **Bật tiếng avatar**
bỏ `muted` và tiếng vẫn chạy — đúng hành vi Chrome chặn tự phát có tiếng.

## 4. Vá bắt buộc trong vendor code

`vendored/LiveTalking/server/rtc_manager.py` (hàm `handle_rtcpush`) thiếu header nên luôn bị 400.
Vá = thêm `Content-Type: application/sdp` và kiểm tra HTTP status (lỗi push trước đây bị ẩn, biểu
hiện là treo ở `setRemoteDescription`). `scripts/patch_rtcpush_whip.py` áp lại y hệt trên Colab (idempotent)
vì `vendored/` không lên GitHub (`scripts/colab_avatar.sh` clone LiveTalking từ upstream ở bước 0/8).

## 5. Chạy

```bash
# Colab (T4): mở colab-avatar-hls.ipynb, chạy lần lượt 4 cell code.
# Hoặc tay:
bash scripts/colab_avatar.sh
```

Script cài thêm FFmpeg development libraries cần để build RTMP transport (torch CUDA có sẵn của Colab
được giữ nguyên) → tải `wav2lip.pth`
(214MB, HF `shibing624/ai-avatar-wav2lip`) + `s3fd.pth` (90MB) → build pack `vn_interviewer_v1`
từ `assets/vn_interviewer_src.png` (pack không vào git, `.gitignore` loại `data/` và `models/`)
→ MediaMTX → LiveTalking `rtcpush --max_session 1` → tunnel HLS → AI service → tunnel AI.
Hai URL ra `/content/ai_url.txt`, `/content/hls_url.txt` và `/content/avatar_urls.txt`.

Biến môi trường AI service script tự set: `AI_AVATAR_SERVER=http://127.0.0.1:8010`,
`AI_AVATAR_ID=vn_interviewer_v1`, `AI_MEDIA_URL=<tunnel HLS>/avatar/index.m3u8`,
`AI_ALLOWED_ORIGIN=https://aiinterview-vn.vercel.app`.

FE: tại `/mock-interviews`, chọn **LiveTalking Avatar**, dán URL tunnel AI từ Colab, kiểm tra kết nối
rồi lưu trên trình duyệt. Nếu AI service chạy cho cả staging và local, đặt
`AI_ALLOWED_ORIGIN=https://aiinterview-vn.vercel.app,http://localhost:3000`.
`mediaUrl` vẫn được đọc động từ `/health`, không cần build lại FE khi tunnel thay đổi.

## 6. Giới hạn cần biết trước khi hứa với ai đó

* `--max_session 1`: một ứng viên xem avatar mỗi lần; muốn nhiều người cùng lúc thì tăng `MAX_SESSION`
  và cho mỗi session một `push_url`/path HLS riêng (FE hiện chỉ lấy `mediaUrl` từ `/health`).
* Colab free cắt phiên (trần ~12h, hoặc sớm hơn khi thiếu tương tác) ⇒ tunnel đổi URL ⇒ phải sửa env
  Vercel + redeploy. Muốn hết cảnh đó thì cần một hostname ổn định (Cloudflare named tunnel + domain,
  hoặc VPS trả phí).
* Đợi HLS nghĩa là trễ trung bình vài giây so với WebRTC trực tiếp; đủ cho avatar đọc câu hỏi, không đủ
  cho hội thoại hai chiều kiểu gọi video thật.
* `llm_provider` mặc định là `template` (ngân hàng câu hỏi), micro-STT cần `faster-whisper` tải model
  ~500MB lúc khởi động.
