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
    print("⚠️ 경고: PIL(Pillow) 라이브러리가 설치되지 않았습니다. 이미지 압축 기능이 제한됩니다.")

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
        # 외부 링크 로드
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
        print(f"🎨 [이미지 생성 단계] 시도 중: {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        
        prompt = (
            f"A professional, high-quality, 4k cinematic photography for a financial blog featured image. "
            f"Subject: A Korean couple or professional in a trustworthy financial setting related to '{title}'. "
            f"Warm sunlight, clean modern office, shallow depth of field. "
            f"Strictly NO TEXT, NO LETTERS, 16:9 aspect ratio."
        )
        
        payload = {
            "instances": [{"prompt": prompt}], 
            "parameters": {"sampleCount": 1}
        }
        
        try:
            res = requests.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                result = res.json()
                if 'predictions' in result and len(result['predictions']) > 0:
                    print("✅ 이미지 데이터 생성 완료")
                    return result['predictions'][0]['bytesBase64Encoded']
                else:
                    print(f"⚠️ API 응답에 이미지 데이터가 없습니다: {result}")
            else:
                print(f"❌ Imagen API 오류 ({res.status_code}): {res.text}")
        except Exception as e:
            print(f"❌ 이미지 생성 중 예외 발생: {e}")
        return None

    def process_and_upload_media(self, img_b64, title):
        """이미지를 처리하여 워드프레스에 업로드"""
        if not img_b64:
            return None
            
        print("📤 [미디어 업로드 단계] 워드프레스 전송 중...")
        raw_data = base64.b64decode(img_b64)
        
        if PIL_AVAILABLE:
            try:
                img = Image.open(io.BytesIO(raw_data))
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                out = io.BytesIO()
                img.save(out, format="JPEG", quality=70, optimize=True)
                upload_data = out.getvalue()
                mime_type = "image/jpeg"
                extension = "jpg"
                print("⚡ JPG 70% 압축 완료")
            except Exception as e:
                print(f"⚠️ 이미지 변환 실패, 원본 업로드 시도: {e}")
                upload_data = raw_data
                mime_type = "image/png"
                extension = "png"
        else:
            upload_data = raw_data
            mime_type = "image/png"
            extension = "png"

        filename = f"thumb_{int(time.time())}.{extension}"
        # 미디어 업로드 API는 별도의 헤더 구성이 필요함
        media_headers = {
            "Authorization": f"Basic {self.auth}",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": mime_type
        }
        
        try:
            upload_res = requests.post(
                f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", 
                headers=media_headers, 
                data=upload_data, 
                timeout=60
            )
            if upload_res.status_code == 201:
                media_id = upload_res.json().get('id')
                print(f"✅ 미디어 등록 성공! ID: {media_id}")
                return media_id
            else:
                print(f"❌ 미디어 업로드 실패 ({upload_res.status_code}): {upload_res.text}")
        except Exception as e:
            print(f"❌ 미디어 업로드 중 예외 발생: {e}")
        return None

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
        except: pass
        return None

    def generate_post(self):
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 작업 시작 ---")
        
        # 1. 소재 찾기
        news = self.search_naver_news("국민연금 혜택")
        
        # 2. 본문 기획
        link_instr = ""
        if self.external_link:
            link_instr = f"본문 중간에 다음 링크를 자연스럽게 한 번 포함하세요: <a href='{self.external_link['url']}' target='_self'><strong>{self.external_link['title']}</strong></a>"

        system = f"""대한민국 금융 전문가로서 2026년 2월 기준의 전문 칼럼을 작성하세요.
        - 인사말/자기소개 절대 금지.
        - 구텐베르크 블록 마커(<!-- wp:paragraph --> 등)를 사용하여 워드프레스 편집기 최적화.
        - 국민연금공단(https://www.nps.or.kr) 링크 포함.
        - {link_instr}
        - 3,000자 이상의 충분한 분량."""

        # 3. 텍스트 생성
        post_data = self.call_gemini(f"뉴스 참고:\n{news}\n\n위 내용을 기반으로 한 롱테일 정보성 가이드 작성.", system)
        if not post_data:
            print("❌ 본문 생성 실패")
            return

        # 4. 이미지 생성 및 업로드 (핵심)
        img_b64 = self.generate_image(post_data['title'])
        media_id = self.process_and_upload_media(img_b64, post_data['title'])

        # 5. 최종 발행
        print("🚀 워드프레스 최종 발행 시도 중...")
        payload = {
            "title": post_data['title'],
            "content": post_data['content'],
            "excerpt": post_data['excerpt'],
            "status": "publish",
            "featured_media": int(media_id) if media_id else 0
        }
        
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers=self.headers, json=payload, timeout=60)
        if res.status_code == 201:
            print(f"🎉 최종 발행 성공: {res.json().get('link')}")
        else:
            print(f"❌ 발행 실패 ({res.status_code}): {res.text}")

if __name__ == "__main__":
    WordPressAutoPoster().generate_post()
