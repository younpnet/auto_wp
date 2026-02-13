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
        self.external_link = self.load_external_link()
        self.recent_titles = self.fetch_recent_post_titles(50)

    def fetch_recent_post_titles(self, count=50):
        url = f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title"}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=20)
            if res.status_code == 200:
                return [re.sub('<.*?>', '', post['title']['rendered']).strip() for post in res.json()]
        except: pass
        return []

    def load_external_link(self):
        try:
            if os.path.exists('links.json'):
                with open('links.json', 'r', encoding='utf-8') as f:
                    links = json.load(f)
                    if links: return random.choice(links)
        except: pass
        return None

    def search_naver_news(self):
        queries = ["국민연금 개혁 전략", "2026 연금액 계산기 활용", "노후 건보료 폭탄 방지", "연금저축 IRP 절세 팁", "유족연금 수령 조건"]
        query = random.choice(queries)
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {"X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]}
        params = {"query": query, "display": 12, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in res.json().get('items', [])])
        except: return "국민연금 수령액 증대 및 노후 설계 핵심 가이드"
        return ""

    def generate_image(self, title, excerpt):
        print(f"🎨 이미지 생성 중 (노년 타겟팅): {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        image_prompt = (
            f"A high-end cinematic lifestyle photography for a Korean finance blog. "
            f"Subject: A happy South Korean elderly couple in their 70s, looking content and financially secure "
            f"in a sun-filled, modern Korean home. "
            f"Context: {title}. Photorealistic, soft focus, warm lighting, high resolution, 16:9 aspect ratio. "
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
        files = {'file': (f"nps_pro_{int(time.time())}.jpg", raw_data, "image/jpeg")}
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", headers=self.headers, files=files, timeout=60)
        return res.json().get('id') if res.status_code == 201 else None

    def clean_content(self, content):
        """본문 구조 보존, 중복 문장 제거 및 AI 불필요 마커 제거"""
        if not content: return ""
        
        # 1. AI 가짜 주석 및 불순물 제거 (//paragraph, [NO CONTENT] 등)
        content = re.sub(r'//[a-zA-Z가-힣]+', '', content)
        content = re.sub(r'\[.*?\]', '', content)
        content = content.replace('```html', '').replace('```', '')

        # 2. 리스트 블록 병합
        content = re.sub(r'</ul>\s*<!-- /wp:list -->\s*<!-- wp:list -->\s*<ul>', '', content, flags=re.DOTALL)
        
        # 3. 문단 단위 중복 지문 제거
        blocks = re.split(r'(<!-- wp:[^>]+-->)', content)
        seen_fingerprints = set()
        refined_output = []
        
        for i in range(len(blocks)):
            segment = blocks[i]
            if segment.startswith('<!-- wp:') or segment.startswith('<!-- /wp:'):
                refined_output.append(segment)
                continue
            
            # 텍스트 내용 추출 및 중복 검사
            text_only = re.sub(r'<[^>]+>', '', segment).strip()
            if len(text_only) > 30:
                fingerprint = re.sub(r'[^가-힣]', '', text_only)[:60]
                if fingerprint in seen_fingerprints:
                    # 중복 블록일 경우 이전 마커까지 제거
                    if refined_output and refined_output[-1].startswith('<!-- wp:'):
                        refined_output.pop()
                    continue
                seen_fingerprints.add(fingerprint)
            
            refined_output.append(segment)
            
        return "".join(refined_output).strip()

    def call_gemini(self, prompt, system_instruction):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.8,
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
                result = res.json()
                if 'candidates' in result and result['candidates']:
                    text_content = result['candidates'][0]['content']['parts'][0]['text']
                    return json.loads(text_content)
            else:
                print(f"❌ API 실패: {res.status_code}")
        except Exception as e:
            print(f"❌ 오류: {e}")
        return None

    def generate_post(self):
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 고품질 SEO 포스팅 생성 시작 ---")
        news = self.search_naver_news()
        
        # 외부 링크 정보
        link_instr = ""
        if self.external_link:
            link_instr = f"본문 중간(두 번째 H2 섹션 이후)에 다음 링크를 <a> 태그로 자연스럽게 한 번만 삽입하세요: {self.external_link['title']} ({self.external_link['url']})"
        
        system = f"""당신은 대한민국 최고의 노후 설계 및 자산 관리 전문가입니다. 2026년 시점의 데이터를 기반으로 독자들에게 강력한 통찰을 주는 3,000자 이상의 초장문 칼럼을 작성하세요.

[필수: SEO 및 구조 표준]
1. 모든 단락은 구텐베르크 블록 마커(<!-- wp:paragraph --> 등)를 완벽히 준수하세요.
2. 절대 동일한 문장이나 단락을 반복하지 마세요. 각 섹션은 '새로운 구체적 정보'를 담아야 합니다. (반복 시 불이익)
3. 소제목(h2, h3)을 6개 이상 사용하여 전문적인 목차 구조를 형성하세요.
4. {link_instr} - 반드시 target="_self" 속성을 부여하세요.
5. 국민연금공단(https://www.nps.or.kr) 링크를 본문 하단 출처로 명기하세요.
6. 복잡한 수치 비교는 반드시 HTML <table> 블록을 한 번 이상 사용하세요.

[내용 가이드라인]
- 인사말 절대 금지. 바로 강력한 화두로 시작하세요.
- 전문가 페르소나: 단순히 '수령액 늘리기'가 아니라 '건보료 폭탄 방지', '세금 최적화' 등 고도의 자산 관리 관점을 포함하세요.
- 중복 방지: 최근 발행된 주제들 {self.recent_titles}와 겹치지 않게 하세요.
- 절대 //paragraph와 같은 주석이나 [NO CONTENT] 같은 표시를 본문에 넣지 마세요.

[구성]
- 서론: 연금의 함정과 자산 방어의 필요성
- 본론: 5개 이상의 상세 분석 섹션
- 실전 대응: <table>을 활용한 시나리오 비교
- FAQ: 4개 이상의 상세 질문과 답변
- 결론: 전문가가 제안하는 노후 로드맵"""

        post_data = self.call_gemini(f"최신 뉴스 참고:\n{news}\n\n위 데이터를 활용해 독창적이고 정보량이 압도적인 전문가 칼럼을 작성해줘.", system)
        
        if not post_data or not post_data.get('content') or len(post_data['content']) < 500:
            print("❌ 생성 실패 또는 분량 미달")
            return

        # 본문 정제 (//paragraph 제거 및 내용 반복 제거)
        post_data['content'] = self.clean_content(post_data['content'])

        # 이미지 처리 (노년 타겟팅)
        img_id = self.upload_media(self.generate_image(post_data['title'], post_data['excerpt']))

        # 최종 발행
        tag_ids = []
        if post_data.get('tags'):
            for name in post_data['tags'].split(','):
                try:
                    t_res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/tags", headers={"Authorization": f"Basic {self.auth}"}, json={"name": name.strip()}, timeout=10)
                    if t_res.status_code in [200, 201]: tag_ids.append(t_res.json()['id'])
                    elif t_res.status_code == 400: # 기존 조회
                        s_res = requests.get(f"{CONFIG['WP_URL']}/wp-json/wp/v2/tags?search={name.strip()}", headers={"Authorization": f"Basic {self.auth}"}, timeout=10)
                        if s_res.status_code == 200 and s_res.json(): tag_ids.append(s_res.json()[0]['id'])
                except: continue

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
