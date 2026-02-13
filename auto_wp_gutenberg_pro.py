import requests
import json
import time
import base64
import re
import os
import io
import random
from datetime import datetime

# 이미지 처리를 위한 PIL 라이브러리 (JPG 변환 및 압축용)
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️ 경고: PIL(Pillow) 라이브러리가 설치되지 않았습니다. 이미지 압축 기능이 제한됩니다.")

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
        self.headers = {
            "Authorization": f"Basic {self.auth}"
        }
        self.external_link = self.load_external_link()
        # 중복 방지를 위한 최근 글 제목 로드
        self.recent_titles = self.fetch_recent_post_titles(50)

    def fetch_recent_post_titles(self, count=50):
        """워드프레스에서 최근 발행된 글 제목들을 가져옵니다."""
        print(f"🔍 중복 방지를 위해 최근 글 {count}개를 분석 중...")
        url = f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts"
        params = {"per_page": count, "status": "publish", "_fields": "title"}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=20)
            if res.status_code == 200:
                return [re.sub('<.*?>', '', post['title']['rendered']).strip() for post in res.json()]
        except Exception as e:
            print(f"⚠️ 최근 글 로드 실패: {e}")
        return []

    def get_or_create_tag_ids(self, tags_input):
        """텍스트 태그를 받아 워드프레스 ID로 변환 (없으면 생성)"""
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
                    if create_res.status_code == 201:
                        tag_ids.append(create_res.json()['id'])
            except: continue
        return tag_ids

    def load_external_link(self):
        try:
            if os.path.exists('links.json'):
                with open('links.json', 'r', encoding='utf-8') as f:
                    links = json.load(f)
                    if links: return random.choice(links)
        except: pass
        return None

    def search_naver_news(self):
        """검색 키워드를 랜덤화하여 소재 중복 방지"""
        queries = ["국민연금 개혁안", "국민연금 수령액 늘리는 법", "국민연금 추납 반납", "기초연금 국민연금 연계", "퇴직연금 운용 전략"]
        query = random.choice(queries)
        print(f"📰 뉴스 검색 키워드: {query}")
        
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 10, "sort": "sim"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                return "\n".join([f"- {re.sub('<.*?>', '', i['title'])}: {re.sub('<.*?>', '', i['description'])}" for i in res.json().get('items', [])])
        except: return "국민연금 최신 동향 및 재테크 전략"
        return ""

    def generate_image(self, title):
        print(f"🎨 이미지 생성 중: {title}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        prompt = f"Professional finance blog header, Korean middle-aged couple smiling happily in a sunny modern home, financial security theme, photorealistic, 16:9, NO TEXT."
        payload = {"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1}}
        try:
            res = requests.post(url, json=payload, timeout=100)
            if res.status_code == 200:
                return res.json()['predictions'][0]['bytesBase64Encoded']
        except: return None
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
        
        headers = {"Authorization": f"Basic {self.auth}", "Content-Type": "image/jpeg", "Content-Disposition": f'attachment; filename="nps_{int(time.time())}.jpg"'}
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/media", headers=headers, data=raw_data)
        return res.json().get('id') if res.status_code == 201 else None

    def call_gemini(self, prompt, system_instruction):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.8,
                "maxOutputTokens": 8192, # 충분한 출력량을 확보하여 본문 잘림 방지
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
                result_json = res.json()
                if 'candidates' in result_json:
                    return json.loads(result_json['candidates'][0]['content']['parts'][0]['text'])
            else:
                print(f"❌ AI 호출 실패 ({res.status_code}): {res.text}")
        except Exception as e:
            print(f"❌ AI 호출 중 오류 발생: {e}")
        return None

    def generate_post(self):
        print(f"--- [{datetime.now().strftime('%H:%M:%S')}] 작업 시작 ---")
        news = self.search_naver_news()
        
        # 외부 링크 구성
        link_instr = ""
        if self.external_link:
            link_instr = f"글의 맥락에 맞춰 다음 링크를 <a> 태그로 자연스럽게 한 번만 삽입하세요: {self.external_link['title']} ({self.external_link['url']})"
        
        system = f"""당신은 대한민국 최고의 금융 자산관리 전문가입니다. 2026년 시점의 통찰력 있는 전문가 칼럼을 작성하세요.

[필수 요구사항]
1. 분량: 3,000자 이상의 매우 상세한 정보글을 작성하세요. 절대 중간에 요약하거나 끊지 마세요.
2. 페르소나: 단순히 정보를 나열하는 기계가 아니라, 독자의 미래를 진심으로 걱정하고 전문적인 대안을 제시하는 전문가의 어조(전문성 + 인간미)를 유지하세요.
3. 중복 방지: 이미 다음 주제들로 글을 썼습니다: {self.recent_titles}. 이와 절대 겹치지 않는 새로운 시각이나 니치한 정보를 다루세요.
4. 구조: 반드시 구텐베르크 블록 마커(<!-- wp:heading -->, <!-- wp:paragraph -->, <!-- wp:list -->)를 사용하여 워드프레스 편집기에서 완벽하게 보이도록 하세요.
5. 구성 요소:
   - 전문가적 시각이 담긴 서론
   - h2, h3 소제목을 활용한 체계적인 본론 (수치와 구체적 사례 포함)
   - {link_instr}
   - 국민연금공단(https://www.nps.or.kr) 링크 포함
   - 마지막에 상세한 FAQ 섹션 (3개 이상의 질문과 답변)
   - 전문가 제언이 담긴 결론

[주의사항]
- 인사말('안녕하십니까' 등) 없이 바로 제목과 본문으로 시작하세요.
- 제목 끝에 연도 관련 문구(예: 2026년 최신 가이드)를 자연스럽게 포함하세요.
- 마크다운 기호(#, **)를 쓰지 말고 오직 HTML과 블록 마커만 사용하세요."""

        post_data = self.call_gemini(f"참고 뉴스 데이터:\n{news}\n\n위 데이터를 바탕으로 당신의 전문 지식을 동원해 독창적이고 풍부한 칼럼을 작성해줘.", system)
        
        if not post_data or not post_data.get('content') or len(post_data['content']) < 500:
            print("❌ 본문이 생성되지 않았거나 내용이 너무 짧습니다. 발행을 중단합니다.")
            return

        # 태그 ID 처리
        tag_ids = self.get_or_create_tag_ids(post_data.get('tags', ''))

        # 이미지 처리
        img_id = self.upload_media(self.generate_image(post_data['title']))

        # 최종 발행
        print("🚀 워드프레스 최종 발행 시도 중...")
        payload = {
            "title": post_data['title'],
            "content": post_data['content'],
            "excerpt": post_data['excerpt'],
            "status": "publish",
            "featured_media": img_id if img_id else 0,
            "tags": tag_ids
        }
        
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers=self.headers, json=payload, timeout=60)
        if res.status_code == 201:
            print(f"🎉 발행 성공: {post_data['title']}")
            print(f"🔗 링크: {res.json().get('link')}")
        else:
            print(f"❌ 워드프레스 발행 실패 ({res.status_code}): {res.text}")

if __name__ == "__main__":
    WordPressAutoPoster().generate_post()
