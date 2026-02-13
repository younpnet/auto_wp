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
        queries = ["국민연금 수령액 증대", "2026 연금개혁안 세부내용", "기초연금 피부양자 탈락", "퇴직연금 IRP 수익률", "조기노령연금 단점"]
        query = random.choice(queries)
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {"X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]}
        params = {"query": query, "display": 12, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in res.json().get('items', [])])
        except: return "국민연금 최신 정책 변화와 노후 관리 전략"
        return ""

    def generate_image(self, title, excerpt):
        print(f"🎨 이미지 생성 중 (노년 타겟팅): {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        image_prompt = (
            f"A high-end cinematic lifestyle photography for a Korean finance blog. "
            f"Subject: A happy South Korean elderly couple in their 70s, looking content and financially secure "
            f"in a sun-filled, modern Korean traditional-meets-modern home. "
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
        files = {'file': (f"nps_{int(time.time())}.jpg", raw_data, "image/jpeg")}
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", headers=self.headers, files=files, timeout=60)
        return res.json().get('id') if res.status_code == 201 else None

    def clean_content(self, content):
        """본문 내 중복 내용 및 AI 불순물 완벽 제거"""
        if not content: return ""
        
        # 1. AI 주석 및 가짜 마커 제거 (//paragraph, //heading 등)
        content = re.sub(r'//[a-zA-Z가-힣]+', '', content)
        content = re.sub(r'\[NO CONTENT FOUND\]', '', content, flags=re.IGNORECASE)
        
        # 2. 끊겨 있는 리스트 블록 병합
        content = re.sub(r'</ul>\s*<!-- /wp:list -->\s*<!-- wp:list -->\s*<ul>', '', content, flags=re.DOTALL)
        
        # 3. 문단 단위 지문 중복 제거
        blocks = re.split(r'(<!-- wp:[^>]+-->)', content)
        seen_fingerprints = set()
        refined_blocks = []
        
        for i in range(0, len(blocks)):
            block = blocks[i]
            # 텍스트만 추출하여 중복 검사 (제목은 보존, 문단만 검사)
            if "wp:paragraph" in block:
                text_only = re.sub(r'<[^>]+>', '', block).strip()
                # 30자 이상의 문단에 대해서만 중복 검사 수행
                if len(text_only) > 30:
                    fingerprint = re.sub(r'[^가-힣]', '', text_only)[:40]
                    if fingerprint in seen_fingerprints: continue
                    seen_fingerprints.add(fingerprint)
            refined_blocks.append(block)
            
        final_content = "".join(refined_blocks).strip()
        
        # 4. 동일 문장 반복 제거 (문장 단위 클리닝)
        sentences = final_content.split('. ')
        unique_sentences = []
        sentence_fingerprints = set()
        for s in sentences:
            s_clean = re.sub(r'[^가-힣]', '', s)
            if len(s_clean) > 20: # 짧은 문장은 제외
                if s_clean in sentence_fingerprints: continue
                sentence_fingerprints.add(s_clean)
            unique_sentences.append(s)
        
        return ". ".join(unique_sentences)

    def call_gemini(self, prompt, system_instruction):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.8, # 다양성을 위해 약간 높임
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
        except: pass
        return None

    def generate_post(self):
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 롱테일 정보성 칼럼 생성 ---")
        news = self.search_naver_news()
        
        link_instr = f"본문 중간에 자연스럽게 링크 삽입: <a href='{self.external_link['url']}' target='_self'><strong>{self.external_link['title']}</strong></a>" if self.external_link else ""
        
        system = f"""당신은 대한민국 최고의 금융 자산관리 전문가입니다. 독자들에게 실질적인 도움을 주는 롱테일 칼럼을 작성하세요.

[필수 요구사항 - 중복 금지]
1. 절대 반복 금지: 서론, 본론의 각 섹션, FAQ, 결론에서 동일한 문장이나 유사한 의미의 단락을 반복하지 마세요. 
2. 정보 밀도: 3,000자 이상을 채우기 위해 같은 말을 되풀이하지 말고, 매 섹션마다 '새로운 데이터', '구체적인 사례', '실전 팁'을 추가하세요.
3. 페르소나: 노년층 독자들에게 신뢰를 주는 따뜻하고 전문적인 어조를 유지하세요. 
4. 금지 표식: 본문에 //paragraph, //heading, [NO CONTENT]와 같은 코멘트를 절대 넣지 마세요.
5. 중복 방지: 최근 제목들 {self.recent_titles}와 다른 새로운 주제를 다루세요.

[구성 요소]
- 강력한 인사이트를 담은 서론
- h2, h3 블록을 활용한 5개 이상의 상세 분석 섹션
- {link_instr}
- 국민연금공단(https://www.nps.or.kr) 공식 링크
- 3개 이상의 새로운 질문이 포함된 FAQ
- 전문가의 최종 제언이 담긴 결론"""

        post_data = self.call_gemini(f"참고 뉴스 데이터:\n{news}\n\n위 데이터를 바탕으로 당신의 전문성을 담은 풍성한 칼럼을 작성해줘.", system)
        
        if not post_data or not post_data.get('content') or len(post_data['content']) < 500:
            print("❌ 본문 생성 실패")
            return

        # 본문 정제 (단락/문장 중복 제거)
        post_data['content'] = self.clean_content(post_data['content'])

        # 이미지 처리 (노년 타겟팅)
        img_id = self.upload_media(self.generate_image(post_data['title'], post_data['excerpt']))

        # 최종 발행
        payload = {
            "title": post_data['title'],
            "content": post_data['content'],
            "excerpt": post_data['excerpt'],
            "status": "publish",
            "featured_media": img_id if img_id else 0,
            "tags": [t['id'] for t in [requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/tags", headers=self.headers, json={"name": name.strip()}).json() for name in post_data.get('tags', '').split(',')] if 'id' in t]
        }
        
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers=self.headers, json=payload, timeout=60)
        if res.status_code == 201:
            print(f"🎉 발행 성공: {post_data['title']}")
        else:
            print(f"❌ 실패: {res.text}")

if __name__ == "__main__":
    WordPressAutoPoster().generate_post()
