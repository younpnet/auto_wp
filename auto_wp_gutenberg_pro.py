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
    "TEXT_MODEL": "gemini-2.5-flash-preview-09-2025",
    "IMAGE_MODEL": "imagen-4.0-generate-001"
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
        
        # 최근 글 제목 30개 로드
        self.recent_titles = self.fetch_recent_post_titles(30)

    def fetch_recent_post_titles(self, count=30):
        url = f"{self.base_url}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title"}
        try:
            res = self.session.get(url, headers=self.common_headers, params=params, timeout=20)
            if res.status_code == 200:
                return [re.sub('<.*?>', '', post['title']['rendered']) for post in res.json()]
        except: pass
        return []

    def search_naver_news(self, query="국민연금 혜택 전략"):
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

    def call_gemini_text(self, prompt, system_instruction, schema=None):
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

    def generate_image(self, title):
        """포스팅 제목을 기반으로 대표 이미지를 생성합니다."""
        print(f"--- [Step 2.5] 대표 이미지 생성 중: {title} ---")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        
        # 이미지 생성을 위한 영문 프롬프트 최적화
        image_prompt = f"A professional and high-quality financial blog featured image for an article titled '{title}'. The image should represent 'National Pension' in South Korea, featuring a clean modern office desk with a calculator, piggy bank, and financial documents. High resolution, 16:9 aspect ratio, minimal and trustworthy style."
        
        payload = {
            "instances": {"prompt": image_prompt},
            "parameters": {"sampleCount": 1}
        }

        try:
            res = self.session.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                return res.json()['predictions'][0]['bytesBase64Encoded']
        except Exception as e:
            print(f"⚠️ 이미지 생성 실패: {e}")
        return None

    def upload_image_to_wp(self, image_base64, filename="featured_image.png"):
        """워드프레스 미디어 라이브러리에 이미지 업로드"""
        if not image_base64: return None
        
        url = f"{self.base_url}/wp-json/wp/v2/media"
        image_data = base64.b64decode(image_base64)
        
        headers = {
            "Authorization": f"Basic {self.auth_header}",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/png"
        }

        try:
            res = self.session.post(url, headers=headers, data=image_data, timeout=60)
            if res.status_code == 201:
                media_id = res.json().get('id')
                print(f"✅ 미디어 업로드 성공 (ID: {media_id})")
                return media_id
        except Exception as e:
            print(f"⚠️ 미디어 업로드 실패: {e}")
        return None

    def generate_content(self, news_items):
        print("--- [Step 2] 롱테일 키워드 기반 정보성 콘텐츠 생성 ---")
        news_context = "\n".join([f"- {n['title']}: {n['desc']}" for n in news_items])
        
        system_instruction = (
            f"당신은 대한민국 최고의 금융 전문가입니다. 현재 시점은 2026년 2월입니다.\n"
            f"[기존 발행글 제목] {self.recent_titles}\n\n"
            f"[지침]\n"
            f"1. 뉴스를 소재로 하되 독자가 검색할 법한 롱테일 주제를 선정하세요.\n"
            f"2. 인사말 없이 바로 본론 제목과 내용으로 시작하세요.\n"
            f"3. 3,000자 이상의 풍부한 정보량을 제공하세요.\n"
            f"4. <a> 태그를 활용해 국민연금공단 링크를 삽입하세요."
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
        
        prompt = f"참고 뉴스({news_context})를 데이터로 활용하여 독자의 실질적인 고민을 해결하는 롱테일 SEO 최적화 글을 3000자 이상 작성해줘."
        data = self.call_gemini_text(prompt, system_instruction, schema)
        
        if not data: sys.exit(1)
        
        assembled = ""
        seen_para = set()
        for i, b in enumerate(data['blocks']):
            content = b['content'].strip()
            if i == 0 and b['type'] == "p" and any(x in content for x in ["안녕", "안녕하십니까", "자산관리사"]): continue

            fingerprint = re.sub(r'[^가-힣]', '', content)[:40]
            if b['type'] == "p" and (fingerprint in seen_para or len(fingerprint) < 10): continue
            seen_para.add(fingerprint)

            if b['type'] == "h2":
                assembled += f"<!-- wp:heading {{\"level\":2}} -->\n<h2>{content}</h2>\n<!-- /wp:heading -->\n\n"
            elif b['type'] == "h3":
                assembled += f"<!-- wp:heading {{\"level\":3}} -->\n<h3>{content}</h3>\n<!-- /wp:heading -->\n\n"
            elif b['type'] == "p":
                if "국민연금공단" in content and "href" not in content:
                    content = content.replace("국민연금공단", "<a href='https://www.nps.or.kr' target='_self'><strong>국민연금공단</strong></a>", 1)
                assembled += f"<!-- wp:paragraph -->\n<p>{content}</p>\n<!-- /wp:paragraph -->\n\n"
            elif b['type'] == "list":
                content = re.sub(r'([둘셋넷다섯]째|마지막으로),', r'\n\1,', content)
                items = [item.strip() for item in content.split('\n') if item.strip()]
                lis = "".join([f"<li>{item}</li>" for item in items])
                assembled += f"<!-- wp:list -->\n<ul>{lis}</ul>\n<!-- /wp:list -->\n\n"

        data['assembled_content'] = assembled
        return data

    def publish(self, data, media_id=None):
        print("--- [Step 3] 워드프레스 발행 중... ---")
        payload = {
            "title": data['title'],
            "content": data['assembled_content'],
            "excerpt": data['excerpt'],
            "status": "publish",
            "featured_media": media_id if media_id else 0,
            "meta": {"_yoast_wpseo_focuskw": data.get('focus_keyphrase', '')}
        }
        res = self.session.post(f"{self.base_url}/wp-json/wp/v2/posts", headers=self.common_headers, json=payload, timeout=60)
        return res.status_code == 201

    def run(self):
        news = self.search_naver_news("국민연금 혜택 전략")
        if not news: sys.exit(1)
        
        # 1. 콘텐츠 생성
        post_data = self.generate_content(news)
        
        # 2. 제목 기반 이미지 생성 및 업로드
        image_base64 = self.generate_image(post_data['title'])
        media_id = self.upload_image_to_wp(image_base64, f"nps_{int(time.time())}.png")
        
        # 3. 발행 (특성 이미지 포함)
        if self.publish(post_data, media_id):
            print(f"🎉 성공: {post_data['title']}")
            if media_id: print(f"🖼️ 대표 이미지 등록 완료 (ID: {media_id})")
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
