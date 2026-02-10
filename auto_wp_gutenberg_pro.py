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

# 최근 발행된 글 목록 (중복 방지용)
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
        wait_seconds = random.randint(1, 10) 
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 시작 전 대기: {wait_seconds}초...")
        time.sleep(wait_seconds)

    def search_naver_news(self, query="국민연금"):
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
                return "\n".join([f"제목: {re.sub('<.*?>', '', i['title'])}\n내용: {re.sub('<.*?>', '', i['description'])}" for i in items])
        except Exception as e: 
            print(f"⚠️ 뉴스 검색 실패: {e}")
        return "최근 국민연금 관련 주요 이슈 분석"

    def fix_gutenberg_content(self, text):
        """AI가 잘못 생성한 블록 마커를 강제로 교정합니다."""
        # 1. //wp:와 같은 잘못된 마커 수정
        text = text.replace("//wp:", "<!-- /wp:")
        text = text.replace("/wp:", "<!-- /wp:")
        
        # 2. 마커가 텍스트로 노출되지 않도록 주석 기호 확인 및 보정
        # 제대로 닫히지 않은 마커나 기호 중복 제거
        text = re.sub(r'(?<!<!-- )wp:paragraph', r'<!-- wp:paragraph', text)
        text = re.sub(r'wp:paragraph(?! -->)', r'wp:paragraph -->', text)
        text = re.sub(r'(?<!<!-- )/wp:paragraph', r'<!-- /wp:paragraph', text)
        text = re.sub(r'/wp:paragraph(?! -->)', r'/wp:paragraph -->', text)
        
        # 중복된 주석 기호 정리
        text = text.replace("<!-- <!--", "<!--").replace("--> -->", "-->")
        return text

    def clean_meta_text(self, text):
        patterns = [r'\(총 문자 수.*?\)', r'\[대한민국 금융 전문가.*?\]', r'글자 수:.*?\d+자', r'작성자:.*']
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        return text.strip()

    def generate_content(self, topic_context):
        print("--- [Step 2] Gemini AI SEO 최적화 콘텐츠 생성 중... ---")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        strategy = random.choice(["NEWS_ANALYSIS", "INFORMATIONAL_GUIDE"])
        
        system_prompt = (
            f"당신은 대한민국 최고의 국민연금 전문가입니다. 현재 시점은 2026년 2월입니다.\n"
            f"[최근 발행된 주제 리스트]\n{RECENT_TITLES}\n\n"
            f"[엄격 지침 - 필독]\n"
            f"1. SEO 제목: 선정된 '초점 키프레이즈'가 제목의 앞부분에 반드시 포함되도록 구성하세요.\n"
            f"2. Yoast SEO 연동: 'focus_keyphrase' 필드에 검색량이 높을 핵심 키워드 1개를 단어 단위로 입력하세요.\n"
            f"3. 구텐베르크 블록 마커 엄수: 단락은 반드시 <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph --> 형식을 사용하세요.\n"
            f"   주의: //wp:paragraph 나 /wp:paragraph 처럼 주석 기호(<!-- -->)가 없는 마커를 절대 사용하지 마세요.\n"
            f"4. 링크: 아래 텍스트를 반드시 포함하고 <strong> 태그로 감싸 볼드 처리하세요.\n"
            f"   - <strong><a href='https://www.nps.or.kr' target='_self'>국민연금공단 공식 홈페이지</a></strong>\n"
            f"   - <strong><a href='https://minwon.nps.or.kr' target='_self'>내 곁에 국민연금(내 연금 조회)</a></strong>"
        )
        
        payload = {
            "contents": [{"parts": [{"text": f"뉴스 데이터:\n{topic_context}\n\n전략: {strategy}. 3,000자 이상의 장문 포스팅을 JSON(title, content, excerpt, tags, focus_keyphrase)으로 작성해줘."}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.7
            }
        }
        
        for i in range(5):
            try:
                res = self.session.post(url, json=payload, timeout=120)
                if res.status_code == 200:
                    raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
                    data = json.loads(re.sub(r'```json|```', '', raw_text).strip())
                    
                    # 데이터 정제 및 블록 마커 교정
                    data['content'] = self.clean_meta_text(data['content'])
                    data['content'] = self.fix_gutenberg_content(data['content'])
                    
                    print(f"키워드 추출 완료: {data.get('focus_keyphrase', '없음')}")
                    return data
                else:
                    print(f"API 오류 (시도 {i+1}): {res.text}")
            except Exception as e:
                print(f"에러 (시도 {i+1}): {e}")
            time.sleep(2 ** i)
        sys.exit(1)

    def publish(self, data):
        print("--- [Step 3] 워드프레스 발행 및 Yoast SEO 연동 중... ---")
        
        # 태그 생성 로직 호출 생략 (기존 파일 참고)
        tag_names = [t.strip() for t in (data['tags'] if isinstance(data['tags'], list) else data['tags'].split(','))][:10]
        tag_ids = [] # 실제 코드에서는 tag_ids 확보 로직 필요 (이전 코드 유지)
        
        payload = {
            "title": data['title'],
            "content": data['content'],
            "excerpt": data['excerpt'],
            "status": "publish",
            "meta": {
                "_yoast_wpseo_focuskw": data.get('focus_keyphrase', '')
            }
        }
        
        res = self.session.post(f"{self.base_url}/wp-json/wp/v2/posts", headers=self.common_headers, json=payload, timeout=60)
        
        if res.status_code == 201:
            return True
        else:
            print(f"❌ 발행 실패 (코드 {res.status_code}): {res.text}")
            return False

    def run(self):
        self.random_sleep()
        news_context = self.search_naver_news()
        post_data = self.generate_content(news_context)
        if self.publish(post_data):
            print(f"🎉 성공: {post_data['title']} (SEO 키워드: {post_data.get('focus_keyphrase')})")
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
