"""
YouTube OAuth 2.0 초기 인증 스크립트.
최초 1회 로컬에서 실행하여 refresh_token을 발급받습니다.

사전 준비:
1. Google Cloud Console에서 OAuth 2.0 클라이언트 ID 생성 (데스크톱 앱)
2. client_secret.json 다운로드 후 이 스크립트와 같은 디렉토리에 배치

사용법:
  pip install google-auth-oauthlib
  python scripts/setup_youtube_oauth.py
"""
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    credentials = flow.run_local_server(port=8080)

    token_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
    }

    with open("youtube_token.json", "w") as f:
        json.dump(token_data, f, indent=2)

    print("youtube_token.json 생성 완료!")
    print("이 파일을 EC2의 Docker 컨테이너에 배포하세요.")
    print(f"  Refresh Token: {credentials.refresh_token[:20]}...")


if __name__ == "__main__":
    main()
