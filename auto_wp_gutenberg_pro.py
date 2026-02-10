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
            
        self.base_url = CONFIG["WP_URL"].rstrip("/")
        self.session = requests.Session()

        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth_header = base64.b64encode(user_pass.encode()).decode()
        
        self.common_headers = {
            "Authorization": f"Basic {self.auth_header}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }

    def random_sleep(self):
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
            res = self.session.get(url, headers=headers, params=params, timeout=15)
            if res.status_code == 200:
                items = res.json().get('items', [])
                return "\n".join([f"제목: {re.sub('<.*?>', '', i['title'])}\n내용: {re.sub('<.*?>', '', i['description'])}" for i in items])
        except: pass
        return "국민연금 제도 변화 가이드"

    def generate_content(self, topic_context):
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        # 구텐베르크 블록 형식을 강제하는 시스템 프롬프트
        system_prompt = (
            "당신은 대한민국 최고의 금융 전문가입니다. 3,000자 이상의 워드프레스 포스팅을 JSON 형식으로 작성하세요.\n"
            "필드명: 'title', 'content', 'excerpt', 'tags'\n\n"
            "[중요: 구텐베르크 블록 형식 지침]\n"
            "모든 본문 요소는 워드프레스 구텐베르크 블록 주석으로 감싸야 합니다.\n"
            "- 단락: <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph -->\n"
            "- 제목(h2): <!-- wp:heading {\"level\":2} --><h2>제목</h2><!-- /wp:heading -->\n"
            "- 제목(h3): <!-- wp:heading {\"level\":3} --><h3>제목</h3><!-- /wp:heading -->\n"
            "- 목록: <!-- wp:list --><ul><li>항목</li></ul><!-- /wp:list -->\n"
            "- 표: <!-- wp:table --><figure class=\"wp-block-table\"><table>...</table></figure><!-- /wp:table -->\n\n"
            "마크다운 강조(**) 대신 <strong> 태그를 사용하고, 모든 따옴표는 JSON 규격에 맞게 이스케이프하세요."
        )
        
        payload = {
            "contents": [{"parts": [{"text": f"뉴스 데이터:\n{topic_context}\n\n위 정보를 바탕으로 구텐베르크 블록 방식으로 상세 포스팅을 작성해줘."}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }
        
        try:
            res = self.session.post(api_url, json=payload, timeout=120)
            if res.status_code == 200:
                raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
                clean_json_str = re.sub(r'```json|```', '', raw_text).strip()
                return json.loads(clean_json_str)
            else:
                print(f"❌ Gemini 오류: {res.text}")
                sys.exit(1)
        except Exception as e:
            print(f"❌ 생성 오류: {e}")
            sys.exit(1)

    def publish(self, data):
        endpoint = f"{self.base_url}/wp-json/wp/v2/posts"
        payload = {
            "title": data['title'],
            "content": data['content'],
            "excerpt": data['excerpt'],
            "status": "publish"
        }
        
        try:
            print(f"발행 시도: {endpoint}")
            res = self.session.post(endpoint, headers=self.common_headers, json=payload, timeout=30)
            
            content = res.text
            if "slowAES" in content or "CUPID" in content or "<script" in content:
                print("\n" + "="*60)
                print("❌ 서버 보안 차단 감지 (WAF/Cafe24 스팸방지)")
                print("해결: 호스팅 관리에서 'REST API 차단' 해제 및 '스팸방지' 설정을 확인하세요.")
                print("="*60 + "\n")
                return False

            if res.status_code == 201:
                return True
            else:
                print(f"❌ 실패 (코드: {res.status_code})")
                print(f"서버 응답 요약: {content[:300]}")
                return False
        except Exception as e:
            print(f"❌ 통신 예외 발생: {e}")
            return False

    def run(self):
        # 실사용 시 random_sleep() 활성화 권장
        # self.random_sleep()
        print("1. 정보 수집 중...")
        news = self.search_naver_news()
        print("2. 구텐베르크 블록 콘텐츠 생성 중...")
        post_data = self.generate_content(news)
        if post_data:
            print(f"3. 발행 중: {post_data['title']}")
            if self.publish(post_data):
                print(f"🎉 구텐베르크 포스팅 성공!")
            else:
                sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
