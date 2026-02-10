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

# 최근 발행된 글 목록 (주제 중복 방지용)
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
        text = text.replace("//wp:", "<!-- /wp:")
        text = text.replace("/wp:", "<!-- /wp:")
        text = re.sub(r'(?<!<!-- )wp:paragraph', r'<!-- wp:paragraph', text)
        text = re.sub(r'wp:paragraph(?! -->)', r'wp:paragraph -->', text)
        text = re.sub(r'(?<!<!-- )/wp:paragraph', r'<!-- /wp:paragraph', text)
        text = re.sub(r'/wp:paragraph(?! -->)', r'/wp:paragraph -->', text)
        text = text.replace("<!-- <!--", "<!--").replace("--> -->", "-->")
        return text

    def check_and_fix_repetition(self, content):
        """문장 단위 중복을 검사하고 동일한 문장이 반복될 경우 제거하거나 경고합니다."""
        # HTML 태그 제거 후 순수 텍스트 추출 (중복 검사용)
        plain_text = re.sub(r'<[^>]+>', '', content)
        # 구텐베르크 주석 마커 제거
        plain_text = re.sub(r'<!--.*?-->', '', plain_text)
        
        # 문장 단위로 분리
        sentences = re.split(r'\.|\?|\!', plain_text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10] # 짧은 문장 제외
        
        for s in set(sentences):
            count = sentences.count(s)
            if count > 3: # 동일 문장이 3회 이상 발견되면 심각한 반복으로 간주
                print(f"⚠️ 중복 문장 발견 ({count}회): {s[:30]}...")
                # 본문에서 해당 문장이 포함된 단락 중 중복되는 것들을 제거하는 대신 
                # AI에게 다시 생성하게 하거나 여기서 에러를 내는 것이 안전함
        
        return content

    def clean_meta_text(self, text):
        """불필요한 글자 수 안내나 전문가 서명을 제거합니다."""
        patterns = [
            r'\(총 문자 수.*?\)', 
            r'\[대한민국 금융 전문가.*?\]', 
            r'글자 수:.*?\d+자', 
            r'작성자:.*',
            r'\d+자 내외로 작성되었습니다',
            r'이 포스팅은.*?작성되었습니다'
        ]
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
            f"[엄격 지침 - 반복 금지 프로토콜]\n"
            f"1. 중복 생성 금지: 글자 수를 채우기 위해 동일한 내용, 문장, 혹은 단락을 반복적으로 작성하는 행위를 '절대' 금지합니다.\n"
            f"2. 내용의 깊이: 3,000자 이상을 달성하기 위해 정보를 반복하지 말고, 제도적 배경, 해외 사례, 구체적 예시, Q&A 등 '새로운 정보'로 분량을 확보하세요.\n"
            f"3. SEO 제목: 선정된 '초점 키프레이즈'가 제목의 앞부분에 반드시 포함되도록 구성하세요.\n"
            f"4. 구텐베르크 마커: 반드시 <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph --> 형식을 사용하세요.\n"
            f"5. 링크: 아래 링크를 반드시 포함하고 <strong> 태그로 감싸 볼드 처리하세요.\n"
            f"   - <strong><a href='https://www.nps.or.kr' target='_self'>국민연금공단 공식 홈페이지</a></strong>\n"
            f"   - <strong><a href='https://minwon.nps.or.kr' target='_self'>내 곁에 국민연금(내 연금 조회)</a></strong>"
        )
        
        payload = {
            "contents": [{"parts": [{"text": f"뉴스 데이터:\n{topic_context}\n\n전략: {strategy}. 중복 없이 3,000자 이상의 매우 상세한 장문 포스팅을 JSON(title, content, excerpt, tags, focus_keyphrase)으로 작성해줘."}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.8 # 온도를 약간 높여 기계적인 반복 패턴을 줄임
            }
        }
        
        for i in range(5):
            try:
                res = self.session.post(url, json=payload, timeout=120)
                if res.status_code == 200:
                    raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
                    data = json.loads(re.sub(r'```json|```', '', raw_text).strip())
                    
                    # 데이터 정제
                    data['content'] = self.clean_meta_text(data['content'])
                    data['content'] = self.fix_gutenberg_content(data['content'])
                    
                    # 반복 검사 및 보정
                    data['content'] = self.check_and_fix_repetition(data['content'])
                    
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
        
        # 태그 처리
        tag_names = [t.strip() for t in (data['tags'] if isinstance(data['tags'], list) else data['tags'].split(','))][:10]
        
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
