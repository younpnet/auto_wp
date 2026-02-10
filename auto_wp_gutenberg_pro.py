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

# 최근 발행된 주제 (중복 방지)
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
                return [{"title": re.sub('<.*?>', '', i['title']), "desc": re.sub('<.*?>', '', i['description'])} for i in items] if (items := res.json().get('items')) else []
        except: return []

    def deduplicate_sentences(self, text):
        """문장 단위로 쪼개어 물리적으로 중복을 제거합니다 (반복 이슈 해결의 핵심)"""
        sentences = re.split(r'(\.|\?|\!)\s+', text)
        processed = []
        seen = set()
        for i in range(0, len(sentences)-1, 2):
            s = sentences[i].strip() + (sentences[i+1] if i+1 < len(sentences) else "")
            fingerprint = re.sub(r'\s+', '', s)
            if fingerprint not in seen and len(fingerprint) > 10:
                processed.append(s)
                seen.add(fingerprint)
        return " ".join(processed)

    def call_gemini(self, prompt, system_instruction, response_mime="text/plain", schema=None):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {"responseMimeType": response_mime, "temperature": 0.7}
        }
        if schema: payload["generationConfig"]["responseSchema"] = schema
        
        for i in range(3):
            try:
                res = self.session.post(url, json=payload, timeout=120)
                if res.status_code == 200:
                    return res.json()['candidates'][0]['content']['parts'][0]['text']
            except: pass
            time.sleep(2 ** i)
        return None

    def generate_content(self, news_items):
        print("--- [Step 2] 고도화된 섹션별 생성 프로세스 작동 ---")
        news_context = "\n".join([f"- {n['title']}: {n['desc']}" for n in news_items])
        
        # 1. 포스팅 기획안 생성 (Yoast SEO 포함)
        plan_instruction = (
            f"당신은 대한민국 최고의 국민연금 전문가입니다. 현재 2026년 2월 기준입니다.\n"
            f"[최근 주제] {RECENT_TITLES}\n"
            f"위 주제와 겹치지 않는 새로운 뉴스 기반 기획안을 JSON으로 만드세요.\n"
            f"반드시 'focus_keyphrase'를 제목에 포함된 핵심 키워드로 1개 선정하세요."
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
                            "instruction": {"type": "string"}
                        }
                    }
                },
                "tags": {"type": "string"},
                "excerpt": {"type": "string"}
            }
        }
        
        plan_raw = self.call_gemini(f"뉴스 데이터:\n{news_context}\n위 정보를 바탕으로 독창적인 기획안을 짜줘.", plan_instruction, "application/json", plan_schema)
        if not plan_raw: sys.exit(1)
        plan = json.loads(plan_raw)
        print(f"기획 완료: {plan['title']} (키워드: {plan['focus_keyphrase']})")

        # 2. 섹션별 본문 생성 (반복 방지를 위해 상태 전달)
        full_body = ""
        for i, section in enumerate(plan['sections']):
            print(f"섹션 {i+1}/{len(plan['sections'])} 생성 중: {section['heading']}")
            
            section_instruction = (
                f"금융 칼럼니스트로서 블로그의 한 섹션을 작성합니다. 이전 섹션의 내용을 절대 반복하지 마세요.\n"
                f"이미 작성된 내용(반복 금지): {full_body[-800:] if full_body else '없음'}\n"
                f"주제: {section['heading']}\n"
                f"지침: {section['instruction']}\n\n"
                f"[엄격 규칙]\n"
                f"1. 반드시 <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph --> 형식을 사용하세요.\n"
                f"2. 필요한 경우 문장 중간에 자연스럽게 아래 링크를 <strong>볼드</strong>처리하여 삽입하세요.\n"
                f"   - <strong><a href='https://www.nps.or.kr' target='_self'>국민연금공단 공식 홈페이지</a></strong>\n"
                f"   - <strong><a href='https://minwon.nps.or.kr' target='_self'>내 곁에 국민연금(내 연금 조회)</a></strong>\n"
                f"3. 링크를 글 마지막에 따로 빼지 마세요. 문장 속에 녹여내세요."
            )
            
            section_body = self.call_gemini(f"전체 제목: {plan['title']}\n현재 섹션 '{section['heading']}'에 대해 600자 이상 상세히 써줘.", section_instruction)
            if section_body:
                full_body += "\n" + self.deduplicate_sentences(section_body)

        # 3. 구텐베르크 문법 보정
        full_body = full_body.replace("//wp:", "<!-- /wp:").replace("/wp:", "<!-- /wp:")
        full_body = re.sub(r'(?<!<!-- )wp:paragraph', r'<!-- wp:paragraph', full_body)
        full_body = re.sub(r'wp:paragraph(?! -->)', r'wp:paragraph -->', full_body)
        
        plan['content'] = full_body
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
            print("뉴스 데이터 부족")
            sys.exit(1)
        post_data = self.generate_content(news)
        if self.publish(post_data):
            print(f"🎉 발행 성공: {post_data['title']}")
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
