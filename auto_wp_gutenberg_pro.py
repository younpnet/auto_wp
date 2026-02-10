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

    def clean_meta_text(self, text):
        patterns = [r'\(총 문자 수.*?\)', r'\[대한민국 금융 전문가.*?\]', r'글자 수:.*?\d+자', r'작성자:.*']
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        return text.strip()

    def call_gemini(self, prompt, system_instruction, response_mime="text/plain", schema=None):
        """Gemini API 호출 통합 함수"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": response_mime,
                "temperature": 0.7
            }
        }
        if schema:
            payload["generationConfig"]["responseSchema"] = schema

        for i in range(3):
            try:
                res = self.session.post(url, json=payload, timeout=120)
                if res.status_code == 200:
                    return res.json()['candidates'][0]['content']['parts'][0]['text']
            except:
                pass
            time.sleep(2 ** i)
        return None

    def generate_content(self, topic_context):
        print("--- [Step 2] 로직 변경: 섹션별 분할 생성 시작 ---")
        
        # 1. 목차(Outline) 생성
        outline_instruction = (
            f"당신은 국민연금 전문가입니다. 현재 2026년 2월 기준이며, 중복을 피해 독창적인 글을 써야 합니다.\n"
            f"[최근 발행 리스트] {RECENT_TITLES}\n"
            f"위 주제들과 겹치지 않는 새로운 제목과 상세 목차(최소 6개 섹션)를 JSON으로 구성하세요."
        )
        outline_schema = {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "string"},
                "focus_keyphrase": {"type": "string"},
                "sections": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "heading": {"type": "string"},
                            "description": {"type": "string"}
                        }
                    }
                },
                "tags": {"type": "string"},
                "excerpt": {"type": "string"}
            }
        }
        
        outline_raw = self.call_gemini(
            f"뉴스 데이터:\n{topic_context}\n위 내용을 바탕으로 최고의 블로그 기획안을 짜줘.",
            outline_instruction, "application/json", outline_schema
        )
        
        if not outline_raw: sys.exit(1)
        plan = json.loads(outline_raw)
        print(f"기획 완료: {plan['title']} (섹션 수: {len(plan['sections'])})")

        # 2. 섹션별 본문 생성
        full_body = ""
        for i, section in enumerate(plan['sections']):
            print(f"섹션 {i+1}/{len(plan['sections'])} 생성 중: {section['heading']}")
            
            section_instruction = (
                f"금융 전문가로서 블로그의 한 섹션을 작성합니다. 이전 섹션의 내용을 절대 반복하지 마세요.\n"
                f"현재 작성할 부분: {section['heading']} ({section['description']})\n"
                f"반드시 <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph --> 또는 <!-- wp:heading --> 주석을 포함한 구텐베르크 형식을 지키세요.\n"
                f"한 문단은 3문장 이내로 짧게 구성하고, 전문적인 데이터를 포함하여 풍부하게 설명하세요."
            )
            
            section_body = self.call_gemini(
                f"전체 제목: {plan['title']}\n현재까지 작성된 글 요약: {full_body[-500:] if full_body else '시작 단계'}\n위 흐름에 이어지게 '{section['heading']}' 부분을 작성해줘.",
                section_instruction
            )
            
            if section_body:
                full_body += "\n" + section_body

        # 3. 링크 및 특수 마커 추가
        links = (
            f"\n<!-- wp:paragraph --><p><strong><a href='https://www.nps.or.kr' target='_self'>국민연금공단 공식 홈페이지</a></strong></p><!-- /wp:paragraph -->"
            f"\n<!-- wp:paragraph --><p><strong><a href='https://minwon.nps.or.kr' target='_self'>내 곁에 국민연금(내 연금 조회)</a></strong></p><!-- /wp:paragraph -->"
        )
        
        plan['content'] = self.fix_gutenberg_content(full_body + links)
        plan['content'] = self.clean_meta_text(plan['content'])
        
        return plan

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
