import requests
import json
import time
import base64
import re
import os
import io
import random
import uuid
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
        
        # 1. 외부 링크 2개 로드
        self.external_links = self.load_external_links(2)
        # 2. 내부 링크 2개용 최근 발행글 데이터 로드
        self.internal_link_pool = self.fetch_internal_link_pool(15)
        # 3. 중복 방지용 제목 리스트
        self.recent_titles = [post['title'] for post in self.internal_link_pool]

    def fetch_internal_link_pool(self, count=15):
        """내부 링크용 최근 발행글을 가져옵니다. 경로 오류 방지를 위해 URL을 엄격히 정제합니다."""
        url = f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title,link"}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=20)
            if res.status_code == 200:
                posts = []
                for post in res.json():
                    clean_url = post['link'].strip().replace(" ", "")
                    # 비정상적인 중복 슬래시나 파편 제거
                    clean_url = re.sub(r'([^:])//+', r'\1/', clean_url)
                    posts.append({
                        "title": re.sub('<.*?>', '', post['title']['rendered']).strip(),
                        "url": clean_url
                    })
                return posts
        except: pass
        return []

    def load_external_links(self, count=2):
        """links.json에서 무작위 외부 링크를 가져옵니다."""
        try:
            if os.path.exists('links.json'):
                with open('links.json', 'r', encoding='utf-8') as f:
                    links = json.load(f)
                    sampled = random.sample(links, min(len(links), count))
                    for link in sampled:
                        link['url'] = link['url'].strip().replace(" ", "")
                    return sampled
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
        queries = ["국민연금 개혁 전략", "노후 자산관리 실전 비법", "국민연금 수령액 늘리는 방법"]
        query = random.choice(queries)
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {"X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]}
        params = {"query": query, "display": 12, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in res.json().get('items', [])])
        except: return "국민연금 최신 동향 및 전문가 칼럼"
        return ""

    def generate_image(self, title, excerpt):
        print(f"🎨 이미지 생성 중 (노년 테마): {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        image_prompt = (
            f"High-end professional photography for a South Korean finance blog. "
            f"Subject: A happy South Korean elderly couple in their 70s, "
            f"smiling warmly in a bright, modern, and secure home environment. "
            f"Aspect ratio 16:9, Photorealistic, high quality, NO TEXT."
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
        """본문 정제 및 하이퍼링크 무결성 강제 검사 엔진"""
        if not content: return ""
        
        # 1. AI 가짜 주석 및 불필요 마크다운 제거
        content = re.sub(r'//\s*[a-zA-Z가-힣]+', '', content)
        content = content.replace('```html', '').replace('```', '')
        
        # 2. 하이퍼링크 도메인 중복 및 경로 파편 (.net/ 등) 정밀 교정
        # href="https://younp.net/https://younp.net/path" -> href="https://younp.net/path"
        def final_link_repair(match):
            url = match.group(1).strip()
            # 2-1. URL 내부에 프로토콜(http)이 다시 등장하는지 확인 (중복 삽입 방어)
            all_urls = re.findall(r'https?://[^\s"<>]+', url)
            if len(all_urls) > 1:
                url = all_urls[-1] # 가장 마지막에 위치한 완전한 URL만 취함
            
            # 2-2. 도메인 확장자 중복 파편 제거 (예: .net/.net/)
            url = re.sub(r'(https?://[^/]+)/+(\.net|net)/+', r'\1/', url)
            # 2-3. 중복 슬래시 제거
            url = re.sub(r'([^:])//+', r'\1/', url)
            return f'href="{url}"'

        content = re.sub(r'href="([^"]+)"', final_link_repair, content)

        # 3. 리스트 블록 병합 및 문단 중복 제거
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
                fingerprint = re.sub(r'[^가-힣]', '', text_only)[:120]
                if fingerprint in seen_fingerprints:
                    if refined_output and refined_output[-1].startswith('<!-- wp:'): refined_output.pop()
                    continue
                seen_fingerprints.add(fingerprint)
            refined_output.append(segment)
            
        final_content = "".join(refined_output).strip()
        # 동일 문장 무한 반복 패턴 물리적 제거
        final_content = re.sub(r'(([가-힣\s\d,.\(\)]{15,})\s*)\2{2,}', r'\1', final_content)
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
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 고유 아이디 기반 링크 보안 모드 가동 ---")
        news = self.search_naver_news()
        
        # 외부/내부 링크를 위한 완전 격리형 고유 아이디 생성
        int_links = random.sample(self.internal_link_pool, min(len(self.internal_link_pool), 2))
        links_mapping = {}
        link_instr_list = []
        
        # AI가 URL로 인식하지 못하도록 특수한 형태의 아이디 사용
        for i, link in enumerate(self.external_links):
            unique_id = f"ID_EXTERNAL_{uuid.uuid4().hex[:8]}"
            links_mapping[unique_id] = link['url']
            link_instr_list.append(f"- 제목: {link['title']}, 삽입코드: {unique_id}")
            
        for i, link in enumerate(int_links):
            unique_id = f"ID_INTERNAL_{uuid.uuid4().hex[:8]}"
            links_mapping[unique_id] = link['url']
            link_instr_list.append(f"- 제목: {link['title']}, 삽입코드: {unique_id}")
            
        link_instruction = "\n".join(link_instr_list)
        
        system = f"""대한민국 최고의 금융 자산관리 전문가로서 2026년 시점의 통찰력 있는 전문가 칼럼을 작성하세요.

[⚠️ 하이퍼링크 삽입 절대 수칙 - 위반 금지]
1. 본문에 아래 4개의 삽입코드를 <a> 태그의 href 값으로 정확히 포함하세요:
{link_instruction}
2. **절대 금기 사항**:
   - 삽입코드(예: ID_INTERNAL_...) 앞에 어떠한 도메인 주소(https://...)도 붙이지 마세요.
   - 삽입코드를 URL처럼 수정하거나 완성하지 마세요. 오직 제공된 '문자열' 그대로 href="" 속성값에 넣으세요.
3. 모든 링크는 target="_self" 속성을 포함해야 합니다.

[⚠️ 필수: 문서 구조 및 가독성]
1. 계층 구조: 반드시 h2, h3 제목 블록을 사용하여 논리적으로 섹션을 나누세요.
2. 문단 가독성: 데스크탑과 모바일 모두를 고려하여 한 문단(p 태그)은 4~6문장의 적절한 길이로 구성하세요.
3. 중복 방지: 동일한 수치, 조언, 문장을 절대 반복하지 마세요.

[본문 구성]
- 제목 맨 앞에 연도를 넣지 마세요. 연도는 제목 끝에 배치하세요.
- 3,000자 이상의 압도적인 정보량과 실질적인 도움을 주는 조언을 포함하세요."""

        post_data = self.call_gemini(f"참고 데이터:\n{news}\n\n위 데이터를 활용해 링크 코드가 안전하게 격리되어 배치된 고품질 칼럼을 작성해줘.", system)
        
        if not post_data or not post_data.get('content'):
            print("❌ 생성 실패")
            return

        # [핵심 로직] AI가 임의로 붙인 도메인 파편을 치환 전 미리 제거
        final_content = post_data['content']
        for unique_id in links_mapping.keys():
            # <a href="https://younp.net/ID_INTERNAL_..."> -> <a href="ID_INTERNAL_..."> 강제 정규화
            final_content = re.sub(rf'href="https?://[^"]*/?{re.escape(unique_id)}"', f'href="{unique_id}"', final_content)

        # [핵심 로직] 고유 아이디를 실제 원본 URL로 1:1 치환 (무결성 100% 보장)
        for unique_id, real_url in links_mapping.items():
            final_content = final_content.replace(unique_id, real_url)
            
        post_data['content'] = final_content

        # [사후 처리] 최종 본문 물리적 정제 (치환 후 혹시라도 남은 중복 프로토콜 및 .net 파편 최종 교정)
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
