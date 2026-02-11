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
        
        # 최신 글 제목 30개 동적 로드 (주제 중복 방지)
        self.recent_titles = self.fetch_recent_post_titles(30)

    def fetch_recent_post_titles(self, count=30):
        """워드프레스에서 최근 글 제목을 가져와 중복을 피합니다."""
        print(f"--- [Step 0.1] 블로그 최신글 {count}개 분석 중... ---")
        url = f"{self.base_url}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title"}
        try:
            res = self.session.get(url, headers=self.common_headers, params=params, timeout=20)
            if res.status_code == 200:
                return [re.sub('<.*?>', '', post['title']['rendered']) for post in res.json()]
        except: pass
        return []

    def search_naver_news(self, query="국민연금 개혁"):
        """실시간 뉴스는 참고 자료(Context)로만 활용합니다."""
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 15, "sort": "sim"}
        try:
            res = self.session.get(url, headers=headers, params=params, timeout=15)
            if res.status_code == 200:
                items = res.json().get('items', [])
                return [{"title": re.sub('<.*?>', '', i['title']), "desc": re.sub('<.*?>', '', i['description'])} for i in items]
        except: return []
        return []

    def call_gemini(self, prompt, system_instruction, schema=None):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.8,
                "responseSchema": schema
            }
        }
        for i in range(3):
            try:
                res = self.session.post(url, json=payload, timeout=180)
                if res.status_code == 200:
                    return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
            except: pass
            time.sleep(5)
        return None

    def generate_content(self, news_items):
        print("--- [Step 2] 롱테일 키워드 기반 정보성 콘텐츠 기획 ---")
        news_context = "\n".join([f"- {n['title']}: {n['desc']}" for n in news_items])
        
        system_instruction = (
            f"당신은 대한민국 최고의 금융 전문가이자 SEO 전문가입니다. 현재 시점은 2026년 2월입니다.\n"
            f"[기존 발행글 제목] {self.recent_titles}\n\n"
            f"[롱테일 키워드 전략: 뉴스보다 검색 의도 우선]\n"
            f"1. 제공된 뉴스는 글의 '소재'일 뿐입니다. 뉴스를 그대로 전달하는 '보도형' 글은 금지합니다.\n"
            f"2. 대신 독자가 실제로 검색할 법한 롱테일 키워드를 주제로 잡으세요.\n"
            f"   - (예) 뉴스가 '건보료 인상'이라면 주제는 '국민연금 수령액과 건보료 피부양자 자격 유지 전략'으로 선정.\n"
            f"   - (예) 뉴스가 '연금개혁'이라면 주제는 '전업주부가 지금 당장 국민연금 임의가입을 해야 하는 수익률적 근거'로 선정.\n"
            f"3. 타겟팅: 전업주부, 이혼 가정, 군필자, 프리랜서 등 특정 페르소나의 문제를 해결해주는 가이드를 작성하세요.\n"
            f"4. 제목: '어떻게 ~할까?', '~하는 법 총정리', '모르면 손해보는 ~' 등 클릭을 유도하는 제목을 지으세요.\n\n"
            f"[필수 규칙]\n"
            f"1. 인사말 금지: '안녕하십니까', '관리사입니다' 등의 소개 없이 바로 본론 제목과 내용으로 시작하세요.\n"
            f"2. 리스트 형식: 나열형 정보는 반드시 'list' 타입을 사용하여 시각적으로 분리하세요.\n"
            f"3. <a> 태그 활용: 문장 중간에 자연스럽게 <a href='https://www.nps.or.kr'>국민연금공단 공식 홈페이지</a> 링크를 볼드 처리하여 삽입하세요.\n"
            f"4. 3,000자 이상의 충분한 정보량을 제공하세요."
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
                            "type": {"type": "string", "enum": ["h2", "h3", "p", "list"]},
                            "content": {"type": "string"}
                        },
                        "required": ["type", "content"]
                    }
                }
            },
            "required": ["title", "focus_keyphrase", "blocks", "tags", "excerpt"]
        }
        
        prompt = f"참고 뉴스({news_context})를 데이터로 활용하되, 이를 독자의 실질적인 고민 해결로 연결하는 롱테일 SEO 최적화 글을 3000자 이상 작성해줘."
        data = self.call_gemini(prompt, system_instruction, schema)
        
        if not data: sys.exit(1)
        
        assembled = ""
        seen_para = set()
        for i, b in enumerate(data['blocks']):
            content = b['content'].strip()
            
            # 인사말 강제 삭제 (첫 단락 필터링)
            if i == 0 and b['type'] == "p" and any(x in content for x in ["안녕", "안녕하십니까", "자산관리사", "전문가입니다", "칼럼니스트"]):
                continue

            # 물리적 중복 제거 (지문 비교)
            fingerprint = re.sub(r'[^가-힣]', '', content)[:40]
            if b['type'] == "p" and (fingerprint in seen_para or len(fingerprint) < 10): continue
            seen_para.add(fingerprint)

            if b['type'] == "h2":
                assembled += f"<!-- wp:heading {{\"level\":2}} -->\n<h2>{content}</h2>\n<!-- /wp:heading -->\n\n"
            elif b['type'] == "h3":
                assembled += f"<!-- wp:heading {{\"level\":3}} -->\n<h3>{content}</h3>\n<!-- /wp:heading -->\n\n"
            elif b['type'] == "p":
                # 내부 링크 자동 통합
                if "국민연금공단" in content and "href" not in content:
                    content = content.replace("국민연금공단", "<a href='https://www.nps.or.kr' target='_self'><strong>국민연금공단</strong></a>", 1)
                assembled += f"<!-- wp:paragraph -->\n<p>{content}</p>\n<!-- /wp:paragraph -->\n\n"
            elif b['type'] == "list":
                # 리스트 항목 정렬 로직 (첫째, 둘째 등 감지 시 줄바꿈)
                content = re.sub(r'([둘셋넷다섯]째|마지막으로),', r'\n\1,', content)
                items = [item.strip() for item in content.split('\n') if item.strip()]
                lis = "".join([f"<li>{item}</li>" for item in items])
                assembled += f"<!-- wp:list -->\n<ul>{lis}</ul>\n<!-- /wp:list -->\n\n"

        data['assembled_content'] = assembled
        return data

    def publish(self, data):
        print("--- [Step 3] 워드프레스 발행 중... ---")
        payload = {
            "title": data['title'],
            "content": data['assembled_content'],
            "excerpt": data['excerpt'],
            "status": "publish",
            "meta": {"_yoast_wpseo_focuskw": data.get('focus_keyphrase', '')}
        }
        res = self.session.post(f"{self.base_url}/wp-json/wp/v2/posts", headers=self.common_headers, json=payload, timeout=60)
        return res.status_code == 201

    def run(self):
        # 롱테일 소재 확보를 위해 포괄적인 검색어 사용
        news = self.search_naver_news("국민연금 혜택 전략")
        if not news: sys.exit(1)
        post_data = self.generate_content(news)
        if self.publish(post_data):
            print(f"🎉 성공: {post_data['title']}")
            print(f"✅ 롱테일 키워드: {post_data.get('focus_keyphrase')}")
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
