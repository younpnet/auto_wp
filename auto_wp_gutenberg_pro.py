import requests
import json
import time
import base64
import re
import os
from datetime import datetime

# ==============================================================================
# Github Actions 환경 변수 설정 (Github Secrets에 저장된 값을 읽어옵니다)
# ==============================================================================
CONFIG = {
    "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
    "WP_URL": os.environ.get("WP_URL", "https://your-domain.com"),
    "WP_USERNAME": os.environ.get("WP_USERNAME", "admin"),
    "WP_APP_PASSWORD": os.environ.get("WP_APP_PASSWORD", ""),
    "TEXT_MODEL": "gemini-2.5-flash-preview-09-2025",
    "NAVER_CLIENT_ID": os.environ.get("NAVER_CLIENT_ID", ""),
    "NAVER_CLIENT_SECRET": os.environ.get("NAVER_CLIENT_SECRET", "")
}

class WordPressAutoPoster:
    def __init__(self):
        # 인증 헤더 생성
        user_pass = f"{CONFIG['WP_USERNAME']}:{CONFIG['WP_APP_PASSWORD']}"
        self.auth = base64.b64encode(user_pass.encode()).decode()
        self.headers = {
            "Authorization": f"Basic {self.auth}",
            "Content-Type": "application/json"
        }

    def search_naver_news(self, query="국민연금"):
        """네이버 뉴스 API를 호출하여 최신 뉴스 5개를 가져옵니다."""
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": CONFIG["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": CONFIG["NAVER_CLIENT_SECRET"]
        }
        params = {"query": query, "display": 5, "sort": "sim"}
        
        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                items = response.json().get('items', [])
                news_text = ""
                for item in items:
                    # HTML 태그 제거
                    title = re.sub(r'<.*?>', '', item['title'])
                    desc = re.sub(r'<.*?>', '', item['description'])
                    news_text += f"제목: {title}\n내용: {desc}\n\n"
                return news_text
            else:
                print(f"네이버 API 오류: {response.status_code}")
                return ""
        except Exception as e:
            print(f"뉴스 검색 중 오류: {e}")
            return ""

    def call_gemini(self, prompt, system_instruction=None):
        """Gemini API 호출 (JSON 응답 방식)"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['TEXT_MODEL']}:generateContent?key={CONFIG['GEMINI_API_KEY']}"
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
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
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        for i in range(5):
            try:
                response = requests.post(url, json=payload, timeout=90)
                if response.status_code == 200:
                    res_json = response.json()
                    return json.loads(res_json['candidates'][0]['content']['parts'][0]['text'])
                else:
                    print(f"API 호출 실패 (시도 {i+1}): {response.text}")
            except Exception as e:
                print(f"오류 발생: {e}")
            time.sleep(2 ** i)
        return None

    def clean_markdown(self, text):
        """불필요한 마크다운 기호를 정제합니다."""
        # 구텐베르크 주석 마커는 보존하고 나머지 마크다운만 제거
        text = re.sub(r'(?<!<!-- )(?<!/)\*\*', '', text) 
        text = re.sub(r'###|##|#', '', text)
        return text.strip()

    def get_or_create_tags(self, tag_names_str):
        if not tag_names_str: return []
        tag_names = [t.strip() for t in tag_names_str.split(',')]
        tag_ids = []
        for name in tag_names:
            try:
                res = requests.get(f"{CONFIG['WP_URL']}/wp-json/wp/v2/tags?search={name}", headers=self.headers)
                existing = res.json()
                match = next((t for t in existing if t['name'].lower() == name.lower()), None)
                if match:
                    tag_ids.append(match['id'])
                else:
                    res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/tags", headers=self.headers, json={"name": name})
                    if res.status_code == 201:
                        tag_ids.append(res.json()['id'])
            except:
                continue
        return tag_ids

    def generate_post(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 실시간 뉴스 검색 및 글 생성 시작...")
        
        # 1. 네이버 뉴스 검색 (실시간 정보 보강)
        news_context = self.search_naver_news("국민연금 개혁 2026")
        
        # 2. 주제 선정 (뉴스를 바탕으로)
        topic_prompt = f"다음은 현재 실시간 뉴스 내용이야:\n{news_context}\n위 뉴스들을 참고해서 2026년 2월 현재 가장 중요한 국민연금 관련 주제를 하나 선정해 제목 형태로 답해줘. 제목 처음에 연도를 넣지 마."
        topic_data = self.call_gemini(topic_prompt)
        topic = topic_data['title'] if topic_data else "국민연금 최신 제도 변화 분석"
        print(f"선정된 주제: {topic}")

        # 3. 본문 생성 (뉴스 데이터 기반 RAG 방식)
        system_instruction = f"""당신은 대한민국 최고의 금융 전문가입니다. 현재 시점은 2026년 2월입니다. 
        아래 제공되는 최신 뉴스 데이터와 당신의 지식을 결합하여 독자들에게 가장 정확하고 유익한 글을 작성하세요.
        
        [참조 뉴스 데이터]
        {news_context}

        [엄격 규칙]
        1. 인사말 및 자기소개 절대 금지.
        2. 구텐베르크 블록 마커(<!-- wp:paragraph --> 등)만 사용하여 본문을 구조화하세요.
        3. 한 단락은 3문장 이내로 짧게 구성하세요.
        4. 마크다운 기호를 사용하지 마세요. 강조는 <strong> 태그를 쓰세요.
        5. 표는 <!-- wp:table --> 블록을 사용해 가독성 있게 작성하세요.
        6. 요약글은 150자 내외로 작성하세요.
        7. 3,000자 이상의 풍부한 내용을 작성하세요."""

        post_data = self.call_gemini(f"주제: {topic}. 실시간 정보를 포함하여 깊이 있는 블로그 글을 작성해줘.", system_instruction)
        
        if not post_data:
            print("글 생성 실패")
            return

        post_data['title'] = self.clean_markdown(post_data['title'])
        post_data['content'] = self.clean_markdown(post_data['content'])
        
        # 4. 태그 및 발행
        tag_ids = self.get_or_create_tags(post_data['tags'])
        print("워드프레스 발행 중...")
        payload = {
            "title": post_data['title'],
            "content": post_data['content'],
            "excerpt": post_data['excerpt'],
            "status": "publish",
            "tags": tag_ids
        }
        
        res = requests.post(f"{CONFIG['WP_URL']}/wp-json/wp/v2/posts", headers=self.headers, json=payload)
        
        if res.status_code == 201:
            print(f"🎉 실시간 정보 보강 포스팅 성공: {post_data['title']}")
        else:
            print(f"포스팅 실패: {res.text}")

if __name__ == "__main__":
    poster = WordPressAutoPoster()
    poster.generate_post()