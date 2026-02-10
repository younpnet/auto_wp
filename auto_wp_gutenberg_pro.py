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
        wait_seconds = random.randint(1, 5) 
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 시작 전 대기: {wait_seconds}초...")
        time.sleep(wait_seconds)

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
        except Exception as e: 
            print(f"⚠️ 뉴스 검색 실패: {e}")
        return []

    def deduplicate_sentences(self, text):
        """본문 전체에서 중복되는 문장을 찾아 하나만 남기고 제거합니다."""
        sentences = re.split(r'(\.|\?|\!)\s+', text)
        processed = []
        seen = set()
        
        # 문장과 문장부호를 다시 합치면서 중복 체크
        for i in range(0, len(sentences)-1, 2):
            s = sentences[i].strip() + (sentences[i+1] if i+1 < len(sentences) else "")
            # 문장 핵심 의미(공백 제거)로 중복 판단
            simple_s = re.sub(r'\s+', '', s)
            if simple_s not in seen and len(simple_s) > 5:
                processed.append(s)
                seen.add(simple_s)
        
        return " ".join(processed)

    def fix_gutenberg_content(self, text):
        """AI가 잘못 생성한 블록 마커를 강제로 교정합니다."""
        text = text.replace("//wp:", "<!-- /wp:")
        text = text.replace("/wp:", "<!-- /wp:")
        text = re.sub(r'(?<!<!-- )wp:paragraph', r'<!-- wp:paragraph', text)
        text = re.sub(r'wp:paragraph(?! -->)', r'wp:paragraph -->', text)
        text = re.sub(r'(?<!<!-- )/wp:paragraph', r'<!-- /wp:paragraph', text)
        text = re.sub(r'/wp:paragraph(?! -->)', r'/wp:paragraph -->', text)
        return text

    def call_gemini(self, prompt, system_instruction, response_mime="text/plain", schema=None):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": response_mime,
                "temperature": 0.85, # 다양성을 위해 온도 소폭 상승
                "topP": 0.95
            }
        }
        if schema:
            payload["generationConfig"]["responseSchema"] = schema

        for i in range(3):
            try:
                response = self.session.post(url, json=payload, timeout=120)
                if response.status_code == 200:
                    return response.json()['candidates'][0]['content']['parts'][0]['text']
                else:
                    print(f"Gemini API 오류: {response.status_code} - {response.text}")
            except Exception as e:
                print(f"Gemini API 호출 중 예외 발생: {e}")
            time.sleep(2 ** i)
        return None

    def generate_content(self, news_items):
        print("--- [Step 2] 로직 고도화: 상태 유지형 순차 생성 시작 ---")
        
        news_context = "\n".join([f"- {n['title']}: {n['desc']}" for n in news_items])
        
        # 1. 독창적인 목차 기획
        outline_instruction = (
            f"당신은 대한민국 최고의 금융 칼럼니스트입니다. 현재 2026년 2월이며, 아래 뉴스를 기반으로 글을 씁니다.\n"
            f"[최근 주제들] {RECENT_TITLES}\n"
            f"위 주제들과는 전혀 다른 관점에서 뉴스를 분석하는 상세 기획안을 JSON으로 만드세요.\n"
            f"섹션은 반드시 5~6개여야 하며, 각 섹션은 서로 다른 뉴스 내용을 전담해야 합니다."
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
                            "instruction": {"type": "string"},
                            "referenced_news_index": {"type": "integer"}
                        }
                    }
                },
                "tags": {"type": "string"},
                "excerpt": {"type": "string"}
            }
        }
        
        plan_raw = self.call_gemini(f"뉴스:\n{news_context}\n위 뉴스 중 중복되지 않는 정보들을 골라 전문적인 글을 기획해줘.", outline_instruction, "application/json", outline_schema)
        if not plan_raw: sys.exit(1)
        plan = json.loads(plan_raw)
        print(f"기획 완료: {plan['title']}")

        # 2. 본문 누적 생성 (상태 유지)
        full_body = ""
        for i, section in enumerate(plan['sections']):
            # 해당 섹션이 참고할 뉴스 특정
            target_news = news_items[section['referenced_news_index'] % len(news_items)]
            
            print(f"섹션 {i+1}/{len(plan['sections'])} 생성 중: {section['heading']}")
            
            # 이전 내용을 '절대 금지 영역'으로 설정
            previous_summary = full_body[-1000:] if full_body else "글의 시작 단계"
            
            section_instruction = (
                f"당신은 금융 전문가입니다. 현재 글의 흐름을 이어가되, 아래 '이미 작성된 내용'과 단 한 문장도 겹치지 않게 작성하세요.\n"
                f"이미 작성된 내용(절대 반복 금지): {previous_summary}\n\n"
                f"이번 섹션 주제: {section['heading']}\n"
                f"참고 뉴스: {target_news['title']} - {target_news['desc']}\n"
                f"특이 지침: {section['instruction']}\n"
                f"형식: 구텐베르크 주석(<!-- wp:paragraph -->)을 반드시 포함하고 마크다운 기호를 쓰지 마세요."
            )
            
            section_body = self.call_gemini(
                f"전체 제목: {plan['title']}\n현재까지의 흐름을 보고, 중복 없이 '{section['heading']}' 섹션을 600자 이상 상세히 써줘.",
                section_instruction
            )
            
            if section_body:
                # 문장 단위 중복 제거 필터링 후 결합
                clean_section = self.deduplicate_sentences(section_body)
                full_body += "\n" + clean_section

        # 3. 최종 정제 및 링크 추가
        full_body = self.fix_gutenberg_content(full_body)
        
        # 최종적으로 전체 텍스트에서 한 번 더 문장 중복 체크
        plan['content'] = self.deduplicate_sentences(full_body)
        
        # 링크 블록 추가
        plan['content'] += (
            f"\n<!-- wp:paragraph --><p><strong><a href='https://www.nps.or.kr' target='_self'>국민연금공단 공식 홈페이지</a></strong></p><!-- /wp:paragraph -->"
            f"\n<!-- wp:paragraph --><p><strong><a href='https://minwon.nps.or.kr' target='_self'>내 곁에 국민연금(내 연금 조회)</a></strong></p><!-- /wp:paragraph -->"
        )
        
        return plan

    def publish(self, data):
        print("--- [Step 3] 워드프레스 발행 중... ---")
        payload = {
            "title": data['title'],
            "content": data['content'],
            "excerpt": data['excerpt'],
            "status": "publish",
            "meta": {"_yoast_wpseo_focuskw": data.get('focus_keyphrase', '')}
        }
        res = self.session.post(f"{self.base_url}/wp-json/wp/v2/posts", headers=self.common_headers, json=payload, timeout=60)
        return res.status_code == 201

    def run(self):
        self.random_sleep()
        news_items = self.search_naver_news()
        if not news_items:
            print("뉴스를 찾을 수 없습니다.")
            sys.exit(1)
            
        post_data = self.generate_content(news_items)
        if self.publish(post_data):
            print(f"🎉 포스팅 성공: {post_data['title']}")
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
