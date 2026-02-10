import requests
import json
import time
import base64
import re
import os
import random
import sys
from datetime import datetime

# ==============================================================================
# 환경 변수 설정 (Github Secrets)
# ==============================================================================
CONFIG = {
    "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
    "WP_URL": os.environ.get("WP_URL", ""),
    "WP_USERNAME": os.environ.get("WP_USERNAME", "admin"),
    "WP_APP_PASSWORD": os.environ.get("WP_APP_PASSWORD", ""),
    "NAVER_CLIENT_ID": os.environ.get("NAVER_CLIENT_ID", ""),
    "NAVER_CLIENT_SECRET": os.environ.get("NAVER_CLIENT_SECRET", ""),
    "TEXT_MODEL": "gemini-2.5-flash-preview-09-2025"
}

class WordPressAutoPoster:
    def __init__(self):
        # 설정값 검증
        if not CONFIG["WP_URL"] or not CONFIG["WP_APP_PASSWORD"]:
            print("❌ 오류: WP_URL 또는 WP_APP_PASSWORD가 설정되지 않았습니다.")
            sys.exit(1)
            
        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth = base64.b64encode(user_pass.encode()).decode()
        self.headers = {
            "Authorization": f"Basic {self.auth}",
            "Content-Type": "application/json"
        }

    def random_sleep(self):
        """테스트 시에는 대기를 건너뛰고 싶다면 아래 randint를 (0, 10) 정도로 수정하세요."""
        # 7시~8시 사이 랜덤 발행 (0~3600초)
        wait_seconds = random.randint(0, 3600)
        minutes = wait_seconds // 60
        seconds = wait_seconds % 60
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 랜덤 대기 시작: {minutes}분 {seconds}초 후 포스팅을 시작합니다...")
        time.sleep(wait_seconds)

    def search_naver_news(self, query="국민연금 개혁"):
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 5, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params)
            if res.status_code == 200:
                items = res.json().get('items', [])
                return "\n".join([f"제목: {re.sub('<.*?>', '', i['title'])}\n내용: {re.sub('<.*?>', '', i['description'])}" for i in items])
        except Exception as e:
            print(f"⚠️ 뉴스 검색 중 오류 발생(무시하고 진행): {e}")
            return "국민연금 최신 제도 안내"
        return ""

    def generate_content(self, topic_context):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        system_prompt = """당신은 대한민국 최고의 금융 전문가입니다. 2026년 최신 뉴스를 기반으로 블로그 글을 작성하세요.
        [규칙]
        1. 인사말 및 자기소개 금지. 바로 본론으로 시작.
        2. 구텐베르크 블록 마커(<!-- wp:paragraph --> 등)를 사용하여 구조화.
        3. 한 문단은 3문장 이내로 짧게 구성.
        4. 마크다운 기호(**, #) 사용 금지. 강조는 <strong> 태그 사용.
        5. 수치는 <table> 태그로 정리.
        6. 전체 분량은 3,000자 이상의 매우 상세한 정보 제공."""

        prompt = f"다음 최신 뉴스를 참고하여 2026년 기준의 전문적인 포스팅을 작성해줘:\n{topic_context}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "excerpt": {"type": "string"},
                        "tags": {"type": "string"}
                    },
                    "required": ["title", "content", "excerpt", "tags"]
                }
            }
        }

        res = requests.post(url, json=payload)
        if res.status_code == 200:
            return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
        else:
            print(f"❌ Gemini API 오류: {res.text}")
            sys.exit(1)

    def publish(self, data):
        payload = {
            "title": data['title'],
            "content": data['content'],
            "excerpt": data['excerpt'],
            "status": "publish"
        }
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers=self.headers, json=payload)
        
        if res.status_code == 201:
            return True
        else:
            print(f"❌ 워드프레스 발행 실패 (상태 코드: {res.status_code})")
            print(f"응답 내용: {res.text}")
            return False

    def run(self):
        # 테스트를 위해 랜덤 대기를 건너뛰고 싶으면 아래 줄을 주석 처리(#) 하세요.
        self.random_sleep()
        
        news = self.search_naver_news()
        post_data = self.generate_content(news)
        
        if post_data:
            if self.publish(post_data):
                print(f"🎉 포스팅 성공: {post_data['title']}")
            else:
                sys.exit(1) # 실패 시 에러 종료 (GitHub Actions에 빨간불 표시됨)

if __name__ == "__main__":
    WordPressAutoPoster().run()
