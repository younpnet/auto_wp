import requests
import json
import time
import base64
import re
import os
import sys
from datetime import datetime
try:
    from PIL import Image
    import io
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️ PIL 없음 - 이미지 비율 검증 생략")

CONFIG = {
    "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
    "WP_URL": os.environ.get("WP_URL", ""),
    "WP_USERNAME": os.environ.get("WP_USERNAME", "admin"),
    "WP_APP_PASSWORD": os.environ.get("WP_APP_PASSWORD", ""),
    "NAVER_CLIENT_ID": os.environ.get("NAVER_CLIENT_ID", ""),
    "NAVER_CLIENT_SECRET": os.environ.get("NAVER_CLIENT_SECRET", ""),
    "TEXT_MODEL": "gemini-2.5-flash-preview-09-2025",
    "IMAGE_MODEL": "gemini-2.5-flash-image",
    "IMAGE_SIZE": "1K"
}

class WordPressAutoPoster:
    def __init__(self):
        print("🚀 국민연금 자동 포스터 최종버전 시작")
        self.validate_config()
        self.setup_session()
        self.load_recent_titles()

    def validate_config(self):
        required = ["WP_URL", "WP_APP_PASSWORD", "GEMINI_API_KEY"]
        for key in required:
            if not CONFIG[key]:
                print(f"❌ {key} 환경변수 필요")
                sys.exit(1)
        print("✅ 설정 완료")

    def setup_session(self):
        self.base_url = CONFIG["WP_URL"].rstrip("/")
        self.session = requests.Session()
        self.session.timeout = 30
        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth_header = base64.b64encode(user_pass.encode()).decode()
        self.common_headers = {
            "Authorization": f"Basic {self.auth_header}",
            "Content-Type": "application/json"
        }

    def load_recent_titles(self):
        try:
            res = self.session.get(f"{self.base_url}/wp-json/wp/v2/posts?per_page=10")
            global RECENT_TITLES
            RECENT_TITLES = [p['title']['rendered'] for p in res.json()]
            print(f"✅ 최근 {len(RECENT_TITLES)}개 제목 로드")
        except:
            RECENT_TITLES = []
            print("⚠️ 최근 제목 로드 생략")

    def search_news(self):
        if not CONFIG["NAVER_CLIENT_ID"]:
            return [{"title": "국민연금 2026 최신 변화", "desc": "연금 정책 업데이트"}]

        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": "국민연금", "display": 15, "sort": "sim"}

        try:
            res = self.session.get(url, headers=headers, params=params)
            items = res.json().get('items', [])
            news = []
            seen = set()
            for item in items:
                title = re.sub(r'<.*?>', '', item['title'])
                if title not in seen:
                    seen.add(title)
                    news.append({
                        "title": title,
                        "desc": re.sub(r'<.*?>', '', item['description'])
                    })
                    if len(news) >= 8:
                        break
            print(f"✅ {len(news)}개 뉴스 수집")
            return news
        except:
            return []

    def generate_content(self, news):
        news_text = "\\n".join([f"• {n['title']}" for n in news])

        system = f"""국민연금 전문가 (2026년 2월 기준).
기존 주제 피하기: {RECENT_TITLES}
롱테일 키워드 필수 (예: "프리랜서 국민연금 납부전략")"""

        schema = {{
            "type": "object",
            "properties": {{
                "title": {{"type": "string"}},
                "focus_keyphrase": {{"type": "string"}},
                "tags": {{"type": "string"}},
                "excerpt": {{"type": "string"}},
                "blocks": {{"type": "array"}}
            }}
        }}

        prompt = f"뉴스 기반 롱테일 글:\\n{news_text}"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {{
            "contents": [{{"parts": [{{"text": prompt}}]}}],
            "systemInstruction": {{"parts": [{{"text": system}}]}},
            "generationConfig": {{"responseMimeType": "application/json", "responseSchema": schema}}
        }}

        try:
            res = self.session.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                data = res.json()['candidates'][0]['content']['parts'][0]['text']
                return json.loads(data)
        except:
            pass
        return None

    def generate_image(self, title):
        scenarios = {{
            "default": "Korean elderly couple happy at home natural light modern interior 16:9 landscape blog header no text DSLR quality",
            "calculator": "calculator Korean won bills desk closeup office lighting 16:9 landscape no text stock photo",
            "documents": "Korean government forms desk pen paperwork office daylight 16:9 landscape no text professional"
        }}

        prompt = scenarios["default"] + " 16:9 LANDSCAPE CRITICAL"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {{
            "contents": [{{"parts": [{{"text": prompt}}]}}],
            "generationConfig": {{
                "responseModalities": ["IMAGE"],
                "imageGenerationConfig": {{"aspectRatio": "LANDSCAPE"}}
            }}
        }}

        try:
            res = self.session.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                data = res.json()
                for c in data['candidates']:
                    for p in c['content']['parts']:
                        if 'inlineData' in p:
                            img_data = base64.b64decode(p['inlineData']['data'])
                            if PIL_AVAILABLE:
                                img = Image.open(io.BytesIO(img_data))
                                w, h = img.size
                                if 1.75 <= w/h <= 1.85:
                                    return self.upload_image(img_data, title)
                            else:
                                return self.upload_image(img_data, title)
        except:
            pass
        return None

    def upload_image(self, img_data, title):
        safe_name = re.sub(r'[^a-zA-Z0-9가-힣]', '_', title)[:30] + '.png'
        files = {{'file': (safe_name, img_data, 'image/png')}}

        try:
            res = self.session.post(f"{self.base_url}/wp-json/wp/v2/media", 
                                  headers={{"Authorization": f"Basic {self.auth_header}"}},
                                  files=files)
            if res.status_code == 201:
                return res.json()['id']
        except:
            pass
        return None

    def publish_post(self, data):
        img_id = self.generate_image(data['title'])
        tags = data.get('tags', '국민연금').split(',')

        payload = {{
            "title": data['title'],
            "content": data['content'],
            "excerpt": data['excerpt'][:155],
            "status": "publish",
            "tags": tags,
            "meta": {{
                "_yoast_wpseo_focuskw": data['focus_keyphrase'],
                "_yoast_wpseo_metadesc": data['excerpt'][:155]
            }}
        }}

        if img_id:
            payload["featured_media"] = img_id

        res = self.session.post(f"{self.base_url}/wp-json/wp/v2/posts", 
                              headers=self.common_headers, json=payload)

        if res.status_code == 201:
            print(f"🎉 성공: {res.json()['link']}")
            return True
        print(f"❌ 실패: {res.status_code}")
        return False

    def run(self):
        print(f"[{datetime.now().strftime('%H:%M')}] 시작")
        news = self.search_news()
        data = self.generate_content(news)
        if data:
            self.publish_post(data)
        print("완료!")

if __name__ == "__main__":
    WordPressAutoPoster().run()
