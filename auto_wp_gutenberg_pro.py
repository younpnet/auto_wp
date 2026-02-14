import requests
import json
import time
import base64
import re
import os
import io
import random
from datetime import datetime

# 이미지 처리를 위한 PIL 라이브러리
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
        self.headers = {"Authorization": f"Basic {self.auth}"}
        
        # 외부 링크 2개 로드
        self.external_links = self.load_external_links(2)
        # 내부 링크 2개용 최근 발행글 데이터 로드
        self.internal_link_pool = self.fetch_internal_link_pool(15)
        # 중복 방지용 제목 리스트
        self.recent_titles = [post['title'] for post in self.internal_link_pool]

    def fetch_internal_link_pool(self, count=15):
        """내부 링크용 최근 발행글을 가져옵니다."""
        url = f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title,link"}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=20)
            if res.status_code == 200:
                return [{"title": re.sub('<.*?>', '', post['title']['rendered']).strip(), "url": post['link'].strip()} for post in res.json()]
        except: pass
        return []

    def load_external_links(self, count=2):
        """무작위 외부 링크를 가져옵니다."""
        try:
            if os.path.exists('links.json'):
                with open('links.json', 'r', encoding='utf-8') as f:
                    links = json.load(f)
                    return random.sample(links, min(len(links), count))
        except: pass
        return []

    def get_or_create_tag_ids(self, tags_input):
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
                    if create_res.status_code == 201: tag_ids.append(create_res.json()['id'])
            except: continue
        return tag_ids

    def search_naver_news(self):
        queries = ["국민연금 개혁안 영향", "노후 자산관리 실전 전략", "국민연금 수령액 늘리는 팁"]
        query = random.choice(queries)
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {"X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]}
        params = {"query": query, "display": 12, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in res.json().get('items', [])])
        except: return "국민연금 최신 동향 분석"
        return ""

    def generate_image(self, title, excerpt):
        print(f"🎨 이미지 생성 중 (노년 테마): {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        image_prompt = (
            f"High-end professional photography for a financial blog. "
            f"Subject: A happy South Korean elderly couple in their late 70s, "
            f"sitting in a sun-drenched, modern minimalist Korean home, holding a financial document and smiling warmly. "
            f"Style: Photorealistic, shallow depth of field, cinematic lighting, 16:9 aspect ratio. "
            f"CRITICAL: NO TEXT, NO LETTERS, NO NUMBERS in the image."
        )
        payload = {"instances": [{"prompt": image_prompt}], "parameters": {"sampleCount": 1}}
        try:
            res = requests.post(url, json=payload, timeout=120)
            if res.status_code == 200: return res.json()['predictions'][0]['bytesBase64Encoded']
        except: pass
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
        files = {'file': (f"nps_senior_{int(time.time())}.jpg", raw_data, "image/jpeg")}
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", headers=self.headers, files=files, timeout=60)
        return res.json().get('id') if res.status_code == 201 else None

    def clean_content(self, content):
        """본문 내 중복 및 불필요 마커 제거"""
        if not content: return ""
        content = re.sub(r'//\s*[a-zA-Z가-힣]+', '', content)
        content = content.replace('```html', '').replace('```', '')
        content = re.sub(r'</ul>\s*<!-- /wp:list -->\s*<!-- wp:list -->\s*<ul>', '', content, flags=re.DOTALL)
        
        blocks = re.split(r'(<!-- wp:[^>]+-->)', content)
        seen_fingerprints = set()
        refined_output = []
        for i in range(len(blocks)):
            segment = blocks[i]
            if segment.startswith('<!-- wp:') or segment.startswith('<!-- /wp:'):
                refined_output.append(segment)
                continue
            text_only = re.sub(r'<[^>]+>', '', segment).strip()
            if len(text_only) > 15:
                fingerprint = re.sub(r'[^가-힣]', '', text_only)[:100]
                if fingerprint in seen_fingerprints:
                    if refined_output and refined_output[-1].startswith('<!-- wp:'): refined_output.pop()
                    continue
                seen_fingerprints.add(fingerprint)
            refined_output.append(segment)
            
        final_content = "".join(refined_output).strip()
        final_content = re.sub(r'(([가-힣\s\d,.\(\)]{10,})\s*)\2{2,}', r'\1', final_content)
        return final_content

    def call_gemini(self, prompt, system_instruction):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.7,
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
        except Exception as e:
            print(f"❌ AI 오류: {e}")
        return None

    def generate_post(self):
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 고도화된 URL 보안 모드 가동 ---")
        news = self.search_naver_news()
        
        # 외부/내부 링크 매핑 데이터 생성
        int_links = random.sample(self.internal_link_pool, min(len(self.internal_link_pool), 2))
        
        # AI에게 전달할 '가짜' URL 플레이스홀더 (보안 및 오류 방지용)
        links_mapping = {}
        link_instr_list = []
        
        for i, link in enumerate(self.external_links):
            key = f"PLACEHOLDER_EXT_{i+1}"
            links_mapping[key] = link['url']
            link_instr_list.append(f"- 제목: {link['title']}, URL: {key} (외부)")
            
        for i, link in enumerate(int_links):
            key = f"PLACEHOLDER_INT_{i+1}"
            links_mapping[key] = link['url']
            link_instr_list.append(f"- 제목: {link['title']}, URL: {key} (내부)")
            
        link_instruction = "\n".join(link_instr_list)
        
        system = f"""대한민국 최고의 금융 전문가로서 2026년 시점의 통찰력 있는 전문가 칼럼을 작성하세요.

[⚠️ 중요: 링크 삽입 절대 규칙 - 위반 시 작업 실패]
1. 본문에 다음 4개의 링크를 반드시 포함하세요:
{link_instruction}
2. 링크 태그 작성 시 URL 부분에 제공된 플레이스홀더(예: PLACEHOLDER_EXT_1)를 **수정하지 말고 그대로** 넣으세요.
3. 모든 링크는 반드시 <a href="PLACEHOLDER_..." target="_self">제목</a> 형식을 사용하세요.
4. 버튼 블록이 필요하다면 수식어 없이 제목만 사용하세요.

[⚠️ 필수: 문서 구조 및 가독성]
1. 계층 구조: 반드시 h2, h3, h4 제목 블록을 사용하여 논리적으로 섹션을 나누세요.
2. 문단 길이: 데스크탑과 모바일 모두를 고려하여 한 문단(p 태그)은 4~6문장으로 구성하세요.

[⚠️ 중복 방지 및 제목]
1. 반복 금지: 동일한 문장, 단락, 조언을 절대 반복하지 마세요. (200번 반복 현상 절대 금지)
2. 제목 규칙: 제목 시작 부분에 '2026년'이나 '2월'을 넣지 마세요. 연도는 제목 끝에 배치하세요.

[본문 구성]
- 3,000자 이상의 압도적인 정보량과 상세한 FAQ를 포함하세요."""

        post_data = self.call_gemini(f"참고 뉴스 데이터:\n{news}\n\n위 데이터를 활용해 링크가 플레이스홀더로 완벽히 배치된 전문가 칼럼을 작성해줘.", system)
        
        if not post_data or not post_data.get('content'):
            print("❌ 생성 실패")
            return

        # [핵심 단계] 플레이스홀더를 실제 원본 URL로 안전하게 치환 (AI의 개입 차단)
        final_content = post_data['content']
        for placeholder, real_url in links_mapping.items():
            final_content = final_content.replace(placeholder, real_url)
            
        post_data['content'] = final_content

        # 본문 물리적 정제 (중복 제거 등)
        post_data['content'] = self.clean_content(post_data['content'])
        
        img_id = self.upload_media(self.generate_image(post_data['title'], post_data['excerpt']))
        tag_ids = self.get_or_create_tag_ids(post_data.get('tags', ''))

        payload = {
            "title": post_data['title'],
            "content": post_data['content'],
            "excerpt": post_data['excerpt'],
            "status": "publish",
            "featured_media": img_id if img_id else 0,
            "tags": tag_ids
        }
        
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers={"Authorization": f"Basic {self.auth}", "Content-Type": "application/json"}, json=payload, timeout=60)
        if res.status_code == 201:
            print(f"🎉 성공: {post_data['title']}")
        else:
            print(f"❌ 실패: {res.text}")

if __name__ == "__main__":
    WordPressAutoPoster().generate_post()
