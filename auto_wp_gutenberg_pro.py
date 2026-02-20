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
    "TEXT_MODEL": "gemini-flash-latest", 
    "IMAGE_MODEL": "imagen-4.0-generate-001",
    "NAVER_CLIENT_ID": os.environ.get("NAVER_CLIENT_ID", ""),
    "NAVER_CLIENT_SECRET": os.environ.get("NAVER_CLIENT_SECRET", ""),
    # 여러 사이트의 RSS 피드 URL을 리스트 형태로 관리합니다.
    "RSS_URLS": [
        "https://younp.net/feed",
        "https://virz.net/feed"  # 요청하신 새로운 피드 주소를 추가했습니다.
    ]
}

class WordPressAutoPoster:
    def __init__(self):
        self._validate_config()
        
        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth = base64.b64encode(user_pass.encode()).decode()
        self.headers = {"Authorization": f"Basic {self.auth}"}
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 멀티 피드 시스템 초기화 중...")
        
        # 1. 여러 RSS 피드를 순회하며 links.json 업데이트
        self.sync_multiple_rss_feeds()
        
        # 2. 통합된 링크 데이터 로드
        self.ext_links = self.load_external_links(2)
        self.int_links = self.fetch_internal_links(2)
        
        # 3. 링크 마커 맵 생성
        self.link_map = {}
        self._setup_link_markers()

    def _validate_config(self):
        """필수 설정값이 있는지 확인합니다."""
        required_keys = ["WP_URL", "GEMINI_API_KEY", "WP_APP_PASSWORD"]
        for key in required_keys:
            if not CONFIG.get(key):
                print(f"❌ 오류: {key} 환경 변수가 설정되지 않았습니다.")
                sys.exit(1)

    def sync_multiple_rss_feeds(self):
        """설정된 모든 RSS 피드에서 최신 포스트를 가져와 links.json을 업데이트합니다."""
        print(f"📡 총 {len(CONFIG['RSS_URLS'])}개의 RSS 피드 동기화 시작...")
        
        # 기존 links.json 로드
        existing_links = []
        if os.path.exists('links.json'):
            with open('links.json', 'r', encoding='utf-8') as f:
                try:
                    existing_links = json.load(f)
                except json.JSONDecodeError:
                    existing_links = []
        
        existing_urls = {link['url'] for link in existing_links}
        total_added = 0

        for rss_url in CONFIG['RSS_URLS']:
            print(f"🔗 수집 중: {rss_url}")
            try:
                res = requests.get(rss_url, timeout=20)
                if res.status_code != 200:
                    print(f"  ⚠️ 피드 접근 실패 (코드: {res.status_code})")
                    continue

                root = ET.fromstring(res.content)
                feed_added = 0
                for item in root.findall('.//item'):
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
                    print(f"  ✅ {feed_added}개의 새로운 링크를 찾았습니다.")
            except Exception as e:
                print(f"  ⚠️ '{rss_url}' 처리 중 오류 발생: {e}")

        # 변경사항이 있을 때만 파일 저장
        if total_added > 0:
            with open('links.json', 'w', encoding='utf-8') as f:
                json.dump(existing_links, f, ensure_ascii=False, indent=4)
            print(f"🎉 동기화 완료: 총 {total_added}개의 링크가 추가되었습니다.")
        else:
            print("ℹ️ 모든 피드가 최신 상태입니다. 추가된 링크가 없습니다.")

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
        """links.json(통합 데이터베이스)에서 무작위 외부 링크를 가져옵니다."""
        try:
            if os.path.exists('links.json'):
                with open('links.json', 'r', encoding='utf-8') as f:
                    links = json.load(f)
                    if not links: return []
                    return random.sample(links, min(len(links), count))
        except Exception as e:
            print(f"⚠️ links.json 로드 실패: {e}")
        return []

    def _setup_link_markers(self):
        for i, link in enumerate(self.int_links):
            self.link_map[f"[[내부참고_{i}]]"] = link
        for i, link in enumerate(self.ext_links):
            self.link_map[f"[[외부추천_{i}]]"] = link

    def inject_smart_links(self, content):
        """본문의 마커를 분석하여 앵커 또는 버튼으로 정밀 치환합니다."""
        for marker, info in self.link_map.items():
            url = info['url']
            title = info['title']
            
            button_html = (
                f'\n<!-- wp:buttons {{"layout":{{"type":"flex","justifyContent":"center"}}}} -->\n'
                f'<div class="wp-block-buttons"><!-- wp:button {{"backgroundColor":"vivid-cyan-blue","borderRadius":5}} -->\n'
                f'<div class="wp-block-button"><a class="wp-block-button__link has-vivid-cyan-blue-background-color has-background wp-element-button" href="{url}" target="_self" rel="noopener noreferrer">{title}</a></div>\n'
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
        final_content = "".join(refined_output).strip()
        final_content = re.sub(r'(([가-힣\s\d,.\(\)]{15,})\s*)\2{2,}', r'\1', final_content)
        return final_content

    def generate_image(self, title, excerpt):
        print(f"🎨 대표 이미지 생성 중...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        scenarios = [
            f"A South Korean financial advisor explaining pension plans to a happy elderly couple in a sunlit office.",
            f"A professional South Korean man in his 50s confidently reviewing retirement fund charts in a modern cafe.",
            f"Close-up of South Korean senior's hands holding a pension guide and a calculator, focus on documents.",
            f"An elderly South Korean couple walking happily in a scenic autumn park, symbolizing financial security."
        ]
        selected_scenario = random.choice(scenarios)
        image_prompt = f"Professional editorial photography: {selected_scenario} Context: {title}. Cinematic lighting, 16:9, NO TEXT."
        
        payload = {"instances": [{"prompt": image_prompt}], "parameters": {"sampleCount": 1}}
        try:
            res = requests.post(url, json=payload, timeout=120)
            if res.status_code == 200: return res.json()['predictions'][0]['bytesBase64Encoded']
        except Exception as e:
            print(f"⚠️ 이미지 오류: {e}")
        return None

    def get_longtail_keyword(self):
        """독자들이 실제로 궁금해하는 틈새 키워드를 발굴합니다."""
        print(f"🔍 실시간 롱테일 키워드 분석 중 (모델: {CONFIG['TEXT_MODEL']})...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        prompt = (
            "2026년 대한민국 국민연금과 관련하여 사람들이 구글이나 네이버에서 가장 많이 검색하지만 "
            "정보가 부족한 구체적인 '롱테일 키워드' 1개를 선정해주세요. "
            "(예: 경력단절 여성 추납 시 수익률 분석, 소득 하위 70% 기초연금 연동 문제 등) "
            "주제만 한 줄로 짧게 답변하세요."
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            res = requests.post(url, json=payload, timeout=30)
            if res.status_code == 200:
                keyword = res.json()['candidates'][0]['content']['parts'][0]['text'].strip().replace('"', '')
                print(f"✅ 발굴된 키워드: {keyword}")
                return keyword
        except: pass
        return "국민연금 수령액 늘리는 실전 전략"

    def call_gemini_with_search(self, target_topic):
        """Google Search Grounding을 사용하여 정보 밀도가 높은 본문을 생성합니다."""
        print(f"🤖 구글 검색 기반 심층 콘텐츠 생성 중...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        marker_desc = "\n".join([f"- {k} (제목: {v['title']})" for k, v in self.link_map.items()])
        
        system_instruction = f"""당신은 대한민국 최고의 금융 자산관리 전문가입니다. 2026년 시점의 데이터를 바탕으로 검색 의도를 완벽히 해결하는 3,000자 초장문 칼럼을 작성하세요.

[⚠️ 구글 검색 활용 필수]
- 당신은 도구(Google Search)를 사용하여 최신 규정, 실제 사례, 수치화된 데이터를 실시간으로 조사한 뒤 이를 바탕으로 글을 써야 합니다.
- 독자들이 읽어야 할 가치 있는 구체적인 정보를 제공하세요.

[⚠️ 구텐베르크 블록 형식]
1. 모든 본문 요소는 반드시 구텐베르크 마커로 감싸야 합니다 (paragraph, heading h2/h3, list, table).
2. 아래 마커들을 본문에 반드시 전략적으로 포함하세요:
{marker_desc}

[⚠️ 분량 및 퀄리티]
1. 분량: 2,500자~3,000자의 압도적인 정보량.
2. 전문성: 소제목 6개 이상. 복잡한 비교는 반드시 <table> 블록 사용.
3. 중복 금지 및 인사말 금지."""

        payload = {
            "contents": [{"parts": [{"text": f"선정된 주제: '{target_topic}'\n\n이 주제에 대해 구글 검색을 통해 심층 분석하여 완성도 높은 칼럼을 작성해줘."}]}],
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
            if res.status_code == 200: 
                return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
            else:
                print(f"❌ AI 생성 실패: {res.status_code}")
        except Exception as e:
            print(f"⚠️ AI 오류: {e}")
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
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 멀티 피드 기반 심층 포스팅 시작 ---")
        
        # 1. 고의도 롱테일 키워드 발굴
        target_topic = self.get_longtail_keyword()
        
        # 2. 구글 검색 기반 심층 본문 생성
        post_data = self.call_gemini_with_search(target_topic)
        if not post_data: return
        
        # 3. 본문 정제 및 지능형 링크 삽입
        content = self.clean_structure(post_data['content'])
        content = self.inject_smart_links(content)
        
        # 4. 이미지 생성 및 업로드
        img_id = None
        img_b64 = self.generate_image(post_data['title'], post_data['excerpt'])
        if img_b64:
            raw_data = base64.b64decode(img_b64)
            files = {'file': (f"nps_deep_{int(time.time())}.jpg", raw_data, "image/jpeg")}
            media_res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", headers=self.headers, files=files, timeout=60)
            if media_res.status_code == 201: img_id = media_res.json().get('id')
        
        # 5. 태그 처리
        tag_ids = self.get_or_create_tags(post_data.get('tags', ''))
        
        # 6. 최종 발행
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
        
        if res.status_code == 201:
            print(f"🎉 성공: 멀티 피드 기반 심층 포스팅 완료! (제목: {post_data['title']})")
        else:
            print(f"❌ 최종 발행 실패: {res.text}")

if __name__ == "__main__":
    WordPressAutoPoster().run()
