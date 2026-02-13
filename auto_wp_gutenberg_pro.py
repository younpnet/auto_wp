import requests
import json
import time
import base64
import re
import os
import io
import random
from datetime import datetime

# 이미지 처리를 위한 PIL 라이브러리 (JPG 변환 및 압축용)
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️ 경고: PIL(Pillow) 라이브러리가 설치되지 않았습니다.")

# ==============================================================================
# 환경 변수 설정
# ==============================================================================
CONFIG = {
    "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
    "WP_URL": os.environ.get("WP_URL", "").rstrip("/"),
    "WP_USERNAME": os.environ.get("WP_USERNAME", "admin"),
    "WP_APP_PASSWORD": os.environ.get("WP_APP_PASSWORD", ""),
    "TEXT_MODEL": "gemini-2.5-flash-preview-09-2025",
    "IMAGE_MODEL": "imagen-4.0-generate-001",
    "NAVER_CLIENT_ID": os.environ.get("NAVER_CLIENT_ID", ""),
    "NAVER_CLIENT_SECRET": os.environ.get("NAVER_CLIENT_SECRET", "")
}

class WordPressAutoPoster:
    def __init__(self):
        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth = base64.b64encode(user_pass.encode()).decode()
        self.headers = {
            "Authorization": f"Basic {self.auth}",
            "Content-Type": "application/json"
        }
        # 외부 링크 및 최근 제목 로드
        self.external_link = self.load_external_link()

    def load_external_link(self):
        """links.json에서 무작위 링크 1개를 가져옵니다."""
        try:
            if os.path.exists('links.json'):
                with open('links.json', 'r', encoding='utf-8') as f:
                    links = json.load(f)
                    if links:
                        return random.choice(links)
        except: pass
        return None

    def search_naver_news(self, query="국민연금"):
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 10, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in res.json().get('items', [])])
        except: return ""
        return ""

    def generate_image(self, title):
        """본문 제목 기반 텍스트 없는 실사 이미지 생성"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        prompt = f"A professional high-quality financial blog header image about '{title}'. Featuring a clean modern office, warm cinematic lighting, Korean people in a reliable retirement setting. NO TEXT, 16:9 aspect ratio."
        payload = {"instances": {"prompt": prompt}, "parameters": {"sampleCount": 1}}
        try:
            res = requests.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                return res.json()['predictions'][0]['bytesBase64Encoded']
        except: return None
        return None

    def process_and_upload_media(self, img_b64, title):
        """이미지를 JPG 70% 품질로 압축하여 업로드"""
        if not img_b64: return None
        raw_data = base64.b64decode(img_b64)
        
        if PIL_AVAILABLE:
            img = Image.open(io.BytesIO(raw_data))
            if img.mode != 'RGB': img = img.convert('RGB')
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=70, optimize=True)
            upload_data = out.getvalue()
        else:
            upload_data = raw_data

        headers = {
            "Authorization": f"Basic {self.auth}",
            "Content-Disposition": f'attachment; filename="thumb_{int(time.time())}.jpg"',
            "Content-Type": "image/jpeg"
        }
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", headers=headers, data=upload_data)
        return res.json().get('id') if res.status_code == 201 else None

    def call_gemini(self, prompt, system_instruction):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "excerpt": {"type": "string"},
                        "tags": {"type": "string"}
                    },
                    "required": ["title", "content", "excerpt", "tags"]
                }
            }
        }
        try:
            res = requests.post(url, json=payload, timeout=120)
            if res.status_code == 200:
                return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
        except: return None
        return None

    def generate_post(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 작업 시작")
        news = self.search_naver_news("국민연금 개혁 전략")
        
        link_instr = ""
        if self.external_link:
            link_instr = f"본문 중간에 다음 링크를 자연스럽게 한 번 포함하세요: <a href='{self.external_link['url']}' target='_self'><strong>{self.external_link['title']}</strong></a>"

        system = f"""대한민국 금융 전문가로서 2026년 2월 기준 3,000자 이상의 롱테일 정보글을 작성하세요.
        - 인사말 및 자기소개 금지. 
        - 구텐베르크 블록 마커(<!-- wp:paragraph --> 등)를 사용해 구조화하세요.
        - 국민연금공단(https://www.nps.or.kr) 링크를 반드시 포함하세요.
        - {link_instr}
        - 마크다운 기호 없이 순수 HTML/블록 마커만 사용하세요."""

        post_data = self.call_gemini(f"참고 뉴스:\n{news}\n\n위 데이터를 활용해 롱테일 가이드를 작성해줘.", system)
        if not post_data: return

        # 이미지 생성 및 업로드
        img_b64 = self.generate_image(post_data['title'])
        media_id = self.process_and_upload_media(img_b64, post_data['title'])

        # 워드프레스 발행
        payload = {
            "title": post_data['title'],
            "content": post_data['content'],
            "excerpt": post_data['excerpt'],
            "status": "publish",
            "featured_media": media_id if media_id else 0
        }
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers=self.headers, json=payload)
        if res.status_code == 201:
            print(f"🎉 성공: {post_data['title']}")

if __name__ == "__main__":
    WordPressAutoPoster().generate_post()
