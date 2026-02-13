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
                # JSON 파싱 실패를 대비한 예외 처리 추가
                try:
                    data = json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
                    if not data.get('content'):
                        print("⚠️ 경고: AI가 본문을 생성하지 않았습니다.")
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
        - 독자의 절실한 고민을 건드리는 핵심 키워드로 제목을 시작하고, 신뢰도를 높이기 위해 제목 끝에 '(2026년 업데이트)', '[2026 최신 기준]', '(올해 바뀌는 핵심 가이드)' 등을 자연스럽게 배치하세요.
        - 예: '매달 30만원 더 받는 국민연금 수령액 증대 전략: 추납과 반납의 실전 수익률 분석 [2026 최신 가이드]'

        [본문 작성 가이드라인 - 사람이 쓴 것처럼]
        - 인사말('안녕하십니까' 등)은 절대 하지 마세요. 바로 강렬한 화두로 본론을 시작하세요.
        - 전문가적 시각: "단순히 얼마를 받느냐보다 중요한 것은 세금과 건보료의 역습입니다"와 같은 깊이 있는 조언을 포함하세요.
        - 문체: 기계적인 설명조가 아닌, 친절하지만 단호한 전문가의 조언을 담은 문체를 사용하세요.
        - 구조화: 반드시 구텐베르크 블록 마커(heading, paragraph, list, table)를 사용하여 웹 환경에 최적화하세요.
        - 중복 금지: 앞에서 언급한 수치나 설명을 뒤에서 다시 반복하지 마세요.
        - {link_instr}
        - 국민연금공단(https://www.nps.or.kr) 공식 홈페이지를 출처로 언급하며 링크하세요.

        [데이터 구조]
        JSON 객체(title, content, excerpt)로 응답하며, content 필드 내부에 모든 구텐베르크 HTML을 포함해야 합니다. 본문이 누락되지 않도록 끝까지 완성하세요."""

        post_data = self.call_gemini(f"최신 뉴스 소스:\n{news}\n\n위 데이터를 기반으로 실생활에 밀접한 전문가 칼럼을 작성해줘.", system)
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
