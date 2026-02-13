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
            f"Subject: A Korean couple or professional in a sun-drenched modern Korean living room, looking happy and secure about their future. "
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

        filename = f"thumb_{int(time.time())}.{ext}"
        files = {'file': (filename, upload_data, mime_type)}
        headers = {"Authorization": f"Basic {self.auth}"}
        
        try:
            res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", headers=headers, files=files, timeout=60)
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
                "temperature": 0.7,
                "maxOutputTokens": 8192,  # 충분한 토큰을 할당하여 장문이 잘리지 않도록 함
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
                try:
                    data = json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
                    if not data.get('content') or len(data['content']) < 500:
                        print("⚠️ 경고: AI가 본문을 너무 짧게 생성했거나 생성하지 않았습니다.")
                    return data
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"❌ JSON 파싱 에러: {e}")
            else:
                print(f"❌ API 요청 실패 ({res.status_code}): {res.text}")
        except Exception as e:
            print(f"❌ 텍스트 생성 중 예외 발생: {e}")
        return None

    def clean_content(self, content):
        """본문 중복 제거 및 리스트 블록 안전 병합"""
        if not content: return ""
        # 1. 리스트 블록 병합
        content = re.sub(r'</ul>\s*<!-- /wp:list -->\s*<!-- wp:list -->\s*<ul>', '', content, flags=re.DOTALL)
        
        # 2. 문단 단위 중복 제거 로직 개선
        blocks = re.split(r'(<!-- wp:)', content)
        if len(blocks) < 2: return content
        
        refined_blocks = [blocks[0]]
        seen_fingerprints = set()
        
        for i in range(1, len(blocks), 2):
            block_marker = blocks[i]
            block_body = blocks[i+1] if (i+1) < len(blocks) else ""
            full_block = block_marker + block_body
            
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
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 국민연금 전문가 칼럼 생성 시작 ---")
        news = self.search_naver_news("국민연금 개혁 전략")
        
        link_instr = ""
        if self.external_link:
            link_instr = f"본문 중간에 자연스럽게 다음 링크를 앵커 텍스트 형식으로 포함하세요: <a href='{self.external_link['url']}' target='_self'><strong>{self.external_link['title']}</strong></a>"

        system = f"""당신은 대한민국 최고의 노후 자산 관리 전문가이자 금융 칼럼니스트입니다. 
        독자들에게 단순히 정보를 나열하는 것이 아니라, 전문가의 통찰력과 진정성이 느껴지는 롱테일 가이드(3,000자 이상)를 작성하세요.

        [제목 전략]
        - 제목 맨 앞에 '2026년'이나 '2월'을 기계적으로 붙이지 마세요.
        - 독자의 절실한 고민을 건드리는 핵심 키워드로 제목을 시작하고, 제목 끝에 '(2026년 업데이트)', '[2026 최신 기준]' 등 신뢰도 높은 문구를 자연스럽게 배치하세요.

        [본문 필수 구성 - 절대 생략 금지]
        1. 서론: 현재의 연금 개혁 트렌드와 독자가 직면한 문제 제기.
        2. 본론: 최소 4개 이상의 h2 소제목 섹션. 구체적인 수치와 법적 근거 제시.
        3. 전문가 제언: 독자의 지갑을 지킬 수 있는 실질적인 Action Plan 조언.
        4. 자주 묻는 질문(FAQ): 반드시 <!-- wp:heading {{"level":2}} --><h2>자주 묻는 질문(FAQ)</h2> 블록을 만들고 3개 이상의 질문과 답변을 상세히 작성하세요.
        5. 결론: 노후 준비에 대한 격려와 마무리 인사.

        [본문 작성 원칙]
        - 인사말('안녕하십니까' 등)은 절대 하지 마세요. 바로 강렬한 화두로 본론을 시작하세요.
        - 구조화: 반드시 구텐베르크 블록 마커(heading, paragraph, list, table)를 사용하여 웹 환경에 최적화하세요.
        - 3,000자 이상의 풍부한 정보량을 제공하며, 절대 요약하거나 중간에 내용을 자르지 마세요.
        - {link_instr}
        - 국민연금공단(https://www.nps.or.kr) 공식 홈페이지를 출처로 언급하며 링크하세요.

        [데이터 구조]
        JSON 객체(title, content, excerpt)로 응답하세요. content 필드 내부에 모든 구텐베르크 HTML을 포함해야 합니다."""

        post_data = self.call_gemini(f"최신 뉴스 소스:\n{news}\n\n위 데이터를 기반으로 실생활에 밀접하고 정보량이 방대한 전문가 칼럼을 작성해줘. FAQ 섹션은 필수로 포함해.", system)
        if not post_data or not post_data.get('content'):
            print("❌ 본문 데이터 생성 실패로 작업을 중단합니다.")
            return

        refined_content = self.clean_content(post_data['content'])

        img_b64 = self.generate_image(post_data['title'])
        media_id = self.process_and_upload_media(img_b64)

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
