import requests
import json
import time
import base64
import re
import os
import io
import random
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

# 이미지 처리를 위한 PIL 라이브러리 (JPG 변환 및 압축용)
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️ 경고: PIL(Pillow) 라이브러리가 설치되지 않았습니다. 'pip install Pillow'가 필요합니다.")

# ==============================================================================
# 환경 변수 설정
# ==============================================================================
CONFIG = {
    "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
    "WP_URL": os.environ.get("WP_URL", "").rstrip("/"),
    "WP_USERNAME": os.environ.get("WP_USERNAME", "admin"),
    "WP_APP_PASSWORD": os.environ.get("WP_APP_PASSWORD", ""),
    "TEXT_MODEL": "gemini-flash-latest", 
    "IMAGE_MODEL": "imagen-4.0-generate-001",
    "NAVER_CLIENT_ID": os.environ.get("NAVER_CLIENT_ID", ""),
    "NAVER_CLIENT_SECRET": os.environ.get("NAVER_CLIENT_SECRET", ""),
    # 외부 링크 수집용 RSS 리스트 (요청하신 네이버 블로그 피드 추가)
    "RSS_URLS": [
        "https://virz.net/feed",
        "https://121913.tistory.com/rss",
        "https://exciting.tistory.com/rss",
        "https://sleepyourmoney.net/feed",
        "https://rss.blog.naver.com/moviepotal.xml"
    ]
}

