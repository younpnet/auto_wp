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
        # 2. 내부 링크 2개용 최근 발행글 로드
        self.internal_link_pool = self.fetch_internal_link_pool(15)
        # 3. 중복 방지용 제목 리스트
        self.recent_titles = [post['title'] for post in self.internal_link_pool]


    def fetch_internal_link_pool(self, count=15):
        url = f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title,link"}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=20)
            if res.status_code == 200:
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
        queries = ["국민연금 수령액 증대 꿀팁", "2026 국민연금 개정 소식", "노후 준비 필수 상식"]
        query = random.choice(queries)
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {"X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]}
        params = {"query": query, "display": 12, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in res.json().get('items', [])])
        except: return "국민연금 최신 이슈 브리핑"
        return ""


    def generate_image(self, title, excerpt):
        print(f"🎨 이미지 생성 중: {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        image_prompt = (
            f"Professional and warm lifestyle photography for a Korean finance blog. "
            f"Subject: A happy South Korean elderly couple in their 70s, "
            f"smiling in a luxurious and bright modern Korean home. "
            f"Style: Photorealistic, cinematic lighting, high quality, 16:9, NO TEXT."
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


    def extract_and_validate_url(self, url_string):
        """URL 문자열에서 유효한 URL만 추출하고 검증합니다."""
        if not url_string:
            return ""

        # 여러 개의 https:// 가 있으면 마지막 것만 선택
        urls = re.findall(r'https?://[^\s"<>]+', url_string)
        if urls:
            url = urls[-1]
        else:
            url = url_string

        # URL이 https://로 시작하지 않으면 빈 문자열 반환
        if not url.startswith('http://') and not url.startswith('https://'):
            return ""

        return url


    def clean_content(self, content):
        """본문 내 중복, 불필요 주석 및 깨진 하이퍼링크 패턴을 물리적으로 제거합니다."""
        if not content: return ""

        # 1. AI 가짜 주석 제거
        content = re.sub(r'//\s*[a-zA-Z가-힣]+', '', content)
        content = content.replace('```html', '').replace('```', '')

        # 2. 하이퍼링크 내 도메인 중복 및 경로 파편 강제 교정 (대폭 강화)
        def repair_links(match):
            url = match.group(1)

            # 2-1. 유효한 URL만 추출
            url = self.extract_and_validate_url(url)
            if not url:
                return f'href="#"'  # 유효하지 않은 URL은 #으로 대체

            # 2-2. URL 파싱하여 도메인과 경로 분리
            url_match = re.match(r'(https?://[^/]+)(.*)', url)
            if not url_match:
                return f'href="{url}"'

            domain = url_match.group(1)
            path = url_match.group(2) if url_match.group(2) else ""

            # 2-3. 경로에서 도메인 파편 제거
            # 예: /.net/ 같은 TLD 파편 제거
            path = re.sub(r'/\.[a-z]{2,}/', '/', path)

            # 2-4. 경로에 다른 도메인이 포함된 경우 제거
            # 예: /경로/-pension.sleepyourmoney.net → /경로/
            path = re.sub(r'/[^/]*\.[a-z]{2,}(?:/|$)', '/', path)

            # 2-5. 경로에서 도메인 자체가 반복되는 경우 제거
            domain_name = domain.replace('https://', '').replace('http://', '')
            if domain_name in path:
                path = re.sub(f'/{re.escape(domain_name)}/?', '/', path)

            # 2-6. 연속된 슬래시 정리
            path = re.sub(r'/+', '/', path)

            # 2-7. 경로가 없거나 /만 있으면 제거
            if path in ['', '/']:
                path = ''

            # 2-8. 최종 URL 재구성
            clean_url = f"{domain}{path}"

            # 2-9. URL 끝의 불필요한 슬래시 제거 (루트 경로 제외)
            if clean_url.endswith('/') and clean_url != f"{domain}/":
                clean_url = clean_url.rstrip('/')

            return f'href="{clean_url}"'

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
                fingerprint = re.sub(r'[^가-힣]', '', text_only)[:120]
                if fingerprint in seen_fingerprints:
                    if refined_output and refined_output[-1].startswith('<!-- wp:'): refined_output.pop()
                    continue
                seen_fingerprints.add(fingerprint)
            refined_output.append(segment)

        final_content = "".join(refined_output).strip()
        # 동일 구절 무한 반복 패턴 물리적 제거
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
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 최종 링크 보호 모드 가동 ---")
        news = self.search_naver_news()

        # 외부/내부 링크 매핑 데이터 생성 (특수 기호 기반 토큰 사용)
        int_links = random.sample(self.internal_link_pool, min(len(self.internal_link_pool), 2))
        links_mapping = {}
        link_instr_list = []

        for i, link in enumerate(self.external_links):
            token = f"EXTLINK{i}TOKEN"  # 더 단순한 토큰으로 변경
            links_mapping[token] = link['url']
            link_instr_list.append(f"- 제목: {link['title']}, 삽입코드: {token} (외부추천)")

        for i, link in enumerate(int_links):
            token = f"INTLINK{i}TOKEN"  # 더 단순한 토큰으로 변경
            links_mapping[token] = link['url']
            link_instr_list.append(f"- 제목: {link['title']}, 삽입코드: {token} (내부참고)")

        link_instruction = "\n".join(link_instr_list)

        system = f"""당신은 대한민국 최고의 금융 자산관리 전문가입니다. 2026년 시점의 통찰력 있는 전문가 칼럼을 작성하세요.


[⚠️ 하이퍼링크 삽입 절대 수칙 - 4개 필수 삽입]
1. 본문에 아래 4개의 삽입코드를 반드시 <a> 태그의 href 값으로 포함하세요:
{link_instruction}

2. **절대 금기 사항**:
   - 삽입코드 앞뒤에 어떤 문자도 추가하지 마세요 (/, -, https:// 등 금지)
   - 삽입코드를 수정하거나 변형하지 마세요
   - 나쁜 예: <a href="https://example.com/INTLINK0TOKEN">
   - 나쁜 예: <a href="/INTLINK0TOKEN">
   - 나쁜 예: <a href="-INTLINK0TOKEN">
   - 좋은 예: <a href="INTLINK0TOKEN">

3. 링크 사용법:
   - href 속성에 삽입코드만 정확히 입력: <a href="INTLINK0TOKEN" target="_self">링크텍스트</a>
   - 모든 링크에 target="_self" 속성 포함


[⚠️ 필수: 문서 구조 및 품질]
1. 계층 구조: 반드시 h2, h3, h4 제목 블록을 사용하여 논리적으로 섹션을 나누세요. 모든 섹션은 제목 블록으로 시작해야 합니다.
2. 가독성: 한 문단(p 태그)은 4~6문장으로 구성하세요.
3. 중복 방지: 동일 문장이나 내용을 절대 반복하지 마세요.


[본문 구성]
- 제목 맨 앞에 연도를 넣지 마세요. 연도는 제목 끝에 배치하세요.
- 3,000자 이상의 압도적인 정보량과 실질적인 도움을 주는 조언을 포함하세요."""


        post_data = self.call_gemini(f"뉴스 소스:\n{news}\n\n위 데이터를 활용해 링크 코드가 안전하게 배치된 고품질 칼럼을 작성해줘.", system)

        if not post_data or not post_data.get('content'):
            print("❌ 생성 실패")
            return


        # [핵심 단계 1] AI가 생성한 모든 잘못된 패턴 사전 제거
        final_content = post_data['content']

        for token in links_mapping.keys():
            # 패턴 1: 도메인/경로/토큰 형태 제거
            final_content = re.sub(
                rf'href="https?://[^"]*[/\-]{re.escape(token)}"',
                f'href="{token}"',
                final_content
            )
            # 패턴 2: 상대경로/토큰 형태 제거
            final_content = re.sub(
                rf'href="[/\-]+{re.escape(token)}"',
                f'href="{token}"',
                final_content
            )
            # 패턴 3: 토큰 앞에 어떤 문자든 있으면 제거
            final_content = re.sub(
                rf'href="[^"]*?{re.escape(token)}"',
                f'href="{token}"',
                final_content
            )


        # [핵심 단계 2] 토큰을 실제 URL로 정확히 치환
        for token, real_url in links_mapping.items():
            # 토큰만 정확히 매칭하여 치환
            final_content = final_content.replace(f'href="{token}"', f'href="{real_url}"')

        post_data['content'] = final_content


        # [디버그] 치환 전후 비교
        print("\n=== 디버그: 링크 치환 검증 ===")
        for token, real_url in links_mapping.items():
            # 토큰이 남아있는지 확인
            if token in final_content:
                print(f"⚠️  미치환 토큰 발견: {token}")

            # 실제 URL이 제대로 들어갔는지 확인
            matches = re.findall(rf'href="([^"]*{re.escape(real_url.split("/")[-1] if "/" in real_url else real_url)}[^"]*)"', final_content)
            print(f"✓ {token} → {real_url}")
            for match in matches[:2]:
                print(f"  → {match}")


        # [핵심 단계 3] 최종 본문 물리적 정제
        post_data['content'] = self.clean_content(post_data['content'])


        # [최종 검증] 깨진 URL 패턴 체크
        print("\n=== 최종 URL 검증 ===")
        broken_patterns = re.findall(r'href="([^"]*(?:/\.[a-z]{2,}/|/[^/]*\.[a-z]{2,}(?:/|$))[^"]*)"', post_data['content'])
        if broken_patterns:
            print(f"⚠️  의심스러운 URL 패턴 {len(broken_patterns)}개 발견:")
            for pattern in broken_patterns[:5]:
                print(f"  - {pattern}")
        else:
            print("✓ 모든 URL이 정상입니다")


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
            print(f"\n🎉 발행 성공: {post_data['title']}")
            print(f"🔗 URL: {res.json().get('link', 'N/A')}")
        else:
            print(f"\n❌ 발행 실패: {res.status_code}")
            print(f"오류 내용: {res.text[:500]}")


if __name__ == "__main__":
    WordPressAutoPoster().generate_post()
