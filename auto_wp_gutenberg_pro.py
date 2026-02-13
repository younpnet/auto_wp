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
            "Authorization": f"Basic {self.auth}"
        }
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
        params = {"query": query, "display": 12, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                items = res.json().get('items', [])
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in items])
        except: return "최근 국민연금 주요 이슈 및 개혁안 분석"
        return ""

    def generate_image(self, title):
        """본문 제목 기반 이미지 생성"""
        print(f"🎨 [이미지 생성 단계] 시도 중: {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        
        prompt = (
            f"A high-end professional lifestyle photography for a South Korean finance blog. "
            f"Subject: A Korean couple or person in a sun-drenched modern Korean living room, looking happy and secure about their future. "
            f"Context: {title}. Realistic, cinematic lighting, shallow depth of field. "
            f"Strictly NO TEXT, NO LETTERS, NO NUMBERS, 16:9 aspect ratio."
        )
        
        payload = {
            "instances": [{"prompt": prompt}], 
            "parameters": {"sampleCount": 1}
        }
        
        try:
            res = requests.post(url, json=payload, timeout=100)
            if res.status_code == 200:
                result = res.json()
                if 'predictions' in result and len(result['predictions']) > 0:
                    return result['predictions'][0]['bytesBase64Encoded']
            else:
                print(f"❌ 이미지 생성 API 오류 ({res.status_code}): {res.text}")
        except Exception as e:
            print(f"❌ 이미지 생성 중 예외 발생: {e}")
        return None

    def process_and_upload_media(self, img_b64):
        """이미지 업로드 (Multipart 방식으로 500 에러 해결 시도)"""
        if not img_b64: return None
            
        print("📤 [미디어 업로드 단계] 워드프레스 전송 중...")
        raw_data = base64.b64decode(img_b64)
        
        if PIL_AVAILABLE:
            try:
                img = Image.open(io.BytesIO(raw_data))
                if img.mode != 'RGB': img = img.convert('RGB')
                out = io.BytesIO()
                img.save(out, format="JPEG", quality=70, optimize=True)
                upload_data = out.getvalue()
                ext = "jpg"
                mime_type = "image/jpeg"
                print("⚡ JPG 70% 압축 완료")
            except:
                upload_data = raw_data
                ext = "png"
                mime_type = "image/png"
        else:
            upload_data = raw_data
            ext = "png"
            mime_type = "image/png"

        # 파일명을 아주 단순하게 만들어 서버측 경로 이동 오류 방지
        filename = f"thumb_{int(time.time())}.{ext}"
        
        # multipart/form-data 방식으로 전송 (requests의 files 파라미터 사용)
        files = {
            'file': (filename, upload_data, mime_type)
        }
        
        # 헤더에서 Content-Type을 제거하여 requests가 boundary를 자동으로 설정하게 함
        headers = {
            "Authorization": f"Basic {self.auth}"
        }
        
        try:
            res = requests.post(
                f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", 
                headers=headers, 
                files=files,
                timeout=60
            )
            if res.status_code == 201:
                mid = res.json().get('id')
                print(f"✅ 미디어 등록 성공 (ID: {mid})")
                return mid
            else:
                print(f"❌ 미디어 업로드 실패 ({res.status_code}): {res.text}")
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
                        "excerpt": {"type": "string"}
                    },
                    "required": ["title", "content", "excerpt"]
                }
            }
        }
        try:
            res = requests.post(url, json=payload, timeout=180)
            if res.status_code == 200:
                return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
        except: pass
        return None

    def clean_content(self, content):
        """본문 중복 제거 및 리스트 블록 안전 병합"""
        # 1. 리스트 블록 병합 (구조 보호를 위해 \s* 활용)
        content = re.sub(r'</ul>\s*<!-- /wp:list -->\s*<!-- wp:list -->\s*<ul>', '', content, flags=re.DOTALL)
        
        # 2. 문단 단위 중복 제거 로직 개선 (제목/블록 마커 보존)
        blocks = re.split(r'(<!-- wp:)', content)
        if len(blocks) < 2: return content
        
        refined_blocks = [blocks[0]] # 초기 텍스트 보존
        seen_fingerprints = set()
        
        for i in range(1, len(blocks), 2):
            block_marker = blocks[i]
            block_body = blocks[i+1] if (i+1) < len(blocks) else ""
            full_block = block_marker + block_body
            
            # 텍스트 내용 추출하여 중복 검사 (제목은 제외하고 문단만 검사)
            if "wp:paragraph" in block_marker:
                text_only = re.sub(r'<[^>]+>', '', block_body).strip()
                if len(text_only) > 15:
                    fingerprint = re.sub(r'[^가-힣]', '', text_only)[:40]
                    if fingerprint in seen_fingerprints:
                        continue
                    seen_fingerprints.add(fingerprint)
            
            refined_blocks.append(full_block)
            
        return "".join(refined_blocks)

    def generate_post(self):
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 국민연금 자동 포스팅 시작 ---")
        news = self.search_naver_news("국민연금 전략 2026")
        
        link_instr = ""
        if self.external_link:
            link_instr = f"본문 중간에 다음 링크를 자연스럽게 한 번 포함하세요: <a href='{self.external_link['url']}' target='_self'><strong>{self.external_link['title']}</strong></a>"

        system = f"""당신은 대한민국 최고의 금융 전문가입니다. 2026년 2월 시점의 전문적이고 유익한 롱테일 가이드(3,000자 이상)를 작성하세요.
        - 인사말 및 자기소개는 절대 하지 마세요.
        - 반드시 구텐베르크 블록 마커(heading, paragraph, list)를 사용하여 구조화하세요.
        - [중요] 리스트 작성 시 모든 항목을 단 하나의 <!-- wp:list --><ul> 블록 내부에 담으세요.
        - 제목(h2, h3)을 생략하지 말고 논리적으로 배치하세요.
        - 국민연금공단(https://www.nps.or.kr) 링크를 포함하세요.
        - {link_instr}
        - 마크다운 기호 없이 순수 HTML과 블록 마커만 사용하세요."""

        post_data = self.call_gemini(f"참고 데이터:\n{news}\n\n위 내용을 활용해 독자의 고민을 해결하는 상세한 롱테일 정보글을 작성해줘.", system)
        if not post_data:
            print("❌ 본문 생성 실패")
            return

        # 본문 정제 (중복 제거 및 리스트 병합)
        refined_content = self.clean_content(post_data['content'])

        # 이미지 생성 및 업로드
        img_b64 = self.generate_image(post_data['title'])
        media_id = self.process_and_upload_media(img_b64)

        # 최종 발행
        print("🚀 워드프레스 최종 발행 시도 중...")
        payload = {
            "title": post_data['title'],
            "content": refined_content,
            "excerpt": post_data['excerpt'],
            "status": "publish",
            "featured_media": int(media_id) if media_id else 0
        }
        
        headers = {
            "Authorization": f"Basic {self.auth}",
            "Content-Type": "application/json"
        }
        
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers=headers, json=payload, timeout=60)
        if res.status_code == 201:
            print(f"🎉 최종 발행 성공: {res.json().get('link')}")
        else:
            print(f"❌ 발행 실패 ({res.status_code}): {res.text}")

if __name__ == "__main__":
    WordPressAutoPoster().generate_post()
