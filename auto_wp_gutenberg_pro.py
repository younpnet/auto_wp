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
        self.internal_link_pool = self.fetch_internal_link_pool(10)
        # 중복 방지용 제목 리스트
        self.recent_titles = [post['title'] for post in self.internal_link_pool]

    def fetch_internal_link_pool(self, count=10):
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
        """links.json에서 지정된 개수만큼 무작위 외부 링크를 가져옵니다."""
        try:
            if os.path.exists('links.json'):
                with open('links.json', 'r', encoding='utf-8') as f:
                    links = json.load(f)
                    if len(links) >= count:
                        return random.sample(links, count)
                    return links
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
        queries = ["국민연금 수령액 증대 전략", "2026 연금 개혁 변화", "노후 자산 보호 팁", "유족연금 승계 조건"]
        query = random.choice(queries)
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {"X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]}
        params = {"query": query, "display": 12, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in res.json().get('items', [])])
        except: return "국민연금 최신 트렌드 및 노후 설계 가이드"
        return ""

    def generate_image(self, title, excerpt):
        print(f"🎨 이미지 생성 중 (노년 테마): {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        image_prompt = (
            f"A professional lifestyle photography for a Korean finance blog. "
            f"Subject: A happy South Korean elderly couple in their 70s with a warm smile, "
            f"in a bright modern Korean home, looking at financial plans. "
            f"Photorealistic, cinematic lighting, 16:9, NO TEXT."
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
        """본문 내 구텐베르크 구조를 보존하며 중복 내용 및 AI 불순물 제거 (강력한 중복 필터링 추가)"""
        if not content: return ""
        
        # 1. AI 가짜 주석 제거 (//paragraph 등)
        content = re.sub(r'//[a-zA-Z가-힣]+', '', content)
        # 2. 반복되는 마크다운 기호 및 비정상적인 코드 블록 제거
        content = content.replace('```html', '').replace('```', '')
        # 3. 리스트 블록 병합
        content = re.sub(r'</ul>\s*<!-- /wp:list -->\s*<!-- wp:list -->\s*<ul>', '', content, flags=re.DOTALL)
        
        # 4. 블록 단위 중복 제거 및 무한 루프 텍스트 방어
        blocks = re.split(r'(<!-- wp:[^>]+-->)', content)
        seen_fingerprints = set()
        refined_output = []
        
        for i in range(len(blocks)):
            segment = blocks[i]
            if segment.startswith('<!-- wp:') or segment.startswith('<!-- /wp:'):
                refined_output.append(segment)
                continue
            
            # 텍스트 내용 추출 (HTML 태그 제거)
            text_only = re.sub(r'<[^>]+>', '', segment).strip()
            if len(text_only) > 30:
                # 텍스트의 앞부분 지문을 사용하여 중복 여부 판단 (한글만 추출하여 비교)
                fingerprint = re.sub(r'[^가-힣]', '', text_only)[:80]
                
                # 지문이 이미 존재하거나, 같은 내용이 수백 번 반복되는 것을 막기 위해
                # 현재 블록 내에서 너무 많은 동일 구절이 있는지 검사 (자체 루프 방어)
                if fingerprint in seen_fingerprints:
                    # 중복된 내용이 발견되면, 이전에 추가된 직전 블록 마커도 제거
                    if refined_output and refined_output[-1].startswith('<!-- wp:'):
                        refined_output.pop()
                    continue
                seen_fingerprints.add(fingerprint)
            
            refined_output.append(segment)
            
        final_content = "".join(refined_output).strip()
        
        # 5. 최종 텍스트에서 동일한 문장이 연속적으로 3번 이상 나타나는 패턴 제거 (정규표현식)
        # 10자 이상의 한글 문장 패턴이 반복되는 경우 하나만 남김
        final_content = re.sub(r'(([가-힣\s\d,.\(\)]{10,})\s*)\2{2,}', r'\1', final_content)
        
        return final_content

    def call_gemini(self, prompt, system_instruction):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.7, # 창의성보다는 일관성을 위해 0.7로 하향 조정
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
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 중복 방지 전문가 칼럼 생성 ---")
        news = self.search_naver_news()
        
        # 외부 링크 지침 (2개)
        ext_link_instr = "본문 중간에 아래 2개의 외부 링크를 <a> 태그로 자연스럽게 분산 배치하세요 (target='_self' 필수):\n"
        for link in self.external_links:
            ext_link_instr += f"- {link['title']}: {link['url']}\n"
            
        # 내부 링크 지침 (2개 선택)
        int_links = random.sample(self.internal_link_pool, min(len(self.internal_link_pool), 2))
        int_link_instr = "또한, 아래의 내부 링크 2개를 글의 맥락에 맞게 삽입하세요:\n"
        for link in int_links:
            int_link_instr += f"- {link['title']}: {link['url']}\n"
        
        system = f"""대한민국 최고의 금융 자산관리 전문가로서 2026년 시점의 통찰력 있는 칼럼을 작성하세요.

[⚠️ 중요: 절대 중복 금지 규칙]
- 동일한 문장이나 단락을 복사하여 분량을 채우지 마세요. 반복 발견 시 검색 엔진 최적화 점수가 하락합니다.
- 각 섹션(서론, 본론 1~6, FAQ, 결론)은 반드시 '서로 다른' 구체적인 정보와 시각을 담아야 합니다.
- 3,000자 이상을 작성하되, '내용의 다양성'을 최우선으로 하세요. 

[필수: 링크 삽입 규칙]
1. 외부 링크: {ext_link_instr}
2. 내부 링크: {int_link_instr}
3. 모든 링크는 <a> 태그를 사용하며 target="_self" 속성을 포함하세요.

[필수: 모바일 가독성 및 태그 규칙]
1. 모든 본론 텍스트는 반드시 <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph --> 블록으로 감싸야 합니다.
2. 문단 최적화: 모바일 가독성을 위해 한 문단(p 태그 하나)은 최대 2문장을 넘지 않게 짧게 끊으세요.
3. 소제목: <!-- wp:heading {{"level":2}} --><h2>...</h2><!-- /wp:heading --> 형식을 사용하며 최소 6개 이상의 H2 섹션을 구성하세요.
4. 중복 방지: 이미 발행된 주제들({self.recent_titles})과 차별화된 새로운 시각을 제시하세요.

[제목 및 구성]
- 제목 끝에 (2026년 최신 가이드) 등의 문구를 추가하세요.
- FAQ: 4개 이상의 상세한 전문가 응답 FAQ 섹션을 포함하세요."""

        post_data = self.call_gemini(f"참고 뉴스:\n{news}\n\n위 데이터를 활용해 중복 없는 풍성한 전문가 칼럼을 작성해줘.", system)
        
        if not post_data or not post_data.get('content'):
            print("❌ 생성 실패")
            return

        # 본문 정제 (내용 중복 및 무한 루프 텍스트 필터링)
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
