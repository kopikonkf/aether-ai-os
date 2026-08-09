# Aether OS — Peta Lengkap: Dari "Install → ON" sampai Semua Setting

> Dokumen ini menjawab satu pertanyaan: **"Kalau aku punya Aether versiku sendiri, apa saja yang harus kuset supaya tinggal tekan Install lalu ON?"**
>
> Dua perspektif:
> - **User / anak Dee:** Install → masukkan key → tekan ON → langsung jalan.
> - **Engineering (yang sebenernya terjadi):** ada lapisan setting yang saling nyambung. Kalau satu salah, yang lain conflict / diam-diam gagal.
>
> Dokumen ini memetakan keduanya. Dibuat 2026-08-09 dari kondisi nyata VPS.

---

## 0. Gambaran Besar — Aether itu "satu rumah, 4 penghuni"

Bayangkan Aether OS sebagai rumah. Setiap "penghuni" = satu proses yang jalan terus (service), masing-masing di kamar (port) sendiri:

```
                ┌────────────────────────────────────────────────────┐
                │                  INTERNET (dunia luar)              │
                │   https://aethers.my.id  (Basic Auth: founder)     │
                └───────────────────────┬────────────────────────────┘
                                        │
              Cloudflare Tunnel 8f53133 (penjaga pintu depan, HTTPS)
                                        │
                    ┌───────────────────┴───────────────────┐
                    │         Caddy  :8080  (satpam+wali)   │
                    │  Basic Auth founder + routing +       │
                    │  buang header Authorization ke dalam  │
                    └───────────────┬───────────────────────┘
                                    │ 127.0.0.1
              ┌─────────────────────┼──────────────────────┐
              │                     │                      │
      ┌───────┴───────┐    ┌───────┴───────┐       ┌───────┴────────┐
      │ AetherGateway  │    │ AetherWatchdog│       │ AetherCaddy    │
      │  :8000 (otak)  │    │ (jaga jaga)   │       │  :8080 (pintu) │
      └───────┬───────┘    └───────────────┘       └────────────────┘
              │
      ┌───────┴──────────────────────────────────┐
      │  AETHER_HOME = C:\ProgramData\Aether     │
      │  (memory, DB, senses, caddy, services)   │
      └──────────────────────────────────────────┘
```

**Empat penghuni wajib:**
| Service | Port | Peran |
|---|---|---|
| `AetherGateway` | 8000 | Otak. API, kognisi, memori, approval, browser-senses |
| `AetherWatchdog` | — | Penjaga: restart Gateway kalau mati, catat heartbeat |
| `AetherCaddy` | 8080 | Pintu: Basic Auth founder + routing ke Gateway |
| `Cloudflared` | 20120 | Koneksi HTTPS dari internet ke :8080 |

Selain itu ada **alat bantu** yang hidup terpisah (bukan bagian inti Aether):
| Proses | Port | Untuk apa |
|---|---|---|
| `opencode serve` | 3000 | OpenCode versi web (oc.aethers.my.id) |
| Proxima (Electron) | 3210 | Gateway AI (ChatGPT/Claude/Gemini) untuk ship-loop |
| JARVIS | 8010 | Proyek Dee yang terpisah (jarvis.aethers.my.id) |
| ACO monitor | 8011 | Otak ACO (sidecar, terpisah dari Aether) |
| bridge daemon | — | Ship-loop: konek OpenCode ↔ ChatGPT via Telegram |

---

## 1. "Instal → ON" dalam 1 kalimat (perspektif user)

> **1. Install Windows service** → **2. Isi key (Gemini/LiveKit/Telegram)** → **3. Tekan Start** → selesai.

Kira-kira begini yang diharapkan Dee & anaknya. **Yang benar di engineering = bab 2.**

---

## 2. Apa yang SEBENARNYA terjadi saat "Install → ON" (perspektif engineering)

Urutan nyata yang harus dijalankan, dan **kenapa** harus urut ini:

| Langkah | Yang dilakukan | Kenapa wajib | Kalau dilewati |
|---|---|---|---|
| 0. Clone repo | `git clone` aether-ai-os → buat venv | Sumber kode | Tidak ada yang jalan |
| 1. **ACL hardening** | Proteksi `C:\ProgramData\Aether` (SYSTEM+Admins only) | Kunci rumah dulu | File bisa diubah user biasa → bocor |
| 2. **Promote release** | Salin source dari git main → `C:\aether\releases\<sha>` immutable, bind service | Biar yang jalan = versi yang disetujui, bukan sembarang | Service jalan dari kode yang tak terkontrol |
| 3. **Bcrypt founder** | Buat hash password founder, simpan di `founder-auth.caddy` | Dasar Basic Auth | Pintu tanpa kunci |
| 4. **Caddy auth** | Caddy :8080 minta login founder + buang `Authorization` sebelum diteruskan | Hanya founder yang boleh akses; secret tidak bocor ke backend | Siapa pun bisa akses /health, /senses |
| 5. **Tunnel** | Cloudflare tunnel arahkan `aethers.my.id` → `localhost:8080` | Internet bisa masuk | Hanya bisa akses dari dalam VPS |
| 6. **Env keys** | `.env` berisi semua key → dibaca Gateway saat start | LLM/voice/telegram bisa jalan | Gemini 401, LiveKit 401, Telegram mati |
| 7. Start | Gateway/Watchdog/Caddy Running | Semua hidup | — |

**Pelajaran utama:** *Gateway butuh env key, Caddy butuh bcrypt, tunnel butuh Caddy dulu.* Kalau urutan dibalik (misal tunnel dulu sebelum Caddy auth), pintu depan terbuka tanpa satpam.

---

## 3. SEMUA Setting — Kamus Lengkap (siapa, butuh apa, konflik apa)

### 3A. API Keys (yang "dipencet user")

| Key / File | Format | Dipakai siapa | Kenapa penting | Kalau salah |
|---|---|---|---|---|
| `GEMINI_API_KEY` | `AQ.*` (AI Studio) | Gateway → Gemini TTS / chat | Suara & pita | `API_KEY_INVALID`, suara mati |
| `LIVEKIT_URL` | `wss://...` | Gateway → LiveKit (voice realtime) | Realtime voice | Voice realtime gagal |
| `LIVEKIT_API_KEY` | string | Gateway | Join room | Room gagal |
| `LIVEKIT_API_SECRET` | string | Gateway | Sign token | Token invalid |
| `TELEGRAM_BOT_TOKEN` | `123:abc` | Bridge (ship-loop) | Approval via Telegram | Bot mati |
| `GH_TOKEN` | `github_pat_...` | Integrator (push/PR) | Ship-loop ke GitHub | Push gagal |

> ⚠️ **Temuan penting sesi ini:** kuota Gemini dihitung **per project Google Cloud**, bukan per key maupun per akun. Bikin 10 key dalam 1 project = tetap 1 kuota (RPM/RPD/TPM). Multi-key hanya menambah kuota kalau masing-masing terikat ke **project yang berbeda** (atau akun berbeda). Jadi cadangan rate-limit yang benar = pisah project, bukan banyak key dalam satu project.

### 3B. Variabel `.env` (satu file, dibaca Gateway saat start)

File: `aether-core/.env` — **tidak ikut git** (sengaja, biar secret tidak bocor). Kategori:

**Provider / AI:**
| Var | Fungsi |
|---|---|
| `GEMINI_API_KEY` | Gemini TTS/chat |
| `OPENAGENTIC_API_KEY`, `KENARI_API_KEY`, `ARZASTORE_API_KEY` | Provider LLM cadangan |
| `AETHER_GEMINI_MODEL`, `AETHER_CLAUDE_MODEL`, `AETHER_CODEX_MODEL`, `AETHER_OPENCODE_MODEL` | Model default per runtime |
| `AETHER_GEMINI_BIN` / `AETHER_CLAUDE_BIN` / `AETHER_CODEX_BIN` / `AETHER_OPENCODE_BIN` | Path binary CLI agent |

