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
        
        # 1. 외부 링크 2개 로드
        self.external_links = self.load_external_links(2)
        # 2. 내부 링크 2개용 최근 발행글 데이터 로드 (사이트맵 대신 API가 제목 정보를 포함하고 있어 AI에게 더 유리함)
        self.internal_link_pool = self.fetch_internal_link_pool(15)
        # 3. 중복 방지용 제목 리스트
        self.recent_titles = [post['title'] for post in self.internal_link_pool]

    def fetch_internal_link_pool(self, count=15):
        """REST API를 사용하면 제목과 URL을 동시에 가져와서 AI가 맥락에 맞게 링크를 배치할 수 있습니다."""
        url = f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title,link"}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=20)
            if res.status_code == 200:
                # URL의 무결성을 위해 앞뒤 공백 및 중복 슬래시 제거
                return [{"title": re.sub('<.*?>', '', post['title']['rendered']).strip(), "url": post['link'].strip()} for post in res.json()]
        except: pass
        return []

    def load_external_links(self, count=2):
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
        queries = ["국민연금 수령액 늘리는 비결", "2026 국민연금 개편안 핵심", "노후 자산관리 실전 가이드"]
        query = random.choice(queries)
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {"X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]}
        params = {"query": query, "display": 12, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in res.json().get('items', [])])
        except: return "국민연금 최신 이슈 및 노후 준비 전략"
        return ""

    def generate_image(self, title, excerpt):
        print(f"🎨 이미지 생성 중 (노년 타겟팅): {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        image_prompt = (
            f"A professional lifestyle photography for a Korean finance blog. "
            f"Subject: A happy South Korean elderly couple in their late 70s, "
            f"smiling warmly in a bright, high-end modern Korean home. "
            f"Style: Photorealistic, cinematic lighting, 16:9, NO TEXT."
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
        """본문 내 중복, 불필요 마커 및 깨진 URL 패턴 사후 교정"""
        if not content: return ""
        
        # 1. AI 주석 제거
        content = re.sub(r'//\s*[a-zA-Z가-힣]+', '', content)
        content = content.replace('```html', '').replace('```', '')
        
        # 2. 하이퍼링크 내 도메인 중복 강제 교정 (혹시 모를 AI의 임의 수정을 대비한 안전장치)
        def repair_links(match):
            url = match.group(1)
            # URL 내부에 프로토콜(http)이 다시 등장하는 비정상 패턴 감지
            find_all_http = re.findall(r'https?://[^\s"<>]+', url)
            if len(find_all_http) > 1:
                url = find_all_http[-1] # 가장 마지막 주소(진짜 주소)만 선택
            
            # 도메인 파편(.net/)이 잘못 끼어든 경우 제거
            url = re.sub(r'(https?://[^/]+)/+\.net/+', r'\1/', url)
            url = re.sub(r'([^:])//+', r'\1/', url) # 중복 슬래시 제거
            return f'href="{url}"'

        content = re.sub(r'href="([^"]+)"', repair_links, content)

        # 3. 리스트 블록 병합 및 문장 반복 제거
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
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 플레이스홀더 보안 링크 모드 실행 ---")
        news = self.search_naver_news()
        
        # 외부/내부 링크 매핑 데이터 생성 (AI에겐 토큰만 전달)
        int_links = random.sample(self.internal_link_pool, min(len(self.internal_link_pool), 2))
        links_mapping = {}
        link_instr_list = []
        
        for i, link in enumerate(self.external_links):
            key = f"SAFE_LINK_EXT_{i+1}"
            links_mapping[key] = link['url']
            link_instr_list.append(f"- 제목: {link['title']}, 매칭토큰: {key}")
            
        for i, link in enumerate(int_links):
            key = f"SAFE_LINK_INT_{i+1}"
            links_mapping[key] = link['url']
            link_instr_list.append(f"- 제목: {link['title']}, 매칭토큰: {key}")
            
        link_instruction = "\n".join(link_instr_list)
        
        system = f"""당신은 대한민국 최고의 금융 자산관리 전문가입니다. 2026년 시점의 통찰력 있는 전문가 칼럼을 작성하세요.

[⚠️ 중요: 하이퍼링크 삽입 절대 수칙]
1. 본문에 아래 4개의 링크를 반드시 <a> 태그의 href 값으로 포함하세요:
{link_instruction}
2. **절대 금기**: 매칭토큰(예: SAFE_LINK_INT_1) 앞에 도메인 주소(https://...)를 붙이거나 토큰 문자열을 수정하지 마세요.
   - 나쁜 예: <a href="https://younp.net/SAFE_LINK_INT_1">
   - 좋은 예: <a href="SAFE_LINK_INT_1">
3. 링크 태그 내부에 제공된 '매칭토큰' 문자열만 정확히 입력하세요. 모든 링크는 target="_self" 속성을 포함하세요.

[⚠️ 필수: 문서 구조 및 품질]
1. 계층 구조: h2, h3, h4 제목 블록을 사용하여 논리적으로 섹션을 나누세요.
2. 문단 가독성: 데스크탑과 모바일 모두를 고려하여 한 문단(p 태그)은 4~6문장으로 구성하세요.
3. 중복 방지: 동일 문장, 조언을 반복하지 마세요. (200번 반복 현상 절대 금지)

[본문 구성]
- 제목 맨 앞에 연도를 넣지 마세요.
- 3,000자 이상의 압도적인 정보량과 상세한 FAQ를 포함하세요."""

        post_data = self.call_gemini(f"참고 뉴스 데이터:\n{news}\n\n위 데이터를 활용해 링크가 토큰화되어 안전하게 배치된 전문가 칼럼을 작성해줘.", system)
        
        if not post_data or not post_data.get('content'):
            print("❌ 생성 실패")
            return

        # [핵심] 플레이스홀더를 실제 원본 URL로 안전하게 치환
        final_content = post_data['content']
        for placeholder, real_url in links_mapping.items():
            # AI가 혹시나 앞에 도메인을 붙였을 경우를 대비해 덮어씌움
            final_content = final_content.replace(f"https://younp.net/{placeholder}", placeholder)
            final_content = final_content.replace(placeholder, real_url)
            
        post_data['content'] = final_content

        # 본문 물리적 정제 (치환 후 발생할 수 있는 파편 복구)
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
