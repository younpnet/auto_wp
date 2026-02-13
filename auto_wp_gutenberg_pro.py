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
        # 중복 방지를 위한 최근 글 제목 로드
        self.recent_titles = self.fetch_recent_post_titles(50)

    def fetch_recent_post_titles(self, count=50):
        """워드프레스에서 최근 발행된 글 제목들을 가져옵니다."""
        print(f"🔍 중복 방지를 위해 최근 글 {count}개를 분석 중...")
        url = f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title"}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=20)
            if res.status_code == 200:
                return [re.sub('<.*?>', '', post['title']['rendered']).strip() for post in res.json()]
        except Exception as e:
            print(f"⚠️ 최근 글 로드 실패: {e}")
        return []

    def get_or_create_tag_ids(self, tags_input):
        """텍스트 태그를 받아 워드프레스 ID로 변환 (없으면 생성)"""
        if not tags_input: return []
        tag_names = [t.strip() for t in tags_input.split(',')]
        tag_ids = []
        for name in tag_names:
            try:
                search_url = f"{CONFIG['WP_URL']}/wp-json/wp/v2/tags?search={name}"
                res = requests.get(search_url, headers=self.headers)
                existing = res.json()
                match = next((t for t in existing if t['name'].lower() == name.lower()), None)
                
                if match:
                    tag_ids.append(match['id'])
                else:
                    create_res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/tags", 
                                             headers=self.headers, json={"name": name})
                    if create_res.status_code == 201:
                        tag_ids.append(create_res.json()['id'])
            except: continue
        return tag_ids

    def load_external_link(self):
        try:
            if os.path.exists('links.json'):
                with open('links.json', 'r', encoding='utf-8') as f:
                    links = json.load(f)
                    if links: return random.choice(links)
        except: pass
        return None

    def search_naver_news(self):
        """다양한 키워드로 뉴스 검색하여 소재 고갈 방지"""
        queries = ["국민연금 수령액 늘리는 전략", "2026년 국민연금 개편 전망", "노후 자산관리 팁", "연금저축 IRP 활용법", "기초연금 기준 변경"]
        query = random.choice(queries)
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 10, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in res.json().get('items', [])])
        except: return "국민연금 최신 이슈 및 노후 설계 전략"
        return ""

    def generate_image(self, title):
        print(f"🎨 이미지 생성 중: {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        prompt = f"Professional and high-end lifestyle photography for a Korean finance blog. A middle-aged Korean couple looking happy in a sunlit modern home. Theme: retirement and pension security. Photorealistic, 16:9, NO TEXT."
        payload = {"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1}}
        try:
            res = requests.post(url, json=payload, timeout=100)
            if res.status_code == 200:
                return res.json()['predictions'][0]['bytesBase64Encoded']
        except: return None
        return None

    def upload_media(self, img_b64):
        if not img_b64: return None
        raw_data = base64.b64decode(img_b64)
        if PIL_AVAILABLE:
            try:
                img = Image.open(io.BytesIO(raw_data)).convert('RGB')
                out = io.BytesIO()
                img.save(out, format="JPEG", quality=70, optimize=True)
                raw_data = out.getvalue()
            except: pass
        
        headers = {"Authorization": f"Basic {self.auth}", "Content-Type": "image/jpeg", "Content-Disposition": f'attachment; filename="nps_{int(time.time())}.jpg"'}
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", headers=headers, data=raw_data)
        return res.json().get('id') if res.status_code == 201 else None

    def call_gemini(self, prompt, system_instruction):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.85, # 다양성을 높여 반복 생성 방지
                "maxOutputTokens": 8192,
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
            res = requests.post(url, json=payload, timeout=300)
            if res.status_code == 200:
                return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
            else:
                print(f"❌ AI 호출 실패: {res.text}")
        except Exception as e:
            print(f"❌ 오류: {e}")
        return None

    def clean_content(self, content):
        """본문 내 불필요한 AI 생성 주석(//paragraph 등) 및 반복 블록 완벽 제거"""
        if not content: return ""
        
        # 1. //paragraph, //heading 등 슬래시 주석 완벽 제거 (정규표현식 강화)
        content = re.sub(r'//[a-zA-Z]+', '', content)
        
        # 2. 리스트 블록 병합 (끊겨 있는 리스트 통합)
        content = re.sub(r'</ul>\s*<!-- /wp:list -->\s*<!-- wp:list -->\s*<ul>', '', content, flags=re.DOTALL)
        
        # 3. 마크다운 기호 및 코드 블록 감싸기 제거
        content = content.replace('```html', '').replace('```', '')
        
        # 4. 문단 단위 중복 지문 검사 및 제거 (Image 2의 무한 루프 방지)
        paragraphs = re.split(r'(<!-- wp:[^>]+-->)', content)
        seen_fingerprints = set()
        refined_blocks = []
        
        for i in range(0, len(paragraphs)):
            block = paragraphs[i]
            # 텍스트가 있는 블록만 지문 추출
            text_only = re.sub(r'<[^>]+>', '', block).strip()
            if len(text_only) > 30:
                fingerprint = re.sub(r'[^가-힣]', '', text_only)[:50]
                if fingerprint in seen_fingerprints:
                    continue # 중복된 내용은 추가하지 않음
                seen_fingerprints.add(fingerprint)
            refined_blocks.append(block)
            
        return "".join(refined_blocks).strip()

    def generate_post(self):
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 고품질 포스팅 생성 시작 ---")
        news = self.search_naver_news()
        
        # 외부 링크 구성
        link_instr = ""
        if self.external_link:
            link_instr = f"글의 맥락에 맞춰 다음 링크를 <a> 태그로 본문 중간에 자연스럽게 한 번만 삽입하세요: {self.external_link['title']} ({self.external_link['url']})"
        
        system = f"""당신은 대한민국 최고의 금융 자산관리 전문가입니다. 독자들에게 통찰력 있는 전문가 칼럼을 작성하세요.

[필수 요구사항 - 반복 금지]
1. 반복 금지: 서론, 본론, FAQ, 결론에서 동일한 문장이나 핵심 조언을 복사해서 붙여넣지 마세요. 각 섹션은 반드시 '새로운' 정보나 시각을 담아야 합니다.
2. 분량: 3,000자 이상의 상세한 정보글을 작성하세요.
3. 페르소나: 노후 설계에 대한 전문적인 비판과 실질적인 대안을 제시하는 전문가의 어조를 유지하세요.
4. 중복 방지: 이미 다음 주제들로 글을 썼습니다: {self.recent_titles}. 이와 절대 겹치지 않는 새로운 주제를 선정하세요.
5. 금지: 본문 내에 //paragraph 같은 불필요한 주석이나 가짜 마커를 절대 포함하지 마세요. 오직 구텐베르크 주석(<!-- wp:paragraph --> 등)만 사용하세요.

[구성 요소]
- 화두를 던지는 전문가적 서론
- h2, h3 소제목을 활용한 체계적인 본론 (데이터와 수치 활용)
- {link_instr}
- 국민연금공단(https://www.nps.or.kr) 공식 링크 포함
- 3개 이상의 상세한 Q&A (FAQ)
- 독자의 실천을 독려하는 결론"""

        post_data = self.call_gemini(f"참고 뉴스:\n{news}\n\n위 데이터를 바탕으로 당신의 통찰을 담은 3,000자 이상의 초고품질 전문가 칼럼을 작성해줘.", system)
        
        if not post_data or not post_data.get('content') or len(post_data['content']) < 500:
            print("❌ 본문 생성 실패")
            return

        # 본문 정제 (//paragraph 제거 및 내용 반복 제거)
        post_data['content'] = self.clean_content(post_data['content'])

        # 태그 ID 처리
        tag_ids = self.get_or_create_tag_ids(post_data.get('tags', ''))

        # 이미지 처리
        img_id = self.upload_media(self.generate_image(post_data['title']))

        # 최종 발행
        print("🚀 워드프레스 최종 발행 중...")
        payload = {
            "title": post_data['title'],
            "content": post_data['content'],
            "excerpt": post_data['excerpt'],
            "status": "publish",
            "featured_media": img_id if img_id else 0,
            "tags": tag_ids
        }
        
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers=self.headers, json=payload, timeout=60)
        if res.status_code == 201:
            print(f"🎉 발행 성공: {post_data['title']}")
        else:
            print(f"❌ 실패: {res.text}")

if __name__ == "__main__":
    WordPressAutoPoster().generate_post()