**Keamanan:**
| Var | Fungsi |
|---|---|
| `AUTH_SECRET_KEY` | Secret utama (HMAC) |
| `AETHER_OPERATOR_ID` / `AETHER_OPERATOR_TOKEN` | Identitas founder / token operator |
| `AETHER_BROWSER_SENSE_SECRET` | Secret sesi browser-senses |
| `AETHER_SENSE_WORKER_TOKEN` | Token worker voice |

**Telegram:**
| Var | Fungsi |
|---|---|
| `TELEGRAM_ENABLED` | On/off bot |
| `TELEGRAM_BOT_TOKEN` | Token bot |
| `TELEGRAM_ALLOWED_USER_IDS` | Siapa boleh chat (whitelist) |

**Senses / Voice:**
| Var | Fungsi |
|---|---|
| `LIVEKIT_URL/API_KEY/API_SECRET/AGENT_NAME` | LiveKit voice |
| `AETHER_STT_MODEL`, `AETHER_TTS_MODEL`, `AETHER_TTS_VOICE`, `AETHER_TURN_DETECTOR`, `AETHER_SENSE_GREETING` | Model STT/TTS, suara, sapaan |
| `AETHER_BROWSER_SENSE_TTL_SECONDS`, `AETHER_VISION_MAX_FRAME_BYTES` | Batas sesi/frame |

**Platform:**
| Var | Fungsi |
|---|---|
| `AETHER_HOME` | Lokasi data (default `C:\ProgramData\Aether`) |
| `HOST`, `PORT`, `MCP_MODE`, `AETHER_GATEWAY_URL` | Listen address, mode MCP, URL gateway |
| `AETHER_FLEET_SCHEDULER_ENABLED`, `AETHER_FLEET_POLL_INTERVAL_SECONDS`, `AETHER_FLEET_AUTO_RENEW` | Scheduler internal |
| `AETHER_MISSION_MAX_STEPS_PER_RUN` | Batas step misi |
| `AETHER_PUBLIC_BASE_URL` | URL publik |
| `AETHER_OPENCODE_ZEN_1/2/3` | Token OpenCode Zen (cadangan model) |

> ⚠️ **Konflik yang sering terjadi:** kalau `AETHER_HOME` salah, Gateway cari DB di tempat lain → memory "hilang". Kalau `HOST`/`PORT` bentrok dengan service lain, Gateway gagal bind.

### 3C. Config file (bukan env, tapi YAML)

| File | Fungsi | Di mana |
|---|---|---|
| `gemini_tts_founder_alpha.yaml` | Config suara Founder Alpha (model, voice `Aoede`, consent, free-tier) | `configs/runtime/` |
| `persona.yaml` | Kepribadian Aether (preset delivery suara) | `aether-core/configs/` |
| `voice_portfolio.yaml` | Daftar kandidat suara | `configs/candidates/` |
| `founder-auth.caddy` | Hash bcrypt password founder (di-proteksi, SYSTEM+Admins) | `C:\ProgramData\Aether\caddy\` |
| `Caddyfile` | Routing Caddy + `import founder-auth.caddy` | `C:\ProgramData\Aether\caddy\` |
| `config.yml` (cloudflared) | Rute tunnel: `aethers→:8080`, `oc→:3000`, `jarvis→:8010`, fallback 404 | `~/.cloudflared/` |

### 3D. AETHER_HOME (memory & state — TIDAK di git)

`C:\ProgramData\Aether\` berisi semua data hidup:
```
db/           → SQLite (memory, sessions, governance, fleet)
memory/       → canonical memory, retrieval index, knowledge proposals
senses/       → browser-senses, vision, voice auditions, acceptance runs
runtime/      → bridge, relay, ingress, releases
services/     → service-manifest.json, heartbeats, release-promotion.json
caddy/        → Caddyfile + founder-auth.caddy
events/       → EventBus journal (browser-senses.jsonl, sense-path.jsonl)
```

> ⚠️ **Pindah VPS:** kalau mau bawa "ingatan" Aether, ini harus **di-export/import** (`EXPORT_AETHER_HOME.ps1` / `IMPORT_AETHER_HOME.ps1` di repo). Source code bisa `git clone`, tapi memory/DB tidak ikut git.

---

## 4. Alur Trafik (siapa memanggil siapa, biar paham "lari kesana")

```
USER (browser)
  │ GET https://aethers.my.id/senses
  ▼
