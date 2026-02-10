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
        print("--- 환경 변수 점검 ---")
        for key in ["WP_URL", "WP_APP_PASSWORD", "GEMINI_API_KEY"]:
            val = CONFIG[key]
            if not val:
                print(f"❌ 오류: '{key}' 환경 변수가 비어 있습니다.")
            else:
                print(f"✅ '{key}' 로드 완료: {val[:4]}****")

        if not CONFIG["WP_URL"] or not CONFIG["WP_APP_PASSWORD"] or not CONFIG["GEMINI_API_KEY"]:
            sys.exit(1)
            
        if not CONFIG["WP_URL"].startswith("http"):
            print("❌ 오류: WP_URL은 반드시 https:// 로 시작해야 합니다.")
            sys.exit(1)
        CONFIG["WP_URL"] = CONFIG["WP_URL"].rstrip("/")

        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth = base64.b64encode(user_pass.encode()).decode()
        
        # [고도화] 일반적인 브라우저처럼 보이도록 User-Agent 보강
        self.headers = {
            "Authorization": f"Basic {self.auth}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*"
        }

    def random_sleep(self):
        # 0~3600초 랜덤 대기
        wait_seconds = random.randint(0, 3600) 
        minutes = wait_seconds // 60
        seconds = wait_seconds % 60
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 시작 전 대기: {minutes}분 {seconds}초 후 시작...")
        time.sleep(wait_seconds)

    def search_naver_news(self, query="국민연금 개혁"):
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 5, "sort": "sim"}
        try:
            if not CONFIG["NAVER_CLIENT_ID"]: return "국민연금 최신 이슈"
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code == 200:
                items = res.json().get('items', [])
                return "\n".join([f"제목: {re.sub('<.*?>', '', i['title'])}\n내용: {re.sub('<.*?>', '', i['description'])}" for i in items])
        except: pass
        return "국민연금 제도 변화 가이드"

    def generate_content(self, topic_context):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        system_prompt = "금융 전문가로서 3,000자 이상의 워드프레스 블로그 포스팅을 JSON(title, content, excerpt, tags) 형식으로 작성하세요. 구텐베르크 블록 마커를 사용하세요."
        payload = {
            "contents": [{"parts": [{"text": f"뉴스 참고: {topic_context}\n\n위 내용을 바탕으로 포스팅해줘."}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"responseMimeType": "application/json"}
        }
        try:
            res = requests.post(url, json=payload, timeout=120)
            if res.status_code == 200:
                return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
            else:
                print(f"❌ Gemini 오류: {res.text}")
                sys.exit(1)
        except Exception as e:
            print(f"❌ 생성 오류: {e}")
            sys.exit(1)

    def publish(self, data):
        endpoint = f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts"
        payload = {
            "title": data['title'],
            "content": data['content'],
            "excerpt": data['excerpt'],
            "status": "publish"
        }
        
        try:
            print(f"발행 시도: {endpoint}")
            res = requests.post(endpoint, headers=self.headers, json=payload, timeout=30)
            
            # [고도화] 보안 차단(JS Challenge) 감지 로직
            if "slowAES" in res.text or "CUPID" in res.text or "<script" in res.text:
                print("\n" + "="*50)
                print("❌ 서버 보안 솔루션(WAF)에 의해 차단되었습니다.")
                print("이 현상은 호스팅사(Cafe24 등)의 '스팸 방지' 기능 때문입니다.")
                print("\n[해결 방법]")
                print("1. 호스팅 관리 페이지에서 'REST API 차단' 해제")
                print("2. '스팸 필터' 또는 '보안 실드' 설정에서 API 접근 허용")
                print("3. 워드프레스 보안 플러그인(Wordfence 등) 일시 중지")
                print("="*50 + "\n")
                return False

            if res.status_code == 201:
                return True
            else:
                print(f"❌ 실패 (코드: {res.status_code})")
                print(f"서버 응답: {res.text[:500]}")
                return False
        except Exception as e:
            print(f"❌ 통신 예외: {e}")
            return False

    def run(self):
        # 자동화 시에는 random_sleep()을 활성화하세요.
        # self.random_sleep()
        print("1. 정보 수집 중...")
        news = self.search_naver_news()
        print("2. 본문 생성 중...")
        post_data = self.generate_content(news)
        if post_data:
            print(f"3. 발행 중: {post_data['title']}")
            if self.publish(post_data):
                print(f"🎉 포스팅 성공!")
            else:
                sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
