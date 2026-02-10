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
        # 1. 설정값 존재 여부 검증 (디버깅 강화)
        print("--- 환경 변수 점검 ---")
        for key in ["WP_URL", "WP_APP_PASSWORD", "GEMINI_API_KEY"]:
            val = CONFIG[key]
            if not val:
                print(f"❌ 오류: '{key}' 환경 변수가 비어 있습니다. Github Secrets 설정을 확인하세요.")
            else:
                # 보안을 위해 앞글자만 출력
                print(f"✅ '{key}' 로드 완료: {val[:8]}...")

        if not CONFIG["WP_URL"] or not CONFIG["WP_APP_PASSWORD"] or not CONFIG["GEMINI_API_KEY"]:
            sys.exit(1)
            
        # 2. URL 형식 검증
        if not CONFIG["WP_URL"].startswith("http"):
            print("❌ 오류: WP_URL은 반드시 https:// 또는 http://로 시작해야 합니다.")
            sys.exit(1)
        CONFIG["WP_URL"] = CONFIG["WP_URL"].rstrip("/")

        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth = base64.b64encode(user_pass.encode()).decode()
        self.headers = {
            "Authorization": f"Basic {self.auth}",
            "Content-Type": "application/json"
        }

    def random_sleep(self):
        # 테스트를 위해 대기 시간을 1~5초로 줄였습니다. (실제 운영 시 random.randint(0, 3600) 권장)
        wait_seconds = random.randint(1, 5) 
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 시작 전 대기: {wait_seconds}초...")
        time.sleep(wait_seconds)

    def search_naver_news(self, query="국민연금 개혁"):
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 5, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code == 200:
                items = res.json().get('items', [])
                if not items: return "국민연금 최신 제도 안내"
                return "\n".join([f"제목: {re.sub('<.*?>', '', i['title'])}\n내용: {re.sub('<.*?>', '', i['description'])}" for i in items])
            else:
                print(f"⚠️ 네이버 뉴스 API 경고 (코드 {res.status_code})")
                return "국민연금 최신 제도 및 수령액 안내"
        except Exception as e:
            print(f"⚠️ 뉴스 검색 중 오류 발생: {e}")
            return "국민연금 최신 제도 안내"

    def generate_content(self, topic_context):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        system_prompt = """당신은 대한민국 최고의 금융 전문가입니다. 2026년 최신 뉴스를 기반으로 블로그 글을 작성하세요.
        제목(title), 본문(content), 요약(excerpt), 태그(tags)를 포함한 JSON으로 응답하세요."""

        prompt = f"다음 뉴스를 참고하여 3,000자 이상의 전문적인 워드프레스 블로그 포스팅을 작성해줘:\n{topic_context}"

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

        try:
            res = requests.post(url, json=payload, timeout=120)
            if res.status_code == 200:
                return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
            else:
                print(f"❌ Gemini API 오류 (코드 {res.status_code}): {res.text}")
                sys.exit(1)
        except Exception as e:
            print(f"❌ 콘텐츠 생성 중 예외 발생: {e}")
            sys.exit(1)

    def publish(self, data):
        payload = {
            "title": data['title'],
            "content": data['content'],
            "excerpt": data['excerpt'],
            "status": "publish"
        }
        
        try:
            print(f"워드프레스 발행 시도: {CONFIG['WP_URL']}/wp-json/wp/v2/posts")
            res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers=self.headers, json=payload, timeout=30)
            if res.status_code == 201:
                return True
            else:
                print(f"❌ 워드프레스 발행 실패 (상태 코드: {res.status_code})")
                print(f"상세 내용: {res.text}")
                return False
        except Exception as e:
            print(f"❌ 워드프레스 통신 중 예외 발생: {e}")
            return False

    def run(self):
        self.random_sleep()
        print("1. 뉴스 검색 중...")
        news = self.search_naver_news()
        print("2. Gemini AI 본문 생성 중...")
        post_data = self.generate_content(news)
        
        if post_data:
            print(f"3. 워드프레스 발행 중: {post_data['title']}")
            if self.publish(post_data):
                print(f"🎉 포스팅 성공!")
            else:
                sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
