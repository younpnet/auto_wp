import requests
import json
import time
import base64
import re
import os
import random
import sys
import io
from datetime import datetime

# 이미지 처리를 위한 PIL 라이브러리
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️ 경고: PIL(Pillow) 라이브러리가 설치되지 않았습니다. 'pip install Pillow'가 필요합니다.")

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
    "IMAGE_MODEL": "gemini-2.5-flash-preview-09-2025" # 이미지 모델 변경
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
        
        # 최근 글 제목 30개 및 외부 링크 로드
        self.recent_titles = self.fetch_recent_post_titles(30)
        self.external_link = self.load_external_link_from_json()

    def fetch_recent_post_titles(self, count=30):
        url = f"{self.base_url}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title"}
        try:
            res = self.session.get(url, headers=self.common_headers, params=params, timeout=20)
            if res.status_code == 200:
                return [re.sub('<.*?>', '', post['title']['rendered']) for post in res.json()]
        except: pass
        return []

    def load_external_link_from_json(self):
        try:
            with open('links.json', 'r', encoding='utf-8') as f:
                links = json.load(f)
                if links:
                    chosen = random.choice(links)
                    print(f"✅ 외부 링크 로드 완료: {chosen.get('title')}")
                    return chosen
        except Exception as e:
            print(f"⚠️ links.json 로드 실패: {e}")
        return None

    def get_or_create_tags(self, tag_names_str):
        if not tag_names_str: return []
        tag_names = [t.strip() for t in tag_names_str.split(',') if t.strip()]
        tag_ids = []
        for name in tag_names:
            try:
                res = self.session.get(f"{self.base_url}/wp-json/wp/v2/tags?search={name}", headers=self.common_headers)
                tags = res.json()
                match = next((t for t in tags if t['name'].lower() == name.lower()), None)
                if match:
                    tag_ids.append(match['id'])
                else:
                    create_res = self.session.post(f"{self.base_url}/wp-json/wp/v2/tags", headers=self.common_headers, json={"name": name})
                    if create_res.status_code == 201: tag_ids.append(create_res.json()['id'])
            except: continue
        return tag_ids

    def search_naver_news(self, query="국민연금 개혁 전략"):
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

    def generate_image(self, title, excerpt):
        """이미지 모델 업데이트: gemini-2.5-flash-preview-09-2025 전용 로직"""
        print(f"--- [Step 2.5] 대표 이미지 생성 중 (모델: {CONFIG['IMAGE_MODEL']}) ---")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        # 한국인 인물 중심, 텍스트 배제 고도화 프롬프트
        image_prompt = (
            f"Generate a high-quality professional photography for a blog post. "
            f"Subject: A middle-aged South Korean person or elderly couple with a warm, confident smile, "
            f"looking financially secure in a clean, modern, sun-lit Korean home environment. "
            f"Theme: Reliable retirement planning and financial security. "
            f"Visual Style: Cinematic lighting, photorealistic, soft depth of field, 16:9 aspect ratio. "
            f"CRITICAL RULE: DO NOT INCLUDE ANY TEXT, LETTERS, OR CHARACTERS in the image."
        )
        
        payload = {
            "contents": [{"parts": [{"text": image_prompt}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"]
            }
        }

        try:
            res = self.session.post(url, json=payload, timeout=120)
            if res.status_code == 200:
                parts = res.json()['candidates'][0]['content']['parts']
                image_part = next((p for p in parts if 'inlineData' in p), None)
                if image_part:
                    return image_part['inlineData']['data'] # base64 data
        except Exception as e:
            print(f"⚠️ 이미지 생성 실패: {e}")
        return None

    def process_and_upload_image(self, image_base64, filename="featured_image.jpg"):
        """생성된 이미지를 JPG 70% 품질로 변환 및 압축 후 업로드"""
        if not image_base64: return None
        
        raw_data = base64.b64decode(image_base64)
        
        if PIL_AVAILABLE:
            try:
                img = Image.open(io.BytesIO(raw_data))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                
                output = io.BytesIO()
                img.save(output, format="JPEG", quality=70, optimize=True)
                processed_data = output.getvalue()
                print("✅ 이미지 JPG 변환 및 70% 압축 완료")
            except Exception as e:
                print(f"⚠️ 이미지 처리 오류: {e}")
                processed_data = raw_data
        else:
            processed_data = raw_data

        url = f"{self.base_url}/wp-json/wp/v2/media"
        headers = {
            "Authorization": f"Basic {self.auth_header}",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/jpeg"
        }

        try:
            res = self.session.post(url, headers=headers, data=processed_data, timeout=60)
            if res.status_code == 201:
                return res.json().get('id')
        except: pass
        return None

    def generate_content(self, news_items):
        print("--- [Step 2] 롱테일 키워드 기반 정보성 콘텐츠 기획 ---")
        news_context = "\n".join([f"- {n['title']}: {n['desc']}" for n in news_items])
        
        link_instruction = ""
        if self.external_link:
            link_instruction = (
                f"또한, 글의 맥락상 가장 적절한 위치에 아래 외부 링크를 자연스럽게 한 번만 삽입하세요.\n"
                f"삽입 형식: <a href='{self.external_link['url']}' target='_self'><strong>{self.external_link['title']}</strong></a>"
            )

        system_instruction = (
            f"당신은 대한민국 최고의 금융 전문가이자 SEO 전문가입니다. 현재 시점은 2026년 2월입니다.\n"
            f"[기존 발행글 제목] {self.recent_titles}\n\n"
            f"[지침]\n"
            f"1. 롱테일 키워드 전략: 독자가 실제로 검색할 법한 틈새 주제를 선정하세요.\n"
            f"2. 인사말 금지: '안녕하십니까' 등의 자기소개 없이 바로 본론 제목과 핵심 내용으로 시작하세요.\n"
            f"3. 분량: 3,000자 이상의 매우 상세하고 유용한 가이드 글을 작성하세요.\n"
            f"4. 링크 삽입: 국민연금공단 공식 홈페이지 링크(https://www.nps.or.kr)를 포함하고,\n"
            f"{link_instruction}\n"
            f"5. 태그(tags): 콤마(,)로 구분된 3~5개의 핵심 키워드로 작성하세요."
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
        
        prompt = f"참고 뉴스({news_context})를 기반으로 독자의 고민을 해결하는 고품질 롱테일 SEO 최적화 글을 작성해줘."
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

    def publish(self, data, media_id=None, tag_ids=None):
        print("--- [Step 3] 워드프레스 발행 중... ---")
        payload = {
            "title": data['title'],
            "content": data['assembled_content'],
            "excerpt": data['excerpt'],
            "status": "publish",
            "featured_media": media_id if media_id else 0,
            "tags": tag_ids if tag_ids else [],
            "meta": {"_yoast_wpseo_focuskw": data.get('focus_keyphrase', '')}
        }
        res = self.session.post(f"{self.base_url}/wp-json/wp/v2/posts", headers=self.common_headers, json=payload, timeout=60)
        return res.status_code == 201

    def run(self):
        news = self.search_naver_news("국민연금 혜택 전략")
        if not news: sys.exit(1)
        
        post_data = self.generate_content(news)
        tag_ids = self.get_or_create_tags(post_data.get('tags', ''))
        
        # 이미지 생성 및 JPG 압축 업로드
        image_base64 = self.generate_image(post_data['title'], post_data['excerpt'])
        media_id = self.process_and_upload_image(image_base64, f"nps_thumb_{int(time.time())}.jpg")
        
        if self.publish(post_data, media_id, tag_ids):
            print(f"🎉 성공: {post_data['title']}")
            if media_id: print(f"🖼️ 대표 이미지(JPG 70%) 등록 완료 (ID: {media_id})")
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
