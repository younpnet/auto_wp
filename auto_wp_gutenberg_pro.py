import requests
import json
import time
import base64
import re
import os
import sys
import io
import random
from datetime import datetime

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️ PIL 없음 - 이미지 비율 검증 생략")

# ==============================================================================
# 환경 변수 및 설정
# ==============================================================================
CONFIG = {
    "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
    "WP_URL": os.environ.get("WP_URL", ""),
    "WP_USERNAME": os.environ.get("WP_USERNAME", "admin"),
    "WP_APP_PASSWORD": os.environ.get("WP_APP_PASSWORD", ""),
    "NAVER_CLIENT_ID": os.environ.get("NAVER_CLIENT_ID", ""),
    "NAVER_CLIENT_SECRET": os.environ.get("NAVER_CLIENT_SECRET", ""),
    "TEXT_MODEL": "gemini-2.5-flash-preview-09-2025",
    "IMAGE_MODEL": "imagen-4.0-generate-001" # 텍스트-투-이미지 생성 최적화 모델
}

class WordPressAutoPoster:
    def __init__(self):
        print("🚀 국민연금 자동 포스팅 시스템 가동 (최종 최적화 버전)")
        self.validate_config()
        self.setup_session()
        self.load_recent_titles()

    def validate_config(self):
        required = ["WP_URL", "WP_APP_PASSWORD", "GEMINI_API_KEY"]
        for key in required:
            if not CONFIG[key]:
                print(f"❌ {key} 환경변수 필요")
                sys.exit(1)
        print("✅ 시스템 환경 점검 완료")

    def setup_session(self):
        self.base_url = CONFIG["WP_URL"].rstrip("/")
        self.session = requests.Session()
        self.session.timeout = 30
        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth_header = base64.b64encode(user_pass.encode()).decode()
        self.common_headers = {
            "Authorization": f"Basic {self.auth_header}",
            "Content-Type": "application/json"
        }

    def load_recent_titles(self):
        try:
            res = self.session.get(f"{self.base_url}/wp-json/wp/v2/posts?per_page=15", headers=self.common_headers)
            self.recent_titles = [p['title']['rendered'] for p in res.json()] if res.status_code == 200 else []
            print(f"✅ 최근 {len(self.recent_titles)}개 제목 로드 완료")
        except:
            self.recent_titles = []
            print("⚠️ 최근 제목 로드 생략")

    def search_news(self):
        if not CONFIG["NAVER_CLIENT_ID"]:
            return "최근 국민연금 주요 제도 변화 및 2026년 수급 가이드"

        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": "국민연금", "display": 15, "sort": "sim"}

        try:
            res = self.session.get(url, headers=headers, params=params)
            items = res.json().get('items', [])
            news_context = "\n".join([f"제목: {re.sub('<.*?>', '', i['title'])}\n설명: {re.sub('<.*?>', '', i['description'])}" for i in items])
            return news_context if news_context else "국민연금 제도 정보"
        except:
            return "국민연금 관련 최신 정보"

    def generate_content(self, news_text):
        print("--- [Step 1] 텍스트 콘텐츠 생성 중... ---")
        system_prompt = (
            f"당신은 국민연금 전문 자산관리사입니다. 현재 2026년 2월 기준입니다.\n"
            f"기존 주제와 겹치지 않게 작성하세요: {self.recent_titles}\n\n"
            f"[지침]\n"
            f"1. 롱테일 키워드 전략: 특정 대상(전업주부, 프리랜서 등)의 고민을 해결하는 상세 주제를 선정하세요.\n"
            f"2. 반복 금지: 각 문단은 독립적인 정보를 담아야 하며 내용을 되풀이하지 마세요.\n"
            f"3. 링크 삽입: 설명 중간에 자연스럽게 <a> 태그를 볼드(<strong>) 처리하여 삽입하세요.\n"
            f"   - <a href='https://www.nps.or.kr'>국민연금공단 공식 홈페이지</a>\n"
            f"   - <a href='https://minwon.nps.or.kr'>내 곁에 국민연금</a>\n"
            f"4. AI는 절대로 구텐베르크 주석(<!-- wp... -->)을 생성하지 마세요. 데이터만 생성하세요."
        )

        schema = {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "string"},
                "focus_keyphrase": {"type": "string"},
                "tags": {"type": "string"},
                "excerpt": {"type": "string"},
                "blocks": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "type": {"type": "string", "enum": ["h2", "p", "list"]},
                            "content": {"type": "string"}
                        }
                    }
                }
            },
            "required": ["title", "focus_keyphrase", "blocks", "tags", "excerpt"]
        }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "contents": [{"parts": [{"text": f"뉴스 데이터:\n{news_text}\n\n위 데이터를 분석하여 독창적인 롱테일 정보글을 작성해줘."}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema, "temperature": 0.8}
        }

        try:
            res = self.session.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
        except Exception as e:
            print(f"❌ 텍스트 생성 에러: {e}")
        return None

    def generate_image(self, title):
        print("--- [Step 2] AI 대표 이미지 생성 중... ---")
        prompt = f"A professional, clean financial blog header for '{title}'. Korean theme, warm office lighting, no text, high quality, 16:9 ratio."
        
        # Imagen 모델은 predict 엔드포인트를 사용합니다.
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        payload = {
            "instances": {"prompt": prompt},
            "parameters": {"sampleCount": 1}
        }

        try:
            res = self.session.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                img_b64 = res.json()['predictions'][0]['bytesBase64Encoded']
                img_data = base64.b64decode(img_b64)
                
                # 이미지 비율 검증 (필요시)
                if PIL_AVAILABLE:
                    img = Image.open(io.BytesIO(img_data))
                    print(f"이미지 크기: {img.size}")
                
                return self.upload_media(img_data, title)
        except Exception as e:
            print(f"⚠️ 이미지 생성 실패: {e}")
        return None

    def upload_media(self, img_data, title):
        safe_name = re.sub(r'[^a-zA-Z0-9가-힣]', '_', title)[:30] + '.png'
        files = {'file': (safe_name, img_data, 'image/png')}
        try:
            res = self.session.post(
                f"{self.base_url}/wp-json/wp/v2/media",
                headers={"Authorization": f"Basic {self.auth_header}"},
                files=files
            )
            return res.json()['id'] if res.status_code == 201 else None
        except: return None

    def assemble_blocks(self, blocks):
        """AI가 생성한 데이터 블록을 구텐베르크 본문으로 변환합니다."""
        assembled = ""
        seen_fingerprints = set()
        for b in blocks:
            content = b['content'].strip()
            # 중복 제거 (지문 비교)
            fingerprint = re.sub(r'[^가-힣]', '', content)[:40]
            if b['type'] == "p" and (fingerprint in seen_fingerprints or len(fingerprint) < 5): continue
            seen_fingerprints.add(fingerprint)

            if b['type'] == "h2":
                assembled += f"<!-- wp:heading {{\"level\":2}} -->\n<h2>{content}</h2>\n<!-- /wp:heading -->\n\n"
            elif b['type'] == "p":
                assembled += f"<!-- wp:paragraph -->\n<p>{content}</p>\n<!-- /wp:paragraph -->\n\n"
            elif b['type'] == "list":
                if "<li>" not in content:
                    lis = "".join([f"<li>{i.strip()}</li>" for i in content.split('\n') if i.strip()])
                    content = f"<ul>{lis}</ul>"
                assembled += f"<!-- wp:list -->\n{content}\n<!-- /wp:list -->\n\n"
        return assembled

    def get_or_create_tag_ids(self, tag_string):
        if not tag_string: return []
        tag_names = [t.strip() for t in str(tag_string).split(',')][:8]
        tag_ids = []
        for name in tag_names:
            try:
                search = self.session.get(f"{self.base_url}/wp-json/wp/v2/tags?search={name}", headers=self.common_headers)
                tags = search.json()
                match = next((t for t in tags if t['name'].lower() == name.lower()), None)
                if match:
                    tag_ids.append(match['id'])
                else:
                    create = self.session.post(f"{self.base_url}/wp-json/wp/v2/tags", headers=self.common_headers, json={"name": name})
                    if create.status_code == 201: tag_ids.append(create.json()['id'])
            except: continue
        return tag_ids

    def run(self):
        print(f"--- [{datetime.now().strftime('%H:%M')}] 작업 시작 ---")
        news = self.search_news()
        data = self.generate_content(news)
        
        if not data:
            print("❌ 콘텐츠 생성 실패로 종료합니다.")
            return

        # 1. 구텐베르크 본문 조립
        data['assembled_content'] = self.assemble_blocks(data['blocks'])
        
        # 2. 이미지 생성 및 업로드
        img_id = self.generate_image(data['title'])
        
        # 3. 태그 ID 연동
        tag_ids = self.get_or_create_tag_ids(data.get('tags', ''))

        # 4. 발행
        print("--- [Step 3] 워드프레스 발행 중... ---")
        payload = {
            "title": data['title'],
            "content": data['assembled_content'],
            "excerpt": data['excerpt'][:155],
            "status": "publish",
            "tags": tag_ids,
            "meta": {
                "_yoast_wpseo_focuskw": data['focus_keyphrase'],
                "_yoast_wpseo_metadesc": data['excerpt'][:155]
            }
        }
        if img_id: payload["featured_media"] = img_id

        res = self.session.post(f"{self.base_url}/wp-json/wp/v2/posts", headers=self.common_headers, json=payload)

        if res.status_code == 201:
            print(f"🎉 발행 성공: {res.json()['link']}")
        else:
            print(f"❌ 실패: {res.status_code} - {res.text}")

if __name__ == "__main__":
    WordPressAutoPoster().run()
