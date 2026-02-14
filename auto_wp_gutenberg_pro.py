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
        """내부 링크로 사용할 최근 발행글의 제목과 URL을 가져옵니다."""
        url = f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title,link"}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=20)
            if res.status_code == 200:
                return [{"title": re.sub('<.*?>', '', post['title']['rendered']).strip(), "url": post['link']} for post in res.json()]
        except: pass
        return []

    def load_external_links(self, count=2):
        """links.json에서 무작위 외부 링크를 가져옵니다."""
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
        queries = ["국민연금 수령액 늘리는 법", "2026 국민연금 개정안", "노후 준비 유망 자산", "기초연금 소득인정액 변화"]
        query = random.choice(queries)
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {"X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]}
        params = {"query": query, "display": 12, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in res.json().get('items', [])])
        except: return "국민연금 최신 동향 및 전문가 제언"
        return ""

    def generate_image(self, title, excerpt):
        print(f"🎨 이미지 생성 중 (노년 테마): {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        image_prompt = (
            f"A high-end cinematic lifestyle photography for a Korean finance blog. "
            f"Subject: A content South Korean elderly couple in their 70s, looking happy and secure "
            f"in a sun-filled, modern home. Photorealistic, soft focus background, 16:9, NO TEXT."
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
        files = {'file': (f"nps_pro_{int(time.time())}.jpg", raw_data, "image/jpeg")}
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", headers=self.headers, files=files, timeout=60)
        return res.json().get('id') if res.status_code == 201 else None

    def clean_content(self, content):
        """본문 내 중복 내용 및 AI 불순물을 완벽하게 제거하며 구조를 유지"""
        if not content: return ""
        
        # 1. AI 주석 및 가짜 마커 제거 (//paragraph 등)
        content = re.sub(r'//\s*[a-zA-Z가-힣]+', '', content)
        content = content.replace('```html', '').replace('```', '')

        # 2. 리스트 블록 병합
        content = re.sub(r'</ul>\s*<!-- /wp:list -->\s*<!-- wp:list -->\s*<ul>', '', content, flags=re.DOTALL)
        
        # 3. 블록 단위 지문 대조 (중복 문단 차단)
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
                    if refined_output and refined_output[-1].startswith('<!-- wp:'):
                        refined_output.pop()
                    continue
                seen_fingerprints.add(fingerprint)
            refined_output.append(segment)
            
        temp_content = "".join(refined_output).strip()
        
        # 4. 동일 문장 패턴 반복 제거
        sentences = re.split(r'(?<=[.!?])\s+', temp_content)
        unique_sentences = []
        sentence_set = set()
        
        for s in sentences:
            s_clean = re.sub(r'[^가-힣]', '', s).strip()
            if len(s_clean) > 20:
                if s_clean in sentence_set:
                    continue
                sentence_set.add(s_clean)
            unique_sentences.append(s)
            
        final_content = " ".join(unique_sentences)
        
        # 5. 연속된 동일 구절 물리적 제거
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
                text_content = res.json()['candidates'][0]['content']['parts'][0]['text']
                return json.loads(text_content)
        except Exception as e:
            print(f"❌ AI 오류: {e}")
        return None

    def generate_post(self):
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 구조화 및 링크 최적화 생성 시작 ---")
        news = self.search_naver_news()
        
        # 외부 링크 지침 (추천 문구 배제)
        ext_link_instr = "[외부 링크 정보]\n"
        for link in self.external_links:
            ext_link_instr += f"- 제목: {link['title']}, URL: {link['url']}\n"
            
        # 내부 링크 지침
        int_links = random.sample(self.internal_link_pool, min(len(self.internal_link_pool), 2))
        int_link_instr = "[내부 링크 정보]\n"
        for link in int_links:
            int_link_instr += f"- 제목: {link['title']}, URL: {link['url']}\n"
        
        system = f"""당신은 대한민국 최고의 금융 자산관리 전문가입니다. 2026년 시점의 통찰력 있는 전문가 칼럼을 작성하세요.

[⚠️ 필수: 문서 구조화 및 제목 블록 사용]
1. 본문은 반드시 논리적 계층에 따라 제목 블록을 사용해야 합니다.
   - 대주제: <!-- wp:heading {{"level":2}} --><h2>...</h2><!-- /wp:heading -->
   - 소주제: <!-- wp:heading {{"level":3}} --><h3>...</h3><!-- /wp:heading -->
   - 세부항목: <!-- wp:heading {{"level":4}} --><h4>...</h4><!-- /wp:heading -->
2. 모든 섹션의 시작은 위 제목 블록으로 시작하세요. 타이틀이 빠지지 않도록 주의하세요.

[필수: 링크 및 버튼 규칙]
1. 외부 링크(2개): {ext_link_instr}
   - [중요] 버튼 블록 사용 시 버튼 텍스트에 '추천링크', '광고', '클릭' 등의 부가적인 수식어를 절대 넣지 마세요. 오직 링크의 '제목'만 텍스트로 사용하세요.
   - 버튼 블록 형식: <!-- wp:buttons {{"layout":{{"type":"flex","justifyContent":"center"}}}} --><div class="wp-block-buttons"><!-- wp:button --><div class="wp-block-button"><a class="wp-block-button__link" href="URL" target="_self">제목</a></div><!-- /wp:button --></div><!-- /wp:buttons -->
2. 내부 링크(2개): {int_link_instr}을 본문 맥락에 맞게 자연스럽게 배치하세요.
3. 모든 링크는 target="_self" 속성을 포함하세요.

[⚠️ 절대 엄수: 중복 및 마커 금지]
1. 반복 금지: 동일한 문장, 단락, 조언을 절대 반복하지 마세요. 
2. 마커 금지: 본문에 //paragraph, //heading 등 어떠한 슬래시(/) 기반 주석도 넣지 마세요.
3. 가독성: 한 문단(p 태그)은 4~6문장의 적절한 길이로 구성하세요.

[제목 및 구성]
- 제목 끝에 (2026년 최신판) 등 신뢰도 높은 문구를 추가하세요.
- 3,000자 이상의 풍부한 정보량을 확보하세요."""

        post_data = self.call_gemini(f"참고 뉴스 데이터:\n{news}\n\n위 데이터를 활용해 제목(H2, H3, H4)이 명확히 구분되고 링크가 깔끔하게 배치된 전문가 칼럼을 작성해줘.", system)
        
        if not post_data or not post_data.get('content'):
            print("❌ 생성 실패")
            return

        # 본문 물리적 정제
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
