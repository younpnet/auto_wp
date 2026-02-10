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
        """문장 단위 중복 제거 로직 강화 (의미론적 중복 방지)"""
        sentences = re.split(r'(?<=[.?!])\s+', text)
        processed = []
        seen_fingerprints = set()
        for s in sentences:
            s = s.strip()
            if not s: continue
            # 문장 내 공백 및 특수문자 제거하여 지문 생성
            fingerprint = re.sub(r'[^가-힣a-zA-Z0-9]', '', s)
            # 너무 짧거나 이미 본 문장은 제외
            if len(fingerprint) > 10 and fingerprint not in seen_fingerprints:
                processed.append(s)
                seen_fingerprints.add(fingerprint)
        return " ".join(processed)

    def call_gemini(self, prompt, system_instruction, response_mime="text/plain", schema=None):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": response_mime,
                "temperature": 0.8, # 다양성 확보
                "topP": 0.95
            }
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
        print("--- [Step 2] 고도화된 상태 유지형 순차 생성 시작 ---")
        news_context = "\n".join([f"- {n['title']}: {n['desc']}" for n in news_items])
        
        # 1. SEO 최적화 기획안 생성 (Yoast SEO 초점 키프레이즈 추출)
        plan_instruction = (
            f"당신은 대한민국 최고의 금융 칼럼니스트입니다. 현재 시점은 2026년 2월입니다.\n"
            f"[최근 주제들] {RECENT_TITLES}\n"
            f"위 주제들과 완전히 차별화된 새로운 뉴스 기반 기획안을 JSON으로 만드세요.\n"
            f"반드시 'focus_keyphrase'를 제목과 첫 단락에 포함될 핵심 키워드(단어)로 선정하세요.\n"
            f"섹션(sections)은 반드시 5개 이상이어야 하며, 각 섹션의 제목(heading)은 검색 의도를 반영해야 합니다."
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
                        },
                        "required": ["heading", "instruction", "required_news_index"]
                    }
                },
                "tags": {"type": "string"},
                "excerpt": {"type": "string"}
            },
            "required": ["title", "focus_keyphrase", "sections", "tags", "excerpt"]
        }
        
        plan_raw = self.call_gemini(f"뉴스 데이터:\n{news_context}\n위 정보를 바탕으로 전문적인 블로그 기획안을 작성해줘.", plan_instruction, "application/json", plan_schema)
        if not plan_raw: sys.exit(1)
        plan = json.loads(plan_raw)
        print(f"기획 완료: {plan['title']} (SEO 키워드: {plan['focus_keyphrase']})")

        # 2. 섹션별 순차 생성 (본문 내 제목 강제 포함 로직)
        full_body = ""
        used_content_summary = "" # 반복 방지를 위한 요약 메모리
        
        for i, section in enumerate(plan['sections']):
            print(f"섹션 {i+1}/{len(plan['sections'])} 생성 중: {section['heading']}")
            
            idx = section.get('required_news_index', i)
            target_news = news_items[idx % len(news_items)] if news_items else {"title": "국민연금", "desc": "가이드"}
            
            # 섹션별 프롬프트 고도화
            section_instruction = (
                f"금융 전문가로서 블로그의 한 섹션을 작성합니다. '반복'은 절대 금물입니다.\n"
                f"이미 작성된 핵심 요약(중복 금지): {used_content_summary}\n\n"
                f"[작성 규정]\n"
                f"1. 섹션 시작은 반드시 구텐베르크 제목 블록으로 시작하세요: <!-- wp:heading {{\"level\":2}} --><h2>{section['heading']}</h2><!-- /wp:heading -->\n"
                f"2. 본문은 <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph --> 형식을 엄수하세요.\n"
                f"3. SEO 최적화: 초점 키워드 '{plan['focus_keyphrase']}'를 자연스럽게 문장 속에 포함하세요.\n"
                f"4. 링크 삽입: 문장 중간에 아래 링크를 <strong>볼드</strong>처리하여 삽입하세요.\n"
                f"   - <strong><a href='https://www.nps.or.kr' target='_self'>국민연금공단 공식 홈페이지</a></strong>\n"
                f"5. 설명 방식: 단순히 뉴스를 나열하지 말고 전문적인 '분석'과 '전망'을 600자 이상 서술하세요."
            )
            
            section_body = self.call_gemini(
                f"전체 제목: {plan['title']}\n현재 섹션: {section['heading']}\n참고 뉴스: {target_news['title']}\n이전 섹션과 겹치지 않는 새로운 내용을 작성해줘.", 
                section_instruction
            )
            
            if section_body:
                # 중복 문장 필터링
                clean_section = self.deduplicate_sentences(section_body)
                full_body += "\n" + clean_section
                
                # 다음 섹션을 위해 현재 섹션의 핵심 요약 업데이트 (AI의 메모리 역할)
                used_content_summary += f" [{section['heading']} 관련 설명 완료]"

        # 3. 구텐베르크 문법 정제 및 최종 중복 검수
        full_body = full_body.replace("//wp:", "<!-- /wp:").replace("/wp:", "<!-- /wp:")
        full_body = re.sub(r'(?<!<!-- )wp:paragraph', r'<!-- wp:paragraph', full_body)
        full_body = re.sub(r'wp:paragraph(?! -->)', r'wp:paragraph -->', full_body)
        
        plan['content'] = self.deduplicate_sentences(full_body)
        return plan

    def publish(self, data):
        print("--- [Step 3] 워드프레스 발행 및 Yoast SEO 적용 ---")
        payload = {
            "title": data['title'],
            "content": data['content'],
            "excerpt": data['excerpt'],
            "status": "publish",
            "meta": {
                "_yoast_wpseo_focuskw": data.get('focus_keyphrase', '') # Yoast SEO 초점 키프레이즈
            }
        }
        res = self.session.post(f"{self.base_url}/wp-json/wp/v2/posts", headers=self.common_headers, json=payload, timeout=60)
        return res.status_code == 201

    def run(self):
        news = self.search_naver_news()
        if not news: 
            print("뉴스 수집 실패")
            sys.exit(1)
            
        post_data = self.generate_content(news)
        if self.publish(post_data):
            print(f"🎉 발행 성공: {post_data['title']} (SEO 키워드: {post_data.get('focus_keyphrase')})")
        else:
            print(f"발행 실패")
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