class WordPressAutoPoster:
    def __init__(self):
        self._validate_config()
        
        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth = base64.b64encode(user_pass.encode()).decode()
        self.headers = {"Authorization": f"Basic {self.auth}"}
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 멀티 피드 시스템 초기화 및 수집 시작...")
        
        # 1. 외부 사이트 RSS 동기화
        self.sync_multiple_rss_feeds()
        
        # 2. 통합된 링크 데이터 로드
        self.ext_links = self.load_external_links(2)
        self.int_links = self.fetch_internal_links(2)
        
        # 3. 링크 마커 맵 생성
        self.link_map = {}
        self._setup_link_markers()

    def _validate_config(self):
        required_keys = ["WP_URL", "GEMINI_API_KEY", "WP_APP_PASSWORD"]
        for key in required_keys:
            if not CONFIG.get(key):
                print(f"❌ 오류: {key} 환경 변수가 설정되지 않았습니다.")
                sys.exit(1)

    def sync_multiple_rss_feeds(self):
        """설정된 모든 RSS 피드에서 새로운 외부 링크를 수집합니다."""
        print(f"📡 총 {len(CONFIG['RSS_URLS'])}개의 외부 RSS 피드 동기화 중...")
        existing_links = []
        if os.path.exists('links.json'):
            with open('links.json', 'r', encoding='utf-8') as f:
                try: existing_links = json.load(f)
                except: existing_links = []
        
        existing_urls = {link['url'] for link in existing_links}
        total_added = 0

        for rss_url in CONFIG['RSS_URLS']:
            print(f"🔗 수집 대상: {rss_url}")
            try:
                res = requests.get(rss_url, timeout=20)
                if res.status_code != 200:
                    print(f"  ⚠️ 접속 실패 (코드: {res.status_code})")
                    continue
                root = ET.fromstring(res.content)
                feed_added = 0
                
                # 티스토리/워드프레스(item) 및 일반 RSS 구조 대응
                items = root.findall('.//item')
                for item in items:
                    title_elem = item.find('title')
                    link_elem = item.find('link')
                    if title_elem is not None and link_elem is not None:
                        title = title_elem.text.strip()
                        link = link_elem.text.strip()
                        if link not in existing_urls:
                            existing_links.append({"title": title, "url": link})
                            existing_urls.add(link)
                            feed_added += 1
                            total_added += 1
                if feed_added > 0:
                    print(f"  ✅ {feed_added}개의 새로운 링크를 발견했습니다.")
            except Exception as e:
                print(f"  ⚠️ 처리 중 오류: {e}")

        if total_added > 0:
            with open('links.json', 'w', encoding='utf-8') as f:
                json.dump(existing_links, f, ensure_ascii=False, indent=4)
            print(f"🎉 동기화 완료: 총 {total_added}개의 링크가 links.json에 추가되었습니다.")

    def fetch_internal_links(self, count=2):
        url = f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts"
        params = {"per_page": 15, "status": "publish", "_fields": "title,link"}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=20)
            if res.status_code == 200:
                posts = res.json()
                sampled = random.sample(posts, min(len(posts), count))
                return [{"title": re.sub('<.*?>', '', p['title']['rendered']).strip(), "url": p['link'].strip()} for p in sampled]
        except Exception as e:
            print(f"⚠️ 내부 링크 호출 실패: {e}")
        return []

    def load_external_links(self, count=2):
        try:
            if os.path.exists('links.json'):
                with open('links.json', 'r', encoding='utf-8') as f:
                    links = json.load(f)
                    if not links: return []
                    return random.sample(links, min(len(links), count))
        except: pass
        return []

    def _setup_link_markers(self):
        for i, link in enumerate(self.int_links):
            self.link_map[f"[[내부참고_{i}]]"] = link
        for i, link in enumerate(self.ext_links):
            self.link_map[f"[[외부추천_{i}]]"] = link

    def inject_smart_links(self, content):
        """마커를 분석하여 앵커 또는 버튼으로 정밀 치환 (내부/외부 통합 관리)"""
        for marker, info in self.link_map.items():
            url = info['url']
            title = info['title']
            
            button_html = (
                f'\n<!-- wp:buttons {{"layout":{{"type":"flex","justifyContent":"center"}}}} -->\n'
                f'<div class="wp-block-buttons"><!-- wp:button {{"backgroundColor":"vivid-cyan-blue","borderRadius":5}} -->\n'
                f'<div class="wp-block-button"><a class="wp-block-button__link has-vivid-cyan-blue-background-color has-background wp-element-button" href="{url}" target="_self">{title}</a></div>\n'
                f'<!-- /wp:button --></div>\n<!-- /wp:buttons -->\n'
            )
            anchor_html = f'<a href="{url}" target="_self"><strong>{title}</strong></a>'
            standalone_regex = rf'<!-- wp:paragraph -->\s*<p>\s*{re.escape(marker)}\s*</p>\s*<!-- /wp:paragraph -->'
            
            if re.search(standalone_regex, content):
                content = re.sub(standalone_regex, button_html, content)
            else:
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
        return "".join(refined_output).strip()

    def generate_image(self, title, excerpt):
        """본문 내용과 맥락에 맞춰 한국인 인물 및 배경 이미지를 생성합니다."""
        print(f"🎨 이미지 다변화 생성 중 (한국인 피사체 강조)...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        
        scenarios = [
            f"A professional South Korean financial advisor explaining pension documents to a middle-aged South Korean couple in a sunlit modern Seoul office.",
            f"A confident South Korean man in his 50s smiling while reviewing retirement plans on a tablet in a modern Korean cafe.",
            f"Close-up of a South Korean senior's hands holding a detailed South Korean National Pension report and glasses.",
            f"A happy elderly South Korean couple in their 70s walking together in a beautiful scenic Korean park during autumn."
        ]
        
        selected_scenario = random.choice(scenarios)
        image_prompt = (
            f"High-end editorial photography for a finance column. "
            f"Concept: {selected_scenario} Context: {title}. "
            f"Visual Style: Photorealistic, cinematic lighting, 16:9 aspect ratio. "
            f"CRITICAL: NO TEXT, NO LETTERS, NO WORDS in the image."
        )
        
        payload = {"instances": [{"prompt": image_prompt}], "parameters": {"sampleCount": 1}}
        try:
            res = requests.post(url, json=payload, timeout=120)
            if res.status_code == 200: return res.json()['predictions'][0]['bytesBase64Encoded']
        except: pass
        return None

    def process_and_upload_image(self, b64_data, title):
        """이미지를 JPG 70% 품질로 변환 및 최적화하여 업로드합니다."""
        if not b64_data: return None
        
        print("📤 이미지 JPG 변환 및 최적화 업로드 중...")
        raw_data = base64.b64decode(b64_data)
        
        if PIL_AVAILABLE:
            try:
                img = Image.open(io.BytesIO(raw_data))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                output = io.BytesIO()
                img.save(output, format="JPEG", quality=70, optimize=True)
                final_data = output.getvalue()
                print("✅ JPG 70% 압축 완료")
            except Exception as e:
                print(f"⚠️ 이미지 최적화 실패: {e}")
                final_data = raw_data
        else:
            final_data = raw_data

        files = {'file': (f"nps_pro_{int(time.time())}.jpg", final_data, "image/jpeg")}
        media_res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", headers=self.headers, files=files, timeout=60)
        
        if media_res.status_code == 201:
            return media_res.json().get('id')
        return None

    def get_longtail_keyword(self):
        """실시간 롱테일 키워드 발굴 로직"""
        print(f"🔍 실시간 롱테일 키워드 분석 중...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        prompt = "대한민국 국민연금과 관련하여 2026년 기준 사람들이 가장 궁금해할 구체적인 롱테일 키워드를 하나 선정해 주제만 짧게 답해줘."
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            res = requests.post(url, json=payload, timeout=30)
            if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text'].strip().replace('"', '')
        except: pass
        return "국민연금 수령액 늘리는 실전 전략"

    def call_gemini_with_search(self, target_topic):
        """Google Search Grounding 기반 심층 본문 및 지능형 제목 생성"""
        print(f"🤖 구글 검색 기반 심층 콘텐츠 생성 중 (3,000자 목표)...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        marker_desc = "\n".join([f"- {k}: {v['title']}" for k, v in self.link_map.items()])
        
        system_instruction = f"""당신은 대한민국 최고의 금융 자산관리 전문가입니다. 실시간 데이터를 바탕으로 독자의 의도를 완벽히 해결하는 3,000자 초장문 전문가 칼럼을 작성하세요.

[⚠️ 제목 작성 규칙]
1. 제목 맨 앞에 '2026년'이나 '2월'을 절대 배치하지 마세요. 
2. 연도(2026년) 문구는 문맥적으로 자연스럽고 독자의 신뢰를 높이는 데 필요할 때만 선택적으로 포함하세요.

[⚠️ 하이퍼링크 마커 삽입 규칙]
1. 아래 제공된 마커들({list(self.link_map.keys())})만 본문에 삽입하세요.
{marker_desc}
2. 마커 옆의 제목 설명을 본문에 같이 적지 마세요. 본문에는 오직 '[[외부추천_0]]'과 같은 마커 코드만 들어가야 합니다.

[⚠️ 구텐베르크 블록 표준] 모든 본문 요소는 반드시 wp:paragraph, wp:heading h2/h3, wp:list, wp:table 마커로 감싸세요.
[⚠️ 분량] 공백 포함 2,500자~3,000자의 압도적인 정보량을 제공하세요."""

        payload = {
            "contents": [{"parts": [{"text": f"선정된 주제: '{target_topic}'\n\n이 주제에 대해 구글 검색을 통해 심층 분석하여 완성도 높은 구텐베르크 칼럼을 작성해줘."}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "tools": [{"google_search": {}}],
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
            if res.status_code == 200: return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
        except: pass
        return None

    def get_or_create_tags(self, tags_str):
        if not tags_str: return []
        tag_ids = []
        for name in [t.strip() for t in tags_str.split(',')]:
            try:
                res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/tags", headers=self.headers, json={"name": name}, timeout=15)
                if res.status_code in [200, 201]: tag_ids.append(res.json()['id'])
                else:
                    search = requests.get(f"{CONFIG['WP_URL']}/wp-json/wp/v2/tags?search={name}", headers=self.headers, timeout=15)
                    if search.status_code == 200 and search.json(): tag_ids.append(search.json()[0]['id'])
            except: continue
        return tag_ids

    def run(self):
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 멀티 피드 및 이미지 최적화 포스팅 시작 ---")
        target_topic = self.get_longtail_keyword()
        post_data = self.call_gemini_with_search(target_topic)
        if not post_data: return
        
        content = self.clean_structure(post_data['content'])
        content = self.inject_smart_links(content)
        
        # 이미지 생성 및 JPG 70% 최적화 업로드
        img_id = None
        img_b64 = self.generate_image(post_data['title'], post_data['excerpt'])
        if img_b64:
            img_id = self.process_and_upload_image(img_b64, post_data['title'])
        
        tag_ids = self.get_or_create_tags(post_data.get('tags', ''))
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 워드프레스 발행 요청 중...")
        payload = {
            "title": post_data['title'],
            "content": content,
            "excerpt": post_data['excerpt'],
            "status": "publish",
            "featured_media": img_id if img_id else 0,
            "tags": tag_ids
        }
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers={"Authorization": f"Basic {self.auth}", "Content-Type": "application/json"}, json=payload, timeout=60)
        
        if res.status_code == 201: print(f"🎉 성공: {post_data['title']}")
        else: print(f"❌ 실패: {res.text}")

if __name__ == "__main__":
    WordPressAutoPoster().run()
