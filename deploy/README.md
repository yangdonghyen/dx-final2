# 배포 (네이버 클라우드, Ubuntu)

DB는 기존 공유 MySQL을 그대로 쓰고, 서버에는 FastAPI만 올린다.

1. 서버 만들기: Ubuntu 22.04/24.04, 공인 IP, ACG에서 80(및 443) 허용. SSH는 22.
2. 공유 MySQL이 IP 허용 목록을 쓰면 서버 공인 IP를 추가한다.
3. 서버에서:
   ```
   git clone https://github.com/yangdonghyen/dx-final2.git /opt/travelmate
   # 내 PC의 backend/.env 를 /opt/travelmate/backend/.env 로 직접 복사 (git에 없음)
   sudo bash /opt/travelmate/deploy/setup_server.sh
   ```
4. `.env`에서 서버용 값 바꾸기 (비밀키 그대로):
   - `PUBLIC_SHARE_BASE_URL=http://<공인IP 또는 도메인>`
   - `EXAONE_BASE_URL` : 아래 EXAONE 선택에 따라
   그다음 `sudo systemctl restart travelmate`
5. 앱: `frontend/flutter/.dart_define.prod.json`에 `API_BASE_URL=http(s)://<서버>` 로 빌드.
   릴리스 앱은 http를 막으므로 HTTPS(도메인+인증서) 또는 앱에 http 허용 설정이 필요하다.
6. 유튜브 확장(tools/chrome_youtube_pause_bridge): `config.js`와 `manifest.json`의 서버 주소를 바꾸고 확장 새로고침.

## EXAONE(Ollama)
- 서버에 GPU가 없으면 일정 생성이 수십 분 걸린다.
- 시연용: PC의 Ollama를 SSH 역방향 터널로 서버에 연결
  `ssh -N -R 11434:127.0.0.1:11434 root@<서버IP>` (PC에서 실행, 시연 중 유지)
  → 서버 `.env`의 `EXAONE_BASE_URL=http://127.0.0.1:11434`
- GPU 서버가 있으면 거기에 Ollama 설치 후 같은 모델을 받는다.

## 업데이트
```
cd /opt/travelmate && git pull && sudo systemctl restart travelmate
```
DB 스키마 변경이 있으면 `backend/.venv/bin/python -m alembic upgrade head` (공유 DB이므로 팀에 먼저 알린다).
