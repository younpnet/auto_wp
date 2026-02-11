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
        
        # 최신 글 제목 30개 동적 로드
        self.recent_titles = self.fetch_recent_post_titles(30)

    def fetch_recent_post_titles(self, count=30):
        """워드프레스에서 최신 포스트 제목들을 가져와 중복을 방지합니다."""
        print(f"--- [Step 0.1] 블로그 최신글 {count}개 분석 중... ---")
        url = f"{self.base_url}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title"}
        try:
            res = self.session.get(url, headers=self.common_headers, params=params, timeout=20)
            if res.status_code == 200:
                titles = [re.sub('<.*?>', '', post['title']['rendered']) for post in res.json()]
                print(f"✅ 기존 포스팅 {len(titles)}개 확인 완료.")
                return titles
        except Exception as e:
            print(f"⚠️ 제목 로드 실패: {e}")
        return []

    def search_naver_news(self, query="국민연금 개혁 수령액"):
        """키워드 소스로 활용할 뉴스 데이터를 가져옵니다."""
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

    def get_or_create_tag_ids(self, tags_input):
        """태그명을 ID로 변환합니다."""
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
                    if create_res.status_code == 201: tag_ids.append(create_res.json()['id'])
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
        print("--- [Step 2] 롱테일 키워드 기반 정보성 콘텐츠 기획 ---")
        news_context = "\n".join([f"- {n['title']}: {n['desc']}" for n in news_items])
        
        system_instruction = (
            f"당신은 대한민국 최고의 국민연금 전문 자산관리사이자 검색 엔진 최적화(SEO) 전문가입니다.\n"
            f"[기존 발행글] {self.recent_titles}\n\n"
            f"[콘텐츠 전략: 롱테일 & 고검색량]\n"
            f"1. 단순 뉴스 요약은 피하세요. 대신 뉴스를 바탕으로 독자들이 가장 많이 검색하는 '실전 가이드'를 작성하세요.\n"
            f"   (예: 추납 시 건보료 영향, 전업주부 임의가입 수익률 분석, 노령연금과 기초연금 중복 수령 시 감액 회피법 등)\n"
            f"2. 특정 페르소나(부부 가입자, 프리랜서, 조기 은퇴자 등)를 타겟팅한 롱테일 키워드를 선정하세요.\n"
            f"3. 제목 전략: '어떻게 하면 ~할까?', '~하는 법 총정리', '모르면 손해보는 ~' 등 클릭을 유도하는 실질적인 제목을 지으세요.\n"
            f"4. SEO: 'focus_keyphrase'는 3~4단어의 구체적인 검색 키워드여야 합니다.\n\n"
            f"[엄격 규칙]\n"
            f"1. 인사말 및 자기소개 금지: 본문 첫 문장에 인사나 신분 밝히기를 절대 하지 마세요.\n"
            f"2. 블록 구조: AI는 구텐베르크 주석을 쓰지 마세요. 오직 순수 데이터만 생성하세요.\n"
            f"3. 중복 금지: 앞에서 한 설명을 다른 단락에서 반복하지 마세요."
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
        
        prompt = f"최신 트렌드({news_context})를 참고하여, 검색량이 높고 독자들에게 실질적 혜택을 주는 롱테일 정보글을 3000자 이상의 상세한 블록 구조로 작성해줘."
        data = self.call_gemini(prompt, system_instruction, schema)
        
        if not data: sys.exit(1)
        
        # 파이썬 레벨에서 구텐베르크 블록 조립 (깨짐 현상 원천 차단)
        assembled = ""
        seen_para = set()
        for i, b in enumerate(data['blocks']):
            content = b['content'].strip()
            
            # 인사말 및 불필요 문구 강제 필터링
            if i == 0 and b['type'] == "p" and any(x in content for x in ["안녕", "안녕하십니까", "자산관리사", "전문가입니다", "칼럼니스트"]):
                continue

            # 물리적 중복 제거 (지문 비교)
            fingerprint = re.sub(r'[^가-힣]', '', content)[:40]
            if b['type'] == "p" and (fingerprint in seen_para or len(fingerprint) < 5): continue
            seen_para.add(fingerprint)

            if b['type'] == "h2":
                assembled += f"<!-- wp:heading {{\"level\":2}} -->\n<h2>{content}</h2>\n<!-- /wp:heading -->\n\n"
            elif b['type'] == "h3":
                assembled += f"<!-- wp:heading {{\"level\":3}} -->\n<h3>{content}</h3>\n<!-- /wp:heading -->\n\n"
            elif b['type'] == "p":
                # 내부 링크 삽입 (문장 중간 자동 통합)
                if "국민연금공단" in content and "href" not in content:
                    content = content.replace("국민연금공단", "<a href='https://www.nps.or.kr' target='_self'><strong>국민연금공단</strong></a>", 1)
                assembled += f"<!-- wp:paragraph -->\n<p>{content}</p>\n<!-- /wp:paragraph -->\n\n"
            elif b['type'] == "list":
                # 리스트 항목 정렬 로직
                content = re.sub(r'([둘셋넷다섯]째|마지막으로),', r'\n\1,', content)
                items = [item.strip() for item in content.split('\n') if item.strip()]
                lis = "".join([f"<li>{item}</li>" for item in items])
                assembled += f"<!-- wp:list -->\n<ul>{lis}</ul>\n<!-- /wp:list -->\n\n"

        data['assembled_content'] = assembled
        return data

    def publish(self, data):
        print("--- [Step 3] 워드프레스 발행 및 Yoast SEO 적용 ---")
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
        # 롱테일 키워드 소스 확보를 위해 '국민연금' 광범위 검색
        news = self.search_naver_news("국민연금")
        if not news: sys.exit(1)
        post_data = self.generate_content(news)
        if self.publish(post_data):
            print(f"🎉 성공: {post_data['title']}")
            print(f"✅ 초점 키워드: {post_data.get('focus_keyphrase')}")
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
