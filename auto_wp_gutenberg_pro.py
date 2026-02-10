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

# 최근 발행된 주제 (중복 방지용 리스트)
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
            if not CONFIG[key]:
                print(f"❌ 오류: '{key}' 누락")
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

    def search_naver_news(self, query="국민연금"):
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 15, "sort": "date"}
        try:
            res = self.session.get(url, headers=headers, params=params, timeout=15)
            if res.status_code == 200:
                items = res.json().get('items', [])
                return [{"title": re.sub('<.*?>', '', i['title']), "desc": re.sub('<.*?>', '', i['description'])} for i in items]
        except: return []
        return []

    def deduplicate_sentences(self, text):
        """문장 단위로 쪼개어 동일한 의미의 중복 문장을 물리적으로 제거합니다."""
        # 문장 경계 식별 (. ? ! 뒤에 공백)
        sentences = re.split(r'(?<=[.?!])\s+', text)
        processed = []
        seen = set()
        
        for s in sentences:
            s = s.strip()
            if not s: continue
            # 공백 제거 및 소문자화하여 문장 지문(fingerprint) 생성
            fingerprint = re.sub(r'\s+', '', s)
            if fingerprint not in seen and len(fingerprint) > 5:
                processed.append(s)
                seen.add(fingerprint)
        
        return " ".join(processed)

    def call_gemini(self, prompt, system_instruction, response_mime="text/plain", schema=None):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": response_mime,
                "temperature": 0.8, # 다양성 확보를 위해 온도 조절
                "topP": 0.9
            }
        }
        if schema: payload["generationConfig"]["responseSchema"] = schema
        
        for i in range(3):
            try:
                res = self.session.post(url, json=payload, timeout=120)
                if res.status_code == 200:
                    return res.json()['candidates'][0]['content']['parts'][0]['text']
                else:
                    print(f"API 오류 (코드 {res.status_code}): {res.text[:200]}")
            except: pass
            time.sleep(2 ** i)
        return None

    def generate_content(self, news_items):
        print("--- [Step 2] 고도화된 상태 유지형 순차 생성 시작 ---")
        news_context = "\n".join([f"- {n['title']}: {n['desc']}" for n in news_items])
        
        # 1. 고유한 주제 및 상세 목차 기획
        plan_instruction = (
            f"당신은 대한민국 최고의 금융 칼럼니스트입니다. 현재 시점은 2026년 2월입니다.\n"
            f"[최근 주제 리스트] {RECENT_TITLES}\n"
            f"위 주제들과 겹치지 않는 새로운 관점의 글을 기획하세요.\n"
            f"반드시 'focus_keyphrase'를 제목에 포함된 핵심 키워드로 선정하세요.\n"
            f"섹션은 최소 5개로 구성하며, 각 섹션의 목적을 명확히 정의하세요."
        )
        plan_schema = {
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
                            "instruction": {"type": "string"},
                            "required_news_index": {"type": "integer"}
                        }
                    }
                },
                "tags": {"type": "string"},
                "excerpt": {"type": "string"}
            }
        }
        
        plan_raw = self.call_gemini(f"뉴스 데이터:\n{news_context}\n위 정보를 바탕으로 독창적인 블로그 기획안을 작성해줘.", plan_instruction, "application/json", plan_schema)
        if not plan_raw: sys.exit(1)
        plan = json.loads(plan_raw)
        print(f"기획 완료: {plan['title']} (키워드: {plan['focus_keyphrase']})")

        # 2. 섹션별 본문 누적 생성 (이전 섹션 피드백 포함)
        full_body = ""
        for i, section in enumerate(plan['sections']):
            print(f"섹션 {i+1}/{len(plan['sections'])} 생성 중: {section['heading']}")
            
            # 특정 뉴스 데이터를 각 섹션에 배정하여 정보 중복 방지
            target_news = news_items[section['required_news_index'] % len(news_items)]
            
            section_instruction = (
                f"당신은 금융 전문가입니다. 이전 섹션의 내용을 '절대' 반복하지 마세요.\n"
                f"이미 작성된 본문(이 내용은 다시 쓰지 마세요): {full_body[-1200:] if full_body else '없음'}\n\n"
                f"현재 주제: {section['heading']}\n"
                f"참고 뉴스: {target_news['title']}\n"
                f"작성 지침: {section['instruction']}\n\n"
                f"[엄격 규칙]\n"
                f"1. 반드시 <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph --> 형식을 사용하세요.\n"
                f"2. 문장 속에 자연스럽게 다음 링크를 <strong>볼드</strong>처리하여 삽입하세요.\n"
                f"   - <strong><a href='https://www.nps.or.kr' target='_self'>국민연금공단 공식 홈페이지</a></strong>\n"
                f"   - <strong><a href='https://minwon.nps.or.kr' target='_self'>내 곁에 국민연금(내 연금 조회)</a></strong>\n"
                f"3. 중복된 문장이나 이미 설명한 논리를 다시 언급하면 탈락입니다. 새로운 정보를 제공하세요."
            )
            
            section_body = self.call_gemini(f"전체 제목: {plan['title']}\n현재 '{section['heading']}' 부분에 대해 600자 이상 아주 상세하게 써줘.", section_instruction)
            
            if section_body:
                # 문장 단위 중복 제거 후 누적
                clean_section = self.deduplicate_sentences(section_body)
                full_body += "\n" + clean_section

        # 3. 구텐베르크 문법 최종 보정 및 중복 검수
        full_body = full_body.replace("//wp:", "<!-- /wp:").replace("/wp:", "<!-- /wp:")
        full_body = re.sub(r'(?<!<!-- )wp:paragraph', r'<!-- wp:paragraph', full_body)
        full_body = re.sub(r'wp:paragraph(?! -->)', r'wp:paragraph -->', full_body)
        
        # 전체 텍스트에서 한 번 더 문장 중복 검사
        plan['content'] = self.deduplicate_sentences(full_body)
        return plan

    def publish(self, data):
        print("--- [Step 3] 워드프레스 발행 및 SEO 적용 ---")
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
        news = self.search_naver_news()
        if not news: 
            print("뉴스 데이터 부족으로 종료")
            sys.exit(1)
            
        post_data = self.generate_content(news)
        if self.publish(post_data):
            print(f"🎉 발행 성공: {post_data['title']}")
            print(f"SEO 키워드: {post_data.get('focus_keyphrase')}")
        else:
            print("발행 실패")
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
