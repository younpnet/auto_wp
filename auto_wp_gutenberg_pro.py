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
        
        # 1. 링크 데이터 수집
        self.ext_links = self.load_external_links(2)
        self.int_links = self.fetch_internal_links(2)
        
        # 2. 링크 마커 맵
        self.link_map = {}
        self._setup_link_markers()

    def fetch_internal_links(self, count=2):
        url = f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts"
        params = {"per_page": 12, "status": "publish", "_fields": "title,link"}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=20)
            if res.status_code == 200:
                posts = res.json()
                sampled = random.sample(posts, min(len(posts), count))
                return [{"title": re.sub('<.*?>', '', p['title']['rendered']).strip(), "url": p['link'].strip()} for p in sampled]
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

    def _setup_link_markers(self):
        for i, link in enumerate(self.int_links):
            self.link_map[f"[[내부참고_{i}]]"] = link
        for i, link in enumerate(self.ext_links):
            self.link_map[f"[[외부추천_{i}]]"] = link

    def inject_smart_links(self, content):
        """본문의 마커를 분석하여 문맥에 맞게 앵커 또는 버튼으로 치환합니다."""
        for marker, info in self.link_map.items():
            url = info['url']
            title = info['title']
            
            # 워드프레스 버튼 블록 (광고/추천 스타일)
            button_html = (
                f'\n<!-- wp:buttons {{"layout":{{"type":"flex","justifyContent":"center"}}}} -->\n'
                f'<div class="wp-block-buttons"><!-- wp:button -->\n'
                f'<div class="wp-block-button"><a class="wp-block-button__link" href="{url}" target="_self">{title}</a></div>\n'
                f'<!-- /wp:button --></div>\n<!-- /wp:buttons -->\n'
            )
            
            # 문장 내 앵커 태그
            anchor_html = f'<a href="{url}" target="_self"><strong>{title}</strong></a>'
            
            # 마커가 단독 문단으로 존재하는지 확인 (구텐베르크 태그 포함 유연하게 매칭)
            standalone_regex = rf'(?:<!-- wp:paragraph -->\s*)?<p>\s*{re.escape(marker)}\s*</p>(?:\s*<!-- /wp:paragraph -->)?'
            
            if re.search(standalone_regex, content):
                # 단독 줄에 마커가 있다면 버튼으로 치환
                content = re.sub(standalone_regex, button_html, content)
            else:
                # 문장 내부에 섞여 있다면 앵커 태그로 치환
                content = content.replace(marker, anchor_html)
                
        return content

    def clean_structure(self, content):
        if not content: return ""
        content = re.sub(r'//\s*[a-zA-Z가-힣]+', '', content)
        content = content.replace('```html', '').replace('```', '')
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
                fingerprint = re.sub(r'[^가-힣]', '', text_only)[:80]
                if fingerprint in seen_fingerprints:
                    if refined_output and refined_output[-1].startswith('<!-- wp:'): refined_output.pop()
                    continue
                seen_fingerprints.add(fingerprint)
            refined_output.append(segment)
        final_content = "".join(refined_output).strip()
        final_content = re.sub(r'(([가-힣\s\d,.\(\)]{15,})\s*)\2{2,}', r'\1', final_content)
        return final_content

    def generate_image(self, title, excerpt):
        """본문 내용과 맥락에 맞춰 다양한 구도와 인물의 이미지를 생성합니다."""
        print(f"🎨 이미지 다변화 생성 중: {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        
        scenarios = [
            f"A warm, professional consultation scene: A South Korean financial advisor in a clean suit is explaining documents to an attentive elderly couple in a bright, modern office.",
            f"A content middle-aged South Korean man in his 50s, smiling confidently while looking at a tablet showing a retirement plan, sitting in a stylish Korean cafe.",
            f"Close-up of South Korean senior's hands holding a financial report and a pair of glasses, with a soft-focus background of a sun-drenched modern living room.",
            f"A middle-aged South Korean woman looking relaxed and happy, sitting in a bright home office, signifying financial freedom and security.",
            f"An elderly South Korean couple in their 70s walking together in a beautiful park with a peaceful expression, symbolizing a secure retirement life."
        ]
        
        selected_scenario = random.choice(scenarios)
        image_prompt = (
            f"High-end editorial photography for a finance blog. "
            f"Concept: {selected_scenario} Article context: {title}. "
            f"Visual Style: Photorealistic, cinematic warm lighting, high quality, 16:9 aspect ratio. "
            f"CRITICAL: NO TEXT, NO WORDS, NO NUMBERS in the image."
        )
        
        payload = {"instances": [{"prompt": image_prompt}], "parameters": {"sampleCount": 1}}
        try:
            res = requests.post(url, json=payload, timeout=120)
            if res.status_code == 200: return res.json()['predictions'][0]['bytesBase64Encoded']
        except: pass
        return None

    def call_gemini(self, news):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        marker_desc = ""
        for k, v in self.link_map.items():
            marker_desc += f"- {k} (제목: {v['title']})\n"
            
        system_instruction = f"""당신은 대한민국 최고의 금융 자산관리 전문가입니다. 2026년 시점의 통찰력 있는 전문가 칼럼을 작성하세요.

[⚠️ 링크 마커 배치 전략 - 필수 규칙]
1. 본문에 URL이나 <a> 태그를 직접 작성하지 말고 아래 제공된 마커들을 반드시 포함하세요:
{marker_desc}
2. 배치 기준:
   - **문맥과 관련이 깊은 경우**: 문장 속에 마커를 단어처럼 넣으세요. (예: ...을 위해 [[외부추천_0]] 내용을 확인하세요.) -> 텍스트 링크로 변환됩니다.
   - **내용과 직접 관련은 없지만 유익한 정보인 경우**: 단락과 단락 사이, 혹은 특정 섹션 끝에 마커만 한 줄로 따로 적으세요. (예: <p>[[외부추천_1]]</p>) -> 버튼으로 변환됩니다.

[⚠️ 필수: 문서 구조]
1. 모든 섹션은 구텐베르크 h2, h3 제목 블록으로 시작하세요.
2. 문단 가독성: 한 문단(p 태그)은 4~6문장으로 풍부하게 구성하여 데스크탑/모바일 가독성을 모두 잡으세요.
3. 중복 방지: 동일한 수치나 정보를 반복하지 마세요."""

        payload = {
            "contents": [{"parts": [{"text": f"뉴스 데이터:\n{news}\n\n위 데이터를 기반으로 마커가 전략적으로 배치된 전문가 칼럼을 작성해줘."}]}],
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
            if res.status_code == 200: return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
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

    def get_or_create_tags(self, tags_str):
        if not tags_str: return []
        tag_ids = []
        for name in [t.strip() for t in tags_str.split(',')]:
            try:
                res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/tags", headers=self.headers, json={"name": name})
                if res.status_code in [200, 201]: tag_ids.append(res.json()['id'])
                else:
                    search = requests.get(f"{CONFIG['WP_URL']}/wp-json/wp/v2/tags?search={name}", headers=self.headers)
                    if search.json(): tag_ids.append(search.json()[0]['id'])
            except: continue
        return tag_ids

    def run(self):
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 지능형 링크 배치 및 이미지 다변화 실행 ---")
        news = self.search_naver_news()
        post_data = self.call_gemini(news)
        if not post_data: return
        
        # 1. 본문 정제 및 마커 주입 (문맥 판별 치환)
        content = self.clean_structure(post_data['content'])
        content = self.inject_smart_links(content)
        
        # 2. 미디어 및 메타데이터 처리
        img_id = self.upload_media(self.generate_image(post_data['title'], post_data['excerpt']))
        tag_ids = self.get_or_create_tags(post_data.get('tags', ''))
        
        payload = {
            "title": post_data['title'],
            "content": content,
            "excerpt": post_data['excerpt'],
            "status": "publish",
            "featured_media": img_id if img_id else 0,
            "tags": tag_ids
        }
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers={"Authorization": f"Basic {self.auth}", "Content-Type": "application/json"}, json=payload, timeout=60)
        if res.status_code == 201: print(f"🎉 발행 성공: {post_data['title']}")
        else: print(f"❌ 실패: {res.text}")

    def search_naver_news(self):
        queries = ["국민연금 개혁 전략", "2026 노후 설계", "기초연금 변화"]
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {"X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]}
        params = {"query": random.choice(queries), "display": 10, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}" for i in res.json().get('items', [])])
        except: pass
        return "국민연금 최신 동향"

if __name__ == "__main__":
    WordPressAutoPoster().run()
