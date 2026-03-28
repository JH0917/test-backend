import os
import json
import asyncio
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN_PATH = os.getenv("YOUTUBE_TOKEN_PATH", "/app/youtube_token.json")


def _get_authenticated_service():
    """저장된 refresh token으로 YouTube API 서비스를 생성한다."""
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(
            f"YouTube 토큰 파일이 없습니다: {TOKEN_PATH}\n"
            "로컬에서 OAuth 인증을 먼저 수행하고 토큰 파일을 배포하세요."
        )

    with open(TOKEN_PATH, "r") as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=["https://www.googleapis.com/auth/youtube"],
    )

    if creds.expired or not creds.token:
        creds.refresh(Request())
        token_data["token"] = creds.token
        with open(TOKEN_PATH, "w") as f:
            json.dump(token_data, f)

    return build("youtube", "v3", credentials=creds)


def _upload_sync(video_path: str, title: str, description: str, tags: list[str]) -> dict:
    """동기 업로드 실행."""
    youtube = _get_authenticated_service()

    body = {
        "snippet": {
            "title": title,
            "description": f"{description}\n\n#밸런스게임 #양자택일 #Shorts",
            "tags": list(dict.fromkeys(tags + ["Shorts", "밸런스게임", "양자택일"])),
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = request.execute()

    return {
        "video_id": response["id"],
        "url": f"https://youtube.com/shorts/{response['id']}",
        "title": title,
    }


async def upload_to_youtube(video_path: str, title: str, description: str, tags: list[str]) -> dict:
    """영상을 YouTube에 업로드한다. (이벤트 루프 블로킹 방지)"""
    return await asyncio.to_thread(_upload_sync, video_path, title, description, tags)
