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

    def deduplicate_content(self, content):
        """문단 단위로 분리하여 중복된 문단을 물리적으로 제거합니다."""
        # 구텐베르크 블록 단위로 쪼개기
        blocks = re.split(r'(<!-- wp:.*? -->)', content)
        
        seen_text = set()
        new_blocks = []
        
        for i in range(len(blocks)):
            block = blocks[i]
            # 주석이 아닌 실제 텍스트 내용 추출 (공백 및 태그 제거)
            clean_text = re.sub(r'<[^>]+>', '', block).strip()
            clean_text = re.sub(r'<!--.*?-->', '', clean_text).strip()
            
            if not clean_text or len(clean_text) < 20: # 짧은 문구나 마커는 통과
                new_blocks.append(block)
                continue
            
            # 텍스트의 앞 30자만 비교하여 중복 여부 판단 (유사 문장 방지)
            fingerprint = clean_text[:40]
            if fingerprint not in seen_text:
                seen_text.add(fingerprint)
                new_blocks.append(block)
            else:
                print(f"🗑️ 중복 단락 제거됨: {clean_text[:30]}...")
                # 만약 이전 블록이 마커였다면 그것도 같이 제거하기 위해 pop 시도
                if len(new_blocks) > 0 and "<!-- wp:" in new_blocks[-1]:
                    new_blocks.pop()
        
        return "".join(new_blocks)

    def is_content_repetitive(self, content):
        """본문에 동일한 문장이 과도하게 반복되는지 최종 검증합니다."""
        plain_text = re.sub(r'<[^>]+>', '', content)
        plain_text = re.sub(r'<!--.*?-->', '', plain_text)
        sentences = re.split(r'\.|\?|\!', plain_text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 15]
        
        if not sentences: return False
        
        duplicate_count = 0
        for s in set(sentences):
            if sentences.count(s) > 2:
                duplicate_count += 1
                
        # 중복 문장 종류가 3개 이상이면 품질 부적합 판정
        return duplicate_count >= 3

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
        print("--- [Step 2] Gemini AI 전략적 콘텐츠 생성 중... ---")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        strategy = random.choice(["NEWS_ANALYSIS", "INFORMATIONAL_GUIDE"])
        
        system_prompt = (
            f"당신은 대한민국 최고의 국민연금 전문가입니다. 현재 시점은 2026년 2월입니다.\n"
            f"[최근 발행된 주제 리스트]\n{RECENT_TITLES}\n\n"
            f"[엄격 지침 - 반복 금지 프로토콜]\n"
            f"1. 중복 생성 금지: 글자 수를 채우기 위해 동일한 내용, 문장, 혹은 단락을 반복적으로 작성하는 행위를 '절대' 금지합니다.\n"
            f"2. 내용 확장 전략: 3,000자 이상의 분량을 확보할 때 정보를 반복하지 말고 다음 섹션을 추가하세요.\n"
            f"   - 관련 법령의 구체적 근거\n"
            f"   - 실제 수혜자 시뮬레이션 사례 (Case Study)\n"
            f"   - 해외 연금 제도와의 비교 분석\n"
            f"   - 자주 묻는 질문(Q&A) 5가지 이상\n"
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
                "temperature": 0.9 # 다양성을 높여 패턴 반복 방지
            }
        }
        
        # 반복 검출 시 최대 2회까지 재생성 시도
        for attempt in range(3):
            try:
                res = self.session.post(url, json=payload, timeout=120)
                if res.status_code == 200:
                    raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
                    data = json.loads(re.sub(r'```json|```', '', raw_text).strip())
                    
                    data['content'] = self.clean_meta_text(data['content'])
                    data['content'] = self.fix_gutenberg_content(data['content'])
                    
                    # 1. 물리적 중복 단락 제거
                    data['content'] = self.deduplicate_content(data['content'])
                    
                    # 2. 품질 검사 (반복률 확인)
                    if self.is_content_repetitive(data['content']):
                        print(f"⚠️ 품질 부적합(반복 감지). 재생성을 시도합니다. (시도 {attempt+1}/3)")
                        continue
                    
                    print(f"키워드 추출 완료: {data.get('focus_keyphrase', '없음')}")
                    return data
                else:
                    print(f"API 오류: {res.text}")
            except Exception as e:
                print(f"에러 발생: {e}")
            time.sleep(5)
            
        sys.exit(1)

    def publish(self, data):
        print("--- [Step 3] 워드프레스 발행 중... ---")
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
        return res.status_code == 201

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