Cloudflare Tunnel  →  Caddy :8080
                        │ Basic Auth (founder bcrypt) → OK?
                        │ header_up -Authorization (buang secret)
                        ▼
                      reverse_proxy 127.0.0.1:8000
                        ▼
                      AetherGateway
                        │ baca .env (GEMINI_API_KEY, dsb)
                        ├─→ Gemini API (TTS suara)
                        ├─→ LiveKit (voice realtime, jika dipakai)
                        ├─→ memory/DB (AETHER_HOME)
                        └─→ bridge (Telegram approval, ship-loop)
```

**Kenapa `header_up -Authorization` penting:** Caddy buang header Authorization sebelum diteruskan ke Gateway, supaya key/secret user tidak sampai ke backend kognisi. Itu temuan penting dari review ChatGPT dulu.

---

## 5. Checklist "Anakku punya Aether sendiri" (dari nol)

Versi paling sederhana (source present, non-LiveKit) — cukup buat **dipakai**, belum perlu realtime voice:

1. **Buat project Google AI Studio** → buat 1 API key (`AIza...` atau `AQ.*` dari AI Studio).
2. **Clone repo** → `pip install -e aether-core -e aether-gateway`.
3. **Buat `.env`** di `aether-core/` → isi minimal:
   - `GEMINI_API_KEY=<key baru>`
   - `AETHER_HOME=C:\ProgramData\Aether`
   - `AUTH_SECRET_KEY=<acak 32+>`, `AETHER_OPERATOR_ID=founder`, `AETHER_OPERATOR_TOKEN=<acak>`
4. **`install-aether-services.ps1`** (ACL + service Gateway/Watchdog/Caddy).
5. **Promote** release dari git main (pakai `promote-aether-release.ps1`).
6. **Bcrypt founder** → `founder-auth.caddy` → Caddy minta login.
7. **Kalau mau akses internet:** Cloudflare tunnel → `aethers.my.id → :8080` (butuh domain + akun CF).
8. **Tekan Start** → Gateway/Watchdog/Caddy Running.

**Tanpa LiveKit/Tunnel = Aether tetap jalan di lokal** (akses `http://127.0.0.1:8080` pakai login founder). Itu cara termudah buat belajar.

Untuk versi **penuh** (voice realtime), tambah: key LiveKit (`LIVEKIT_URL/API_KEY/API_SECRET`) + install `livekit-api` di venv.

---

## 6. Cara Menyimpan Setting (best practice yang dipakai di sini)

| Jenis | Disimpan di | Kenapa |
|---|---|---|
| Secret/key | `.env` (tidak di git) | Tidak bocor ke repo |
| Config non-secret | `configs/*.yaml` (di git) | Ikut review & versioning |
| Password founder | `founder-auth.caddy` (file protected) | Caddy baca langsung |
| State/memory | `AETHER_HOME` (tidak di git) | Data hidup, di-export manual |

---

## 7. One-liner ringkas (untuk diingat)

> **Gateway = otak** (butuh `.env`), **Caddy = pintu** (butuh bcrypt), **Tunnel = jembatan** (butuh Caddy), **AETHER_HOME = memori** (tidak di git, di-export saat pindah). **Urutan: clone → ACL → promote → bcrypt → Caddy → tunnel → env → ON.**

---

*Dokumen ini dibuat dari observasi nyata VPS 2026-08-09. Nilai secret tidak pernah ditampilkan.*
