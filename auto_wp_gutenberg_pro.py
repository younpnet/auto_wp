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
        
        # 최신 글 제목 30개 로드
        self.recent_titles = self.fetch_recent_post_titles(30)

    def fetch_recent_post_titles(self, count=30):
        """워드프레스에서 최신 포스트 제목들을 가져옵니다."""
        print(f"--- [Step 0.1] 최신글 {count}개 제목 로드 중... ---")
        url = f"{self.base_url}/wp-json/wp/v2/posts"
        params = {
            "per_page": count,
            "status": "publish",
            "_fields": "title"
        }
        try:
            res = self.session.get(url, headers=self.common_headers, params=params, timeout=20)
            if res.status_code == 200:
                titles = [re.sub('<.*?>', '', post['title']['rendered']) for post in res.json()]
                print(f"✅ 성공적으로 {len(titles)}개의 제목을 가져왔습니다.")
                return titles
            else:
                print(f"⚠️ 제목 로드 실패 (코드 {res.status_code}). 하드코딩된 기본 리스트를 사용합니다.")
        except Exception as e:
            print(f"⚠️ 제목 로드 중 에러 발생: {e}")
        
        return ["국민연금 관련 기본 주제"]

    def search_naver_news(self, query="국민연금 개혁"):
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 20, "sort": "sim"}
        try:
            res = self.session.get(url, headers=headers, params=params, timeout=15)
            if res.status_code == 200:
                items = res.json().get('items', [])
                return [{"title": re.sub('<.*?>', '', i['title']), "desc": re.sub('<.*?>', '', i['description'])} for i in items]
        except: return []
        return []

    def get_or_create_tag_ids(self, tags_input):
        if not tags_input: return []
        tag_names = [t.strip() for t in (tags_input if isinstance(tags_input, list) else str(tags_input).split(','))][:10]
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
                "temperature": 0.8,
                "responseSchema": schema
            }
        }
        for i in range(3):
            try:
                res = self.session.post(url, json=payload, timeout=150)
                if res.status_code == 200:
                    return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
            except: pass
            time.sleep(5)
        return None

    def generate_content(self, news_items):
        print("--- [Step 2] 롱테일 키워드 기반 구조적 데이터 생성 ---")
        news_context = "\n".join([f"- {n['title']}: {n['desc']}" for n in news_items])
        
        system_instruction = (
            f"당신은 대한민국 최고의 국민연금 전문 칼럼니스트입니다. 현재 시점은 2026년 2월입니다.\n"
            f"[최근 블로그에 발행된 실제 글 제목 30개]\n{self.recent_titles}\n\n"
            f"[엄격 금지 사항]\n"
            f"1. 인사말 및 자기소개 금지: '안녕하십니까', '안녕하세요', '자산관리사입니다' 등을 절대 쓰지 마세요. 바로 본론으로 시작하세요.\n"
            f"2. 리스트 형식 엄수: 정보를 나열할 때는 반드시 'list' 타입을 사용하세요. 한 문장에 '첫째, 둘째'를 몰아넣지 말고, 반드시 각 항목을 줄바꿈(\\n)으로 구분하여 분리된 항목으로 만드세요.\n\n"
            f"[롱테일 키워드 전략]\n"
            f"1. 중복 절대 금지: 위 30개 글과 주제가 겹치지 않는 아주 새로운 시나리오를 선정하세요.\n"
            f"2. SEO 최적화: 'focus_keyphrase'를 롱테일 키워드로 설정하고 제목 앞부분에 배치하세요.\n\n"
            f"[필수 작성 규정]\n"
            f"1. 문장 내 링크 삽입: 설명 중간에 자연스럽게 <a> 태그를 사용하여 링크를 삽입하세요.\n"
            f"   - <a href='https://www.nps.or.kr'>국민연금공단 공식 홈페이지</a>\n"
            f"2. 블록 방식: AI는 절대로 구텐베르크 주석을 생성하지 마세요. 오직 순수 데이터만 생성하세요."
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
        
        prompt = f"다음 뉴스 데이터를 분석하여 깊이 있는 분석글을 작성하세요. 나열형 정보는 반드시 리스트 형식을 사용하고 항목별로 줄바꿈을 하세요:\n{news_context}"
        data = self.call_gemini(prompt, system_instruction, schema)
        
        if not data: sys.exit(1)
        
        assembled = ""
        seen_para = set()
        
        for i, b in enumerate(data['blocks']):
            content = b['content'].strip()
            
            # 인사말 패턴 필터링
            if i == 0 and b['type'] == "p" and any(x in content for x in ["안녕", "안녕하십니까", "자산관리사", "전문가입니다"]):
                continue

            fingerprint = re.sub(r'[^가-힣]', '', content)[:40]
            if b['type'] == "p" and (fingerprint in seen_para or len(fingerprint) < 5): continue
            seen_para.add(fingerprint)

            if b['type'] == "h2":
                assembled += f"<!-- wp:heading {{\"level\":2}} -->\n<h2>{content}</h2>\n<!-- /wp:heading -->\n\n"
            elif b['type'] == "h3":
                assembled += f"<!-- wp:heading {{\"level\":3}} -->\n<h3>{content}</h3>\n<!-- /wp:heading -->\n\n"
            elif b['type'] == "p":
                assembled += f"<!-- wp:paragraph -->\n<p>{content}</p>\n<!-- /wp:paragraph -->\n\n"
            elif b['type'] == "list":
                # [고도화 로직] '첫째, 둘째...'가 줄바꿈 없이 붙어 있을 경우 강제로 분리
                content = re.sub(r'([둘셋넷다섯]째|마지막으로),', r'\n\1,', content)
                
                # 줄바꿈 기준으로 항목 분리
                items = [item.strip() for item in content.split('\n') if item.strip()]
                
                # HTML 리스트 태그로 조립
                lis = "".join([f"<li>{item}</li>" for item in items])
                formatted_list = f"<ul>{lis}</ul>"
                
                assembled += f"<!-- wp:list -->\n{formatted_list}\n<!-- /wp:list -->\n\n"

        data['assembled_content'] = assembled
        return data

    def publish(self, data):
        print("--- [Step 3] 워드프레스 발행 및 Yoast SEO 연동 ---")
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
        return res.status_code == 201

    def run(self):
        news = self.search_naver_news("국민연금")
        if not news: sys.exit(1)
        post_data = self.generate_content(news)
        if self.publish(post_data):
            print(f"🎉 발행 성공: {post_data['title']}")
            print(f"✅ 롱테일 키워드(SEO): {post_data.get('focus_keyphrase')}")
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
