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

# 주제 중복 방지용 리스트
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
                print(f"❌ 오류: '{key}' 환경 변수가 설정되지 않았습니다.")
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

    def get_or_create_tag_ids(self, tags_input):
        """태그를 확인하고 없으면 생성하여 ID 리스트를 반환합니다."""
        if not tags_input: return []
        if isinstance(tags_input, list):
            tag_names = [str(t).strip() for t in tags_input][:8]
        else:
            tag_names = [t.strip() for t in str(tags_input).split(',')][:8]
            
        tag_ids = []
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
            except: continue
        return tag_ids

    def call_gemini(self, prompt, system_instruction, schema=None):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.7,
                "responseSchema": schema
            }
        }
        
        for i in range(3):
            try:
                res = self.session.post(url, json=payload, timeout=120)
                if res.status_code == 200:
                    return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
            except: pass
            time.sleep(2 ** i)
        return None

    def generate_content(self, news_items):
        print("--- [Step 2] 구조적 콘텐츠 생성 시작 (Gutenberg Integrity) ---")
        news_context = "\n".join([f"- {n['title']}: {n['desc']}" for n in news_items])
        
        # AI에게는 데이터만 생성하게 하고, 블록 래핑은 파이썬이 수행합니다.
        system_instruction = (
            f"당신은 대한민국 최고의 국민연금 금융 전문가입니다. 현재 시점은 2026년 2월입니다.\n"
            f"[최근 주제들] {RECENT_TITLES}\n"
            f"위 주제들과 완전히 차별화된 새로운 뉴스 기반 포스팅을 작성하세요.\n\n"
            f"[엄격 규칙]\n"
            f"1. 중복 금지: 앞에서 한 말을 다른 문단에서 절대 반복하지 마세요.\n"
            f"2. SEO 최적화: focus_keyphrase를 제목과 첫 단락에 반드시 포함하세요.\n"
            f"3. 링크 자연 통합: 문장 내에 '국민연금공단 공식 홈페이지' 등 키워드에 맞춰 링크를 삽입하세요.\n"
            f"   - https://www.nps.or.kr (국민연금공단 공식 홈페이지)\n"
            f"   - https://minwon.nps.or.kr (내 곁에 국민연금)\n"
            f"4. 서명 금지: 인사말, 전문가 이름, 글자 수 안내 등을 절대 포함하지 마세요."
        )

        schema = {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "string"},
                "focus_keyphrase": {"type": "string"},
                "tags": {"type": "string"},
                "excerpt": {"type": "string"},
                "blocks": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "type": {"type": "string", "enum": ["h2", "h3", "p", "list", "table"]},
                            "content": {"type": "string"}
                        }
                    }
                }
            },
            "required": ["title", "focus_keyphrase", "blocks", "tags", "excerpt"]
        }
        
        prompt = f"다음 뉴스 데이터를 분석하여 깊이 있는 분석 글을 작성해줘:\n{news_context}"
        raw_data = self.call_gemini(prompt, system_instruction, schema)
        
        if not raw_data: sys.exit(1)
        
        # 파이썬 레벨에서 구텐베르크 블록으로 조립 (깨짐 방지)
        assembled_content = ""
        seen_paragraphs = set()
        
        for block in raw_data['blocks']:
            b_type = block['type']
            b_content = block['content'].strip()
            
            # 문단 중복 검사 (내용의 지문 생성)
            fingerprint = re.sub(r'[^가-힣]', '', b_content)
            if b_type == "p" and (fingerprint in seen_paragraphs or len(fingerprint) < 10):
                continue
            seen_paragraphs.add(fingerprint)

            if b_type == "h2":
                assembled_content += f"<!-- wp:heading {{\"level\":2}} -->\n<h2>{b_content}</h2>\n<!-- /wp:heading -->\n\n"
            elif b_type == "h3":
                # f-string 내 중괄호 이스케이프 수정: { -> {{, } -> }}
                assembled_content += f"<!-- wp:heading {{\"level\":3}} -->\n<h3>{b_content}</h3>\n<!-- /wp:heading -->\n\n"
            elif b_type == "p":
                assembled_content += f"<!-- wp:paragraph -->\n<p>{b_content}</p>\n<!-- /wp:paragraph -->\n\n"
            elif b_type == "list":
                assembled_content += f"<!-- wp:list -->\n{b_content}\n<!-- /wp:list -->\n\n"
            elif b_type == "table":
                assembled_content += f"<!-- wp:table -->\n<figure class=\"wp-block-table\">{b_content}</figure>\n<!-- /wp:table -->\n\n"

        raw_data['assembled_content'] = assembled_content
        return raw_data

    def publish(self, data):
        print("--- [Step 3] 워드프레스 발행 및 SEO 데이터 전송 ---")
        tag_ids = self.get_or_create_tag_ids(data.get('tags', ''))
        
        payload = {
            "title": data['title'],
            "content": data['assembled_content'],
            "excerpt": data['excerpt'],
            "status": "publish",
            "tags": tag_ids,
            "meta": {
                "_yoast_wpseo_focuskw": data.get('focus_keyphrase', '')
            }
        }
        
        res = self.session.post(f"{self.base_url}/wp-json/wp/v2/posts", headers=self.common_headers, json=payload, timeout=60)
        
        if res.status_code == 201:
            return True
        else:
            print(f"❌ 발행 실패 (코드 {res.status_code}): {res.text[:500]}")
            return False

    def run(self):
        news = self.search_naver_news()
        if not news: 
            print("뉴스 데이터 수집 실패")
            sys.exit(1)
            
        post_data = self.generate_content(news)
        if self.publish(post_data):
            print(f"🎉 발행 성공: {post_data['title']} (SEO 키워드: {post_data.get('focus_keyphrase')})")
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
