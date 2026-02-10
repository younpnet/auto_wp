import requests
import json
import time
import base64
import re
import os
import random
import sys
from datetime import datetime

# ==============================================================================
# 환경 변수 설정 (Github Secrets)
# ==============================================================================
CONFIG = {
    "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
    "WP_URL": os.environ.get("WP_URL", ""),
    "WP_USERNAME": os.environ.get("WP_USERNAME", "admin"),
    "WP_APP_PASSWORD": os.environ.get("WP_APP_PASSWORD", ""),
    "NAVER_CLIENT_ID": os.environ.get("NAVER_CLIENT_ID", ""),
    "NAVER_CLIENT_SECRET": os.environ.get("NAVER_CLIENT_SECRET", ""),
    "TEXT_MODEL": "gemini-2.5-flash-preview-09-2025",
    "IMAGE_MODEL": "imagen-4.0-generate-001" 
}

class WordPressAutoPoster:
    def __init__(self):
        print("--- [Step 0] 시스템 환경 및 인증 점검 ---")
        for key in ["WP_URL", "WP_APP_PASSWORD", "GEMINI_API_KEY"]:
            val = CONFIG[key]
            if not val:
                print(f"❌ 오류: '{key}' 환경 변수가 설정되지 않았습니다.")
            else:
                print(f"✅ '{key}' 로드 완료 (데이터 확인됨)")

        if not CONFIG["WP_URL"] or not CONFIG["WP_APP_PASSWORD"] or not CONFIG["GEMINI_API_KEY"]:
            print("❗ 필수 설정 누락으로 실행을 종료합니다.")
            sys.exit(1)
            
        self.base_url = CONFIG["WP_URL"].rstrip("/")
        self.session = requests.Session()
        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth_header = base64.b64encode(user_pass.encode()).decode()
        
        self.common_headers = {
            "Authorization": f"Basic {self.auth_header}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        }

    def random_sleep(self):
        """
        테스트 시 로딩이 길어지는 주범입니다. 
        실제 운영 시에는 (0, 3600)으로 설정하여 1시간 범위를 주시고,
        지금은 테스트를 위해 (1, 10)초로 대폭 줄렸습니다.
        """
        wait_seconds = random.randint(1, 10) 
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ 보안 및 랜덤화를 위한 대기: {wait_seconds}초 후 작업을 시작합니다...")
        time.sleep(wait_seconds)

    def search_naver_news(self, query="국민연금 개혁"):
        print("--- [Step 1] 네이버 뉴스 실시간 검색 중... ---")
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 5, "sort": "sim"}
        try:
            res = self.session.get(url, headers=headers, params=params, timeout=15)
            if res.status_code == 200:
                items = res.json().get('items', [])
                print(f"뉴스 {len(items)}건 수집 완료")
                return "\n".join([f"제목: {re.sub('<.*?>', '', i['title'])}\n내용: {re.sub('<.*?>', '', i['description'])}" for i in items])
        except Exception as e: 
            print(f"⚠️ 뉴스 검색 실패 (기본 지식으로 진행): {e}")
        return "국민연금 최신 제도 변화 분석"

    def get_or_create_tag_ids(self, tags_input):
        """태그 데이터가 문자열(String)이든 리스트(List)이든 안전하게 처리합니다."""
        if not tags_input: return []
        
        # AI가 리스트 형식을 반환할 경우와 문자열 형식을 반환할 경우 모두 대응
        if isinstance(tags_input, list):
            tag_names = [str(t).strip() for t in tags_input][:10]
        else:
            tag_names = [t.strip() for t in str(tags_input).split(',')][:10]
            
        tag_ids = []
        print(f"태그 {len(tag_names)}개 처리 중...")
        for name in tag_names:
            try:
                # 검색 API 호출 시 특수문자 인코딩 처리
                search_res = self.session.get(f"{self.base_url}/wp-json/wp/v2/tags?search={name}", headers=self.common_headers)
                existing = search_res.json()
                
                # 검색 결과 중 정확히 일치하는 이름이 있는지 확인
                match = next((t for t in existing if t['name'].lower() == name.lower()), None)
                if match:
                    tag_ids.append(match['id'])
                else:
                    # 일치하는 태그가 없으면 새로 생성
                    create_res = self.session.post(f"{self.base_url}/wp-json/wp/v2/tags", headers=self.common_headers, json={"name": name})
                    if create_res.status_code == 201:
                        tag_ids.append(create_res.json()['id'])
            except Exception as e:
                print(f"⚠️ 태그 '{name}' 처리 실패: {e}")
                continue
        return tag_ids

    def generate_content(self, topic_context):
        print("--- [Step 2] Gemini AI 본문 및 태그 생성 중... ---")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        system_prompt = (
            "당신은 대한민국 최고의 금융 전문가입니다. 3,000자 이상의 상세 포스팅을 JSON(title, content, excerpt, tags)으로 작성하세요.\n"
            "본문은 반드시 워드프레스 구텐베르크 블록 주석(<!-- wp:paragraph --> 등)으로 감싸야 합니다.\n"
            "태그는 10개 내외로 생성하세요. 인사말은 생략하고 바로 본론으로 시작하세요."
        )
        payload = {
            "contents": [{"parts": [{"text": f"뉴스 데이터:\n{topic_context}\n\n위 정보를 바탕으로 발행해줘."}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"responseMimeType": "application/json"}
        }
        res = self.session.post(url, json=payload, timeout=120)
        if res.status_code != 200:
            print(f"❌ 텍스트 생성 실패: {res.text}")
            sys.exit(1)
            
        raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
        data = json.loads(re.sub(r'```json|```', '', raw_text).strip())
        print(f"글 생성 완료: {data['title'][:20]}...")
        return data

    def generate_image(self, title):
        print("--- [Step 3] Imagen 4.0 대표 이미지 생성 중... ---")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['IMAGE_MODEL']}:predict?key={CONFIG['GEMINI_API_KEY']}"
        
        prompt = (
            f"A professional, high-quality 16:9 aspect ratio (1366x745) blog featured image for an article titled '{title}'. "
            "The design should be modern and financial-themed, representing 'National Pension Service of Korea'. "
            "Clean, minimalist composition with soft lighting. High resolution, 4k."
        )
        
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1}
        }
        
        try:
            res = self.session.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                print("이미지 생성 성공")
                return res.json()['predictions'][0]['bytesBase64Encoded']
            else:
                print(f"⚠️ 이미지 생성 API 오류: {res.status_code}")
        except Exception as e:
            print(f"⚠️ 이미지 생성 중 예외 발생: {e}")
        return None

    def upload_media(self, base64_image, filename):
        print("--- [Step 4] 워드프레스 미디어 업로드 중... ---")
        url = f"{self.base_url}/wp-json/wp/v2/media"
        image_data = base64.b64decode(base64_image)
        
        headers = {
            "Authorization": f"Basic {self.auth_header}",
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "image/png"
        }
        
        res = self.session.post(url, headers=headers, data=image_data, timeout=60)
        if res.status_code == 201:
            media_id = res.json().get('id')
            print(f"미디어 업로드 성공 (ID: {media_id})")
            return media_id
        print(f"⚠️ 미디어 업로드 실패: {res.status_code}")
        return None

    def publish(self, data, media_id):
        print("--- [Step 5] 워드프레스 최종 발행 중... ---")
        # tags 데이터 형식에 관계없이 안전하게 처리되도록 get_or_create_tag_ids를 호출합니다.
        tag_ids = self.get_or_create_tag_ids(data.get('tags', []))
        
        payload = {
            "title": data['title'],
            "content": data['content'],
            "excerpt": data['excerpt'],
            "status": "publish",
            "tags": tag_ids,
            "featured_media": media_id if media_id else 0
        }
        res = self.session.post(f"{self.base_url}/wp-json/wp/v2/posts", headers=self.common_headers, json=payload, timeout=60)
        
        if res.status_code == 201:
            return True
        else:
            print(f"❌ 발행 실패 (코드 {res.status_code}): {res.text[:500]}")
            return False

    def run(self):
        # 1. 랜덤 대기 (테스트를 위해 짧게 수정됨)
        self.random_sleep()
        
        # 2. 정보 수집 및 텍스트 생성
        news = self.search_naver_news()
        post_data = self.generate_content(news)
        
        # 3. 이미지 생성 및 업로드
        media_id = None
        img_b64 = self.generate_image(post_data['title'])
        if img_b64:
            media_id = self.upload_media(img_b64, f"nps_featured_{int(time.time())}.png")
        
        # 4. 발행
        if self.publish(post_data, media_id):
            print("\n" + "="*50)
            print(f"🎉 포스팅 발행 성공!")
            print(f"제목: {post_data['title']}")
            print("="*50)
        else:
            sys.exit(1)

if __name__ == "__main__":
    WordPressAutoPoster().run()
