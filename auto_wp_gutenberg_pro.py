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
        """본문 내 중복 내용 및 무한 반복을 물리적으로 제거하는 고도화된 클리닝"""
        if not content: return ""
        
        # 1. AI 주석 제거
        content = re.sub(r'//[a-zA-Z가-힣]+', '', content)
        content = content.replace('```html', '').replace('```', '')

        # 2. 리스트 블록 병합
        content = re.sub(r'</ul>\s*<!-- /wp:list -->\s*<!-- wp:list -->\s*<ul>', '', content, flags=re.DOTALL)
        
        # 3. 블록 단위 지문 대조 (중복 문단 100% 차단)
        blocks = re.split(r'(<!-- wp:[^>]+-->)', content)
        seen_fingerprints = set()
        refined_output = []
        
        for i in range(len(blocks)):
            segment = blocks[i]
            if segment.startswith('<!-- wp:') or segment.startswith('<!-- /wp:'):
                refined_output.append(segment)
                continue
            
            # 텍스트에서 한글만 추출하여 지문 생성 (의미적 중복 체크)
            text_only = re.sub(r'<[^>]+>', '', segment).strip()
            if len(text_only) > 20:
                fingerprint = re.sub(r'[^가-힣]', '', text_only)[:60]
                if fingerprint in seen_fingerprints:
                    # 중복 블록이면 직전 마커까지 제거
                    if refined_output and refined_output[-1].startswith('<!-- wp:'):
                        refined_output.pop()
                    continue
                seen_fingerprints.add(fingerprint)
            refined_output.append(segment)
            
        final_content = "".join(refined_output).strip()
        
        # 4. 동일 문장 패턴 반복 제거 (강력한 문장 수준 클리닝)
        final_content = re.sub(r'(([가-힣\s\d,.\(\)]{10,})\s*)\2{2,}', r'\1', final_content)
        
        return final_content

    def call_gemini(self, prompt, system_instruction):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.75,
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
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 맞춤형 링크 및 문단 고도화 생성 시작 ---")
        news = self.search_naver_news()
        
        # 외부 링크 지침 고도화 (관련성 기반 배치)
        ext_link_instr = "[외부 링크 정보]\n"
        for link in self.external_links:
            ext_link_instr += f"- 제목: {link['title']}, URL: {link['url']}\n"
            
        ext_link_instr += "\n[외부 링크 배치 규칙 (필수)]\n"
        ext_link_instr += "1. 내용 관련성 판단: 링크의 제목이나 목적이 현재 작성 중인 단락의 내용과 직접적인 관련이 있다면 문장 내부에 <a> 태그(앵커 텍스트)로 자연스럽게 삽입하세요.\n"
        ext_link_instr += "2. 버튼 블록 사용: 만약 링크가 본문 내용과 맥락상 직접적인 연관이 적다면, 단락 사이에 '외부 광고'나 '추천 정보' 느낌이 나도록 아래의 구텐베르크 버튼 블록 형식을 사용하여 독립적으로 배치하세요.\n"
        ext_link_instr += "   버튼 블록 예시: <!-- wp:buttons {\"layout\":{\"type\":\"flex\",\"justifyContent\":\"center\"}} --><div class=\"wp-block-buttons\"><!-- wp:button --><div class=\"wp-block-button\"><a class=\"wp-block-button__link\" href=\"URL\" target=\"_self\">제목</a></div><!-- /wp:button --></div><!-- /wp:buttons -->\n"
            
        # 내부 링크 지침 (2개)
        int_links = random.sample(self.internal_link_pool, min(len(self.internal_link_pool), 2))
        int_link_instr = "[내부 링크 정보]\n"
        for link in int_links:
            int_link_instr += f"- 제목: {link['title']}, URL: {link['url']}\n"
        int_link_instr += "규칙: 위 내부 링크 2개를 글의 맥락에 맞게 삽입하여 독자의 체류 시간을 높이세요.\n"
        
        system = f"""당신은 대한민국 최고의 금융 자산관리 전문가입니다. 2026년 시점의 통찰력 있는 전문가 칼럼을 작성하세요.

[⚠️ 절대 엄수: 중복 방지 및 문단 구조]
1. 반복 금지: 동일한 문장, 수치, 조언을 절대 중복하여 사용하지 마세요. (반복 발견 시 품질 점수 하락)
2. 문단 가독성: 데스크탑과 모바일 모두를 고려하여, 한 문단(p 태그 하나)은 4~6문장 내외의 논리적 덩어리로 구성하세요. 너무 짧은 한 문장 위주의 나열을 지양하되, 너무 길어지지 않게 주의하세요.
3. 정보 밀도: 3,000자 이상을 채우기 위해 같은 말을 되풀이하지 말고, 매 섹션마다 '새로운 데이터'와 '실전 전략'을 추가하세요.

[필수 구성 및 링크]
1. 외부 링크 적용: {ext_link_instr}
2. 내부 링크 적용: {int_link_instr}
3. 구조: 반드시 <!-- wp:paragraph --><p>...</p><!-- /wp:paragraph --> 마커를 사용하고 h2 소제목을 6개 이상 만드세요.
4. 중복 방지: 이미 다룬 주제들({self.recent_titles})과 다른 독창적인 정보를 다루세요.
5. 모든 링크는 target="_self" 속성을 포함하세요.

[제목 및 구성]
- 제목 끝에 (2026년 업데이트) 등의 문구를 자연스럽게 추가하세요.
- FAQ 섹션은 4개 이상의 독립적인 질문과 답변으로 구성하세요."""

        post_data = self.call_gemini(f"참고 뉴스 데이터:\n{news}\n\n위 데이터를 활용해 중복 없는 풍성하고 링크가 완벽히 배치된 전문가 칼럼을 작성해줘.", system)
        
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
