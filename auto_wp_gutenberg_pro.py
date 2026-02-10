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
        print("--- [Step 0] 시스템 환경 및 인증 점검 ---")
        for key in ["WP_URL", "WP_APP_PASSWORD", "GEMINI_API_KEY"]:
            val = CONFIG[key]
            if not val:
                print(f"❌ 오류: '{key}' 환경 변수가 설정되지 않았습니다.")
            else:
                print(f"✅ '{key}' 로드 완료")

        if not CONFIG["WP_URL"] or not CONFIG["WP_APP_PASSWORD"] or not CONFIG["GEMINI_API_KEY"]:
            print("❗ 필수 설정 누락으로 실행을 종료합니다.")
            sys.exit(1)
            
        self.base_url = CONFIG["WP_URL"].rstrip("/")
        self.session = requests.Session()
        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth_header = base64.b64encode(user_pass.encode()).decode()
        
        self.common_headers = {
            "Authorization": f"Basic {self.auth_header}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        }

    def random_sleep(self):
        """
        오전 7시~8시 사이 랜덤 발행을 위한 대기.
        테스트 시에는 (1, 10)초, 실제 운영 시에는 (0, 3600) 권장.
        """
        wait_seconds = random.randint(1, 10) 
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ 보안 및 랜덤화를 위한 대기: {wait_seconds}초 후 시작합니다...")
        time.sleep(wait_seconds)

    def search_naver_news(self, query="국민연금 개혁"):
        print("--- [Step 1] 네이버 뉴스 실시간 검색 중... ---")
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 5, "sort": "sim"}
        try:
            res = self.session.get(url, headers=headers, params=params, timeout=15)
            if res.status_code == 200:
                items = res.json().get('items', [])
                print(f"뉴스 {len(items)}건 수집 완료")
                return "\n".join([f"제목: {re.sub('<.*?>', '', i['title'])}\n내용: {re.sub('<.*?>', '', i['description'])}" for i in items])
        except Exception as e: 
            print(f"⚠️ 뉴스 검색 실패: {e}")
        return "국민연금 최신 제도 변화 분석"

    def get_or_create_tag_ids(self, tags_input):
        if not tags_input: return []
        
        if isinstance(tags_input, list):
            tag_names = [str(t).strip() for t in tags_input][:10]
        else:
            tag_names = [t.strip() for t in str(tags_input).split(',')][:10]
            
        tag_ids = []
        print(f"태그 {len(tag_names)}개 처리 중...")
        for name in tag_names:
            try:
                search_res = self.session.get(f"{self.base_url}/wp-json/wp/v2/tags?search={name}", headers=self.common_headers)
                existing = search_res.json()
                match = next((t for t in existing if t['name'].lower() == name.lower()), None)
                if match:
                    tag_ids.append(match['id'])
                else:
                    create_res = self.session.post(f"{self.base_url}/wp-json/wp/v2/tags", headers=self.common_headers, json={"name": name})
                    if create_res.status_code == 201:
                        tag_ids.append(create_res.json()['id'])
            except Exception as e:
                print(f"⚠️ 태그 '{name}' 처리 실패: {e}")
                continue
        return tag_ids

    def clean_meta_text(self, text):
        """본문에 불필요한 서명이나 글자 수 안내 패턴을 제거합니다."""
        patterns = [
            r'\(총 문자 수.*?\)',
            r'\[대한민국 금융 전문가.*?\]',
            r'글자 수:.*?\d+자',
            r'작성자:.*',
            r'\d+자 내외',
            r'이 포스팅은.*?입니다\.?'
        ]
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        return text.strip()

    def generate_content(self, topic_context):
        print("--- [Step 2] Gemini AI 본문 및 태그 생성 중... ---")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        system_prompt = (
            "당신은 대한민국 최고의 금융 전문가입니다. 독자들에게 상세하고 유익한 정보를 제공하세요.\n"
            "본문은 워드프레스 구텐베르크 블록 주석(<!-- wp:paragraph --> 등)으로 구성하세요.\n\n"
            "[엄격 지침]\n"
            "1. 내용 반복 금지: 각 섹션은 서로 다른 깊이 있는 정보를 담아야 합니다.\n"
            "2. 메타 정보 금지: '총 문자 수', '글자 수', '작성자 이름', '금융 전문가 OOO' 등 서명이나 수치를 본문에 절대 포함하지 마세요.\n"
            "3. 인사말 생략: 바로 제목과 본론으로 시작하세요.\n"
            "4. 링크 포함: <a href='https://www.nps.or.kr' target='_self'>국민연금공단 공식 홈페이지</a>를 반드시 자연스럽게 포함하세요."
        )
        
        payload = {
            "contents": [{"parts": [{"text": f"뉴스 데이터:\n{topic_context}\n\n위 정보를 바탕으로 중복 없는 풍부한 포스팅을 JSON(title, content, excerpt, tags)으로 작성해줘."}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.7
            }
        }
        
        # API 호출 및 재시도 로직 (Exponential Backoff)
        for i in range(5):
            try:
                res = self.session.post(url, json=payload, timeout=120)
                if res.status_code == 200:
                    raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
                    data = json.loads(re.sub(r'```json|```', '', raw_text).strip())
                    data['content'] = self.clean_meta_text(data['content'])
                    print(f"글 생성 완료: {data['title'][:20]}...")
                    return data
            except:
                pass
            time.sleep(2 ** i)
            
        print("❌ 텍스트 생성 실패")
        sys.exit(1)

    def publish(self, data):
        print("--- [Step 3] 워드프레스 최종 발행 중... ---")
        tag_ids = self.get_or_create_tag_ids(data.get('tags', []))
        
        payload = {
            "title": data['title'],
            "content": data['content'],
            "excerpt": data['excerpt'],
            "status": "publish",
            "tags": tag_ids
        }
        
        res = self.session.post(f"{self.base_url}/wp-json/wp/v2/posts", headers=self.common_headers, json=payload, timeout=60)
        
        if res.status_code == 201:
            return True
        else:
            print(f"❌ 발행 실패 (코드 {res.status_code}): {res.text[:500]}")
            return False

    def run(self):
        self.random_sleep()
        
        # 1. 뉴스 검색
        news_context = self.search_naver_news()
        
        # 2. 텍스트 생성
        post_data = self.generate_content(news_context)
        
        # 3. 발행 (이미지 단계 제외)
        if self.publish(post_data):
            print("\n" + "="*50)
            print(f"🎉 포스팅 발행 성공!")
            print(f"제목: {post_data['title']}")
            print("="*50)
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
