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

# 최근 발행된 글 목록 (중복 방지 및 주제 균형을 위해 참고합니다)
RECENT_TITLES = [
    "국민연금 수령시기 연기 혜택 연기연금 인상률 신청 방법 최대 36% 증액 꿀팁 (2026)",
    "국민연금 연말정산 환급금 받는 법 연금소득세 공제 부양가족 신고 총정리 (2026년)",
    "2026년 국민연금 수급자 카드 혜택 신청 방법 지하철 무료 대형마트 할인 안심카드 총정리",
    "2026년 국민연금 수급자 의료비 지원 혜택 실버론 신청 방법 한도 금리 완벽 정리",
    "국민연금 기초연금 중복 수령 감액 기준 2026 연계감액 폐지 소식 완벽 정리 (쉬운 설명)",
    "국민연금 연금소득세 과세 기준 계산 방법 연말정산 주의사항 완벽 정리 (2026 최신)",
    "국민연금 감액 제도 폐지 확정! 일해도 연금 안 깎인다! 재직자 노령연금 100% 수령 완벽 정리 (2026년 시행)",
    "“잠자고 있던 내 연금 깨워보세요” 국민연금 수령액 쑥쑥 키우는 효자 방법 3총사",
    "2026년 국민연금 인상 소식! 내 수령액 얼마나 오를까? 물가상승률 반영 인상분 조회 방법 (쉬운 설명)"
]

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
        """오전 7시~8시 사이 랜덤 발행을 위한 대기."""
        wait_seconds = random.randint(1, 10) 
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ 보안 및 랜덤화를 위한 대기: {wait_seconds}초 후 시작합니다...")
        time.sleep(wait_seconds)

    def search_naver_news(self, query="국민연금"):
        print("--- [Step 1] 네이버 뉴스 실시간 검색 중... ---")
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 10, "sort": "date"}
        try:
            res = self.session.get(url, headers=headers, params=params, timeout=15)
            if res.status_code == 200:
                items = res.json().get('items', [])
                print(f"뉴스 {len(items)}건 수집 완료")
                return "\n".join([f"제목: {re.sub('<.*?>', '', i['title'])}\n내용: {re.sub('<.*?>', '', i['description'])}" for i in items])
        except Exception as e: 
            print(f"⚠️ 뉴스 검색 실패: {e}")
        return "최근 국민연금 관련 주요 뉴스 없음"

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
        print("--- [Step 2] Gemini AI 전략적 주제 선정 및 본문 생성 중... ---")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        strategy = random.choice(["NEWS_ANALYSIS", "INFORMATIONAL_GUIDE"])
        print(f"오늘의 콘텐츠 전략: {strategy}")

        system_prompt = (
            f"당신은 대한민국 최고의 국민연금 및 금융 전문가입니다.\n"
            f"현재 시점은 2026년 2월이며, 아래 정보를 참고하여 중복 없는 유익한 블로그 글을 작성하세요.\n\n"
            f"[최근 발행된 글 제목 리스트]\n{RECENT_TITLES}\n\n"
            f"[엄격 준수: 구텐베르크 본문 구조 지침]\n"
            f"모든 본문 요소는 워드프레스 구텐베르크 블록 마커로 감싸야 하며, HTML 태그를 누락하지 마세요.\n"
            f"1. 단락 블록: 반드시 <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph --> 형식을 사용하세요. <p> 태그가 없으면 디자인이 깨지므로 절대 누락하지 마세요.\n"
            f"2. 제목 블록: <!-- wp:heading {{\"level\":2}} --><h2>소제목</h2><!-- /wp:heading --> 형식을 사용하세요.\n"
            f"3. 중복 방지: 제공된 리스트와 겹치지 않는 새로운 주제를 선정하세요.\n"
            f"4. 서명 및 메타 정보 금지: 글자 수 안내나 전문가 서명을 포함하지 마세요.\n"
            f"5. 링크: 반드시 <a href='https://www.nps.or.kr' target='_self'>국민연금공단 공식 홈페이지</a>를 포함하세요."
        )
        
        payload = {
            "contents": [{"parts": [{"text": f"뉴스 데이터:\n{topic_context}\n\n위 데이터를 분석하여 {strategy} 전략에 맞춰 3,000자 이상의 풍부한 포스팅을 JSON(title, content, excerpt, tags)으로 작성해줘."}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.8
            }
        }
        
        for i in range(5):
            try:
                res = self.session.post(url, json=payload, timeout=120)
                if res.status_code == 200:
                    raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
                    data = json.loads(re.sub(r'```json|```', '', raw_text).strip())
                    data['content'] = self.clean_meta_text(data['content'])
                    print(f"글 생성 완료 (전략: {strategy}): {data['title'][:25]}...")
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
        news_context = self.search_naver_news()
        post_data = self.generate_content(news_context)
        
        if self.publish(post_data):
            print("\n" + "="*50)
            print(f"🎉 포스팅 발행 성공!")
            print(f"제목: {post_data['title']}")
            print("="*50)
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
